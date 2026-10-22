"""One-shot paused dispatch on an independently qualified canonical load.

No process or connection is opened here. The caller owns authorization, secure
transport, complete native snapshot collection, and owned-process cleanup.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from app.simulation.openttd.freight_canonical import CanonicalState
from app.simulation.openttd.freight_capacity_execution import (
    CapacityReceipt,
    CapacityRequest,
    validate_capacity_replay,
)


@dataclass(frozen=True)
class BoundaryRequest:
    request_id: str
    type: str = "canonical-ready"
    service: int = -1

    def to_bytes(self) -> bytes:
        if (
            self.type
            not in {
                "canonical-seal",
                "canonical-ready",
                "canonical-arm",
                "canonical-start",
                "canonical-dispatch-read",
                "canonical-dispatched",
            }
            or not 1 <= len(self.request_id) <= 32
            or not self.request_id.isascii()
            or not self.request_id.replace("-", "").isalnum()
            or type(self.service) is not int
            or self.service not in ((0, 1, 2) if self.type == "canonical-seal" else (-1,))
        ):
            raise ValueError("invalid canonical boundary request")
        return json.dumps(
            dict(protocol=1, type=self.type, request_id=self.request_id, service=self.service),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")


class BoundaryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    protocol: Literal[1]
    type: str
    request_id: str
    service: StrictInt
    status: Literal["ok"]
    tick: StrictInt
    economy_date: StrictInt
    paused: StrictBool
    command_pause_level: StrictInt
    restored: StrictBool
    originals: list[tuple[StrictInt, StrictInt, StrictInt, StrictInt, StrictInt, StrictInt]]
    extra: tuple[StrictInt, StrictInt, StrictInt, StrictInt, StrictInt, StrictInt] | None
    cash: StrictInt
    loan: StrictInt

    @classmethod
    def parse_for(cls, request: BoundaryRequest, raw: bytes):
        request.to_bytes()
        if not 0 < len(raw) <= 1450:
            raise ValueError("canonical boundary packet bound")
        pairs = json.loads(raw, object_pairs_hook=list)
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError("duplicate canonical boundary key")
        receipt = cls.model_validate_json(raw)
        if (
            receipt.type != request.type + "-result"
            or receipt.request_id != request.request_id
            or receipt.service != request.service
            or receipt.tick < 0
            or receipt.economy_date < 0
            or receipt.loan < 0
        ):
            raise ValueError("canonical boundary correlation")
        if request.type == "canonical-dispatched":
            if receipt.paused or receipt.originals or receipt.extra is not None:
                raise ValueError("native unpause acknowledgement missing")
        elif request.type != "canonical-seal":
            if (
                not receipt.paused
                or len(receipt.originals) != 3
                or tuple(row[0] for row in receipt.originals) != (0, 1, 2)
                or len({row[1] for row in receipt.originals}) != 3
                or any(row[3] != 0 or row[4] != 0 for row in receipt.originals)
            ):
                raise ValueError("canonical originals or pause mismatch")
        return receipt


async def seal_service(session, directory: Path, service: int):
    from app.simulation.openttd.proof.freight_delivery import exchange

    return await exchange(
        session,
        BoundaryRequest(f"canonical-seal-{service}", "canonical-seal", service),
        directory,
        response_type=BoundaryReceipt,
    )


async def read_boundary(session, directory: Path, name="canonical-ready"):
    from app.simulation.openttd.proof.freight_delivery import exchange

    return await exchange(session, BoundaryRequest(name), directory, response_type=BoundaryReceipt)


def require_common_state(canonical: CanonicalState, loaded: CanonicalState):
    """No relaxed matching of time, queues, finances or original identities."""
    if loaded != canonical:
        raise ValueError("unmatched canonical pre-intervention state")


def require_stable_boundary(before: BoundaryReceipt, after: BoundaryReceipt, *, started=False):
    if (
        not before.paused
        or not after.paused
        or after.tick < before.tick
        or before.economy_date != after.economy_date
        or before.command_pause_level != after.command_pause_level
        or before.loan != after.loan
        or before.cash != after.cash
        or len(before.originals) != 3
        or len(after.originals) != 3
    ):
        raise ValueError("canonical intervention-time drift")
    if before.extra != after.extra:
        raise ValueError("additional vehicle movement or identity drift")
    for old, new in zip(before.originals, after.originals, strict=True):
        if old[:5] != new[:5] or (not started and old[5] != new[5]):
            raise ValueError("canonical original movement or identity drift")
    if after.tick <= before.tick:
        raise ValueError("paused GameScript heartbeat did not advance")


async def dispatch_common(
    session,
    directory: Path,
    canonical: CanonicalState,
    loaded: CanonicalState,
    *,
    arm: Literal["A", "B"],
    snapshot,
    unpause,
    service_plans: tuple[str, str, str],
    max_cost: int = 100000,
    purchase_only: bool = False,
):
    """Run one intervention/dispatch; retain failure evidence, never retry.

    snapshot is the existing collector plus paused save DATE readback. unpause
    must perform a single owned-console unpause with native acknowledgement.
    Dispatch result is an acknowledgement, not a completed capacity experiment.
    """
    from app.simulation.openttd.proof.freight_delivery import exchange

    if arm not in ("A", "B"):
        raise ValueError("canonical arm must be A or B")
    require_common_state(canonical, loaded)
    first = await read_boundary(session, directory, "canonical-before")
    armed = await exchange(
        session,
        BoundaryRequest("canonical-arm", "canonical-arm"),
        directory,
        response_type=BoundaryReceipt,
    )
    require_stable_boundary(first, armed)
    if not armed.restored or armed.command_pause_level not in (2, 3):
        raise ValueError("paused purchase unavailable or bindings not restored")
    for row, vehicle in zip(armed.originals, canonical.vehicles, strict=True):
        if row[:5] != (vehicle.service, vehicle.vehicle, vehicle.tile, 0, 0):
            raise ValueError("canonical original binding mismatch")
    binding = None
    capex = 0
    if arm == "B":
        command = await exchange(
            session,
            CapacityRequest("capacity-add", 1, max_cost),
            directory,
            response_type=CapacityReceipt,
        )
        independent = await exchange(
            session,
            CapacityRequest("capacity-read", 1, max_cost, read=True),
            directory,
            response_type=CapacityReceipt,
        )
        v = canonical.vehicles[1]
        binding = validate_capacity_replay(
            command,
            independent,
            plan=service_plans[1],
            service=1,
            original_vehicle=v.vehicle,
            engine=v.engine,
            cargo=v.cargo,
            capacity=v.capacity,
            source=v.orders[0].destination,
            destination=v.orders[1].destination,
            full_load_flag=v.orders[0].flags,
            no_load_flag=v.orders[1].flags,
            max_cost=max_cost,
        )
        if (
            command.economy_date != canonical.economy_date
            or independent.economy_date != canonical.economy_date
        ):
            raise ValueError("capacity intervention date drift")
        if (
            command.cash_before != armed.cash
            or independent.cash_after != armed.cash - command.purchase_capex
            or command.tick < armed.tick
        ):
            raise ValueError("capacity funding or native timing mismatch")
        capex = command.purchase_capex
    ready = await read_boundary(session, directory, "canonical-after-intervention")
    expected = armed.model_copy(update={"cash": armed.cash - capex, "extra": ready.extra})
    require_stable_boundary(expected, ready)
    if arm == "A" and ready.extra is not None:
        raise ValueError("unexpected additional vehicle in A")
    if arm == "B" and (
        ready.extra is None
        or binding is None
        or ready.extra[0] != 1
        or ready.extra[1] != binding["vehicle"]
        or ready.extra[2] != armed.originals[1][2]
        or ready.extra[3:5] != (0, 0)
    ):
        raise ValueError("additional vehicle movement or binding mismatch")
    # Full collector independently verifies all semantic state, including exact
    # fractional time and additional-vehicle exclusion/receipt correspondence.
    verified = await snapshot(binding, capex, started=False)
    if verified is not True:
        raise ValueError("complete intervention snapshot verification missing")
    if purchase_only:
        if arm != "B":
            raise ValueError("purchase qualification requires B intervention")
        return dict(
            binding=binding,
            purchase_capex=capex,
            before=armed.model_dump(mode="json"),
            after=ready.model_dump(mode="json"),
        )
    started = await exchange(
        session,
        BoundaryRequest("canonical-start", "canonical-start"),
        directory,
        response_type=BoundaryReceipt,
    )
    require_stable_boundary(ready, started, started=True)
    checked = await exchange(
        session,
        BoundaryRequest("canonical-dispatch-read", "canonical-dispatch-read"),
        directory,
        response_type=BoundaryReceipt,
    )
    require_stable_boundary(started, checked)
    verified = await snapshot(binding, capex, started=True)
    if verified is not True:
        raise ValueError("complete dispatch snapshot verification missing")
    acknowledgement = await unpause()
    if not isinstance(acknowledgement, dict):
        raise ValueError("native dispatch acknowledgement missing")
    ack = BoundaryReceipt.model_validate(acknowledgement)
    if (
        ack.type != "canonical-dispatched-result"
        or ack.request_id != "canonical-dispatched"
        or ack.paused
        or ack.tick < checked.tick
        or ack.economy_date < checked.economy_date
    ):
        raise ValueError("native dispatch acknowledgement missing")
    return dict(
        arm=arm,
        binding=binding,
        purchase_capex=capex,
        before=armed.model_dump(mode="json"),
        dispatch=checked.model_dump(mode="json"),
        unpause=acknowledgement,
    )


async def qualify_paused_purchase(
    session,
    directory: Path,
    canonical: CanonicalState,
    loaded: CanonicalState,
    *,
    snapshot,
    service_plans: tuple[str, str, str],
    max_cost: int = 100000,
):
    """Stage-2 single B purchase/readback only: never starts or unpauses originals."""

    async def forbidden_unpause():
        raise ValueError("purchase qualification cannot dispatch")

    return await dispatch_common(
        session,
        directory,
        canonical,
        loaded,
        arm="B",
        snapshot=snapshot,
        unpause=forbidden_unpause,
        service_plans=service_plans,
        max_cost=max_cost,
        purchase_only=True,
    )


async def unpause_native(backend, prepared, session):
    """One owned-console unpause and one correlated native GS acknowledgement."""
    from app.simulation.openttd.proof.freight_delivery import exchange
    from app.simulation.openttd.proof.road_mutation import console

    console(backend, "unpause")
    receipt = await exchange(
        session,
        BoundaryRequest("canonical-dispatched", "canonical-dispatched"),
        prepared.directory,
        response_type=BoundaryReceipt,
    )
    return receipt.model_dump(mode="json")


async def dispatch_loaded_arm(backend, prepared, session, *, created, loaded, arm):
    """Dispatch one already loaded arm using concrete native collectors and saves.

    The caller owns its separately authorized fresh process and secure session.
    This function opens neither. It cannot reuse the purchase qualification world.
    """
    from app.simulation.openttd.freight_canonical import compare_canonical
    from app.simulation.openttd.freight_canonical_runtime import verify_intervention_snapshot
    from app.simulation.openttd.proof.canonical_fleet import protected_save
    from app.simulation.openttd.proof.harness import write_json

    compare_canonical(created, loaded)
    service_plans = tuple(loaded.state.map["service_plans"])
    if len(service_plans) != 3:
        raise ValueError("three restored service plan identities required")
    snapshot_number = 0

    async def snapshot(binding, capex, *, started):
        nonlocal snapshot_number
        snapshot_number += 1
        name = f"dispatch-snapshot-{snapshot_number}"
        directory = prepared.directory / name
        directory.mkdir()
        await protected_save(backend, prepared, name)
        return await verify_intervention_snapshot(
            session,
            directory,
            canonical=created.state,
            binding=binding,
            capex=capex,
            started=started,
            identity=loaded.qualification_id,
            runtime_sha256=loaded.runtime_sha256,
            bridge_sha256=loaded.bridge_sha256,
            configuration_sha256=loaded.configuration_sha256,
            source_save_sha256=loaded.source_save_sha256,
            snapshot_path=prepared.directory / (name + ".sav"),
        )

    async def unpause():
        return await unpause_native(backend, prepared, session)

    result = await dispatch_common(
        session,
        prepared.directory,
        created.state,
        loaded.state,
        arm=arm,
        snapshot=snapshot,
        unpause=unpause,
        service_plans=service_plans,
    )
    write_json(prepared.directory / "canonical-dispatch.json", result)
    return result
