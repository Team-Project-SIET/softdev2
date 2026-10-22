"""Production offline evidence boundaries, with controlled files and fake lifecycle only."""

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.simulation.openttd.proof import terrain_preparation as prep
from app.simulation.openttd.proof.terrain_attempt import (
    execute_single_page,
    verify_retained_attempt,
)
from tests.test_terrain_model_a import LocalFakeBackend, authorize, destination
from tests.test_terrain_model_a import local_seal as local_seal  # noqa: F401
from tests.test_terrain_single_page_preparation import candidate as candidate  # noqa: F401
from tests.test_terrain_single_page_preparation import evidence, exchange


def test_offline_after_candidate_and_runtime_cleanup(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    target = destination(local_seal)
    result = asyncio.run(
        execute_single_page(
            local_seal, LocalFakeBackend(), target, authorization=authorize(local_seal)
        )
    )
    assert result["status"] == "CONTROLLED_PASS"
    assert not local_seal.spec.workspace.root.exists()
    assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"
    local_seal.dispose()
    candidate = Path(
        json.loads((local_seal.directory / "PRELAUNCH.json").read_text())["candidate_path"]
    )
    shutil.rmtree(candidate)
    assert not local_seal.key_path.exists()
    assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"


def test_log_append_preserves_snapshot():
    from app.simulation.openttd.proof.terrain_logs import log_record, verify_log_record

    raw = evidence(exchange())
    final = raw + b"native shutdown\n"
    record = log_record(raw, final, prep.REQUEST.request_id)
    assert verify_log_record(record, final, prep.REQUEST.request_id) == raw
    assert record["snapshot"]["end_offset"] == len(raw)
    assert record["final"]["sha256"] == hashlib.sha256(final).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        "mutate",
        "truncate",
        "start",
        "end",
        "length",
        "full_hash",
        "full_length",
        "artifact",
        "snapshot_hash",
        "marker",
        "request",
        "missing",
        "duplicate_marker",
    ],
)
def test_log_scope_rejects_tampering(change):
    from app.simulation.openttd.proof.terrain_logs import log_record, verify_log_record

    raw = evidence(exchange())
    final = raw + b"native shutdown\n"
    record = log_record(raw, final, prep.REQUEST.request_id)
    if change == "mutate":
        final = b"X" + final[1:]
        record["final"]["sha256"] = hashlib.sha256(final).hexdigest()
    elif change == "truncate":
        final = final[: len(raw) - 1]
        record["final"].update(byte_length=len(final), sha256=hashlib.sha256(final).hexdigest())
    elif change == "start":
        record["snapshot"]["start_offset"] = 1
    elif change == "end":
        record["snapshot"]["end_offset"] -= 1
    elif change == "length":
        record["snapshot"]["byte_length"] += 1
    elif change == "full_hash":
        record["final"]["sha256"] = "0" * 64
    elif change == "full_length":
        record["final"]["byte_length"] += 1
    elif change == "artifact":
        record["final"]["artifact"] = "stdout.log"
    elif change == "snapshot_hash":
        record["snapshot"]["sha256"] = record["final"]["sha256"]
    elif change == "marker":
        record["snapshot"]["lifecycle_marker"] = "BRIDGE_STARTED"
    elif change == "request":
        record["request_id"] = "other"
    elif change == "missing":
        del record["snapshot"]["end_offset"]
    elif change == "duplicate_marker":
        final += raw.splitlines(keepends=True)[-1]
        record["final"].update(byte_length=len(final), sha256=hashlib.sha256(final).hexdigest())
    with pytest.raises(ValueError):
        verify_log_record(record, final, prep.REQUEST.request_id)


