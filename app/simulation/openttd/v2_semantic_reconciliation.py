"""Offline V1/V2 semantic reconciliation for the Tile Classification V2 census.

Policy ``vacant-projection-1`` (derived from
``docs/p08-v1v2-semantic-provenance-diagnosis.md``; the strict sealed coherence
gate and the sealed native verdict are read-only here and stay untouched).

Concept mapping enforced by the policy:

* ``water/coast/tree/farm/rock/rough/rail/water_transport`` are the *same*
  native ``GSTile`` calls in both the retained schema-1 producer
  (``freight_delivery_package/planner.nut``) and the schema-2 bridge, so any
  difference is a state difference, never semantics: bit-for-bit compare with
  ``TEMPORAL_SECOND_INSTANT`` attribution when the capture instants differ,
  and ``GENUINE_CONTRADICTION`` when both records claim the same instant
  (same-state differences must not be silently absorbed).
* ``road`` in both records is ``GSRoad.IsRoadTile``; the raw gate's OR of
  ``road_track``/``road_src_type`` is deliberately not the V1 concept (those
  schema-2-only bits have no V1 counterpart and enter solely through the
  Vacant exclusion).
* ``air_transport`` uses ``GSTile.HasTransportType(TRANSPORT_AIR)`` on the V1
  side and ``GSAirport.IsAirportTile`` on the V2 side: two distinct native
  predicates whose equality was observed on the full corpus but is not
  guaranteed. Any mismatch is ``UNRESOLVED_DISTINCT_PREDICATE``: unresolved
  evidence that blocks a binding verdict rather than being reinterpreted.
* ``buildable`` in the retained record is the planner producer's ``Vacant(t)``
  (flat, unowned, bare ground) while the schema-2 bit is
  ``GSTile.IsBuildable`` (verified for OpenTTD 15.3 sources: true for
  ``MP_CLEAR``, ``MP_TREES``, coasts and town/own single-bit normal roads).
  The rule rebuilds the V1 projection from the schema-2 mask and records the
  accepted transformation ``SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE`` for the
  raw disagreements it explains; it never weakens the raw gate.

Same-state is enforced by verdict, not by reinterpretation: any
shared-predicate second-instant difference keeps the fusion gate closed, P08
stays unbound (``INCOMPLETE_TILE_CLASSIFICATION`` preserved) and the report
states the minimum additional evidence required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.simulation.openttd.supplemental_planning_facts import (
    SupplementalPlanningFacts,
    TileFact,
)
from app.simulation.openttd.tile_classification import (
    TileClassificationExchange,
    TileClassificationFact,
    TileClassificationReceipt,
    TileClassificationResponse,
    TileClassificationSweep,
    classification_plan,
    flags_index,
    projection_disagrees,
)
from app.simulation.openttd.tile_facts import TileFailure, TileQueryError

POLICY_VERSION = "vacant-projection-1"

RECONCILED = "SEMANTIC_RECONCILED"
TEMPORAL = "TEMPORAL_SECOND_INSTANT"
CONTRADICTION = "GENUINE_CONTRADICTION"
UNRESOLVED = "UNRESOLVED_DISTINCT_PREDICATE"
SEMANTIC_BUILDABLE_ACCEPTANCE = "SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE"

VERDICT_ESTABLISHED = "CORRESPONDENCE_ESTABLISHED"
VERDICT_PARTIAL = "SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED"
VERDICT_REJECTED = "REJECTED"

# Schema-2 owner sentinel for "no valid ownable owner" on the wire. The native
# GS ``GetOwner`` maps OWNER_NONE/OWNER_TOWN/... to ``COMPANY_INVALID`` and the
# classification bridge serializes that as -1.
OWNER_UNOWNED_SENTINEL = -1

SAME_API_FIELDS = (
    # Identical native predicate on both producers, hence equal-by-state.
    "water",
    "coast",
    "tree",
    "farm",
    "rock",
    "rough",
    "rail",
    "water_transport",
    # Identical ``GSRoad.IsRoadTile`` call on both sides; ``road_track`` and
    # ``road_src_type`` have no V1 counterpart (Vacant exclusion only).
    "road",
)
VACANT_EXCLUDED_BIT_NAMES = (
    "water",
    "coast",
    "tree",
    "farm",
    "rock",
    "rough",
    "road_tile",
    "road_track",
    "rail",
    "water_transport",
    "house",
    "station",
    # The planner excluded ``HasTransportType(TRANSPORT_AIR)``; the schema-2
    # mask carries the nearest concept ``GSAirport.IsAirportTile`` instead.
    # The projection is provably equivalent either way: an airport tile is an
    # ``MP_STATION`` tile and native ``IsBuildable`` is false for stations, so
    # the planner's Vacant was false there too.
    "airport",
)
DISTINCT_PREDICATE_FIELDS = (
    # V1 ``HasTransportType(TRANSPORT_AIR)`` vs V2 ``IsAirportTile``.
    "air_transport",
)


def bit(flags: int, name: str) -> bool:
    return bool(flags & (1 << flags_index(name)))


def vacant_projection(slope: int, owner: int, flags: int) -> bool:
    """Rebuild the retained producer's ``Vacant(t)`` from the schema-2 mask."""

    if not bit(flags, "buildable") or slope != 0 or owner != OWNER_UNOWNED_SENTINEL:
        return False
    return not any(bit(flags, name) for name in VACANT_EXCLUDED_BIT_NAMES)


