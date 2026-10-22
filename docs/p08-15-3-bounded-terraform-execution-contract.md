# Bounded terraforming execution: D3 offline contract

## Scope and status

This document pins the offline execution contract for the bounded terrain
corner-operation phase (D3). It covers the compiled operation spec, the
wire-contract admission/execution/verification module, and the controlled
GameScript dispatcher package. Everything here was produced and validated
offline against the real Squirrel VM executing the shipped `main.nut`; no
OpenTTD launch, AdminPort session, staging area, native mutation, or claim
consumption happened. Native execution and final preparation stay gated on the
D2 security boundary, which remains owned by its own session.

Owned and reviewed files for this contract:

- `app/planning/p08_terraform.py` — proposal to spec compiler, digest pin,
  supplemental bridging, point-bounds and duplicate-clear rejections.
- `app/simulation/openttd/terrain_terraform.py` — request/readback/intent/
  expectation models, phase-admission, verification, phase-outcome.
- `app/simulation/openttd/terrain_terraform_package/main.nut` — controlled
  dispatcher: validation, stale guards, native commands, reply bounds.
- `tests/test_terrain_terraform.py`, `tests/test_p08_terraform.py`.

The reviewed Seed 17 proposal is preserved: `PINNED_SPEC_DIGEST` in
`tests/test_p08_terraform.py` pins
`9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d`, the exact
compiled 18-operation inventory ("CC" plus 16 corner raises); only
specification order and prerequisite bindings changed under review.

## Wire contract summary

One corner operation consumes nine wire exchanges: one `inspect`, three
correlated neighbor reads on the other directly sharing tiles, one
`terraform` command, and four independent post-state reads scoped by the
intent digest. Admission binds tile identity, corner, direction, company,
tested cost, admitted corner heights, and the prelaunch/source digests; the
dispatcher re-derives every admitted fact at execution time and refuses with
`STALE_ADMISSION` when anything drifted.

Disposition statuses are the pinned `company-terraform-receipt-v1` set:
`READY`, `NO_OP`, `RAISED`, `LOWERED`, `READ`, plus the failure set
`INVALID_COMPANY`, `INVALID_LOCATION`, `FORBIDDEN_CLASS`,
`OWNERSHIP_MISMATCH`, `UNSUPPORTED_NATIVE_FACT`, `REJECTED`,
`READBACK_MISMATCH`, `ALREADY_ATTEMPTED`, `COST_LIMIT`,
`INSUFFICIENT_FUNDS`, `STALE_ADMISSION`. A receipt carries the 24 pinned
keys including before/construction/after digests, the four independent
readback request ids, cost, cost category, and the verification verdict.

Response numeric bounds are enforced identically on both sides: the
dispatcher refuses funds below -2147483648 or above 2147483647, cost outside
`[0, 2147483647]`, and flags outside `[0, 32767]` before sending; the Python
readback models mirror the same `Field` bounds so a report the dispatcher
cannot produce is also not accepted in Python.

Request budget sizing follows the reviewed plan budget. The terrain budget
admits up to 32 corner operations (`MAX_TERRAIN_CORNER_OPS = 32`); at nine
exchanges each the dispatcher's accepted-request counter therefore stands at
296 (288 plus slack before dispatch). A smaller cap would strand a fully
budgeted plan mid-phase, so `max_requests = 296` is pinned next to that
rationale.

## Canonical execution order: clears hoisted

The compiler emits clearing operations first, then corner operations in the
proposal's `(tile, corner-kind)` order, regardless of the position the
proposal lists clears at. Rationale: any corner operation whose host or any
of its four sharing tiles still needs a clearing ceremony depends on that
clear; leaving a clear later than its dependent corner op would ask the
dispatcher to raise or lower terrain while the tree still occupies the
lattice. The review found exactly one such case in the pinned inventory
(shared tile 49326 held a tree and five corner operations depended on it),
and eight of the sixteen raises touch tiles whose own minimum shifts.