@pytest.fixture
def completed(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    target = destination(local_seal)
    result = asyncio.run(
        execute_single_page(
            local_seal, LocalFakeBackend(), target, authorization=authorize(local_seal)
        )
    )
    assert result["status"] == "CONTROLLED_PASS"
    prelaunch = json.loads((local_seal.directory / "PRELAUNCH.json").read_text())
    shutil.rmtree(Path(prelaunch["candidate_path"]))
    return local_seal, target


def remanifest(directory):
    from app.simulation.openttd.proof.harness import manifest

    path = directory / "artifact-manifest.sha256"
    path.chmod(0o600)
    path.write_text(manifest(directory))


@pytest.mark.parametrize("change", ["missing", "altered", "unexpected"])
def test_durable_input_damage_rejects(completed, change):
    p, target = completed
    blob = next((p.directory / "canonical").iterdir())
    if change == "missing":
        blob.parent.chmod(0o700)
        blob.unlink()
    elif change == "altered":
        blob.chmod(0o600)
        blob.write_bytes(b"replacement")
    else:
        p.directory.chmod(0o700)
        (p.directory / "unexpected.txt").write_bytes(b"foreign")
    remanifest(p.directory)
    with pytest.raises(ValueError, match="canonical|artifacts"):
        verify_retained_attempt(target)


def test_wrong_original_source_provenance_rejects(completed):
    from app.simulation.openttd.proof.terrain_retention import verify_inputs

    p, _ = completed
    index_path = p.directory / "canonical-inputs.json"
    index = json.loads(index_path.read_text())
    index["entries"][0]["origin"] = "/tmp/unreviewed-input"
    index_path.chmod(0o600)
    index_path.write_text(json.dumps(index))
    record = json.loads((p.directory / "PRELAUNCH.json").read_text())
    record["canonical_inputs_sha256"] = prep.sha256(index_path)
    frozen = json.loads((p.directory / "source-freeze.json").read_text())
    with pytest.raises(ValueError, match="source digest"):
        verify_inputs(p.directory, record, frozen)


def fixture_disposal_sets(p):
    """Candidate cache disposal is allowed only after durable controlled acceptance."""
    record = json.loads((p.directory / "PRELAUNCH.json").read_text())
    index = json.loads((p.directory / "canonical-inputs.json").read_text())
    history = json.loads((p.directory / "historical-integrity.json").read_text())
    disposable = {
        Path(e["origin"]).resolve()
        for e in index["entries"]
        if e["identity"].startswith("candidate:")
    }
    persistent = {
        Path(e["origin"]).resolve() for e in index["entries"] if e["identity"].startswith("source:")
    }
    protected = {
        (Path(record["historical_base"]) / e["path"]).resolve() for e in history["entries"]
    }
    retained = {f.resolve() for f in p.directory.rglob("*") if f.is_file()}
    assert not disposable & (persistent | protected | retained)
    return disposable, protected, persistent, retained


def delete_fixture_originals(p, paths):
    disposable, protected, persistent, retained = fixture_disposal_sets(p)
    approved = []
    for path in paths:
        resolved = path.resolve()
        if (
            not path.is_absolute()
            or path != resolved
            or path.is_symlink()
            or resolved not in disposable
            or resolved in protected | persistent | retained
        ):
            raise ValueError("Fixture deletion ownership overlap or alias")
        approved.append(path)
    # Check the complete set before any mutation, and validate the production package.
    assert verify_retained_attempt(destination(p))["mode"] == "CONTROLLED"
    for path in approved:
        path.unlink(missing_ok=True)


def test_all_permitted_temporary_originals_can_disappear(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    p = local_seal
    target = destination(p)
    result = asyncio.run(
        execute_single_page(p, LocalFakeBackend(), target, authorization=authorize(p))
    )
    assert result["status"] == "CONTROLLED_PASS"
    disposable, protected, persistent, retained = fixture_disposal_sets(p)
    before = {f: f.read_bytes() for f in protected | persistent | retained}
    assert len(disposable) == 13
    delete_fixture_originals(p, disposable)
    assert all(not f.exists() for f in disposable)
    assert all(f.read_bytes() == raw for f, raw in before.items())
    assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"
    fresh_controlled_verification(target)


def fresh_controlled_verification(target):
    import os
    import sys

    child = os.fork()
    if child == 0:
        os.chdir("/tmp")
        repo = str(Path(__file__).resolve().parents[1])
        env = dict(os.environ, PYTHONPATH=repo, PYTHONDONTWRITEBYTECODE="1")
        code = (
            "from pathlib import Path; "
            "from app.simulation.openttd.proof.terrain_attempt "
            "import verify_retained_attempt; assert verify_retained_attempt(Path("
            + repr(str(target))
            + "))['mode']=='CONTROLLED'"
        )
        os.execve(sys.executable, [sys.executable, "-B", "-c", code], env)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0


def test_private_key_not_retained_and_cleanup_mandatory(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    secret = local_seal.key_path.read_bytes()
    assert all(secret not in p.read_bytes() for p in local_seal.directory.rglob("*") if p.is_file())
    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    target = destination(local_seal)
    result = asyncio.run(
        execute_single_page(
            local_seal, LocalFakeBackend(), target, authorization=authorize(local_seal)
        )
    )
    assert result["status"] == "CONTROLLED_PASS"
    assert not local_seal.key_path.exists()
    assert all(secret not in p.read_bytes() for p in target.rglob("*") if p.is_file())
    local_seal.key_path.parent.mkdir()
    local_seal.key_path.write_bytes(secret)
    with pytest.raises(ValueError, match="cleanup incomplete"):
        verify_retained_attempt(target)


@pytest.mark.parametrize(
    "relative,secret",
    [
        ("materialization-inputs/secrets.cfg", b"admin_password = FORBIDDEN_SECRET\n"),
        ("materialization-inputs/private.cfg", b"private_key = FORBIDDEN_SECRET\n"),
        ("config-template.cfg", b"token = FORBIDDEN_SECRET\n"),
    ],
)
def test_secret_configuration_never_copied(candidate, tmp_path, relative, secret):
    from app.simulation.openttd.proof.terrain_retention import retain_inputs

    path = candidate.directory / relative
    path.write_bytes(secret)
    candidate.record["source_integrity"][str(path)] = prep.sha256(path)
    stage = tmp_path / "controlled-retention"
    stage.mkdir()
    with pytest.raises(ValueError, match="configuration"):
        retain_inputs(candidate, stage)
    assert all(secret not in p.read_bytes() for p in stage.rglob("*") if p.is_file())


def test_missing_scope_cannot_pass(completed):
    _, target = completed
    (target / "execution-log.json").unlink()
    remanifest(target)
    with pytest.raises(ValueError, match="LEGACY_EVIDENCE_LIMITATION"):
        verify_retained_attempt(target)


def test_appended_log_production_verifier(completed):
    from app.simulation.openttd.proof.terrain_logs import log_record

    _, target = completed
    raw = (target / "stderr.log").read_bytes()
    final = raw + b"shutdown after evidence snapshot\n"
    (target / "stderr.log").write_bytes(final)
    (target / "execution-log.json").write_text(
        json.dumps(log_record(raw, final, prep.REQUEST.request_id))
    )
    remanifest(target)
    assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "REAL_PASS"),
        ("mode", "unknown"),
        ("mode", "REAL"),
    ],
)
def test_contradictory_status_and_mode_cannot_bypass_lineage(completed, field, value):
    _, target = completed
    path = target / "result.json"
    result = json.loads(path.read_text())
    result[field] = value
    path.write_text(json.dumps(result))
    remanifest(target)
    with pytest.raises(ValueError, match="Failed attempt"):
        verify_retained_attempt(target)


