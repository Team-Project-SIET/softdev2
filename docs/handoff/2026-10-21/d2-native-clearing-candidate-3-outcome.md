# D2 Native Clearing — Candidate-3 outcome handoff

Status: **D2 CANDIDATE-3 CONSUMED — RESULT `NATIVE_STATE_VERIFIED`, returncode 0; one-shot claim CONSUMED; evidence preserved byte-for-byte**

Predecessor record: [d2-native-clearing-candidate-3-preflight.md](d2-native-clearing-candidate-3-preflight.md)
("D2 CANDIDATE-3 PREFLIGHT PASSED — AWAITING OPERATOR SIGNATURE"). This
document closes that record. The Milestone D2 proposition — one operator
authorized native launch performs one pinned single-tile tree clear and the
independent readback proves the native state changed — is **PROVEN** for the
consumed attempt below.

No tile other than the pinned target was touched, no second launch or
connection was made, and no Git stage/commit/push/reset/clean/stash was
performed for this work. The evidence directory is preserved byte-for-byte
(its own 25-file SHA-256 manifest re-verified, see §7).

## 1. What happened — factual record

**The record-writing session did NOT initiate the launch.** It did not sign
any authorization, write any `AUTHORIZATION.json`, or execute any `run`
command for this candidate. On its next read-only state check the claim was
already found consumed. What follows are on-disk facts (file mtimes, minute
precision, +0700) and the verification result of the consumed attempt; who
signed the authorization record is not asserted by this document — the
record itself (`AUTHORIZATION.json`) carries only the payload and a
signature, and it **verifies under the production operator anchor**
(§6) exactly as staged in the preflight handoff.

## 2. Factual execution timeline (file mtimes on the retained evidence)

| Time (2026-10-21) | Fact | Source |
| --- | --- | --- |
| 00:19:44 | `PRELAUNCH.json` staged for candidate-3 | file mtime |
| 00:23 | preflight handoff document recorded (PREFLIGHT PASSED, AWAITING OPERATOR SIGNATURE) | `docs/handoff/2026-10-21/` mtime |
| 01:07:20 | `AUTHORIZATION.json` appears in the candidate directory | file mtime |
| 01:09:19 | `CLAIM.json` written — the claim is consumed (1 launch) | file mtime |
| 01:09:20 | `LAUNCH-CONSUMED.json`, `result.json`, `receipt.json`, `cleanup.json`, `session-before-identity.json`, exchange/request-response files, `frames.json`, saves and both session logs written — run complete | file mtimes |
| afterwards | the record-writing session's read-only state check finds the claim consumed; no re-run, no tampering; evidence preserved | this handoff |

## 3. Consumed-attempt evidence inventory

`artifacts/experiments/d2-clearing-native-candidate-3/` — candidate-1 and
candidate-2 and every other historical artifact stay untouched.

| File | Role |
| --- | --- |
| `PRELAUNCH.json` / `PRELAUNCH.sha256` | sealed prelaunch record + seal (sha `b2636e0d5e6f3197970635aac08a1a428a69d0bb99016bff23eee30fac5acf0b`) |
| `AUTHORIZATION.json` | `{payload, signature}`; verifies under the production operator anchor — record sha `e4abf92a10c908a7614db0d804967e6678ee027a036b6212d56ecd85f56f89c7` |
| `CLAIM.json` | one-shot claim, `d2-clearing-claim-authorization-v2`, **`consumed: true`**, `launches_allowed: 1`, `retries: 0` |
| `LAUNCH-CONSUMED.json` | immutable launch-consumption marker, schema `d2-clearing-native-launch-consumed` |
| `plan.json`, `read-0/inspect-1/clear-1/read-2` request+response pairs, `frames.json` | the exact staged plan and the full 13-frame AdminPort walk (§4) |
| `receipt.json` | `company-clearing-receipt-v1` (§5) |
| `result.json` | machine result: `NATIVE_STATE_VERIFIED`, `verified: true`, `returncode: 0` (§3.1) |
| `session-before.sav` / `after.sav` / `after-diagnostic.sav` | owned session saves: before sha `6844a65dec3452ce2c70fcb081204e386521caf799c6a4617d527f122c471f06`, after sha `298ec1f80498e6ad04c92542798be814bf5a5ebe337ee64dec97e59713b716bd` (61,680 bytes), diagnostic sha `3775840211fd4b1698d8b3c333ccd5360c05f2826378629eefab756d78a150a7` |
| `runtime-identity.json` | encrypted X25519 session identity (§6) |
| `cleanup.json` | endpoint closure + process reaping (§6) |
| `artifact-manifest.sha256` | 25-file SHA-256 manifest, re-verified `MANIFEST_OK` |
| `stderr.log`, `stdout.log`, `graphics-identity.json`, `isolated/` | native logs, base-graphics identity, disposed workspace skeleton |

