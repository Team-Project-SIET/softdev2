# First company-owned road mutation probe

This implements a separate version-15 GameScript package and narrow secure-session
policy for one adjacent road segment. Existing read-only bridges and P06/P08/P05
contracts remain unchanged. A no-op AI provisions the disposable company and issues
no construction commands. `RoadSegmentIntent` is a construction probe intent, not
a freight `ExecutionPlan` or a claim that the controlled freight terrain is real.

The runner reuses pinned binary/OpenGFX checks, owned runtime/config creation,
authorized-key encryption, subscription barrier, process lifecycle and endpoint
cleanup. It freezes generated-world identity, bounded candidate policy, exact
launch/bootstrap commands, source hashes, budgets and cleanup requirements before
launch. The final intent binds native tile/test-cost evidence and before-save bytes.
Construction is latched before the real command. Receipt verification requires
fresh ownership/connectivity readback, funds/cost agreement, unique retained secure
frames, plan/save hashes and successful cleanup.

## Consumed attempt

Preflight passed. Exactly one OpenTTD 15.3 process and one continuous secure Admin
connection were used, with ten inspection requests and no build request. The native
candidate at tiles 1292–1293 was vacant and buildable; test-mode cost was 172 and
company 0 had 100000 funds. Python rejected the native unowned sentinel `-1` because
the initial validator incorrectly expected spectator ID `255`.

[Tagged 15.3 company declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_company.hpp)
define `COMPANY_INVALID = -1` and `COMPANY_SPECTATOR = 255`. Controlled stubs and
Python admission now use the correct sentinel. The captured native response passes
offline admission replay. This does not execute or validate a construction.

The failed attempt is preserved byte-identically at
`artifacts/runtime/openttd-15.3-company-road-mutation-attempt1/`, including immutable
prelaunch/claim, before save, native frames, requests/responses, logs, result and
cleanup. The original attempted source is archived separately under
`artifacts/runtime/openttd-15.3-company-road-mutation-controlled-repair/`.

Cleanup passed: process reaped, secure stream and listeners closed, credential
removed and owned workspace disposed. No construction receipt exists. No retry,
reconnection, replacement seal, commit or push occurred during Attempt 1.

## Attempt 2

The corrected Python admission and packaged GameScript both use
`GSCompany.COMPANY_INVALID` (`-1`). Focused mutation, secure Admin, transport and
execution-contract tests passed before the immutable Attempt 2 prelaunch seal.
The staged GameScript bytes matched the corrected package, and the seal bound the
OpenTTD 15.3 binary, frozen source inputs, generated disposable world, exact run
command, one-launch/one-connection/one-build budgets and required readback.

Exactly one process and one continuous secure Admin connection were used. Ten
bounded inspection requests found adjacent tiles 1292–1293 vacant and buildable;
company 0 had 100000 funds and native test-mode cost was 172. One construction
request returned `BUILT`. Independent `read` returned both roads present, connected
and owned by company 0, with funds 99828. The plan-bound receipt independently
replays the build and readback exchanges, save identities and cleanup evidence.

Attempt 2 artifacts are in
`artifacts/runtime/openttd-15.3-company-road-mutation-attempt2/`. Its artifact
manifest and Attempt 1's original manifest both verify. Cleanup reaped the process,
closed the secure stream and listener, removed the credential and disposed the
owned workspace. No retry, reconnect or second native launch occurred.

The first company-owned road mutation is proven on OpenTTD 15.3 for this disposable
world and bound plan. It does not claim that a freight ExecutionPlan is
native-executable.

Controlled verification: 132 focused tests passed. The final ordinary serial suite
passed with 3664 passed, 48 skipped and three real-runtime tests deselected. Ruff,
format, scoped typecheck and whitespace checks passed. All 2684 initially captured
files and all 33 consumed-attempt files remain byte-identical.
