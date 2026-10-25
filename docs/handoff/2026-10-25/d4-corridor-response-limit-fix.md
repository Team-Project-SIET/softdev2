# D4 corridor protocol-4 response-limit fix (offline)

**Date:** 2026-10-25. **Scope:** offline implementation, tests and documentation.
No OpenTTD launch, AdminPort connection, save mutation, candidate staging,
signing, claim creation/consumption or native retry occurred. The consumed
`D4-CORRIDOR-4` attempt remains `INCOMPLETE (native)`.

## Root cause

Protocol 4 deliberately permits corridor responses up to **640 bytes**: the
final route read echoes the ordered 24-tile witness and cannot honestly fit the
historical version-one 512-byte response bound (`corridor_construction.py`,
`proof/corridor_construction_native.py::budgets()`, and the staged plan all bind
640). The shared transport decoder still enforced the version-one limit:

- `observation_protocol.MAX_PAYLOAD_BYTES = 512` (the v1 contract),
- `gamescript_transport.decode_gamescript()` applied that same 512-byte limit
  to every GameScript body regardless of protocol.

During `op-06` the retained depot response had a 517-byte Admin frame:

| Layer | Bytes |
|---|---:|
| Admin frame (2-byte length + 1-byte packet ID + body) | 517 |
| Body (513-byte UTF-8 JSON + terminating NUL) | 514 |
| Application JSON payload | 513 |

The payload is valid under the protocol-4 contract but exceeded the decoder's
hard-coded 512-byte check, so `decode_gamescript` raised
`MalformedMessage: GameScript packet exceeds application limit` before
`CorridorReadback.parse_for()` could correlate it. The native log and retained
frame both report `BUILT`, but no `confirm-06`, `receipt.json`, authoritative
`after.sav` or route read exists.

This was an application-bound mismatch, not a serializer overflow, a byte-count
character/byte confusion, or an Admin framing failure. The frame is far below
the 32767-byte shared frame ceiling and the 513-byte payload is below the
1450-byte `GSAdmin.Send` ceiling.

## Chosen correction

The smallest safe fix keeps the version-one limit as the default and makes a
protocol-specific bound explicit:

- `encode_gamescript` / `decode_gamescript` accept a keyword-only
  `max_payload_bytes` parameter, defaulting to the unchanged 512.
- The supplied bound is validated (positive integer, no greater than
  `MAX_GAMESCRIPT_PAYLOAD_BYTES = 32767 - 4 = 32763`). A GameScript frame spends
  3 bytes on the Admin header and 1 on the terminating NUL, so 32763 is the
  absolute application maximum inside one frame.
- Protocol 4 defines `MAX_CORRIDOR_RESPONSE_BYTES = 640` and
  `MAX_CORRIDOR_REQUEST_BYTES = 512` in `corridor_construction.py`.
  `CorridorReadback.parse_for()` and the corridor proof's live exchange and
  retained-frame replay pass the 640 bound explicitly.
- All other protocols continue to use the 512 default. A global constant raise
  was rejected because it would loosen unrelated v1/v2/v3 contracts.

The fix does not truncate responses, skip schema/correlation checks, weaken
UTF-8 validation, or change the Admin framing rules. Non-UTF-8, embedded-NUL,
unterminated, malformed, duplicate-key and genuinely oversized messages still
fail closed.

## Changed files

| File | Change |
|---|---|
| `app/simulation/openttd/gamescript_transport.py` | Opt-in validated `max_payload_bytes` for encode/decode; default 512 preserved; absolute frame-body ceiling 32763 |
| `app/simulation/openttd/corridor_construction.py` | Shared protocol-4 request/response constants; `parse_for()` and `to_bytes()` use them |
| `app/simulation/openttd/proof/corridor_construction_native.py` | Corridor live exchange and retained-frame replay decode responses under the 640-byte protocol-4 bound |
| `tests/test_gamescript_transport.py` | Default-limit preservation, 513/640/641 boundaries, multibyte UTF-8 byte counting, invalid bounds, malformed bodies, 32767-byte frame boundary |
| `tests/test_corridor_construction.py` | Retained candidate-4 depot frame regression, inclusive 640 / one-over 641, malformed/truncated/duplicate/invalid-UTF-8 responses |
| `tests/test_corridor_construction_native.py` | Retained candidate-4 replay now decodes the 513-byte depot reply and stops at the next honest missing-evidence refusal |

## Validation (actually run)

Offline only, with the repository virtual environment:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/test_corridor_construction.py
29 passed

.venv/bin/python -m pytest -o addopts='' -q tests/test_corridor_construction_native.py
33 passed

.venv/bin/python -m pytest -o addopts='' -q tests/test_gamescript_transport.py
38 passed

.venv/bin/python -m pytest -o addopts='' -q tests/test_gamescript_protocol.py
29 passed

Combined focused run: 129 passed
```

The retained candidate-4 fixture is read byte-for-byte and never modified. If
the gitignored candidate directory is absent, those tests skip with an explicit
reason; they do not fabricate evidence.

Additional checks after the final run:

```text
.venv/bin/ruff check --ignore UP037 <touched Python files>
All checks passed!

.venv/bin/ruff check <touched Python files>
Found 4 errors: UP037 quoted annotations at corridor_construction.py:116,
:214 and :534. All four are pre-existing, unchanged lines (not part of this
diff); the changed lines add no lint finding.

.venv/bin/python -m py_compile <touched modules/tests>
exit 0

git diff --check
exit 0
```

The full project suite was not re-run; the focused protocol/corridor suites and
these targeted checks cover the change.

## Evidence and compatibility implications

- The consumed `D4-CORRIDOR-4` authorization, claim, seal, payload, frames,
  diagnostic save, outcome and 80-file manifest were not changed.
- The retained 513-byte depot response now parses to a `BUILT` readback under
  the corrected protocol contract, but that is **regression evidence**, not a
  new verified native result. No receipt is fabricated from the unverified
  frame.
- Read-only replay now gets past the frame decoder. It still refuses the attempt
  at the next honest gate (`retained gateway response lacks its durable response
  file`, because the client never persisted `depot-06-response.json`), and no
  confirmation, receipt or authoritative save exists.
- Version-one and every other protocol keep the strict 512-byte default. A
  future protocol that needs a larger bound must pass and document it
  explicitly, and can never exceed 32763 application bytes.

## Remaining gate

A successful offline fix does not complete D4. A future native attempt still
requires:

1. a fresh never-consumed candidate staged from reviewed source (not
   `D4-CORRIDOR-1/3/4`, and not stale `D4-CORRIDOR-2`),
2. independent review of the candidate and this protocol change,
3. ONE fresh explicit operator authorization for signing and a single native
   attempt.

No retry, re-sign, replacement or claim reuse for `D4-CORRIDOR-4` is
authorized. D4 remains **INCOMPLETE (native)**.
