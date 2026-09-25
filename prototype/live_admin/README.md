# Throwaway: live Admin telemetry alongside OpenTTDLab

Question: can Python receive live telemetry from the same OpenTTD process whose
monthly saves are subsequently processed by the existing experiment adapter?

This is a Linux technical integration prototype. No production application or
schema changes. It uses the current `devmodule2` workspace's existing
`SimpleRoadOnlyStrategy` and `OpenTTDLabRunner`; its purpose is evidence, not reuse
as an application service. The final verdict and real values are in `REPORT.md`.

## Run

From the repository root, with the existing uv environment:

```bash
uv run python -m prototype.live_admin.run
uv run pytest prototype/live_admin/test_protocol.py
uv run ruff check prototype/live_admin
```

For this sandbox, use `UV_CACHE_DIR=/tmp/softdev2-uv-cache` before `uv` because the
normal uv cache is read-only. The simulation takes approximately five minutes.
The supervisor refuses to overwrite `artifacts/live-admin-proof`, preventing an
accidental second experiment. Archive that directory explicitly before any
future deliberate run. No database access is needed for this integration proof.

## The seam

Inspected installed OpenTTDLab **0.0.75**, SHA-256 of `openttdlab.py`:
`8a210f78e5fa6556d24539867d3e9efa6959ee23cfa6d730e45afbc173bfe0f7`.
Its `run_experiments` downloads/verifies pinned binaries and AI, creates a
TemporaryDirectory, writes `game_start.scr` with `start_ai`, writes user config
followed by `[gui] threaded_saves=false`, monthly autosaves, and
`keep_all_autosave=true`. It runs `_run_experiment` in a multiprocessing Pool,
blocks on each result, and parses all monthly saves for OpenTTD 13.4.

The stock launch is:

```text
openttd -g -G SEED -snull -mnull -vnull:ticks=74*DAYS -c GENERATED_CONFIG
```

The null video driver has a bounded simulation loop but never sets the dedicated
server flags or starts network listeners. Config injection alone is insufficient.
Using `-D` *before* `-vnull` would not work: the last video-driver selection wins,
and the dedicated driver's MainLoop is what enables server mode.

`lab_seam.py` replaces the private `_run_experiment` callable only in the isolated
Lab worker. That callable temporarily substitutes the module's subprocess
reference, delegates to the original implementation, then restores it. Only the
launch is altered: remove `-vnull:ticks=...`, append
`-D127.0.0.1:GAME_PORT -dnet=0 -x`. No installed files or OpenTTDLab fork are used.
`-x` disables config saving. Dedicated mode advances at normal game speed; the
stock null-driver tick limit is replaced by a Date-based exit at day 120.

The parent Python process concurrently runs the asyncio listener. It retries
localhost connections while Lab extracts binaries and generates the world, then
requires Protocol and Welcome within the handshake deadline. It subscribes to
daily Date, automatic CompanyInfo, and monthly CompanyEconomy/CompanyStats,
validating the advertised frequency masks; it also polls all four initially.
Only at the target date does it issue Admin RCON `quit` for lifecycle completion.
It then awaits normal Lab save parsing and the existing adapter's gzip artifact.
No route, fleet, economic, or AI control is performed by the listener.

## Configuration and authentication

Generated configuration (ports are allocated per run):

```ini
[game_creation]
map_x = 8
map_y = 8
starting_year = 1950
[network]
server_name = Live telemetry prototype
server_admin_port = ADMIN_PORT
server_game_type = local
min_active_clients = 0
admin_password = EPHEMERAL_RANDOM_VALUE
[ai]
ai_in_multiplayer = true
```

OpenTTDLab appends its existing GUI/autosave section. The launch's
`-D127.0.0.1:GAME_PORT` binds both network listeners to loopback. There is a small
port-allocation race between selecting a free port and OpenTTD binding it; server
identity and authentication checks prevent accepting an unrelated endpoint.

**13.4 config-version detail:** Lab's generated config has no `[version]`.
`settings.cpp` therefore loads the pre-private/secrets format, including
`admin_password` from `[network]` in that same file. A normal modern config with
`ini_version >= 1` must put that password in `[network]` in adjacent `secrets.cfg`;
private bind lists live in `private.cfg`. Do not copy this legacy injection
technique into a production config manager.

The random password is injected only into the ephemeral generated config with
mode 0600, never into the application ExperimentConfig or recorded command.
13.4 authentication is legacy AdminJoin (type 0): NUL-terminated password,
application name, application version. Protocol (103) then Welcome (104) confirm
authorized access. This is plaintext TCP, scoped here to loopback; modern secure
AdminJoin/encryption must not be assumed to exist in 13.4. No RCON password is
needed once Admin authentication succeeds. The listener sends AdminQuit on
cleanup when the transport is still writable.

## Verified packet layouts and semantics

