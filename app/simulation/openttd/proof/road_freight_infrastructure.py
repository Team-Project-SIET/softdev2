"""One-shot road freight infrastructure proof using the existing road lifecycle."""

import argparse
import asyncio
import json
import shutil
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
)
from app.simulation.openttd.road_freight_infrastructure import (
    STAGES,
    FreightConstructionPlan,
    FreightReadback,
    FreightRequest,
    admit_site,
    verify_construction,
    verify_step,
)
from app.simulation.openttd.secure_admin import AuthState

from . import road_mutation as road
from .endpoints import kernel_socket_rows, verify_cleanup_endpoints
from .harness import PreparedProof, manifest, sha256, write_json
from .native import NativeBackend
from .road_mutation import CANDIDATES, MAX_COST, console, reopen, save, wait_log


class FreightSecureSession(road.RoadSecureSession):
    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            FreightRequest.model_validate_json(decode_gamescript(frame[3:])).to_bytes()
        else:
            super().validate_outbound(frame)


def prepare(directory: Path) -> PreparedProof:
    return road.prepare(directory, freight=True)


def preflight(prepared: PreparedProof) -> None:
    road.preflight(prepared)
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    if (
        metadata["schema"] != "road-freight-infrastructure-prelaunch-v1"
        or metadata["budgets"]["real_builds"] != 3
        or metadata["budgets"]["requests"] != 38
        or metadata["binary_sha256"] != road.BINARY_SHA256
        or any(
            metadata["budgets"][k] != v
            for k, v in {
                "launches": 1,
                "connection_attempts": 1,
                "retries": 0,
                "reconnects": 0,
                "response_bytes": 512,
                "gsadmin_bytes": 1450,
            }.items()
        )
    ):
        raise ValueError("freight profile mismatch")
    for file in ("main.nut", "info.nut"):
        source = road.PACKAGES / "road_freight_package" / file
        staged = prepared.spec.workspace.game / "RoadFreightProof" / file
        if source.read_bytes() != staged.read_bytes():
            raise ValueError("stale freight GameScript package")


async def exchange(session, request, directory):
    return await road.exchange(session, request, directory, response_type=FreightReadback)


