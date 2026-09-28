# Production specification: realtime OpenTTD telemetry

Status: implementation specification; no implementation authorized by this document's creation.
Target: current devmodule2 experiment domain. Initial runtime: Linux, Python 3.14.6,
OpenTTDLab 0.0.75, OpenTTD 13.4, OpenGFX 7.1, PostgreSQL, SQLAlchemy and Alembic.
Publication: local specification; tracker/triage configuration is absent. Run
`/setup-matt-pocock-skills` before tracker publication with `ready-for-agent`.
Test seams confirmed by the user: existing ExperimentService/SimulationRunner
contract, supported by wire-format fixtures and PostgreSQL integration tests.

## Problem Statement

Researchers can already run reproducible, fast, fixed-seed experiments and compare
final savegame metrics. They cannot yet observe a simulation through a supported,
supervised production path while it is running. The successful prototype requires
private OpenTTDLab interception and mixes lifecycle control into its Admin listener.
Promoting that arrangement would couple observation to simulator ownership and
make cancellation, concurrent runs, persistence failures and upgrades unreliable.

Economic observations have different periods and meanings. Treating Admin's
annual net economic figure as the savegame's quarterly income would produce false
comparisons. Company-level Admin totals also cannot answer questions about routes,
individual vehicles, train consists, or construction versus operating costs.

## Solution

Provide two explicitly selected execution modes under the experiment application:

* **Batch:** retain the existing OpenTTDLab runner, accelerated null-driver execution,
  fixed seeds, pinned configuration, final parsing, persistence and multi-seed
  comparison behavior. No Admin endpoint, observer, telemetry queue or live timeout
  is added to a batch execution.
* **Live-observed:** an application-owned LiveSimulationRunner prepares a pinned
  runtime and directly supervises one dedicated OpenTTD process. A read-only
  AdminObserver emits typed observations concurrently. TelemetryProcessor validates
  and annotates them; TelemetryRepository persists them. At completion, the public
  OpenTTDLab savegame parser and the existing result conversion produce the normal
  application SimulationResult and final artifact.

This is a separate launch path, not an OpenTTDLab fork or a replacement batch
pipeline. Production live mode does not call Lab's run_experiments to launch a
process, import its private launcher, monkeypatch modules, rewrite cached
executables, or run a second simulation to obtain the final result.

## User Stories

1. As an experiment researcher, I want existing batch commands to remain unchanged, so that established comparison workflows remain reproducible.
2. As a researcher, I want to select live mode explicitly, so that normal-speed observation does not silently slow batch experiments.
3. As a researcher, I want both modes to record the same pinned scenario, AI and seed metadata, so that run provenance remains understandable.
4. As a researcher, I want execution mode visible in results, so that I do not assume different drivers are tick-equivalent.
5. As an operator, I want one owner of the simulator, so that observers cannot accidentally terminate it.
6. As an operator, I want bounded startup and authentication, so that an unavailable endpoint cannot hang a command.
7. As an operator, I want reserved loopback ports, so that concurrent runs do not connect to one another.
8. As an operator, I want temporary secrets kept out of logs and artifacts, so that reproducing an experiment does not expose administrative access.
9. As a researcher, I want live game dates, so that progress follows simulation time rather than wall time.
10. As a researcher, I want company identity and AI status, so that economic observations identify the company they describe.
11. As a researcher, I want current cash and loan balances, so that I can inspect the company's current financial state.
12. As a researcher, I want Admin annual net economic values labeled precisely, so that I do not interpret them as gross revenue.
13. As a researcher, I want current-quarter and historical-quarter cargo observations separated, so that quarterly resets do not look like data corruption.
14. As a researcher, I want vehicle and station-facility counts by exposed category, so that I can inspect aggregate transport activity.
15. As a researcher, I want absent data distinguished from zero, so that unsupported route or wagon metrics are not invented.
16. As a researcher, I want observations linked to the experiment before final save processing, so that failed runs retain useful evidence.
17. As a researcher, I want the final parsed save linked to that same experiment, so that live and final evidence can be inspected together.
18. As an operator, I want bounded observation queues and database writes, so that slow persistence cannot freeze simulator supervision.
19. As an operator, I want database failure reported distinctly, so that a completed process is not falsely reported as fully recorded.
20. As a researcher, I want reconnection gaps recorded, so that later comparisons do not assume an uninterrupted time series.
21. As an operator, I want Ctrl-C to save when possible and clean up, so that interrupted work leaves no running server.
22. As an operator, I want timeout and unexpected shutdown distinguished from normal completion, so that incomplete experiments are visible.
23. As a researcher, I want concise terminal updates and machine-readable observations, so that monitoring does not require a dashboard.
24. As a maintainer, I want wire fixtures tied to OpenTTD 13.4, so that protocol changes cannot silently reinterpret data.
25. As a maintainer, I want additive migrations, so that existing experiment history and unrelated workflows remain intact.
26. As a maintainer, I want tests at the existing service/runner boundary, so that internal organization can change without brittle tests.
27. As a researcher, I want final artifacts retained when persistence fails, so that recovery does not require repeating a simulation.
28. As a future optimizer author, I want source-specific telemetry contracts, so that later vehicle, consist and route sources can be added without pretending Admin supplies them today.
29. As a maintainer, I want the prototype runtime deleted after replacement, so that an unsupported launcher cannot become an accidental production entry point.
30. As a researcher, I want a clear completeness indicator, so that a successful simulation with observation gaps is not mistaken for a complete live recording.

