# D5 corridor freight — T7 comprehensive current-byte review

## 1. Review identity and repository state

- Review date: 2026-10-27
- Timezone: +07 (UTC+07:00)
- Repository: `/home/fed/codes/softdev2`
- Branch: `devmodule2`
- Actual HEAD at review time: `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`
- Expected HEAD in the task brief: `70d4ce7edf3d2c09e1f5b6f95ea1c12bdba6a88f`
- Commit A: `f67f10748161e7b35c63b28c7a90f61cdfebb039`
- Commit B: `70d4ce7edf3d2c09e1f5b6f95ea1c12bdba6a88f`

The expected HEAD was not met. The two commits after Commit B are:

```text
1e6d6c1 update gitignore ignore perch
9bd1409 update ignore
```

Both touch only `.gitignore`. `git diff 70d4ce7..HEAD -- <the ten reviewed paths>` is empty, so the reviewed implementation and documentation bytes are identical to Commit A, and the reviewed file hashes below match the current working tree. This is recorded as a repository-state discrepancy, not as an implementation change.

Working tree state at review start and end:

```text
## devmodule2...origin/devmodule2
 M OpenTTD-Knowledge/.obsidian/workspace.json
```

That modification was pre-existing and is on the excluded list. No file under `artifacts/`, no `.agents/`, `.perch/`, `skills-lock.json`, `OpenTTD-Knowledge.zip`, `.env`, root `--version`, or other excluded path was touched. No staging, commit, amend, rebase, reset, clean, stash, push, candidate staging, OpenTTD launch, AdminPort connection, signing, claim, or Gate C authorization occurred.

## 2. SHA-256 of the ten reviewed Commit A paths

| Path | SHA-256 |
|---|---|
| `app/simulation/openttd/corridor_freight.py` | `22b01902a87a3780f9e4c00e7dc30cb12f31913d511df3f96e03759727e27880` |
| `app/simulation/openttd/corridor_route_optimizer.py` | `637b51191d1771f40438571938db93b2c84722009a194d22f44d5a25ee4d59e0` |
| `app/simulation/openttd/proof/corridor_freight_native.py` | `65a4c1c78dba8d4213642e7fcb72a7681e6e60d40de312697e628f9fbfb037b9` |
| `app/simulation/openttd/d5_freight_package/info.nut` | `f9c58f0e1bfa91d847ae56a0206bca170986d462aa7b616c9c69de459a9bde26` |
| `app/simulation/openttd/d5_freight_package/main.nut` | `0b3f7e82b67f213fbc4cca81a894453a871bb8b44c9820417b63755c4716d605` |
| `tests/test_corridor_freight.py` | `209ea7d230110c504eaeee4f18ced7b3066794cf9857d397862aba6886d229e9` |
| `tests/test_corridor_freight_native.py` | `680dcc0e892d4061370717955617ad71d75e5fcbb61897e493625cecfcd28571` |
| `tests/test_corridor_route_optimizer.py` | `b74c4a9578c9038ff891a805a3cbc91da6e05b7a0ac34f491393ce957ea1144d` |
| `docs/d5-corridor-freight-design.md` | `d9757ec66f89a101a895b5cf31e4483c56451bfe9cf6c9a30f2865d24b5038e1` |
| `docs/d5-corridor-freight-preparation.md` | `f0a4eaae0a6a040b64260e064ee1831facf805a573a6ec4988903c8bc2ea7729` |

## 3. Scope and method

This was a read-only, adversarial review of the committed D5 implementation, tests, design, and preparation record. The reviewer read the production wire contract, the GameScript package, the optimizer, the staging/preflight/replay module, the three D5 test files, the two D5 documents, the retained D4 prerequisite contract, and the current task/status text. Findings were re-checked against the exact bytes by line number.

A fresh-context review subagent performed a separate read-only pass over the same paths. Its findings were then re-verified by the primary reviewer. The subagent is an independent session, but it is not a human or third-party independent reviewer, and this record does not claim that stronger status. No native OpenTTD process, AdminPort, candidate, claim, signature, or receipt was created.

## 4. Actual test and static-check results

