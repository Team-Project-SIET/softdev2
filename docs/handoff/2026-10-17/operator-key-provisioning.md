# Operator key provisioning procedure — D2 Native Clearing

Status on 2026-10-20: **unseeded by design.** `OPERATOR_PUBLIC_KEY_HEX` in
`app/simulation/openttd/proof/operator_authorization.py` is `None`, every
launch-capable path fails closed on the unseeded anchor, and nothing in this
repository generates, stores or signs with an operator key. This document is
the procedure the OPERATOR executes to change that state; the runner-side
agent does not execute it.

## Non-negotiables

1. The private signing key (the 32-byte RFC 8032 seed) is generated,
   stored and used **only off the runner host**, by the operator. It never
   enters this repository, this agent's context, chat logs, screenshots or
   the candidate directory.
2. The runner never signs, never approves execution, and never bypasses the
   gate. Approval artifacts are: (a) a *reviewed code change* pinning the
   public key hex, (b) a candidate-bound signed AUTHORIZATION.json, and
   (c) an explicit operator statement authorizing the exact launch scope.
3. Nothing here provisions any key automatically; each action below is an
   explicit human action with an explicit human approval.

## 1. Operator generates an Ed25519 key pair (off the runner)

Use any audited RFC 8032 Ed25519 tool on an operator-controlled machine.
With OpenSSL 3.x, in a **Bash-compatible shell**:

```sh
# Capture the shell's original pipefail state and restore it afterwards.
if shopt -qo pipefail; then PIPE_FAIL_WAS_SET=1; else PIPE_FAIL_WAS_SET=0; fi
set -o pipefail

openssl genpkey -algorithm ED25519 -out operator_seed.pem
# raw public key (last 32 bytes of the SPKI DER) — public, safe to display:
openssl pkey -in operator_seed.pem -pubout -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n'
# raw seed (last 32 bytes of the unencrypted PKCS#8 DER) — capture ONLY;
# never run this bare, echo the variable, write it to a file or pass it as an argument:
export SEED_HEX
SEED_HEX=$(openssl pkey -in operator_seed.pem -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n')
EXTRACT_STATUS=$?
if [ "$PIPE_FAIL_WAS_SET" -eq 0 ]; then set +o pipefail; fi

if [ "$EXTRACT_STATUS" -ne 0 ] || ! printf '%s' "$SEED_HEX" | grep -Eq '^[0-9a-f]{64}$'; then
  unset SEED_HEX
  echo "REFUSED: seed extraction exited nonzero or the result is not exactly 64 lowercase hex characters. No seed is held; do not proceed to the §2 cross-check or any signing step. Do not reveal secret material when reporting this." >&2
fi
```

Both extraction forms yield exactly 64 lowercase hex characters; the public
hex is safe to display, the seed is not. The seed form above uses command
substitution so it is **captured** into `SEED_HEX` rather than printed. The
block above then performs the explicit checks the extraction procedure
requires, matching the discipline already written into D2 candidate-3
preflight §6(b):

1. the extraction pipeline's **exit status** is checked
   (`EXTRACT_STATUS`, captured under `set -o pipefail` so a failed
   `openssl` is not masked by the downstream `tail`/`od`/`tr` commands);
