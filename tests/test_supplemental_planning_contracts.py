"""Controlled facts/artifacts/source composition. No native runtime or socket activity."""

import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import ValidationError
from test_qualification_coordinator import QualificationWire, collect

from app.planning.domain import PreparedWorldManifest
from app.simulation.openttd.planning_fact_artifacts import MAX_ARTIFACT_BYTES, import_planning_facts
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.prepared_source_correspondence import (
    ControlledSourceLinks,
    PreparedSourceCorrespondence,
    SourceTrust,
)
from app.simulation.openttd.supplemental_planning_facts import (
    PlanningFactError,
    SupplementalPlanningFacts,
)
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


def world_for(*, empty=False, zero=False, accepts=None):
    async def run():
        wire = QualificationWire(
            industries=() if empty else (2, 17), produces=() if empty else (1,)
        )
        if accepts is not None:
            wire.accepts = accepts
        if zero:
            wire.metrics = (0, 0, 0)
        result = await collect(wire, await wire.owner())
        return WorldPlanningObservation(result.verification.stability.final, result)

    return asyncio.run(run())


@pytest.fixture(scope="module")
def world():
    return world_for()


def fact_dict(w):
    c = w.context
    return {
        "schema_version": 1,
        "transport_mode": "road",
        "source": {
            "world_observation_digest": w.composition_digest,
            "structural_digest": w.structural.structural_world_digest,
            "production_digest": w.production.production_digest,
            "world_id": c.world.world_id,
            "runtime_digest": c.world.runtime_identity.sha256,
            "configuration_digest": c.configuration_digest,
            "bridge_digest": c.bridge.sha256,
            "content_digest": "a" * 64,
            "map_width": c.world.map_width,
            "map_height": c.world.map_height,
        },
        "region": {"x": 0, "y": 0, "width": 2, "height": 1},
        "settings": {
            "content_digest": "a" * 64,
            "generation_seed": 1,
            "modified_catchment": True,
            "serve_neutral_industries": False,
            "timekeeping": "calendar",
            "effective_truck_stop_radius": 3,
            "context": "deity-public",
            "gameplay_newgrf_ids": [],
        },
        "road": {
            "road_type_id": 0,
            "public_available": True,
            "max_speed_native": 0,
            "road_piece_cost_gbp": 10,
            "truck_stop_cost_gbp": 50,
            "depot_cost_gbp": 100,
            "currency": "GBP",
        },
        "tiles": [
            dict(
                tile_id=x,
                x=x,
                y=0,
                min_height=1,
                slope=0,
                buildable=True,
                water=False,
                coast=False,
                tree=False,
                farm=False,
                rock=False,
                rough=False,
                road=False,
                rail=False,
                water_transport=False,
                air_transport=False,
                industry_id=None,
            )
            for x in (0, 1)
        ],
        "coverage_scopes": [],
        "coverage": [],
        "engines": [
            {
                "engine_id": 7,
                "default_cargo_id": 1,
                "engine_road_type_id": 0,
                "public_available": True,
                "articulated": False,
                "has_power_on_road": True,
                "capacity_cargo_units": 30,
                "purchase_cost_gbp": 1000,
                "running_cost_gbp_per_economy_year": 365,
                "max_speed_native": 40,
            }
        ],
        "capture_economy_date_before": w.production.qualification.current_month.start_date,
        "capture_economy_date_after": w.production.qualification.current_month.start_date,
    }


def facts(w, data=None):
    return SupplementalPlanningFacts.model_validate_json(json.dumps(data or fact_dict(w)))


