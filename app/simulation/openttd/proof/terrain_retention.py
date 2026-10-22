"""Terrain seal-owned non-secret canonical copies; live launch checks remain separate."""

import hashlib
import json
from pathlib import Path

from .harness import sha256, write_json

POLICY = "terrain-durable-canonical-v1"
INDEX = "canonical-inputs.json"
CONTENT = "canonical"
LOCAL_INPUTS = {
    "CANDIDATE.json",
    "bridge/info.nut",
    "bridge/main.nut",
    "config-template.cfg",
    "historical-integrity.json",
    "materialization-inputs/.runtime-owned",
    "materialization-inputs/openttd.cfg",
    "materialization-inputs/private.cfg",
    "materialization-inputs/secrets.cfg",
    "path-ownership.json",
    "request.json",
    "runtime-materializations.json",
    "source.json",
}


def _public_input(relative: str, raw: bytes, row: dict) -> None:
    """Only audited public-only configuration is eligible, even with a private filename."""
    if relative not in LOCAL_INPUTS:
        raise ValueError("Undeclared canonical candidate input")
    if relative == "materialization-inputs/secrets.cfg":
        # This exact placeholder contains no password. Nonempty or other secret
        # settings are never retained; this proof only authorizes keyed Admin.
        if raw != b"[version]\nini_version = 7\n[network]\nadmin_password = \n":
            raise ValueError("Secret-bearing configuration cannot enter proof package")
    elif relative == "materialization-inputs/private.cfg":
        expected = (
            "[version]\nini_version = 7\n[server_bind_addresses]\n127.0.0.1\n"
            "[admin_authorized_keys]\n" + row["public_key"] + "\n"
        ).encode()
        if raw != expected:
            raise ValueError("Unaudited private configuration cannot enter proof package")
    elif relative.endswith(".cfg"):
        from .terrain_preparation import configuration_template

        expected = configuration_template()
        if relative == "materialization-inputs/openttd.cfg":
            expected = (
                "[version]\nversion_string = 15.3\nini_version = 7\n[network]\n"
                f"server_port = {row['endpoints'][0]}\nserver_admin_port = {row['endpoints'][1]}\n"
                "server_game_type = local\nmin_active_clients = 0\nreload_cfg = false\n"
                "allow_insecure_admin_login = false\n[gui]" + expected.split("[gui]", 1)[1]
            )
        if raw != expected.encode():
            raise ValueError("Secret-bearing configuration cannot enter proof package")
    elif relative == "materialization-inputs/.runtime-owned":
        if raw != b"OpenTTD 15.3 isolated runtime\n":
            raise ValueError("Unaudited workspace ownership template")


def retain_inputs(candidate, stage: Path) -> dict:
    """Exact checked copies, deduplicated by digest; no workspace traversal or credentials."""
    frozen = dict(candidate.record["source_integrity"])
    from .terrain_preparation import source_freeze

    external = source_freeze()
    external[candidate.record["executable"]] = candidate.record["executable_digest"]
    external[candidate.record["graphics_archive"]] = candidate.record["graphics_digest"]
    for asset in Path(candidate.record["graphics_directory"]).iterdir():
        if asset.is_file():
            external[str(asset.resolve())] = sha256(asset)
    frozen[str(candidate.directory / "CANDIDATE.json")] = sha256(
        candidate.directory / "CANDIDATE.json"
    )
    content = stage / CONTENT
    content.mkdir(mode=0o700)
    entries = []
    for origin, expected in sorted(frozen.items()):
        path = Path(origin)
        if (
            not path.is_absolute()
            or str(path.resolve()) != origin
            or path.is_symlink()
            or not path.is_file()
            or sha256(path) != expected
        ):
            raise ValueError("Canonical source provenance changed before retention")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Canonical source changed during retention")
        if path.is_relative_to(candidate.directory):
            relative = path.relative_to(candidate.directory).as_posix()
            _public_input(relative, raw, candidate.record)
            identity = "candidate:" + relative
        else:
            # All external sources must come from the already validated source
            # inventory, never credential/config files supplied by an arbitrary path.
            if external.get(origin) != expected:
                raise ValueError("Unreviewed external canonical source")
            if path.name == ".admin-secret" or path.suffix == ".cfg":
                raise ValueError("Private source cannot enter proof package")
            identity = "source:" + origin
        artifact = CONTENT + "/" + expected
        target = stage / artifact
        if not target.exists():
            target.write_bytes(raw)
        entries.append(dict(identity=identity, origin=origin, artifact=artifact, sha256=expected))
    index = dict(policy=POLICY, candidate_path=str(candidate.directory), entries=entries)
    write_json(stage / INDEX, index)
    return index