## Implementation Decisions

### 1. Application boundaries and execution contracts

Retain the repository's vocabulary: ExperimentConfig describes the scenario,
PlanningConfiguration, pinned AI, versions, seed and duration; ExperimentRun is
one attempted execution; SimulationResult is the typed final save interpretation;
SimulationRun is the persisted final result. Do not repurpose SimulationRun as a
process/session row or create it with invented final dates at startup.

| Boundary | Owns | Must not own |
|---|---|---|
| ExperimentService | Create the run before launch, select mode, coordinate terminal persistence and application outcome | Sockets, packet layouts, process signaling |
| Existing OpenTTDLabRunner | Unchanged batch execution and its existing adapter behavior | Live observation or live port allocation |
| LiveSimulationRunner | Process group, prepared runtime, ports, readiness, temporary config/secrets, deadlines, cancellation, save/quit, joining owned tasks and resources | SQL statements or interpretation of economic measures |
| AdminObserver | Authenticated read-only connection, framing, version checks, subscriptions/polls, decoded observations and connection health | Process launch, shutdown, pause, save, RCON, database writes, run outcome decisions |
| TelemetryProcessor | Typed validation, source/period annotations, ordering, date context, gap diagnostics, bounded handoff to storage | Cross-source economic aggregation, process control, generated missing measurements |
| TelemetryRepository | Transactional observation batches, idempotent retry, ordered reads, telemetry summary state | Network reconnection or simulation lifecycle |
| FinalResultProcessor | Parse completed save with public Lab parser, normalize its result, validate provenance, write final artifact | Running OpenTTD, reading live state, replacing save metrics with Admin metrics |

Keep SimulationRunner's synchronous run contract returning SimulationResult on
successful final processing. Configure live-specific execution options and its
telemetry dependencies when constructing LiveSimulationRunner; do not add Admin
configuration to every batch caller. The live runner may own an internal async
execution scope behind this boundary. Its synchronous entry point is for the CLI
and existing synchronous service, not for nesting in an already-running event loop.

Add a typed execution failure at this boundary: stable reason code, sanitized
message, optional partial-artifact reference, last observed day, process exit
code and cleanup diagnostics. Cancellation must be converted to an application
outcome after cleanup, not swallowed by the service's current Exception-only path.
Add an optional LiveExecutionSummary to SimulationResult, absent for batch results:
telemetry completeness, coverage endpoints, gap/drop counters, last sequence/day,
process exit code, requested/actual final day, artifact references and cleanup
outcome. Typed failures carry the same summary where available. This is execution
metadata, never an economic metric. ExperimentService uses this summary to commit
the terminal live-session state atomically with the experiment/final result; it
must not infer completeness from a successful return alone. Add execution_mode,
optional failure_code and optional live summary to ExperimentResult with backward-
compatible batch defaults; omit absent optional fields in legacy batch exports.

Keep legacy ExperimentRun status values running/succeeded/failed: cancellation
and timeout are failed attempts with distinct reason codes. Do not modify legacy
batch failure handling except where needed to safely accept the new mode metadata.

TelemetryRepository is injected into the live execution composition. The runner
owns its bounded writer task's lifetime; the processor invokes repository methods.
Use an independent SQLAlchemy session per write transaction, never the service's
startup/finalization session across async tasks or threads. Blocking driver work
must run in a bounded worker with database-side timeouts; timing out an await must
not leave a background query/thread running indefinitely.

### 2. Supported runtime preparation and final parsing

Live mode directly launches the pinned dedicated executable. Use an application
runtime adapter to validate executable identity, graphics archive, AI content and
its dependency libraries. Reuse verified local cached assets; when provisioning
is needed, use pinned official archive manifests/checksums and public Lab content
helpers behind that adapter. No private Lab function is an acceptable shortcut.
Record the asset manifest/checksums and sanitized effective configuration as
provenance. Extract archives safely into an owned workspace, not arbitrary paths.

Use the existing chosen strategy's AI startup configuration; no new AI algorithm
or commands controlling AI behavior during execution. Live mode must work with the
existing baseline and the existing SimpleAI strategy options. Validate all supplied
configuration before launch and override/reject settings that conflict with runner
ownership: bind addresses, secrets, autosave behavior, auto-restart and reload.

Generate a versioned 13.4 configuration deliberately. Use normal network settings
in the main config, private settings in private config, and admin_password in the
adjacent secrets config. Do not retain the prototype's versionless-config migration
trick. Set dedicated loopback binding, local advertisement, zero minimum clients,
AI multiplayer enabled, threaded saves disabled, monthly autosaves retained, and
pause-on-newgame for the initial readiness barrier. Disable automatic config
rewriting, automatic world restarts and config reload. Exact generated files and
13.4 setting precedence must be verified in integration tests.

The runner alone owns the dedicated process stdin. Its internal lifecycle command
allowlist is pause, unpause, save to a runner-generated destination, and quit.
These are not a public game-control API. AdminObserver may send only Join, Quit
(disconnect itself), UpdateFrequency, Poll and Ping. Do not move RCON into it.
A read-only client is enforced by its interface and packet allowlist: the 13.4
password itself still grants server-admin authority and is not privilege-limited.

