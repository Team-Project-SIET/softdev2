"""Offline native-generator recipes and bounded P08/P05 extension interfaces."""

import json
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt

from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash
from app.planning.domain import Contract, ExecutionPlan, PlanningScenario
from app.planning.p08_adapter import BoundedRoadInput
from app.planning.p08_network import generate_freight_network
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


class RandomWorldSettings(Contract):
    seed: StrictInt = Field(default=42, ge=0, le=4294967294)
    map_size: Literal[256] = 256
    climate: Literal["temperate", "arctic", "tropic", "toyland"] = "temperate"
    terrain: StrictInt = Field(default=0, ge=0, le=5)
    towns: StrictInt = Field(default=1, ge=0, le=3)
    industries: StrictInt = Field(default=2, ge=0, le=4)

    def config(self) -> str:
        """OpenTTD 15.3 native generator settings, never a heightmap replacement."""
        return (
            "[game_creation]\nmap_x = 8\nmap_y = 8\n"
            f"landscape = {self.climate}\nstarting_year = 1950\nland_generator = 1\n"
            "[difficulty]\n"
            f"terrain_type = {self.terrain}\nnumber_towns = {self.towns}\n"
            f"industry_density = {self.industries}\nmax_no_competitors = 0\n"
            "infinite_money = false\nvehicle_breakdowns = 0\ndisasters = false\n"
            "[economy]\ntimekeeping_units = 0\n[newgrf]\n"
        )


class DemoBudgets(Contract):
    max_services: StrictInt = Field(default=3, ge=1, le=8)
    max_vehicles: StrictInt = Field(default=3, ge=1, le=8)
    max_relationships: StrictInt = Field(default=16, ge=1, le=16)
    max_pair_checks: StrictInt = Field(default=8192, ge=1, le=8192)
    planning_seconds: StrictInt = Field(default=30, ge=1, le=60)
    capture_tile_limit: Literal[256, 512] = 512
    capture_seconds: StrictInt = Field(default=45, ge=1, le=60)

    @classmethod
    def from_sealed(cls, value: dict) -> DemoBudgets:
        # Retained v1 random packages used 256 tiles; never reinterpret their identity.
        return cls.model_validate({"capture_tile_limit": 256, **value})

    @property
    def supplemental_request_limit(self) -> int:
        return (self.capture_tile_limit + 36) * self.max_relationships + 1