def test_launch_mode_disagreement_rejected(completed):
    _, target = completed
    path = target / "launch-claim.json"
    claim = json.loads(path.read_text())
    claim["mode"] = "REAL"
    path.write_text(json.dumps(claim))
    remanifest(target)
    with pytest.raises(ValueError, match="mode"):
        verify_retained_attempt(target)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("auth", "encrypted", False),
        ("auth", "state", "FAILED"),
        ("auth", "public_key", "0" * 64),
        ("auth", "public_key_sha256", "0" * 64),
        ("auth", "method", "password"),
        ("welcome", "width", 128),
        ("welcome", "height", 128),
        ("welcome", "seed", 43),
        ("welcome", "revision", "13.4"),
        ("protocol", "version", 2),
    ],
)
def test_production_verifier_checks_authentication(synthetic_real, section, field, value):
    _, target, auth, _ = synthetic_real
    auth[section][field] = value
    (target / "authentication.json").write_text(json.dumps(auth))
    remanifest(target)
    with pytest.raises(ValueError, match="authenticated runtime") as error:
        verify_retained_attempt(target)
    assert error.value.__cause__ is not None
    frames = []
    traceback = error.value.__traceback__
    while traceback is not None:
        frames.append(traceback.tb_frame.f_code.co_name)
        traceback = traceback.tb_next
    assert "verify_retained_authentication" in frames


@pytest.fixture
def synthetic_real(completed):
    """Synthetic record shapes only; never an operator grant or native execution."""
    from app.simulation.openttd.proof.terrain_attempt import (
        verify_attempt_inventory,
        verify_execution_lineage,
        verify_retained_authentication,
    )

    p, target = completed
    result_path, claim_path = target / "result.json", target / "launch-claim.json"
    result = json.loads(result_path.read_text())
    result.update(mode="REAL", status="REAL_PASS")
    result_path.write_text(json.dumps(result))
    claim = json.loads(claim_path.read_text())
    claim["mode"] = "REAL"
    claim_path.write_text(json.dumps(claim))
    seal = Path(claim["prepared_directory"])
    prelaunch = json.loads((seal / "PRELAUNCH.json").read_text())
    consumed_path = target / "authorization-consumed.json"
    consumed = json.loads(consumed_path.read_text())
    consumed["trust"] = "LOCAL_OPERATOR_ATTESTED"  # Untrusted synthetic JSON, not a typed grant.
    consumed_path.write_text(json.dumps(consumed))
    controlled_marker = target / "controlled-launch-claimed.json"
    marker = json.loads(controlled_marker.read_text())
    marker.update(mode="REAL", consumed_record_sha256=prep.sha256(consumed_path))
    controlled_marker.unlink()
    (target / "native-launch-claimed.json").write_text(json.dumps(marker))
    key = prelaunch["public_key"]
    auth = dict(
        auth=dict(
            encrypted=True,
            state="ACTIVE",
            method="X25519_AuthorizedKey",
            public_key=key,
            public_key_sha256=hashlib.sha256(bytes.fromhex(key)).hexdigest(),
        ),
        welcome=dict(revision="15.3", dedicated=True, width=64, height=64, seed=42, landscape=0),
        protocol=dict(version=3),
    )
    (target / "authentication.json").write_text(json.dumps(auth))
    remanifest(target)
    verify_attempt_inventory(target, "REAL", canonical=True)
    verify_execution_lineage(target, seal, prelaunch, "REAL")
    verify_retained_authentication(auth, prelaunch)
    return p, target, auth, prelaunch


