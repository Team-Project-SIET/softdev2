# Bounded tile clearing construction support (OpenTTD 15.3, D1/D2)

Status: offline implementation and controlled validation complete; **native
clearing execution remains unsupported** until a separately reviewed one-shot
authorization. Nothing here launched OpenTTD, connected to the AdminPort,
performed a native mutation, edited the frozen Tile Classification observation
package, or claimed the V1/V2 `SOURCE_SAVE_FUSION` verdict is anything other
than REJECTED.

## Why this milestone exists

The V2 snapshot P08 corridor needs exactly two bounded clearing operations
(`required_ops: clear [46769, 47537]`) and the levelling proposal clears
`[45999, 49326]` before any road can be admitted. This milestone implements
the smallest safe demolition contract, reusing the verified road-mutation
ceremony rather than inventing a new execution framework.

## D1 — reusable-contract mapping (verified road pipeline → clearing)

| Verified road component | Clearing counterpart |
| --- | --- |
| `RoadSegmentIntent` + `admit_segment` (`app/simulation/openttd/road_mutation.py`) | `ClearingIntent` + `admit_clearing` (`app/simulation/openttd/terrain_clearing.py`) |
| `RoadRequest` (protocol 1, op inspect/build/read, `^[a-z0-9-]{1,32}$` request id, plan-digest bound, canonical ≤512 bytes) | `ClearingRequest`, identical rules, single `tile` 0..65535 (covers the 64×64 disposable mutation world and the retained 256×256 Seed 17 world) |
| Native test quote: `GSTestMode()` + `GSAccounting().GetCosts()` around the exact command | Same ceremony per tile around `GSTile.DemolishTile(tile)` |
| One latched real command (`attempted` set before the command, including a rejected command; no retry) | `attempted[tile]` per-tile latch; stricter than road only in that a post-failure re-inspect answers `ALREADY_ATTEMPTED` instead of re-quoting (fail-closed) |
| Independent readback: fresh native state | Fresh full 15-predicate classification + owner + elevation/slope/funds (predicate set identical to `terrain_classification.nut`; frozen package untouched) |
| `verify_segment` receipt | `verify_clearing` → `company-clearing-receipt-v1` |
| Secured session and staging budget (`proof/road_mutation.py`) | Same runtime ceremony shape; the plan-digest correlation and duplicate-key gates live in the contract layer (`road_mutation.py`), as the mirrored clearing ones do; a dedicated mutation-proof run needs a NEW reviewed staging contract (below), so none was written |

Exact verified sequence reused: **Intent → Admission (inspect readback) →
latched build request → Native test quote → Native execution → Independent
readback → Verified receipt**.

## D2 — implemented surface (offline)

- `app/simulation/openttd/terrain_clearing.py` — `ClearingIntent`
  (binds `expected_classification`, sealed pre-launch/save digests, tested
  cost), `ClearingRequest`, `ClearingReadback` (`parse_for` correlation on
  protocol/op/request_id/plan/company/tile with duplicate-key and 512-byte
  gates), `admit_clearing`, `verify_clearing`, `phase_outcome`.
- `app/simulation/openttd/terrain_clearing_package/{info,main}.nut` —
  separate additive GameScript package; the only mutation command is
  `GSTile.DemolishTile` in company mode (test quote once, real command once);
  a static test forbids RaiseTile/LowerTile/BuildRoad/BuildDock/BuildObject/
  BuildBridge/BuildTunnel.
- `app/planning/p08_clearing.py` — `ClearingPlanCandidate` plus
  `candidates_for_proposal` / `candidates_for_clear_requirement`; candidates
  are census-evidence-bound (allowed class, unowned, geometry) and are
  `PLANNING_ONLY`.
- `tests/test_terrain_clearing.py` — 34 controlled tests on a real Squirrel
  VM with verified-API stubs.

### Admission/execution rules (fail-closed)

- Allowed clearing classes only: `TREES`, `FARM`, `ROUGH`, `ROCK` (single
  class by the frozen `classify_tile` precedence; contradictory or unknown
  occupancy is refused, `UNKNOWN_OCCUPANCY` included).
