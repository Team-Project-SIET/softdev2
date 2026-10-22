"""Offline byte-identical prepared-save clones; never grant native authority."""

import hashlib
import json
import zipfile
from pathlib import Path

from app.experiments.freight_evaluation import evaluate_freight
from app.simulation.openttd.prepared_source_correspondence import ControlledSourceLinks

SOURCE_FILES = (
    "before.sav",
    "qualified.sav",
    "prepared-source-links.json",
    "world-planning-observation.json",
    "native-save-correspondence.json",
    "runtime-identity.json",
    "graphics-identity.json",
    "planning-policy.json",
    "PRELAUNCH.json",
    "PRELAUNCH.sha256",
    "frozen-source.zip",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_manifest(source: Path) -> tuple[dict, dict[str, bytes]]:
    """Copy the qualified pre-execution state, with independent provenance readback."""
    source = source.resolve(strict=True)
    if any((source / name).is_symlink() for name in SOURCE_FILES):
        raise ValueError("source files must not be symlinks")
    hashes = {name: digest(source / name) for name in SOURCE_FILES}
    report = evaluate_freight(source)
    if report.status != "verified-delivery" or report.network_report is None:
        raise ValueError("cloning requires independently verified native network source")
    if hashes != {name: digest(source / name) for name in SOURCE_FILES}:
        raise ValueError("source changed during independent verification")
    links = ControlledSourceLinks.model_validate_json(
        (source / "prepared-source-links.json").read_bytes()
    )
    world = json.loads((source / "world-planning-observation.json").read_bytes())
    observation_digest = hashlib.sha256(
        json.dumps(world, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        observation_digest != links.world_observation_digest
        or world["structural_world_digest"] != links.final_structural_digest
        or world["production_digest"] != links.qualified_production_digest
    ):
        raise ValueError("prepared observation identity mismatch")
    if (
        links.original_save_digest != hashes["before.sav"]
        or links.post_qualification_save_digest != hashes["qualified.sav"]
        or links.evidence_kind != "owned-native-save-snapshots"
    ):
        raise ValueError("prepared native save identity mismatch")
    seal = json.loads((source / "PRELAUNCH.json").read_bytes())
    if hashes["PRELAUNCH.json"] != (source / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("source prelaunch seal mismatch")
    with zipfile.ZipFile(source / "frozen-source.zip") as archive:
        names = sorted(
            name.removeprefix("staged/")
            for name in archive.namelist()
            if name.startswith("staged/")
            and (name.endswith(".nut") or name == "staged/openttd.cfg")
        )
        if (
            len(names) != len(set(names))
            or any(Path(name).name != name or "\\" in name for name in names)
            or not {"openttd.cfg", "info.nut", "main.nut"}.issubset(names)
        ):
            raise ValueError("frozen staged files must be unique basenames with config/main/info")
        staged = {name: archive.read("staged/" + name) for name in names}
    bridge_digest = hashlib.sha256(
        b"".join(name.encode() + b"\0" + staged[name] for name in names if name.endswith(".nut"))
    ).hexdigest()
    if (
        hashlib.sha256(staged["openttd.cfg"]).hexdigest() != links.configuration_digest
        or bridge_digest != links.bridge_digest
    ):
        raise ValueError("frozen settings/bridge source identity mismatch")
    runtime = json.loads((source / "runtime-identity.json").read_bytes())
    if (
        runtime["welcome"]["seed"] != seal["world"]["seed"]
        or seal["binary_sha256"] != links.runtime_digest
    ):
        raise ValueError("source seed/runtime identity mismatch")
    clone_files = {
        "source.sav": (source / "qualified.sav").read_bytes(),
        "settings.cfg": staged["openttd.cfg"],
        **{f"bridge/{name}": data for name, data in staged.items() if name.endswith(".nut")},
    }
    manifest = dict(
        schema_version=1,
        classification="MATCHED_PREPARED_SOURCE_BYTES",
        source_directory=str(source),
        source_file="qualified.sav",
        source_sha256=hashes["qualified.sav"],
        original_save_sha256=hashes["before.sav"],
        source_files=hashes,
        seed=runtime["welcome"]["seed"],
        runtime_sha256=links.runtime_digest,
        configuration_sha256=links.configuration_digest,
        bridge_sha256=links.bridge_digest,
        content_identity=json.loads((source / "graphics-identity.json").read_bytes()),
        observation_policy=json.loads((source / "planning-policy.json").read_bytes()),
        world_observation_digest=links.world_observation_digest,
        clone_files={name: hashlib.sha256(data).hexdigest() for name, data in clone_files.items()},
        native_launches=0,
        admin_connections=0,
        runtime_correspondence="NOT_RELOADED; fresh native readback required",
    )
    if hashes != {name: digest(source / name) for name in SOURCE_FILES}:
        raise ValueError("source changed during clone preparation")
    return manifest, clone_files


def prepare_paired_source(source: Path, output: Path) -> dict:
    if (
        source.is_symlink()
        or output.is_symlink()
        or any(p.is_symlink() for p in (*source.parents, *output.parents))
    ):
        raise ValueError("source and output must not contain symlink ancestors")
    source, output = source.resolve(strict=True), output.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("clone output must be fresh and outside retained source")
    manifest, clone_files = _source_manifest(source)
    output.mkdir(parents=True)
    for variant in ("baseline", "feedback"):
        for name, data in clone_files.items():
            path = output / variant / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    (output / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return verify_paired_source(output)


def verify_paired_source(output: Path) -> dict:
    """Reject clone or historical-source drift without executing a process."""
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("clone output must not contain symlink ancestors")
    manifest_path = output / "source-manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("clone manifest must not be a symlink")
    manifest = json.loads(manifest_path.read_bytes())
    source = Path(manifest["source_directory"])
    if source.is_symlink() or any(p.is_symlink() for p in source.parents):
        raise ValueError("source must not contain symlink ancestors")
    if manifest["source_files"] != {name: digest(source / name) for name in SOURCE_FILES}:
        raise ValueError("historical source changed after cloning")
    expected_manifest, _ = _source_manifest(source)
    if manifest != expected_manifest:
        raise ValueError("clone manifest differs from verified historical source")
    for variant in ("baseline", "feedback"):
        for name, expected in manifest["clone_files"].items():
            path = output / variant / name
            if any(p.is_symlink() for p in (path, *path.parents)) or digest(path) != expected:
                raise ValueError(f"{variant} clone identity mismatch: {name}")
    if any(
        manifest["clone_files"][name] != manifest[key]
        for name, key in (("source.sav", "source_sha256"), ("settings.cfg", "configuration_sha256"))
    ):
        raise ValueError("clone manifest prepared-source identity mismatch")
    return manifest
