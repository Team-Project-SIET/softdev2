from concurrent.futures import CancelledError
from decimal import Decimal
from threading import Event

import pytest
from ortools.constraint_solver import routing_enums_pb2
from pydantic import ValidationError

from app.routing.optimizer import (
    CVRPOptimizer,
    InfeasibleRoutingError,
    InvalidRoutingModelError,
    RoutingSearchError,
    RoutingTimeoutError,
)
from app.routing.schemas import (
    Coordinates,
    RoutingProblem,
    RoutingShipment,
    RoutingVehicle,
)


class MatrixDistanceProvider:
    """Deterministic distance provider backed by a kilometer matrix."""

    def __init__(self, locations: list[Coordinates], matrix: list[list[float]]) -> None:
        self.indices = {
            (location.latitude, location.longitude): index
            for index, location in enumerate(locations)
        }
        self.matrix = matrix

    def distance(self, origin: Coordinates, destination: Coordinates) -> float:
        origin_index = self.indices[(origin.latitude, origin.longitude)]
        destination_index = self.indices[(destination.latitude, destination.longitude)]
        return self.matrix[origin_index][destination_index]


@pytest.fixture
def routing_problem() -> tuple[RoutingProblem, MatrixDistanceProvider]:
    locations = [Coordinates(latitude=0, longitude=index) for index in range(5)]
    matrix = [
        [0, 1, 2, 10, 11],
        [1, 0, 1, 9, 10],
        [2, 1, 0, 8, 9],
        [10, 9, 8, 0, 1],
        [11, 10, 9, 1, 0],
    ]
    problem = RoutingProblem(
        depot=locations[0],
        shipments=[
            RoutingShipment(
                shipment_id=index,
                customer_id=100 + index,
                location=locations[index],
                demand_kg=Decimal(demand),
            )
            for index, demand in enumerate([6, 4, 6, 4], start=1)
        ],
        vehicles=[
            RoutingVehicle(vehicle_id=10, capacity_kg=Decimal("10")),
            RoutingVehicle(vehicle_id=20, capacity_kg=Decimal("10")),
        ],
    )
    return problem, MatrixDistanceProvider(locations, matrix)


def test_distance_matrix_is_deterministic(
    routing_problem: tuple[RoutingProblem, MatrixDistanceProvider],
) -> None:
    problem, provider = routing_problem
    optimizer = CVRPOptimizer(provider, time_limit_seconds=1)

    matrix = optimizer.build_distance_matrix(
        [problem.depot, *(shipment.location for shipment in problem.shipments)]
    )

    assert matrix[0] == [0, 1000, 2000, 10000, 11000]
    assert matrix[3][4] == 1000


def test_multiple_vehicle_solution_assigns_every_shipment_once_and_within_capacity(
    routing_problem: tuple[RoutingProblem, MatrixDistanceProvider],
) -> None:
    problem, provider = routing_problem

    plan = CVRPOptimizer(provider, time_limit_seconds=1).optimize(problem)

    assigned = [
        stop.shipment_id for route in plan.routes for stop in route.stops if not stop.is_depot
    ]
    assert sorted(assigned) == [1, 2, 3, 4]
    assert len(assigned) == len(set(assigned))
    assert len([route for route in plan.routes if route.total_weight > 0]) == 2
    assert all(route.total_weight <= Decimal("10") for route in plan.routes)
    assert plan.total_distance == Decimal("26.000")


def test_every_route_starts_and_ends_at_depot(
    routing_problem: tuple[RoutingProblem, MatrixDistanceProvider],
) -> None:
    problem, provider = routing_problem

    plan = CVRPOptimizer(provider, time_limit_seconds=1).optimize(problem)

    assert all(route.stops[0].is_depot for route in plan.routes)
    assert all(route.stops[-1].is_depot for route in plan.routes)
    assert all(route.stops[0].stop_order == 0 for route in plan.routes)