@pytest.mark.parametrize(
    "change", ["missing_auth", "controlled_marker", "missing_marker", "lineage", "extra"]
)
def test_synthetic_real_contract_rejects(synthetic_real, change):
    _, target, _, _ = synthetic_real
    marker = target / "native-launch-claimed.json"
    if change == "missing_auth":
        (target / "authentication.json").unlink()
    elif change == "controlled_marker":
        marker.rename(target / "controlled-launch-claimed.json")
    elif change == "missing_marker":
        marker.unlink()
    elif change == "lineage":
        path = target / "authorization-consumed.json"
        consumed = json.loads(path.read_text())
        consumed["owner_nonce"] = "0" * 32
        path.write_text(json.dumps(consumed))
    else:
        (target / "unexpected-audit-artifact.txt").write_bytes(b"foreign")
    remanifest(target)
    expected = "lineage" if change == "lineage" else "artifact inventory"
    with pytest.raises(ValueError, match=expected):
        verify_retained_attempt(target)


def test_controlled_grant_cannot_authorize_native_process(local_seal):
    grant = authorize(local_seal)
    with pytest.raises(PermissionError):
        grant.require_process(native=True)


def test_historical_pass_remains_blocked_and_byte_identical():
    from app.simulation.openttd.proof.terrain_attempt import inspect_legacy_attempt

    target = (
        Path(__file__).resolve().parents[1]
        / "artifacts/runtime"
        / "terrain-single-page-road-selector-model-a-attempt-83ac85b96daf435aa82de98901808ace"
    )
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    report = inspect_legacy_attempt(target)
    assert report["status"] == "AUDIT_BLOCKED"
    assert report["recorded_status"] == "REAL_PASS"
    assert report["native_single_page_supported"]
    assert len(report["missing_source_inputs"]) == 13
    assert report["diagnostic_prefix_length"] == 7334
    assert (
        report["diagnostic_prefix_sha256"]
        == "4f2a467d8e916325b07c170c86adba310172fc1d43ec1efdc84c043732336a04"
    )
    assert report["final_log_length"] == 7529
    assert (
        report["final_log_sha256"]
        == "221f9a703ba4bea46d9b83307c43d695a3e9c8869dcf2b0ce96d6a12657d6dd0"
    )
    with pytest.raises(ValueError, match="LEGACY_EVIDENCE_LIMITATION"):
        verify_retained_attempt(target)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "trust",
        "allowance",
        "retry",
        "owner",
        "seal",
        "attempt",
        "destination",
        "invocation",
        "duplicate",
    ],
)
def test_controlled_lineage_defect_regression(completed, change):
    _, target = completed
    path = target / "authorization-consumed.json"
    row = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
    elif change == "invocation":
        marker = target / "controlled-launch-claimed.json"
        if marker.exists():
            value = json.loads(marker.read_text())
            value["consumed_record_sha256"] = "0" * 64
            marker.write_text(json.dumps(value))
        else:
            marker.write_text("{}")
    elif change == "duplicate":
        (target / "authorization-extra.json").write_text(json.dumps(row))
    else:
        field, value = {
            "trust": ("trust", "UNTRUSTED"),
            "allowance": ("launch_allowance", 99),
            "retry": ("no_retry", False),
            "owner": ("owner_nonce", "foreign"),
            "seal": ("seal_sha256", "0" * 64),
            "attempt": ("attempt_identity", "foreign"),
            "destination": ("attempt_directory", "/tmp/foreign"),
        }[change]
        row[field] = value
        path.write_text(json.dumps(row))
    remanifest(target)
    with pytest.raises(ValueError):
        verify_retained_attempt(target)


def test_ownership_substitution_defect_regression(completed):
    p, target = completed
    path = p.directory / "path-ownership.json"
    path.chmod(0o600)
    path.write_text('{"invalid_ownership":true}\n')
    frozen_path = p.directory / "source-freeze.json"
    frozen = json.loads(frozen_path.read_text())
    frozen[str(path)] = prep.sha256(path)
    frozen_path.chmod(0o600)
    frozen_path.write_text(json.dumps(frozen))
    ids_path = target / "source-identities.json"
    ids = json.loads(ids_path.read_text())
    ids["source_integrity"] = frozen
    ids_path.write_text(json.dumps(ids))
    remanifest(p.directory)
    remanifest(target)
    with pytest.raises(ValueError):
        verify_retained_attempt(target)


