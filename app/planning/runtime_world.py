"""P03 runtime identity v1: dimensions, seed and required existing world objects.

This projection is not the full prepared-world manifest identity. Planner labels,
provenance and unbuilt candidates are excluded. Object order is insignificant.
"""

import hashlib
import re
from typing import Literal

from pydantic import Field, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, PreparedWorldManifest
from app.planning.setup_evidence import SetupEvidenceError


class RuntimeWorldObject(Contract):
    kind: Literal["industry", "station"]
    object_id: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class RuntimeWorldObservation(Contract):
    schema_version: Literal[1] = 1
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    seed: int = Field(ge=0)
    objects: tuple[RuntimeWorldObject, ...]

    @model_validator(mode="after")
    def valid_objects(self):
        identities = [(o.kind, o.object_id) for o in self.objects]
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("runtime objects must be nonempty and unique")
        if any(o.x >= self.width or o.y >= self.height for o in self.objects):
            raise ValueError("runtime object outside map")
        return self


def runtime_projection_from_manifest(manifest: PreparedWorldManifest) -> RuntimeWorldObservation:
    objects: dict[tuple[str, int], RuntimeWorldObject] = {}
    for site in manifest.resolved_sites:
        if site.world_kind is None or site.world_id is None:
            continue
        obj = RuntimeWorldObject(
            kind=site.world_kind, object_id=site.world_id, x=site.tile.x, y=site.tile.y
        )
        key = (obj.kind, obj.object_id)
        if key in objects and objects[key] != obj:
            raise ValueError("conflicting expected runtime object")
        objects[key] = obj
    return RuntimeWorldObservation(
        width=manifest.width_tiles,
        height=manifest.height_tiles,
        seed=manifest.seed,
        objects=tuple(objects.values()),
    )


def runtime_world_hash(observation: RuntimeWorldObservation) -> str:
    ordered = observation.model_copy(
        update={
            "objects": tuple(sorted(observation.objects, key=lambda obj: (obj.kind, obj.object_id)))
        }
    )
    return hashlib.sha256(canonical_bytes(ordered)).hexdigest()


_INFO = re.compile(r"^dbg: \[script\] \[(\d+)\] \[I\] (.*)$")
_OBSERVATION = "P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|"
_SUCCESS = "P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_SUCCEEDED|"


def parse_runtime_world_evidence(
    log: str, expected: RuntimeWorldObservation, expected_plan_hash: str
) -> dict:
    """Require one observation, then one success, from the receipt's AI instance.

    The observed hash function receives only values parsed from the observation.
    Plan hash is envelope correlation, never an input to runtime identity hashing.
    """
    messages = [
        (index, int(m[1]), m[2])
        for index, line in enumerate(log.splitlines())
        if (m := _INFO.fullmatch(line)) is not None
    ]
    observations = [row for row in messages if row[2].startswith(_OBSERVATION)]
    successes = [row for row in messages if row[2].startswith(_SUCCESS)]
    receipts = [row for row in messages if row[2].startswith("P03_EXECUTOR_AI|P03_SETUP_V1|")]
    if len(observations) != 1 or len(successes) != 1 or len(receipts) != 1:
        raise SetupEvidenceError("require one runtime observation, validation success and receipt")
    observation_row, success, receipt = observations[0], successes[0], receipts[0]
    if (
        not (observation_row[0] < success[0] < receipt[0])
        or len({observation_row[1], success[1], receipt[1]}) != 1
    ):
        raise SetupEvidenceError("runtime evidence order or instance mismatch")
    if success[2] != _SUCCESS + expected_plan_hash:
        raise SetupEvidenceError("runtime validation plan mismatch")
    try:
        parts = observation_row[2].removeprefix(_OBSERVATION).split("|")
        if len(parts) != 5 or parts[0] != expected_plan_hash:
            raise ValueError("runtime observation envelope")

        def integer(value: str) -> int:
            if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
                raise ValueError("invalid runtime integer")
            return int(value)

        objects = []
        for item in parts[4].split(","):
            kind, identifier, x, y = item.split(":")
            if kind != "industry" and kind != "station":
                raise ValueError("unsupported runtime object kind")
            objects.append(
                RuntimeWorldObject(
                    kind="industry" if kind == "industry" else "station",
                    object_id=integer(identifier),
                    x=integer(x),
                    y=integer(y),
                )
            )
        observed = RuntimeWorldObservation(
            width=integer(parts[1]),
            height=integer(parts[2]),
            seed=integer(parts[3]),
            objects=tuple(objects),
        )
    except ValueError as error:
        raise SetupEvidenceError("malformed runtime observation") from error
    observed_hash = runtime_world_hash(observed)
    expected_hash = runtime_world_hash(expected)
    if observed_hash != expected_hash:
        raise SetupEvidenceError("runtime world hash mismatch")
    return {
        "runtime_observation_schema_version": 1,
        "runtime_world_observation_raw": observation_row[2],
        "runtime_world_observation": observed.model_dump(mode="json"),
        "expected_runtime_world_hash": expected_hash,
        "observed_runtime_world_hash": observed_hash,
        "runtime_world_hash_match": True,
        "thin_ai_world_validation_result": "WORLD_VALIDATION_SUCCEEDED",
        "runtime_instance_id": observation_row[1],
    }
