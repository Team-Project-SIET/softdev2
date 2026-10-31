"""Controlled offline tests for the D5-CORRIDOR-EXTENSION-1 staging pipeline.

The pipeline under test is
``app/simulation/openttd/proof/corridor_extension_native.py``, staged as a
fresh derived candidate from the pinned D4 candidate-5 after-save.
Everything here is strictly offline: no OpenTTD launch, no AdminPort
connection, no claim, no authorization artifact, and no mutation of any
retained attempt record or authoritative save. Replay behavior is exercised
with real production verdict paths (claim-absent, tampered seals, forced
success labels, malformed/out-of-schedule/duplicate frames,
funds/cost/station-merge drift), so every refusal is the real fail-closed
outcome, never a mock of the verifier.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import app.simulation.openttd.proof.corridor_construction_native as d4
import app.simulation.openttd.proof.corridor_extension_native as e
from app.simulation.openttd.admin_protocol import (
    ServerProtocol,
    ServerWelcome,
    encode_admin_frame,
)
from app.simulation.openttd.corridor_construction import (
    CorridorReadback,
    CorridorRequest,
    admit_corridor,
    corridor_phase_outcome,
    verify_corridor,
    verify_corridor_route,
)
from app.simulation.openttd.gamescript_transport import (
    SERVER_GAMESCRIPT,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.proof.harness import (
    BINARY,
    BINARY_SHA256,
    PreparedProof,
    manifest,
    sha256,
)
from app.simulation.openttd.proof.operator_authorization import (
    LaunchGrant,
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_clearing import claim_status, replay_authorization_state
from app.simulation.openttd.proof.terrain_terraform_native import ROAD_PROOF_COMPANY_READY_MARKER
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState
from tests.test_corridor_extension import OP_COSTS, WITNESS

SEAL = "a" * 64
MAX_COST = 2000
FUNDS = e.FUNDS_PIN

PINNED_SCHEDULE = [
    dict(
        kind="full", index=0, start=50096, end=50864, run_len=4, tiles=[50096, 50352, 50608, 50864]
    ),
    dict(kind="road", index=1, start=50095, end=50096, run_len=2, tiles=[50095, 50096]),
    dict(kind="station", index=2, tile=50863, front=50864, stop_role="delivery"),
]


# --- synthetic readback construction (explicitly synthetic) --------------------


def rb(request: CorridorRequest, **extra) -> CorridorReadback:
    """One correlated protocol-4 readback built from its own request."""
    body: dict = {
        "protocol": 4,
        "op": request.op,
        "request_id": request.request_id,
        "plan": request.plan,
        "company": request.company,
        "max_cost": request.max_cost,
        "target": request.target,
        "start": request.start,
        "end": request.end,
        "tile": request.tile,
        "front": request.front,
        "tiles": request.tiles,
    }
    body.update(extra)
    return CorridorReadback.model_validate(body)


def road_fields(run_len: int, *, owners, roads, covered, pairs_ok):
    return dict(
        owner0=owners[0],
        owner1=owners[1],
        road0=roads[0],
        road1=roads[1],
        run_len=run_len,
        covered=covered,
        pairs_ok=pairs_ok,
        pair_total=run_len - 1,
    )


def site_fields(*, built: bool, sid: int | None = 2):
    if not built:
        return dict(
            stop=False,
            drive_through=False,
            truck=False,
            stop_owner=-1,
            front_owner=0,
            linked=False,
            depot=False,
            depot_linked=False,
            stop_min_height=1,
            stop_slope=0,
            front_min_height=1,
            front_slope=0,
            sid=None,
        )
    return dict(
        stop=True,
        drive_through=False,
        truck=True,
        sid=sid,
        stop_owner=0,
        front_owner=0,
        linked=True,
        depot=False,
        depot_linked=False,
        stop_min_height=1,
        stop_slope=0,
        front_min_height=1,
        front_slope=0,
    )


def _op_requests(seal: str, position: int):
    """The three wired requests of one scheduled exchange group."""
    schedule = e.extension_schedule()
    entry = schedule[position]
    kind = entry["kind"]
    return (
        e._extension_request("inspect", f"inspect-{position:02d}", seal, 0, MAX_COST, entry),
        e._extension_request(kind, f"{kind}-{position:02d}", seal, 0, MAX_COST, entry),
        e._extension_request("read", f"confirm-{position:02d}", seal, 0, MAX_COST, entry),
    )


def build_attempt(seal: str, source_digest: str, position: int, *, spent: int, sid: int = 2):
    """One full exchange group (inspect -> command -> read) with its intent."""
    schedule = e.extension_schedule()
    entry = schedule[position]
    kind = entry["kind"]
    inspect_request, built_request, read_request = _op_requests(seal, position)
    cost = OP_COSTS[position]
    funds_before = FUNDS - spent
    funds_after = funds_before - cost
    if kind in ("full", "road"):
        run_len = entry["run_len"]
        if kind == "full":
            pre = road_fields(run_len, owners=(-1, -1), roads=(False, False), covered=0, pairs_ok=0)
        else:
            pre = road_fields(
                run_len, owners=(0, 0), roads=(True, True), covered=run_len, pairs_ok=0
            )
        post = road_fields(
            run_len, owners=(0, 0), roads=(True, True), covered=run_len, pairs_ok=run_len - 1
        )
        before = rb(
            inspect_request, status="READY", eligible=True, cost=cost, funds=funds_before, **pre
        )
        built = rb(
            built_request, status="BUILT", eligible=True, cost=cost, funds=funds_after, **post
        )
    else:
        pre = site_fields(built=False)
        post = site_fields(built=True, sid=sid)
        before = rb(
            inspect_request, status="READY", eligible=True, cost=cost, funds=funds_before, **pre
        )
        built = rb(
            built_request, status="BUILT", eligible=True, cost=cost, funds=funds_after, **post
        )
    intent = admit_corridor(
        before,
        prelaunch_digest=seal,
        source_save_digest=source_digest,
        staged_run_len=entry.get("run_len"),
        max_cost=MAX_COST,
    )
    read_request = read_request.model_copy(update={"plan": intent.digest})
    independent = rb(
        read_request,
        plan=intent.digest,
        status="READ",
        eligible=True,
        cost=0,
        funds=funds_after,
        **post,
    )
    verify = verify_corridor(intent, before, built, independent)
    assert verify["verification"] == "NATIVE_STATE_CHANGED"
    return dict(
        label=f"op-{position:02d}",
        intent=intent,
        before=before,
        built=built,
        independent=independent,
        cost=cost,
        spent=spent + cost,
        files=(
            (inspect_request, before),
            (built_request, built),
            (read_request, independent),
        ),
    )


def route_exchange(seal: str, *, funds: int, sid: int = 2, witness=WITNESS):
    request = CorridorRequest(
        op="route", request_id="route-00", plan=seal, company=0, max_cost=0, tiles=witness
    )
    readback = rb(
        request,
        status="READ",
        eligible=True,
        cost=0,
        funds=funds,
        connected_pairs=len(witness) - 1,
        first_fail=-1,
        pickup_stop=True,
        pickup_truck=True,
        pickup_sid=0,
        delivery_stop=True,
        delivery_truck=True,
        delivery_sid=sid,
        depot_pin_ok=True,
    )
    route_receipt = verify_corridor_route(
        readback,
        prelaunch_digest=seal,
        expected_pairs=len(witness) - 1,
        expected_path=witness,
    )
    assert route_receipt["verification"] == "ROUTE_VERIFIED"
    return request, readback, route_receipt


def _reply_bytes(request: CorridorRequest, readback: CorridorReadback) -> bytes:
    """The op-scoped wire serialization, exactly the handler's reply shape: the
    correlation keys, every pin echo and only the observed fields."""
    body: dict = dict(
        protocol=4,
        op=request.op,
        request_id=request.request_id,
        plan=request.plan,
        company=request.company,
        max_cost=request.max_cost,
        target=request.target,
        start=request.start,
        end=request.end,
        tile=request.tile,
        front=request.front,
        tiles=request.tiles,
    )
    for key, value in readback.model_dump(mode="json").items():
        if key in body or value is None:
            continue
        body[key] = value
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _admin_frame(payload: bytes) -> bytes:
    return encode_admin_frame(SERVER_GAMESCRIPT, payload)


def _persist(directory: Path, request: CorridorRequest, readback, frames: list) -> bytes:
    response = _reply_bytes(request, readback)
    parsed = CorridorReadback.parse_for(request, response)
    assert parsed == readback
    (directory / (request.request_id + "-request.json")).write_bytes(request.to_bytes())
    (directory / (request.request_id + "-response.json")).write_bytes(response)
    frames.append(["outbound", encode_gamescript(request.to_bytes()).hex()])
    frames.append(["inbound", _admin_frame(response + b"\0").hex()])
    return response


def _op_files(directory: Path, attempt: dict) -> None:
    index = int(attempt["label"].split("-")[1])
    for name in ("before", "intent", "built", "independent"):
        (directory / f"ext-{index:02d}-{name}.json").write_text(
            json.dumps(attempt[name].model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )


def _common_records(directory: Path, seal: str, metadata: dict) -> None:
    (directory / "CLAIM.json").write_text(
        json.dumps(
            dict(
                prelaunch_digest=seal,
                consumed=True,
                launches_allowed=1,
                retries=0,
                requests_allowed=32,
                authorization_schema="d2-clearing-claim-authorization-v2",
                authorization_sha256="f" * 64,
                operator_key_identity="synthetic-test-fixture",
            ),
            sort_keys=True,
        )
        + "\n"
    )
    welcome = dict(metadata["world"]["expected_welcome"], dedicated=True)
    (directory / "runtime-identity.json").write_text(
        json.dumps(
            dict(auth="X25519_AuthorizedKey", encrypted=True, welcome=welcome, pid=4242),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _certified_cleanup(directory: Path) -> None:
    (directory / "cleanup.json").write_text(
        json.dumps(
            dict(
                reaped=True,
                sockets_closed=True,
                workspace_disposed=True,
                credential_removed=True,
                returncode=0,
            ),
            sort_keys=True,
        )
        + "\n"
    )


def _restamp(directory: Path) -> None:
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))


def _revise(directory: Path, name: str, **fields) -> None:
    """Rewrite one retained JSON evidence record with the given field drift."""
    record = json.loads((directory / name).read_text())
    record.update(fields)
    (directory / name).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _replace_inbound(directory: Path, request_id: str, response: bytes) -> None:
    """Swap one exchange's inbound frame (and response file) to new bytes."""
    path = directory / (request_id + "-response.json")
    path.write_bytes(response)
    frames = json.loads((directory / "frames.json").read_text())
    index = next(
        position
        for position, (direction, frame) in enumerate(frames)
        if direction == "inbound" and request_id.encode() in bytes.fromhex(frame)[3:]
    )
    frames[index][1] = _admin_frame(response + b"\0").hex()
    (directory / "frames.json").write_text(json.dumps(frames))