All test runs used `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.

| Check | Command scope | Actual result | Exit |
|---|---|---|---|
| D5 controlled VM | `tests/test_corridor_freight.py` | 32 passed in 16.28 s | 0 |
| D5 staging/preflight | `tests/test_corridor_freight_native.py` | 29 passed in 169.23 s | 0 |
| D5 optimizer | `tests/test_corridor_route_optimizer.py` | 13 passed in 15.80 s | 0 |
| D5 suite combined | the three files above | 74 passed | 0 |
| D4/transport regression | `tests/test_corridor_construction_native.py` | 33 passed in 75.30 s | 0 |
| D4/transport regression | `tests/test_gamescript_transport.py` | 38 passed in 0.63 s | 0 |
| Regression suite combined | the two regression files | 71 passed | 0 |
| Ruff lint | the six Python reviewed/implementation files | All checks passed | 0 |
| Ruff format check | same six files | 6 files already formatted | 0 |
| `git diff --check` | whole tree | clean | 0 |
| TASKS mirror | `cmp TASKS.md OpenTTD-Knowledge/99-Source-Documents/TASKS.md` | byte-identical | 0 |

No auto-fix, formatter write, or bytecode/cache write was used.

## 5. Findings

Severity is about consequence for a future controlled native attempt. A finding marked Critical or High is a blocker for T8 staging until it is fixed and retested.

### Critical

**C1 — A cleanup failure can leave `verified: true` and make the runner exit 0.**

- `app/simulation/openttd/proof/corridor_freight_native.py:1330-1331` sets `result["verified"] = True` and `status = "NATIVE_FREIGHT_VERIFIED"` after a complete phase.
- `app/simulation/openttd/proof/corridor_freight_native.py:1383-1386` handles a cleanup verification/disposal failure by setting only `result["status"] = "FAILED_CLEANUP"`. It does not clear `result["verified"]` or deny the receipt.
- `app/simulation/openttd/proof/corridor_freight_native.py:1671-1673` returns exit 0 whenever `result["verified"] is True`.

Consequence: a run whose cleanup was not certified can still write `result.json` with `verified: true` and exit 0. This is exactly the "failure path incorrectly claims success" case the review was asked to detect. The replay verifier would refuse the receipt because `cleanup_complete` is false, but the runner and any consumer of `result.json` can be misled. Fix: in the cleanup failure path clear `verified`, set a failed terminal state, and make `exit_status` require both `verified is True` and a verified native status and certified cleanup. Add a test for `verified: true` plus `FAILED_CLEANUP`.

### High

**H1 — The `verify` subcommand always exits 0, including for unverified attempts.**

`app/simulation/openttd/proof/corridor_freight_native.py:1690-1692` prints the verdict and falls through without a `SystemExit`. `AUTHORIZATION_UNVERIFIED`, `ATTEMPT_FAILED_EVIDENCE_PRESERVED`, and every other non-`RECEIPT_VERIFIED` verdict therefore exit 0. This contradicts design §7 item 8 and A10 ("read-only replay verifier exit 0 with `RECEIPT_VERIFIED`"). The existing test at `tests/test_corridor_freight_native.py:852-860` tests only the `exit_status` helper, not the CLI. Fix: make `verify` exit 0 only for `RECEIPT_VERIFIED` and 1 otherwise.

**H2 — The fixed 10-second exchange timeout is shorter than the documented watch-window budget.**

`app/simulation/openttd/proof/corridor_freight_native.py:1083` wraps every exchange in `asyncio.timeout(10)`. The staged budget also says `request_seconds=10` (`:615`), while the design allows `load-watch` and the other windows up to 60 seconds wall (`docs/d5-corridor-freight-design.md:373-376`). A legitimate slow load or transit window can exceed 10 seconds and will be killed by the client before the GameScript returns its bounded observation. That is fail-closed, but it makes a legitimate native attempt likely to halt and does not honor the documented cap. Fix: derive the per-exchange timeout from the op/window budget plus margin, or give window exchanges their own named timeout.

**H3 — Replay does not re-bind the attempt to the pinned D4 prerequisite, source save, or full world identity.**

`app/simulation/openttd/proof/corridor_freight_native.py:1443-1495` reads the prelaunch record, checks the manifest, schema, authorization evidence, schedule, plan, result, and runtime identity. It does not call `prerequisite_binding()`, does not compare the staged world's `save_sha256` to `PINNED_PREREQUISITE_AFTER_SAVE`, does not call `verify_staged_source_save` for `session-before.sav`, and checks only `runtime["welcome"]["revision"] == "15.3"` (`:1494-1495`) rather than the full expected welcome. Consequently a correctly re-sealed and re-authorized attempt staged from a different world with the same route geometry could replay to `RECEIPT_VERIFIED`. The authorization record binds the world the candidate itself declares, which is not the same as independently proving the pinned prerequisite. Fix: call `prerequisite_binding` and `verify_staged_source_save` in replay, compare the full welcome, and check the pinned after-save digest.

### Medium

**M1 — Preflight does not compare the staged world's save digest to the independently derived prerequisite binding.**

`app/simulation/openttd/proof/corridor_freight_native.py:986-1002` compares the staged `metadata["prerequisite"]` block to `binding`, then verifies `source.sav` against `metadata["world"]["save_sha256"]`. It never asserts `metadata["world"]["save_sha256"] == binding["save_sha256"]`. A re-sealed record with a different world save and a matching `source.sav` can pass preflight while retaining the correct prerequisite metadata. Fix: add that equality check and a negative test.

**M2 — A site refusal for a nonzero fleet produces a readback shape the Python contract rejects.**

`app/simulation/openttd/d5_freight_package/main.nut:487-499` attaches `paused`, `truck0`/`sid0`, `truck1`/`sid1`, `depot_ok`, `owner`, `pairs_ok`, `pair_total`, `accept`, `prod`, `wait`, and `vehicles`, and then sets `INVALID_SITE` when `obs.fleet != 0`. `app/simulation/openttd/corridor_freight.py:594-602` allows a refusal readback to carry no observation fields; this one carries many. The response therefore fails `FreightReadback` validation and becomes an unstructured protocol error instead of the typed `INVALID_SITE` evidence the design requires. The controlled VM suite does not exercise the nonzero-fleet site path. Fix: return the fleet refusal before attaching observation fields, or give the contract an explicit refusal observation shape.

**M3 — `finish` toggles `StartStopVehicle` without checking the current state.**

`app/simulation/openttd/d5_freight_package/main.nut:1109-1129` calls `GSVehicle.StartStopVehicle` unconditionally and reports `PHASE_STOPPED` if the call returns true. The command is a toggle: an already-stopped vehicle would be started while the receipt says the phase stopped it. `app/simulation/openttd/corridor_freight.py:1286-1298` verifies only `stop_issued is True`; it does not require `state == "STOPPED"` or `speed == 0`. Fix: read state before the command, stop only when not already stopped, and require the final readback to prove stopped.

**M4 — Failure evidence can label a post-mutation refusal as `HALTED_BEFORE_MUTATION`.**

`app/simulation/openttd/corridor_freight.py:1561-1574` classifies every non-inconclusive, non-success status as `HALTED_BEFORE_MUTATION`. But `PurchaseOp` can build a vehicle and then return `COST_CHANGED` (`main.nut:602-615`), `OrderOp` can append an order and then return `READBACK_MISMATCH` (`main.nut:681-693`), and `StartOp` can start a vehicle and then return `READBACK_MISMATCH` (`main.nut:791-800`). Those are mutation-bearing failures. The design explicitly says a failed command is never reported as leaving the world unchanged. Fix: map statuses and op positions to a mutation-aware world-state label, including `UNCERTAIN_AFTER_FAILED_COMMAND` where a command may have been applied.

**M5 — The load receipt records a waiting delta but never enforces it.**

`app/simulation/openttd/corridor_freight.py:1168-1182` computes `waiting_delta = (loaded.wait or 0) - waiting_baseline` and records it. It never requires a decrement or any consistency relation. A7 asks for "waiting decrement consistent"; the current receipt can show an unchanged or increased waiting level and still verify. Fix: require the recorded delta to corroborate the load, or explicitly document why station waiting can legitimately not decrease.

**M6 — Transit verification samples positions; it does not prove tile-by-tile continuity.**

`app/simulation/openttd/d5_freight_package/main.nut:901-984` samples `GSVehicle.GetLocation` once per script tick and rejects any sampled off-witness tile. Arrival requires the delivery tile, a full load, and `progress == witness_len - 1`. The vehicle could leave the witness between samples and return without being observed, and the receipt does not claim a continuous path. The design's D5-M4 wording ("transit tile after tile") is therefore stronger than the evidence. Fix: either record the observed witness index sequence and require monotonic coverage of all indices, or narrow the design claim to sampled observation.

**M7 — The replay success path has not been exercised against consumed frames.**

`tests/test_corridor_freight_native.py:837-849` exercises `verify_freight_attempt` only for the unconsumed `CLAIM_ABSENT` verdict. There is no test with a consumed claim, complete fifteen-exchange frames, a receipt, and a certified cleanup that returns `RECEIPT_VERIFIED`; likewise no negative test for the C1 cleanup path. `tests/test_corridor_freight.py` exercises the cycle verifier in the stub VM, not the staged replay entry point. `verify_freight_attempt` is therefore **UNKNOWN** against real consumed native-attempt frames. Fix: add a synthetic consumed-frame replay success test (all fifteen exchanges, receipt, cleanup) and failure tests for tampered frames, missing responses, and failed cleanup.

**M8 — The staged D5 plan is an optimizer round-trip over one witness, not a choice among competing executable routes.**

`app/simulation/openttd/proof/corridor_freight_native.py:311-349` calls `route_from_d5_map` with `witness_candidates=(tuple(facts["witness"]),)` — exactly one candidate — and then refuses staging unless the selected route equals that witness. The production `optimize_candidate_network` is called (`corridor_route_optimizer.py:689`), and the route/digest binding is real, but the staged native plan does not select among competing executable geometries. The GameScript latches the route from `site`; it does not construct road. The offline tests over sealed census tiles prove the optimizer can choose among feasible tile sets, not that a second executable route exists. This is a limitation, not a hidden false claim, but it blocks any "optimizer-selected native construction" claim. See §8.

**M9 — Company identity is pinned in Python but only range-checked in the GameScript.**

`app/simulation/openttd/d5_freight_package/main.nut:1146-1147` accepts any company id 0..14 and `:1193` accepts any resolvable company; it never compares `q.company` to `FREIGHT_COMPANY` (0). The Python plan and `verify_request_against_plan` pin company 0, so this is defense-in-depth rather than a direct wire exploit. It still means the native handler would admit another valid company if it owned the same stops/depot and funds. Fix: refuse any company other than `FREIGHT_COMPANY` before admission.

### Low

**L1 — Schema-1 `FreightPlan` witnesses are not geometrically validated.**

`app/simulation/openttd/corridor_freight.py:724-735` validates schema 1 only for the pinned stop/depot constants, a 24-tile length, and distinct endpoints. It does not validate adjacency, uniqueness, or depot relationship for the schema-1 witness. Production D5 plans use schema 2 (`corridor_freight_native.py:511`), so this is latent. Fix: validate schema-1 witnesses with the same route helper or mark schema 1 as historical-only.

**L2 — The package `info.nut` is not the staged GameScript identity.**

`app/simulation/openttd/d5_freight_package/info.nut:7` declares `CreateInstance()` returning `"D5FreightProof"`, while staging replaces `info.nut` with the retained frozen-source identity (`corridor_freight_native.py:214-232`), whose `CreateInstance()` is `NetworkFreightProof`. `main.nut:1348-1352` provides the bridge. The package `info.nut` is frozen but unused during staging, so it can mislead a reader. Fix: document it as a test/local identity only, or stop treating it as the staged identity.

**L3 — The 1450-byte send ceiling is named but not directly enforced.**

`app/simulation/openttd/corridor_freight.py:79` defines `MAX_FREIGHT_SEND_BYTES = 1450`, and staging reports it (`corridor_freight_native.py:610`), but encoding is bounded at 640 and no code compares the final frame to 1450. The stricter 640 bound makes this harmless today, but it is not an enforced contract. Fix: enforce the named send bound at the one outbound helper, or document it as an inherited engine ceiling.

**L4 — The artifact manifest is verified but not required to be exhaustive.**

`app/simulation/openttd/proof/corridor_freight_native.py:1459-1464` verifies every line that the manifest contains, but does not require the manifest to list every file in the directory. `app/simulation/openttd/proof/harness.py:76-81` generates a list of all regular files except the manifest itself at write time. A file omitted from a rewritten manifest is not hash-checked by replay. Fix: compare the manifest's name set to the directory's regular-file set (excluding the manifest).

**L5 — Live `exchange()` returns on the first GameScript frame without draining duplicates.**

`app/simulation/openttd/proof/corridor_freight_native.py:1077-1093` reads until the first `SERVER_GAMESCRIPT` frame and returns. A duplicate or delayed response can remain in the stream and be consumed by the next exchange; correlation would then fail closed, but the duplicate is not rejected at the point it occurs. Replay does check response uniqueness (`:1544-1549`). Fix: drain to a bounded barrier or reject a second GameScript frame before returning.

**L6 — The `INVALID_COMPANY` path is untested.**

The controlled world exposes `::valid_company` and `::second_company` (`tests/test_corridor_freight.py:77-78`, `:158`, `:166`), but no test exercises `main.nut:1193` or a company other than 0. Fix: add a refused-company test, especially after M9 is addressed.

**L7 — Refusal responses from the GameScript are not byte-bounded before send.**

`main.nut:1266-1333` bounds individual numeric/boolean fields but does not measure the serialized response length; the 640-byte response ceiling is enforced only by the Python decoder (`corridor_freight_native.py:1091`, `:1424`) and the VM test helper (`tests/test_corridor_freight.py:407-409`). An oversized refusal would fail closed as a decode error, but the native sender does not enforce the named bound. Fix: measure the encoded string before `GSAdmin.Send`, or document the Python-side enforcement explicitly.

**L8 — Malformed orphan response files are skipped during replay.**

`app/simulation/openttd/proof/corridor_freight_native.py:1533-1538` catches `ValueError` while parsing every `*-response.json` and continues. An extra malformed response file with no matching request is therefore ignored rather than rejected. The manifest would cover it if present, but replay does not fail on it. Fix: fail on any unpaired or unparsable response file.

### Informational

- **I1 — HEAD discrepancy.** Actual HEAD is `1e6d6c1`, not the brief's `70d4ce7`; the two extra commits only touch `.gitignore`, and the reviewed paths are byte-identical to Commit A. No reviewed implementation byte changed.
- **I2 — Status text is pre-commit.** `TASKS.md:478-494` still describes T5/T6 as uncommitted and the optimizer route as future work, while the committed tree contains those files. This does not affect the reviewed code, but the status narrative lags the commit.
- **I3 — Native behavior is entirely unproven.** No OpenTTD 15.3 process, AdminPort session, save load, depot/stop readback, engine quote, purchase, order, load, transit, delivery, monitor, finance, finish, cleanup, or replay against consumed native frames occurred. Every native fact below remains **UNKNOWN**.
- **I4 — The D5 package is additive and does not modify the D4 machinery.** The dependency imports and staging path are consistent with the stated reuse; no D4 file was changed by this review.

## 6. Verified, partially verified, and unknown behavior

### Verified (offline, against current bytes)

- The fifteen-exchange schedule is consistent across `FREIGHT_EXCHANGE_IDS`, the staged schedule, the package's `planned` table, and the tests.
- The 640-byte request bound is applied on the live encode/decode path and the replay parse/re-encode path; the generic transport default remains 512; 640 is accepted and 641 refused on the shared helper.
- Request/response correlation and per-op field subsets are enforced; malformed bodies, duplicate IDs, out-of-order stages, plan-digest drift, and route-digest drift fail closed in the controlled tests.
- The staged candidate seals a PRELAUNCH record, binds the pinned D4 prerequisite, freezes the source closure, refuses an existing claim, and verifies an unconsumed candidate as `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT`.
- Preflight re-checks the seal, freeze, closure, dependencies, schedule, world pins, optimizer pins, budgets, source save, and staged composition; the tested tamper cases are refused.
- The optimizer calls the production `optimize_candidate_network`, enumerates bounded simple paths deterministically, applies the CAPEX objective, and binds the selected route digest into the plan/wire contract.
- The controlled Squirrel VM executes the shipped package across the full cycle and the optimizer-alternate-route tests.

### Partially verified

- **GameScript execution correctness** is verified against a controlled stub world only. The control flow, status names, digest latching, stage accounting, and refusal paths are exercised, but the stub is not OpenTTD 15.3.
- **Failure semantics** are mostly fail-closed, but M2 (site refusal shape), M3 (finish toggle), M4 (mutation label), and C1 (cleanup success leak) show that not every failure path preserves the intended evidence or exit contract.
- **Replay semantics** are structurally consistent with live parsing (`parse_for`, shared encode/decode helpers), but the success path has not been run on consumed frames (M7), and the pinned prerequisite/world binding is incomplete in replay (H3).
- **Optimizer-to-route** is real as an offline production step, but the staged native plan is a single-witness round-trip (M8); it is not proof of an executable competing-route choice.

### Unknown

- All native site facts on the real candidate-5 world, including station type/front linkage, depot ownership, 24-tile road connectivity, acceptance, production, waiting, funds, fleet count, and pause state.
- Native engine enumeration, test quote, real purchase price, realized cost, funds delta, and vehicle identity.
- Native order append/readback semantics, monitor arming/consumption semantics, and 15.3 API behavior.
- Native loading, transit, unloading, monitor equality, finance corroboration, and finish behavior.
- Native cleanup, endpoint certification, process reaping, credential removal, and workspace disposal.
- A full `verify_freight_attempt` replay to `RECEIPT_VERIFIED` against real consumed native-attempt frames.
- Whether the staged AI/bootstrap or the loaded save changes funds or world state before the `session-before` save.

## 7. Protocol and evidence-integrity conclusions

**Protocol.** The 15-exchange schedule and the 640-byte protocol-5 boundary are consistently implemented and tested. The shared live/replay request helpers are the right shape, the generic 512-byte default is preserved, and the 640/641 boundary is exact on the tested helper. Correlation, per-op subsets, duplicate-ID dropping, stage enforcement, and digest latching are materially fail-closed. The 1450-byte ceiling is not directly enforced (L3), and live duplicate-response draining is weaker than replay (L5), but the 640-byte application bound is the effective ceiling today.

**Evidence integrity.** Staging, sealing, freezing, claim consumption, and unconsumed fail-closed behavior are well structured. The critical weakness is C1: a cleanup failure after a complete phase can still leave `verified: true` and exit 0. The second weakness is H1: the `verify` CLI cannot signal a non-verified verdict through its exit code. The third is H3: replay does not independently re-bind the attempt to the pinned D4 prerequisite, source save, and full world identity, so a receipt can verify without the world-level binding the design promises. M1, L4, and L8 are narrower tamper-surface gaps. No failure path was found that can make the strict replay path return `RECEIPT_VERIFIED` without a complete fifteen-exchange cycle and cleanup, but C1/H1 are enough to prevent a clean success claim at the runner/CLI boundary.

**Native proof.** None. Passing offline tests are not native proof. The review does not claim native freight delivery, optimizer-selected native construction, or Gate C authorization.

## 8. Optimizer-to-route limitations

The production optimizer is genuinely called, and the selected route is bound into the plan and wire digest. The offline tests demonstrate deterministic selection among source-backed feasible geometries and a CAPEX flip. That is useful and is not a renamed hardcoded route in the offline path.

However, the staged D5 candidate passes exactly one witness candidate (the D4 corridor) and refuses any deviation. It therefore does not choose among competing executable routes in the live world. The GameScript receives and latches the route but issues no road-construction command; D5 remains a freight cycle on the existing D4-built corridor. There is no authoritative post-D4 built-road connectivity survey in the repository, so a second executable route cannot be established from retained evidence. The current POC cannot demonstrate a live choice among competing routes. Any "optimizer-selected native construction" claim remains **PARTIAL/UNKNOWN** and out of scope for T7.

## 9. Suitability and verdict

**Verdict: BLOCKED.**

The core design is disciplined: bounded protocol, fixed schedule, digest latching, staging/seal/freeze/claim gates, fail-closed parsing, and a comprehensive controlled test suite. The prior 74/71 test counts revalidated cleanly. But the review found one Critical evidence-integrity defect (C1: cleanup failure can still report `verified: true` and exit 0), two High CLI/timeout defects (H1, H2), one High replay-binding defect (H3), and the replay success path has never been exercised against consumed native frames (M7). Those must be fixed and retested before a candidate is staged.

This is **not** a blanket PASS, and it is not authorization for T8 or Gate C. The fixed-corridor freight implementation is close to a defensible offline harness, but it is not yet suitable to proceed to a controlled native attempt on the current bytes.

## 10. Remaining blockers and recommended next milestone

Blockers before any T8 staging request:

1. Fix C1: clear `verified`, deny the receipt, and set a failed terminal status on any cleanup failure; require certified cleanup in `exit_status`.
2. Fix H1: make the `verify` CLI exit nonzero for every non-`RECEIPT_VERIFIED` verdict.
3. Fix H2: align the per-exchange timeout with the documented watch-window wall budget.
4. Fix H3: bind replay to the pinned D4 prerequisite, pinned source save, and full welcome identity.
5. Fix M1-M5 (preflight world-save equality, nonzero-fleet refusal shape, finish toggle, mutation-aware failure labels, waiting-delta enforcement) and M9 (company pin).
6. Add M7 tests: a synthetic consumed-frame `RECEIPT_VERIFIED` replay, plus failure tests for cleanup, tampering, missing responses, and the CLI exit contract.
7. Re-run the D5 and D4/transport suites, Ruff check/format check, and `git diff --check`; re-review the changed bytes.

Recommended next milestone: **T7 remediation and re-review**, followed by a separate T8 staging request under a new explicit authorization. Gate C operator authorization remains a separate decision and has not been granted.

## 11. Preservation statement

This review created only `docs/d5-corridor-freight-t7-review.md`. No source, test, status, design, preparation, artifact, or excluded file was modified. No candidate, claim, signature, or native evidence was created. The working tree before and after this review contains only the pre-existing `OpenTTD-Knowledge/.obsidian/workspace.json` modification; HEAD remains `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`.

---

## 12. Remediation and re-review addendum — 2026-10-27

### 12.1 Repository state and scope

- Repository: `/home/fed/codes/softdev2`
- Branch: `devmodule2`
- HEAD and `origin/devmodule2`: `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f` (both matched before and after this task)
- Working tree at start and end: the pre-existing `OpenTTD-Knowledge/.obsidian/workspace.json` modification, the untracked earlier review record, and the two files changed by this remediation.
- No staging, commit, push, reset, clean, stash, history rewrite, OpenTTD launch, AdminPort connection, candidate staging, claim creation, signing, sealing, or Gate C authorization occurred.
- Nothing under `artifacts/` and no excluded path (`.obsidian/workspace.json`, `.gitignore`, root `--version`, `.agents/`, `.perch/`, `skills-lock.json`, `OpenTTD-Knowledge.zip`, `.env`) was modified by this task.

This addendum preserves sections 1–11 unchanged and records only the remediation and its re-review.

### 12.2 Remediation changes

All changes are in `app/simulation/openttd/proof/corridor_freight_native.py` and `tests/test_corridor_freight_native.py`.

**C1 — cleanup failure now fails closed.**

- `apply_cleanup_outcome()` (`corridor_freight_native.py:1277`) is the single final cleanup transition. An uncertified cleanup sets `cleanup_complete: false` and `cleanup_failure: true`; if the attempt had been verified it clears `verified`, sets `FAILED_CLEANUP`, records the successful status under `prior_status`, and records the denial message.
- `deny_verification()` (`:1259`) preserves an existing `error` and appends the denial to `denial_errors` instead of masking the original exception.
- Live cleanup computes `cleanup_complete` from `reaped`, absence of `cleanup_error`, `workspace_disposed`, and `credential_removed` before `result.json` is written (`:1505-1525`).
- Script-log health findings and an abnormal runtime return code now go through the same deny path.
- `exit_status()` (`:1948`) returns zero only when `verified is True`, `status == "NATIVE_FREIGHT_VERIFIED"`, and `cleanup_complete is True`.
- Replay treats a genuine `FAILED_CLEANUP` record as failed evidence (`:1889`), never as a receipt, and its cleanup completeness check now also requires no `cleanup_error` and no `verification_error` (`:1844`).

**H1 — the verify CLI exit code now matches the verdict.**

- `verdict_exit_status()` (`:1962`) returns zero only for `RECEIPT_VERIFIED`.
- `main()` (`:1967`) raises `SystemExit(verdict_exit_status(verdict))` for the `verify` command. `AUTHORIZATION_UNVERIFIED` and every other non-success verdict exit 1; malformed CLI input still exits 2; exceptions propagate.

**H2 — exchange timing now follows the staged budgets.**

- The fixed `asyncio.timeout(10)` is gone.
- `exchange_timeout_seconds()` (`:1102`) derives a watch exchange's budget from `watch_seconds` (60) plus a 5-second client margin, and a non-watch exchange's budget from `request_seconds` (10). `budgets()` now reports `watch_seconds: 60`.
- `exchange()` (`:1121`) clamps that budget to the remaining overall attempt deadline, refuses before sending once the overall window is exhausted, and fails closed on timeout, cancellation, disconnection, partial reads, duplicate response frames, and stale/correlation-mismatched late responses.
- The overall attempt remains bounded by `total_seconds` in `execute_freight_attempt`.

**H3 — replay now re-binds the attempt to its prerequisites.**

- `verify_attempt_identity()` (`:1567`) re-runs the pinned D4 prerequisite binding (including its full receipt replay and pinned after-save digest), compares the staged prerequisite block, pins the staged world's retained directory/source/save digest to the prerequisite binding and `PINNED_PREREQUISITE_AFTER_SAVE`, re-verifies the retained after-save bytes, checks the full expected welcome, and re-derives the schedule digest, budget contract, world pins, plan-model digest, route digest, and optimizer candidate/scenario/execution digests.
- Replay compares every `WELCOME_ORDER` field of the retained runtime identity, not only `revision` (`:1755`).
- Receipt replay continues to compare the recomputed phase/cycle and before/after save digests.
- Preflight additionally requires the staged world's save digest to equal the independently derived prerequisite binding, resolving M1 (`:1009-1021`).

**Successful consumed-frame replay (M7).**

- A synthetic-but-complete attempt fixture now drives the real `verify_freight_attempt` entry point through all fifteen scheduled exchanges, thirty correlated frames, full prerequisite/identity/welcome/budget evidence, a receipt, and certified cleanup.
- The success path exposed and fixed a latent pre-existing defect: `dict(phase, cycle, ...)` could never execute (`TypeError`); it is now `dict(phase, cycle=cycle, ...)`. This is the first execution of that branch.

### 12.3 New regression tests

`tests/test_corridor_freight_native.py`:

- C1: `test_cleanup_failure_after_success_denies_the_verified_result` (`:912`), `test_cleanup_failure_after_an_unsuccessful_attempt_preserves_its_status` (`:928`), `test_deny_verification_preserves_the_original_error`, and the extended `test_exit_status_zero_only_for_the_verified_receipt`.
- H1: `test_verify_cli_exits_nonzero_for_unverified_verdicts` (`:1645`), `test_verify_cli_exits_zero_only_for_a_verified_receipt` (`:1654`), `test_verify_cli_cannot_turn_errors_or_malformed_input_into_success` (`:1665`).
- H2: `test_exchange_timeout_is_derived_from_the_phase_budget` (`:998`), `test_watch_exchange_inside_its_budget_is_not_killed_at_ten_seconds` (`:1026`), `test_exchange_exceeding_its_permitted_budget_fails_closed` (`:1064`), `test_exchange_is_clamped_to_the_remaining_overall_budget` (`:1081`), `test_exhausted_overall_watch_window_refuses_before_sending`, cancellation, stale-response, duplicate-frame, and partial-read tests (`:1126-1191`).
- H3/M1: `test_preflight_rejects_a_staged_world_that_is_not_the_pinned_after_save` (`:401`), `test_replay_fails_closed_on_wrong_source_save_digest` (`:1589`), `test_replay_fails_closed_on_wrong_pinned_d4_digest` (`:1602`), `test_replay_fails_closed_on_incomplete_world_welcome` (`:1610`), `test_replay_fails_closed_on_candidate_receipt_identity_mismatch` (`:1622`), `test_replay_fails_closed_on_optimizer_plan_digest_drift` (`:1702`).
- Replay: `test_replay_verifies_a_fully_consumed_valid_frame_sequence` (`:1537`), `test_replay_refuses_missing_duplicated_out_of_order_and_altered_frames` (`:1551`), `test_replay_preserves_a_failed_cleanup_as_failed_evidence` (`:1677`).

The replay fixtures are explicitly labelled synthetic. They copy a freshly staged candidate whose prerequisite is the real pinned D4 attempt and fabricate the missing post-launch artifacts. Only the operator-authorization seam (`replay_authorization_state`) is monkeypatched, because no authorized D5 attempt exists in the repository and signing one is outside this task. Every other prerequisite, identity, digest, phase, frame, cleanup, and receipt fact is checked by the production replay path.

### 12.4 Actual test and static-check results

All test runs used `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.

