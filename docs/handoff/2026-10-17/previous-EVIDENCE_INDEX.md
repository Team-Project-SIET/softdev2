# Evidence index

Collected 2026-10-16 from the local dirty worktree. Paths are repository-relative.
SHA-256 identifies inspected bytes; it does not authenticate a claim or authorize
execution. E1–E3 are handoff snapshots, not replacements for historical protection
manifests, immutable seals or independently reviewed digests. The source inventory
was captured before the intentional CONTEXT update. Secrets, symlinks, environments,
Git internals and caches are excluded; no secret contents are retained here.

E4 is a fresh 47-test controlled run, exit 0. E8 is a fresh exact-VM seven-case run,
exit 0, no OpenTTD game process or Admin connection. E5/E6 are read-only historical/
prepared evidence inspection. E9/E10 were not fully replayed in this handoff. E11
contains historical reports and an explicitly reconstructed audit summary; those
reported counts are not fresh executions. E12 identifies design/implementation
contracts, not native success. See AI_HANDOFF for proposition-level limits.

The complete nonsecret artifact inventory has 29,517 regular files, distinct from
the older 1,868-artifact historical baseline. The source/doc inventory has 768 files.
Neither count is a new runtime acceptance gate. Ignored artifacts are local-only;
Git does not back them up. Missing paths on another machine remain missing evidence.
Do not commit or transmit raw attempt directories without credential review.

## Selected immutable artifacts and references