- Ownership: only `GSCompany.COMPANY_INVALID` (-1) is admissible;
  company-owned or protected infrastructure is `OWNERSHIP_MISMATCH`.
- Already-clear tile ⇒ `NO_OP`: no quote and no demolition command is
  triggered, and admission refuses to build an intent from it.
- Before any command: world identity (plan digest = pre-launch seal), tile
  identity (`IsValidTile` + x/y parity), company resolution and mode
  validity, classification eligibility.
- Cost ceiling and funds: positive tested quote ≤ `max_cost`, bank balance ≥
  quote; otherwise `COST_LIMIT` / `INSUFFICIENT_FUNDS` and no execution.
- After execution the receipt requires: obstruction actually removed
  (re-classification is exactly `CLEAR`), tile valid, geometry unchanged
  (elevation/slope identical to the pre-clear readback), no ownership
  change, no industry pointer, executed cost == tested quote, funds delta ==
  cost. Any disagreement fails the receipt without retrying.
- Test/exec disagreement, native command failure, forbidden re-clear, and
  duplicate request ids all halt the phase; `phase_outcome` verifies
  preserved evidence only — first failure marks the halt position, keeps
  verified prior receipts, reports later attempts as pending, and never
  retries or compensates.
- `GSTile.IsBuildable()` is held to be a host readback predicate, never proof
  that a cleared tile is road-ready; construction-readiness gates stay
  upstream in the P08 corridor assessment.

## Seed 17 controlled binding (V2 census snapshot)

- Levelling proposal `cleared_tiles` = 45999 (TREES, elevation 2, slope 0),
  49326 (TREES, elevation 1, slope 0); assessment clear requirement = 46769
  (TREES, elevation 2, slope 0), 47537 (ROUGH, elevation 1, slope 13). All
  four candidates validated unowned against the retained census (pages 25,
  63, 34 and 43 respectively, single-instant bracket 712224–712226) and
  emitted `PLANNING_ONLY`.
- Terrain-height operations remain `PLANNING_ONLY`; no proposal is marked
  natively executed and no fusion evidence is created.

## Native API compatibility review (official 15.3 tag sources)

- `GSTile.DemolishTile(tile)` (`CMD_LANDSCAPE_CLEAR`) is valid in company
  mode and is the demolition surface for trees, farm fields, rough and rocky
  ground; quotes are captured through the same test-mode/accounting pattern
  the verified road pipeline used.
- Cost readback uses `GSAccounting().GetCosts()` around the exact command in
  test mode and again around the real command, so quote/exec disagreement is
  independently observable.
- Geometry readbacks come from `GSTile.GetMinHeight` + `GSTile.GetSlope`
  before and after the command (no `GetCornerHeight` needed for clearing);
  rough-ground demolition preserves slope — the contract enforces exactly
  that and fails closed if native behavior ever differs.
- Map/tile identity assertions mirror the staged classification bridge
  (`GetTileX/GetTileY/GetMapSizeX`), keeping wire facts byte-comparable so
  census expectations and execution readbacks can be diffed mechanically.

## What a real one-shot native clearing validation still requires

1. A separately reviewed staging/reservation contract that names the NEW
   package (`terrain_clearing_package`), the exact tile(s), the company,
   cost ceilings and world identity; the existing road staging contract is
   road-specific and must not be silently reused.
2. A same-session paired capture through the one qualified session: pre-clear
   classification readback, quote, command, post-clear readback for each tile
   (the `SAME_SESSION_CENSUS` schedule pattern), with artifact manifests.
3. Fresh retained runtime identity + pre-launch seal re-verification; the
   clearing receipt binds those digests exactly as the road receipt does.
4. The V1/V2 fusion verdict stays REJECTED regardless; no fusion is needed
   for a clearing-only validation, and none may be manufactured.

## Recommended D3 (terraforming milestone)

Bounded corner terraforming on the retained levelling corridor with the same
ceremony: per-op intent (`RaiseTile`/`LowerTile` corner ops), test quote,
one latched command per op, post-op `GetCornerHeight` readback compared to
the census-derived target vertices, per-op receipts, cumulative cost ledger,
fail-closed phase handling, and a separately reviewed staging contract. It
must not reuse the clearing package bytes; it is a new package and a new
one-shot authorization.