| Check | Actual result | Exit |
|---|---|---|
| D5 combined: `tests/test_corridor_freight.py`, `tests/test_corridor_freight_native.py`, `tests/test_corridor_route_optimizer.py` | 98 passed in 187.74 s | 0 |
| D4/transport regression: `tests/test_corridor_construction_native.py`, `tests/test_gamescript_transport.py` | 71 passed in 76.20 s | 0 |
| Ruff lint (two modified files) | All checks passed | 0 |
| Ruff format check (two modified files) | 2 files already formatted | 0 |
| `git diff --check` | clean | 0 |

The historical 74/71 counts are superseded by 98/71. The increase is entirely new tests; no existing D5 test was removed or skipped. No auto-fix or formatter write was used.

### 12.5 Finding status after remediation

| Finding | Status | Basis |
|---|---|---|
| C1 cleanup success leak | **Resolved** | Final cleanup transition denies `verified`, `FAILED_CLEANUP` cannot coexist with success, `exit_status` needs all three conditions; tests cover success-then-cleanup-failure, already-failed cleanup, repeated transition, and CLI exit. |
| H1 verify CLI always exits 0 | **Resolved** | `verify` exits 0 only for `RECEIPT_VERIFIED`; CLI tests cover success, `AUTHORIZATION_UNVERIFIED`, exceptions, and malformed input. |
| H2 fixed 10 s exchange timeout | **Resolved** | Watch exchanges get 60 s + 5 s margin, non-watch stay at 10 s, every exchange is clamped to the remaining 900 s attempt budget; deterministic tests cover inside-budget, over-budget, exhaustion, cancellation, stale, duplicate, and partial reads. |
| H3 incomplete replay binding | **Resolved** | Replay re-runs the pinned D4 prerequisite replay, pins source-save and after-save digests, full welcome, plan/route/optimizer/scenario/execution digests, and receipt identity; negative tests cover each mismatch. |
| M1 preflight world-save equality | **Resolved** | Preflight now equates the staged world binding with the independently derived prerequisite binding; negative test added. |
| M7 replay success path untested | **Resolved** | Real `verify_freight_attempt` returns `RECEIPT_VERIFIED` over a complete consumed fifteen-exchange fixture, with missing/duplicate/out-of-order/altered negative variants. |
| M2 nonzero-fleet refusal shape | **Unresolved** | No GameScript or contract change was made. |
| M3 finish toggle without state check | **Unresolved** | No GameScript or verifier change was made. |
| M4 post-mutation refusal labelled `HALTED_BEFORE_MUTATION` | **Unresolved** | No mutation-aware label change was made. |
| M5 waiting delta not enforced | **Unresolved** | It is still recorded but not enforced. |
| M6 transit sampled, not tile-continuous | **Unresolved** | Sampling semantics are unchanged. |
| M8 single-witness optimizer round-trip | **Unresolved limitation** | Staging still passes exactly the one D4 witness candidate. |
| M9 company range-check only in GameScript | **Unresolved** | No company pin was added natively. |
| L1 schema-1 witness geometry | **Unresolved** | Latent; production uses schema 2. |
| L2 package `info.nut` identity | **Unresolved** | Documentation-only issue, not touched. |
| L3 1450-byte send ceiling not enforced | **Unresolved** | The effective 640-byte application bound remains. |
| L4 manifest not required exhaustive | **Unresolved** | Unchanged. |
| L5 no live duplicate draining | **Partially addressed** | Multiple GameScript frames in one receive are now refused; a duplicate arriving in a later frame is still rejected only by the next correlation check. |
| L6 `INVALID_COMPANY` untested | **Unresolved** | Unchanged. |
| L7 native refusal byte bound | **Unresolved** | Unchanged. |
| L8 malformed orphan response files skipped | **Unresolved** | Unchanged. |
| I1 HEAD discrepancy | **Resolved as a state discrepancy** | HEAD and origin both match `1e6d6c1`; no reviewed byte changed. |
| I2 status text lags commits | **Unresolved** | `TASKS.md` was not modified by this task. |
| I3 native behavior unproven | **Remains true** | No native process or AdminPort session occurred. |
| I4 D5 additive over D4 | **Remains true** | No D4 file was modified. |

