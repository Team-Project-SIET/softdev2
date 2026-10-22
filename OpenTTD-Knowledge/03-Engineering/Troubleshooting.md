---
title: "Troubleshooting"
type: engineering
status: current
updated: 2026-10-22
tags:
  - openttd
  - engineering
  - troubleshooting
---

# Troubleshooting

**Source:** [[99-Source-Documents/README]] "Troubleshooting" + retained records. Every
rule below is fail-closed oriented; do not bypass a gate to make something pass.

## Setup / environment

- **Pinned executable/assets mismatch:** check the exported paths and SHA-256 values
  ([[03-Engineering/Runtime and Environment]]). Keep the distribution's bundled files
  together; do not substitute a system binary.
- **uv cannot write its cache:** export writable paths, e.g.
  `UV_CACHE_DIR=/tmp/softdev2-uv-cache`, `UV_TOOL_DIR=/tmp/softdev2-uv-tools`.
- **Missing retained evidence in a fresh clone:** some tests require ignored retained
  files; absence is UNKNOWN — do not synthesize replacements (REPRODUCE).
- **Port/process ownership failure:** another matching runtime or live endpoint blocks
  preflight. Stop only a process you own; never bypass the ownership gate.

## Native run failures (immutable outcomes)

- **`NO_NATIVE_FEASIBLE_OD`:** inspect `result.json` and the inspection response.
  Versioned failure counters distinguish absent pairs from rejected pairs and report the
  first rejecting gate. Attempt 2 rejected all layouts on topology/footprint; `--demo`
  supplies genuine flat terrain without weakening those checks.
- **`quote` rejection or failed purchase:** read the native response. Vehicle purchase is
  tested only after the owned depot exists; initial admission reserves the native engine
  price; funds and native command-cost checks still apply.
- **Frozen source changed:** the prepared attempt is stale. Do not rewrite its seal.
  Restore the exact prepared source, or discard only that unconsumed preparation and
  create a fresh attempt under the applicable authorization policy.
- **Window exhaustion or readback mismatch:** a failed/inconclusive attempt — not proof
  of delivery or path blockage. Inspect the retained phase response and save.
- **Script died:** read `stderr.log`. Runtime script errors are reported separately from
  cleanup failures; a disposal-recovery record never changes the original failure record.
- **Native gate failures (fail-closed semantics to expect):**
  - A zero-cost native refusal in corridor admission is **terminal** — never trigger a
    build command (E20).
  - A failed native road command may still have built pieces; world state after failure is
    explicitly uncertain — no compensating mutation exists (E20).
  - The health vocabulary treats OpenTTD 15.3's `which is no longer available` save-load
    fallback as always fatal; `[S]`-severity lines are fatal; the dummy-AI death is exempt
    only under the exact three-line + adjacency condition, once (E15).
- **Consumed attempts are consumed:** contract runners exit 1 on every
  failed/halted/pre-verified state and never retry; retries need a new reviewed candidate
  and fresh authorization.

## Protocol / wire

- **`TransportTimeout` on page 1 + stderr markers** in classification capture: the
  fail-closed design intentionally surfaces save-load GameScript resolution problems —
  see E14 (consumed failure, no `Load()` hook) and E15 (repair: stage the stored AI
  package; probes are byte-verified).
- **Duplicate/surplus/stale/malformed exchange responses:** refused by design
  (schema-2 dispatch keyed `(request_id, region, cursor)`; E13).
- **Oversized readings:** any response exceeding the contract's `Guard()` bounds is a
  refused frame (E20).

## Data / reporting

- **P07 shows a FAILED terminal in insights:** correct behavior — analysis output keeps
  failed native terminals visible (REPRODUCE addendum). No native relabeling.
- **Baseline suite failures:** the two protected-authority tests + one architecture test
  fail by design until the CONTEXT.md authority-pin conflict is resolved with explicit
  authorization ([[03-Engineering/Testing Strategy]], [[04-Evidence/Evidence Preservation]]).
- **Missing OPEX/profit columns:** they are UNKNOWN, not zero. Full OPEX, net profit and
  ROI never get invented values (README, AI_HANDOFF financial boundaries).

## If something here disagrees with the repo

The working tree wins for operational state; then date-stamp the correction and update
the relevant [[00-Project/Current Status]] entry — without editing historical evidence.