@dataclass(frozen=True)
class FieldOutcome:
    """One compared concept between one retained fact and its census row."""

    field: str
    retained_value: bool
    census_value: bool
    outcome: str


@dataclass(frozen=True)
class TileReconciliation:
    """Decision ledger for one tile under policy ``vacant-projection-1``."""

    tile_id: int
    raw_gate_disagrees: bool
    status: str
    field_outcomes: tuple[FieldOutcome, ...]


@dataclass(frozen=True)
class SameStateProvenance:
    """Capture-instant provenance for the same-state verdict determination.

    The native census takes several economy real-time seconds, so each page is
    its own single-instant observation (``date_before == date_after`` per
    page); pages together span a small census window. A shared-predicate
    difference is a same-state contradiction only when the observed page
    instant falls inside the retained capture window; otherwise the two
    records describe different states at different instants.
    """

    census_page_dates: tuple[int, ...]
    retained_date_before: int
    retained_date_after: int

    def within_window(self, census_date: int) -> bool:
        return self.retained_date_before <= census_date <= self.retained_date_after

    @property
    def census_span(self) -> tuple[int, int]:
        if not self.census_page_dates:
            return (0, 0)
        return (min(self.census_page_dates), max(self.census_page_dates))

    @property
    def same_instant(self) -> bool:
        low, high = self.census_span
        return self.within_window(low) and self.within_window(high)

    def detail(self) -> dict:
        low, high = self.census_span
        return {
            "census_page_economy_dates": {
                "count": len(self.census_page_dates),
                "min": low,
                "max": high,
            },
            "retained_capture_economy_dates": [
                self.retained_date_before,
                self.retained_date_after,
            ],
            "census_window_inside_retained_capture_window": self.same_instant,
        }


def _shared_field_outcomes(
    fact: TileFact, flags: int, provenance: SameStateProvenance, census_date: int
) -> list[FieldOutcome]:
    outcomes: list[FieldOutcome] = []
    for field in SAME_API_FIELDS:
        bit_name = "road_tile" if field == "road" else field
        census_value = bit(flags, bit_name)
        retained_value = getattr(fact, field)
        if retained_value != census_value:
            outcomes.append(
                FieldOutcome(
                    field=field,
                    retained_value=retained_value,
                    census_value=census_value,
                    outcome=CONTRADICTION if provenance.within_window(census_date) else TEMPORAL,
                )
            )
    for field in DISTINCT_PREDICATE_FIELDS:
        census_value = bit(flags, "airport")
        retained_value = getattr(fact, field)
        if retained_value != census_value:
            outcomes.append(
                FieldOutcome(
                    field=field,
                    retained_value=retained_value,
                    census_value=census_value,
                    # Distinct predicates: unresolved evidence, never rewritten.
                    outcome=UNRESOLVED,
                )
            )
    return outcomes


