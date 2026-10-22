"""Adversarial regression tests for D2 clearing native proof.

These tests reproduce the confirmed failures from Codex re-review.
Run with: pytest tests/test_terrain_clearing_adversarial.py -v

No OpenTTD launch, no AdminPort connection and no claim consumption of the
sealed candidate occurs anywhere: Squirrel handlers run on the controlled VM,
replay gates run on fully sealed controlled attempt evidence, and the run()
rehearsal drives execute_attempt against a controlled seam backend whose
in-memory peer speaks the real X25519 AuthorizedKey handshake.
"""

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import struct
import tempfile
import unittest.mock as mock
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import monocypher
import pytest
from squirrel import SQVM
from test_secure_admin import NONCE, SERVER, STREAM_NONCE, Writer

from app.simulation.openttd.admin_crypto import AuthorizedKey, PacketCipher, derive_keys
from app.simulation.openttd.admin_protocol import (
    AdminClientPacketType,
    encode_admin_frame,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    decode_gamescript,
    encode_gamescript,
)
from app.simulation.openttd.proof import native as native_module
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.proof.harness import (
    PreparedProof,
    manifest,
    sha256,
    write_json,
)
from app.simulation.openttd.proof.operator_authorization import (
    AUTHORIZATION_FILE_NAME,
    ClearingAuthorizationError,
    authorization_payload,
    sign_authorization_record,
)
from app.simulation.openttd.proof.terrain_clearing import (
    MAX_CLEARING_COST,
    STAGED_GS_DIRECTORY,
    TARGET_TILE,
    ClearingNativeBackend,
    ClearingSecureSession,
    admit_pinned_target,
    execute_attempt,
    exit_status,
    pinned_target,
    prepare_candidate,
    verify_attempt,
)
from app.simulation.openttd.terrain_clearing import (
    ALLOWED_CLEARING_CLASSES,
    ClearingReadback,
    ClearingRequest,
    admit_clearing,
    verify_clearing,
)

TREE, CLEAR, FARM = 0x0009, 0x0001, 0x0011
SEAL_GOAL = "a" * 64
SAVE_GOAL = "b" * 64


# --- Evidence helpers -------------------------------------------------------


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


def synthetic_attempt(
    root: Path,
    mode: str,
    *,
    defect: str | None = None,
    result_returncode: int = 0,
    cleanup_returncode: int = 0,
):
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
    stderr_text = "dbg: [script:4] [20] [I] ROAD_PROOF_COMPANY_READY\n"
    if defect == "fatal-log":
        stderr_text += "dbg: [script:4] [F] The script died unexpectedly\n"
    (directory / "stderr.log").write_text(stderr_text)

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
        dispatch_state="NOT_DISPATCHED" if stopped else "CONFIRMED",
        returncode=result_returncode,
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
            returncode=cleanup_returncode,
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


def outbound_requests_of(directory: Path):
    """Parse every outbound GameScript frame into its ClearingRequest."""
    frames = json.loads((directory / "frames.json").read_text())
    parsed = []
    for i, (direction, frame_hex) in enumerate(frames):
        if direction != "outbound":
            continue
        payload = decode_gamescript(bytes.fromhex(frame_hex)[3:])
        parsed.append((i, ClearingRequest.model_validate_json(payload)))
    return parsed


def find_outbound_frame(frames, *, op: str, request_id: str) -> int:
    """Locate an outbound frame by its decoded payload, not by hex substrings."""
    for i, (direction, frame_hex) in enumerate(frames):
        if direction != "outbound":
            continue
        payload = decode_gamescript(bytes.fromhex(frame_hex)[3:])
        try:
            query = ClearingRequest.model_validate_json(payload)
        except Exception:
            continue
        if query.op == op and query.request_id == request_id:
            return i
    raise AssertionError(f"outbound {op} frame for {request_id!r} not found")


def find_inbound_frame(frames, *, op: str, request_id: str) -> int:
    """Locate an inbound gateway reply by its decoded payload."""
    for i, (direction, frame_hex) in enumerate(frames):
        if direction != "inbound":
            continue
        try:
            readback = ClearingReadback.model_validate_json(
                decode_gamescript(bytes.fromhex(frame_hex)[3:])
            )
        except Exception:
            continue
        if readback.op == op and readback.request_id == request_id:
            return i
    raise AssertionError(f"inbound {op} reply for {request_id!r} not found")


def rewrite_frames(directory: Path, frames):
    """Refresh frames.json and the artifact manifest after an adversarial edit."""
    (directory / "frames.json").write_text(json.dumps(frames))
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))


def remove_inbound_reply(directory: Path, *, op: str, request_id: str):
    """Drop exactly one retained inbound gateway reply identified by payload."""
    frames = json.loads((directory / "frames.json").read_text())
    kept = []
    removed = 0
    for entry in frames:
        direction, frame_hex = entry
        drop = False
        if direction == "inbound":
            try:
                readback = ClearingReadback.model_validate_json(
                    decode_gamescript(bytes.fromhex(frame_hex)[3:])
                )
            except Exception:
                readback = None
            if readback is not None and readback.op == op and readback.request_id == request_id:
                drop = True
        if drop:
            removed += 1
        else:
            kept.append(entry)
    assert removed == 1, f"expected exactly one inbound {op} reply, removed {removed}"
    rewrite_frames(directory, kept)


# ============================================================================
# Controlled Squirrel VM for the actual clearing execution path
# ============================================================================