| ID | Path | SHA-256 |
|---|---|---|
| E1 | [docs/handoff/environment.json](docs/handoff/environment.json) | `97632cd33e0ae5cea742f92aecefea471a11bc1db7c0e95630509bec9c93a118` |
| E1 | [docs/handoff/git-status-before.txt](docs/handoff/git-status-before.txt) | `f7b3438bac839e83df2816ebfc589e85a36bdcca871194f85108ea80b37e84b1` |
| E1 | [docs/handoff/tracked-diff-before.stat](docs/handoff/tracked-diff-before.stat) | `5d091d39a1863e2567caa3660b859bbfec1952c6636612725c98192cd37cde2c` |
| E2 | [docs/handoff/repository-files-before.json](docs/handoff/repository-files-before.json) | `ff203a4eec630427dd88fc70a5528c0c7919c31823be3cd6dc400c1a313d7856` |
| E2 | [docs/handoff/context-before.md](docs/handoff/context-before.md) | `98f860ef83b21aefae39863fdde8e040ee0df5ebf0dc2bde9428fa918dd78e83` |
| E3 | [docs/handoff/local-artifacts-before.json](docs/handoff/local-artifacts-before.json) | `aaf1c33c351b5a121abfa2cb6940ba360dae2d1a2a8d853c40bc52e0d9da4d1b` |
| E4 | [docs/handoff/focused-tests.txt](docs/handoff/focused-tests.txt) | `325b7cf7b0d6ead544ebb7e833a08009fa10cf90ce29b8f9021e2ede461488f5` |
| E4 | [tests/test_native_save_path.py](tests/test_native_save_path.py) | `77705ce0ee8760daa321768af0c51d7fda61488a5f17c4af1c504c7d9440d767` |
| E4 | [tests/test_canonical_fleet_driver.py](tests/test_canonical_fleet_driver.py) | `ffd4a4f3ecb0fbc857b0ddbecb83fa65fbc0d6fd42f2bb2e868c378a1d5cdd2f` |
| E5 | [artifacts/runtime/canonical-fleet-create-q1/result.json](artifacts/runtime/canonical-fleet-create-q1/result.json) | `15caa8951c1f14e120849e59f22923c5bc8a884b10c73e68595704d89a755325` |
| E5 | [artifacts/runtime/canonical-fleet-create-q1/PRELAUNCH.json](artifacts/runtime/canonical-fleet-create-q1/PRELAUNCH.json) | `835083b007218d7f0830156d1c6a52ca64cff0a68ebfae561eb6731d54ee69b0` |
| E5 | [artifacts/runtime/canonical-fleet-create-q1/artifact-manifest.sha256](artifacts/runtime/canonical-fleet-create-q1/artifact-manifest.sha256) | `cfd68eb62ba5e26d2cdba84f2c0c933d55722db0c00dbc3172f2b4d2788a4ed3` |
| E5 | [artifacts/runtime/canonical-fleet-create-q1/frozen-source.zip](artifacts/runtime/canonical-fleet-create-q1/frozen-source.zip) | `47c200cae7c2dc3fddc568f3e811276d55f6d38e1d0d736b42ee623c13a23c10` |
| E5 | [artifacts/runtime/canonical-fleet-create-q1/stderr.log](artifacts/runtime/canonical-fleet-create-q1/stderr.log) | `22f7a06ef5b376c68cb03ad42b6ebc7cc4b01fda656b560f3fef4e2a33bf016e` |
| E6 | [artifacts/validation/canonical-fleet-create-q2/suspension.json](artifacts/validation/canonical-fleet-create-q2/suspension.json) | `7db5b9ca1673b22ed773e62f9a249df7182dd7b2c3cb072aa2c4fdf0989dadfc` |
| E6 | [artifacts/runtime/canonical-fleet-create-q2/PRELAUNCH.json](artifacts/runtime/canonical-fleet-create-q2/PRELAUNCH.json) | `f4cd87aee4ca603702efb72b99d0c69b32348838f0e6873f63ef4979c41e53c5` |
| E6 | [artifacts/runtime/canonical-fleet-create-q2/PRELAUNCH.sha256](artifacts/runtime/canonical-fleet-create-q2/PRELAUNCH.sha256) | `8429cb3ba97ed11dd9d69af9bcd46529148e68d9ffb097e125adcc778f780b76` |
| E6 | [artifacts/runtime/canonical-fleet-create-q2/frozen-source.zip](artifacts/runtime/canonical-fleet-create-q2/frozen-source.zip) | `9301f5db6aba3d7aad6f10b95385c74100b8872b83f8000e254e859c4b88697a` |
| E7 | [docs/capacity-experiment.md](docs/capacity-experiment.md) | `8353c7609f2af3437724642aec11dd3bb636b55dd8b52799e0834fc24e5c8c96` |
| E7 | [app/simulation/openttd/proof/canonical_fleet.py](app/simulation/openttd/proof/canonical_fleet.py) | `029bc735c8a5ef73c3ff276fbd4c0b5a08295d0f05913c9942f8209f79dbabf2` |
| E7 | [app/simulation/openttd/proof/road_mutation.py](app/simulation/openttd/proof/road_mutation.py) | `ddef5d5e3cabe2a31ef88edf0e6f683683c3e295770e30ff23523136fdae7c15` |
| E8 | [docs/handoff/squirrel-validation.txt](docs/handoff/squirrel-validation.txt) | `8fbbecab47341c865ce53232042a07ab9feba628dd15cc11c504ef4fa2d2ed44` |
| E8 | [docs/handoff/suspension-rerun.json](docs/handoff/suspension-rerun.json) | `7db5b9ca1673b22ed773e62f9a249df7182dd7b2c3cb072aa2c4fdf0989dadfc` |
| E8 | [tests/validate_canonical_squirrel.py](tests/validate_canonical_squirrel.py) | `0b6a8bfa8d22a4b216db71fe66c1ff660701412d752fb98cf587f06777fe2985` |
| E8 | [tests/support/canonical_startup_vm.nut](tests/support/canonical_startup_vm.nut) | `eb130d78dcbb8076500e909bf2791b3f49ed3cd5e8e3b15c3e15f52b31e1c192` |
| E8 | [tests/support/openttd_squirrel_suspend.cpp](tests/support/openttd_squirrel_suspend.cpp) | `0eb9552875d46950dd0919f22816c12948a562071fbfae860c0512406d3440ea` |
| E9 | [README.md](README.md) | `6e4b2c5d7eb57af6c5efb18a817719341a5139741e883e84962918362cdcfa14` |
| E9 | [docs/first-freight-delivery-proof.md](docs/first-freight-delivery-proof.md) | `28caf0c24612153393aa0ad0d08b375154f0cdc995132b32530d58cd2e61725c` |
| E9 | [artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4/receipt.json](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt4/receipt.json) | `0ecf7793e45c7a55d8f954479891b0341b383200a2c01665bae6284acee21cd6` |
| E9 | [artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9/receipt.json](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9/receipt.json) | `6d28ceb4d30283d5de234e7287f2f32b57f2fd99e86107ab69f479682cddb246` |
| E9 | [artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12/receipt.json](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt12/receipt.json) | `df7320c28bd8acddb2c96bac0a9f0f3861eee8ce09e4e9492c83b8b0778b8060` |
| E9 | [artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/receipt.json](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/receipt.json) | `317f98eb1ab74dfc5728ab1adc1d9e43a7c0255e6472e73774a20122ecb93c34` |
| E10 | [artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/result.json](artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/result.json) | `583584e679087552c9b2fe6811df4c5026baad90e3168e4c0e433daf680839ba` |
| E10 | [artifacts/experiments/attempt19-offline-recovery/derived-finalization.json](artifacts/experiments/attempt19-offline-recovery/derived-finalization.json) | `025154c472a611af02f16feb341aa5789b8fb93814d87bf8920f26c39ecc5234` |
| E10 | [artifacts/experiments/attempt19-offline-recovery/verification.json](artifacts/experiments/attempt19-offline-recovery/verification.json) | `c90a13e469e65022addec92ff85e983b85a64bd7fb6197db6929791fa1d3e162` |
| E10 | [artifacts/experiments/p07-attempt19-five-year-offline/summary.json](artifacts/experiments/p07-attempt19-five-year-offline/summary.json) | `1a1eb384cdbdd96b07a71f8852f2094ccc3a8d45f6d8f902494439bea3ea7b84` |
| E11 | [docs/specs/openttd-offline-evidence-freeze.md](docs/specs/openttd-offline-evidence-freeze.md) | `6aa3e9c2ce0b89322a2078abe15f2393b80ca485a33f883a0b02a9e2e13c8616` |
| E11 | [docs/specs/openttd-offline-evidence-baseline.md](docs/specs/openttd-offline-evidence-baseline.md) | `520f0317031e545b548ec842fae41ae055cad435aa7c06b3034e77d3c92eb309` |
| E11 | [docs/specs/openttd-offline-evidence-baseline-1.json](docs/specs/openttd-offline-evidence-baseline-1.json) | `bd5e3838cc5581150ee834ce2995611fd8728d2cd1a1b666dc82ba4c7260e0e0` |
| E11 | [docs/specs/openttd-reconstructed-independent-audit-summary.md](docs/specs/openttd-reconstructed-independent-audit-summary.md) | `d4b0b371823e3b14c2a88a3e5601d508b3854bf566fb6a819d92d7655d46a2c4` |
| E12 | [docs/specs/p08-multi-page-terrain-acquisition.md](docs/specs/p08-multi-page-terrain-acquisition.md) | `bc9af075344ddce54d47495d4d224d6bd5a982e99587414942652d1bb64e6427` |
| E12 | [docs/specs/p08-native-multi-page-integration-design.md](docs/specs/p08-native-multi-page-integration-design.md) | `3eb3eeda7dca3dde957ab888b662147d21a5c9bf77c020ddd91ef5e28f2a179a` |
| E12 | [docs/specs/p08-two-sweep-equality-design.md](docs/specs/p08-two-sweep-equality-design.md) | `ce9b8a167f6461d36fce68a0071851f79b170bca5257c5d3ffa137c6709e6b1f` |
| E12 | [docs/specs/terrain-paired-evidence-v1.md](docs/specs/terrain-paired-evidence-v1.md) | `b3146840453b75249a0e0d10341734c212c8b1f3147af7d6a718e670269181c6` |
| E12 | [docs/specs/terrain-native-paired-evidence-v1.md](docs/specs/terrain-native-paired-evidence-v1.md) | `7016da39c640ab9383a6189ae4dccca5986d9d5762eaafdc2bf5e1e3fa45e5a7` |

