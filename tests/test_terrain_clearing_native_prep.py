"""Controlled offline tests for the D2 clearing native-preparation contract.

No OpenTTD launch, no AdminPort connection, no native mutation, and no native
success claim anywhere: staging, pins, seals, claim gates, budget seals and
retained evidence replay are exercised against controlled peers only.
"""

import json
from pathlib import Path

import pytest

import app.simulation.openttd.proof.terrain_clearing as terrain_clearing  # noqa: E402
from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.proof.harness import (
    BRIDGE_DIRECTORY,
    PROJECT,
    manifest,
    sha256,
    source_freeze,
    write_json,
)
from app.simulation.openttd.proof.terrain_clearing import (
    CENSUS_DIRECTORY,
    MAX_CLEARING_COST,
    REQUEST_BUDGET,
    SEED17_RUN,
    TARGET_TILE,
    StopNoMutation,
    admit_pinned_target,
    claim_status,
    d2_conditionally_imported,
    d2_source_closure,
    pinned_target,
    preflight,
    prepare_candidate,
    verify_attempt,
)
from app.simulation.openttd.terrain_clearing import (
    ClearingReadback,
    ClearingRequest,
    admit_clearing,
    verify_clearing,
)

TREE, CLEAR, FARM = 0x0009, 0x0001, 0x0011
SEAL_GOAL = "a" * 64
SAVE_GOAL = "b" * 64

# The synthetic RFC 8032 Ed25519 operator identity (identical to the one used
# by the adversarial suite): the production anchor is the operator's seeded
# LOCAL DEVELOPMENT PROOF key and these keys exist only inside isolated
# temporary test environments.
_TEST_OPERATOR_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
_TEST_OPERATOR_PUBLIC = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
_PROD_ANCHOR = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
# Seeded in the reviewed provisioning change: every test below patches the
# anchor with the synthetic key and restores exactly what it found, and the
# seeded production value must remain a valid Ed25519 key identity.
assert _PROD_ANCHOR is not None
operator_authorization.operator_key_identity(_PROD_ANCHOR)


@pytest.fixture(autouse=True)
def _synthetic_operator_anchor_fixture():
    """The whole module verifies under one synthetic RFC 8032 test anchor."""
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _TEST_OPERATOR_PUBLIC.hex()
    try:
        yield
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved


