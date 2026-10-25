# D4 Native Road & Station Construction — candidate-5 consumed outcome: PROVEN

Status: **`D4-CORRIDOR-5` CONSUMED EXACTLY ONCE under explicit operator
authorization (message dated 2026-10-26 authorizing signing and exactly one
native attempt). The phase is `PHASE_COMPLETE`: all seven scheduled
operations built and were independently read back, the pure-observation route
read verified 23/23 witness pairs, the authoritative receipt-bound `after.sav`
exists, the read-only production replay verifier returns `RECEIPT_VERIFIED`,
and cleanup is certified (all four fields true). Result `verified: true`,
`status: NATIVE_CORRIDOR_VERIFIED`, return code 0. **Milestone D4 native road
and station construction is COMPLETE (native)** for exactly the reviewed v3
schedule over the receipt-verified post-D3 world — and nothing beyond it.**

Date: 2026-10-26. Predecessors:

- [candidate-5 preparation + independent review](../2026-10-25/d4-corridor-native-candidate-5-preparation.md)
  (staged 2026-10-25; reviewer verdict PASS, 20/20)
- [candidate-4 outcome](../2026-10-25/d4-corridor-native-candidate-4-outcome.md)
  (consumed exactly once; `op-06` response-size halt; must not be retried)
- [response-limit fix](../2026-10-25/d4-corridor-response-limit-fix.md) (E33)
- [candidate-4 preparation](../2026-10-25/d4-corridor-native-candidate-4-preparation.md)
  (E31 — the staging procedure followed for candidate-5)

No retry, second launch, reconnect, replacement candidate, claim reuse or Git
stage/commit/push/reset/clean/stash was performed. The attempt ran once:
1 launch, 1 connection, 22 of the 28 request budget used.

## 1. Pre-signing verification (all gates PASS, 2026-10-26)

Re-verified independently before signing, exactly as the authorization
message required:

| Gate | Result |
| --- | --- |
| Candidate identity | `D4-CORRIDOR-5`, milestone `D4-CONSTRUCTION`, kind `corridor`, schema `d4-corridor-native-prelaunch-v1`; module constant `CORRIDOR_ATTEMPT` current |
| PRELAUNCH seal | `sha256(PRELAUNCH.json)` = `505b5d493752845041838e5f4dfc6d068f09a8ccb8a264bba3a7a1ba490a4a7c` = `PRELAUNCH.sha256` |
| Authorization payload | sha-256 `77a965f0d0b0404637385c522bd518a2ab525ec249be67d5f848416ed455d0e4` over 2,307 canonical bytes, recomputed from the candidate's own staged bytes via `staged_authorization_payload_digest` |
| Plan digest | `b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78`; triple-match (sealed record / re-derived `plan_digest_of(corridor_schedule())` / reviewed documentation) |
| Schedule v3 invariants | 7 ops (3 `full`, 1 corner `road` `45743↔45999` = op-03, 2 `station`, 1 `depot`); 22 planned exchanges; request cap 28 (budget `requests: 28`); `MAX_CORRIDOR_COST` £2,000 per op; no `48047↔48303` interior join |
| Source save | staged `source.sav` = D3 after-save `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`; D3 prerequisite seal `edb6b34c…cff9e` and after-save re-read unchanged |
| Frozen closure | 3,448 entries; `verify_freeze` PASS inside read-only `PREFLIGHT PASS` (re-ran 2026-10-26) |
| Independent review | [preparation record §6](../2026-10-25/d4-corridor-native-candidate-5-preparation.md): fresh-context reviewer, read-only, verdict **PASS 20/20** |
| Implementation vs reviewed version | working-tree delta versus HEAD is exactly the reviewed scope (E33 protocol rules + the one identity constant now `D4-CORRIDOR-5`); the freeze re-hash binds current bytes == reviewed bytes; focused suites re-run 129/129 PASS |
| Protocol limits | protocol 4 explicit `MAX_CORRIDOR_RESPONSE_BYTES = 640` (513-byte bodies decode, exact 640 passes, 641 refuses); default `MAX_PAYLOAD_BYTES = 512` unchanged (513 refused by default decode and default encode); requests bounded 512; `MAX_GAMESCRIPT_PAYLOAD_BYTES = AdminFrameDecoder.MAX_FRAME_LENGTH − 4 = 32763`; malformed/truncated/double-NUL/non-UTF-8 all fail closed |
| Budget machinery | admission requires a positive tested quote within the ceiling (`0 < readback.cost <= max_cost` → `native READY admission with positive tested cost required`); budgets bound ceremony (900 s total, 10 s per exchange, 1 launch, 1 connection, 0 retries) |
| Runtime isolation | no OpenTTD process; no listener on 54655/50765; candidate-3/candidate-4 `isolated/` empty; no staged secret outside the candidate workspace |
| Never-consumed state | no `AUTHORIZATION.json`, `CLAIM.json`, `LAUNCH-CONSUMED.json`, `receipt.json` or `result.json` in the candidate directory |

