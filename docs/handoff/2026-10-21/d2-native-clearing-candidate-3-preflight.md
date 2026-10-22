# D2 Native Clearing — Candidate-3 preflight handoff

Status: **D2 CANDIDATE-3 PREFLIGHT PASSED — AWAITING OPERATOR SIGNATURE**

No OpenTTD launch was performed, no AdminPort connection was opened, no claim
was consumed, no tile was cleared, and no Git commit/push/reset/clean/stash
was made for this work.

## 1. Operator key provisioning — LOCAL DEVELOPMENT PROOF

`OPERATOR_PUBLIC_KEY_HEX` in `app/simulation/openttd/proof/operator_authorization.py`
was seeded on 2026-10-21 with the operator-supplied Ed25519 public key.

| Item | Value |
| --- | --- |
| Public key hex | `5063982bd28d48573705f334ed4f396618c4930ce21083789dfbbf13a564880f` |
| Fingerprint (`operator_key_identity`) | `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` |
| Setup class | **LOCAL DEVELOPMENT PROOF** — the key pair was generated **on the runner host**, not off-runner |
| Private key location | Operator-held material **outside the Git repository** at `~/.local/share/openttd-operator/operator-private.pem` |

The runner never opened, read, copied, printed or signed with the private
key; the runner never generated a replacement key. Only the 32-byte public
key entered the repository.

Recorded deviation: this setup does **not** satisfy the off-runner isolation
requirement (non-negotiable 1) of
`docs/handoff/2026-10-17/operator-key-provisioning.md`; it is provisionally
accepted as a local development proof of the operator-authorization trust
boundary, and the anchor semantics (fail-closed, operator-only signatures,
rotation binding) are unchanged.

Validation performed with the existing production rules only:

- the pinned hex decodes to exactly 32 bytes;
- `ed25519_rfc8032.check_public` accepts it (decodable curve point);
- the maintained `cryptography` backend (`Ed25519PublicKey.from_public_bytes`)
  round-trips the identical 32 bytes — compatibility with
  `app.simulation.openttd.proof.ed25519_cryptography` confirmed;
- `operator_key_identity` derives the recorded fingerprint and
  `_anchor_key(None)` resolves to the same key;
- the test suites below were updated for the seeded anchor: the module-level
  unseeded guards in `tests/test_terrain_clearing_native_prep.py` and
  `tests/test_terrain_clearing_adversarial.py` now assert the seeded,
  fingerprint-checked anchor, and the adversarial suite additionally gained
  `test_production_anchor_refuses_records_not_signed_by_the_operator` (the
  fail-closed unseeded path is still exercised by patching the anchor to a
  falsy value explicitly).

## 2. Source freeze and dependency integrity

- Concurrent-session check: no other agent session was running; no file in
  the repository was modified by anything besides this provisioning work
  (mtime scan across the repo; the only changed files are the four additions
  below); no Git index lock existed. The dirty tree set found at session
  start was re-compared verbatim afterwards and is preserved.
- All pre-existing dirty-tree changes were left byte-for-byte untouched.
  The production review state is frozen into the candidate as-is.
- No architecture review was started.

Focused regression suites (offline, controlled peers only):

| Suite | Result |
| --- | --- |
| `tests/test_ed25519_cryptography.py` + `tests/test_terrain_clearing.py` | 43 passed |
| `tests/test_terrain_clearing_native_prep.py` | 53 passed |
| `tests/test_terrain_clearing_adversarial.py` | 74 passed |
| `tests/test_native_clearing_repair.py` | 27 passed |

Dependency integrity: `uv lock --check` resolves cleanly against
`pyproject.toml`/`uv.lock`; `cryptography==50.0.2` (the maintained
verification backend) is installed; the exact installed dependency bytes
(pydantic, pydantic_core, ortools, google/abseil, monocypher and every other
runtime-reachable distribution) are SHA-256 inventoried and frozen into the
candidate record by `d2_dependency_inventory()`.

Changes this work made (all related to the provisioning step):

- `app/simulation/openttd/proof/operator_authorization.py` — anchor seeded; docstrings/comments updated to the seeded, LOCAL-DEVELOPMENT-PROOF record;
- `tests/test_terrain_clearing_native_prep.py`, `tests/test_terrain_clearing_adversarial.py` — stale "unseeded" assumptions updated;
- `docs/handoff/2026-10-17/operator-key-provisioning.md` — dated amendment appended;
- this handoff document.

## 3. Candidate-3 identity and verified target facts

Freshly staged candidate (never reused candidate-1 or candidate-2; both
remain untouched as historical evidence, as does all other historical
artifacts — the retained census manifest, source save and qualified save
re-verified by seal each time):

