"""Real candidate validators and capture setup, exclusively controlled assets."""

import pytest

from app.simulation.openttd.proof import terrain_preparation as prep
from tests.test_terrain_single_page_preparation import candidate as candidate  # noqa: F401


def test_real_preflight_after_capture_setup(candidate):
    candidate.preflight()
    root = prep.Path(candidate.record["workspace"])
    for name in ("stdout.log", "stderr.log"):
        (root / "logs" / name).touch(mode=0o600)
    candidate.preflight(capture_phase="prepared")


@pytest.mark.parametrize(
    "defect",
    ["third", "cache", "changed", "missing", "symlink", "directory", "fifo", "parent", "nonempty"],
)
def test_capture_and_input_rejections(candidate, defect):
    import os

    root = prep.Path(candidate.record["workspace"])
    for name in ("stdout.log", "stderr.log"):
        (root / "logs" / name).touch(mode=0o600)
    output = root / "logs/stdout.log"
    if defect == "third":
        (root / "logs/extra.log").touch()
    elif defect == "cache":
        (root / "extra").touch()
    elif defect == "changed":
        (root / "game/NoMutationBridge/main.nut").write_text("changed")
    elif defect == "missing":
        (root / "game/NoMutationBridge/main.nut").unlink()
    elif defect in ("symlink", "directory", "fifo"):
        output.unlink()
        if defect == "symlink":
            output.symlink_to(root / "openttd.cfg")
        elif defect == "directory":
            output.mkdir()
        else:
            os.mkfifo(output)
    elif defect == "parent":
        (root / "logs").chmod(0o777)
    else:
        output.write_bytes(b"not empty")
    with pytest.raises(ValueError):
        candidate.preflight(capture_phase="prepared")


def test_capture_exact_paths_and_collision(candidate):
    from app.simulation.openttd.proof.terrain_capture import open_capture, validate_captures

    root = prep.Path(candidate.record["workspace"])
    for path in (root / "logs/../other.log", root / "logs/other.log", root / "openttd.cfg"):
        with pytest.raises(ValueError, match="Unapproved"):
            open_capture(root, path)
    with pytest.raises(ValueError, match="collision"):
        validate_captures(root, inputs=[root / "logs/stdout.log"])


def test_running_capture_contents_are_not_inputs(candidate):
    root = prep.Path(candidate.record["workspace"])
    for name in ("stdout.log", "stderr.log"):
        path = root / "logs" / name
        path.touch(mode=0o600)
        path.write_bytes(b"generated runtime output")
    candidate.preflight(capture_phase="running")
    with pytest.raises(ValueError):
        candidate.preflight()


# Temporary seals and claims below are controlled fixtures only, never native attempts.
from tests.test_terrain_model_a import local_seal as local_seal  # noqa: E402,F401


@pytest.fixture
def backend_boundary(local_seal, monkeypatch):
    from app.simulation.openttd.proof import native
    from app.simulation.openttd.proof.terrain_authorization import LocalOperatorAuthorization
    from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend
    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt
    from tests.test_terrain_model_a import authorize, destination

    original = LocalOperatorAuthorization.require_process
    # Only the trust gate is adapted to controlled grants. Production validators run unchanged.
    monkeypatch.setattr(
        LocalOperatorAuthorization,
        "require_process",
        lambda self, *, native: original(self, native=False),
    )
    monkeypatch.setattr(native, "BINARY", prep.BINARY)
    monkeypatch.setattr(native, "BINARY_SHA256", prep.BINARY_SHA256)
    monkeypatch.setattr(native, "matching_processes", lambda p: [])
    grant = authorize(local_seal)
    claim = consume_authorized_attempt(local_seal.directory, destination(local_seal), grant)
    from app.simulation.openttd.proof.harness import sha256, write_json

    write_json(
        destination(local_seal) / "launch-claim.json",
        dict(
            mode="REAL",
            prepared_directory=str(local_seal.directory),
            request_sha256=sha256(local_seal.directory / "request.json"),
            no_retry=True,
        ),
    )
    backend = SinglePageNativeBackend(authorized_one_launch=True)
    backend.bind_authorization(grant, claim)
    return local_seal, backend, destination(local_seal)