def materialize_consumed(
    directory: Path,
    source: Path,
    *,
    ops: int = 3,
    route: bool = True,
    station_sid: int = 2,
    result: dict | None = None,
) -> dict:
    """Materialize an explicitly synthetic consumed extension attempt.

    ``source`` is the staged candidate directory; only its sealed PRELAUNCH
    pair is carried over. Every other artifact here (exchanges, frame stream,
    saves, cleanup certification, claim, result) is fabricated below with the
    same correlated protocol-4 discipline the pipeline writes.
    """
    directory.mkdir(parents=True)
    for name in ("PRELAUNCH.json", "PRELAUNCH.sha256"):
        shutil.copyfile(source / name, directory / name)
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    (directory / "session-before.sav").write_bytes(b"synthetic session-before fixture")
    source_digest = sha256(directory / "session-before.sav")
    frames: list = []
    attempts: list = []
    exchange_ids: list[str] = []
    completed: list[str] = []
    spent = 0
    for position in range(ops):
        attempt = build_attempt(seal, source_digest, position, spent=spent, sid=station_sid)
        _op_files(directory, attempt)
        for request, readback in attempt["files"]:
            _persist(directory, request, readback, frames)
        exchange_ids.extend(request.request_id for request, _ in attempt["files"])
        completed.append(attempt["label"])
        attempts.append(
            (
                attempt["label"],
                {name: attempt[name] for name in ("intent", "before", "built", "independent")},
            )
        )
        spent = attempt["spent"]
    phase = corridor_phase_outcome(attempts)
    receipt: dict = json.loads(json.dumps(phase))
    if route:
        request, readback, route_receipt = route_exchange(
            seal, funds=FUNDS - spent, sid=station_sid
        )
        (directory / "ext-route-read.json").write_text(
            json.dumps(readback.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        _persist(directory, request, readback, frames)
        exchange_ids.append("route-00")
        receipt["route"] = route_receipt
        receipt["station_receipt"] = dict(
            schema="extension-station-new-receipt-v1",
            existing_sids=list(e.corridor_station_sids()),
            route_pickup_sid=int(readback.pickup_sid),
            route_delivery_sid=int(readback.delivery_sid),
            verdict="DISTINCT_NEW_STATION",
        )
        (directory / "after.sav").write_bytes(b"synthetic after fixture")
        receipt["after_save_sha256"] = sha256(directory / "after.sav")
    receipt["before_save_sha256"] = source_digest
    receipt["acceptance_recheck"] = e.ACCEPTANCE_RECHECK_STATEMENT
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    _common_records(directory, seal, metadata)
    if route:
        _certified_cleanup(directory)
        status = "NATIVE_EXTENSION_VERIFIED"
        result = result or dict(
            preflight="PASS",
            native_launches=1,
            connections=1,
            requests=len(exchange_ids),
            exchanges=exchange_ids,
            built_ops=completed,
            last_status="READ",
            command_accepted=True,
            state_changed=True,
            verified=True,
            status=status,
            halt=None,
            dispatch_state="CONFIRMED",
            returncode=0,
        )
    else:
        _certified_cleanup(directory)
        # The halt tail: op-02 holds its inspection evidence only — the READY
        # admission refused (its readbacks never reach a build command).
        position = ops
        tail = build_attempt(seal, source_digest, position, spent=spent, sid=station_sid)
        (directory / f"ext-{position:02d}-before.json").write_text(
            json.dumps(tail["before"].model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        inspect_request, before = tail["files"][0]
        _persist(directory, inspect_request, before, frames)
        exchange_ids.append(inspect_request.request_id)
        completed.append(f"op-{position:02d}")
        attempts.append((f"op-{position:02d}", dict(before=before)))
        phase = corridor_phase_outcome(attempts)
        status = "PHASE_HALTED_PREFIX_PRESERVED"
        result = result or dict(
            preflight="PASS",
            native_launches=1,
            connections=1,
            requests=len(exchange_ids),
            exchanges=exchange_ids,
            built_ops=completed[:-1],
            last_status="READ",
            command_accepted=True,
            state_changed=True,
            verified=False,
            status=status,
            halt=dict(
                label=f"op-{position:02d}",
                error="ValueError: native READY admission with positive tested cost required",
            ),
            dispatch_state="DISPATCHED_UNKNOWN",
            returncode=0,
        )
    (directory / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (directory / "frames.json").write_text(json.dumps(frames))
    _restamp(directory)
    return dict(phase=phase, spent=spent, exchange_ids=exchange_ids, status=status)


def _clone(consumed: Path, tmp_path: Path) -> Path:
    """One cheap per-test clone of the synthetic consumed attempt."""
    target = tmp_path / "clone"
    shutil.copytree(consumed, target)
    return target


# --- the staging fixture -------------------------------------------------------


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    prepared = e.prepare_extension_candidate(
        tmp_path_factory.mktemp("extension-staging") / "candidate"
    )
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(staged) -> dict:
    return json.loads((staged.directory / "PRELAUNCH.json").read_text())


@pytest.fixture(scope="module")
def consumed(tmp_path_factory, staged):
    directory = tmp_path_factory.mktemp("extension-consumed") / "candidate"
    materialize_consumed(directory, staged.directory, route=True)
    yield directory


@pytest.fixture(scope="module")
def halted(tmp_path_factory, staged):
    directory = tmp_path_factory.mktemp("extension-halted") / "candidate"
    materialize_consumed(directory, staged.directory, ops=2, route=False)
    yield directory


# --- derivation: arithmetic pins, never hand-written ---------------------------


def test_extension_schedule_is_the_pinned_approved_design():
    schedule = e.extension_schedule()
    assert schedule == PINNED_SCHEDULE
    assert e.extension_witness() == e.PINNED_WITNESS == WITNESS
    assert e.corridor_station_sids() == (0, 1)
    assert e._expected_funds(0) == e.FUNDS_PIN == 492149
    route_policy = e.extension_route_policy()
    assert route_policy["expected_pairs"] == len(WITNESS) - 1 == 29
    assert route_policy["statement"].startswith("the route read is pure observation")


def test_census_slope_drift_refuses_branch_derivation(monkeypatch):
    census = d4_census()
    for entry in census["tiles"]:
        if entry["tile_id"] == 50096:
            entry["slope"] = 3
    monkeypatch.setattr(d4, "_retained_network_facts", lambda: census)
    with pytest.raises(e.ExtensionStagingError, match="not buildable flat census ground"):
        e.network_pins()


def test_census_obstruction_refuses_branch_derivation(monkeypatch):
    census = d4_census()
    for entry in census["tiles"]:
        if entry["tile_id"] == 50863:
            entry["tree"] = True
    monkeypatch.setattr(d4, "_retained_network_facts", lambda: census)
    with pytest.raises(e.ExtensionStagingError, match="carries an obstructing fact"):
        e.network_pins()


def test_built_route_evidence_drift_refuses_derivation(monkeypatch, tmp_path):
    evidence = json.loads(e.D4_ROUTE_READ_EVIDENCE.read_text())
    evidence["tiles"][15] += 1
    path = tmp_path / "route-read.json"
    path.write_text(json.dumps(evidence))
    monkeypatch.setattr(e, "D4_ROUTE_READ_EVIDENCE", path)
    with pytest.raises(
        e.ExtensionStagingError, match="built route evidence drifted from the compiled corridor"
    ):
        e.network_pins()


def test_branch_overlap_with_built_corridor_refuses(monkeypatch):
    base = d4.corridor_facts()
    corridor = list(base["corridor"])
    corridor[13] = 50352  # a real south-branch tile inside the built corridor
    monkeypatch.setattr(d4, "corridor_facts", lambda: dict(corridor=corridor, depot=base["depot"]))
    monkeypatch.setattr(e, "built_route_witness", lambda: tuple(corridor))
    with pytest.raises(e.ExtensionStagingError, match="overlaps the built D4 corridor"):
        e.network_pins()


def test_pinned_witness_disagreement_refuses_the_schedule(monkeypatch):
    pinned = list(e.PINNED_WITNESS)
    pinned[-1] = 50606
    monkeypatch.setattr(e, "PINNED_WITNESS", tuple(pinned))
    with pytest.raises(e.ExtensionStagingError, match="drifted from the pinned approved witness"):
        e.extension_schedule()


def test_front_adjacency_gate_refuses_the_schedule(monkeypatch):
    monkeypatch.setattr(e, "_adjacent", lambda a, b: False)
    with pytest.raises(e.ExtensionStagingError, match="not adjacent"):
        e.extension_schedule()


def d4_census() -> dict:
    return json.loads(json.dumps(d4._retained_network_facts()))


# --- the plan policy, budgets, wire bounds and exit discipline -----------------


def test_plan_policy_carries_the_extension_scopes():
    policy = e.extension_plan_policy()
    assert set(policy) == {
        "company",
        "target_tile",
        "max_cost",
        "command",
        "stale_rule",
        "identity",
        "schedule",
        "plan_digest",
        "schedule_version",
        "route",
        "station",
        "acceptance_recheck",
        "funds_initial",
        "funds_rule",
        "world",
        "coverage",
    }
    assert policy["company"] == 0
    assert policy["max_cost"] == e.PER_OP_MAX_COST == 2000
    assert policy["target_tile"] == int(WITNESS[25]) == 50096
    assert policy["schedule"] == PINNED_SCHEDULE
    assert policy["schedule_version"] == e.EXTENSION_SCHEDULE_VERSION == 1
    assert policy["funds_initial"] == 492149
    assert (
        "GSRoad.BuildRoadStation" in policy["command"]
        and "GSRoad.BuildRoadFull" in policy["command"]
    )
    assert "STATION_NEW" in policy["station"]["statement"]
    assert policy["station"]["existing_sids"] == [0, 1]
    assert policy["acceptance_recheck"]["statement"] == e.ACCEPTANCE_RECHECK_STATEMENT
    assert policy["route"]["witness_path"] == list(WITNESS)
    assert policy["world"]["expected_funds"] == 492149
    assert policy["world"]["branch_run"] == [50096, 50352, 50608, 50864]


def test_budgets_and_wire_bounds():
    budgets = e.extension_budgets()
    assert budgets["launches"] == budgets["connection_attempts"] == 1
    assert budgets["requests"] == e.EXTENSION_REQUEST_BUDGET == 16
    assert budgets["planned_exchanges"] == e.PLANNED_EXTENSION_REQUESTS == 10
    assert budgets["gsadmin_bytes"] == 512
    assert budgets["response_bytes"] == 640
    assert budgets["expected_funds"] == 492149
    assert budgets["per_op_max_cost"] == 2000
    for position in range(3):
        for request in _op_requests(SEAL, position):
            assert len(request.to_bytes()) <= 512
    attempt = build_attempt(SEAL, "0" * 64, 0, spent=0)
    for request, readback in attempt["files"]:
        assert len(request.to_bytes()) <= 512
        assert len(_reply_bytes(request, readback)) <= 640


def test_exit_status_discipline():
    assert e.exit_status(dict(verified=True, status="NATIVE_EXTENSION_VERIFIED")) == 0
    for bad in (
        dict(verified=False, status="FAILED"),
        dict(status="NATIVE_EXTENSION_VERIFIED"),
        dict(verified=None, status="NATIVE_EXTENSION_VERIFIED"),
    ):
        assert e.exit_status(bad) == 1
    assert e.verdict_exit_status(dict(verification="EXTENSION_COMPLETION_VERIFIED")) == 0
    assert e.verdict_exit_status(dict(verification="PHASE_HALTED_EVIDENCE_PRESERVED")) == 1


# --- staging correctness --------------------------------------------------------


def test_staged_candidate_binds_the_extension_lineage(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == e.D5_EXTENSION_PRELAUNCH_SCHEMA
    assert metadata["attempt"] == e.EXTENSION_ATTEMPT == "D5-CORRIDOR-EXTENSION-2"
    assert metadata["milestone"] == e.MILESTONE_EXTENSION == "D5-CORRIDOR-EXTENSION"
    assert metadata["kind"] == e.KIND == "corridor-extension"
    assert metadata["prerequisite"]["after_save_sha256"] == e.PINNED_PREREQUISITE_AFTER_SAVE
    assert metadata["world"]["save_sha256"] == e.PINNED_PREREQUISITE_AFTER_SAVE
    assert metadata["pin_provenance"]["manifest_verified"] is True
    assert metadata["station_merge"]["existing_sids"] == [0, 1]
    assert "STATION_NEW" in metadata["station_merge"]["statement"]
    assert metadata["acceptance_recheck"]["statement"] == e.ACCEPTANCE_RECHECK_STATEMENT
    assert metadata["budgets"] == e.extension_budgets()


def test_staged_source_save_is_the_pinned_prerequisite_after_save(staged):
    metadata = metadata_of(staged)
    assert sha256(Path(metadata["workspace"]) / "source.sav") == e.PINNED_PREREQUISITE_AFTER_SAVE


def test_staged_composition_binds_the_extension_package(staged):
    metadata = metadata_of(staged)
    files, create_instance, version = e.staged_extension_composition()
    game = Path(metadata["workspace"]) / "game" / e.SOURCE_SAVE_GS_NAME
    assert game.joinpath("main.nut").read_bytes() == files["main.nut"]
    assert game.joinpath("info.nut").read_bytes() == files["info.nut"]
    assert (
        f"class {create_instance} extends D5CorridorExtensionProof"
        in game.joinpath("main.nut").read_text()
    )
    assert version > 0


def test_design_pins_and_accepted_sharing_records(staged):
    pins = e.extension_staging_pins()
    assert pins["schema"] == "d5-corridor-extension-design-pins-v1"
    assert pins["branch_run"] == [50096, 50352, 50608, 50864]
    assert pins["branch_stop"] == 50863 and pins["branch_front"] == 50864
    assert pins["existing_station_sids"] == [0, 1]
    assert pins["census_facts"]["50096"]["buildable"] is True
    assert "no acceptance hypotheses" in pins["statement"]
    metadata = metadata_of(staged)
    assert metadata["design_pins"] == pins


def test_authorization_payload_digest_is_stable_and_no_claim_exists(staged):
    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    digest = e.staged_extension_authorization_payload_digest(staged.directory)
    rebuilt = sha256_bytes(canonical_authorization_bytes(authorization_payload(metadata, seal)))
    assert rebuilt == digest == e.staged_extension_authorization_payload_digest(staged.directory)
    assert not (staged.directory / "CLAIM.json").exists()
    assert claim_status(staged.directory) == "ABSENT"


def sha256_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def test_preflight_rehearsal_conserves_the_sealed_candidate(staged):
    metadata = e.extension_preflight(staged)
    assert metadata["attempt"] == e.EXTENSION_ATTEMPT


def _retamper(staged, mutate):
    """Apply a prelaunch mutation, restamp its seal and restore both after."""
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    seal_text = (target / "PRELAUNCH.sha256").read_text()
    mutate(json.loads(original), target)
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        e.extension_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(seal_text)


def test_preflight_refuses_budget_drift(staged):
    def mutate(metadata, target):
        metadata["budgets"]["requests"] = 64
        (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="budget pins drifted"):
        _retamper(staged, mutate)


def test_preflight_refuses_schedule_drift(staged):
    def mutate(metadata, target):
        metadata["plan_policy"]["schedule"] = metadata["plan_policy"]["schedule"][1:]
        (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="drifted"):
        _retamper(staged, mutate)


def test_preflight_refuses_design_pins_drift(staged):
    def mutate(metadata, target):
        metadata["design_pins"]["branch_stop"] = 50864
        (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="design pins drifted"):
        _retamper(staged, mutate)


def test_preflight_refuses_frozen_workspace_bytes(staged):
    workspace = Path(metadata_of(staged)["workspace"])
    config = workspace / "openttd.cfg"
    original = config.read_bytes()
    config.write_bytes(original + b"\n")
    try:
        with pytest.raises(Exception, match="Frozen source/input changed"):
            e.extension_preflight(staged)
    finally:
        config.write_bytes(original)


def test_preflight_refuses_already_consumed(staged):
    (staged.directory / "CLAIM.json").write_text(json.dumps(dict(prelaunch_digest="0" * 64)))
    try:
        with pytest.raises(ValueError, match="already consumed"):
            e.extension_preflight(staged)
    finally:
        (staged.directory / "CLAIM.json").unlink()


# --- replay verification fail-closed behavior -----------------------------------


def test_unconsumed_candidate_verifies_fail_closed(staged):
    verdict = e.verify_extension_attempt(staged.directory)
    assert verdict == {
        "verification": "AUTHORIZATION_UNVERIFIED",
        "authorization_state": "CLAIM_ABSENT",
        "statement": (
            "the extension candidate was never consumed by an operator "
            "authorization; no verified completion is possible"
        ),
    }
    assert claim_status(staged.directory) == "ABSENT"


def test_replay_refuses_a_claim_mismatched_to_its_seal(staged):
    target = staged.directory
    (target / "CLAIM.json").write_text(json.dumps(dict(prelaunch_digest="0" * 64)))
    try:
        with pytest.raises(ValueError, match="claim does not match"):
            e.verify_extension_attempt(target)
    finally:
        (target / "CLAIM.json").unlink()


@pytest.fixture()
def claimed(staged, tmp_path):
    """A forced-label attempt beside the staged seal: a self-consistent claim
    and a synthetic NATIVE_EXTENSION_VERIFIED result, but no operator
    authorization record. Everything is removed again after each test."""
    target = staged.directory
    originals = {}
    if (target / "artifact-manifest.sha256").is_file():
        originals["artifact-manifest.sha256"] = (target / "artifact-manifest.sha256").read_text()
    (target / "CLAIM.json").write_text(
        json.dumps(dict(prelaunch_digest=sha256(target / "PRELAUNCH.json"), consumed=True))
    )
    (target / "result.json").write_text(
        json.dumps(
            dict(
                verified=True,
                status="NATIVE_EXTENSION_VERIFIED",
                requests=10,
                native_launches=1,
                connections=1,
                command_accepted=True,
                returncode=0,
            ),
            sort_keys=True,
        )
        + "\n"
    )
    (target / "cleanup.json").write_text(json.dumps(dict(reaped=True, sockets_closed=True)))
    (target / "runtime-identity.json").write_text(
        json.dumps(dict(auth="X25519_AuthorizedKey", encrypted=True, welcome={}, pid=None))
    )
    (target / "frames.json").write_text("[]")
    (target / "artifact-manifest.sha256").write_text(manifest(target))
    yield target
    for name in (
        "CLAIM.json",
        "result.json",
        "cleanup.json",
        "runtime-identity.json",
        "frames.json",
    ):
        (target / name).unlink()
    for name, text in originals.items():
        (target / name).write_text(text)
    if not originals:
        (target / "artifact-manifest.sha256").unlink()


def test_replay_never_verifies_a_forced_label_without_authorization(claimed, staged):
    seal = sha256(claimed / "PRELAUNCH.json")
    claims = json.loads((claimed / "CLAIM.json").read_text())
    metadata = json.loads((claimed / "PRELAUNCH.json").read_text())
    assert replay_authorization_state(claimed, metadata, seal, claims) is not None
    verdict = e.verify_extension_attempt(claimed)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] not in (None, "CLAIM_ABSENT")


def test_replay_refuses_an_unreferenced_stray_file(claimed):
    (claimed / "stray.txt").write_text("not in the manifest")
    with pytest.raises(ValueError, match="exhaustive"):
        e.verify_extension_attempt(claimed)
    (claimed / "stray.txt").unlink()
    verdict = e.verify_extension_attempt(claimed)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_replay_refuses_an_unknown_prelaunch_schema(tmp_path, staged):
    target = tmp_path / "alien"
    target.mkdir()
    metadata = metadata_of(staged)
    metadata["schema"] = "d5-freight-prelaunch-v1"
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    (target / "CLAIM.json").write_text(
        json.dumps(dict(prelaunch_digest=sha256(target / "PRELAUNCH.json"), consumed=True))
    )
    (target / "artifact-manifest.sha256").write_text(manifest(target))
    verdict = e.verify_extension_attempt(target)
    assert verdict["authorization_state"] == "UNKNOWN_PRELAUNCH_SCHEMA"


# --- the offline session exchange boundary --------------------------------------


class _FakeSession:
    def __init__(self, reply: bytes) -> None:
        self._reply = reply
        self.sent: list[bytes] = []

    async def send(self, frame: bytes) -> None:
        self.sent.append(frame)

    async def receive(self) -> bytes:
        if getattr(self, "_read", False):
            return b""
        self._read = True
        return self._reply


def test_extension_exchange_persists_request_and_response_pair(tmp_path):
    schedule = e.extension_schedule()
    request = e._extension_request("inspect", "inspect-00", SEAL, 0, MAX_COST, schedule[0])
    readback = rb(
        request,
        status="READY",
        eligible=True,
        cost=OP_COSTS[0],
        funds=FUNDS,
        **road_fields(3, owners=(-1, -1), roads=(False, False), covered=0, pairs_ok=0),
    )
    reply = _admin_frame(_reply_bytes(request, readback) + b"\0")
    parsed = asyncio.run(e.exchange(_FakeSession(reply), request, tmp_path))
    assert parsed == readback
    assert (tmp_path / "inspect-00-request.json").read_bytes() == request.to_bytes()
    assert (
        CorridorReadback.parse_for(request, (tmp_path / "inspect-00-response.json").read_bytes())
        == readback
    )
    with pytest.raises(ConnectionError):
        asyncio.run(e.exchange(_FakeSession(b""), request, tmp_path))


# --- consumed-frame replay: the synthetic verified attempt ----------------------
#
# Explicitly synthetic: the consumed fixture only copies the sealed staged
# PRELAUNCH pair, then fabricates every post-launch artifact with the same
# correlated protocol-4 discipline. No native process, AdminPort session,
# signature or authorization is created. Because no authorized run exists
# under the tests, the operator-authorization gate is the one monkeypatched
# seam; every identity, digest, phase, frame, funds and cleanup fact is
# otherwise verified by the production replay path.


def test_replay_verifies_the_synthetic_consumed_attempt(consumed, monkeypatch):
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    verdict = e.verify_extension_attempt(consumed)
    assert verdict["verification"] == "EXTENSION_COMPLETION_VERIFIED"
    receipt = verdict["receipt"]
    assert receipt["verification"] == "PHASE_COMPLETE"
    assert [entry["kind"] for entry in receipt["completed"]] == ["full", "road", "station"]
    assert len(e.extension_request_sequence(e.extension_schedule())) == 10
    assert receipt["station_receipt"]["verdict"] == "DISTINCT_NEW_STATION"
    assert receipt["station_receipt"]["existing_sids"] == [0, 1]
    assert receipt["station_receipt"]["route_delivery_sid"] == 2
    assert receipt["station_receipt"]["route_delivery_sid"] not in (0, 1)
    assert receipt["route"]["funds"] == FUNDS - sum(OP_COSTS.values()) == 491317
    assert receipt["acceptance_recheck"] == e.ACCEPTANCE_RECHECK_STATEMENT
    assert e.verdict_exit_status(verdict) == 0


def test_replay_fails_closed_on_opening_funds_drift(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-00-before.json", funds=FUNDS - 1)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="opening funds pin"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_native_cost_overrun(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-01-built.json", cost=OP_COSTS[1] + 10)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="verified receipt contradicts its phase outcome"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_per_op_ceiling_drift(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-01-intent.json", max_cost=3000)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="per-op cost ceiling"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_station_merge_sid1(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-02-built.json", sid=1)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="station-merge defect at op-02"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_drive_through_stop(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-02-built.json", drive_through=True)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="drive-through stop refused at op-02"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_pairs_accounting_mismatch(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "ext-00-built.json", pairs_ok=1)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="verified receipt contradicts its phase outcome"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_route_funds_drift(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    raw = (target / "route-00-response.json").read_bytes()
    record = json.loads(raw)
    record["funds"] = FUNDS - sum(OP_COSTS.values()) + 1
    _replace_inbound(
        target, "route-00", json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    )
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="funds arithmetic drifted"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_duplicate_outbound_frame(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    frames = json.loads((target / "frames.json").read_text())
    frames.insert(4, frames[2])  # the inspect-00 outbound frame, repeated
    (target / "frames.json").write_text(json.dumps(frames))
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="duplicate request_id|exceeds request file count"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_out_of_schedule_request(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    request = CorridorRequest(
        op="road",
        request_id="road-99",
        plan=SEAL,
        company=0,
        max_cost=MAX_COST,
        start=50095,
        end=50096,
    )
    (target / "road-99-request.json").write_bytes(request.to_bytes())
    frames = json.loads((target / "frames.json").read_text())
    frames.append(["outbound", encode_gamescript(request.to_bytes()).hex()])
    (target / "frames.json").write_text(json.dumps(frames))
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="outside the staged schedule"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_malformed_outbound_frame(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    frames = json.loads((target / "frames.json").read_text())
    frames.append(["outbound", encode_gamescript(b'{"op":"site"}').hex()])
    (target / "frames.json").write_text(json.dumps(frames))
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="invalid CorridorRequest"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_orphan_response_file(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    record = json.loads((target / "route-00-response.json").read_text())
    record["request_id"] = "route-01"
    (target / "route-01-response.json").write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":"))
    )
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="lacks its request"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_uncertified_cleanup(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "cleanup.json", workspace_disposed=False)
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="cleanup or built inventory incomplete"):
        e.verify_extension_attempt(target)


def test_replay_fails_closed_on_manifest_digest_drift(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    _revise(target, "cleanup.json", returncode=3)  # no restamp: the drift itself
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    with pytest.raises(ValueError, match="manifest mismatch"):
        e.verify_extension_attempt(target)


def test_replay_is_unresolved_when_the_frame_stream_is_truncated(consumed, tmp_path, monkeypatch):
    target = _clone(consumed, tmp_path)
    frames = json.loads((target / "frames.json").read_text())
    del frames[-2:]
    (target / "frames.json").write_text(json.dumps(frames))
    _restamp(target)
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    verdict = e.verify_extension_attempt(target)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "NATIVE_EXTENSION_VERIFIED"


def test_halted_attempt_replays_as_prefix_preserved(halted, monkeypatch):
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    verdict = e.verify_extension_attempt(halted)
    assert verdict["verification"] == "PHASE_HALTED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert verdict["completed"] == ["full", "road"]
    assert verdict["failed"]["label"] == "op-02"
    assert verdict["error"] == "corridor attempt lacks retained execution evidence"
    assert e.verdict_exit_status(verdict) == 1


# --- execution arm: scripted backend over the production run path ---------------
#
# These tests drive the real ``execute_extension_attempt`` production function
# end to end: the real preflight, the real ``exchange``/``CorridorReadback``
# wire parsing, the real ``admit_corridor``/``verify_corridor``/
# ``corridor_phase_outcome``/``verify_corridor_route`` verifiers, the real
# funds/station gates, the real diagnostic-save/cleanup/log-health tail and
# the real replay verifier over the retained evidence. The scripted backend
# implements the same production backend interface (preflight/launch/health/
# connect/cleanup, console saves, frame observation) and answers each
# protocol-4 request with correlated readbacks built by the same synthetic
# helpers the replay fixtures use. The ONLY monkeypatched seam is the
# operator-authorization gate (``grant_launch``): no operator private key
# exists under the tests, exactly as in the consumed-frame replay section
# above. Nothing here launches OpenTTD or opens AdminPort.


class ScriptedSession:
    """One correlated protocol-4 session over scripted readbacks.

    Implements the production secure-session surface the execution arm uses:
    ``authenticate``, ``send``/``receive`` over real Admin wire frames, the
    ``welcome``/``protocol``/``state`` identity attributes and ``close``.
    Subscription and ping frames are answered exactly as the native runtime
    would (ordered AdminPong barrier); corridor requests are answered from
    the scripted response table, decoded and re-correlated through the real
    ``CorridorRequest`` model.
    """

    def __init__(self, responses, welcome, *, drop_ids=(), dead_after=None):
        self._responses = responses
        self._drop = set(drop_ids)
        self._dead_after = dead_after
        self._queue: list[bytes] = []
        self.state = AuthState.ACTIVE
        self.protocol = ServerProtocol(version=3, advertised_frequencies=((9, 0x40),))
        self.welcome = welcome
        self.served: list[str] = []
        self.closed = False
        self._saw_dead = False

    async def authenticate(self, attempt, password, *, timeout=None):
        return None

    async def send(self, *frames):
        for frame in frames:
            if frame == gamescript_subscription():
                continue
            if frame[2] == 7:  # ADMIN ping: the ordered barrier pong
                self._queue.append(encode_admin_frame(126, frame[3:]))
                continue
            if frame[2] != 6:  # ADMIN_GAMESCRIPT
                raise AssertionError(f"unexpected outbound frame kind {frame[2]}")
            payload = json.loads(decode_gamescript(frame[3:]))
            if isinstance(payload.get("tiles"), list):
                payload = dict(payload, tiles=tuple(payload["tiles"]))
            request = CorridorRequest.model_validate(payload)
            self.served.append(request.request_id)
            if self._dead_after is not None and request.request_id == self._dead_after:
                self._saw_dead = True
                continue  # the command frame is never answered
            if self._saw_dead:
                raise AssertionError(f"stream reused after the dead point: {request.request_id}")
            if request.request_id in self._drop:
                continue
            readback = self._responses[request.request_id]
            self._queue.append(
                encode_admin_frame(SERVER_GAMESCRIPT, _reply_bytes(request, readback) + b"\0")
            )

    async def receive(self, *args):
        if self._queue:
            return self._queue.pop(0)
        return b""

    async def close(self, *, quit=False):
        self.closed = True


class FakeStdin:
    """The owned native console: save commands write real files and acks."""

    def __init__(self, backend):
        self._backend = backend

    def write(self, data: bytes):
        self._backend.console_commands.append(data.decode())
        text = data.decode()
        if text.startswith("save "):
            name = json.loads('"' + text[5:].strip().strip('"') + '"')
            path = Path(name + ".sav")  # OpenTTD 15.3 ConSave appends .sav
            if path.name.startswith("after-diagnostic") and self._backend.fail_diagnostic_save:
                with self._backend.logs[0].open("a") as stream:
                    stream.write("Saving map failed.\n")
                return
            path.write_bytes(b"synthetic native save fixture\n")
            with self._backend.logs[0].open("a") as stream:
                stream.write(f"Map successfully saved to '{path}'.\n")

    def flush(self):
        pass


class FakeProcess:
    def __init__(self, backend, returncode=0):
        self._backend = backend
        self.pid = 424242
        self.returncode = returncode
        self.exited = False
        self.stdin = FakeStdin(backend)

    def poll(self):
        return self.returncode if self.exited else None


class ScriptedBackend:
    """The production backend interface, scripted: no process, no socket."""

    def __init__(
        self,
        responses,
        welcome,
        *,
        fail_diagnostic_save=False,
        returncode=0,
        fatal_log_line=None,
        **session_kwargs,
    ):
        self._responses = responses
        self._welcome = welcome
        self._session_kwargs = session_kwargs
        self.fail_diagnostic_save = fail_diagnostic_save
        self._returncode = returncode
        self._fatal_log_line = fatal_log_line
        self.process = None
        self.session = None
        self.console_commands: list[str] = []
        self.logs: list[Path] = []
        self.cleaned = False

    def preflight(self, prepared):
        return None

    async def launch(self, prepared, *, authorization=None):
        assert authorization is not None, "the launch boundary requires the grant"
        self.logs = [prepared.spec.stdout_path, prepared.spec.stderr_path]
        for path in self.logs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        with self.logs[0].open("a") as stream:
            stream.write(f"{e.EXTENSION_READY_MARKER}\n")
            stream.write(f"{ROAD_PROOF_COMPANY_READY_MARKER}\n")
            if self._fatal_log_line is not None:
                stream.write(self._fatal_log_line + "\n")
        self.process = FakeProcess(self, returncode=self._returncode)

    def health(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("scripted native runtime is not alive")

    async def connect(self, prepared, *, frame_observer):
        self.session = ScriptedSession(self._responses, self._welcome, **self._session_kwargs)
        inner_send, inner_receive = self.session.send, self.session.receive

        async def observed_send(*frames):
            for frame in frames:
                frame_observer("outbound", frame)
            await inner_send(*frames)

        async def observed_receive(*args):
            chunk = await inner_receive(*args)
            if chunk:
                frame_observer("inbound", chunk)
            return chunk

        self.session.send = observed_send
        self.session.receive = observed_receive
        return self.session

    async def cleanup(self, prepared):
        self.cleaned = True
        if self.process is not None:
            self.process.exited = True
        if self.session is not None:
            await self.session.close(quit=True)
        return {
            "pid": None if self.process is None else self.process.pid,
            "graceful_attempted": True,
            "quit_command": "quit",
            "returncode": self.process.returncode if self.process else None,
            "reaped": True,
            "remaining_processes": [],
            "events": ["reaped"],
            "cleanup_error": [],
        }


def clone_candidate(source: Path, target: Path) -> Path:
    """One consumable per-test copy of the staged candidate.

    The staged module fixture must survive every execution test (an attempt
    consumes its claim and disposes its workspace), so each run gets a full
    copy with only the workspace path re-anchored and the seal restamped.
    """
    shutil.copytree(source, target, symlinks=True)
    metadata = json.loads((target / "PRELAUNCH.json").read_text())
    metadata["workspace"] = str(target / "isolated" / Path(metadata["workspace"]).name)
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    return target


def reopen_prepared(directory: Path) -> PreparedProof:
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    workspace = RuntimeWorkspace.reopen(directory / "isolated" / Path(metadata["workspace"]).name)
    spec = LaunchSpecification(
        workspace,
        RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
        tuple(metadata["argv"]),
        workspace.root,
        workspace.environment,
        workspace.logs / "stdout.log",
        workspace.logs / "stderr.log",
    )
    return PreparedProof(
        directory,
        spec,
        workspace.root / ".admin-secret",
        metadata["public_key"],
        (metadata["game_port"], metadata["admin_port"]),
    )


def scripted_world(seal: str, source_digest: str, *, ops=3, route=True, mutate=None):
    """The full scripted protocol-4 world for one candidate seal.

    Every readback is built by the same synthetic helpers the replay fixtures
    use (each exchange group pre-verified by the production
    ``verify_corridor`` inside ``build_attempt``) unless a ``mutate`` hook
    deliberately corrupts one response: the hook sees
    ``(position, name, readback)`` and returns the replacement. Returns
    ``(responses_by_request_id, spent_total)``.
    """
    responses: dict[str, CorridorReadback] = {}
    spent = 0
    for position in range(ops):
        attempt = build_attempt(seal, source_digest, position, spent=spent)
        for (request, readback), name in zip(
            attempt["files"], ("before", "built", "independent"), strict=True
        ):
            if mutate is not None:
                readback = mutate(position, name, readback) or readback
            responses[request.request_id] = readback
        spent = attempt["spent"]
    if route:
        request, readback, _ = route_exchange(seal, funds=FUNDS - spent)
        if mutate is not None:
            readback = mutate(None, "route", readback) or readback
        responses[request.request_id] = readback
    return responses, spent


def welcome_of(directory: Path) -> ServerWelcome:
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    expected = metadata["world"]["expected_welcome"]
    return ServerWelcome(
        name="synthetic",
        revision=expected["revision"],
        dedicated=True,
        map_name="synthetic",
        seed=expected["seed"],
        landscape=expected["landscape"],
        start_day=expected["start_day"],
        width=expected["width"],
        height=expected["height"],
    )


def run_execution(directory: Path, backend_factory, monkeypatch) -> tuple[dict, object]:
    """Drive the production execution arm against one scripted backend.

    The candidate is reopened through the production ``PreparedProof``
    machinery and executed by the real ``execute_extension_attempt``. The
    operator-authorization gate is the single monkeypatched seam (synthetic
    grant; no private key exists under the tests).
    """
    prepared = reopen_prepared(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    grant = LaunchGrant(
        directory=directory.resolve(),
        prelaunch_sha256=seal,
        authorization_sha256="f" * 64,
        operator_key_identity="synthetic-test-fixture",
        record={"synthetic": True},
    )
    monkeypatch.setattr(e, "grant_launch", lambda *a, **k: grant)
    backend = backend_factory(directory)
    result = asyncio.run(e.execute_extension_attempt(prepared, backend))
    return result, backend


@pytest.fixture()
def execution_candidate(staged, tmp_path):
    """One fresh consumable candidate clone with its scripted-world factory."""
    target = clone_candidate(staged.directory, tmp_path / "run")
    seal = sha256(target / "PRELAUNCH.json")
    metadata = json.loads((target / "PRELAUNCH.json").read_text())
    source_digest = metadata["world"]["save_sha256"]

    def factory(mutate=None, ops=3, route=True, **backend_kwargs):
        responses, spent = scripted_world(seal, source_digest, ops=ops, route=route, mutate=mutate)

        def build(directory):
            return ScriptedBackend(responses, welcome_of(directory), **backend_kwargs)

        return build, responses, spent

    return dict(directory=target, seal=seal, source_digest=source_digest, factory=factory)


# --- execution-arm tests: the production run path, scripted world --------------


def test_execution_completes_the_full_schedule_and_verifies(execution_candidate, monkeypatch):
    """The successful path: three inspect-command-read groups, the 30-tile
    (29 expected pairs) route read, exact cumulative funds accounting and
    the verified receipt,
    re-verified by the production replay over the retained evidence."""
    build, responses, spent = execution_candidate["factory"]()
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    directory = execution_candidate["directory"]
    assert result["status"] == "NATIVE_EXTENSION_VERIFIED"
    assert result["verified"] is True
    assert result["halt"] is None
    assert result["built_ops"] == ["op-00", "op-01", "op-02"]
    assert result["phase"]["verification"] == "PHASE_COMPLETE"
    # Every scheduled exchange reached the wire, in schedule order, ending
    # with the independent route read: proof the arm ran to completion.
    assert backend.session.served == [
        "inspect-00",
        "full-00",
        "confirm-00",
        "inspect-01",
        "road-01",
        "confirm-01",
        "inspect-02",
        "station-02",
        "confirm-02",
        "route-00",
    ]
    assert result["requests"] == 10 == e.PLANNED_EXTENSION_REQUESTS
    assert len(responses["route-00"].tiles) == 30
    # Cumulative cost/funds accounting: each op's retained post-debit
    # balance is the pin minus the verified prefix cost, and the route read
    # closes at the pin minus the full spend.
    cumulative = 0
    for position, cost in enumerate(OP_COSTS.values()):
        cumulative += cost
        built = json.loads((directory / f"ext-{position:02d}-built.json").read_text())
        independent = json.loads((directory / f"ext-{position:02d}-independent.json").read_text())
        assert built["funds"] == independent["funds"] == FUNDS - cumulative
    route = json.loads((directory / "ext-route-read.json").read_text())
    assert spent == sum(OP_COSTS.values())
    assert route["funds"] == FUNDS - spent
    assert result["route"]["verification"] == "ROUTE_VERIFIED"
    receipt = json.loads((directory / "receipt.json").read_text())
    assert receipt["verification"] == "PHASE_COMPLETE"
    assert receipt["station_receipt"]["verdict"] == "DISTINCT_NEW_STATION"
    assert receipt["route"]["funds"] == FUNDS - spent
    # The retained evidence replays to a verified completion (the synthetic
    # operator-authorization gate is the single patched seam).
    monkeypatch.setattr(e, "replay_authorization_state", lambda *a, **k: None)
    verdict = e.verify_extension_attempt(directory)
    assert verdict["verification"] == "EXTENSION_COMPLETION_VERIFIED"
    assert e.verdict_exit_status(verdict) == 0
    assert e.exit_status(result) == 0


def test_execution_accepts_post_debit_balances_at_every_gate(execution_candidate, monkeypatch):
    """Each command/read pair is gated on the POST-debit balance: the pin
    minus the previous spend minus this operation's own cost."""
    build, _, _ = execution_candidate["factory"]()
    result, _ = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["status"] == "NATIVE_EXTENSION_VERIFIED"
    directory = execution_candidate["directory"]
    spent = 0
    for position, cost in enumerate(OP_COSTS.values()):
        before = json.loads((directory / f"ext-{position:02d}-before.json").read_text())
        built = json.loads((directory / f"ext-{position:02d}-built.json").read_text())
        # The inspect observes the pre-debit balance; the command and the
        # independent read observe the post-debit balance for this op's cost.
        assert before["funds"] == FUNDS - spent
        assert built["funds"] == FUNDS - spent - cost
        assert built["cost"] == cost
        spent += cost


def test_execution_regression_accepts_the_valid_post_debit_command(
    execution_candidate, monkeypatch
):
    """The exact F1 regression: initial funds 492149, op-00 costs 454 (within
    the 2000 ceiling), the handler reports the correct post-debit balance
    491695, and the host execution path accepts the command and its readback
    instead of comparing them against the pre-debit balance."""
    assert FUNDS == 492149
    assert OP_COSTS[0] == 454 and 0 < OP_COSTS[0] <= MAX_COST
    build, responses, _ = execution_candidate["factory"]()
    # The scripted handler reports exactly the post-debit balance for op-00.
    assert responses["full-00"].funds == 492149 - 454 == 491695
    assert responses["confirm-00"].funds == 491695
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    # The pre-fix gate expected 492149 at "op-00 command" and halted there;
    # the fixed gate accepts the valid post-debit construction and the whole
    # schedule runs to its verified completion.
    assert result["halt"] is None
    assert "op-00" in result["built_ops"]
    assert result["status"] == "NATIVE_EXTENSION_VERIFIED"
    assert backend.session.served[-1] == "route-00"


def test_execution_regression_refuses_a_pre_debit_command_balance(
    execution_candidate,
    monkeypatch,
):
    """The negative regression: a handler that reports the PRE-debit balance
    (no debit for a positive cost) still fails closed at the command gate."""

    def pre_debit(position, name, readback):
        if position == 0 and name == "built":
            return readback.model_copy(update={"funds": FUNDS})  # 492149, un-debited
        return readback

    build, _, _ = execution_candidate["factory"](mutate=pre_debit)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert result["halt"]["label"] == "op-00"
    assert "funds drift" in result["halt"]["error"]
    # Nothing after the refused command was ever dispatched.
    assert backend.session.served == ["inspect-00", "full-00"]
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_halts_on_funds_drift_and_blocks_later_ops(execution_candidate, monkeypatch):
    """An unexpected balance change at op-01 halts the attempt prefix-
    preservingly; op-02 and the route read are never reached."""

    def drift(position, name, readback):
        if position == 1 and name == "built":
            return readback.model_copy(update={"funds": readback.funds - 1})
        return readback

    build, _, _ = execution_candidate["factory"](mutate=drift)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert result["halt"]["label"] == "op-01"
    assert "funds drift" in result["halt"]["error"]
    assert result["built_ops"] == ["op-00"]
    assert backend.session.served == [
        "inspect-00",
        "full-00",
        "confirm-00",
        "inspect-01",
        "road-01",
    ]
    # The verified op-00 prefix evidence is preserved; the refused op-01
    # command never reached its evidence write (the gate precedes it).
    directory = execution_candidate["directory"]
    assert (directory / "ext-00-built.json").is_file()
    assert (directory / "ext-01-before.json").is_file()
    assert not (directory / "ext-01-built.json").exists()
    assert not (directory / "ext-02-before.json").exists()
    assert not (directory / "receipt.json").exists()


@pytest.mark.parametrize(
    ("name", "cost"),
    [("over-limit", MAX_COST + 1), ("negative", -5), ("zero", 0)],
)
def test_execution_fails_closed_on_cost_violations(execution_candidate, monkeypatch, name, cost):
    """Over-limit, negative and zero costs all fail closed before any
    mutation is accepted."""

    def bad_cost(position, readback_name, readback):
        if position == 0 and readback_name == "before":
            return readback.model_copy(update={"cost": cost})
        return readback

    build, _, _ = execution_candidate["factory"](mutate=bad_cost)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False, name
    assert result["halt"]["label"] == "op-00", name
    assert result["built_ops"] == [], name
    # The refusal lands at the inspect admission: no build command is ever
    # dispatched, so no later mutation can run.
    assert backend.session.served == ["inspect-00"], name
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_fails_closed_on_inconsistent_command_cost(execution_candidate, monkeypatch):
    """A command whose reported cost disagrees with the admitted native test
    cost fails closed even though the funds gate arithmetic would balance."""

    def inconsistent(position, name, readback):
        if position == 0 and name in ("built", "independent"):
            # Keep the gate arithmetic self-consistent but the cost wrong:
            # both post-command observations agree on the drifted cost, so
            # only verify_corridor's native-tested-cost equality can catch it.
            return readback.model_copy(
                update={"cost": OP_COSTS[0] + 1, "funds": FUNDS - OP_COSTS[0] - 1}
                if name == "built"
                else {"funds": FUNDS - OP_COSTS[0] - 1}
            )
        return readback

    build, _, _ = execution_candidate["factory"](mutate=inconsistent)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["halt"]["label"] == "op-00"
    assert "funds mismatch" in result["halt"]["error"]
    # verify_corridor runs after the independent read, so op-00's group is
    # fully dispatched; op-01 is never reached.
    assert backend.session.served == ["inspect-00", "full-00", "confirm-00"]
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_halts_on_unanswered_command_without_fabrication(
    execution_candidate, monkeypatch
):
    """A command frame that is never answered halts the attempt at the
    dispatch boundary: no fabricated success, no later mutation, and the
    uncertain world state triggers the diagnostic-save path."""
    build, _, _ = execution_candidate["factory"](dead_after="full-00")
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert result["halt"]["label"] == "op-00"
    assert result["dispatch_state"] == "DISPATCHED_UNKNOWN"
    assert result["command_accepted"] is False
    assert result["state_changed"] is False
    assert backend.session.served == ["inspect-00", "full-00"]
    directory = execution_candidate["directory"]
    # The attempted operation's evidence is retained; nothing later exists.
    assert (directory / "ext-00-before.json").is_file()
    assert (directory / "ext-00-intent.json").is_file()
    assert not (directory / "ext-00-built.json").exists()
    assert not (directory / "receipt.json").exists()
    # The uncertain state was diagnostically preserved.
    assert result.get("after_diagnostic_save_sha256")
    assert (directory / "after-diagnostic.sav").is_file()


def test_execution_records_diagnostic_save_failure_and_never_verifies(
    execution_candidate, monkeypatch
):
    """When the world state is uncertain and the diagnostic save cannot be
    retained, the failure is recorded and no verified success is possible."""

    def drift(position, name, readback):
        if position == 1 and name == "built":
            return readback.model_copy(update={"funds": readback.funds + 1})
        return readback

    build, _, _ = execution_candidate["factory"](mutate=drift, fail_diagnostic_save=True)
    result, _ = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert "after_save_error" in result
    assert "after_diagnostic_save_sha256" not in result
    assert not (execution_candidate["directory"] / "after-diagnostic.sav").exists()
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_refuses_verified_success_when_the_receipt_save_fails(
    execution_candidate, monkeypatch
):
    """The receipt-bound after-save is required diagnostic evidence for a
    verified completion: if it cannot be retained, the run cannot verify."""
    responses, _ = scripted_world(
        execution_candidate["seal"],
        execution_candidate["source_digest"],
    )

    # Patch only the receipt save: the scripted console refuses the "after"
    # save while every protocol exchange stays nominally successful.
    def build_refusing(directory):
        backend = ScriptedBackend(responses, welcome_of(directory))
        original = FakeStdin.write

        def write(stdin, data):
            text = data.decode()
            if text.startswith("save "):
                name = json.loads('"' + text[5:].strip().strip('"') + '"')
                if Path(name).name == "after":
                    stdin._backend.console_commands.append(text)
                    with stdin._backend.logs[0].open("a") as stream:
                        stream.write("Saving map failed.\n")
                    return
            original(stdin, data)

        monkeypatch.setattr(FakeStdin, "write", write)
        return backend

    result, _ = run_execution(execution_candidate["directory"], build_refusing, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "FAILED"
    assert "save" in result["error"].lower()
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_demotes_verified_on_script_log_health_findings(
    execution_candidate,
    monkeypatch,
):
    """A nominally successful protocol sequence cannot override a failed
    process-health check: a fatal native log marker demotes the receipt."""
    build, _, _ = execution_candidate["factory"](fatal_log_line="Fatal error: scripted demotion")
    result, _ = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "FAILED"
    assert "script log health findings deny the verified receipt" in result["error"]
    # The retained result record is the authority and it is a demoted FAILED.
    retained = json.loads((execution_candidate["directory"] / "result.json").read_text())
    assert retained["verified"] is False
    assert retained["status"] == "FAILED"
    assert e.exit_status(retained) == 1


def test_execution_demotes_verified_on_abnormal_returncode(execution_candidate, monkeypatch):
    """A nominally successful protocol sequence cannot override an abnormal
    native process exit: return code 3 demotes the receipt to FAILED."""
    build, _, _ = execution_candidate["factory"](returncode=3)
    result, _ = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["status"] == "FAILED"
    assert result["returncode"] == 3
    assert "exited abnormally" in result["error"]
    retained = json.loads((execution_candidate["directory"] / "result.json").read_text())
    assert retained["verified"] is False
    assert retained["status"] == "FAILED"


def test_execution_preserves_evidence_on_failed_independent_readback(
    execution_candidate, monkeypatch
):
    """Partial mutation with a failed readback: op-01's build mutated the
    world but its independent read reports the pre-mutation state. The
    attempted-operation evidence is preserved, later operations are halted
    and success is refused."""

    def stale_read(position, name, readback):
        if position == 1 and name == "independent":
            return readback.model_copy(update={"pairs_ok": 0})  # pre-mutation state
        return readback

    build, _, _ = execution_candidate["factory"](mutate=stale_read)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    directory = execution_candidate["directory"]
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert result["halt"]["label"] == "op-01"
    assert result["built_ops"] == ["op-00"]
    assert result["phase"]["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    assert result["phase"]["failed"]["label"] == "op-01"
    assert result["phase"]["failed"]["world_state"] == "UNCERTAIN_AFTER_FAILED_COMMAND"
    # op-01's attempted evidence (including the built mutation) is retained.
    assert (directory / "ext-01-built.json").is_file()
    assert (directory / "ext-01-independent.json").is_file()
    # op-02 and the route read were never dispatched.
    assert backend.session.served == [
        "inspect-00",
        "full-00",
        "confirm-00",
        "inspect-01",
        "road-01",
        "confirm-01",
    ]
    assert not (directory / "ext-02-before.json").exists()
    assert not (directory / "receipt.json").exists()
    # The uncertain world state was diagnostically preserved.
    assert (directory / "after-diagnostic.sav").is_file()


def test_execution_halts_on_station_merge_defect(execution_candidate, monkeypatch):
    """A branch stop reporting an existing corridor station sid is the
    station-merge defect: halt before any later operation."""

    def merge(position, name, readback):
        if position == 2 and name == "built":
            return readback.model_copy(update={"sid": 1})  # an existing corridor sid
        return readback

    build, _, _ = execution_candidate["factory"](mutate=merge)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["halt"]["label"] == "op-02"
    assert "station-merge defect" in result["halt"]["error"]
    assert backend.session.served[-1] == "station-02"
    assert "route-00" not in backend.session.served
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_halts_on_invalid_station_identity(execution_candidate, monkeypatch):
    """A drive-through stop contradicts the pinned truck-stop design and is
    refused before the independent read or any later operation."""

    def invalid(position, name, readback):
        if position == 2 and name == "built":
            return readback.model_copy(update={"drive_through": True})
        return readback

    build, _, _ = execution_candidate["factory"](mutate=invalid)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    assert result["verified"] is False
    assert result["halt"]["label"] == "op-02"
    assert "drive-through stop refused" in result["halt"]["error"]
    assert backend.session.served[-1] == "station-02"
    assert not (execution_candidate["directory"] / "receipt.json").exists()


def test_execution_refuses_success_on_route_read_mismatch(execution_candidate, monkeypatch):
    """All three ops build, but the final 30-tile (29 expected pairs) route
    read reports an
    incomplete corridor: no route receipt, no completion verdict, no
    verified success."""

    def broken_route(position, name, readback):
        if name == "route":
            return readback.model_copy(update={"connected_pairs": 27, "first_fail": 12})
        return readback

    build, _, _ = execution_candidate["factory"](mutate=broken_route)
    result, backend = run_execution(execution_candidate["directory"], build, monkeypatch)
    directory = execution_candidate["directory"]
    assert result["verified"] is False
    assert result["status"] == "FAILED"
    assert "route connectivity is incomplete" in result["error"]
    # The phase itself completed; the route read was reached and refused.
    assert result["phase"]["verification"] == "PHASE_COMPLETE"
    assert backend.session.served[-1] == "route-00"
    assert not (directory / "receipt.json").exists()
    assert "route" not in result
    # Even the retained result record refuses the completion.
    retained = json.loads((directory / "result.json").read_text())
    assert retained["verified"] is False


# --- consumed terrain-survey evidence of record (fail-closed reader) ----------


def _clone_survey(tmp_path: Path, mutate=None, *, drop=False) -> Path:
    """A private copy of the retained survey for tamper tests (evidence of
    record itself stays untouched)."""
    target = tmp_path / "survey-copy"
    shutil.copytree(e.PINNED_TERRAIN_SURVEY, target)
    if drop:
        (target / "result.json").unlink()
    elif mutate is not None:
        path = target / "result.json"
        result = json.loads(path.read_text())
        mutate(result)
        path.write_text(json.dumps(result, sort_keys=True))
    return target


def test_terrain_survey_facts_match_the_pinned_evidence_of_record():
    facts = e.terrain_survey_facts()
    assert facts["schema"] == "d5-terrain-survey-evidence-v1"
    assert facts["plan_digest"] == e.TERRAIN_SURVEY_PLAN_DIGEST
    assert facts["seal"] == e.TERRAIN_SURVEY_SEAL
    assert facts["world_save"] == e.PINNED_PREREQUISITE_AFTER_SAVE
    assert facts["tiles"]["50096"]["slope"] == 12
    assert facts["tiles"]["50352"]["slope"] == 12
    assert facts["tiles"]["50608"]["slope"] == 8
    assert facts["tiles"]["50096"]["buildable"] is True
    assert facts["tiles"]["50095"]["road"] is True
    assert facts["acceptance"] == {"50351": 0, "50863": 8}
    assert facts["statement"].startswith("the consumed read-only survey")


def test_terrain_survey_absence_and_outcome_label_refuse(tmp_path):
    with pytest.raises(e.ExtensionStagingError, match="evidence is absent"):
        e.terrain_survey_facts(_clone_survey(tmp_path, drop=True))
    with pytest.raises(e.ExtensionStagingError, match="not a verified zero-mutation"):
        e.terrain_survey_facts(
            _clone_survey(
                tmp_path / "a",
                lambda result: result.__setitem__("status", "OTHER"),
            )
        )


def test_terrain_survey_identity_drift_refuses(tmp_path):
    with pytest.raises(e.ExtensionStagingError, match="identity drifted"):
        e.terrain_survey_facts(
            _clone_survey(
                tmp_path / "a",
                lambda result: result["phase"].__setitem__("plan_digest", "0" * 64),
            )
        )
    with pytest.raises(e.ExtensionStagingError, match="identity drifted"):
        e.terrain_survey_facts(
            _clone_survey(
                tmp_path / "b",
                lambda result: result["phase"].__setitem__("seal", "1" * 64),
            )
        )
    with pytest.raises(e.ExtensionStagingError, match="facts for 50096 drifted"):
        e.terrain_survey_facts(
            _clone_survey(
                tmp_path / "c",
                lambda result: result["phase"]["terra"]["50096"].__setitem__("buildable", False),
            )
        )


def test_terrain_survey_acceptance_drift_refuses(tmp_path):
    with pytest.raises(e.ExtensionStagingError, match="for 50863 drifted"):
        e.terrain_survey_facts(
            _clone_survey(
                tmp_path,
                lambda result: result["phase"]["observations"]["50863"].__setitem__("value", 9),
            )
        )


def test_design_pins_carry_the_terrain_survey_evidence():
    pins = e.extension_staging_pins()
    facts = e.terrain_survey_facts()
    assert pins["terrain_survey"] == facts
    assert pins["terrain_survey"]["tiles"]["50352"]["slope"] == 12
    assert (
        "census ground whose live escarpment slopes" in pins["statement"]
        and "D5-TERRAIN-SURVEY-1" in pins["statement"]
    )


def test_preflight_refuses_terrain_survey_drift_standing_in_the_pins(staged, tmp_path, monkeypatch):
    """The survey evidence is part of the design pins: a drifted tile fact in
    the sealed prelaunch record can never re-derive."""

    def mutate(metadata, target):
        metadata["design_pins"]["terrain_survey"]["tiles"]["50608"]["slope"] = 0
        (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="design pins drifted"):
        _retamper(staged, mutate)


# --- the final route witness: pair semantics and station-terminal gates ---------


def _route_readback(seal: str, *, witness=WITNESS, **overrides):
    """A synthetic final route readback (explicitly synthetic; the acceptance
    and refusals below go through the real production verifier)."""
    request = CorridorRequest(
        op="route", request_id="route-00", plan=seal, company=0, max_cost=0, tiles=witness
    )
    fields = dict(
        status="READ",
        eligible=True,
        cost=0,
        funds=FUNDS,
        connected_pairs=len(witness) - 1,
        first_fail=-1,
        pickup_stop=True,
        pickup_truck=True,
        pickup_sid=0,
        delivery_stop=True,
        delivery_truck=True,
        delivery_sid=2,
        depot_pin_ok=True,
    )
    fields.update(overrides)
    return request, rb(request, **fields)


def test_route_witness_accepts_ordinary_road_to_road_pairs():
    """A fully road-tiled witness with consistent observation fields derives
    the ROUTE_VERIFIED receipt through the production verifier."""
    witness = (50352, 50608, 50864)  # all ordinary company road tiles
    _, readback = _route_readback(SEAL, witness=witness)
    receipt = verify_corridor_route(
        readback, prelaunch_digest=SEAL, expected_pairs=2, expected_path=witness
    )
    assert receipt["verification"] == "ROUTE_VERIFIED"
    assert receipt["connected_pairs"] == 2 and receipt["first_fail_index"] == -1


def test_route_witness_accepts_the_road_to_station_terminal_pair():
    """The full 30-tile D5 witness ends in a bay truck-stop tile reached from
    its front road; when the world is actually connected the same production
    route path accepts the terminal pair (the pickup head 45748 -> 45747 pair
    of the 28/29 accepted read is this exact shape in the live world)."""
    _, readback = _route_readback(SEAL)
    receipt = verify_corridor_route(
        readback, prelaunch_digest=SEAL, expected_pairs=len(WITNESS) - 1, expected_path=WITNESS
    )
    assert receipt["verification"] == "ROUTE_VERIFIED"
    assert receipt["expected_pairs"] == 29
    assert receipt["funds"] == FUNDS


def test_route_witness_refuses_the_failed_final_pair_of_the_consumed_attempt():
    """The recorded shape of the D5-CORRIDOR-EXTENSION-2 failure: 28/29
    connected with the lateral-truck-stop pair (50864 -> 50863) disconnected.
    A forged or incomplete terminal record can never turn that into success:
    the refusal is the connectivity rule, not the terminal metadata."""
    request, readback = _route_readback(
        SEAL, connected_pairs=28, first_fail=28, eligible=False
    )
    with pytest.raises(ValueError, match="route connectivity is incomplete"):
        verify_corridor_route(
            readback, prelaunch_digest=SEAL, expected_pairs=29, expected_path=WITNESS
        )


def test_route_witness_refuses_mutated_terminal_flags():
    """Stop-structure flags that contradict a genuine truck-stop terminal are
    refused at the production structure gate."""
    for overrides in (
        dict(delivery_stop=False),
        dict(delivery_truck=False),
        dict(delivery_sid=None),
        dict(pickup_stop=False),
        dict(pickup_truck=False),
        dict(pickup_sid=None),
        dict(depot_pin_ok=False),
    ):
        _, readback = _route_readback(SEAL, **overrides)
        with pytest.raises(ValueError, match="route stop/depot structure"):
            verify_corridor_route(
                readback, prelaunch_digest=SEAL, expected_pairs=29, expected_path=WITNESS
            )


def test_route_witness_refuses_witness_path_drift():
    _, readback = _route_readback(SEAL)
    with pytest.raises(ValueError, match="correlated route observation"):
        verify_corridor_route(
            readback, prelaunch_digest=SEAL, expected_pairs=29, expected_path=WITNESS[:-1] + (17,)
        )


def test_route_witness_refuses_a_mutating_route_read():
    """The route read is pure observation: any nonzero cost means it mutated
    the world and the witness is refused."""
    _, readback = _route_readback(SEAL, cost=1)
    with pytest.raises(ValueError, match="correlated route observation"):
        verify_corridor_route(
            readback, prelaunch_digest=SEAL, expected_pairs=29, expected_path=WITNESS
        )


def test_station_gate_refuses_forged_and_drifting_terminal_records():
    """The FAIL-CLOSED station gates behind the route read: station merge onto
    ids {0, 1}, a drive-through stop where the design pins a truck stop, and a
    stop not linked to its pinned front are each refused before any route
    success can be recorded."""
    schedule = e.extension_schedule()
    request = e._extension_request("station", "station-02", SEAL, 0, MAX_COST, schedule[2])
    merged = rb(
        request, status="BUILT", eligible=True, cost=OP_COSTS[2], funds=FUNDS,
        **site_fields(built=True, sid=0),
    )
    with pytest.raises(ValueError, match="station-merge defect"):
        e._station_gate(merged, "station-02")
    drive_through = rb(
        request, status="BUILT", eligible=True, cost=OP_COSTS[2], funds=FUNDS,
        **dict(site_fields(built=True), drive_through=True),
    )
    with pytest.raises(ValueError, match="drive-through stop refused"):
        e._station_gate(drive_through, "station-02")
    unlinked = rb(
        request, status="BUILT", eligible=True, cost=OP_COSTS[2], funds=FUNDS,
        **dict(site_fields(built=True), linked=False),
    )
    with pytest.raises(ValueError, match="not linked to its front"):
        e._station_gate(unlinked, "station-02")
