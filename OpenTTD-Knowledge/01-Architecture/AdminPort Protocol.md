---
title: "AdminPort Protocol"
type: architecture
status: current
updated: 2026-10-22
tags:
  - openttd
  - architecture
  - adminport
---

# AdminPort Protocol

**Sources:** [[99-Source-Documents/CONTEXT]] §6, §10–§13, §18; retained records E12/E13,
D4 staging record E20 (wire contract v4). Transport implementation:
`app/simulation/openttd/secure_admin.py`, `gamescript_transport.py`.

## Transport and security

- One **encrypted** AdminPort session per attempt (X25519; credentials removed after
  cleanup). Historical revision banner observed: revision `15.3`, seed 17, 256×256,
  `start_day 712223` (E17/E19 welcome identity).
- The attempt model is one launch + one connection, zero retries, zero reconnects.
  Failure closes without retry and retains partial evidence.
- Request IDs must match the staged plan; the wire responder enforces duplicate/surplus/
  stale/malformed rejection fail-closed (E13).

## Packets and updates (as catalogued in CONTEXT)

Protocol concepts:

```text
ADMIN_PACKET_ADMIN_GAMESCRIPT      Python → engine → GSEventAdminPort
ADMIN_PACKET_SERVER_GAMESCRIPT     GameScript → AdminPort client (via GSAdmin.Send)
ADMIN_UPDATE_GAMESCRIPT            subscription enabling the GameScript channel
ADMIN_PACKET_ADMIN_RCON            remote console (future automation; verify commands first)
```

Useful subscriptions (CONTEXT §13):

```text
ADMIN_UPDATE_DATE
ADMIN_UPDATE_COMPANY_INFO
ADMIN_UPDATE_COMPANY_ECONOMY
ADMIN_UPDATE_COMPANY_STATS
ADMIN_UPDATE_CONSOLE
ADMIN_UPDATE_CMD_NAMES
ADMIN_UPDATE_CMD_LOGGING      ← especially relevant for controlled real-game proof
ADMIN_UPDATE_GAMESCRIPT
```

## Initial transport proof (first milestone, proven)

```text
Python Admin client → ADMIN_PACKET_ADMIN_GAMESCRIPT → OpenTTD 15.3
→ GSEventAdminPort → Bridge GameScript → GSAdmin.Send(...) → Python ACK correlated by request_id
```

Success criteria 1–6 are recorded in CONTEXT §22. No game-world mutation is in scope of
that proof. This round trip is proven; the planner/executor acceptance gates are separate.

## Message shape and size discipline

```json
{
  "type": "command_result",
  "request_id": "p08-000123",
  "status": "ok",
  "object_id": 42
}
```

- Engine-side limit: `GSAdmin.Send` JSON ≤ **1450 bytes** — design small messages, chunk
  large snapshots. Do not assume an equivalent inbound limit without evidence.
- Project working bounds (recorded per contract): classification pages ≤ 508 B with page
  budget 103 and census total 52,324 B; D4 requests ≤ 512 B, responses ≤ 640 B; tile
  replies exactly 19 integers ≤ 512 B.
- World-state extraction is paginated: `map_info`, `industries page=k`,
  `stations page=k`, `vehicles page=k`, `tiles region=x1,y1,x2,y2` (CONTEXT §9).

## Correlated ACK (P03 lineage → current)

Correlated ACK is a committed OpenTTD-15.3 capability (CONTEXT §20): every command
carries its `request_id`; responses are matched by identity key
(`(request_id, region, cursor)` for schema-2 classification; plan digest for
mutation ceremonies). Duplicate keys are rejected fail-closed.

## Command protocol lifecycle

```text
COMMAND → ACCEPTED → VALIDATED → EXECUTED → VERIFIED → COMPLETED
failure states: REJECTED | FAILED | TIMEOUT | DUPLICATE
```

No wall-clock sleeps as proof of completion — explicit acknowledgements only.

## Wire style of the D-ceremony contracts (v4 example)

The inspection request presents the **prelaunch seal**; the command request presents the
same seal; the independent verification read presents the **admitted intent digest**;
observation-only route reads carry the seal as pure observation. Every response exceeding
`Guard()` numeric bounds is refused (E20). The v1 torn-envelope convention and
identity-read precedence are retained for bytes recorded under older contracts (E12).

## RCON

`ADMIN_PACKET_ADMIN_RCON` may later drive game/server lifecycle automation (save/load,
console inspection, script management, orchestration). Do not assume a console command
exists until verified against 15.3 docs/source.

## Related

[[01-Architecture/Data Flow]] · [[01-Architecture/OpenTTD Integration]] ·
[[90-Templates/Experiment Record]] (per-attempt exchange manifests)
