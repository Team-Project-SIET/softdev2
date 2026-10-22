# D3 Native Terraforming — close-out handoff

Status: **D3 COMPLETE — all three candidates CONSUMED, all three receipts
`RECEIPT_VERIFIED` under the read-only production replay verifier; one-shot
claims CONSUMED; evidence preserved byte-for-byte**

Predecessor record:
[d3-native-integration-preflight-preparation.md](../2026-10-21/d3-native-integration-preflight-preparation.md)
("read-only preflight PASS ×3; awaiting the ONE fresh operator signature per
candidate"). This document closes that record for the whole D3 chain. The
Milestone D3 proposition — after a deterministic chain of two bounded operator-
authorized clears, one operator-authorized native launch performs the sixteen
compiled S-corner raises and the independent per-operation readbacks prove each
native state change, halting the phase with a preserved prefix on any failure —
is **PROVEN** for the consumed attempts below.

No tile outside the compiled specification was touched, no second launch or
connection was made, and no Git stage/commit/push/reset/clean/stash was
performed for this work. All three evidence directories are preserved
byte-for-byte (their own SHA-256 manifests re-verified, §7).

## 1. What happened — factual record

**The record-writing session did NOT initiate any launch.** It signed no
authorization and executed no `run` command for any candidate. On its next
read-only state check each of the three claims was already consumed. What
follows are on-disk facts and the verification results of the consumed
attempts; who signed each authorization record is not asserted — the records
verify under the production operator anchor (§6) exactly as staged in the
preflight handoff.

## 2. The three consumed attempts

| Candidate directory | Attempt | Operation | Tile pin | Result | Cost |
| --- | --- | --- | --- | --- | --- |
| `artifacts/experiments/d3-clearing-native-candidate-1/` | D3-CLEARING-1 | `CMD_LANDSCAPE_CLEAR` (tree → clear) | 45999 (175,179), TREES, flags 9, elevation 2, slope 0, unowned, census p025 sha `26dae90c…4da019` | `NATIVE_STATE_VERIFIED` | £30 |
| `artifacts/experiments/d3-clearing-native-candidate-2/` | D3-CLEARING-2 | `CMD_LANDSCAPE_CLEAR` (tree → clear) | 49326 (174,192), TREES, census p063 sha `b328c57d…302b1` | `NATIVE_STATE_VERIFIED` | £45 |
| `artifacts/experiments/d3-terraform-native-candidate-1/` | D3-TERRAFORMING-1 | 16 × `CMD_TERRAFORM_LAND` (S-corner raise, direction up, mask `0x2`) | hosts 48558, 48559, 48814, 48815, 49070, 49071, 49326, 49327, 49582, 49583, 49838, 49839, 50094, 50095, 50350, 50351 | `NATIVE_TERRAFORM_VERIFIED` (`PHASE_COMPLETE`) | £3,382 |

Each candidate: status `verified: true`, `returncode: 0`, `command_accepted`,
`state_changed`, exactly **1 launch / 1 connection** (encrypted X25519,
revision 15.3, seed 17, 256×256, `start_day 712223`), 0 retries, 0 reconnects.
The clearing candidates made 4 requests each (`read-0`, `inspect-1`, `clear-1`,
`read-2`); the terraforming candidate made 144 requests (16 operations × 9:
inspect + 3 admission neighbor reads + the prelaunch-sealed command + 4
intent-scoped verification reads).

## 3. Receipt-bound save world lineage (complete chain)

The staged chain bound every stage's source world to the predecessor's
receipt-verified output; the verify replay re-derived all of it.

| Stage | before-save SHA-256 | after-save SHA-256 |
| --- | --- | --- |
| retained Seed 17 source world (`before.sav`) | — | `79722b88f3067a9c806a7477604f5601596c36d4c11852a08c0699620bf636fe` |
| D3-CLEARING-1 (`retained before.sav` → after) | `79722b88…36fe` | `63e9b37d05f81a28db854531b00f29d0c49ba6f9597bc6ea02e17f0de490a354` |
| D3-CLEARING-2 (clearing-1 after → after) | `597583fea4af0b88f386ce16c07a19d9bdc3a58c59f40ea30f56f22c83b29a50` | `fd0f9fc27b5c124f16db29f4e807cc3fde201a5436274a3fed05dc646322244d` |
| D3-TERRAFORMING-1 (clearing-2 after → after) | `1422109a6ba4da4f13e101e16c9942fcd91b24e454b1063d4e2e59c6250230ba` | **`fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`** |

Notes.

- Each stage's `session-before.sav` is byte-identical to the predecessor's
  bound after world (the chain check in the verify replay); D3-TERRAFORMING-1's
  `session-before.sav` digest equals the record above exactly.
- D3-TERRAFORMING-1 additionally retained an `after-diagnostic.sav`
  (sha `2942b7787528b9cfff9bd844fa123f205ec1b4fa33272d90d82e7d56c7255b07`),
  distinct from `after.sav` and never substituted for it: the receipt-bound
  authoritative output remains `after.sav` (`fbebef54…d59e`).
- **Milestone D4 source world**: the receipt-bound D3-TERRAFORMING-1
  `after.sav` (`fbebef54…d59e`) is the authoritative verified post-D3 world.

## 4. Native cost and finance reconciliation

Company 0 cash: **£500,000 → £496,543**.

| Command | Native cost |
| --- | --- |
| D3-CLEARING-1, `CMD_LANDSCAPE_CLEAR` tile 45999 | £30 |
| D3-CLEARING-2, `CMD_LANDSCAPE_CLEAR` tile 49326 | £45 |
| D3-TERRAFORMING-1, 16 × `CMD_TERRAFORM_LAND` (247, 217, 217, 202, 202, 202, 217, 202, 217, 202, 217, 202, 217, 202, 217, 202) | £3,382 |
| Total | **£3,457** |

500,000 − 30 = 499,970 → − 45 = 499,925 → − 3,382 = **496,543**, confirmed by
the last-in-order readback funds (`verify-15-0` … `verify-15-3`: `funds
496543`). Each terraforming command's cost equals its inspect-time tested
quote (`native_quote`), GSAccounting command-scoped cost and company cash
delta agree per operation, and any mismatch fails the receipt.

## 5. Compiled-file lineage and independent geometry verification

The staged terraforming schedule is the compiled levelling specification
(`tests/test_p08_terraform.py` pins): levelling proposal digest
`4d698a9d748922efac8041af909428cd91d3c26409e30f2e698c62dfef8d644c`, compiled
specification digest
`9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d`. The
verify replay re-compiled the specification offline (identical digests), then
re-bound:
- the 16 staged schedule entries to their exchanged request bytes (prelaunch
  seal `edb6b34c6597d146be766ca42728da816d27eaaf40dcb51eb779dd13e30cff9e` on
  inspect/command correlation; per-intent digests on the 64 verification
  reads);
- each admitted intent to the exact retained response digest and the
  session-before save digest;
- the 144 outbound frames to the 144 retained request files (exact byte
  equality, unique ids, frame-ordering: every response after its request).

**Independent geometry result — 0 mismatches.** Folding the compiled per-op
corner shifts produces the post-phase projected corner heights for the 27
raised-band tiles; the last-in-order retained readbacks (the final native
observation of every touched tile) agree on every tile, including each
*untouched* neighbor's unchanged encoding.

The verified post-D3 geometry of the 24-tile corridor
`45748 (180,178) → 45747…45743 (179…175,178) → 45999 (175,179) → 46255 … 50351
(175,196)`:

| # | tile | (x,y) | role | pre-D3 minh/slope/class | post-D3 native readback |
|---|---|---|---|---|---|
| 0 | 45748 | (180,178) | planned pickup stop | 2/0/CLEAR | unchanged (no raise touches it) |
| 1–5 | 45747, 45746, 45745, 45744, 45743 | (179…175,178) | planned road (5 tiles); 45743 is the future depot-front | 2/0/CLEAR | unchanged |
| 6 | 45999 | (175,179) | planned road; cleared by D3-CLEARING-1 | 2/0/TREE → | CLEAR minh 2 slope 0 (clearing-1 receipt) |
| 7–15 | 46255…48303 | (175,180…188) | planned road | 2/0/CLEAR | unchanged |
| 16 | 48559 | (175,189) | planned road | 1/9/CLEAR | minh 2, slope 0 (2,2,2,2) |
| 17–22 | 48815, 49071, 49327, 49583, 49839, 50095 | (175,190…195) | planned road; 50095 the delivery-stop front | 1/0/CLEAR | minh 2, slope 0 (2,2,2,2) |
| 23 | 50351 | (175,196) | planned delivery stop | 1/0/CLEAR | minh 2, slope 0 (2,2,2,2) |

Untouched flank band (last-in-order native reads, all flags 1 = CLEAR, owner −1,
`industry null`): 48558 (174,189) slope 11; 48560 (176,189) and 48816, 49072,
49328, 49584, 49840, 50096, 50352 (176,190…196) slope 12; 48814, 49070, 49326,
49582, 49838, 50094, 50350 (174,190…196) slope 3; and the southern guard row
50606 (174,197) slope 1, 50607 (175,197) slope 9, 50608 (176,197) slope 8 —
all still minh 1: exactly the 16 corner changes from the compiled S raises, no
shift beyond them, and no edge point moved by more than one step.

This establishes the D3 terminal fact for Milestone D4 planning: **the planned
road corridor is flat min-height 2, slope 0, classified CLEAR, unowned and
industry-free on all 24 tiles post-D3**, the only corridor tree (45999) was
cleared, and both compiled clear prerequisites are satisfied in one world.

## 6. Runtime, authorization and cleanup facts

| Fact | Value |
| --- | --- |
| binary | `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`, sha `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` |
| welcome | revision `15.3`, seed `17`, landscape `0`, 256×256, `start_day 712223`, dedicated |
| operator identity | fingerprint `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` (production anchor; claim + authorization records agree) |
| authorization re-verification (this close-out, read-only) | clearing-1 record sha-claim `4ac15b5f1a1db1859d92e2f625baea7e05469cc985aa50e8a38fc562716b6a77` BINDS; clearing-2 `43f8e8c9b8bc7cf44594e2a26c964636caaa8031c505bdc0cadfa395cf055045` BINDS; terraforming `d6b8eed2118e91b06b8c5602737b8a9ff3ae66dcdc0014bb7bbab8df2e8c15e4` BINDS |
| claims | one-shot (`d2-clearing-claim-authorization-v2`), `consumed: true`, `launches_allowed: 1`, `retries: 0` — all three |
| cleanup | `quit_requested`, `graceful_attempted`, `reaped: true` returncode 0, sockets closed, admin credential removed, port reservation released, workspace disposed, `remaining_processes: []`, `cleanup_error: []` — all three (pids 501370 / 505599 / 512439) |

## 7. Preservation verification performed for this document

- `sha256sum -c artifact-manifest.sha256` in all three candidate directories →
  every entry OK (28/28/387 files).
- Read-only production replay verification of all three consumed attempts via
  `.venv/bin/python -m app.simulation.openttd.proof.terrain_terraform_native
  verify <directory>`: D3-CLEARING-1 → `RECEIPT_VERIFIED` (after_digest
  `e1eecd006de39bd3…d98`, after-save `63e9b37d…a354`); D3-CLEARING-2 →
  `RECEIPT_VERIFIED` (after_save `fd0f9fc2…244d`); D3-TERRAFORMING-1 →
  `RECEIPT_VERIFIED` (`PHASE_COMPLETE`, 16/16 operations `NATIVE_STATE_CHANGED`,
  after-save `fbebef54…d59e`). No `run` command was executed; nothing relaunched.
- The pinned binary's SHA-256 re-checked live — unchanged.
- Independent wholesale geometry reconciliation (§5): 27/27 raised-band tiles
  agree, 0 mismatches, from the retained readback bytes only.
- No `openttd` process is running on the host; no claim remains consumable.

## 8. Honesty and limits

- **Strictly the compiled specification.** The proof covers exactly the two
  pinned tree tiles and the sixteen pinned S-corner raises in the retained
  Seed 17 world; anything beyond is not claimed. In particular no road, no
  stop and no depot was constructed — Milestone D4 is future, separately
  authorized work staged from the receipt-bound D3 after world.
- **Catchment/acceptance caution.** Post-D3 flatness, CLEAR classification and
  unowned ownership are verified facts for the corridor; *service* catchment
  and cargo acceptance at a future 1×1 truck stop are native facts only — the
  retained census observed `producer_count 1` (pickup anchor 45748, industry 0,
  cargo 1, `industry_covered`) and `industry_covered` for the delivery anchor
  (50351, industry 1) with `acceptance_eighths 0` measured at unplanned
  ground, so acceptance must be re-checked natively at construction admission
  and never inferred from terraforming success.
- **The consumed attempts are not portable to later milestones.** D4 gets its
  own attempt identifier, prelaunch seal, one-shot claim and fresh
  authorization; prior-consumed evidence is never retried or re-run.
- **Launch initiator.** This document records on-disk evidence only; it does
  not attribute the launches to any actor. Each candidate's
  `AUTHORIZATION.json` verifies under the production operator public key,
  which by design no agent-run code holds or uses.
