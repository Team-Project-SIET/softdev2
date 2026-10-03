# Software requirements reference

This file is an index to the current authoritative project specifications, not a
standalone replacement SRS or a new set of requirements.

The project goal is transport network and infrastructure optimization evaluated
in OpenTTD. Current experiments compare pinned external AI policies; the
repository-owned network optimizer and construction executor remain absent.
OpenTTD handles simulation and lower-level vehicle pathfinding. Legacy operational
shipment CVRP and physical packing code have been retired; historical specification
references retain the prior design context.

## Authoritative specifications and implementation context

- [Current architecture and project status](../README.md#current-architecture-and-project-status):
  implemented experiment path, planning boundary, missing integration and history.
- [Production realtime OpenTTD telemetry specification](specs/realtime-openttd-telemetry.md):
  production runtime/observation requirements. The [T01–T18 ticket definitions](specs/realtime-openttd-telemetry-ticket-plan.md)
  record delivery boundaries; the specification takes precedence over summaries.
- [P01 planning/executor boundary](specs/planning-executor-boundary.md): schema v1
  and target responsibilities. P02 implements contracts/validation, P03 implements
  transport/acknowledgement and P04 completes observation; target construction and
  plan-attributed evaluation responsibilities are not implemented by those slices.
- [P03 runtime-world identity and proof coverage](planning-runtime-world-identity.md):
  current Attempt #6 status and its limits.
- [Production smoke evidence](live-production-smoke.md),
  [failure matrix](live-failure-matrix.md) and
  [outcome recovery](live-outcome-recovery.md): retained evidence and operational
  boundaries. Historical attempt entries retain their original status.

Use current code and completion history to determine implemented capabilities;
use the specifications for requirements. This index defines no new roadmap,
T-to-P mapping or P05.
