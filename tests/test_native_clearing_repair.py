"""Remaining Codex-confirmed D2 Native Clearing defects (B1/B3/B4/B5/B6).

Each test pins ONE defect with its smallest runnable counterexample and uses
the controlled seams of the adversarial suite: a fresh real candidate per
Popen attempt plus a Popen interception boundary that creates no process.
"""

import asyncio
import dataclasses
import json
import unittest.mock as mock
from importlib.metadata import PackagePath
from pathlib import Path

import pytest
from test_terrain_clearing_adversarial import (
    _TEST_OPERATOR_PUBLIC,
    _TEST_OPERATOR_SEED,
    synthetic_attempt,
)

import app.simulation.openttd.proof.terrain_clearing as terrain_clearing
from app.simulation.openttd.proof import native as native_module
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.proof.harness import manifest, sha256, write_json
from app.simulation.openttd.proof.terrain_clearing import (
    ClearingNativeBackend,
    launch_critical_identity,
    prepare_candidate,
)


@pytest.fixture(autouse=True)
def _synthetic_operator_anchor():
    """Every boundary and replay in this module verifies under the test anchor."""
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _TEST_OPERATOR_PUBLIC.hex()
    try:
        yield
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved


def _minted_grant(prepared):
    """Issue one separately minted launch grant against the staged candidate."""
    directory = prepared.directory
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    record = operator_authorization.sign_authorization_record(
        operator_authorization.authorization_payload(metadata, seal),
        _TEST_OPERATOR_SEED.hex(),
    )
    operator_authorization.write_authorization_record(directory, record)
    return operator_authorization.LaunchGrant(
        directory=Path(directory).resolve(),
        prelaunch_sha256=seal,
        authorization_sha256=operator_authorization.record_digest(directory),
        operator_key_identity=operator_authorization.operator_key_identity(
            _TEST_OPERATOR_PUBLIC.hex()
        ),
        record=record,
        launch_identity=launch_critical_identity(prepared, metadata),
    )


def _write_claim(prepared, grant, *, launches_allowed=1, retries=0, consumed=True):
    """The retained one-shot claim exactly as the launch ceremony writes it."""
    write_json(
        prepared.directory / "CLAIM.json",
        dict(
            prelaunch_digest=grant.prelaunch_sha256,
            consumed=consumed,
            launches_allowed=launches_allowed,
            retries=retries,
            authorization_schema=operator_authorization.CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
            authorization_sha256=grant.authorization_sha256,
            operator_key_identity=grant.operator_key_identity,
        ),
    )


