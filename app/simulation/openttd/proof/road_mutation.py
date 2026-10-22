"""Separate one-shot disposable-road proof; existing read-only bridges stay unchanged."""

import argparse
import asyncio
import json
import os
import re
import shutil
import struct
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.road_mutation import (
    RoadReadback,
    RoadRequest,
    RoadSegmentIntent,
    admit_segment,
    verify_segment,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState, SecureAdminSession

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

PACKAGES = Path(__file__).resolve().parents[1]
CANDIDATES = tuple(
    (y * 64 + x, y * 64 + x + 1) for y in (8, 20, 32, 44) for x in (4, 12, 20, 28, 36, 44, 52, 60)
)
MAX_COST = 10000  # Authorized ceiling in native GBP, never a construction estimate.


class RoadSecureSession(SecureAdminSession):
    """Only the three narrow road-proof operations extend the secure write policy."""

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = RoadRequest.model_validate_json(decode_gamescript(frame[3:]))
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


def prepare(directory: Path, *, freight: bool = False) -> PreparedProof:
    """Prepare only. No OpenTTD process or Admin connection is created."""
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise ValueError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        with os.fdopen(os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as f:
            f.write(key._secret)
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
        script_name = "RoadFreightProof" if freight else "RoadMutationProof"
        package_name = "road_freight_package" if freight else "road_mutation_package"
        config += (
            "\n[game_creation]\nmap_x = 6\nmap_y = 6\nlandscape = temperate\n"
            "starting_year = 1950\nland_generator = 1\ngeneration_seed = 42\n"
            "[difficulty]\nmax_no_competitors = 0\n"
            "[ai]\nai_in_multiplayer = true\n[misc]\ngraphicsset = OpenGFX\n"
            f"[game_scripts]\n{script_name} = \n"
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
        for source, parent, name in (
            (PACKAGES / package_name, workspace.game, script_name),
            (PACKAGES / "road_company_package", workspace.ai, "RoadProofCompany"),
        ):
            target = parent / name
            target.mkdir()
            for file in ("info.nut", "main.nut"):
                shutil.copyfile(source / file, target / file)
        argv = launch_argv(BINARY.resolve(), workspace.config, reservation.game_port)
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
        for package in (package_name, "road_company_package"):
            for path in (PACKAGES / package).glob("*.nut"):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(p): sha256(p)
                for p in workspace.root.rglob("*")
                if p.is_file() and p.name != ".admin-secret"
            }
        )
        metadata = dict(
            schema="road-freight-infrastructure-prelaunch-v1"
            if freight
            else "first-company-road-prelaunch-v1",
            attempt=1 if freight else 2,
            workspace=str(workspace.root),
            binary_sha256=BINARY_SHA256,
            argv=list(argv),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            world=dict(
                source="GENERATED_DISPOSABLE_WORLD",
                source_save=None,
                seed=42,
                width=64,
                height=64,
                landscape=0,
                starting_year=1950,
            ),
            save_policy="owned before.sav and after.sav, no load, no existing save",
            plan_policy=dict(
                company=0,
                candidates=CANDIDATES,
                mode="road",
                max_cost=MAX_COST,
                command=(
                    "BuildRoadFull(start,end); BuildRoadStation(start-1,start,TRUCK,NEW); "
                    "BuildRoadDepot(end+1,end)"
                    if freight
                    else "GSRoad.BuildRoad(start,end)"
                ),
                identity="final intent binds fresh native facts and this seal",
            ),
            expected_readback=dict(
                before=(
                    "all four horizontal tiles vacant, flat, equal height, unowned; three positive "
                    "native costs affordable by company 0"
                    if freight
                    else "both adjacent tiles vacant, buildable, unowned, affordable by company 0"
                ),
                after=(
                    "owned truck stop, two full road tiles, depot, all linked bidirectionally"
                    if freight
                    else "both tiles contain connected road owned by company 0"
                ),
                independent_query=(
                    "read operation after each construction; stop on mismatch"
                    if freight
                    else "read operation after the single build request"
                ),
                receipt="plan-bound only after build result and independent native readback agree",
            ),
            bootstrap_command="start_ai RoadProofCompany",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                (
                    "app.simulation.openttd.proof.road_freight_infrastructure"
                    if freight
                    else "app.simulation.openttd.proof.road_mutation"
                ),
                "run",
                str(directory),
            ],
            budgets=dict(
                launches=1,
                connection_attempts=1,
                requests=38 if freight else 34,
                real_builds=3 if freight else 1,
                response_bytes=512,
                gsadmin_bytes=1450,
                retries=0,
                reconnects=0,
                readiness_seconds=45,
                request_seconds=10,
                total_seconds=180,
            ),
            cleanup=[
                "close secure session",
                "quit and reap process",
                "verify endpoints",
                "retain logs and saves",
                "remove credential",
                "dispose owned workspace",
            ],
            authorization="user authorized at most one launch after all preflight gates pass",
            frozen=frozen,
        )
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
    finally:
        reservation.close()


