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
With OpenSSL 3.x:

```sh
openssl genpkey -algorithm ED25519 -out operator_seed.pem
# raw public key (last 32 bytes of the SPKI DER):
openssl pkey -in operator_seed.pem -pubout -outform DER | tail -c 32 | xxd -p -c 64
# raw seed (last 32 bytes of the unencrypted PKCS#8 DER):
openssl pkey -in operator_seed.pem -noout -outform DER | tail -c 32 | xxd -p -c 64
```

Preserve the seed on encrypted operator media. Other tools make no
difference to the runner: verification accepts the standard encodings only.

## 2. Public-key material the runner requires

Exactly 32 raw bytes of the standard Ed25519 public key, as 64 lowercase
hex characters. Not the PEM/SPKI; not a hash of the key. The pinned change
must satisfy `ed25519_rfc8032.check_public` (decodable 32-byte curve
point) — which is what makes a mistyped or wrapped key refuse rather than
trust-fail silently. As a provenance cross-check, the operator confirms

```sh
# public key derived from the seed matches the published hex:
python3 -c "import sys; sys.path.insert(0, '<repo>'); from
app.simulation.openttd.proof import ed25519_rfc8032;
print(ed25519_rfc8032.public_from_seed(bytes.fromhex('<seed>')).hex())"
```

on the operator's own copy of the repo (off-runner). Output must equal the
hex committed in step 3.

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
   off-runner copy, or with their own audited RFC 8032 tool;
3. drops the record `{"payload": ..., "signature": "<128-hex>"}` into the
   candidate directory as `AUTHORIZATION.json` (canonical-JSON style, as
   `write_authorization_record` does).

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