def clearing_vm(*, companies=(0, 1), funds=100000):
    """Controlled clearing VM on the same mock pattern as test_terrain_clearing.vm_for.

    Unlike the frozen contract VM, this one resolves both companies 0 and 1 so
    an admission-identity refusal at the mutation boundary is distinguishable
    from a company-resolution refusal.
    """
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::dims <- [256, 256]; ::tiles <- {{}}; ::funds <- {funds};
        ::companies <- [{", ".join(str(c) for c in companies)}];
        ::mode_ok <- true; ::reject <- false;
        ::quote_cost <- 20; ::exec_cost <- 20;
        ::account <- 0; ::tests <- {{}}; ::real_calls <- 0; ::test_calls <- 0;
        class GSCompany {{
            static COMPANY_INVALID = -1;
            static function ResolveCompanyID(c) {{
                foreach (v in ::companies) if (v == c) return v;
                return GSCompany.COMPANY_INVALID;
            }}
            static function GetBankBalance(c) {{ return ::funds; }}
        }}
        class GSCompanyMode {{
            constructor(c) {{
                foreach (v in ::companies) if (v == c) return;
                throw "company";
            }}
            static function IsValid() {{ return ::mode_ok; }}
        }}
        class GSAccounting {{
            constructor() {{ ::account++; }}
            function GetCosts() {{ return (::account in ::tests) ? ::quote_cost : ::exec_cost; }}
        }}
        class GSTestMode {{ constructor() {{ ::tests[::account] <- true; }} }}
        class GSMap {{
            static function GetMapSizeX() {{ return ::dims[0]; }}
            static function GetMapSizeY() {{ return ::dims[1]; }}
            static function IsValidTile(t) {{ return t in ::tiles; }}
            static function GetTileX(t) {{ return t % ::dims[0]; }}
            static function GetTileY(t) {{ return t / ::dims[0]; }}
        }}
        class GSTile {{
            static TRANSPORT_ROAD=0; static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2; static TRANSPORT_AIR=3;
            static function b(t, n) {{ return (::tiles[t].flags & (1 << n)) != 0; }}
            static function IsBuildable(t) {{ return GSTile.b(t, 0); }}
            static function IsWaterTile(t) {{ return GSTile.b(t, 1); }}
            static function IsCoastTile(t) {{ return GSTile.b(t, 2); }}
            static function HasTreeOnTile(t) {{ return GSTile.b(t, 3); }}
            static function IsFarmTile(t) {{ return GSTile.b(t, 4); }}
            static function IsRockTile(t) {{ return GSTile.b(t, 5); }}
            static function IsRoughTile(t) {{ return GSTile.b(t, 6); }}
            static function IsHouseTile(t) {{ return GSTile.b(t, 13); }}
            static function IsStationTile(t) {{ return GSTile.b(t, 14); }}
            static function HasTransportType(t, kind) {{
                return (kind == 0 && GSTile.b(t, 7)) || (kind == 1 && GSTile.b(t, 10)) ||
                       (kind == 2 && GSTile.b(t, 11));
            }}
            static function GetOwner(t) {{ return ::tiles[t].owner; }}
            static function GetMinHeight(t) {{ return ::tiles[t].elevation; }}
            static function GetSlope(t) {{ return ::tiles[t].slope; }}
            static function DemolishTile(t) {{
                if (::account in ::tests) {{ ::test_calls++; return true; }}
                ::real_calls++;
                if (::reject) return false;
                local entry = ::tiles[t];
                entry.flags = entry.flags & ~(1<<3) & ~(1<<4) & ~(1<<5) & ~(1<<6) | 1;
                entry.slope = entry.slope;
                ::funds -= ::exec_cost;
                return true;
            }}
        }}
        class GSRoad {{
            static function IsRoadTile(t) {{ return GSTile.b(t, 7); }}
            static function HasRoadType(t, i) {{ return i == 0 && GSTile.b(t, 9); }}
        }}
        class GSAirport {{
            static function IsAirportTile(t) {{ return GSTile.b(t, 12); }}
        }}
        class GSIndustry {{
            static function GetIndustryID(t) {{ return ::tiles[t].industry; }}
            static function IsValidIndustry(i) {{ return i != null && i >= 0; }}
        }}
    """)
    vm.execute((Path("app/simulation/openttd/terrain_clearing_package") / "main.nut").read_text())
    vm.execute("::bridge <- NetworkFreightProof();")
    return vm


def seed_tile(vm, tile, flags, *, elevation=2, slope=0, owner=-1, industry=None):
    vm.execute(
        f"::tiles[{tile}] <- {{flags={flags}, owner={owner}, elevation={elevation}, "
        f"slope={slope}, industry={json.dumps(industry)}}}"
    )


def clearing_handle(vm, q):
    """Drive one query through the real Handle entry point; return the reply."""
    before = len(list(vm.get_roottable()["replies"]))
    vm.execute("::bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = list(vm.get_roottable()["replies"])
    if len(replies) == before:
        raise AssertionError("handler dropped the request without a correlated reply")
    response = replies[len(replies) - 1]
    data = {}
    for key in response.keys():
        k, v = str(key), response[key]
        data[k] = (
            str(v)
            if k in ("op", "request_id", "plan", "status")
            else (bool(v) if k == "eligible" else (None if v is None else int(v)))
        )
    return data


def vm_probe(vm, tile):
    """Snapshot the execution-path state that only the Squirrel side can read."""
    vm.execute(f"""
        ::admission_probe <- {{ count=0, missing="", flags=null, industry=null,
            owner=null, elevation=null, slope=null, classification=null,
            cost=null, funds=null, plan=null, company=null, latched=false }};
        local entry = (::bridge.attempted != null && {tile} in ::bridge.attempted);
        ::admission_probe.latched = entry;
        if (::bridge.admitted != null && {tile} in ::bridge.admitted) {{
            local bound = ::bridge.admitted[{tile}];
            foreach (field in ["flags", "industry", "owner", "elevation", "slope",
                               "classification", "cost", "funds", "plan", "company"]) {{
                if (!(field in bound)) {{
                    ::admission_probe.count++;
                    ::admission_probe.missing = ::admission_probe.missing + field + ":";
                }} else {{
                    ::admission_probe[field] = bound[field];
                }}
            }}
        }} else {{
            ::admission_probe.count++;
            ::admission_probe.missing = ::admission_probe.missing + "entry:";
        }}
    """)
    return dict(vm.get_roottable()["admission_probe"])


# ============================================================================
# A. Admission identity at the actual execution path (Task 2)
# ============================================================================


def _admitted_two_company_vm(vm):
    seed_tile(vm, TARGET_TILE, TREE)
    inspect_query = ClearingRequest(
        op="inspect",
        request_id="inspect-1",
        plan=SEAL_GOAL,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    assert clearing_handle(vm, inspect_query)["status"] == "READY"
    return inspect_query


def test_stale_company_mismatch_refused():
    """A clear from another company must never reuse a company-0 admission.

    Both companies resolve and enter company mode on this controlled VM, so the
    refusal below can only come from the admission company identity comparison
    at the mutation boundary, never from company resolution.
    """
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    intent = admit_under_pin(pin_readback(pin_request()))
    clear_query = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=intent.prelaunch_digest,
        company=1,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    reply = clearing_handle(vm, clear_query)
    root = vm.get_roottable()
    assert reply["status"] == "STALE_ADMISSION"
    assert root["real_calls"] == 0, "a mismatched admission must never demolish"
    probe = vm_probe(vm, TARGET_TILE)
    assert probe["latched"] is False, "a refused clear must not latch the attempt"

    # Positive control: the same request from company 0 executes demolition.
    control = clearing_vm()
    _admitted_two_company_vm(control)
    control_query = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=intent.prelaunch_digest,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    control_reply = clearing_handle(control, control_query)
    assert control_reply["status"] == "CLEARED"
    assert control.get_roottable()["real_calls"] == 1


def test_stale_plan_mismatch_refused():
    """A clear dispatched under an unrelated plan must never verify.

    The frozen wire contract sends the clear with the intent digest derived
    from THIS admission's inspect readback (inspect carries the prelaunch
    seal). The handler therefore cannot compare plans in-script; the plan
    identity gate is the Python exchange policy plus the replay correlation
    gate, which is the actual execution path for every dispatched clear.
    """
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        # Retarget the dispatched clear to an unrelated but well-formed plan,
        # consistently everywhere: request file, response file and both frames.
        frames = json.loads((directory / "frames.json").read_text())
        index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        query = ClearingRequest.model_validate_json(
            decode_gamescript(bytes.fromhex(frames[index][1])[3:])
        )
        assert query.plan != "f" * 64
        tampered = query.model_copy(update={"plan": "f" * 64})
        frames[index] = ("outbound", encode_gamescript(tampered.to_bytes()).hex())
        # Rewrite the dispatched clear consistently: request file, response
        # file and both retained frames now carry the unrelated plan, so the
        # multiset(frame, file) integrity holds and only the plan chain broke.
        raw = tampered.to_bytes()
        (directory / (query.request_id + "-request.json")).write_bytes(raw)
        response_path = directory / (query.request_id + "-response.json")
        readback = ClearingReadback.model_validate_json(response_path.read_bytes())
        tampered_reply = readback.model_copy(update={"plan": "f" * 64})
        reply_raw = tampered_reply.model_dump_json().encode()
        response_path.write_bytes(reply_raw)
        for i, (direction, frame_hex) in enumerate(frames):
            if direction != "inbound":
                continue
            candidate = ClearingReadback.model_validate_json(
                decode_gamescript(bytes.fromhex(frame_hex)[3:])
            )
            if candidate.request_id == query.request_id and candidate.op == query.op:
                frames[i] = (
                    "inbound",
                    encode_admin_frame(SERVER_GAMESCRIPT, reply_raw + b"\0").hex(),
                )
        rewrite_frames(directory, frames)

        # The frame and file multisets still agree; only the plan chain broke.
        with pytest.raises(
            ValueError, match="clearing execution evidence does not correlate to its intent"
        ):
            verify_attempt(directory)


def test_admission_flags_drift_refused():
    """Flag changes between inspect and clear must prevent demolition."""
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    intent = admit_under_pin(pin_readback(pin_request()))
    # A second tree class keeps the tile clearing-eligible; only the observed
    # predicate identity drifts (trees removed, trees and farm both present).
    vm.execute(f"::tiles[{TARGET_TILE}].flags = 0x{0x0019:x};")  # trees + rough
    clear_query = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=intent.prelaunch_digest,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    reply = clearing_handle(vm, clear_query)
    root = vm.get_roottable()
    assert reply["status"] == "STALE_ADMISSION"
    assert root["real_calls"] == 0, "drifted admission facts must never demolish"


def test_admission_geometry_drift_refused():
    """Geometry changes between inspect and clear must prevent demolition."""
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    intent = admit_under_pin(pin_readback(pin_request()))
    vm.execute(f"::tiles[{TARGET_TILE}].slope = 3;")
    clear_query = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=intent.prelaunch_digest,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    reply = clearing_handle(vm, clear_query)
    root = vm.get_roottable()
    assert reply["status"] == "STALE_ADMISSION"
    assert root["real_calls"] == 0, "drifted geometry must never demolish"


def test_stale_admission_status_is_valid_rejection():
    """STALE_ADMISSION must parse as a readback status and never admit success."""
    response = {
        "protocol": 2,
        "op": "clear",
        "request_id": "clear-1",
        "plan": "a" * 64,
        "company": 0,
        "tile": TARGET_TILE,
        "status": "STALE_ADMISSION",
        "flags": 9,
        "industry": None,
        "owner": -1,
        "elevation": 2,
        "slope": 0,
        "eligible": True,
        "funds": 100000,
        "cost": 20,
    }
    readback = ClearingReadback.model_validate(response)
    assert readback.status == "STALE_ADMISSION"
    assert readback.status not in ALLOWED_CLEARING_CLASSES
    # A gateway that refuses execution may never be read as a READY admission.
    with pytest.raises(ValueError, match="native allowed clearing class"):
        admit_clearing(
            readback,
            prelaunch_digest=SEAL_GOAL,
            source_save_digest=SAVE_GOAL,
            max_cost=MAX_CLEARING_COST,
        )


# ============================================================================
# B. Lost Clear Response
# ============================================================================


def test_lost_clear_response_dispatch_state():
    """When the clear response is lost, verification must stay unresolved."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        # Remove the clear response file AND its gateway reply frame: the full
        # transport-loss shape (frame identification is by decoded payload).
        (directory / "clear-1-response.json").unlink()
        remove_inbound_reply(directory, op="clear", request_id="clear-1")
        result = verify_attempt(directory)
        assert result["verification"] != "STOPPED_WITHOUT_MUTATION"
        assert result["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


def test_diagnostic_save_attempted_on_lost_response():
    """A lost response never erases the recorded dispatch uncertainty."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        result = json.loads((directory / "result.json").read_text())
        result["dispatch_state"] = "DISPATCHED_UNKNOWN"
        (directory / "result.json").write_text(json.dumps(result))
        (directory / "clear-1-response.json").unlink()
        remove_inbound_reply(directory, op="clear", request_id="clear-1")
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        # The retained result must still say the command was dispatched with an
        # unknown outcome, and the replay must resolve to preserved evidence.
        retained = json.loads((directory / "result.json").read_text())
        assert retained["dispatch_state"] == "DISPATCHED_UNKNOWN"
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


def test_missing_clear_frame_classified_as_unresolved():
    """A dispatched clear without its outbound frame is never a verdict."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        frames = [entry for i, entry in enumerate(frames) if i != index]
        rewrite_frames(directory, frames)
        result = verify_attempt(directory)
        assert result["verification"] != "RECEIPT_VERIFIED"
        assert result["verification"] != "STOPPED_WITHOUT_MUTATION"
        assert result["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


# ============================================================================
# D. Process Crash
# ============================================================================


def test_process_crash_prevents_verified():
    """Abnormal process exit (e.g., return code 139) must prevent RECEIPT_VERIFIED."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        result = json.loads((directory / "result.json").read_text())
        result["process_crash"] = True
        result["returncode"] = 139
        result["process_exited_abnormally"] = True
        (directory / "result.json").write_text(json.dumps(result))
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        verdict = verify_attempt(directory)
        assert verdict["verification"] != "RECEIPT_VERIFIED"
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"


# ============================================================================
# E. Partial Replay
# ============================================================================


def test_partial_replay_dispatched_unknown_not_stopped():
    """DISPATCHED_UNKNOWN with a lost clear response must never be a stop."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        result = json.loads((directory / "result.json").read_text())
        result["dispatch_state"] = "DISPATCHED_UNKNOWN"
        result["status"] = "FAILED"
        (directory / "result.json").write_text(json.dumps(result))
        (directory / "clear-1-response.json").unlink()
        remove_inbound_reply(directory, op="clear", request_id="clear-1")
        verdict = verify_attempt(directory)
        assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"
        assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


def test_no_mutation_downgrade_from_unknown():
    """DISPATCHED_UNKNOWN evidence can never be downgraded to no mutation."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        result = json.loads((directory / "result.json").read_text())
        result["dispatch_state"] = "DISPATCHED_UNKNOWN"
        (directory / "result.json").write_text(json.dumps(result))
        (directory / "clear-1-response.json").unlink()
        remove_inbound_reply(directory, op="clear", request_id="clear-1")
        verdict = verify_attempt(directory)
        assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"
        assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


# ============================================================================
# F. Outbound Frame Integrity and Causal Order (Task 4)
# ============================================================================


def test_orphan_outbound_request_rejected():
    """Orphan outbound request (no request file) should be rejected."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        fake_clear = ClearingRequest(
            op="clear",
            request_id="clear-orphan",
            plan="f" * 64,
            company=0,
            tile=TARGET_TILE,
            max_cost=MAX_CLEARING_COST,
        )
        frames.append(("outbound", encode_gamescript(fake_clear.to_bytes()).hex()))
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="outbound frame count exceeds request file count"):
            verify_attempt(directory)