Two Low findings raised by the independent-session reviewer during this re-review were also resolved and retested: the `FAILED_CLEANUP` replay arm now returns failed evidence instead of an unreachable/misleading "halted attempt cleanup incomplete" error, and replay cleanup completeness now also rejects `cleanup_error`/`verification_error`.

### 12.6 Review method and independence

This addendum is based on a self-review of every changed path plus a fresh-context review subagent over the diff. The subagent independently confirmed C1, H1, H2, H3, and the Phase-6 replay requirement resolved and raised the two Low findings noted above; both were then fixed and checked in a follow-up pass of the same session. The subagent is an independent session but is not a human or third-party reviewer, and this record does not claim that stronger status. I ran the final full suites myself after those fixes.

### 12.7 Native-runtime limitations

No OpenTTD 15.3 process, AdminPort connection, save load, site/engine admission, purchase, order, load, transit, delivery, finance, finish, cleanup, or candidate claim occurred. The successful replay fixture is offline and synthetic; it proves the replay verifier's bindings and terminal logic, not native freight delivery. All native facts from §6 remain **UNKNOWN**.

The fixed-corridor implementation still cannot demonstrate optimizer-selected native construction or a live choice among competing executable routes (M8). Gate C authorization does not exist and was not performed.

### 12.8 Suitability and recommended next milestone