def correspondence(w, *, final=None, missing=False):
    source = hashlib.sha256(b"original save fixture").hexdigest()
    manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=source,
        openttd_version=w.context.world.runtime_identity.version,
        base_set_name="OpenGFX",
        base_set_version="controlled",
        width_tiles=w.context.world.map_width,
        height_tiles=w.context.world.map_height,
        seed=1,
        resolved_sites=(),
        cargo_types=(),
        vehicle_types=(),
        buildable_tiles=(),
    )
    links = ControlledSourceLinks(
        original_save_digest=source,
        loaded_source_digest=None if missing else source,
        runtime_digest=w.context.world.runtime_identity.sha256,
        configuration_digest=w.context.configuration_digest,
        bridge_digest=w.context.bridge.sha256,
        world_id=w.context.world.world_id,
        world_observation_digest=w.composition_digest,
        final_structural_digest=w.structural.structural_world_digest,
        qualified_production_digest=w.production.production_digest,
        post_qualification_save_digest=final,
        evidence_kind="missing" if missing else "controlled-simulation",
    )
    return PreparedSourceCorrespondence(w, manifest, links)


def test_valid_immutable_canonical_facts(world):
    data = fact_dict(world)
    f = facts(world, data)
    f.require_world(world)
    data["tiles"].reverse()
    assert f.to_bytes() == facts(world, data).to_bytes()
    assert f.semantic_digest == hashlib.sha256(f.to_bytes()).hexdigest()
    with pytest.raises(ValidationError):
        f.tiles[0].x = 4
    with pytest.raises(ValidationError):
        f.transport_mode = "rail"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["tiles"][0].update(tile_id=4),
        lambda d: d["tiles"].append(d["tiles"][0]),
        lambda d: d["tiles"].pop(),
        lambda d: d["region"].update(x=65535),
        lambda d: d["region"].update(width=256, height=2),
        lambda d: d["tiles"][0].update(slope=65535),
        lambda d: d["engines"][0].update(articulated=True),
        lambda d: d["engines"][0].update(has_power_on_road=False),
        lambda d: d["engines"][0].update(engine_road_type_id=1),
        lambda d: d["engines"].append(d["engines"][0]),
        lambda d: d["road"].update(currency="USD"),
        lambda d: d["road"].update(road_piece_cost_gbp=-1),
        lambda d: d.pop("road"),
        lambda d: d["settings"].update(content_digest="b" * 64),
        lambda d: d["settings"].update(effective_truck_stop_radius=4),
        lambda d: d["settings"].update(gameplay_newgrf_ids=[5]),
        lambda d: d.update(transport_mode="rail"),
        lambda d: d.update(trusted=True),
        lambda d: d["tiles"][0].update(x=True),
    ],
)
def test_malformed_bundle_rejected(world, change):
    d = fact_dict(world)
    change(d)
    with pytest.raises(ValueError):
        facts(world, d)


@pytest.mark.parametrize(
    "field",
    [
        "runtime_digest",
        "configuration_digest",
        "bridge_digest",
        "structural_digest",
        "production_digest",
        "world_observation_digest",
    ],
)
def test_source_conflict_rejected(world, field):
    d = fact_dict(world)
    d["source"][field] = "e" * 64
    with pytest.raises(PlanningFactError):
        facts(world, d).require_world(world)


def test_references_and_complete_coverage(world):
    d = fact_dict(world)
    d["coverage_scopes"] = [{"industry_id": 2, "cargo_id": 1, "role": "pickup"}]
    with pytest.raises(ValueError, match="incomplete declared"):
        facts(world, d)
    d["coverage"] = [
        dict(
            tile_id=t,
            industry_id=2,
            cargo_id=1,
            role="pickup",
            producer_count=1,
            acceptance_eighths=0,
            industry_covered=True,
        )
        for t in (0, 1)
    ]
    f = facts(world, d)
    f.require_world(world)
    d["coverage"].reverse()
    assert facts(world, d).semantic_digest == f.semantic_digest
    for cargo in (9, 5):
        changed = json.loads(json.dumps(d))
        changed["coverage_scopes"][0]["cargo_id"] = cargo
        for record in changed["coverage"]:
            record["cargo_id"] = cargo
        with pytest.raises(PlanningFactError):
            facts(world, changed).require_world(world)
    d["engines"][0]["default_cargo_id"] = 5
    with pytest.raises(PlanningFactError, match="engine default cargo"):
        facts(world, d).require_world(world)