def verify_inputs(directory: Path, record: dict, frozen: dict) -> dict[str, bytes]:
    """Offline copy verification never requires the original temporary candidate paths."""
    try:
        if directory.is_symlink() or (directory / CONTENT).is_symlink():
            raise ValueError("Aliasing canonical artifact root")
        if sha256(directory / INDEX) != record["canonical_inputs_sha256"]:
            raise ValueError("Canonical index differs from seal")
        if sha256(directory / "path-ownership.json") != record["ownership_sha256"]:
            raise ValueError("Ownership metadata differs from immutable seal")
        index = json.loads((directory / INDEX).read_bytes())
        allowed = {
            "PRELAUNCH.json",
            "SEAL.sha256",
            "artifact-manifest.sha256",
            "source-freeze.json",
            "historical-integrity.json",
            "runtime-materializations.json",
            "path-ownership.json",
            "request.json",
            INDEX,
            CONTENT,
        }
        if {p.name for p in directory.iterdir()} != allowed:
            raise ValueError("Unexpected seal artifacts")
        if (
            set(index) != {"policy", "candidate_path", "entries"}
            or index["policy"] != POLICY
            or index["candidate_path"] != record["candidate_path"]
        ):
            raise ValueError("Canonical source provenance mismatch")
        origins, identities, artifacts = set(), set(), set()
        retained = {}
        for entry in index["entries"]:
            if set(entry) != {"identity", "origin", "artifact", "sha256"}:
                raise ValueError("Canonical input schema mismatch")
            origin, identity, artifact, expected = (
                entry[k] for k in ("origin", "identity", "artifact", "sha256")
            )
            if (
                not isinstance(expected, str)
                or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)
                or artifact != CONTENT + "/" + expected
                or origin in origins
                or identity in identities
                or frozen.get(origin) != expected
            ):
                raise ValueError("Canonical identity or source digest mismatch")
            path = directory / artifact
            if path.is_symlink() or not path.is_file() or sha256(path) != expected:
                raise ValueError("Required durable canonical input missing or changed")
            source = Path(origin)
            if not source.is_absolute() or source.absolute() != source.resolve():
                raise ValueError("Canonical source path alias or escape")
            candidate = Path(record["candidate_path"])
            relative = (
                source.relative_to(candidate).as_posix()
                if source.is_relative_to(candidate)
                else None
            )
            expected_identity = "candidate:" + relative if relative else "source:" + origin
            if identity != expected_identity:
                raise ValueError("Canonical original source identity mismatch")
            if relative:
                # Verify safe configuration against the sealed public identity.
                _public_input(relative, path.read_bytes(), record)
            elif source.name == ".admin-secret" or source.suffix == ".cfg":
                raise ValueError("Private source in canonical inventory")
            origins.add(origin)
            identities.add(identity)
            artifacts.add(artifact)
            retained[origin] = path.read_bytes()
        actual = {p.relative_to(directory).as_posix() for p in (directory / CONTENT).rglob("*")}
        if actual != artifacts or (directory / CONTENT).is_symlink():
            raise ValueError("Unexpected canonical artifacts")
        # Every frozen input must be covered by a retained origin or an exact seal
        # member. Live filesystem disappearance is never an excuse to omit one.
        for origin, expected in frozen.items():
            if origin in retained:
                continue
            path = Path(origin)
            if not path.is_relative_to(directory) or path.is_symlink() or sha256(path) != expected:
                raise ValueError("Incomplete durable canonical input coverage")
        candidate_bytes = retained[str(Path(record["candidate_path"]) / "CANDIDATE.json")]
        if hashlib.sha256(candidate_bytes).hexdigest() != record["candidate_sha256"]:
            raise ValueError("Reviewed candidate provenance mismatch")
        candidate_record = json.loads(candidate_bytes)
        candidate_files = {
            str(Path(record["candidate_path"]) / relative): expected
            for relative, expected in candidate_record["files"].items()
        }
        if any(frozen.get(origin) != expected for origin, expected in candidate_files.items()):
            raise ValueError("Reviewed candidate file provenance mismatch")
        original = dict(candidate_record["source_integrity"])
        original[str(Path(record["candidate_path"]) / "CANDIDATE.json")] = record[
            "candidate_sha256"
        ]
        if {e["origin"]: e["sha256"] for e in index["entries"]} != original:
            raise ValueError("Canonical inventory omits original reviewed source")
        for field in (
            "historical_base",
            "argv",
            "environment",
            "executable_digest",
            "graphics_digest",
            "bridge_digest",
            "source_digest",
            "configuration_digest",
            "request_sha256",
            "source",
            "public_key",
            "endpoints",
            "region",
            "expected_tiles",
            "cursor",
            "environment_allowlist",
        ):
            if candidate_record[field] != record[field]:
                raise ValueError("Seal and reviewed source provenance disagree")
        materializations = json.loads((directory / "runtime-materializations.json").read_bytes())
        original_materializations = json.loads(
            retained[str(Path(record["candidate_path"]) / "runtime-materializations.json")]
        )
        if materializations != original_materializations:
            raise ValueError("Runtime materialization provenance mismatch")
        for item in materializations["entries"]:
            if frozen.get(item["canonical_source"]) != item["canonical_sha256"]:
                raise ValueError("Runtime materialization source not retained")
            if (
                item["derivation"] in ("byte-copy", "generated-template-copy")
                and item["sha256"] != item["canonical_sha256"]
            ):
                raise ValueError("Runtime copy provenance mismatch")
        from .terrain_preparation import digest, package_digest

        base = Path(record["candidate_path"])
        if (
            json.loads(retained[str(base / "source.json")]) != record["source"]
            or digest(record["source"]) != record["source_digest"]
            or package_digest(
                {n: retained[str(base / "bridge" / n)] for n in ("info.nut", "main.nut")}
            )
            != record["bridge_digest"]
            or hashlib.sha256(retained[str(base / "request.json")]).hexdigest()
            != record["request_sha256"]
            or hashlib.sha256(
                retained[str(base / "materialization-inputs/openttd.cfg")]
            ).hexdigest()
            != record["configuration_digest"]
        ):
            raise ValueError("Canonical semantic source provenance mismatch")
        verify_retained_ownership(directory, record, frozen, candidate_record, materializations)
        from .historical_protection import explicit_protection_base, validate_protection

        history_path = directory / "historical-integrity.json"
        if sha256(history_path) != record["historical_integrity_sha256"]:
            raise ValueError("Historical protection differs from immutable seal")
        history = json.loads(history_path.read_bytes())
        base = explicit_protection_base(history, Path(record["historical_base"]))
        validate_protection(base, history)
        return retained
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("Required durable canonical provenance unavailable") from error


