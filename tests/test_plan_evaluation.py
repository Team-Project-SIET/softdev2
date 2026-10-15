"""P07 attribution gates use actual P06 Squirrel evidence, without OpenTTD."""

import hashlib
from pathlib import Path

import pytest

from app.experiments.model import ExperimentRunRecord
from app.experiments.plan_evaluation import PlanEvaluationInput, accept_execution, retain_inputs
from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.optimizer import optimize_candidate_network
from tests.test_planning_execution import executable_scenario, run_executor


def request():
    plan, scenario, bindings = executable_scenario()
    return PlanEvaluationInput(
        scenario=scenario,
        plan=plan,
        bindings=bindings,
        estimated=optimize_candidate_network(scenario).metrics,
    )


def test_successful_execution_gate():
    value = request()
    log, _ = run_executor(value.plan, value.scenario, value.bindings)
    receipt = accept_execution(value, log)
    assert receipt.plan_hash == plan_hash(value.plan)
    assert receipt.result == "success"


def test_partial_execution_never_scores():
    value = request()
    log, _ = run_executor(value.plan, value.scenario, value.bindings, fail="road_station")
    with pytest.raises(ValueError):
        accept_execution(value, log)


def test_artifacts_are_content_identified_and_replay_exact(tmp_path: Path):
    value = request()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = retain_inputs(value, a)
    second = retain_inputs(value, b)
    assert first == second
    assert (a / "plan.json").read_bytes() == canonical_bytes(value.plan)
    assert first.plan_hash == hashlib.sha256((a / "plan.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("field", ["plan_hash", "world_fingerprint"])
def test_wrong_receipt_identity_rejected(field):
    value = request()
    log, _ = run_executor(value.plan, value.scenario, value.bindings)
    import json

    lines = log.splitlines()
    for i, line in enumerate(lines):
        prefix, sep, raw = line.partition("P06_EXECUTION_V1|")
        if sep:
            data = json.loads(raw)
            data[field] = "f" * 64
            lines[i] = prefix + sep + json.dumps(data)
    with pytest.raises(ValueError):
        accept_execution(value, "\n".join(lines))


def test_invalid_input_rejected_before_launch():
    value = request()
    with pytest.raises(ValueError):
        PlanEvaluationInput(
            scenario=value.scenario,
            bindings=value.bindings,
            plan=value.plan.model_copy(update={"world_fingerprint": "f" * 64}),
        )


def plan_world(value, path):
    from app.planning.canonical import world_manifest_hash

    data = b"controlled prepared world"
    path.write_bytes(data)
    manifest = value.scenario.world_manifest.model_copy(
        update={"source_digest": hashlib.sha256(data).hexdigest()}
    )
    fingerprint = world_manifest_hash(manifest)
    locations = tuple(
        location.model_copy(
            update={
                "world_reference": location.world_reference.model_copy(
                    update={"world_fingerprint": fingerprint}
                )
            }
        )
        if location.world_reference
        else location
        for location in value.scenario.locations
    )
    scenario = value.scenario.model_copy(
        update={
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "locations": locations,
        }
    )
    result = optimize_candidate_network(scenario)
    return PlanEvaluationInput(
        scenario=scenario, plan=result.plan, bindings=value.bindings, estimated=result.metrics
    )


class ControlledPlanRunner:
    def __init__(
        self,
        value,
        world,
        config,
        options,
        root,
        processor_factory,
        cancellation,
        *,
        fail=None,
        wrong=None,
    ):
        self.value = value
        self.fail = fail
        self.wrong = wrong
        from types import SimpleNamespace

        self.plan_setup = SimpleNamespace(observed_start_day=100)

    def run(self, config, *, run_id, artifact_dir):
        import gzip
        import json
        from datetime import date

        from app.experiments.domain import (
            LiveExecutionSummary,
            Metric,
            SimulationResult,
            TelemetryStatus,
        )
        from app.experiments.plan_evaluation import retain_bytes
        from app.planning.execution_evidence import parse_execution_evidence

        log, _ = run_executor(
            self.value.plan, self.value.scenario, self.value.bindings, fail=self.fail
        )
        if self.wrong:
            log = log.replace(plan_hash(self.value.plan), "e" * 64)
        retain_bytes(log.encode(), artifact_dir, "execution-evidence.log")
        if not self.wrong:
            receipt = parse_execution_evidence(
                log, self.value.plan, self.value.scenario, self.value.bindings
            )
            retain_bytes(canonical_bytes(receipt), artifact_dir, "execution-receipt.json")
        (artifact_dir / "final.sav").write_bytes(b"controlled final")
        parsed = {
            "configuration": config.model_dump(mode="json"),
            "chunks": {
                "PLYR": {
                    "0": {
                        "money": 123,
                        "current_loan": 100,
                        "cur_economy": [{"income": 4, "expenses": -5, "delivered_cargo": [2, 3]}],
                    }
                }
            },
        }
        with gzip.open(artifact_dir / "parsed.gz", "wt") as f:
            json.dump(parsed, f)
        summary = LiveExecutionSummary(
            telemetry_status=TelemetryStatus.INCOMPLETE,
            requested_target_day=100 + config.duration_days,
            actual_final_day=100 + config.duration_days,
            raw_save_reference=str(artifact_dir / "final.sav"),
            raw_save_sha256=hashlib.sha256(b"controlled final").hexdigest(),
            parsed_artifact_reference=str(artifact_dir / "parsed.gz"),
            parsed_artifact_sha256=hashlib.sha256(
                (artifact_dir / "parsed.gz").read_bytes()
            ).hexdigest(),
        )
        return SimulationResult(
            simulation_date=date(1950, 1, 1),
            savegame_version=213,
            metrics=(Metric(name="company_money", value=123, unit="GBP"),),
            raw_artifact_reference=str(artifact_dir / "parsed.gz"),
            live_summary=summary,
        )


def test_successful_plan_run_and_reload(session_factory, tmp_path):
    from sqlalchemy import select

    from app.experiments.domain import RunStatus
    from app.experiments.model import PlanningStrategyRecord
    from app.experiments.service import ExperimentService

    value = plan_world(request(), tmp_path / "world.sav")
    result = ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=ControlledPlanRunner,
    )
    assert result.outcome.status == RunStatus.SUCCEEDED
    assert result.realized.plan_hash == plan_hash(value.plan)
    assert result.realized.values[0].source == "public_save"
    assert result.realized.observations.status == "incomplete"
    assert not any("profit" in x.name for x in result.realized.values)
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.outcome.run_id)
        assert row.strategy is None
        assert row.plan_evaluation.provenance == result.provenance.model_dump(mode="json")
        assert session.scalars(select(PlanningStrategyRecord)).all() == []


