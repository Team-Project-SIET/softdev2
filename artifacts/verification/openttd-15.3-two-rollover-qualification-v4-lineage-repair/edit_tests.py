from pathlib import Path
p=Path('tests/test_historical_attempt_lineage.py');s=p.read_text()
pos=s.index('\n\n@pytest.mark.parametrize("number", [1, 2])')
helpers='''

def controlled_freeze(root, revision, number):
    from app.simulation.openttd.proof.harness import manifest, write_json
    from app.simulation.openttd.proof.qualification_contract import qualification_contract

    suffix = "" if revision == 1 else f"-v{revision}"
    directory = root / f"{PREFIX}-real-prelaunch{suffix}"
    directory.mkdir()
    destination = root / f"{PREFIX}-real-attempt{number}"
    value = lineage.derive_next_attempt(directory, revision, destination)
    contract = qualification_contract() | {"revision": revision, "future_destination": destination.name}
    metadata = dict(
        mode=lineage.KIND, proof_kind=lineage.KIND, prelaunch_revision=revision,
        attempt_id=value["attempt_id"], attempt_directory=str(destination),
        lineage_digest=value["lineage_digest"], proof_config_sha256=lineage.digest(contract),
        predecessor_attempt_ids=sorted(r["attempt_id"] for r in lineage.lineage_rows(value)),
    )
    write_json(directory / "PRELAUNCH.json", metadata)
    write_json(directory / "attempt-lineage.json", value)
    write_json(directory / "qualification-contract.json", contract)
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return directory, destination, value


def controlled_consume(frozen, status, *, offline_failure=False):
    from app.simulation.openttd.proof.harness import manifest, write_json

    directory, destination, value = frozen
    destination.mkdir()
    native = dict(
        status=status, launches=1, connections=1, requests_sent=1,
        preparation=str(directory), attempt_id=value["attempt_id"],
        states=["COMPLETED"] if status == "REAL_SUCCESS" else ["FAILED"],
        qualified_for_planning=status == "REAL_SUCCESS", retries=0, reconnects=0,
    )
    write_json(destination / "proof-evidence.json", native)
    if offline_failure:
        write_json(destination / "production-observation.json", dict(
            complete=True, qualified_for_planning=True,
        ))
        write_json(destination / "process-lifecycle.json", dict(
            cleanup_error=[], remaining_processes=[], credential_removed=True,
            postrun_integrity_verified=True, reaped=True, sockets_closed=True,
            workspace_disposed=True,
        ))
        write_json(destination / "source-freeze-post.json", dict(unchanged=True))
        analysis = destination.with_name(destination.name + "-postrun-verification")
        analysis.mkdir()
        suites = {}
        for name in ("focused", "ordinary"):
            suites[name] = dict(tests="1", failures="1", errors="0", skipped="0")
            (analysis / f"{name}.xml").write_text(
                '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/>'
                '</testsuites>'
            )
        write_json(analysis / "verification.json", dict(
            native_status=status, native_lifecycle="COMPLETED",
            final_acceptance="FAILED_POSTRUN_VERIFICATION", terminal_reason="controlled offline failure",
            integrity={"integrity": "PASS"}, tests=suites,
        ))
        (analysis / "final-report.md").write_text("Controlled mandatory offline verification FAILED.\\n")
        (analysis / "artifact-manifest.sha256").write_text(manifest(analysis))
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    lineage.retain_attempt_identity(destination, metadata, native)
    (destination / "artifact-manifest.sha256").write_text(manifest(destination))


@pytest.fixture
def controlled_history(tmp_path):
    from app.simulation.openttd.proof.world_attempt import record_prelaunch_failure

    first = controlled_freeze(tmp_path, 1, 1)
    controlled_consume(first, "REAL_FAILED")
    second = controlled_freeze(tmp_path, 2, 2)
    controlled_consume(second, "REAL_SUCCESS", offline_failure=True)
    third = controlled_freeze(tmp_path, 3, 3)
    record_prelaunch_failure(third[0], ValueError("Controlled post-consumption test contract failure"))
    return controlled_freeze(tmp_path, 4, 3)
'''
s=s[:pos]+helpers+s[pos:]
s=s.replace('def test_current_next_attempt_preserves_frozen_identity():\n    path = freeze(2) / "attempt-lineage.json"','def test_current_next_attempt_preserves_frozen_identity(controlled_history):\n    directory, destination, _ = controlled_history\n    path = directory.with_name(f"{PREFIX}-real-prelaunch-v2") / "attempt-lineage.json"')
s=s.replace('        ROOT / f"{PREFIX}-real-prelaunch-v3", 3, ROOT / f"{PREFIX}-real-attempt3"','        directory, 4, destination')
s=s.replace('    assert value["attempt_id"] == "two-rollover-qualification-v3-native-attempt3"','    assert value["attempt_id"] == "two-rollover-qualification-v4-native-attempt3"')
s=s.replace('    assert len(rows) == 2\n    row = next', '''    assert len(rows) == 2
    prelaunch = value["supersedes_prelaunch_attempts"]
    assert len(prelaunch) == 1
    assert prelaunch[0]["freeze_revision"] == 3
    assert prelaunch[0]["classification"] == "PRELAUNCH"
    assert tuple(prelaunch[0][k] for k in ("launches", "connections", "requests")) == (0, 0, 0)
    assert not destination.exists()
    row = next''')
