# P08 Tile Classification V2 — consumed-attempt startup failure diagnosis and minimal repair

**Date:** 2026-10-18. Scope: offline diagnosis of the consumed native attempt
`artifacts/demos/classification-exec-seed17-e71c95a3/` (attempt
`750167949a4f46af…`, see [the terminal outcome record](p08-classification-v2-native-capture-outcome.md)),
a minimal no-new-launch repair, and a fresh non-executed replacement candidate.
This record **supersedes the outcome record's tentative Native-GameScript-death
interpretation** (and its "add `Load()/Save()` remedies" step): the source save
GameScript did **not** die — the run was killed by two engine-factual details
the runner's health check did not yet recognize. Historical bytes, records and
conclusions in the outcome record are unchanged; only the interpretation below
is corrected. No native launch was made and none is authorized here.

**Repair status: GAMESCRIPT STARTUP REPAIR READY FOR NATIVE VALIDATION** — code
implemented, offline-verified, and a fresh `PENDING_AUTHORIZATION` candidate
staged (zero launches, zero connections, zero claims consumed). Native
validation still requires its own fresh authorization.

## 1. Root cause (engine-quoted, both facts verified)

The log recorded (per section 2 below) two independent facts that the old
health-vocabulary could not separate:

1. **The staged runtime could not resolve the save's stored AI identity.**
   `artifacts/demos/classification-exec-seed17-e71c95a3/stderr.log` `-d script`
   lines (consumed run, 2026-10-18 11:32:09):
   `The savegame has an AI by the name 'RoadProofCompany', version 1 which is
   no longer available.` → `Configuration switched to Random AI.` →
   `No suitable AI found, loading 'dummy' AI.` The runner staged **no AI at
   all**, while the byte-verified retained source save
   (`before.sav` from `playable-demo-698799a2dfb146948fd2983ff2032253/`, sha
   `e81f6553…7117c`) stores the AI identity `RoadProofCompany`/version 1 (the
   retained freight AI that produced the world). OpenTTD 15.3's
   save-load fallback tries a random AI substitute and, with no AI installed,
   falls back to the built-in dummy AI.
2. **That dummy-AI fallback "death" is engine-designed, not a script failure.**
   `script_info_dummy.cpp` (`Script_CreateDummy`) logs exactly three
   `AILog.Error` lines — `No suitable AI found to load.` /
   `This AI is a dummy AI and won't do anything.` / `You can download several
   AIs via the 'Online Content' system` — and its `Start()` **returns**.
   `script_instance.cpp`'s game loop then evaluates
   `!CallMethod("Start") || !IsSuspended()` and calls `Died()`, which prints
   the unattributed line `The script died unexpectedly.` at `[script:0]`. This
   is the documented instant-death of the dummy AI; it says nothing about the
   classification GameScript.

**Who actually survived:** the GameScript. It logs at root-company marker
`[18]` (`script_object.cpp` `GetRootCompany` of `ScriptController`'s
`SetCompany` = `OWNER_DEITY`, `company_type.h`, value `0x12` = 18; AI instances
log at `[0]`). The consumed log shows `[18] [W] Loading failed: … no
`Load()` function` (a *warning* — `ScriptInstance::CallLoad` pops the stored
data and continues; missing `Load()` is not fatal), then
`[18] [I] BRIDGE_STARTED protocol=1 api=15` (the staged composed main started),
then the AI's `[0] [E]` dummy sequence and the `[script:0]` death line, then —
after the death — `[18] [W] Save function is not implemented` twice. Those two
post-death GameScript warnings are decisive survival evidence: the run has
exactly one save attempt (`autosave_interval = 0`; the save happens at exit),
a **dead** script saves silently-empty (`ScriptInstance::Save` with a dead
controller writes an empty table), and only a **live** script reaches the
`Save function is not implemented` warning. The GameScript was alive at the
single exit-save, i.e. it never died during the run.

**Why the run failed:** the runner (`classification_capture.py`) checks the
captured logs at every health/`wait_log` point. Its old fatal-marker list
contained `no longer found` (legacy wording) but **not** the OpenTTD 15.3
fallback wording `which is no longer available` (verified against the pinned
binary's `strings`; source texts live in `src/saveload/ai_sl.cpp`,
`src/saveload/game_sl.cpp`), and it had one blanket fatal rule for
`The script died unexpectedly.` regardless of who died. The health check hit a
died-line inside the readiness window (~0.38 s) and raised
`Native script/asset error` → `RUNTIMEERROR` → 0 connections / 0 pages → the
fail-closed cleanup chain reported `FAILED_CLEANUP` because its final log
health step still returns the fatal finding. The runner did what it was
written to do: it failed closed on a fatal *shape* it recognized. The defect
was *misattribution*: a benign, engine-designed dummy-AI death was treated as
a GameScript failure, so a repairable staging gap was diagnosed as an
unrecoverable native script error.