def reconcile_tile(
    fact: TileFact,
    flags: int,
    slope: int,
    owner: int,
    census_date: int,
    provenance: SameStateProvenance,
) -> TileReconciliation:
    """Reconcile one retained TileFact against its schema-2 census row."""

    outcomes = _shared_field_outcomes(fact, flags, provenance, census_date)
    projected = vacant_projection(slope, owner, flags)
    raw_buildable = bit(flags, "buildable") and not (bit(flags, "house") or bit(flags, "station"))
    if projected != fact.buildable:
        if any(o.outcome in (TEMPORAL, CONTRADICTION) for o in outcomes):
            inferring = CONTRADICTION if provenance.within_window(census_date) else TEMPORAL
        else:
            # No state difference in any shared predicate: an unexplained
            # buildable residual between the pinned producer and the
            # same-state mask contradicts the claims instead of reconciling.
            inferring = CONTRADICTION
        outcomes.append(
            FieldOutcome(
                field="buildable",
                retained_value=fact.buildable,
                census_value=projected,
                outcome=inferring,
            )
        )
    elif raw_buildable != fact.buildable:
        # The raw coherence gate flagged this tile only on ``buildable``: the
        # policy accepts the recorded definitional projection (Vacant) and the
        # transformation is spelled out per tile.
        outcomes.append(
            FieldOutcome(
                field="buildable",
                retained_value=fact.buildable,
                census_value=projected,
                outcome=SEMANTIC_BUILDABLE_ACCEPTANCE,
            )
        )

    places = {o.outcome for o in outcomes}
    if UNRESOLVED in places:
        status = UNRESOLVED
    elif CONTRADICTION in places:
        status = CONTRADICTION
    elif TEMPORAL in places:
        status = TEMPORAL
    else:
        status = RECONCILED
    return TileReconciliation(
        tile_id=fact.tile_id,
        raw_gate_disagrees=projection_disagrees(fact, flags),
        status=status,
        field_outcomes=tuple(sorted(outcomes, key=lambda o: o.field)),
    )


