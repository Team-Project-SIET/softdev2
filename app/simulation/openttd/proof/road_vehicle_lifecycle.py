"""One authorized vehicle lifecycle on a copy of proven infrastructure."""

import argparse
import asyncio
import json
import os
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
    FreightConstructionPlan,
    FreightReadback,
    FreightRequest,
    verify_state,
)
from app.simulation.openttd.road_vehicle_lifecycle import (
    MOTION_POLLS,
    MOTION_SECONDS,
    MOTION_TICKS,
    VehicleLifecyclePlan,
    VehicleReadback,
    VehicleRequest,
    admit_engine,
    verify_lifecycle,
    verify_order,
    verify_purchase,
    verify_start,
    verify_vehicle,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState

from . import road_freight_infrastructure as freight
from . import road_mutation as road
from .endpoints import kernel_socket_rows, verify_cleanup_endpoints
from .graphics import stage_opengfx
from .harness import (
    BINARY,
    BINARY_SHA256,
    PROJECT,
    EndpointReservation,
    PreparedProof,
    launch_argv,
    manifest,
    sha256,
    source_freeze,
    verify_freeze,
    write_json,
)
from .native import NativeBackend, matching_processes
from .road_mutation import reopen, save, wait_log

SOURCE = PROJECT / "artifacts/runtime/openttd-15.3-road-freight-infrastructure-attempt1"
PREVIOUS = PROJECT / "artifacts/runtime/openttd-15.3-road-vehicle-lifecycle-attempt1"
PACKAGE = road.PACKAGES / "road_vehicle_package"
MAX_COST = 20000  # Purchase ceiling, never a price assumption.
BUDGETS = dict(
    launches=1,
    connection_attempts=1,
    retries=0,
    reconnects=0,
    requests=12,
    mutations=3,
    engines=32,
    motion_script_ticks=MOTION_TICKS,
    motion_polls=MOTION_POLLS,
    motion_poll_interval=1,
    response_bytes=512,
    gsadmin_bytes=1450,
    request_seconds=10,
    motion_seconds=MOTION_SECONDS,
    total_seconds=180,
)


def load_argv(binary, config, game_port, source):
    argv = list(launch_argv(binary, config, game_port))
    index = argv.index("-g")
    argv[index : index + 3] = ["-g", str(source)]
    return tuple(argv)


def previous_identity(directory=PREVIOUS):
    """Admit the consumed, cleaned-up predecessor without rewriting its evidence."""
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    claim = json.loads((directory / "CLAIM.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    cleanup = json.loads((directory / "cleanup.json").read_text())
    q = VehicleRequest.model_validate_json((directory / "motion-1-request.json").read_bytes())
    motion = VehicleReadback.parse_for(q, (directory / "motion-1-response.json").read_bytes())
    if (
        manifest(directory) != (directory / "artifact-manifest.sha256").read_text()
        or seal != (directory / "PRELAUNCH.sha256").read_text().strip()
        or metadata["attempt"] != 1
        or metadata["binary_sha256"] != BINARY_SHA256
        or claim != dict(prelaunch_digest=seal, consumed=True, launches_allowed=1, retries=0)
        or (
            result["native_launches"],
            result["connections"],
            result["mutation_requests"],
            result["status"],
        )
        != (1, 1, 3, "FAILED")
        or (motion.status, motion.vehicle, motion.location) != ("NO_MOVEMENT", 1, 1294)
        or not all(
            cleanup.get(k) is True
            for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
        or cleanup.get("cleanup_error")
        or cleanup.get("remaining_processes")
    ):
        raise ValueError("Attempt 1 predecessor identity, failure or cleanup mismatch")
    return dict(
        directory=str(directory),
        prelaunch_sha256=seal,
        artifact_manifest_sha256=sha256(directory / "artifact-manifest.sha256"),
        result_sha256=sha256(directory / "result.json"),
    )


class VehicleBackend(NativeBackend):
    def validate_launch(self, prepared):
        expected = load_argv(
            BINARY.resolve(),
            prepared.spec.workspace.config,
            prepared.endpoints[0],
            prepared.spec.workspace.root / "source.sav",
        )
        if (
            prepared.spec.argv != expected
            or sha256(BINARY) != BINARY_SHA256
            or matching_processes(BINARY)
        ):
            raise ValueError("native loaded-runtime identity/ownership mismatch")


class VehicleSecureSession(freight.FreightSecureSession):
    def validate_outbound(self, frame: bytes) -> None:
        if (
            self.state is not AuthState.ACTIVE
            or len(frame) < 3
            or struct.unpack_from("<H", frame)[0] != len(frame)
        ):
            raise ValueError("valid encrypted ACTIVE frame required")
        if frame[2] == ADMIN_GAMESCRIPT:
            raw = decode_gamescript(frame[3:])
            if json.loads(raw).get("op") == "read":
                FreightRequest.model_validate_json(raw).to_bytes()
            else:
                VehicleRequest.model_validate_json(raw).to_bytes()
        else:
            super().validate_outbound(frame)


def prepare(directory: Path) -> PreparedProof:
    predecessor = previous_identity()
    verified = freight.verify_receipt(SOURCE)
    original = SOURCE / "after.sav"
    if sha256(original) != verified["after_save_sha256"] or matching_processes(BINARY):
        raise ValueError("proven infrastructure source mismatch")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        secret = workspace.root / ".admin-secret"
        with os.fdopen(
            os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as stream:
            stream.write(key._secret)
        workspace.write_config(
            AdminSettings(
                password="",
                port=reservation.admin_port,
                game_port=reservation.game_port,
                authorized_public_key_hex=key.public_hex,
            )
        )
        config = workspace.config.read_text().replace(
            "pause_on_newgame = true", "pause_on_newgame = false"
        )
        config += (
            "\n[misc]\ngraphicsset = OpenGFX\n[ai]\nai_in_multiplayer = true\n"
            "[game_scripts]\nRoadFreightProof = \n"
        )
        workspace.config.write_text(config)
        graphics = stage_opengfx(
            PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip",
            workspace.root / "baseset/OpenGFX",
        )
        write_json(
            directory / "graphics-identity.json",
            dict(asdict(graphics), directory=str(graphics.directory)),
        )
        for package, parent, name in (
            (PACKAGE, workspace.game, "RoadFreightProof"),
            (road.PACKAGES / "road_company_package", workspace.ai, "RoadProofCompany"),
        ):
            target = parent / name
            target.mkdir()
            for path in package.glob("*.nut"):
                shutil.copyfile(path, target / path.name)
        shutil.copyfile(original, workspace.root / "source.sav")
        argv = load_argv(
            BINARY.resolve(), workspace.config, reservation.game_port, workspace.root / "source.sav"
        )
        spec = LaunchSpecification(
            workspace,
            RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        frozen = source_freeze()
        for path in list(PACKAGE.glob("*.nut")) + list(
            (road.PACKAGES / "road_company_package").glob("*.nut")
        ):
            frozen[str(path.resolve())] = sha256(path)
        for path in list(SOURCE.iterdir()) + list(PREVIOUS.iterdir()):
            if path.is_file():
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(p): sha256(p)
                for p in workspace.root.rglob("*")
                if p.is_file() and p.name != ".admin-secret"
            }
        )
        metadata = dict(
            schema="road-vehicle-lifecycle-prelaunch-v2",
            attempt=2,
            predecessor=predecessor,
            workspace=str(workspace.root),
            binary_sha256=BINARY_SHA256,
            argv=list(argv),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            source=dict(
                directory=str(SOURCE),
                save=str(original),
                save_sha256=sha256(original),
                receipt_sha256=sha256(SOURCE / "receipt.json"),
            ),
            world=dict(
                source="COPIED_NATIVE_PROVEN_INFRASTRUCTURE_SAVE", seed=42, width=64, height=64
            ),
            plan_policy=dict(
                company=verified["company"],
                stop=verified["tiles"][0],
                depot=verified["tiles"][-1],
                station_id=verified["station_id"],
                max_cost=MAX_COST,
                selection="lowest available compatible non-articulated default-cargo road engine",
                order_flags=0,
                engine_capacity="native default cargo; verify actual after purchase",
            ),
            commands=[
                "GSVehicle.BuildVehicle(depot,engine)",
                "GSOrder.AppendOrder(vehicle,stop,OF_NONE)",
                "GSVehicle.StartStopVehicle(vehicle)",
            ],
            expected_readback=[
                "owned vehicle stopped in depot; actual engine and cargo capacity",
                "exactly one station order at proven truck stop",
                "started vehicle and independently observed location outside depot",
            ],
            movement=dict(
                clock="GSController.GetTick; script ticks, not vehicle ticks",
                pause="GSGame.IsPaused at each poll; fail without unpausing",
                success="native tile outside depot in owned connected four-tile site",
                exhaustion="inconclusive; not evidence of path blockage",
            ),
            script=dict(
                saved_name="RoadFreightProof", version=1, profile="RoadVehicleProof", api="15"
            ),
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.road_vehicle_lifecycle",
                "run",
                str(directory),
            ],
            budgets=BUDGETS,
            cleanup=[
                "close secure stream",
                "quit/reap process",
                "verify endpoints",
                "retain saves and logs",
                "remove credential",
                "dispose owned copied world",
            ],
            authorization="user authorized one disposable-world launch after preflight passes",
            frozen=frozen,
        )
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return PreparedProof(
            directory, spec, secret, key.public_hex, (reservation.game_port, reservation.admin_port)
        )
    finally:
        reservation.close()


def preflight(prepared: PreparedProof):
    p = prepared.directory
    if (p / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    if sha256(p / "PRELAUNCH.json") != (p / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    m = json.loads((p / "PRELAUNCH.json").read_text())
    if m["schema"] != "road-vehicle-lifecycle-prelaunch-v2" or m["budgets"] != BUDGETS:
        raise ValueError("vehicle profile or budgets mismatch")
    if m.get("attempt") != 2 or m.get("predecessor") != previous_identity():
        raise ValueError("Attempt 2 predecessor lineage mismatch")
    verify_freeze(m["frozen"])
    verified = freight.verify_receipt(SOURCE)
    if (
        m["source"]["save_sha256"] != verified["after_save_sha256"]
        or sha256(prepared.spec.workspace.root / "source.sav") != verified["after_save_sha256"]
        or sha256(SOURCE / "receipt.json") != m["source"]["receipt_sha256"]
    ):
        raise ValueError("source save/receipt provenance mismatch")
    if not prepared.spec.workspace.root.is_relative_to(p / "isolated"):
        raise ValueError("workspace ownership mismatch")
    for path in PACKAGE.glob("*.nut"):
        if (
            path.read_bytes()
            != (prepared.spec.workspace.game / "RoadFreightProof" / path.name).read_bytes()
        ):
            raise ValueError("stale vehicle package")
    if (PACKAGE / "infrastructure.nut").read_bytes() != (
        road.PACKAGES / "road_freight_package/main.nut"
    ).read_bytes():
        raise ValueError("infrastructure dependency changed")
    backend = VehicleBackend(authorized_one_launch=True)
    backend.preflight(prepared)
    backend.validate_launch(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()


async def exchange(session, q, directory):
    if isinstance(q, FreightRequest):
        return await road.exchange(session, q, directory, response_type=FreightReadback)
    raw = q.to_bytes()
    (directory / (q.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    try:
        async with asyncio.timeout(MOTION_SECONDS if q.op == "motion" else 10):
            while True:
                chunk = await session.receive()
                if not chunk:
                    raise ConnectionError("vehicle proof stream disconnected")
                for kind, payload in decoder.feed_frames(chunk):
                    if kind != SERVER_GAMESCRIPT:
                        raise ValueError("unexpected vehicle-proof packet")
                    response = decode_gamescript(payload)
                    (directory / (q.request_id + "-response.json")).write_bytes(response)
                    return VehicleReadback.parse_for(q, response)
    except TimeoutError as error:
        if q.op == "motion":
            raise TimeoutError("MOVEMENT_WALL_DEADLINE_EXPIRED; progress unknown") from error
        raise


async def run(prepared: PreparedProof):
    directory = prepared.directory
    preflight(prepared)
    seal = sha256(directory / "PRELAUNCH.json")
    write_json(
        directory / "CLAIM.json",
        dict(prelaunch_digest=seal, consumed=True, launches_allowed=1, retries=0),
    )
    backend = VehicleBackend(authorized_one_launch=True)
    backend.preflight(prepared)
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        connection_attempts=0,
        requests=0,
        mutation_requests=0,
        construction="NOT_EXECUTED",
        status="FAILED",
    )
    frames = []
    try:
        async with asyncio.timeout(180):
            await backend.launch(prepared)
            result["native_launches"] = 1
            await wait_log(backend, prepared, "ROAD_VEHICLE_READY")
            if not any(
                r["table"] == "tcp"
                and r["local_port"] == prepared.endpoints[1]
                and r["state"] == 10
                for r in kernel_socket_rows()
            ):
                raise ValueError("native Admin listener readiness absent")
            key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
            result["connection_attempts"] = 1
            session = await VehicleSecureSession.connect_secure(
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
            metadata = json.loads((directory / "PRELAUNCH.json").read_text())
            infra = FreightConstructionPlan.model_validate_json((SOURCE / "plan.json").read_bytes())
            siteq = FreightRequest(
                op="read",
                request_id="site-before",
                plan=infra.digest,
                company=infra.company,
                start=infra.start,
                end=infra.end,
                max_cost=infra.max_cost,
            )
            site = await exchange(session, siteq, directory)
            result["requests"] += 1
            verify_state(infra, site, 2)
            if site.status != "READ" or site.sid != metadata["plan_policy"]["station_id"]:
                raise ValueError("loaded native infrastructure mismatch")
            q = VehicleRequest(
                op="engine",
                request_id="engine-1",
                plan=seal,
                company=infra.company,
                depot=infra.end + 1,
                stop=infra.start - 1,
                max_cost=MAX_COST,
            )
            engine = await exchange(session, q, directory)
            result["requests"] += 1
            plan = admit_engine(
                engine,
                prelaunch_digest=seal,
                infrastructure_receipt_digest=metadata["source"]["receipt_sha256"],
                source_save_digest=metadata["source"]["save_sha256"],
                site_digest=site.digest,
                max_cost=MAX_COST,
            )
            write_json(directory / "plan.json", plan.model_dump(mode="json"))
            records = {}

            async def query(op, request_id, vehicle=-1):
                q = VehicleRequest(
                    op=op,
                    request_id=request_id,
                    plan=plan.digest,
                    company=plan.company,
                    depot=plan.depot,
                    stop=plan.stop,
                    engine=plan.engine,
                    cargo=plan.cargo,
                    vehicle=vehicle,
                    max_cost=plan.max_cost,
                    expected_cost=plan.purchase_cost,
                )
                if op in ("purchase", "order", "start"):
                    result["mutation_requests"] += 1
                value = await exchange(session, q, directory)
                result["requests"] += 1
                records[request_id] = value
                return value

            built = await query("purchase", "purchase-1")
            result["construction"] = "purchase:" + built.status
            if built.status != "PURCHASED":
                raise ValueError("purchase failed: " + built.status)
            read = await query("vread", "read-purchase", built.vehicle)
            verify_purchase(plan, engine, built, read)
            vid = built.vehicle
            check = await query("order-check", "order-check-1", vid)
            verify_vehicle(plan, check, vid, 0, stopped=True)
            if check.status != "READY" or check.cost != 0 or check.funds != read.funds:
                raise ValueError("order admission failed: " + check.status)
            ordered = await query("order", "order-1", vid)
            if ordered.status != "ORDERED":
                raise ValueError("order failed: " + ordered.status)
            orderread = await query("vread", "read-order", vid)
            verify_order(plan, read, check, ordered, orderread)
            check = await query("start-check", "start-check-1", vid)
            verify_vehicle(plan, check, vid, 1, stopped=True)
            if check.status != "READY" or check.cost != 0:
                raise ValueError("start admission failed: " + check.status)
            started = await query("start", "start-1", vid)
            if started.status != "STARTED":
                raise ValueError("start failed: " + started.status)
            startread = await query("vread", "read-start", vid)
            verify_vehicle(plan, startread, vid, 1, stopped=False)
            if startread.status != "READ":
                raise ValueError("start readback missing")
            motion = await query("motion", "motion-1", vid)
            verify_start(plan, orderread, check, started, startread, motion)
            finalq = siteq.model_copy(update={"request_id": "site-after"})
            finalsite = await exchange(session, finalq, directory)
            result["requests"] += 1
            verify_state(infra, finalsite, 2)
            if finalsite.sid != site.sid or finalsite.status != "READ":
                raise ValueError("infrastructure changed during vehicle lifecycle")
            receipt = verify_lifecycle(plan, engine, records)
            receipt.update(
                before_save_sha256=before_save,
                after_save_sha256=await save(backend, prepared, "after"),
                final_site_digest=finalsite.digest,
            )
            write_json(directory / "receipt.json", receipt)
            result["construction"] = "VEHICLE_LIFECYCLE_VERIFIED"
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
    """Replay unique ordered secure exchanges and actual lifecycle transitions."""
    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("artifact manifest mismatch")
    m = json.loads((directory / "PRELAUNCH.json").read_text())
    if m.get("attempt") != 2 or m.get("predecessor") != previous_identity():
        raise ValueError("Attempt 2 receipt predecessor lineage mismatch")
    seal = sha256(directory / "PRELAUNCH.json")
    if (
        seal != (directory / "PRELAUNCH.sha256").read_text().strip()
        or m["schema"] != "road-vehicle-lifecycle-prelaunch-v2"
        or m["budgets"] != BUDGETS
        or m["binary_sha256"] != BINARY_SHA256
    ):
        raise ValueError("prelaunch identity/budgets mismatch")
    if json.loads((directory / "CLAIM.json").read_text()) != {
        "prelaunch_digest": seal,
        "consumed": True,
        "launches_allowed": 1,
        "retries": 0,
    }:
        raise ValueError("single launch claim mismatch")
    source = Path(m["source"]["directory"])
    source_receipt = freight.verify_receipt(source)
    if (
        sha256(source / "after.sav") != m["source"]["save_sha256"]
        or source_receipt["after_save_sha256"] != m["source"]["save_sha256"]
        or sha256(source / "receipt.json") != m["source"]["receipt_sha256"]
    ):
        raise ValueError("proven source-save lineage mismatch")
    plan = VehicleLifecyclePlan.model_validate_json((directory / "plan.json").read_bytes())
    if (
        plan.prelaunch_digest,
        plan.infrastructure_receipt_digest,
        plan.source_save_digest,
        plan.company,
        plan.stop,
        plan.depot,
        plan.max_cost,
    ) != (
        seal,
        m["source"]["receipt_sha256"],
        m["source"]["save_sha256"],
        m["plan_policy"]["company"],
        m["plan_policy"]["stop"],
        m["plan_policy"]["depot"],
        MAX_COST,
    ):
        raise ValueError("plan/source/proven infrastructure mismatch")
    frames = json.loads((directory / "frames.json").read_text())
    outbound = [bytes.fromhex(f) for d, f in frames if d == "outbound"]
    replies = []
    for d, f in frames:
        if d == "inbound":
            for kind, body in AdminFrameDecoder().feed_frames(bytes.fromhex(f)):
                if kind == SERVER_GAMESCRIPT:
                    replies.append(decode_gamescript(body))
    records = {}
    sites = {}
    for path in directory.glob("*-request.json"):
        raw = path.read_bytes()
        response = path.with_name(path.name.replace("-request.json", "-response.json")).read_bytes()
        if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
            raise ValueError("retained exchange lacks unique secure frame evidence")
        if json.loads(raw)["op"] == "read":
            q = FreightRequest.model_validate_json(raw)
            sites[q.request_id] = FreightReadback.parse_for(q, response)
        else:
            q = VehicleRequest.model_validate_json(raw)
            records[q.request_id] = VehicleReadback.parse_for(q, response)
            if q.max_cost != plan.max_cost or (
                q.op != "engine" and q.expected_cost != plan.purchase_cost
            ):
                raise ValueError("request purchase ceiling or cost mismatch")
    expected_ids = [
        "site-before",
        "engine-1",
        "purchase-1",
        "read-purchase",
        "order-check-1",
        "order-1",
        "read-order",
        "start-check-1",
        "start-1",
        "read-start",
        "motion-1",
        "site-after",
    ]
    actual_ids = [
        json.loads(decode_gamescript(f[3:]))["request_id"]
        for f in outbound
        if f[2] == ADMIN_GAMESCRIPT
    ]
    if actual_ids != expected_ids or len(records) != 10 or len(sites) != 2:
        raise ValueError("bounded lifecycle sequence mismatch")
    infra = FreightConstructionPlan.model_validate_json((source / "plan.json").read_bytes())
    for site in sites.values():
        verify_state(infra, site, 2)
        if site.status != "READ" or site.sid != source_receipt["station_id"]:
            raise ValueError("loaded native site identity mismatch")
    if sites["site-before"].digest != plan.site_digest:
        raise ValueError("native site observation provenance mismatch")
    engine = records.pop("engine-1")
    expected = verify_lifecycle(plan, engine, records)
    expected.update(
        before_save_sha256=sha256(directory / "before.sav"),
        after_save_sha256=sha256(directory / "after.sav"),
        final_site_digest=sites["site-after"].digest,
    )
    if (
        expected != json.loads((directory / "receipt.json").read_text())
        or expected["before_save_sha256"] == expected["after_save_sha256"]
    ):
        raise ValueError("receipt/plan/save mismatch")
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    w = runtime["welcome"]
    if (
        runtime["encrypted"] is not True
        or runtime["auth"] != "X25519_AuthorizedKey"
        or (w["revision"], w["dedicated"], w["seed"], w["width"], w["height"])
        != ("15.3", True, 42, 64, 64)
        or (
            result["native_launches"],
            result["connection_attempts"],
            result["connections"],
            result["mutation_requests"],
            result["requests"],
            result["status"],
        )
        != (1, 1, 1, 3, 12, "NATIVE_STATE_VERIFIED")
    ):
        raise ValueError("single encrypted native runtime evidence mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if (
        cleanup.get("cleanup_error")
        or cleanup.get("verification_error")
        or cleanup.get("remaining_processes")
        or not all(
            cleanup.get(k) is True
            for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
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
        p = prepare(directory)
        preflight(p)
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
