"""CONTROLLED-only offline validation of REAL-shaped outer evidence.

There is no launch, authorization-token or genuine REAL acceptance API here.
Caller pins and the declared historical authority remain external trust inputs.
"""

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_paired_evidence import (
    Context,
    _inventory,
    _manifest,
    _plans,
    _read,
    _root,
    verify_paired_package,
)
from app.simulation.openttd.terrain_sweeps import (
    TerrainTwoSweep,
    TwoSweepBudget,
    VerifiedTerrainPair,
)
from app.simulation.openttd.tile_facts import TileFactsRequest

SCHEMA = "terrain-native-paired-evidence-v1"
OPERATION = "openttd-15.3.tile_facts_page.two_sweeps"
COMMON = frozenset(
    {
        "seal/PRELAUNCH.json",
        "seal/SEAL.sha256",
        "seal/artifact-manifest.sha256",
        "authorization-consumed.json",
        "runtime.json",
        "authentication.json",
        "frame-accounting.json",
        "lifecycle.json",
        "execution-log.json",
        "stdout.log",
        "stderr.log",
        "cleanup.raw.json",
        "cleanup.json",
        "credential-disposal.json",
        "post-run-integrity.json",
        "result.json",
        "completion.json",
        "artifact-manifest.sha256",
    }
)
SEAL_METADATA = frozenset(
    {
        "seal/source-freeze.json",
        "seal/canonical-inputs.json",
        "seal/path-ownership.json",
        "seal/runtime-materializations.json",
        "seal/historical-integrity.json",
        "seal/page-plan.json",
    }
)
KINDS = (
    "runtime",
    "authentication",
    "frame-accounting",
    "lifecycle",
    "execution-log",
    "cleanup.raw",
    "cleanup",
    "credential-disposal",
    "post-run-integrity",
    "result",
)


@dataclass(frozen=True)
class NativePackagePins:
    """Writer measurements, to be separately reviewed/pinned by controlled callers."""

    prelaunch_sha256: str
    completion_sha256: str


@dataclass(frozen=True)
class ControlledNativeContractResult:
    """Computational validation of synthetic native attestations, never REAL_PASS."""

    status: Literal["CONTROLLED_CONTRACT_ACCEPTED", "CONTROLLED_CONTRACT_FAILURE_RETAINED"]
    prelaunch_sha256: str
    completion_sha256: str
    pair: VerifiedTerrainPair | None

    def __post_init__(self) -> None:
        if self.status not in (
            "CONTROLLED_CONTRACT_ACCEPTED",
            "CONTROLLED_CONTRACT_FAILURE_RETAINED",
        ):
            raise ValueError("result: Invalid controlled contract status")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pin(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("commitment: Missing or invalid independently supplied pin")


def _json(raw: bytes):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("schema: Duplicate JSON field")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=unique)


