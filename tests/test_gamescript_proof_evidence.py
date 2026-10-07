import pytest

from app.simulation.openttd.proof.gamescript_evidence import parse_gamescript_evidence

REQUEST_ID = "openttd15-real-ack-002"
MARKERS = (
    "BRIDGE_STARTED protocol=1 api=15",
    f"BRIDGE_REQUEST_RECEIVED request_id={REQUEST_ID}",
    f"BRIDGE_ACK_SENT request_id={REQUEST_ID}",
    f"BRIDGE_POST_ACK_ALIVE request_id={REQUEST_ID}",
)


def native_log(markers=MARKERS):
    return "".join(
        f"[2026-10-05 00:00:00] dbg: [script:4] [18] [I] {m}\n" for m in markers
    ).encode()


def test_complete_internal_evidence_retains_exact_support():
    raw = native_log()
    evidence = parse_gamescript_evidence(raw, REQUEST_ID)
    evidence.require_complete()
    assert evidence.startup_observed and evidence.request_received
    assert evidence.ack_sent and evidence.post_ack_alive
    assert evidence.request_id == REQUEST_ID
    assert evidence.ordered_sequence == tuple(m.split()[0] for m in MARKERS)
    assert [record.line_number for record in evidence.records] == [1, 2, 3, 4]
    assert evidence.records[0].raw_line.endswith(MARKERS[0])
    assert evidence.source_log == "stderr.log"
    assert (
        evidence.raw_evidence_digest
        == parse_gamescript_evidence(raw, REQUEST_ID).raw_evidence_digest
    )


@pytest.mark.parametrize(
    "markers",
    [
        (MARKERS[0], MARKERS[0]),
        (MARKERS[1], MARKERS[0]),
        (MARKERS[0], MARKERS[1], MARKERS[3], MARKERS[2]),
        (MARKERS[0], MARKERS[1].replace(REQUEST_ID, "wrong")),
        (MARKERS[0], MARKERS[1], MARKERS[2].replace(REQUEST_ID, "wrong")),
        (MARKERS[0], MARKERS[1], MARKERS[2], MARKERS[3].replace(REQUEST_ID, "wrong")),
    ],
)
def test_invalid_order_duplicate_or_wrong_identity_rejected(markers):
    with pytest.raises(ValueError):
        parse_gamescript_evidence(native_log(markers), REQUEST_ID)


@pytest.mark.parametrize("count", range(4))
def test_missing_lifecycle_fact_cannot_satisfy_proof(count):
    evidence = parse_gamescript_evidence(native_log(MARKERS[:count]), REQUEST_ID)
    with pytest.raises(ValueError, match="Incomplete"):
        evidence.require_complete()


def test_non_native_and_partial_records_do_not_prove_liveness():
    with pytest.raises(ValueError):
        parse_gamescript_evidence(("Python " + MARKERS[0] + "\n").encode(), REQUEST_ID)
    evidence = parse_gamescript_evidence(native_log()[:-1], REQUEST_ID)
    assert not evidence.post_ack_alive


def test_actual_start_emits_ordered_evidence_after_loop_continues():
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="ping",request_id="'
        + REQUEST_ID
        + '"})); ::bridge <- NoMutationBridge(); '
        'try { bridge.Start(); } catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    assert [str(x) for x in root["markers"]] == list(MARKERS)
    assert list(root["marker_ticks"]) == [0, 0, 0, 1]
    assert len(root["replies"]) == 1 and root["ticks"] == 2


def test_send_failure_emits_no_ack_or_post_ack_marker():
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute("::send_ok = false;")
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="ping",request_id="'
        + REQUEST_ID
        + '"})); ::bridge <- NoMutationBridge(); '
        'try { bridge.Start(); } catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    assert [str(x) for x in vm.get_roottable()["markers"]] == list(MARKERS[:2])