s=s.replace('def test_next_attempt_requires_new_freeze():\n    with pytest.raises(ValueError, match="Newer freeze"):\n        lineage.derive_next_attempt(ROOT / "next-freeze", 2, ROOT / f"{PREFIX}-real-attempt3")','''def test_next_attempt_requires_new_freeze(controlled_history):
    directory, destination, _ = controlled_history
    with pytest.raises(ValueError, match="Newer freeze"):
        lineage.derive_next_attempt(directory, 3, destination)''')
s=s.replace('def test_next_attempt_wrong_destination_rejected(destination):','def test_next_attempt_wrong_destination_rejected(destination, controlled_history):')
s=s.replace('lineage.derive_next_attempt(ROOT / "next-freeze", 3, ROOT / f"{PREFIX}-{destination}")','lineage.derive_next_attempt(controlled_history[0], 4, controlled_history[0].parent / f"{PREFIX}-{destination}")')
s += '''

@pytest.mark.parametrize("status", ["REAL_FAILED", "REAL_SUCCESS"])
def test_after_attempt3_consumption_next_is_attempt4(controlled_history, status):
    directory, destination, frozen = controlled_history
    before = (directory / "attempt-lineage.json").read_bytes()
    controlled_consume(controlled_history, status)
    assert lineage.validate_historical_attempt(directory, destination).terminal_status == status
    with pytest.raises(ValueError, match="consumed"):
        lineage.validate_lineage(directory, frozen, 4, destination)
    next_value = lineage.derive_next_attempt(
        directory.with_name(f"{PREFIX}-real-prelaunch-v5"), 5,
        destination.with_name(f"{PREFIX}-real-attempt4"),
    )
    assert next_value["attempt_number"] == 4
    assert next_value["attempt_id"] == "two-rollover-qualification-v5-native-attempt4"
    assert len(next_value["post_launch_predecessors"]) == 3
    assert len(next_value["supersedes_prelaunch_attempts"]) == 1
    row = next(r for r in next_value["post_launch_predecessors"] if r["freeze_revision"] == 4)
    assert row["post_launch_failure"] == (status == "REAL_FAILED")
    assert (directory / "attempt-lineage.json").read_bytes() == before
    assert lineage.validate_historical_attempt(directory, destination).terminal_status == status
    with pytest.raises(ValueError, match="consumed"):
        lineage.derive_next_attempt(directory.with_name("next-freeze"), 5, destination)


def test_historical_attempt3_after_consumption_never_derives_next(controlled_history, monkeypatch):
    directory, destination, _ = controlled_history
    controlled_consume(controlled_history, "REAL_SUCCESS")
    monkeypatch.setattr(lineage, "relevant_failures", lambda *a: pytest.fail("current history read"))
    monkeypatch.setattr(lineage, "derive_next_attempt", lambda *a: pytest.fail("next derivation"))
    identity = lineage.validate_historical_attempt(directory, destination)
    assert identity.proof_kind == lineage.KIND
    assert identity.freeze_revision == 4
    assert identity.evidence_directory == f"{PREFIX}-real-attempt3"
    assert identity.evidence_digest and identity.parent_attempt_ids


@pytest.mark.parametrize("module", ["qualification", "production", "raw_production"])
@pytest.mark.parametrize("status", ["REAL_FAILED", "REAL_SUCCESS"])
def test_shared_terminal_consumption_derives_new_destination(module, status, tmp_path):
    from app.simulation.openttd.proof.harness import manifest, write_json

    api = importlib.import_module(f"app.simulation.openttd.proof.{module}_lineage")
    old = tmp_path / "old-freeze"
    old.mkdir()
    write_json(old / "PRELAUNCH.json", dict(mode=api.KIND, prelaunch_revision=1))
    consumed = tmp_path / f"{api.PREFIX}-real-attempt1"
    consumed.mkdir()
    write_json(consumed / "proof-evidence.json", dict(
        status=status, launches=1, connections=1, requests_sent=1,
        preparation=str(old), states=["COMPLETED"] if status == "REAL_SUCCESS" else ["FAILED"],
    ))
    (consumed / "artifact-manifest.sha256").write_text(manifest(consumed))
    value = api.capture_lineage(tmp_path / "new-freeze", 2, tmp_path / f"{api.PREFIX}-real-attempt2")
    assert value["attempt_number"] == 2
    with pytest.raises(ValueError, match="consumed"):
        api.validate_lineage(tmp_path / "new-freeze", value, 2, consumed)


def test_v3_retained_prelaunch_failure_identity():
    directory = ROOT / f"{PREFIX}-real-prelaunch-v3-gate-failure"
    identity = lineage.read_attempt(directory)
    assert identity.classification == "PRELAUNCH"
    assert identity.freeze_revision == 3
    assert (identity.launches, identity.connections, identity.requests) == (0, 0, 0)
    assert identity.terminal_status == "PRELAUNCH_FAILED"
'''
p.write_text(s)
