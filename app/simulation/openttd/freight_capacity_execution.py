"""Opt-in fourth-vehicle command correlation and independent offline readback.

These receipts describe native observations; controlled replay is not native proof.
"""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import StrictBool, StrictInt

from app.planning.domain import Contract


@dataclass(frozen=True)
class CapacityRequest:
    request_id: str
    service: int
    max_cost: int
    read: bool = False

    @property
    def type(self) -> str:
        return "capacity-read" if self.read else "capacity-add"

    def to_bytes(self) -> bytes:
        return capacity_request(self.request_id, self.service, self.max_cost, read=self.read)


class CapacityReceipt(Contract):
    protocol: StrictInt
    type: Literal["capacity-add-result", "capacity-read-result"]
    request_id: str
    status: Literal["ok", "partial"]
    service: StrictInt
    vehicle: StrictInt
    original_vehicle: StrictInt
    plan: str
    engine: StrictInt
    cargo: StrictInt
    capacity: StrictInt
    owner: StrictInt
    state: StrictInt
    orders: list[tuple[StrictInt, StrictInt, StrictBool]]
    commands: list[tuple[StrictInt, StrictBool, StrictInt, StrictInt, StrictInt, StrictInt]]
    purchase_capex: StrictInt
    cash_before: StrictInt
    cash_after: StrictInt
    tick: StrictInt
    economy_date: StrictInt
    error: str | None

    @classmethod
    def parse_for(cls, request: CapacityRequest, payload: bytes) -> CapacityReceipt:
        return decode_capacity_receipt(payload, request.to_bytes())


def capacity_request(request_id: str, service: int, max_cost: int, *, read: bool = False) -> bytes:
    if (
        not 1 <= len(request_id) <= 32
        or not request_id.isascii()
        or not request_id.replace("-", "").isalnum()
        or type(service) is not int
        or service not in (0, 1, 2)
        or type(max_cost) is not int
        or not 0 < max_cost <= 2147483647
    ):
        raise ValueError("invalid capacity request")
    return json.dumps(
        dict(
            protocol=1,
            type="capacity-read" if read else "capacity-add",
            request_id=request_id,
            service=service,
            max_cost=max_cost,
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def decode_capacity_receipt(raw: bytes, request: bytes) -> CapacityReceipt:
    if not 0 < len(raw) <= 1450:
        raise ValueError("capacity receipt packet bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate capacity key")
            result[key] = value
        return result

    q = json.loads(request, object_pairs_hook=unique)
    json.loads(raw, object_pairs_hook=unique)
    receipt = CapacityReceipt.model_validate_json(raw)
    if (
        receipt.protocol != 1
        or receipt.type != q["type"] + "-result"
        or receipt.request_id != q["request_id"]
        or receipt.service != q["service"]
    ):
        raise ValueError("capacity command/readback correlation")
    if receipt.status != "ok" or receipt.error is not None:
        raise ValueError("partial capacity mutation; retain raw evidence, never retry")
    return receipt


def validate_capacity_replay(
    command: CapacityReceipt,
    readback: CapacityReceipt,
    *,
    plan: str,
    service: int,
    original_vehicle: int,
    engine: int,
    cargo: int,
    capacity: int,
    source: int,
    destination: int,
    full_load_flag: int,
    no_load_flag: int,
    max_cost: int,
    running_states: tuple[int, ...] = (0, 3),
) -> dict[str, int]:
    """Validate against frozen service facts and a later independent read request."""
    expected_orders = [(source, full_load_flag, True), (destination, no_load_flag, True)]
    if command.type != "capacity-add-result" or readback.type != "capacity-read-result":
        raise ValueError("independent capacity readback required")
    for r in (command, readback):
        if (
            r.status != "ok"
            or r.error is not None
            or r.protocol != 1
            or r.plan != plan
            or r.service != service
            or r.original_vehicle != original_vehicle
            or r.vehicle == original_vehicle
            or r.vehicle < 0
            or r.owner != 0
            or r.engine != engine
            or r.cargo != cargo
            or r.capacity != capacity
            or r.orders != expected_orders
            or r.state not in running_states
            or r.tick < 0
            or r.economy_date < 0
        ):
            raise ValueError("capacity identity or orders mismatch")
    if (
        command.request_id == readback.request_id
        or command.vehicle != readback.vehicle
        or readback.tick < command.tick
        or readback.economy_date < command.economy_date
        or not 0 < command.purchase_capex <= max_cost
        or command.cash_before - command.cash_after != command.purchase_capex
        or len(command.commands) != 4
    ):
        raise ValueError("capacity receipt completeness or finance mismatch")
    for stage, row in enumerate(command.commands):
        n, success, quote, cost, before, after = row
        if (
            n != stage
            or not success
            or quote != cost
            or cost != (command.purchase_capex if stage == 0 else 0)
            or before - after != cost
            or (stage == 0 and before != command.cash_before)
            or (stage > 0 and before != command.commands[stage - 1][5])
        ):
            raise ValueError("partial capacity command sequence")
    if (
        command.commands[-1][5] != command.cash_after
        or readback.purchase_capex != command.purchase_capex
        or readback.commands != command.commands
        or readback.cash_before != command.cash_before
        or readback.cash_after != command.cash_after
    ):
        raise ValueError("capacity finance binding")
    return {
        "service": service,
        "vehicle": command.vehicle,
        "purchase_capex": command.purchase_capex,
    }


def decode_capacity_wire(payload: bytes) -> bytes:
    """Decode only native capacity replies within GSAdmin's 1,450-byte JSON limit."""
    if not 1 < len(payload) <= 1451 or not payload.endswith(b"\0"):
        raise ValueError("capacity native packet bound or terminator")
    raw = payload[:-1]
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("type") not in (
        "capacity-add-result",
        "capacity-read-result",
    ):
        raise ValueError("typed native capacity reply required")
    return raw