def test_additional_outbound_clear_rejected():
    """A second clearing command in the retained stream is rejected."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        fake_clear = ClearingRequest(
            op="clear",
            request_id="clear-2",
            plan="f" * 64,
            company=0,
            tile=TARGET_TILE,
            max_cost=MAX_CLEARING_COST,
        )
        frames.append(("outbound", encode_gamescript(fake_clear.to_bytes()).hex()))
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="outbound frame count exceeds request file count"):
            verify_attempt(directory)


def test_duplicate_clear_with_files_rejected():
    """Duplicate clear backed by request files must hit the one-clear gate."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        clear_request_file = directory / "clear-1-request.json"
        clear_response_file = directory / "clear-1-response.json"
        frames = json.loads((directory / "frames.json").read_text())
        duplicate = ClearingRequest.model_validate_json(clear_request_file.read_bytes())
        duplicate = duplicate.model_copy(update={"request_id": "clear-2"})
        clear2_response = ClearingReadback.model_validate_json(clear_response_file.read_bytes())
        clear2_response = clear2_response.model_copy(update={"request_id": "clear-2"})
        raw = duplicate.to_bytes()
        reply_raw = clear2_response.model_dump_json().encode()
        (directory / "clear-2-request.json").write_bytes(raw)
        (directory / "clear-2-response.json").write_bytes(reply_raw)
        frames.append(("outbound", encode_gamescript(raw).hex()))
        frames.append(("inbound", encode_admin_frame(SERVER_GAMESCRIPT, reply_raw + b"\0").hex()))
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="more than one clearing command in outbound frames"):
            verify_attempt(directory)


def test_same_count_mismatched_payload_rejected():
    """Same request count but a mismatched outbound payload is rejected."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        # Modify the clear outbound frame so its payload no longer equals its
        # retained request file (identification by decoded payload, not a hex
        # substring that lives deep in the JSON body).
        frames = json.loads((directory / "frames.json").read_text())
        index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        query = ClearingRequest.model_validate_json(
            decode_gamescript(bytes.fromhex(frames[index][1])[3:])
        )
        tampered = query.model_copy(update={"plan": "f" * 64})
        frames[index] = ("outbound", encode_gamescript(tampered.to_bytes()).hex())
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError, match="outbound frame payloads do not match request file payloads"
        ):
            verify_attempt(directory)


def test_swapped_request_content_rejected():
    """Swapped request content (inspect/clear) should be rejected."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        inspect_req = (directory / "inspect-1-request.json").read_bytes()
        clear_req = (directory / "clear-1-request.json").read_bytes()
        (directory / "inspect-1-request.json").write_bytes(clear_req)
        (directory / "clear-1-request.json").write_bytes(inspect_req)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        # A name-agnostic multiset comparison cannot see this swap; the
        # retained file identity gate binds each file to its request id.
        with pytest.raises(
            ValueError, match="retained request file identity does not match its payload"
        ):
            verify_attempt(directory)


def test_read_before_clear_rejected():
    """The independent post-mutation read must come after the clear command."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        clear_index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        frames[clear_index], frames[clear_index + 2] = frames[clear_index + 2], frames[clear_index]
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError, match="independent read precedes the clearing command it observes"
        ):
            verify_attempt(directory)


def test_missing_response_for_existing_outbound_rejected():
    """A retained gateway reply without its durable file is tampering, not loss."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        # Keep the inbound frame; delete only the durable response file. The
        # frame proves the gateway answered; a missing file contradicts it.
        (directory / "clear-1-response.json").unlink()
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        with pytest.raises(
            ValueError, match="retained gateway response lacks its durable response file"
        ):
            verify_attempt(directory)


def test_max_one_real_clear_enforced():
    """Maximum one real clear enforced against the authoritative stream."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        fake_clear = ClearingRequest(
            op="clear",
            request_id="clear-2",
            plan="f" * 64,
            company=0,
            tile=TARGET_TILE,
            max_cost=MAX_CLEARING_COST,
        )
        frames.append(("outbound", encode_gamescript(fake_clear.to_bytes()).hex()))
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="outbound frame count exceeds request file count"):
            verify_attempt(directory)


def test_eight_request_budget_enforced():
    """The sealed request budget is enforced against the outbound stream."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        seal = sha256(directory / "PRELAUNCH.json")
        for i in range(8):
            fake_req = ClearingRequest(
                op="read",
                request_id=f"read-extra-{i}",
                plan=seal,
                company=0,
                tile=TARGET_TILE,
                max_cost=MAX_CLEARING_COST,
            )
            frames.append(("outbound", encode_gamescript(fake_req.to_bytes()).hex()))
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="clearing request budget exceeded"):
            verify_attempt(directory)


