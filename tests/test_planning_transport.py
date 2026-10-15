"""P03 transport/receipt proof without starting OpenTTD."""

import hashlib
import re
from pathlib import Path

import pytest
from test_planning import tiny_plan, tiny_scenario

from app.planning.domain import ExecutionPlan, Mode, PlanningScenario
from app.planning.serialization import plan_hash, world_manifest_hash
from app.planning.setup_evidence import (
    SetupEvidenceError,
    SetupFailureCode,
    SetupLogCapture,
    inspect_setup_log,
    parse_setup_evidence,
)
from app.planning.transport import (
    PlanTransportError,
    materialize_plan,
    transport_bytes,
    verify_staged_package,
    verify_world_source,
)
from app.planning.validation import PlanningFailureCode, PlanningValidationError


def _world_bound(tmp_path: Path) -> tuple[ExecutionPlan, PlanningScenario, Path]:
    world = tmp_path / "world.sav"
    world.write_bytes(b"prepared world")
    scenario = tiny_scenario()
    manifest = scenario.world_manifest.model_copy(
        update={"source_digest": hashlib.sha256(world.read_bytes()).hexdigest()}
    )
    fingerprint = world_manifest_hash(manifest)
    scenario = scenario.model_copy(
        update={"world_manifest": manifest, "world_fingerprint": fingerprint}
    )
    plan = tiny_plan()
    declaration = plan.validation.model_copy(update={"validated_world_fingerprint": fingerprint})
    plan = plan.model_copy(update={"world_fingerprint": fingerprint, "validation": declaration})
    return plan, scenario, world


def _marker(mode: Mode = Mode.ROAD, *, status: str = "accepted", code: str = "NONE") -> str:
    plan = tiny_plan(mode)
    return "dbg: [script] [0] [I] " + "|".join(
        (
            "P03_EXECUTOR_AI",
            "P03_SETUP_V1",
            "1",
            "1",
            status,
            code,
            plan_hash(plan),
            plan.world_fingerprint,
            tiny_scenario().world_manifest.source_digest,
            plan.scenario_id,
            plan.scenario_version,
            plan.routes[0].route_id if status == "accepted" else "",
            plan.fleet.groups[0].fleet_group_id if status == "accepted" else "",
            ",".join(action.construction_id for action in plan.infrastructure.actions)
            if status == "accepted"
            else "",
        )
    )


@pytest.mark.parametrize("mode", [Mode.ROAD, Mode.RAIL])
def test_deterministic_data_transport(mode: Mode) -> None:
    scenario, plan = tiny_scenario(), tiny_plan(mode)
    before = plan.model_dump_json()
    first = transport_bytes(plan, scenario, plan_hash(plan))
    second = transport_bytes(plan, scenario, plan_hash(plan))
    assert first == second
    assert plan_hash(plan).encode() in first
    assert scenario.world_fingerprint.encode() in first
    assert b"::P03_TRANSPORT <-" in first
    assert b'"route_ids"' in first
    assert plan.model_dump_json() == before


def test_semantic_change_changes_module() -> None:
    plan = tiny_plan()
    changed = plan.model_copy(update={"plan_id": "changed"})
    assert transport_bytes(plan, tiny_scenario(), plan_hash(plan)) != transport_bytes(
        changed, tiny_scenario(), plan_hash(changed)
    )


def test_unknown_version_and_script_text_rejected() -> None:
    plan, scenario = tiny_plan(), tiny_scenario()
    future = plan.model_copy(update={"schema_version": 2})
    with pytest.raises(PlanningValidationError) as error:
        transport_bytes(future, scenario, plan_hash(future))
    assert error.value.code is PlanningFailureCode.UNSUPPORTED_PLAN_VERSION
    injected = plan.model_copy(update={"plan_id": 'bad"; system("evil")'})
    with pytest.raises(PlanningValidationError):
        transport_bytes(injected, scenario, plan_hash(injected))


def test_invalid_plan_rejected_before_materialization(tmp_path: Path) -> None:
    workspace = tmp_path / "owned"
    workspace.mkdir(mode=0o700)
    plan, scenario, world = _world_bound(tmp_path)
    with pytest.raises(PlanningValidationError):
        materialize_plan(plan, scenario, "0" * 64, workspace, world)
    assert list(workspace.iterdir()) == []


def test_workspace_is_fresh_private_and_not_symlink(tmp_path: Path) -> None:
    plan, scenario, world = _world_bound(tmp_path)
    workspace = tmp_path / "owned"
    workspace.mkdir(mode=0o700)
    output = materialize_plan(plan, scenario, plan_hash(plan), workspace, world)
    assert output.module_path.read_bytes() == transport_bytes(plan, scenario, plan_hash(plan))
    assert output.artifact_path.is_file()
    verify_staged_package(output)
    with pytest.raises(PlanTransportError):
        materialize_plan(plan, scenario, plan_hash(plan), workspace, world)
    link = tmp_path / "link"
    link.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(PlanTransportError):
        materialize_plan(plan, scenario, plan_hash(plan), link, world)


