---
id: ADR-013
title: "P08 native IsBuildable semantics for the 19 definitional tiles"
type: decision
status: accepted
date: 2026-10-25
updated: 2026-10-25
relates: ADR-012
source: "docs/p08-native-tile-classification.md"
tags:
  - openttd
  - decisions
  - p08
---

# ADR-013 — P08 native `IsBuildable` semantics for the 19 definitional tiles

**Status: ACCEPTED (operator-authorized 2026-10-25).** The operator explicitly
approved this policy for the exact 19-tile scope. The fail-closed application
layer and the separate combined P08 rebinding pass are implemented and
offline-verified. The base ledger, sealed bytes and original evidence are
unchanged. The sealed fusion gate remains **closed**, and P08 is **not**
claimed complete: this policy establishes planning classification only.

## Decision (accepted)

Adopt native `GSTile.IsBuildable` semantics for P08 segment classification of
exactly these 19 tiles:

```
46517 46518 46772 47027 47028 47282 47283 47538 47793 48049
48304 48305 48554 48555 48556 48557 48558 48559 48560
```

Scope is the tile set plus the single field concept `buildable`. For those
tiles only, the retained planner-`Vacant` `buildable=False` value is treated as
the definitional projection of native `IsBuildable` on **sloped clear ground**,
and the P08 segment class becomes `TERRAIN_MODIFICATION`. No other field,
tile, segment class or count is covered.

The mapping is deliberately narrow:

| Observed sealed evidence | Adopted P08 class |
| --- | --- |
| retained `buildable=False`, census `CLEAR`, owner `-1`, slope `!= 0` | `TERRAIN_MODIFICATION` |
| any other retained/census shape | refuse the whole application |

All 19 census observations are on the single-instant page
`date_before == date_after == 712225`.

## Why this is technically sound

- All 19 are already in the accepted 77-tile definitional set under policy
  `vacant-projection-1`, with exactly one field outcome:
  `buildable` / `SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE`.
- The root cause is semantic, not missing occupancy evidence: retained
  `buildable` is planner `Vacant()` (flat only), while the census bit is native
  `GSTile.IsBuildable()`; slope alone makes `Vacant` false on otherwise clear
  ground.
- The census facts are coherent and independently classify all 19 as
  `TERRAIN_MODIFICATION` when projected through the existing
  `classify_segment` rules. This decision adds authority, not new geometry.
- No temporal delta or contradiction exists on these tiles; they are outside
  ADR-012's six-tile scope.
- A fresh capture is not the primary path: re-observing the same world would
  reproduce clear sloped ground and the same `Vacant` versus `IsBuildable`
  semantics gap. Fresh evidence is retained as the alternative if the operator
  prefers observation over policy.

## Evidence requirements (fail-closed)

The implementation is explicit-token and refuses everything else:

1. Base reconciliation verdict is exactly
   `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`, with zero contradictions and
   zero unresolved tiles; completeness/manifest verified.
2. The declared scope equals **exactly** the retained-legacy
   `UNKNOWN_OCCUPANCY` set — no extra, missing or duplicated tile.
3. Every scope tile is `SEMANTIC_RECONCILED` with exactly the single
   `buildable` / `SEMANTIC_V1_VACANT_VS_NATIVE_ISBUILDABLE` outcome.
4. Census class `CLEAR`, owner `-1`, slope `!= 0`, and the census projection is
   coherent (`projection_disagrees` false on the census fact).
5. The census page is single-instant for every tile.
6. Retained counts are exactly
   `339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING / 19 UNKNOWN_OCCUPANCY /
   29 UNSUPPORTED_CONSTRUCTION`.
7. Application is derived only: base ledger, base report bytes, sealed
   verdicts and historical counts stay untouched.
8. Any mismatch refuses the whole application; no tile is partially
   reclassified.

## Consequences (activated and verified)

- Derived retained segmentation is
  **339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING / 29 UNSUPPORTED_CONSTRUCTION /
  19 TERRAIN_MODIFICATION / 0 UNKNOWN_OCCUPANCY**.
- The census-backed P08 snapshot assessment remains
  `TERRAIN_MODIFICATION_REQUIRED` (22-tile corridor, `ROBUST`); the ADR-013
  rebinding resolves the derived retained-UNKNOWN blocker without touching the
  assessment input.
- The six temporal tiles remain under ADR-012. The sealed fusion verdict stays
  immutable and the **fusion gate remains closed**; opening it still requires
  the unchanged same-instant criterion, which this policy does not satisfy.
