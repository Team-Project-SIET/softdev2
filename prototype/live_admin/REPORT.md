# Live Admin Network integration proof

## Verdict

**FEASIBLE.** On 2026-09-24, one real simulation delivered independent live
Admin telemetry and then completed the existing OpenTTDLab final-save pipeline.
Elapsed time: **277.215 seconds**, Lab return code **0**. Credential-free machine
readable evidence is in [proof.json](proof.json).

Received: ServerProtocol **103 ×1**, ServerWelcome **104 ×1**, Date **107 ×121**,
CompanyInfo **114 ×1**, CompanyEconomy **117 ×5**, CompanyStats **118 ×5**,
RconEnd **125 ×1**, ServerShutdown **106 ×1**. All 134 parsed typed observations
were recorded while the Lab subprocess was still running. Protocol version 2
advertised the required polling/subscription frequencies.

| Game date | Company | Money | Loan | Admin yearly net income | Vehicles | Station facilities |
|---|---:|---:|---:|---:|---:|---:|
| 1950-01-01 | 0 | 100000 | 100000 | 0 | 0 | 0 |
| 1950-02-01 | 0 | 17390 | 50000 | -32610 | 5 | 2 |
| 1950-03-01 | 0 | 17533 | 50000 | -32467 | 5 | 2 |
| 1950-04-01 | 0 | 95908 | 130000 | -34092 | 5 | 4 |
| 1950-05-01 | 0 | 96732 | 130000 | -33268 | 5 | 4 |

All five vehicles were lorries; all four final facilities were lorry stations.
April's completed-quarter record reported company value **8463**, performance
**32**, and delivered cargo **84**. May's current-quarter delivered cargo was **63**.

**Final savegame processing succeeded:** snapshot **1950-05-01**, savegame version
**302**, cash **96732 GBP**, loan **130000 GBP**, current-period income **1239 GBP**,
expenses **-390 GBP**, delivered cargo **63**. The existing adapter produced
`artifacts/live-admin-proof/experiment-1.json.gz`. Cash, loan and delivered cargo
agree with the final live sample; Admin yearly net income and savegame quarterly
income/expenses are intentionally different measures.

**Cleanup succeeded:** ServerShutdown received, socket closed, Lab returned
normally, owned process group gone, Admin port **57231** and game port **41639**
closed. The run used `-D127.0.0.1:41639` and `server_admin_port=57231`.

## What was exercised

One OpenTTD process, launched by **OpenTTDLab 0.0.75**, observed by a separate
Python asyncio Admin listener. Pinned **OpenTTD 13.4**, **OpenGFX 7.1**,
**Python 3.14.6**, seed **17**, 256×256 temperate map, starting **1950-01-01**,
**120 game days**, existing SimpleAI road-only strategy. AI content ID
`534d504c`, MD5 `b3137bbd0c73641cf510ead06e36dab6`, parameters
`use_trains=0,use_roadvehs=1,use_aircraft=0`.

The initial wrapper setup attempt failed before any OpenTTD launch because its
subprocess proxy omitted `STDOUT`. The corrected proxy has a regression test.
The prelaunch failure is separately recorded under
`artifacts/live-admin-prelaunch-failure`. Only **one real simulation** was run;
no comparison batch or real integration test was launched.

## Integration answer

OpenTTDLab writes an ephemeral config and AI startup script, launches a Pool
worker, and blocks on `subprocess.check_output` until OpenTTD exits. For 13.4 it
then parses monthly autosaves. Its supplied config string is usable, but its
stock null driver never starts a server. Therefore **an unchanged Lab launch plus
configuration alone is insufficient**.

The prototype temporarily wraps Lab's private `_run_experiment` callable inside
its own process. Only that worker's launch reference is substituted, changing the
null driver to `-D127.0.0.1:GAME_PORT`. The existing AI initialization, monthly
savegame generation/parsing, typed result conversion and gzip artifact writer
remain in use. No OpenTTDLab fork or installed-package modification. The listener
runs independently in the supervising process, and issues `quit` at day 120 to
replace the null driver's tick-based exit. Dedicated mode is paced normally.

Exact config, source references, framing, authentication and frequency details are
in [README.md](README.md). Required settings are nonempty `network.admin_password`
and `network.server_admin_port`, with actual server startup via `-D`. This proof
also sets local advertisement, zero minimum clients, AI multiplayer enabled, and
loopback binding. Password is randomly generated per run, injected only into the
mode-0600 temporary config, and excluded from result configuration. The versionless
Lab config activates 13.4's legacy settings-loading path; modern versioned configs
use `secrets.cfg` for the password.

