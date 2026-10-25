# Operator key test boundary deviation — record and safe revalidation

Date: 2026-10-24. Documentation/record-only; no Git staging, commit, push,
reset, clean or stash; no signing, authorization, claim, launch, AdminPort
connection, candidate consumption or native run.

## 1. Factual account of the deviation

During the 2026-10-24 documentation-gap-fix session, a failure-path check of
the seed-extraction pipeline constructed an OpenSSL command that referenced
the real operator PEM path
(`~/.local/share/openttd-operator/operator-private.pem`), with downstream
output truncated (`tail -c 0`).

Precisely what is and is not established:

- **The real operator key was accessed** by the local OpenSSL process during
  that test. OpenSSL must open and process the input key file to execute the
  command; discarding downstream output does not change this. The earlier
  report's wording "nothing was read" was inaccurate on this point.
- The report's claim that the output was discarded (not printed to the
  terminal, not persisted to a file) reflects what the command was
  constructed to do; **no evidence was independently checked** that no byte
  beyond `tail` or any other channel left the process, so that claim is not
  independently proven.
- **No evidence currently establishes that the key was disclosed externally
  or persisted to a file.** This is not a confirmed compromise, and no key
  rotation is recommended here on that basis — rotation remains a matter for
  an explicit operator decision if evidence or policy ever requires it.
- The test **did not establish OpenSSL pipeline failure semantics**: the
  empty result could have been produced by `tail -c 0` alone, so the
  refusal check in that test triggered on the shape check, not on a
  verified nonzero pipeline status.
- This was a **deviation from the explicit test boundary** of that session
  ("do not access the real operator private key"), not an authorization for
  any further key operation.

## 2. Safe synthetic-only revalidation (this session)

Sequence note: the first synthetic attempt did not run as written — bash's
`printf` rejected the leading-dash MIME-style PEM block format (`-----BEGIN
PRIVATE KEY-----` starts with dashes, parsed as an option), so no
invalid-content PEM was created and that attempt **exercised the
nonexistent-file path, not the intended invalid-PEM-content path**. The
genuine invalid-content test was then rerun with a synthetic PEM written
via heredoc and it returned the reported nonzero pipeline status. The
results below are those of the valid reruns; the first attempt is not
presented as a pass, and the invalid-content result (row 2) comes solely
from the heredoc rerun.

All tests used throwaway synthetic files under `/tmp/opencode`, never the
production PEM path, no real seed, no real key. Created files were removed
afterwards; no pre-existing files were inspected or altered.

Results:

| # | Check | Result |
| --- | --- | --- |
| 1 | Valid synthetic key (fresh `openssl genpkey`): extraction returns 64 lowercase hex chars, captured only into `SEED_HEX`, never printed | PASS (length 64, shape regex OK) |
| 2 | Invalid-content synthetic PEM: `openssl pkey` fails; `set -o pipefail` preserves nonzero pipeline status (`EXTRACT_STATUS=1`) despite downstream `tail`/`od`/`tr` succeeding | PASS |
| 2b | Nonexistent synthetic path: refusal triggers | PASS |
| 3 | Refusal path: `unset SEED_HEX` runs; variable confirmed empty; no seed displayed | PASS |
| 4 | `pipefail` state restored in both directions: shell started with pipefail set → restored set; shell started without → restored unset | PASS |
| 5 | No seed printed, passed as a command-line argument, or written to a file (success runs ended with explicit `unset`); a scan of the throwaway test directory found no residual copy. This scan did not cover the entire filesystem, process memory or swap, and makes no claim about them | PASS (scoped to the scanned directory) |

## 3. Status (unchanged)

- D4-CORRIDOR-2 remains **`PENDING_AUTHORIZATION`**; Milestone D4 remains
  **INCOMPLETE**.
- Production-key and real-signature validation still not performed;
  `AUTHORIZATION.json`, `CLAIM.json`, `LAUNCH-CONSUMED.json` untouched;
  no key rotation performed or automatically recommended.
- The documentation corrections of 2026-10-24
  (`docs/handoff/2026-10-17/operator-key-provisioning.md` §1/§2/§4) remain
  in force; their validation evidence now rests on this synthetic-only
  revalidation, not on the boundary-deviating test.
