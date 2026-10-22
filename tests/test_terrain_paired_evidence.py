"""Controlled package acceptance at writer and full offline verifier interfaces."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_paired_evidence import (
    Descriptor,
    verify_paired_package,
    write_paired_package,
)
from app.simulation.openttd.terrain_sweeps import TerrainSweepContext, TerrainTwoSweep
from tests.test_terrain_sweeps import collect, context


def test_valid_package(tmp_path):
    c = context()
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    collect(pair, c, 2)
    destination = tmp_path / "evidence"
    write_paired_package(pair.finish(), destination)
    pinned = hashlib.sha256((destination / "package.json").read_bytes()).hexdigest()
    accepted = verify_paired_package(destination, expected_descriptor_sha256=pinned)
    assert accepted == pair.finish()
    assert accepted.metadata["pages"] == 4


def test_boolean_version_is_not_integer_one(tmp_path):
    c = context()
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    collect(pair, c, 2)
    destination = tmp_path / "evidence"
    write_paired_package(pair.finish(), destination)
    descriptor = json.loads((destination / "package.json").read_bytes())
    descriptor["version"] = True
    raw = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    (destination / "package.json").write_bytes(raw)
    pinned = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="schema:"):
        verify_paired_package(destination, expected_descriptor_sha256=pinned)


@pytest.fixture
def package(tmp_path):
    c = context()
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    collect(pair, c, 2)
    directory = tmp_path / "evidence"
    write_paired_package(pair.finish(), directory)
    pinned = hashlib.sha256((directory / "package.json").read_bytes()).hexdigest()
    return directory, pinned


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def refreshed(directory):
    """Independent test authority pins intentionally invalid semantic fixtures."""
    descriptor = json.loads((directory / "package.json").read_bytes())
    for a in descriptor["artifacts"]:
        p = directory / a["path"]
        if p.is_file():
            raw = p.read_bytes()
            a.update(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (directory / "package.json").write_bytes(encode(descriptor))
    rebuild_manifest(directory)
    return hashlib.sha256((directory / "package.json").read_bytes()).hexdigest()


def rebuild_manifest(directory):
    raw = "".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(directory).as_posix()}\n"
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "artifact-manifest.sha256"
    )
    (directory / "artifact-manifest.sha256").write_text(raw)


def mutate(directory, path, action):
    p = directory / path
    value = json.loads(p.read_bytes())
    action(value)
    p.write_bytes(encode(value))


@pytest.mark.parametrize("n", [1, 5, 6, 255, 256])
def test_deterministic_complete_sizes(tmp_path, n):
    region = (
        Region(x=1, y=1, width=16, height=16) if n == 256 else Region(x=1, y=1, width=n, height=1)
    )
    c = TerrainSweepContext("sizes", "a" * 64, 512, 512, region)
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    collect(pair, c, 2)
    a, b = tmp_path / "a", tmp_path / "b"
    write_paired_package(pair.finish(), a)
    write_paired_package(pair.finish(), b)
    assert (a / "package.json").read_bytes() == (b / "package.json").read_bytes()
    digest = hashlib.sha256((a / "package.json").read_bytes()).hexdigest()
    result = verify_paired_package(a, expected_descriptor_sha256=digest)
    assert len(result.rows) == n
    assert len(list(a.rglob("*.json"))) == 2 + 6 * ((n + 4) // 5)


@pytest.mark.parametrize("digest", [None, "", "x" * 64, "0" * 64])
def test_external_authority_is_mandatory(package, digest):
    directory, _ = package
    with pytest.raises(ValueError, match="commitment:"):
        verify_paired_package(directory, expected_descriptor_sha256=digest)


def test_omitted_authority_has_no_package_fallback(package):
    invoke = getattr(verify_paired_package, "__call__")
    with pytest.raises(TypeError, match="expected_descriptor_sha256"):
        invoke(package[0])


def test_descriptor_external_schema_and_digest_round_trip(package):
    directory, pinned = package
    raw = (directory / "package.json").read_bytes()
    value = json.loads(raw)
    assert set(value) == {
        "schema",
        "version",
        "mode",
        "status",
        "context",
        "budgets",
        "sweeps",
        "artifacts",
        "failure",
    }
    assert value["schema"] == "terrain-paired-evidence-v1"
    assert "schema_id" not in value
    descriptor = Descriptor.model_validate_json(raw)
    assert descriptor.schema_id == "terrain-paired-evidence-v1"
    assert encode(descriptor.model_dump(mode="json", by_alias=True)) == raw
    # Captured from this deterministic fixture before the Python attribute rename.
    assert pinned == "dbc768e3d512b3329d5b78354aa5c676a1543ed693357a7b41fe0c515a1e57c7"
    assert verify_paired_package(directory, expected_descriptor_sha256=pinned).metadata["complete"]
    value["schema_id"] = value.pop("schema")
    with pytest.raises(ValueError):
        Descriptor.model_validate_json(encode(value))


@pytest.mark.parametrize(
    "problem", ["extra", "nested", "empty-dir", "missing", "symlink", "directory", "hardlink"]
)
def test_exact_inventory(package, tmp_path, problem):
    directory, pinned = package
    p = directory / "pages/s1/p001/response.json"
    if problem == "extra":
        (directory / "unknown.txt").write_text("not authorized")
    elif problem == "nested":
        (directory / "pages/s1/p001/unknown.txt").write_text("not authorized")
    elif problem == "empty-dir":
        (directory / "unknown").mkdir()
    elif problem == "missing":
        p.unlink()
    elif problem == "directory":
        p.unlink()
        p.mkdir()
    else:
        source = tmp_path / "alias.json"
        source.write_bytes(p.read_bytes())
        p.unlink()
        if problem == "symlink":
            p.symlink_to(source)
        else:
            os.link(source, p)
    with pytest.raises(ValueError, match="inventory:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "path", ["pages/s1/p001/request.json", "pages/s2/p001/response.json", "summary.json"]
)
def test_mutable_manifest_cannot_authorize_bytes(package, path):
    directory, pinned = package
    p = directory / path
    p.write_bytes(p.read_bytes() + b" ")
    rebuild_manifest(directory)
    with pytest.raises(ValueError, match="bytes:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_descriptor_and_manifest_replacement_cannot_replace_authority(package):
    directory, pinned = package
    mutate(directory, "package.json", lambda d: d["context"].update(world_fingerprint="b" * 64))
    refreshed(directory)
    with pytest.raises(ValueError, match="commitment:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "change", ["version", "mode", "status", "unknown", "missing", "duplicate-json", "noncanonical"]
)
def test_schema_dispatch(package, change):
    directory, _ = package
    p = directory / "package.json"
    d = json.loads(p.read_bytes())
    if change == "version":
        d["version"] = 2
    elif change == "mode":
        d["mode"] = "REAL"
    elif change == "status":
        d["status"] = "INCOMPLETE"
    elif change == "unknown":
        d["equal"] = True
    elif change == "missing":
        del d["context"]
    raw = encode(d)
    if change == "duplicate-json":
        raw = raw[:-1] + b',"version":1}'
    elif change == "noncanonical":
        raw += b"\n"
    p.write_bytes(raw)
    pinned = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="schema:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-page",
        "missing-page",
        "request-id",
        "tile-index",
        "traversal",
        "absolute",
        "duplicate-artifact",
        "extra-artifact",
    ],
)
def test_authorized_descriptor_still_requires_exact_plan(package, change):
    directory, _ = package

    def alter(d):
        pages = d["sweeps"][0]["pages"]
        if change == "duplicate-page":
            pages[1] = pages[0]
        elif change == "missing-page":
            pages.pop()
        elif change == "request-id":
            pages[0]["request_id"] = "other"
        elif change == "tile-index":
            pages[0]["tile_ids"][0] = 99
        elif change == "traversal":
            d["artifacts"][0]["path"] = "../outside"
        elif change == "absolute":
            d["artifacts"][0]["path"] = "/tmp/outside"
        elif change == "duplicate-artifact":
            d["artifacts"][1] = d["artifacts"][0]
        else:
            d["artifacts"].append(dict(path="extra", byte_length=0, sha256="a" * 64))

    mutate(directory, "package.json", alter)
    # Do not resolve malicious artifact paths even in the disposable fixture helper.
    pinned = hashlib.sha256((directory / "package.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="inventory:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "change",
    [
        "receipt",
        "operation",
        "retry",
        "boolean-counter",
        "sequence",
        "missing-field",
        "unknown-field",
    ],
)
def test_exchange_semantics(package, change):
    directory, _ = package

    def alter(d):
        if change == "receipt":
            d["receipt"]["response_payload_sha256"] = "b" * 64
        elif change == "operation":
            d["protocol_operations"] = 9
        elif change == "retry":
            d["retries"] = 1
        elif change == "boolean-counter":
            d["requests_sent"] = True
        elif change == "sequence":
            d["ordered_sequence"] = ["WRONG"]
        elif change == "missing-field":
            del d["receipt"]
        else:
            d["extra"] = True

    mutate(directory, "pages/s2/p001/exchange.json", alter)
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="exchange:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize("change", ["fingerprint", "region", "geometry"])
def test_page_context_cannot_change(package, change):
    directory, _ = package

    def alter(d):
        c = d["observed_context"]
        if change == "fingerprint":
            c["world_fingerprint"] = "b" * 64
        elif change == "region":
            c["region"]["x"] = 2
        else:
            c["map_width"] = 128

    mutate(directory, "pages/s2/p001/exchange.json", alter)
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="replay: Page admission"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_valid_schema_terrain_drift_reaches_equality(package):
    directory, _ = package
    response = "pages/s2/p001/response.json"
    mutate(directory, response, lambda d: d["tiles"][0].__setitem__(1, 1))
    digest = hashlib.sha256((directory / response).read_bytes()).hexdigest()
    mutate(
        directory,
        "pages/s2/p001/exchange.json",
        lambda d: d["receipt"].update(response_payload_sha256=digest),
    )
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="replay: Sweep completion") as error:
        verify_paired_package(directory, expected_descriptor_sha256=pinned)
    assert "Terrain sweep drift" in str(error.value.__cause__)


@pytest.mark.parametrize("change", ["request", "response", "duplicate-tile", "date"])
def test_protocol_mutations_with_refreshed_receipts(package, change):
    directory, _ = package
    request, response = "pages/s2/p001/request.json", "pages/s2/p001/response.json"
    if change == "request":
        mutate(directory, request, lambda d: d.update(cursor=5))
    elif change == "response":
        mutate(directory, response, lambda d: d.update(request_id="wrong"))
    elif change == "date":
        mutate(directory, response, lambda d: d.update(date_before=3, date_after=2))
    else:
        mutate(directory, response, lambda d: d["tiles"][1].__setitem__(0, 65))

    def receipts(d):
        d["receipt"].update(
            request_payload_sha256=hashlib.sha256((directory / request).read_bytes()).hexdigest(),
            response_payload_sha256=hashlib.sha256((directory / response).read_bytes()).hexdigest(),
        )

    mutate(directory, "pages/s2/p001/exchange.json", receipts)
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="exchange:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize("change", ["summary-bytes", "summary-equality", "dataset-identity"])
def test_derived_summary_is_not_authority(package, change):
    directory, _ = package

    def alter(d):
        if change == "summary-bytes":
            d["pair_metadata"]["request_bytes"] += 1
        elif change == "summary-equality":
            d["pair_metadata"]["complete"] = False
        else:
            d["dataset_identity"] = "b" * 64

    mutate(directory, "summary.json", alter)
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="summary: Replayed"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "scope,field,limit",
    [
        ("per_sweep", "page_request_bytes", 1),
        ("per_sweep", "page_response_bytes", 1),
        ("per_sweep", "max_operations", 4),
        ("combined", "max_request_bytes", 350),
        ("combined", "max_response_bytes", 800),
        ("combined", "max_operations", 12),
    ],
)
def test_selected_budgets_are_enforced(package, scope, field, limit):
    directory, _ = package
    mutate(directory, "package.json", lambda d: d["budgets"][scope].update(**{field: limit}))
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="replay: Page admission"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize("value", [True, 833, 0])
def test_invalid_combined_budget(package, value):
    directory, _ = package
    mutate(
        directory, "package.json", lambda d: d["budgets"]["combined"].update(max_operations=value)
    )
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="schema:|replay: Invalid context or budgets"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_cross_sweep_substitution(package):
    directory, _ = package
    for name in ("request.json", "response.json", "exchange.json"):
        (directory / "pages/s2/p001" / name).write_bytes(
            (directory / "pages/s1/p001" / name).read_bytes()
        )
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="replay: Page admission"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_cleanup_and_fresh_process(package, tmp_path):
    directory, pinned = package
    moved = tmp_path / "retained"
    shutil.copytree(directory, moved)
    shutil.rmtree(directory)
    assert verify_paired_package(moved, expected_descriptor_sha256=pinned).metadata["complete"]
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(repo))
    code = (
        "from pathlib import Path; import sys; "
        "from app.simulation.openttd.terrain_paired_evidence import verify_paired_package; "
        "r=verify_paired_package(Path(sys.argv[1]), expected_descriptor_sha256=sys.argv[2]); "
        "assert len(r.rows)==6; print('CONTROLLED replay accepted')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(moved), pinned],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "CONTROLLED replay accepted"


def test_duplicate_response_json_key_rejects_at_exchange(package):
    directory, _ = package
    path = directory / "pages/s2/p001/response.json"
    raw = path.read_bytes()[:-1] + b',"date_before":0}'
    path.write_bytes(raw)
    mutate(
        directory,
        "pages/s2/p001/exchange.json",
        lambda d: d["receipt"].update(response_payload_sha256=hashlib.sha256(raw).hexdigest()),
    )
    pinned = refreshed(directory)
    with pytest.raises(ValueError, match="exchange:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_missing_package_root_rejects_with_diagnosable_inventory_error(tmp_path):
    with pytest.raises(ValueError, match="inventory:") as error:
        verify_paired_package(tmp_path / "absent", expected_descriptor_sha256="a" * 64)
    assert isinstance(error.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("kind", ["root", "intermediate", "traversal"])
def test_root_and_intermediate_aliases_reject(package, tmp_path, kind):
    directory, pinned = package
    if kind == "root":
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        directory = alias
    elif kind == "intermediate":
        original = directory / "pages/s1"
        outside = tmp_path / "outside"
        original.rename(outside)
        original.symlink_to(outside, target_is_directory=True)
    else:
        directory = directory / ".." / directory.name
    with pytest.raises(ValueError, match="inventory:"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


@pytest.mark.parametrize(
    "path,limit",
    [
        ("package.json", 131072),
        ("summary.json", 65536),
        ("pages/s1/p001/exchange.json", 4096),
        ("pages/s1/p001/request.json", 159),
        ("pages/s1/p001/response.json", 508),
    ],
)
def test_bounded_artifact_reads(package, path, limit):
    directory, pinned = package
    (directory / path).write_bytes(b" " * (limit + 1))
    with pytest.raises(ValueError, match="inventory:.*size"):
        verify_paired_package(directory, expected_descriptor_sha256=pinned)


def test_empty_owned_output_and_incomplete_writer_rejection(package, tmp_path):
    from dataclasses import replace

    directory, pinned = package
    accepted = verify_paired_package(directory, expected_descriptor_sha256=pinned)
    with pytest.raises(ValueError, match="Output directory must be empty"):
        write_paired_package(accepted, directory)
    incomplete = replace(
        accepted,
        sweeps=(
            accepted.sweeps[0],
            replace(accepted.sweeps[1], exchanges=accepted.sweeps[1].exchanges[:-1]),
        ),
    )
    destination = tmp_path / "incomplete"
    with pytest.raises(ValueError):
        write_paired_package(incomplete, destination)
    assert not destination.exists()