- No native construction, terraforming, authorization or execution
  entitlement is created. Terraform cost and native success stay unproven.
- The separate combined P08 rebinding pass now computes
  `p08_binding.allowed: true` **for planning classification only**
  (`p08_complete: false`), with the fusion gate explicitly closed and no
  native evidence claimed.
- The base reconciliation ledger still records the 19 tiles as
  `UNKNOWN_OCCUPANCY`; only the derived ADR-013 layer maps them. The existing
  retained-only assessment test that pins 19 UNKNOWN remains valid and was not
  weakened.

## Alternatives

- **Fresh same-instant classification capture of exactly these 19 tiles**
  (new reviewed candidate + separate authorization): admissible alternative,
  but it answers an observation question the census already answers; the open
  question is which `buildable` semantics P08 carries. Retained as fallback.
- **Keep the 19 UNKNOWN indefinitely:** would leave the P08 classification
  blocker intact and preserve a known definitional artifact; no longer chosen.
- **Global change to `_legacy_segment`:** rejected. It would silently alter
  historical counts and unrelated tiles; the accepted policy is scope-contained.

## Acceptance tests (implemented)

- Exact 19-tile scope equality; extra/missing/duplicate tile is refused.
- Each tile maps to `TERRAIN_MODIFICATION`; no tile maps to
  `ROAD_BUILDABLE`.
- Non-definitional status, contradiction, unresolved predicate, wrong census
  class/owner/slope, non-single-instant page, count drift or report drift each
  refuses the whole application.
- Base object, base report bytes and sealed verdicts are byte-identical after
  application; derived output is deterministic.
- The fusion gate remains closed. The policy layer itself does not open P08
  binding; only the separate combined rebinding pass does, and that report
  records `p08_complete: false`.

Implemented in `tests/test_p08_policy_rebinding.py` (`TestNativeIsBuildablePolicy`).
The focused file passes **41/41**; the broader reconciliation/snapshot group
passes **83/83**; the feasibility-classification suite passes **24/24**.

## Implementation and rebinding evidence

- `app/simulation/openttd/v2_semantic_reconciliation.py` —
  `NativeIsBuildableDecision`, `apply_native_isbuildable_policy`,
  `NativeIsBuildablePolicyApplication`, `P08NativeIsBuildableRebinding`,
  `rebind_p08_native_isbuildable`; CLI flags `--apply-adr-013` and
  `--rebind-p08`.
- `app/planning/p08_v2_snapshot.py` — optional
  `native_isbuildable_report=` / `--native-isbuildable-report` integration;
  requires the ADR-012 report and emits `native_isbuildable_rebinding` without
  changing the planning input or the pinned base assessment.
- Derived artifacts (all re-derivable from sealed inputs):
  - `artifacts/experiments/v1v2-semantic-reconciliation/native-isbuildable-policy-report.json`
    (sha256 `7616f6262c99dc7a97bd26c0043dcc1c0dc6ba5287f1b203b1ffe72529a3a65d`)
  - `artifacts/experiments/v1v2-semantic-reconciliation/p08-native-isbuildable-rebinding-report.json`
    (sha256 `079fce64c4a37295c05cb87cf129aa9317abccfddba9114bb84341ee04adee62`)
- Unchanged sealed/derived inputs verified after activation:
  - `reconciliation-report.json` sha256
    `c1cfa970c2ccb8310b6bfb1f949ecbd846887ea9c3b04b3b763fe84ef2acf34d`
  - `census-authority-policy-report.json` sha256
    `221ce926cd0b24f3b1e32cb7d73b3844c93b5d9837f03187a2d6d6c15e0faf28`
  - `p08-policy-rebinding-report.json` sha256
    `c9d11d41aba6e937b73897ea9d358897581990788af45c627ad1b32a5b107ed0`
  - `p08-unknown-occupancy-diagnosis.json` sha256
    `66ed07ccf2fb519d713aa6069c51aabb210281e2dbbc2a967eae1c5fe7b7e459`

## Authorization and activation

The operator explicitly approved ADR-013 on 2026-10-25 for the exact 19-tile
scope. This authorization permits offline policy implementation and validation
only. It does **not** permit signing, candidate consumption, OpenTTD launch,
AdminPort access or native execution. No native evidence was collected.

Still closed and not claimed:

- the sealed SOURCE_SAVE_FUSION verdict and the fusion gate;
- any native construction, terraforming or delivery outcome;
- P08 as a complete milestone (`p08_binding.p08_complete: false`).

## Supersession

<!-- none; accepted 2026-10-25 -->