The runner uses the observer's Date notification directly for its stopping
condition; database/terminal consumers cannot delay that notification. At normal
completion it pauses via its own stdin, requests a synchronous final save, verifies
the save operation completed, then requests quit and waits for process exit.
Drain stdout/stderr concurrently with bounded storage so pipe pressure cannot
block the process. Do not infer successful saving merely from a fixed sleep.

After exit, FinalResultProcessor uses public openttdlab.parse_savegame on that
same process's final save. Normalize its chunk records/date into the existing
savegame adapter shape and reuse existing metric definitions and artifact format.
It is acceptable to extract a small shared conversion/artifact-writing helper
from the existing adapter, provided batch behavior remains covered and unchanged.
Never call Lab's experiment launcher to parse or regenerate this result.
Live observations cover every company the Admin server reports, but v1 final metric
selection preserves the existing configured experiment's company-0 adapter behavior;
no multi-company aggregation is introduced. A missing required final company is a
finalization failure, not a fabricated zero result.

Persist explicit raw final save and parsed-artifact references/checksums. The
prototype only proved the final monthly-save path, not this new explicit-save
barrier; the production integration test must establish it. A missing/corrupt
requested final save is a finalization failure. An earlier monthly autosave may
be retained as a partial artifact but cannot silently replace the requested final
save for a successful live run.

### 3. Domain types and observation semantics

Use immutable, validated application types. Wire parsing and domain validation
are separate concerns; use exact integers for signed 64-bit money and counts,
never floating-point conversion in live telemetry. Server-reported booleans,
strings and unsigned integers retain their actual protocol meaning.

**LiveExecutionOptions:** startup, handshake, running and shutdown deadlines;
reconnect budget; telemetry cadence; local port policy; bounded persistence
settings. Resolved options and execution_mode belong to execution provenance,
not scenario identity or planning-strategy parameters. Ports/passwords must not
cause duplicate scenario versions or secret-bearing ExperimentConfig records.

**TelemetryObservation envelope:** experiment_run_id; monotonically increasing
sequence per run; connection_epoch; received_at UTC; schema_version; source
(openttd_admin for measurements, live_runtime for lifecycle diagnostics);
protocol_version (nullable before negotiation for diagnostics); kind; optional company_id; optional game_day;
optional date_context_sequence; date_quality (packet_date, preceding_date, unknown);
typed payload. OpenTTD day numbers are authoritative, converted to ISO calendar
only where representable. Initially support game dates in years 1–9999, rejecting
unsupported scenarios before launch rather than silently truncating dates.

Use connection_epoch zero for pre-connection diagnostics; each successfully
established observer transport increments the epoch, including a reauthentication
attempt. Measurements require a positive epoch. Sequence assignment is centralized
within the run and includes diagnostics; do not reset it at reconnect.

Date packets carry their own day. Economy, info and stats do not. Their game_day
is the latest preceding Date on the same connection, with its sequence recorded;
it is a context association, not an atomic server snapshot timestamp. After any
reconnect clear date context until a fresh Date arrives; preserve intervening
observations with unknown date rather than assigning the previous connection's
date. Store wall-clock reception time separately. No synthetic per-packet tick
or generation timestamp is claimed.

| Observation type | Minimum payload and meaning |
|---|---|
| GameDateObservation | Reported game_day; no company ID |
| CompanyInfoObservation | Company wire ID, name, manager, colour, password-protected flag, inauguration year, is_ai; optional known bankruptcy/share fields may be decoded but are not required business metrics |
| CompanyEconomyObservation | cash_balance_gbp, loan_balance_gbp, admin_year_to_date_net_income_gbp, current_quarter_delivered_cargo_capped, two completed-quarter history entries |
| CompanyStatsObservation | Primary-vehicle counts and station-facility counts for train, lorry, bus, plane, ship; each is a separate integer category |
| TelemetryDiagnostic | Finite code, severity, connection epoch, UTC start/end or event time, last known day and bounded sanitized context; used for gap, unsupported data, reset or persistence diagnostics |

Each historical economy entry contains history_offset (1 or 2),
company_value_gbp, performance_score, and delivered_cargo_capped. Preserve offsets
and raw exposed zeros. The protocol does not identify whether a zero-valued history
slot is an actual zero quarter or uninitialized history. Do not invent a validity
flag or claim an inferred quarter predates the company's actual creation. Calendar
period labels derived from date context must be explicitly marked inferred;
missing context means no assigned calendar period. Values at 65535 mean saturation
is possible, not proof that exactly 65535 cargo units were delivered.

Company IDs are zero-based and scoped to a run; they are not global identities.
Preserve every full CompanyInfo observation, including periodic polls to capture
renames. Subscribe to automatic company information and tolerate its associated
new/update/remove packets: record creation/removal as diagnostics and poll full
CompanyInfo after new/update rather than inventing full records from partial
updates. Do not merge history across an observed company-ID removal/reuse.
No new company master table or speculative durable company identity is needed.

Economic meanings are fixed as follows:

| Name/source | Period or measurement kind | Permitted interpretation |
|---|---|---|
| Admin cash_balance_gbp and loan_balance_gbp | Current stock/balance at emission | Balance, not income or accumulated profit |
| Admin admin_year_to_date_net_income_gbp | Current calendar-year-to-date, negative sum of yearly expense categories | Includes construction/vehicle purchases and other categories; not gross transport revenue or pure operating profit |
| Admin current_quarter_delivered_cargo_capped | Current calendar-quarter-to-date; saturating uint16 | Cargo units delivered in that period; not rate, lifetime total or per-route volume |
| Admin history company_value_gbp | Value at a completed-quarter snapshot | Company valuation; not period income |
| Admin history performance_score | Completed-quarter performance score | Score, not currency or utilization percentage |
| Admin history delivered_cargo_capped | Completed-quarter total, potentially saturated | Period quantity; do not sum repeated snapshots |
| Savegame company_money/company_loan | Current balances at final save | Preserve existing final metric names and GBP units |
| Savegame current_period_income/current_period_expenses | Current calendar-quarter-to-date in the pinned 13.4 economy model | Separate signed source fields; preserve signs and names, do not substitute Admin yearly net values |
| Savegame current_period_cargo_delivered | Sum of the save's current-quarter cargo categories | Preserve existing value and unit; its range need not match Admin uint16 saturation |
| Future cumulative metric | Since a specified reset/epoch, if a future source actually supplies it | New explicitly named/source-qualified measure with reset semantics; never fabricated by summing present snapshots |

Publish source, measurement kind, period and sign conventions as typed metric
metadata/registry shared by output and analysis. Existing final metric identifiers
must remain compatible. No generic income, expenses or profit column combines
these sources. Reconciliation may compare same-date balances and unsaturated
cargo with timing qualifications; equality is not guaranteed across sequential
non-atomic observations. Never coerce quarterly and yearly values to match.

Counts are not capacity: train counts represent primary trains, not wagons;
station counts are facility counts and a combined station may count in several
categories. No train length, cargo capacity, per-vehicle expense, route assignment,
construction cost, or operating-cost breakdown is synthesized.

### 4. Lifecycle, deadlines and ownership

The runner has a monotonic internal state progression: preparing, starting,
connecting, running, stopping, finalizing, finished. A terminal reason records
completion, startup_failure, authentication_failure, protocol_failure,
observer_lost, persistence_failure, unexpected_shutdown, timeout, cancelled,
finalization_failure or cleanup_failure. Record the original reason; later cleanup
errors are additional diagnostics, not replacements. No terminal run is reopened.

1. ExperimentService commits a running ExperimentRun with execution mode and a
   unique run artifact directory. For live mode initialize a live-session record.
   If this transaction fails, launch nothing.
2. Runner validates/prepares assets, obtains port leases, creates its private
   workspace and secrets, and launches one dedicated process group with stdin.
3. The generated world starts paused. Readiness requires owned process alive,
   authenticated Protocol v2 and Welcome for the pinned revision/seed/map,
   supported required frequencies, and an initial Date. A listening TCP socket
   alone is not readiness. No company snapshot is required before unpause: AI
   creation may not have progressed yet.
4. Subscribe to daily Date, automatic CompanyInfo and monthly Economy/Stats;
   initially poll all four. The observer also polls full CompanyInfo monthly.
   Runner unpauses, enters running, and records the observed start day and target
   day. These days derive from the configured world start, not connection time.
5. Run until observed game_day reaches configured start_day + duration_days.
   Local scheduling can overshoot; record requested target, last observation and
   actual final-save day. Do not claim tick-exact equivalence to batch mode.
6. Runner executes the save/quit barrier, awaits exit, closes observer, flushes
   queued telemetry within its deadline, and processes the final save. Required
   cleanup completes before returning a result or failure to the service.
7. Commit SimulationRun/final metrics and terminal ExperimentRun together, then
   terminal live summary in that same final transaction. Observation batches were
   already committed independently. Write an atomic sanitized local outcome
   manifest even when terminal database persistence fails.

Defaults: startup 120 seconds (including asset preparation, configurable);
handshake 10 seconds after TCP connection; running wall timeout
max(300 seconds, 5 × duration_days seconds), explicitly configurable and recorded;
reconnect budget 15 seconds with 0.25/0.5/1/2-second capped backoff; heartbeat Ping
at 5 seconds and no response for 15 seconds treated as connection loss. A stalled
game while the heartbeat works is handled by the running timeout, not by assuming
that a missing monthly economy packet means a broken connection. Clock measurements
use monotonic time, never the game date or system wall-clock adjustments.

Shutdown budget: up to 15 seconds for pause/save/quit and graceful exit; then
SIGTERM to owned process group, wait 5 seconds; then SIGKILL and reap within 5
seconds. A forced stop cannot become normal success merely because exit succeeds.
Final parsing and final DB flush each have a bounded 30-second deadline, configurable
for larger saves. Cleanup still runs after any exceeded deadline. The runner owns
all observer/writer/log-reader tasks and cancels/awaits them; no detached tasks or
unbounded executor threads are acceptable.

### 5. Failure and completeness policy

Persist three different facts: experiment outcome (existing status and reason),
process/final-result outcome, and telemetry_status (pending, recording, complete,
incomplete, failed). complete means no known gap/drop in the negotiated observation
coverage interval, all required types received, and all accepted observations
flushed; it does not promise every tick or every game event was observed.