def test_chronological_causality_enforced():
    """Chronological causality: clear may never precede its inspect."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        inspect_index = find_outbound_frame(frames, op="inspect", request_id="inspect-1")
        clear_index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        assert inspect_index < clear_index
        frames[inspect_index], frames[clear_index] = frames[clear_index], frames[inspect_index]
        rewrite_frames(directory, frames)
        with pytest.raises(ValueError, match="clear request precedes its inspect"):
            verify_attempt(directory)


# --- complete chronology (BLOCKER 2) ----------------------------------------


def test_correct_chronology_accepted():
    """The complete inspect→clear→independent-read chain in real order verifies.

    Every reordered pair below is a tamper; this untouched stream is the
    only accepted shape: inspect request, inspect response, clear request,
    clear response, independent read request, independent read response.
    """
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "RECEIPT_VERIFIED"
        assert verdict["receipt"]["verification"] == "NATIVE_STATE_CHANGED"


def test_read_response_moved_before_clear_rejected():
    """The independent post-clear RESPONSE moved before the clear is tampering.

    Counterexample shape: payloads, files and counts are all preserved; only
    the inbound read-2 reply is relocated ahead of the clearing command. The
    replay must reject it, never return RECEIPT_VERIFIED, and never accept
    sorted payload equality in place of chronology.
    """
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        moved = frames.pop(find_inbound_frame(frames, op="read", request_id="read-2"))
        clear_index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        frames.insert(clear_index, moved)
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError,
            match="a retained response precedes its own request in the frame stream",
        ):
            verify_attempt(directory)


def test_read_pair_moved_before_clear_rejected():
    """The independent read request/response pair moved before the clear fails."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        reply = frames.pop(find_inbound_frame(frames, op="read", request_id="read-2"))
        query = frames.pop(find_outbound_frame(frames, op="read", request_id="read-2"))
        clear_index = find_outbound_frame(frames, op="clear", request_id="clear-1")
        frames[clear_index:clear_index] = [query, reply]
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError,
            match="independent read precedes the clearing command it observes",
        ):
            verify_attempt(directory)


def test_read_pair_moved_before_inspect_rejected():
    """A whole read exchange moved ahead of the inspect breaks the chain.

    The attempt-level read-position gate allows reads before the inspect
    (pre-mutation observation); the executed verifier's full-chain order test
    is what rejects an independent read whose response provably predates the
    mutation it exists to confirm.
    """
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        reply = frames.pop(find_inbound_frame(frames, op="read", request_id="read-2"))
        query = frames.pop(find_outbound_frame(frames, op="read", request_id="read-2"))
        inspect_index = find_outbound_frame(frames, op="inspect", request_id="inspect-1")
        frames[inspect_index:inspect_index] = [query, reply]
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError,
            match="verified receipt lacks its chronological exchange chain",
        ):
            verify_attempt(directory)


def test_clear_request_before_inspect_response_rejected():
    """A clear request ahead of the inspect RESPONSE cannot latch an admission.

    The clear may only be dispatched after its admission was latched by the
    inspect response; a clear inbound-ahead frame order is impossible for the
    serial owned session that owns each stream position.
    """
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        command = frames.pop(find_outbound_frame(frames, op="clear", request_id="clear-1"))
        inspect_reply_index = find_inbound_frame(frames, op="inspect", request_id="inspect-1")
        frames.insert(inspect_reply_index, command)
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError,
            match="clear command precedes the inspect response that latches its admission",
        ):
            verify_attempt(directory)


