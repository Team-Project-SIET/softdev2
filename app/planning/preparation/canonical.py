"""P08 canonical reparse and independent artifact identities."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from app.planning.canonical import canonical_bytes
from app.planning.execution import ExecutionBindings
from app.planning.preparation.domain import ExtractedWorldSnapshot

_ENUMERATIONS = {
    "industries": "industry_id",
    "cargos": "cargo_id",
    "cargo_facts": "cargo_id",
    "station_sampling": "role",
    "cargo_ids": "identifier",
    "rail_types": "identifier",
}


def _normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        items = [_normalize(v) for v in value]
        if key in _ENUMERATIONS:
            return sorted(items, key=lambda v: v[_ENUMERATIONS[key]])
        if key == "footprint":
            return sorted(items)
        return items
    return value


def preparation_bytes(model: BaseModel) -> bytes:
    """Enumeration normalization never changes corridor tile sequence."""
    parsed = type(model).model_validate_json(model.model_dump_json())
    value = _normalize(json.loads(canonical_bytes(parsed)))
    if isinstance(parsed, ExtractedWorldSnapshot):
        value["tiles"] = sorted(value["tiles"], key=lambda t: t["tile_index"])
        value["engines"] = sorted(value["engines"], key=lambda e: e["engine_id"])
    # ExecutionBindings.engines use vehicle labels, not extraction native engine IDs.
    if isinstance(parsed, ExecutionBindings):
        value["engines"] = sorted(value["engines"], key=lambda e: e["vehicle_type"])
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def authoritative[T: BaseModel](model: T) -> T:
    return type(model).model_validate_json(preparation_bytes(model))


def artifact_hash(model: BaseModel) -> str:
    return hashlib.sha256(preparation_bytes(authoritative(model))).hexdigest()


def authoritative_snapshot(snapshot: ExtractedWorldSnapshot) -> ExtractedWorldSnapshot:
    return authoritative(snapshot)


def snapshot_hash(snapshot: ExtractedWorldSnapshot) -> str:
    return artifact_hash(snapshot)