class PopenIntercept:
    """The process seam: record the launch request and create no process."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        raise RuntimeError("Popen intercepted; no process created")


async def _attempt_launch(prepared, grant, *, intercept):
    backend = ClearingNativeBackend(authorized_one_launch=True)
    try:
        await backend.launch(prepared, authorization=grant)
        return None
    except RuntimeError as error:
        if "Popen intercepted" not in str(error):
            raise
        return None
    except operator_authorization.ClearingAuthorizationError as error:
        return error


# --- B1: candidate-wide atomic launch consumption ---------------------------


def test_second_grant_on_second_backend_instance_cannot_reach_the_seam(tmp_path):
    """B1: two minted grants, two backend instances — only one may reach Popen."""
    prepared = prepare_candidate(tmp_path / "candidate")
    grant_a = _minted_grant(prepared)
    grant_b = _minted_grant(prepared)
    _write_claim(prepared, grant_a)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        assert asyncio.run(_attempt_launch(prepared, grant_a, intercept=intercept)) is None
        obstruction = asyncio.run(_attempt_launch(prepared, grant_b, intercept=intercept))
    assert obstruction is not None, "a second grant reached the Popen seam"
    assert "consumed" in str(obstruction), str(obstruction)
    assert len(intercept.calls) == 1, "the seam was reached for two grants"


def test_consumption_marker_guards_a_replay_after_failed_boundary(tmp_path):
    """B1: the consumption is durable across backend instances, not per-instance."""
    prepared = prepare_candidate(tmp_path / "candidate")
    grant_a = _minted_grant(prepared)
    grant_b = _minted_grant(prepared)
    _write_claim(prepared, grant_a)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        asyncio.run(_attempt_launch(prepared, grant_a, intercept=intercept))
        marker = prepared.directory / "LAUNCH-CONSUMED.json"
        assert marker.is_file(), "the boundary consumption was never retained"
        evidence = json.loads(marker.read_text())
        assert evidence["prelaunch_digest"] == grant_a.prelaunch_sha256
        assert evidence["authorization_sha256"] == grant_a.authorization_sha256
        obstruction = asyncio.run(_attempt_launch(prepared, grant_b, intercept=intercept))
    assert obstruction is not None
    assert len(intercept.calls) == 1


# --- B3: complete static closure (deferred + computed import sites) ---------


def _closure_project(root: Path, entry: str, **files: str) -> Path:
    project = root / "probe-project"
    package = project / "d2_probe_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(files.get("__init__.py", ""))
    (package / "entry.py").write_text(entry)
    return project


@pytest.fixture()
def probe_closure(tmp_path, monkeypatch):
    """Point the full closure walk at an isolated probe project root."""

    def install(entry: str, **files: str):
        project = _closure_project(tmp_path, entry, **files)
        monkeypatch.setattr(terrain_clearing, "PROJECT", project)
        monkeypatch.setattr(terrain_clearing, "D2_CLOSURE_ROOT", "d2_probe_pkg.entry")
        return project

    return install


def test_closure_refuses_deferred_required_unresolved_import(probe_closure):
    """B3: a function-scoped unresolved import must fail the closure."""
    probe_closure(
        "def work():\n"
        "    import d2_probe_pkg.required_missing_helper  # deferred required\n"
        "    return helper.VALUE\n"
        "VALUE = 1\n"
    )
    with pytest.raises(terrain_clearing.D2ClosureError, match="required import"):
        terrain_clearing.d2_source_closure()


def test_closure_refuses_top_level_required_unresolved_import(probe_closure):
    """B3: statically required missing modules prevent launch at enumeration."""
    probe_closure("import d2_probe_pkg.required_missing_helper\nVALUE = 1\n")
    with pytest.raises(terrain_clearing.D2ClosureError, match="required import"):
        terrain_clearing.d2_source_closure()


def test_closure_refuses_from_import_of_missing_submodule(probe_closure):
    """B3: from-imports of nonexistent submodules without a binding refuse."""
    probe_closure(
        "from d2_probe_pkg import totally_missing_submodule\nVALUE = 1\n",
        **{"__init__.py": ""},
    )
    with pytest.raises(terrain_clearing.D2ClosureError, match="required import"):
        terrain_clearing.d2_source_closure()


def test_closure_refuses_computed_dynamic_import_site(probe_closure):
    """B3: dynamic import sites whose name is computed must be accounted for."""
    probe_closure(
        "import importlib\n"
        "name = 'd2_probe_pkg.' + 'helper'\n"
        "def work():\n"
        "    importlib.import_module(name)\n"
        "VALUE = 1\n"
    )
    with pytest.raises(terrain_clearing.D2ClosureError, match="computed dynamic import"):
        terrain_clearing.d2_source_closure()


def test_closure_still_covers_attribute_and_resolved_imports(probe_closure):
    """B3 guard: attribute imports and initializer-bound names stay resolvable."""
    probe_closure(
        "from d2_probe_pkg import VALUEHOLDER\n"
        "from typing import TYPE_CHECKING\n"
        "VALUE = VALUEHOLDER.x\n",
        **{"__init__.py": "VALUEHOLDER = type('V', (), {'x': 1})\n"},
    )
    closure = terrain_clearing.d2_source_closure()
    assert any(path.endswith("entry.py") for path in closure)


def test_real_d2_closure_walk_completes_without_refusals():
    """B3 guard: the tightened walk keeps producing the real project closure."""
    terrain_clearing.d2_source_closure()


# --- B4: dependency inventory covers observed native dependencies -----------


def test_dependency_inventory_contains_independently_observed_native_extensions():
    """B4: NumPy and Pandas native extensions join the dependency freeze."""
    inventory = terrain_clearing.d2_dependency_inventory()
    for top in ("numpy", "pandas"):
        native = [path for path in inventory if f"/{top}/" in path and path.endswith(".so")]
        assert native, f"{top} native extensions are absent from the dependency inventory"


def test_previously_omitted_native_extension_omission_is_refused():
    """B4: a staged freeze missing the native extensions is refused."""
    inventory = terrain_clearing.d2_dependency_inventory()
    native_paths = [path for path in inventory if "/numpy/" in path or "/pandas/" in path]
    assert native_paths, "the inventory never covered the native extensions"
    frozen = {path: digest for path, digest in inventory.items() if path not in native_paths}
    with pytest.raises(ValueError, match="dependencies are not frozen"):
        terrain_clearing.require_frozen_d2_dependencies(frozen)


def test_native_extension_content_drift_is_refused():
    """B4: a native extension whose frozen bytes drifted refuses the freeze."""
    inventory = terrain_clearing.d2_dependency_inventory()
    native_path = next(path for path in inventory if "/numpy/" in path and path.endswith(".so"))
    frozen = dict(inventory)
    frozen[native_path] = "0" * 64
    with pytest.raises(ValueError, match="Frozen source/input changed"):
        terrain_clearing.verify_freeze(frozen)


class _FakeDistribution:
    """Distribution stand-in recording its own declared files and base."""

    def __init__(self, files, locate_base):
        self._files = files
        self._base = locate_base

    @property
    def files(self):
        return self._files

    def locate_file(self, path):
        return self._base / path


def _install_fake_distribution(monkeypatch, name, files, locate_base):
    monkeypatch.setattr(
        terrain_clearing,
        "_d2_dependency_distributions",
        lambda cwd, closure_root: ((name,), ()),
    )
    monkeypatch.setattr(
        terrain_clearing.importlib.metadata,
        "distribution",
        lambda dist: _FakeDistribution(files, locate_base),
    )


def test_dependency_inventory_refuses_a_missing_distribution_record(monkeypatch):
    """B4: a distribution without a RECORD cannot be staged fail-openly."""
    _install_fake_distribution(monkeypatch, "recordless", None, Path("/nonexistent-locate-base"))
    with pytest.raises(ValueError, match="record"):
        terrain_clearing.d2_dependency_inventory()


def test_dependency_inventory_refuses_missing_installed_file_identity(monkeypatch, tmp_path):
    """B4: a declared installed file absent on disk is never silently skipped."""
    declared = PackagePath("absent_native/fake_extension.so")
    _install_fake_distribution(monkeypatch, "phantom_dist", [declared], tmp_path / "phantom-base")
    with pytest.raises(ValueError, match="installed-file identity"):
        terrain_clearing.d2_dependency_inventory()


def test_unowned_observed_dependency_tops_are_pinned_by_their_files():
    """B4: a third-party top no distribution owns is pinned by its own bytes."""
    inventory = terrain_clearing.d2_dependency_inventory()
    assert any(path.endswith("_virtualenv.py") for path in inventory)
    files = terrain_clearing._d2_unowned_top_files("_virtualenv")
    assert any(str(path).endswith("_virtualenv.py") for path in files)
    with pytest.raises(ValueError, match="unowned"):
        terrain_clearing._d2_unowned_top_files("d2_repair_absent_top_xyz")


# --- B5: the launch environment is part of the sealed approval ---------------


def test_launch_runs_exactly_the_sealed_approved_environment(tmp_path):
    """B5: Popen receives exactly the metadata-sealed environment."""
    prepared = prepare_candidate(tmp_path / "candidate")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    approved = metadata["environment"]
    assert approved, "the staged approval must seal the launch environment"
    grant = _minted_grant(prepared)
    _write_claim(prepared, grant)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        assert asyncio.run(_attempt_launch(prepared, grant, intercept=intercept)) is None
    assert intercept.calls, "the approved launch never reached the seam"
    assert intercept.calls[0]["env"] == approved


def test_host_environment_drift_after_authorization_is_neutralized(tmp_path, monkeypatch):
    """B5: PATH tampering in the host environment cannot reach the process."""
    prepared = prepare_candidate(tmp_path / "candidate")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    approved_path = metadata["environment"]["PATH"]
    grant = _minted_grant(prepared)
    _write_claim(prepared, grant)
    monkeypatch.setenv("PATH", "/tmp/evil/bin")
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        assert asyncio.run(_attempt_launch(prepared, grant, intercept=intercept)) is None
    assert intercept.calls[0]["env"]["PATH"] == approved_path
    assert intercept.calls[0]["env"]["PATH"] != "/tmp/evil/bin"


def test_launch_refuses_forged_environment_overrides(tmp_path):
    """B5: an extra unapproved variable refuses at the boundary."""
    prepared = prepare_candidate(tmp_path / "candidate")
    grant = _minted_grant(prepared)
    _write_claim(prepared, grant)
    forged_spec = dataclasses.replace(
        prepared.spec,
        environment=(*prepared.spec.environment, ("X_D2_UNAPPROVED", "injected")),
    )
    forged = dataclasses.replace(prepared, spec=forged_spec)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        obstruction = asyncio.run(_attempt_launch(forged, grant, intercept=intercept))
    assert obstruction is not None, "an unapproved environment variable launched"
    assert "launch environment" in str(obstruction), str(obstruction)
    assert intercept.calls == []


def test_launch_refuses_replacement_of_an_approved_override(tmp_path):
    """B5: replacing HOME (or any approved override) refuses at the boundary."""
    prepared = prepare_candidate(tmp_path / "candidate")
    grant = _minted_grant(prepared)
    _write_claim(prepared, grant)
    approved = json.loads((prepared.directory / "PRELAUNCH.json").read_text())["environment"]
    replaced = {
        name: ("C:/hostile/replacement" if name == "HOME" else value)
        for name, value in approved.items()
    }
    assert replaced != approved, "the approved environment contains no forgeable value"
    forged_spec = dataclasses.replace(prepared.spec, environment=tuple(replaced.items()))
    forged = dataclasses.replace(prepared, spec=forged_spec)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        obstruction = asyncio.run(_attempt_launch(forged, grant, intercept=intercept))
    assert obstruction is not None, "a replaced environment value launched"
    assert "launch environment" in str(obstruction), str(obstruction)
    assert intercept.calls == []


# --- B6: the one-shot claim is complete, consumed and candidate-matching -----


def _retarget_claim(directory, mutate):
    claim = json.loads((directory / "CLAIM.json").read_text())
    mutate(claim)
    (directory / "CLAIM.json").write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))


@pytest.mark.parametrize(
    ("mutation", "state"),
    (
        pytest.param(
            lambda claim: claim.update(consumed=False), "NOT_CONSUMED", id="consumed-false"
        ),
        pytest.param(lambda claim: claim.pop("consumed"), "NOT_CONSUMED", id="consumed-missing"),
        pytest.param(
            lambda claim: claim.update(launches_allowed=99, retries=5),
            "ONE_SHOT_ALLOWANCE_EXPANDED",
            id="expanded-allowances",
        ),
        pytest.param(
            lambda claim: claim.pop("launches_allowed"),
            "INCOMPLETE_CLAIM",
            id="allowance-missing",
        ),
    ),
)
def test_replay_requires_a_complete_consumed_one_shot_claim(tmp_path, mutation, state):
    """B6: incomplete or unconsumed claims never replay as verified receipts."""
    directory = synthetic_attempt(tmp_path, "verified")
    _retarget_claim(directory, mutation)
    verdict = terrain_clearing.verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == state


def test_replay_refuses_non_one_shot_allowance_values_even_when_consumed(tmp_path):
    """B6: retries beyond zero deny the single-attempt verdict."""
    directory = synthetic_attempt(tmp_path, "verified")
    _retarget_claim(directory, lambda claim: claim.update(retries=1))
    verdict = terrain_clearing.verify_attempt(directory)
    assert verdict["authorization_state"] == "ONE_SHOT_ALLOWANCE_EXPANDED"


def test_replay_refuses_unrecognized_prelaunch_schema_strings(tmp_path):
    """B6: a caller-controlled schema string can never skip the v2 gate."""
    directory = synthetic_attempt(tmp_path, "verified")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    metadata["schema"] = "rogue-prelaunch-v0"
    (directory / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    seal = sha256(directory / "PRELAUNCH.json")

    def mutation(claim):
        claim["prelaunch_digest"] = seal

    _retarget_claim(directory, mutation)
    verdict = terrain_clearing.verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "UNKNOWN_PRELAUNCH_SCHEMA"


def test_replay_refuses_mismatched_authorization_digests(tmp_path):
    """B6: a claim pinning different record bytes stands tampered."""
    directory = synthetic_attempt(tmp_path, "verified")
    _retarget_claim(directory, lambda claim: claim.update(authorization_sha256="0" * 64))
    verdict = terrain_clearing.verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "TAMPERED"


def test_replay_of_untouched_valid_evidence_still_receives_the_receipt(tmp_path):
    """B6 guard: the complete retained claim still replays as a receipt."""
    directory = synthetic_attempt(tmp_path, "verified")
    verdict = terrain_clearing.verify_attempt(directory)
    assert verdict["verification"] == "RECEIPT_VERIFIED"


def test_launch_boundary_refuses_the_same_incomplete_claims(tmp_path):
    """B6: the consumed flag and one-shot allowances gate the boundary too."""
    prepared = prepare_candidate(tmp_path / "candidate")
    grant = _minted_grant(prepared)
    _write_claim(prepared, grant, launches_allowed=99, retries=5)
    intercept = PopenIntercept()
    with mock.patch.object(native_module.subprocess, "Popen", intercept):
        obstruction = asyncio.run(_attempt_launch(prepared, grant, intercept=intercept))
    assert obstruction is not None, "an expanded claim reached the seam"
    assert "ONE_SHOT_ALLOWANCE_EXPANDED" in str(obstruction)
    assert intercept.calls == []