def test_read_request_inside_clear_response_window_rejected():
    """A read sent between the clear command and its response is impossible."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        frames = json.loads((directory / "frames.json").read_text())
        query = frames.pop(find_outbound_frame(frames, op="read", request_id="read-2"))
        clear_reply_index = find_inbound_frame(frames, op="clear", request_id="clear-1")
        frames.insert(clear_reply_index, query)
        rewrite_frames(directory, frames)
        with pytest.raises(
            ValueError,
            match="a read request arrives between the clearing command and its response",
        ):
            verify_attempt(directory)


# ============================================================================
# Admission identity binding (Squirrel side)
# ============================================================================


def test_game_script_entrypoint_networkfreightproof():
    """Verify NetworkFreightProof is properly defined after TerrainClearingProof."""
    main_text = Path("app/simulation/openttd/terrain_clearing_package/main.nut").read_text()
    terrain_idx = main_text.index("class TerrainClearingProof")
    network_idx = main_text.index("class NetworkFreightProof")
    assert network_idx > terrain_idx, (
        "NetworkFreightProof must be defined after TerrainClearingProof"
    )
    assert "extends TerrainClearingProof" in main_text[network_idx : network_idx + 100]


def test_admission_binds_all_identities():
    """Every admission identity field must be bound at the inspection boundary."""
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    probe = vm_probe(vm, TARGET_TILE)
    assert probe["missing"] == "", f"admission is missing identity fields: {probe['missing']}"
    assert probe["flags"] == TREE
    assert probe["owner"] == -1
    assert probe["elevation"] == 2 and probe["slope"] == 0
    assert probe["classification"] == "TREES"
    assert probe["cost"] == 20 and probe["funds"] == 100000
    assert probe["plan"] == SEAL_GOAL
    assert probe["company"] == 0, "admission must bind the accepting company"
    probe = vm_probe(vm, TARGET_TILE)
    assert probe["latched"] is False, "inspection alone must not latch an attempt"


# ============================================================================
# G2. Plan identity enforced by the GameScript mutation boundary itself
# ============================================================================


def test_inspect_plan_a_clear_plan_a_allowed():
    """The executing clear presents the admission plan it latched under (v2).

    Positive control: with the plan identity equal to the inspect's plan the
    mutation boundary accepts the executing clear (adopted wire contract v2:
    a clear request is bound to the admission plan, not to an uncorrelated
    digest).
    """
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    intent = admit_under_pin(pin_readback(pin_request()))
    assert intent.prelaunch_digest == SEAL_GOAL
    clear_query = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=SEAL_GOAL,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    reply = clearing_handle(vm, clear_query)
    assert reply["status"] == "CLEARED"
    assert vm.get_roottable()["real_calls"] == 1


def test_plan_mismatch_refused_before_demolition():
    """A clear under an unrelated plan identity must be refused in-script.

    The counterexample: inspect plan A latches the admission, a clear arrives
    under plan B ("f"*64) and the mutation boundary must return
    STALE_ADMISSION with zero GSTile.DemolishTile calls — the demolition must
    never be deferred to a retrospective replay check.
    """
    vm = clearing_vm()
    _admitted_two_company_vm(vm)
    attack = ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan="f" * 64,
        company=0,
        tile=TARGET_TILE,
        max_cost=MAX_CLEARING_COST,
    )
    reply = clearing_handle(vm, attack)
    assert reply["status"] == "STALE_ADMISSION"
    root = vm.get_roottable()
    assert root["real_calls"] == 0, "a mismatched plan must never demolish"
    probe = vm_probe(vm, TARGET_TILE)
    assert probe["latched"] is False, "a refused clear must not latch the attempt"


# ============================================================================
# H. Failure injection through run() (Task 5)
# ============================================================================


def controlled_handshake(key, welcome):
    """Adapted from test_secure_admin.server_handshake for the candidate key."""
    keys = derive_keys(key, SERVER.public_key)
    cipher = PacketCipher(keys.server_to_client, STREAM_NONCE)
    protocol = encode_admin_frame(103, b"\x03\x01" + struct.pack("<HH", 9, 64) + b"\0")
    payload = (
        b"proof\x00"
        + welcome["revision"].encode()
        + b"\0\x01\0"
        + struct.pack(
            "<IBIHH",
            welcome["seed"],
            welcome["landscape"],
            welcome["start_day"],
            welcome["width"],
            welcome["height"],
        )
    )
    wire = (
        encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE)
        + encode_admin_frame(129, STREAM_NONCE)
        + cipher.encrypt(protocol)
        + cipher.encrypt(encode_admin_frame(104, payload))
    )
    return wire, cipher


class ControlledClearingPeer(Writer):
    """Controlled clearing gateway speaking the real encrypted Admin protocol.

    In-memory peer in the shape of test_secure_admin.ReferencePeer: it performs
    the exact X25519 AuthorizedKey handshake and answers the ceremony's
    subscription barrier and clearing exchanges. No host TCP socket is bound;
    the failure modes are selected per case.
    """

    def __init__(self, reader, *, key, welcome, case="ok", on_exchange=None):
        super().__init__()
        self.reader = reader
        self.authorized = key.public_key
        self._key = key
        self._in_cipher = PacketCipher(
            derive_keys(key, SERVER.public_key).client_to_server, STREAM_NONCE
        )
        self.authenticated = False
        self.welcome = welcome
        self.case = case
        self.on_exchange = on_exchange or (lambda query: None)
        self.exchanges = []

    def write(self, frame):
        if not self.authenticated:
            if frame[2] == 9:
                self.reader.feed_data(encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE))
                return
            if frame[2] == 10:
                payload = frame[3:]
                shared = monocypher.x25519(bytes(range(32, 64)), payload[:32])
                keys = hashlib.blake2b(
                    shared + SERVER.public_key + payload[:32], digest_size=64
                ).digest()
                message = monocypher.unlock(
                    keys[:32], NONCE, payload[32:48], payload[48:], payload[:32]
                )
                if message is None or payload[:32] != self.authorized:
                    self.reader.feed_data(encode_admin_frame(102, b"\x01"))
                    return
                self.authenticated = True
                wire, self._out_cipher = controlled_handshake(self._key, self.welcome)
                self.reader.feed_data(wire[60:])
                return
            raise AssertionError(f"unexpected pre-authentication frame kind {frame[2]}")
        plain = self._in_cipher.decrypt(frame)
        kind = plain[2]
        if kind == AdminClientPacketType.PING:
            token = struct.unpack("<I", plain[3:7])[0]
            self.reader.feed_data(
                self._out_cipher.encrypt(encode_admin_frame(126, struct.pack("<I", token)))
            )
        elif kind == ADMIN_GAMESCRIPT:
            query = ClearingRequest.model_validate_json(decode_gamescript(plain[3:]))
            self.exchanges.append(query)
            self.on_exchange(query)
            response = self._response_payload(query)
            if response is None:
                self.reader.feed_eof()
                return
            self.reader.feed_data(
                self._out_cipher.encrypt(encode_admin_frame(SERVER_GAMESCRIPT, response + b"\0"))
            )
        elif kind in (AdminClientPacketType.UPDATE_FREQUENCY, AdminClientPacketType.QUIT):
            pass
        else:
            raise AssertionError(f"unexpected authenticated frame kind {kind}")

    def _response_payload(self, query) -> bytes | None:
        if self.case == "crash-after-clear" and query.request_id == "read-2":
            # The runtime dies right after the clear response: the stream ends
            # before the independent read can be served (partial evidence).
            return None
        if query.op == "inspect":
            return pin_readback(query).model_dump_json().encode()
        if query.op == "read":
            value = CLEAR
            funds = 99980
            if self.case == "receipt-fail" and query.request_id == "read-2":
                value = TREE
                funds = 100000
            return (
                pin_readback(query, op="read", status="READ", flags=value, funds=funds)
                .model_dump_json()
                .encode()
            )
        if self.case == "malformed-clear":
            return b'{"broken"'
        if self.case == "lost-clear":
            return None
        return (
            pin_readback(query, op="clear", status="CLEARED", flags=CLEAR, funds=99980, cost=20)
            .model_dump_json()
            .encode()
        )


class _ConsoleSink:
    """Controlled native console: reacts synchronously to owned save commands."""

    def __init__(self, backend):
        self._backend = backend
        self.commands = []

    def write(self, data: bytes) -> None:
        for line in data.decode(errors="replace").splitlines():
            self.commands.append(line)
            if not line.startswith("save ") or not line.endswith('"'):
                continue
            stem = line[len("save ") :].strip()[1:-1]
            target = Path(stem + ".sav")
            if self._backend.save_fail and "after-diagnostic" in stem:
                raise ValueError("controlled native save command failure")
            if target.exists() or target.is_symlink():
                raise ValueError("controlled save path already existed")
            target.write_bytes(b"controlled native save\n" + str(len(self.commands)).encode())
            marker = "Map successfully saved to '" + str(target) + "'."
            with self._backend._stdout_log.open("a") as stream:
                stream.write(marker + "\n")

    def flush(self) -> None:
        pass


# --- Synthetic operator authorization (test-only issuance) ------------------
#
# The production trust anchor is the operator's seeded LOCAL DEVELOPMENT
# PROOF key (never re-pinned here); these synthetic
# RFC 8032 Ed25519 keys exist only inside isolated test environments and
# never on any real candidate. Issuance here mirrors exactly what the
# off-machine operator tooling does: sign the canonical candidate-bound
# payload, write the record. The identity below is literally the RFC 8032
# §7.1 TEST 1 vector, so every synthetic authorization also cross-checks the
# production implementation against a published interoperable reference.

_TEST_OPERATOR_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
_TEST_OPERATOR_PUBLIC = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
_FORGED_OPERATOR_SEED = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
)
_FORGED_OPERATOR_PUBLIC = bytes.fromhex(
    "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
)
# The production anchor, captured before any session patching: the runner
# never swaps the seeded operator key, and the identity check below refuses
# an unseeded or malformed anchor for every test.
_PROD_ANCHOR = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
assert _PROD_ANCHOR is not None
operator_authorization.operator_key_identity(_PROD_ANCHOR)


@contextlib.contextmanager
def synthetic_operator_anchor():
    """Patch the pinned trust anchor with the synthetic TEST operator key."""
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _TEST_OPERATOR_PUBLIC.hex()
    try:
        yield
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved


def issue_test_authorization(prepared, *, mutate=None, private_hex=None):
    """Sign the candidate-bound payload with a synthetic operator key.

    mutate() may distort the payload BEFORE signing (forge shapes); the
    record is then written into the temporary candidate directory.
    """
    directory = prepared.directory
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    payload = authorization_payload(metadata, seal)
    if mutate is not None:
        payload = mutate(payload)
    secret = _TEST_OPERATOR_SEED if private_hex is None else bytes.fromhex(private_hex)
    record = sign_authorization_record(payload, secret.hex())
    operator_authorization.write_authorization_record(directory, record)
    return record


def _controlled_backend(prepared, **kwargs):
    return ControlledClearingBackend(
        welcome=json.loads((prepared.directory / "PRELAUNCH.json").read_text())["world"][
            "expected_welcome"
        ],
        **kwargs,
    )


class ControlledClearingBackend:
    """Controlled seam backend for the D2 clearing ceremony rehearsal.

    Mirrors ControlledIndustryBackend and ControlledCaptureBackend: the
    ceremony under test is untouched. No OpenTTD binary exists and no host
    port is bound; the real kernel-readiness gate belongs to the production
    backend and its semantics are covered by the endpoints tests.
    """

    kind = "CONTROLLED"

    def __init__(self, *, welcome, case="ok", save_fail=False, process_returncode=0):
        self.welcome = welcome
        self.case = case
        self.save_fail = save_fail
        self.process_returncode = process_returncode
        self.session = None
        self.process = None
        self.peer = None
        self.proof = None

    def preflight(self, prepared) -> None:
        pass

    async def launch(self, prepared, *, authorization=None) -> dict:
        self.proof = prepared
        logs = prepared.spec.workspace.logs
        logs.mkdir(parents=True, exist_ok=True)
        self._stdout_log = logs / "stdout.log"
        self._stderr_log = logs / "stderr.log"
        self._stdout_log.write_text("dbg: [script:4] [18] [I] TERRAIN_CLEARING_READY\n")
        self._stderr_log.write_text("dbg: [script:4] [20] [I] ROAD_PROOF_COMPANY_READY\n")
        self.process = SimpleNamespace(
            pid=-1,
            returncode=None,
            stdin=_ConsoleSink(self),
            stdout=BytesIO(),
            stderr=BytesIO(),
            poll=lambda: None,
            wait=lambda timeout=None: self.process_returncode,
        )
        return {"pid": -1, "argv": ["/controlled/clearing"], "cwd": str(prepared.directory)}

    def health(self) -> None:
        pass

    async def connect(self, prepared, *, frame_observer):
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        reader = asyncio.StreamReader()
        self.peer = ControlledClearingPeer(
            reader, key=key, welcome=self.welcome, case=self.case, on_exchange=self._on_exchange
        )
        session = ClearingSecureSession(reader, self.peer, key=key, frame_observer=frame_observer)
        self.session = session
        return session

    def _on_exchange(self, query) -> None:
        if query.op == "clear" and self.case == "fatal-after-clear":
            with self._stderr_log.open("a") as stream:
                stream.write("dbg: [script:4] [F] The script died unexpectedly\n")

    async def cleanup(self, prepared) -> dict:
        if self.session is not None:
            await self.session.close(quit=True)
        if self.process is not None:
            self.process.returncode = self.process_returncode
        prepared.key_path.unlink(missing_ok=True)
        return dict(
            pid=-1,
            graceful_attempted=True,
            quit_command="quit",
            returncode=self.process_returncode,
            reaped=True,
            remaining_processes=[],
            events=[],
            cleanup_error=[],
        )


def run_rehearsal(tmp_path, *, case="ok", **backend_kwargs):
    """Rehearse execute_attempt against the controlled seam on a real candidate.

    Provisioning includes the test-only operator authorization: without it
    the ceremony refuses before any launch-capable step.
    """
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    backend = ControlledClearingBackend(
        welcome=json.loads((prepared.directory / "PRELAUNCH.json").read_text())["world"][
            "expected_welcome"
        ],
        case=case,
        **backend_kwargs,
    )
    with synthetic_operator_anchor():
        result = asyncio.run(execute_attempt(prepared, backend))
    return prepared, backend, result


@pytest.fixture(autouse=True)
def _synthetic_operator_anchor_fixture():
    """The whole module verifies under one synthetic RFC 8032 test anchor."""
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _TEST_OPERATOR_PUBLIC.hex()
    try:
        yield
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved


def test_run_rehearsal_lost_clear_response_is_unresolved(tmp_path):
    """A lost clear response keeps DISPATCHED_UNKNOWN and never a verdict."""
    prepared, backend, result = run_rehearsal(tmp_path, case="lost-clear")
    assert result["dispatch_state"] == "DISPATCHED_UNKNOWN"
    assert result["status"] == "FAILED" and result["verified"] is False
    assert result["after_save_sha256"], "the diagnostic save was attempted and retained"
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"
    assert verdict["verification"] != "RECEIPT_VERIFIED"


def test_run_rehearsal_malformed_clear_response_is_unresolved(tmp_path):
    """A malformed clear response keeps the mutation uncertainty visible."""
    prepared, backend, result = run_rehearsal(tmp_path, case="malformed-clear")
    assert result["dispatch_state"] == "DISPATCHED_UNKNOWN"
    assert result["status"] == "FAILED" and result["verified"] is False
    assert "error" in result
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert "unparseable or uncorrelated" in verdict["statement"]
    assert not (prepared.directory / "receipt.json").exists()


def test_run_rehearsal_diagnostic_save_failure_preserved(tmp_path):
    """Diagnostic save failure keeps both the original error and the save error."""
    prepared, backend, result = run_rehearsal(tmp_path, case="lost-clear", save_fail=True)
    assert "clearing proof stream disconnected" in result["error"]
    assert "controlled native save command failure" in result["after_save_error"]
    assert result["dispatch_state"] == "DISPATCHED_UNKNOWN"
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"


def test_run_rehearsal_returncode_139_never_verified(tmp_path):
    """A fully executed attempt whose runtime reaped 139 denies its own receipt."""
    prepared, backend, result = run_rehearsal(tmp_path, case="ok", process_returncode=139)
    assert result["returncode"] == 139
    # Explict normal process termination is part of verified success: the
    # runner demotes its own receipt once the reaped exit code is abnormal,
    # and the CLI exit status is nonzero.
    assert result["status"] == "FAILED" and result["verified"] is False
    assert "abnormally" in result.get("error", "")
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "RECEIPT_VERIFIED"
    assert exit_status(result) == 1


def test_run_rehearsal_crash_after_clear_preserves_partial_evidence(tmp_path):
    """A runtime death after the clear response keeps partial evidence."""
    prepared, backend, result = run_rehearsal(
        tmp_path, case="crash-after-clear", process_returncode=139
    )
    assert result["dispatch_state"] == "CONFIRMED"
    assert result["clearing"] == "CLEARED"
    assert result["status"] == "FAILED" and result["verified"] is False
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "RECEIPT_VERIFIED"
    assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"
    assert exit_status(result) == 1


def test_exit_status_nonzero_for_everything_but_the_verified_receipt():
    """The runner CLI is nonzero unless the receipt claim stands."""
    assert exit_status(dict(status="NATIVE_STATE_VERIFIED")) == 0
    for status in ("FAILED", "STOPPED_NO_MUTATION", "FAILED_CLEANUP"):
        assert exit_status(dict(status=status)) == 1


def patch_exit_evidence(
    directory,
    *,
    result=None,
    cleanup=None,
    omit_result=False,
    omit_cleanup=False,
):
    """Rewrite the retained exit-code evidence and refresh the manifest."""
    for name, override, omit in (
        ("result.json", result, omit_result),
        ("cleanup.json", cleanup, omit_cleanup),
    ):
        path = directory / name
        record = json.loads(path.read_text())
        if omit:
            record.pop("returncode", None)
        elif override is not None:
            record["returncode"] = override
        # The harness write_json is exclusive-create; a tampering simulation
        # overwrites the retained record directly instead.
        path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))


def test_result_rc_missing_cleanup_139_never_verified():
    """cleanup records 139 while result.json omits the code: never verified."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        patch_exit_evidence(directory, omit_result=True, cleanup=139)
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
        assert verdict["verification"] != "RECEIPT_VERIFIED"
        assert verdict["exit_evidence"] == dict(result_returncode=None, cleanup_returncode=139)


