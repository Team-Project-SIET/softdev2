# Continuation tasks

This handoff authorizes read-only review and offline controlled verification only.
It does not authorize implementation changes, runtime preparation that overwrites
existing state, launches, AdminPort connections, reloads, or evidence modification.
Use the status definitions and evidence IDs in [AI_HANDOFF.md](AI_HANDOFF.md).

1. **Next authorized task: independently review Q2 readiness offline.** Read
   `docs/capacity-experiment.md` (especially Q1 failure/Q2 repair),
   `app/simulation/openttd/proof/canonical_fleet.py`,
   `app/simulation/openttd/proof/road_mutation.py`,
   `app/simulation/openttd/freight_delivery_package/canonical.nut`,
   `tests/validate_canonical_squirrel.py`, its two `tests/support/` helpers,
   `tests/test_native_save_path.py` and `tests/test_canonical_fleet_driver.py`.
   Compare source/package/helper hashes with the retained suspension report and
   Q2 PRELAUNCH, without changing either. Run the controlled commands in REPRODUCE
   into fresh outputs. Acceptance: 47 focused tests pass; all seven VM cases have
   their expected outcomes; Q1/Q2 frozen bytes unchanged; no launches/connections;
   report remaining blockers and exact package correspondence. A mismatch is a
   blocker, not permission to reseal. Full offline readiness is not established by
   the 47 tests alone. Do not claim canonical save or native construction success.
2. **Before requesting a native decision:** inspect Q2 public PRELAUNCH, source
   archive, suspension provenance, runtime/content hashes, effective gameplay
   settings, one-shot claim absence, budgets, endpoint reservation and cleanup
   ownership. Verify the pending workspace has not become stale; do not consume
   a claim or expose its credential. Acceptance: a concrete reviewable readiness
   report identifies exact inputs and any portability/staleness blockers. This is
   a review task; preflight may inspect local process/socket state and is optional,
   not needed for this handoff. Do not run it without reading its implementation.
3. **Requires new explicit authority: Q2 native creation.** Exactly one launch of
   `canonical-fleet-create-q2`, no reload or monitoring. Acceptance: build three
   original services without dispatch; exactly three stopped empty depot vehicles
   with two correct orders each; full native map/industry/production/infrastructure,
   ownership, finances, policy/date/timekeeping readback; paused save bracketed by
   equal semantic observations; canonical save hash/provenance; independent replay;
   reaped process, closed session/listeners, removed credential and disposed owned
   workspace. Retain partial evidence and stop if any gate fails. No retries.
4. **Requires separate authority after successful creation:** fresh-process
   `canonical-fleet-reload-q1`. Acceptance: load exact frozen bytes without world
   reconstruction, stay paused before world/economy movement, independently prove
   full correspondence and script heartbeat; native paused S2 fourth-vehicle test
   plus independent receipt/readback without unexplained cash/date/state drift;
   no overwrite of canonical save, no dispatch/monitoring, complete cleanup.
5. **Later, separate authority per arm:** matched fresh A and B, optional C.
   Acceptance: common verified canonical source, runtime/content/settings/bridge,
   identical common dispatch boundary and telemetry cadence, original services
   unchanged, only receipted extra vehicle/CAPEX differs; five-year bounded evidence,
   annual target/network delivery and network revenue deltas, residual accounting
   and uncertainty labels. Attempt 19 is context, not matched control. Attempt 20
   stays unused until qualification and a separately reviewed experiment seal.
6. **Parallel future backlog, no runtime authority:** review P08 multi-page/native
   retention and two-sweep contracts (E12), then request scoped implementation work
   if desired. Acceptance must cover exact pagination/terminal coverage, coherence,
   same-session lineage, aggregate budgets, independent retained verification and
   cleanup. A single-page acceptance writer cannot silently certify multi-page work.

Unresolved defects/limits: native industry construction and diagnostic saving after
Q1 repair are unqualified; native reload and paused intervention are unqualified;
historical terrain offline acceptance lacks 13 canonical inputs; original audit
matrix unavailable; exact expense categories, actual vehicle OPEX, per-service
revenue, profit/ROI and unexplained cash movements remain UNKNOWN where APIs do
not supply evidence. Do not turn these limitations into invented historical facts.
Full current-tree test/lint/typecheck health is UNKNOWN beyond handoff checks.
