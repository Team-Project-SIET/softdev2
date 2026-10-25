# D4 candidate-3 cleanup remediation verification

Status: **`D4-CORRIDOR-3` credential removal and workspace disposal are
verified. The historical execution outcome is unchanged: the candidate remains
consumed exactly once, `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`status: FAILED_CLEANUP`; no authoritative `after.sav` or `receipt.json` exists.
Milestone D4 remains `INCOMPLETE (native)`.**

Date: 2026-10-25. Scope: read-only, non-secret verification of the reported
post-run cleanup remediation plus documentation reconciliation. No candidate was
created, signed, launched or consumed by this record. No credential value was
read, printed, copied or modified.

Predecessors:

- [candidate-3 outcome](d4-corridor-native-candidate-3-outcome.md) (E28)
- [candidate-3 preparation](d4-corridor-native-candidate-3-preparation.md) (E27)
- [`op-03` root cause](d4-corridor-op03-root-cause.md) (E29)

## 1. Remediation boundary

The 2026-10-25 post-run close-out recorded a failed cleanup gate: the immediate
post-quit endpoint observation caught the closing connection in TCP state 5
instead of `TIME_WAIT`, so cleanup aborted before workspace closure and the
isolated operational credential remained in the candidate workspace.

The remediation reported afterwards removed that credential and disposed of the
workspace. It did **not** claim a successful full cleanup certification, a
verified receipt, native execution success, or a change to the consumed
attempt's historical outcome. This record verifies only those disposition facts
and the integrity of the retained evidence that remains.

## 2. Verified cleanup fields

[`cleanup.json`](../../../artifacts/experiments/d4-corridor-native-candidate-3/cleanup.json)
now contains:

| Field | Verified value |
| --- | --- |
| `events` | `["quit_requested", "reaped"]` |
| `graceful_attempted` | `true` |
| `quit_command` | `quit` |
| `pid` | `99654` |
| `reaped` | `true` |
| `returncode` | `0` |
| `remaining_processes` | `[]` |
| `cleanup_error` | `[]` |
| `credential_removed` | `true` |
| `workspace_disposed` | `true` |
| `verification_error` | **retained verbatim** — the historical `Live or ambiguous endpoint socket` record naming local port `36515` / remote port `40094` in TCP state `5` |

`cleanup.json` still has **no `sockets_closed` field**. The historical
verification error is preserved exactly; the remediation added only the two
disposition observations. Therefore the cleanup gate's original failure is not
erased, and read-only replay still refuses with
`ValueError: halted attempt cleanup incomplete`.

`cleanup.json` bytes: `52e1055c3171a108d7aa4016ab381634f686e44826e28502093ac37b48463d8f`
(469 bytes, mtime 2026-10-25 21:34:04 local).

## 3. Workspace-disposal and non-secret checks

| Check | Result |
| --- | --- |
| Workspace path `isolated/openttd-15.3-aghwu0j0` | **absent** |
| Candidate-3 `isolated/` directory | present and **empty** |
| Any `secrets.cfg`, `private.cfg` or `openttd.cfg` under candidate-3 | **none found** |
| OpenTTD process referencing the workspace | **none found** |
| Listener on game port `33725` or Admin port `36515` | **none** |
| `result.json` status / verified | unchanged `FAILED_CLEANUP` / `false` |
| `result.json` launches / connections / requests | unchanged 1 / 1 / 10 |
| Built operations | unchanged `op-00`, `op-01`, `op-02` |
| Halt | unchanged `op-03`, `ValueError: native READY admission with positive tested cost required` |
| `CLAIM.json` | unchanged, `consumed: true`, `launches_allowed: 1`, `retries: 0` |
| `AUTHORIZATION.json` | unchanged sha-256 `5484cdc1…3be705e` |
| Retained `session-before.sav` | unchanged `a3e6b510…69cc5c` |
| Retained `after-diagnostic.sav` | unchanged `b52d0ecf…9d970b`; still **not** an authoritative save |
| `after.sav` / `receipt.json` | **absent** |

These checks confirm disposition and preservation. They do not certify the
original cleanup attempt, and they do not make `after-diagnostic.sav`
authoritative.

## 4. Manifest verification

[`artifact-manifest.sha256`](../../../artifacts/experiments/d4-corridor-native-candidate-3/artifact-manifest.sha256)
re-verifies **48/48 OK** with no missing, changed or extra listed entry. The
listed `cleanup.json` hash matches the remediated bytes above.

The manifest was regenerated after the remediation: its mtime is 2026-10-25
21:34:13 local, whereas the candidate's diagnostic copies were captured at
15:58. The pre-remediation manifest bytes and the pre-remediation `cleanup.json`
bytes are **not retained** in the candidate directory. The historical
manifest-check result is preserved separately in
`artifacts/diagnostics/d4-corridor-native-candidate-3-2026-10-25/manifest-check.log`
(48/48 OK at capture time), and the historical cleanup failure remains visible
in `verification_error` and `result.json`.

No other retained candidate file was rewritten by the remediation: the
documented digests for the prelaunch seal, authorization, claim, launch record,
saves, exchange pairs and result all remain unchanged, and the diagnostic
directory's own checksums still verify.

## 5. What this does not establish

- It does **not** upgrade `D4-CORRIDOR-3` to a verified attempt or a successful
  cleanup certification; `sockets_closed` is still absent.
- It does **not** create or reconstruct an authoritative `after.sav`, receipt,
  route read, or the unexecuted `op-03`–`op-07` evidence.
- It does **not** authorize reuse of the consumed identity, signing, a native
  launch, AdminPort access, save mutation or candidate consumption.
- It does **not** complete Milestone D4.

## 6. Files affected by this reconciliation

- `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-cleanup-remediation.md`
  (this record)
- `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md` — appended
  subsequent-event section
- `docs/handoff/2026-10-25/d4-corridor-op03-root-cause.md` — residual-remediation
  status appended
- `EVIDENCE_INDEX.md` — E30
- `docs/requirements-evidence-matrix.md` — cleanup-remediation status
- Relevant Obsidian notes and the synchronized
  `OpenTTD-Knowledge/99-Source-Documents/EVIDENCE_INDEX.md` copy

No candidate evidence, source, test, save, claim or authorization record was
edited by this record.
