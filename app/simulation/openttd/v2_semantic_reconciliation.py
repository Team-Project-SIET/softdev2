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
from collections.abc import Mapping
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
VERDICT_POLICY_RESOLVED = "SEMANTIC_RECONCILED_CENSUS_AUTHORITATIVE_TEMPORAL"
POLICY_REPORT_SCHEMA = "v1v2-census-authority-policy-report/1"
REBINDING_REPORT_SCHEMA = "v1v2-p08-policy-rebinding/1"

# Operator-approved ADR-013 (2026-10-25): adopt native ``IsBuildable``
# semantics for exactly the 19 definitional retained-UNKNOWN tiles and map
# them to ``TERRAIN_MODIFICATION`` for derived P08 planning. The scope is
# embedded because the authorization is exact: a different tile set is never
# silently accepted.
NATIVE_ISBUILDABLE_DECISION_ADR = "ADR-013"
NATIVE_ISBUILDABLE_DECISION_TOKEN = "NATIVE_ISBUILDABLE_DEFINITIONAL_SEMANTICS"
NATIVE_ISBUILDABLE_RESOLVED_OUTCOME = "NATIVE_ISBUILDABLE_TERRAIN_MODIFICATION"
NATIVE_ISBUILDABLE_POLICY_REPORT_SCHEMA = "v1v2-native-isbuildable-policy-report/1"
NATIVE_ISBUILDABLE_REBINDING_REPORT_SCHEMA = (
    "v1v2-p08-native-isbuildable-rebinding/1"
)
NATIVE_ISBUILDABLE_VERDICT = "SEMANTIC_RECONCILED_NATIVE_ISBUILDABLE"
NATIVE_ISBUILDABLE_DECISION_DATE = "2026-10-25"
NATIVE_ISBUILDABLE_CENSUS_INSTANT = 712225
NATIVE_ISBUILDABLE_SCOPE_TILES = frozenset(
    {
        46517,
        46518,
        46772,
        47027,
        47028,
        47282,
        47283,
        47538,
        47793,
        48049,
        48304,
        48305,
        48554,
        48555,
        48556,
        48557,
        48558,
        48559,
        48560,
    }
)
NATIVE_ISBUILDABLE_BASE_COUNTS = {
    "ROAD_BUILDABLE": 339,
    "SUPPORTED_CLEARING": 63,
    "UNKNOWN_OCCUPANCY": 19,
    "UNSUPPORTED_CONSTRUCTION": 29,
}
NATIVE_ISBUILDABLE_DERIVED_CLASS = "TERRAIN_MODIFICATION"

# Delegated operator decision recorded as ADR-012 (see
# docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md): the
# six second-instant tiles' tree-lifecycle deltas are authoritative-census
# for planning evidence. The code below never embeds the tiles: the caller
# must pass the exact decision scope and it is validated fail-closed against
# the reconciliation itself.
AUTHORITY_DECISION_ADR = "ADR-012"
AUTHORITY_DECISION_TOKEN = "AUTHORITATIVE_CENSUS_TREE_LIFECYCLE"
AUTHORITY_RESOLVED_OUTCOME = "AUTHORITY_ACCEPTED_TEMPORAL"
AUTHORITY_SCOPE_FIELDS = frozenset({"tree", "rough", "buildable", "road"})

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
    # Additive, derived provenance: (tile_id, page_date_before, page_date_after)
    # for every censused tile, taken verbatim from the sealed page responses.
    # Used by the census-authority layer; empty only for hand-built test
    # instances that have no sealed candidate behind them.
    census_tile_instants: tuple[tuple[int, int, int], ...] = ()

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


@dataclass(frozen=True)
class CensusAuthorityDecision:
    """Explicit decision token that applies ADR-012 to a reconciliation.

    The token carries the operator-delegated decision (ADR-012, 2026-10-24,
    see ``docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md``)
    and the caller-declared scope. Nothing is applied automatically: the
    application layer validates the scope against the reconciliation and
    refuses everything else (fail-closed, scope-contained). The decision also
    does not establish which tile was observed on which page: the caller must
    supply the per-tile census-page instants from the sealed responses, and
    each one is re-checked to be a single instant.
    """

    adr: str = AUTHORITY_DECISION_ADR
    decision: str = AUTHORITY_DECISION_TOKEN
    scope_tiles: frozenset[int] = frozenset()
    acceptable_fields: frozenset[str] = frozenset({"tree", "rough", "buildable"})
    date: str = "2026-10-24"


