"""V1 operational bounds, independent of semantic native rollover evidence."""

import math
from dataclasses import dataclass
from types import MappingProxyType

from app.simulation.openttd.qualification_clock import (
    MAX_CLOCK_RESPONSE_BYTES,
    MAX_LIFETIME_RESPONSE_BYTES,
)


@dataclass(frozen=True)
class QualificationPollPolicy:
    interval: float = 1.0
    timeout: float = 300.0

    def __post_init__(self):
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (self.interval, self.timeout)
            )
            or not 1 <= self.interval <= self.timeout <= 300
        ):
            raise ValueError("bounded V1 polling policy requires interval>=1 and timeout<=300")

    @property
    def max_wait_polls(self):
        return math.ceil(self.timeout / self.interval) - 1

    @property
    def max_clock_requests(self):
        # Baseline + paced polls across BOTH waits + before/after each collection.
        return 1 + self.max_wait_polls + 2 + 2


V1_POLL_POLICY = QualificationPollPolicy()
MAX_CLOCK_REQUESTS = V1_POLL_POLICY.max_clock_requests
PHASE_BOUNDS = MappingProxyType(
    {
        "clock": (
            MAX_CLOCK_REQUESTS,
            MAX_CLOCK_REQUESTS * MAX_CLOCK_RESPONSE_BYTES,
            MAX_CLOCK_REQUESTS * 8,
        ),
        "anchor_structural": (96, 49152, 1024),
        "anchor_lifetime": (32, 32 * MAX_LIFETIME_RESPONSE_BYTES, 32 * 8),
        "final_structural": (96, 49152, 1024),
        "final_lifetime": (32, 32 * MAX_LIFETIME_RESPONSE_BYTES, 32 * 8),
        "production": (512, 171520, 4096),
    }
)
MAX_APPLICATION_REQUESTS = sum(v[0] for v in PHASE_BOUNDS.values())
MAX_RESPONSE_BYTES = sum(v[1] for v in PHASE_BOUNDS.values())
MAX_QUERY_OPERATIONS = sum(v[2] for v in PHASE_BOUNDS.values())
LIFECYCLE_FRAMES = 2 + 3 + 1
MAX_POST_AUTH_FRAMES = MAX_QUERY_OPERATIONS + LIFECYCLE_FRAMES


def qualification_resource_contract():
    return dict(
        poll_interval=V1_POLL_POLICY.interval,
        timeout=V1_POLL_POLICY.timeout,
        wait_polls=V1_POLL_POLICY.max_wait_polls,
        clock_requests=MAX_CLOCK_REQUESTS,
        phase_bounds={
            k: dict(requests=v[0], response_bytes=v[1], query_operations=v[2])
            for k, v in PHASE_BOUNDS.items()
        },
        application_requests=MAX_APPLICATION_REQUESTS,
        response_bytes=MAX_RESPONSE_BYTES,
        query_operations=MAX_QUERY_OPERATIONS,
        lifecycle_frames=LIFECYCLE_FRAMES,
        post_auth_frames=MAX_POST_AUTH_FRAMES,
    )
