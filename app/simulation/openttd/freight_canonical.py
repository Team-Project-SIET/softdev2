"""Strict offline correspondence for canonical fleet qualification.

These checks compare evidence supplied by a native collector. They neither
launch OpenTTD nor establish that caller-supplied observations are native.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Index = Annotated[int, Field(strict=True, ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Order(Record):
    destination: Index
    flags: Index
    goto_station: Literal[True]


class FleetVehicle(Record):
    service: Literal[0, 1, 2]
    vehicle: Index
    owner: Literal[0]
    engine: Index
    cargo: Index
    capacity: Annotated[int, Field(strict=True, gt=0)]
    tile: Index
    stopped: Literal[True]
    in_depot: Literal[True]
    speed: Literal[0]
    load: Literal[0]
    orders: tuple[Order, Order]


class CanonicalState(Record):
    """Complete semantic boundary; only collector metadata is excluded."""

    economy_date: Index
    economy_date_fraction: Index
    calendar_date: Index
    calendar_date_fraction: Index
    timekeeping: Literal[0, 1]
    paused: Literal[True]
    auto_renew: Literal[False]
    company: Literal[0]
    cash: Annotated[int, Field(strict=True)]
    loan: Index
    # Exact enumerated observations, not hashes or caller readiness labels.
    map: Annotated[dict, Field(min_length=1)]
    industries_production: Annotated[list[dict], Field(min_length=1)]
    stations_cargo: Annotated[list[dict], Field(min_length=1)]
    infrastructure: Annotated[list[dict], Field(min_length=1)]
    vehicles: tuple[FleetVehicle, FleetVehicle, FleetVehicle]
    delivered: tuple[Literal[0], Literal[0], Literal[0]]

    @model_validator(mode="after")
    def bindings(self):
        if tuple(v.service for v in self.vehicles) != (0, 1, 2):
            raise ValueError("exact ordered logical service bindings required")
        if len({v.vehicle for v in self.vehicles}) != 3:
            raise ValueError("distinct physical vehicle bindings required")
        return self


class CanonicalObservation(Record):
    qualification_id: Annotated[str, Field(min_length=1, max_length=80)]
    runtime_sha256: Digest
    bridge_sha256: Digest
    configuration_sha256: Digest
    source_save_sha256: Digest
    raw_readback_sha256: Digest
    # Process-local tick/request/log metadata may change across reload.
    script_tick: Index
    state: CanonicalState


def compare_canonical(created: CanonicalObservation, loaded: CanonicalObservation) -> None:
    """Exact state equality, including dates, IDs, positions and cargo.

    Qualification ID, raw readback hash and script tick are the only excluded
    fields. Runtime/config/bridge and loaded source bytes must remain identical.
    A successful comparison is correspondence only, never native provenance.
    """
    if created.qualification_id == loaded.qualification_id:
        raise ValueError("creation and reload require distinct qualification identities")
    for key in (
        "runtime_sha256",
        "bridge_sha256",
        "configuration_sha256",
        "source_save_sha256",
        "state",
    ):
        if getattr(created, key) != getattr(loaded, key):
            raise ValueError(f"canonical correspondence mismatch: {key}")


def seal_canonical_inputs(
    destination: Path, save: Path, observation: CanonicalObservation, raw_readback: Path
) -> str:
    """Create an exclusive provenance record; never overwrite historical files.

    Keep the original .sav and raw transcript immutable alongside this record.
    This is an offline integrity seal and contains no native success assertion.
    """
    for path in (save, raw_readback, destination):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("canonical evidence must not traverse symlinks")
    save_digest = hashlib.sha256(save.read_bytes()).hexdigest()
    raw_digest = hashlib.sha256(raw_readback.read_bytes()).hexdigest()
    if (save_digest, raw_digest) != (
        observation.source_save_sha256,
        observation.raw_readback_sha256,
    ):
        raise ValueError("canonical evidence bytes mismatch")
    payload = (
        json.dumps(
            dict(
                schema=1,
                classification="OFFLINE_INTEGRITY_ONLY",
                observation=observation.model_dump(mode="json"),
            ),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        + b"\n"
    )
    with destination.open("xb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()
