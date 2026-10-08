"""Linux proof cleanup: listener/connection closure is not immediate port reuse.

Only the frozen IPv4 loopback endpoints are supported. No connections, bind
attempts, sleeps or retries are performed. Missing/ambiguous kernel evidence
fails closed; IPv6 wildcard coverage is conservatively treated as a conflict.
"""

import ipaddress
import json
import socket
import sys
from pathlib import Path

TABLES = ("tcp", "tcp6", "udp", "udp6")
POLICY = "linux-kernel-endpoint-closure-v1"


def endpoint_cleanup_contract():
    return dict(
        policy=POLICY,
        family="AF_INET",
        host="127.0.0.1",
        required=[
            "owned_process_reaped",
            "reservation_released",
            "listener_closed",
            "connection_closed",
            "game_udp_closed",
        ],
        kernel_tables=list(TABLES),
        allowed_residual_state="TCP_TIME_WAIT_ONLY",
        ambiguous_state="FAIL_CLOSED",
        ipv6_wildcard="FAIL_CLOSED_UNLESS_COVERAGE_DISPROVED",
        immediate_rebindability_required=False,
        connection_probe=False,
        sleeps=0,
        retries=0,
    )


def _address(value: str, ipv6: bool) -> tuple[str, int]:
    address, port = value.split(":")
    size = 32 if ipv6 else 8
    if len(address) != size or len(port) != 4:
        raise ValueError("Malformed kernel endpoint address")
    raw = b"".join(
        int(address[i : i + 8], 16).to_bytes(4, sys.byteorder) for i in range(0, size, 8)
    )
    return str(ipaddress.ip_address(raw)), int(port, 16)


def kernel_socket_rows() -> list[dict]:
    """Read all families/transports in this proof process's network namespace."""
    if sys.platform != "linux":
        raise ValueError("Linux kernel endpoint evidence required")
    rows = []
    for table in TABLES:
        lines = (Path("/proc/self/net") / table).read_text().splitlines()
        if not lines or "local_address" not in lines[0] or "st" not in lines[0].split():
            raise ValueError("Missing kernel socket table header")
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 10 or len(fields[3]) != 2:
                raise ValueError("Malformed kernel socket row")
            local, local_port = _address(fields[1], table.endswith("6"))
            remote, remote_port = _address(fields[2], table.endswith("6"))
            state = int(fields[3], 16)
            if not 1 <= state <= 12:
                raise ValueError("Unknown kernel socket state")
            rows.append(
                dict(
                    table=table,
                    local=local,
                    local_port=local_port,
                    remote=remote,
                    remote_port=remote_port,
                    state=state,
                    inode=int(fields[9]),
                )
            )
    return rows


def _covers_ipv4(address: str) -> bool:
    value = ipaddress.ip_address(address)
    return (
        value.is_unspecified
        or str(value) == "127.0.0.1"
        or (isinstance(value, ipaddress.IPv6Address) and str(value.ipv4_mapped) == "127.0.0.1")
    )


def verify_cleanup_endpoints(prepared, cleanup: dict, reservation=None, *, family=socket.AF_INET):
    """Require reaped ownership and no live endpoint sockets; retain TIME_WAIT.

    A tcp6 wildcard row does not expose IPV6_V6ONLY in procfs. Reject it rather
    than guessing whether it covers IPv4. UDP bound sockets also reject cleanup.
    Both local server tuples and remote client tuples are checked. This is a
    post-reap observation, not an atomic promise that another process cannot
    claim the port later.
    """
    if (
        cleanup.get("reaped") is not True
        or cleanup.get("remaining_processes") != []
        or bool(cleanup.get("cleanup_error"))
    ):
        raise ValueError("Endpoint closure requires unambiguous owned process reap")
    if reservation is not None and reservation.sockets:
        raise ValueError("Endpoint reservation still owned/open")
    if family != socket.AF_INET:
        raise ValueError("Frozen IPv4 endpoint family required")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    ports = prepared.endpoints
    if (
        type(ports) is not tuple
        or len(ports) != 2
        or any(type(p) is not int or not 0 < p < 65536 for p in ports)
        or ports[0] == ports[1]
        or ports != (metadata["game_port"], metadata["admin_port"])
    ):
        raise ValueError("Frozen endpoint identity mismatch")
    matched = []
    for row in kernel_socket_rows():
        local = row["local_port"] in ports and _covers_ipv4(row["local"])
        remote = row["remote_port"] in ports and _covers_ipv4(row["remote"])
        if not (local or remote):
            continue
        if row["table"].startswith("udp") or row["state"] != 6:
            raise ValueError(f"Live or ambiguous endpoint socket: {row}")
        matched.append(dict(row, state="TIME_WAIT"))
    return dict(
        sockets_closed=True,
        endpoint_verification=dict(
            policy=POLICY,
            family="AF_INET",
            host="127.0.0.1",
            game_port=ports[0],
            admin_port=ports[1],
            process_reaped=True,
            reservation_released=True,
            listener_closed=True,
            connection_closed=True,
            kernel_states=matched,
            immediate_rebindability_required=False,
            connection_probe=False,
        ),
    )
