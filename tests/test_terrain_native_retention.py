"""Native outer retention keeps checked bytes after disposable candidate deletion."""

import hashlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof.harness import write_json
from app.simulation.openttd.proof.ownership import build_ownership
from app.simulation.openttd.proof.terrain_native_retention import (
    retain_native_inputs,
    verify_native_inputs,
)
from tests.test_terrain_single_page_preparation import candidate as candidate  # noqa: F401


def test_native_retention_missing_required_source_rejects():
    with pytest.raises(ValueError, match="provenance"):
        verify_native_inputs({}, {"source": {}}, {})


def native_provenance_fixture(candidate, stage, destination):
    stage.mkdir()
    index = retain_native_inputs(candidate, stage)
    frozen = dict(candidate.record["source_integrity"])
    frozen[str(candidate.directory / "CANDIDATE.json")] = hashlib.sha256(
        (candidate.directory / "CANDIDATE.json").read_bytes()
    ).hexdigest()
    for name in (
        "canonical-inputs.json",
        "runtime-materializations.json",
        "historical-integrity.json",
    ):
        if name != "canonical-inputs.json":
            (stage / name).write_bytes((candidate.directory / name).read_bytes())
        frozen[str(stage / name)] = hashlib.sha256((stage / name).read_bytes()).hexdigest()
    graph = build_ownership(
        stage,
        Path(candidate.record["workspace"]),
        Path(candidate.record["key_path"]),
        destination,
        frozen,
        {},
        capture_outputs=tuple(Path(p) for p in candidate.record["capture_outputs"]),
    )
    write_json(stage / "path-ownership.json", graph.public())
    frozen[str(stage / "path-ownership.json")] = hashlib.sha256(
        (stage / "path-ownership.json").read_bytes()
    ).hexdigest()
    write_json(stage / "source-freeze.json", frozen)
    content = {
        "seal/" + p.relative_to(stage).as_posix(): p.read_bytes()
        for p in stage.rglob("*")
        if p.is_file()
    }

    def digest(name):
        return hashlib.sha256(content["seal/" + name]).hexdigest()

    def source_input(identity):
        entry = next(e for e in index["entries"] if e["identity"] == identity)
        return {
            "identity": identity,
            "origin": entry["origin"],
            "sha256": entry["sha256"],
            "byte_length": len(content["seal/" + entry["artifact"]]),
        }

    runtime = {
        "argv": candidate.record["argv"],
        "environment": candidate.record["environment"],
        "executable": source_input("source:" + candidate.record["executable"]),
        "graphics_archive": source_input("source:" + candidate.record["graphics_archive"]),
        "graphics_files": [],
        "bridge_inputs": [
            source_input("candidate:bridge/main.nut"),
            source_input("candidate:bridge/info.nut"),
        ],
        "public_config": [source_input("candidate:materialization-inputs/openttd.cfg")],
    }
    prelaunch = {
        "attempt": {"seal_destination": str(stage), "destination": str(destination)},
        "runtime": runtime,
        "source": {
            "candidate": source_input("candidate:CANDIDATE.json"),
            **{
                field: digest(name)
                for field, name in [
                    ("source_freeze_sha256", "source-freeze.json"),
                    ("canonical_inputs_sha256", "canonical-inputs.json"),
                    ("ownership_sha256", "path-ownership.json"),
                    ("materializations_sha256", "runtime-materializations.json"),
                    ("historical_integrity_sha256", "historical-integrity.json"),
                ]
            },
        },
        "external_authorities": [
            {
                "identity": "controlled-history",
                "provenance_base": candidate.record["historical_base"],
                "inventory_sha256": digest("historical-integrity.json"),
            }
        ],
    }
    return content, prelaunch, {"controlled-history": Path(candidate.record["historical_base"])}


def test_native_retention_survives_disposable_original_cleanup(candidate, tmp_path):
    import shutil

    content, prelaunch, authorities = native_provenance_fixture(
        candidate, tmp_path / "native-seal", tmp_path / "attempt"
    )
    before = verify_native_inputs(content, prelaunch, authorities)
    shutil.rmtree(candidate.directory)
    assert verify_native_inputs(content, prelaunch, authorities) == before


@pytest.mark.parametrize("mutation", ["content", "extra", "index", "history", "ownership"])
def test_native_retention_rejects_mutation(candidate, tmp_path, mutation):
    content, prelaunch, authorities = native_provenance_fixture(
        candidate, tmp_path / "native-seal", tmp_path / "attempt"
    )
    if mutation == "content":
        name = next(n for n in content if n.startswith("seal/canonical/"))
        content[name] += b"changed"
    elif mutation == "extra":
        content["seal/canonical/" + "0" * 64] = b"unknown"
    elif mutation == "history":
        authorities["controlled-history"] = tmp_path
    else:
        name = "seal/canonical-inputs.json" if mutation == "index" else "seal/path-ownership.json"
        content[name] = b"{}"
    with pytest.raises(ValueError):
        verify_native_inputs(content, prelaunch, authorities)


def test_native_ownership_semantics_survive_recomputed_metadata(candidate, tmp_path):
    content, prelaunch, authorities = native_provenance_fixture(
        candidate, tmp_path / "native-seal", tmp_path / "attempt"
    )
    name = "seal/path-ownership.json"
    value = json.loads(content[name])
    row = next(e for e in value["entries"] if e["path"] == candidate.record["key_path"])
    row["kind"] = "RUNTIME_EPHEMERAL"
    content[name] = json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
    digest = hashlib.sha256(content[name]).hexdigest()
    prelaunch["source"]["ownership_sha256"] = digest
    frozen = json.loads(content["seal/source-freeze.json"])
    frozen[str(tmp_path / "native-seal/path-ownership.json")] = digest
    content["seal/source-freeze.json"] = (
        json.dumps(frozen, sort_keys=True, indent=2).encode() + b"\n"
    )
    prelaunch["source"]["source_freeze_sha256"] = hashlib.sha256(
        content["seal/source-freeze.json"]
    ).hexdigest()
    with pytest.raises(ValueError, match="ownership path classification"):
        verify_native_inputs(content, prelaunch, authorities)
