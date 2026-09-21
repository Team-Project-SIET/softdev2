from concurrent.futures import CancelledError
from decimal import Decimal
from itertools import combinations
from random import Random
from threading import Event

import pytest

from app.packing.optimizer import PackingOptimizer
from app.packing.schemas import (
    DeliveryStop,
    LoadingStatus,
    Orientation,
    PackingPackage,
    PackingResult,
    PackingVehicle,
)


def vehicle(width=10, length=20, height=10, max_weight=100) -> PackingVehicle:
    return PackingVehicle(
        vehicle_id=1, width=width, length=length, height=height, max_weight=max_weight
    )


def package(package_id=1, shipment_id=1, width=2, length=2, height=2, weight=1, stackable=True):
    return PackingPackage(
        package_id=package_id,
        shipment_id=shipment_id,
        width=width,
        length=length,
        height=height,
        weight=weight,
        stackable=stackable,
    )


def solve(cargo, packages, sequence=None) -> PackingResult:
    return PackingOptimizer().solve(
        cargo, packages, sequence or [DeliveryStop(shipment_id=1, stop_order=1)]
    )


def test_cancelled_packing_job_stops_before_search() -> None:
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        PackingOptimizer().solve(
            vehicle(),
            [package()],
            [DeliveryStop(shipment_id=1, stop_order=1)],
            cancel_event=cancelled,
        )


def assert_feasible(result: PackingResult, cargo: PackingVehicle, packages: list[PackingPackage]):
    by_id = {p.package_id: p for p in packages}
    placed = result.placements
    assert len({p.package_id for p in placed}) == len(placed)
    assert {p.package_id for p in placed}.isdisjoint(p.package_id for p in result.unplaced_packages)
    assert {p.package_id for p in placed} | {p.package_id for p in result.unplaced_packages} == set(
        by_id
    )
    assert result.total_loaded_weight == sum(by_id[p.package_id].weight for p in placed)
    assert result.total_loaded_weight <= cargo.max_weight
    for p in placed:
        assert 0 <= p.x < p.x + p.width <= cargo.width
        assert 0 <= p.y < p.y + p.length <= cargo.length
        assert 0 <= p.z < p.z + p.height <= cargo.height
        assert (p.width, p.length, p.height) == by_id[p.package_id].dimensions(p.orientation)
        if p.z > 0:
            supports = [
                other
                for other in placed
                if other.z + other.height == p.z
                and other.x <= p.x
                and p.x + p.width <= other.x + other.width
                and other.y <= p.y
                and p.y + p.length <= other.y + other.length
            ]
            assert supports
            assert any(by_id[s.package_id].stackable for s in supports)
            assert all(s.loading_order < p.loading_order for s in supports)
            assert all(s.unloading_order > p.unloading_order for s in supports)
    for a, b in combinations(placed, 2):
        assert (
            a.x + a.width <= b.x
            or b.x + b.width <= a.x
            or a.y + a.length <= b.y
            or b.y + b.length <= a.y
            or a.z + a.height <= b.z
            or b.z + b.height <= a.z
        ), f"overlapping packages: {a.package_id}, {b.package_id}"
        if a.stop_order < b.stop_order:
            assert a.y + a.length <= b.y
            assert a.unloading_order < b.unloading_order
            assert a.loading_order > b.loading_order
    assert sorted(p.loading_order for p in placed) == list(range(1, len(placed) + 1))
    assert sorted(p.unloading_order for p in placed) == list(range(1, len(placed) + 1))
    # Simulate straight extraction through the rear door, checking every remaining box.
    remaining = sorted(placed, key=lambda p: p.unloading_order)
    while remaining:
        p = remaining.pop(0)
        for other in remaining:
            overlaps_x = p.x < other.x + other.width and other.x < p.x + p.width
            overlaps_z = p.z < other.z + other.height and other.z < p.z + p.height
            assert not (overlaps_x and overlaps_z and other.y < p.y)


def test_packages_stay_inside_boundaries_and_do_not_overlap() -> None:
    cargo = vehicle(width=4, length=6, height=4)
    packages = [package(package_id=i) for i in range(1, 13)]
    result = solve(cargo, packages)

    assert len(result.placements) == 12
    assert result.volume_utilization_percentage == 100
    assert result.status is LoadingStatus.COMPLETE
    assert_feasible(result, cargo, packages)


def test_payload_capacity_favors_earlier_deliveries() -> None:
    cargo = vehicle(max_weight=5)
    packages = [package(1, shipment_id=1, weight=4), package(2, shipment_id=2, weight=2)]
    result = solve(
        cargo,
        packages,
        [DeliveryStop(shipment_id=2, stop_order=3), DeliveryStop(shipment_id=1, stop_order=1)],
    )

    assert [p.package_id for p in result.placements] == [1]
    assert result.total_loaded_weight == 4
    assert result.unplaced_packages[0].package_id == 2
    assert "Payload" in result.unplaced_packages[0].reason
    assert_feasible(result, cargo, packages)


