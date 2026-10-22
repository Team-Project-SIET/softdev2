"""Authorization and immutable acquisition orchestration, without native launch."""

import asyncio
from types import SimpleNamespace

import pytest

from app.simulation.openttd.proof import canonical_fleet as driver


def test_run_requires_authorization_before_preflight_or_claim(monkeypatch, tmp_path):
    def forbidden(*args):
        pytest.fail("authorization must precede preflight and launch")

    monkeypatch.setattr(driver, "preflight", forbidden)
    with pytest.raises(ValueError, match="authorization"):
        asyncio.run(driver.run(SimpleNamespace(directory=tmp_path)))
    assert list(tmp_path.iterdir()) == []


def test_protected_save_cannot_overwrite_existing_evidence(monkeypatch, tmp_path):
    existing = tmp_path / "canonical.sav"
    existing.write_bytes(b"protected")

    async def forbidden(*args):
        pytest.fail("console save must not run on an existing path")

    monkeypatch.setattr(driver, "save", forbidden)
    with pytest.raises(ValueError, match="overwrite"):
        asyncio.run(driver.protected_save(None, SimpleNamespace(directory=tmp_path), "canonical"))
    assert existing.read_bytes() == b"protected"


def test_protected_save_uses_existing_native_completion_helper(monkeypatch, tmp_path):
    calls = []

    async def saved(*args):
        calls.append(args)
        return "a" * 64

    monkeypatch.setattr(driver, "save", saved)
    prepared = SimpleNamespace(directory=tmp_path)
    assert asyncio.run(driver.protected_save("owned", prepared, "canonical")) == "a" * 64
    assert calls == [("owned", prepared, "canonical")]


def test_prepare_identity_rejects_attempt20_before_any_write(tmp_path):
    directory = tmp_path / "openttd-15.3-first-freight-delivery-attempt20"
    with pytest.raises(ValueError, match="identity"):
        driver.prepare(directory, stage=driver.CREATE)
    assert not directory.exists()


@pytest.mark.parametrize("identity", ["canonical-fleet-create-q1", "canonical-fleet-create-q2"])
def test_prepare_never_reuses_consumed_creation_identity(tmp_path, monkeypatch, identity):
    def forbidden(*args, **kwargs):
        pytest.fail("consumed identity must be rejected before workspace creation")

    monkeypatch.setattr(driver.RuntimeWorkspace, "create", forbidden)
    directory = tmp_path / identity
    with pytest.raises(ValueError, match="identity"):
        driver.prepare(directory, stage=identity)
    assert not directory.exists()


def test_reopen_normalizes_relative_artifact_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / driver.CREATE
    directory.mkdir()
    calls = []
    monkeypatch.setattr(driver.freight, "reopen", lambda path: calls.append(path))
    driver.reopen(directory.relative_to(tmp_path))
    assert calls == [directory]


def test_reopen_rejects_alias_before_reading_evidence(tmp_path, monkeypatch):
    directory = tmp_path / driver.CREATE
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="alias or symlink"):
        driver.reopen(alias)


def test_reload_requires_canonical_evidence_before_workspace_creation(tmp_path):
    directory = tmp_path / driver.RELOAD
    with pytest.raises(ValueError, match="requires canonical"):
        driver.prepare(directory, stage=driver.RELOAD)
    assert not directory.exists()


def test_configuration_correspondence_excludes_only_connection_ports(tmp_path):
    a, b = tmp_path / "a.cfg", tmp_path / "b.cfg"
    text = "[network]\nserver_port = 1\nserver_admin_port = 2\n[economy]\ntimekeeping_units = 0\n"
    a.write_text(text)
    b.write_text(text.replace("port = 1", "port = 3").replace("port = 2", "port = 4"))
    assert driver.configuration_digest(a) == driver.configuration_digest(b)
    b.write_text(b.read_text().replace("units = 0", "units = 1"))
    assert driver.configuration_digest(a) != driver.configuration_digest(b)


def test_configuration_correspondence_rejects_duplicate_sections(tmp_path):
    config = tmp_path / "bad.cfg"
    config.write_text("[economy]\ntimekeeping_units = 0\n[economy]\ntimekeeping_units = 1\n")
    import configparser

    with pytest.raises(configparser.DuplicateSectionError):
        driver.configuration_digest(config)