The Critical and High blockers from §5 (C1, H1, H2, H3), M1, and the consumed-frame replay gap (M7) are resolved and covered by regression tests. The implementation is materially closer to a defensible offline harness.

It is **not yet suitable to proceed to T8 staging without further work or explicit operator risk acceptance**, because the material Medium findings M2–M6 and M9 remain unresolved. Several of those affect failure evidence and native refusal semantics that a controlled attempt would rely on. This is not a claim of native freight delivery, optimizer-to-route completion, or Gate C authorization.

Recommended next milestone: a second offline remediation of M2–M6 and M9 (site refusal shape, finish state proof, mutation-aware failure labels, waiting-delta corroboration, transit continuity claim or evidence, and native company pin), then a fresh re-review. T8 staging and Gate C operator authorization remain separate explicit gates.

### 12.9 Preservation statement

This remediation changed only `app/simulation/openttd/proof/corridor_freight_native.py`, `tests/test_corridor_freight_native.py`, and this addendum in `docs/d5-corridor-freight-t7-review.md`. The original review text is preserved. No excluded path, artifact, secret, Git ref, native runtime, candidate, claim, signature, or authorization was touched. HEAD remains `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`, equal to `origin/devmodule2`.

---

## 13. Second offline remediation addendum (M2–M6, M9) — 2026-10-27

This addendum records the second offline remediation and its re-review. Sections 1–12 are preserved unchanged. It supersedes only the unresolved statuses of M2–M6 and M9 in §12.5.

### 13.1 Repository state and scope

- Repository: `/home/fed/codes/softdev2`
- Branch: `devmodule2`
- HEAD and `origin/devmodule2` at start and end: `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`
- Changes were confined to `app/simulation/openttd/d5_freight_package/main.nut`, `app/simulation/openttd/corridor_freight.py`, `tests/test_corridor_freight.py`, and this addendum. The files and pre-existing modification from the first remediation were preserved unmodified.
- No staging, commit, push, reset, clean, stash, history rewrite, OpenTTD launch, AdminPort connection, candidate staging, claim, signing, sealing, or Gate C authorization occurred. Nothing under `artifacts/` and no excluded path was modified. The pre-existing `.obsidian/workspace.json` modification is untouched.

### 13.2 Exact fixes

**M2 — nonzero-fleet site refusal keeps the typed refusal shape.**