def test_rotation_is_required_and_applied() -> None:
    cargo = vehicle(width=2, length=3, height=4)
    packages = [package(width=4, length=2, height=3)]
    result = solve(cargo, packages)

    assert len(result.placements) == 1
    assert result.placements[0].orientation is Orientation.LHW
    assert_feasible(result, cargo, packages)


def test_earlier_stops_are_near_door_and_unloaded_first() -> None:
    cargo = vehicle(width=2, length=6, height=4)
    packages = [package(i, shipment_id=(i + 1) // 2) for i in range(1, 7)]
    sequence = [DeliveryStop(shipment_id=i, stop_order=i * 2) for i in (3, 1, 2)]
    result = solve(cargo, packages, sequence)

    assert len(result.placements) == 6
    assert [p.stop_order for p in result.placements] == [2, 2, 4, 4, 6, 6]
    assert any(p.z > 0 for p in result.placements)
    assert_feasible(result, cargo, packages)


@pytest.mark.parametrize(
    ("cargo", "packages", "reason"),
    [
        (vehicle(width=1, length=1, height=1), [package()], "Dimensions"),
        (vehicle(max_weight=1), [package(weight=2)], "Payload"),
        (vehicle(width=2, length=2, height=2), [package(1), package(2)], "No space"),
    ],
)
def test_infeasible_packages_are_reported(cargo, packages, reason) -> None:
    result = solve(cargo, packages)

    assert len(result.unplaced_packages) == 1
    assert reason in result.unplaced_packages[0].reason
    assert result.status is (
        LoadingStatus.PARTIAL if result.placements else LoadingStatus.INFEASIBLE
    )
    assert_feasible(result, cargo, packages)


def test_stacks_require_support_and_respect_non_stackable_flag() -> None:
    cargo = vehicle(width=2, length=2, height=4)
    packages = [package(1, stackable=False), package(2)]
    result = solve(cargo, packages)

    assert len(result.placements) == 1
    assert len(result.unplaced_packages) == 1
    assert_feasible(result, cargo, packages)


def test_utilization_counts_only_loaded_packages() -> None:
    cargo = vehicle(width=4, length=6, height=2, max_weight=10)
    packages = [package(1), package(2, weight=2), package(3, width=10, length=10, height=10)]
    result = solve(cargo, packages)

    assert result.total_package_volume == 1016
    assert result.used_cargo_volume == 16
    assert result.cargo_volume == 48
    assert result.volume_utilization_percentage == Decimal("33.33")
    assert result.total_loaded_weight == 3
    assert result.payload_utilization_percentage == Decimal("30.00")


def test_fixed_input_and_reordered_input_are_deterministic() -> None:
    cargo = vehicle()
    packages = [package(i, width=i % 3 + 1, shipment_id=i % 2 + 1) for i in range(1, 12)]
    sequence = [
        DeliveryStop(shipment_id=2, stop_order=1),
        DeliveryStop(shipment_id=1, stop_order=2),
    ]
    result = solve(cargo, packages, sequence)

    assert solve(cargo, packages, sequence) == result
    assert solve(cargo, list(reversed(packages)), list(reversed(sequence))) == result
    assert_feasible(result, cargo, packages)


def test_empty_route_has_zero_utilization() -> None:
    result = PackingOptimizer().solve(vehicle(), [], [])

    assert not result.placements
    assert not result.unplaced_packages
    assert result.total_loaded_weight == result.used_cargo_volume == 0
    assert result.payload_utilization_percentage == result.volume_utilization_percentage == 0
    assert result.status is LoadingStatus.COMPLETE


@pytest.mark.parametrize("seed", range(12))
def test_varied_dimensions_preserve_geometry_and_accessibility(seed: int) -> None:
    rng = Random(seed)
    cargo = vehicle(width=8, length=20, height=7, max_weight=45)
    packages = [
        package(
            i,
            shipment_id=i % 3 + 1,
            width=Decimal(rng.randint(1, 20)) / 4,
            length=Decimal(rng.randint(1, 20)) / 4,
            height=Decimal(rng.randint(1, 20)) / 4,
            weight=rng.randint(1, 5),
            stackable=rng.choice([True, False]),
        )
        for i in range(1, 25)
    ]
    sequence = [DeliveryStop(shipment_id=i, stop_order=i) for i in range(1, 4)]

    assert_feasible(solve(cargo, packages, sequence), cargo, packages)


@pytest.mark.parametrize(
    ("packages", "sequence", "message"),
    [
        ([package(), package()], [DeliveryStop(shipment_id=1, stop_order=1)], "IDs must be unique"),
        ([package(shipment_id=2)], [DeliveryStop(shipment_id=1, stop_order=1)], "delivery stop"),
        ([], [DeliveryStop(shipment_id=1, stop_order=1)] * 2, "shipment must occur once"),
        ([], [DeliveryStop(shipment_id=i, stop_order=1) for i in (1, 2)], "stop orders"),
    ],
)
def test_invalid_delivery_input_is_rejected(packages, sequence, message) -> None:
    with pytest.raises(ValueError, match=message):
        PackingOptimizer().solve(vehicle(), packages, sequence)