def test_bridge_digest_binds_names_and_contents():
    assert driver.bridge_digest({"a": b"x", "b": b"y"}) == driver.bridge_digest(
        {"b": b"y", "a": b"x"}
    )
    assert driver.bridge_digest({"a": b"x"}) != driver.bridge_digest({"b": b"x"})


def test_acquisition_constructs_nine_stages_then_seals_without_dispatch(monkeypatch, tmp_path):
    from app.planning import canonical
    from app.simulation.openttd import freight_canonical_dispatch as dispatch
    from app.simulation.openttd import freight_native_network as network

    calls, sealed = [], []
    native = SimpleNamespace(digest="a" * 64)
    service = SimpleNamespace(
        selection_request=lambda **kwargs: SimpleNamespace(op="select", **kwargs),
        validate_native_selection=lambda *args: None,
    )

    async def plan(*args):
        return None, None, [(0, service), (1, service), (2, service)], "save"

    async def exchange(session, request, directory):
        calls.append(request)
        arg = getattr(request, "arg", 0)
        stage = arg + 1 if request.op == "build" or request.request_id.startswith("s") else 0
        return SimpleNamespace(
            status="BUILT" if request.op == "build" else "READ", s={22: stage, 4: -1}
        )

    async def seal(session, directory, n):
        sealed.append(n)
        calls.append(SimpleNamespace(op="seal", arg=n))

    monkeypatch.setattr(network, "plan_network_world", plan)
    monkeypatch.setattr(network, "require_selected_service_count", lambda *args: None)
    monkeypatch.setattr(dispatch, "seal_service", seal)
    monkeypatch.setattr(canonical, "plan_hash", lambda value: "execution")
    monkeypatch.setattr(driver.freight, "exchange", exchange)
    monkeypatch.setattr(driver, "admit", lambda *args, **kwargs: native)
    monkeypatch.setattr(driver, "verify_snapshot", lambda *args: None)
    native.model_dump = lambda **kwargs: {"digest": "plan"}
    metadata = {"predecessor": {"executor_source_digest": "source"}}
    result = {"mutations": 0}
    plans = asyncio.run(
        driver.construct_originals(
            None,
            SimpleNamespace(directory=tmp_path),
            None,
            None,
            "before",
            "seal",
            metadata,
            result,
        )
    )
    assert plans == [native] * 3
    assert sealed == [0, 1, 2]
    assert [q.op for q in calls if q.op in ("select", "seal")] == ["select", "seal"] * 3
    assert result["mutations"] == 27
    assert [q.arg for q in calls if q.op == "build"] == list(range(9)) * 3
    assert not any(q.op in ("observe", "finish") for q in calls)


def test_created_manifest_roundtrips_strict_tuple_state(tmp_path):
    import json

    from test_freight_canonical import observation, parse

    expected = parse(observation())
    (tmp_path / "canonical-provenance.json").write_text(
        json.dumps({"observation": expected.model_dump(mode="json")})
    )
    assert driver.load_created(tmp_path) == expected


