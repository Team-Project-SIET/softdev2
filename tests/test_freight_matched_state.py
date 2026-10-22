"""Matched branch equality never upgrades prepared bytes to native proof."""

import copy
import hashlib
import json

import pytest

from app.simulation.openttd.freight_matched_state import (
    inspect_capacity_source,
    validate_capacity_branches,
)


def source(tmp_path):
    (tmp_path / "before.sav").write_bytes(b"before")
    (tmp_path / "qualified.sav").write_bytes(b"qualified")

    def digest(name):
        return hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()

    links = dict(
        original_save_digest=digest("before.sav"),
        loaded_source_digest=None,
        runtime_digest="a" * 64,
        configuration_digest="b" * 64,
        bridge_digest="c" * 64,
        world_id="world",
        world_observation_digest="d" * 64,
        final_structural_digest="e" * 64,
        qualified_production_digest="f" * 64,
        post_qualification_save_digest=digest("qualified.sav"),
        evidence_kind="owned-native-save-snapshots",
    )
    (tmp_path / "prepared-source-links.json").write_text(json.dumps(links))
    return tmp_path


def branches():
    state = {
        key: {}
        for key in (
            "map",
            "industries_production",
            "company",
            "infrastructure",
            "vehicles_orders",
            "finances",
            "economy_date",
            "timekeeping",
        )
    }
    return {
        name: dict(
            save_sha256="a" * 64,
            runtime_sha256="b" * 64,
            configuration_sha256="c" * 64,
            bridge_sha256="d" * 64,
            settings={},
            state=copy.deepcopy(state),
            auto_renew=False,
            attempt_id=f"future-{name}",
            intervention_service=service,
            intervention_after_branch=True,
        )
        for name, service in (("A", None), ("B", 1), ("C", 2))
    }


def test_prepared_source_does_not_prove_matched_fleet_or_reload(tmp_path):
    result = inspect_capacity_source(source(tmp_path))
    assert result["native_ready"] is False
    assert result["canonical_fleet_save"] is None
    assert len(result["blockers"]) == 2
    assert result["native_launches"] == result["admin_connections"] == 0


@pytest.mark.parametrize("name", ["before.sav", "qualified.sav"])
def test_changed_save_rejected(tmp_path, name):
    directory = source(tmp_path)
    (directory / name).write_bytes(b"replacement")
    with pytest.raises(ValueError, match="identity mismatch"):
        inspect_capacity_source(directory)


def test_controlled_labels_cannot_become_native_proof(tmp_path):
    directory = source(tmp_path)
    path = directory / "prepared-source-links.json"
    links = json.loads(path.read_text())
    links["evidence_kind"] = "controlled-simulation"
    path.write_text(json.dumps(links))
    with pytest.raises(ValueError, match="identity mismatch"):
        inspect_capacity_source(directory)


def test_equivalent_proposals_have_no_authority_return_value():
    assert validate_capacity_branches(branches()) is None


@pytest.mark.parametrize(
    "key", ["save_sha256", "bridge_sha256", "configuration_sha256", "settings"]
)
def test_changed_branch_input_rejected(key):
    value = branches()
    value["B"][key] = "e" * 64 if key.endswith("sha256") else {"changed": True}
    with pytest.raises(ValueError, match="correspondence mismatch"):
        validate_capacity_branches(value)


@pytest.mark.parametrize(
    "key", ["vehicles_orders", "finances", "economy_date", "industries_production"]
)
def test_loaded_state_identity_mismatch_rejected(key):
    value = branches()
    value["C"]["state"][key] = {"changed": True}
    with pytest.raises(ValueError, match="correspondence mismatch"):
        validate_capacity_branches(value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("attempt_id", "future-A"),
        ("auto_renew", True),
        ("intervention_after_branch", False),
        ("intervention_service", 2),
    ],
)
def test_policy_and_arm_identity_rejected(key, value):
    proposed = branches()
    proposed["B"][key] = value
    with pytest.raises(ValueError):
        validate_capacity_branches(proposed)
