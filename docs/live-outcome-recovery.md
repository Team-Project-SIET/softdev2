# Recover a live outcome

Use the explicit recovery command when a live run has an `outcome-v1.json` manifest
and its terminal PostgreSQL transaction may not have completed:

```sh
transport-experiment recover artifacts/experiments/run-17/outcome-v1.json
```

The trusted artifact root defaults to `artifacts/experiments`. For a run stored
elsewhere, pass its independently chosen root with `--artifact-dir`. The manifest
path must be directly under that root in the expected `run-<id>` directory.

The command validates the manifest, its run directory, and referenced artifact
hashes before querying PostgreSQL. It reconciles only the original run's terminal
outcome. It does not start OpenTTD, rerun the final parser, or reconstruct missing
telemetry observations.

`recovery=recovered` means the terminal outcome was committed and verified in a fresh
database session. `recovery=already_reconciled` means the current database outcome
matches the manifest. Both exit with code 0. Invalid, unsupported, conflicting, or
unconfirmed outcomes exit with code 1 and leave the manifest in place. A conflict
requires investigation; recovery never overwrites a different terminal outcome.

Manifests, raw saves, and parsed artifacts remain after recovery. The command may
remove a temporary secret workspace only when a run-specific owner marker identifies
it and its recorded process group has no members. Older unmarked workspaces are
retained for manual inspection. No old PID is signaled during recovery.

## Manifest v1 trust boundary

Manifest v1 is trusted local recovery evidence. T15 detects structural corruption,
artifact tampering, filesystem/path attacks, identity mismatches, and database
conflicts. It does not cryptographically authenticate plausible edits to
manifest-only outcome fields because v1 has no external integrity anchor.

For example, if the database has no terminal outcome yet, a well-formed local edit
to a metric value or a failure code cannot be distinguished from the original v1
record. Keep the owned artifact directory protected. A stronger adversarial-tamper
model requires a separately specified manifest v2 with external authentication.
