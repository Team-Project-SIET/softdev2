# P03 attempt 1: setup evidence did not run

This records the failed P03 proof. It does not claim that a plan was consumed or accepted. The original log remains at `/tmp/softdev2-p03-proof-20260928/p03-proof-log.txt`; the run workspace was removed after the child exited. No second real OpenTTD run is part of this diagnosis.

## Observed sequence

The retained 1,615-byte log records these relevant lines, in order:

```text
dbg: [net] Starting dedicated server, version 13.4
dbg: [net] Listening on 127.0.0.1:39891 (IPv4)
dbg: [script] The savegame has an AI by the name 'SimpleAI', version 14 which is no longer available.
dbg: [script] A random other AI will be loaded in its place.
dbg: [script] [0] [I] 12 API compatibility in effect.
dbg: [console] Executing cmdline: 'exec scripts/game_start.scr 0'
dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'
dbg: [script] [1] [I] 12 API compatibility in effect.
```

There is no `unpause` command, P03 stage marker, P03 terminal marker, or visible Squirrel error in this captured output. Absence of a marker alone would not prove that `Start()` never ran; the paused-save and source-code evidence below establish the causal path.

The pinned save's public parser record is `DATE[0].pause_mode = 1` (normal pause). It also contains a SimpleAI company in slot 0. The attempt-1 P03 harness loaded this save and waited for evidence without submitting an unpause command. In [OpenTTD 13.4 `StateGameLoop()`](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/openttd.cpp), a nonzero pause mode returns before the `AI::GameLoop()` call. In [OpenTTD 13.4 `ScriptInstance::GameLoop()`](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/script_instance.cpp), the first scheduler call invokes `Start()`. The compatibility message is emitted during script initialization and does not establish that `Start()` ran.

**Root cause:** the proof harness never resumed the paused save, so the AI scheduler did not advance to `Start()`. The missing SimpleAI package also let OpenTTD substitute another AI into the save's old company slot; this was a separate isolation flaw and could have produced duplicate receipts after unpausing.

## Lifecycle stage matrix for attempt 1

| Stage | Status | Evidence and limit |
| --- | --- | --- |
| A. AI package discovered | PROVEN | `start_ai P03ThinExecutor` was accepted and a second AI compatibility message followed; the log does not identify the absolute package path. |
| B. AI selected | PROVEN | Console executed `start_ai P03ThinExecutor`. |
| C. AI instance created | NOT PROVEN | API compatibility logging can precede main-script loading and class creation. |
| D. `Start()` entered | FAILED to reach | The save was paused, no unpause occurred, and 13.4 bypasses `AI::GameLoop()` while paused. |
| E. Transported plan loaded | NOT PROVEN | No P03 plan marker. |
| F. Plan decoded | NOT PROVEN | No P03 plan marker. |
| G. Plan/world validated | NOT PROVEN | No P03 validation marker. |
| H. Evidence generated | NOT PROVEN | No terminal marker. |
| I. Evidence emitted | NOT PROVEN | No terminal marker. |
| J. Python observed evidence | FAILED | The harness timed out and raised `SetupEvidenceError`. |

## Controlled correction and remaining proof

The P03-only proof sequence now stops the save's old AI, selects `P03ThinExecutor`, then sends a separate `unpause` script after those console commands are observed. That script acknowledges the transition with `__P03_UNPAUSE_ACK__`. The harness assembles complete stdout lines from bytes, retains bounded script diagnostics, and records the last proven lifecycle stage on timeout. A fake child process exercises that same stdin/stdout handshake for success and typed failure, with workspace cleanup, without launching OpenTTD. No production `LiveSimulationRunner` pause/barrier behavior changes.

The thin AI now emits `START_ENTERED`, `PLAN_FOUND`, and `WORLD_VALIDATION_STARTED` diagnostics before its terminal receipt. Ordinary world/contract rejections emit one typed terminal failure; unexpected validation exceptions are caught and reported as `EXECUTOR_SETUP_FAILURE`. If the plan root is absent after `Start()` enters, the AI emits a bounded typed fatal marker, which the parser reports as `EXECUTOR_SETUP_FAILURE`. A module load failure before `Start()` remains a script startup error, with no AI receipt possible. The parser accepts terminal receipts only from complete OpenTTD script-info log lines and rejects duplicate/conflicting receipts. Controlled tests verify the final workspace contains the generated `plan.nut` beside `info.nut` and `main.nut`, plus the exact save and OpenGFX copy. The `main.nut` `require("plan.nut")` path matches the package layout used by pinned SimpleAI 14. The controlled proof verifies package placement and digest; only a future real run can prove which absolute package path OpenTTD actually loaded.

The 13.4 `script=5` debug channel reached stdout in attempt 1 (the compatibility messages prove that channel was captured). It showed no Squirrel error before unpause. A post-unpause Squirrel exception or world rejection remains possible and must be distinguished by the new stage markers, script-error capture, and typed terminal parser. The generated plan/module hashes are verified in Python before launch; the AI compares transported declarations and world-visible facts. The AI does not independently compute SHA-256 of the full plan.

P03 still requires one separately authorized real attempt showing the thin AI's exact plan hash and world identity in a successful terminal setup receipt, with a single live AI instance, bounded diagnostics, and cleanup. No construction or economic result is claimed by this setup proof.
