# D3 Native Integration — preflight preparation handoff

Status: **D3 NATIVE PREFLIGHT PREPARATION READY — candidate-1 PREFLIGHT PASS (verified again for this record); the one and only open item is ONE fresh operator authorization**

This preparation work launched no OpenTTD, opened no AdminPort connection,
consumed no claim, wrote no `AUTHORIZATION.json`, mutated no tile, staged no
pre-launch capability beyond the sealed `PRELAUNCH.json`, and performed no
Git stage/commit/push/reset/clean/stash. All pre-existing uncommitted changes
remain byte-for-byte untouched.

Predecessor record: [d2-native-clearing-candidate-3-preflight.md](d2-native-clearing-candidate-3-preflight.md)
(the shared operator-key provisioning the D3 chain reuses) and
[d2-native-clearing-candidate-3-outcome.md](d2-native-clearing-candidate-3-outcome.md)
(the consumed D2 attempt; **recorded limit: it does not fulfill any D3
prerequisite**).

## 1. What is being prepared — the reviewed Seed-17 levelling chain as fresh save-load candidate compositions

The compiled `p08-terraform` levelling specification (pinned
independently by `tests/test_p08_terraform.py`: proposal
`4d698a9d748922efac8041af909428cd91d3c26409e30f2e698c62dfef8d644c`,
specification `9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d`)
is staged as THREE one-shot native attempts, each a self-contained
operator-authorized ceremony reusing the proven D2 machinery exactly — the
same operator authorization, runtime source freeze (`verify_freeze`,
`require_frozen_d2_closure`, `require_frozen_d2_dependencies`, the frozen
`d2_dependency_inventory()`), immutable launch environment, one-shot claim
and signed replay boundaries. No second security framework exists; the
shared machinery is parameterized at call time (closure root, lineage
schema, census pin) and the D2 ceremony bytes are untouched.

| Attempt | Target | Operation | Census pin (sealed world) | Staged world | Prerequisite |
| --- | --- | --- | --- | --- | --- |
| `D3-CLEARING-1` | tile 45999 | 1 × `GSTile.DemolishTile(tile)` (D2 clearing ceremony on a new tile) | `TREES`, flags 9, elevation 2, slope 0, unowned, page 25 sha `26dae90c…da019` | retained `before.sav` (`RETAINED_SOURCE_SAVE_LOAD`, save sha `e81f6553…117c`) | none |
| `D3-CLEARING-2` | tile 49326 | 1 × `GSTile.DemolishTile(tile)` | `TREES`, flags 9, elevation 1, slope 0, unowned, page 63 sha `b328c57d…302b1` | candidate-1's after.sav via a `d3-native-prerequisite-attempt-v1` record (`PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD`) | candidate-1 consumed |
| `D3-TERRAFORMING-1` | 16 S-corner raises, host tiles 48558, 48559, 48814, 48815, 49070, 49071, 49326, 49327, 49582, 49583, 49838, 49839, 50094, 50095, 50350, 50351 | `GSTile.RaiseTile` per compiled shift; the compiled specification's two clear operations are the completed prerequisites bound through the chain | compiled schedule, plan digest `104484eccd114a4a…57e588` | candidate-2's after.sav (`PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD`) | candidate-2 consumed |

The two clears are never combined in one candidate; each is one
independently pinned, independently authorized attempt. Both clearing
pins carry `manifest_verified` provenance from the sealed census pages of
the retained Tile Classification V2 capture (`classification-exec-seed17-3a8f9e46`).

### Wire exchange accounting (the "2 clears + 16 raises" cost model)

- Each clearing attempt: D2's 8-request bounded budget (`requests: 8`,
  `real_clears: 1`), four exchanges planned (`read-0`, `inspect-1`,
  `clear-1`, `read-2`).
- The terraform attempt: **16 scheduled corner operations × 9 exchanges
  each = 144 planned** (inspect + 3 admission neighbor reads + 1 terraform
  + 4 intent-scoped independent verification reads), **+ 8 diagnostics
  read slack = 152 budgeted requests**; the dispatcher's own pool cap
  stays 296. `MAX_TERRAFORM_COST` = £1,000 per raise-local budget
  (compiled), prefix-preserving halt per
  `app.simulation.openttd.terrain_terraform.terraform_phase_outcome` — a
  halt preserves every already-executed prefix as retained evidence.

## 2. What is staged on disk right now

`artifacts/experiments/d3-clearing-native-candidate-1/` — attempt
`D3-CLEARING-1`, milestone `D3-CLEARING`, schema
`d3-clearing-terraform-native-prelaunch-v1`:

| Fact | Value |
| --- | --- |
| PRELAUNCH seal (exact sha256 of `PRELAUNCH.json`) | `5ec446d8cdbc1de29eb93ac569a53c520fbe643189cc5bd2d33fcb805142e0e8` (recorded in `PRELAUNCH.sha256`) |
| attempt / target | `D3-CLEARING-1` / tile 45999 (pin §1) |
| binary | `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`, sha `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` (pinned, verified) |
| world | seed 17, 256×256, temperate, `start_day 712223`; `RETAINED_SOURCE_SAVE_LOAD` from the retained `before.sav` sha `e81f655363347b808daf07e504dee281144cc095cbec128f0b3c0ff7b127117c`; qualified save digest `a51ffe47…91e93` |
| GameScript identity | `RoadFreightProof` / `1` / `create_instance NetworkFreightProof` (the save's stored identity; `bootstrap_command: start_ai RoadProofCompany`) |
| budgets | `requests 8, real_clears 1, launches 1, connection_attempts 1, reconnects 0, retries 0`, readiness 45 s, request 10 s, total 180 s, `gsadmin_bytes 1450`, `response_bytes 512`, `max_cost 10000`, company 0 |
| isolated workspace | `isolated/openttd-15.3-uzkurhf5` with `openttd.cfg`, `private.cfg`, `secrets.cfg`, source save, full dependency/source freeze frozen into `PRELAUNCH.json` |
| authorization field | `PENDING — requires ONE fresh operator authorization after all preflight gates; offline staging consumed no claim and no authorization file exists` |
| claim | ABSENT (`CLAIM.json` does not exist; nothing can launch) |

Candidates 2 and the terraform candidate are not staged yet — by design:
`REQUIRED_PREREQUISITES = {45999: False, 49326: True}` means their staging
source (the prerequisite's retained after.sav) exists only after the
prerequisite attempt is consumed. Their pins, schedule and digests above
are frozen in the module and re-checked at their own `prepare` time.

### Preflight status

`preflight` (read-only: opens nothing, connects nowhere, consumes nothing)
has now returned **PASS three independent times** — twice during staging
(`prepare`, then `preflight`) and again for this record. The gate list is
the preflight handoff's §4 list: exact binary identity, source-save
identity, candidate seal, source+dependency freeze, staged GameScript
identity, operator key identity, exact execution command, budgets, claim
absence, authorization unconsumed, no conflicting native process.

## 3. The one open item — exact blocker

**Blocker: ONE fresh operator authorization for attempt `D3-CLEARING-1`.**

| Item | Value |
| --- | --- |
| Candidate directory | `/home/fed/codes/softdev2/artifacts/experiments/d3-clearing-native-candidate-1` |
| Exact authorization payload SHA-256 | `71a89503209f1971830211eb4891336b63d6da6b8dbd6fe98ec260d6c25488dc` over 1,474 canonical bytes (sorted keys, compact separators, UTF-8); the canonical bytes are retained at `/tmp/opencode/d3-candidate-1-authorization-payload.json` (sha re-verified for this record) |
| Payload binds | prelaunch seal `5ec446d8…42e0e8`, attempt `D3-CLEARING-1`, milestone `D3-CLEARING`, tile 45999 with its census pin, the full budget table, `max_cost 10000`, binary sha, source-world identity and the exact execution command |
| Exact execution command (if authorized) | `.venv/bin/python -m app.simulation.openttd.proof.terrain_terraform_native run /home/fed/codes/softdev2/artifacts/experiments/d3-clearing-native-candidate-1` |
| Operator key fingerprint | `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` (production anchor; the private key stays operator-held material outside the repository) |
| Signing procedure | identical to the preflight handoff §5 (recompute the payload from the candidate's own staged bytes and the live seal; do not trust any printed copy, including this document; sign with the operator-held key; optional read-only `verify_authorization` self-check). The launch ceremony then re-verifies the record itself (`grant_launch` → one-shot claim → re-verify at the process boundary) before the single authorized launch |
| Explicit approval statement | after a valid `AUTHORIZATION.json` is in place, the operator states the explicit approval for this exact scope (candidate seal, tile, one bounded clear, budget table, command, key identity) in the decision thread, per `docs/handoff/2026-10-17/operator-key-provisioning.md` §5 |

Nothing else is missing: preflight PASS ×3, the claim is absent (grand),
the staged world identity is verified, and there is no conflicting native
process. After candidate-1 is consumed, candidates 2 and 3 of the chain are
staged in turn by the same CLI (`prepare` → `preflight`) and **each of the
three attempts receives its own fresh authorization** — the chain never
reuses a claim or an authorization.

## 4. Evidence contracts this preparation freezes (for replay/audit honesty)

- **Authorization/launch lineage**: clearing attempts keep the proven D2
  one-shot claim and `d2-clearing-native-launch-consumed` launch marker
  (`ClearingNativeBackend.launch_marker_schema`); D3's own schemas are
  `d3-clearing-terraform-native-prelaunch-v1` (the staged prelaunch),
  `d3-native-prerequisite-attempt-v1` (the prerequisite binding consumed
  by candidates 2/3) and `d3-native-launch-consumed` (the terraform
  attempt's launch marker).
- **Staged-world duality**: `d3_preflight`'s pin gate accepts BOTH staging
  modes — the retained `before.sav` for `D3-CLEARING-1` and the
  prerequisite after.sav for the later attempts — and every other mismatch
  fails closed.
- **Shared transport**: the controlled terraform peer delegates the
  handshake to the shared D2 `ControlledClearingPeer` and dispatches
  authenticated frames inside its own `write()` (PONG → gamescript
  dispatch); no inline crypto re-implementation exists anywhere in D3.
- **Replay loading** (mirror of D2): non-`SERVER_GAMESCRIPT` inbound frames
  are skipped; `intent` is loaded via `TerraformIntent.model_validate_json`
  (strict dicts cannot coerce JSON lists into tuples natively) plus the
  `built` readback; receipt comparison is normalized by JSON round-trip
  (tuple/list asymmetry).
- **Terraform wire contract**: protocol-3
  `TerraformRequest`/`TerraformReadback`/`TerraformIntent` with
  `terraform_phase_outcome` halt semantics
  (`app/simulation/openttd/terrain_terraform.py`); the terraform payload
  reuses the D2 scalar `target_tile` request shape and adds the additive
  `operation_schedule` + `plan_digest` keys in the same shared envelope.

## 5. Offline validation performed

| Suite / check | Result |
| --- | --- |
| `tests/test_terrain_terraform_native.py` (staging, pins, schedule, budgets, payload-builder reuse, gates, freeze drift, chain rehearsals, full terraform phase, halt-prefix-preserved, claim gates) | 23 tests PASS |
| module lints | ruff clean |
| `preflight <candidate-1>` (read-only) | PASS ×3 (two during staging, one for this record) |
| retained canonical authorization payload | sha `71a89503209f…488dc` re-verified; 1,474 bytes |
| D2 pre-edit regression totals (the four suites `test_terrain_clearing.py`, `test_terrain_clearing_native_prep.py`, `test_terrain_clearing_adversarial.py`, `test_terrain_terraform.py`) | 190 dots, all PASS |
| D2 final re-validation of the same four suites (post all session edits, one run, offline) | 194 collected = 36 + 74 + 53 + 31, **194 dots at [100%], zero failure/skip letters, process exit 0** |
| pinned D3 literals re-checked independently | `tests/test_p08_terraform.py` proposal/spec digests unchanged (`4d698a9d…8d644c`, `9e70b360…5a0d1d`) |

Recording note: the in-process Squirrel VM extension
(`_squirrel.cpython-314-x86_64-linux-gnu.so`) writes `Time difference = 0[ms]`
lines directly to file descriptor 1 and terminates via C-level `exit(0)`,
which suppresses pytest's own summary line; the pass/fail reading above comes
from the progress letters (dots only, no `F`/`E`/`s`/`x`) and the collected
test counts. No native process is involved — the noise is a local, in-process
artifact, and the suites remain strictly offline.

## 6. Honesty and limits

- **No native execution has happened for D3.** Every fact in this
  document is offline: staged bytes, sealed census pins, compiled
  schedule digests and controlled-peer tests. Whether the staged chain
  runs natively to completion is exactly what the three authorized
  attempts will prove or fail to prove.
- **D2's consumed 46769 attempt does not carry over.** Different tile,
  different pinned evidence, different attempt identifiers, own claim,
  own authorization per attempt.
- **A halt preserves the prefix.** If the terraform phase halts (budget,
  health or pin drift), the already-executed raise prefix remains as
  retained evidence and the receipts bound it; nothing beyond the prefix
  is claimed.
- **No construction claims.** No P05/P07 service, delivery, OPEX, ROI or
  corridor claim follows from clearing two trees and raising sixteen
  corners; constructing the road is future, separately authorized work.