2. the resulting `SEED_HEX` is checked to match `^[0-9a-f]{64}$` (grep is
   fed from the variable's value only; nothing is printed to the terminal);
3. on **any** failure the seed variable is immediately `unset`, the
   procedure reports refusal for the operator to act on — without revealing
   secret material — and the operator stops: no §2 cross-check, no anchor
   pinning, no signing. A refused extraction must never be mistaken for a
   successful one.

The extraction output **is the seed**. It must never be printed to a terminal,
written to a file, or passed as a command-line argument (process arguments are
visible to other local users); it is held only in the shell variable captured
above, in the **same Bash-compatible shell** that exported it. Seed cleanup is
ordered by the workflow, not a single step:

- On **every** refusal or failed gate above (extraction status/malformed
  value, or any later cross-check mismatch), run `unset SEED_HEX` in that
  same shell immediately. Failed gates clear the seed right away.
- Do **not** unset the seed while a legitimate operation still needs it: the
  §2 public-key cross-check reads `SEED_HEX` from the environment, and a
  later approved same-shell operation (e.g. the §4 signing checklist) may
  also read it. Leave it set until the **last** legitimate use in that shell.
- After the **final** legitimate use — the §2 cross-check in this shell
  (or, if a same-shell signing step runs later, immediately after that
  step) — run, explicitly, in that same shell:

  ```sh
  unset SEED_HEX
  ```

  and verify it is gone with `test -z "${SEED_HEX:-}" && echo cleared`.
- `unset` removes the shell variable; it does **not** guarantee erasure of
  every possible copy from process memory. Do not treat it as such.

This procedure is environment-specific: it was tested on Linux with a
Bash-compatible shell, OpenSSL 3.6.3, and `tail`/`od`/`tr` present and
`xxd` absent.

Preserve the seed on encrypted operator media. Other tools make no
difference to the runner: verification accepts the standard encodings only.

> **Correction (2026-10-24, documentation only).** The earlier form of these
> two commands used `xxd -p -c 64`, and the seed command also carried
> `-noout`; that form produced zero bytes for the seed on the tested
> environment. The corrected pipelines above were validated in this session
> with **synthetic keys only** (a freshly generated key pair): both outputs
> were 64 hex characters and the extracted public key matched
> `ed25519_rfc8032.public_from_seed()`'s derivation; the published RFC 8032
> TEST-1 vector had likewise validated the same seed pipeline in the preceding
> review. **No production operator key was accessed, extracted, displayed or
> tested, and nothing was signed.** This correction is documentation, not
> authorization, and does not alter the pinned anchor, any candidate, or any
> authorization record.

## 2. Public-key material the runner requires

Exactly 32 raw bytes of the standard Ed25519 public key, as 64 lowercase
hex characters. Not the PEM/SPKI; not a hash of the key. The pinned change
must satisfy `ed25519_rfc8032.check_public` (decodable 32-byte curve
point) — which is what makes a mistyped or wrapped key refuse rather than
trust-fail silently. As a provenance cross-check, the operator confirms

```sh
# public key derived from the seed matches the published hex.
# SEED_HEX is the exported shell variable captured in §1; it is read from the
# environment, never passed as a command-line argument or echoed:
python3 - <<'PY'
import os, sys
sys.path.insert(0, "<repo>")
from app.simulation.openttd.proof import ed25519_rfc8032
seed = os.environ["SEED_HEX"].strip()
print(ed25519_rfc8032.public_from_seed(bytes.fromhex(seed)).hex())
PY
```

on the operator's own copy of the repo (off-runner, in the same shell as §1).
Output must equal the hex committed in step 3.

If the output does **not** match, this is a failed gate: run
`unset SEED_HEX` in that same shell immediately, report the mismatch without
revealing seed material, and do not proceed to any signing step.

If the cross-check **is** the last legitimate use of the seed in that shell
(no later same-shell signing step runs), clear it explicitly, in that same
Bash-compatible shell that holds `SEED_HEX`:

```sh
unset SEED_HEX
test -z "${SEED_HEX:-}" && echo cleared
```

If an approved signing step follows and needs `SEED_HEX`, do **not** unset
here; unset immediately after that final use instead. `unset` removes the
shell variable and does not erase every possible copy from process memory.

## 3. Reviewed change that pins the anchor (the approval artifact)

A reviewed pull request setting

```python
OPERATOR_PUBLIC_KEY_HEX: str | None = "<64-hex public key>"
```

in `app/simulation/openttd/proof/operator_authorization.py`. Review
approval requires the reviewer to record, in the PR itself:

- that the hex was produced from operator-held material (step 1) and
  matches the seed's derived public key (step 2),
- that the seed never touched the runner host or the repository,
- which operator/session issued the key (transcript reference).

Until this reviewed change lands, no launch-capable path exists — that is
the deliberate fail-closed state.

## 4. Signing the candidate-bound authorization (after staging, off-runner)

A fresh candidate must be staged, sealed and preflighted first (the
launch ceremony binds the signature to the candidate's own staged facts —
prelaunch digest, binary, retained world, target tile, budgets and the
exact `execution_command`). The operator then:

1. reads the candidate's PRELAUNCH metadata and recomputes the canonical
   authorization payload exactly as
   `operator_authorization.authorization_payload(metadata, seal)` does;
2. signs the canonical JSON bytes (sorted keys, compact separators,
   UTF-8) either with this repo's `sign_authorization_record` on their own
   off-runner copy, or with their own audited RFC 8032 tool. **For the
   current reviewed signing checklist only the repository-tooling path is
   approved; external-tool signing (Option 2) remains excluded until
   separately reviewed and approved.**
3. drops the record `{"payload": ..., "signature": "<128-hex>"}` into the
   candidate directory as `AUTHORIZATION.json` (canonical-JSON style, as
   `write_authorization_record` does).

If this signing step read `SEED_HEX` from the environment, clear it
immediately afterwards with `unset SEED_HEX` **in the same shell** that
exported it — this is that shell's last legitimate use of the seed. Do not
print, file, or pass the seed as an argument at any point here, and do not
assume `unset` erases every copy from process memory.

The reviewed checklist additionally refuses to start when any of
`AUTHORIZATION.json`, `CLAIM.json` or `LAUNCH-CONSUMED.json` already exists,
re-checks those records immediately before signing, and verifies the produced
signature under the pinned anchor over the exact canonical bytes **before**
writing. This generic section describes the artifacts, not a substitute for that
checklist; it grants no authority to sign or execute.

## 5. Explicit operator approval statement

Before the runner consumes the claim, the operator states — in writing,
in the review/PR thread referencing the candidate digest — that the exact
scope (candidate, tile, one bounded clear, budget table, command, key
identity) is approved. The signature alone proves possession of the
anchored key; the statement is the recorded human authorization decision.

## Residual rules

- Key rotation = a new reviewed change (steps 1–3). Grants minted under an
  older anchor verifiably refuse re-use afterwards
  (`operator_key_identity` binding), so rotation is safe.
- The LAN host must keep `cryptography==50.0.2` (the maintained
  verification backend, see `ed25519-verifier-preference.md`) consistent
  with `pyproject.toml`/`uv.lock`.
- No synthetic/test key may ever be pinned here; the test anchors are
  mocks inside isolated temporary candidates.

## Amendment 2026-10-21 — anchor seeded (LOCAL DEVELOPMENT PROOF)

The anchor was seeded by the operator on 2026-10-21, deviating deliberately
from non-negotiable 1 above: the Ed25519 key pair was generated **on the
runner host** — not off-runner. The setup is recorded as **LOCAL
DEVELOPMENT PROOF** (a local proof of the operator-authorization trust
boundary, not off-runner key isolation). The private key remains
operator-held material outside the Git repository at
`~/.local/share/openttd-operator/operator-private.pem` and was never
opened, read, copied or used by the runner. Full record, validations and
the candidate-bound next step:
`docs/handoff/2026-10-21/d2-native-clearing-candidate-3-preflight.md`.
