"""Bounded opt-in point samples; transitions are bracketed inferences, never events.

These read-only queries cannot create vehicles. Native collection remains unproven.
A sampler must retain raw responses, fixed vehicle/service identities, and gaps.
"""

import json
from dataclasses import dataclass, field

from pydantic import StrictBool, StrictInt, model_validator

from app.planning.domain import Contract


class VehicleSample(Contract):
    protocol: StrictInt
    type: str
    request_id: str
    status: str
    service: StrictInt
    vehicle: StrictInt
    tick: StrictInt
    economy_date: StrictInt
    tile: StrictInt
    state: StrictInt
    speed: StrictInt
    load: StrictInt
    capacity: StrictInt
    queue: StrictInt
    stopped_in_depot: StrictBool
    at_station: StrictBool
    source_tile: StrictInt
    destination_tile: StrictInt
    profit_this_year: StrictInt | None = None
    profit_last_year: StrictInt | None = None
    running_cost_rate_per_year: StrictInt | None = None

    @model_validator(mode="after")
    def measurement_bounds(self):
        if (
            self.protocol != 1
            or self.type != "continuous-telemetry-result"
            or self.status != "ok"
            or self.service not in (0, 1, 2)
            or min(
                self.vehicle,
                self.tick,
                self.economy_date,
                self.tile,
                self.speed,
                self.load,
                self.queue,
                self.source_tile,
                self.destination_tile,
            )
            < 0
            or self.capacity <= 0
            or self.load > self.capacity
            or (self.stopped_in_depot and (self.at_station or self.speed != 0))
        ):
            raise ValueError("invalid telemetry measurement or state coherence")
        return self