@pytest.mark.parametrize(
    "change",
    ["unknown", "wrong_path", "digest", "provenance", "symlink", "traversal", "missing_bridge"],
)
def test_exact_external_source_policy(candidate, tmp_path, change):
    from app.simulation.openttd.proof.terrain_retention import retain_inputs

    origin = Path(next(iter(prep.source_freeze())))
    unknown = tmp_path / "terrain_bridge.nut"
    unknown.write_bytes(origin.read_bytes())
    if change in ("unknown", "wrong_path"):
        candidate.record["source_integrity"][str(unknown)] = prep.sha256(unknown)
    elif change == "digest":
        candidate.record["source_integrity"][str(origin)] = "0" * 64
    elif change == "provenance":
        candidate.record["source_integrity"][str(unknown)] = prep.sha256(origin)
        candidate.record["source_integrity"].pop(str(origin))
    elif change == "symlink":
        unknown.unlink()
        unknown.symlink_to(origin)
        candidate.record["source_integrity"][str(unknown)] = prep.sha256(origin)
    elif change == "traversal":
        candidate.record["source_integrity"][
            str(origin.parent / ".." / origin.parent.name / origin.name)
        ] = prep.sha256(origin)
    else:
        origin.unlink()
    stage = tmp_path / "retention-challenge"
    stage.mkdir()
    with pytest.raises((ValueError, FileNotFoundError)):
        retain_inputs(candidate, stage)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "unknown_type",
        "missing_path",
        "duplicate",
        "conflict",
        "input",
        "output",
        "disposable",
        "escape",
        "canonical",
        "secret",
    ],
)
def test_ownership_semantic_challenges(completed, change):
    from app.simulation.openttd.proof.terrain_retention import verify_inputs

    p, _ = completed
    path = p.directory / "path-ownership.json"
    value = json.loads(path.read_text())
    if change == "schema":
        value = {"invalid_ownership": True}
    elif change == "unknown_type":
        value["entries"][0]["kind"] = "PUBLIC_SECRET"
    elif change == "missing_path":
        del value["entries"][0]["path"]
    elif change == "duplicate":
        value["entries"].append(value["entries"][0])
    elif change == "conflict":
        value["entries"].append(dict(value["entries"][0], kind="RUNTIME_CREDENTIAL"))
    else:
        row = json.loads((p.directory / "PRELAUNCH.json").read_text())
        index = json.loads((p.directory / "canonical-inputs.json").read_text())
        origins = {e["origin"] for e in index["entries"]}
        if change in ("input", "canonical"):
            entry = next(e for e in value["entries"] if e["path"] in origins)
            entry["kind"] = "GENERATED_EVIDENCE" if change == "input" else "PROTECTED_HISTORICAL"
        elif change == "output":
            next(e for e in value["entries"] if e["path"] == row["attempt_directory"])["kind"] = (
                "IMMUTABLE_SOURCE"
            )
        elif change in ("disposable", "secret"):
            entry = next(
                e
                for e in value["entries"]
                if e["kind"]
                == ("RUNTIME_EPHEMERAL" if change == "disposable" else "RUNTIME_CREDENTIAL")
            )
            entry["kind"] = "IMMUTABLE_SOURCE"
        else:
            value["entries"][0]["path"] = "/tmp/../foreign"
    path.chmod(0o600)
    path.write_text(json.dumps(value))
    record = json.loads((p.directory / "PRELAUNCH.json").read_text())
    # Supply a valid hash for invalid semantics: the semantic validator must still reject.
    record["ownership_sha256"] = prep.sha256(path)
    frozen = json.loads((p.directory / "source-freeze.json").read_text())
    frozen[str(path)] = prep.sha256(path)
    with pytest.raises(ValueError):
        verify_inputs(p.directory, record, frozen)