def test_world_source_digest_and_package_tamper(tmp_path: Path) -> None:
    plan, scenario, world = _world_bound(tmp_path)
    verify_world_source(scenario, world)
    world.write_bytes(b"other world")
    with pytest.raises(PlanTransportError):
        verify_world_source(scenario, world)
    workspace = tmp_path / "owned"
    workspace.mkdir(mode=0o700)
    world.write_bytes(b"prepared world")
    output = materialize_plan(plan, scenario, plan_hash(plan), workspace, world)
    original_module = output.module_path.read_bytes()
    output.module_path.write_bytes(b"tampered")
    with pytest.raises(PlanTransportError):
        verify_staged_package(output)
    output.module_path.write_bytes(original_module)
    output.artifact_path.write_bytes(b"tampered")
    with pytest.raises(PlanTransportError):
        verify_staged_package(output)


def test_evidence_binds_exact_plan_world_and_ids() -> None:
    for mode in (Mode.ROAD, Mode.RAIL):
        evidence = parse_setup_evidence(_marker(mode), tiny_plan(mode), tiny_scenario())
        assert evidence.status == "accepted"
        assert evidence.code is SetupFailureCode.NONE
        with pytest.raises(SetupEvidenceError):
            parse_setup_evidence(
                _marker(mode).replace("tiny", "wrong"), tiny_plan(mode), tiny_scenario()
            )


def test_evidence_rejects_duplicates_malformed_and_hash_mismatch() -> None:
    marker = _marker()
    plan, scenario = tiny_plan(), tiny_scenario()
    for log in (
        marker + "\n" + marker,
        marker + "\n" + _marker(status="failed", code="WORLD_RESOLUTION_FAILURE"),
        marker.replace(plan_hash(plan), "0" * 64),
        marker + "|extra",
        marker.replace("P03_SETUP_V1|1|1", "P03_SETUP_V1|2|1"),
        marker.replace("P03_SETUP_V1|1|1", "P03_SETUP_V1|1|2"),
        marker.replace("P03_EXECUTOR_AI|", "UNTRUSTED_AI|"),
    ):
        with pytest.raises(SetupEvidenceError):
            parse_setup_evidence(log, plan, scenario)


def test_typed_failure_preserved() -> None:
    marker = _marker(status="failed", code="WORLD_RESOLUTION_FAILURE")
    evidence = parse_setup_evidence(marker, tiny_plan(), tiny_scenario())
    assert evidence.status == "failed"
    assert evidence.code is SetupFailureCode.WORLD_RESOLUTION_FAILURE


def test_world_resolution_failure_retains_exact_site_and_predicate() -> None:
    plan = tiny_plan()
    digest = plan_hash(plan)
    log = (
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_STARTED|"
        f"{digest}\n"
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_WORLD_RESOLUTION_V1|"
        f"{digest}|INDUSTRY_LOCATION_MISMATCH|origin|industry|0|168|70|18089\n"
        + _marker(status="failed", code="WORLD_RESOLUTION_FAILURE")
    )

    trace = inspect_setup_log(log, digest)

    assert len(trace.world_resolution_failures) == 1
    failure = trace.world_resolution_failures[0]
    assert failure.instance_id == 0
    assert failure.reason == "INDUSTRY_LOCATION_MISMATCH"
    assert failure.location_id == "origin"
    assert failure.kind == "industry"
    assert failure.expected_id == 0
    assert (failure.expected_x, failure.expected_y) == (168, 70)
    assert failure.actual == "18089"


def test_world_resolution_diagnostics_reject_unknown_or_wrong_plan_markers() -> None:
    digest = plan_hash(tiny_plan())
    base = (
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_WORLD_RESOLUTION_V1|"
        f"{digest}|INDUSTRY_INVALID|origin|industry|0|168|70|false\n"
    )
    assert len(inspect_setup_log(base, digest).world_resolution_failures) == 1
    assert not inspect_setup_log(
        base.replace("INDUSTRY_INVALID", "UNBOUNDED_UNKNOWN_REASON"), digest
    ).world_resolution_failures
    assert not inspect_setup_log(base.replace(digest, "0" * 64), digest).world_resolution_failures