## 2. Verbatim decisive evidence (immutable, retained)

From `artifacts/demos/classification-exec-seed17-e71c95a3/stderr.log`
(lines 45–63, script-relevant slice; sha
`57a11449cb413b530ac1c20a8b29ac66f9c9791da1f261028396fc0b868b2dd3`):

```
dbg: [script:0] The savegame has an AI by the name 'RoadProofCompany', version 1 which is no longer available.
dbg: [script:0] Configuration switched to Random AI.
dbg: [script:0] The savegame has an AI by the name 'RoadProofCompany', version 1 which is no longer available.
dbg: [script:0] A random other AI will be loaded in its place.
dbg: [script:0] No suitable AI found, loading 'dummy' AI.
dbg: [script:3] [18] [W] Loading failed: there was data for the script to load, but the script does not have a Load() function.
dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15
dbg: [script:1] [0] [E] No suitable AI found to load.
dbg: [script:1] [0] [E] This AI is a dummy AI and won't do anything.
dbg: [script:1] [0] [E] You can download several AIs via the 'Online Content' system
dbg: [script:0] The script died unexpectedly.
dbg: [script:3] [18] [W] Save function is not implemented
dbg: [script:3] [18] [W] Save function is not implemented
```

Cross-checks against the working retained runs: the freight demo
`playable-demo-25d891bc9f34…/stderr.log` shows the same healthy shape — the
GameScript at `[18] [I]`, the freight AI at `[0] [W] Save function is not
implemented` — i.e. the log-severity/company-attribute vocabulary used here is
the engine's own, and a *live* root-company-18 script with warnings is exactly
what a working capture leaves behind. The consumed run's `[18]` lines match
that healthy shape; only the AI side (no staged AI) deviated.

## 3. Minimal repair (two changes, no semantics broadening)

### Fix 1 — `classification_capture.py`: recognize the fallback vocabulary and attribute the designed dummy death

- New function `script_log_health_findings(text)` computes the fatal findings;
  `_check_logs` fails with `Native script/asset error: …` when it is non-empty
  (failure code unchanged, `RUNTIMEERROR`; result schema unchanged).
- Fatal vocabulary keeps every legacy marker verbatim (`Error compiling`,
  `Fatal error`, `Script is not started`, `no longer found`, `corrupted or
  missing`, `but it is incomplete`, `illegal packet`,
  `not supported update frequency`) and adds `which is no longer available` —
  the actual OpenTTD 15.3 save-load fallback text. Recognized, never
  tolerated: a save-identity fallback means the staged world did not reproduce
  the stored script identity and the capture must fail closed.
- New tripwire: any script line whose severity slot is `[S]`
  (`dbg: [script:<n>] [x] [S] <message>`, a bare end-of-line `[S]` slot
  included — Squirrel error output) is fatal regardless of the script that
  raised it; a `[S]` occurring inside message text of a differently-severed
  line does not trip.
- Exactly **one** death line per captured log is exempted, and only when (a)
  all three dummy-AI sequence lines appear in the captured text and (b) the
  death line directly follows the sequence's final line in script-log order.
  Every other death line is fatal, a **second** death line is always fatal
  (even a perfectly shaped second dummy fallback — the exemption is capped at
  one per captured log), and any weakening of the sequence (missing first
  line, interleaving script line) is fatal. The exemption is the engine's
  designed fallback death — excluded from the fatal findings as survival
  evidence, never tolerated as failure.

### Fix 2 — `classification_execution.py`: stage the retained save's stored AI package

- SOURCE_SAVE staging now installs the retained AI package
  `app/simulation/openttd/road_company_package/` (`info.nut` 507 B /
  `main.nut` 156 B) into the runtime workspace `ai/RoadProofCompany/`
  (mode 0700): name `RoadProofCompany`, version 1, controller
  `class RoadProofCompany extends AIController` whose `Start()` is
  `AILog.Info("ROAD_PROOF_COMPANY_READY"); while (true) Sleep(1);` — it never
  dies, so the dummy fallback (with its instant death) cannot recur. This is
  the same staged-AI-package pattern `proof/freight_delivery.py` already uses
  for its own natively validated runs.
- Staged identity is sealed and verified: `validate_staged_ai_identity`
  refuses a package that lost the retained goods; `staged_ai_digest` uses the
  same `name\0<8BE length>content` convention as the GameScript package
  binding; the identity enters the composition payload
  (hence the composition/attempt identity and directory name change), the
  candidate record, and the sealed `PRELAUNCH.json`; preflight re-verifies the
  staged bytes byte-exactly (sha256 per file) as defense-in-depth behind the
  whole-workspace freeze (fail closed, same as every other staged seam).
- FRESH_GENERATION modes stage no AI (unchanged); preparing the fallback mode
  continues to be refused without a new reviewed candidate.