def test_network_ack_without_internal_evidence_fails(tmp_path):
    import asyncio

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    class NoInternalEvidence(ControlledBackend):
        async def wait_gamescript(self, prepared, *, complete):
            evidence = parse_gamescript_evidence(native_log(MARKERS[:1]), REQUEST_ID)
            if complete:
                evidence.require_complete()
            return evidence

    prepared = make_prepared(tmp_path)
    result = asyncio.run(execute_attempt(prepared, NoInternalEvidence()))
    assert result["status"] == "CONTROLLED_FAILED"
    assert result["requests_sent"] == 1
    assert result["receipt"] is None


def test_internal_evidence_without_network_ack_fails(tmp_path):
    import asyncio

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    class NoNetworkAck(ControlledBackend):
        async def ping(self, request):
            await super().ping(request)
            raise TimeoutError("No network ACK")

    result = asyncio.run(execute_attempt(make_prepared(tmp_path), NoNetworkAck()))
    assert result["status"] == "CONTROLLED_FAILED" and result["receipt"] is None


def test_observed_log_retained_before_shutdown_and_workspace_cleanup(tmp_path):
    import asyncio

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    class CheckRetention(ControlledBackend):
        async def cleanup(self, prepared):
            attempt = tmp_path / "openttd-15.3-real-ack-attempt2"
            assert (attempt / "gamescript-evidence.json").is_file()
            raw = (attempt / "gamescript-observed.log").read_bytes()
            parse_gamescript_evidence(raw, REQUEST_ID).require_complete()
            assert prepared.spec.workspace.root.exists()
            return await super().cleanup(prepared)

    backend = CheckRetention()
    result = asyncio.run(execute_attempt(make_prepared(tmp_path), backend))
    assert result["status"] == "CONTROLLED_SUCCESS"
    assert backend.sends == 1


def test_attempt1_history_immutable_and_classification_unchanged(tmp_path):
    import asyncio
    import json
    from dataclasses import replace

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.proof.attempt import execute_attempt
    from app.simulation.openttd.proof.harness import manifest, prepare_proof

    history = tmp_path / "openttd-15.3-real-ack-attempt1"
    history.mkdir()
    report = (
        "REAL ACK PROOF FAILED — NO RETRY PERFORMED — "
        "required explicit GameScript startup/event-processing and post-ACK "
        "liveness evidence not retained"
    )
    (history / "final-report.md").write_text(report)
    (history / "proof-evidence.json").write_text(
        json.dumps(
            {"status": "REAL_FAILED", "launches": 1, "requests_sent": 1, "automatic_retries": 0}
        )
    )
    before = manifest(history)
    prepared = make_prepared(tmp_path)
    backend = ControlledBackend()
    try:
        with pytest.raises(ValueError, match="Attempt1"):
            asyncio.run(
                execute_attempt(
                    replace(
                        prepared, directory=history, request=PingRequest("openttd15-real-ack-001")
                    ),
                    backend,
                )
            )
        with pytest.raises(ValueError, match="Attempt1"):
            prepare_proof(
                history,
                binary=prepared.spec.identity.executable,
                binary_sha256=prepared.spec.identity.sha256,
            )
        assert manifest(history) == before
        assert (history / "final-report.md").read_text() == report
        assert json.loads((history / "proof-evidence.json").read_text()) == {
            "status": "REAL_FAILED",
            "launches": 1,
            "requests_sent": 1,
            "automatic_retries": 0,
        }
        assert backend.launches == backend.sends == 0
    finally:
        prepared.dispose()


