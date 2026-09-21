from collections.abc import Sequence
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from decimal import Decimal
from threading import Event

from app.packing.schemas import (
    DeliveryStop,
    LoadingStatus,
    Orientation,
    PackingPackage,
    PackingProblem,
    PackingResult,
    PackingVehicle,
    Placement,
    UnplacedPackage,
)

ZERO = Decimal("0")


@dataclass
class _Stack:
    """A supported column; successive boxes have non-increasing footprints."""

    top: Placement
    stackable: bool


@dataclass
class _Row:
    y: Decimal
    depth: Decimal
    used_width: Decimal = ZERO
    stacks: list[_Stack] = field(default_factory=list)


@dataclass
class _Candidate:
    placement: Placement
    row: _Row | None
    stack: _Stack | None


class PackingOptimizer:
    """Deterministic stop bands, floor rows and supported stacks.

    The rear door spans x/z at y=0. Each stop owns a separate band along y,
    starting with the earliest delivery. Rows reserve their full depth and each
    stack reserves its base footprint. Boxes never bridge stacks or stops.
    This deliberately favors simple unloading over filling every free pocket.
    No database access or dependence on ORM objects is needed.
    """

    def solve(
        self,
        vehicle: PackingVehicle,
        packages: Sequence[PackingPackage],
        delivery_sequence: Sequence[DeliveryStop],
        *,
        cancel_event: Event | None = None,
    ) -> PackingResult:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("loading optimization was replaced")
        problem = PackingProblem(
            vehicle=vehicle, packages=list(packages), delivery_sequence=list(delivery_sequence)
        )
        placements: list[Placement] = []
        unplaced: list[UnplacedPackage] = []
        loaded_weight = ZERO
        band_end = ZERO
        for stop in sorted(problem.delivery_sequence, key=lambda stop: stop.stop_order):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("loading optimization was replaced")
            rows: list[_Row] = []
            stop_packages = sorted(
                (p for p in problem.packages if p.shipment_id == stop.shipment_id),
                key=lambda p: (-p.volume, p.package_id),
            )
            for package in stop_packages:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("loading optimization was replaced")
                reason = None
                if not any(
                    w <= vehicle.width and length <= vehicle.length and h <= vehicle.height
                    for w, length, h in (package.dimensions(o) for o in Orientation)
                ):
                    reason = "Dimensions exceed cargo space in every orientation"
                elif loaded_weight + package.weight > vehicle.max_weight:
                    reason = "Payload capacity exceeded"
                else:
                    candidate = self._find_position(
                        vehicle, package, stop, rows, band_end, cancel_event=cancel_event
                    )
                    if candidate is None:
                        reason = "No space in delivery bands / supported stacks"
                    else:
                        placement = candidate.placement
                        row = candidate.row
                        if row is None:
                            row = _Row(y=band_end, depth=placement.length)
                            rows.append(row)
                            band_end += row.depth
                        if candidate.stack is None:
                            row.stacks.append(_Stack(placement, package.stackable))
                            row.used_width += placement.width
                        else:
                            candidate.stack.top = placement
                            candidate.stack.stackable = package.stackable
                        placements.append(placement)
                        loaded_weight += package.weight
                if reason:
                    unplaced.append(
                        UnplacedPackage(
                            package_id=package.package_id, stop_order=stop.stop_order, reason=reason
                        )
                    )

        # Entire near-door rows are removed first, then each column top-down.
        # Reversing this is a feasible loading sequence: deep rows, bases, tops.
        placements.sort(key=lambda p: (p.stop_order, p.y, -p.z, p.x, p.package_id))
        placements = [
            p.model_copy(
                update={"unloading_order": index, "loading_order": len(placements) - index + 1}
            )
            for index, p in enumerate(placements, start=1)
        ]
        by_id = {package.package_id: package for package in packages}
        used_volume = sum((by_id[p.package_id].volume for p in placements), start=ZERO)
        status = LoadingStatus.COMPLETE
        if unplaced:
            status = LoadingStatus.PARTIAL if placements else LoadingStatus.INFEASIBLE
        return PackingResult(
            vehicle_id=vehicle.vehicle_id,
            placements=placements,
            unplaced_packages=unplaced,
            total_package_volume=sum((p.volume for p in packages), start=ZERO),
            used_cargo_volume=used_volume,
            cargo_volume=vehicle.volume,
            volume_utilization_percentage=self._percentage(used_volume, vehicle.volume),
            total_loaded_weight=loaded_weight,
            payload_utilization_percentage=self._percentage(loaded_weight, vehicle.max_weight),
            status=status,
        )

    @staticmethod
    def _percentage(used: Decimal, capacity: Decimal) -> Decimal:
        return (used / capacity * 100).quantize(Decimal("0.01"))

    @staticmethod
    def _find_position(
        vehicle: PackingVehicle,
        package: PackingPackage,
        stop: DeliveryStop,
        rows: list[_Row],
        band_end: Decimal,
        *,
        cancel_event: Event | None = None,
    ) -> _Candidate | None:
        candidates: list[_Candidate] = []
        for orientation in Orientation:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("loading optimization was replaced")
            width, length, height = package.dimensions(orientation)

            def add(
                x: Decimal, y: Decimal, z: Decimal, row: _Row | None, stack: _Stack | None
            ) -> None:
                if (
                    x + width <= vehicle.width
                    and y + length <= vehicle.length
                    and z + height <= vehicle.height
                ):
                    candidates.append(
                        _Candidate(
                            Placement(
                                package_id=package.package_id,
                                vehicle_id=vehicle.vehicle_id,
                                x=x,
                                y=y,
                                z=z,
                                orientation=orientation,
                                width=width,
                                length=length,
                                height=height,
                                loading_order=1,
                                unloading_order=1,
                                stop_order=stop.stop_order,
                            ),
                            row,
                            stack,
                        )
                    )

            for row in rows:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("loading optimization was replaced")
                if length <= row.depth:
                    add(row.used_width, row.y, ZERO, row, None)
                for stack in row.stacks:
                    top = stack.top
                    if stack.stackable and width <= top.width and length <= top.length:
                        add(top.x, top.y, top.z + top.height, row, stack)
            add(ZERO, band_end, ZERO, None, None)

        if not candidates:
            return None

        def score(candidate: _Candidate) -> tuple:
            p = candidate.placement
            return (
                max(band_end, p.y + p.length),
                p.z,
                p.height,
                p.y,
                p.x,
                list(Orientation).index(p.orientation),
            )

        return min(candidates, key=score)
