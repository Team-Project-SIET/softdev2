# D4 corridor Option C implementation — independent offline review record

Status: **`PASS WITH CONCERNS`** — the reviewed Option C implementation and its
controlled tests are correct and sufficiently tested for every in-scope question of
this review; two non-blocking code observations and one documentation defect (fixed
during this review) are recorded below. This is a **read-only review record**: the
review session modified no source file, no test, no candidate artifact, no retained
evidence, no save, and performed no Git stage/commit/push/reset/clean/stash; it
launched no OpenTTD process and connected to no AdminPort; it created, consumed or
modified no authorization or claim; it staged no fresh candidate. The only writes of
this session are this record, the E23 evidence-index entry (root + vault), and the
justified Obsidian/notebook documentation updates listed in §8.

Reviewed artifact: the uncommitted E22 work —
`app/simulation/openttd/proof/corridor_construction_native.py`,
`app/simulation/openttd/d4_corridor_package/main.nut`,
`tests/test_corridor_construction.py`, `tests/test_corridor_construction_native.py`
(working tree of `devmodule2`, HEAD `f5d2f1e`), plus
[the implementation record](d4-corridor-option-c-implementation.md).

## 1. Review scope and baseline

- Repository `/home/fed/codes/softdev2`, branch `devmodule2`, HEAD
  `f5d2f1e4a8557ea7c93964dc758f7a22c7be4b5c` at review start; the branch also holds
  commit `5872689` referenced by the vault snapshot.
- Working tree dirty (intentional project state): the four review-target files plus
  the E22 documentation (root + vault) are modified; `docs/handoff/2026-10-22/`
  `d4-corridor-option-c-implementation.md` is untracked (the reviewed record).
- Pre-existing unrelated change preserved untouched: `mise.toml` (+1 line,
  `bun = "latest"`) — outside this review's scope and never edited. *(End-of-review
  observation: at final verification the working tree showed `mise.toml` clean vs
  HEAD — the `bun = "latest"` line is no longer present in the checkout; HEAD itself
  is unchanged and its `mise.toml` history goes back to `8d2fc9e`. This review edited,
  removed and restored nothing in that file.)*
- Untracked files left untouched by this review: `--version` (accidental redirect of
  an `ls --version` command: coreutils license text), `OpenTTD-Knowledge.zip`,
  `opencode-debug.log`, `docs/handoff/local-artifacts-before.json`,
  `OpenTTD-Knowledge/.obsidian/`.
- **Inventory discrepancy (recorded honestly):** the review request named
  `app/simulation/openttd/proof/corridor_construction.py`; no such file exists. The
  wire contract is `app/simulation/openttd/corridor_construction.py` (verified
  **unmodified** vs HEAD: empty diff; sha256
  `a494f577cba261c55bc35dbb51455b76787dc23f8f4e98e9202f0c30db02cc7f`). Everything in
  this record refers to that actual path. The file inventory and claimed state
  otherwise matched the live checkout exactly (diff-stat, test counts, and the
  pre-existing `mise.toml` change).
- The consumed candidate `artifacts/experiments/d4-corridor-native-candidate-1/` was
  only ever read; its 28-file `artifact-manifest.sha256` was hash-verified read-only
  immediately before and immediately after every replay/test interaction (56/56 OK),
  and its `isolated/` workspace husk is an empty directory owned by the retained
  staging (`retain=True`); it was not touched.

## 2. Independent verification performed (actual commands and results)