def telemetry_request(request_id: str, service: int, vehicle: int) -> bytes:
    if (
        not 1 <= len(request_id) <= 32
        or not request_id.isascii()
        or not request_id.replace("-", "").isalnum()
        or type(service) is not int
        or service not in (0, 1, 2)
        or type(vehicle) is not int
        or vehicle < 0
    ):
        raise ValueError("invalid telemetry request")
    return json.dumps(
        dict(
            protocol=1,
            type="continuous-telemetry",
            request_id=request_id,
            service=service,
            vehicle=vehicle,
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def decode_telemetry(raw: bytes, request: bytes) -> VehicleSample:
    """Accept raw JSON bytes (transport NUL removed), bound and correlate identity."""
    if not 0 < len(raw) <= 1450:
        raise ValueError("telemetry payload exceeds native bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate telemetry key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    sample = VehicleSample.model_validate(value)
    q = json.loads(request)
    if (
        sample.protocol != 1
        or sample.type != "continuous-telemetry-result"
        or sample.status != "ok"
        or sample.request_id != q["request_id"]
        or sample.service != q["service"]
        or sample.vehicle != q["vehicle"]
        or min(
            sample.tick,
            sample.economy_date,
            sample.tile,
            sample.speed,
            sample.load,
            sample.queue,
            sample.source_tile,
            sample.destination_tile,
        )
        < 0
        or sample.capacity <= 0
        or sample.load > sample.capacity
    ):
        raise ValueError("invalid telemetry identity or measurement")
    return sample


@dataclass
class SampleWindow:
    """Fixed finite stream. Gaps suppress event inference; zero speed is not idle."""

    max_tick_gap: int
    max_samples: int = 20000
    samples: list[VehicleSample] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    candidate_cycles: list[dict] = field(default_factory=list)
    _departure: dict | None = None

    def __post_init__(self):
        if not 1 <= self.max_tick_gap <= 10000 or not 1 <= self.max_samples <= 20000:
            raise ValueError("invalid telemetry bounds")

    def append(self, sample: VehicleSample):
        sample = VehicleSample.model_validate(sample.model_dump())
        if len(self.samples) >= self.max_samples:
            raise ValueError("telemetry sample budget exhausted")
        if self.samples:
            previous = self.samples[-1]
            if (
                sample.service,
                sample.vehicle,
                sample.capacity,
                sample.source_tile,
                sample.destination_tile,
            ) != (
                previous.service,
                previous.vehicle,
                previous.capacity,
                previous.source_tile,
                previous.destination_tile,
            ):
                raise ValueError("telemetry stream identity changed")
            if sample.tick <= previous.tick or sample.economy_date < previous.economy_date:
                raise ValueError("telemetry clock did not advance")
            gap = sample.tick - previous.tick > self.max_tick_gap
            labels = ["sampling_gap"] if gap else []
            if not gap:
                if sample.load != previous.load:
                    labels.append(
                        "net_load_increase" if sample.load > previous.load else "net_load_decrease"
                    )
                for name, tile in (
                    ("source", sample.source_tile),
                    ("destination", sample.destination_tile),
                ):
                    if sample.tile == tile and previous.tile != tile:
                        labels.append(f"possible_{name}_arrival")
                    if previous.tile == tile and sample.tile != tile:
                        labels.append(f"possible_{name}_departure")
                if sample.stopped_in_depot != previous.stopped_in_depot:
                    labels.append("stopped_in_depot_change")
                if sample.load > previous.load and (sample.at_station or previous.at_station):
                    labels.append("possible_loading_episode")
                if sample.load < previous.load and (sample.at_station or previous.at_station):
                    labels.append("possible_unloading_episode")
                if "possible_source_departure" in labels and previous.load > 0:
                    self._departure = dict(
                        from_tick=previous.tick,
                        to_tick=sample.tick,
                        carried_at_last_source_sample=previous.load,
                    )
                if (
                    self._departure is not None
                    and sample.tile == sample.destination_tile
                    and sample.load < previous.load
                ):
                    self.candidate_cycles.append(
                        dict(
                            evidence="inferred_censored_candidate_cycle",
                            departure=self._departure,
                            unloading_interval=[previous.tick, sample.tick],
                            observed_net_load_decrease=previous.load - sample.load,
                            missed_cycles_possible=True,
                        )
                    )
                    self._departure = None
            else:
                self._departure = None
            if labels:
                self.transitions.append(
                    dict(
                        evidence="inferred_between_samples",
                        from_tick=previous.tick,
                        to_tick=sample.tick,
                        labels=labels,
                        net_load_change=None if gap else sample.load - previous.load,
                    )
                )
        self.samples.append(sample)

    def report(self):
        elapsed = self.samples[-1].tick - self.samples[0].tick if len(self.samples) > 1 else 0
        return dict(
            schema="freight-point-telemetry-v1",
            classification={
                "samples": "OBSERVED",
                "transitions_and_candidate_cycles": "DERIVED",
                "exact_completed_frequency_idle_and_servicing": "UNKNOWN",
            },
            samples=len(self.samples),
            transitions=self.transitions,
            candidate_cycles=self.candidate_cycles,
            inferred_candidate_cycles_per_script_tick=(
                len(self.candidate_cycles) / elapsed if elapsed else None
            ),
            queue_series=[
                dict(tick=s.tick, economy_date=s.economy_date, queue=s.queue) for s in self.samples
            ],
            zero_speed_sample_count=sum(s.speed == 0 for s in self.samples),
            stopped_in_depot_sample_count=sum(s.stopped_in_depot for s in self.samples),
            at_station_sample_count=sum(s.at_station for s in self.samples),
            exact_arrival_departure_times=None,
            loading_unloading_event_times=None,
            cargo_per_completed_cycle=None,
            completed_delivery_frequency=None,
            idle_time=None,
            servicing_time=None,
            observation="point measurements; intervals can contain missed cycles",
        )


@dataclass(frozen=True)
class TelemetryRequest:
    request_id: str
    service: int
    vehicle: int
    type: str = "continuous-telemetry"

    def to_bytes(self):
        return telemetry_request(self.request_id, self.service, self.vehicle)


class TelemetryReadback:
    @staticmethod
    def parse_for(request, raw):
        return decode_telemetry(raw, request.to_bytes())


def validate_bindings(bindings):
    """Exactly the original three services, optionally one extra physical vehicle."""
    if not isinstance(bindings, list) or len(bindings) not in (3, 4):
        raise ValueError("three or four telemetry vehicle bindings required")
    normalized = []
    for binding in bindings:
        if set(binding) != {"service", "vehicle"}:
            raise ValueError("invalid telemetry binding fields")
        telemetry_request("binding", binding["service"], binding["vehicle"])
        normalized.append(dict(binding))
    if len({b["vehicle"] for b in normalized}) != len(normalized) or {
        b["service"] for b in normalized
    } != {0, 1, 2}:
        raise ValueError("telemetry vehicle or service coverage mismatch")
    return normalized