def test_result_zero_cleanup_139_contradiction_never_verified():
    """result 0 against cleanup 139 is contradictory exit evidence."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        patch_exit_evidence(directory, cleanup=139)
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
        assert verdict["verification"] != "RECEIPT_VERIFIED"


def test_result_139_cleanup_zero_contradiction_never_verified():
    """result 139 against cleanup 0 is contradictory exit evidence."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        patch_exit_evidence(directory, result=139, cleanup=0)
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
        assert verdict["verification"] != "RECEIPT_VERIFIED"


def test_missing_exit_evidence_denies_verified_receipt():
    """Verified success requires explicit normal termination on both records."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        patch_exit_evidence(directory, omit_result=True, omit_cleanup=True)
        with pytest.raises(
            ValueError,
            match="explicit consistent normal process exit evidence",
        ):
            verify_attempt(directory)


def test_run_rehearsal_receipt_verification_failure_never_verified(tmp_path):
    """A receipt-verification failure is never read as a verified clearing."""
    prepared, backend, result = run_rehearsal(tmp_path, case="receipt-fail")
    assert result["state_changed"] is False and result["verified"] is False
    assert result["status"] == "FAILED"
    assert not (prepared.directory / "receipt.json").exists()
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "RECEIPT_VERIFIED"


def test_dispatch_state_machine_consistency(tmp_path):
    """The dispatch state advances exactly once per outcome.

    LOSS keeps DISPATCHED_UNKNOWN; a confirmed clear response reaches
    CONFIRMED. The transition never passes through a no-mutation state.
    """
    prepared, backend, result = run_rehearsal(tmp_path / "a", case="lost-clear")
    assert result["dispatch_state"] == "DISPATCHED_UNKNOWN"
    assert result["clearing"] == "NOT_DISPATCHED"
    prepared, backend, result = run_rehearsal(tmp_path / "b", case="ok")
    assert result["dispatch_state"] == "CONFIRMED"
    assert result["clearing"] == "CLEARED"


def test_fatal_script_logs_not_suppressed(tmp_path):
    """Fatal script logs after dispatch are retained, never suppressed or claimed."""
    prepared, backend, result = run_rehearsal(tmp_path, case="fatal-after-clear")
    retained = (prepared.directory / "stderr.log").read_text()
    assert "The script died unexpectedly" in retained
    assert result["dispatch_state"] == "CONFIRMED"
    # The runner replays the copied logs through the production log-health
    # implementation: the fatal finding denies any verified claim this
    # attempt could make, while the failure-safe diagnostic save proceeds.
    assert result["status"] == "FAILED" and result["verified"] is False
    assert any("The script died unexpectedly" in f for f in result["script_log_findings"])
    assert result.get("after_save_sha256"), "diagnostic save proceeded despite the fatal log"
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "RECEIPT_VERIFIED"
    assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"


def test_retained_fatal_script_log_denies_verified_receipt():
    """The replay independently denies a receipt with fatal retained findings."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified", defect="fatal-log")
        assert "The script died unexpectedly" in (directory / "stderr.log").read_text()
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
        assert verdict["verification"] != "RECEIPT_VERIFIED"
        assert any(
            "The script died unexpectedly" in finding for finding in verdict["script_log_findings"]
        )


def test_retained_missing_script_health_denies_verified_receipt():
    """A verified claim without retained logs cannot prove script health."""
    with tempfile.TemporaryDirectory() as td:
        directory = synthetic_attempt(Path(td), "verified")
        (directory / "stdout.log").unlink()
        (directory / "stderr.log").unlink()
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        verdict = verify_attempt(directory)
        assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
        assert verdict["verification"] != "RECEIPT_VERIFIED"


def test_run_rehearsal_dead_process_save_failure_documented(tmp_path):
    """An already-dying runtime documents the impossible save; evidence persists."""
    prepared, backend, result = run_rehearsal(
        tmp_path, case="lost-clear", save_fail=True, process_returncode=139
    )
    assert "controlled native save command failure" in result["after_save_error"]
    assert result["returncode"] == 139
    verdict = verify_attempt(prepared.directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["verification"] != "RECEIPT_VERIFIED"
    assert verdict["verification"] != "STOPPED_WITHOUT_MUTATION"


def test_execute_attempt_without_operator_authorization_is_refused(tmp_path):
    """BLOCKER 1 counterexample: no independently issued operator authorization
    means the launch-capable ceremony must be refused before anything happens.

    The runner supplies its own backend flags; those are launch invariants, not
    a launch authorization. Without a record bound to the candidate seal and
    verified against the operator trust anchor, no claim may be consumed and no
    backend session or process may exist afterwards.
    """
    prepared = prepare_candidate(tmp_path / "candidate")
    backend = ControlledClearingBackend(
        welcome=json.loads((prepared.directory / "PRELAUNCH.json").read_text())["world"][
            "expected_welcome"
        ]
    )
    with pytest.raises(ValueError, match="authorization"):
        asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists(), "claim must not be consumed"
    assert backend.session is None and backend.process is None, "no launch-capable work"


# --- BLOCKER 1 regression suite: operator authorization boundary -------------


def test_unseeded_trust_anchor_refuses_even_a_well_formed_record(tmp_path):
    """The fail-closed path outlives seeding: a falsy anchor refuses everything.

    A structurally valid record signed by any other party cannot pass while
    the operator anchor is unsafe to assume; an unset anchor still refuses
    outright exactly as it did before the anchor was seeded.
    """
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    backend = _controlled_backend(prepared)
    # This test verifies the explicit fail-closed anchor semantics, so the
    # module's synthetic anchor fixture is explicitly suspended for it.
    # Nothing here may pretend an unseeded anchor exists in production.
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = None
    try:
        assert operator_authorization.OPERATOR_PUBLIC_KEY_HEX is None
        with pytest.raises(ClearingAuthorizationError, match="trust anchor is unseeded"):
            asyncio.run(execute_attempt(prepared, backend))
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None


def test_production_anchor_refuses_records_not_signed_by_the_operator(tmp_path):
    """BLOCKER 1 at the seeded anchor: only the operator's key ever authorizes.

    The production anchor is now the seeded operator key (LOCAL DEVELOPMENT
    PROOF, docs/handoff/2026-10-17/operator-key-provisioning.md), so the
    runner-side refusal is cryptographic: a well-formed record bound to this
    candidate but signed by any other key — here the synthetic TEST issuer —
    never satisfies it. The runner can never self-approve.
    """
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    backend = _controlled_backend(prepared)
    # Suspend the module's synthetic anchor fixture: verify under the exact
    # production anchor the launch ceremony uses in production.
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _PROD_ANCHOR
    try:
        with pytest.raises(
            ClearingAuthorizationError, match="not signed by the seeded operator anchor"
        ):
            asyncio.run(execute_attempt(prepared, backend))
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None


def test_missing_operator_authorization_means_no_claim_and_no_launch(tmp_path):
    """No record at all: no claim file, no backend preflight, no launch."""
    prepared = prepare_candidate(tmp_path / "candidate")
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="no operator authorization"):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None