@dataclass(frozen=True)
class AuthorityTileResult:
    """Derived policy row for one scope tile: evidence preserved verbatim."""

    tile_id: int
    accepted: bool
    refusal: str | None
    field_results: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class PolicyAppliedReconciliation:
    """Derived, separately-labeled verdict layer over an untouched base.

    The base :class:`SemanticReconciliation` (its statuses, its report, its
    sealed-provenance claims) is never modified and is embedded verbatim. This
    layer records which exact field outcomes the delegated decision accepts
    for planning purposes and what remains blocked.
    """

    decision: CensusAuthorityDecision
    base: SemanticReconciliation
    resolved_field_rows: tuple[tuple[int, dict[str, object]], ...]
    refused_tiles: tuple[tuple[int, str], ...]
    refused_reason: str | None

    @property
    def verdict(self) -> str:
        if self.refused_reason is not None or self.refused_tiles:
            return self.base.verdict()
        if self.base.verdict() != VERDICT_PARTIAL:
            return self.base.verdict()
        return VERDICT_POLICY_RESOLVED

    def p08_binding(self) -> dict:
        """Honest binding statement: the base gate is never opened by policy.

        The sealed fusion verdict (ADR-010) is immutable and the retained
        assessment still carries 19 UNKNOWN tiles plus a separately-reviewed
        rebinding step, so P08 binding stays not-allowed here. What policy
        resolution changes is *which evidence the 19-tile/open question is
        not about*: the six tiles' deltas stop being an unresolved-fusion
        blocker while every other blocker stands unchanged.
        """

        return {
            "allowed": False,
            "gate": "sealed fusion verdict immutable (ADR-010); rebinding pass "
            "implemented (this report is the rebinding input); 19 retained-UNKNOWN "
            "tiles remain unresolved; P08 stays INCOMPLETE_TILE_CLASSIFICATION",
            "preserved_retained_status": "INCOMPLETE_TILE_CLASSIFICATION",
            "policy_resolved_temporal_tiles": sorted(
                tile for tile, _row in self.resolved_field_rows
            ),
        }

    def report(self) -> dict:
        return {
            "schema": POLICY_REPORT_SCHEMA,
            "offline_only": True,
            "decision": {
                "adr": self.decision.adr,
                "token": self.decision.decision,
                "date": self.decision.date,
                "scope_tiles": sorted(self.decision.scope_tiles),
                "acceptable_fields": sorted(self.decision.acceptable_fields),
                "recorded_at": "docs/handoff/2026-10-24/"
                "adr-012-six-temporal-tiles-census-authority.md",
            },
            "base_verdict": self.base.verdict(),
            "verdict": self.verdict,
            "resolved_field_rows": [
                {"tile_id": tile, **row} for tile, row in self.resolved_field_rows
            ],
            "refused_tiles": [
                {"tile_id": tile, "reason": reason} for tile, reason in self.refused_tiles
            ],
            "refused_reason": self.refused_reason,
            "p08_binding": self.p08_binding(),
            "base_prepared_status_verbatim": {
                "temporal_tiles": list(self.base.temporal_tiles),
                "retained_segmentation_counts": self.base.retained_class_counts,
                "census_segmentation_counts": self.base.census_class_counts,
            },
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


def _authority_refusals(
    base: SemanticReconciliation,
    decision: CensusAuthorityDecision,
    tile_page_dates: Mapping[int, int],
) -> str | None:
    """Global fail-closed checks: refuse the whole application on any of these."""

    if base.identity_failures or base.hygiene_failures:
        return "identity or census hygiene failures present"
    if not base.completeness_reproduced:
        return "sealed census completeness not reproduced"
    if not base.manifest_verified:
        return "candidate artifact manifest unverified"
    status_of = {t.tile_id: t.status for t in base.tiles}
    temporal = set(base.temporal_tiles)
    if decision.scope_tiles != temporal:
        return (
            "decision scope must equal exactly the temporal tile set "
            f"(decision={sorted(decision.scope_tiles)} temporal={sorted(temporal)})"
        )
    for tile in sorted(decision.scope_tiles):
        if status_of.get(tile) != TEMPORAL:
            return f"tile {tile} is not a temporal tile"
        if tile not in tile_page_dates:
            return f"missing census page instant for tile {tile}"
        if tile_page_dates[tile] < 0 or tile_page_dates[tile] > _PAGE_SINGLE_INSTANT_MAX:
            return f"census page instant for tile {tile} is not an economy date"
    return None


_PAGE_SINGLE_INSTANT_MAX = 2147483647


def apply_census_authority(
    base: SemanticReconciliation,
    decision: CensusAuthorityDecision,
    tile_page_dates: Mapping[int, int],
) -> PolicyAppliedReconciliation:
    """Apply the delegated ADR-012 decision, fail-closed and scope-contained.

    ``tile_page_dates`` maps each scope tile to the ``date_before`` (== ``date_after``)
    of the single-instant census page the tile was observed on; both values must
    be equal in the sealed page, so passing only one is safe and the caller
    supplies it from the sealed responses.

    The application never mutates ``base``: results are emitted as a derived
    :class:`PolicyAppliedReconciliation` where every accepted row keeps both
    the retained and the census values verbatim.
    """

    refusal = _authority_refusals(base, decision, tile_page_dates)
    if refusal is not None:
        return PolicyAppliedReconciliation(
            decision=decision,
            base=base,
            resolved_field_rows=(),
            refused_tiles=(),
            refused_reason=refusal,
        )
    resolved: list[tuple[int, dict[str, object]]] = []
    refused: list[tuple[int, str]] = []
    tile_report = {t.tile_id: t for t in base.tiles}
    for tile in sorted(base.temporal_tiles):
        tile_recon = tile_report[tile]
        rows: list[dict[str, object]] = []
        definitional: list[dict[str, object]] = []
        block: str | None = None
        for outcome in tile_recon.field_outcomes:
            if outcome.outcome == SEMANTIC_BUILDABLE_ACCEPTANCE:
                # Already accepted by policy ``vacant-projection-1`` as a
                # definitional (Vacant vs ``IsBuildable``) transformation —
                # not a temporal delta. It carries its own acceptance, so it
                # passes through untouched here and neither blocks nor is
                # re-accepted by ADR-012.
                definitional.append(
                    {
                        "field": outcome.field,
                        "retained_value": outcome.retained_value,
                        "census_value": outcome.census_value,
                        "base_outcome": outcome.outcome,
                        "note": "definitional transformation accepted by "
                        "vacant-projection-1; unchanged by ADR-012",
                    }
                )
                continue
            if outcome.outcome != TEMPORAL:
                # Policy never absorbs contradictions, unresolved predicates
                # or definitional rows on scope tiles: fail closed.
                block = f"field {outcome.field} carries outcome {outcome.outcome}"
                break
            if outcome.field not in AUTHORITY_SCOPE_FIELDS:
                block = f"field {outcome.field} is outside ADR-012's evidence scope"
                break
            if outcome.field not in decision.acceptable_fields:
                block = f"field {outcome.field} is not in the decision's declared fields"
                break
            rows.append(
                {
                    "field": outcome.field,
                    "retained_value": outcome.retained_value,
                    "census_value": outcome.census_value,
                    "base_outcome": outcome.outcome,
                    "policy_outcome": AUTHORITY_RESOLVED_OUTCOME,
                    "census_page_economy_date": tile_page_dates[tile],
                }
            )
        if block is not None:
            refused.append((tile, block))
            continue
        if not rows and not definitional:
            refused.append((tile, "no temporal field outcomes on the ledger"))
            continue
        resolved.append((tile, {"fields": rows, "definitional_passthrough": definitional}))
    return PolicyAppliedReconciliation(
        decision=decision,
        base=base,
        resolved_field_rows=tuple(resolved),
        refused_tiles=tuple(refused),
        refused_reason=None,
    )


def _scope_page_instants(
    base: SemanticReconciliation, decision: CensusAuthorityDecision
) -> dict[int, int]:
    """Per-tile census-page instants from the base's sealed provenance.

    Each referenced page must be single-instant (``date_before ==
    date_after``) or the application is refused immediately: the delegated
    decision accepts per-page instants only, never a multi-day window.
    """

    dates: dict[int, int] = {}
    for tile, before, after in base.census_tile_instants:
        if tile not in decision.scope_tiles:
            continue
        if before < 0 or before > _PAGE_SINGLE_INSTANT_MAX:
            raise ValueError(f"tile {tile} carries an invalid census economy date")
        if before != after:
            raise ValueError(
                f"tile {tile} was observed on a non-single-instant page "
                f"({before} != {after}); ADR-012 cannot be applied"
            )
        dates[tile] = before
    missing = set(decision.scope_tiles) - set(dates)
    if missing:
        raise ValueError(f"census page instants missing for scope tiles {sorted(missing)}")
    return dates


def _policy_report_failure(message: str) -> ValueError:
    return ValueError(f"P08 policy rebinding refused: {message}")


def rebind_p08_policy(
    base: SemanticReconciliation,
    report_bytes: bytes | bytearray | None,
) -> P08PolicyRebinding:
    """Rebind a derived ADR-012 policy report into the P08 evidence gate.

    The report is accepted only when it is the *exact* deterministic
    derivation of the sealed inputs behind ``base``: same schema, decision
    token, temporal scope, verbatim rows, segmentation counts and sealed
    digests. A stale, hand-edited, narrowed or widened report is refused
    (``ValueError``), never repaired.

    Rebinding never mutates ``base``, never relabels the base ledger, never
    absorbs contradictions/unresolved evidence, and never resolves a tile
    outside the reconciliation's own temporal set. The result's ``allowed``
    is computed from remaining blockers; the 19 retained-UNKNOWN
    (``UNKNOWN_OCCUPANCY``) tiles are not in ADR-012's scope, so P08 stays
    unbound on the sealed inputs.
    """

    if not isinstance(report_bytes, (bytes, bytearray)) or not bytes(report_bytes).strip():
        raise _policy_report_failure("derived policy report missing")
    raw = bytes(report_bytes)
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _policy_report_failure(f"derived policy report is not valid JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise _policy_report_failure("derived policy report is not a JSON object")
    if document.get("schema") != POLICY_REPORT_SCHEMA:
        raise _policy_report_failure(
            f"unexpected schema {document.get('schema')!r}; expected {POLICY_REPORT_SCHEMA!r}"
        )
    if base.verdict() != VERDICT_PARTIAL:
        raise _policy_report_failure(
            f"base verdict {base.verdict()!r} is not the policy-partial state {VERDICT_PARTIAL!r}"
        )
    decision_doc = document.get("decision")
    if not isinstance(decision_doc, dict):
        raise _policy_report_failure("derived policy report carries no decision record")
    if decision_doc.get("adr") != AUTHORITY_DECISION_ADR:
        raise _policy_report_failure(
            f"decision ADR {decision_doc.get('adr')!r} is not {AUTHORITY_DECISION_ADR}"
        )
    if decision_doc.get("token") != AUTHORITY_DECISION_TOKEN:
        raise _policy_report_failure(
            f"decision token {decision_doc.get('token')!r} is not {AUTHORITY_DECISION_TOKEN}"
        )
    if document.get("refused_reason") is not None or document.get("refused_tiles"):
        raise _policy_report_failure("derived policy report records refusals")
    if document.get("verdict") != VERDICT_POLICY_RESOLVED:
        raise _policy_report_failure(
            f"derived policy verdict {document.get('verdict')!r} is not {VERDICT_POLICY_RESOLVED}"
        )
    if document.get("base_verdict") != base.verdict():
        raise _policy_report_failure("report base_verdict does not match the sealed replay")
    if base.identity_failures or base.hygiene_failures:
        raise _policy_report_failure("base carries identity or census hygiene failures")
    if not base.completeness_reproduced or not base.manifest_verified:
        raise _policy_report_failure("base completeness/manifest did not verify")
    if base.contradiction_tiles or base.unresolved_tiles:
        raise _policy_report_failure("base carries contradictions or unresolved evidence")

    temporal = tuple(sorted(base.temporal_tiles))
    if not temporal:
        raise _policy_report_failure("base carries no temporal tiles to rebind")
    try:
        scope = tuple(sorted(int(tile) for tile in decision_doc.get("scope_tiles") or ()))
        declared_fields = frozenset(
            str(field) for field in decision_doc.get("acceptable_fields") or ()
        )
    except (TypeError, ValueError) as exc:
        raise _policy_report_failure(f"decision scope/fields are malformed ({exc})") from exc
    if not scope:
        raise _policy_report_failure("decision scope is empty")
    if scope != temporal:
        raise _policy_report_failure(
            f"decision scope {list(scope)} is not exactly the sealed temporal set {list(temporal)}"
        )
    if not declared_fields or not declared_fields <= AUTHORITY_SCOPE_FIELDS:
        raise _policy_report_failure(
            f"decision fields {sorted(declared_fields)} exceed ADR-012's scope "
            f"{sorted(AUTHORITY_SCOPE_FIELDS)}"
        )

    rows_doc = document.get("resolved_field_rows")
    if not isinstance(rows_doc, list):
        raise _policy_report_failure("derived policy report carries no resolved_field_rows")
    tile_rows: dict[int, dict[str, object]] = {}
    for entry in rows_doc:
        if not isinstance(entry, dict):
            raise _policy_report_failure("resolved_field_rows contains a non-object row")
        try:
            tile = int(entry["tile_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _policy_report_failure(f"resolved row has an invalid tile_id ({exc})") from exc
        if tile in tile_rows:
            raise _policy_report_failure(f"tile {tile} is resolved twice")
        if tile not in temporal:
            raise _policy_report_failure(f"tile {tile} is outside ADR-012's temporal scope")
        fields = entry.get("fields")
        if not isinstance(fields, list):
            raise _policy_report_failure(f"tile {tile} carries no field rows")
        tile_rows[tile] = entry
    if tuple(sorted(tile_rows)) != temporal:
        raise _policy_report_failure(
            f"resolved tiles {sorted(tile_rows)} are not exactly the temporal set {list(temporal)}"
        )

    base_outcomes = {
        reconciliation.tile_id: {o.field: o for o in reconciliation.field_outcomes}
        for reconciliation in base.tiles
    }
    for tile in temporal:
        entry = tile_rows[tile]
        fields = entry["fields"]
        if not fields:
            raise _policy_report_failure(f"tile {tile} has no accepted temporal field rows")
        seen: set[str] = set()
        for row in fields:
            if not isinstance(row, dict):
                raise _policy_report_failure(f"tile {tile} carries a non-object field row")
            field = row.get("field")
            if not isinstance(field, str) or field not in declared_fields:
                raise _policy_report_failure(f"tile {tile} field {field!r} is not declared")
            if field in seen:
                raise _policy_report_failure(f"tile {tile} field {field} is duplicated")
            seen.add(field)
            if row.get("policy_outcome") != AUTHORITY_RESOLVED_OUTCOME:
                raise _policy_report_failure(
                    f"tile {tile} field {field} carries outcome {row.get('policy_outcome')!r}"
                )
            if not isinstance(row.get("census_page_economy_date"), int):
                raise _policy_report_failure(
                    f"tile {tile} field {field} carries no single-instant census date"
                )
            observed = base_outcomes.get(tile, {}).get(field)
            if observed is None:
                raise _policy_report_failure(f"tile {tile} field {field} is absent from the base")
            if (
                observed.outcome != TEMPORAL
                or row.get("retained_value") != observed.retained_value
                or row.get("census_value") != observed.census_value
                or row.get("base_outcome") != observed.outcome
            ):
                raise _policy_report_failure(
                    f"tile {tile} field {field} does not preserve the sealed base evidence verbatim"
                )

    prepared = document.get("base_prepared_status_verbatim")
    if not isinstance(prepared, dict):
        raise _policy_report_failure("derived policy report carries no base status snapshot")
    if tuple(prepared.get("temporal_tiles") or ()) != temporal:
        raise _policy_report_failure("report temporal_tiles do not match the sealed replay")
    if prepared.get("retained_segmentation_counts") != base.retained_class_counts:
        raise _policy_report_failure("report retained segmentation counts drifted")
    if prepared.get("census_segmentation_counts") != base.census_class_counts:
        raise _policy_report_failure("report census segmentation counts drifted")

    decision = CensusAuthorityDecision(
        scope_tiles=frozenset(temporal),
        acceptable_fields=declared_fields,
        date=str(decision_doc.get("date") or ""),
    )
    expected = apply_census_authority(
        base, decision, _scope_page_instants(base, decision)
    ).to_json_bytes()
    if raw != expected:
        raise _policy_report_failure(
            "report is not the deterministic derivation of the sealed inputs "
            "(stale, edited, or provenance-mismatched)"
        )

    unknown = int(base.retained_class_counts.get("UNKNOWN_OCCUPANCY", 0))
    blockers: list[str] = []
    if unknown:
        blockers.append(
            f"{unknown} retained-UNKNOWN (UNKNOWN_OCCUPANCY) tiles remain unresolved; "
            "ADR-012 does not cover them and no separate admissible evidence exists"
        )
    resolved_fields = tuple(
        (
            tile,
            tuple(dict(row) for row in tile_rows[tile]["fields"]),
            tuple(
                dict(row)
                for row in tile_rows[tile].get("definitional_passthrough", ())
            ),
        )
        for tile in temporal
    )
    return P08PolicyRebinding(
        decision_adr=AUTHORITY_DECISION_ADR,
        decision_token=AUTHORITY_DECISION_TOKEN,
        decision_date=decision.date,
        base_verdict=base.verdict(),
        policy_verdict=VERDICT_POLICY_RESOLVED,
        resolved_tiles=temporal,
        resolved_fields=resolved_fields,
        retained_segmentation_counts=dict(sorted(base.retained_class_counts.items())),
        unresolved_classification_tiles=unknown,
        blockers=tuple(blockers),
        base_report_sha256=hashlib.sha256(base.to_json_bytes()).hexdigest(),
        policy_report_sha256=hashlib.sha256(raw).hexdigest(),
        retained_facts_sha256=base.retained_facts_sha256,
        census_page_payload_sha256=base.census_page_payload_sha256,
    )


@dataclass(frozen=True)
class P08PolicyRebinding:
    """Derived bridge from the ADR-012 policy report to the P08 evidence gate.

    This is a *binding statement*, not new evidence: it records exactly which
    sealed temporal rows policy authority covers and which blockers remain.
    ``allowed`` is computed from those blockers, so it cannot be raised by
    relabelling the base report or by hiding unresolved tiles.
    """

    decision_adr: str
    decision_token: str
    decision_date: str
    base_verdict: str
    policy_verdict: str
    resolved_tiles: tuple[int, ...]
    resolved_fields: tuple[
        tuple[int, tuple[dict[str, object], ...], tuple[dict[str, object], ...]], ...
    ]
    retained_segmentation_counts: dict[str, int]
    unresolved_classification_tiles: int
    blockers: tuple[str, ...]
    base_report_sha256: str
    policy_report_sha256: str
    retained_facts_sha256: str
    census_page_payload_sha256: str

    @property
    def allowed(self) -> bool:
        return not self.blockers

    def report(self) -> dict:
        return {
            "schema": REBINDING_REPORT_SCHEMA,
            "offline_only": True,
            "decision": {
                "adr": self.decision_adr,
                "token": self.decision_token,
                "date": self.decision_date,
                "recorded_at": "docs/handoff/2026-10-24/"
                "adr-012-six-temporal-tiles-census-authority.md",
            },
            "base_verdict": self.base_verdict,
            "policy_verdict": self.policy_verdict,
            "resolved_tiles": list(self.resolved_tiles),
            "resolved_field_rows": [
                {
                    "tile_id": tile,
                    "fields": [dict(row) for row in rows],
                    "definitional_passthrough": [dict(row) for row in passthrough],
                }
                for tile, rows, passthrough in self.resolved_fields
            ],
            "retained_segmentation_counts": dict(self.retained_segmentation_counts),
            "unresolved_classification": {
                "class": "UNKNOWN_OCCUPANCY",
                "count": self.unresolved_classification_tiles,
                "within_adr_012_scope": False,
                "resolution_requires": "separate admissible same-instant evidence "
                "(not present offline)",
            },
            "p08_binding": {
                "allowed": self.allowed,
                "preserved_retained_status": None
                if self.allowed
                else "INCOMPLETE_TILE_CLASSIFICATION",
                "blockers": list(self.blockers),
            },
            "standing_facts": [
                "the sealed fusion verdict stays rejected (ADR-010); this "
                "rebinding does not relabel it",
                "the base reconciliation ledger keeps every temporal tile as "
                "TEMPORAL_SECOND_INSTANT and every observation verbatim",
                "no native evidence was captured, signed, consumed or launched",
            ],
            "provenance": {
                "base_report_sha256": self.base_report_sha256,
                "policy_report_sha256": self.policy_report_sha256,
                "retained_facts_sha256": self.retained_facts_sha256,
                "census_page_payload_sha256": self.census_page_payload_sha256,
            },
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


@dataclass(frozen=True)
class NativeIsBuildableDecision:
    """Explicit ADR-013 token; the caller supplies the exact sealed scope.

    The default scope is the operator-approved 19-tile set. The application
    layer still re-derives the retained-UNKNOWN set and refuses unless it is
    exactly this scope, so the token cannot be widened or narrowed.
    """

    adr: str = NATIVE_ISBUILDABLE_DECISION_ADR
    decision: str = NATIVE_ISBUILDABLE_DECISION_TOKEN
    scope_tiles: frozenset[int] = NATIVE_ISBUILDABLE_SCOPE_TILES
    acceptable_fields: frozenset[str] = frozenset({"buildable"})
    date: str = NATIVE_ISBUILDABLE_DECISION_DATE


def _isbuildable_refusal(
    base: SemanticReconciliation,
    retained: SupplementalPlanningFacts,
    census: Mapping[int, object],
    decision: NativeIsBuildableDecision,
) -> str | None:
    """Global fail-closed checks for the ADR-013 application layer."""

    if decision.adr != NATIVE_ISBUILDABLE_DECISION_ADR:
        return f"decision ADR {decision.adr!r} is not {NATIVE_ISBUILDABLE_DECISION_ADR}"
    if decision.decision != NATIVE_ISBUILDABLE_DECISION_TOKEN:
        return f"decision token {decision.decision!r} is not {NATIVE_ISBUILDABLE_DECISION_TOKEN}"
    if decision.acceptable_fields != frozenset({"buildable"}):
        return "ADR-013 covers exactly the buildable field"
    if decision.date != NATIVE_ISBUILDABLE_DECISION_DATE:
        return f"decision date {decision.date!r} is not {NATIVE_ISBUILDABLE_DECISION_DATE}"
    if decision.scope_tiles != NATIVE_ISBUILDABLE_SCOPE_TILES:
        return "ADR-013 scope is not exactly the authorized 19 definitional tiles"
    if base.verdict() != VERDICT_PARTIAL:
        return (
            f"base verdict {base.verdict()!r} is not the policy-partial state "
            f"{VERDICT_PARTIAL!r}"
        )
    if base.identity_failures or base.hygiene_failures:
        return "identity or census hygiene failures present"
    if not base.completeness_reproduced or not base.manifest_verified:
        return "sealed completeness/manifest did not verify"
    if base.contradiction_tiles or base.unresolved_tiles:
        return "base carries contradictions or unresolved evidence"
    if dict(base.retained_class_counts) != NATIVE_ISBUILDABLE_BASE_COUNTS:
        return (
            "retained segmentation counts drifted from the ADR-013 evidence "
            f"({base.retained_class_counts!r})"
        )
    if set(base.temporal_tiles) & set(decision.scope_tiles):
        return "ADR-013 scope overlaps the ADR-012 temporal set"

    from app.planning.p08_terrain import SegmentClass, _legacy_segment, classify_segment

    unknown = tuple(
        sorted(
            fact.tile_id
            for fact in retained.tiles
            if _legacy_segment(fact)[0] is SegmentClass.UNKNOWN_OCCUPANCY
        )
    )
    if len(unknown) != 19 or frozenset(unknown) != decision.scope_tiles:
        return (
            "retained UNKNOWN_OCCUPANCY set is not exactly the authorized "
            f"19-tile scope ({unknown!r})"
        )

    ledger = {tile.tile_id: tile for tile in base.tiles}
    instants = {
        tile: (before, after) for tile, before, after in base.census_tile_instants
    }
    facts = {fact.tile_id: fact for fact in retained.tiles}
    for tile_id in sorted(decision.scope_tiles):
        fact = facts.get(tile_id)
        row = ledger.get(tile_id)
        observation = census.get(tile_id)
        if fact is None:
            return f"tile {tile_id} is absent from the retained facts"
        if row is None:
            return f"tile {tile_id} is absent from the reconciliation ledger"
        if row.status != RECONCILED:
            return f"tile {tile_id} is {row.status}, not {RECONCILED}"
        outcomes = row.field_outcomes
        if len(outcomes) != 1:
            return f"tile {tile_id} does not carry exactly one definitional field outcome"
        outcome = outcomes[0]
        if (
            outcome.field != "buildable"
            or outcome.outcome != SEMANTIC_BUILDABLE_ACCEPTANCE
            or outcome.retained_value is not False
            or outcome.census_value is not False
        ):
            return (
                f"tile {tile_id} is not exactly the accepted "
                "Vacant-vs-IsBuildable definitional transformation"
            )
        if fact.slope == 0:
            return f"tile {tile_id} has flat retained ground; ADR-013 requires non-flat"
        if observation is None:
            return f"tile {tile_id} has no census observation"
        try:
            classification = observation.classification
            owner = observation.owner
            slope = observation.slope
            flags = observation.flags
            observation_fact = observation.fact()
        except AttributeError as exc:
            return f"tile {tile_id} census observation is malformed ({exc})"
        if classification != "CLEAR":
            return f"tile {tile_id} census class is {classification!r}, not CLEAR"
        if owner != OWNER_UNOWNED_SENTINEL:
            return f"tile {tile_id} census owner is {owner!r}, not unowned"
        if slope == 0 or slope != fact.slope:
            return f"tile {tile_id} census/retained slope disagrees or is flat"
        if not isinstance(flags, int) or projection_disagrees(observation_fact, flags):
            return f"tile {tile_id} census projection is incoherent"
        if observation_fact.buildable is not True:
            return f"tile {tile_id} native IsBuildable bit is not set"
        observed = instants.get(tile_id)
        if observed is None:
            return f"tile {tile_id} has no sealed census-page instant"
        if observed[0] != observed[1] or observed[0] != NATIVE_ISBUILDABLE_CENSUS_INSTANT:
            return (
                f"tile {tile_id} is not on the single authorized census instant "
                f"{NATIVE_ISBUILDABLE_CENSUS_INSTANT}"
            )
        segment, reason = classify_segment(
            observation_fact, classification, flags=flags
        )
        if (
            segment is not SegmentClass.TERRAIN_MODIFICATION
            or reason != "classified-clear-sloped"
        ):
            return (
                f"tile {tile_id} does not derive TERRAIN_MODIFICATION from the "
                f"sealed census evidence ({segment}, {reason})"
            )
    return None


@dataclass(frozen=True)
class NativeIsBuildablePolicyApplication:
    """Derived ADR-013 policy layer over an untouched reconciliation base."""

    decision: NativeIsBuildableDecision
    base: SemanticReconciliation
    resolved_field_rows: tuple[tuple[int, dict[str, object]], ...]
    refused_reason: str | None
    derived_segmentation_counts: dict[str, int]

    @property
    def verdict(self) -> str:
        if self.refused_reason is not None:
            return self.base.verdict()
        return NATIVE_ISBUILDABLE_VERDICT

    def p08_binding(self) -> dict:
        return {
            "allowed": False,
            "gate": "ADR-013 changes the derived segmentation only; a separate "
            "P08 rebinding pass is required. The sealed fusion verdict remains "
            "immutable and the fusion gate stays closed",
            "preserved_retained_status": "INCOMPLETE_TILE_CLASSIFICATION",
            "policy_resolved_tiles": sorted(
                tile for tile, _row in self.resolved_field_rows
            ),
        }

    def report(self) -> dict:
        return {
            "schema": NATIVE_ISBUILDABLE_POLICY_REPORT_SCHEMA,
            "offline_only": True,
            "decision": {
                "adr": self.decision.adr,
                "token": self.decision.decision,
                "date": self.decision.date,
                "scope_tiles": sorted(self.decision.scope_tiles),
                "acceptable_fields": sorted(self.decision.acceptable_fields),
                "recorded_at": "docs/handoff/2026-10-25/"
                "adr-013-p08-native-isbuildable-definitional-semantics.md",
            },
            "base_verdict": self.base.verdict(),
            "verdict": self.verdict,
            "resolved_field_rows": [
                {"tile_id": tile, **row}
                for tile, row in self.resolved_field_rows
            ],
            "refused_reason": self.refused_reason,
            "base_prepared_status_verbatim": {
                "temporal_tiles": list(self.base.temporal_tiles),
                "retained_segmentation_counts": dict(
                    sorted(self.base.retained_class_counts.items())
                ),
            },
            "derived_segmentation_counts": dict(
                sorted(self.derived_segmentation_counts.items())
            ),
            "p08_binding": self.p08_binding(),
            "standing_facts": [
                "the base reconciliation ledger and all sealed bytes are unchanged",
                "the sealed SOURCE_SAVE_FUSION verdict stays REJECTED; no fusion "
                "gate is opened",
                "no native evidence was captured, signed, consumed or launched",
            ],
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


def apply_native_isbuildable_policy(
    base: SemanticReconciliation,
    retained: SupplementalPlanningFacts,
    census: Mapping[int, object],
    decision: NativeIsBuildableDecision,
) -> NativeIsBuildablePolicyApplication:
    """Apply ADR-013 to exactly the sealed 19-tile definitional group.

    The application is all-or-nothing. It never mutates ``base``; the base
    ledger, sealed report bytes and historical counts stay verbatim. Accepted
    rows preserve both the retained and census values and add only the derived
    ``TERRAIN_MODIFICATION`` mapping and its reason.
    """

    refusal = _isbuildable_refusal(base, retained, census, decision)
    if refusal is not None:
        return NativeIsBuildablePolicyApplication(
            decision=decision,
            base=base,
            resolved_field_rows=(),
            refused_reason=refusal,
            derived_segmentation_counts=dict(base.retained_class_counts),
        )

    resolved: list[tuple[int, dict[str, object]]] = []
    instants = {
        tile: before for tile, before, after in base.census_tile_instants if before == after
    }
    for tile_id in sorted(decision.scope_tiles):
        outcome = next(
            outcome
            for row in base.tiles
            if row.tile_id == tile_id
            for outcome in row.field_outcomes
        )
        resolved.append(
            (
                tile_id,
                {
                    "fields": [
                        {
                            "field": "buildable",
                            "retained_value": outcome.retained_value,
                            "census_value": outcome.census_value,
                            "base_outcome": outcome.outcome,
                            "policy_outcome": NATIVE_ISBUILDABLE_RESOLVED_OUTCOME,
                            "census_page_economy_date": instants[tile_id],
                            "census_native_isbuildable": bool(
                                census[tile_id].fact().buildable
                            ),
                        }
                    ],
                    "derived_segment_class": NATIVE_ISBUILDABLE_DERIVED_CLASS,
                    "mapping_reason": "classified-clear-sloped",
                },
            )
        )
    derived = dict(base.retained_class_counts)
    derived["UNKNOWN_OCCUPANCY"] = 0
    derived[NATIVE_ISBUILDABLE_DERIVED_CLASS] = (
        derived.get(NATIVE_ISBUILDABLE_DERIVED_CLASS, 0) + len(resolved)
    )
    return NativeIsBuildablePolicyApplication(
        decision=decision,
        base=base,
        resolved_field_rows=tuple(resolved),
        refused_reason=None,
        derived_segmentation_counts=derived,
    )


@dataclass(frozen=True)
class P08NativeIsBuildableRebinding:
    """Separate combined ADR-012 + ADR-013 P08 policy rebinding statement."""

    decision_adr: str
    decision_token: str
    decision_date: str
    base_verdict: str
    policy_verdict: str
    resolved_temporal_tiles: tuple[int, ...]
    resolved_unknown_tiles: tuple[int, ...]
    resolved_field_rows: tuple[tuple[int, dict[str, object]], ...]
    derived_segmentation_counts: dict[str, int]
    blockers: tuple[str, ...]
    base_report_sha256: str
    native_isbuildable_policy_report_sha256: str
    census_authority_policy_report_sha256: str
    retained_facts_sha256: str
    census_page_payload_sha256: str

    @property
    def allowed(self) -> bool:
        return not self.blockers

    def report(self) -> dict:
        return {
            "schema": NATIVE_ISBUILDABLE_REBINDING_REPORT_SCHEMA,
            "offline_only": True,
            "decision": {
                "adr": self.decision_adr,
                "token": self.decision_token,
                "date": self.decision_date,
                "recorded_at": "docs/handoff/2026-10-25/"
                "adr-013-p08-native-isbuildable-definitional-semantics.md",
            },
            "base_verdict": self.base_verdict,
            "policy_verdict": self.policy_verdict,
            "resolved_temporal_tiles": list(self.resolved_temporal_tiles),
            "resolved_unknown_tiles": list(self.resolved_unknown_tiles),
            "resolved_field_rows": [
                {"tile_id": tile, **row}
                for tile, row in self.resolved_field_rows
            ],
            "derived_segmentation_counts": dict(
                sorted(self.derived_segmentation_counts.items())
            ),
            "unresolved_classification": {
                "class": "UNKNOWN_OCCUPANCY",
                "count": 0,
                "resolved_by": NATIVE_ISBUILDABLE_DECISION_ADR,
                "within_adr_013_scope": True,
            },
            "p08_binding": {
                "allowed": self.allowed,
                "preserved_retained_status": None
                if self.allowed
                else "INCOMPLETE_TILE_CLASSIFICATION",
                "blockers": list(self.blockers),
                "scope": "P08 planning classification only",
                "p08_complete": False,
                "completion_requirements": [
                    "the sealed SOURCE_SAVE_FUSION verdict remains REJECTED; "
                    "the fusion gate is closed and was not opened by this pass",
                    "no native construction, delivery or execution evidence "
                    "exists for this classification",
                ],
            },
            "fusion_gate": {
                "status": "CLOSED",
                "opened": False,
                "reason": "sealed SOURCE_SAVE_FUSION verdict is immutable; "
                "this policy pass does not relabel or fuse it",
            },
            "standing_facts": [
                "the base reconciliation ledger keeps every temporal tile as "
                "TEMPORAL_SECOND_INSTANT and every observation verbatim",
                "the 19 retained-UNKNOWN tiles are resolved only in the derived "
                "ADR-013 planning layer, never rewritten in the base ledger",
                "no native evidence was captured, signed, consumed or launched",
            ],
            "provenance": {
                "base_report_sha256": self.base_report_sha256,
                "native_isbuildable_policy_report_sha256": (
                    self.native_isbuildable_policy_report_sha256
                ),
                "census_authority_policy_report_sha256": (
                    self.census_authority_policy_report_sha256
                ),
                "retained_facts_sha256": self.retained_facts_sha256,
                "census_page_payload_sha256": self.census_page_payload_sha256,
            },
        }

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.report(), sort_keys=True, indent=1) + "\n").encode()


def _native_isbuildable_report_failure(message: str) -> ValueError:
    return ValueError(f"P08 native-IsBuildable rebinding refused: {message}")


def rebind_p08_native_isbuildable(
    base: SemanticReconciliation,
    report_bytes: bytes | bytearray | None,
    retained: SupplementalPlanningFacts,
    census: Mapping[int, object],
    *,
    census_authority_report_bytes: bytes | bytearray | None,
) -> P08NativeIsBuildableRebinding:
    """Rebind the combined ADR-012 + ADR-013 policy evidence into P08.

    The ADR-013 report must be the exact deterministic derivation of the
    sealed inputs; the ADR-012 report is independently re-derived by the
    existing rebinding function. A stale, edited, narrowed, widened or
    refusal-carrying report is refused rather than repaired. The resulting
    ``allowed`` statement is scoped to P08 planning classification only: the
    sealed fusion verdict and the fusion gate remain closed, and P08 is not
    claimed complete.
    """

    census_authority = rebind_p08_policy(base, census_authority_report_bytes)
    if census_authority.policy_verdict != VERDICT_POLICY_RESOLVED:
        raise _native_isbuildable_report_failure(
            "census-authority report is not policy-resolved"
        )
    if tuple(sorted(census_authority.resolved_tiles)) != tuple(sorted(base.temporal_tiles)):
        raise _native_isbuildable_report_failure(
            "census-authority report does not resolve exactly the sealed temporal set"
        )

    if not isinstance(report_bytes, (bytes, bytearray)) or not bytes(report_bytes).strip():
        raise _native_isbuildable_report_failure("derived ADR-013 report missing")
    raw = bytes(report_bytes)
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _native_isbuildable_report_failure(
            f"derived ADR-013 report is not valid JSON ({exc})"
        ) from exc
    if not isinstance(document, dict):
        raise _native_isbuildable_report_failure(
            "derived ADR-013 report is not a JSON object"
        )
    if document.get("schema") != NATIVE_ISBUILDABLE_POLICY_REPORT_SCHEMA:
        raise _native_isbuildable_report_failure(
            f"unexpected schema {document.get('schema')!r}; expected "
            f"{NATIVE_ISBUILDABLE_POLICY_REPORT_SCHEMA!r}"
        )
    decision_doc = document.get("decision")
    if not isinstance(decision_doc, dict):
        raise _native_isbuildable_report_failure(
            "derived ADR-013 report carries no decision record"
        )
    if decision_doc.get("adr") != NATIVE_ISBUILDABLE_DECISION_ADR:
        raise _native_isbuildable_report_failure(
            f"decision ADR {decision_doc.get('adr')!r} is not "
            f"{NATIVE_ISBUILDABLE_DECISION_ADR}"
        )
    if decision_doc.get("token") != NATIVE_ISBUILDABLE_DECISION_TOKEN:
        raise _native_isbuildable_report_failure(
            f"decision token {decision_doc.get('token')!r} is not "
            f"{NATIVE_ISBUILDABLE_DECISION_TOKEN}"
        )
    if decision_doc.get("date") != NATIVE_ISBUILDABLE_DECISION_DATE:
        raise _native_isbuildable_report_failure(
            f"decision date {decision_doc.get('date')!r} is not "
            f"{NATIVE_ISBUILDABLE_DECISION_DATE!r}"
        )
    if document.get("refused_reason") is not None:
        raise _native_isbuildable_report_failure("derived ADR-013 report records a refusal")
    if document.get("verdict") != NATIVE_ISBUILDABLE_VERDICT:
        raise _native_isbuildable_report_failure(
            f"derived ADR-013 verdict {document.get('verdict')!r} is not "
            f"{NATIVE_ISBUILDABLE_VERDICT}"
        )
    if document.get("base_verdict") != base.verdict():
        raise _native_isbuildable_report_failure(
            "report base_verdict does not match the sealed replay"
        )
    try:
        scope = frozenset(int(tile) for tile in decision_doc.get("scope_tiles") or ())
        fields = frozenset(
            str(field) for field in decision_doc.get("acceptable_fields") or ()
        )
    except (TypeError, ValueError) as exc:
        raise _native_isbuildable_report_failure(
            f"decision scope/fields are malformed ({exc})"
        ) from exc
    decision = NativeIsBuildableDecision(
        scope_tiles=scope,
        acceptable_fields=fields,
        date=str(decision_doc.get("date") or ""),
    )
    expected = apply_native_isbuildable_policy(base, retained, census, decision)
    if expected.refused_reason is not None:
        raise _native_isbuildable_report_failure(
            f"sealed evidence cannot support ADR-013 ({expected.refused_reason})"
        )
    if raw != expected.to_json_bytes():
        raise _native_isbuildable_report_failure(
            "report is not the deterministic derivation of the sealed inputs "
            "(stale, edited, or provenance-mismatched)"
        )

    return P08NativeIsBuildableRebinding(
        decision_adr=NATIVE_ISBUILDABLE_DECISION_ADR,
        decision_token=NATIVE_ISBUILDABLE_DECISION_TOKEN,
        decision_date=decision.date,
        base_verdict=base.verdict(),
        policy_verdict=expected.verdict,
        resolved_temporal_tiles=tuple(sorted(base.temporal_tiles)),
        resolved_unknown_tiles=tuple(sorted(decision.scope_tiles)),
        resolved_field_rows=expected.resolved_field_rows,
        derived_segmentation_counts=expected.derived_segmentation_counts,
        blockers=(),
        base_report_sha256=hashlib.sha256(base.to_json_bytes()).hexdigest(),
        native_isbuildable_policy_report_sha256=hashlib.sha256(raw).hexdigest(),
        census_authority_policy_report_sha256=hashlib.sha256(
            bytes(census_authority_report_bytes)
        ).hexdigest(),
        retained_facts_sha256=base.retained_facts_sha256,
        census_page_payload_sha256=base.census_page_payload_sha256,
    )


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
        census_tile_instants=tuple(
            (tile, pages[ordinal].date_before, pages[ordinal].date_after)
            for tile, (ordinal, _observation) in sorted(census_by_id.items())
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Write the derived reconciliation report; never touches retained inputs."""

    parser = argparse.ArgumentParser(description="offline V1/V2 semantic reconciliation replay")
    parser.add_argument("retained_facts")
    parser.add_argument("candidate_dir")
    parser.add_argument("output_dir")
    parser.add_argument(
        "--apply-adr-012",
        action="store_true",
        help=(
            "also emit the derived ADR-012 census-authority policy report "
            "(census-authority-policy-report.json); requires the delegated "
            "decision and revalidates every check fail-closed"
        ),
    )
    parser.add_argument(
        "--apply-adr-013",
        action="store_true",
        help=(
            "also emit the derived ADR-013 native-IsBuildable policy report "
            "(native-isbuildable-policy-report.json) for the exact 19-tile "
            "definitional scope; refuses any drift"
        ),
    )
    parser.add_argument(
        "--rebind-p08",
        action="store_true",
        help=(
            "with both policy reports present, emit the separate combined P08 "
            "rebinding report (p08-native-isbuildable-rebinding-report.json)"
        ),
    )
    args = parser.parse_args(argv)
    reconciliation = replay_retained_census(Path(args.retained_facts), Path(args.candidate_dir))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "reconciliation-report.json").write_bytes(reconciliation.to_json_bytes())
    decision_line = ""
    if args.apply_adr_012:
        decision = CensusAuthorityDecision(scope_tiles=frozenset(reconciliation.temporal_tiles))
        tile_page_dates = _scope_page_instants(reconciliation, decision)
        applied = apply_census_authority(reconciliation, decision, tile_page_dates)
        (output / "census-authority-policy-report.json").write_bytes(applied.to_json_bytes())
        decision_line = (
            f" authority_verdict={applied.verdict} "
            f"authority_resolved={len(applied.resolved_field_rows)} "
            f"authority_refusals={len(applied.refused_tiles) or applied.refused_reason}"
        )
    if args.apply_adr_013 or args.rebind_p08:
        from app.planning.p08_v2_snapshot import _load_census

        retained, census, _bracket, _pages = _load_census(
            Path(args.retained_facts), Path(args.candidate_dir)
        )
    if args.apply_adr_013:
        native_decision = NativeIsBuildableDecision()
        native_applied = apply_native_isbuildable_policy(
            reconciliation, retained, census, native_decision
        )
        (output / "native-isbuildable-policy-report.json").write_bytes(
            native_applied.to_json_bytes()
        )
        decision_line += (
            f" isbuildable_verdict={native_applied.verdict} "
            f"isbuildable_resolved={len(native_applied.resolved_field_rows)} "
            f"isbuildable_refusal={native_applied.refused_reason or 'none'}"
        )
    if args.rebind_p08:
        policy_path = output / "census-authority-policy-report.json"
        native_policy_path = output / "native-isbuildable-policy-report.json"
        if not policy_path.is_file() or not native_policy_path.is_file():
            parser.error("--rebind-p08 requires both policy reports in the output directory")
        rebound = rebind_p08_native_isbuildable(
            reconciliation,
            native_policy_path.read_bytes(),
            retained,
            census,
            census_authority_report_bytes=policy_path.read_bytes(),
        )
        (output / "p08-native-isbuildable-rebinding-report.json").write_bytes(
            rebound.to_json_bytes()
        )
        decision_line += (
            f" rebinding_allowed={rebound.allowed} "
            f"rebinding_unknown={len(rebound.resolved_unknown_tiles)} "
            f"rebinding_temporal={len(rebound.resolved_temporal_tiles)}"
        )
    print(
        f"policy={reconciliation.policy_version} verdict={reconciliation.verdict()} "
        f"raw_gate={len(reconciliation.raw_gate_tiles)} "
        f"definitional={len(reconciliation.semantic_tiles)} "
        f"temporal={len(reconciliation.temporal_tiles)} "
        f"contradictions={len(reconciliation.contradiction_tiles)} "
        f"unresolved={len(reconciliation.unresolved_tiles)} "
        f"manifest={reconciliation.manifest_verified}/{reconciliation.manifest_entries} "
        f"completeness_reproduced={reconciliation.completeness_reproduced}"
        f"{decision_line}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