**Deliberately unchanged:** historical evidence and every record of the
consumed attempt (including its `FAILED_CLEANUP` semantics) stay byte-identical;
no `Load()`/`Save()` methods were added to the GameScript (missing `Load()` is
a benign warning — the save-carried data is simply dropped); the composed
`main.nut` is byte-identical to the frozen classification composition
(GameScript package digest `392c42baae19…332d34` unchanged); no commit, push or
stage.

## 4. Fresh, non-executed replacement candidate

Staged offline (no authorization consumed, no claim, no launch):

- Directory: `artifacts/demos/classification-exec-seed17-3a8f9e46/`
- Attempt identity `556e97b81230bfd39d2146c6e05885c5492e416dde2e26513ef42916029d94ed`
- Composition identity `3a8f9e46969687b68af7a69adb391c2c5e6d93c1bd13050f9e1d638505da4886`
  (new, because the sealed composition now includes the staged AI package)
- `CANDIDATE.json`: `state=PENDING_AUTHORIZATION`, `authorized=false`,
  `native_launches=0`, `requests_sent=0`, no `CLAIM.json`
- Sealed AI package digest
  `3708a4181df49a3e066e061895c2d3b0648089caf8573960cf2583e9d725c8d0`
  (`info.nut` sha `d38f06816b7e36a11fcb51182b4642f9f885f495e1b8b1aca5ff62f79436a5d7`,
  507 B; `main.nut` sha `3d8fcc560520caafbd6d54ee3bfbf4c138cae4c10d91ed369bb660c9bc674277`,
  156 B); staged byte-exact under the isolated workspace `ai/RoadProofCompany/`
- GameScript package digest unchanged
  `392c42baaee1974f6022eed18300f09e472f50d2a295139d32ee73a34d5f2309`
- Read-only preflight re-run **once**, PASS (prints the attempt identity);
  the candidate remains executable-pending and must not be re-consumed
  without a fresh operator authorization.

## 5. Offline verification (all controlled, no native seams)

- Focused suites: `tests/test_classification_capture.py` +
  `tests/test_classification_execution.py` — 35 PASS. New regressions cover:
  the consumed-log replay (the only finding is the genuine
  `marker:which is no longer available`; the death line is no longer
  misattributed), the healthy working-run shape (no findings), a genuine
  GameScript death (fatal), both save-identity fallback wordings (fatal),
  `[S]` tripwire (fatal), and the single/strict dummy-death exemption
  (missing line, interleaved script line, second death, capped exemption
  across two perfectly shaped fallbacks — all fatal); plus sealed AI
  identity/digest-convention records, preflight refusal of a drifted staged
  AI file, staging failure when the retained AI sources are missing, and
  identity-tamper refusal before any runtime is built.
- Broader controlled suites re-run green: `tests/test_gamescript_transport_classification.py`
  + `tests/test_tile_classification.py` + `tests/test_tile_classification_receipt.py`
  (39 PASS); the REPRODUCE.md controlled regression set
  (`tests/test_demo_random.py` … `tests/test_openttd_demo.py`, 90 PASS);
  `tests/test_p08_classification_workflow.py` +
  `tests/test_p08_controlled_road.py` + `tests/test_freight_canonical_dispatch.py`
  (84 PASS).
- Gates: `ruff check` clean, `ruff format --check` clean,
  `compileall` clean, `git diff --check` clean. Typecheck: `ty` is configured
  (`tool.ty.environment`) but still not installed in this venv — unavailable,
  as historically recorded.
- Independent review (OpenCode subagent, offline, read-only): **PASS, no
  blocking findings**; four non-blocking observations (a bare end-of-line
  `[S]` slot, the exemption-cap branch coverage, a comment wording nuance,
  and freight-runner vocabulary sharing as future work) addressed or noted —
  the first three were folded into the final code/tests before re-staging.
- No OpenTTD launch, no AdminPort connection, no resident `openttd` process;
  the pinned binary was never executed; the untracked root file `--version`
  was never executed.

## 6. What the repair does and does not claim

- It repairs the two identified staging/health gaps and reproduces the
  consumed run's log vocabulary in regression tests. It does **not** claim
  that a fresh capture will succeed: native save-load resolution of the
  staged AI, the new controller's real behavior, welcome identity, the 90-page
  census and correspondence still require exactly one fresh authorized
  launch of the new candidate and can fail closed like before.
- The 19 historically unknown tiles remain UNKNOWN; the retained
  `INCOMPLETE_TILE_CLASSIFICATION` assessment and every retained number are
  unchanged. The consumed attempt stays a terminal `FAILED_CLEANUP` outcome.
- Any future native attempt must (a) re-run the preflight on
  `classification-exec-seed17-3a8f9e46` (or prepare a further updated
  candidate), (b) receive its own explicit one-shot authorization, and
  (c) write no interpretation beyond what its own logs and records show.
