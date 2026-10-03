"""Independent runtime identity, without running OpenTTD."""

import json
from pathlib import Path

import pytest

from app.planning.canonical import world_manifest_hash
from app.planning.runtime_world import (
    RuntimeWorldObject,
    RuntimeWorldObservation,
    parse_runtime_world_evidence,
    runtime_projection_from_manifest,
    runtime_world_hash,
)
from app.planning.serialization import plan_hash
from app.planning.setup_evidence import SetupEvidenceError
from tests.test_planning_transport_live import WORLD_SOURCE, pinned_plan_and_scenario


def test_runtime_projection_is_distinct_from_manifest():
    _, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    manifest = scenario.world_manifest
    projected = runtime_projection_from_manifest(manifest)
    assert runtime_world_hash(projected) == runtime_world_hash(
        runtime_projection_from_manifest(manifest.model_copy(update={"source_digest": "0" * 64}))
    )
    assert len(projected.objects) == 2


def identity():
    plan, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    return plan_hash(plan), runtime_projection_from_manifest(scenario.world_manifest)


def log_for(observation, *, success=True):
    plan, _ = identity()
    sites = ",".join(f"{o.kind}:{o.object_id}:{o.x}:{o.y}" for o in observation.objects)
    payload = (
        f"P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|{plan}|{observation.width}|"
        f"{observation.height}|{observation.seed}|{sites}"
    )
    messages = [payload]
    if success:
        messages.append(f"P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_SUCCEEDED|{plan}")
    messages.append("P03_EXECUTOR_AI|P03_SETUP_V1|receipt-parsed-separately")
    return "".join(f"dbg: [script] [0] [I] {m}\n" for m in messages)


def test_manifest_semantics_and_projection():
    _, s = pinned_plan_and_scenario(WORLD_SOURCE)
    m = s.world_manifest
    assert (
        world_manifest_hash(m) == "fb2f32a4b3a5d3382583271c6562b52767a7c9a2f695270fcb096f2b5deaaf1b"
    )
    sites = list(m.resolved_sites)
    sites[0] = sites[0].model_copy(
        update={"location_id": "different", "serves_location_id": "planner-link"}
    )
    for mutated in (
        m.model_copy(update={"source_digest": "0" * 64}),
        m.model_copy(update={"resolved_sites": tuple(sites)}),
    ):
        assert world_manifest_hash(mutated) != world_manifest_hash(m)
        assert runtime_world_hash(runtime_projection_from_manifest(mutated)) == runtime_world_hash(
            runtime_projection_from_manifest(m)
        )


@pytest.mark.parametrize("field", ["width", "height", "seed", "x", "y", "object_id"])
def test_runtime_mutations_fail_despite_success(field):
    plan, expected = identity()
    if field in ("width", "height", "seed"):
        mutated = expected.model_copy(update={field: getattr(expected, field) + 1})
    else:
        first = expected.objects[0]
        mutated = expected.model_copy(
            update={
                "objects": (
                    first.model_copy(update={field: getattr(first, field) + 10}),
                    *expected.objects[1:],
                )
            }
        )
    assert runtime_world_hash(mutated) != runtime_world_hash(expected)
    with pytest.raises(SetupEvidenceError, match="runtime world hash mismatch"):
        parse_runtime_world_evidence(log_for(mutated), expected, plan)


def test_matching_runtime_and_success_dual_gate():
    plan, expected = identity()
    result = parse_runtime_world_evidence(log_for(expected), expected, plan)
    independently_parsed = RuntimeWorldObservation.model_validate_json(
        json.dumps(result["runtime_world_observation"])
    )
    assert result["observed_runtime_world_hash"] == runtime_world_hash(independently_parsed)
    assert result["runtime_world_hash_match"] is True
    assert result["thin_ai_world_validation_result"] == "WORLD_VALIDATION_SUCCEEDED"
    reversed_objects = expected.model_copy(update={"objects": tuple(reversed(expected.objects))})
    assert runtime_world_hash(reversed_objects) == runtime_world_hash(expected)
    assert parse_runtime_world_evidence(log_for(reversed_objects), expected, plan)[
        "runtime_world_hash_match"
    ]
    with pytest.raises(SetupEvidenceError):
        parse_runtime_world_evidence(log_for(expected, success=False), expected, plan)
    with pytest.raises(SetupEvidenceError):
        parse_runtime_world_evidence(
            log_for(expected).replace("WORLD_VALIDATION_SUCCEEDED", "WORLD_VALIDATION_STARTED"),
            expected,
            plan,
        )