| Condition | Required behavior | Recorded result / CLI |
|---|---|---|
| Startup or bind/asset failure | Stop/reap anything started; close leases, sockets and secrets; never connect to an unrelated server or silently restart the experiment | Experiment failed/startup_failure, no SimulationRun; telemetry failed; exit 1 |
| Authentication failure | No password retries; runner terminates its own process; observer only reports rejection and closes its socket | Failed/authentication_failure; no canonical final result; exit 1 |
| Unsupported protocol/identity or malformed known packet | Fail explicitly; runner stops; preserve sanitized diagnostics; safely ignore unknown packet types and appended fields | Failed/protocol_failure; exit 1 |
| Observer connection loss while running | Observer reports loss and attempts bounded reconnect only under runner policy; new epoch, clear date context, reauthenticate/resubscribe/poll; do not pause/restart the world just to hide a gap | Recovered run may finish succeeded but telemetry incomplete and exit 3; exhausted budget fails/observer_lost and runner stops, exit 1 |
| DB failure before launch | Do not start the process | No run if initial commit never happened; exit 1 |
| Transient telemetry DB failure | Retry the identical batch idempotently with bounded backoff for at most 10 seconds; keep bounded queue and health reporting responsive | If all samples persist and no gap/drop occurred, completeness need not degrade |
| DB failure beyond budget, permanent DB validation error or full queue | Notify runner immediately; runner performs failure shutdown and retains final/partial save where possible; no unlimited spooling or silent dropping | Failed/persistence_failure, telemetry failed; exit 1; local manifest if DB remains unreachable |
| Normal target reached | Runner saves, quits, reaps; observer never initiates process shutdown; parse and commit final result | Succeeded; telemetry complete gives exit 0, incomplete gives exit 3 |
| Missing required observation kinds by completion | Final result may still be valid, but do not claim full live recording | Succeeded with telemetry incomplete/missing_required_types; exit 3 |
| Timeout | Runner attempts bounded partial save, then graceful/forced cleanup; do not relabel as successful completion | Failed/timeout, exit 124 |
| User cancellation/SIGINT | Runner stops; best-effort partial save within shutdown budget, flush what can be flushed, cleanup and record cancellation | Failed/cancelled, exit 130 |
| SIGTERM to supervisor | Same controlled cleanup, distinct signal metadata | Failed/cancelled, exit 143 |
| ServerShutdown/EOF before runner-requested normal stop | Never assume EOF means success; terminate/reap residual owned children and retain diagnostic saves | Failed/unexpected_shutdown, exit 1 |
| ServerShutdown/EOF after runner requested quit | Expected transport termination, but still require process exit and valid final save | Normal finalization, not success by packet alone |
| Final save or parse failure | Preserve available artifacts and raw telemetry; do not populate normal final metric rows from live data | Failed/finalization_failure; no SimulationRun; exit 1 |
| Final DB commit fails | Keep completed final artifact and atomic local manifest; do not falsely report persisted success or rerun simulation | exit 1, outcome persistence_failed locally; DB can remain running until recovery |

Unrecovered fatal live failures have no canonical SimulationRun, matching existing
failed-run behavior. Partial or even technically parseable failure saves remain
explicitly partial artifacts. A recovered observation gap alone does not discard a
valid completed simulation: status succeeded plus telemetry incomplete is deliberate,
and the nonzero completeness exit code makes that visible to automation.

Recovering terminal database state is a narrow, explicit operation, not automatic
simulation resume: given a local outcome manifest and original experiment ID,
validate hashes/configuration, refuse an already conflicting terminal result, and
idempotently persist the recorded outcome/final result. It must not replay the world,
claim missing observations exist, or turn a gap into complete coverage. No new
always-running recovery service is required.

Unexpected supervisor death must not leave a live process running: use an owned
Linux parent-death mechanism in addition to process-group cleanup for catchable
signals, and test it. SIGKILL cannot guarantee final save, DB terminal update or
filesystem cleanup. Retain a run manifest and remove only verified abandoned owned
workspaces on explicit recovery/next startup; never signal a PID from an old file
without verifying ownership and avoiding PID reuse. Such runs remain failed or
unresolved, not silently succeeded.

### 6. Minimal persistence model and migrations

Use PostgreSQL and the existing experiment repository. No new queue service,
company/vehicle/route master tables, or table for each speculative metric.

**experiment_runs additive fields:** execution_mode, non-null default batch;
nullable failure_code; nullable sanitized execution_metadata containing resolved
options, asset manifest, initial/target/actual days and artifact references.
Existing historical rows remain batch. Do not store passwords, environment dumps,
raw command input or secret config contents in metadata.

**live_telemetry_sessions:** experiment_run_id is both primary key and cascading
foreign key, enforcing one session per live ExperimentRun. Fields: telemetry_status;
protocol_version nullable until handshake; started_at/connected_at/ended_at UTC
nullable where not yet applicable; negotiated subscriptions JSON; connection_count;
received_count, persisted_count, unknown_packet_count, gap_count, dropped_count;
last_observed_sequence/day and final_persisted_sequence nullable; process_exit_code;
terminal_reason; bounded sanitized error summary. Record host-local assigned ports
as nonsecret diagnostics only, never as a durable identity. A session row exists
before launch; an experiment can have observations without a SimulationRun.

**telemetry_observations:** composite primary key (experiment_run_id, sequence);
cascading foreign key to live_telemetry_sessions; connection_epoch integer;
received_at timestamptz; source; schema_version; protocol_version nullable for
pre-handshake diagnostics; kind; nullable company_id, game_day,
date_context_sequence; date_quality; payload JSONB. Supported payloads are the
closed typed union specified above, not arbitrary unvalidated dictionaries.
Diagnostic rows share ordering but are not game measurements. No redundant
simulation_run_id: join via existing unique simulation_runs.experiment_run_id after
finalization. No synthetic SimulationRun at startup.