@pytest.mark.parametrize("empty,zero", [(False, True), (True, False)])
def test_zero_and_empty_world_remain_valid(empty, zero):
    w = world_for(empty=empty, zero=zero)
    result = ValidatedPlanningFactInput(w, facts(w), correspondence(w, missing=True))
    assert result.world.production.qualified_for_planning
    assert result.correspondence.post_qualification_status == "UNPROVEN"


def test_source_layers_preserved_and_real_execution_blocked(world):
    c = correspondence(world, final=hashlib.sha256(b"different final save").hexdigest())
    assert c.manifest.source_digest == c.links.original_save_digest
    assert c.links.post_qualification_save_digest != c.links.original_save_digest
    assert c.world_fingerprint != world.structural.structural_world_digest
    assert c.trust == SourceTrust.CONTROLLED_FIXTURE
    assert c.post_qualification_status == "CONTROLLED_SIMULATED"
    composed = ValidatedPlanningFactInput(world, facts(world), c)
    with pytest.raises(PlanningFactError, match="unproven"):
        composed.require_real_executable_source()
    with pytest.raises(FrozenInstanceError):
        c.world = world
    assert correspondence(world, missing=True).post_qualification_status == "UNPROVEN"


@pytest.mark.parametrize(
    "field",
    [
        "loaded_source_digest",
        "runtime_digest",
        "configuration_digest",
        "bridge_digest",
        "final_structural_digest",
        "qualified_production_digest",
        "world_observation_digest",
    ],
)
def test_correspondence_mismatches_rejected(world, field):
    c = correspondence(world)
    changed = c.links.model_dump(mode="json")
    changed[field] = "e" * 64
    with pytest.raises(PlanningFactError):
        replace(c, links=ControlledSourceLinks.model_validate_json(json.dumps(changed)))


def test_fabricated_real_link_rejected(world):
    d = correspondence(world).links.model_dump(mode="json")
    d["evidence_kind"] = "real"
    with pytest.raises(ValidationError):
        ControlledSourceLinks.model_validate_json(json.dumps(d))
    d["evidence_kind"] = "controlled-simulation"
    d["verified"] = True
    with pytest.raises(ValidationError):
        ControlledSourceLinks.model_validate_json(json.dumps(d))


def artifact_bytes(world):
    f = facts(world)
    return json.dumps(
        {
            "schema_version": 1,
            "source_class": "CONTROLLED_FIXTURE",
            "facts_digest": f.semantic_digest,
            "facts": f.model_dump(mode="json"),
        }
    ).encode()


def imported(tmp_path, world, raw=None, **kw):
    raw = artifact_bytes(world) if raw is None else raw
    path = tmp_path / "facts.json"
    path.write_bytes(raw)
    result = import_planning_facts(
        tmp_path,
        "facts.json",
        expected_bytes_digest=kw.get("digest", hashlib.sha256(raw).hexdigest()),
        world=world,
    )
    assert path.read_bytes() == raw
    return result


def test_artifact_import_byte_identity_and_semantics(tmp_path, world):
    original = artifact_bytes(world)
    a = imported(tmp_path, world, original)
    data = json.loads(original)
    data["facts"]["tiles"].reverse()
    b = imported(tmp_path, world, json.dumps(data, indent=2).encode())
    assert a.artifact.facts.to_bytes() == b.artifact.facts.to_bytes()
    assert a.input_bytes_digest != b.input_bytes_digest
    assert a.trust == SourceTrust.CONTROLLED_FIXTURE
    data["source_class"] = "SOURCE_BYTES_VERIFIED"
    assert (
        imported(tmp_path, world, json.dumps(data).encode()).trust
        == SourceTrust.SOURCE_BYTES_VERIFIED
    )