@pytest.mark.parametrize("kwargs", [{"fail": "road_station"}, {"wrong": "hash"}])
def test_failed_setup_with_final_save_is_not_scored(session_factory, tmp_path, kwargs):
    from functools import partial

    from app.experiments.domain import RunStatus
    from app.experiments.service import ExperimentService

    value = plan_world(request(), tmp_path / "world.sav")
    result = ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=partial(ControlledPlanRunner, **kwargs),
    )
    assert result.outcome.status == RunStatus.FAILED
    assert result.realized is None
    assert not list((tmp_path / "runs").rglob("realized.json"))


def test_terminal_persistence_failure_recovery_preserves_plan(session_factory, tmp_path):
    from app.experiments.outcome_recovery import OutcomeRecoveryService, RecoveryStatus
    from app.experiments.repository import ExperimentRepository
    from app.experiments.service import ExperimentService

    class FailingCommit(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            raise RuntimeError("controlled terminal write failure")

    value = plan_world(request(), tmp_path / "world.sav")
    root = tmp_path / "runs"
    result = ExperimentService(session_factory, repository=FailingCommit()).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=root,
        runner_factory=ControlledPlanRunner,
    )
    assert result.outcome.terminal_persistence_failed
    assert result.provenance.realized is not None
    recovery = OutcomeRecoveryService(session_factory).recover(
        root, root / result.outcome.live_summary.outcome_manifest_reference
    )
    assert recovery.status == RecoveryStatus.RECOVERED
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.outcome.run_id)
        assert row.plan_evaluation.plan_hash == plan_hash(value.plan)
        assert row.plan_evaluation.provenance == result.provenance.model_dump(mode="json")


@pytest.mark.parametrize(
    "code",
    [
        "observer_lost",
        "timeout",
        "finalization_failure",
        "persistence_failure",
        "unexpected_shutdown",
    ],
)
def test_runtime_failure_retains_attributed_setup_and_coverage(session_factory, tmp_path, code):
    from app.experiments.domain import (
        ExecutionFailure,
        ExecutionFailureCode,
        SimulationExecutionError,
    )
    from app.experiments.service import ExperimentService

    class FailedRuntime(ControlledPlanRunner):
        def run(self, config, *, run_id, artifact_dir):
            result = super().run(config, run_id=run_id, artifact_dir=artifact_dir)
            summary = result.live_summary.model_copy(
                update={"actual_final_day": None, "last_observed_day": 102}
            )
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=ExecutionFailureCode(code),
                    message=code.replace("_", " "),
                    live_summary=summary,
                )
            )

    value = plan_world(request(), tmp_path / "world.sav")
    root = tmp_path / "runs"
    result = ExperimentService(session_factory).run_plan(
        value, world_source=tmp_path / "world.sav", artifact_dir=root, runner_factory=FailedRuntime
    )
    assert result.outcome.failure_code == code
    assert result.realized is None
    assert result.provenance.receipt is not None
    assert result.provenance.telemetry is not None
    import json

    evidence = json.loads(
        (root / f"run-{result.outcome.run_id}" / result.provenance.evaluation.reference).read_text()
    )
    assert evidence["plan_hash"] == plan_hash(value.plan)
    assert evidence["observed_start_day"] == 100
    assert evidence["observed_terminal_day"] == 102
    assert not evidence["coverage_complete"]