| Check | Command | Result |
| --- | --- | --- |
| Focused offline suites | `.venv/bin/python -m pytest tests/test_corridor_construction.py tests/test_corridor_construction_native.py -q` | exit 0; **55 progress markers, all passed dots, 0 failed, 0 skipped** (the in-process Squirrel extension suppresses pytest's terminal summary; the counts were cross-checked with `--collect-only`: wire 23 + native 32); both consumed-artifact replay tests ran (not skipped — the retained evidence is present) |
| Lint | `.venv/bin/python -m ruff check` on the changed module + both test files | exit 0, "All checks passed!" |
| Byte-compile | `.venv/bin/python -m compileall` on the two modules + both test files | exit 0, clean |
| Whitespace hygiene | `git diff --check` | exit 0, clean |
| Production read-only replay of the consumed candidate | `.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native verify artifacts/experiments/d4-corridor-native-candidate-1` | exit 0; verdict **byte-identical to the E21 close-out**: `PHASE_HALTED_EVIDENCE_PRESERVED`, `completed ["full"]`, `failed op-01` (native admission refusal), `pending op-02…op-05` |
| Evidence manifests, before and after | `sha256sum -c artifact-manifest.sha256` inside the consumed D4 candidate and the D2/D3 candidates | consumed D4 28/28 OK (before) and 28/28 OK (after); D2 clearing candidate-3 26/26; D3 clearing-1 26/26, clearing-2 26/26, terraforming-1 385/385 — zero mismatches in every run |
| Pinned D3 after-save | `sha256sum artifacts/experiments/d3-terraform-native-candidate-1/after.sav` | unchanged `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`; diagnostic save remains distinct (`2942b778…25b07`) |
| Independent derivation probe | in-process read of the module's own derivations | exact results in §3 |

Not run: typecheck (`mypy`/`ty`/`pyright` absent from the venv — environment gap,
honest, unchanged); neighboring suites (p08 road/terrain, D3 native staging suite) —
justified below; no native/OpenTTD execution of any kind.

## 3. Schedule geometry and operation ordering — independently confirmed

The module's `corridor_schedule()` derivation (re-executed offline in this review,
not copied from any record) produces **exactly the eight operations proposed**:

| Index | Operation | Pins (derived + asserted) | Native preconditions |
| --- | --- | --- | --- |
| 0 | `full` run A | `45747 → 45743`, run_len 5, tiles = witness[1..5] | endpoints unowned, roadless |
| 1 | `full` run-B segment 1 | `45999 → 48047`, run_len 9 | endpoints unowned, roadless |
| 2 | `full` run-B segment 2 | `48303 → 50095`, run_len 8 | endpoints unowned, roadless |
| 3 | `road` interior join | `48047 ↔ 48303` | both endpoints company road (after ops 1–2) |
| 4 | `road` corner join | `45743 ↔ 45999` | both endpoints company road (after ops 0–1) |
| 5 | `station` pickup | tile `45748`, front `45747` | unplanned footprint, company-road front |
| 6 | `station` delivery | tile `50351`, front `50095` | unplanned footprint, company-road front |
| 7 | `depot` | tile `45487`, front `45743`, orientation `south` | unplanned ground, company-road front |

Independently verified in this review:

- **Witness preservation:** `corridor_facts()["corridor"]` is the 24-tile ordered
  witness `45748,45747,…,45743,45999,…,50095,50351`; 23 adjacent pairs, zero
  adjacency violations; `route_policy()["witness_path"]` equals it.