Every digest, manifest item, review figure, source byte and runtime check
matched the reviewed candidate. No artifact was refreshed, regenerated or
substituted.

## 2. Signing (documented approved procedure)

Exactly the reviewed signing checklist was executed
([key provisioning §4](../../handoff/2026-10-17/operator-key-provisioning.md),
Option 1 repository tooling only):

1. Refusal gates first: none of `AUTHORIZATION.json`, `CLAIM.json`
   or `LAUNCH-CONSUMED.json` existed, re-checked in the signing script and
   again inside the payload builder.
2. The canonical payload was recomputed offline from the candidate's own
   staged bytes (digest + 2,307-byte count matching the authorized identity).
3. The operator seed was extracted from the operator-held PEM with the
   corrected exit-status/shape-checked pipeline into a shell variable; it was
   never printed, written to a file, passed as an argument or logged;
   extraction failure or malformed value would have refused the ceremony.
4. The record was signed with `sign_authorization_record`; the seed's derived
   public key was checked equal to the pinned production anchor
   `5063982bd28d48573705f334ed4f396618c4930ce21083789dfbbf13a564880f`, and the
   64-byte signature was verified under that anchor over the exact canonical
   bytes **before** writing.
5. `AUTHORIZATION.json` written (canonical JSON style); the seed variable was
   cleared immediately after signing (`unset`, verified empty).

Verification of the resulting record (the same gate the launch uses):

| Fact | Value |
| --- | --- |
| `AUTHORIZATION.json` sha-256 | `5548697100c4255af6b87e7b9c8980c174685647a9ff5cbe18b97878819dec03` |
| `verify_authorization` | PASS (candidate binding equality + trusted-origin RFC 8032 Ed25519 signature) |
| Signed payload digest | `77a965f0d0b0404637385c522bd518a2ab525ec249be67d5f848416ed455d0e4` — matched the authorized payload |
| Operator identity | `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` (unchanged production anchor) |

## 3. The one native attempt

`openttd-15.3` 15.3 launched once from the staged workspace, one encrypted
X25519 AdminPort connection (admin 54655, game 50765), welcome identity
matched exactly (revision 15.3, seed 17, landscape 0, 256×256,
`start_day 712223`); pid `105464`.

Funds started at **£496,543** (first `inspect-00` funds, unchanged from D3).

| Op | Planned scope | Tested quote | Native cost | Readback | Funds after |
| --- | --- | --- | --- | --- | --- |
| `op-00` | run A `45747→45743`, 5 tiles | £785 | £785 | `confirm-00` READ, digest matched | £495,758 |
| `op-01` | run-B segment `45999→48047`, 9 tiles | £1,398 | £1,398 | `confirm-01` READ, digest matched | £494,360 |
| `op-02` | run-B segment `48303→50095`, 8 tiles | £1,151 | £1,151 | `confirm-02` READ, digest matched | £493,209 |
| `op-03` | perpendicular corner `45743↔45999`, 2 tiles | £71 | £71 | `confirm-03` READ, digest matched | £493,138 |
| `op-04` | pickup stop tile `45748`, front `45747` | £307 | £307 | `confirm-04` READ, digest matched | £492,831 |
| `op-05` | delivery stop tile `50351`, front `50095` | £292 | £292 | `confirm-05` READ, digest matched | £492,539 |
| `op-06` | depot tile `45487`, front `45743`, orientation `south` | £390 | £390 | **`confirm-06` READ, digest matched** (the E33 640-byte bound applied; `depot-06-response.json`, 513-byte payload, retained) | **£492,149** |
| route read | 24-tile witness, 23 adjacent pairs | — | 0 | `ROUTE_VERIFIED`, 23/23 pairs, `first_fail_index −1` | £492,149 |

Funds reconciliation for every operation — native costs equal their positive
tested quotes, all within the £2,000 per-op ceiling:

```text
£496,543 − £785 − £1,398 − £1,151 − £71 − £307 − £292 − £390 = £492,149
```

The final funds figure is confirmed twice by independent evidence: the
route-read observation (`route-00`, funds `492,149`) and the
`op-06` depot readback path. Every one-line receipt binds the same
`source_save_digest` (`a3e6b5102ae12f98fd782c5a417ac2bc2237397ef3ca66163ed4695ce369cc5c`,
the owned `session-before.sav`) and the prelaunch seal
`505b5d49…4a7c`; each carries `NATIVE_STATE_CHANGED`.

## 4. Receipt, saves, manifest, replay, cleanup

