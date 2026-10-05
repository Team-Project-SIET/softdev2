# OpenTTD 15.3 one-launch ACK proof procedure

**PRELAUNCH ONLY — not executed.** `CONTEXT.md` remains the local architecture
 authority. The next real attempt requires separate explicit authorization for
exactly one gameplay launch and one bridge request. This is communication only:
P05, P06, P07, P08 extraction, construction, vehicles, orders, terrain and finance
are outside this proof. No real world or live AdminPort was used in preparation.

## Frozen preparation

Entry point: `python -m app.simulation.openttd.proof prepare`.
It hashes the explicit executable without running it, generates an isolated
owned workspace, stages verified assets and the existing bridge, binds then
releases local endpoint reservations, and writes PRELAUNCH evidence. There is no
process/connection call in preparation. It must not be rerun over an existing
preparation directory.

Default preparation directory:
`artifacts/runtime/openttd-15.3-real-ack-attempt1-prelaunch/`.
The future attempt directory is
`artifacts/runtime/openttd-15.3-real-ack-attempt1/`, claimed once at execution.
PRELAUNCH.json lists every expected future evidence file. No fabricated runtime
logs, responses, receipts, or success evidence are created during preparation.

The executable is pinned to the supplied OpenTTD 15.3 path and SHA-256. Its
version authority before launch is the prior version inspection plus the exact
binary content identity. Native Welcome must independently report `15.3`.

## Graphics and script identity