| Fact | Requirement | Staged value | Verified against source evidence |
| --- | --- | --- | --- |
| OpenTTD version | 15.3 | `15.3` (`RuntimeIdentity("15.3")`), binary `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` at `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd` | byte-verified against the pinned identity |
| Seed | 17 | `seed: 17` in `expected_welcome` | sealed census `CANDIDATE.json` `retained_welcome` (sha `a3559852d523f46486488ac6a2d0f0ba3c29c4ca37f2145f7e15a6fb286a5765`) |
| Target tile | 46769 | `target_tile: 46769` | sealed census page `classification-p034-response.json` row `[46769, 2, 0, 9, None, -1]`, page sha `7ab777648aed5450287f964ac7e334a9c1881dbe5bdf502cc8ea22b5d3c9e5af` |
| Expected classification | TREE | pinned `classification: TREES`, tile-type flags `9`, geometry (2, 0), unowned (`owner: -1`), no industry | census taxonomy value for the tree tile group |
| Max real clearing operations | 1 | `budgets.real_clears: 1` | staged record + admission contract |
| Max launches | 1 | `budgets.launches: 1` | staged record + one-shot launch gate |
| Max AdminPort connections | 1 | `budgets.connection_attempts: 1` (plus `reconnects: 0`, `retries: 0`) | staged record + ceremony |
| Retries | 0 | `budgets.retries: 0` | staged record + one-shot claim schema |
| Max clearing cost | £10,000 | `max_cost: 10000` (`MAX_CLEARING_COST`), `company: 0`, command `GSTile.DemolishTile(tile)` | staged plan policy + quote/stop rules |

Retained world identity (save-load composition; no reseed — the staged
config has no `[game_creation]` block):

