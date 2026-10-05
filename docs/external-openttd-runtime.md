# External OpenTTD 15.3 controlled bootstrap

`CONTEXT.md` is the architecture authority. The primary runtime is the user's explicit
OpenTTD 15.3 executable, not OpenTTDLab. OpenTTDLab / OpenTTD 13.4 code and retained
P03/P06/P07 proofs remain historical regression support. No existing experiment,
planner, transport, executor, evaluation, or preparation caller has been migrated.

## Boundary

`app/simulation/openttd/runtime/` contains:

- `identity.py`: immutable external backend identity: resolved executable path,
  exact version, executable SHA-256. Workspace paths, PIDs, and inspection logs do
  not enter semantic identity.
- `external.py`: explicit-path inspection and launch-spec preparation. No PATH
  discovery, download, alternative executable, or OpenTTDLab fallback exists.
- `config.py`: an owned temporary workspace and loopback Admin configuration.
- `base.py`: typed launch specification and cleanup of an already-owned process.

`ExternalRuntime.inspect(Path(...))` requires a regular executable file, hashes
its contents, runs only `[resolved_executable, "--version"]`, requires version
`15.3`, and checks the executable hash again. Inspection uses temporary HOME/XDG
paths and cwd, captures stdout/stderr, and enforces a 10-second process timeout.

The verified generic Linux 15.3 binary treats `--version` as an unknown option:
its help path prints a version header and help listings and exits **1**, without
starting a world. The adapter accepts this specific 15.3 help result with empty
stderr; it retains the raw exit code instead of rewriting it to zero. Other
nonzero results and other versions are rejected. Version-only inspection is
accounted separately from gameplay launches.

## Isolation and future launch

Create a workspace with `RuntimeWorkspace.create(proof_parent)`. It uses a unique
mode-0700 temporary child. Preparation writes mode-0600 `openttd.cfg`, `private.cfg`,
and `secrets.cfg` there. Existing files are never overwritten. Workspace creation
rejects locations inside the user's normal OpenTTD configuration/data profiles.

Prepared directories include `save/`, `save/autosave/`, `logs/`, `game/`,
`game/library/`, `ai/`, `ai/library/`, `baseset/`, `scripts/`, and `artifacts/`.
No package is copied or selected yet. The future GameScript bridge targets API
major **"15"**. Content hashes and a configuration digest can extend provenance
later; they are not claimed by this binary-only identity.

`ExternalRuntime.prepare(workspace, admin=AdminSettings(password=...), seed=17)`
returns a specification, without executing it. It requires exactly one seed or
an existing workspace-local savegame. The uint32 random-generation sentinel is
rejected. Example argv (not executed):

```text
/explicit/openttd -D127.0.0.1:3979 -c /proof/openttd-15.3-<unique>/openttd.cfg -x -X -g -G 17
```

Save selection replaces `-g -G 17` with `-g /proof/.../save/world.sav`.
`-D` selects the dedicated/null video, sound, music, and blitter drivers; `-c`
anchors config-relative paths; `-x` disables configuration saving; `-X` excludes
global/profile search directories (binary and working-directory searches remain).
The launcher must use the explicit cwd and merge the provided HOME/XDG environment
overrides, pipe stdin, capture stdout and stderr into separate log files, and
track its direct process PID. There is deliberately no launch entry point yet.

The generated INI schema version is 7, matching 15.3. It disables autosaves and
pauses new games. `private.cfg` sets `server_bind_addresses` to `127.0.0.1`, which
applies to the game and Admin listeners. Defaults are game port 3979 and Admin
port 3977; callers can supply distinct valid local ports. Preparation does not
reserve ports or claim endpoint readiness. Passwords are caller supplied,
validated ASCII values stored only in `secrets.cfg`, absent from argv/repr.

`allow_insecure_admin_login = false` preserves the 15.3 authentication default.
The next transport slice must explicitly implement compatible authentication or
make a reviewed local-only decision about legacy authentication. Existing P04
remains read-only and unchanged. Admin update subscriptions are client protocol
messages after login, not runtime INI settings; none are sent here.

A future authorized launcher attaches its owned process to `spec.lifecycle`.
`spec.close()` attempts console `quit\n`, waits, falls back to SIGTERM then kill,
and waits again. It removes the workspace only after the process is reaped.
Cleanup is idempotent; failure to reap retains files. The launcher must separately
own/close the stdout/stderr capture handles and must retain desired artifacts
before workspace cleanup. This task does not claim owner-death supervision or
port leasing for the new runtime.

## Controlled evidence and next slice

Binary:
`/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`

SHA-256:
`276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`

Raw stdout, empty stderr, exit code 1, parsed version 15.3, and inspection counts
are retained under `artifacts/runtime/openttd-15.3-bootstrap/`.
The test fixture `tests/fixtures/openttd_15_3_version.stdout` preserves the actual
output so ordinary tests never inspect the real binary.

Three version-only inspections occurred: the first revealed an overly strict
parser, the second captured raw output, and the third verified the corrected
adapter with isolated directories. The first invocation's raw output was not
retained; the second and third produced identical stdout/stderr and exit code.
The user's `~/.config/openttd` and `~/.local/share/openttd` remained absent when
checked after inspection. No real 15.3 world has been launched or loaded, and no
AdminPort connection has been attempted. Controlled lifecycle tests use fake
owned processes, not OpenTTD.

The NEXT vertical slice is Python AdminPort ↔ GameScript correlated ACK transport,
with explicit controlled launch authorization. It must supply a bridge package,
compatible authentication, deterministic world settings/content, and endpoint
ownership checks before attempting a real round trip. The inspected installation
lists only unusable original graphics sets; a usable verified base graphics set
has not been staged here. No 15.3 content compatibility or gameplay proof is claimed.

## Verified 15.3 sources

- [CLI parsing and help-only exit](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/openttd.cpp)
- [Config-relative paths and local search](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/fileio.cpp)
- [Directory layout](https://github.com/OpenTTD/OpenTTD/blob/15.3/docs/directory_structure.md)
- [INI version and private/secret configuration](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/settings.cpp)
- [Admin/network settings](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/network_settings.ini)
- [Admin listener and bind addresses](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network.cpp)
- [Dedicated signal handling](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/video/dedicated_v.cpp)
- [Console quit](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/console_cmds.cpp)
