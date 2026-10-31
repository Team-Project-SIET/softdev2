# D5-CORRIDOR-EXTENSION-3 — Handshake remediation record

Status: **REMEDIATION COMPLETE — fresh survey candidate staged, awaiting the
operator's Gate C signature.** No OpenTTD process was launched, no AdminPort
connection was made, and no world mutation occurred during this work.

## 1. Consumed attempt (immutable historical evidence)

Attempt `D5-CORRIDOR-EXTENSION-3-SURVEY-1` (candidate directory
`artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-1/`)
reached `A0_SURVEY = FAILED`:

- PRELAUNCH, authorization, native preflight: passed; OpenTTD 15.3 launched
  once; the AdminPort TCP connection was accepted.
- `JOIN_SECURE` authentication failed with
  `AuthProtocolError: invalid secure client identification` before any
  survey request, so 0 of 10 exchanges dispatched.
- `CLAIM.json` and `LAUNCH-CONSUMED.json` exist; consumption is permanent.
  No world mutation occurred. Cleanup completed; evidence preserved.
- **This candidate is never retried**, even though zero survey exchanges
  were dispatched; its evidence is never rewritten.

## 2. Root cause (verified against source, not only the prior report)

Call chain of the defect:

1. `app/simulation/openttd/proof/corridor_terrain_survey_native.py` staged
   `attempt = terrain_attempt_name()` into PRELAUNCH metadata.
2. The native execution path authenticates with
   `await session.authenticate(metadata["attempt"], "1", timeout=10)`.
3. `app/simulation/openttd/secure_admin.py::encode_join_secure` encodes the
   client name; it correctly rejects the identity, but it is the *last*
   defense — nothing upstream validated the identity, so a 32-byte
   `attempt` survived preparation, PRELAUNCH and PREFLIGHT and only failed
   at the live handshake.

Capacity semantics (15.3, verified against the pinned source in this repo):

- `ottd/src/network/core/config.h`: `NETWORK_CLIENT_NAME_LENGTH = 25`
  "including '\0'"; `NETWORK_REVISION_LENGTH = 33` "including '\0'".
- `ottd/src/network/core/packet.cpp` `Recv_string` reads at most
  `length - 1` payload bytes and the empty-string check in
  `ottd/src/network/network_admin.cpp` `Receive_ADMIN_JOIN_SECURE` rejects
  empty identification server-side.
- Therefore the maximum accepted JOIN_SECURE client-name payload is
  **24 UTF-8 bytes** (25 capacity − NUL terminator). The consumed identity
  `D5-CORRIDOR-EXTENSION-3-SURVEY-1` is 32 UTF-8 bytes: unencodable. The
  server accepted the TCP connection and logged an empty client-name
  disconnect. No OpenTTD source was modified.

Other JOIN_SECURE callers audited: `corridor_freight_native.py` and
`corridor_accept_survey_native.py` also authenticate with
`metadata["attempt"]`, but both pin it to the 13-byte literal
`D4-CORRIDOR-5` by fail-closed equality checks; only the terrain-survey
pipeline staged a long identity. The shared defensive validation below
protects every path regardless.

## 3. Changed code

- `app/simulation/openttd/secure_admin.py`
  - New constants `JOIN_SECURE_CLIENT_NAME_CAPACITY = 25` and
    `JOIN_SECURE_VERSION_CAPACITY = 33`, replacing the magic numbers.
  - New shared fail-closed helper `validate_join_secure_string(value, *,
    capacity)` and `InvalidSecureIdentity(ValueError)`: UTF-8 encoded byte
    length (never a character count), rejects empty, embedded NUL, and
    anything above `capacity - 1` bytes; never truncates or rewrites.
  - `encode_join_secure` delegates to the helper but keeps its own
    defensive `AuthProtocolError("invalid secure client identification")`
    so an invalid name still fails inside the encoder, before any frame is
    written.
- `app/simulation/openttd/proof/corridor_terrain_survey_native.py`
  - `TERRAIN_SURVEY_ATTEMPT = "D5CE3-SURVEY-2"` (14 ASCII bytes,
    distinct from the consumed identity). Milestone unchanged:
    `D5-CORRIDOR-EXTENSION-3`.
  - New `require_join_secure_attempt_identity`; reused
    `TerrainSurveyStagingError` for fail-closed staging refusal.
  - `prepare_terrain_survey_candidate` validates the attempt identity
    **before any candidate artifact is written** (before
    `directory.mkdir`).
  - `terrain_survey_preflight` independently re-derives capacity
    validation from the sealed metadata bytes before the constant-equality
    check; no stage relies solely on an earlier stage.

## 4. Regression tests added and exact results

`tests/test_secure_admin.py`:

- byte-boundary parametrization: `""`, `"x"*24`, `"x"*25`, `"na\0me"`,
  `"ø"*12` (24 bytes, accepted), `"ø"*13` (26 bytes, rejected), `"ä"*8`;
- exact 24-byte boundary encodes with NUL termination; 25 rejected;
- multibyte character-count-below-byte-capacity boundary (12 vs 13 `ø`);
- invalid name fails `authenticate` before any frame write; writer saw
  zero frames; session closes clean.

`tests/test_corridor_terrain_survey_native.py`:

- staged identity is `D5CE3-SURVEY-2` (14 bytes) and passes the shared
  production validator; preflight re-passes on the sealed bytes;
- oversized (25-byte) and empty identities are refused by preparation
  **before any candidate artifact exists**; the accepted identity passes
  the preparation validator;
- preflight independently re-refuses a re-sealed oversized identity,
  then restores and re-verifies the untouched staged candidate.

Commands and results (exact):