## Preservation and provenance

The Q1 archive, PRELAUNCH, result and manifest must remain byte-identical. Q2's
prepared package and frozen VM report also remain unchanged. Logs and save files
for all retained attempts are indexed in E3; check exact paths/hashes there rather
than searching prior conversations. The original 24-case audit JSON is unavailable;
E11's secondary summary cannot restore exact payloads or primary evidence.
Historical native REAL_PASS and complete offline acceptance are separate claims.

The repository inventory excludes private files by filename and is a digest-only
record, not a complete secret-scanning certificate. `.env` and runtime private keys
must be managed outside Git. No credentials were opened or copied into this package.
The original CONTEXT rules remain in CONTEXT and E2's unchanged archival copy.

Final handoff integrity checks are recorded in
[docs/handoff/integrity-check.json](docs/handoff/integrity-check.json).
The repeatable checker is [docs/handoff/verify_snapshot.py](docs/handoff/verify_snapshot.py).
It verifies captured public files and implementation bytes; it is not a production
proof validator and never grants runtime authority.

Fresh execution commands and exit codes are retained in
[docs/handoff/run-record.json](docs/handoff/run-record.json). The fresh VM report
is byte-identical to the frozen Q2 report. Local handoff link checks are recorded
in [docs/handoff/document-check.json](docs/handoff/document-check.json).