- retained directory: `artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253`
- source save: `before.sav`, SHA-256 `e81f655363347b808daf07e504dee281144cc095cbec128f0b3c0ff7b127117c`
- qualified save digest: `a51ffe47c848e02b1207e959d78ea5e5596feffc1e4444555439ab9c94191e93`
- expected welcome: revision `15.3`, seed `17`, landscape `0`, 256×256, start_day `712223`
- staged GameScript identity: name `RoadFreightProof`, version `1`, create_instance `NetworkFreightProof` (staged `info.nut` byte-identical to the save's stored identity from the retained frozen-source evidence)

## 4. Offline preflight — all checks PASS

Preflight ran twice independently (once during preparation via the `prepare`
CLI, once via `reopen` + `preflight`): read-only, opens nothing, consumes
nothing, and both runs returned PASS.

- Exact OpenTTD binary identity: PASS (sha256 == pin; live re-check).
- Source-save identity and SHA-256: PASS (retained `before.sav`, its binding
  record, and the staged copy digest all equal).
- Candidate-specific PRELAUNCH seal: PASS (`PRELAUNCH.sha256` matches the exact
  staged bytes; see digest in §5).
- Complete source and dependency freeze: PASS (`verify_freeze` +
  `require_frozen_d2_closure` + `require_frozen_d2_dependencies`; the
  full runtime source closure — transitive, conditional, dynamic and package
  initializers — and the exact installed dependency bytes are frozen).
- Staged GameScript identity: PASS (see §3).
- Operator public-key identity: PASS (§1).
- Exact execution command: PASS (§5, `execution_command`).
- Launch and clearing budgets: PASS (§3).
- One-shot claim is absent: PASS (`CLAIM.json` absent; `claim_status == "ABSENT"`).
- Authorization has not been consumed: PASS (no `AUTHORIZATION.json`, no
  `LAUNCH-CONSUMED.json`).
- No conflicting native process: PASS (`matching_processes` empty; no
  `openttd` process on the host).

Staged authorization note (descriptive metadata only): the candidate's
`authorization` field remains `PENDING — requires ONE fresh operator
authorization after all preflight gates; offline staging consumed no claim
and no authorization file exists`.

## 5. Operator handoff package

1. **Candidate directory**
   `/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3`
2. **Candidate seal (exact PRELAUNCH.json SHA-256)**
   `b2636e0d5e6f3197970635aac08a1a428a69d0bb99016bff23eee30fac5acf0b`
3. **Operator key fingerprint**
   `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614`
4. **Exact proposed native execution command** (from the staged
   `execution_command`; one process, one owned secure session, budgets above)
   ```
   /home/fed/codes/softdev2/.venv/bin/python -m app.simulation.openttd.proof.terrain_clearing run /home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3
   ```
5. **Exact authorization payload** — SHA-256
   `0ca2cf7a12583d39c84c45673421cc60e8079e3a7e8ce8a03ffa229df481d4da` over the
   canonical bytes below (sorted keys, compact separators, UTF-8) — the
   exact byte string the operator signature covers:

   ```json
   {"attempt":"D2-CLEARING-1","binary_sha256":"276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c","budgets":{"connection_attempts":1,"gsadmin_bytes":1450,"launches":1,"readiness_seconds":45,"real_clears":1,"reconnects":0,"request_seconds":10,"requests":8,"response_bytes":512,"retries":0,"total_seconds":180},"clearing_command":"GSTile.DemolishTile(tile)","company":0,"execution_command":["/home/fed/codes/softdev2/.venv/bin/python","-m","app.simulation.openttd.proof.terrain_clearing","run","/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3"],"max_cost":10000,"milestone":"D2-CLEARING","prelaunch_sha256":"b2636e0d5e6f3197970635aac08a1a428a69d0bb99016bff23eee30fac5acf0b","schema":"d2-clearing-native-prelaunch-v2","source_world":{"expected_welcome":{"height":256,"landscape":0,"revision":"15.3","seed":17,"start_day":712223,"width":256},"qualified_save_sha256":"a51ffe47c848e02b1207e959d78ea5e5596feffc1e4444555439ab9c94191e93","retained_directory":"/home/fed/codes/softdev2/artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253","save_sha256":"e81f655363347b808daf07e504dee281144cc095cbec128f0b3c0ff7b127117c","source_save":"before.sav"},"stale_rule":"re-observe the target immediately before admission; any pin mismatch stops the attempt without any command","target_tile":46769,"workspace":"/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3/isolated/openttd-15.3-xwqa0u6r"}
   ```
6. **Repository-supported signing procedure** — executed BY THE OPERATOR
   (LOCAL DEVELOPMENT PROOF: the private key lives on this host but is
   operator-held material; the agent-run code must never touch it), per
   `docs/handoff/2026-10-17/operator-key-provisioning.md` §4:

   ```sh
   cd /home/fed/codes/softdev2

   # (a) Recompute the payload from the candidate's own staged bytes (do not
   #     trust any printed copy — including this document):
   .venv/bin/python - <<'PY'
   import hashlib, json
   from pathlib import Path
   from app.simulation.openttd.proof.harness import sha256
   from app.simulation.openttd.proof.operator_authorization import (
       authorization_payload, canonical_authorization_bytes,
   )
   d = Path("/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3")
   seal = sha256(d / "PRELAUNCH.json")
   canon = canonical_authorization_bytes(authorization_payload(json.loads((d / "PRELAUNCH.json").read_text()), seal))
   assert seal == "b2636e0d5e6f3197970635aac08a1a428a69d0bb99016bff23eee30fac5acf0b"
   print("payload sha256:", hashlib.sha256(canon).hexdigest())
   Path("/tmp/opencode/d2-candidate-3 Authorization-payload.bin").unlink(missing_ok=True)
   Path("/tmp/opencode/d2-candidate-3-payload.bin").write_bytes(canon)
   # expect: 0ca2cf7a12583d39c84c45673421cc60e8079e3a7e8ce8a03ffa229df481d4da
   PY

   # (b) Sign — either option, then record:
   # Option 1 (repository issuance tooling; the operator keeps the seed out
   # of any file, prompt or log):
   SEED_HEX=$(openssl pkey -in ~/.local/share/openttd-operator/operator-private.pem -noout -outform DER | tail -c 32 | xxd -p -c 64)
   .venv/bin/python - <<'PY'
   import os
   from pathlib import Path
   from app.simulation.openttd.proof.operator_authorization import (
       canonical_authorization_bytes, sign_authorization_record,
       write_authorization_record,
   )
   from app.simulation.openttd.proof.operator_authorization import ClearingAuthorizationError
   payload_bytes = Path("/tmp/opencode/d2-candidate-3-payload.bin").read_bytes()
   import json
   payload = json.loads(payload_bytes)
   assert canonical_authorization_bytes(payload) == payload_bytes
   record = sign_authorization_record(payload, os.environ["SEED_HEX"].strip())
   write_authorization_record(
       Path("/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3"),
       record,
   )
   PY
   unset SEED_HEX
   # Option 2 (any audited RFC 8032 tool; -rawin gives the RFC 8032 signature):
   #   openssl pkeyutl -sign -inkey ~/.local/share/openttd-operator/operator-private.pem \
   #       -rawin -in /tmp/opencode/d2-candidate-3-payload.bin -out /tmp/opencode/d2-candidate-3-sig.bin
   # then assemble AUTHORIZATION.json in the candidate directory as:
   #   {"payload": <the payload object>, "signature": "<128-hex of the 64-byte signature>"}
   # (canonical-JSON style, exactly as write_authorization_record writes it)

   # (c) Optional read-only self-check before handing back (never
   #     `run`; that consumes the one-shot claim):
   .venv/bin/python -c "from pathlib import Path; import json; from app.simulation.openttd.proof.harness import sha256; from app.simulation.openttd.proof.operator_authorization import verify_authorization; d = Path('/home/fed/codes/softdev2/artifacts/experiments/d2-clearing-native-candidate-3'); metadata = json.loads((d / 'PRELAUNCH.json').read_text()); verified = verify_authorization(d, metadata, sha256(d / 'PRELAUNCH.json')); print('BINDS:', verified.authorization_sha256, verified.operator_key_identity)"
   ```

   After a valid `AUTHORIZATION.json` is in place, the operator states the
   explicit approval for this exact scope (candidate digest, tile, one
   bounded clear, budget table, command, key identity) in the decision
   thread, per provisioning doc §5. The runner's launch ceremony will then
   re-verify the record itself (`grant_launch` → claim consumption → re-verify
   at the process boundary) before the single authorized launch.