Authentication is 13.4's plaintext AdminJoin, followed by ServerProtocol version
**2** and ServerWelcome. The client checks revision, seed, dedicated mode and the
server-advertised update-frequency masks. It subscribes to daily Date, automatic
CompanyInfo, monthly Economy and Stats, plus initial polls. Unknown packet IDs and
appended fields are ignored safely; unsupported protocol versions fail closed.

## Libraries and validation

No external Admin library used. The inspected `python3-openttd` uses removed
asyncio APIs; maintained `pyOpenTTDAdmin` has legacy login but its inspected source
misreads signed monetary values, drops station counts, and needs unknown-packet
and receive-lifecycle adaptation. A narrow standard-library client was less work.
The exact inspected revisions and primary-source links are recorded in README.

Eight synthetic tests cover signed economy values, quarter/station layouts,
Protocol/Welcome/CompanyInfo/date parsing, appended/unknown data, fragmented and
coalesced packets, truncation/EOF, invalid frame lengths, failed readiness,
authentication rejection, listener cancellation/socket cleanup, launch arguments,
and restoration of the worker's subprocess reference. Existing experiment tests
remain unmodified; the real integration test is skipped unless explicitly enabled.

## Scope, limitations and next phase

* The application and database schema are unchanged. This proof calls the existing
  simulation adapter directly and does not insert a PostgreSQL experiment row.
* Private Lab launch interception is a fragile 0.0.75-specific seam. It changes
  driver and stopping semantics, so this does **not** establish bit-for-bit or
  tick-for-tick equivalence with stock accelerated batch runs.
* Final result is the latest monthly save that Lab normally processes, not a new
  custom telemetry-derived result. Live updates and saves are separate snapshots.
* `income` is year-to-date net expense-category total, including capital costs.
  No separate expense/gross-revenue field exists in these Admin packets.
* CompanyStats counts primary vehicles and station facilities. It cannot describe
  train wagon counts, consist capacity, routes, or cargo-by-route throughput.
* Only localhost, one company, one version and one simulation were proven. No
  reconnect/backpressure/load testing, remote security solution, or long-run
  reliability claim. The free-port selection has a short bind race.
* Samples join the most recently received date, economy and stats for this one
  company; the protocol does not provide an atomic multi-packet snapshot.

**Throw away:** the private-function/module monkeypatch, hardcoded scenario and
termination date, temporary password injection, ad hoc launcher/JSONL evidence
writer, and prototype console presentation. Do not promote this module directly
into production.

**Retain as reference:** the proof evidence, version-pinned packet layouts and
field semantics, config migration finding, library evaluation, independent
observer/lifecycle result, and targeted wire-format test fixtures. Retain the
working batch adapter and savegame parser.

**Recommended production architecture, not implemented:** keep the existing batch
experiment path. Add a deliberate supervised live-server launch option behind a
small runner interface (prefer an upstream-supported Lab launch hook over private
patching). Let one owner manage OpenTTD startup, readiness, timeout and exit;
attach a version-aware Admin observer for immutable typed observations tagged by
run ID and simulation date. Keep final savegame extraction as the independent
completion/evaluation path. Reconcile metrics by period before economic analysis.
Choose storage only after defining those metrics and missing data requirements.
Future RoutePlan execution/optimizer components should remain separate from this
read-only observer; Admin's limited company totals are not sufficient route/fleet
state for them. No such architecture or optimization/control system was built here.

## Files and preservation

Only `prototype/live_admin/` was created by this task:

* `protocol.py`: minimum typed packet/framing subset.
* `lab_seam.py`: isolated dedicated-mode Lab launch wrapper.
* `run.py`: one-run supervisor and live listener.
* `test_protocol.py`: focused synthetic checks.
* `README.md`: reproduction/config/protocol research and primary sources.
* `REPORT.md`: verdict, findings and next-phase recommendation.
* `proof.json`: compact credential-free evidence copied from the real run.

Runtime artifacts live in ignored `artifacts/live-admin-proof/`: typed
`telemetry.jsonl`, `evidence.json`, `launch.json`, `final-result.json`, Lab console
log, and the existing `experiment-1.json.gz` savegame artifact. The shared binary/AI
cache is reused. Other already-modified/untracked files on `devmodule2` were left
untouched. The existing SimpleAI strategy was already present as workspace work
in progress when this task began; a prototype-only Git capture depends on it.