def test_attempt2_preparation_new_identity_freeze_and_no_native_activity(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    import json
    import subprocess

    from test_real_ack_harness import make_prepared

    from app.simulation.openttd.proof.harness import REQUEST

    def forbidden(*args, **kwargs):
        raise AssertionError("No native activity authorized")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "open_connection", forbidden)
    prepared = make_prepared(tmp_path)
    try:
        assert REQUEST.request_id == REQUEST_ID
        assert (
            prepared.request.to_bytes()
            == b'{"protocol":1,"request_id":"openttd15-real-ack-002","type":"ping"}'
        )
        data = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert data["request_sha256"] == hashlib.sha256(prepared.request.to_bytes()).hexdigest()
        assert (
            data["attempt"] == 2
            and data["gameplay_launches"] == data["live_admin_connections"] == 0
        )
        freeze = json.loads((prepared.directory / "source-freeze.json").read_text())
        assert any(name.endswith("/proof/gamescript_evidence.py") for name in freeze)
        assert any(name.endswith("/gamescript_bridge_package/main.nut") for name in freeze)
        assert not (prepared.directory / "gamescript-evidence.json").exists()
        secret = prepared.key_path.read_bytes()
        evidence = b"".join(p.read_bytes() for p in prepared.directory.glob("*.json"))
        assert secret not in evidence and secret.hex().encode() not in evidence
    finally:
        prepared.dispose()


def test_company_script_cannot_substitute_for_gamescript():
    with pytest.raises(ValueError, match="GameScript"):
        parse_gamescript_evidence(native_log().replace(b"[18]", b"[0]"), REQUEST_ID)


def test_missing_startup_blocks_the_single_request(tmp_path):
    import asyncio

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    class NoStartup(ControlledBackend):
        async def wait_gamescript(self, prepared, *, complete):
            return parse_gamescript_evidence(b"", REQUEST_ID)

    backend = NoStartup()
    result = asyncio.run(execute_attempt(make_prepared(tmp_path), backend))
    assert result["status"] == "CONTROLLED_FAILED"
    assert backend.sends == result["requests_sent"] == 0


def test_late_duplicate_startup_fails_even_after_network_and_internal_evidence(tmp_path):
    import asyncio

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    class LateDuplicate(ControlledBackend):
        async def cleanup(self, prepared):
            with prepared.spec.stderr_path.open("ab") as stream:
                stream.write(native_log(MARKERS[:1]))
            return await super().cleanup(prepared)

    result = asyncio.run(execute_attempt(make_prepared(tmp_path), LateDuplicate()))
    assert result["status"] == "CONTROLLED_FAILED"


def test_native_capture_waits_for_complete_visible_record_not_shutdown(tmp_path, monkeypatch):
    import asyncio

    from test_real_ack_harness import make_prepared

    from app.simulation.openttd.proof.native import NativeBackend

    prepared = make_prepared(tmp_path)
    backend = NativeBackend(authorized_one_launch=True)
    monkeypatch.setattr(backend, "health", lambda: None)
    prepared.spec.stderr_path.write_bytes(native_log()[:-1])
    polls = []

    async def visible_on_next_poll(delay):
        polls.append(delay)
        prepared.spec.stderr_path.write_bytes(native_log())

    monkeypatch.setattr(asyncio, "sleep", visible_on_next_poll)
    try:
        evidence = asyncio.run(backend.wait_gamescript(prepared, complete=True))
        evidence.require_complete()
        assert polls == [0.01]
        assert prepared.spec.workspace.root.exists()
    finally:
        prepared.dispose()


def test_proof_records_and_raw_snapshot_digest_agree(tmp_path):
    import asyncio
    import hashlib
    import json

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt

    result = asyncio.run(execute_attempt(make_prepared(tmp_path), ControlledBackend()))
    assert result["status"] == "CONTROLLED_SUCCESS"
    attempt = tmp_path / "openttd-15.3-real-ack-attempt2"
    evidence = json.loads((attempt / "gamescript-evidence.json").read_text())
    raw = (attempt / evidence["source_log"]).read_bytes()
    assert evidence["raw_evidence_digest"] == hashlib.sha256(raw).hexdigest()
    assert result["requests_sent"] == 1 and result["automatic_retries"] == 0


def test_native_backend_refuses_second_ping_without_writing():
    import asyncio

    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.proof.native import NativeBackend

    backend = NativeBackend(authorized_one_launch=True)
    backend._sent = True
    with pytest.raises(RuntimeError, match="Exactly one"):
        asyncio.run(backend.ping(PingRequest(REQUEST_ID)))


# These historical modes retain their pre-production bridge safety contract.
pytestmark = pytest.mark.usefixtures("checkpoint_structural_bridge")