def _encode(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _plan(prelaunch) -> dict:
    context = Context.model_validate_json(_encode(prelaunch["context"]))
    replay = TerrainTwoSweep(
        context.runtime(),
        per_sweep_budget=PaginationBudget(**prelaunch["budgets"]["per_sweep"]),
        combined_budget=TwoSweepBudget(**prelaunch["budgets"]["combined"]),
    )
    sweeps = []
    for sweep in _plans(replay, context):
        pages = []
        for page in sweep.pages:
            q = TileFactsRequest(page.request_id, context.region, page.cursor).to_bytes()
            pages.append(
                dict(
                    ordinal=page.ordinal,
                    request_id=page.request_id,
                    cursor=page.cursor,
                    tile_ids=list(page.tile_ids),
                    request_byte_length=len(q),
                    request_sha256=_sha(q),
                )
            )
        sweeps.append(dict(identity=sweep.identity.model_dump(mode="json"), pages=pages))
    return dict(schema=SCHEMA, version=1, context=prelaunch["context"], sweeps=sweeps)


def _expected(prelaunch, records) -> set[str]:
    commitments = [a["path"] for a in prelaunch["commitments"]]
    if commitments != sorted(set(commitments)) or not SEAL_METADATA.issubset(commitments):
        raise ValueError("inventory: Invalid sealed commitment identities")
    for path in commitments:
        if path not in SEAL_METADATA and not re.fullmatch(r"seal/canonical/[0-9a-f]{64}", path):
            raise ValueError("inventory: Unexpected sealed artifact identity")
    expected = set(COMMON) | set(commitments)
    life = records["lifecycle"]["observations"]
    events = life.get("events", []) if life["available"] else []
    names = [e["event"] for e in events]
    if "claimed" in names:
        expected.add("launch-claim.json")
    if "invocation_recorded" in names:
        expected.add("native-launch-claimed.json")
    admitted = [(e["sweep"], e["page"]) for e in events if e["event"] == "page_admitted"]
    result = records["result"]["observations"]
    successful = result["available"] and result["status"] == "REAL_PASS"
    all_pages = [
        (s, p["ordinal"])
        for s, sweep in enumerate(_plan(prelaunch)["sweeps"], 1)
        for p in sweep["pages"]
    ]
    if successful and admitted != all_pages:
        raise ValueError("inventory: Successful lifecycle does not admit exact two-sweep plan")
    if admitted != all_pages[: len(admitted)] or len(admitted) != len(set(admitted)):
        raise ValueError("inventory: Nonsequential or duplicated admitted page prefix")
    if admitted:
        expected.update(
            {"paired/package.json", "paired/summary.json", "paired/artifact-manifest.sha256"}
        )
        for sweep, page in admitted:
            for name in ("request", "response", "exchange"):
                expected.add(f"paired/pages/s{sweep}/p{page:03d}/{name}.json")
    return expected


def _records(content, prelaunch_digest):
    from app.simulation.openttd.terrain_native_records import (
        parse_claim,
        parse_grant,
        parse_invocation,
        parse_record,
    )

    records = {}
    for kind in KINDS:
        model = parse_record(content[kind + ".json"])
        value = model.model_dump(mode="json", by_alias=True)
        if value["kind"] != kind or value["prelaunch_sha256"] != prelaunch_digest:
            raise ValueError("lineage: Record kind or prelaunch commitment mismatch")
        records[kind] = value
    for path, parser in (
        ("authorization-consumed.json", parse_grant),
        ("launch-claim.json", parse_claim),
        ("native-launch-claimed.json", parse_invocation),
    ):
        if path in content:
            records[path.removesuffix(".json")] = parser(content[path]).model_dump(
                mode="json", by_alias=True
            )
    return records


def verify_native_paired_package(
    directory: Path,
    *,
    expected_prelaunch_sha256: str,
    expected_completion_sha256: str,
    immutable_authorities: Mapping[str, Path],
) -> ControlledNativeContractResult:
    """Validate REAL-shaped synthetic records; no operator/native certification."""
    from app.simulation.openttd.proof.terrain_native_retention import verify_native_inputs
    from app.simulation.openttd.terrain_native_records import parse_completion, parse_prelaunch
    from app.simulation.openttd.terrain_native_validation import validate_observations

    _pin(expected_prelaunch_sha256)
    _pin(expected_completion_sha256)
    root = _root(directory)
    try:
        prelaunch_raw = _read(root, "seal/PRELAUNCH.json", 262144)
        completion_raw = _read(root, "completion.json", 262144)
        if (
            _sha(prelaunch_raw) != expected_prelaunch_sha256
            or _sha(completion_raw) != expected_completion_sha256
        ):
            raise ValueError("commitment: Independently pinned descriptor mismatch")
        prelaunch = parse_prelaunch(prelaunch_raw).model_dump(mode="json", by_alias=True)
        completion = parse_completion(completion_raw).model_dump(mode="json", by_alias=True)
        if (
            completion["prelaunch_sha256"] != expected_prelaunch_sha256
            or completion["attempt_identity"] != prelaunch["attempt"]["identity"]
        ):
            raise ValueError("lineage: Completion/prelaunch mismatch")
        # Only fixed record names may be read before the authoritative inventory is derived.
        content = {"seal/PRELAUNCH.json": prelaunch_raw, "completion.json": completion_raw}
        for kind in KINDS:
            content[kind + ".json"] = _read(root, kind + ".json", 262144)
        records = _records(
            content
            | {"authorization-consumed.json": _read(root, "authorization-consumed.json", 8192)},
            expected_prelaunch_sha256,
        )
        expected = _expected(prelaunch, records)
        _inventory(root, expected)
        entries = completion["artifacts"]
        identities = [a["path"] for a in entries]
        if identities != sorted(expected - {"completion.json", "artifact-manifest.sha256"}):
            raise ValueError("inventory: Completion identities differ from authoritative inventory")
        total = len(prelaunch_raw) + len(completion_raw)
        cap = prelaunch["resources"]["outer_bytes"]
        if len(expected) != prelaunch["resources"]["outer_files"]:
            raise ValueError("inventory: Sealed file count mismatch")
        for entry in entries:
            length = entry["byte_length"]
            if total + length > cap:
                raise ValueError("bytes: Sealed package byte ceiling exceeded")
            raw = content.get(entry["path"])
            if raw is None:
                raw = _read(root, entry["path"], length)
            if len(raw) != length or _sha(raw) != entry["sha256"]:
                raise ValueError("bytes: Retained artifact commitment mismatch")
            content[entry["path"]] = raw
            if entry["path"] != "seal/PRELAUNCH.json":
                total += length
        content["artifact-manifest.sha256"] = _read(root, "artifact-manifest.sha256", 262144)
        if total + len(content["artifact-manifest.sha256"]) > cap:
            raise ValueError("bytes: Package read ceiling exceeded")
        if content["artifact-manifest.sha256"] != _manifest(content):
            raise ValueError("bytes: Outer manifest mismatch")
        if content["seal/SEAL.sha256"] != (expected_prelaunch_sha256 + "\n").encode("ascii"):
            raise ValueError("commitment: Seal representation mismatch")
        seal_content = {p[5:]: raw for p, raw in content.items() if p.startswith("seal/")}
        if seal_content["artifact-manifest.sha256"] != _manifest(seal_content):
            raise ValueError("bytes: Seal manifest mismatch")
        for entry in prelaunch["commitments"]:
            raw = content[entry["path"]]
            if len(raw) != entry["byte_length"] or _sha(raw) != entry["sha256"]:
                raise ValueError("commitment: Seal member differs from prelaunch")
        plan = _json(content["seal/page-plan.json"])
        if content["seal/page-plan.json"] != _encode(_plan(prelaunch)) or plan != _plan(prelaunch):
            raise ValueError("plan: Retained scheduling differs from production pagination")
        verify_native_inputs(content, prelaunch, immutable_authorities)
        records = _records(content, expected_prelaunch_sha256)
        records["page-plan"] = plan
        pair = None
        if "paired/package.json" in content:
            pair_digest = _sha(content["paired/package.json"])
            if pair_digest != completion["paired_descriptor_sha256"]:
                raise ValueError("commitment: Embedded descriptor binding mismatch")
            pair = verify_paired_package(
                directory / "paired", expected_descriptor_sha256=pair_digest
            )
            if pair.context != Context.model_validate_json(_encode(prelaunch["context"])).runtime():
                raise ValueError("replay: Embedded context differs from prelaunch")
            if pair.per_sweep_budget != PaginationBudget(
                **prelaunch["budgets"]["per_sweep"]
            ) or pair.combined_budget != TwoSweepBudget(**prelaunch["budgets"]["combined"]):
                raise ValueError("replay: Embedded budgets differ from prelaunch")
        elif completion["paired_descriptor_sha256"] is not None:
            raise ValueError("commitment: Paired descriptor present without package")
        status = validate_observations(prelaunch, records, content, pair)
        result = records["result"]["observations"]
        if (
            completion["status"] != result["status"]
            or completion["terminal_phase"] != result["terminal_phase"]
        ):
            raise ValueError("result: Completion contradicts validated result")
        return ControlledNativeContractResult(
            status, expected_prelaunch_sha256, expected_completion_sha256, pair
        )
    except OSError as error:
        raise ValueError("inventory: Unreadable retained outer package") from error
    finally:
        os.close(root)


def write_native_paired_package(
    directory: Path,
    *,
    content: Mapping[str, bytes],
    immutable_authorities: Mapping[str, Path],
) -> NativePackagePins:
    """Serialize a new CONTROLLED fixture; returned measurements confer no authority."""
    from app.simulation.openttd.terrain_native_records import parse_completion, parse_prelaunch

    payloads = dict(content)
    if "completion.json" in payloads or "artifact-manifest.sha256" in payloads:
        raise ValueError("writer: Completion/manifests are derived, not supplied")
    prelaunch = parse_prelaunch(payloads["seal/PRELAUNCH.json"]).model_dump(
        mode="json", by_alias=True
    )
    pinned = _sha(payloads["seal/PRELAUNCH.json"])
    records = _records(payloads, pinned)
    expected = _expected(prelaunch, records) - {"completion.json", "artifact-manifest.sha256"}
    if set(payloads) != expected:
        raise ValueError("inventory: Writer inputs differ from authoritative inventory")
    completion = dict(
        schema=SCHEMA,
        version=1,
        mode="REAL",
        operation=OPERATION,
        attempt_identity=prelaunch["attempt"]["identity"],
        prelaunch_sha256=pinned,
        status=records["result"]["observations"]["status"],
        terminal_phase=records["result"]["observations"]["terminal_phase"],
        paired_descriptor_sha256=_sha(payloads["paired/package.json"])
        if "paired/package.json" in payloads
        else None,
        artifacts=[
            dict(path=p, byte_length=len(raw), sha256=_sha(raw))
            for p, raw in sorted(payloads.items())
        ],
    )
    completion_raw = _encode(completion)
    parse_completion(completion_raw)
    payloads["completion.json"] = completion_raw
    payloads["artifact-manifest.sha256"] = _manifest(payloads)
    directory.mkdir(mode=0o700, exist_ok=True)
    root = _root(directory)
    try:
        if os.listdir(root):
            raise ValueError("inventory: Writer requires empty owned directory")
        for path, raw in payloads.items():
            target = directory / path
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
    finally:
        os.close(root)
    pins = NativePackagePins(pinned, _sha(completion_raw))
    verify_native_paired_package(
        directory,
        expected_prelaunch_sha256=pins.prelaunch_sha256,
        expected_completion_sha256=pins.completion_sha256,
        immutable_authorities=immutable_authorities,
    )
    return pins
