# Realtime OpenTTD telemetry — T01–T18 production foundation

**Status: implemented T01–T18 production telemetry/runtime foundation.**
The original ticket definitions below are preserved as historical scope and
acceptance criteria, not an active incomplete draft or instructions to rerun work.
Implementation history reaches T17 completion (`eca5a44`) with the accepted sixth
attempt in [the production smoke report](../live-production-smoke.md), then T18
prototype retirement (`5a7e5ee`). T18 removed the executable prototype and retained
reference material; the production T-series implementation remains current.

Older pre-T-series documents/scaffolding were cleaned up in `6b612fa`; this does
not make T01–T18 obsolete. P01–P04 are later planning/integration work, with P02
(`76e176c`), P03 (`7260f8c`) and P04 (`84ccb61`) following T18. No one-to-one T-to-P
mapping or P05 is defined. See [current architecture](../../README.md#current-architecture-and-project-status).

Source SHA-256 at planning: `d605200c4bf2a5240b4fbeb84372f8b603824e45e27b0342e8313db7c3b280dd`.

Sole implementation source of truth: [production specification](realtime-openttd-telemetry.md).
Repository: Team-Project-SIET/softdev2. Integration branch: devmodule2.
This document records the original ticket boundaries, not additional product requirements.
If a ticket summary and the specification differ, the specification wins.
The planning-time source digest above is historical provenance, not a current
completion ledger. Consult implementation history and retained proof reports for
completion evidence; the task definitions do not add requirements to the specification.

## Plan rules and sequencing

- Preserve the existing accelerated OpenTTDLab batch path in every slice. Use
  additive changes, compatible defaults and its existing regression tests.
- Use the user-confirmed ExperimentService/SimulationRunner test seam, with focused
  protocol fixtures and PostgreSQL tests. Controlled executables/peers verify
  lifecycle behavior without launching repeated real OpenTTD experiments.
- No production dependency on prototype runtime, private Lab launch functions,
  monkeypatches or executable rewriting. Fixtures/research may be retained exactly
  as the specification permits, with captured versus synthesized provenance.
- No Kafka, Redis, web UI, TUI, route/AI control, GameScript, realtime optimization,
  ML, speculative vehicle/route/cost schemas or unrelated logistics changes.
- Each ticket delivers a complete observable behavior at its boundary. Early
  infrastructure tickets are runnable contract slices, not empty interface
  scaffolding. No ticket creates every abstraction in advance.
- Dependencies below are direct blockers; inherited blockers are not repeated.
  Ticket numbers give one valid implementation order, not a requirement to serialize
  independent work. Before implementation, recheck existing work in progress and
  avoid overwriting it. No broad prefactor is required; the small final-result
  extraction belongs in T09 and must preserve batch outputs.
- T09 precedes service/CLI integration so they can use a working final-result
  path. T07 already includes safe cleanup when failures occur; later failure
  tickets complete specified policies and coverage, not permission to leak processes
  until those tickets land. Live CLI completion is not production release approval:
  T12–T17 remain required release gates.
- Candidate new component names below are locations to consider, not mandates to
  create one file/interface per responsibility. Existing file paths are included
  at the user's request and must be rechecked when implementation starts.

## Recorded task breakdown

1. **T01 — Preserve batch behavior with execution-mode metadata.** Blocked by: none. Delivers compatible domain/result metadata and an executable batch-regression contract.
2. **T02 — Persist mode metadata and add the telemetry schema.** Blocked by: T01. Delivers a reversible PostgreSQL migration plus existing batch-history round trips.
3. **T03 — Decode typed 13.4 telemetry with explicit economic meanings.** Blocked by: none. Delivers source-derived wire fixtures to validated observations without prototype imports.
4. **T04 — Observe an authenticated Admin connection read-only.** Blocked by: T03. Delivers negotiated subscriptions and typed observations from a controlled peer.
5. **T05 — Prepare verified pinned runtime assets.** Blocked by: none. Delivers a ready runtime bundle with deterministic, safe asset provenance.
6. **T06 — Isolate live configuration, secrets and port leases.** Blocked by: T01, T05. Delivers per-run launch material and collision-safe ownership checks.
7. **T07 — Supervise one live process through the runner contract.** Blocked by: T04, T06. Delivers readiness, progress, owned stopping and bounded baseline cleanup.
8. **T08 — Process and persist observations with bounded backpressure.** Blocked by: T02, T03. Delivers typed observations to ordered, idempotent PostgreSQL storage.
9. **T09 — Save explicitly and produce the existing final result.** Blocked by: T07. Delivers runner-owned save/quit followed by public Lab parsing of that same world.
10. **T10 — Link live execution to ExperimentService history.** Blocked by: T08, T09. Delivers pre-launch linkage and atomic final result/session persistence.
11. **T11 — Expose explicit live mode and concise CLI output.** Blocked by: T10. Delivers mode selection, validation, summaries, JSONL and mode-safe comparisons.
12. **T12 — Recover observation connections without hiding gaps.** Blocked by: T11. Delivers bounded reconnect, correct date context, completeness and exit outcomes.
13. **T13 — Complete cancellation, timeout and owner-death behavior.** Blocked by: T11. Delivers signal-specific outcomes, escalation and verified process cleanup.
14. **T14 — Preserve truthful outcomes during database failure.** Blocked by: T11. Delivers bounded storage-failure shutdown and retained recovery manifests/artifacts.
15. **T15 — Recover terminal persistence without rerunning simulation.** Blocked by: T14. Delivers validated, idempotent manifest recovery through the CLI.
16. **T16 — Verify cross-run isolation, security and the failure matrix.** Blocked by: T12, T13, T15. Delivers integrated evidence that ownership/failure boundaries hold together.
17. **T17 — Prove production live telemetry in one real simulation.** Blocked by: T16. Delivers the opt-in PostgreSQL/OpenTTD acceptance smoke test and evidence.
18. **T18 — Remove prototype runtime and retain validated reference material.** Blocked by: T17. Delivers production independence with useful research/fixtures preserved.

Initially available frontier: T01, T03, T05. After T11, T12, T13 and T14 are
independent; T15 follows T14. T16 joins those policy slices before the real proof.
These are scheduling opportunities, not instructions to spawn agents now.

## Preserved ticket definitions

### T01 — Preserve batch behavior with execution-mode metadata

**Objective / delivery:** Existing batch callers continue to receive the same
experiment behavior while results can express execution mode and optional live outcomes.

**Blocked by:** None (can start immediately).

**Exact scope:** Add execution-mode defaults, the specified LiveExecutionOptions,
optional LiveExecutionSummary and typed execution-failure/result metadata. Preserve
running/succeeded/failed and absent-live-field serialization compatibility. Keep
SimulationRunner synchronous; no live settings in scenario/strategy identity.
Exercise the existing injected batch runner with the expanded types. Define the
specified reason/completeness values, not new statuses or policy choices.

**Likely files/components:** `app/experiments/domain.py`,
`app/simulation/openttd/runner.py` contract only if necessary,
`tests/test_experiments.py`; focused new domain tests if useful.

**Tests required:** Existing batch configuration/result/artifact tests; old fake
runner still satisfies the contract; default mode batch; optional fields omitted
where required; invalid options/reason values rejected; exact final metric names,
units and signs preserved; no Admin import/work from batch execution.

**Spec acceptance:** Owner AC01. Shared foundation for AC03 and AC04; decisions §1/§3.

**Non-goals:** No migration, live launcher, observer, CLI live flag, outcome
persistence or general runner framework. Global scope exclusions also apply.

**Completion conditions:** Old batch service tests pass unchanged in intent; new
metadata validates and serializes compatibly; no runtime behavior switches to live.

### T02 — Persist mode metadata and add the telemetry schema

**Objective / delivery:** Upgrade existing populated experiment history safely and
round-trip batch mode metadata while providing the exact live storage constraints.

**Blocked by:** T01 — types/defaults used by model and repository mappings.

**Exact scope:** Add experiment execution fields and the two specified live tables,
constraints, indexes and batch backfill; update model registration. Persist batch
mode metadata through existing experiment repository operations. Verify live-session
and observation relationships with small SQL/model fixtures, without inventing a
production telemetry API before T08. Keep SimulationRun creation at finalization.
Provide reversible downgrade and document that it removes telemetry additions only.

**Likely files/components:** Next additive revision in `alembic/versions/`,
`app/experiments/model.py`, `app/experiments/repository.py`,
`app/database/models.py`, `tests/test_experiment_migration.py`,
`tests/test_postgres_integration.py`; telemetry ORM definitions may be adjacent.

**Tests required:** Upgrade/downgrade on populated old history; default batch
backfill; JSONB, foreign keys, cascade behavior, indexes and envelope constraints in
real isolated PostgreSQL; model/migration agreement; existing batch history and
metric values unchanged; no unrelated table changes. Keep migration assertions strong.

**Spec acceptance:** Owner AC21. Shared AC01, AC03, AC11; decisions §6.

**Non-goals:** No metrics ETL, observation processor, persistence queue, live
SimulationRun placeholder, per-vehicle tables or migration of old runs to telemetry.

**Completion conditions:** Migration applies and reverses; both database test
conventions pass; batch persistence remains functional; telemetry relationships
are testable before any process launch.

### T03 — Decode typed 13.4 telemetry with explicit economic meanings

**Objective / delivery:** Version-pinned packet fixtures become immutable typed
observations whose names and metadata cannot confuse measurement periods or counts.

**Blocked by:** None (can start immediately).

**Exact scope:** Build the narrow production framing/decoder and the specified
payload/envelope types and source/period/sign metadata. Decode required handshake,
Date, CompanyInfo, Economy and Stats fields and supporting packets needed by the
specified observer (rejection, heartbeat, shutdown, company lifecycle/world reset).
Retain exact integers, history offsets, capped cargo semantics, date-quality fields
and known zero/unknown distinctions. Do not assign receive sequence/date context
here; that behavior belongs to T08. Adapt selected fixtures/tests without importing
prototype modules, and label reconstructed bytes honestly.

**Likely files/components:** New production Admin protocol/telemetry domain
components under `app/simulation/openttd/`; focused tests/fixtures under `tests/`;
existing final metric metadata references in `app/experiments/domain.py` if necessary.

**Tests required:** Signed money/annual net income; complete quarter/stat categories;
leap-year-zero conversion and supported date range; protocol masks; fragmented and
coalesced frames, truncation/EOF/length/string bounds; unknown/trailing fields;
source/period distinctions, 65535 saturation, zero history; no invented wagon,
capacity, expenses, route or cumulative metrics.

**Spec acceptance:** Owners AC09, AC10. Shared AC07, AC22; decisions §3/§8.

**Non-goals:** No network connection, process/SQL lifecycle, complete Admin client,
new versions, generic metric registry platform or speculative future payloads.

**Completion conditions:** Production types/parser pass fixtures independently;
metric semantics match the source spec; fixtures run without prototype runtime.

### T04 — Observe an authenticated Admin connection read-only

**Objective / delivery:** A controlled 13.4 Admin peer can authenticate the observer,
negotiate updates and deliver typed events, with no simulator control capability.

**Blocked by:** T03 — protocol and payload contracts.

**Exact scope:** Implement connection-local authentication, revision/seed/map checks,
Protocol-v2 frequency validation, initial polls, daily Date/automatic info/monthly
Economy and Stats subscriptions, monthly full-info poll, and full-info repoll after
partial company changes. Emit lifecycle/health notifications, heartbeat Ping/Pong,
shutdown/reset detection, and typed events. Close on rejection or cancellation.
Outbound allowlist: Join, Quit for the connection, UpdateFrequency, Poll, Ping.
Implement observable loss reporting here; runner-directed reconnection policy is T12.

**Likely files/components:** New AdminObserver beside the production protocol;
controlled socket-peer tests and async stream fixtures in `tests/`.

**Tests required:** Valid handshake and subscriptions; bad password with no retry;
unsupported version/identity/frequency; 10-second handshake and heartbeat deadlines
using controlled time; company creation/update/removal; missing Date before data;
EOF/cancellation cleanup. Assert outbound bytes cannot contain RCON/game-control
packets and observer cannot launch or signal a process.

**Spec acceptance:** Owners AC05, AC06. Shared AC07 and AC15; decisions §1/§4/§7.

**Non-goals:** No automatic world restart, DB writes, process shutdown, runner
readiness decisions, general Admin API or reconnection-gap policy.

**Completion conditions:** Typed stream and health events work against a local
controlled peer; every termination closes the connection; observer remains read-only.

### T05 — Prepare verified pinned runtime assets

**Objective / delivery:** A run can obtain a verified executable/graphics/AI bundle
and provenance without calling or modifying Lab's private launcher.

**Blocked by:** None (can start immediately).

**Exact scope:** Implement the specified application runtime asset adapter: pinned
executable identity, official checksums/manifests, graphics, chosen AI and dependency
libraries, verified cache reuse, safe extraction, locking and atomic cache publication.
Use public Lab content helpers where appropriate. Support existing baseline and
SimpleAI strategy configurations. Errors are sanitized and no process is launched.

**Likely files/components:** New runtime-preparation component under
`app/simulation/openttd/`; existing strategy/config types consumed unchanged;
focused runtime and cache tests in `tests/`.

**Tests required:** Controlled downloads/manifests; cached success; checksum/version
mismatch; dependency materialization; safe archive/path handling; interrupted and
concurrent cache writes; pinned parameters preserved; no private Lab calls or
network-dependent unit tests.

**Spec acceptance:** Shared AC02, AC17, AC18, AC22; decisions §2/§7.

**Non-goals:** No OpenTTD run, new provisioning platform, alternate version support,
change to batch asset behavior, replacement binary or new AI strategy.

**Completion conditions:** Deterministic verified bundle plus sanitized provenance
is produced under test; failed preparation exposes no partial cache as valid.

### T06 — Isolate live configuration, secrets and port leases

**Objective / delivery:** Two local invocations can prepare separate live launch
workspaces without sharing mutable config, credentials, save paths or port ownership.

**Blocked by:** T01 — validated options; T05 — verified runtime bundle.

**Exact scope:** Under runner-owned resource management, create per-run directories,
versioned 13.4 main/private/secrets config and existing AI startup configuration;
enforce all specified owned settings and loopback-only policy. Generate compliant
random passwords; enforce 0700/0600, sanitized provenance and argv-safe paths.
Lease distinct ports from the specified range or fixed choices; check game TCP/UDP
and Admin TCP; retain leases across handoff until confirmed process exit. Document
and expose the unavoidable external bind race; no silent rerun after collision.

**Likely files/components:** Runtime configuration/resource helpers under
`app/simulation/openttd/`, consumed by the upcoming runner; resource/port tests.

**Tests required:** Versioned config placement/precedence fixtures; conflicting
settings rejected/overridden per spec; secrets absent from argv/metadata/errors;
permissions, path traversal, public binds, port collisions and reservation handoff;
concurrent preparation and cleanup on preparation failure; existing scenario identity
unchanged by chosen ports/secrets. Actual OpenTTD config verification is T17.

**Spec acceptance:** Owner AC17. Shared AC02, AC04, AC18; decisions §2/§7.

**Non-goals:** No process supervisor yet, global port daemon, atomicity claims
against unrelated programs, secret CLI flags or legacy config-migration trick.

**Completion conditions:** Controlled concurrent preparation proves isolation;
leases/resources have explicit single ownership and release conditions; no secret
is persisted outside its owned temporary location.

### T07 — Supervise one live process through the runner contract

**Objective / delivery:** The runner can own one controlled dedicated process from
preparation through authenticated readiness, progress and a bounded stop.

**Blocked by:** T04 — observer; T06 — launch resources (including options/assets).

**Exact scope:** Implement LiveSimulationRunner behind the existing synchronous
contract, owning its internal task scope, process group/stdin/log drains, options,
ports/secrets and cleanup. Start paused; require owned process, negotiated identity
and initial Date before unpause. Deliver Date to stop logic without waiting for
DB/output. Track configured start, requested target and observed day. Supply the
specified lifecycle-command allowlist and monotonic deadlines/escalation. Require an
injected final-result operation for a successful contract return; controlled tests
supply it until T09 implements the concrete save/parser path. Never ship a success
stub or silently return an earlier save. Do not expose CLI live mode yet.

**Likely files/components:** New LiveSimulationRunner under
`app/simulation/openttd/`, existing `SimulationRunner` contract, owned controlled
executable/peer fixtures and runner contract tests.

**Tests required:** One owned process; paused readiness ordering; TCP availability
alone insufficient; delayed Date; no required pre-unpause company; normal stop and
joined tasks; startup/auth/protocol failures; basic timeout/cancellation cleanup;
stdout/stderr pressure; unexpected EOF versus requested shutdown; no live overhead
on batch. Date stopping remains responsive to a stalled observation consumer.

**Spec acceptance:** Owners AC02, AC04. Shared AC06, AC15, AC16, AC19; decisions §1/§4.

**Non-goals:** No SQL, live CLI, real final save/parser implementation, invented
result, Admin RCON, arbitrary control API, automatic process retry or Lab launch seam.

**Completion conditions:** Runner contract is independently verified with controlled
processes and injected final result; all started resources are bounded and reaped
on tested paths. Normal production save behavior remains explicitly gated on T09.

### T08 — Process and persist observations with bounded backpressure

**Objective / delivery:** A decoded observation stream becomes ordered, queryable
PostgreSQL telemetry without blocking lifecycle notifications or hiding overload.

**Blocked by:** T02 — schema; T03 — typed observation/metric contracts.

**Exact scope:** Implement TelemetryProcessor and TelemetryRepository together as a
single input-to-storage slice. Assign run sequences/epochs and reception times;
annotate preceding-date context and inferred periods; clear context at a connection
boundary; preserve lifecycle diagnostics and company identity discontinuities.
Implement cursor reads, exact-value storage, session summaries/counters and identical
batch retries with conflict detection. Use the specified 1024 total bound, 100-row/
1-second flush rule, separate health path, independent short DB sessions, 10-second
retry budget and bounded flush/query/worker behavior. Emit typed fatal storage
notifications; actual runner/service failure persistence is completed in T14.

**Likely files/components:** New telemetry processor/repository near experiment
persistence and OpenTTD observations; telemetry ORM from T02; PostgreSQL and
stream-to-repository tests. Avoid new infrastructure packages.

**Tests required:** Input-to-DB exact signed values; date-null/context transitions;
sequence/epoch ordering; same-day duplicate samples retained; identical retry versus
conflicting sequence; cursor filters/limits; flush clock/size triggers; rollback,
transient retry, permanent error, exhaustion and full-queue health; no unbounded
worker/query remains. Saturation/history metadata and missing values survive storage.

**Spec acceptance:** Owner AC16. Shared AC07, AC09, AC11, AC14, AC15, AC21; decisions §3/§6.

**Non-goals:** No new event bus, unlimited disk spooling, sample dropping, process
signaling, final SimulationRun placeholder or speculative telemetry tables.

**Completion conditions:** A controlled event stream is persisted and read back via
the specified interface; backpressure is bounded and externally observable; no
process/CLI is required for this proof.

### T09 — Save explicitly and produce the existing final result

**Objective / delivery:** A completed owned world produces the application's final
SimulationResult through explicit runner save/quit and public Lab parsing.

**Blocked by:** T07 — owned stdin/process lifecycle and final-result integration point.

**Exact scope:** Implement the runner-owned pause/synchronous-save acknowledgment/
quit barrier with bounded completion, and FinalResultProcessor using public
openttdlab.parse_savegame. Validate provenance/company-0 presence; normalize date
and chunks; retain raw save, parsed artifact and hashes. Extract only the small
shared conversion/artifact helper needed to preserve existing batch semantics.
Record target, last observation and actual save day honestly. Classify missing,
corrupt or stale-only saves as failure, keeping autosaves explicitly partial.

**Likely files/components:** Live runner and new final-result processor;
`app/simulation/openttd/runner.py` narrowly scoped shared helper;
`tests/test_experiments.py`, stored save fixtures and controlled save-barrier tests.

**Tests required:** Save acknowledged before quit; no fixed-sleep success; controlled
overshoot retained; parse a stored valid save using public parser; missing/corrupt
save, missing company and incorrect provenance; earlier autosave never accepted
as successful final save; exact batch artifacts/metric names/signs unchanged;
only the original process can produce the live result. Real barrier proof is T17.

**Spec acceptance:** Owners AC12, AC13. Shared AC01, AC04, AC09, AC11, AC15, AC22; decisions §2/§4.

**Non-goals:** No second simulation, private Lab launch/extraction call, Admin-driven
quit, telemetry-derived final economics, multi-company final aggregation or DB recovery.

**Completion conditions:** The runner has a concrete final-result path, independently
tested with controlled process and real stored-save parsing; failures cannot return
normal success; batch regression passes.

### T10 — Link live execution to ExperimentService history

**Objective / delivery:** Service invocation records live observations against an
existing ExperimentRun and commits one linked final result and live summary.

**Blocked by:** T08 — processor/repository; T09 — complete runner/final-result path.

**Exact scope:** Compose live runner/observer/processor/writer under ExperimentService
without changing batch default. Commit ExperimentRun/live-session startup before
launch; route by explicit mode; atomically commit final SimulationRun/metrics,
terminal experiment and live summary. Map typed failures, including cancellation,
without reopening terminal runs; retain received observations on failure and avoid
canonical final rows for unrecovered fatal runs. Keep independent write sessions
and runner-owned task lifecycle. Use unique run artifact directories.

**Likely files/components:** `app/experiments/service.py`,
`app/experiments/repository.py`, new live composition/factory if needed;
existing domain/models and `tests/test_experiments.py`/PostgreSQL contract tests.

**Tests required:** Service-level controlled live run with observations visible
before a SimulationRun exists; one final relation only; complete and incomplete
summaries distinct from experiment success; failed run retains observations/no
canonical final metrics; startup commit failure launches nothing; terminal transaction
rollback; batch mode still selects the existing adapter.

**Spec acceptance:** Owner AC11. Shared AC01, AC03, AC07, AC14, AC15; decisions §1/§4/§6.

**Non-goals:** No CLI commands, new run-status vocabulary, automatic resume,
prototype imports or claiming final DB-outage recovery is complete before T14–T15.

**Completion conditions:** The existing service test seam exercises the fully
composed happy path and typed failure linkage; transactions are externally verified;
batch contracts remain intact.

### T11 — Expose explicit live mode and concise CLI output

**Objective / delivery:** A user can select one live run, observe concise output,
and distinguish mode and telemetry completeness without altering batch defaults.

**Blocked by:** T10 — composed service entry point and typed outcomes.

**Exact scope:** Add single-run mode/strategy/scenario selection and the spec's
live-only validated options, owned artifact directories, human summaries and
optional typed JSONL. Keep diagnostics separate from machine-readable stdout;
label yearly versus quarterly values. Render mode in provenance/results and reject
mixed-mode comparisons; compare remains batch-only. Implement the specified exit-code
mapping using service outcomes and document normal-speed/live limits. No recovery
subcommand until T15; no placeholder recovery command. CLI tests may supply typed
failure outcomes until T12–T14 generate them through real lifecycle paths.

**Likely files/components:** `app/experiments/cli.py`,
`app/experiments/comparison.py`, result serialization, `README.md` command docs,
`tests/test_comparison.py`, focused CLI tests.

**Tests required:** Existing run/compare defaults; valid single live invocation;
invalid flag/mode/port combinations fail before launch; mode export and comparison
isolation; all specified exit codes from injected outcomes; at-most-monthly summaries,
period labels and clean JSONL; no password/raw-packet output; output consumer cannot
own process control or database persistence.

**Spec acceptance:** Owner AC03. Shared AC01, AC09, AC14, AC18; decisions §7.

**Non-goals:** No UI/TUI, live multi-seed comparison, secret flags, recovery command
stub, new strategy or implicit change to batch speed/summaries.

**Completion conditions:** CLI-to-service contract works through controlled fixtures;
old commands remain compatible; mode and completeness are visible and machine-readable.

### T12 — Recover observation connections without hiding gaps

**Objective / delivery:** A temporary Admin disconnect can recover within budget,
but its gap remains visible through persisted observations, results and CLI outcome.

**Blocked by:** T11 — complete service/CLI path, including processor and observer.

**Exact scope:** Add runner-authorized reconnect with the specified capped backoff/
budget, new transport epochs, reauthentication/resubscription/repolls and cleared
date context. Preserve receive sequences, gap intervals and company discontinuities.
Compute complete/incomplete/failed from required types, coverage and flushed samples;
recovered gaps or missing required types give succeeded plus incomplete/exit 3.
Exhausted reconnect gives observer_lost and runner-owned stop. Reject server NewGame
or identity reset; never pause/restart a world to conceal gaps. Initial auth rejection
still has no password retry.

**Likely files/components:** AdminObserver health/reconnect support, live runner
policy, TelemetryProcessor summaries, service/CLI outcome integration tests.

**Tests required:** Controlled drops around year/quarter boundaries; measurements
before new Date remain unknown; same-day repolls retained; retries stay in budget;
heartbeat failure versus stalled simulation; gap remains after recovery; missing
types; failure/exit outcomes; reset/identity mismatch and cancellation during reconnect.
Assert observer remains read-only and does not stop the process itself.

**Spec acceptance:** Owner AC14. Shared AC05, AC15; decisions §3/§4/§5.

**Non-goals:** No replayed history, false complete coverage, changed database
failure policy, world restart, infinite reconnect or remote Admin support.

**Completion conditions:** Controlled service-to-CLI failure tests verify complete,
incomplete and fatal outcomes with matching stored gaps and no lifecycle leaks.

### T13 — Complete cancellation, timeout and owner-death behavior

**Objective / delivery:** Timeout, user signals and unexpected supervisor death leave
no live owned OpenTTD process and produce truthful outcomes where recording is possible.

**Blocked by:** T11 — composed service/CLI signal-to-outcome path.

**Exact scope:** Complete SIGINT/SIGTERM/cancellation handling, bounded best-effort
partial save, graceful/TERM/KILL escalation, joined observer/writer/log tasks and
bounded finalization workers. Add the specified Linux parent-death mechanism.
Preserve original failure reason and secondary cleanup diagnostics. Distinguish
expected quit EOF from unexpected shutdown. Document SIGKILL's unavoidable inability
to guarantee final save, terminal DB update or secret-workspace removal.

**Likely files/components:** Live runner/process ownership, CLI signal handling,
service typed-failure mapping; controlled child/supervisor tests.

**Tests required:** Actual signals to controlled owned processes; timeouts and hung
save/quit/parser/flush paths; forced termination never success; exit 124/130/143;
parent death; EOF timing; no living children, tasks, sockets, threads or held leases;
no unrelated process signaled; failure reason retained when cleanup also fails.

**Spec acceptance:** Owner AC19. Shared AC04, AC15; decisions §4/§5.

**Non-goals:** No general daemon/watchdog service, platform expansion, pretending
SIGKILL cleanup is guaranteed, or implementing manifest reconciliation (T15).

**Completion conditions:** Catchable failure paths record the specified outcomes;
owner-death tests prove child termination; resources are bounded and released, and
unavoidable abrupt-death artifacts are documented.

### T14 — Preserve truthful outcomes during database failure

**Objective / delivery:** Persistence outages stop an unsafe live run within budget
or preserve a completed result for recovery without falsely claiming DB success.

**Blocked by:** T11 — complete CLI/service/runner/storage composition.

**Exact scope:** Wire T08 storage health into runner failure shutdown and service
outcomes. Complete startup, transient write, retry exhaustion, permanent error,
queue-full and final-commit failure behavior. Write atomic sanitized outcome manifests
for successful and failed attempts with original IDs, configuration/artifact hashes,
summary and cleanup state. Preserve requested final or explicitly partial artifacts
as appropriate; keep terminal DB failure distinct from simulator failure. No silent
replay, unbounded buffering, synthetic observations or canonical final result on
fatal live failure.

**Likely files/components:** TelemetryProcessor/Repository error handoff, live runner,
`app/experiments/service.py` and repository transaction handling; small outcome
manifest writer; PostgreSQL outage/controlled process tests.

**Tests required:** Initial commit failure means no launch; transient recovery keeps
complete when lossless; full queue/permanent error/exhaustion stops owner; final commit
rollback retains artifacts/manifest and exit 1 rather than success; DB sessions and
worker threads finish; no original failure masking when failure-record commit also
fails; manifests contain no credentials and are written atomically.

**Spec acceptance:** Shared AC14, AC15, AC16, AC18, AC20; decisions §4/§5/§6.

**Non-goals:** No recovery reader/command yet, no new broker/spooling service,
automatic simulation rerun, invented terminal DB state or relaxed retry limits.

**Completion conditions:** All DB failure stages are distinguishable through CLI,
local evidence and available DB state; manifests are usable inputs for T15;
owned simulation and persistence work terminate within specification budgets.

### T15 — Recover terminal persistence without rerunning simulation

**Objective / delivery:** A user can reconcile a recorded terminal outcome into
PostgreSQL from its retained manifest without launching another simulation.

**Blocked by:** T14 — durable manifest/artifact semantics and outage outcomes.

**Exact scope:** Implement the spec's narrow recovery operation and CLI subcommand.
Validate local path ownership, original run ID/configuration and hashes; atomically
persist a missing compatible terminal outcome/final result. Accept idempotent repeat;
reject conflicting terminal state/artifacts. Preserve incomplete telemetry and failed
partial-result classification. Handle verified abandoned owned workspaces during
explicit recovery or next startup; never signal a PID solely from an old file.
Keep raw saves/parsed results while removing only confirmed abandoned temporary secrets.

**Likely files/components:** Small recovery component beside ExperimentService,
`app/experiments/repository.py`, `app/experiments/cli.py`, command documentation,
manifest/CLI/PostgreSQL tests.

**Tests required:** Successful and failed recovery, idempotent replay, conflicting
result, bad/missing/hash-mismatched artifact, wrong configuration/run, unsafe path,
active workspace and stale/PID-reuse safety; database failure while recovering;
no process launcher invoked; no missing telemetry synthesized or promoted to complete.

**Spec acceptance:** Owner AC20. Shared AC15, AC18; decisions §5/§7.

**Non-goals:** No simulation resume, telemetry-history reconstruction, automatic
recovery daemon, general artifact management or change to terminal outcome policy.

**Completion conditions:** Recovery CLI reconciles valid outcomes exactly once,
rejects conflicts without mutation, and never starts/restarts a world or kills an
unrelated process.

### T16 — Verify cross-run isolation, security and the failure matrix

**Objective / delivery:** The integrated application proves that independent live
runs cannot share authority/data and that all specified failure outcomes agree.

**Blocked by:** T12 — observation-loss policy; T13 — process failure policies;
T15 — DB failure and recovery path.

**Exact scope:** Add a focused cross-component acceptance suite through the agreed
service/CLI seams using two controlled processes/peers and isolated PostgreSQL.
Verify ports, identifiers, config, artifacts and credentials remain isolated under
concurrent startup/stop/failure. Audit the spec's full failure table and close only
integration defects exposed by it. Test redaction at output, exception, persisted
metadata and artifact boundaries, not just individual helper return values.
This is a bounded integration slice; do not redesign completed components.

**Likely files/components:** Service/CLI integration tests, PostgreSQL fixtures,
controlled process/peer fixtures, minimal fixes in affected live components;
no new architecture layer.

**Tests required:** Cross-run auth mismatch, external port collision, concurrent
cache publication, cancellation of one run while the other progresses, DB isolation,
secret scan of emitted artifacts/metadata/output and exact permissions/loopback.
A table-driven audit links every startup/auth/protocol/loss/DB/timeout/cancellation/
shutdown/finalization row to a passing test from T04/T07/T09/T12–T15; do not duplicate
those implementations or rerun real simulations to simulate failures.

**Spec acceptance:** Owners AC15, AC18. Shared AC17, AC19, AC21; decisions §4–§7.

**Non-goals:** No generic security platform, remote transport, large load benchmark,
new behavior beyond the specification or production real OpenTTD run yet.

**Completion conditions:** Failure table has no untested rows; two controlled runs
remain isolated; credential-free boundaries and cleanup assertions pass together;
remaining production proof is limited to T17's actual simulator path.

### T17 — Prove production live telemetry in one real simulation

**Objective / delivery:** One actual production-launcher simulation stores useful
live telemetry and then produces its correctly linked final parsed save.

**Blocked by:** T16 — integrated failure/security/isolation verification.

**Exact scope:** Add and exercise the opt-in real production smoke test from the
spec: OpenTTD 13.4, OpenGFX 7.1, existing SimpleAI road-only, seed 17, 120 days,
disposable PostgreSQL schema. Require all required observation types queryable while
the same owned process is alive, changing values and completed-quarter data, explicit
save/quit acknowledgment, public Lab final parsing, same-run linkage and cleanup.
Record actual date, mode and completeness; verify generated versioned config really
works. Keep evidence concise, deterministic in assertions rather than AI cash values.

**Likely files/components:** `tests/test_openttd_integration.py` or adjacent dedicated
live smoke test, `tests/conftest.py` opt-in controls, isolated PostgreSQL fixture,
short reproduction/verification documentation.

**Tests required:** The one real smoke test plus existing batch regressions; no
second hidden simulation used for final parsing; raw/final artifact validity;
no ports/processes/tasks/leases/secrets left; fixture is skipped by default;
no exact prototype financial-value or elapsed-time equality assertion. Run the full
existing suite once for the production feature completion gate, then review.

**Spec acceptance:** Owners AC07, AC08. Shared AC01, AC02, AC11, AC12, AC22;
Testing Decisions group 8.

**Non-goals:** No twenty-run comparison, performance study, alternate version matrix,
optimization/control functionality or prototype launcher fallback.

**Completion conditions:** All real-run acceptance evidence passes using production
components only; no known failure/security gate remains; completed-quarter/live/final
coexistence is independently demonstrated and documented.

### T18 — Remove prototype runtime and retain validated reference material

**Objective / delivery:** Production no longer has an executable unsupported fallback,
while the useful feasibility evidence and independent fixtures remain available.

**Blocked by:** T17 — production proof before removal of the working prototype.

**Exact scope:** Remove prototype launch interception/proxy, hardcoded supervisor,
lifecycle RCON, fixed scenario/date, legacy password injection and ad hoc pipeline.
Remove its interception regression test. Retain/archive report, research links,
credential-free proof and hashes; keep adapted independent production fixtures and
semantic/socket tests. Ensure report/spec reference links still resolve after any
archiving. Do not commit bulk generated saves or secrets. Audit production imports,
commands and docs for prototype/private-launch references or fallback flags.

**Likely files/components:** `prototype/live_admin/` runtime/test files, retained
research documents, production fixture provenance, command docs and narrowly scoped
import/reference checks. Preserve source-spec meaning; update links only if required.

**Tests required:** Production tests run with prototype runtime unavailable;
reference/import audit; retained fixtures distinguish captured decoded examples from
synthesized wire bytes; relevant post-cleanup regressions and documentation links.
Do not rerun the expensive real smoke solely because reference files were archived
unless cleanup changed runtime behavior or exposed a new concern.

**Spec acceptance:** Owner AC22. Shared knowledge retention under Further Notes.

**Non-goals:** No deleting research evidence, replacing production code with prototype
imports, new runtime behavior, bulk artifacts in version control or unrelated cleanup.

**Completion conditions:** Only permitted reference material remains from the
prototype; production and retained tests are independent; user can trace the final
implementation back to the spec and validated evidence.

## Acceptance coverage map

AC01–AC22 are ordinal aliases for the production acceptance checklist in the source
spec, in its original order. They do not add or edit specification requirements.
Each has exactly one accountable owner ticket. Shared tickets contribute explicitly
listed implementation or regression evidence; the owner verifies that evidence
before claiming its criterion complete. Feature acceptance waits for all tickets,
not merely the tickets with owner assignments. Tickets without an owner assignment
are necessary supporting slices, not optional work.

| Spec criterion (verbatim) | Owner | Shared coverage |
|---|---|---|
| AC01: Existing run/compare defaults execute the existing fast batch path; history and metrics remain compatible. | T01 | T02, T09, T10, T11, T17 |
| AC02: Live mode launches exactly one owned dedicated process using pinned verified assets and no private Lab launch interception or replacement binary. | T07 | T05, T06, T09, T17 |
| AC03: Live and batch mode provenance are explicit, and mixed-mode comparison is rejected by default. | T11 | T01, T02, T10 |
| AC04: LiveSimulationRunner alone owns ports, secrets, readiness, deadlines, save/quit, signaling, cancellation and cleanup. | T07 | T06, T09, T13 |
| AC05: AdminObserver is restricted to observation/authentication/connection maintenance; packet tests forbid RCON and other game-control messages. | T04 | T12 |
| AC06: Protocol v2 and correct Welcome identity are required; required update frequencies are negotiated before running. | T04 | T07 |
| AC07: Date, CompanyInfo, CompanyEconomy and CompanyStats become typed, persisted observations during the same real process's lifetime. | T17 | T03, T04, T08, T10 |
| AC08: The production real test receives meaningful changing values and completed-quarter data without asserting prototype-specific financial results. | T17 | — |
| AC09: Yearly Admin net values, quarter-scoped save metrics, current balances, history values and any future cumulative series cannot be confused by names or metadata. | T03 | T08, T09, T11 |
| AC10: No route, consist, wagon, capacity or separate cost metrics are invented from Admin counts. | T03 | — |
| AC11: Observations link to the existing ExperimentRun before a final SimulationRun exists; the final result links through that same run exactly once. | T10 | T02, T08, T09, T17 |
| AC12: Explicit final save succeeds after a runner-owned stopping barrier, and the public Lab parser plus existing conversion produce the final SimulationResult/artifact. | T09 | T07, T17 |
| AC13: A final-save date later than the requested target is recorded honestly; an older autosave is never silently substituted for successful live finalization. | T09 | — |
| AC14: Successful simulation with recovered gaps reports telemetry incomplete and exit 3; fatal observation/storage failures follow the specified table. | T12 | T08, T10, T11, T14 |
| AC15: All listed startup, authentication, loss, DB, timeout, cancellation and shutdown cases have externally observable tests and bounded cleanup. | T16 | T04, T07, T08, T09, T10, T12, T13, T14, T15 |
| AC16: Queue/database backpressure cannot indefinitely block supervision; retries are bounded/idempotent and overload is visible. | T08 | T07, T14 |
| AC17: Concurrent runs isolate ports, files, IDs and secrets; collisions cannot attach an observer to another run or kill an unrelated process. | T06 | T05, T07, T16 |
| AC18: Passwords never appear in CLI output, argv, stored metadata, final artifacts or exception reports; loopback and permission checks pass. | T16 | T04, T05, T06, T08, T09, T10, T11, T14, T15 |
| AC19: Cancellation and supervisor death leave no live owned OpenTTD process; resource/task/thread cleanup is verified, with unavoidable SIGKILL artifact limits documented. | T13 | T07, T16 |
| AC20: Database outage retains an outcome manifest/artifacts; recovery cannot rerun the simulation or overwrite a conflicting result. | T15 | T14 |
| AC21: Additive migration preserves existing populated history and passes actual PostgreSQL checks; unrelated logistics workflows are untouched. | T02 | T08, T16 |
| AC22: Production has no imports from the prototype and no private OpenTTDLab launcher references; selected evidence/fixtures remain available after prototype runtime removal. | T18 | T03, T04, T05, T07, T09, T17 |

## Failure-table coverage audit

This table makes AC15's shared coverage explicit rather than burying failure work
in the smoke test. T16 audits completion of every row; owning implementation slices
supply the tests, and T11 supplies CLI exit-code rendering.

| Specification condition | Implementation/test slice |
|---|---|
| Startup, assets or bind failure | T05, T06, T07; composed evidence T16 |
| Admin authentication failure | T04, T07 |
| Unsupported protocol/identity or malformed known packet | T03, T04, T07 |
| Connection loss, recovered/exhausted budget, world reset | T12 |
| DB failure before launch | T10; outage evidence T14 |
| Transient telemetry DB failure | T08; composed outcome T14 |
| Exhausted/permanent DB failure or queue full | T08, T14 |
| Normal completion and missing required observation types | T09, T10, T12 |
| Timeout, SIGINT/cancellation, SIGTERM | T07 baseline; full policy T13 |
| Expected versus unexpected ServerShutdown/EOF | T04/T07 baseline; full policy T13 |
| Save or final parse failure | T09 |
| Final DB commit failure and local retention | T14 |
| Explicit terminal recovery and conflict rejection | T15 |
| Abrupt supervisor death / abandoned workspace handling | T13, T15 |

## Validation and publication boundary

Review questions:

1. Is 18 tickets the right granularity, or are any too coarse/fine?
2. Do the direct blocking edges represent genuine prerequisites?
3. Should any tickets be merged or split before publication?

User approval is required before turning this draft into tracker tickets. The
[to-tickets skill](/home/fed/.agents/skills/to-tickets/SKILL.md) says,
“Iterate until the user approves the breakdown.” No approval is inferred from a
structural validation script or from the earlier approval of specification test seams.

Tracker and triage setup is still absent. Before publication run
`/setup-matt-pocock-skills`, as the invoked skill requires. After plan approval and
tracker setup, publish one ticket per issue/file in blocker-first order, apply the
configured ready-for-agent label/status, and translate Txx edges to real blocking
links (or explicit text where unsupported). Do not modify/close a parent issue.
Do not implement any ticket as part of planning or publication.