@pytest.mark.parametrize("drift", [False, True])
def test_acquire_brackets_native_save_and_rejects_drift(monkeypatch, tmp_path, drift):
    import hashlib
    import json

    from test_freight_canonical import observation, parse

    from app.simulation.openttd import freight_canonical_dispatch as dispatch
    from app.simulation.openttd import freight_canonical_runtime as runtime
    from app.simulation.openttd import scenario_capital as capital

    calls = []

    async def exchange(*args, **kwargs):
        return None

    async def construct(*args):
        calls.append("construct-three")

    async def boundary(*args, **kwargs):
        calls.append("paused-native-ack")

    async def save(backend, prepared, name):
        calls.append("save-" + name)
        path = prepared.directory / (name + ".sav")
        path.write_bytes(name.encode())
        return hashlib.sha256(path.read_bytes()).hexdigest()

    async def collect(session, directory, **kwargs):
        calls.append("collect-" + directory.name)
        raw = directory / "canonical-readback.jsonl"
        raw.write_bytes(b"correlated-native-readback")
        value = observation()
        value.update(
            qualification_id=kwargs["identity"],
            source_save_sha256=kwargs["source_save_sha256"],
            raw_readback_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        )
        if drift and directory.name == "checkpoint-after":
            value["state"]["cash"] += 1
        return parse(value)

    monkeypatch.setattr(driver.freight, "exchange", exchange)
    monkeypatch.setattr(driver, "construct_originals", construct)
    monkeypatch.setattr(driver, "protected_save", save)
    monkeypatch.setattr(driver, "console", lambda *args: calls.append("pause-console"))
    monkeypatch.setattr(dispatch, "read_boundary", boundary)
    monkeypatch.setattr(runtime, "collect_canonical", collect)
    monkeypatch.setattr(capital, "verify_capital", lambda *args: {})
    monkeypatch.setattr(capital, "require_company_policy", lambda *args: None)
    accounting = SimpleNamespace(begin_funding=lambda: None, end_funding=lambda: None)
    metadata = {"bridge_sha256": "b" * 64, "configuration_sha256": "c" * 64}
    result = {}
    coro = driver.acquire(
        None, SimpleNamespace(directory=tmp_path), None, accounting, "seal", metadata, result
    )
    if drift:
        with pytest.raises(ValueError, match="correspondence"):
            asyncio.run(coro)
        assert not (tmp_path / "canonical-provenance.json").exists()
    else:
        asyncio.run(coro)
        manifest = json.loads((tmp_path / "canonical-provenance.json").read_bytes())
        assert (
            manifest["observation"]["source_save_sha256"]
            == hashlib.sha256(b"canonical").hexdigest()
        )
        assert result["status"] == "CANONICAL_CREATED_PENDING_FRESH_PROCESS_RELOAD"
    assert calls == [
        "save-before",
        "construct-three",
        "pause-console",
        "paused-native-ack",
        "save-checkpoint-before",
        "collect-checkpoint-before",
        "save-canonical",
        "collect-checkpoint-after",
    ]


def test_prepare_failure_removes_owned_credentials_and_workspace(monkeypatch, tmp_path):
    def fail(*args):
        raise ValueError("injected graphics staging failure")

    monkeypatch.setattr(driver, "stage_opengfx", fail)
    directory = tmp_path / driver.CREATE
    with pytest.raises(ValueError, match="injected graphics"):
        driver.prepare(directory, stage=driver.CREATE)
    assert directory.exists()
    assert not list(directory.rglob(".admin-secret"))
    assert not list(directory.rglob("openttd.cfg"))


@pytest.mark.parametrize("artifact_collision", [False, True])
def test_failed_launch_retains_diagnostics_and_cleans_owned_workspace(
    monkeypatch, tmp_path, artifact_collision
):
    import json

    root = tmp_path / "isolated"
    root.mkdir()
    logs = root / "logs"
    logs.mkdir()
    key = root / ".admin-secret"
    key.write_bytes(b"secret")

    def close():
        key.unlink()
        logs.rmdir()
        root.rmdir()

    prepared = SimpleNamespace(
        directory=tmp_path,
        key_path=key,
        spec=SimpleNamespace(workspace=SimpleNamespace(root=root, logs=logs, close=close)),
    )
    (tmp_path / "PRELAUNCH.json").write_text("{}")
    if artifact_collision:
        (tmp_path / "frames.json").write_text("protected diagnostic")

    class Backend:
        process = None

        async def launch(self, prepared):
            raise RuntimeError("injected launch failure")

        async def cleanup(self, prepared):
            return dict(reaped=True, sockets_closed=True, cleanup_error=[], remaining_processes=[])

    monkeypatch.setattr(driver, "CanonicalBackend", lambda **kwargs: Backend())
    monkeypatch.setattr(driver, "preflight", lambda value: {"budgets": {"total_seconds": 1}})
    monkeypatch.setattr(driver, "verify_cleanup_endpoints", lambda *args: {})
    result = asyncio.run(driver.run(prepared, authorize_one_launch=True))
    assert result["status"] == ("FAILED_EVIDENCE" if artifact_collision else "FAILED")
    assert "injected launch failure" in result["error"]
    assert not root.exists()
    cleanup = json.loads((tmp_path / "cleanup.json").read_bytes())
    assert cleanup["workspace_disposed"] and cleanup["credential_removed"]
    assert json.loads((tmp_path / "CLAIM.json").read_bytes())["consumed"]
    assert (tmp_path / "artifact-manifest.sha256").exists()
    if artifact_collision:
        assert (tmp_path / "frames.json").read_text() == "protected diagnostic"
        assert result["status"] == "FAILED_EVIDENCE"
