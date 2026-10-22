"""V2 snapshot-scoped P08 planning adapter (policy ``p08-v2-snapshot-planning/1``).

Offline only. This adapter answers exactly one question with the retained
Tile Classification V2 census: *is the retained native census, by itself, a
sufficient and defensible planning input for the existing bounded P08
feasibility assessment, without fusing temporally incompatible V1
observations?*

Established separation of concerns (all from verified evidence):

- The sealed ``SOURCE_SAVE_FUSION`` verdict stays ``REJECTED`` and nothing
  here relabels it. This adapter does not fuse: it consumes no historical
  V1 world-state field as planning input.
- Tile world-state fields (ground-type mask bits, geometry, ownership,
  industry footprint, native class) are taken exclusively from the census.
- World/configuration identity facts (seed, revision, road type costs,
  engine data, catchment radius, content pin) are composition/save identity
  properties of the SAME staged save the census ran against (sealed
  ``save_binding_sha256``), not per-instant state; their reuse is explicit
  and labeled, never silent.
- Stop viability (a candidate truck-stop tile) uses the documented native
  15.3 station-construction semantic — flat, native-buildable, unowned,
  bare ground — which is exactly the planner's ``vacant`` rule applied to
  census-native ``TileFact`` projections. This is a planning rule, not the
  reconstruction of a V1 producer field (the two coexist and disagree on
  tree/rough tiles; both are reported). The census is additionally
  verified to contain no ``road_track``/``road_src_type`` rows, so the
  ``road_tile``-bit projection agrees with the three-bit-OR oracle that
  the same-instant coherence gate uses; any such row is a fail-closed
  error, never a silent divergence.
- Eligibility scope capability (industry 0 produces cargo 1, industry 1
  accepts cargo 1) is an industry-specification constant of this world.
  Per-industry *production quantities* are NOT re-observed in the census:
  coverage quantities are recorded as zero and explicitly declared
  not-consumed; stop eligibility therefore uses capability + census
  geometry only. The historical quantity gates
  (``producer_count > 0`` / ``acceptance_eighths >= 8``) belong to the
  production observations of the historical capture and are out of scope
  for a corridor feasibility verdict. A second assessment pin reuses the
  historical eligibility *structure* only as an endpoint set definition,
  with every endpoint re-validated stop-viable at the census instant.
- The census is a multi-day collection window (economy days 712224-712226,
  90 single-instant pages). The adapter never claims all 450 tiles were
  read at one instant. Instead it (a) records the true per-tile page
  provenance, (b) requires the recomputed catchment geometry to equal the
  historical ``industry_covered`` capture exactly (sites are stable), and
  (c) proves P08 verdict robustness across an explicit, mechanism-bounded
  perturbation set of the only measured dynamic classes: the six
  historically observed V1/V2 tree-lifecycle alternates, every single-tree
  death, and every tree spread onto a neighboring clear or rough tile.
  Any verdict flip is recorded, never hidden. Town-driven house growth
  inside the window is an explicitly listed residual (no town-adjacency
  data exists offline; the region shows zero house/station tiles).

Outputs a deterministic, hash-pinned, versioned derived report. No launch,
no administrative connection, no historical evidence mutation, no commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.planning.p08_road import vacant
from app.planning.p08_terrain import (
    FeasibilityDiagnosis,
    TerrainOutcome,
    TerrainProposal,
    assess_world_feasibility,
    plan_bounded_levelling,
)
from app.simulation.openttd.supplemental_planning_facts import (
    CoverageFact,
    PlanningFactError,
    SupplementalPlanningFacts,
    TileFact,
)
from app.simulation.openttd.tile_classification import (
    TileClass,
    TileClassificationReceipt,
    TileClassificationResponse,
    TileFailure,
    TileQueryError,
    classification_plan,
    classify_tile,
    flags_index,
    projection_disagrees,
)
from app.simulation.openttd.v2_semantic_reconciliation import (
    OWNER_UNOWNED_SENTINEL,
    bit,
    replay_retained_census,
)

POLICY_ID = "p08-v2-snapshot-planning"
POLICY_VERSION = "p08-v2-snapshot-planning/1"
SNAPSHOT_WORLD_ID = "v2-snapshot-census-seed17"

# Census-side classification bridge pair consumed by the retained candidate;
# hashed byte-exact and pinned in the derived report.
BRIDGE_PAIR_FILES = (
    "app/simulation/openttd/terrain_classification.nut",
    "app/simulation/openttd/terrain_classification_bridge.py",
)

# The two capability scopes of the assessed coal relationship (identity-stable
# industry specification, carried by the same staged save). (role, industry, cargo)
EXPECTED_CAPABILITY_SCOPES = (("delivery", 1, 1), ("pickup", 0, 1))

# Documented, non-fabricated semantics of each snapshot FactSource digest
# (all values are real digests of census-chain bytes; see module docstring).
DIGEST_SEMANTICS = {
    "world_observation_digest": "aggregate sha256 of the census page payloads",
    "structural_digest": "sealed source-save binding of the census session",
    "production_digest": (
        "no production observation exists in-session; pinned to the census "
        "corpus for contract shape; corridor feasibility consumes no "
        "production quantity"
    ),
    "runtime_digest": "sha256 of the census session's runtime-identity.json",
    "configuration_digest": "sha256 of the staged CANDIDATE.json composition",
    "bridge_digest": "sha256 over the classification bridge pair files",
    "content_digest": "pinned content identity carried by the same save",
}


@dataclass(frozen=True)
class CensusTile:
    """One census observation; per-page single-instant provenance attached."""

    tile_id: int
    x: int
    y: int
    elevation: int
    slope: int
    flags: int
    classification: str
    industry_id: int | None
    owner: int
    page_ordinal: int
    page_date: int

    def fact(self) -> TileFact:
        """Native 15.3 ``TileFact`` projection of the census mask.

        ``buildable`` is the native ``GSTile.IsBuildable`` semantics with the
        historical schema-1 house/station-collapse guard applied (both bits
        are absent in this region, verified). ``road`` is
        ``GSRoad.IsRoadTile`` (the road_tile bit, not the three-bit OR —
        the census is separately verified to carry no road_track /
        road_src_type rows, so the two semantics coincide; see the build
        gate), and ``air_transport`` is the bridge's airport-tile reading.
        The shared predicates must project the mask exactly.
        """

        return TileFact(
            tile_id=self.tile_id,
            x=self.x,
            y=self.y,
            min_height=self.elevation,
            slope=self.slope,
            buildable=bit(self.flags, "buildable")
            and not (bit(self.flags, "house") or bit(self.flags, "station")),
            water=bit(self.flags, "water"),
            coast=bit(self.flags, "coast"),
            tree=bit(self.flags, "tree"),
            farm=bit(self.flags, "farm"),
            rock=bit(self.flags, "rock"),
            rough=bit(self.flags, "rough"),
            road=bit(self.flags, "road_tile"),
            rail=bit(self.flags, "rail"),
            water_transport=bit(self.flags, "water_transport"),
            air_transport=bit(self.flags, "airport"),
            industry_id=self.industry_id,
        )


@dataclass(frozen=True)
class SnapshotGate:
    """Verified policy gate between the census and any snapshot planning use."""

    reconciliation_verdict: str
    semantic_tiles: int
    temporal_tiles: int
    contradiction_tiles: int
    unresolved_tiles: int
    completeness_reproduced: bool
    manifest_verified: bool
    manifest_entries: int
    hygiene_failures: tuple[str, ...]
    identity_failures: tuple[tuple[int, str], ...]
    retained_facts_sha256: str
    census_page_payload_sha256: str
    fused_mode: str
    fused_status: str
    fused_save_binding_sha256: str

    def failures(self) -> list[str]:
        problems: list[str] = []
        if not self.completeness_reproduced:
            problems.append("sealed completeness not reproduced offline")
        if not self.manifest_verified:
            problems.append("candidate artifact manifest did not verify")
        if self.hygiene_failures:
            problems.append(f"census hygiene failures: {sorted(self.hygiene_failures)}")
        if self.identity_failures:
            problems.append(f"identity failures: {self.identity_failures}")
        if self.contradiction_tiles or self.unresolved_tiles:
            problems.append("semantic reconciliation produced blocking evidence")
        if self.fused_mode != "SOURCE_SAVE_FUSION" or self.fused_status != "REJECTED":
            problems.append("sealed fusion verdict is not the expected immutable state")
        return problems


@dataclass(frozen=True)
class SnapshotAssessment:
    """The derived snapshot-scoped P08 assessment (never a native claim)."""

    policy_version: str
    gate: SnapshotGate
    census_bracket: tuple[int, int]
    census_pages: int
    census_tiles: int
    projection_disagreements: int
    stop_viable_tiles: int
    eligible_pickups: tuple[int, ...]
    eligible_deliveries: tuple[int, ...]
    revalidated_endpoints_pickups: tuple[int, ...]
    revalidated_endpoints_deliveries: tuple[int, ...]
    vac_semantic_divergent_tiles: int
    primary: FeasibilityDiagnosis
    revalidated: FeasibilityDiagnosis | None
    levelling: TerrainOutcome | None
    robustness: tuple[dict, ...]
    robustness_verdict: str
    facts_source: dict
    digest_semantics: dict
    facts_document_digest: str

    def report(self) -> dict:
        levelling_record: dict
        levelling = self.levelling
        if levelling is None:
            levelling_record = {"attached": False}
        elif isinstance(levelling, TerrainProposal):
            levelling_record = {
                "attached": True,
                "kind": "TerrainProposal",
                "code": "PLANNING_ONLY",
                "corridor": list(levelling.corridor),
                "interior_road_tiles": levelling.interior_road_tiles,
                "target_height": levelling.target_height,
                "pickup_stop": levelling.pickup_stop,
                "delivery_stop": levelling.delivery_stop,
                "cleared_tiles": list(levelling.cleared_tiles),
                "ops": len(levelling.ops),
                "search_expansions": levelling.search_expansions,
                "terraform_cost_gbp": levelling.terraform_cost_gbp,
                "native_execution": levelling.native_execution,
                "digest": levelling.digest,
            }
        else:
            levelling_record = {
                "attached": True,
                "kind": "TerrainInfeasibility",
                "code": str(levelling.code),
                "detail": levelling.detail,
                "search_expansions": levelling.search_expansions,
            }
        return {
            "schema": "p08-v2-snapshot-assessment/1",
            "policy_id": POLICY_ID,
            "policy_version": self.policy_version,
            "offline_only": True,
            "gate": {
                "reconciliation_verdict": self.gate.reconciliation_verdict,
                "semantic_tiles": self.gate.semantic_tiles,
                "temporal_tiles": self.gate.temporal_tiles,
                "genuine_contradictions": self.gate.contradiction_tiles,
                "unresolved_predicates": self.gate.unresolved_tiles,
                "completeness_reproduced": self.gate.completeness_reproduced,
                "manifest_verified": self.gate.manifest_verified,
                "manifest_entries": self.gate.manifest_entries,
                "hygiene_failures": list(self.gate.hygiene_failures),
                "identity_failures": [list(f) for f in self.gate.identity_failures],
                "sealed_fusion_mode": self.gate.fused_mode,
                "sealed_fusion_status": self.gate.fused_status,
                "sealed_save_binding_sha256": self.gate.fused_save_binding_sha256,
                # Invariant: this dict is produced only after SnapshotGate.failures()
                # returned empty (the build raises otherwise), so the list is
                # always empty by construction, not by omission.
                "gate_problems": [],
            },
            "sources": self.facts_source,
            "digest_semantics": self.digest_semantics,
            "census": {
                "pages": self.census_pages,
                "tiles": self.census_tiles,
                "bracket": list(self.census_bracket),
                "all_pages_sampled_simultaneously_is_not_claimed": True,
                "native_projection_disagreements": self.projection_disagreements,
                "stop_viable_tiles": self.stop_viable_tiles,
                "vac_semantic_divergent_tiles": self.vac_semantic_divergent_tiles,
            },
            "eligibility": {
                "primary_pickups": list(self.eligible_pickups),
                "primary_deliveries": list(self.eligible_deliveries),
                "revalidated_historical_pickups": list(self.revalidated_endpoints_pickups),
                "revalidated_historical_deliveries": list(self.revalidated_endpoints_deliveries),
                "quantity_gates": (
                    "production quantities are not re-observed in-session and are "
                    "not consumed by the corridor feasibility assessment"
                ),
                "revalidated_endpoints_note": (
                    "both retained endpoint sets survived census re-validation"
                    if self.revalidated is not None
                    else (
                        "variant B skipped: census re-validation removed all "
                        "historical endpoints on at least one side (see eligibility "
                        "lists above)"
                    )
                ),
            },
            "assessment_primary": self.primary.as_dict(),
            "assessment_revalidated_historical_endpoints": (
                None if self.revalidated is None else self.revalidated.as_dict()
            ),
            "levelling": levelling_record,
            "robustness": {
                "verdict": self.robustness_verdict,
                "cases": list(self.robustness),
            },
            "facts_document_digest": self.facts_document_digest,
            "not_claimed": [
                "no historical V1/V2 fusion (sealed SOURCE_SAVE_FUSION REJECTED unchanged)",
                "no native construction or terraform execution entitlement",
                "no production quantity or OPEX/ROI claim",
                "no same-instant (single-instant census) claim; multi-day window "
                "handled by per-page provenance plus bounded robustness evidence",
            ],
            "residuals": [
                "town-driven house growth inside the multi-day census window is "
                "unmeasured (no town-adjacency data offline; region shows zero "
                "house/station tiles); robustness covers the measured lifecycle "
                "mechanisms only",
                "delivery-side quantity gates belong to production observations "
                "not present in the census (P06/P07 domain)",
            ],
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


def _load_census(
    retained_path: Path,
    candidate_dir: Path,
) -> tuple[SupplementalPlanningFacts, dict[int, CensusTile], tuple[int, int], int]:
    """Receipt-bound re-parse of the census pages (fail-closed, read-only)."""

    retained = SupplementalPlanningFacts.model_validate_json(retained_path.read_bytes())
    first_request = json.loads((candidate_dir / "classification-p000-request.json").read_bytes())
    if not isinstance(first_request, dict) or not isinstance(first_request.get("request_id"), str):
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    requests = classification_plan(retained.region, first_request["request_id"])
    tiles: dict[int, CensusTile] = {}
    for ordinal, request in enumerate(requests):
        request_bytes = request.to_bytes()
        staged_request = (
            candidate_dir / f"classification-p{ordinal:03d}-request.json"
        ).read_bytes()
        if staged_request != request_bytes:
            raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
        response_bytes = (
            candidate_dir / f"classification-p{ordinal:03d}-response.json"
        ).read_bytes()
        TileClassificationReceipt.correlate(request_bytes, response_bytes)
        response = TileClassificationResponse.parse(response_bytes)
        if response.date_before != response.date_after:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        for tile, tile_class, industry, owner in response.classification:
            if tile in tiles:
                raise TileQueryError(TileFailure.DUPLICATE_TILE)
            elevation, slope, flags = response.geometry[tile]
            tiles[tile] = CensusTile(
                tile_id=tile,
                x=tile % response.map_width,
                y=tile // response.map_width,
                elevation=elevation,
                slope=slope,
                flags=flags,
                classification=tile_class.value,
                industry_id=industry,
                owner=owner,
                page_ordinal=ordinal,
                page_date=response.date_before,
            )
    expected = retained.region.width * retained.region.height
    if len(tiles) != expected:
        raise PlanningFactError(f"census tile count {len(tiles)} != region tile count {expected}")
    return (
        retained,
        tiles,
        (min(t.page_date for t in tiles.values()), max(t.page_date for t in tiles.values())),
        len(requests),
    )


def _disc_catchment(
    site_tiles: tuple[int, ...], known_tiles: set[int], map_width: int, map_height: int
) -> set[int]:
    """Configured radius-3 truck-stop catchment (Chebyshev) about site tiles."""

    out: set[int] = set()
    for tile_id in site_tiles:
        x, y = tile_id % map_width, tile_id // map_width
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < map_width and 0 <= ny < map_height):
                    continue
                neighbor = ny * map_width + nx
                if neighbor in known_tiles:
                    out.add(neighbor)
    return out


def _snapshot_source(
    retained: SupplementalPlanningFacts,
    gate: SnapshotGate,
    candidate_dir: Path,
    project_root: Path,
) -> dict:
    """Identity facts of the snapshot document (all real, census-side digests)."""

    runtime_digest = hashlib.sha256(
        (candidate_dir / "runtime-identity.json").read_bytes()
    ).hexdigest()
    composition_digest = hashlib.sha256((candidate_dir / "CANDIDATE.json").read_bytes()).hexdigest()
    bridge_digest = hashlib.sha256()
    for relative in BRIDGE_PAIR_FILES:
        path = project_root / relative
        if not path.is_file():
            raise PlanningFactError(f"census bridge file missing: {relative}")
        bridge_digest.update(path.read_bytes())
    return {
        "world_observation_digest": gate.census_page_payload_sha256,
        "structural_digest": gate.fused_save_binding_sha256,
        "production_digest": gate.census_page_payload_sha256,
        "world_id": SNAPSHOT_WORLD_ID,
        "runtime_digest": runtime_digest,
        "configuration_digest": composition_digest,
        "bridge_digest": bridge_digest.hexdigest(),
        "content_digest": retained.settings.content_digest,
        "map_width": retained.source.map_width,
        "map_height": retained.source.map_height,
    }


def _native_fact_from_flags(
    base: TileFact, variant_flags: int, industry_id: int | None
) -> TileFact:
    """Native projection of one tile under (possibly variant) mask flags."""

    return TileFact(
        tile_id=base.tile_id,
        x=base.x,
        y=base.y,
        min_height=base.min_height,
        slope=base.slope,
        buildable=bit(variant_flags, "buildable")
        and not (bit(variant_flags, "house") or bit(variant_flags, "station")),
        water=bit(variant_flags, "water"),
        coast=bit(variant_flags, "coast"),
        tree=bit(variant_flags, "tree"),
        farm=bit(variant_flags, "farm"),
        rock=bit(variant_flags, "rock"),
        rough=bit(variant_flags, "rough"),
        road=bit(variant_flags, "road_tile"),
        rail=bit(variant_flags, "rail"),
        water_transport=bit(variant_flags, "water_transport"),
        air_transport=bit(variant_flags, "airport"),
        industry_id=industry_id,
    )


def _robustness(
    census: dict[int, CensusTile],
    facts_document: SupplementalPlanningFacts,
    temporal_tiles: tuple[int, ...],
    retained: SupplementalPlanningFacts,
    pickups: tuple[int, ...],
    deliveries: tuple[int, ...],
    primary: FeasibilityDiagnosis,
    map_width: int,
) -> list[dict]:
    """Deterministic perturbation suite with a recorded invariance verdict.

    The six measured V1/V2 alternates are used as *perturbation probes only*
    (the adapter's planning input itself never carries them); baseline states
    are the census observations.
    """

    reference = (primary.code, tuple(sorted(primary.corridor)))
    base_facts = {t.tile_id: t for t in facts_document.tiles}
    retained_by_id = {t.tile_id: t for t in retained.tiles}

    def flag_bit(name: str) -> int:
        return 1 << flags_index(name)

    def run_case(label: str, target_tile: int, target_flags: int) -> dict:
        variant_flags = {tid: census[tid].flags for tid in base_facts}
        variant_classes = {tid: census[tid].classification for tid in base_facts}
        variant_flags[target_tile] = target_flags
        variant_classes[target_tile] = classify_tile(
            target_flags, census[target_tile].industry_id
        ).value
        variant_facts = {
            tid: _native_fact_from_flags(
                base_facts[tid], variant_flags[tid], census[tid].industry_id
            )
            for tid in base_facts
        }
        variant_document = SupplementalPlanningFacts(
            schema_version=1,
            transport_mode="road",
            source=facts_document.source,
            region=facts_document.region,
            settings=facts_document.settings,
            road=facts_document.road,
            tiles=tuple(variant_facts[tid] for tid in sorted(variant_facts)),
            coverage_scopes=facts_document.coverage_scopes,
            coverage=facts_document.coverage,
            engines=facts_document.engines,
            capture_economy_date_before=facts_document.capture_economy_date_before,
            capture_economy_date_after=facts_document.capture_economy_date_after,
        )
        diagnosis = assess_world_feasibility(
            variant_document,
            pickups,
            deliveries,
            tile_classes=variant_classes,
            tile_flags=variant_flags,
        )
        changed = (diagnosis.code, tuple(sorted(diagnosis.corridor))) != reference
        return {
            "case": label,
            "tile": target_tile,
            "flags": target_flags,
            "assessment_code": diagnosis.code,
            "corridor": sorted(diagnosis.corridor),
            "verdict_changed": changed,
        }

    cases: list[dict] = []
    # (1) The six historically measured V1/V2 lifecycle alternates: apply the
    # retained tree/rough state for exactly the sealed temporal tiles, used as
    # probe states only (never planning input). The probe construction
    # assumes the lifecycle delta touches tree/rough only; other lifecyclable
    # same-API fields are asserted equal to the projected variant, failing
    # closed instead of silently no-op-ing the probe.
    for tile_id in sorted(temporal_tiles):
        retained_tile = retained_by_id.get(tile_id)
        if retained_tile is None:
            raise PlanningFactError(f"sealed temporal tile {tile_id} lacks retained facts")
        variant = census[tile_id].flags
        if retained_tile.tree:
            variant |= flag_bit("tree")
        else:
            variant &= ~flag_bit("tree")
        if retained_tile.rough:
            variant |= flag_bit("rough")
        else:
            variant &= ~flag_bit("rough")
        # Fail-closed probe-construction gate: outside tree/rough, the retained
        # same-API bitmask bits (from the census-side probe flags) must equal
        # the retained TileFact fields, so the measured alternate really is the
        # sealed delta and not a silently reduced diff.
        for field in ("water", "coast", "farm", "rock", "rail", "water_transport"):
            if bool(bit(variant, field)) != getattr(retained_tile, field):
                raise PlanningFactError(
                    f"sealed temporal delta on tile {tile_id} touches {field}; "
                    "the tree/rough-only probe is invalid (fail-closed)"
                )
        cases.append(run_case(f"temporal-measured:{tile_id}", tile_id, variant))
    # (2) Every census tree dies (observed lifecycle mechanism).
    for tile_id in sorted(census):
        if census[tile_id].classification == TileClass.TREES.value:
            cases.append(
                run_case(
                    f"tree-death:{tile_id}",
                    tile_id,
                    census[tile_id].flags & ~flag_bit("tree"),
                )
            )
    # (3) Tree spread onto every bare clear tile 8-adjacent to a census tree.
    tree_tiles = {tid for tid in census if census[tid].classification == TileClass.TREES.value}
    spread_targets: list[int] = []
    map_height = facts_document.source.map_height
    for tile_id in sorted(tree_tiles):
        x, y = tile_id % map_width, tile_id // map_width
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < map_width and 0 <= ny < map_height):
                    continue
                neighbor = ny * map_width + nx
                tile = census.get(neighbor)
                if tile is None or neighbor in tree_tiles:
                    continue
                fact = base_facts[neighbor]
                if any(
                    (
                        tile.industry_id is not None,
                        fact.water,
                        fact.coast,
                        fact.farm,
                        fact.rock,
                        fact.rough,
                        fact.road,
                        fact.rail,
                        fact.water_transport,
                        fact.air_transport,
                    )
                ):
                    continue
                spread_targets.append(neighbor)
    for tile_id in sorted(set(spread_targets)):
        cases.append(
            run_case(
                f"tree-spread:{tile_id}",
                tile_id,
                census[tile_id].flags | flag_bit("tree"),
            )
        )
    # (4) Tree spread onto every rough tile: a counterfactual co-occurrence
    # probe (tree-on-rough is NOT observed in either corpus; tree/rough
    # transitions are observed, co-occurrence is not).
    for tile_id in sorted(census):
        if census[tile_id].classification == TileClass.ROUGH.value:
            cases.append(
                run_case(
                    f"rough-spread:{tile_id}",
                    tile_id,
                    census[tile_id].flags | flag_bit("tree"),
                )
            )
    return cases


def build_v2_snapshot_assessment(
    retained_path: Path,
    candidate_dir: Path,
    *,
    project_root: Path | None = None,
) -> SnapshotAssessment:
    """Run the full offline snapshot-scoped P08 readiness pipeline."""

    root = project_root if project_root is not None else Path.cwd()
    replay = replay_retained_census(retained_path, candidate_dir)
    fused = json.loads((candidate_dir / "correspondence-verdict.json").read_bytes())
    gate = SnapshotGate(
        reconciliation_verdict=replay.verdict(),
        semantic_tiles=len(replay.semantic_tiles),
        temporal_tiles=len(replay.temporal_tiles),
        contradiction_tiles=len(replay.contradiction_tiles),
        unresolved_tiles=len(replay.unresolved_tiles),
        completeness_reproduced=replay.completeness_reproduced,
        manifest_verified=replay.manifest_verified,
        manifest_entries=replay.manifest_entries,
        hygiene_failures=replay.hygiene_failures,
        identity_failures=replay.identity_failures,
        retained_facts_sha256=replay.retained_facts_sha256,
        census_page_payload_sha256=replay.census_page_payload_sha256,
        fused_mode=str(fused.get("mode")),
        fused_status=str(fused.get("status")),
        fused_save_binding_sha256=str(fused.get("save_binding_sha256", "")),
    )
    problems = gate.failures()
    if problems:
        raise PlanningFactError(f"snapshot policy gate failed: {problems}")

    retained, census, bracket, page_count = _load_census(retained_path, candidate_dir)
    facts = {tid: tile.fact() for tid, tile in census.items()}
    disagreement_tiles = sorted(
        tid for tid, fact in facts.items() if projection_disagrees(fact, census[tid].flags)
    )
    if disagreement_tiles:
        raise PlanningFactError(
            f"native projection disagrees with the census mask on {disagreement_tiles[:8]}"
        )
    # The road_tile-bit projection coincides with the oracle's three-bit OR
    # only while no road_track/road_src_type row exists; verify, never assume.
    road_or_rows = sorted(
        tid
        for tid in census
        if bit(census[tid].flags, "road_track") or bit(census[tid].flags, "road_src_type")
    )
    if road_or_rows:
        raise PlanningFactError(
            "census carries road_track/road_src_type rows "
            f"{road_or_rows[:8]}; road_tile-only projection is unsupported (fail-closed)"
        )

    # Stop viability: native station-construction semantics on census facts,
    # equivalent to historical Vacant exactly on the census corpus (proven
    # below before any assessment consumes it).
    viable = {tid for tid in census if vacant(facts[tid])}
    if any(census[tid].owner != OWNER_UNOWNED_SENTINEL for tid in viable):
        raise PlanningFactError("stop-viable tile with a company owner; fail-closed")
    from app.simulation.openttd.v2_semantic_reconciliation import vacant_projection

    vac_divergent = [
        tid
        for tid in sorted(census)
        if vacant(facts[tid])
        != vacant_projection(census[tid].slope, census[tid].owner, census[tid].flags)
    ]
    if vac_divergent:
        raise PlanningFactError(
            f"stop semantics diverge from the sealed Vacant projection on {vac_divergent[:8]}"
        )

    # Coverage geometry recomputation + historical-capture equality gate.
    scopes = [(scope.role, scope.industry_id, scope.cargo_id) for scope in retained.coverage_scopes]
    if tuple(sorted(scopes)) != EXPECTED_CAPABILITY_SCOPES:
        raise PlanningFactError(f"unexpected capability scopes: {tuple(sorted(scopes))}")
    industry_sites: dict[int, tuple[int, ...]] = {}
    for tid in sorted(census):
        industry = census[tid].industry_id
        if industry in (0, 1):
            industry_sites[industry] = (*industry_sites.get(industry, ()), tid)
    missing_sites = [industry for industry in (0, 1) if industry not in industry_sites]
    if missing_sites:
        raise PlanningFactError(
            f"census lacks capability industry sites {missing_sites} (fail-closed)"
        )
    coverage: list[CoverageFact] = []
    catchments: dict[tuple[str, int, int], frozenset[int]] = {}
    for role, industry_id, cargo_id in sorted(scopes):
        catchment = _disc_catchment(
            industry_sites[industry_id],
            set(census),
            retained.source.map_width,
            retained.source.map_height,
        )
        captured = {
            row.tile_id
            for row in retained.coverage
            if (row.industry_id, row.cargo_id, row.role) == (industry_id, cargo_id, role)
            and row.industry_covered
        }
        if catchment != captured:
            raise PlanningFactError(
                "coverage geometry drift: recomputed catchment does not equal the "
                "historical industry_covered capture (fail-closed, no quantity reuse)"
            )
        catchments[(role, industry_id, cargo_id)] = frozenset(catchment)
        for tid in sorted(census):
            coverage.append(
                CoverageFact(
                    tile_id=tid,
                    industry_id=industry_id,
                    cargo_id=cargo_id,
                    role=role,
                    producer_count=0,
                    acceptance_eighths=0,
                    industry_covered=tid in catchment,
                )
            )

    source = _snapshot_source(retained, gate, candidate_dir, root)
    facts_document = SupplementalPlanningFacts(
        schema_version=1,
        transport_mode="road",
        source=source,
        region=retained.region,
        settings=retained.settings,
        road=retained.road,
        tiles=tuple(facts[tid] for tid in sorted(facts)),
        coverage_scopes=retained.coverage_scopes,
        coverage=tuple(coverage),
        engines=retained.engines,
        capture_economy_date_before=bracket[0],
        capture_economy_date_after=bracket[1],
    )
    facts_document_digest = hashlib.sha256(
        json.dumps(json.loads(facts_document.model_dump_json()), sort_keys=True).encode()
    ).hexdigest()

    pickups = tuple(sorted(tid for tid in viable if tid in catchments[("pickup", 0, 1)]))
    deliveries = tuple(sorted(tid for tid in viable if tid in catchments[("delivery", 1, 1)]))
    if not pickups or not deliveries:
        raise PlanningFactError("no viable stop in a required catchment")

    # Endpoint variant B: historical eligibility structure (capability + the
    # historical quantity capture) used only as an endpoint set definition,
    # with every endpoint re-validated stop-viable at the census instant.
    retained_pickup_ids = {
        row.tile_id
        for row in retained.coverage
        if (row.industry_id, row.cargo_id, row.role) == (0, 1, "pickup")
        and row.industry_covered
        and row.producer_count > 0
    }
    retained_delivery_ids = {
        row.tile_id
        for row in retained.coverage
        if (row.industry_id, row.cargo_id, row.role) == (1, 1, "delivery")
        and row.industry_covered
        and row.acceptance_eighths >= 8
    }
    revalidated_pickups = tuple(sorted(retained_pickup_ids & viable))
    revalidated_deliveries = tuple(sorted(retained_delivery_ids & viable))
    revalidated_diagnosis: FeasibilityDiagnosis | None = None
    if revalidated_pickups and revalidated_deliveries:
        revalidated_diagnosis = _assessment(
            facts_document,
            revalidated_pickups,
            revalidated_deliveries,
            census,
        )

    primary = _assessment(facts_document, pickups, deliveries, census)
    levelling: TerrainOutcome | None = plan_bounded_levelling(facts_document, pickups, deliveries)

    robustness = _robustness(
        census,
        facts_document,
        replay.temporal_tiles,
        retained,
        pickups,
        deliveries,
        primary,
        retained.source.map_width,
    )
    deviations = [case for case in robustness if case["verdict_changed"]]
    robust_verdict = "ROBUST" if not deviations else f"SENSITIVE: {len(deviations)} case(s)"

    return SnapshotAssessment(
        policy_version=POLICY_VERSION,
        gate=gate,
        census_bracket=bracket,
        census_pages=page_count,
        census_tiles=len(census),
        projection_disagreements=len(disagreement_tiles),
        stop_viable_tiles=len(viable),
        eligible_pickups=pickups,
        eligible_deliveries=deliveries,
        revalidated_endpoints_pickups=revalidated_pickups,
        revalidated_endpoints_deliveries=revalidated_deliveries,
        vac_semantic_divergent_tiles=len(vac_divergent),
        primary=primary,
        revalidated=revalidated_diagnosis,
        levelling=levelling,
        robustness=tuple(robustness),
        robustness_verdict=robust_verdict,
        facts_source=source,
        digest_semantics=DIGEST_SEMANTICS,
        facts_document_digest=facts_document_digest,
    )


def _assessment(
    facts_document: SupplementalPlanningFacts,
    pickups: tuple[int, ...],
    deliveries: tuple[int, ...],
    census: dict[int, CensusTile],
) -> FeasibilityDiagnosis:
    return assess_world_feasibility(
        facts_document,
        pickups,
        deliveries,
        tile_classes={tid: tile.classification for tid, tile in census.items()},
        tile_flags={tid: tile.flags for tid, tile in census.items()},
    )


def main(argv: list[str] | None = None) -> int:
    """Write the derived snapshot assessment; never touches retained inputs."""

    parser = argparse.ArgumentParser(description="offline V2 snapshot P08 assessment")
    parser.add_argument("retained_facts")
    parser.add_argument("candidate_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args(argv)
    assessment = build_v2_snapshot_assessment(
        Path(args.retained_facts),
        Path(args.candidate_dir),
        project_root=Path(args.project_root) if args.project_root else None,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "snapshot-assessment-report.json").write_bytes(assessment.to_json_bytes())
    primary = assessment.primary
    print(
        f"policy={POLICY_VERSION} gate={assessment.gate.reconciliation_verdict} "
        f"semantic={assessment.gate.semantic_tiles} temporal={assessment.gate.temporal_tiles} "
        f"assessment_code={primary.code} corridor={len(primary.corridor)} "
        f"levelling={type(assessment.levelling).__name__} "
        f"robustness={assessment.robustness_verdict} "
        f"facts_digest={assessment.facts_document_digest[:12]}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
