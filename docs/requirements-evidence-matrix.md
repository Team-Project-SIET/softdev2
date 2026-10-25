# Requirements → evidence matrix (single consolidated view)

**Date:** 2026-10-25. Offline consolidation only. This matrix summarizes
already-retained evidence; it creates no native authority and does not relabel
any failed, rejected, consumed or sealed outcome. Status vocabulary:
`PROVEN`, `CONTROLLED`, `PREPARED`, `PARTIAL`, `FAILED`, `UNKNOWN`. A test or
offline derivation is not native proof.

| Requirement / acceptance condition | Status | Evidence | Remaining gap / boundary |
|---|---|---|---|
| Stable fixed-demo native gameplay: selected services, deliveries, revenue, spectator, P07, cleanup | **PROVEN** (native 15.3, scope-bound) | E1; `artifacts/demos/playable-demo-25d891bc…/` | No direct company control; no full OPEX/profit/ROI |
| Canonical create + fresh-process reload Q3 correspondence | **PROVEN** (historical engineering; reload-only) | E2; `artifacts/runtime/canonical-fleet-{create,reload}-q3/` | Purchase/dispatch/unpause not exercised |
| Random World generation, discovery, spectator, cleanup | **PROVEN** (Seed 17 native) | E4, E8 | Service execution is a separate, failed outcome below |
| Seed 17 native coal-pair feasibility through P08/P05 | **FAILED** (terminal), with complete-search infeasibility proof | E8, E9, E10 | Do not promise a feasible route; no retry of the consumed identity |
| Tile Classification V2 native census capture | **PROVEN** (capture only) | E16; `artifacts/demos/classification-exec-seed17-3a8f9e46/` | Capture success is not world correspondence |
| `SOURCE_SAVE_FUSION` correspondence / fusion gate | **FAILED / CLOSED** (sealed `REJECTED`, 83 disagreements) | E16, ADR-010 | Same-instant criterion structurally unmet; no relabeling |
| Offline V1/V2 semantic reconciliation (77 definitional / 6 temporal / 0 contradictions / 0 unresolved) | **CONTROLLED** (offline replay) | `reconciliation-report.json`; `docs/p08-v1v2-semantic-reconciliation.md` | Base remains `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` |
| Six temporal tiles under ADR-012 (save-instant census authoritative for planning evidence) | **CONTROLLED** (policy layer) | ADR-012; `census-authority-policy-report.json`; `p08-policy-rebinding-report.json` | Planning evidence only; base keeps `TEMPORAL_SECOND_INSTANT` |
| Nineteen definitional retained-UNKNOWN tiles under ADR-013 (native `IsBuildable` → `TERRAIN_MODIFICATION`) | **CONTROLLED** (accepted policy, fail-closed offline) | E25; ADR-013; `native-isbuildable-policy-report.json` | Native `IsBuildable` semantics adopted by policy, not fresh native capture; base keeps `UNKNOWN_OCCUPANCY` |
| Combined P08 planning binding after ADR-012 + ADR-013 | **CONTROLLED** (`allowed: true`, `p08_complete: false`) | `p08-native-isbuildable-rebinding-report.json`; snapshot with both reports | Fusion gate closed; no native construction/delivery/execution evidence |
| D2 native clearing (tile 46769) | **PROVEN** (native, one tile) | E17 | One tile only; no road/service claim |
| D3 native clearing + bounded terraforming (finances reconcile) | **PROVEN** (native, scope-bound) | E19; post-D3 after-save `fbebef54…d59e` | No road/stop/depot constructed |
| D4 native road + station construction | **FAILED / INCOMPLETE** (two attempts consumed; offline `op-03` correction added) | E21, E28, E29 | `D4-CORRIDOR-1`: run-B exceeded per-op ceiling, only `op-00` verified. `D4-CORRIDOR-3`: 3/8 ops built; `op-03` redundant interior join was correctly `NOT_BUILDABLE` (`pairs_ok 1`); no authoritative after-save/receipt; cleanup incomplete. E29 identifies the scheduling/modeling defect and defines an offline v3 7-op schedule with no interior join, preserving v1/v2 replay |
| D4 `D4-CORRIDOR-2` fresh candidate | **STALE / SUPERSEDED** (never consumed) | E24; `artifacts/experiments/d4-corridor-native-candidate-2/` | Frozen closure predates the ADR-012/ADR-013 source edits; read-only preflight now fails `verify_freeze`. Not edited or reused |
| D4 `D4-CORRIDOR-3` fresh candidate | **CONSUMED ONCE / PARTIAL** (`verified: false`) | E27, E28; `artifacts/experiments/d4-corridor-native-candidate-3/`; seal `8cc8c1f7…7d24`, payload `e1163d09…068d`, authorization `5484cdc1…3be705e` | `op-00`–`op-02` built and read back (£496,543 → £493,209); `op-03` interior join refused at admission, `op-04`–`op-07` and route read not executed; no receipt-bound after-save; replay refuses incomplete cleanup. Must not be retried or reused |
| Repository authority-pin integrity | **PROVEN** (offline, explicit repair) | E26; ADR-014; `docs/authority/context-authority-supersession.json` | Historical 2026-10-08 bytes are not retained; the record scopes only the exact path/digest transition, all other entries remain byte-exact |
| P07 offline analytics extension | **CONTROLLED** (offline; advisory) | P07 analytics record; retained Attempt 19/fixed-demo evidence | No new native OPEX/profit/ROI facts |
| Full OPEX / net-profit / ROI | **UNKNOWN** | — | Never invent; requires native accounting evidence |
| Native execution / AdminPort / signing / candidate consumption for ADR-013 | **NOT AUTHORIZED** | Operator authorization (2026-10-25) | Explicitly excluded from the ADR-013 authorization |

## Key boundaries

- `p08_binding.allowed: true` in the combined rebinding is **planning
  classification only**. It is not a fusion verdict, not native proof and not
  completion of P08 (`p08_complete: false`).
- The sealed fusion verdict remains `REJECTED`; the fusion gate remains
  **CLOSED**.
- The base reconciliation ledger and all consumed/frozen evidence remain
  byte-unchanged; ADR-013 changes only the derived policy view.
- Native proof for the 19 tiles, D4 completion and full OPEX/ROI remain
  uncollected and require separate authorization.
- `D4-CORRIDOR-2` is stale by construction (later accepted source edits); it is
  not launchable and must not be edited or reused. `D4-CORRIDOR-3` was the only
  launchable candidate, was consumed exactly once on 2026-10-25, and must not
  be retried or reused. Its `after-diagnostic.sav` is not an authoritative
  save. E29 corrects the `op-03` defect offline: the interior join was
  redundant because collinear `BuildRoadFull` endpoints auto-connect; v3
  schedules 7 ops and keeps the perpendicular corner join. D4 still needs a
  fresh identity, code review and separate operator authorization.
