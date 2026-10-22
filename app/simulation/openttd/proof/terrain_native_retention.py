"""Native outer durable provenance; original disposable paths are labels only."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from app.simulation.openttd.runtime.ownership import OwnershipGraph, PathClass

from .historical_protection import explicit_protection_base, validate_protection
from .terrain_retention import _public_input, retain_inputs

POLICY = "terrain-native-durable-canonical-v1"


def retain_native_inputs(candidate, stage: Path) -> dict:
    """Retain reviewed public bytes in a caller-owned disposable seal stage."""
    index = retain_inputs(candidate, stage)
    index["policy"] = POLICY
    (stage / "canonical-inputs.json").write_text(json.dumps(index, sort_keys=True, indent=2) + "\n")
    return index


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path) != value or path != path.resolve():
        raise ValueError("Canonical provenance path alias")
    return path


def _document(content: Mapping[str, bytes], name: str, expected: str):
    raw = content["seal/" + name]
    if _digest(raw) != expected:
        raise ValueError("Native provenance differs from immutable preparation")
    return json.loads(raw)


def verify_native_inputs(
    content: Mapping[str, bytes], prelaunch: dict, external_authorities: Mapping[str, Path]
) -> dict[str, bytes]:
    """Verify pinned native provenance without reopening deleted canonical originals.

    The caller has validated PRELAUNCH against its independent pin. Content keys
    are exact outer-package relative paths; the outer inventory validator owns
    filesystem type checks before constructing this bytes mapping.
    """
    try:
        source = prelaunch["source"]
        frozen = _document(content, "source-freeze.json", source["source_freeze_sha256"])
        index = _document(content, "canonical-inputs.json", source["canonical_inputs_sha256"])
        if set(index) != {"policy", "candidate_path", "entries"} or index["policy"] != POLICY:
            raise ValueError("Native canonical provenance schema mismatch")
        base = _absolute(index["candidate_path"])
        if not isinstance(frozen, dict):
            raise ValueError("Native source freeze schema mismatch")
        retained: dict[str, bytes] = {}
        identities: set[str] = set()
        objects: set[str] = set()
        candidate_input = source["candidate"]
        for entry in index["entries"]:
            if set(entry) != {"identity", "origin", "artifact", "sha256"}:
                raise ValueError("Native canonical entry schema mismatch")
            origin, identity, artifact, digest = (
                entry[k] for k in ("origin", "identity", "artifact", "sha256")
            )
            path = _absolute(origin)
            relative = path.relative_to(base).as_posix() if path.is_relative_to(base) else None
            expected_identity = "candidate:" + relative if relative else "source:" + origin
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or artifact != "canonical/" + digest
                or origin in retained
                or identity in identities
                or identity != expected_identity
                or frozen.get(origin) != digest
            ):
                raise ValueError("Native canonical identity provenance mismatch")
            raw = content["seal/" + artifact]
            if _digest(raw) != digest:
                raise ValueError("Native canonical content mismatch")
            retained[origin] = raw
            identities.add(identity)
            objects.add("seal/" + artifact)
        if {n for n in content if n.startswith("seal/canonical/")} != objects:
            raise ValueError("Unexpected native canonical artifacts")
        candidate_raw = retained[str(base / "CANDIDATE.json")]
        if (
            candidate_input["identity"] != "candidate:CANDIDATE.json"
            or candidate_input["origin"] != str(base / "CANDIDATE.json")
            or candidate_input["sha256"] != _digest(candidate_raw)
            or candidate_input["byte_length"] != len(candidate_raw)
        ):
            raise ValueError("Native reviewed candidate provenance mismatch")
        candidate = json.loads(candidate_raw)
        original = dict(candidate["source_integrity"])
        original[str(base / "CANDIDATE.json")] = candidate_input["sha256"]
        if {e["origin"]: e["sha256"] for e in index["entries"]} != original:
            raise ValueError("Native original source coverage mismatch")
        for relative, digest in candidate["files"].items():
            if frozen.get(str(base / relative)) != digest:
                raise ValueError("Native candidate file provenance mismatch")
        for origin, raw in retained.items():
            path = Path(origin)
            if path.is_relative_to(base):
                _public_input(path.relative_to(base).as_posix(), raw, candidate)
            elif path.name == ".admin-secret" or path.suffix == ".cfg":
                raise ValueError("Private canonical source forbidden")
        seal_base = _absolute(prelaunch["attempt"]["seal_destination"])
        for origin, digest in frozen.items():
            if origin in retained:
                continue
            path = _absolute(origin)
            if not path.is_relative_to(seal_base):
                raise ValueError("Incomplete native durable source coverage")
            artifact = "seal/" + path.relative_to(seal_base).as_posix()
            if _digest(content[artifact]) != digest:
                raise ValueError("Native seal metadata coverage mismatch")
        materializations = _document(
            content, "runtime-materializations.json", source["materializations_sha256"]
        )
        if materializations != json.loads(retained[str(base / "runtime-materializations.json")]):
            raise ValueError("Native materialization provenance mismatch")
        ownership = _document(content, "path-ownership.json", source["ownership_sha256"])
        _verify_ownership(ownership, materializations, frozen, candidate, prelaunch)
        runtime = prelaunch["runtime"]
        for item in [
            runtime["executable"],
            runtime["graphics_archive"],
            *runtime["graphics_files"],
            *runtime["bridge_inputs"],
            *runtime["public_config"],
        ]:
            raw = retained[item["origin"]]
            if (
                item["identity"] not in identities
                or not any(
                    e["identity"] == item["identity"] and e["origin"] == item["origin"]
                    for e in index["entries"]
                )
                or len(raw) != item["byte_length"]
                or _digest(raw) != item["sha256"]
            ):
                raise ValueError("Native runtime input identity mismatch")
        if (
            candidate["argv"] != runtime["argv"]
            or candidate["environment"] != runtime["environment"]
        ):
            raise ValueError("Native runtime candidate provenance mismatch")
        from .terrain_preparation import digest, package_digest

        if (
            candidate["executable_digest"] != runtime["executable"]["sha256"]
            or candidate["graphics_digest"] != runtime["graphics_archive"]["sha256"]
            or json.loads(retained[str(base / "source.json")]) != candidate["source"]
            or digest(candidate["source"]) != candidate["source_digest"]
            or package_digest(
                {name: retained[str(base / "bridge" / name)] for name in ("info.nut", "main.nut")}
            )
            != candidate["bridge_digest"]
            or _digest(retained[str(base / "materialization-inputs/openttd.cfg")])
            != candidate["configuration_digest"]
        ):
            raise ValueError("Native canonical semantic source provenance mismatch")
        history = _document(
            content, "historical-integrity.json", source["historical_integrity_sha256"]
        )
        (authority,) = prelaunch["external_authorities"]
        if authority["inventory_sha256"] != source["historical_integrity_sha256"]:
            raise ValueError("Native historical authority commitment mismatch")
        trusted = external_authorities[authority["identity"]]
        if str(trusted) != authority["provenance_base"]:
            raise ValueError("Native historical independent authority mismatch")
        validate_protection(explicit_protection_base(history, trusted), history)
        return retained
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError("Required native durable provenance unavailable") from error


def _verify_ownership(value, materializations, frozen, candidate, prelaunch):
    if set(value) != {"policy", "cleanup_roots", "entries"} or any(
        set(e) != {"path", "kind"} for e in value["entries"]
    ):
        raise ValueError("Native ownership schema mismatch")
    graph = OwnershipGraph.from_public(value)
    root = _absolute(candidate["workspace"])
    if (
        graph.cleanup_roots != (root,)
        or materializations["policy"] != "frozen-content-disposable-path-v1"
        or materializations["workspace"] != str(root)
    ):
        raise ValueError("Native disposable ownership root mismatch")
    kinds = {str(e.path): e.kind for e in graph.entries}
    required = {p: PathClass.IMMUTABLE_SOURCE for p in frozen}
    seal = prelaunch["attempt"]["seal_destination"]
    required.update(
        {
            str(Path(seal) / n): PathClass.IMMUTABLE_SOURCE
            for n in ("source-freeze.json", "artifact-manifest.sha256")
        }
    )
    required[candidate["key_path"]] = PathClass.RUNTIME_CREDENTIAL
    required[prelaunch["attempt"]["destination"]] = PathClass.GENERATED_EVIDENCE
    required.update({p: PathClass.RUNTIME_EPHEMERAL for p in candidate["capture_outputs"]})
    seen = set()
    for row in materializations["entries"]:
        if (
            set(row)
            != {
                "path",
                "sha256",
                "canonical_source",
                "canonical_sha256",
                "derivation",
                "classification",
            }
            or row["path"] in seen
        ):
            raise ValueError("Native materialization schema mismatch")
        seen.add(row["path"])
        derivation = row["derivation"]
        generated = derivation == "generated-template-copy"
        if row["classification"] != ("GENERATED_RUNTIME" if generated else "RUNTIME_COPY") or not (
            derivation in ("byte-copy", "generated-template-copy")
            or derivation.startswith("archive-member:opengfx-8.0/")
        ):
            raise ValueError("Native materialization ownership mismatch")
        if frozen.get(row["canonical_source"]) != row["canonical_sha256"] or (
            derivation in ("byte-copy", "generated-template-copy")
            and row["sha256"] != row["canonical_sha256"]
        ):
            raise ValueError("Native materialization content relationship mismatch")
        required[row["path"]] = PathClass.RUNTIME_EPHEMERAL
    if kinds != required:
        raise ValueError("Native ownership path classification mismatch")