`main.nut` `SiteOp` now issues the zero-fleet gate in the admission `else if` chain (`obs.fleet != 0` → `INVALID_SITE`) *before* any observation field (`paused`, `truck0`,`sid0`, `truck1`, `sid1`, `depot_ok`, `owner`, `pairs_ok`, `pair_total`, `accept`, `prod`, `wait`, `vehicles`) attaches; the post-attach fleet check is deleted. A nonzero-fleet readback therefore parses as a valid `INVALID_SITE` refusal instead of dying as "refusal readback carries an unclaimed observation set".

**M3 — `finish` is state-aware and proves the stop.**

`main.nut` `FinishOp` reads the state first; it issues `GSVehicle.StartStopVehicle` only when the state is neither `STOPPED` nor `IN_DEPOT` (it is a toggle), records `stop_issued` truthfully (`true` only for an issued toggle), and refuses with `READBACK_MISMATCH` unless the final readback proves `speed == 0` and a stopped state (`STOPPED`/`IN_DEPOT`). `corridor_freight.py` `verify_freight_finish` now requires `stop_issued is True` **and** the state proof (`state` in `("STOPPED","IN_DEPOT")`, `speed == 0`). An already-stopped vehicle produces an honest `PHASE_STOPPED` with `stop_issued: false`, which the verifier refuses — the cycle halts with the world labelled `UNCERTAIN_AFTER_FAILED_COMMAND`, never claiming a stop that did not happen.

**M4 — mutation-aware failure labels.**

`corridor_freight.py` adds `_FREIGHT_POST_MUTATION_STATUS`: per-op refusal statuses that the native handler can emit only after (or possibly after) its mutation command — `purchase: {COST_CHANGED, READBACK_MISMATCH, UNSUPPORTED_NATIVE_FACT}`, `order: {READBACK_MISMATCH, UNSUPPORTED_NATIVE_FACT}`, `start: {READBACK_MISMATCH, UNSUPPORTED_NATIVE_FACT}`, `finish: {READBACK_MISMATCH, UNSUPPORTED_NATIVE_FACT}`. `freight_phase_outcome` labels such failures `UNCERTAIN_AFTER_FAILED_COMMAND` instead of `HALTED_BEFORE_MUTATION`. Sets are deliberately conservative (a purchase `COST_CHANGED` fires pre-build too; the honest label is the stronger one), matching main.nut's rule that "no failed command is ever reported as leaving the world unchanged". Non-mutating ops and other statuses keep the pre-mutation label.

**M5 — waiting delta is recorded corroboration, explicitly not enforced.**

`corridor_freight.py` `verify_freight_loaded` now (a) requires the loaded readback to carry its station `wait` level (no `None` defaulting), (b) computes the delta against the admitted site baseline as before, and (c) records in the receipt the reason the A7 "waiting decrement" cannot be an enforced gate: pickup-station waiting is fed by unbounded industry arrivals during the window and cannot fall below zero, so no decrement is provable without inventing an arrival bound. The receipt carries `waiting_note` stating exactly that. This is the finding's sanctioned "explicitly document why station waiting can legitimately not decrease" alternative.

**M6 — transit sampled-monotonicity enforcement; continuity claim remains a design gap.**

`main.nut` `TransitWatch` now tracks `last_progress` across its samples: a sampled witness index behind an earlier one is a typed `INVALID_ROUTE` refusal (fail-closed, no observation fields attached). Combined with the existing off-witness and depot-wait exemptions, within-window sampled movement may only advance along the ordered witness. Regression tests cover (a) a forward-sampling drive that skips tiles between samples still reaching `AT_DELIVERY` (the sampled semantics are unchanged) and (b) a backward-sampled drive refused `INVALID_ROUTE`. Genuine tile-by-tile continuity remains stronger than per-tick sampling can prove; the design §1 D5-M4 wording ("transit tile after tile") is still broader than the evidence, and narrowing that wording is a design-document edit outside this task's authorized scope, left recorded here as the remaining gap (PARTIALLY RESOLVED).

**M9 — native company pin.**

`main.nut` `Handle` extends the admission refusal chain: any planned exchange from a company other than `FREIGHT_COMPANY` (0) is refused `INVALID_COMPANY` and halts the schedule prefix-preservingly, even when `GSCompany.ResolveCompanyID` would resolve it. The Python plan/verifier pin remains the primary control; the native handler now also refuses rather than range-checking.

### 13.3 New regression tests (`tests/test_corridor_freight.py`)

