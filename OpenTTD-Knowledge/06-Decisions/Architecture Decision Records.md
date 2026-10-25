---
title: "Architecture Decision Records"
type: decision
status: current
updated: 2026-10-25
tags:
  - openttd
  - decisions
---

# Architecture Decision Records (ADR)

Lightweight ADR practice for this project. A decision is *recorded* only when the source
documents state it. When a future decision is made, add an entry to [[06-Decisions/Decision Log]]
using the template below (or promote a dated statement from a new source document).

## How decisions are recorded here

- **A.** One ADR = one decision. Immutable once recorded: a replacement decision gets a
  new numbered record that supersedes the old one — with links both ways and the
  supersession date. History is never rewritten to match the latest opinion.
- **B.** Status field values: `accepted` (current rule), `superseded` (by which record),
  `proposed` (not yet authoritative). Dates reflect the linked source record.
- **C.** Non-decisions stay unrecorded (no speculative ADRs); open questions go to
  [[05-Planning/Blockers]] until decided.

## Record template

See [[90-Templates/Decision Record]]. Frontmatter shape:

```yaml
---
id: ADR-000
title: "…"
type: decision
status: accepted
date: 1970-01-01   # decision date recorded by the source
updated: 2026-10-22
source: ""        # repo path of the authoritative record
tags: [openttd, decisions]
---
```

## Accepted-record index

All currently accepted rules from project history are summarized in
[[06-Decisions/Decision Log]]; the individual records there are the ADR entries. Two
umbrella records dominate the architecture and are worth reading first:

1. **Python owns optimization; GameScript stays a thin executor** — the entire
   P01–P08 boundary design. (Root: `docs/specs/planning-executor-boundary.md`, CONTEXT
   §§5–7, 21.)
2. **One-shot operator-authorized native attempts with immutable evidence** — the
   execution/evidence ceremony. (Root: AI_HANDOFF, EVIDENCE_INDEX, offline-evidence freeze
   spec.)

The 2026-10-22 D4 restage decision (Option C, split-run-B at staging time inside the
unchanged per-op ceiling, schedule-version binding) is recorded as **ADR-011** in
[[06-Decisions/Decision Log]] with its offline implementation scope (E22).

The 2026-10-24 delegated decision on the six temporal P08 tiles (save-instant census
authoritative for their tree-lifecycle deltas, planning evidence only, fail-closed
application layer, no P08 binding) is **ADR-012** in [[06-Decisions/Decision Log]]
(source: `docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md`).

**Accepted (2026-10-25):** **ADR-013** adopts native `IsBuildable` semantics
for exactly the 19 definitional `UNKNOWN_OCCUPANCY` tiles in the derived layer,
mapping them to `TERRAIN_MODIFICATION` under explicit operator authorization.
It is separate from ADR-012
(`docs/handoff/2026-10-25/adr-013-p08-native-isbuildable-definitional-semantics.md`).
The base ledger keeps the 19 as UNKNOWN, the derived counts become
339/63/29/19/0, and the separate combined rebinding computes
`p08_binding.allowed: true` for planning classification only. P08 is **not**
complete (`p08_complete: false`) and the fusion gate remains **CLOSED**.


**Accepted (2026-10-25):** **ADR-014** records an explicit, fail-closed
supersession of the 2026-10-08 `CONTEXT.md` authority pin. The historical
manifests and bytes stay frozen and unmodified; one operator-authorized record
scopes only the exact path/digest transition, and the base
`validate_protection` contract remains unchanged
(`docs/handoff/2026-10-25/context-authority-pin-repair.md`).
