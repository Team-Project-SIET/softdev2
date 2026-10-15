"""Structural proof ceilings; query accounting is distinct from owned-stream traffic."""

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType

from app.simulation.openttd.structural_world_session import (
    STRUCTURAL_PAGE_SIZE,
    STRUCTURAL_WORLD_SESSION_ID,
)

STRUCTURAL_REVISION = 1
STRUCTURAL_MODEL = "structural-world-correlated-channels-v1"
STRUCTURAL_PRELAUNCH_DIRECTORY = "openttd-15.3-structural-world-real-prelaunch"
STRUCTURAL_ATTEMPT_DIRECTORY = "openttd-15.3-structural-world-real-attempt1"

MAX_QUERY_OPERATIONS = 256 + 256 + 512
# Encryption enablement finishes the authentication exchange. The encrypted
# PROTOCOL/WELCOME frames follow it, before ACTIVE/configure_transport. Setup is
# explicitly performed outside the first query: UPDATE_FREQUENCY + PING + PONG.
# Each query's receipt accounts for its send/response/completion PING/PONG and
# any other decoded frames. Graceful QUIT is outbound only; TCP EOF is not a frame.
MAX_TOTAL_POST_AUTH_FRAMES = 2 + 3 + MAX_QUERY_OPERATIONS + 1
FRAME_LIMITS = MappingProxyType(
    {
        "establishment": 2,
        "setup": 3,
        "inventory": 256,
        "capability": 256,
        "catalog": 512,
        "cleanup": 1,
    }
)


class StructuralFrameBudgetExceeded(ValueError):
    """A frame was rejected before an outbound write or semantic admission."""


@dataclass
class StructuralFrameBudget:
    """Fail before admitting a frame beyond either its category or total ceiling.

    The secure session invokes observe at its encryption/decryption boundary,
    including establishment and graceful QUIT. Query receipts are correlated
    with these counters, never added again.
    """

    limits = FRAME_LIMITS
    maximum_frames = MAX_TOTAL_POST_AUTH_FRAMES
    query_phases = ("inventory", "capability", "catalog")

    _counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(FRAME_LIMITS, 0), init=False
    )

    phase: str = field(default="establishment", init=False)
    failed: bool = field(default=False, init=False)
    _frames: list[dict] = field(default_factory=list, init=False)

    def enter(self, phase: str) -> None:
        order = list(self.limits)
        if self.failed or phase not in order or order.index(phase) != order.index(self.phase) + 1:
            raise ValueError("Invalid structural accounting phase; no reset/resume")
        self.phase = phase

    def observe(self, direction: str, frame: bytes) -> None:
        if direction not in ("inbound", "outbound") or len(frame) < 3:
            raise ValueError("Malformed frame accounting input")
        category = "cleanup" if direction == "outbound" and frame[2] == 1 else self.phase
        record = dict(
            direction=direction,
            packet_type=frame[2],
            category=category,
            sha256=hashlib.sha256(frame).hexdigest(),
            admitted=False,
        )
        try:
            if self.failed and category != "cleanup":
                raise ValueError("Structural accounting failed; no later traffic")
            self.consume(category)
            record["admitted"] = True
        except BaseException:
            self.failed = True
            raise
        finally:
            if len(self._frames) < self.maximum_frames + 1:
                self._frames.append(record)

    def snapshot(self) -> dict:
        return dict(
            query_operations=self.query_operations,
            total_post_auth_frames=self.total_frames,
            categories=dict(self._counts),
            frames=[dict(row) for row in self._frames],
            failed=self.failed,
        )

    @property
    def query_operations(self) -> int:
        return sum(self._counts[p] for p in self.query_phases)

    @property
    def total_frames(self) -> int:
        return sum(self._counts.values())

    def consume(self, category: str, count: int = 1) -> None:
        if category not in self.limits or type(count) is not int or count <= 0:
            raise ValueError("invalid structural frame accounting")
        if (
            self._counts[category] + count > self.limits[category]
            or self.total_frames + count > self.maximum_frames
        ):
            raise StructuralFrameBudgetExceeded("structural post-auth frame budget exhausted")
        self._counts[category] += count


def structural_contract() -> dict:
    """Canonical production contract; execution still requires frozen authorization."""
    return {
        "proof_kind": "structural-world",
        "session_id": STRUCTURAL_WORLD_SESSION_ID,
        "industry_page_size": STRUCTURAL_PAGE_SIZE,
        "cargo_page_size": STRUCTURAL_PAGE_SIZE,
        "phase_order": ["inventory", "capability", "catalog", "assembly"],
        "max_application_requests": 32 + 32 + 32,
        "max_response_bytes": 16384 + 16384 + 16384,
        "max_query_operations": MAX_QUERY_OPERATIONS,
        "max_total_post_auth_frames": MAX_TOTAL_POST_AUTH_FRAMES,
        "frame_budget_derivation": {
            "encrypted_protocol_and_welcome": 2,
            "subscription_outbound": 2,
            "subscription_pong": 1,
            "query_operations": MAX_QUERY_OPERATIONS,
            "graceful_quit": 1,
        },
        "launches": 1,
        "connections": 1,
        "additional_command_types": 0,
        "phase_limits": {
            "inventory": {
                "requests": 32,
                "records": 32,
                "response_bytes": 16384,
                "query_operations": 256,
            },
            "capability": {
                "requests": 32,
                "records": 32,
                "response_bytes": 16384,
                "query_operations": 256,
            },
            "catalog": {
                "requests": 32,
                "records": 64,
                "response_bytes": 16384,
                "query_operations": 512,
            },
        },
        "application_limit": 512,
        "native_ceiling": 1450,
        "independent_inventory_source": None,
        "independent_capability_source": None,
        "independent_catalog_source": None,
        "production_history": "NOT INCLUDED",
        "p08_completion": False,
        "retries": 0,
        "reconnects": 0,
    }


def structural_contract_digest() -> str:
    return hashlib.sha256(
        json.dumps(structural_contract(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def structural_first_request():
    from app.simulation.openttd.industry_inventory import inventory_request_id
    from app.simulation.openttd.industry_page import IndustryPageRequest

    return IndustryPageRequest(
        inventory_request_id(STRUCTURAL_WORLD_SESSION_ID + "-inv", 1), None, 2
    )