```
.venv/bin/python -m pytest tests/test_secure_admin.py -q
  → 46 passed
.venv/bin/python -m pytest tests/test_corridor_terrain_survey_native.py -q
  → 36 passed
.venv/bin/python -m pytest tests/test_secure_admin.py \
    tests/test_corridor_terrain_survey_native.py \
    tests/test_corridor_freight_native.py \
    tests/test_corridor_accept_survey_native.py \
    tests/test_corridor_terrain_survey.py --tb=no -q -p no:cacheprovider
  → 166 passed, 1 skipped, 0 failed
```

Existing behavior preserved: authentication, authorization and claim
semantics, protocol-7 read-only survey semantics, and all sibling freight /
accept-survey suites pass unchanged.

## 5. Independent review

A fresh-context independent review pass was requested against the actual
changes and returned **PASS**:

- 15.3 capacity pinned in-repo (`ottd/src/network/core/config.h`: 25 and 33
  bytes *including* NUL; `packet.cpp` `Recv_string` reads `length - 1`
  payload bytes); validator semantics match exactly.
- UTF-8 byte length verified by live run (`ø`×13 rejected at 26 bytes);
  NUL termination and embedded-NUL rejection verified.
- Preparation fail-closed ordering confirmed: the identity check precedes
  `directory.mkdir` and every candidate write; nothing leaks on refusal.
- PRELAUNCH and PREFLIGHT validation independent; encoder retains its
  defensive check; no partial frame writes on invalid input.
- No changes to authorization, claim, or protocol-7 semantics; no changes
  to any consumed evidence (candidate-1 `PRELAUNCH.json` still carries the
  old 32-byte identity, read-only); no unrelated behavior changes.
- One cosmetic note (error-message wording on the empty/NUL branches) was
  fixed narrowly after the review; affected tests re-ran green.

## 6. Fresh survey candidate (staged, not authorized)

- Attempt identity: **`D5CE3-SURVEY-2`** — 14 UTF-8 bytes, within the
  JOIN_SECURE 24-byte payload, validated fail-closed.
- Milestone: `D5-CORRIDOR-EXTENSION-3` (unchanged); schema
  `d5-terrain-survey-prelaunch-v1`; kind `terrain-survey`.
- Candidate directory:
  `artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2/`
  (fresh; the consumed candidate-1 directory is untouched).
- Same verified protocol-7 read-only terrain survey schedule — 10
  exchanges: `radius-00`, `tile-00` (50095), `tile-01` (50096), `tile-02`
  (50352), `tile-03` (50608), `tile-04` (50864), `tile-05` (50863),
  `tile-06` (50862), `accept-00` (control stop 50351), `accept-01`
  (proposed stop 50862). Read-only semantics preserved; `max_cost = 0`.
- Pinned prerequisite world (D4 after-save, recomputed from staged bytes
  and freshly sealed — nothing copied from any consumed candidate):
  `a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`
  (`D4-CORRIDOR-5`).

Candidate-specific values (recomputed from actual staged bytes):

| Field | Value |
| --- | --- |
| PRELAUNCH seal `sha256(PRELAUNCH.json)` | `c76992187b0ace7b317e9f992f678bac675f9f89711cd87730fa8d0456aaa2b6` |
| Plan model digest | `82246eb67f0fa6dfc0631a1fe7b84e84f963f9b7d8c8919fe4a064e8c98ef8d9` |
| Schedule digest | `f091754de6d364d226b77555766ed5d2f3f3dfb38e23f42f5d3757fd62246c3a` |
| Authorization payload digest | `38dd8ecc86f5d86edc3474bdd88e0aff4f7022be56d8891b15b06c547f3abbf9` |
| Request / exchange budgets | requests 32, planned exchanges 10, max_cost 0, launches 1, retries 0, reconnects 0 |

Verification executed for this candidate:

```
.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native \
    prepare artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2
  → PRELAUNCH PASS
.venv/bin/python -m app.simulation.openttd.proof.corridor_terrain_survey_native \
    preflight  artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2
  → PREFLIGHT PASS
```

Stop-checkpoint confirmation:

- Attempt identity within the 24-byte UTF-8 limit (and validated at
  preparation, PRELAUNCH/PREFLIGHT, and by the encoder).
- `AUTHORIZATION.json` absent; `CLAIM.json` absent;
  `LAUNCH-CONSUMED.json` absent.
- No OpenTTD process launched; no AdminPort connection; no world
  mutation. Candidate contents: `PRELAUNCH.json`, `PRELAUNCH.sha256`,
  `graphics-identity.json`, `isolated/` workspace only.

## 7. Remaining limitations

- The authorization payload digest above is over the canonical payload of
  the staged candidate; any change to the staged bytes (including the
  workspace contents) invalidates the Gate C payload and requires re-staging.
- Runtime authorization depends on the documented tooling signing path and
  the pinned 15.3 binary /
  `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` being
  present on the executing host.
- Full protocol-7 exchange behavior remains exercised by the offline suite
  only; live behavior is asserted at replay time after the survey runs.

## 8. Exact operator action for the fresh Gate C signature

1. Verify the staged bytes:
   `python -m app.simulation.openttd.proof.corridor_terrain_survey_native preflight artifacts/experiments/d5-corridor-extension-3-survey-native-candidate-2` → `PREFLIGHT PASS`.
2. Confirm the authorization payload digest equals
   `38dd8ecc86f5d86edc3474bdd88e0aff4f7022be56d8891b15b06c547f3abbf9` over
   the canonical payload built from `PRELAUNCH.json` and its seal.
3. Run the documented trusted local Gate C signing step (Option 1,
   repository tooling only) with the operator-held Ed25519 seed to produce
   `AUTHORIZATION.json` for this candidate. **No private key material may
   ever be pasted into chat or logs.**
4. Report back; the survey may then execute exactly once, under a separate
   operator authorization for launch.