- **Segment geometry:** split point `(17+1)//2 = 9`; segment A = `run_b[:9]`,
  segment B = `run_b[9:]`; `segment_a + segment_b == run_b`; both segments are
  straight, contiguous `+256`-step walks on the compiled run-B axis; the interior
  join is exactly the shared edge (`segment_a[-1] = 48047`, `segment_b[0] = 48303`),
  each endpoint carrying its own company road from its segment op before the join
  runs (index 3 > 1 and 2); the corner join is unchanged at index 4 (after run A
  op-0 and segment 1 op-1 — its own two coverage preconditions are satisfied with
  slack from the interior join's placement; ordering is safe).
- **Array-shape checks fail closed:** the derivation refuses segments shorter than
  2 tiles, non-reassembly, non-adjacent interior endpoints (±1/±`CORRIDOR_WIDTH`
  check), corner drift, index drift from `0..ROAD_OP_COUNT-1`, and out-of-bound
  spans/pins (`MAX_FULL_SPAN = 36`; largest scheduled run delta is 16).
- **Geometric description is unchanged:** `corridor_facts()` is byte-untouched by
  the diff and still derives exactly two straight runs and one corner from the
  witness; both joins are build (`road`) ops with their own admission, never a
  second geometric corner; `route_policy()` is untouched.
- **Stops and depot keep their pinned roles and order:** pickup at index 5 fronts
  the (built) run A start; delivery at index 6 fronts the (built) run B end
  (50095); the depot at index 7 fronts run A's end — the front tiles are company
  road by the time each site op runs, satisfying `admit_corridor`'s site pre-state.

## 4. Schedule-version compatibility and replay — independently confirmed

- **Selector binding:** `plan_policy()` pins `schedule_version: 2` and
  `prepare_candidate()` refuses any drift (`len(schedule) != ROAD_OP_COUNT`,
  index drift, or the version key ≠ 2). Fresh staging binds the 8-op derivation,
  whose plan digest (`2a30e950…cabb3a`) differs from the historical v1 digest.
- **Consumed-record compatibility:** the retained `D4-CORRIDOR-1` plan record
  carries **no `schedule_version` key**; `staged_plan_schedule()` defaults absent →
  v1. Re-derived from the current pinned facts, `plan_digest_of(corridor_schedule_v1())`
  equals the consumed record's stored digest `3bf3eddf…d8a912` **exactly**, and the
  derived v1 schedule equals the retained record's schedule — the binding is
  re-derivable, not hand-retold. The production `verify` replay (§2) then returned
  the historical verdict verbatim, with the v1-derived pending list `op-02…op-05`
  proving the selector actually selected v1 in the live replay path.
- **Fail-closed versions:** `{"schedule_version": 0}`, `2`-as-string, `3`, `null`,
  and a non-integer all raise `ValueError` — no best-effort guess.
- **No captured-result trust:** `verify_corridor_attempt()` recomputes the phase
  per op from retained `corridor-{pos}-*.json` evidence via
  `corridor_phase_outcome()` and cross-checks the retained `result.json`'s
  status/labels/built-ops against the recomputed outcome (`result.json` alone can
  never produce a verdict; a fabricated `NATIVE_CORRIDOR_VERIFIED` result would
  still need a matching route readback, receipt digests, manifest and frame
  evidence to pass the deep checks).
- **The v2 path never uses the legacy schedule:** for a v2 plan the selection is
  `corridor_schedule()`, and the record-vs-selection equality check (`plan["schedule"]
  != schedule or plan["plan_digest"] != plan_digest_of(schedule)`), the request
  identity set `_scheduled_request_ids(schedule)`, the per-op evidence loop and the
  budgets are all driven by the selected schedule — a v2 record replaying against
  the v1 derivation (or vice versa) cannot pass the equality gate.

## 5. Request accounting and cost enforcement — independently confirmed

- `PLANNED_CORRIDOR_REQUESTS = ROAD_OP_COUNT * 3 + 1 = 25` (8 ops × 3 exchanges +
  1 route read); `CORRIDOR_REQUEST_BUDGET = 25 + 6 = 31`; `budgets()` exposes
  `requests = 31` and `road_ops = len(corridor_schedule()) = 8`
  (`tests` assert all three; nothing hardcodes 6 outside the dedicated v1 function).
- `main.nut`: 8 baked `StageIndex` keys in exact execution order, loop bound 8,
  `max_requests = 31`; request #32 is dropped by the dispatcher without any reply,
  and the runner's `exchange()` treats a late reply as a timeout — nothing past the
  cap can ever be silently counted as successful work (the VM test drives 25 planned
  + 6 slack reads to exactly 31 and proves request 32 disappears without a reply).
- Duplicate/unknown request ids, invalid company/location rows and malformed
  frames fail closed through the request-id accounting and the contract validators
  (`READY` never accompanies a zero-cost quote — a native refusal at admission is
  terminal before any command).
- `MAX_CORRIDOR_COST = 2000` exactly, unchanged; `admit_corridor` enforces the
  per-operation ceiling (`0 < cost <= max_cost`, funds ≥ cost) and command-time
  re-quotes must equal the admitted quote; nothing in the code or contract collects
  an aggregate phase budget (`budgets()` has no cost key — the docstring's
  no-aggregate-budget rule is real). The £16,000 figure appears in the records only
  as a clearly-labeled worst-case exposure bound.

## 6. Regression coverage assessment

The 55 tests genuinely cover the review checklist without circular self-trust:

- **Exact schedule pins/order:** `test_corridor_schedule_is_the_compiled_eight_ops`
  and the wire suite's `test_setup_pins_stay_derived_not_retold` assert every pin of
  the table above against the module's own derivation (no hand-retold numbers).
- **Geometry:** `test_corridor_facts_bind_the_sealed_witness_and_runs` (24 tiles,
  run A/run B, corner, depot `45487`/`45743` south) and
  `test_run_b_segments_reassemble_the_compiled_run` (contiguous halves, shared
  edge, straight-axis proof, witness 24/23 intact).
- **Joins as build ops:** `test_road_pieces_never_auto_merge_in_the_stub` traps the
  corner op as `OUT_OF_ORDER` before its stage and proves the interior pair is
  still unlinked after both segments until its own op runs; plus the site-op and
  route tests chain the exact 8-op order.
- **Eight staged keys and request cap:**
  `test_gamescript_stage_keys_track_the_staged_schedule` statically equates the
  shipped `main.nut` StageIndex keys to the Python derivation;
  `test_planned_exchange_inventory_is_exactly_schedule_bound`,
  `test_wire_requests_map_the_planned_schedule_pins` (all 25 requests ≤ 512 B,
  worst `route-00` 304 B) and `test_dispatcher_budget_refuses_the_request_after_the_cap`.
- **Version binding:** `test_schedule_version_binding_selects_the_plan_derivation`
  (v2 fresh / v1 absent-key / unknown refused / digests differ) — and, live, the
  consumed-artifact replay test pins the v1 outcome (`pending op-02…op-05`).
- **Phase verification / incomplete prefix:** the halted-phase tests on both wire
  and staging sides, plus the retained-candidate replay regression.
- **Quote/funds/fail-closed:** zero-cost refusal terminal, quote-reject,
  insufficient funds, COST_LIMIT, COST_CHANGED, READBACK_MISMATCH, STALE_ADMISSION,
  ALREADY_ATTEMPTED, plan drift, unknown company.
- **Site-op `_pins()` branch:** `test_site_ops_feed_the_entry_scoped_pins_with_their_intent`
  covers both station and depot intents (closing E21's second prior concern).
- **Gitignored-evidence independence:** the always-on `_pins()` and schedule tests
  run without the consumed candidate; only the two replay regressions are gated on
  the retained directory (and were truly executed here, zero skipped).

**Neighboring-boundary decision (recorded, not skipped-for-default):** the only
inbound code boundary used by the changed module other than its own package is
unchanged source — `app.planning.p08_road.find_depot`, the unchanged wire contract
`app/simulation/openttd/corridor_construction.py` (per-op generic, not re-knowledge
of length), and the D2/D3 machinery (`terrain_clearing`, `terrain_terraform_native`,
`operator_authorization`). None of those files changed in this diff, so the p08
road/terrain and D3 staging suites are outside the affected boundary **as to code
they own** — but the one shared *runtime* boundary the D4 code calls into
(replay-verifying the retained D3 attempt in `prerequisite_binding`) was actually
executed read-only twice in this review-session's runs (staging fixture + the
prerequisite-binding tests in the native suite), and it passed with the retained
D3 bytes.

## 7. Findings (ranked)

1. **[Fixed during review — documentation]** `OpenTTD-Knowledge/01-Architecture/`
   `Component Map.md`: the E22 vault edit dropped the leading `|` of the "Corridor
   GameScript" table row, breaking the Markdown table; the adjacent
   "Corridor construction contract" note also attached "25 planned exchanges" to the
   wire-contract module although planned exchanges are a property of the staged
   schedule (the contract module itself is unchanged and per-op generic). Both fixed
   in this review session (§8).
2. **[Non-blocking observation — latent, fails safe]** `verify_corridor_attempt()`
   (staging module, `NATIVE_CORRIDOR_VERIFIED` branch, final request-inventory
   check) compares `len(outbound_requests) != PLANNED_CORRIDOR_REQUESTS`, where the
   module constant is the **v2-schedule planned count (25)**, not the selected
   schedule's planned count. A hypothetical *completed* v1 receipt (19 planned)
   would be **falsely refused** there — never falsely accepted, so the fail-closed
   direction is safe, and nothing can reach this branch today: the only consumed
   candidate halted at `op-01`, fresh staging always pins v2, and no v1 completion
   receipt exists. This is a follow-up hygiene item only (derive the planned count
   from the selected schedule), not a correctness defect of any executed path.
3. **[Non-blocking observation]** the signed authorization payload binds
   `max_cost`, the full `operation_schedule` and `plan_digest` (additively, through
   the shared scalar builder) but not the `schedule_version` number itself. No
   bypass exists — the version's only role is choosing the derivation, and the
   record's schedule and digest must equal that derivation at preflight and verify —
   but a future change to the payload builder may wish to include the version
   explicitly so the signed message names its own derivation. Enhancement, not a
   defect.
4. **[Observation]** the retained candidate keeps an empty `isolated/` directory
   husk beside its disposed workspace (files gone, `cleanup.json` says
   `workspace_disposed: true`; the husk is not part of the 28-file manifest and was
   not created or removed by this review). Harmless; left untouched.

No defect was found in the eight-operation schedule, the schedule-version
compatibility, the GameScript request handling, the verification/replay logic, the
request/cost accounting, or any consumed-artifact or D2/D3 boundary. The two prior
review concerns of E21 (artifact-gated skips; missing site-op `_pins()` coverage)
are genuinely addressed by the new tests.

## 8. Documentation updates made by this review

- `OpenTTD-Knowledge/01-Architecture/Component Map.md` — repaired the broken table
  row and tightened the planned-exchange wording (finding 1).
- This record: `docs/handoff/2026-10-22/d4-corridor-option-c-implementation-review.md`.
- `EVIDENCE_INDEX.md` + `OpenTTD-Knowledge/99-Source-Documents/EVIDENCE_INDEX.md`
  (byte-verified copy): E23 entry appended (2026-10-22 addendum, fifth entry + table
  row); no historical entry edited or relabeled.
- Vault notes updated for the review outcome (dated): `AI_START_HERE.md` (§3 D4 row,
  §4 next task), `00-Project/Current Status.md`, `00-Project/Roadmap.md`,
  `02-Milestones/Pending Milestones.md`, `03-Engineering/Testing Strategy.md`,
  `04-Evidence/Evidence Index.md`, `04-Evidence/Controlled Tests.md`,
  `05-Planning/Task Board.md`, `05-Planning/Next Actions.md`,
  `05-Planning/Blockers.md` §8, `06-Decisions/Decision Log.md` (ADR-011 review
  status line).
- `OpenTTD-Knowledge/99-Source-Documents/TASKS.md` byte-copy refresh follows the
  root `TASKS.md` continuation line.

## 9. Status distinctions kept explicit

- The implementation and its tests are **controlled/offline validated** (55 PASS,
  lint/compile/hygiene clean, replay compatible); controlled evidence never
  upgrades a project status.
- The old D4 native attempt **remains halted and incomplete**
  (`PHASE_HALTED_PREFIX_PRESERVED`, `verified: false`); its frozen closure is never
  edited or reused.
- **No native proof exists for the eight-operation schedule:** no native quote, no
  command, no receipt, no authorization — the historical £2,549/£785 quotes are
  controlled references of the consumed attempt only.
- Milestone D4 remains **INCOMPLETE (native)**.
- Fresh candidate preparation and native execution remain separate future steps
  requiring the project's existing authorization process (staging → prelaunch → ONE
  fresh explicit operator authorization → one-shot run). This record is not
  authorization; per its review outcome, the implementation **is suitable to
  proceed** to fresh-candidate preparation by that process.

## 10. Clarification (2026-10-22, later same day) — the `mise.toml` inventory note

This record's §1 noted that `mise.toml` carried a pre-existing +1-line
modification (`bun = "latest"`) outside the review's scope, and separately
observed that at end-of-review the file showed clean against HEAD. The
discrepancy is now explained by the operator:

- The operator confirms they personally removed `bun = "latest"` from
  `mise.toml` because they do not use Bun.
- The subsequent clean comparison of the working tree against HEAD is
  consistent with that change (the earlier "pre-existing modification" was an
  observation from an earlier point in time and is retained above as history —
  it is not rewritten).
- Nothing about the observation indicates unexplained repository activity.
- `bun = "latest"` is **not** restored; the file stays exactly as the operator
  left it (clean vs HEAD, verified again on 2026-10-22 during fresh-candidate
  preparation).
