"""Controlled preparation lifecycle and P07 artifact linking, with zero native launches."""

from hashlib import sha256

import pytest

from app.planning.preparation.failures import PreparationError
from app.planning.preparation.lifecycle import PreparationWorldDescriptor, prepare_with_runtime
from tests.test_planning_preparation import corridor_request, corridor_world
from tests.test_preparation_probe import frames


class FakeRuntime:
    def __init__(self, world, *, corrupt=False, mutate_source=False, start_error=False):
        self.world = world
        self.corrupt = corrupt
        self.mutate_source = mutate_source
        self.start_error = start_error
        self.closed = False
        self.staged_probe = False

    def start(self, workspace, source_save, config):
        self.workspace = workspace
        self.source_save = source_save
        self.staged_probe = (workspace / "game" / "P08Preparation" / "main.nut").is_file()
        if self.start_error:
            raise RuntimeError("fake startup failure")
        self.save = workspace / "prepared.sav"
        self.save.write_bytes(b"prepared save")
        return self

    def collect(self):
        rows = frames(self.world)
        if self.corrupt:
            rows.pop()
        if self.mutate_source:
            self.source_save.chmod(0o644)
            self.source_save.write_bytes(b"changed save")
        return iter(rows)

    def prepared_save(self):
        return self.save

    def close(self):
        self.closed = True


def run_fixture(tmp_path, **kwargs):
    source = tmp_path / "source.sav"
    source.write_bytes(b"source save")
    digest = sha256(source.read_bytes()).hexdigest()
    req = corridor_request().model_copy(update={"expected_source_save_digest": digest})
    world = corridor_world().model_copy(
        update={
            "source_save_digest": digest,
            "prepared_save_digest": sha256(b"prepared save").hexdigest(),
        }
    )
    runtime = FakeRuntime(world, **kwargs)
    descriptor = PreparationWorldDescriptor(profile=world.profile, seed=42, company_id=0)
    return source, req, world, runtime, descriptor


def test_controlled_lifecycle_stages_cleans_and_retains_p07_compatible_artifacts(tmp_path):
    from app.experiments.plan_evaluation import PlanEvaluationInput, retain_inputs
    from app.planning.canonical import canonical_bytes
    from app.planning.optimizer import optimize_candidate_network

    source, req, world, runtime, descriptor = run_fixture(tmp_path)
    result = prepare_with_runtime(
        req,
        source,
        descriptor,
        runtime,
        workspace_root=tmp_path / "work",
        output_directory=tmp_path / "accepted",
    )
    assert runtime.closed and runtime.staged_probe
    assert not runtime.workspace.exists()
    assert result.bundle.snapshot == world
    assert result.bundle.manifest.source_digest == sha256(b"prepared save").hexdigest()
    assert result.artifacts.scenario_hash == result.bundle.provenance.scenario_hash
    refs = {a.reference: a.sha256 for a in result.artifacts.artifacts}
    assert refs["p08-scenario.json"] == sha256(canonical_bytes(result.bundle.scenario)).hexdigest()
    evaluation = PlanEvaluationInput(
        scenario=result.bundle.scenario,
        plan=optimize_candidate_network(result.bundle.scenario).plan,
        bindings=result.bundle.bindings,
    )
    run_dir = tmp_path / "p07-run"
    run_dir.mkdir()
    p07 = retain_inputs(evaluation, run_dir)
    assert p07.scenario_hash == result.artifacts.scenario_hash
    assert p07.manifest_hash == result.artifacts.manifest_hash
    assert refs["p08-provenance.json"] == result.bundle.provenance_hash


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"corrupt": True}, "EXTRACTION_INCOMPLETE"),
        ({"mutate_source": True}, "WORLD_CHANGED_DURING_PREPARATION"),
        ({"start_error": True}, "EXTRACTION_INCOMPLETE"),
    ],
)
def test_failure_cleans_and_never_publishes_partial_preparation(tmp_path, kwargs, code):
    source, req, _, runtime, descriptor = run_fixture(tmp_path, **kwargs)
    with pytest.raises(PreparationError, match=code):
        prepare_with_runtime(
            req,
            source,
            descriptor,
            runtime,
            workspace_root=tmp_path / "work",
            output_directory=tmp_path / "accepted",
        )
    assert runtime.closed
    assert not runtime.workspace.exists()
    assert not (tmp_path / "accepted").exists()


def test_cleanup_failure_does_not_publish_accepted_artifacts(tmp_path):
    source, req, _, runtime, descriptor = run_fixture(tmp_path)

    def fail_close():
        runtime.closed = True
        raise RuntimeError("controlled cleanup failure")

    runtime.close = fail_close
    with pytest.raises(PreparationError, match="EXTRACTION_INCOMPLETE"):
        prepare_with_runtime(
            req,
            source,
            descriptor,
            runtime,
            workspace_root=tmp_path / "work",
            output_directory=tmp_path / "accepted",
        )
    assert runtime.closed
    assert not runtime.workspace.exists()
    assert not (tmp_path / "accepted").exists()


def test_cleanup_world_mutation_is_detected_before_publication(tmp_path):
    source, req, _, runtime, descriptor = run_fixture(tmp_path)

    def mutate_close():
        runtime.closed = True
        runtime.save.write_bytes(b"changed prepared save")

    runtime.close = mutate_close
    with pytest.raises(PreparationError, match="WORLD_CHANGED_DURING_PREPARATION"):
        prepare_with_runtime(
            req,
            source,
            descriptor,
            runtime,
            workspace_root=tmp_path / "work",
            output_directory=tmp_path / "accepted",
        )
    assert not (tmp_path / "accepted").exists()


def test_missing_source_is_a_typed_bounded_lifecycle_failure(tmp_path):
    source, req, _, runtime, descriptor = run_fixture(tmp_path)
    with pytest.raises(PreparationError, match="EXTRACTION_INCOMPLETE"):
        prepare_with_runtime(
            req,
            tmp_path / "missing.sav",
            descriptor,
            runtime,
            workspace_root=tmp_path / "work",
            output_directory=tmp_path / "accepted",
        )
    assert not (tmp_path / "accepted").exists()
