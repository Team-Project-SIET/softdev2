# Single-page terrain proof: one-launch authorization contract

## Trust model and operator authority

Repository source, Codex/automation, proof preparation, and the proof harness run
under the same user authority. That user can write source, local approval JSON,
and proof storage. A CLI flag, boolean, same-user file, file mode, or local digest
cannot establish independent operator approval against that authority. The seal
is a content identity and preparation boundary, not a trusted approval issuer.

The inspected runtime/proof code uses explicit caller permission flags. Secure
Admin authorized keys authenticate the network session, not operator consent to
launch. No independently authenticated approval service, operator signing trust
store, or OS-protected approval/launcher boundary is configured. **Production
issuer unavailable; trusted authorization is blocked.** No key is generated,
cryptographic scheme invented, real approval issued, or attempt consumed here.

A future trust anchor must be administered independently of the preparation
process: operator authentication, an authenticated issuer identity and approval
verification, and issuer configuration that automation cannot replace. Examples
are an existing authenticated external approval service or an independently
administered OS-protected launcher/approval store. Choosing and provisioning that
anchor is a separate operator decision, not a self-asserted local file. If that
anchor uses signatures, use its established signature format and a maintained
verification library; this task does not implement a signing protocol.

## Schema and seal binding

`proof/terrain_authorization.py` defines immutable `OneLaunchAuthorization`.
Exact fields, with unknown fields rejected:

| Field | Meaning |
| --- | --- |
| schema | `openttd-terrain-one-launch` |
| version | integer 1 |
| authorization_id | issuer-correlated approval identity |
| seal_sha256 | exact immutable PRELAUNCH bytes, lowercase SHA256 |
| attempt_identity | exactly the identity reserved in that seal |
| attempt_directory | exactly the canonical absolute proof destination |
| authorized_launch_count | integer 1; booleans rejected |
| proof_operation | `openttd-15.3.tile_facts_page.single_page` |
| issuer_id | independently authenticated issuer identity |
| approval_evidence | bounded opaque authenticated approval evidence |

Identity strings are ASCII tokens of at most 128 characters, destination at most
1024 characters, and approval evidence at most 4096 UTF-8 bytes. The approval
subject is canonical sorted compact JSON of all fields except `approval_evidence`.
The issuer must authenticate that exact subject; the evidence is not trusted
merely because it exists. Input dictionary ordering does not affect the subject.
No expiration is asserted: a future issuer must define its clock/validity policy
before expiration fields can be admitted. The present validity limit is one exact
seal/attempt/destination/operation and at most one claimed attempt.

## Validation and issuance boundary

`terrain_seal.validate_authorization()` requires the immutable seal and every
candidate/source/asset/materialization check, then exact artifact schema and
binding, an absent attempt root, and issuer verification. Production callers do
not inject an issuer: they continue to fail closed. Controlled tests use an
isolated opaque approval registry matching the exact canonical subject, issuer,
and evidence. That registry is not a production service, credential, or signer.
The existing injected authority callback remains a controlled validation seam;
no native entry point exposes it as permission.

Missing or fabricated approval, unknown issuer, altered evidence or subject,
wrong seal/attempt/destination/operation/count, consumed attempt, changed source,
and changed package are rejected. The same artifact cannot be replayed for
another destination or seal. The attempt root is the per-approval replay ledger;
there is no separately trusted global authorization-ID ledger or revocation
service yet. Those policies belong to the future independent issuer.

## Launch routes and durable one-shot consumption

Legitimate terrain routes are `authorized_native_run()` to
`execute_single_page()` to `SinglePageNativeBackend.launch()`. Direct entry into
the executor's REAL mode still validates authorization before creating the root.
The backend independently runs the strict `validate_final_prelaunch()` immediately
before Popen and requires its owned launch claim. Candidate-only, seal-only, or
boolean-only execution cannot pass. Production issuance/consumption integration
remains inaccessible pending the trust anchor; no controlled callback reaches it.
Historical native proof modes have their own explicit authorization contracts;
they are not terrain approval routes and were not rewritten. This module cannot
prevent a malicious same-user process from invoking Popen directly, monkeypatching
Python, modifying verifier source, or deleting a same-user replay ledger. That
requires the independent deployment/OS boundary described above.

The controlled consumption seam now uses exclusive `mkdir(0700)` as its
cross-process claim, fsyncs the parent, writes and fsyncs
`authorization-consumed.json`, and fsyncs the attempt directory before returning.
The record is explicitly `CONTROLLED_AUTHORITY_VALIDATION`, state STARTED, and
binds approval and issuer identities. Two competing acquisitions admit at most
one. A failed write, simulated crash, or post-claim integrity failure keeps the
root; no retry, deletion, replacement, reconnect, or resume releases the claim.
Directory existence alone means consumed, even if the consumption file is absent.
An fsync failure is fatal; durability is not claimed after failed fsync.

After durable acquisition, seal and sources are checked again. A source change
inside the controlled approval callback fails after claiming and retains consumed
state. This closes that tested verification/acquisition gap; it does not make all
filesystem reads plus Popen atomic against malicious same-user replacement. A
future independently protected native launcher must own the claim and ledger,
verify approval and frozen inputs immediately before launch, and retain consumption
on every post-claim failure. No production path is enabled until this is reviewed.

## Existing seal invalidation

The existing PRELAUNCH SHA256 remains
`0d98f819f085b66a098ccb8c787de174cc0625bc6caea689885ff42ec142a663`, reserving
`terrain-single-page-809378528d2d4b36a4e1c5ef9cb68b57`. Its bytes and read-only modes
are preserved. This implementation changes frozen `terrain_seal.py`; it also
adds runtime-critical `terrain_authorization.py` not present in the old inventory.
Therefore **STALE_SEAL_REQUIRES_REPREPARATION**. All 185 original inputs are audited;
unchanged seal bytes do not imply unchanged source. Candidate-v2/v3 remain retained,
but their frozen source identity cannot admit the repaired current source.

No old inventory, candidate, or seal is updated. No replacement is created.
After the trust-anchor design and source settle, a separately requested fresh
candidate/preflight and renewed immutable unauthorized seal must include all
current runtime-critical files. Only then may the operator consider issuance.

## Controlled verification and future operator procedure

Tests cover schema and binding failures, canonical ordering, unknown/forged issuer
and evidence, missing approval, controlled-only validation, production rejection,
concurrent claim exclusion, fsync durability, crash retention, replay rejection,
and post-approval source drift. Existing package/VM, fake-child, source, transport,
accounting, cleanup, lineage, P08/P05 and ordinary regressions remain required.
There is no real OpenTTD launch, live Admin session, or native query.

Future operator action must: select/provision the independent anchor; review its
verifier and protected launch/replay ownership; settle source; request fresh
preparation and sealing; independently review the exact seal and destination;
authenticate to the issuer to approve one bound operation; then separately
explicitly authorize the one-shot native run. Issuance must never modify the seal.
No usable real issuance command is supplied while the anchor is absent.