def test_full_production_inventory_package(tmp_path, monkeypatch):
    import os
    import sys

    from app.simulation.openttd.proof import endpoints
    from app.simulation.openttd.proof.terrain_seal import seal_candidate
    from app.simulation.openttd.runtime.config import RuntimeWorkspace
    from app.simulation.openttd.runtime.ownership import OwnershipGraph

    c = prep.prepare_candidate(
        tmp_path / "actual-candidate", authorization_policy="OPERATOR_ATTENDED_LOCAL_PROOF"
    )
    p = None
    try:
        p = seal_candidate(
            c,
            tmp_path / "actual-seal",
            tmp_path / "actual-attempt",
            authorization_policy="OPERATOR_ATTENDED_LOCAL_PROOF",
        )
        secret = p.key_path.read_bytes()
        assert (
            str(prep.PROJECT / "app/simulation/openttd/terrain_bridge.nut")
            in c.record["source_integrity"]
        )
        monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
        target = destination(p)
        result = asyncio.run(
            execute_single_page(p, LocalFakeBackend(), target, authorization=authorize(p))
        )
        assert result["status"] == "CONTROLLED_PASS"
        assert verify_retained_attempt(target)["mode"] == "CONTROLLED"
        index = json.loads((p.directory / "canonical-inputs.json").read_text())
        assert len(index["entries"]) == len(c.record["source_integrity"]) + 1
        assert all(
            secret not in f.read_bytes()
            for d in (p.directory, target)
            for f in d.rglob("*")
            if f.is_file()
        )
        shutil.rmtree(c.directory)
        assert not p.key_path.exists() and not p.spec.workspace.root.exists()
        assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"
        # Fresh interpreter via fork/exec; never subprocess.Popen or an OpenTTD process.
        child = os.fork()
        if child == 0:
            os.chdir("/tmp")
            env = dict(os.environ, PYTHONPATH=str(prep.PROJECT), PYTHONDONTWRITEBYTECODE="1")
            code = (
                "from pathlib import Path; "
                "from app.simulation.openttd.proof.terrain_attempt "
                "import verify_retained_attempt; assert verify_retained_attempt(Path("
                + repr(str(target))
                + "))['mode']=='CONTROLLED'"
            )
            os.execve(sys.executable, [sys.executable, "-B", "-c", code], env)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        if p is not None:
            p.dispose()
        elif Path(c.record["workspace"]).exists():
            graph = OwnershipGraph.from_public(
                json.loads((c.directory / "path-ownership.json").read_text())
            )
            Path(c.record["key_path"]).unlink(missing_ok=True)
            RuntimeWorkspace.reopen(Path(c.record["workspace"])).close(ownership=graph)


def test_mutable_manifests_cannot_replace_historical_base(completed, tmp_path):
    p, target = completed
    path = p.directory / "historical-integrity.json"
    history = json.loads(path.read_text())
    history["provenance_base"] = str(tmp_path)
    from app.simulation.openttd.proof.historical_protection import protection_digest

    history["sha256"] = protection_digest(history)
    path.chmod(0o600)
    path.write_text(json.dumps(history))
    frozen_path = p.directory / "source-freeze.json"
    frozen = json.loads(frozen_path.read_text())
    frozen[str(path)] = prep.sha256(path)
    frozen_path.chmod(0o600)
    frozen_path.write_text(json.dumps(frozen))
    ids_path = target / "source-identities.json"
    ids = json.loads(ids_path.read_text())
    ids["source_integrity"] = frozen
    ids_path.write_text(json.dumps(ids))
    remanifest(p.directory)
    remanifest(target)
    with pytest.raises(ValueError, match="Historical protection"):
        verify_retained_attempt(target)


@pytest.mark.parametrize("change", ["none", "digest", "protected_bytes", "missing_protected"])
def test_dispose_and_verify_hash_import_regression(local_seal, change):
    from app.simulation.openttd.proof.ownership import dispose_and_verify

    p = local_seal
    frozen_path = p.directory / "source-freeze.json"
    frozen = json.loads(frozen_path.read_text())
    record_path = p.directory / "PRELAUNCH.json"
    record = json.loads(record_path.read_text())
    if change == "digest":
        record["historical_integrity_sha256"] = "0" * 64
        record_path.chmod(0o600)
        record_path.write_text(json.dumps(record))
        frozen[str(record_path)] = prep.sha256(record_path)
        frozen_path.chmod(0o600)
        frozen_path.write_text(
            json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
        )
        remanifest(p.directory)
    elif change in ("protected_bytes", "missing_protected"):
        history = json.loads((p.directory / "historical-integrity.json").read_text())
        protected = Path(record["historical_base"]) / history["entries"][0]["path"]
        if change == "protected_bytes":
            protected.write_bytes(b"altered protected evidence")
        else:
            protected.unlink()
    if change == "none":
        result = dispose_and_verify(p, frozen)
        assert result == dict(
            workspace_disposed=True, credential_removed=True, postrun_integrity_verified=True
        )
    elif change == "missing_protected":
        with pytest.raises(FileNotFoundError) as failure:
            dispose_and_verify(p, frozen)
        assert failure.value.filename == str(protected)
        assert failure.value.__cause__ is None  # Original filesystem exception, untranslated.
    else:
        with pytest.raises(ValueError):
            dispose_and_verify(p, frozen)
    assert not p.spec.workspace.root.exists()
    assert not p.key_path.exists()