Compiler behaviors pinned with it:

- Required clearing prerequisites are bound over the host **and all four
  sharing tiles**; an unserved prerequisite rejects the spec with
  `MISSING_CLEARING_PREREQUISITE` naming the unserved tiles.
- `op_index` and `required_earlier_clearings` are remapped onto the hoisted
  order; consumers must read them from the compiled operation, not from list
  position assumptions carried over from the proposal.
- A second clear on the same tile rejects with `DUPLICATE_CLEAR_OP`; two
  attempts to run the D2 ceremony on one tile is a spec defect, not a retry.

## The minimum-shifting raise must verify

Raising a corner that is the tile's last minimum corner lifts the tile
minimum by exactly one and leaves the tile flat one step higher. The pinned
inventory forces this shape eight times (hosts 48559, 48815, 49071, 49327,
49583, 49839, 50095, 50351), so the dispatcher's raise post-check accepts
`min_height == admitted.min_height` **or** `min_height == admitted.min_height + 1`,
symmetric to the lowering direction. Reporting `READBACK_MISMATCH` here
would reject eight legal native commands. The runtime test drives this exact
shape on a controlled ridge world and pins the derived after-states of all
four watchers.

## Geometry and slope encodings

Corner-height derivation accepts the official `slope_type.h` corner-bit
constants. Connected-slope encodings (bit 0x20 and above) are rejected as
halftile encodings no corner command can produce. The steep bit requires
exactly three raised corners; steep masks with 0, 1, or 4 corner bits are
encodings the native command set cannot emit and fail closed with
`ValueError` rather than standing in for a native assertion.

Shared-point interior bounds are symmetric: a shared point may sit on the
last column or the last row of the census rectangle equally; the compiled
`shifts` are valid whenever the point itself lies inside the rectangle and
each watcher's corner is recomputed from the lattice, not assumed from
st offsets.

## Phase verification discipline

`terraform_phase_outcome` verifies recorded evidence only and never issues
requests. Every attempt must retain intent, admission evidence, neighbor
readbacks, the construction result, and the four independent readbacks; the
first failed attempt halts the phase, earlier receipts are preserved in
`completed`, later attempts are reported as `pending` labels, and the failed
attempt is recorded with `world_state="UNCERTAIN_AFTER_FAILED_COMMAND"` — a
failed native terraform may still have auto-cleared tiles or shifted other
geometry, and nothing claims otherwise.

Verification correlations enforced on the Python side: all evidence carries
the admitted company (`intent.company`) on the neighbor inspection reads and
the independent post-state reads; plans are scoped (`prelaunch_digest` for
admission reads, the intent digest for post-state reads); the construction
result must correlate on company/tile/corner/direction and cost must equal
the natively tested cost; funds reported by any independent read must equal
the construction result's funds.

## Controlled test world

The controlled stub mirrors only what the dispatcher touches: a flat margin
world, owner/flag overrides for classification paths, costing and funds
knobs, and the test-mode refusal knob set. Additional knobs are disabled by
default: `::host_ridge` seeds the minimum-shifting raise pre-state through
the same alias-consistent shift, and `::second_company` enables a second
valid company id so the foreign-company `STALE_ADMISSION` guard is reachable.
Both ship in `tests/test_terrain_terraform.py` only; the package source
carries no test-only branches.

## Review outcomes recorded here

The independent review of this contract reported two blockers; both were
reproduced, fixed, and pinned by test as described above (hoisted clears with
sharer-wide prerequisite binding; the minimum-shifting raise). Its request
budget finding (cap 160 versus 32 × 9 = 288 exchanges) is fixed by sizing
`max_requests` from the budget to 296. Remaining review minors were adopted
where they governed contract strength (steep completeness, funds/cost
bounds, company correlation on independent reads, symmetric shared-point
bounds, `StopIteration`-free expectation bridging) and skipped only where
they were presentation nits or graded unreachable in the single-company
controlled world.
