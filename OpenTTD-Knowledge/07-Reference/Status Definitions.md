---
title: "Status Definitions"
type: reference
status: current
updated: 2026-10-22
tags:
  - openttd
  - reference
  - statuses
---

# Status Definitions

The project's own vocabulary (AI_HANDOFF "Current evidence-backed state", CONTEXT
insert-header, EVIDENCE_INDEX). These are **project statuses about evidence**. They are
distinct from the vault's frontmatter `status` hygiene field (`current` = actively
maintained note; `frozen` = byte-for-byte source copy; `template` = template).

| Status | Meaning | Rules |
|---|---|---|
| **VERIFIED** | Supported by inspected retained reports — only within the exact scope the reports state | Not a fresh re-run; not broader than its record; never upgraded because tests pass or code exists |
| **PROVEN** | Historical retained native engineering evidence that carried its full gate chain at recording time (canonical Q3, D-milestones) | Unlike VERIFIED, the term marks an engineering proposition closed by consumed attempt evidence; scope rules identical |
| **CONTROLLED** | Offline tests, synthetic fixtures, or controlled validation | Never proves native runtime behavior; never proves source/save correspondence |
| **PREPARED** | Implementation or a candidate awaiting required authorization or native verification | e.g. `PENDING_AUTHORIZATION`; never counts as an accepted save, reload, or experiment |
| **PARTIAL** | Only part of the acceptance criteria has been established | E.g. native capture complete but fusion rejected; reconciliation semantics accounted but same-state not achieved |
| **FAILED** | A recorded failed attempt whose historical outcome must remain immutable | Never renamed, never buried, never retried to flip the status; failure records are learning assets |
| **UNKNOWN** | Facts not established by available evidence | Includes: unavailable tools, absent artifacts, unmeasured OPEX/ROI, missing canonical inputs. Record honestly; do not fill with assumptions |

## Hard rules

1. A status may only be upgraded by **new evidence consistent with its scope** — consumed
   one-shot attempts with receipts for native claims; fresh recorded controlled runs for
   controlled claims. Never by: tests passing, code existing, a candidate being prepared,
   or a previous AI claiming success.
2. Statuses are dated and scoped. "VERIFIED 2026-10-18 at world X" is not
   "VERIFIED" universally.
3. Native-phase success does not imply overall success (qualification Attempt 2: native
   SUCCESS/COMPLETED, overall FAILED before post-run verification failed).
4. Controlled pass + prepared candidate + authorization grant is still not `VERIFIED`
   (see E12→E16 lineage).
5. FAILED terminals stay visible in every derived artifact (P07 keeps FAILED terminals
   visible; insights never relabel).
6. UNKNOWN never becomes zero or a best guess ("unknown expenses never become zero or a
   claimed net return").

## Where it matters most

- [[00-Project/Current Status]] — per-area table.
- [[04-Evidence/Native Verification]] — VERIFIED/PROVEN with exact artifacts.
- [[04-Evidence/Controlled Tests]] — CONTROLLED inventory.
- [[04-Evidence/Failed Attempts]] — FAILED, immutable.
- [[02-Milestones/Pending Milestones]] — PREPARED/PARTIAL items.