@pytest.fixture()
def staged(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    yield prepared
    prepared.spec.workspace.close()


def provenance_page_digest():
    return sha256(CENSUS_DIRECTORY / "classification-p034-response.json")


# --- staging correctness and identity resolution ---------------------------


def test_staged_composition_is_evidence_bound(staged):
    gs = staged.spec.workspace.root / "game" / "RoadFreightProof"
    package = Path("app/simulation/openttd/terrain_clearing_package/main.nut")
    assert gs.joinpath("main.nut").read_bytes() == package.read_bytes()
    # The save-restore bridge class (NetworkFreightProof) is now defined inline
    # in main.nut after TerrainClearingProof, not in a separate identity.nut.
    main_text = gs.joinpath("main.nut").read_text()
    assert "class NetworkFreightProof extends TerrainClearingProof" in main_text
    candidate = json.loads((CENSUS_DIRECTORY / "CANDIDATE.json").read_text())
    ai = staged.spec.workspace.root / "ai" / "RoadProofCompany"
    for name, record in candidate["ai_package"]["files"].items():
        assert sha256(ai / name) == record["sha256"]


def test_staged_script_identity_matches_the_retained_save(staged):
    gs = staged.spec.workspace.root / "game" / "RoadFreightProof"
    text = gs.joinpath("info.nut").read_text()
    assert 'GetName() { return "RoadFreightProof"; }' in text
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    identity = metadata["game_script_identity"]
    assert identity["name"] == "RoadFreightProof"
    assert identity["version"] == 1
    assert identity["create_instance"] == "NetworkFreightProof"


def test_staged_source_save_is_byte_identical_to_the_retained_save(staged):
    root = staged.spec.workspace.root
    assert sha256(root / "source.sav") == sha256(SEED17_RUN / "before.sav")
    config = root.joinpath("openttd.cfg").read_text()
    assert "[game_creation]" not in config
    assert "[game_scripts]\nRoadFreightProof = \n" in config


def test_pinned_target_matches_the_sealed_census_page(staged):
    pin = json.loads((staged.directory / "PRELAUNCH.json").read_text())["plan_policy"]["pinned"]
    assert pin["tile"] == 46769
    assert pin["classification"] == "TREES"
    assert pin["flags"] == 9
    assert (pin["elevation"], pin["slope"], pin["owner"]) == (2, 0, -1)
    assert pin["page_sha256"] == provenance_page_digest()
    assert pin["verification"].startswith("sealed census")


def test_startup_identity_and_ceiling_are_sealed(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    try:
        assert claim_status(prepared.directory) == "ABSENT"
        metadata = preflight(prepared)
        assert metadata["authorization"].startswith("PENDING")
        assert metadata["budgets"]["real_clears"] == 1
        assert metadata["budgets"]["requests"] == REQUEST_BUDGET
        assert metadata["budgets"]["retries"] == 0
        assert metadata["budgets"]["reconnects"] == 0
        assert metadata["budgets"]["response_bytes"] == 512
        assert metadata["budgets"]["gsadmin_bytes"] == 1450
        assert metadata["budgets"]["total_seconds"] == 180
        assert metadata["plan_policy"]["max_cost"] == MAX_CLEARING_COST
        assert metadata["plan_policy"]["company"] == 0
        assert claim_status(prepared.directory) == "ABSENT"
    finally:
        prepared.spec.workspace.close()


def test_preflight_refuses_after_a_consumed_claim(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    try:
        seal = sha256(prepared.directory / "PRELAUNCH.json")
        write_json(prepared.directory / "CLAIM.json", dict(prelaunch_digest=seal, consumed=True))
        assert claim_status(prepared.directory) == "CONSUMED"
        with pytest.raises(ValueError, match="one native attempt already consumed"):
            preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_claim_status_refuses_mismatched_claim_content(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    try:
        write_json(
            prepared.directory / "CLAIM.json", dict(prelaunch_digest="0" * 64, consumed=True)
        )
        with pytest.raises(ValueError, match="claim does not match"):
            claim_status(prepared.directory)
    finally:
        prepared.spec.workspace.close()


def test_staged_artifact_tamper_refuses_preflight(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    try:
        config = prepared.spec.workspace.config
        config.write_text(config.read_text() + "# tampered\n")
        with pytest.raises(ValueError):
            preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_drifted_source_save_refuses_preflight(tmp_path):
    prepared = prepare_candidate(tmp_path / "candidate")
    try:
        (prepared.spec.workspace.root / "source.sav").write_bytes(b"tampered world bytes")
        with pytest.raises(ValueError):
            preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_history_and_evidence_remain_untouched_by_staging(tmp_path):
    records = (
        SEED17_RUN / "before.sav",
        CENSUS_DIRECTORY / "CANDIDATE.json",
        CENSUS_DIRECTORY / "CLAIM.json",
        CENSUS_DIRECTORY / "result.json",
        CENSUS_DIRECTORY / "classification-p034-response.json",
    )
    before = {path: sha256(path) for path in records}
    prepared = prepare_candidate(tmp_path / "candidate")
    prepared.spec.workspace.close()
    assert {path: sha256(path) for path in records} == before


# --- controlled admission: re-observation vs pinned evidence ---------------


def pin_request(request_id="inspect-1", plan=SEAL_GOAL):
    return ClearingRequest(
        op="inspect",
        request_id=request_id,
        plan=plan,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )


def pin_readback(
    request,
    *,
    status="READY",
    flags=TREE,
    funds=100000,
    cost=20,
    op="inspect",
    tile=TARGET_TILE,
    owner=-1,
    elevation=2,
    slope=0,
):
    return ClearingReadback(
        op=op,
        request_id=request.request_id,
        plan=request.plan,
        company=0,
        tile=tile,
        status=status,
        flags=flags,
        industry=None,
        owner=owner,
        elevation=elevation,
        slope=slope,
        eligible=True,
        funds=funds,
        cost=cost,
    )


def clear_request(intent, request_id="clear-1"):
    return ClearingRequest(
        op="clear",
        request_id=request_id,
        plan=intent.prelaunch_digest,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )


def admit_under_pin(before):
    return admit_pinned_target(
        before,
        pinned=pinned_target(),
        prelaunch_digest=SEAL_GOAL,
        source_save_digest=SAVE_GOAL,
        max_cost=MAX_CLEARING_COST,
    )


def test_live_reobservation_matching_the_pin_admits():
    intent = admit_under_pin(pin_readback(pin_request()))
    assert (intent.tile, intent.company, intent.native_test_cost) == (TARGET_TILE, 0, 20)


@pytest.mark.parametrize(
    "changes",
    [
        {"flags": FARM},
        {"elevation": 3},
        {"slope": 2},
        {"owner": 1},
        {"tile": 46770},
    ],
)
def test_stale_reobservation_stops_without_mutation(changes):
    with pytest.raises(StopNoMutation, match="pinned expected classification"):
        admit_under_pin(pin_readback(pin_request(), **changes))


def test_read_operation_is_not_inspection_and_stops():
    with pytest.raises(StopNoMutation, match="pinned expected classification"):
        admit_under_pin(pin_readback(pin_request("read-0"), op="read", status="READ"))


def test_matched_pin_with_refused_quote_cannot_admit():
    before = pin_readback(pin_request(), status="COST_LIMIT", cost=MAX_CLEARING_COST + 1)
    with pytest.raises(ValueError):
        admit_under_pin(before)


def test_already_attempted_status_never_admits():
    before = pin_readback(pin_request(), status="ALREADY_ATTEMPTED")
    with pytest.raises(ValueError):
        admit_under_pin(before)


# --- synthetic retained attempt replay (controlled, never native) ----------


def write_exchange(root, query, readback, frames):
    raw = readback.model_dump_json().encode()
    (root / (query.request_id + "-request.json")).write_bytes(query.to_bytes())
    (root / (query.request_id + "-response.json")).write_bytes(raw)
    frames += [
        ("outbound", encode_gamescript(query.to_bytes()).hex()),
        ("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0").hex()),
    ]


def read_exchange(plan, request_id="read-0"):
    query = ClearingRequest(
        op="read",
        request_id=request_id,
        plan=plan,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    return query, pin_readback(query, op="read", status="READ")


def synthetic_attempt(root: Path, mode: str, *, defect: str | None = None):
    """Fully sealed controlled attempt evidence inside a real staged candidate."""
    prepared = prepare_candidate(root / "candidate")
    directory = prepared.directory
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    (directory / "session-before.sav").write_bytes(b"controlled session-before save")
    (directory / "after.sav").write_bytes(b"controlled after save")
    save_digest = sha256(directory / "session-before.sav")
    # Retained script logs: the runner copies these from the owned runtime;
    # replay gates claimed receipts on their health (BLOCKER 3).
    (directory / "stdout.log").write_text("dbg: [script:4] [18] [I] TERRAIN_CLEARING_READY\n")
    (directory / "stderr.log").write_text("dbg: [script:4] [20] [I] ROAD_PROOF_COMPANY_READY\n")

    stopped = mode in ("stale", "quote-limit")
    result = dict(
        preflight="PASS",
        native_launches=0 if stopped else 1,
        connections=0 if stopped else 1,
        requests=0,
        clearing="NOT_DISPATCHED",
        command_accepted=False,
        state_changed=False,
        verified=False,
        status="STOPPED_NO_MUTATION" if stopped else "FAILED",
        pin=metadata["plan_policy"]["pinned"],
        error=None if stopped else "ValueError: controlled " + mode,
        returncode=0,
    )
    frames = []
    if stopped:
        read0_query, read0 = read_exchange(seal)
        write_exchange(directory, read0_query, read0, frames)
        query = pin_request(plan=seal)
        if mode == "quote-limit":
            value = pin_readback(query, status="COST_LIMIT", cost=MAX_CLEARING_COST + 1)
            result["stop_reason"] = "inspect did not authorize a clearing command: COST_LIMIT"
        else:
            value = pin_readback(query, flags=FARM)
            result["stop_reason"] = (
                "target no longer matches its pinned expected classification: "
                "live=FARM flags=" + hex(FARM) + " pinned controlled evidence"
            )
        write_exchange(directory, query, value, frames)
        result["requests"] = 2
    else:
        before = pin_readback(pin_request(plan=seal))
        intent = admit_clearing(
            before,
            prelaunch_digest=seal,
            source_save_digest=save_digest,
            max_cost=MAX_CLEARING_COST,
        )
        clear = clear_request(intent)
        rejected = mode == "rejected"
        built = pin_readback(
            clear,
            op="clear",
            status="REJECTED" if rejected else "CLEARED",
            flags=TREE if rejected else CLEAR,
            funds=100000 if rejected else 99980,
            cost=0 if rejected else 20,
        )
        if mode == "quote-exec":
            built = pin_readback(
                clear, op="clear", status="CLEARED", flags=CLEAR, funds=99980, cost=7
            )
        read2_query, _ = read_exchange(intent.digest, "read-2")
        cleared = built.status == "CLEARED"
        after = pin_readback(
            read2_query,
            op="read",
            status="READ",
            flags=CLEAR if cleared else TREE,
            funds=99980 if cleared else 100000,
        )
        base_query, base_read = read_exchange(seal)
        exchanges = [(base_query, base_read), (pin_request(plan=seal), before), (clear, built)]
        if mode != "missing-readback":
            exchanges.append((read2_query, after))
        for query, value in exchanges:
            write_exchange(directory, query, value, frames)
        result.update(
            requests=len(exchanges),
            clearing=built.status,
            command_accepted=cleared,
            state_changed=after.flags == CLEAR,
            status="NATIVE_STATE_VERIFIED" if mode == "verified" else "FAILED",
        )
        if mode == "verified" and defect == "connection":
            result["connections"] = 2
        if mode == "verified" and defect != "connection":
            write_json(directory / "plan.json", intent.model_dump(mode="json"))
            receipt = verify_clearing(intent, before, built, after)
            receipt["before_save_sha256"] = save_digest
            receipt["after_save_sha256"] = sha256(directory / "after.sav")
            write_json(directory / "receipt.json", receipt)
            result["verified"] = True
            result["cost_attribution"] = dict(
                method="GSAccounting command-scoped native cost",
                test_quote=intent.native_test_cost,
                command_cost=built.cost,
                funds_at_inspect=before.funds,
                funds_at_exec=built.funds,
                company_cash_delta=before.funds - built.funds,
                statement="controlled stub",
            )
    write_json(directory / "frames.json", frames)
    write_json(
        directory / "runtime-identity.json",
        dict(encrypted=True, welcome=dict(revision="15.3")),
    )
    write_json(directory / "result.json", result)
    write_json(
        directory / "cleanup.json",
        dict(
            reaped=True,
            sockets_closed=True,
            workspace_disposed=True,
            credential_removed=defect != "credential",
            returncode=0,
        ),
    )
    record = operator_authorization.sign_authorization_record(
        operator_authorization.authorization_payload(metadata, seal),
        _TEST_OPERATOR_SEED.hex(),
    )
    operator_authorization.write_authorization_record(directory, record)
    write_json(
        directory / "CLAIM.json",
        dict(
            prelaunch_digest=seal,
            consumed=True,
            launches_allowed=1,
            retries=0,
            authorization_schema=operator_authorization.CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
            authorization_sha256=operator_authorization.record_digest(directory),
            operator_key_identity=operator_authorization.operator_key_identity(
                _TEST_OPERATOR_PUBLIC.hex()
            ),
        ),
    )
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    prepared.spec.workspace.close()
    return directory


def test_verified_replay_succeeds_for_consistent_controlled_evidence(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    verification = verify_attempt(directory)
    assert verification["verification"] == "RECEIPT_VERIFIED"
    receipt = verification["receipt"]
    assert receipt["schema"] == "company-clearing-receipt-v1"
    assert receipt["original_classification"] == "TREES"
    assert receipt["verification"] == "NATIVE_STATE_CHANGED"


def test_stale_controlled_attempt_replays_as_stopped_without_mutation(tmp_path):
    directory = synthetic_attempt(tmp_path, "stale")
    outcome = verify_attempt(directory)
    assert outcome["verification"] == "STOPPED_WITHOUT_MUTATION"
    assert "pinned" in outcome["stop_reason"]


def test_quote_limit_stop_replays_without_mutation(tmp_path):
    outcome = verify_attempt(synthetic_attempt(tmp_path, "quote-limit"))
    assert outcome["verification"] == "STOPPED_WITHOUT_MUTATION"


@pytest.mark.parametrize("mode", ["rejected", "quote-exec", "missing-readback"])
def test_failed_and_partial_attempts_preserve_evidence_without_receipt(tmp_path, mode):
    directory = synthetic_attempt(tmp_path, mode)
    outcome = verify_attempt(directory)
    assert outcome["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert not (directory / "receipt.json").exists()


def test_missing_read_exchange_reports_state_change_uncertain(tmp_path):
    outcome = verify_attempt(synthetic_attempt(tmp_path, "missing-readback"))
    assert outcome["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert outcome["command_accepted"] is True


def test_duplicate_command_evidence_is_refused(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    raw = json.loads((directory / "clear-1-request.json").read_bytes())
    raw["request_id"] = "clear-2"
    second = json.dumps(raw).encode()
    body = json.loads((directory / "clear-1-response.json").read_bytes())
    body["request_id"] = "clear-2"
    response2 = json.dumps(body).encode()
    frames = json.loads((directory / "frames.json").read_text())
    frames.append(("outbound", encode_gamescript(second).hex()))
    frames.append(("inbound", encode_admin_frame(SERVER_GAMESCRIPT, response2 + b"\0").hex()))
    (directory / "clear-2-request.json").write_bytes(second)
    (directory / "clear-2-response.json").write_bytes(response2)
    (directory / "frames.json").write_text(json.dumps(frames))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(
        ValueError, match="outbound frame payloads do not match request file payloads"
    ):
        verify_attempt(directory)


def test_budget_exhaustion_is_refused(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    raw = json.loads((directory / "read-2-request.json").read_text())
    # Add extra request files AND corresponding outbound frames.
    frames = json.loads((directory / "frames.json").read_text())
    for index in range(REQUEST_BUDGET):
        raw["request_id"] = "read-x-" + str(index)
        req_bytes = json.dumps(raw).encode()
        (directory / ("read-x-" + str(index) + "-request.json")).write_bytes(req_bytes)
        frames.append(("outbound", encode_gamescript(req_bytes).hex()))
        # No corresponding inbound frame - incomplete exchange.
    (directory / "frames.json").write_text(json.dumps(frames))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(ValueError, match="clearing request budget exceeded"):
        verify_attempt(directory)


def test_undisclosed_record_tamper_is_refused(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    result = json.loads((directory / "result.json").read_text())
    result["native_launches"] = 2
    (directory / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="artifact manifest mismatch"):
        verify_attempt(directory)


def test_restamped_tampered_connections_still_fails_replay(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    result = json.loads((directory / "result.json").read_text())
    result["connections"] = 2
    (directory / "result.json").write_text(json.dumps(result))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(ValueError, match="launch/connection seal"):
        verify_attempt(directory)


def test_restamped_tampered_receipt_still_fails_replay(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    receipt = json.loads((directory / "receipt.json").read_text())
    receipt["cost"] += 1
    (directory / "receipt.json").write_text(json.dumps(receipt))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(ValueError, match="receipt replay mismatch"):
        verify_attempt(directory)


def test_dropped_frame_evidence_is_refused(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified")
    frames = json.loads((directory / "frames.json").read_text())
    frames.pop()
    (directory / "frames.json").write_text(json.dumps(frames))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(ValueError, match="lacks unique secure-session frame evidence"):
        verify_attempt(directory)


def test_incomplete_cleanup_cannot_verify(tmp_path):
    directory = synthetic_attempt(tmp_path, "verified", defect="credential")
    with pytest.raises(ValueError, match="cleanup incomplete"):
        verify_attempt(directory)


def test_mutation_claim_without_command_request_is_refused(tmp_path):
    directory = synthetic_attempt(tmp_path, "stale")
    result = json.loads((directory / "result.json").read_text())
    result["verified"] = True
    (directory / "result.json").write_text(json.dumps(result))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with pytest.raises(ValueError, match="mutation claim"):
        verify_attempt(directory)


def test_runtime_source_closure_fully_frozen(staged):
    """BLOCKER 2 counterexample: the runtime source closure must be frozen.

    The D2 native execution path imports local modules outside
    app/simulation/openttd (planning DTOs, canonicalization and the retained
    world generation module). The candidate freeze must list every one of
    them so a post-approval source change refuses preflight.
    """
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    frozen = set(metadata["frozen"])
    missing = [
        name
        for name in (
            "app/planning/canonical.py",
            "app/planning/domain.py",
            "app/demo_random.py",
        )
        if str((PROJECT / name).resolve()) not in frozen
    ]
    assert not missing, f"execution-critical sources missing from the freeze: {missing}"


# --- BLOCKER 2 regression suite: complete runtime source freeze --------------


def _restamp_prelaunch(directory):
    (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")


def _add_freeze_probe(directory, source):
    """Alias one extra frozen entry to a byte-identical in-candidate copy.

    Drift tests must stay read-only against real sources: the probe copy is
    byte-identical to the reviewed module at staging time, so any later byte
    change is exactly the "frozen source changed after preparation" condition
    the freeze contract guards.
    """
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    probe = directory / "freeze-probe" / source.name
    probe.parent.mkdir(exist_ok=True)
    probe.write_bytes(source.read_bytes())
    metadata["frozen"][str(probe.resolve())] = sha256(source)
    (directory / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _restamp_prelaunch(directory)
    return probe


def test_every_local_runtime_module_is_frozen(staged):
    """The complete D2 execution closure is a subset of the staged freeze."""
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    missing = set(d2_source_closure()) - set(metadata["frozen"])
    assert not missing, sorted(Path(module).name for module in missing)


def test_blocker_examples_are_closure_members(staged):
    """The audited missing modules are closure members and frozen."""
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    closure = d2_source_closure()
    for name in ("canonical.py", "domain.py", "demo_random.py"):
        paths = [path for path in closure if Path(path).name == name]
        assert paths, f"{name} is not in the computed closure"
        for path in paths:
            assert path in metadata["frozen"]


def test_transitive_dependency_is_frozen(staged):
    """Dependencies reached only through other imports are still frozen."""
    closure = set(d2_source_closure())
    assert str((PROJECT / "app/planning/canonical.py").resolve()) in closure
    assert str((PROJECT / "app/planning/domain.py").resolve()) in closure
    assert str((PROJECT / "app/planning/domain.py").resolve()) in set(
        json.loads((staged.directory / "PRELAUNCH.json").read_text())["frozen"]
    )


def test_conditionally_loaded_module_is_frozen(staged):
    """A source imported only inside a function/guard is still frozen."""
    conditional = d2_conditionally_imported()
    ownership = "app.simulation.openttd.runtime.ownership"
    assert ownership in conditional
    assert str((PROJECT / "app/simulation/openttd/runtime/ownership.py").resolve()) in set(
        json.loads((staged.directory / "PRELAUNCH.json").read_text())["frozen"]
    )


def test_unchanged_reviewed_source_passes_preflight(staged):
    """Byte-identical sources and an alias probe both keep preflight green."""
    _add_freeze_probe(staged.directory, PROJECT / "app/planning/canonical.py")
    preflight(staged)


@pytest.mark.parametrize(
    "module",
    ("app/planning/canonical.py", "app/planning/domain.py", "app/demo_random.py"),
)
def test_frozen_source_drift_refuses_preflight(staged, module):
    """Changing canonical.py, domain.py or demo_random.py refuses preflight."""
    probe = _add_freeze_probe(staged.directory, PROJECT / module)
    preflight(staged)
    probe.write_bytes(probe.read_bytes() + b"\n# drifted after preparation\n")
    with pytest.raises(ValueError, match="Frozen source"):
        preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_removed_closure_entry_refuses_preflight(staged):
    """Removing a frozen closure entry from the manifest refuses preflight."""
    target = str((PROJECT / "app/planning/canonical.py").resolve())
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    del metadata["frozen"][target]
    (staged.directory / "PRELAUNCH.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    )
    _restamp_prelaunch(staged.directory)
    with pytest.raises(ValueError, match="closure is not frozen"):
        preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_frozen_source_modified_after_preparation_refuses_before_claim(staged):
    """Post-preparation frozen drift refuses ahead of any claim consumption."""
    probe = _add_freeze_probe(staged.directory, PROJECT / "app/planning/domain.py")
    probe.write_bytes(probe.read_bytes() + b"\n# modified after preparation\n")
    with pytest.raises(ValueError, match="Frozen source"):
        preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_historical_source_freeze_contract_unchanged():
    """The shared historical freeze contract keeps its exact member set."""
    import sys

    import monocypher as _monocypher

    frozen = set(source_freeze())
    openttd_sources = {
        str(path.resolve()) for path in (PROJECT / "app/simulation/openttd").rglob("*.py")
    }
    bridge_sources = {str(path.resolve()) for path in BRIDGE_DIRECTORY.glob("*.nut")}
    shared = {
        str((PROJECT / "pyproject.toml").resolve()),
        str((PROJECT / "uv.lock").resolve()),
        str((PROJECT / "app/__init__.py").resolve()),
        str((PROJECT / "app/simulation/__init__.py").resolve()),
        str(Path(sys.executable).resolve()),
        str(Path(_monocypher.__file__).resolve()),
    }
    if (PROJECT / "CONTEXT.md").is_file():
        shared.add(str((PROJECT / "CONTEXT.md").resolve()))
    symmetric = frozen ^ (openttd_sources | bridge_sources | shared)
    assert not symmetric, sorted(symmetric)


# --- BLOCKER 3 regression: executed initializers, dynamic and outside roots --


def test_executed_package_initializers_are_closure_members(staged):
    """Every executed parent package initializer must join the closure."""
    for name in (
        "app/planning/__init__.py",
        "app/planning/preparation/__init__.py",
    ):
        path = str((PROJECT / name).resolve())
        assert path in d2_source_closure(), f"{name} is missing from the closure"
        assert path in metadata_of(staged)["frozen"], f"{name} is not frozen"


def metadata_of(staged):
    return json.loads((staged.directory / "PRELAUNCH.json").read_text())


def test_initializer_drift_refuses_preflight(staged):
    """Changing an executed initializer after preparation refuses preflight."""
    probe = _add_freeze_probe(staged.directory, PROJECT / "app/planning/__init__.py")
    preflight(staged)
    probe.write_bytes(probe.read_bytes() + b"\n# initializer drift after preparation\n")
    with pytest.raises(ValueError, match="Frozen source"):
        preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_closure_sandbox_covers_initializers_dynamic_and_outside_roots(tmp_path, monkeypatch):
    """Codex probe mirror: initializers, dynamic imports and outside-root files."""
    sandbox = tmp_path / "dummy-project"
    sandbox.mkdir()
    (sandbox / "outside_d2_probe.py").write_text("VALUE = 'outside'\n")
    package = sandbox / "d2_probe_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "dynamic.py").write_text("VALUE = 'dynamic'\n")
    (package / "entry.py").write_text(
        "import importlib\n"
        "import outside_d2_probe\n"
        "DYNAMIC = importlib.import_module('d2_probe_pkg.dynamic')\n"
    )
    monkeypatch.setattr(terrain_clearing, "PROJECT", sandbox)
    monkeypatch.setattr(terrain_clearing, "D2_CLOSURE_ROOT", "d2_probe_pkg.entry")
    monkeypatch.syspath_prepend(sandbox)
    closure = terrain_clearing.d2_source_closure()
    present = {Path(path).name for path in closure}
    assert "entry.py" in present
    assert "__init__.py" in present, "executed initializer missing from the closure"
    assert "dynamic.py" in present, "dynamic literal import missing from the closure"
    assert "outside_d2_probe.py" in present, "outside-root module missing"


def test_unresolved_dynamic_import_literal_refuses_closure(tmp_path, monkeypatch):
    """A literal dynamic import resolving nowhere must fail closed."""
    sandbox = tmp_path / "dummy-project"
    sandbox.mkdir()
    package = sandbox / "d2_probe_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "entry.py").write_text(
        "import importlib\nimportlib.import_module('d2_probe_pkg.unresolvable_probe_module')\n"
    )
    monkeypatch.setattr(terrain_clearing, "PROJECT", sandbox)
    monkeypatch.setattr(terrain_clearing, "D2_CLOSURE_ROOT", "d2_probe_pkg.entry")
    monkeypatch.syspath_prepend(sandbox)
    with pytest.raises(terrain_clearing.D2ClosureError, match="unresolvable dynamic import"):
        terrain_clearing.d2_source_closure()


# --- BLOCKER 4 regression: installed dependency identity ---------------------


def _dependency_inventory():
    return terrain_clearing.d2_dependency_inventory()


def test_loaded_execution_dependencies_are_identified_and_frozen(staged):
    """The runtime-loaded third-party implementations join the staged freeze."""
    inventory = _dependency_inventory()
    frozen = metadata_of(staged)["frozen"]
    pydantic_core = [p for p in inventory if "pydantic_core" in p and p.endswith(".so")]
    assert pydantic_core, "pydantic_core native extension is not inventoried"
    ortools_files = [p for p in inventory if "/ortools/" in p]
    assert ortools_files, "ortools implementation bytes are not inventoried"
    for path, digest in sorted(inventory.items()):
        assert path in frozen, f"dependency not frozen: {path}"
        assert frozen[path] == digest


def test_dependency_drift_refuses_preflight(staged):
    """Changing an installed dependency byte after preparation refuses preflight."""
    inventory = _dependency_inventory()
    target = next(path for path in sorted(inventory) if path.endswith(".so"))
    probe = _add_freeze_probe(staged.directory, Path(target))
    preflight(staged)
    probe.write_bytes(probe.read_bytes() + b"\x00drift")
    with pytest.raises(ValueError, match="Frozen source"):
        preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_dependency_inventory_is_deterministic():
    """The same environment yields the same reviewable inventory twice."""
    assert _dependency_inventory() == _dependency_inventory()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