@pytest.mark.parametrize(
    "case",
    [
        "schema",
        "semantic",
        "source",
        "duplicate",
        "unknown",
        "json",
        "oversize",
        "bytes",
        "world",
        "duplicate-key",
    ],
)
def test_bad_artifacts_rejected(tmp_path, world, case):
    data = json.loads(artifact_bytes(world))
    kw = {}
    if case == "schema":
        data["schema_version"] = 2
    if case == "semantic":
        data["facts_digest"] = "0" * 64
    if case == "source":
        data["source_class"] = "REAL_RUNTIME_CORRESPONDENCE_PROVEN"
    if case == "duplicate":
        data["facts"]["tiles"].append(data["facts"]["tiles"][0])
    if case == "unknown":
        data["force"] = True
    if case == "bytes":
        kw["digest"] = "0" * 64
    if case == "world":
        data["facts"]["source"]["world_observation_digest"] = "0" * 64
    raw = json.dumps(data).encode()
    if case == "json":
        raw = b"{"
    if case == "oversize":
        raw = b" " * (MAX_ARTIFACT_BYTES + 1)
    if case == "duplicate-key":
        raw = raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1', 1)
    with pytest.raises(PlanningFactError):
        imported(tmp_path, world, raw, **kw)


@pytest.mark.parametrize(
    "path",
    ["../facts.json", "/tmp/facts.json", "./facts.json", "a/../facts.json", "a\\facts.json", ""],
)
def test_unsafe_paths_rejected(tmp_path, world, path):
    with pytest.raises(PlanningFactError):
        import_planning_facts(
            tmp_path,
            path,
            expected_bytes_digest="0" * 64,
            world=world,
        )


def test_symlink_rejected(tmp_path, world):
    (tmp_path / "real.json").write_bytes(artifact_bytes(world))
    (tmp_path / "link.json").symlink_to(tmp_path / "real.json")
    with pytest.raises(PlanningFactError):
        import_planning_facts(
            tmp_path,
            "link.json",
            expected_bytes_digest="0" * 64,
            world=world,
        )


