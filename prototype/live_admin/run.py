"""THROWAWAY: run exactly one real simulation with concurrent Admin telemetry.

Run from repository root: uv run python -m prototype.live_admin.run
Output under ignored artifacts/live-admin-proof; no database writes.
"""

import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import struct
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from prototype.live_admin.protocol import (
    CompanyEconomy,
    CompanyInfo,
    CompanyStats,
    Date,
    ServerProtocol,
    ServerWelcome,
    check_error,
    parse,
    receive,
    send,
)

OUTPUT = Path("artifacts/live-admin-proof").resolve()
TARGET_DAY = date(1950, 1, 1).toordinal() + 365 + 120


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def connect(port, process, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.returncode is not None:
            raise RuntimeError("Lab exited before Admin became ready")
        try:
            return await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1)
        except OSError, TimeoutError:
            await asyncio.sleep(0.05)
    raise TimeoutError("Admin readiness deadline expired")


async def listen(port, password, process, evidence):
    reader, writer = await connect(port, process)
    evidence["connected"] = True
    protocol = None
    welcomed = False
    quitting = False
    current_date = None
    economies = {}
    counts = Counter()
    with (OUTPUT / "telemetry.jsonl").open("w") as events:
        try:
            await send(writer, 0, f"{password}\0live-prototype\0v1\0".encode())
            handshake_deadline = time.monotonic() + 10
            while True:
                if not welcomed and time.monotonic() > handshake_deadline:
                    raise TimeoutError("Admin handshake deadline expired")
                try:
                    kind, payload = await asyncio.wait_for(receive(reader), 10)
                except asyncio.IncompleteReadError:
                    evidence["end"] = "eof"
                    if not quitting:
                        raise RuntimeError("Server closed before target date") from None
                    break
                check_error(kind, payload)
                counts[str(kind)] += 1
                event = parse(kind, payload)
                if event is not None:
                    record = {
                        "packet": kind,
                        "event": type(event).__name__,
                        "data": asdict(event),
                        "observed_monotonic": time.monotonic(),
                        "lab_running": process.returncode is None,
                    }
                    events.write(json.dumps(record) + "\n")
                    events.flush()
                if isinstance(event, ServerProtocol):
                    if event.version != 2:
                        raise RuntimeError(f"Unsupported Admin protocol {event.version}")
                    protocol = event
                    evidence["protocol"] = asdict(event)
                elif isinstance(event, ServerWelcome):
                    if protocol is None:
                        raise RuntimeError("Welcome before protocol")
                    if event.revision != "13.4" or not event.dedicated or event.seed != 17:
                        raise RuntimeError("Unexpected server identity")
                    welcomed = True
                    evidence["welcome"] = asdict(event)
                    print(
                        "Admin authenticated: OpenTTD 13.4, protocol=2, dedicated=true", flush=True
                    )
                    # Daily dates control stop; monthly stats/economy bound terminal output.
                    for update, frequency in ((0, 2), (2, 64), (3, 8), (4, 8)):
                        if protocol.frequencies.get(update, 0) & frequency != frequency:
                            raise RuntimeError("Server does not advertise required frequency")
                        await send(writer, 2, struct.pack("<HH", update, frequency))
                    for update in (0, 2, 3, 4):
                        if not protocol.frequencies.get(update, 0) & 1:
                            raise RuntimeError("Server does not advertise polling")
                        await send(writer, 3, struct.pack("<BI", update, 0xFFFFFFFF))
                elif isinstance(event, Date):
                    current_date = event
                    if event.day >= TARGET_DAY and not quitting:
                        required = {"103", "104", "107", "114", "117", "118"}
                        if not required <= counts.keys():
                            raise RuntimeError("Target reached without required telemetry")
                        evidence["stop_date"] = event.iso
                        evidence["quit_requested_while_lab_running"] = process.returncode is None
                        # Lifecycle only: exit normally, then Lab parses autosaves.
                        await send(writer, 5, b"quit\0")
                        quitting = True
                elif isinstance(event, CompanyInfo):
                    evidence.setdefault("companies", {})[str(event.company_id)] = asdict(event)
                elif isinstance(event, CompanyEconomy):
                    economies[event.company_id] = event
                elif isinstance(event, CompanyStats) and current_date is not None:
                    economy = economies.get(event.company_id)
                    if economy is not None:
                        sample = {
                            "date": current_date.iso,
                            "company": event.company_id,
                            "economy": asdict(economy),
                            "stats": asdict(event),
                        }
                        evidence.setdefault("samples", []).append(sample)
                        print(
                            f"{current_date.iso} company={event.company_id} "
                            f"money={economy.money} loan={economy.loan} "
                            f"income={economy.income} vehicles={sum(event.vehicles)} "
                            f"station_facilities={sum(event.stations)}",
                            flush=True,
                        )
                elif kind == 106:
                    evidence["end"] = "server_shutdown"
                    if not quitting:
                        raise RuntimeError("Server shut down before target date")
                    break
        finally:
            evidence["packet_counts"] = dict(counts)
            with contextlib.suppress(OSError):
                await send(writer, 1)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            evidence["socket_closed"] = True


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def cleanup(process):
    # Group includes Lab, its pool, resource tracker/forkserver and OpenTTD.
    if group_exists(process.pid):
        os.killpg(process.pid, signal.SIGTERM)
        for _ in range(50):
            if not group_exists(process.pid):
                break
            await asyncio.sleep(0.1)
        if group_exists(process.pid):
            os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def main():
    if OUTPUT.exists():
        raise RuntimeError(f"Proof output already exists: {OUTPUT}; refusing accidental rerun")
    OUTPUT.mkdir(parents=True)
    cache = Path("artifacts/experiments/cache").resolve()
    if cache.is_dir():
        (OUTPUT / "cache").symlink_to(cache, target_is_directory=True)
    password = secrets.token_hex(12)
    admin_port, game_port = available_port(), available_port()
    while admin_port == game_port:
        game_port = available_port()
    env = dict(
        os.environ,
        PROTOTYPE_ADMIN_PASSWORD=password,
        PROTOTYPE_ADMIN_PORT=str(admin_port),
        PROTOTYPE_GAME_PORT=str(game_port),
        PROTOTYPE_OUTPUT=str(OUTPUT),
    )
    evidence = {
        "started_utc": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "admin_port": admin_port,
        "game_port": game_port,
        "seed": 17,
        "duration_days": 120,
    }
    with (OUTPUT / "lab.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "prototype.live_admin.lab_seam",
            env=env,
            start_new_session=True,
            stdout=log,
            stderr=log,
        )
        evidence["lab_pid"] = process.pid
        started = time.monotonic()
        try:
            async with asyncio.timeout(600):
                await listen(admin_port, password, process, evidence)
                code = await process.wait()
            if code:
                raise RuntimeError(f"Lab worker exited with code {code}; inspect lab.log")
            result = json.loads((OUTPUT / "final-result.json").read_text())
            evidence["final_result"] = result
            evidence["verdict"] = "FEASIBLE"
            print(f"Lab final savegame parsed: {result['simulation_date']}", flush=True)
        except BaseException as exc:
            evidence["verdict"] = "NOT PROVEN"
            evidence["failure"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            await cleanup(process)
            evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
            evidence["lab_returncode"] = process.returncode
            evidence["process_group_gone"] = not group_exists(process.pid)
            for label, port in (("admin", admin_port), ("game", game_port)):
                with socket.socket() as sock:
                    evidence[label + "_port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
            (OUTPUT / "evidence.json").write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