- M2: `test_nonzero_fleet_refuses_site_as_a_typed_refusal` — a seeded second vehicle makes `site-00` answer a parseable fieldless `INVALID_SITE`, halting `HALTED_BEFORE_MUTATION`.
- M3: `test_finish_proves_the_stopped_state_and_only_a_real_toggle` (happy stop proof; tampered `speed: 5` and `stop_issued: False` readbacks each refuse), `test_already_stopped_vehicle_is_never_toggled_and_honestly_halted` (`stop_issued: false` → world `UNCERTAIN_AFTER_FAILED_COMMAND`).
- M4: `test_post_build_purchase_refusal_is_not_labelled_before_mutation` (quote 20, realized cost 22 → `COST_CHANGED` *after* a real build, world `UNCERTAIN_AFTER_FAILED_COMMAND`), `test_pre_build_purchase_refusal_stays_labelled_before_mutation` (`STALE_ADMISSION` with zero vehicles → `HALTED_BEFORE_MUTATION`), `test_conservative_start_refusal_label` (conservative post-mutation labelling).
- M5: `test_loaded_receipt_records_the_waiting_delta_corroboration` (delta recorded, note present, delta 0 does not fail).
- M6: `test_transit_forward_progress_still_reaches_delivery` (skipping samples still verifies), `test_transit_sampled_direction_monotonicity_refuses_a_backward_drive`.
- M9: `test_native_handler_refuses_a_resolvable_foreign_company` (a resolvable second company answers `INVALID_COMPANY` and the schedule's `halted` flag is set).

The stub world gained a per-tick `::mover` hook (test-only, `tests/test_corridor_freight.py`) used solely to simulate sampled within-window movement; it is inert (`null`) for every pre-existing test.

### 13.4 Actual test and static-check results

All runs with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`:

| Check | Actual result | Exit |
|---|---|---|
| D5 combined (freight, native, optimizer) | 108 passed | 0 |
| D4/transport regression (construction, transport) | 71 passed | 0 |
| Ruff lint (the two modified Python files) | All checks passed | 0 |
| Ruff format check (same two files) | 2 files already formatted | 0 |
| `git diff --check` | clean | 0 |

Counts rose from 98 controlled-suite tests (of which 32 in the controlled file) to 108 total because of the ten new regression tests; no pre-existing test was removed, skipped, or re-targeted, and no formatter wrote files (format-only fixes were applied by hand).

### 13.5 Re-review status

Review method: self-review of the changed bytes plus the passing D5/regression suites; **not an independent review session** (none was available in this task). Findings re-checked by inspection of the current implementation and failure paths, not by test outcomes alone.

| Finding | Status | Basis |
|---|---|---|
| C1 | RESOLVED (unchanged) | `apply_cleanup_outcome`/`deny_verification`/`exit_status` bytes re-verified; native tests pass. |
| H1 / H2 / H3 / M1 / M7 | RESOLVED (unchanged) | `verdict_exit_status`, `exchange_timeout_seconds`+clamp, `verify_attempt_identity` re-binding, preflight equality, consumed-frame replay all re-verified; corresponding tests pass. |
| M2 | **RESOLVED** | Fleet refusal precedes field attachment; typed refusal tested. |
| M3 | **RESOLVED offline** | State-aware toggle plus verifier stop proof; native timing of the toggle (whether `GetState` reads `STOPPED`/`IN_DEPOT` with speed 0 at the exchange boundary in OpenTTD 15.3) is **UNKNOWN**; the verifier's strict refusal on any non-stopped proof makes a wrong native reading fail-closed, never falsely successful. The already-stopped-before-finish case halts honestly. |
| M4 | **RESOLVED** | Conservative per-op post-mutation sets and the new labelling; purchase pre/post-build and start negative cases tested. The `order`/`finish` post-mutation `READBACK_MISMATCH` arms are covered by inspection only (the controlled stub cannot make the handler fail its readback after a successful mutation); the sets are conservative so untested arms cannot over-claim a clean world. |
| M5 | **RESOLVED (documented)** | The delta is recorded, required present, and its non-enforcement is explained in the receipt itself; the load gate needs no unprovable arrival bound. |
| M6 | **PARTIALLY RESOLVED** | Within-window sampled-direction monotonicity is now enforced and tested; the true tile-by-tile continuity remains unproven by sampling, and the design §1 D5-M4 wording still overstates the evidence. Narrowing that wording needs a separately authorized design-document edit; left outstanding. |
| M8 | UNRESOLVED limitation | Unchanged (single-witness optimizer round-trip). |
| M9 | **RESOLVED** | Native `FREIGHT_COMPANY` pin; foreign resolvable company refused and halts. |
| L1–L8, I2 | UNRESOLVED | Not in this task's scope; unchanged. |
| I3 | Remains true | No native process, AdminPort, candidate, claim, signature, or authorization occurred. |

False-positive re-check: no new failure path can produce `RECEIPT_VERIFIED`, a wrong accounting figure, or an invalid state transition. The finish verifier is stricter (a stopped-proof-less `PHASE_STOPPED` now fails), the fleet and company refusals widen fail-closed behavior, the transit monotonic gate can only refuse, and the waiting note adds no gate to exploit.

### 13.6 Native-runtime limitations and UNKNOWNs

No native behavior was observed. Everything in §6/§12.7 remains UNKNOWN. Added offline-known UNKNOWNs: (1) whether an OpenTTD 15.3 stop toggle synchronously yields a stopped `GetState` at zero speed inside one exchange (M3's reading), with harmless fail-closed consequence; (2) whether sampled-direction monotonicity can misfire on a native (re-)routing nuance such as a station-buffered hop backward (a native-time `INVALID_ROUTE` halt — honest, evidence-preserving).

### 13.7 Suitability and next milestone

The second offline remediation closes every material Medium gate from §12.8: M2, M3, M4, M5, M9 are resolved (M5 via the honest documentation option; M3 offline-resolved with an explicit native UNKNOWN) and M6 is resolved as far as sampled evidence can carry it, with the design-wording gap recorded rather than silently narrowed. The offline harness now enforces a typed refusal shape at every admission refusal, proves the finish stop, labels post-mutation refusals honestly, and pins the company natively.

**Assessment: suitable to proceed toward a controlled T8 staging request under a new explicit operator authorization, with the following caveats:** (a) M6's design §1 D5-M4 wording should be narrowed to "sampled-direction monotonic transit observation" before the receipt is used as continuity evidence; (b) M8 remains an unresolved limitation (no competing executable-route choice is demonstrated; no "optimizer-selected native construction" claim may be made); (c) all native facts remain UNKNOWN until a controlled attempt; (d) several Low findings (L1–L8) and the status-document lag (I2) remain open. Gate C operator authorization remains a separate, ungranted decision.

### 13.8 Preservation statement

This second remediation changed only `app/simulation/openttd/d5_freight_package/main.nut`, `app/simulation/openttd/corridor_freight.py`, `tests/test_corridor_freight.py`, and this addendum in `docs/d5-corridor-freight-t7-review.md`. All first-remediation changes were preserved byte-for-byte. No artifact, secret, excluded path, Git ref, native runtime, candidate, claim, signature, or authorization was touched. HEAD remains `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`, equal to `origin/devmodule2`.

---

## 14. Final offline readiness addendum (M8, M6 wording, L1–L8, I2) — 2026-10-27

This addendum records the final offline readiness review before any T8 request. Sections 1–13 are preserved unchanged. It supersedes only the outstanding statuses of M6 (design wording), L1–L8, and I2 in §12.5/§13.5.

### 14.1 Repository state and scope

- Repository: `/home/fed/codes/softdev2`, branch `devmodule2`
- HEAD and `origin/devmodule2` at start and end: `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`
- Files changed by this task: `docs/d5-corridor-freight-design.md` (D5-M4 bullet only), `app/simulation/openttd/proof/corridor_freight_native.py` (L4/L8 replay hardening only), `tests/test_corridor_freight_native.py` (two new regression tests), `TASKS.md` and `OpenTTD-Knowledge/99-Source-Documents/TASKS.md` (one appended status paragraph, mirror kept byte-identical), and this addendum.
- All prior remediation bytes (first and second rounds) were preserved; the pre-existing `OpenTTD-Knowledge/.obsidian/workspace.json` modification is untouched.
- No staging, commit, push, reset, clean, stash, history rewrite, ref change, OpenTTD launch, AdminPort connection, candidate staging, claim, signing, sealing, or Gate C authorization occurred. Nothing under `artifacts/` was written or modified (the D4 candidate-5 directory was read only); no excluded path (`.gitignore`, root `--version`, `.agents/`, `.perch/`, `skills-lock.json`, `OpenTTD-Knowledge.zip`, `.env`, secrets) was touched.

### 14.2 M8 — disposition: NOT VERIFIABLE OFFLINE (unresolved limitation; does not block a fixed-corridor T8)

The expectation M8 records as unmet is that the staged D5 plan should select among competing executable routes. `optimized_freight_route()` (`app/simulation/openttd/proof/corridor_freight_native.py:322-349`) passes exactly one witness candidate — the retained D4 corridor — to `route_from_d5_map`, then refuses staging unless the optimizer's selection round-trips to that same witness. Evidence inspected for this disposition:

- `route_from_d5_map` (`app/simulation/openttd/corridor_route_optimizer.py:766-801`) genuinely supports several candidates ("Supplying more than one witness candidate makes the same endpoints compete in the production optimizer"), the production `optimize_candidate_network` path is really invoked, and the route/digest binding into the wire plan is real. The single-candidate call is a staging input choice, not a bypassed optimizer.
- The retained D4 evidence (`artifacts/experiments/d4-corridor-native-candidate-5/corridor-route-read.json`) records exactly the 24 built corridor tiles (`connected_pairs: 23`, `status: "READ"`, `eligible: true`) and no other road. There is no post-D4 built-road connectivity survey anywhere in the repository establishing that a second executable route exists on the pinned world.
- The GameScript latches the route from `site` and issues no road-construction command, so D5 cannot build an alternative route natively either.

Supplying a second candidate would assert tile feasibility that no retained evidence supports — inventing evidence — so no source change was made and the contract was not weakened. M8 is therefore a scope limitation, not a defect: the harness never claims optimizer-selected native construction (§8, §12.7, §13.7 all record this). It does not block a **fixed-corridor** freight POC attempt, because that attempt needs only the one retained corridor. It does block, permanently and until a native road survey or a construction-capable milestone exists, any claim that the optimizer chose among competing executable routes in the live world.

### 14.3 M6 — disposition: RESOLVED (documentation precision completed)

`docs/d5-corridor-freight-design.md` D5-M4 (lines 56-65) previously claimed "transit tile after tile along the built road". It now states exactly what `main.nut` `TransitWatch` (lines 903-997) enforces: per-tick position sampling; every sampled position on the ordered witness (the pinned depot tile exempt at any sample, being off-witness by construction); sampled witness indices never regress (sampled-direction monotonicity, typed `INVALID_ROUTE` on regression); arrival requires the delivery tile with a full load; and an explicit disclaimer that this is sampled evidence, **not** tile-by-tile continuity — a vehicle that left the witness and returned between two samples would not be observed, and the receipt makes no continuous-path claim. Only that one bullet was modified; the §13.2 enforcement bytes in `main.nut` are unchanged. With the design claim narrowed to match the evidence, M6 is resolved and no continuity overstatement remains in the design record.

### 14.4 L1–L8 triage

| Finding | Disposition | Rationale |
|---|---|---|
| L1 schema-1 witness geometry | **Defer (documented limitation)** | Latent only: production D5 plans are schema 2, and a schema-1 plan still pins the exact stop/depot constants, the 24-tile length and distinct endpoints. No false-positive path exists in the staged lineage. Does not block T8. |
| L2 package `info.nut` identity | **Defer (documentation nuance)** | The staged identity is the retained frozen-source `NetworkFreightProof` composition, enforced by preflight/replay identity checks; the unused package `info.nut` cannot affect a staged attempt. Reader-confusion only. Does not block T8. |
| L3 1450-byte ceiling not enforced | **Defer** | The 640-byte application bound is strictly tighter and is enforced on both the live encode/decode path and the replay parse path, so the named engine ceiling cannot be reached. Does not block T8. |
| L4 manifest not exhaustive | **RESOLVED this task** | Evidence-integrity gap: a rewritten manifest omitting a retained file escaped hash checking. `verify_freight_attempt` now requires the manifest's name set to equal the directory's regular-file set excluding the manifest itself (`corridor_freight_native.py:1712-1726`). Regression test `test_replay_refuses_a_manifest_that_omits_a_retained_file` fails with the fix reverted and passes with it applied (both verified). Subdirectories such as `isolated/` are excluded by `is_file()`, matching `harness.manifest()` generation, so legitimate retained attempts still replay. |
| L5 live duplicate draining | **Defer (partially addressed in round 1)** | Multiple GameScript frames in one receive are refused; a duplicate arriving in a later frame fails closed at the next correlation check, and replay independently enforces response uniqueness. Worst case is an honest halt, never false success. Does not block T8. |
| L6 `INVALID_COMPANY` untested | **RESOLVED (by round 2)** | `tests/test_corridor_freight.py:1378` `test_native_handler_refuses_a_resolvable_foreign_company` exercises the M9 native pin and asserts the typed `INVALID_COMPANY` refusal plus the schedule halt. The finding's own precondition ("especially after M9 is addressed") is met. |
| L7 native refusal byte bound | **Defer** | An oversized native refusal fails closed as a Python-side decode error at the 640-byte bound; the failure mode is an honest protocol error, not false success. Enforcing the bound inside Squirrel would add native risk for no integrity gain. Does not block T8. |
| L8 malformed orphan responses skipped | **RESOLVED this task** | Evidence-integrity gap: an unparsable `*-response.json` was silently skipped during replay. The parse loop now raises `ValueError` naming the file (`corridor_freight_native.py:1804-1809`). Regression test `test_replay_refuses_a_malformed_orphan_response_file` fails with the fix reverted and passes with it applied (both verified). All fifteen legitimate response files parse as `FreightReadback`, so the consumed-frame success fixture is unaffected. |

None of the deferred items can cause false-positive verification, incorrect cargo/accounting claims, identity drift, or loss of evidence integrity: each either fails closed or is inert in the staged lineage.

### 14.5 I2 — disposition: RESOLVED (minimal status correction)

The exact inconsistency: the D5 entry's 2026-10-26 update in `TASKS.md` described the T5/T6 implementation as existing "uncommitted" and an optimizer-produced route as future work ("the eventual POC still needs an optimizer-produced route in place of the fixed compiled plan"), while the committed tree contains those files and the staged plan already runs through the production optimizer. Minimum correction: one appended `**Update (2026-10-27, offline):**` paragraph (15 lines) inside the same D5 entry, stating (1) the implementation is committed on the `f67f107`…`70d4ce7` lineage rather than uncommitted, (2) the optimizer-produced route now exists via `route_from_d5_map`/`optimized_freight_route` with the selected route digest-bound into the wire plan, (3) the single-witness M8 limitation, (4) T7 plus two offline remediation rounds are recorded in this review document, and (5) native freight delivery remains UNKNOWN with T8 staging and Gate C as separate ungranted gates. No other status text was touched and no broad rewrite was performed. The TASKS mirror contract is preserved: `cmp TASKS.md OpenTTD-Knowledge/99-Source-Documents/TASKS.md` is byte-identical after the edit.

### 14.6 Actual test and static-check results

All runs used `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`, after every source and test change:

| Check | Actual result | Exit |
|---|---|---|
| D5 combined: `tests/test_corridor_freight.py`, `tests/test_corridor_freight_native.py`, `tests/test_corridor_route_optimizer.py` | 110 passed (72 + 38 progress dots; the prior 108 plus the 2 new tests) | 0 |
| D4/transport regression: `tests/test_corridor_construction_native.py`, `tests/test_gamescript_transport.py` | 71 passed | 0 |
| Ruff lint (the two modified Python files) | All checks passed | 0 |
| Ruff format check (same two files) | 2 files already formatted | 0 |
| `git diff --check` | clean | 0 |
| TASKS mirror | `cmp` byte-identical | 0 |
| Pre-fix regression proof | both new tests fail with the L4/L8 hunks temporarily reverted, and pass after re-applying | 0 |

No auto-fix, formatter write, bytecode write, or cache write was used; the one format deviation the check reported (a test signature reflow) was corrected by hand. No pre-existing test was removed, skipped, or re-targeted.

### 14.7 Re-review

Method: **self-review**. A fresh-context review subagent was dispatched over the same four changes but hit its execution time limit without returning a report, so no independent-session findings are available to cite and this addendum does not claim independent review.

Re-reviewed by inspection of the current bytes: cleanup and CLI exit status (`apply_cleanup_outcome`, `deny_verification`, `exit_status`, `verdict_exit_status` — unchanged this task, still requiring `verified`, `NATIVE_FREIGHT_VERIFIED` and certified cleanup); timeout and cancellation handling (`exchange_timeout_seconds` plus the remaining-budget clamp — unchanged); pinned prerequisite and identity binding (`verify_attempt_identity`, the preflight world-save equality, the full-welcome comparison — unchanged, and the new L4 exhaustiveness check sits before the schema and authorization branches so it cannot be bypassed); consumed-frame replay correctness (the success fixture still returns `RECEIPT_VERIFIED`; both new checks can only raise); GameScript state transitions and cargo/accounting invariants (`main.nut` untouched this task); route and plan digest binding (untouched; the M8 round-trip refusal is intact); and every byte this task changed.

False-positive hunt on the two source changes: each converts a previously skipped or unhashed condition into a raised `ValueError`. Neither can produce `RECEIPT_VERIFIED`, alter a cargo or accounting figure, or mask an earlier error — the manifest loop still raises on any digest mismatch before the new set comparison runs, and the response loop still raises on identity/request mismatch after parsing. `verify_freight_attempt` writes nothing (confirmed by inspection of the replay body), so the exhaustiveness check cannot race against replay's own file creation.

### 14.8 Remaining unknown native behavior

Everything in §6, §12.7 and §13.6 remains UNKNOWN: all native site, engine, purchase, order, load, transit, delivery, monitor, finance, finish and cleanup facts on OpenTTD 15.3; the M3 question of whether a stop toggle synchronously yields a stopped zero-speed `GetState` inside one exchange; and whether sampled-direction monotonicity can misfire on a native re-routing nuance such as a station-buffered backward hop. Both unknowns fail closed. This task observed no native process, opened no AdminPort session, and created no native evidence.

### 14.9 Suitability verdict

**The remaining review findings do not prevent a controlled fixed-corridor native freight POC attempt.** With M6's design wording now matching the sampled evidence, L4 and L8 closed, L6 closed by round 2, and the remaining Lows deferred on documented fail-closed grounds, no open finding can cause false-positive verification, incorrect cargo or accounting claims, identity drift, or loss of evidence integrity in the staged lineage. M8 is a scope limitation of this POC rather than a readiness defect: the attempt is a freight cycle over the one retained D4 corridor, and no optimizer-route-choice claim may be drawn from it.

It is **suitable to proceed toward a T8 staging request under a new explicit operator authorization**, carrying forward §13.7's caveats with (a) now discharged: (b) M8 remains an unresolved limitation — no "optimizer-selected native construction" claim may be made; (c) all native facts remain UNKNOWN until a controlled attempt; (d) L1, L2, L3, L5 and L7 remain deferred documented limitations. This addendum is not T8 staging, not native execution, and not Gate C authorization. It does not claim verified native freight delivery, and it does not claim optimizer-to-route construction is complete.

### 14.10 Preservation statement

This task changed only `docs/d5-corridor-freight-design.md` (one bullet), `app/simulation/openttd/proof/corridor_freight_native.py` (two replay-hardening hunks), `tests/test_corridor_freight_native.py` (two tests plus one hand-applied signature reflow), `TASKS.md` and its byte-identical mirror `OpenTTD-Knowledge/99-Source-Documents/TASKS.md` (one appended paragraph each), and this addendum. All prior remediation work and the earlier review text are preserved. HEAD remains `1e6d6c1f6b0b5deede9072d67f4e692a1f94a96f`, equal to `origin/devmodule2`; nothing was staged, committed, pushed, reset, cleaned, stashed, or rewritten. No artifact, secret, candidate, claim, signature, seal, or authorization was created.