def test_lifecycle_markers_and_partial_line_handling() -> None:
    marker = _marker()
    capture = SetupLogCapture()
    capture.feed(b"dbg: [console] Executing cmdline: 'stop_ai 3'\n")
    capture.feed(b"AI stopped, company deleted.\n")
    capture.feed(b"dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'\n")
    capture.feed(b"__P03_UNPAUSE_ACK__\n")
    capture.feed(b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none\n")
    capture.feed(
        b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|PLAN_FOUND|" + b"a" * 64 + b"\n"
    )
    capture.feed(
        b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_STARTED|"
        + b"a" * 64
        + b"\n"
    )
    capture.feed(marker[:-1].encode())
    assert capture.trace.terminal_count == 0
    capture.feed(marker[-1:].encode() + b"\n")
    assert capture.trace.old_ai_stopped
    assert capture.trace.ai_selected
    assert capture.trace.unpause_acknowledged
    assert capture.trace.start_entered
    assert capture.trace.plan_found
    assert capture.trace.world_validation_started
    assert capture.trace.terminal_count == 1
    assert parse_setup_evidence(capture.text, tiny_plan(), tiny_scenario()).status == "accepted"


def test_unrelated_log_ignored_and_timeout_reports_last_stage() -> None:
    log = (
        "dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'\n"
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none\n"
        "unrelated AI: " + _marker() + "\n"
    )
    assert inspect_setup_log(log).last_stage == "START_ENTERED"
    with pytest.raises(SetupEvidenceError, match="last stage: START_ENTERED"):
        parse_setup_evidence(log, tiny_plan(), tiny_scenario())


def test_script_error_is_reported_as_last_proven_stage() -> None:
    log = (
        "dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'\n"
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none\n"
        "dbg: [script] [0] [E] Squirrel runtime error\n"
    )
    assert inspect_setup_log(log).script_error_count == 1
    with pytest.raises(SetupEvidenceError, match="last stage: SCRIPT_ERROR"):
        parse_setup_evidence(log, tiny_plan(), tiny_scenario())


def test_squirrel_crash_lines_are_grouped_by_instance_and_stage() -> None:
    log = (
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_STARTED|"
        + plan_hash(tiny_plan())
        + "\n"
        "dbg: [script] [0] [S] Your script made an error: the index 'getroottable' "
        "does not exist\n"
        "dbg: [script] [0] [S] *FUNCTION [Start()] P03ThinExecutor/main.nut line [40]\n"
        "dbg: [script] [0] [S] [error] \"the index 'format' does not exist\"\n"
        "dbg: [script] [1] [I] P03_EXECUTOR_AI|P03_STAGE_V1|PLAN_DECODED|"
        + plan_hash(tiny_plan())
        + "\n"
        "dbg: [script] [1] [S] Your script made an error: the index 'getroottable' "
        "does not exist\n"
        "dbg: [script] [1] [S] [error] \"the index 'format' does not exist\"\n"
    )
    trace = inspect_setup_log(log, plan_hash(tiny_plan()))
    assert trace.script_error_count == 2
    assert trace.last_stage == "SCRIPT_ERROR"
    assert [
        (crash.instance_id, crash.last_stage, crash.detail) for crash in trace.script_crashes
    ] == [
        (0, "WORLD_VALIDATION_STARTED", "the index 'format' does not exist"),
        (1, "PLAN_DECODED", "the index 'format' does not exist"),
    ]
    assert trace.script_crashes[0].stack == (
        "*FUNCTION [Start()] P03ThinExecutor/main.nut line [40]",
    )


def test_missing_transport_after_start_is_typed_failure() -> None:
    log = (
        "dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none\n"
        "dbg: [script] [0] [E] "
        "P03_EXECUTOR_AI|P03_FATAL_V1|EXECUTOR_SETUP_FAILURE|PLAN_NOT_FOUND\n"
    )
    with pytest.raises(SetupEvidenceError) as error:
        parse_setup_evidence(log, tiny_plan(), tiny_scenario())
    assert error.value.code is SetupFailureCode.EXECUTOR_SETUP_FAILURE


def test_plan_found_diagnostic_must_match_expected_hash() -> None:
    capture = SetupLogCapture(plan_hash(tiny_plan()))
    capture.feed(
        b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|PLAN_FOUND|" + b"0" * 64 + b"\n"
    )
    assert not capture.trace.plan_found
    assert capture.trace.last_stage == "PLAN_HASH_MISMATCH"


def test_thin_ai_avoids_unavailable_squirrel_globals() -> None:
    source = (Path(__file__).parents[1] / "app/planning/thin_ai/main.nut").read_text()
    assert re.search(r"\b(?:getroottable|format)\s*\(", source) is None
    assert 'require("plan.nut")' in source
    assert "data = ::P03_TRANSPORT" in source
    assert '_stage("PLAN_DECODED", data.plan_hash)' in source
    assert '_stage("WORLD_VALIDATION_SUCCEEDED", data.plan_hash)' in source
    assert "P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|" in source
    assert "AIIndustryList()" in source
    assert "AIIndustry.GetLocation(observed_id)" in source
