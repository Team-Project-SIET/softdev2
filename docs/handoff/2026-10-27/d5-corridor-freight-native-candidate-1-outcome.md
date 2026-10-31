# D5 native freight POC — candidate-1 consumed outcome: Attempted, refused at site admission

Status: **`D5-FREIGHT-1` CONSUMED EXACTLY ONCE under the operator authorization
record dated 2026-10-27 (this session's task brief) covering signing and exactly
one bounded native attempt. The attempt ran to its first real gate: the native
`site-00` admission returned `READY` with every pinned corridor world fact
correct — funds £492,149 exactly, all 23 witness pairs `pairs_ok 23`, pickup-side
industry 0 production 104 — but the delivery stop's cargo-1 acceptance read
**0** (below the design's required ≥ 1/8), the pinned admission refused
before any mutation, and the runner halted with zero-cost, zero world change.
Result `verified: false`, `status: PHASE_HALTED_PREFIX_PRESERVED`,
`world` unmutated. **Milestone D5 (native pickup→delivery freight cycle) is
ATTEMPTED, NOT DELIVERED** — a valid experimental result, never a pass.**

Date: 2026-10-27. Predecessors:

- [T7 review + addendum 14](../../d5-corridor-freight-t7-review.md) (suitable-to-proceed verdict)
- [D5 design](../../../docs/d5-corridor-freight-design.md) (risk table row:
  "Delivery-stop acceptance below 1/8 natively … admission refuses before
  mutation → typed `INVALID_SITE`; no order, no purchase; the acceptance fact
  will then be the design finding of record")
- [candidate-5 D4 outcome](../2026-10-26/d4-corridor-native-candidate-5-outcome.md) (source world)

## 1. What happened, in order

1. **Staging (T8).** Fresh candidate `D5-FREIGHT-1` staged at
   `artifacts/experiments/d5-corridor-freight-native-candidate-1/` from the
   reviewed working tree (HEAD `1e6d6c1…94a96f`, byte-identical dirty set =
   the §14-reviewed bytes). `PRELAUNCH PASS` at prepare; a separate fresh
   read-only `PREFLIGHT PASS` re-ran after staging. Seal
   `c8bdc65f…d0f7c9` (= `sha256(PRELAUNCH.json)` = `PRELAUNCH.sha256`),
   schema `d5-freight-prelaunch-v1`, 15 planned exchanges / request cap 32,
   per-op ceiling £2,000, total budget 900 s, source-save binding =
   candidate-5 authoritative after-save
   `a81ac836…ef261`, frozen source closure 3,486 entries, route digest
   `6bc6c00b…fc4542` digested into every planned exchange payload.
2. **Gate C signing.** Canonical authorization payload rebuilt offline from
   the staged bytes: sha-256 `fdb1325f…3f75c7` (2,410 bytes), recomputed
   twice (in-module digest helper matches). The documented Option-1
   repository-tooling checklist was executed exactly
   ([key provisioning §1/§4](../2026-10-17/operator-key-provisioning.md)):
   refusal gates first (`AUTHORIZATION.json`/`CLAIM.json`/
   `LAUNCH-CONSUMED.json` absent), seed extracted from the operator-held PEM
   into a shell variable via the corrected exit-status/shape-checked pipeline
   (never printed, never passed as an argument), derived public key checked
   equal to the pinned production anchor
   `5063982b…4880f`, 64-byte signature verified under that anchor over the
   exact canonical bytes **before** writing, `AUTHORIZATION.json` written
   (sha-256 `f99e8233…7fde`), seed cleared immediately (`unset`, verified
   empty). Two earlier signing-debug substeps found no write path issues:
   one attempt used an argument-ordered `verify()` call incorrectly, one
   used the record in place of the prelaunch as `metadata` — in both cases
   the signature itself had been verified before any write, `verify_authorization`
   then returned PASS on the written record: operator identity
   `sha256-ed25519-public-key:cbb63ff5…40c614` (unchanged production anchor).
3. **The one attempt.** `run` consumed the claim exactly once:
   1 launch (OpenTTD 15.3, dedicated, pid 15053), 1 fully encrypted X25519
   AdminPort connection, welcome identity matched exactly
   (`revision 15.3`, `seed 17`, `landscape 0`, `256×256`, `start_day 712223`).
   Staged composition announced and started
   (`[18] [I] D5_READY`), and the GameScript answered the first planned
   exchange `site-00`.
4. **The halt.** Native `site-00` response retained
   (`site-00-response.json`):
   `status READY`, `funds 492149` (exactly the D4 close-out figure),
   `pairs_ok 23` / `pair_total 23` (the whole 24-tile witness connected natively),
   `prod 104` (pickup industry 0 producing cargo 1), `wait 0`,
   `owner 0`, both stops truck stops, depot joined to its pinned front,
   `vehicles 0` — but `accept 0`. The admission policy
   (`admit_freight_site` in `app/simulation/openttd/proof/corridor_freight_native.py`,
   mirrored by the package's own local check) refuses any delivery-catchment
   acceptance below the required 1 freight-eighth, so:
   - **no order was set, no engine quoted, no vehicle purchased**
     (`engine -1`, `vehicle -1`, `cost 0`, `command_accepted false`),
   - funds stayed at £492,149 — every-penny unchanged,
   - `state_changed false`, phase `PARTIAL_EXECUTION_EVIDENCE` with zero
     completed operations, `status PHASE_HALTED_PREFIX_PRESERVED`,
     four certification flags true in `cleanup.json`
     (credential removed, process reaped, listener closed, workspace
     disposed; connection probe false opportunistically recorded as
     expected), 16/16 manifest OK, returned exit 1.

## 2. Read-only replay verifier

`corridor_freight_native verify` over the consumed candidate returns
`PHASE_HALTED_EVIDENCE_PRESERVED` for the first honest refusal — the message
exactly matches the run's halt (`delivery acceptance below 1/8 refuses the
site admission`), all fifteen original decision bytes unchanged:
0 completed, 0 pending, `failed` records `site-00`, `status READY`.
No receipt, no `after.sav`, `session-before.sav`
being the only own-save. Nothing in the replay path can convert this into
`RECEIPT_VERIFIED`.

## 3. The finding of record

**The pinned delivery stop (`50351`, front `50095`) has zero cargo-1
acceptance in the pinned live world on OpenTTD 15.3.** The design's own risk
table anticipated exactly this refusal, and the D5 offline preparation
records had already measured acceptance 0 at that location pre-construction.
The freight cycle therefore does not exist on this corridor stop placement:
without a cargo-1 catchment the vehicle could load (the pickup side reads
production 104) but the delivery side could never unload a full load profitably;
a retreated full-load order would cycle empty.

Per the D5 Gate D discipline:

- **D5 is ATTEMPTED, NOT DELIVERED.** No D5 criterion A4–A10 was even
  attempted; A4 failure (`accept < 1`) stops everything.
- No "optimizer-selected native construction" claim (M8 limit unchanged):
  this attempt only proves the one fixed corridor's facts.
- Consumed identity is closed forever: `D5-FREIGHT-1` must never be retried,
  re-signed, or reused. A future attempt needs a fresh reviewed candidate,
  fresh explicit authorization, and — critically — a delivery stop whose
  native cargo-1 acceptance fact is re-derived first (a new fixed-stop
  design transition, or an industry-station kitchen design change, never a
  silent byte tweak of the pinned stop tile).

## 4. Preservation statement

No `.perch/`, no excluded file, no `OpenTTD-Knowledge/.obsidian/workspace.json`
byte was touched beyond the pre-existing dirty state. Candidate-5 (90/90 OK)
and candidate-4 (80/80 OK) manifest verification re-verified byte-unchanged
after the attempt, and the staged composition's source-save binding to the
candidate-5 authoritative after-save `a81ac836…ef261` was proven inside the
fresh read-only `PREFLIGHT PASS`. The staged composition's isolated workspace was disposed by certified
cleanup; the candidate directory retains `PRELAUNCH.json/sha256`,
`AUTHORIZATION.json`, consumed `CLAIM.json`/`LAUNCH-CONSUMED.json`,
`result.json`, `cleanup.json`, `frames.json`, the retained `site-00` pair,
`session-before.sav` (sha
`67099b50…56643`), `runtime-identity.json`, both logs and a 16-file
`artifact-manifest.sha256` re-verifying 16/16 OK.

**Limits:** fixed-corridor-only POC — the outcome proves nothing about route
choice M8, OPEX/net-profit/ROI (still UNKNOWN), or any other service, world or
network. This attempt's `site-00` native facts (`funds 492149`,
`pairs_ok 23`, `prod 104`, `accept 0`) are retained natively observed.