def test_no_optimizer_call_after_launch_and_replay(session_factory, tmp_path, monkeypatch):
    import app.planning.optimizer as optimizer
    from app.experiments.service import ExperimentService

    value = plan_world(request(), tmp_path / "world.sav")

    class FrozenRunner(ControlledPlanRunner):
        def run(self, *args, **kwargs):
            def forbidden(*args, **kwargs):
                raise AssertionError("optimizer invoked after launch")

            monkeypatch.setattr(optimizer, "optimize_candidate_network", forbidden)
            return super().run(*args, **kwargs)

    service = ExperimentService(session_factory)
    before = canonical_bytes(value.scenario)
    first = service.run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=FrozenRunner,
    )
    second = service.run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=FrozenRunner,
    )
    assert first.outcome.simulation is not None and second.outcome.simulation is not None
    assert first.plan_hash == second.plan_hash
    assert first.provenance.input_artifact == second.provenance.input_artifact
    assert canonical_bytes(value.scenario) == before


def test_corrupt_final_parser_evidence_preserves_receipt_but_no_metrics(session_factory, tmp_path):
    from app.experiments.domain import ExecutionFailureCode
    from app.experiments.service import ExperimentService

    class CorruptParser(ControlledPlanRunner):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            (kwargs["artifact_dir"] / "parsed.gz").write_bytes(b"corrupt")
            return result

    value = plan_world(request(), tmp_path / "world.sav")
    result = ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=CorruptParser,
    )
    assert result.outcome.failure_code == ExecutionFailureCode.FINALIZATION_FAILURE
    assert result.realized is None
    assert result.provenance.evaluation is not None and result.provenance.receipt is not None
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.outcome.run_id)
        assert row.plan_evaluation.provenance == result.provenance.model_dump(mode="json")


def test_failed_receipt_has_partial_failure_identity(session_factory, tmp_path):
    from functools import partial

    from app.experiments.service import ExperimentService

    value = plan_world(request(), tmp_path / "world.sav")
    result = ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=partial(ControlledPlanRunner, fail="purchase"),
    )
    assert result.outcome.failure_code == "partial_execution"
    assert result.realized is None
    assert result.provenance.receipt is not None


def test_recovery_rejects_replaced_plan_artifact(session_factory, tmp_path):
    from app.experiments.outcome_recovery import OutcomeRecoveryService, RecoveryStatus
    from app.experiments.service import ExperimentService

    value = plan_world(request(), tmp_path / "world.sav")
    root = tmp_path / "runs"
    result = ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=root,
        runner_factory=ControlledPlanRunner,
    )
    path = root / f"run-{result.outcome.run_id}" / "plan-input.json"
    path.chmod(0o600)
    path.write_bytes(b"{}")
    assert (
        OutcomeRecoveryService(session_factory)
        .recover(root, root / result.outcome.live_summary.outcome_manifest_reference)
        .status
        == RecoveryStatus.INVALID_MANIFEST
    )


def test_observation_window_excludes_setup_and_detects_missing_days():
    import json

    from app.experiments.plan_artifacts import observation_window

    rows = [{"kind": "date", "company_id": None, "game_day": day} for day in (99, 100, 102)]
    rows += [
        {"kind": kind, "company_id": 0, "game_day": 100}
        for kind in ("company_info", "company_economy", "company_stats")
    ]
    count, complete = observation_window(json.dumps(rows).encode(), 100, 102)
    assert count == 5 and not complete
    rows.append({"kind": "date", "company_id": None, "game_day": 101})
    assert observation_window(json.dumps(rows).encode(), 100, 102) == (6, True)


def test_prelaunch_save_mismatch_creates_no_run(session_factory, tmp_path):
    from sqlalchemy import select

    from app.experiments.service import ExperimentService

    value = request()
    wrong = tmp_path / "world.sav"
    wrong.write_bytes(b"wrong")
    with pytest.raises(ValueError):
        ExperimentService(session_factory).run_plan(
            value,
            world_source=wrong,
            artifact_dir=tmp_path / "runs",
            runner_factory=ControlledPlanRunner,
        )
    with session_factory() as session:
        assert session.scalars(select(ExperimentRunRecord)).all() == []
    assert not (tmp_path / "runs").exists()