async def run(prepared: PreparedProof):
    directory = prepared.directory
    preflight(prepared)
    seal = sha256(directory / "PRELAUNCH.json")
    write_json(
        directory / "CLAIM.json",
        dict(prelaunch_digest=seal, consumed=True, launches_allowed=1, retries=0),
    )
    backend = NativeBackend(authorized_one_launch=True)
    backend.preflight(prepared)
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        connection_attempts=0,
        requests=0,
        build_requests=0,
        construction="NOT_EXECUTED",
        status="FAILED",
    )
    frames = []
    try:
        async with asyncio.timeout(180):
            await backend.launch(prepared)
            result["native_launches"] = 1
            await wait_log(backend, prepared, "ROAD_FREIGHT_READY")
            console(backend, "start_ai RoadProofCompany")
            await wait_log(backend, prepared, "ROAD_PROOF_COMPANY_READY")
            if not any(
                r["table"] == "tcp"
                and r["local_port"] == prepared.endpoints[1]
                and r["state"] == 10
                for r in kernel_socket_rows()
            ):
                raise ValueError("native Admin listener readiness absent")
            key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
            result["connection_attempts"] = 1
            session = await FreightSecureSession.connect_secure(
                "127.0.0.1",
                prepared.endpoints[1],
                5,
                key=key,
                frame_observer=lambda d, f: frames.append((d, f.hex())),
            )
            backend.session = session
            result["connections"] = 1
            await session.authenticate("Road-proof", "1", timeout=10)
            welcome = session.welcome
            if (
                session.protocol is None
                or welcome is None
                or (
                    welcome.revision,
                    welcome.dedicated,
                    welcome.seed,
                    welcome.width,
                    welcome.height,
                )
                != ("15.3", True, 42, 64, 64)
            ):
                raise ValueError("native runtime identity mismatch")
            write_json(
                directory / "runtime-identity.json",
                dict(
                    auth="X25519_AuthorizedKey",
                    encrypted=session.state is AuthState.ACTIVE,
                    welcome=asdict(welcome),
                    pid=backend.process.pid if backend.process else None,
                ),
            )
            await GameScriptTransport(session, session.protocol).subscribe()
            before_save = await save(backend, prepared, "before")
            write_json(directory / "before-save-identity.json", dict(sha256=before_save))
            before = None
            for index, (start, end) in enumerate(CANDIDATES):
                q = FreightRequest(
                    op="inspect",
                    request_id=f"inspect-{index}",
                    plan=seal,
                    company=0,
                    start=start,
                    end=end,
                    max_cost=MAX_COST,
                )
                value = await exchange(session, q, directory)
                result["requests"] += 1
                if value.status not in ("NOT_BUILDABLE", "READY"):
                    raise ValueError("native site admission failed: " + value.status)
                if value.status == "READY":
                    before = value
                    break
            if before is None:
                raise ValueError("no native-feasible four-tile site in frozen candidates")
            plan = admit_site(
                before, prelaunch_digest=seal, source_save_digest=before_save, max_cost=MAX_COST
            )
            write_json(directory / "plan.json", plan.model_dump(mode="json"))
            exchanges = []
            funds = before.funds
            for i, stage in enumerate(STAGES):
                q = FreightRequest(
                    op=stage,
                    request_id=stage + "-1",
                    plan=plan.digest,
                    company=plan.company,
                    start=plan.start,
                    end=plan.end,
                    max_cost=plan.max_cost,
                )
                result["build_requests"] += 1
                built = await exchange(session, q, directory)
                result["requests"] += 1
                result["construction"] = stage + ":" + built.status
                if built.status != "BUILT":
                    raise ValueError("native " + stage + " construction failed: " + built.status)
                read = q.model_copy(update={"op": "read", "request_id": "read-" + stage})
                after = await exchange(session, read, directory)
                result["requests"] += 1
                verify_step(plan, built, after, i, funds)
                if i == 2 and after.sid != exchanges[-1][1].sid:
                    raise ValueError("station identity changed during depot construction")
                exchanges.append((built, after))
                funds = after.funds
            receipt = verify_construction(plan, before, exchanges)
            receipt["before_save_sha256"] = before_save
            receipt["after_save_sha256"] = await save(backend, prepared, "after")
            write_json(directory / "receipt.json", receipt)
            result["status"] = "NATIVE_STATE_VERIFIED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        result["native_launches"] = int(backend.process is not None)
        write_json(directory / "frames.json", frames)
        cleanup = await backend.cleanup(prepared)
        for name in ("stdout.log", "stderr.log"):
            path = prepared.spec.workspace.logs / name
            if path.is_file():
                shutil.copyfile(path, directory / name)
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("cleanup incomplete")
            prepared.spec.workspace.close()
            cleanup["workspace_disposed"] = not prepared.spec.workspace.root.exists()
            cleanup["credential_removed"] = not prepared.key_path.exists()
        except Exception as error:
            cleanup["verification_error"] = str(error)
            result["status"] = "FAILED_CLEANUP"
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