@pytest.mark.parametrize(
    "change",
    [
        "protected",
        "source",
        "asset",
        "retained",
        "symlink",
        "traversal",
        "classification",
        "overlap",
    ],
)
def test_fixture_deletion_rejects_persistent_and_aliased_paths(completed, tmp_path, change):
    p, _ = completed
    disposable, protected, persistent, retained = fixture_disposal_sets(p)
    source = next(iter(persistent))
    if change == "protected":
        bad = next(iter(protected))
    elif change == "asset":
        bad = next(f for f in persistent if f.suffix == ".zip")
    elif change == "retained":
        bad = next(iter(retained))
    elif change == "symlink":
        bad = tmp_path / "alias"
        bad.symlink_to(source)
    elif change == "traversal":
        bad = source.parent / ".." / source.parent.name / source.name
    elif change == "classification":
        index_path = p.directory / "canonical-inputs.json"
        index = json.loads(index_path.read_text())
        entry = next(e for e in index["entries"] if e["origin"] == str(source))
        entry["identity"] = "candidate:wrongly-disposable"
        index_path.chmod(0o600)
        index_path.write_text(json.dumps(index))
        bad = source
    else:
        bad = source
    snapshot = {f: f.read_bytes() for f in protected | persistent | retained if f.is_file()}
    with pytest.raises((ValueError, AssertionError)):
        delete_fixture_originals(p, [next(iter(disposable)), bad])
    assert all(f.read_bytes() == raw for f, raw in snapshot.items())


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "nested",
        "unmanifested",
        "secret",
        "missing",
        "directory",
        "symlink",
        "opposite_marker",
        "failure_artifact",
        "canonical_in_attempt",
        "alias",
    ],
)
def test_exact_attempt_inventory(completed, tmp_path, change):
    _, target = completed
    original = target / "receipt.json"
    if change in ("extra", "unmanifested", "secret"):
        (target / "unexpected-audit-artifact.txt").write_bytes(b"controlled secret fixture")
    elif change == "nested":
        (target / "logs").mkdir()
        (target / "logs" / "unexpected.txt").write_bytes(b"extra")
    elif change == "missing":
        original.unlink()
    elif change == "directory":
        original.unlink()
        original.mkdir()
    elif change == "symlink":
        copy = tmp_path / "receipt-copy.json"
        copy.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(copy)
    elif change == "opposite_marker":
        (target / "native-launch-claimed.json").write_bytes(b"{}")
    elif change == "failure_artifact":
        (target / "failed-response.json").write_bytes(b"{}")
    elif change == "canonical_in_attempt":
        (target / "canonical").mkdir()
        (target / "canonical" / ("0" * 64)).write_bytes(b"extra")
    elif change == "alias":
        alias = tmp_path / "attempt-alias"
        alias.symlink_to(target, target_is_directory=True)
        target = alias
    if change != "unmanifested":
        remanifest(target)
    with pytest.raises(ValueError):
        verify_retained_attempt(target)


def test_valid_optional_stdout_inventory(completed):
    _, target = completed
    (target / "stdout.log").write_bytes(b"controlled stdout capture\n")
    remanifest(target)
    assert verify_retained_attempt(target)["mode"] == "CONTROLLED"


@pytest.mark.parametrize(
    "change",
    [
        "raw_false",
        "summary_false",
        "both_false",
        "missing_raw",
        "missing_summary",
        "malformed",
        "missing_field",
        "unknown",
        "remaining",
        "error",
        "wrong_type",
        "foreign_raw",
        "endpoint_contradiction",
        "credential_missing",
    ],
)
def test_cleanup_consistency_full_verifier(completed, change):
    _, target = completed
    raw_path, summary_path = target / "cleanup.raw.json", target / "cleanup.json"
    raw = json.loads(raw_path.read_text())
    summary = json.loads(summary_path.read_text())
    if change in ("raw_false", "both_false"):
        raw["reaped"] = False
    if change in ("summary_false", "both_false"):
        summary["cleanup"]["reaped"] = False
    if change == "missing_field":
        del raw["cleanup_error"]
    elif change == "unknown":
        raw["status"] = "SUCCESS"
        summary["cleanup"]["status"] = "SUCCESS"
    elif change == "remaining":
        raw["remaining_processes"] = [12345]
    elif change == "error":
        raw["cleanup_error"] = [{"stage": "process_cleanup", "type": "Failure"}]
    elif change == "wrong_type":
        raw["reaped"] = 1
    elif change == "foreign_raw":
        raw["pid"] = 12345
    elif change == "endpoint_contradiction":
        summary["endpoints"]["endpoint_verification"]["process_reaped"] = False
    raw_path.write_text(json.dumps(raw))
    summary_path.write_text(json.dumps(summary))
    if change == "missing_raw":
        raw_path.unlink()
    elif change == "missing_summary":
        summary_path.unlink()
    elif change == "malformed":
        raw_path.write_text("{bad json")
    elif change == "credential_missing":
        (target / "cleanup-attestation.json").unlink()
    remanifest(target)
    with pytest.raises(ValueError):
        verify_retained_attempt(target)


def test_coordinated_cleanup_cannot_override_endpoint_observation(completed):
    _, target = completed
    raw = json.loads((target / "cleanup.raw.json").read_text())
    raw.update(reaped=True, remaining_processes=[], cleanup_error=[])
    (target / "cleanup.raw.json").write_text(json.dumps(raw))
    summary_path = target / "cleanup.json"
    summary = json.loads(summary_path.read_text())
    summary["cleanup"] = raw
    summary["endpoints"]["endpoint_verification"]["process_reaped"] = False
    summary_path.write_text(json.dumps(summary))
    remanifest(target)
    with pytest.raises(ValueError, match="endpoint observation"):
        verify_retained_attempt(target)