Check constraints: positive sequence/schema version, nonnegative epoch (positive
for measurements); enumerated source/kind/
quality/status/mode; company IDs within the pinned version's valid range when
present; Date rows have no company and their own date; company observations have
company IDs; unknown date quality implies no assigned day/context reference;
payload is an object. Application validation enforces per-kind keys, exact integer
ranges, the five statistics categories and history offsets. JSONB numbers preserve
exact values; downstream queries must not cast money to floating point.

Indexes: existing experiment linkage; observations (experiment_run_id,
received_at, sequence) and (experiment_run_id, company_id, game_day, sequence).
Use sequence as authoritative local receive order, not timestamp uniqueness or
company/date uniqueness. Duplicate observations from repolling are legitimate.
Retry deduplication is solely the identical run/sequence key: an identical persisted
payload is accepted, a conflicting payload is an integrity failure. Repository
read interface uses run ID and an after-sequence cursor with bounded limit and
optional kind/company filter; no web API is required.

Batch writes contain up to 100 observations or flush after 1 second, whichever
comes first, into short transactions. A run-local queue holds at most 1024
observations, including an in-flight retry batch. No dropping oldest/newest to
hide overload. Reserve a diagnostic/control path so a full measurement queue can
still notify the runner. Received/persisted counters and completeness are not
inferred from the last printed sample. Track a bounded diagnostic summary and
persist gaps when storage is available again.

Create an additive Alembic migration following the current experiment-history
revision; include indexes, constraints, defaults and safe backfill. Preserve all
existing ExperimentRun, SimulationRun and ExperimentMetric rows and metric names.
Do not modify legacy logistics tables or create telemetry for old runs. Downgrade
removes only these additions, explicitly documenting telemetry loss; it must not
delete old experiment history. Migration tests must use both repository test
conventions and actual PostgreSQL for JSONB, constraints and concurrent retries.
Update model registration and migration-head expectations during implementation,
without weakening existing migration assertions.

No time partitioning, retention daemon or general schema-version registry in v1.
Deleting an experiment intentionally cascades its live observations/session and
existing final result according to the established history relationship. Artifact
retention is separate: final saves, parsed artifacts and outcome manifests persist;
temporary secret/config workspaces are destroyed after owned processes exit.

### 7. CLI behavior, concurrency and security

Existing run and compare commands retain batch default and current results.
Add --mode batch|live to single-run execution. Live accepts one seed and existing
scenario/strategy choices; no new policy is implemented. compare remains batch-only
and rejects live mode rather than silently creating observed multi-seed jobs.
Record/report execution mode in persisted results and exports; comparison validation
must refuse mixing batch and live runs by default, without changing current batch
summary calculations.

Live options: explicit positive --startup-timeout, --timeout and --shutdown-timeout;
optional fixed --admin-port and --game-port for diagnosis; otherwise use the runner's
leased loopback range. Validate mode-inapplicable flags and invalid/conflicting
ports before launch. Secrets are never CLI flags. --artifact-dir remains supported;
create a unique child directory per experiment ID, preventing one concurrent run
from overwriting another. No automatic rerun after a failure.

Human output: one startup/readiness line, at most one economic/statistics summary
per company per game month, meaningful gap/failure transitions, and a terminal
summary containing experiment ID, execution mode, outcome, telemetry completeness,
final-save date and artifact references. Label yearly net income distinctly from
final quarterly income/expenses. Never print raw packets continuously. Optional
--telemetry-jsonl emits credential-free typed observations with schema/version and
sequence; keep operational diagnostics on stderr and avoid mixed-format stdout.
Terminal rendering is a consumer, never the trigger for stopping or persisting.

Expose the narrow manifest recovery operation as a subcommand; it accepts a local
manifest path and commits no conflicting existing final result. No interactive
prompts are required for ordinary execution or Ctrl-C cleanup. Command help must
state normal-speed live execution, observation completeness exit code 3, and the
absence of batch tick-equivalence guarantees.

Concurrency is between independent run invocations; each runner owns one server.
Use host-local advisory locks for two selected ports and reserve/check the game
TCP and UDP endpoint plus Admin TCP endpoint on loopback. Hold leases for the
whole process lifetime; default configurable range is 39770–39999 with two
distinct ports required. OpenTTD cannot inherit the temporary reservation sockets,
so closing reservations immediately before binding leaves an external-process
race: verify owned process readiness and fail a collision explicitly. Do not claim
allocation is atomic against unrelated programs, kill another process, or retry a
running world under the same ExperimentRun. Fixed ports use the same lease checks.

Each run has a private directory mode 0700 and secret files mode 0600, a fresh
cryptographically random Admin password within the 13.4 maximum of 32 UTF-8 bytes, scoped handles and an owned process group.
Use argv arrays without a shell; fixed lifecycle commands cannot interpolate
arbitrary user input or traversal-prone paths. Resolve artifact paths under the
owned workspace. Avoid secrets in argv/environment where possible: write the
secret file and pass the password in memory to the observer. Redact exception and
log payloads; persist only sanitized config/asset provenance. Release leases only
after exit/kill is confirmed. Shared asset-cache downloads require locking and
atomic verification/publication, but run workspaces and writeable saves are isolated.

