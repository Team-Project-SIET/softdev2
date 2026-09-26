#!/usr/bin/env python3
"""Small OpenTTD-shaped child for T07 process/observer lifecycle tests."""

import configparser
import os
import select
import shutil
import signal
import socket
import struct
import sys
import threading
from datetime import date
from pathlib import Path


def frame(packet_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HB", len(payload) + 3, packet_id) + payload


def read_frame(connection: socket.socket) -> tuple[int, bytes]:
    def read_exactly(size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            chunk = connection.recv(size - len(result))
            if not chunk:
                raise EOFError
            result.extend(chunk)
        return bytes(result)

    header = read_exactly(2)
    size = struct.unpack("<H", header)[0]
    body = read_exactly(size - 2)
    return body[0], body[1:]


config_path = Path(sys.argv[sys.argv.index("-c") + 1])
workspace = config_path.parent
mode_path = Path(__file__).parent / "mode.txt"
if not mode_path.exists():
    mode_path = Path(__file__).parent / "lib" / "mode.txt"
mode = mode_path.read_text().strip()
config = configparser.ConfigParser()
config.read(config_path)
secrets = configparser.ConfigParser()
secrets.read(workspace / "secrets.cfg")
game_port = int(config["network"]["server_port"])
admin_port = int(config["network"]["server_admin_port"])
start_day = date(1950, 1, 1).toordinal() + 365
password = secrets["network"]["admin_password"]
lock = threading.Lock()
connection: socket.socket | None = None
commands = workspace / "commands.log"

if mode == "exit_early":
    sys.exit(4)
if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

game_tcp = socket.socket()
game_tcp.bind(("127.0.0.1", game_port))
game_tcp.listen()
game_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
if mode != "missing_udp":
    game_udp.bind(("127.0.0.1", game_port))
admin = socket.socket()
admin.bind(("127.0.0.1", admin_port))
admin.listen()

if mode == "large_output":
    os.write(1, b"o" * 1_000_000 + b"\n")
    os.write(2, b"e" * 1_000_000 + b"\n")


def send(data: bytes) -> None:
    global connection
    with lock:
        if connection is not None:
            connection.sendall(data)


def peer() -> None:
    global connection
    try:
        conn, _ = admin.accept()
        connection = conn
        packet_id, payload = read_frame(conn)
        if packet_id != 0:
            return
        if mode == "bad_auth" or not payload.startswith(password.encode() + b"\0"):
            send(frame(102, b"\x0a"))
            return
        if mode == "bad_protocol":
            send(frame(103, b"\x03\x00"))
            return
        protocol = (
            b"\x02"
            + b"".join(
                struct.pack("<BHH", 1, kind, mask)
                for kind, mask in ((0, 63), (2, 65), (3, 61), (4, 61))
            )
            + b"\x00"
        )
        welcome = b"Server\x0013.4\x00\x01\x00" + struct.pack("<IBIHH", 17, 0, start_day, 256, 256)
        if mode == "wrong_identity":
            welcome = b"Server\0wrong-revision\0\x01\0" + struct.pack(
                "<IBIHH", 17, 0, start_day, 256, 256
            )
        send(frame(103, protocol) + frame(104, welcome))
        if mode != "no_date":
            send(frame(107, struct.pack("<I", start_day)))
        while True:
            packet_id, payload = read_frame(conn)
            if packet_id == 7:
                send(frame(126, payload))
    except EOFError, BrokenPipeError, ConnectionResetError, OSError:
        return


thread = threading.Thread(target=peer, daemon=True)
thread.start()


def input_lines():
    if mode in {"noisy_stdio_select", "stdio_read_ahead_probe"}:
        read_count = 0
        while True:
            if mode == "stdio_read_ahead_probe" and read_count == 1:
                ready, _, _ = select.select([sys.stdin], [], [], 0)
                print(
                    "fd-ready-after-pause" if ready else "fd-empty-after-pause",
                    file=sys.stderr,
                    flush=True,
                )
                read_count += 1
            readable, _, _ = select.select([sys.stdin], [], [], 0.05)
            if readable:
                line = sys.stdin.readline()
                if not line:
                    return
                read_count += 1
                yield line
    else:
        yield from sys.stdin


for line in input_lines():
    command = line.strip()
    with commands.open("a") as output:
        output.write(line)
    if command == "echo __T09_DIRECT_STDIN_PROBE__":
        print("__T09_DIRECT_STDIN_PROBE__", flush=True)
    if command == "exec scripts/t09_exec_probe.scr":
        script = workspace / "scripts/t09_exec_probe.scr"
        if script.is_file() and script.read_bytes() == b"echo __T09_EXEC_PROBE__\n":
            print("__T09_EXEC_PROBE__", flush=True)
        else:
            print("Script file 'scripts/t09_exec_probe.scr' not found.", flush=True)
    if command == "exec scripts/t09_missing.scr":
        print("Script file 'scripts/t09_missing.scr' not found.", flush=True)
    if command == "exec scripts/live_pause_barrier.scr":
        script = (workspace / "scripts/live_pause_barrier.scr").read_text()
        if script != "pause\necho __LIVE_PAUSE_BARRIER_DONE__\n":
            sys.exit(5)
        if mode == "pause_exit":
            sys.exit(4)
        if mode == "pause_close_stdout":
            os.close(1)
        elif mode == "pause_shutdown":
            send(frame(105))
        elif mode != "pause_no_marker":
            if mode == "noisy_stdio_select":
                os.write(1, b"ordinary AI log line\n" * 30_000)
            print("__LIVE_PAUSE_BARRIER_DONE__", flush=True)
    if command == "exec scripts/live_unpause_barrier.scr":
        script = (workspace / "scripts/live_unpause_barrier.scr").read_text()
        if script != "unpause\necho __LIVE_UNPAUSE_BARRIER_DONE__\n":
            sys.exit(5)
        if mode == "unpause_exit":
            sys.exit(4)
        if mode == "unpause_close_stdout":
            os.close(1)
        elif mode == "unpause_shutdown":
            send(frame(105))
        elif mode != "unpause_no_marker":
            print("__LIVE_UNPAUSE_BARRIER_DONE__", flush=True)
    if command == "pause":
        print("dbg: [console] Executing cmdline: 'pause'", file=sys.stderr, flush=True)
    if mode == "noisy_stdio_select" and command == "save final":
        os.write(1, b"ordinary AI log line\n" * 30_000)
    if command in {"unpause", "exec scripts/live_unpause_barrier.scr"}:
        if mode == "eof_after_ready":
            with lock:
                if connection is not None:
                    connection.shutdown(socket.SHUT_RDWR)
                    connection.close()
                    connection = None
        elif mode == "shutdown_after_ready":
            send(frame(105))
        elif mode == "malformed_after_ready":
            send(frame(117, b"\x02\x01"))
        elif mode not in {"no_target", "no_date", "unpause_no_new_date"}:
            day = (
                start_day
                if mode == "unpause_same_date"
                else start_day - 1
                if mode == "unpause_older_date"
                else start_day + 1
                if mode == "save_valid_fixture"
                else start_day + (32 if mode == "overshoot" else 30)
            )
            send(frame(107, struct.pack("<I", day)))
    if command == "pause" and mode == "shutdown_on_pause":
        send(frame(105))
    if command.startswith("save "):
        basename = command[5:]
        if mode == "noisy_stdio_select":
            os.write(1, b"more ordinary output\n" * 30_000)
        if mode != "save_no_start":
            print("Saving map...", flush=True)
        if mode == "save_fail":
            print("Saving map failed.", flush=True)
        elif mode == "save_close_stdout":
            os.close(1)
        elif mode == "save_shutdown":
            send(frame(105))
        elif mode == "save_exit":
            sys.exit(4)
        elif mode != "save_no_terminal":
            if mode == "noisy_stdio_select":
                os.write(1, b"after start ordinary output\n" * 30_000)
            if mode != "save_missing":
                destination = workspace / "save" / f"{basename}.sav"
                if mode == "save_directory":
                    destination.mkdir()
                elif mode == "save_valid_fixture":
                    shutil.copyfile(Path(__file__).parent / "static.sav", destination)
                else:
                    destination.write_bytes(b"controlled save")
            name = "old_save" if mode == "save_wrong_name" else basename
            print(f"Map successfully saved to '{name}.sav'.", flush=True)
    if command == "quit" and mode not in {"hang_on_quit", "ignore_term"}:
        break

if connection is not None:
    connection.close()
admin.close()
game_tcp.close()
game_udp.close()
