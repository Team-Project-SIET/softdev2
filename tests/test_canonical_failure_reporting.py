"""Offline replay of Q2 fatal evidence, without native processes or connections."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.simulation.openttd.proof.canonical_fleet import failure_details

Q2 = Path("artifacts/runtime/canonical-fleet-create-q2")


def prepared(tmp_path, text):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "stderr.log").write_text(text)
    return SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )


def test_replay_q2_retains_native_fatal_and_pending_request(tmp_path):
    value = prepared(tmp_path, (Q2 / "stderr.log").read_text())
    request = (Q2 / "select-1-request.json").read_bytes()
    (tmp_path / "select-1-request.json").write_bytes(request)
    result = failure_details(value, TimeoutError())
    assert result["error"] == "GameScriptError: CANONICAL_UNSEALED_SERVICE"
    assert result["secondary_error"] == "TimeoutError: "
    native = result["native_failure"]
    assert native["line"] == 701
    assert any("Handle()]" in line and "line [127]" in line for line in native["context"])
    assert native["pending_requests"] == [
        dict(artifact="select-1-request.json", request=json.loads(request))
    ]


@pytest.mark.parametrize(
    "text",
    [
        "CANONICAL_UNSEALED_SERVICE\n",
        "dbg: [script:4] [18] [I] Your script made an error: MISLEADING\n"
        "dbg: [script:0] The script died unexpectedly.\n",
        "dbg: [script:0] [18] [S] Your script made an error: INCOMPLETE\n",
    ],
)
def test_no_promotion_without_complete_native_fatal(tmp_path, text):
    value = prepared(tmp_path, text)
    assert failure_details(value, TimeoutError("transport")) == {"error": "TimeoutError: transport"}


def test_explicit_python_failure_is_not_replaced_by_log(tmp_path):
    value = prepared(tmp_path, (Q2 / "stderr.log").read_text())
    assert failure_details(value, ValueError("receipt mismatch")) == {
        "error": "ValueError: receipt mismatch"
    }


def test_ambiguous_requests_do_not_invent_correlation(tmp_path):
    value = prepared(tmp_path, (Q2 / "stderr.log").read_text())
    for name in ("a", "b"):
        (tmp_path / (name + "-request.json")).write_text(json.dumps(dict(request_id=name)))
    assert (
        failure_details(value, ConnectionError())["native_failure"]["correlation"] == "unresolved"
    )


def test_partial_request_artifact_cannot_obscure_native_fatal(tmp_path):
    value = prepared(tmp_path, (Q2 / "stderr.log").read_text())
    (tmp_path / "select-1-request.json").write_text('{"request_id":')
    result = failure_details(value, TimeoutError())
    assert result["error"] == "GameScriptError: CANONICAL_UNSEALED_SERVICE"
    assert result["secondary_error"] == "TimeoutError: "
    native = result["native_failure"]
    assert native["correlation"] == "unresolved"
    assert native["correlation_errors"][0]["artifact"] == "select-1-request.json"