Support localhost only in v1. 13.4 Admin authentication is plaintext and inherently
privileged; reject non-loopback binds/connections and public advertisement. Do not
claim TLS or modern secure AdminJoin compatibility. Unknown packets are ignored
with bounded counters, malformed known packets fail, and appended fields are
ignored as allowed by the versioned protocol. Guard receive sizes, string bounds
and auth deadlines. Version 2 alone is not sufficient for accepting another game
release: validate the pinned revision and source-derived layouts too.

### 8. Future extension boundaries

Keep source identification and immutable observation envelopes so a later approved
source can emit vehicle, train-consist, route-throughput or cost-component types.
Such additions require actual source data, identity/time/period semantics and
schema-versioned payloads; do not add empty columns now. Keep route/fleet decisions
in future optimizer/executor components. AdminObserver remains company-level and
read-only. A future source or control channel must not gain authority by being
injected into this observer. Economic evaluation must account for period, capital
versus operating categories and measured capacity before deriving profit or ROI.

## Testing Decisions

Prefer the highest existing seam: ExperimentService with the SimulationRunner
contract, observable repository state, CLI outcomes and returned SimulationResult.
Exercise LiveSimulationRunner through that contract using a controlled process/
Admin peer and injected clock/runtime adapter. Do not assert private helper calls,
thread choices, table write ordering, or copied implementation logic. Two focused
supporting seams are justified: wire decoding fixtures and real repository/migration
integration. Separate isolated tests for every named architectural box are not a
requirement.

Prior art: existing fake-runner service tests verify persisted success/failure;
the injected Lab callable verifies pinned launch configuration and final gzip
artifact; experiment migration tests verify additive/reversible schema changes;
the opt-in PostgreSQL tests create isolated schemas; the real OpenTTD test is
opt-in. Reuse those conventions and fixtures rather than adding a new harness.

Required test groups:

1. **Batch regression:** unchanged default routing to Lab, pinned AI/seed/duration,
   no Admin activity, same final metric names/signs/artifacts, existing multi-seed
   comparison behavior and unchanged failed-run history. Mode isolation must not
   impose live sleeps/timeouts on the null-driver path.
2. **Production lifecycle contract:** normal paused startup/handshake/unpause,
   target-day save barrier, owned-process exit, final result and DB linkage;
   startup/auth/version/bind failures; unexpected shutdown; timeout and signals;
   owner death; cleanup after each error. Observer cannot emit RCON/control packets
   or invoke shutdown; a Date notification can cause only the runner to stop.
3. **Wire and semantics:** source-derived 13.4 Protocol/Welcome/Date/Info/Economy/
   Stats fixtures; signed negative money and annual net income; leap-year-zero
   conversion; fragmented/coalesced TCP, truncation, EOF, bounded lengths,
   unknown/appended fields, supported frequency masks; quarter/year boundaries,
   zero history, saturated cargo, vehicle/facility category order; no invented
   wagon counts, expense breakdown or cumulative values.
4. **Observation coverage:** reconnect epochs, resubscription, initial repolls,
   null date context before first Date, gaps retained after recovery, non-atomic
   packet timing, company ID reuse/removal diagnostics, missing required types,
   stable sequence ordering, bounded queue/console behavior and heartbeat timing.
5. **Persistence:** PostgreSQL exact signed values in typed JSONB, foreign keys,
   indexes, idempotent same-batch retry, conflicting sequence failure, duplicate
   same-day samples retained, isolated concurrent runs, rollback and bounded
   retries, queue exhaustion, final DB outage and manifest recovery without a
   second simulation. No false persisted-success message during DB outage.
6. **Migrations:** upgrading existing populated history keeps rows and names;
   batch backfill is correct; downgrade only removes telemetry additions;
   constraints/model metadata agree with the migration; unrelated tables unchanged.
7. **CLI/security:** mode/flag validation and exact exit codes, output labeling,
   JSONL framing, redaction, file permissions, forbidden binds, malicious paths,
   cache/port races and proof all sockets/tasks/processes/leases are released.
8. **One opt-in real production smoke test:** pinned 13.4/7.1 and existing SimpleAI
   road-only configuration, seed 17, 120 days, disposable PostgreSQL schema. Start
   via the production dedicated launcher with no Lab private interception. Confirm
   live DB observations are queryable while the owned process is still running,
   receive all required types and at least one completed-quarter history, then
   perform explicit final save/quit/public Lab parsing and assert linkage/cleanup.
   Validate fields and invariants, not exact AI cash values or wall time. A short
   concurrent two-run test may use controlled peers/processes; do not re-run a
   twenty-run comparison merely to test telemetry.

During later implementation, use TDD at these seams, run focused tests/typechecking
as changes land, run the full existing suite once at completion, then perform the
requested implementation review. Real simulations remain opt-in; this specification
creation itself runs none and creates no migrations or application code.

### Production acceptance criteria