def test_real_shaped_cleanup_requires_observed_process_exit(synthetic_real):
    _, target, _, _ = synthetic_real
    raw = json.loads((target / "cleanup.raw.json").read_text())
    raw.update(
        pid=12345,
        graceful_attempted=True,
        quit_command="quit",
        returncode=None,
        events=["quit_requested", "reaped"],
        admin_frame_accounting=json.loads((target / "accounting.json").read_text()),
    )
    (target / "cleanup.raw.json").write_text(json.dumps(raw))
    path = target / "cleanup.json"
    summary = json.loads(path.read_text())
    summary["cleanup"] = raw
    path.write_text(json.dumps(summary))
    remanifest(target)
    with pytest.raises(ValueError, match="native cleanup lifecycle"):
        verify_retained_attempt(target)


@pytest.mark.parametrize(
    "gate,value",
    [
        ("cleanup", False),
        ("cleanup", None),
        ("cleanup", 1),
        ("cleanup", "true"),
        ("schema_valid", False),
        ("coverage_valid", False),
        ("native_read_evidence", False),
        ("post_yield_liveness", False),
        ("post_run_integrity", False),
    ],
)
def test_result_gate_consistency_full_verifier(completed, gate, value):
    _, target = completed
    assert verify_retained_attempt(target)["mode"] == "CONTROLLED"
    path = target / "result.json"
    result = json.loads(path.read_text())
    if value is None:
        del result["gates"][gate]
    else:
        result["gates"][gate] = value
    path.write_text(json.dumps(result))
    remanifest(target)
    with pytest.raises(ValueError):
        verify_retained_attempt(target)


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "time_wait",
        "missing_states",
        "malformed",
        "wrong_port",
        "wrong_host",
        "wrong_policy",
        "closed_false",
        "unrelated",
        "udp",
        "wildcard",
        "ipv4_wildcard",
        "ipv6_time_wait",
        "tcp6_listen",
        "tcp6_established",
        "tcp6_close_wait",
        "missing_field",
        *range(1, 13),
    ],
)
def test_endpoint_observation_full_verifier(completed, change):
    p, target = completed
    assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"
    path = target / "cleanup.json"
    value = json.loads(path.read_bytes())
    ep = value["endpoints"]["endpoint_verification"]
    row = dict(
        table="tcp",
        local="127.0.0.1",
        local_port=ep["admin_port"],
        remote="127.0.0.1",
        remote_port=30000,
        state="TIME_WAIT",
        inode=0,
    )
    if change == "time_wait":
        ep["kernel_states"] = [row]
    elif type(change) is int:
        ep["kernel_states"] = [dict(row, state=change)]
    elif change == "missing_states":
        del ep["kernel_states"]
    elif change == "malformed":
        ep["kernel_states"] = [{}]
    elif change == "wrong_port":
        ep["admin_port"] += 1
    elif change == "wrong_host":
        ep["host"] = "192.0.2.1"
    elif change == "wrong_policy":
        ep["policy"] = "untrusted"
    elif change == "closed_false":
        ep["listener_closed"] = False
    elif change == "unrelated":
        port = next(n for n in range(1, 65536) if n not in p.endpoints)
        ep["kernel_states"] = [dict(row, local_port=port, remote_port=port)]
    elif change == "udp":
        ep["kernel_states"] = [dict(row, table="udp")]
    elif change == "wildcard":
        ep["kernel_states"] = [dict(row, table="tcp6", local="::", remote="::")]
    elif change == "ipv4_wildcard":
        ep["kernel_states"] = [dict(row, local="0.0.0.0")]
    elif change == "ipv6_time_wait":
        ep["kernel_states"] = [dict(row, table="tcp6", local="::ffff:127.0.0.1", remote="::")]
    elif change in ("tcp6_listen", "tcp6_established", "tcp6_close_wait"):
        states = {"tcp6_listen": 10, "tcp6_established": 1, "tcp6_close_wait": 8}
        ep["kernel_states"] = [
            dict(row, table="tcp6", local="::", remote="::", state=states[change])
        ]
    elif change == "missing_field":
        ep["kernel_states"] = [dict(row)]
        del ep["kernel_states"][0]["inode"]
    path.write_text(json.dumps(value))
    remanifest(target)
    if change in ("valid", "time_wait", "wildcard", "ipv4_wildcard", "ipv6_time_wait"):
        assert verify_retained_attempt(target)["status"] == "OFFLINE_ACCEPTANCE_PASS"
    else:
        with pytest.raises(ValueError, match="endpoint observation"):
            verify_retained_attempt(target)