def test_pure_imports_in_fresh_interpreter():
    script = """
import sys
import app.simulation.openttd.planning_fact_input
import app.simulation.openttd.planning_fact_artifacts
prefixes = ("ortools", "app.planning.preparation", "app.planning.optimizer")
execution = ("admin_", "secure_", "gamescript_", "runtime.external", "runtime.config")
bad = [n for n in sys.modules if n.startswith(prefixes) or
       n.startswith("app.simulation.openttd.") and any(s in n for s in execution)]
assert not bad, bad
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_owned_save_bytes_import_is_not_runtime_proof(tmp_path, world):
    from app.simulation.openttd.planning_fact_artifacts import import_prepared_source

    final = b"different final save"
    c = correspondence(world, final=hashlib.sha256(final).hexdigest())
    (tmp_path / "original.sav").write_bytes(b"original save fixture")
    (tmp_path / "final.sav").write_bytes(final)
    result = import_prepared_source(
        tmp_path,
        "original.sav",
        world=world,
        manifest=c.manifest,
        links=c.links,
        post_qualification_relative="final.sav",
    )
    assert result.original_bytes_digest == c.manifest.source_digest
    assert result.post_qualification_bytes_digest == c.links.post_qualification_save_digest
    assert result.trust == SourceTrust.SOURCE_BYTES_VERIFIED
    assert result.correspondence.trust == SourceTrust.CONTROLLED_FIXTURE
    with pytest.raises(PlanningFactError):
        result.correspondence.require_real_executable_source()
    assert (tmp_path / "final.sav").read_bytes() == final
    (tmp_path / "final.sav").write_bytes(b"corrupted")
    with pytest.raises(PlanningFactError, match="post-qualification save bytes"):
        import_prepared_source(
            tmp_path,
            "original.sav",
            world=world,
            manifest=c.manifest,
            links=c.links,
            post_qualification_relative="final.sav",
        )


def test_final_save_not_interchangeable_with_structure(world):
    c = correspondence(world)
    with pytest.raises(PlanningFactError, match="manifest save source"):
        replace(
            c,
            manifest=c.manifest.model_copy(
                update={"source_digest": world.structural.structural_world_digest}
            ),
        )


def test_explicit_service_required_facts_without_generation(world):
    value = ValidatedPlanningFactInput(world, facts(world), correspondence(world))
    with pytest.raises(PlanningFactError, match="coverage unavailable"):
        value.require_road_service_facts(2, 17, 1)
    with pytest.raises(PlanningFactError, match="distinct"):
        value.require_road_service_facts(2, 2, 1)
    with pytest.raises(PlanningFactError, match="positive qualified supply"):
        value.require_road_service_facts(2, 17, 9)


def test_owned_original_save_corruption_rejected(tmp_path, world):
    from app.simulation.openttd.planning_fact_artifacts import import_prepared_source

    c = correspondence(world, missing=True)
    (tmp_path / "source.sav").write_bytes(b"corrupted original")
    with pytest.raises(PlanningFactError, match="original prepared save bytes"):
        import_prepared_source(
            tmp_path, "source.sav", world=world, manifest=c.manifest, links=c.links
        )


def test_manifest_seed_conflict_and_capture_outside_m2_rejected(world):
    c = correspondence(world)
    with pytest.raises(PlanningFactError, match="seed mismatch"):
        ValidatedPlanningFactInput(
            world, facts(world), replace(c, manifest=c.manifest.model_copy(update={"seed": 2}))
        )
    data = fact_dict(world)
    data["capture_economy_date_before"] = 0
    data["capture_economy_date_after"] = 0
    with pytest.raises(PlanningFactError, match="outside final M2"):
        ValidatedPlanningFactInput(world, facts(world, data), c)


def test_symlink_directory_and_special_file_rejected(tmp_path, world):
    import os

    (tmp_path / "dir").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "dir", target_is_directory=True)
    for name in ("alias/facts.json", "pipe"):
        if name == "pipe":
            os.mkfifo(tmp_path / name)
        with pytest.raises(PlanningFactError):
            import_planning_facts(
                tmp_path,
                name,
                expected_bytes_digest="0" * 64,
                world=world,
            )


def test_complete_explicit_service_facts_accepted_and_unavailable_engine_rejected():
    w = world_for(accepts=(1,))
    data = fact_dict(w)
    data["coverage_scopes"] = [
        dict(industry_id=i, cargo_id=1, role=r) for i, r in ((2, "pickup"), (17, "delivery"))
    ]
    data["coverage"] = [
        dict(
            tile_id=t,
            industry_id=i,
            cargo_id=1,
            role=r,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=True,
        )
        for t in (0, 1)
        for i, r in ((2, "pickup"), (17, "delivery"))
    ]
    value = ValidatedPlanningFactInput(w, facts(w, data), correspondence(w))
    assert value.require_road_service_facts(2, 17, 1) is None
    data["engines"][0]["public_available"] = False
    with pytest.raises(PlanningFactError, match="engine unavailable"):
        ValidatedPlanningFactInput(w, facts(w, data), correspondence(w)).require_road_service_facts(
            2, 17, 1
        )
    data["coverage_scopes"].append(data["coverage_scopes"][0])
    with pytest.raises(ValueError):
        facts(w, data)


def test_import_resolves_cross_references_and_full_source(world, tmp_path):
    for change in ("source", "cargo"):
        data = fact_dict(world)
        if change == "source":
            data["source"]["configuration_digest"] = "0" * 64
        else:
            data["engines"][0]["default_cargo_id"] = 5
        f = facts(world, data)
        raw = json.dumps(
            {
                "schema_version": 1,
                "source_class": "CONTROLLED_FIXTURE",
                "facts_digest": f.semantic_digest,
                "facts": f.model_dump(mode="json"),
            }
        ).encode()
        with pytest.raises(PlanningFactError):
            imported(tmp_path, world, raw)
