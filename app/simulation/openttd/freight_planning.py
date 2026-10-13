"""P08/P05 freight intent boundary. Controlled correspondence never authorizes execution."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, StrictInt

from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import (
    Contract,
    Digest,
    ExecutionPlan,
    Mode,
    RoadComposition,
    RoadFleetOption,
)
from app.planning.p08_road import ControlledRoadScenario
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.freight_delivery import DeliveryPlan, DeliveryReadback, DeliveryRequest


class PlanningSelectionRequest(Contract):
    protocol: Literal[1] = 1
    op: Literal["select"] = "select"
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,32}$")
    plan: Digest
    arg: Literal[0] = 0
    max_cost: Literal[100000] = 100000
    a: tuple[StrictInt, ...] = Field(min_length=10, max_length=10)
    path: tuple[StrictInt, ...] = Field(min_length=2, max_length=47)
    depot_front: StrictInt = Field(ge=0, le=4095)

    def to_bytes(self):
        from app.planning.canonical import canonical_bytes

        raw = canonical_bytes(self)
        if (
            len(raw) > 1450
            or any(not 0 <= v <= 65534 for v in self.a)
            or any(not 0 <= v < 4096 for v in self.path)
        ):
            raise ValueError("bounded native planning selection required")
        return raw

    @property
    def admission_request(self):
        return DeliveryRequest(op="inspect", request_id=self.request_id, plan=self.plan)


@dataclass(frozen=True)
class PlannedFreightService:
    road: ControlledRoadScenario
    execution_plan_digest: str
    source: int
    destination: int
    cargo: int
    engine: int
    capacity: int

    def require_real_executable_source(self):
        self.road.require_real_executable_source()

    def selection_request(self, *, request_id="inspect-1", require_native=True):
        if require_native:
            self.require_real_executable_source()
            if self.road.benchmark.quantity != self.capacity:
                raise ValueError(
                    "full-load executor requires planned batch equal to native capacity"
                )
        road = self.road
        path = road.corridor[1:-1]
        if len(path) > 47 or len(path) < 2:
            raise ValueError("native freight supports 2..47 corridor road tiles")
        a = (
            self.source,
            self.destination,
            self.cargo,
            self.engine,
            road.pickup.tile_id,
            road.pickup.front_tile_id,
            road.delivery.tile_id,
            road.delivery.front_tile_id,
            road.depot.tile_id,
            path[0],
        )
        return PlanningSelectionRequest(
            request_id=request_id,
            plan=self.execution_plan_digest,
            a=a,
            path=path,
            depot_front=road.depot.front_tile_id,
        )

    def validate_native_selection(
        self, native: DeliveryPlan, admission: DeliveryReadback | None = None
    ):
        """A match is a geometry/identity check, never an upgrade of source trust."""
        self.require_real_executable_source()
        if (
            admission is None
            or admission.digest != native.admission_digest
            or admission.status != "READY"
            or admission.plan != self.execution_plan_digest
        ):
            raise ValueError("plan-bound native admission readback required")
        road = self.road
        a = native.a
        selection = self.selection_request()
        records = {
            r.id: r for r in road.input.admitted.world.structural.inventory.observation.records
        }
        engine = next(e for e in road.input.facts.engines if e.engine_id == self.engine)
        expected_f = (
            records[self.source].type,
            records[self.destination].type,
            records[self.source].tile,
            records[self.destination].tile,
            road.benchmark.supply.quantity,
            self.capacity,
            engine.purchase_cost_gbp,
            road.input.facts.settings.effective_truck_stop_radius,
        )
        month = road.input.admitted.world.production.qualification.current_month
        if (
            (self.source, self.destination, self.cargo, self.engine) != a[:4]
            or self.capacity != native.f[5]
            or expected_f != native.f
            or not month.start_date <= admission.s[1] < month.end_date
            or (road.pickup.tile_id, road.pickup.front_tile_id) != a[4:6]
            or (road.delivery.tile_id, road.delivery.front_tile_id) != a[6:8]
            or selection.a != a
            or (road.scenario.width_tiles, road.scenario.height_tiles) != (64, 64)
            or road.scenario.world_manifest.source_digest != native.source_save_digest
        ):
            raise ValueError("P05 decisions differ from admitted native freight service")
        return dict(
            execution_plan_digest=self.execution_plan_digest,
            native_plan_digest=native.digest,
            selection=selection.model_dump(mode="json"),
            world_observation_digest=road.input.admitted.world.composition_digest,
            supplemental_digest=road.input.facts.semantic_digest,
            prepared_save_digest=native.source_save_digest,
            policy_digest=road.input.policy.digest,
        )


def compile_freight_service(road: ControlledRoadScenario, plan: ExecutionPlan):
    """Reuse supplied P08 candidates and P05 decisions, without selecting or optimizing again."""
    validate_execution_plan(plan, road.scenario)
    if (
        plan.planner_inputs_digest != scenario_hash(road.scenario)
        or len(plan.routes) != 1
        or len(plan.fleet.groups) != 1
    ):
        raise ValueError("one source-bound freight route required")
    group = plan.fleet.groups[0]
    options = {option.option_id: option for option in road.scenario.fleet_options}
    option = options[group.option_id]
    selected = {a.candidate_id for a in plan.infrastructure.actions}
    expected = {p.candidate_id for p in road.candidate_provenance if p.engine_id is None}
    if (
        group.mode is not Mode.ROAD
        or group.count != 1
        or group.start_day != 0
        or group.planned_trips_per_vehicle != 1
        or not isinstance(group.composition, RoadComposition)
        or not isinstance(option, RoadFleetOption)
        or selected != expected
    ):
        raise ValueError("freight demo supports the supplied single-vehicle road service only")
    engine_ids = {
        p.engine_id
        for p in road.candidate_provenance
        if p.engine_id is not None and p.candidate_id == group.option_id
    }
    if len(engine_ids) != 1:
        raise ValueError("unambiguous native engine provenance required")
    engine = engine_ids.pop()
    return PlannedFreightService(
        road=road,
        execution_plan_digest=plan_hash(plan),
        source=road.benchmark.producer.industry_id,
        destination=road.benchmark.acceptor.industry_id,
        cargo=road.benchmark.cargo.cargo_id,
        engine=engine,
        capacity=option.vehicle.capacity_cargo_units,
    )