@pytest.mark.parametrize(
    "mutation", ["missing", "malformed", "claimed", "duplicate", "instance", "order"]
)
def test_invalid_observation_cannot_establish_identity(mutation):
    plan, expected = identity()
    log = log_for(expected)
    if mutation == "missing":
        log = log.replace(f"|{expected.width}|{expected.height}|", f"|{expected.width}|")
    elif mutation == "malformed":
        log = log.replace(f"|{expected.width}|", "|not-an-integer|")
    elif mutation == "claimed":
        log = log.replace("P03_RUNTIME_WORLD_V1", "P03_WORLD_V1")
    elif mutation == "duplicate":
        log = log.splitlines()[0] + "\n" + log
    elif mutation == "instance":
        log = log.replace("[0] [I] P03_EXECUTOR_AI|P03_STAGE", "[1] [I] P03_EXECUTOR_AI|P03_STAGE")
    else:
        log = "\n".join(reversed(log.splitlines()))
    with pytest.raises(SetupEvidenceError):
        parse_runtime_world_evidence(log, expected, plan)


def test_source_observation_uses_runtime_values():
    from pathlib import Path

    source = Path("app/planning/thin_ai/main.nut").read_text()
    payload = source.split('AILog.Info("P03_EXECUTOR_AI|P03_RUNTIME_WORLD_V1|')[1].split("_stage(")[
        0
    ]
    assert "data.world_fingerprint" not in payload
    for api in (
        "AIMap.GetMapSizeX()",
        "AIMap.GetMapSizeY()",
        'AIGameSettings.GetValue("game_creation.generation_seed")',
        "AIIndustryList()",
        "AIStation.GetStationID(observed_location)",
        "AIMap.GetTileX(observed_location)",
        "AIMap.GetTileY(observed_location)",
    ):
        assert api in source


def test_unbuilt_candidates_require_valid_tiles_without_claiming_objects():
    """Static Squirrel contract; the later authorized run supplies runtime proof."""
    from pathlib import Path

    _, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    candidates = [s for s in scenario.world_manifest.resolved_sites if s.world_kind is None]
    assert candidates and all(s.world_id is None for s in candidates)
    assert len(runtime_projection_from_manifest(scenario.world_manifest).objects) == 2
    source = Path("app/planning/thin_ai/main.nut").read_text()
    tile_check = source.index("if (!AIMap.IsValidTile(tile))")
    candidate_check = source.index("if (site.world_kind == null && site.world_id == null)")
    object_check = source.index('if (site.world_kind == "industry")')
    assert tile_check < candidate_check < object_check
    assert '_world_failure(data, "TILE_INVALID", site' in source[tile_check:candidate_check]
    candidate_branch = source[
        candidate_check : source.index("local observed_location", candidate_check)
    ]
    assert "continue;" in candidate_branch
    assert "observed_sites" not in candidate_branch
    assert "AILog" not in candidate_branch
    assert "if (observed_location != tile)" in source
    assert "if (observed_id != site.world_id)" in source


def test_pinned_fixture_isolation_does_not_delete_required_runtime_objects():
    """The disposable AI owns no object in the runtime identity projection."""
    from openttdlab import parse_savegame

    with WORLD_SOURCE.open("rb") as stream:
        saved = parse_savegame(iter(lambda: stream.read(65536), b""))
    _, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    projected = runtime_projection_from_manifest(scenario.world_manifest)

    assert not saved["chunks"]["STNN"]["records"]
    assert {(obj.kind, obj.object_id) for obj in projected.objects} == {
        ("industry", 0),
        ("industry", 1),
    }
    assert all(
        saved["chunks"]["INDY"]["records"][str(obj.object_id)]["owner"] == 16
        for obj in projected.objects
    )


def test_irregular_industry_anchor_is_not_reverse_resolved_as_a_tile_object():
    """Coal-mine layout 4 has no industry tile at its bounding-box origin."""
    from openttdlab import parse_savegame

    with WORLD_SOURCE.open("rb") as stream:
        saved = parse_savegame(iter(lambda: stream.read(65536), b""))
    origin = saved["chunks"]["INDY"]["records"]["0"]
    source = Path("app/planning/thin_ai/main.nut").read_text()
    # OpenTTD 13.4 build_industry.h, _tile_table_coal_mine_3. The save stores
    # selected_layout as the one-based layout index, so value 4 selects this layout.
    runtime_industry_tile_offsets = {
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 0),
        (2, 1),
        (2, 2),
    }

    assert origin["type"] == 0
    assert origin["selected_layout"] == 4
    assert (0, 0) not in runtime_industry_tile_offsets
    assert "AIIndustryList()" in source
    assert "AIIndustry.GetIndustryID(observed_location)" not in source


def test_existing_objects_remain_strict_and_deletion_is_not_a_candidate_fallback():
    source = Path("app/planning/thin_ai/main.nut").read_text()
    _, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    existing = [s for s in scenario.world_manifest.resolved_sites if s.world_kind is not None]

    assert [(s.location_id, s.world_kind, s.world_id) for s in existing] == [
        ("origin", "industry", 0),
        ("destination", "industry", 1),
    ]
    for reason in (
        "INDUSTRY_INVALID",
        "INDUSTRY_NOT_LISTED",
        "INDUSTRY_LOCATION_MISMATCH",
        "INDUSTRY_ID_MISMATCH",
        "STATION_INVALID",
        "STATION_LOCATION_MISMATCH",
        "STATION_ID_MISMATCH",
    ):
        assert f'"{reason}"' in source
    candidate = source.index("if (site.world_kind == null && site.world_id == null)")
    industry = source.index('if (site.world_kind == "industry")')
    assert source[candidate:industry].count("continue;") == 1
    assert "continue;" not in source[industry:]