@pytest.mark.parametrize("failure", [None, "popen", "input", "third"])
def test_production_backend_capture_sequence(backend_boundary, monkeypatch, failure):
    import asyncio
    from io import BytesIO

    from app.simulation.openttd.proof import terrain_native
    from app.simulation.openttd.proof.harness import sha256

    prepared, backend, destination = backend_boundary
    calls = []
    checks = []
    original = backend.validate_launch

    def checked(p):
        checks.append(len(backend._logs))
        if len(backend._logs) == 2:
            if failure == "input":
                (p.spec.workspace.game / "NoMutationBridge/main.nut").write_text("changed")
            if failure == "third":
                (p.spec.workspace.logs / "extra.log").touch()
        return original(p)

    monkeypatch.setattr(backend, "validate_launch", checked)

    class FakeProcess:
        pid = 99999999
        returncode = None
        stdin = BytesIO()
        stdout = BytesIO()
        stderr = BytesIO()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    def fake_popen(*args, **kwargs):
        calls.append(args)
        assert checks == [0, 2]
        assert all(stream.closed is False for stream in backend._logs)
        if failure == "popen":
            raise OSError("controlled Popen failure")
        return FakeProcess()

    monkeypatch.setattr(terrain_native.subprocess, "Popen", fake_popen)

    async def run():
        try:
            if failure:
                with pytest.raises(Exception):
                    await backend.launch(prepared)
            else:
                await backend.launch(prepared)
            assert len(calls) == (0 if failure in ("input", "third") else 1)
            marker = prep.json.loads((destination / "native-launch-claimed.json").read_text())
            assert marker["consumed_record_sha256"] == sha256(
                destination / "authorization-consumed.json"
            )
            with pytest.raises(Exception):
                await backend.launch(prepared)
            assert len(calls) <= 1
        finally:
            result = await backend.cleanup(prepared)
            assert result["reaped"] and not result["remaining_processes"]
            assert not backend._logs

    asyncio.run(run())
    assert destination.exists() and (destination / "authorization-consumed.json").exists()


def test_capture_descriptor_replacement(candidate):
    from app.simulation.openttd.proof.terrain_capture import open_capture, validate_captures

    root = prep.Path(candidate.record["workspace"])
    streams = [open_capture(root, root / "logs" / n) for n in ("stdout.log", "stderr.log")]
    try:
        output = root / "logs/stdout.log"
        output.unlink()
        output.touch(mode=0o600)
        with pytest.raises(ValueError, match="descriptor/path"):
            validate_captures(root, phase="prepared", streams=streams)
    finally:
        for stream in streams:
            stream.close()


