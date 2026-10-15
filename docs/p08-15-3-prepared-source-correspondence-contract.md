# Controlled prepared-source correspondence

This contract accompanies [supplemental facts](p08-15-3-supplemental-facts-controlled-contract.md).
It validates explicit identities without fabricating native save/load receipt evidence.
WPO remains valid when saved-world correspondence is missing. Real executable-source
admission is a separate fail-closed gate.

## Distinct semantic layers

| Layer | Identity / implemented relation | Evidence status |
|---|---|---|
| A. Original prepared-save bytes | `ControlledSourceLinks.original_save_digest`; optional owned fixture import hashes actual bytes | SOURCE_BYTES_VERIFIED for imported bytes, not parsed/loaded |
| B. PreparedWorldManifest | Existing immutable model; `source_digest` must be A or explicitly identified G; `world_manifest_hash` remains sole world_fingerprint | CONTROLLED_VALIDATED; fingerprint includes preparation/planner metadata, not only save bytes |
| C. Actual source loaded into runtime | `loaded_source_digest` equals A when asserted; None means missing | CONTROLLED_SIMULATED or MISSING, never real-proof receipt |
| D. Continuous M0→M1→M2 runtime | Existing WPO qualification and owner context | REAL_PROVEN historical Attempt 4; controlled imported linkage to A remains UNPROVEN |
| E. Final M2 structural observation | Exact existing structural digest and WPO match | REAL_PROVEN historical pipeline; matched typed input CONTROLLED_VALIDATED |
| F. Qualified M1 production collected in M2 | Existing production digest/WPO identity; unchanged exact structural-source and qualification gates | REAL_PROVEN historical pipeline; matched typed input CONTROLLED_VALIDATED |
| G. Post-qualification saved bytes | Separate nullable `post_qualification_save_digest`; optional owned fixture import hashes different bytes separately | None → UNPROVEN; present → CONTROLLED_SIMULATED; byte verification does not establish state correspondence |
| H. Candidate-generation input | Frozen composition of WPO/facts/correspondence; future candidate references retain separate digests | CONTROLLED_VALIDATED; P08 adapter not implemented |

`ControlledSourceLinks` schema has required original/runtime/config/bridge/world,
WPO/final-structure/production identities; loaded and final save digests are nullable.
Digests are lowercase SHA-256. `evidence_kind` is controlled-simulation or missing;
missing cannot claim loaded/final correspondence. Runtime/config/bridge/world and
observation references must exactly match the supplied WPO. Typed correspondence
requires manifest/native version/map dimensions and declared save source coherence.
Assembly additionally requires matching resolved seed and same owned WPO process/
connection context, not merely matching strings. WPO continues to validate native
rollover/stability qualification and exact produced-target coverage itself.

The model never substitutes A for G or a structure/production digest for a save digest.
A caller may reference a manifest whose source is original A for a controlled test;
this is not a post-qualification executable manifest. A future executable manifest
must use actual final G with independently established E/F-to-G correspondence.
The model permits A and G hashes to coincide only if their declared identities do;
the importer still hashes each supplied file separately. It does not assume evolved
world bytes are equal merely because map dimensions or industry counts match.

`import_prepared_source` independently reads/hashes bounded original and optional
final save **fixtures**, validates expected distinct link hashes, preserves bytes,
and returns SOURCE_BYTES_VERIFIED byte status with a CONTROLLED correspondence.
It does not parse save format, determine seed/content from bytes, execute a load,
perform a save, or attach real evidence. Declared final bytes must be supplied for
this import. Missing final evidence is representable in the pure model and blocks
real execution without invalidating observation/planning algorithm tests.

## Trust and admission

- CONTROLLED_FIXTURE: schema/semantic coherence with simulated or missing source links.
- SOURCE_BYTES_VERIFIED: importer calculated exact owned-byte hashes and checked
  accepted expected identities. Says nothing about native origin or live state.
- REAL_RUNTIME_CORRESPONDENCE_PROVEN: reserved for independently accepted owned
  load/continuous-runtime/final-capture evidence. There is **no issuer** here.

No trusted/verified/force flag grants authority. JSON real labels and extra fields
reject. `require_real_executable_source()` always rejects with an explicit unproven
correspondence error, including after successful fixture hashing or simulation.
The future native issuer must establish exact byte-to-load, uninterrupted qualification,
final state capture and save evidence through a separately reviewed contract.
No arbitrary caller assertion, map count comparison, structural digest or neighboring
log timestamp can satisfy that proof.

Controlled P08 algorithm development can proceed through the immutable validated
input. Real executable-source claims remain blocked. Qualification Attempts 1–3,
Attempt 4 PASS, V1–V5, complete raw and production proof history, CONTEXT.md and all
pre-existing P08/pure-type work are preserved. No native activity is required here.