| Fact | Value |
| --- | --- |
| `receipt.json` | present; `verification: PHASE_COMPLETE`, `failed: null`, `pending: []`, all 7 per-op receipts + route receipt |
| Route receipt | `ROUTE_VERIFIED`, 23/23 pairs (pure observation — never a build assertion) |
| `after.sav` | **present, authoritative, receipt-bound**; sha-256 `a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261` |
| `after-diagnostic.sav` | retained (`7a853eba7c3cb00418f182c335315ddca66267d79a270a23ddc9044ccaaf89a3`); diagnostic copy, never a substitute |
| Response evidence | 22 request/response pairs retained (inspect ×7, build ×7, confirm ×7, route ×1) + `frames.json`; every op has `corridor-XX-{before,intent,built,independent}.json` |
| `result.json` | `verified: true`, `status: NATIVE_CORRIDOR_VERIFIED`, `native_launches: 1`, `connections: 1`, `requests: 22`, `returncode: 0`, no halt, no error, no script-log health findings |
| Artifact manifest | **90/90 OK** (`sha256sum -c`, no failures) |
| Read-only replay verifier | **`RECEIPT_VERIFIED`**, exit 0 (independent re-derivation from retained bytes; the E33 protocol fix and the durable depot response both exercised) |
| Cleanup | `reaped: true`, `sockets_closed: true`, `workspace_disposed: true`, `credential_removed: true`, `cleanup_error: []`, return code 0; endpoint verification: listener closed, connection closed, reservation released, process reaped, kernel TIME_WAIT only |
| Post-run isolation | no OpenTTD process, no listener on 54655/50765, `isolated/` empty (0 files) |

## 5. Evidence preservation

The consumed attempt evidence is entirely in
`artifacts/experiments/d4-corridor-native-candidate-5/` (sealed
`PRELAUNCH.json`/`PRELAUNCH.sha256`, `graphics-identity.json`, the signed
`AUTHORIZATION.json`, consumed `CLAIM.json`, `LAUNCH-CONSUMED.json`,
`session-before.sav`/`after.sav`/`after-diagnostic.sav`, all 22 exchange
pairs, per-op evidence, `corridor-route-read.json`, `runtime-identity.json`,
`frames.json`, `stdout.log`/`stderr.log`, `result.json`, `receipt.json`,
`cleanup.json`, `artifact-manifest.sha256`).

Preserved, unchanged, verified: the D3 prerequisite record (seal `edb6b34c…`
and after-save `fbebef54…d59e` re-read identical), candidate-4's 80-file
manifest (80/80 OK re-verified before the run), candidate-1/2/3 directories
and manifests, and every historical outcome. Nothing was edited, relabeled or
implied-success: candidates 1/3/4 remain `verified: false` partial/failed
attempts and candidate-2 remains stale.

## 6. Acceptance assessment

| D4 acceptance area | Result |
| --- | --- |
| Candidate identity / authorization binding | PASS (signed + verified under pinned anchor) |
| One-shot claim / no retry | PASS — consumed once, `launches_allowed: 1`, `retries: 0`, 1 launch / 1 connection / 22 requests |
| v3 schedule invariants | PASS — 7 ops, 22 planned, cap 28, ceiling £2,000, no interior join, corner present |
| All seven scheduled operations executed + verified | **PASS — 7/7 with independent native readbacks** |
| Per-operation receipts for the full schedule | **PASS — 7/7 `NATIVE_STATE_CHANGED` receipt lines + `receipt.json`** |
| Route receipt (23/23 witness pairs, stops, depot) | **PASS — `ROUTE_VERIFIED`** |
| Authoritative receipt-bound after-save | **PASS — `after.sav` `a81ac836…`** |
| Funds reconciliation | PASS — £496,543 → £492,149, native cost = quote per op |
| Cleanup certification | PASS — all four fields true, endpoints certified, workspace disposed |
| Replay verification | **PASS — `RECEIPT_VERIFIED`** |
| Milestone D4 native construction | **COMPLETE (native, exactly this v3 scope)** |

## 7. Limits (scope-of-proof discipline)

- This proves exactly the reviewed v3 corridor construction over the
  receipt-verified post-D3 Seed 17 world: the two runs, the corner join, the
  two truck stops, the depot and the connected route observation. It asserts
  nothing beyond the staged schedule, the pins, and the world after `after.sav`.
- It is not: vehicle purchase/orders, deliveries, OPEX, net profit, ROI, or
  any P07/P08 claim. Those remain separate future work (D5 and beyond).
- The retained post-D3 `fbebef54…d59e` source world is a controlled
  historical reference; the authoritative current world is the candidate-5
  `after.sav`.
- Consumed identities must never be retried or reused: `D4-CORRIDOR-1`,
  `D4-CORRIDOR-3`, `D4-CORRIDOR-4` remain failed/partial; `D4-CORRIDOR-4` was
  halted by its response-size path (fixed offline in E33 but never
  re-executed); `D4-CORRIDOR-2` was never launchable.

## 8. What this record does not authorize

- Any further native execution: the candidate's one-shot claim is consumed;
  a next milestone (D5 vehicle purchase/orders/delivery on this corridor) or
  any new construction needs a fresh reviewed candidate and a fresh explicit
  operator authorization.
- Any Git staging, commit, push, reset, clean, or stash.
- Any edit to retained historical evidence.