All integers are little-endian. Frame: uint16 total length including header,
uint8 packet type, payload. Strings are NUL-terminated UTF-8. Receive uses
`readexactly`, bounds lengths, and tolerates fragmented/coalesced TCP frames.
Unknown packet types and trailing fields are ignored. Truncated known packets,
server rejection, unexpected shutdown, or unsupported protocol versions fail
explicitly. This client accepts only advertised protocol **2**.

| Packet | ID | Parsed fields |
|---|---:|---|
| ServerProtocol | 103 | uint8 version; boolean-delimited uint16 update/frequency pairs |
| ServerWelcome | 104 | name, revision, dedicated flag, legacy map-name, seed, landscape, start date, map dimensions |
| Date | 107 | uint32 day number from 0000-01-01 (year zero is leap) |
| CompanyInfo | 114 | ID, company/manager names, colour, password flag, inauguration year, AI flag, bankruptcy quarters, four share owners |
| CompanyEconomy | 117 | ID, signed 64-bit money/loan/yearly net income, current-quarter delivered cargo, two completed-quarter records (value, performance, delivered cargo) |
| CompanyStats | 118 | ID; five uint16 vehicle counts and five uint16 facility counts: train, lorry, bus, plane, ship |

Read the sender, not only the header comments: 13.4 CompanyInfo sends bankruptcy
and share data beyond the fields documented in its header. Economy `income` is
minus the sum of this year's expense categories, including construction and
vehicle purchases; it is not gross revenue or current-quarter operating profit.
There is no independent expenses field. Cargo counters saturate at 65535.
Vehicle counts count primary vehicles, not individual wagons/consist capacity;
a multi-facility station can contribute to several facility counters. Company IDs
are zero-based wire IDs, so the first AI is company 0.

UpdateFrequency uses uint16 update type + uint16 frequency. Poll uses uint8 update
type + uint32 parameter; `0xFFFFFFFF` requests all companies for CompanyInfo.
Economy and Stats polls always return all companies in 13.4.

## External library investigation

No external Admin library was installed or added as a project dependency.

* [python3-openttd at e23bd94](https://github.com/horazont/python3-openttd/tree/e23bd94a52e533c1ee7d5f9be0d7a610fbc3536f)
  last commit inspected: 2021-08-15. Its protocol/client uses `asyncio.coroutine`
  and `asyncio.Event(loop=...)`, incompatible with the pinned Python 3.14 runtime.
* [pyOpenTTDAdmin at 8b23207](https://github.com/liki-mc/pyOpenTTDAdmin/tree/8b23207f67a64ee0b965a7d4e56f6c85d51d8eca)
  last commit inspected: 2026-06-12. Legacy password join exists, so it is not
  inherently restricted to modern OpenTTD. However `packet.py` parses income and
  money unsigned, CompanyStats discards station counts, and unknown packet IDs
  raise via enum/dictionary lookup. Its synchronous receive/auth path also needs
  EOF/partial-frame handling work, and installation builds a crypto extension
  unnecessary for 13.4. Fixing/wrapping these concerns did not materially reduce
  this narrow prototype's work. This is a scoped source evaluation, not a claim
  that every available library was exhaustively tested.

## Primary sources inspected before implementation

Pinned OpenTTD tag **13.4**, commit
`7e457a367e67f4e1b7d28ebd769e3a649ea60175`:

* [Admin protocol guide](https://github.com/OpenTTD/OpenTTD/blob/13.4/docs/admin_network.md)
* [tcp_admin.h](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/tcp_admin.h)
* [Actual packet senders/receivers](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/network_admin.cpp)
* [Packet serialization](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/packet.cpp)
* [Protocol version and packet limits](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/core/config.h)
* [Dedicated driver](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/video/dedicated_v.cpp)
  and [null driver](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/video/null_v.cpp)
* [Launch option handling](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/openttd.cpp)
* [Listener startup](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/network.cpp)
* [Config version migration](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/settings.cpp)
* [Password settings](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/table/settings/network_secrets_settings.ini)
* [Vehicle/station count semantics](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/network/network_server.cpp)
* [Date conversion](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/date.cpp)
* [OpenTTDLab 0.0.75 source](https://github.com/michalc/OpenTTDLab/blob/v0.0.75/openttdlab.py)

## Lifecycle and limits

Readiness is bounded (90 seconds), handshake bounded (10 seconds), whole proof
bounded (600 seconds), and launched OpenTTD has a 540-second backstop. The parent
awaits the listener directly, closing the socket in `finally`; no background
listener threads/tasks are left. A separate process session lets it terminate
only its own Lab/OpenTTD process group on failure/cancellation. Normal completion
awaits Lab first. Evidence checks both ports closed and group disappearance.

This does not prove reconnection, large-company loads, remote transport, arbitrary
versions, tick-equivalence with the batch runner, or database ingestion. Monthly
save snapshots and live packets have different observation timing. Console output
joins the most recently seen date/economy/stats for this one-company experiment;
it is not a transactional multi-company snapshot. The supervision and monkeypatch
are deliberately version-specific. The prototype has no persistence schema,
telemetry service, optimizer, executor, or event bus.