def verify_receipt(directory: Path):
    """Replay plan, ordered secure frames, native costs, topology and cleanup."""
    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("artifact manifest mismatch")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    seal = sha256(directory / "PRELAUNCH.json")
    if seal != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    claim = json.loads((directory / "CLAIM.json").read_text())
    if claim != {"prelaunch_digest": seal, "consumed": True, "launches_allowed": 1, "retries": 0}:
        raise ValueError("single launch claim mismatch")
    plan = FreightConstructionPlan.model_validate_json((directory / "plan.json").read_bytes())
    if (
        plan.prelaunch_digest != seal
        or plan.company != metadata["plan_policy"]["company"]
        or plan.max_cost != metadata["plan_policy"]["max_cost"]
        or [plan.start, plan.end] not in metadata["plan_policy"]["candidates"]
    ):
        raise ValueError("plan/prelaunch policy mismatch")
    frames = json.loads((directory / "frames.json").read_text())
    outbound = [bytes.fromhex(f) for d, f in frames if d == "outbound"]
    replies = []
    for direction, frame in frames:
        if direction == "inbound":
            for kind, body in AdminFrameDecoder().feed_frames(bytes.fromhex(frame)):
                if kind == SERVER_GAMESCRIPT:
                    replies.append(decode_gamescript(body))
    requests = list(directory.glob("*-request.json"))
    if not 7 <= len(requests) <= 38:
        raise ValueError("request budget mismatch")
    responses = {}
    for path in requests:
        raw = path.read_bytes()
        q = FreightRequest.model_validate_json(raw)
        response = path.with_name(path.name.replace("-request.json", "-response.json")).read_bytes()
        if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
            raise ValueError("retained exchange lacks unique secure frame evidence")
        responses[q.request_id] = FreightReadback.parse_for(q, response)
    inspections = sorted(
        (v for v in responses.values() if v.op == "inspect"),
        key=lambda v: int(v.request_id.removeprefix("inspect-")),
    )
    if (
        not inspections
        or len(inspections) > 32
        or [v.request_id for v in inspections] != [f"inspect-{i}" for i in range(len(inspections))]
        or any(v.status == "READY" for v in inspections[:-1])
    ):
        raise ValueError("bounded inspection sequence mismatch")
    before = inspections[-1]
    for i, value in enumerate(inspections):
        if (
            (value.start, value.end) != tuple(metadata["plan_policy"]["candidates"][i])
            or value.plan != seal
            or value.company != plan.company
        ):
            raise ValueError("inspection provenance mismatch")
    expected_ids = [v.request_id for v in inspections]
    exchanges = []
    for stage in STAGES:
        expected_ids += [stage + "-1", "read-" + stage]
        exchanges.append((responses[stage + "-1"], responses["read-" + stage]))
    actual_ids = [
        FreightRequest.model_validate_json(decode_gamescript(f[3:])).request_id
        for f in outbound
        if f[2] == ADMIN_GAMESCRIPT
    ]
    if actual_ids != expected_ids or len(responses) != len(expected_ids):
        raise ValueError("construction/readback sequence mismatch")
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    welcome = runtime["welcome"]
    if (
        runtime["encrypted"] is not True
        or runtime["auth"] != "X25519_AuthorizedKey"
        or (
            welcome["revision"],
            welcome["dedicated"],
            welcome["seed"],
            welcome["width"],
            welcome["height"],
        )
        != ("15.3", True, 42, 64, 64)
        or (
            result["native_launches"],
            result["connections"],
            result["connection_attempts"],
            result["build_requests"],
            result["requests"],
            result["status"],
        )
        != (1, 1, 1, 3, len(expected_ids), "NATIVE_STATE_VERIFIED")
    ):
        raise ValueError("single encrypted native runtime evidence mismatch")
    expected = verify_construction(plan, before, exchanges)
    expected.update(
        before_save_sha256=sha256(directory / "before.sav"),
        after_save_sha256=sha256(directory / "after.sav"),
    )
    if (
        plan.source_save_digest != expected["before_save_sha256"]
        or expected["before_save_sha256"] == expected["after_save_sha256"]
        or expected != json.loads((directory / "receipt.json").read_text())
    ):
        raise ValueError("receipt/plan/save mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if (
        cleanup.get("cleanup_error")
        or cleanup.get("verification_error")
        or not all(
            cleanup.get(k) is True
            for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
        or cleanup.get("remaining_processes")
    ):
        raise ValueError("receipt cleanup incomplete")
    return expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare(directory)
        preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        preflight(reopen(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        print(json.dumps(verify_receipt(directory), sort_keys=True))
    else:
        result = asyncio.run(run(reopen(directory)))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["status"] == "NATIVE_STATE_VERIFIED" else 1)


if __name__ == "__main__":
    main()
