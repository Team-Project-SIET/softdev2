---
title: "Architecture Decision Records"
type: decision
status: current
updated: 2026-10-22
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