def test_infeasible_capacity_raises_clear_error(
    routing_problem: tuple[RoutingProblem, MatrixDistanceProvider],
) -> None:
    problem, provider = routing_problem
    infeasible = problem.model_copy(
        update={"vehicles": [RoutingVehicle(vehicle_id=10, capacity_kg=Decimal("9"))]}
    )

    with pytest.raises(InfeasibleRoutingError, match="exceeds fleet capacity"):
        CVRPOptimizer(provider, time_limit_seconds=1).optimize(infeasible)


def test_precise_weights_are_not_rounded_below_capacity_usage() -> None:
    depot = Coordinates(latitude=0, longitude=0)
    problem = RoutingProblem(
        depot=depot,
        shipments=[
            RoutingShipment(
                shipment_id=index,
                customer_id=index,
                location=Coordinates(latitude=0, longitude=index),
                demand_kg=Decimal("0.5004"),
            )
            for index in (1, 2)
        ],
        vehicles=[RoutingVehicle(vehicle_id=index, capacity_kg=1) for index in (1, 2)],
    )

    class ZeroDistanceProvider:
        def distance(self, origin: Coordinates, destination: Coordinates) -> float:
            return 0.0

    plan = CVRPOptimizer(ZeroDistanceProvider(), time_limit_seconds=1).optimize(problem)
    assert sorted(route.total_weight for route in plan.routes) == [
        Decimal("0.5004"),
        Decimal("0.5004"),
    ]
    assert all(route.total_weight <= 1 for route in plan.routes)


def test_capacity_scaling_rejects_unsupported_precision_and_int64_overflow() -> None:
    with pytest.raises(ValidationError, match="decimal places"):
        RoutingShipment(
            shipment_id=1,
            customer_id=1,
            location=Coordinates(latitude=0, longitude=0),
            demand_kg=Decimal("0.00001"),
        )
    with pytest.raises(ValueError, match="four decimal places"):
        CVRPOptimizer._kilograms_to_units(Decimal("0.00001"))
    assert CVRPOptimizer._kilograms_to_units(Decimal("922337203685477.5807")) == 2**63 - 1
    with pytest.raises(ValueError, match="integer capacity"):
        CVRPOptimizer._kilograms_to_units(Decimal("922337203685477.5808"))


def test_cancelled_route_job_stops_before_solver(
    routing_problem: tuple[RoutingProblem, MatrixDistanceProvider],
) -> None:
    problem, provider = routing_problem
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        CVRPOptimizer(provider, time_limit_seconds=1).optimize(problem, cancel_event=cancelled)


def test_indivisible_allocation_can_fail_with_sufficient_total_capacity() -> None:
    depot = Coordinates(latitude=0, longitude=0)
    problem = RoutingProblem(
        depot=depot,
        shipments=[
            RoutingShipment(
                shipment_id=index,
                customer_id=index,
                location=Coordinates(latitude=0, longitude=index),
                demand_kg=6,
            )
            for index in (1, 2, 3)
        ],
        vehicles=[
            RoutingVehicle(vehicle_id=1, capacity_kg=10),
            RoutingVehicle(vehicle_id=2, capacity_kg=8),
        ],
    )

    class ZeroDistanceProvider:
        def distance(self, origin: Coordinates, destination: Coordinates) -> float:
            return 0.0

    with pytest.raises((InfeasibleRoutingError, RoutingSearchError)):
        CVRPOptimizer(ZeroDistanceProvider(), time_limit_seconds=1).optimize(problem)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (routing_enums_pb2.RoutingSearchStatus.Value.ROUTING_INFEASIBLE, InfeasibleRoutingError),
        (routing_enums_pb2.RoutingSearchStatus.Value.ROUTING_FAIL_TIMEOUT, RoutingTimeoutError),
        (routing_enums_pb2.RoutingSearchStatus.Value.ROUTING_INVALID, InvalidRoutingModelError),
        (routing_enums_pb2.RoutingSearchStatus.Value.ROUTING_FAIL, RoutingSearchError),
    ],
)
def test_missing_solution_reports_solver_status(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        CVRPOptimizer._raise_for_search_status(status)
