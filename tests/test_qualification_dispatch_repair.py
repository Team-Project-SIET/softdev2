"""Attempt-1 dispatch reproduction and delayed phase-entry deadline regressions."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_qualification_coordinator import QualificationWire, collect
from test_qualification_native import vm_for

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.proof.qualification_contract import qualification_contract
from app.simulation.openttd.qualification_bridge import qualification_bridge_source
from app.simulation.openttd.qualification_session import QualificationPhase

HISTORY = Path("artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt1")


def legacy_probe_source(source):
    # Native APIs are stubs; compiler and VM are the unmodified tagged 15.3 sources.
    fixture = (
        Path("tests/fixtures/industry_page_api_15.nut")
        .read_text()
        .replace("return ::invalid_ids.find(id) == null;", "return true;")
    )  # Array.find is a modern test-fixture convenience, absent in the native VM.
    clock = """
        class GSDate {
            static function GetCurrentDate(){return 712254;}
            static function GetYear(d){return 1950;}
            static function GetMonth(d){return 2;}
            static function GetDayOfMonth(d){return 1;}
            static function GetDate(y,m,d){return m==2?712254:712282;}
        }
    """
    return (
        Path("tests/fixtures/gamescript_api_15.nut").read_text()
        + fixture
        + clock
        + source
        + """
        local b=NoMutationBridge();
        for(local i=0;i<61;i++) b.Handle({protocol=1,type="economy_clock",request_id="clock"+i});
        b.Handle({after_id=null,limit=2,protocol=1,
            request_id="openttd15-qualification-001-anchor-inv-p001",type="industry_page"});
        if(::replies.len()!=62)throw "response missing";
        """
    )


def test_exact_tagged_vm_red_and_green(tmp_path):
    executable = os.environ.get("SQUIRREL_15_3_PROBE")
    if executable is None:
        pytest.skip("Set SQUIRREL_15_3_PROBE to the standalone tagged-source interpreter")
    source = qualification_bridge_source()
    fixed = "RawObservationBridge.Handle.call(this, request)"
    assert fixed in source
    for name, text, code in (
        ("old", source.replace(fixed, "base.Handle(request)"), 1),
        ("repaired", source, 0),
    ):
        path = tmp_path / (name + ".nut")
        path.write_text(legacy_probe_source(text))
        result = subprocess.run([executable, str(path)], capture_output=True, text=True, timeout=10)
        assert result.returncode == code
        if code:
            assert "the index 'base' does not exist" in result.stderr
        else:
            assert result.stdout.strip() == "PASS"


def test_native_language_authority_and_adapter_compatibility():
    root = Path("tests/reference/qualification_dispatch_15_3")
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    lexer = (root / "sqlexer.cpp").read_text()
    assert "ADD_KEYWORD(parent,TK_PARENT)" in lexer
    assert "ADD_KEYWORD(base," not in lexer
    assert "base.Handle" not in qualification_bridge_source()


@pytest.mark.parametrize("clock_calls", [0, 1, 61, 299])
def test_actual_composed_handler_keeps_non_clock_dispatch_alive(clock_calls):
    vm = vm_for()
    vm.execute(Path("tests/fixtures/industry_page_api_15.nut").read_text())
    vm.execute(f"""
        ::b <- NoMutationBridge();
        for(local i=0;i<{clock_calls};i++)
            b.Handle({{protocol=1,type="economy_clock",request_id="clock"+i}});
        b.Handle({{protocol=1,type="industry_page",request_id="anchor",after_id=null,limit=2}});
    """)
    assert len(vm.get_roottable()["replies"]) == clock_calls + 1
    assert any(
        "INDUSTRY_PAGE_READ request_id=anchor" in str(m) for m in vm.get_roottable()["markers"]
    )


@pytest.mark.parametrize("delay", [0, 1, 60, 120, 290])
def test_phase_entry_after_virtual_wait_has_fresh_request_budget(delay):
    async def run():
        wire = QualificationWire()
        original = wire.pace
        calls = 0

        async def pace(seconds):
            nonlocal calls
            calls += 1
            await original(seconds)
            if calls == 1:
                wire.virtual_time += delay

        setattr(wire, "pace", pace)
        owner = await wire.owner()
        original_query = wire.transport.industry_page
        seen = []

        async def query(request, world, **kwargs):
            seen.append((wire.virtual_time, kwargs["timeout"], owner._deadline))
            return await original_query(request, world, **kwargs)

        setattr(wire.transport, "industry_page", query)
        result = await collect(wire, owner)
        assert result.production.qualified_for_planning
        assert owner.anchor_session is not owner.final_session
        assert seen[0][0] >= delay
        assert all(timeout == min(5, deadline - now) for now, timeout, deadline in seen)
        assert owner.evidence.retries == owner.evidence.reconnects == 0
        assert wire.transport.pending_request_id is None
        assert owner.accounting is wire.accounting
        assert owner._deadline == 300
        assert owner.evidence.anchor.request_attempts > 0

    asyncio.run(run())


@pytest.mark.parametrize("delay", [300, 301, 600])
def test_expired_overall_attempt_cannot_be_resurrected_by_fresh_phase(delay):
    async def run():
        wire = QualificationWire()
        original = wire.pace

        async def pace(seconds):
            await original(seconds)
            wire.virtual_time += delay

        setattr(wire, "pace", pace)
        owner = await wire.owner()
        with pytest.raises(TimeoutError, match="operational deadline"):
            await collect(wire, owner)
        assert owner.phase is QualificationPhase.FAILED
        assert owner.anchor_session is None
        assert owner.result is None
        with pytest.raises(BridgeProtocolError, match="single-use"):
            await collect(wire, owner)

    asyncio.run(run())


def test_attempt_one_request_send_classification_and_no_response():
    rows = [json.loads(line) for line in (HISTORY / "transactions.jsonl").read_text().splitlines()]
    assert len(rows) == 62
    assert all(row["validated"] for row in rows[:-1])
    assert rows[-1]["delivery"] == "SENT"
    assert rows[-1]["request"]["type"] == "industry_page"
    assert rows[-1]["response"] is rows[-1]["receipt"] is rows[-1]["gamescript"] is None
    evidence = json.loads((HISTORY / "proof-evidence.json").read_text())
    assert evidence["status"] == "REAL_FAILED"
    assert evidence["source_integrity"] is True
    assert evidence["qualified_for_planning"] is False
    assert evidence["accounting"]["query_operations"] == 245


@pytest.mark.parametrize(
    "key,value",
    [
        ("clock_requests", 304),
        ("application_requests", 1072),
        ("response_bytes", 368080),
        ("query_operations", 9088),
        ("post_auth_frames", 9094),
    ],
)
def test_dispatch_repair_does_not_add_requests_or_frames(key, value):
    assert qualification_contract()["resources"][key] == value


@pytest.mark.parametrize(
    "category",
    [
        "clock",
        "anchor_structural",
        "anchor_lifetime",
        "final_structural",
        "final_lifetime",
        "production",
    ],
)
def test_phase_limits_remain_independent(category):
    limits = qualification_contract()["resources"]["phase_bounds"]
    expected = {
        "clock": (304, 82384, 2432),
        "anchor_structural": (96, 49152, 1024),
        "anchor_lifetime": (32, 7936, 256),
        "final_structural": (96, 49152, 1024),
        "final_lifetime": (32, 7936, 256),
        "production": (512, 171520, 4096),
    }
    assert tuple(limits[category].values()) == expected[category]


@pytest.mark.parametrize(
    "group",
    [
        "CONTEXT.md",
        "industry-production-real-attempt1",
        "industry-production-real-attempt2",
        "complete-raw-production-real-attempt1",
        "structural-world",
        "cargo",
        "inventory",
    ],
)
def test_protected_historical_authority_remains_exact(group):
    history = json.loads((HISTORY / "historical-integrity.json").read_text())
    rows = [r for r in history["entries"] if group in r["path"]]
    assert rows
    for row in rows:
        assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_new_lineage_requires_revision_two_attempt_two_and_runtime_predecessor():
    from app.simulation.openttd.proof.qualification_lineage import (
        capture_lineage,
        validate_historical_attempt,
    )

    directory = HISTORY.resolve().with_name(
        "openttd-15.3-two-rollover-qualification-real-prelaunch-v2"
    )
    value = json.loads((directory / "attempt-lineage.json").read_text())
    destination = directory.with_name(value["evidence_directory"])
    assert validate_historical_attempt(directory, destination).freeze_revision == 2
    assert value["attempt_id"] == "two-rollover-qualification-v2-native-attempt2"
    assert value["prelaunch_continuation_exception_used"] is False
    row = value["post_launch_predecessors"][0]
    assert row["classification"] == "RUNTIME" and row["post_launch_failure"]
    assert row["native_attempt_id"] == "two-rollover-qualification-v1-native-attempt1"
    assert row["terminal_error"] == "TransportTimeout: structural-world phase deadline expired"
    assert row["launches"] == row["connections"] == 1
    with pytest.raises(ValueError):
        capture_lineage(directory, 2, HISTORY)


def test_nested_predecessor_tamper_rejected_without_rewriting_original(tmp_path):
    import shutil

    from app.simulation.openttd.proof.qualification_lineage import read_attempt

    copied = tmp_path / HISTORY.name
    shutil.copytree(HISTORY, copied)
    # The historical absolute preparation authority remains in the original root.
    # Relocate only the copied record and regenerate its top-level/payload identities
    # through the controlled retainer before testing a nested mutation.
    from app.simulation.openttd.proof.harness import manifest
    from app.simulation.openttd.proof.qualification_lineage import _files, digest

    record = json.loads((copied / "proof-evidence.json").read_text())
    old = tmp_path / "old-freeze"
    old.mkdir()
    (old / "PRELAUNCH.json").write_text(
        json.dumps(dict(mode="two-rollover-qualification", prelaunch_revision=1))
    )
    record["preparation"] = str(old)
    (copied / "proof-evidence.json").write_text(json.dumps(record))
    modern = json.loads((copied / "proof-attempt.json").read_text())
    payload = digest(_files(copied, ("artifact-manifest.sha256", "proof-attempt.json")))
    modern.update(
        payload_digest=payload,
        evidence_manifest_digest=payload,
        attempt_id=f"two-rollover-qualification-v1-runtime-{payload[:16]}",
    )
    (copied / "proof-attempt.json").write_text(json.dumps(modern))
    (copied / "artifact-manifest.sha256").write_text(manifest(copied))
    assert read_attempt(copied).classification == "RUNTIME"
    (copied / "anchor/structural-session.json").write_text("{}")
    with pytest.raises(ValueError, match="payload digest"):
        read_attempt(copied)