def test_pending_metadata_alone_never_launches(tmp_path):
    """The staged PENDING note is descriptive metadata, not an approved gate."""
    prepared = prepare_candidate(tmp_path / "candidate")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    assert metadata["authorization"].startswith("PENDING")
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="no operator authorization"):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None


def test_self_supplied_backend_flag_cannot_bypass(tmp_path):
    """authorized_one_launch=True is a launch invariant, not an approval."""
    prepared = prepare_candidate(tmp_path / "candidate")
    backend = ClearingNativeBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="no operator authorization"):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()


def test_wrong_candidate_digest_authorization_is_refused(tmp_path):
    """A record naming a different prelaunch digest binds nothing here."""
    prepared = prepare_candidate(tmp_path / "candidate")

    def wrong_seal(payload):
        return {**payload, "prelaunch_sha256": "f" * 64}

    issue_test_authorization(prepared, mutate=wrong_seal)
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="does not bind this candidate"):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()


def test_authorization_for_another_candidate_is_refused(tmp_path):
    """A valid record issued elsewhere is unusable anywhere else."""
    other = prepare_candidate(tmp_path / "other")
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(other)
    (prepared.directory / AUTHORIZATION_FILE_NAME).write_text(
        (other.directory / AUTHORIZATION_FILE_NAME).read_text()
    )
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="does not bind this candidate"):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()


def test_wrong_target_or_world_identity_is_refused(tmp_path):
    """Tile and retained source world identity are mandatory binding terms."""
    target_prepared = prepare_candidate(tmp_path / "tile-case")

    def wrong_tile(payload):
        return {**payload, "target_tile": 46768}

    issue_test_authorization(target_prepared, mutate=wrong_tile)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="does not bind this candidate"):
            asyncio.run(execute_attempt(target_prepared, _controlled_backend(target_prepared)))

    world_prepared = prepare_candidate(tmp_path / "world-case")

    def wrong_world(payload):
        return {
            **payload,
            "source_world": {**payload["source_world"], "save_sha256": "e" * 64},
        }

    issue_test_authorization(world_prepared, mutate=wrong_world)
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="does not bind this candidate"):
            asyncio.run(execute_attempt(world_prepared, _controlled_backend(world_prepared)))
    for name in ("tile-case", "world-case"):
        assert not (tmp_path / name / "candidate" / "CLAIM.json").exists()


def test_expanded_request_or_mutation_budget_is_refused(tmp_path):
    """Any budget or cost expansion in the record breaks the exact binding."""
    for index, mutate in enumerate(
        (
            lambda p: {**p, "budgets": {**p["budgets"], "requests": 16}},
            lambda p: {**p, "budgets": {**p["budgets"], "real_clears": 2}},
            lambda p: {**p, "budgets": {**p["budgets"], "launches": 2}},
            lambda p: {**p, "max_cost": 20000},
        )
    ):
        prepared = prepare_candidate(tmp_path / f"budget-case-{index}")
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert metadata["budgets"]["requests"] == 8 and metadata["plan_policy"]["max_cost"] == 10000
        issue_test_authorization(prepared, mutate=mutate)
        with synthetic_operator_anchor():
            with pytest.raises(ClearingAuthorizationError, match="does not bind this candidate"):
                asyncio.run(execute_attempt(prepared, _controlled_backend(prepared)))
        assert not (prepared.directory / "CLAIM.json").exists()


def test_untrusted_authorization_signature_is_refused(tmp_path):
    """A correctly bound record is worthless without the operator's signature."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared, private_hex=_FORGED_OPERATOR_SEED.hex())
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        with pytest.raises(
            ClearingAuthorizationError, match="not signed by the seeded operator anchor"
        ):
            asyncio.run(execute_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()


def test_missing_or_malformed_authorization_is_refused(tmp_path):
    """Broken encodings and wrong record shapes never reach a launch step."""
    malformed = prepare_candidate(tmp_path / "malformed")
    (malformed.directory / AUTHORIZATION_FILE_NAME).write_text("{ not json")
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="not valid JSON"):
            asyncio.run(execute_attempt(malformed, _controlled_backend(malformed)))

    wrong_shape = prepare_candidate(tmp_path / "wrong-shape")
    (wrong_shape.directory / AUTHORIZATION_FILE_NAME).write_text(
        json.dumps({"payloadz": {"milestone": "D2-CLEARING"}, "signature": "00"})
    )
    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="malformed"):
            asyncio.run(execute_attempt(wrong_shape, _controlled_backend(wrong_shape)))
    for name in ("malformed", "wrong-shape"):
        assert not (tmp_path / name / "candidate" / "CLAIM.json").exists()


def test_valid_authorization_permits_exactly_one_claim(tmp_path):
    """A valid record drives exactly one claim transition and one ceremony."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    backend = _controlled_backend(prepared)
    with synthetic_operator_anchor():
        result = asyncio.run(execute_attempt(prepared, backend))
    assert result["dispatch_state"] == "CONFIRMED" and result["clearing"] == "CLEARED"
    claim = json.loads((prepared.directory / "CLAIM.json").read_text())
    seal = sha256(prepared.directory / "PRELAUNCH.json")
    assert claim["prelaunch_digest"] == seal
    assert claim["consumed"] is True and claim["launches_allowed"] == 1
    assert claim["authorization_sha256"] == operator_authorization.record_digest(prepared.directory)
    with synthetic_operator_anchor():
        with pytest.raises(ValueError, match="already consumed"):
            asyncio.run(execute_attempt(prepared, _controlled_backend(prepared)))


def test_second_use_of_consumed_authorization_is_refused(tmp_path):
    """The one-shot claim makes record reuse impossible after the first run."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    with synthetic_operator_anchor():
        asyncio.run(execute_attempt(prepared, _controlled_backend(prepared)))
        with pytest.raises(ValueError, match="already consumed"):
            asyncio.run(execute_attempt(prepared, _controlled_backend(prepared)))


def test_previously_consumed_claim_is_refused(tmp_path):
    """A consumed candidate cannot be re-gated into a second launch."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    seal = sha256(prepared.directory / "PRELAUNCH.json")
    write_json(
        prepared.directory / "CLAIM.json",
        dict(
            prelaunch_digest=seal,
            consumed=True,
            launches_allowed=1,
            retries=0,
            authorization_sha256=operator_authorization.record_digest(prepared.directory),
        ),
    )
    with synthetic_operator_anchor():
        with pytest.raises(ValueError, match="already consumed"):
            asyncio.run(execute_attempt(prepared, _controlled_backend(prepared)))


def test_direct_execute_attempt_invocation_cannot_bypass_authorization(tmp_path):
    """The public ceremony function itself is the choke point; no bypass."""
    prepared = prepare_candidate(tmp_path / "candidate")
    backend = _controlled_backend(prepared)
    # Same fail-closed production-anchor semantics as the unseeded-anchor test
    # above: suspend the module's synthetic anchor fixture for this check, so
    # a direct invocation without an operator record cannot get past the
    # trust anchor at all.
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = None
    try:
        assert operator_authorization.OPERATOR_PUBLIC_KEY_HEX is None
        with pytest.raises(ClearingAuthorizationError, match="trust anchor is unseeded"):
            asyncio.run(execute_attempt(prepared, backend))
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None


# --- BLOCKER: launch-boundary interception utilities -------------------------


class ReachedProcessBoundary(RuntimeError):
    """Records one intercepted Popen call, then stops the ceremony loudly."""