def verify_retained_ownership(directory, record, frozen, candidate, materializations):
    """Validate the authoritative graph without requiring disposable file content."""
    from types import SimpleNamespace

    from app.simulation.openttd.runtime.ownership import OwnershipGraph, PathClass

    from .ownership import validate_ownership

    value = json.loads((directory / "path-ownership.json").read_bytes())
    if (
        not isinstance(value, dict)
        or set(value) != {"policy", "cleanup_roots", "entries"}
        or not isinstance(value["cleanup_roots"], list)
        or not isinstance(value["entries"], list)
        or any(
            not isinstance(e, dict)
            or set(e) != {"path", "kind"}
            or not isinstance(e["path"], str)
            or not Path(e["path"]).is_absolute()
            for e in value["entries"]
        )
    ):
        raise ValueError("Ownership schema mismatch")
    graph = OwnershipGraph.from_public(value)
    expected = set(frozen) | {
        candidate["key_path"],
        record["attempt_directory"],
        str(directory / "source-freeze.json"),
        str(directory / "artifact-manifest.sha256"),
        *candidate["capture_outputs"],
    }
    expected.update(e["path"] for e in materializations["entries"])
    if {str(e.path) for e in graph.entries} != expected:
        raise ValueError("Ownership path inventory mismatch")
    kinds = {str(e.path): e.kind for e in graph.entries}
    required_kinds = {p: PathClass.IMMUTABLE_SOURCE for p in frozen}
    required_kinds.update(
        {
            str(directory / "source-freeze.json"): PathClass.IMMUTABLE_SOURCE,
            str(directory / "artifact-manifest.sha256"): PathClass.IMMUTABLE_SOURCE,
            candidate["key_path"]: PathClass.RUNTIME_CREDENTIAL,
            record["attempt_directory"]: PathClass.GENERATED_EVIDENCE,
        }
    )
    required_kinds.update({p: PathClass.RUNTIME_EPHEMERAL for p in candidate["capture_outputs"]})
    required_kinds.update(
        {e["path"]: PathClass.RUNTIME_EPHEMERAL for e in materializations["entries"]}
    )
    if kinds != required_kinds:
        raise ValueError("Ownership input/output classification mismatch")
    for item in materializations["entries"]:
        derivation = item["derivation"]
        classification = (
            "GENERATED_RUNTIME" if derivation == "generated-template-copy" else "RUNTIME_COPY"
        )
        if item["classification"] != classification or not (
            derivation in ("byte-copy", "generated-template-copy")
            or derivation.startswith("archive-member:opengfx-8.0/")
        ):
            raise ValueError("Unsupported runtime materialization ownership")
    prepared = SimpleNamespace(
        directory=directory,
        key_path=Path(candidate["key_path"]),
        spec=SimpleNamespace(workspace=SimpleNamespace(root=Path(candidate["workspace"]))),
    )
    validate_ownership(prepared, frozen, materializations=False)
