from concurrent.futures import CancelledError
from decimal import Decimal
from threading import Event

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.routing.distance import DistanceProvider, HaversineDistanceProvider
from app.routing.schemas import (
    Coordinates,
    RouteStopPlan,
    RoutingPlan,
    RoutingProblem,
    VehicleRoutePlan,
)


class InfeasibleRoutingError(ValueError):
    """Raised when the selected fleet cannot serve every shipment."""


class RoutingTimeoutError(RuntimeError):
    """The search timed out before finding a route."""


class InvalidRoutingModelError(ValueError):
    """OR-Tools rejected the routing model or parameters."""


class RoutingSearchError(RuntimeError):
    """The search ended without proving infeasibility."""


class CVRPOptimizer:
    """Pure CVRP optimizer with no database dependencies.

    OR-Tools uses integer meters for arc costs and 0.0001 kg units for its
    capacity dimension. Public results are in kilometers and kilograms.
    """

    def __init__(
        self,
        distance_provider: DistanceProvider | None = None,
        time_limit_seconds: int = 5,
    ) -> None:
        if time_limit_seconds < 1:
            raise ValueError("time_limit_seconds must be at least 1")
        self.distance_provider = distance_provider or HaversineDistanceProvider()
        self.time_limit_seconds = time_limit_seconds

    def build_distance_matrix(self, locations: list[Coordinates]) -> list[list[int]]:
        """Build an integer distance matrix in meters."""

        matrix: list[list[int]] = []
        for origin in locations:
            row: list[int] = []
            for destination in locations:
                distance_km = self.distance_provider.distance(origin, destination)
                if distance_km < 0:
                    raise ValueError("distance providers cannot return negative distances")
                row.append(round(distance_km * 1000))
            matrix.append(row)
        return matrix

    def optimize(
        self, problem: RoutingProblem, *, cancel_event: Event | None = None
    ) -> RoutingPlan:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("route optimization was replaced")
        self._validate_capacity(problem)

        locations = [problem.depot, *(shipment.location for shipment in problem.shipments)]
        distance_matrix = self.build_distance_matrix(locations)
        demands = [0, *(self._kilograms_to_units(item.demand_kg) for item in problem.shipments)]
        capacities = [self._kilograms_to_units(item.capacity_kg) for item in problem.vehicles]

        manager = pywrapcp.RoutingIndexManager(
            len(locations),
            len(problem.vehicles),
            0,
        )
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index: int, to_index: int) -> int:
            origin = manager.IndexToNode(from_index)
            destination = manager.IndexToNode(to_index)
            return distance_matrix[origin][destination]

        distance_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)

        def demand_callback(from_index: int) -> int:
            return demands[manager.IndexToNode(from_index)]

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,
            capacities,
            True,
            "Capacity",
        )

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.FromSeconds(self.time_limit_seconds)

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("route optimization was replaced")
        solution = routing.SolveWithParameters(search_parameters)
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("route optimization was replaced")
        if solution is None:
            self._raise_for_search_status(routing.status())

        routes: list[VehicleRoutePlan] = []
        assigned_shipments: set[int] = set()
        for vehicle_index, vehicle in enumerate(problem.vehicles):
            route, route_shipments = self._extract_route(
                problem,
                vehicle_index,
                manager,
                routing,
                solution,
                distance_matrix,
            )
            if assigned_shipments.intersection(route_shipments):
                raise RuntimeError("OR-Tools assigned a shipment more than once")
            assigned_shipments.update(route_shipments)
            if route.total_weight > vehicle.capacity_kg:
                raise RuntimeError("OR-Tools produced a route above vehicle capacity")
            routes.append(route)

        expected_shipments = {shipment.shipment_id for shipment in problem.shipments}
        if assigned_shipments != expected_shipments:
            raise InfeasibleRoutingError("not every shipment could be assigned")

        return RoutingPlan(
            depot=problem.depot,
            routes=routes,
            total_distance=sum(
                (route.total_distance for route in routes),
                start=Decimal("0"),
            ),
            source_problem=problem,
        )

    def _extract_route(
        self,
        problem: RoutingProblem,
        vehicle_index: int,
        manager: pywrapcp.RoutingIndexManager,
        routing: pywrapcp.RoutingModel,
        solution: pywrapcp.Assignment,
        distance_matrix: list[list[int]],
    ) -> tuple[VehicleRoutePlan, set[int]]:
        index = routing.Start(vehicle_index)
        stops = [
            RouteStopPlan(
                stop_order=0,
                distance_from_previous=Decimal("0"),
                is_depot=True,
            )
        ]
        assigned_shipments: set[int] = set()
        total_distance_meters = 0
        total_weight = Decimal("0")

        while not routing.IsEnd(index):
            next_index = solution.Value(routing.NextVar(index))
            origin_node = manager.IndexToNode(index)
            destination_node = manager.IndexToNode(next_index)
            leg_distance_meters = distance_matrix[origin_node][destination_node]
            total_distance_meters += leg_distance_meters
            stop_order = len(stops)

            if routing.IsEnd(next_index):
                stops.append(
                    RouteStopPlan(
                        stop_order=stop_order,
                        distance_from_previous=self._meters_to_kilometers(leg_distance_meters),
                        is_depot=True,
                    )
                )
            else:
                shipment = problem.shipments[destination_node - 1]
                assigned_shipments.add(shipment.shipment_id)
                total_weight += shipment.demand_kg
                stops.append(
                    RouteStopPlan(
                        shipment_id=shipment.shipment_id,
                        customer_id=shipment.customer_id,
                        stop_order=stop_order,
                        distance_from_previous=self._meters_to_kilometers(leg_distance_meters),
                    )
                )
            index = next_index

        return (
            VehicleRoutePlan(
                vehicle_id=problem.vehicles[vehicle_index].vehicle_id,
                stops=stops,
                total_distance=self._meters_to_kilometers(total_distance_meters),
                total_weight=total_weight,
            ),
            assigned_shipments,
        )

    @staticmethod
    def _validate_capacity(problem: RoutingProblem) -> None:
        total_demand = sum(
            (shipment.demand_kg for shipment in problem.shipments),
            start=Decimal("0"),
        )
        total_capacity = sum(
            (vehicle.capacity_kg for vehicle in problem.vehicles),
            start=Decimal("0"),
        )
        largest_capacity = max(vehicle.capacity_kg for vehicle in problem.vehicles)
        if total_demand > total_capacity:
            raise InfeasibleRoutingError(
                f"total demand {total_demand} kg exceeds fleet capacity {total_capacity} kg"
            )
        oversized = [
            shipment.shipment_id
            for shipment in problem.shipments
            if shipment.demand_kg > largest_capacity
        ]
        if oversized:
            raise InfeasibleRoutingError(
                f"shipments {oversized} exceed every selected vehicle's capacity"
            )

    @staticmethod
    def _kilograms_to_units(kilograms: Decimal) -> int:
        units = kilograms * 10_000
        if units != units.to_integral_value():
            raise ValueError("routing weights support at most four decimal places in kilograms")
        if units > 2**63 - 1:
            raise ValueError("routing weight exceeds OR-Tools integer capacity")
        return int(units)

    @staticmethod
    def _raise_for_search_status(status: int) -> None:
        search_status = routing_enums_pb2.RoutingSearchStatus.Value
        if status == search_status.ROUTING_INFEASIBLE:
            raise InfeasibleRoutingError("OR-Tools proved the route plan infeasible")
        if status == search_status.ROUTING_FAIL_TIMEOUT:
            raise RoutingTimeoutError("OR-Tools timed out before finding a route plan")
        if status == search_status.ROUTING_INVALID:
            raise InvalidRoutingModelError("OR-Tools rejected the routing model or parameters")
        raise RoutingSearchError(
            f"OR-Tools found no route plan (status: {search_status.Name(status)})"
        )

    @staticmethod
    def _meters_to_kilometers(meters: int) -> Decimal:
        return (Decimal(meters) / 1000).quantize(Decimal("0.001"))
