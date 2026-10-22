# Offline evidence contract baseline 1

The documented baseline identifier is `openttd-offline-evidence-contract-baseline-1`.
Its exact relevant source/document SHA256 values and current HEAD are recorded in
[the digest record](openttd-offline-evidence-baseline-1.json). HEAD is
`b10cd2dc99b241ff713b3211d87662be7d5136b7`; the uncommitted worktree is identified by
individual file digests, not HEAD alone. This is a documentation version, not a new
wire/evidence schema, native PRELAUNCH seal, authorization or proof attempt.

The [contract reference](openttd-offline-evidence-baseline.md) defines existing schema
identifiers, artifact inventories, validation boundaries and compatibility rules.
The [reconstructed audit summary](openttd-reconstructed-independent-audit-summary.md)
records 24 reported PASS cases with provenance limits. The original JSON remains
unavailable. No temporary audit file is needed to read or check this baseline.

Future changes to the recorded contract require explicit compatibility review,
including affected policy identifiers, mandatory artifacts, result/evidence bindings,
legacy rejection and CONTROLLED/REAL trust separation. Do not change these baseline
records in place to hide a changed contract. A future reviewed documentation baseline
can supersede this one without rewriting historical seals or proof records.

CONTROLLED acceptance is verified within its documented scope. Historical native
REAL_PASS remains supported; historical complete offline acceptance remains
AUDIT_BLOCKED with 13 missing canonical inputs. Historical 1,868 baseline artifacts
and 1,847 protected paths remain distinct from current broader file snapshots.
The [P08 plan](p08-multi-page-terrain-acquisition.md) authorizes no runtime action.
A new pure pagination module can be developed separately without altering this
single-page proof contract. Multi-page native proof packaging remains a later gate.