def test_repeated_planner_references_emit_one_validated_runtime_object():
    """Static AI contract plus independent Python evidence, without OpenTTD."""
    from app.planning.domain import WorldReference
    from app.planning.transport import transport_bytes
    from app.planning.validation import validate_execution_plan

    plan, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    origin = scenario.world_manifest.resolved_sites[0]
    alias = origin.model_copy(update={"location_id": "origin-alias"})
    manifest = scenario.world_manifest.model_copy(
        update={"resolved_sites": (*scenario.world_manifest.resolved_sites, alias)}
    )
    fingerprint = world_manifest_hash(manifest)
    alias_location = scenario.locations[0].model_copy(update={"location_id": "origin-alias"})
    locations = tuple(
        location.model_copy(
            update={
                "world_reference": WorldReference(
                    world_fingerprint=fingerprint,
                    kind=location.world_reference.kind,
                    world_id=location.world_reference.world_id,
                )
            }
        )
        if location.world_reference is not None
        else location
        for location in (*scenario.locations, alias_location)
    )
    scenario = scenario.model_copy(
        update={
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "locations": locations,
        }
    )
    plan = plan.model_copy(
        update={
            "world_fingerprint": fingerprint,
            "validation": plan.validation.model_copy(
                update={"validated_world_fingerprint": fingerprint}
            ),
        }
    )
    validate_execution_plan(plan, scenario)
    module = transport_bytes(plan, scenario, plan_hash(plan))
    assert b'"origin-alias"' in module and b'"origin"' in module
    expected = runtime_projection_from_manifest(manifest)
    assert [(obj.kind, obj.object_id) for obj in expected.objects] == [
        ("industry", 0),
        ("industry", 1),
    ]

    source = Path("app/planning/thin_ai/main.nut").read_text()
    # Every site reaches validity, location and ID checks BEFORE deduplication.
    site_loop = source.index("foreach (site in data.sites)")
    dedup = source.index("if (!(object_key in observed_objects))")
    for check in (
        "AIIndustry.IsValidIndustry(site.world_id)",
        "AIIndustry.GetLocation(observed_id)",
        "if (observed_location != tile)",
        "if (observed_id != site.world_id)",
    ):
        assert site_loop < source.index(check) < dedup
    assert 'local object_key = observed_kind + ":" + observed_id.tostring();' in source
    assert "site.location_id" not in source[source.index("local object_key") : dedup]
    assert "runtime_objects.append(" in source[dedup:]
    assert source.index("runtime_objects.sort(") > dedup
    assert "a.kind < b.kind" in source and "a.object_id < b.object_id" in source
    emission_loop = source.index("foreach (object in runtime_objects)")
    assert source.index('observed_sites += object.kind + ":"') > emission_loop > dedup

    # The wire example has one entry for industry 0 despite two planner labels.
    wire = log_for(expected).replace(identity()[0], plan_hash(plan))
    assert wire.splitlines()[0].count("industry:0:168:70") == 1
    result = parse_runtime_world_evidence(wire, expected, plan_hash(plan))
    assert result["observed_runtime_world_hash"] == runtime_world_hash(expected)
    assert result["runtime_world_hash_match"]
    reversed_manifest = manifest.model_copy(
        update={"resolved_sites": tuple(reversed(manifest.resolved_sites))}
    )
    assert (
        runtime_world_hash(runtime_projection_from_manifest(reversed_manifest))
        == result["observed_runtime_world_hash"]
    )


def test_runtime_identity_orders_numeric_ids_and_keeps_kinds_distinct():
    """The canonical key is kind plus numeric ID, never a planner label."""
    from app.planning.canonical import canonical_bytes

    unordered = RuntimeWorldObservation(
        width=256,
        height=256,
        seed=17,
        objects=(
            RuntimeWorldObject(kind="station", object_id=2, x=30, y=40),
            RuntimeWorldObject(kind="industry", object_id=10, x=10, y=20),
            RuntimeWorldObject(kind="industry", object_id=2, x=50, y=60),
        ),
    )
    ordered = unordered.model_copy(
        update={"objects": (unordered.objects[2], unordered.objects[1], unordered.objects[0])}
    )
    import hashlib

    assert runtime_world_hash(unordered) == hashlib.sha256(canonical_bytes(ordered)).hexdigest()
    assert runtime_world_hash(unordered) == runtime_world_hash(ordered)
    assert len(unordered.objects) == 3
