"""Linux endpoint evidence for the opt-in T17 smoke; no simulator launch."""

import errno
import os
import re
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_SOCKET_INODE = re.compile(r"socket:\[(\d+)\]\Z")
_LOOPBACK_OR_WILDCARD = {"0100007F", "00000000"}
_DUAL_STACK_ADDRESSES = {
    "00000000000000000000000000000000",  # IPv6 wildcard may also accept IPv4.
    "0000000000000000FFFF00000100007F",  # IPv4-mapped 127.0.0.1.
}


@dataclass(frozen=True)
class Endpoint:
    role: str
    protocol: str
    port: int


@dataclass(frozen=True)
class PortEvidence:
    role: str
    protocol: str
    port: int
    bind_address: str
    address_family: str
    bind_errno: int | None
    tcp_states: tuple[str, ...]
    socket_inodes: tuple[str, ...]
    state: str
    owner_pids: tuple[int, ...]
    owner_groups: tuple[int, ...]
    elapsed_seconds: float
    process_checks_passed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class PortReleaseError(AssertionError):
    def __init__(self, evidence: tuple[PortEvidence, ...]) -> None:
        self.evidence = evidence
        latest = evidence[-1]
        super().__init__(
            f"{latest.role} {latest.protocol} 127.0.0.1:{latest.port} "
            f"AF_INET state={latest.state} errno={latest.bind_errno} "
            f"tcp_states={latest.tcp_states} inodes={latest.socket_inodes} "
            f"owners={latest.owner_pids} groups={latest.owner_groups} "
            f"elapsed={latest.elapsed_seconds:.3f}s "
            f"process_checks_passed={latest.process_checks_passed}"
        )


def _bound_inodes(endpoint: Endpoint) -> set[str]:
    result: set[str] = set()
    for family in ("", "6"):
        filename = endpoint.protocol + family
        addresses = _LOOPBACK_OR_WILDCARD if not family else _DUAL_STACK_ADDRESSES
        for line in Path("/proc/net", filename).read_text().splitlines()[1:]:
            fields = line.split()
            address, encoded_port = fields[1].split(":")
            if (
                address in addresses
                and int(encoded_port, 16) == endpoint.port
                and (endpoint.protocol == "udp" or fields[3] == "0A")
            ):
                result.add(fields[9])
    return result


def _tcp_states(endpoint: Endpoint) -> tuple[str, ...]:
    if endpoint.protocol != "tcp":
        return ()
    names = {"0A": "LISTEN", "06": "TIME_WAIT", "08": "CLOSE_WAIT"}
    states: set[str] = set()
    for family in ("", "6"):
        addresses = _LOOPBACK_OR_WILDCARD if not family else _DUAL_STACK_ADDRESSES
        for line in Path("/proc/net", "tcp" + family).read_text().splitlines()[1:]:
            fields = line.split()
            address, encoded_port = fields[1].split(":")
            if address in addresses and int(encoded_port, 16) == endpoint.port:
                states.add(names.get(fields[3], fields[3]))
    return tuple(sorted(states))


def _owners(inodes: set[str]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    pids: set[int] = set()
    groups: set[int] = set()
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for descriptor in (process / "fd").iterdir():
                match = _SOCKET_INODE.fullmatch(os.readlink(descriptor))
                if match is not None and match.group(1) in inodes:
                    pid = int(process.name)
                    pids.add(pid)
                    groups.add(os.getpgid(pid))
                    break
        except OSError, PermissionError, ProcessLookupError:
            continue
    return tuple(sorted(pids)), tuple(sorted(groups))


def _bind_errno(endpoint: Endpoint) -> int | None:
    kind = socket.SOCK_STREAM if endpoint.protocol == "tcp" else socket.SOCK_DGRAM
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", endpoint.port))
        except OSError as exc:
            return exc.errno
    return None


def _inspect(
    endpoint: Endpoint, owned_pgid: int, started: float, process_checks_passed: bool
) -> PortEvidence:
    inodes = _bound_inodes(endpoint)
    pids, groups = _owners(inodes) if inodes else ((), ())
    bind_errno = _bind_errno(endpoint)
    if bind_errno == errno.EADDRINUSE and not inodes:
        # A different process may claim the port between the first snapshot and
        # the bind. Resample before labeling the conflict as connection state.
        inodes = _bound_inodes(endpoint)
        pids, groups = _owners(inodes) if inodes else ((), ())
    if owned_pgid in groups:
        state = "owned_listener"
    elif inodes and pids:
        state = "unrelated_reuse"
    elif inodes:
        state = "unattributed_listener"
    elif bind_errno == errno.EADDRINUSE:
        state = "bind_blocked_without_listener"
    elif bind_errno is not None:
        state = "bind_error"
    else:
        state = "released"
    return PortEvidence(
        endpoint.role,
        endpoint.protocol,
        endpoint.port,
        "127.0.0.1",
        "AF_INET",
        bind_errno,
        _tcp_states(endpoint),
        tuple(sorted(inodes)),
        state,
        pids,
        groups,
        time.monotonic() - started,
        process_checks_passed,
    )


def verify_port_release(
    game_port: int,
    admin_port: int,
    *,
    owned_pgid: int,
    timeout_seconds: float = 1.0,
    process_checks_passed: bool,
) -> tuple[PortEvidence, ...]:
    """Require no owned endpoint, with one monotonic deadline for all three sockets."""
    if timeout_seconds <= 0:
        raise ValueError("port-release deadline must be positive")
    if not process_checks_passed:
        raise ValueError("process ownership checks must complete before port verification")
    started = time.monotonic()
    deadline = started + timeout_seconds
    endpoints = (
        Endpoint("game", "tcp", game_port),
        Endpoint("game", "udp", game_port),
        Endpoint("admin", "tcp", admin_port),
    )
    evidence: list[PortEvidence] = []
    for endpoint in endpoints:
        while True:
            item = _inspect(endpoint, owned_pgid, started, process_checks_passed)
            if item.state in {"released", "bind_blocked_without_listener", "unrelated_reuse"}:
                evidence.append(item)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PortReleaseError((*evidence, item))
            time.sleep(min(0.02, remaining))
    return tuple(evidence)
