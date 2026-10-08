"""Pure observation imports and compatibility with the existing runtime owners."""

import subprocess
import sys
from pathlib import Path


def test_domain_import_does_not_load_execution_stack():
    code = """
import sys
from app.simulation.openttd.structural_world import StructuralWorldObservation
from app.simulation.openttd.production_observation import IndustryProductionObservation
from app.simulation.openttd.qualified_production import QualifiedProductionResult
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation
for name in sys.modules:
    assert not name.startswith((
        "app.simulation.openttd.admin_",
        "app.simulation.openttd.secure_",
        "app.simulation.openttd.gamescript_",
        "app.simulation.openttd.proof.",
        "app.planning.preparation", "ortools",
    )), name
    assert name not in (
        "app.simulation.openttd.runtime.config",
        "app.simulation.openttd.runtime.external",
        "app.simulation.openttd.runtime.base",
        "app.simulation.openttd.structural_world_session",
        "app.simulation.openttd.production_session",
        "app.simulation.openttd.qualification_session",
    ), name
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).parents[1], capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()


def test_legacy_exports_are_the_same_pure_types():
    from app.simulation.openttd import (
        capability_observation,
        cargo_catalog,
        catalog_observation,
        gamescript_bridge,
        gamescript_protocol,
        industry_capability,
        observation_identity,
        observation_protocol,
        observation_session_evidence,
        production_session,
        qualification_session,
        qualified_production,
        structural_world_session,
    )
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    assert cargo_catalog.CargoCatalogObservation is catalog_observation.CargoCatalogObservation
    assert cargo_catalog.CargoCatalogRecord is catalog_observation.CargoCatalogRecord
    assert (
        industry_capability.IndustryCapabilityObservation
        is capability_observation.IndustryCapabilityObservation
    )
    assert gamescript_protocol.BridgeProtocolError is observation_protocol.BridgeProtocolError
    assert gamescript_bridge.BridgePackage is observation_identity.BridgePackage
    assert RuntimeIdentity is observation_identity.RuntimeIdentity
    assert (
        qualification_session.QualifiedProductionResult
        is qualified_production.QualifiedProductionResult
    )
    assert (
        production_session.ProductionSessionEvidence
        is observation_session_evidence.ProductionSessionEvidence
    )
    assert (
        structural_world_session.StructuralWorldSessionEvidence
        is observation_session_evidence.StructuralWorldSessionEvidence
    )