def prepare_random(directory: Path, settings: RandomWorldSettings, budgets: DemoBudgets) -> Path:
    """Write a reviewable recipe. No runtime workspace, socket or process is created."""
    directory.mkdir(parents=True, exist_ok=False)
    config = settings.config()
    (directory / "generation.cfg").write_text(config)
    (directory / "generation-arguments.json").write_text(
        json.dumps(["-G", str(settings.seed), "-g"]) + "\n"
    )
    request = dict(settings=settings.model_dump(), budgets=budgets.model_dump())
    metadata = dict(
        schema="random-demo-preparation-v1",
        status="PREPARED_RECIPE_ONLY",
        openttd_version="15.3",
        request=request,
        experiment_key=sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
        configuration_sha256=sha256(config.encode()).hexdigest(),
        requested_generator="native-terragenesis",
        actual_generation_settings=None,
        actual_world_identity=None,
        native_execution_ready=False,
        next_step="separately authorized native run for observed world/candidates",
    )
    (directory / "experiment.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return directory


@dataclass(frozen=True)
class RelationshipDiscovery:
    relationships: tuple[tuple[int, int, int], ...]
    rejected: tuple[dict, ...]
    truncated: bool
    checks: int

    @property
    def status(self) -> str:
        if self.relationships:
            return "CANDIDATES_REQUIRE_P08"
        return "SEARCH_LIMIT" if self.truncated else "NO_SUPPORTED_RELATIONSHIP"


def discover_relationships(
    world: WorldPlanningObservation, budgets: DemoBudgets
) -> RelationshipDiscovery:
    """Use observed cargo capabilities/production; geometry remains P08's decision.

    Compatibility does not assert terrain coverage or construction feasibility.
    Capture admission is a separate bounded step, including map-edge checks.
    """
    caps = sorted(world.structural.capability.observation.capabilities, key=lambda c: c.industry_id)
    positive = {
        (r.industry_id, r.cargo_id) for r in world.production.records if r.last_month_produced > 0
    }
    freight = {r.cargo_id for r in world.structural.catalog.observation.records if r.is_freight}
    selected, rejected = [], []
    checks = 0
    for source in caps:
        for cargo in sorted(set(source.produces) & freight):
            if (source.industry_id, cargo) not in positive:
                continue
            for destination in caps:
                if checks >= budgets.max_pair_checks or len(selected) >= budgets.max_relationships:
                    return RelationshipDiscovery(tuple(selected), tuple(rejected), True, checks)
                checks += 1
                if (
                    source.industry_id == destination.industry_id
                    or cargo not in destination.accepts
                ):
                    continue
                # Geometry belongs to capture admission, after compatible discovery.
                selected.append((source.industry_id, destination.industry_id, cargo))
    return RelationshipDiscovery(tuple(selected), tuple(rejected), False, checks)


def relationship_region(world: WorldPlanningObservation, relationship: tuple, tile_limit=256):
    """Complete padded rectangle; clipped interior padding only for the opt-in profile."""
    if tile_limit not in (256, 512):
        raise ValueError("CAPTURE_PROFILE_UNSUPPORTED")
    records = {r.id: r for r in world.structural.inventory.observation.records}
    a, b = records[relationship[0]], records[relationship[1]]
    map_width, map_height = world.context.world.map_width, world.context.world.map_height
    if any(not 1 <= r.x < map_width - 1 or not 1 <= r.y < map_height - 1 for r in (a, b)):
        raise ValueError("CAPTURE_MAP_BOUND: industry anchor outside map interior")
    x, y = min(a.x, b.x) - 2, min(a.y, b.y) - 2
    right, bottom = max(a.x, b.x) + 2, max(a.y, b.y) + 2
    if tile_limit == 512:
        x, y = max(1, x), max(1, y)
        right, bottom = min(map_width - 1, right), min(map_height - 1, bottom)
    elif x < 1 or y < 1 or right >= map_width - 1 or bottom >= map_height - 1:
        raise ValueError("CAPTURE_MAP_BOUND: padded region outside supported interior")
    width, height = right - x, bottom - y
    if width * height > tile_limit:
        raise ValueError(f"CAPTURE_TILE_BUDGET: {width * height} tiles exceeds {tile_limit}")
    return dict(x=x, y=y, width=width, height=height) | (
        {"profile": "random-rectangle-512-v1"} if tile_limit == 512 else {}
    )


def planning_diagnostic(world: WorldPlanningObservation, metadata: dict) -> dict:
    discovery = discover_relationships(world, DemoBudgets.from_sealed(metadata["random_budget"]))
    records = {r.id: r for r in world.structural.inventory.observation.records}
    pairs = []
    for src, dst, cargo in discovery.relationships:
        a, b = records[src], records[dst]
        dx, dy = abs(a.x - b.x), abs(a.y - b.y)
        pairs.append(
            dict(
                source=src,
                destination=dst,
                cargo=cargo,
                origin=[a.x, a.y],
                destination_coordinates=[b.x, b.y],
                manhattan_distance=dx + dy,
                padded_capture_tiles=(dx + 4) * (dy + 4),
            )
        )
    return dict(
        schema="random-planning-diagnostic-v1",
        classification="OBSERVED_WITH_DERIVED_PLANNING",
        world_observation_digest=world.composition_digest,
        requested_settings=metadata["random_world"],
        industries=[dict(id=r.id, type=r.type, x=r.x, y=r.y) for r in records.values()],
        cargo_types=[
            dict(cargo_id=c.cargo_id, cargo_label=c.cargo_label, is_freight=c.is_freight)
            for c in world.structural.catalog.observation.records
        ],
        compatible_relationships=pairs,
        pair_checks=discovery.checks,
        search_truncated=discovery.truncated,
        capture_rejections=[],
        candidate_rejections=[],
        captured_relationships=0,
        capture_requests_attempted=0,
        capture_requests_completed=0,
        candidate_count=None,
        selected_service_count=None,
        status="DISCOVERED",
        budgets=DemoBudgets.from_sealed(metadata["random_budget"]).model_dump(),
        limitations=[
            "complete rectangular capture only; at most 512 tiles per relationship",
            "flat vacant land only; no clearing, slopes, bridges or tunnels",
            "native executor requires 2..47 road tiles and independent admission",
            "missing terrain, catchment or engine facts cannot establish feasibility",
        ],
        delivery_metrics=None,
        financial_results=None,
        p07="REQUIRES_COMPLETED_NATIVE_RECEIPT",
    )


def diagnostic_status(value: dict) -> str:
    return (
        f"Random planning: {value['status']}; "
        f"compatible={len(value['compatible_relationships'])} "
        f"candidates={value['candidate_count']} selected={value['selected_service_count']}; "
        "delivery/finance UNKNOWN until native receipts"
    )


def write_planning_diagnostic(directory: Path, value: dict) -> None:
    """Retain a planning result even when no native services can be attempted."""
    runtime_path = directory / "runtime-identity.json"
    value = value | dict(
        actual_world_identity=(
            json.loads(runtime_path.read_bytes())["welcome"] if runtime_path.exists() else None
        )
    )
    observed = directory / "generation-observation.json"
    value["actual_generation_settings"] = (
        json.loads(observed.read_bytes())["actual_settings"] if observed.exists() else None
    )
    with (directory / "planning-diagnostic.json").open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
    with (directory / "planning-diagnostic.html").open("x") as stream:
        stream.write(
            "<!doctype html><meta charset=utf-8><title>Random planning diagnostic</title>"
            + "<h1>"
            + escape(diagnostic_status(value))
            + "</h1><pre>"
            + escape(json.dumps(value, indent=2))
            + "</pre>"
        )
    print(diagnostic_status(value), flush=True)


def plan_packages(inputs: tuple[BoundedRoadInput, ...], budgets: DemoBudgets):
    """P08 -> P05 -> validated ExecutionPlan, retaining source trust and identities.

    Caller supplies adapter-issued packages from qualified observed state. This
    interface does not deserialize caller claims into native authority.
    """
    if not inputs:
        raise ValueError("NO_SUPPORTED_RELATIONSHIP: no qualified P08 packages")
    if len(inputs) > budgets.max_relationships:
        raise ValueError("P08 package budget exceeded")
    network = generate_freight_network(
        inputs, max_vehicles=min(budgets.max_services, budgets.max_vehicles)
    )
    plan = optimize_bounded(network.scenario, budgets)
    return (
        network,
        plan,
        dict(
            schema="random-demo-plan-v1",
            scenario_digest=scenario_hash(network.scenario),
            execution_plan_digest=plan_hash(plan),
            selected_services=len(plan.routes),
            budgets=budgets.model_dump(),
            native_execution_ready=False,
        ),
    )


def optimize_bounded(scenario: PlanningScenario, budgets: DemoBudgets) -> ExecutionPlan:
    # A separate Python solver worker provides a hard wall-clock bound without
    # changing the existing P05 solver or leaking a background solver on timeout.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.demo_random"],
            input=scenario.model_dump_json(),
            text=True,
            capture_output=True,
            timeout=budgets.planning_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("PLANNING_TIMEOUT: P05 budget exhausted") from error
    if result.returncode:
        raise ValueError("P05 planning failed: " + result.stderr[-2000:])
    plan = ExecutionPlan.model_validate_json(result.stdout)
    validate_execution_plan(plan, scenario)
    return plan


def _worker():
    from app.planning.domain import PlanningScenario
    from app.planning.optimizer import optimize_candidate_network

    raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("planning scenario exceeds 8 MiB")
    scenario = PlanningScenario.model_validate_json(raw)
    sys.stdout.write(canonical_bytes(optimize_candidate_network(scenario).plan).decode())


if __name__ == "__main__":
    _worker()