@dataclass(frozen=True)
class SemanticReconciliation:
    """Derived correspondence verdict under policy ``vacant-projection-1``."""

    policy_version: str
    retained_facts_sha256: str
    census_page_payload_sha256: str
    provenance: SameStateProvenance
    region: tuple[int, int, int, int]
    census_pages: int
    census_tiles: int
    census_class_counts: dict[str, int]
    retained_class_counts: dict[str, int]
    identity_failures: tuple[tuple[int, str], ...]
    hygiene_failures: tuple[str, ...]
    raw_gate_tiles: tuple[tuple[int, str], ...]
    tiles: tuple[TileReconciliation, ...]
    completeness_reproduced: bool
    manifest_verified: bool
    manifest_entries: int
    semantic_tiles: tuple[int, ...]
    temporal_tiles: tuple[int, ...]
    contradiction_tiles: tuple[int, ...]
    unresolved_tiles: tuple[int, ...]

    # --- derived fragments -------------------------------------------------

    @property
    def same_state_failing_tiles(self) -> tuple[int, ...]:
        return tuple(t.tile_id for t in self.tiles if t.status == TEMPORAL)

    def verdict(self) -> str:
        if self.identity_failures or self.hygiene_failures:
            return VERDICT_REJECTED
        if not self.completeness_reproduced:
            # The pages and the complements are manifest-pinned together; a
            # non-reproducing seal means an inconsistent sealed candidate and
            # must fail closed instead of describing a derived verdict.
            return VERDICT_REJECTED
        if self.contradiction_tiles or self.unresolved_tiles:
            return VERDICT_REJECTED
        if self.temporal_tiles:
            return VERDICT_PARTIAL
        return VERDICT_ESTABLISHED

    def p08_binding(self) -> dict:
        """P08 assessment gate: only binds on a fully established verdict."""

        complete = self.verdict() == VERDICT_ESTABLISHED
        return {
            "allowed": complete,
            "reason": None
            if complete
            else (
                "same-state provenance incomplete: second-instant tiles"
                if self.temporal_tiles
                else (
                    "contradictions present" if self.contradiction_tiles else "unresolved present"
                )
                if (self.contradiction_tiles or self.unresolved_tiles)
                else "identity or census hygiene failures"
            ),
            "preserved_retained_status": None if complete else "INCOMPLETE_TILE_CLASSIFICATION",
        }

    def minimum_additional_evidence(self) -> list[str]:
        failing = list(self.same_state_failing_tiles)
        if not failing:
            return []
        failing.sort()
        return [
            "a bounded, separately-authorized same-instant native re-observation "
            "(single census with date_before == date_after) of tiles "
            f"{failing}, and/or",
            "an explicit operator policy decision declaring the save-instant "
            "census authoritative for those tiles' tree-lifecycle deltas, "
            "sealed in a new reviewed candidate under a fresh authorization",
        ]

    def report(self) -> dict:
        temporal_detail = {
            str(t.tile_id): [
                {
                    "field": o.field,
                    "retained_value": o.retained_value,
                    "census_value": o.census_value,
                    "outcome": o.outcome,
                }
                for o in t.field_outcomes
            ]
            for t in self.tiles
            if t.tile_id in set(self.temporal_tiles)
        }
        semantic_detail = {
            str(t.tile_id): sorted(
                o.field for o in t.field_outcomes if o.outcome == SEMANTIC_BUILDABLE_ACCEPTANCE
            )
            for t in self.tiles
            if t.tile_id in set(self.semantic_tiles)
        }
        verdict = self.verdict()
        binding = self.p08_binding()
        return {
            "schema": "v1v2-semantic-reconciliation-report/1",
            "policy_version": self.policy_version,
            "offline_only": True,
            "sources": {
                "retained_facts_sha256": self.retained_facts_sha256,
                "census_page_payload_sha256": self.census_page_payload_sha256,
                "region": list(self.region),
                "census_pages": self.census_pages,
                "census_tiles": self.census_tiles,
                "census_class_counts": dict(sorted(self.census_class_counts.items())),
                "retained_class_counts": dict(sorted(self.retained_class_counts.items())),
                "sealed_completeness_reproduced": self.completeness_reproduced,
                "artifact_manifest_verified": self.manifest_verified,
                "artifact_manifest_entries": self.manifest_entries,
                "identity_failures": [list(f) for f in self.identity_failures],
                "census_hygiene_failures": list(self.hygiene_failures),
                "provenance": self.provenance.detail(),
            },
            "raw_gate": {
                "disagreement_tiles": len(self.raw_gate_tiles),
                "tile_ids": [tile for tile, _ in self.raw_gate_tiles],
                "code": self.raw_gate_tiles[0][1] if self.raw_gate_tiles else None,
            },
            "policy_verdict": {
                "reconciled_definitional": {
                    "count": len(self.semantic_tiles),
                    "tile_ids": list(self.semantic_tiles),
                    "transformation": SEMANTIC_BUILDABLE_ACCEPTANCE,
                    "field_detail": semantic_detail,
                },
                "temporal_second_instant": {
                    "count": len(self.temporal_tiles),
                    "tile_ids": list(self.temporal_tiles),
                    "fused": False,
                    "field_detail": temporal_detail,
                },
                "genuine_contradictions": {
                    "count": len(self.contradiction_tiles),
                    "tile_ids": list(self.contradiction_tiles),
                },
                "unresolved_distinct_predicate": {
                    "count": len(self.unresolved_tiles),
                    "tile_ids": list(self.unresolved_tiles),
                    "field": "air_transport",
                },
            },
            "same_state": {
                "same_instant": self.provenance.same_instant,
                "failing_tiles": list(self.same_state_failing_tiles),
                "minimum_additional_evidence": self.minimum_additional_evidence(),
            },
            "verdict": verdict,
            "p08_binding": binding,
            "tile_ledger": {
                str(t.tile_id): {
                    "raw_gate_disagrees": t.raw_gate_disagrees,
                    "status": t.status,
                    "field_outcomes": [
                        {
                            "field": o.field,
                            "retained_value": o.retained_value,
                            "census_value": o.census_value,
                            "outcome": o.outcome,
                        }
                        for o in t.field_outcomes
                    ],
                }
                for t in sorted(self.tiles, key=lambda t: t.tile_id)
            },
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


def completeness_indicator(candidate_dir: Path) -> bool | None:
    """Sealed ``world_identity_mismatch`` from the candidate completeness file."""

    completeness = json.loads((candidate_dir / "classification-completeness.json").read_bytes())
    return completeness.get("world_identity_mismatch")


def _rebuild_sweep(
    retained_path: Path, candidate_dir: Path
) -> tuple[
    SupplementalPlanningFacts,
    TileClassificationSweep,
    tuple[TileClassificationExchange, ...],
    str,
]:
    """Rebuild the sealed census from candidate page payloads, read-only.

    Returns the retained facts, the receipt-bound sweep (band-level, as the
    sealed sweep is structured) and the per-page exchange payloads whose
    responses are themselves single-instant observations.
    """

    retained_bytes = retained_path.read_bytes()
    retained = SupplementalPlanningFacts.model_validate_json(retained_bytes)
    candidate = json.loads((candidate_dir / "CANDIDATE.json").read_bytes())
    requirements = candidate.get("world_identity_requirements")
    if (
        not isinstance(requirements, dict)
        or requirements.get("retained_facts_sha256") != hashlib.sha256(retained_bytes).hexdigest()
    ):
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    first_request = json.loads((candidate_dir / "classification-p000-request.json").read_bytes())
    if not isinstance(first_request, dict) or not isinstance(first_request.get("request_id"), str):
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    requests = classification_plan(retained.region, first_request["request_id"])
    exchanges: list[TileClassificationExchange] = []
    page_digest = hashlib.sha256()
    for ordinal, request in enumerate(requests):
        stored_request_bytes = (
            candidate_dir / f"classification-p{ordinal:03d}-request.json"
        ).read_bytes()
        if stored_request_bytes != request.to_bytes():
            raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
        response_bytes = (
            candidate_dir / f"classification-p{ordinal:03d}-response.json"
        ).read_bytes()
        page_digest.update(response_bytes)
        receipt = TileClassificationReceipt.correlate(request.to_bytes(), response_bytes)
        exchanges.append(
            TileClassificationExchange(
                request_payload=request.to_bytes(),
                response_payload=response_bytes,
                receipt=receipt,
            )
        )
    # The sealed sweep observed exactly the pinned welcome values (its sealed
    # ``world_identity_mismatch`` was False), so an offline rebuild reuses the
    # pinned values on both sides of the identity gate; the assertion below
    # requires that sealed fact instead of merely assuming it.
    if completeness_indicator(candidate_dir) is not False:
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    welcome = requirements.get("retained_welcome")
    if welcome is None:
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    sweep = TileClassificationSweep.record(
        tuple(requests),
        tuple(exchanges),
        retained_facts=retained,
        retained_facts_digest=requirements["retained_facts_sha256"],
        retained_welcome=welcome,
        observed_welcome=welcome,
    )
    return retained, sweep, tuple(exchanges), page_digest.hexdigest()


def _census_hygiene(
    pages: tuple[TileClassificationResponse, ...],
) -> tuple[str, ...]:
    """Per-page single-instant stamps and full-census coverage invariants."""

    hygiene: list[str] = []
    seen: set[int] = set()
    for ordinal, page in enumerate(pages):
        if page.date_before != page.date_after:
            hygiene.append(f"CENSUS_PAGE_INSTANCE_NOT_IMMEDIATE:page{ordinal}")
        for tile, _cls, _industry, _owner in page.classification:
            if tile in seen:
                hygiene.append(f"CENSUS_TILE_DUPLICATED:{tile}")
                continue
            seen.add(tile)
    return tuple(hygiene)


def _verify_manifest(candidate_dir: Path) -> tuple[bool, int]:
    """Verify the candidate's frozen artifact manifest in place (read only)."""

    path = candidate_dir / "artifact-manifest.sha256"
    if not path.exists():
        return False, 0
    verified = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry_digest, _, name = line.partition("  ")
        target = candidate_dir / name
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != entry_digest:
            return False, verified
        verified += 1
    return True, verified


def replay_retained_census(retained_path: Path, candidate_dir: Path) -> SemanticReconciliation:
    """Deterministic offline replay of the retained census under the policy."""

    retained, sweep, exchanges, page_digest = _rebuild_sweep(retained_path, candidate_dir)
    pages = tuple(exchange.response for exchange in exchanges)
    hygiene = list(_census_hygiene(pages))
    manifest_verified, manifest_entries = _verify_manifest(candidate_dir)
    if not manifest_verified:
        hygiene = hygiene + ["CANDIDATE_MANIFEST_UNVERIFIED"]
    provenance = SameStateProvenance(
        census_page_dates=tuple(page.date_before for page in pages),
        retained_date_before=retained.capture_economy_date_before,
        retained_date_after=retained.capture_economy_date_after,
    )

    completeness = json.loads((candidate_dir / "classification-completeness.json").read_bytes())
    sealed_failures = sorted(tuple(x) for x in completeness["coherence_failures"])
    rebuilt = sorted(tuple(f) for f in sweep.coherence_failures if f[1] == "PROJECTED_FLAGS_DIFFER")
    other_failures = tuple(
        sorted(f for f in sweep.coherence_failures if f[1] != "PROJECTED_FLAGS_DIFFER")
    )
    if "class_counts" not in completeness:
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    class_counts = {k: sweep.class_counts.get(k, 0) for k in completeness["class_counts"]}
    completeness_reproduced = (
        rebuilt == sealed_failures
        and class_counts == completeness["class_counts"]
        and completeness.get("unknown_tiles", []) == list(sweep.unknown_tiles)
        and completeness.get("bound") == sweep.bound
        and completeness.get("pages") == sweep.pages
        and completeness.get("region")
        == [
            retained.region.x,
            retained.region.y,
            retained.region.width,
            retained.region.height,
        ]
    )

    fact_by_id = {fact.tile_id: fact for fact in retained.tiles}
    census_by_id: dict[int, tuple[int, TileClassificationFact]] = {}
    for ordinal, page in enumerate(pages):
        geometry = page.geometry
        for tile, cls, industry, owner in page.classification:
            if tile in census_by_id:
                continue  # duplicates are hygiene failures above
            elevation, slope, flags = geometry[tile]
            census_by_id[tile] = (
                ordinal,
                TileClassificationFact(
                    tile_id=tile,
                    x=tile % page.map_width,
                    y=tile // page.map_width,
                    min_height=elevation,
                    slope=slope,
                    tile_class=cls,
                    flags=flags,
                    industry_id=industry,
                    owner=owner,
                ),
            )

    reconciliations: list[TileReconciliation] = []
    semantic: list[int] = []
    temporal: list[int] = []
    contradiction: list[int] = []
    unresolved: list[int] = []
    for tile_id in sorted(census_by_id):
        fact = fact_by_id.get(tile_id)
        if fact is None:
            continue  # stays visible as the sweep's TILE_FACT_MISSING failure
        ordinal, observation = census_by_id[tile_id]
        tile_reconciliation = reconcile_tile(
            fact,
            flags=observation.flags,
            slope=observation.slope,
            owner=observation.owner,
            census_date=provenance.census_page_dates[ordinal],
            provenance=provenance,
        )
        reconciliations.append(tile_reconciliation)
        if tile_reconciliation.status == RECONCILED:
            # Accepted definitional transformations are meaningful only where
            # the raw coherence gate actually flagged the tile.
            if tile_reconciliation.raw_gate_disagrees:
                semantic.append(tile_id)
        else:
            # Verdict buckets track the policy ledger statuses, so
            # ``same_state_failing_tiles`` can never contradict the buckets
            # even for exotic shapes where the raw gate and the policy disagree.
            bucket = {
                TEMPORAL: temporal,
                CONTRADICTION: contradiction,
                UNRESOLVED: unresolved,
            }[tile_reconciliation.status]
            bucket.append(tile_id)

    from app.planning.p08_terrain import _legacy_segment

    retained_class_counts = dict(
        sorted(Counter(str(_legacy_segment(fact)[0]) for fact in retained.tiles).items())
    )
    census_class_counts = dict(
        sorted(
            Counter(
                observation.tile_class.value for _, observation in census_by_id.values()
            ).items()
        )
    )

    return SemanticReconciliation(
        policy_version=POLICY_VERSION,
        retained_facts_sha256=hashlib.sha256(retained_path.read_bytes()).hexdigest(),
        census_page_payload_sha256=page_digest,
        provenance=provenance,
        region=(
            retained.region.x,
            retained.region.y,
            retained.region.width,
            retained.region.height,
        ),
        census_pages=len(pages),
        census_tiles=len(census_by_id),
        census_class_counts=census_class_counts,
        retained_class_counts=retained_class_counts,
        identity_failures=other_failures,
        hygiene_failures=tuple(hygiene),
        raw_gate_tiles=tuple(rebuilt),
        tiles=tuple(reconciliations),
        completeness_reproduced=completeness_reproduced,
        manifest_verified=manifest_verified,
        manifest_entries=manifest_entries,
        semantic_tiles=tuple(sorted(semantic)),
        temporal_tiles=tuple(sorted(temporal)),
        contradiction_tiles=tuple(sorted(contradiction)),
        unresolved_tiles=tuple(sorted(unresolved)),
    )


def main(argv: list[str] | None = None) -> int:
    """Write the derived reconciliation report; never touches retained inputs."""

    parser = argparse.ArgumentParser(description="offline V1/V2 semantic reconciliation replay")
    parser.add_argument("retained_facts")
    parser.add_argument("candidate_dir")
    parser.add_argument("output_dir")
    args = parser.parse_args(argv)
    reconciliation = replay_retained_census(Path(args.retained_facts), Path(args.candidate_dir))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "reconciliation-report.json").write_bytes(reconciliation.to_json_bytes())
    print(
        f"policy={reconciliation.policy_version} verdict={reconciliation.verdict()} "
        f"raw_gate={len(reconciliation.raw_gate_tiles)} "
        f"definitional={len(reconciliation.semantic_tiles)} "
        f"temporal={len(reconciliation.temporal_tiles)} "
        f"contradictions={len(reconciliation.contradiction_tiles)} "
        f"unresolved={len(reconciliation.unresolved_tiles)} "
        f"manifest={reconciliation.manifest_verified}/{reconciliation.manifest_entries} "
        f"completeness_reproduced={reconciliation.completeness_reproduced}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