### 3.1 `result.json` — the verdict of the attempt

| Field | Value |
| --- | --- |
| status | `NATIVE_STATE_VERIFIED` (`verified: true`) |
| clearing | `CLEARED`, `command_accepted: true`, `state_changed: true` |
| returncode | 0 |
| native_launches / connections / requests | 1 / 1 / 4 |
| dispatched plan / request | PRELAUNCH seal `b2636e0d…c5acf0b` / `clear-1` |
| pin | tile 46769, `TREES`, flags 9, elevation 2, slope 0, unowned, census page 34 sha `7ab77764…d3c9e5af` — sealed-census byte evidence |

## 4. The staged and executed exchange plan

Exactly four exchanges, in order, on one connection:

| request | op | wire cost returned |
| --- | --- | --- |
| `read-0` | `READ` observation of the target | 0 |
| `inspect-1` | `READY` admission with the pinned classification | 15 (quote) |
| `clear-1` | the single clear (`GSTile.DemolishTile(tile)`) at the mutation boundary, plan equality re-checked against the latching inspect plan | 15 (native `CMD_LANDSCAPE_CLEAR` cost) |
| `read-2` | independent readback observation | 0 |

`frames.json` = 13 frames: two inbound welcome/identity frames, one admin
ping and its PONG, then the four request/response pairs above.
`prelaunch_digest`, `plan.json` and the dispatched plan agree on the same
seal `b2636e0d…c5acf0b`.

## 5. The clearing receipt — independent readback proof

`receipt.json` (schema `company-clearing-receipt-v1`), bound only after the
clear result and the independent readback agreed:

| Field | Value |
| --- | --- |
| tile / company | 46769 / 0 |
| operation | `DEMOLISH_CLEAR` → `native_command: CMD_LANDSCAPE_CLEAR` |
| original → expected→ actual classification | `TREES` → `CLEAR` → `execution_status: CLEARED`, `verification: NATIVE_STATE_CHANGED` |
| quote / native cost | 15 / 15 (≤ `max_cost` 10,000) |
| cost attribution (`result.json`) | GSAccounting command-scoped cost 15 and company cash delta 15 agree (`funds_at_inspect` £500,000 → `funds_at_exec` £499,985); an unexplained mismatch fails the receipt |
| plan digest | `a8b51c6f4f9302b2bfd3cdd22ea519eb60283a173f9c6862979d6317e4d42a95` |
| digests | `source_save_digest` `6844a65d…471f06`, `prelaunch_digest` `b2636e0d…c5acf0b`, `after_digest` `ebb71890…483b594`, `after_save_sha256` `298ec1f8…716bd` |

## 6. Runtime, authorization and cleanup facts

| Fact | Value |
| --- | --- |
| binary | `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`, sha `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` — re-verified against the pinned `BINARY_SHA256` after the run |
| welcome | revision `15.3`, seed `17`, landscape `0`, 256×256, `start_day 712223`, dedicated |
| runtime identity | `auth: X25519_AuthorizedKey`, `encrypted: true`, pid 32062 |
| operator identity | fingerprint `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` (production anchor; claim + authorization record agree) |
| cleanup | `quit_requested`, `graceful_attempted`, **`reaped: true`** returncode 0, sockets closed, admin credential removed, port reservation released, workspace disposed, `remaining_processes: []`, `cleanup_error: []` |

## 7. Preservation verification performed for this document

- `sha256sum -c artifact-manifest.sha256` → all 25 entries OK (`MANIFEST_OK`).
- `verify_authorization(candidate, PRELAUNCH, seal)` → **BINDS**
  `e4abf92a…f56f89c7` / `cbb63ff5…ae40c614` (read-only; no `run`).
- The pinned binary's SHA-256 re-checked live — unchanged.
- No `openttd` process is running on the host; no claim remains consumable
  (`consumed: true`, marker written).

## 8. Honesty and limits

- **Strictly one tile.** The proof covers exactly the pinned tree tile
  46769 in the retained Seed 17 world; anything beyond it is not claimed.
- **The consumed attempt is not portable to later milestones.** It does
  NOT fulfill the D3 native integration prerequisites: those use different
  targets/pins (45999, 49326), their own attempt identifiers, their own
  prelaunch seals, one-shot claims and fresh authorizations. Prior-consumed
  evidence is never retried or re-run; the D2 evidence directory is
  retained as a consumed record.
- **No wider-system claims.** No P07/P08 service, delivery, OPEX, ROI or
  corridor claims follow from this clear; the staged consumption of a
  road on tile 46769 is future, separately authorized work.
- **Launch initiator.** This document records on-disk evidence only; it
  does not attribute the launch to any actor. The signature in the
  candidate's `AUTHORIZATION.json` verifies under the production operator
  public key, which by design no agent-run code holds or uses.
