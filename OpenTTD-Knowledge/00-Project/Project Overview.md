---
title: "Project Overview"
type: project
status: current
updated: 2026-10-26
tags:
  - openttd
  - project
---

# Project Overview

**Source of truth:** [[99-Source-Documents/CONTEXT]] (goal, runtime target, codebase),
[[99-Source-Documents/README]] (product surface). This note condenses; it adds nothing new.

## Goal

Connect the existing Python logistics/planning system to **real OpenTTD 15.3** and allow
externally generated plans to be:

1. created by Python,
2. validated,
3. executed inside OpenTTD,
4. verified against actual game state,
5. returned as machine-verifiable execution evidence.

Use documented OpenTTD 15.3 APIs and engine behavior — not assumptions inherited from
older OpenTTDLab/OpenTTD 13.4 experiments (those remain historical regression baselines
only and cannot establish 15.3 compatibility).

## Target environment

```text
OpenTTD 15.3, Linux generic amd64
Python 3.14+ (this work used 3.14.6; uv-managed)
Pinned binary  sha256 276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c
Pinned OpenGFX 8.0 sha256 43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be
```

Local installation reference: `/home/fed/Downloads/openttd-15.3-linux-generic-amd64`
(set `OPENTTD_BINARY` on other machines). Environment details:
[[03-Engineering/Runtime and Environment]].

## Main codebase

- Repository: `https://github.com/Team-Project-SIET/softdev2.git`, working branch `devmodule2`.
- Project name (`pyproject.toml`): `logistics-optimizer`. Primarily Python.
- Technologies in use: Python, OR-Tools, SQLAlchemy, PostgreSQL/Alembic (optional research
  persistence), pytest, Ruff, uv, Docker Compose.
- Working rule: **do not rewrite unrelated planner/domain logic** when changing the OpenTTD
  integration; isolate/refactor the adapter/transport/executor boundary instead.

## Product shape (as implemented and documented)

- `app.openttd_demo` runs a fixed, stable playable demo (default) or an opt-in bounded
  **Random World** mode (256×256). [[03-Engineering/Runtime and Environment]] commands.
- P08 generates bounded road/network candidates from qualified observations and
  supplemental facts; P05 (OR-Tools CP-SAT) selects services into an `ExecutionPlan`;
  the freight compiler stages checked intents; the GameScript bridge executes them under
  `GSCompanyMode`; independent native readbacks and receipt replay verify the outcome;
  P07 produces planned-vs-actual reports. [[01-Architecture/System Architecture]].
- Evidence discipline: each native attempt is a one-shot, preflighted, operator-authorized
  event with retained receipts, manifests, saves and cleanup records. [[04-Evidence/Evidence Preservation]].

## Current state

See [[00-Project/Current Status]] and [[00-Project/Roadmap]]. Short version: the fixed demo
is VERIFIED natively; the canonical create/reload engineering is PROVEN; the P08→P05→execute
planner path has native proofs (Attempts 9/12/17 with historical scope); Random World
native execution remains blocked, though ADR-012/ADR-013 now allow the derived P08
planning classification (`p08_complete: false`, fusion gate closed); the D-chain of native construction ceremonies
has D2/D3 PROVEN and **D4 PROVEN for exactly the reviewed v3 scope** (four attempts
consumed; the first three ended incomplete — E21, E28, E32 — and identity
`D4-CORRIDOR-5` completed all seven v3 operations natively on 2026-10-26, E35). The authority-pin conflict is resolved offline (E26/ADR-014). `D4-CORRIDOR-4` was consumed exactly once on 2026-10-25: `op-00`–`op-05` built and read back (£4,004; £496,543 → £492,539), including the corner and both stops; `op-06` depot's 513-byte response exceeded the then-hard-coded 512-byte application limit and was rejected before parsing. Cleanup passed and the manifest is 80/80, but there is no `confirm-06`, receipt or authoritative after-save. Offline E33 corrects protocol 4's decode bound to 640 (version-one 512 unchanged); the retained frame now parses, but replay still refuses for missing durable confirmation. The follow-up identity `D4-CORRIDOR-5` — signed under the explicit 2026-10-26 operator authorization after every pre-signing gate was re-verified and the independent review returned PASS 20/20 — completed the same v3 schedule natively on 2026-10-26 (E35): all seven ops verified with quote-equal native costs (£496,543 → £492,149), `ROUTE_VERIFIED` 23/23, authoritative `after.sav` retained, cleanup certified, manifest 90/90, replay `RECEIPT_VERIFIED`. D4 is COMPLETE for exactly that scope; any next native step needs a fresh reviewed candidate and a fresh explicit operator authorization.

## Related

[[00-Project/Scope and Non-Goals]] · [[07-Reference/Important Paths]] · [[07-Reference/Glossary]]
