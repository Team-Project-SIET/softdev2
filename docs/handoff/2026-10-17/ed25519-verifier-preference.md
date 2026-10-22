# Ed25519 verifier preference — decision recorded 2026-10-20

## Context

The D2 Native Clearing operator-authorization gate verifies Ed25519 records
through the vendored `app/simulation/openttd/proof/ed25519_rfc8032.py`
module (RFC 8032 §5.1, pinned by the published §7.1 vectors and the RFC §6
illustration implementation in `tests/test_ed25519_rfc8032.py`). The B2
review asked whether an established verifier backed by maintained crypto
should be preferred instead.

## Decision

**Preference: a maintained, established verifier — specifically
`cryptography.hazmat.primitives.asymmetric.ed25519` (Ed25519PublicKey /
Ed25519Verifier). The vendored `ed25519_rfc8032` module stays in use for
this repair, and is not silently replaced.**

Rationale for the preference:

1. A maintained crypto library removes the need to trust a hand-vendored
   implementation long-term; `cryptography` is the standard, audited,
   wheel-published choice and exposes Ed25519 verification directly.
2. The vendored module is pure Python and therefore not constant-time on
   `sign`. The runner only verifies, so this is currently acceptable, but a
   maintained backend closes the class of concern permanently.
3. The vendored module's correctness is proven today (published vectors +
   independent cross-implementation), so there is no security urgency: the
   preference is about long-term maintenance, not a present defect. B2 stays
   open and out of scope for this repair round.

## Why not migrated in this repair

- The verified `.venv` is offline and installs no maintained Ed25519
  provider today (`cryptography`/`pynacl` are absent from `uv.lock`).
  Introducing one mid-repair would change the environment identity the
  staged freezes pin (BLOCKER 4's dependency inventory hashes every
  installed byte) without a reviewed change of its own.
- The repair contract for this round forbids silently replacing the
  verifier; the switch is its own reviewed change.

## Migration implications (for the follow-up change)

- Dependency: add `cryptography` to the project environment; its native
  extension then automatically joins the BLOCKER 4 dependency inventory
  (every installed byte is frozen), so staging cost grows by hashing the
  library's files — no contract change.
- Signature/record compatibility: both paths are RFC 8032 Ed25519; the
  record format (`{"payload", "signature"}`) and the retained record bytes
  are unchanged, so historical AUTHORIZATION.json evidence re-verifies
  byte-for-byte under the new verifier.
- Key identity stability: `OPERATOR_KEY_IDENTITY_ALGORITHM`
  (`sha256-ed25519-public-key`) is derived from the raw 32-byte public key,
  independent of the verifying library, so retained claims and their
  operator key identities remain valid across the migration.
- Recommendation for the follow-up: migrate `verify` (and operator issuance
  tooling stays off-host), keep the vendored module only as the pinned
  reference implementation used by the vector tests, and note the change in
  the B2 blocker resolution.

## Resolution — 2026-10-20 (B2 executed as the follow-up change)

The premise above was corrected first: the pinned `.venv` was **not**
offline — the package index is reachable; only `cryptography` was absent
from it. The migration documented as "the follow-up" was therefore executed
and is now in place:

- `cryptography==50.0.2` (transitively `cffi==2.1.1`, `pycparser==3.11`)
  was installed into the pinned `.venv` and pinned exactly in
  `pyproject.toml` + `uv.lock` (additive-only lock change: no existing
  entry moved, so the pinned runtime is otherwise unchanged).
- New module `app/simulation/openttd/proof/ed25519_cryptography.py`
  implements total RFC 8032 `verify` over the maintained backend, and
  `operator_authorization._check_record_signature` now executes it — the
  single production verification call site. Nothing else changed: payload
  schema, canonical JSON encoding, record digests,
  `OPERATOR_KEY_IDENTITY_ALGORITHM` (`sha256-ed25519-public-key`) and the
  stored-key validation (`ed25519_rfc8032.check_public` in `_anchor_key`
  and `operator_key_identity`) are byte-for-byte identical, so retained
  replay evidence re-verifies unchanged.
- The vendored `ed25519_rfc8032` module is unchanged in code and remains:
  the pinned published-vector reference, the key-validation helper
  (`check_public`), and reference issuance tooling (`sign`, used
  off-runner). Only its docstring records the migration (the "offline"
  rationale is superseded).
- Pinned by `tests/test_ed25519_cryptography.py`: the published §7.1
  vectors under the maintained backend, full accept/reject agreement
  between the two implementations (valid, tampered, malformed input
  classes), byte-identical signing interop, and a vendored-issuance →
  maintained-verification pass at the authorization layer.
  `tests/test_ed25519_rfc8032.py` and the focused D2 suites (189 tests)
  stayed green.
- B2 is closed on the code path; the production trust anchor itself
  remains deliberately unseeded — see
  `docs/handoff/2026-10-17/operator-key-provisioning.md` for the
  operator-controlled provisioning procedure that must land under review
  before any launch-capable path becomes seizable.