Official [OpenGFX download/checksum page](https://www.openttd.org/downloads/opengfx-releases/latest):
release **8.0**; archive source
`https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip`;
SHA-256 `43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be`.
The verified project cache is `artifacts/runtime/verified-assets/`.
The ZIP contains `opengfx-8.0.tar`. Safe extraction rejects links, traversal,
duplicate files, unexpected layouts and excessive sizes. All six descriptor
entries must exist and pass native data-section MD5 checks. Container-v2 GRF
MD5 covers the header plus data section, not the whole sprite file. Full SHA-256
of each extracted file and descriptor metadata are retained separately.

The set is staged under workspace `baseset/OpenGFX/`. OpenTTD scans baseset
subdirectories; config explicitly selects OpenGFX. This establishes static
completeness, not a native load claim. Future success additionally requires the
native `Using the OpenGFX base graphics set` diagnostic and no missing/corrupt
asset errors.

The unchanged `NoMutationBridge` version 1 package targets API **"15"** and
supports only protocol-1 `ping` / `ack`. Preparation freezes info.nut/main.nut
hashes and the complete package digest. `[game_scripts] NoMutationBridge =`
selects it automatically for the new world. No save is loaded and no GUI is used.
The bridge's Start loop stays alive; no gameplay mutation API is present.

## Isolation and credentials

Workspace root is mode 0700. All config, save/autosave, package/library, baseset,
logs, HOME and XDG paths are isolated. Normal `~/.config/openttd` and
`~/.local/share/openttd` are forbidden before any preparation write.
The server binds only `127.0.0.1`.

A cryptographically random X25519 key is generated. Its private 32 bytes are stored
only in workspace `.admin-secret`, mode 0600. They are excluded from all evidence,
source hashes, manifests and console output. Evidence records the derived public
key and its SHA-256. private.cfg contains exactly that `[admin_authorized_keys]`
entry. secrets.cfg has an empty Admin password, so PAKE/password fallback is not
configured. Insecure login remains false. Key permissions, owner and derived
public identity are rechecked before a future launch. The secret is removed on
failure or cleanup, and in-memory references are dropped.

## World, endpoints and argv

New world: seed **42**, map **64×64** (map_x/map_y 6), temperate climate,
starting year **1950**, terrain generator 1, zero AI competitors. No special
industry or planner scenario is needed. New-game pause is disabled and
min_active_clients is zero so the GameScript can run without a game client.
Autosave/config writes are disabled.

The exact ports and workspace path are in PRELAUNCH.json. Future argv is:

```text
/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd
-D127.0.0.1:<game-port> -c <workspace>/openttd.cfg
-x -X -g -G 42 -dscript=3,grf=1,net=3
```

`-D` selects the **game** endpoint; `server_admin_port` independently selects
AdminPort. Game TCP + UDP and Admin TCP are reserved on loopback with reuse
options disabled. They are released after preparation, then the exact frozen
ports are re-reserved immediately before execution. Occupied/TIME_WAIT ports
fail PRELAUNCH with zero launches; the harness does not substitute ports.
OpenTTD cannot inherit these reservations: they must be released just before
Popen. This unavoidable handoff race is handled by failure, not a retry.
A pre-existing process using the pinned executable blocks the attempt; the
harness never kills unrelated processes.

## Packet-driven gates and one request

The future native adapter owns launch, logs, stdin and the secure connection.
It checks process health during bounded TCP readiness polling (30 seconds).
Refused connections are readiness probes; once connected, authentication is
attempted only once under the secure transport's 10-second deadline.

The secure transport enforces AUTH_REQUEST → AUTH_RESPONSE → ENABLE_ENCRYPTION
→ encrypted Protocol → encrypted Welcome. The proof then validates ACTIVE,
protocol 3, revision 15.3, dedicated mode, seed, dimensions, climate and start day.
GameScript traffic cannot pass before these gates.

Registration sends update type 9 / AUTOMATIC mask 64, then an ordered AdminPing.
15.3 defines no subscription ACK. A matching encrypted ServerPong confirms that
the server processed the preceding subscription without rejecting it; it is
not a fictitious update-registration packet. Only then is the one proof request
sent. The frozen bridge has no separate alive notification: **its correlated ACK
establishes the BRIDGE_ALIVE gate**, reception and script execution. A timer or
absence of a crash never establishes that gate.

Exact canonical request (digest recorded in PRELAUNCH.json):

```json
{"protocol":1,"request_id":"openttd15-real-ack-001","type":"ping"}
```

The ACK deadline is 15 seconds. Existing strict envelope validation and exact-ID
correlation produce an immutable CommunicationReceipt with request/response
SHA-256 values. There is one request attempt, no resend and no mutation command.
Polling delays only pace connection probes; they never prove completion.

## Execution after separate authorization

Only the separately authorized next task may invoke:

```sh
.venv/bin/python -m app.simulation.openttd.proof run --authorize-one-launch
```

The flag is an explicit operator action, not automatic permission from this
preparation. The harness verifies the PRELAUNCH manifest, source/content hashes,
credentials, official graphics identity, binary and endpoint availability before
claiming attempt1. All runtime-critical OpenTTD adapter Python files, package
files, dependency lock/metadata and the native Monocypher binding are frozen,
along with staged config/assets. Private-key bytes/hashes are excluded.
Source/content hashes are collected again after cleanup and must match exactly.
No source edits are permitted during the attempt.

Success requires one launched gameplay process; the pinned binary/version;
complete verified graphics with native load evidence; a running frozen bridge;
secure authentication/encryption; validated Protocol/Welcome/map identity;
confirmed subscription barrier; exactly one request and correlated ACK; matching
receipt digests; no script/protocol errors; graceful shutdown attempted; process
reaped; and no process using the pinned executable remaining. None is waived.

## Failure, evidence and cleanup

PRELAUNCH failure retains preparation/failure evidence and stops with zero
launches. POST-LAUNCH failure retains available stdout/stderr, packet/envelope
metadata, response, source hashes and lifecycle evidence. Failed attempts receive
no successful proof receipt. Attempt1 cannot be invoked again once claimed;
attempt2 requires separate explicit authorization and preparation.

Cleanup independently attempts encrypted AdminQuit/connection close, console
`quit`, bounded wait, SIGTERM, kill only if necessary, and reap. Observed quit,
signal, kill and reap events are recorded. A session-close error cannot bypass
process cleanup. Logs are closed, evidence copied and private credentials removed.
The workspace is removed only after process reaping is established and evidence
retained; uncertain cleanup retains it and fails the proof. Cleanup is idempotent.
`artifact-manifest.sha256` hashes sorted public evidence files deterministically.

Controlled tests use synthetic graphics, fake processes and encrypted in-memory
peers, labeling all simulated evidence CONTROLLED. Ordinary tests neither download
assets nor consume the real attempt directory. A controlled success does not
constitute the real ACK proof.

## OpenTTD 15.3 authority

- [CLI dedicated endpoint, seed, isolated paths and no config saving](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/openttd.cpp)
- [Config-relative files and recursive asset search](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/fileio.cpp)
- [GameScript and graphics config selection](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/settings.cpp)
- [GRF data-section sizing](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/newgrf_config.cpp)
- [Base graphics checksums and native load diagnostic](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/gfxinit.cpp)
- [Admin enablement with authorized keys](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network.cpp)
- [Admin update processing and Ping/Pong](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp)
- [World settings](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/world_settings.ini)
- [GameScript startup](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/game/game_core.cpp)
- [Script crash diagnostic](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/script_instance.cpp)
- [Console quit](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/console_cmds.cpp)