- [ ] Existing run/compare defaults execute the existing fast batch path; history and metrics remain compatible.
- [ ] Live mode launches exactly one owned dedicated process using pinned verified assets and no private Lab launch interception or replacement binary.
- [ ] Live and batch mode provenance are explicit, and mixed-mode comparison is rejected by default.
- [ ] LiveSimulationRunner alone owns ports, secrets, readiness, deadlines, save/quit, signaling, cancellation and cleanup.
- [ ] AdminObserver is restricted to observation/authentication/connection maintenance; packet tests forbid RCON and other game-control messages.
- [ ] Protocol v2 and correct Welcome identity are required; required update frequencies are negotiated before running.
- [ ] Date, CompanyInfo, CompanyEconomy and CompanyStats become typed, persisted observations during the same real process's lifetime.
- [ ] The production real test receives meaningful changing values and completed-quarter data without asserting prototype-specific financial results.
- [ ] Yearly Admin net values, quarter-scoped save metrics, current balances, history values and any future cumulative series cannot be confused by names or metadata.
- [ ] No route, consist, wagon, capacity or separate cost metrics are invented from Admin counts.
- [ ] Observations link to the existing ExperimentRun before a final SimulationRun exists; the final result links through that same run exactly once.
- [ ] Explicit final save succeeds after a runner-owned stopping barrier, and the public Lab parser plus existing conversion produce the final SimulationResult/artifact.
- [ ] A final-save date later than the requested target is recorded honestly; an older autosave is never silently substituted for successful live finalization.
- [ ] Successful simulation with recovered gaps reports telemetry incomplete and exit 3; fatal observation/storage failures follow the specified table.
- [ ] All listed startup, authentication, loss, DB, timeout, cancellation and shutdown cases have externally observable tests and bounded cleanup.
- [ ] Queue/database backpressure cannot indefinitely block supervision; retries are bounded/idempotent and overload is visible.
- [ ] Concurrent runs isolate ports, files, IDs and secrets; collisions cannot attach an observer to another run or kill an unrelated process.
- [ ] Passwords never appear in CLI output, argv, stored metadata, final artifacts or exception reports; loopback and permission checks pass.
- [ ] Cancellation and supervisor death leave no live owned OpenTTD process; resource/task/thread cleanup is verified, with unavoidable SIGKILL artifact limits documented.
- [ ] Database outage retains an outcome manifest/artifacts; recovery cannot rerun the simulation or overwrite a conflicting result.
- [ ] Additive migration preserves existing populated history and passes actual PostgreSQL checks; unrelated logistics workflows are untouched.
- [ ] Production has no imports from the prototype and no private OpenTTDLab launcher references; selected evidence/fixtures remain available after prototype runtime removal.

## Out of Scope

Kafka, Redis, event-bus frameworks, a web UI/dashboard, Textual UI, route construction
or control, interactive AI control, GameScript bridges, realtime optimization,
replanning, machine learning, broad operational-logistics refactors, and changing
the existing batch economic evaluation. No implementation of vehicle-level data,
train wagon/consist data, per-route throughput, construction/operating-cost
breakdowns, or long-term profitability evaluation is included.

No remote Admin service, TLS infrastructure, general-purpose Admin/RCON client,
multi-world continuation/restart, live observer fan-out platform, automatic
simulation retries, telemetry retention service, or schema redesign for all
possible future sources. One live invocation owns one world; a server NewGame or
identity reset is an unsupported world transition and fails the run rather than
merging different worlds into one time series.

## Further Notes

### Evidence and prototype disposition

The completed prototype's [report](../../prototype/live_admin/REPORT.md),
[protocol/config research](../../prototype/live_admin/README.md), and
[credential-free proof](../../prototype/live_admin/proof.json) establish feasibility:
134 typed observations during one process, 121 Date packets, five Economy and five
Stats samples, 277.215 seconds, final save dated 1950-05-01, successful cleanup.
Final live cash/loan were 96732/130000; Admin annual net income was -33268 while
save current-period income/expenses were 1239/-390. Those unequal values are evidence
for keeping semantics separate, not a discrepancy to normalize away.

The local capture ref is codex/prototype-live-admin at
2b6e714c2749108a79b7bec26c4c79d3f71663ff, based on devmodule2. It is local, not a
published GitHub link, and depends on the supplied workspace's existing SimpleAI
strategy work. Do not present the prototype as a standalone production dependency.

During implementation, remove the prototype's launch monkeypatch, subprocess proxy,
hardcoded run supervisor, lifecycle RCON calls, fixed scenario/date, legacy password
injection and ad hoc file/console pipeline once their supported replacements pass.
Remove the regression test that tests the private interception: it verifies a
technique production forbids. Do not ship a fallback flag invoking that launcher.

Retain the report, source references, compact credential-free evidence and artifact
hashes as archived research. Adapt the signed-economy, quarter/statistic layout,
date, fragmentation, unknown/trailing packet, authentication failure and socket
cancellation tests into production contract fixtures. Preserve real decoded
samples as labeled captured examples; synthesize byte fixtures from pinned source
where original raw packets were not captured. Never call reconstructed bytes a
captured wire trace. Keep raw/parsed proof saves locally if available; no secrets
or generated bulk artifacts need to enter version control. Retain the existing
batch adapter and result semantics throughout.

### Primary protocol and adapter references

All Admin wire decisions target the 13.4 source, not today's protocol:
[Admin guide](https://github.com/OpenTTD/OpenTTD/blob/13.4/docs/admin_network.md),
[packet declarations](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/tcp_admin.h),
[actual senders/receivers](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/network_admin.cpp),
[serialization](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/packet.cpp),
[config migration](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/settings.cpp),
[dedicated driver](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/video/dedicated_v.cpp),
and [OpenTTDLab v0.0.75](https://github.com/michalc/OpenTTDLab/blob/v0.0.75/openttdlab.py).
The public savegame parser was confirmed in the installed pinned source; the
production launcher, pause/save barrier, reconnection and DB behavior specified
here are requirements for the later implementation, not claims already proved
by the prototype.