def reopen(directory: Path) -> PreparedProof:
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    workspace = RuntimeWorkspace.reopen(Path(metadata["workspace"]))
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


def preflight(prepared: PreparedProof) -> None:
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    if (directory / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    verify_freeze(metadata["frozen"])
    if metadata["plan_policy"]["candidates"] != [list(p) for p in CANDIDATES]:
        raise ValueError("frozen bounded candidate policy mismatch")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    backend = NativeBackend(authorized_one_launch=True)
    backend.preflight(prepared)
    backend.validate_launch(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()


async def wait_log(backend, prepared, marker):
    deadline = time.monotonic() + 45
    while True:
        backend.health()
        text = prepared.spec.stdout_path.read_text(
            errors="replace"
        ) + prepared.spec.stderr_path.read_text(errors="replace")
        if marker in text:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("explicit native readiness marker missing: " + marker)
        await asyncio.sleep(0.05)


def console(backend, command: str):
    if backend.process is None or backend.process.stdin is None:
        raise ValueError("owned console missing")
    backend.process.stdin.write(command.encode() + b"\n")
    backend.process.stdin.flush()


def owned_save_path(prepared, name: str) -> Path:
    """Resolve a native console filename within the authorized artifact directory."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) is None:
        raise ValueError("invalid owned native save name")
    directory = prepared.directory.absolute()
    if ".." in directory.parts or any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("native save directory alias or symlink")
    if not directory.is_dir() or any(c in str(directory) for c in '\n\r"\\'):
        raise ValueError("invalid native save directory")
    path = directory / (name + ".sav")
    if path.exists() or path.is_symlink():
        raise ValueError("refusing to overwrite or redirect protected native save")
    return path


async def save(backend, prepared, name, *, diagnostic=False):
    def health():
        if diagnostic:
            # A known startup script error must not prevent retaining a diagnostic save.
            # Never bypass process liveness or fresh save-command failures.
            if backend.process is None or backend.process.poll() is not None:
                raise RuntimeError("OpenTTD exited before diagnostic save")
        else:
            backend.health()

    if diagnostic:
        health()
    path = owned_save_path(prepared, name)
    logs = (prepared.spec.stdout_path, prepared.spec.stderr_path)
    offsets = [log.stat().st_size for log in logs]
    # OpenTTD 15.3 ConSave appends .sav and uses SAVE_DIR for relative names.
    # Supply an absolute, quoted name; never infer the native directory from cwd.
    console(backend, 'save "' + str(path.with_suffix("")) + '"')
    marker = "Map successfully saved to '" + str(path) + "'."
    deadline = time.monotonic() + 15
    while True:
        health()
        fresh = []
        for log, offset in zip(logs, offsets, strict=True):
            with log.open("rb") as stream:
                stream.seek(offset)
                fresh.append(stream.read().decode(errors="replace"))
        text = "\n".join(fresh)
        count = text.count(marker)
        if count > 1:
            raise ValueError("duplicate native save completion acknowledgement")
        if "Saving map failed." in text or "Game save failed" in text:
            raise ValueError("native save command failed")
        if count == 1:
            if path.is_symlink() or not path.is_file():
                raise ValueError("acknowledged native save missing or nonregular")
            if any(p.is_symlink() for p in path.parents):
                raise ValueError("native save directory redirected")
            if path.stat().st_size == 0:
                raise ValueError("acknowledged native save empty")
            return sha256(path)
        if time.monotonic() >= deadline:
            raise TimeoutError("owned native save completion missing")
        await asyncio.sleep(0.05)


async def exchange(session, request, directory, *, response_type=RoadReadback):
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    async with asyncio.timeout(10):
        while True:
            chunk = await session.receive()
            if not chunk:
                raise ConnectionError("road proof stream disconnected")
            for kind, payload in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected road-proof packet")
                response = decode_gamescript(payload)
                (directory / (request.request_id + "-response.json")).write_bytes(response)
                return response_type.parse_for(request, response)


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
        requests=0,
        construction="NOT_EXECUTED",
        status="FAILED",
    )
    frames = []
    try:
        async with asyncio.timeout(180):
            await backend.launch(prepared)
            result["native_launches"] = 1
            await wait_log(backend, prepared, "ROAD_MUTATION_READY")
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
            session = await RoadSecureSession.connect_secure(
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
                request = RoadRequest(
                    op="inspect",
                    request_id=f"inspect-{index}",
                    plan=seal,
                    company=0,
                    start=start,
                    end=end,
                    max_cost=MAX_COST,
                )
                value = await exchange(session, request, directory)
                result["requests"] += 1
                if value.status == "INVALID_COMPANY":
                    raise ValueError("native company invalid")
                if value.status == "READY":
                    before = value
                    break
            if before is None:
                raise ValueError("no native-feasible segment in frozen bounded candidates")
            intent = admit_segment(
                before, prelaunch_digest=seal, source_save_digest=before_save, max_cost=MAX_COST
            )
            write_json(directory / "plan.json", intent.model_dump(mode="json"))
            request = RoadRequest(
                op="build",
                request_id="build-1",
                plan=intent.digest,
                company=intent.company,
                start=intent.start,
                end=intent.end,
                max_cost=intent.max_cost,
            )
            built = await exchange(session, request, directory)
            result["requests"] += 1
            result["construction"] = built.status
            read = request.model_copy(update={"op": "read", "request_id": "read-1"})
            after = await exchange(session, read, directory)
            result["requests"] += 1
            receipt = verify_segment(intent, before, built, after)
            receipt["before_save_sha256"] = before_save
            receipt["after_save_sha256"] = await save(backend, prepared, "after")
            write_json(directory / "receipt.json", receipt)
            result["status"] = "NATIVE_STATE_VERIFIED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
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
    """Replay actual retained request/response semantics; never trust a success label."""
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or sha256(directory / name) != digest:
            raise ValueError("artifact manifest mismatch")
    frames = json.loads((directory / "frames.json").read_text())
    outbound = [bytes.fromhex(frame) for direction, frame in frames if direction == "outbound"]
    inbound = [bytes.fromhex(frame) for direction, frame in frames if direction == "inbound"]
    replies = []
    for frame in inbound:
        for kind, body in AdminFrameDecoder().feed_frames(frame):
            if kind == SERVER_GAMESCRIPT:
                replies.append(decode_gamescript(body))
    requests = sorted(directory.glob("*-request.json"))
    if len(requests) > 34:
        raise ValueError("request budget exceeded")
    for path in requests:
        raw = path.read_bytes()
        response = path.with_name(path.name.replace("-request.json", "-response.json")).read_bytes()
        if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
            raise ValueError("retained exchange lacks unique secure-session frame evidence")
    if sum(RoadRequest.model_validate_json(p.read_bytes()).op == "build" for p in requests) != 1:
        raise ValueError("exactly one construction request required")
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    if (
        runtime["encrypted"] is not True
        or runtime["welcome"]["revision"] != "15.3"
        or (result["native_launches"], result["connections"], result["status"])
        != (1, 1, "NATIVE_STATE_VERIFIED")
    ):
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    intent = RoadSegmentIntent.model_validate_json((directory / "plan.json").read_bytes())
    values = {}
    for name in ("build-1", "read-1"):
        q = RoadRequest.model_validate_json((directory / (name + "-request.json")).read_bytes())
        values[name] = RoadReadback.parse_for(
            q, (directory / (name + "-response.json")).read_bytes()
        )
    before = next(
        RoadReadback.model_validate_json(p.read_bytes())
        for p in directory.glob("inspect-*-response.json")
        if RoadReadback.model_validate_json(p.read_bytes()).digest == intent.before_digest
    )
    expected = verify_segment(intent, before, values["build-1"], values["read-1"])
    actual = json.loads((directory / "receipt.json").read_text())
    expected.update(
        before_save_sha256=sha256(directory / "before.sav"),
        after_save_sha256=sha256(directory / "after.sav"),
    )
    if intent.source_save_digest != expected["before_save_sha256"]:
        raise ValueError("intent source save mismatch")
    if expected != actual or sha256(directory / "PRELAUNCH.json") != intent.prelaunch_digest:
        raise ValueError("retained receipt / plan / save mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_text())
    if not all(
        cleanup.get(k) is True
        for k in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
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
    elif args.command == "verify":
        print(json.dumps(verify_receipt(directory), sort_keys=True))
    elif args.command == "preflight":
        preflight(reopen(directory))
        print("PREFLIGHT PASS")
    else:
        result = asyncio.run(run(reopen(directory)))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["status"] == "NATIVE_STATE_VERIFIED" else 1)


if __name__ == "__main__":
    main()