def intercepted_boundary():
    """Patch the real Popen boundary: capture argv/env/cwd, never spawn."""
    calls = []

    def intercept(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        message = "CONTROLLED process boundary sentinel; no process created"
        raise ReachedProcessBoundary(message)

    return mock.patch.object(native_module.subprocess, "Popen", side_effect=intercept), calls


# --- BLOCKER 1: the actual process-launch boundary carries the gate ----------


def test_launch_boundary_requires_a_grant_and_binds_exact_state(tmp_path):
    """Direct public launch reached Popen with no authorization and no claim.

    Three obligations at the real boundary:
      1) launch() without a verified grant reaches no Popen and consumes no claim,
      2) the packaged ceremony reaches exactly one intercepted launch whose argv,
         cwd and environment are exactly the recorded authorized ones,
      3) a minted grant cannot outlive its single use nor authorize change.
    """
    prepared = prepare_candidate(tmp_path / "candidate")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    issue_test_authorization(prepared)
    patch, calls = intercepted_boundary()
    backend = ClearingNativeBackend(authorized_one_launch=True)

    with synthetic_operator_anchor():
        with pytest.raises(ClearingAuthorizationError, match="grant"):
            with patch:
                asyncio.run(backend.launch(prepared))
        assert calls == [], "a granted boundary must see the call arguments"
        assert not (prepared.directory / "CLAIM.json").exists()

        with patch:
            asyncio.run(execute_attempt(prepared, backend))
        assert len(calls) == 1, "exactly one launch may pass the boundary"
        launch = calls[0]
        assert tuple(launch["argv"]) == tuple(metadata["argv"])
        assert str(launch["cwd"]) == str(prepared.spec.workspace.root)
        env = launch["env"]
        assert isinstance(env, dict)
        assert not set(env) & operator_authorization.FORBIDDEN_ENV_KEYS

        with pytest.raises(ClearingAuthorizationError, match="already consumed"):
            operator_authorization.grant_launch(
                prepared.directory,
                metadata,
                sha256(prepared.directory / "PRELAUNCH.json"),
            )
    assert len(calls) == 1


def test_grant_never_authorized_a_different_candidate(tmp_path):
    """A grant minted for one candidate is unusable against another."""
    first = prepare_candidate(tmp_path / "first")
    second = prepare_candidate(tmp_path / "second")
    issue_test_authorization(first)
    patch, calls = intercepted_boundary()
    backend = ClearingNativeBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        grant = operator_authorization.grant_launch(
            first.directory,
            json.loads((first.directory / "PRELAUNCH.json").read_text()),
            sha256(first.directory / "PRELAUNCH.json"),
        )
        with patch:
            with pytest.raises(ClearingAuthorizationError, match="candidate"):
                asyncio.run(backend.launch(second, authorization=grant))
    assert calls == []
    assert not (second.directory / "CLAIM.json").exists()


# --- BLOCKER 5: mutable launch environment and verification-to-launch gap ----


def test_staged_game_script_mutation_after_claim_refuses_launch(tmp_path):
    """A staged main.nut that changes after signature verification and claim
    creation must never reach the Popen boundary (timing-probe counterexample)."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    patch, calls = intercepted_boundary()

    class TimingBackend(ClearingNativeBackend):
        def preflight(self, target):
            super().preflight(target)
            staged_main = (
                Path(json.loads((target.directory / "PRELAUNCH.json").read_text())["workspace"])
                / "game"
                / STAGED_GS_DIRECTORY
                / "main.nut"
            )
            assert (target.directory / "CLAIM.json").exists()
            staged_main.write_bytes(staged_main.read_bytes() + b"\n// drift after claim\n")

    backend = TimingBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        asyncio.run(execute_attempt(prepared, backend))
    assert calls == [], f"launch boundary must refuse mutated staged files: {calls}"
    assert not backend.process
    assert not backend.session


def test_ld_preload_injection_refuses_launch(tmp_path, monkeypatch):
    """An inherited LD_PRELOAD is environment injection, never a clean launch."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    patch, calls = intercepted_boundary()
    monkeypatch.setenv("LD_PRELOAD", "/tmp/opencode/hostile.so")
    backend = ClearingNativeBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        asyncio.run(execute_attempt(prepared, backend))
    assert calls == [], f"injected environment reached the boundary: {calls}"


def test_unexpected_launch_working_directory_refuses_launch(tmp_path):
    """cwd is part of the authorized execution scope; substitutions refuse."""
    prepared = prepare_candidate(tmp_path / "candidate")
    issue_test_authorization(prepared)
    other = tmp_path / "unsealed"
    other.mkdir()
    patch, calls = intercepted_boundary()
    forged = PreparedProof(
        prepared.directory,
        dataclasses.replace(prepared.spec, cwd=other),
        prepared.key_path,
        prepared.public_key,
        prepared.endpoints,
    )

    class CwdTamperBackend(ClearingNativeBackend):
        async def launch(self, target, **kwargs):
            return await ClearingNativeBackend.launch(self, forged, **kwargs)

    backend = CwdTamperBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        asyncio.run(execute_attempt(prepared, backend))
    assert calls == [], f"an unexpected cwd reached the boundary: {calls}"


def test_authorization_bytes_replaced_after_verification_refuse_launch(tmp_path):
    """The exact verified record bytes are pinned; a swap cannot substitute."""
    prepared = prepare_candidate(tmp_path / "candidate")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    issue_test_authorization(prepared)
    patch, calls = intercepted_boundary()

    class SwapBackend(ClearingNativeBackend):
        def preflight(self, target):
            super().preflight(target)
            forged_payload = authorization_payload(
                metadata, sha256(target.directory / "PRELAUNCH.json")
            )
            forged = sign_authorization_record(forged_payload, _FORGED_OPERATOR_SEED.hex())
            (target.directory / AUTHORIZATION_FILE_NAME).write_text(
                json.dumps(forged, sort_keys=True, indent=2) + "\n"
            )

    backend = SwapBackend(authorized_one_launch=True)
    with synthetic_operator_anchor():
        asyncio.run(execute_attempt(prepared, backend))
    assert calls == [], f"substituted authorization bytes reached the boundary: {calls}"


# --- BLOCKER 6: replay evidence carries the authorization story --------------


def test_verified_replay_without_authorization_evidence_is_denied(tmp_path):
    """BLOCKER counterexample: unauthorized evidence returned RECEIPT_VERIFIED."""
    directory = synthetic_attempt(tmp_path, "verified")
    claim = json.loads((directory / "CLAIM.json").read_text())
    claim.pop("authorization_sha256", None)
    claim.pop("authorization", None)
    (directory / "CLAIM.json").write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with synthetic_operator_anchor():
        verdict = verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "MISSING"


def test_forged_replay_authorization_is_denied(tmp_path):
    """A forged record cannot make an unauthorized attempt look authorized."""
    directory = synthetic_attempt(tmp_path, "verified")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    forged = sign_authorization_record(
        authorization_payload(metadata, seal), _FORGED_OPERATOR_SEED.hex()
    )
    operator_authorization.write_authorization_record(directory, forged)
    claim = json.loads((directory / "CLAIM.json").read_text())
    claim["authorization_sha256"] = hashlib.sha256(
        (directory / AUTHORIZATION_FILE_NAME).read_bytes()
    ).hexdigest()
    (directory / "CLAIM.json").write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with synthetic_operator_anchor():
        verdict = verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_replay_authorization_bytes_tampered_after_launch_are_denied(tmp_path):
    """Authorization bytes that differ from the launched digest stand denied."""
    directory = synthetic_attempt(tmp_path, "verified")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    other = sign_authorization_record(
        authorization_payload(metadata, seal), _FORGED_OPERATOR_SEED.hex()
    )
    claim = json.loads((directory / "CLAIM.json").read_text())
    claim["authorization_sha256"] = hashlib.sha256(
        (directory / AUTHORIZATION_FILE_NAME).read_bytes()
    ).hexdigest()
    operator_authorization.write_authorization_record(directory, other)
    (directory / "CLAIM.json").write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with synthetic_operator_anchor():
        verdict = verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_authorized_replay_with_valid_evidence_still_verifies(tmp_path):
    """A valid authorized attempt keeps producing the verified receipt."""
    directory = synthetic_attempt(tmp_path, "verified")
    with synthetic_operator_anchor():
        verification = verify_attempt(directory)
    assert verification["verification"] == "RECEIPT_VERIFIED"
    receipt = verification["receipt"]
    assert receipt["original_classification"] == "TREES"


def test_verified_replay_requires_the_seeded_replay_key_identity(tmp_path):
    """Replay must verify against the key identity recorded at launch."""
    directory = synthetic_attempt(tmp_path, "verified")
    claim = json.loads((directory / "CLAIM.json").read_text())
    claim.pop("operator_key_identity", None)
    (directory / "CLAIM.json").write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    with synthetic_operator_anchor():
        verdict = verify_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "KEY_IDENTITY_MISSING"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
