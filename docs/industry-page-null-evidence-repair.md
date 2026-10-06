# Industry-page canonical scalar evidence: controlled repair

Local CONTEXT.md remains the architecture authority. Real industry-page attempt
#1 remains **FAILED — NO RETRY PERFORMED**. Its runtime and post-run evidence are
immutable. This repair does not reinterpret its valid response as a passed proof.

## Diagnosis and feedback loop

The captured five GameScript markers and response are retained as controlled test
fixtures. Running `pytest tests/test_industry_evidence_null.py` initially reproduced
`industry page read/send metadata mismatch` in under a second. Replay isolated the
failure to the read-marker suffix: replacing only its null token in a synthetic
copy makes correlation pass; the unmodified captured trace still fails.

The exact official OpenTTD 15.3
[sqvm.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/3rdparty/squirrel/squirrel/sqvm.cpp)
shows that string addition dispatches to `SQVM::StringCat`, which invokes
`ToString` on both operands. `ToString` has explicit integer and boolean branches,
but no null branch. Null reaches the default type/raw-value object representation,
producing `(null : 0x00000000)`. This was direct string concatenation, not
interpolation, a project formatter, or a logging rewrite.

[sqbaselib.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/3rdparty/squirrel/squirrel/sqbaselib.cpp)
verifies the integer `tostring` delegate, and
[script_log.cpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_log.cpp)
passes the completed string to the log. The three exact source files and their
SHA-256 manifest are retained in `tests/reference/industry_evidence_15_3/` and
included in revision 2's source authority and freeze.

The existing in-memory native Squirrel package renders null as `null`, unlike
OpenTTD's vendored VM. That controlled seam alone therefore did not expose the
old native fallback. Regression coverage combines captured native trace rejection,
exact engine source authority, and execution of the corrected production handler
in the existing VM. It does not claim a new native OpenTTD binding/runtime proof.

## Canonical policy and field audit

`EvidenceOptionalInt` returns literal `null` for null; otherwise it requires an
integer and uses the verified base-10 integer `tostring` delegate. `EvidenceBool`
requires a boolean and returns literal `true` or `false`. Wrong scalar types throw.
No native debug/object/address representations are permitted in formal fields.

| Field | Emission policy |
| --- | --- |
| after_id, next_after_id, first_id, last_id | Optional integer helper |
| requested limit, returned count | Integer helper |
| has_more | Boolean helper |
| world-info dimensions | Integer helper after existing dimension validation |
| request_id | Already validated unescaped ASCII string |
| protocol, type, status, API version | Fixed literals after existing validation |

No logging framework is added. The evidence parser and validator remain unchanged
and strict: complete metadata must exactly match canonical correlated fields.
Native null dumps, whitespace variants, hexadecimal cursors, signed positive
forms, leading zeroes, and floating-point forms fail. Tests also prohibit address
patterns in handler-generated read markers. Ping and world-info retain their
existing evidence semantics. Both local chains and semantic digest correlation
remain unchanged; no total cross-process timestamp order is imposed.

Request/response schemas, limits (proof 3; protocol 5), application maximum
(512 bytes), native ceiling (1450 bytes), cursor/order/page semantics, mutation
behavior, and the lack of an independent second-source industry inventory are
unchanged. Only scalar emission and future proof preparation identity change.

## Revision 2 and authorization

The previous industry preparation is invalid for future execution because the
runtime-critical source changed. Production industry mode now requires attempt 2,
prelaunch revision 2, and proof model `industry-page-correlated-channels-v2`.
Its contract freezes the canonical scalar policy. Old preparations are rejected.

Public production commands, with no launch:

```text
.venv/bin/python -m app.simulation.openttd.proof prepare --mode industry-page
.venv/bin/python -m app.simulation.openttd.proof preflight --mode industry-page
```

New freeze: `artifacts/runtime/openttd-15.3-industry-page-real-prelaunch-v2/`.
Future destination: `artifacts/runtime/openttd-15.3-industry-page-real-attempt2/`.
No future runtime evidence is fabricated. The guarded public preflight validates
the source/bridge/request/contract, secure credentials, historical integrity and
`EndpointReservation.allocate()` path while blocking process creation and connects.

The unchanged canonical request is 106 bytes with SHA-256
`0050e460326e397a32ada31d3608c3aa4a1a8826bff361593e8d17e322a2dab8`:

```json
{"after_id":null,"limit":3,"protocol":1,"request_id":"openttd15-industry-page-001","type":"industry_page"}
```

**FRESH AUTHORIZATION REQUIRED — FROZEN SOURCE CHANGED.** No real launch,
Admin connection, application request, commit or push is part of this repair.

## Verified preparation result

Revision 2 public prepare and guarded preflight passed to `READY_TO_LAUNCH`.
The canonical policy and validator loaded; process creation and connections were
blocked. The freeze contains **103 source/input hashes**, all revalidated.
Bridge digest:
`2151a6a4b9669c3e9a0fef595c758f6f8aeae20a21a26c6f808ab23fcefdccfc`.
The request digest and 106-byte size are unchanged. The new private key is fresh,
mode 0600, and excluded from the public manifest. The attempt #2 directory is absent.

All **280** pre-existing protected artifact/CONTEXT files remain byte-identical,
including both attempt #1 directories and every previous preparation. Attempt #1
still has `REAL_FAILED` status and its original report is untouched.

Null regressions: **29 passed**. Focused compatibility checks: **794 passed,
1 skipped**. Serial ordinary suite: **1,516 passed, 38 skipped**. An initial
concurrent run had one unrelated controlled fake-peer isolation failure; its
isolated recheck and the subsequent serial ordinary run passed without changing
that code. Ruff, format, applicable typecheck, diff, whitespace and query/proof
import-boundary audits passed. Real gameplay launches/connections/requests: **0/0/0**.