def test_production_failure_retention(local_seal, monkeypatch):
    import asyncio

    from app.simulation.openttd.proof import native, terrain_native
    from app.simulation.openttd.proof.terrain_attempt import execute_single_page
    from app.simulation.openttd.proof.terrain_authorization import LocalOperatorAuthorization
    from tests.test_terrain_model_a import authorize, destination

    original = LocalOperatorAuthorization.require_process
    monkeypatch.setattr(
        LocalOperatorAuthorization,
        "require_process",
        lambda self, *, native: original(self, native=False),
    )
    monkeypatch.setattr(native, "BINARY", prep.BINARY)
    monkeypatch.setattr(native, "BINARY_SHA256", prep.BINARY_SHA256)
    monkeypatch.setattr(native, "matching_processes", lambda p: [])
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise OSError("password=hidden controlled Popen failure")

    monkeypatch.setattr(terrain_native.subprocess, "Popen", fail)
    backend = terrain_native.SinglePageNativeBackend(authorized_one_launch=True)
    result = asyncio.run(
        execute_single_page(
            local_seal, backend, destination(local_seal), authorization=authorize(local_seal)
        )
    )
    assert len(calls) == 1 and result["launches"] == 0
    assert result["failure_code"] == "LAUNCH_FAILED"
    diag = result["diagnostics"]
    assert diag["failure_stage"] == "popen" and diag["popen_invoked"]
    assert diag["claim_state"] == "CONSUMED"
    assert diag["cleanup"]["passed"] and diag["cleanup"]["reaped"]
    assert diag["validation"]["unexpected_paths"] == []
    assert (
        diag["validation"]["expected_runtime_input_count"]
        == diag["validation"]["actual_runtime_input_count"]
    )
    assert "hidden" not in prep.json.dumps(diag)
    assert "<REDACTED>" in prep.json.dumps(diag)
    assert diag["exception_causes"][-1]["type"] == "OSError"
    assert (destination(local_seal) / "authorization-consumed.json").exists()
    with pytest.raises(ValueError, match="already claimed"):
        asyncio.run(execute_single_page(local_seal, backend, destination(local_seal)))
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["third", "input"])
def test_final_validation_failure_retains_precise_diagnostics(local_seal, monkeypatch, change):
    import asyncio

    from app.simulation.openttd.proof import native, terrain_native
    from app.simulation.openttd.proof.terrain_attempt import execute_single_page
    from app.simulation.openttd.proof.terrain_authorization import LocalOperatorAuthorization
    from tests.test_terrain_model_a import authorize, destination

    original_guard = LocalOperatorAuthorization.require_process
    monkeypatch.setattr(
        LocalOperatorAuthorization,
        "require_process",
        lambda self, *, native: original_guard(self, native=False),
    )
    monkeypatch.setattr(native, "BINARY", prep.BINARY)
    monkeypatch.setattr(native, "BINARY_SHA256", prep.BINARY_SHA256)
    monkeypatch.setattr(native, "matching_processes", lambda p: [])
    backend = terrain_native.SinglePageNativeBackend(authorized_one_launch=True)
    original = backend.validate_launch

    def mutated(p):
        if len(backend._logs) == 2:
            if change == "third":
                (p.spec.workspace.logs / "extra.log").touch()
            else:
                (p.spec.workspace.game / "NoMutationBridge/main.nut").write_text("changed")
        return original(p)

    monkeypatch.setattr(backend, "validate_launch", mutated)

    def forbidden(*args, **kwargs):
        raise AssertionError("Popen must not be invoked")

    monkeypatch.setattr(terrain_native.subprocess, "Popen", forbidden)
    result = asyncio.run(
        execute_single_page(
            local_seal, backend, destination(local_seal), authorization=authorize(local_seal)
        )
    )
    assert result["failure_code"] == "SOURCE_INTEGRITY_FAILED"
    diag = result["diagnostics"]
    assert diag["failure_stage"] == "final_pre_popen_validation"
    assert diag["popen_invoked"] is False and diag["claim_state"] == "CONSUMED"
    assert diag["failing_function"] == "preflight"
    if change == "third":
        assert diag["exception_causes"][-1]["message"] == "Unexpected runtime cache input"
        assert diag["validation"]["unexpected_paths"] == [
            str(local_seal.spec.workspace.logs / "extra.log")
        ]
        assert (
            diag["validation"]["actual_runtime_input_count"]
            == diag["validation"]["expected_runtime_input_count"] + 1
        )
    else:
        assert diag["validation"]["identity_mismatches"]
    assert len(prep.json.dumps(diag)) < 32768


def test_capture_preflight_checks_spec_before_claim(local_seal):
    from dataclasses import replace

    from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend
    from tests.test_terrain_model_a import destination

    bad = replace(
        local_seal,
        spec=replace(local_seal.spec, stdout_path=local_seal.spec.workspace.root / "other.log"),
    )
    backend = SinglePageNativeBackend(authorized_one_launch=True)
    with pytest.raises(ValueError, match="capture paths"):
        backend.preflight(bad)
    assert not destination(local_seal).exists()


def test_failure_diagnostics_preserve_failure_when_manifest_damaged(local_seal, monkeypatch):
    from types import SimpleNamespace

    from app.simulation.openttd.proof.terrain_failure import failure_diagnostics
    from tests.test_terrain_model_a import destination

    original = prep.Path.read_text

    def unreadable(path, *args, **kwargs):
        if path.name == "runtime-materializations.json":
            raise OSError("secret=must-not-be-retained")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(prep.Path, "read_text", unreadable)
    diag = failure_diagnostics(
        ValueError("private_key=must-not-be-retained"),
        local_seal,
        SimpleNamespace(launches=0),
        destination(local_seal),
    )
    assert diag["diagnostics_error"] == "OSError"
    assert "must-not-be-retained" not in prep.json.dumps(diag)
