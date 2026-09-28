"""Dependency-neutral canonical planning JSON and content digests."""

import hashlib
import json
import unicodedata
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.planning.domain import ExecutionPlan, PlanningScenario, PreparedWorldManifest, Tile

_ID_COLLECTIONS = {
    "locations": "location_id",
    "cargo_demands": "demand_id",
    "fleet_options": "option_id",
    "infrastructure_candidates": "candidate_id",
    "routes": "route_id",
    "groups": "fleet_group_id",
    "supported_modes": None,
    "permitted_modes": None,
    "compatible_cargo_types": None,
    "route_ids": None,
    "demand_ids": None,
    "infrastructure_ids": None,
    "depends_on": None,
    "resolved_sites": "location_id",
    "cargo_types": None,
    "vehicle_types": None,
}


def _decimal_string(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("nonfinite decimal")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        return {name: _json_field(name, getattr(value, name)) for name in fields}
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    raise ValueError("noncanonical planning value")


def _json_field(name: str, value: object) -> object:
    if not isinstance(value, tuple):
        return _json_value(value)
    key = _ID_COLLECTIONS.get(name, "ordered")
    if key == "ordered":
        if name == "buildable_tiles":
            if not all(isinstance(item, Tile) for item in value):
                raise ValueError("buildable tile is invalid")
            return [_json_value(item) for item in sorted(value, key=lambda item: (item.y, item.x))]
        return [_json_value(item) for item in value]
    if key is None:
        if not all(isinstance(item, str) for item in value):
            raise ValueError("unordered reference must be a string")
        return sorted(unicodedata.normalize("NFC", str(item)) for item in value)
    return [_json_value(item) for item in sorted(value, key=lambda item: getattr(item, key))]


def canonical_bytes(model: BaseModel) -> bytes:
    """Stable UTF-8 JSON. Stops and construction actions retain their order."""
    return json.dumps(
        _json_value(model),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def plan_hash(plan: ExecutionPlan) -> str:
    """SHA-256 of semantic plan bytes; estimated metrics and artifact metadata excluded."""
    return hashlib.sha256(canonical_bytes(plan)).hexdigest()


def scenario_hash(scenario: PlanningScenario) -> str:
    """Identity of the full planner-visible snapshot, separate from world fingerprint."""
    return hashlib.sha256(canonical_bytes(scenario)).hexdigest()


def world_manifest_hash(manifest: PreparedWorldManifest) -> str:
    """SHA-256 of typed world evidence and generation identity."""
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()
