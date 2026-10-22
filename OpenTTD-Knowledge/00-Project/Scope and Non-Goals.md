---
title: "Scope and Non-Goals"
type: project
status: current
updated: 2026-10-22
tags:
  - openttd
  - scope
---

# Scope and Non-Goals

**Sources:** [[99-Source-Documents/CONTEXT]] §23 (Non-Goals for Initial Proof) and known
limits (README "Known limits", `docs/specs/planning-executor-boundary.md` §3). Dated
limitation text describes the milestones it was recorded for; check each claim's date.

## In scope (current product)

- Stable fixed playable demo on OpenTTD 15.3 (default) and an opt-in bounded Random World
  mode at 256×256 only.
- Bounded P08 road-candidate generation from admitted native observations + supplemental
  facts; P05 CP-SAT selection over **supplied** candidates.
- One encrypted AdminPort connection per attempt; thin GameScript execution under
  `GSCompanyMode`; independent readbacks; receipt replay; P07 reporting; complete cleanup.
- Bounded native construction ceremonies (clearing, terraforming, road/station/depot) with
  one-shot claims — the D-milestone chain.
- Fixed Scenario is the default; Random World is explicitly opt-in.

## Explicit non-goals (initial proof / current demo)

```text
maximum performance
large maps (fixed demo scenario / random world is 256×256 only)
full network extraction
async command batching (GSAsyncMode is not the default; see CONTEXT §12)
multiplayer production deployment
complete transport-mode support
all vehicle types
all OpenTTD versions (target is 15.3; 13.4 is historical only)
BaNaNaS / Online Content publishing
GameScript public distribution
```

BaNaNaS is an optional future distribution layer only.

## Not supported / not verified (do not assume)

- Arbitrary-world road feasibility: no arbitrary slopes, clearing, bridges or tunnels;
  P08 is bounded flat-land routing with explicit budgets; mixed terrain needs explicit
  bounded contracts ([[99-Source-Documents/TASKS]] item 5).
- Direct player control of the Python-operated company is unsupported (the graphical
  client is a spectator).
- Concurrent network throughput, paid shared-asset reuse, recurring profitability:
  unproven (serial batches only).
- Full OPEX and net profit/ROI: UNKNOWN — never invented from revenue.
- Rail/air/water delivery: outside the demonstrated native MVP.
- Whole-world extraction: P08 is not an arbitrary-world extractor; production
  completeness means exact produced-pair coverage only.

## Evidentiary rule that governs scope claims

A status may only be claimed within the exact scope supported by evidence. Passing tests,
existing code, a prepared candidate, or an AI's assertion never upgrade a status
([[07-Reference/Status Definitions]]). Controlled/offline results never prove native
runtime behavior; OpenTTD 13.4 results never prove 15.3 compatibility.
