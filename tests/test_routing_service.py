from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.customer.model import Customer
from app.driver.model import Driver
from app.routing.model import Route
from app.routing.optimizer import CVRPOptimizer
from app.routing.schemas import Coordinates
from app.routing.service import InvalidRoutingPlanError, RoutingService, StaleRoutingPlanError
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


class GridDistanceProvider:
    def distance(self, origin: Coordinates, destination: Coordinates) -> float:
        return abs(origin.latitude - destination.latitude) + abs(
            origin.longitude - destination.longitude
        )


def test_service_calculates_demand_and_persists_plan(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        customer = Customer(
            name="Routing Customer",
            phone="123",
            address="Test address",
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        vehicle = Vehicle(
            name="Routing Van",
            width=180,
            length=300,
            height=180,
            max_weight=100,
            status=VehicleStatus.AVAILABLE,
        )
        session.add_all([customer, vehicle])
        session.flush()
        driver = Driver(
            name="Routing Driver",
            phone="123456",
            line_user_id="U" + "c" * 32,
            vehicle_id=vehicle.id,
        )
        session.add(driver)
        session.flush()
        driver_id = driver.id
        session.add(
            Shipment(
                customer_id=customer.id,
                delivery_date=date(2026, 1, 1),
                priority=ShipmentPriority.NORMAL,
                status=ShipmentStatus.PENDING,
                notes=None,
                packages=[
                    Package(width=10, length=10, height=10, weight=Decimal("12.25")),
                    Package(width=10, length=10, height=10, weight=Decimal("7.75")),
                ],
            )
        )

    service = RoutingService(
        session_factory=session_factory,
        optimizer=CVRPOptimizer(GridDistanceProvider(), time_limit_seconds=1),
        depot=Coordinates(latitude=0, longitude=0),
    )

    candidates = service.list_candidates()
    assert candidates.shipments[0].demand_kg == Decimal("20.00")

    plan = service.optimize(
        [candidates.shipments[0].id],
        [candidates.vehicles[0].id],
    )
    saved = service.save_plan(plan)

    assert saved.shipment_count == 1
    with session_factory() as session:
        route = session.scalar(select(Route).options(selectinload(Route.stops)))
        shipment = session.get(Shipment, candidates.shipments[0].id)
        assert route is not None
        assert [stop.is_depot for stop in route.stops] == [True, False, True]
        assert route.total_weight == Decimal("20.000")
        assert route.total_distance == sum(
            (stop.distance_from_previous for stop in route.stops), Decimal(0)
        )
        assert route.driver_id == driver_id
        assert shipment is not None
        assert shipment.status is ShipmentStatus.PLANNED


def preview_for_save(session_factory: sessionmaker[Session]):
    with session_factory.begin() as session:
        customer = Customer(
            name="Preview Customer",
            phone="123",
            address="Preview address",
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        vehicle = Vehicle(
            name="Preview Van",
            width=180,
            length=300,
            height=180,
            max_weight=100,
            status=VehicleStatus.AVAILABLE,
        )
        shipment = Shipment(
            customer=customer,
            delivery_date=date(2026, 1, 1),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PENDING,
            packages=[Package(width=10, length=10, height=10, weight=Decimal("12.25"))],
        )
        session.add_all([vehicle, shipment])
        session.flush()
        shipment_id, vehicle_id = shipment.id, vehicle.id
    service = RoutingService(
        session_factory=session_factory,
        optimizer=CVRPOptimizer(GridDistanceProvider(), time_limit_seconds=1),
        depot=Coordinates(latitude=0, longitude=0),
    )
    return service, service.optimize([shipment_id], [vehicle_id]), shipment_id, vehicle_id


def test_cancelled_shipment_after_preview_is_not_resurrected(
    session_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _ = preview_for_save(session_factory)
    with session_factory.begin() as session:
        session.get(Shipment, shipment_id).status = ShipmentStatus.CANCELLED

    with pytest.raises(StaleRoutingPlanError, match="no longer pending"):
        service.save_plan(plan)

    with session_factory() as session:
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.CANCELLED
        assert session.scalar(select(func.count()).select_from(Route)) == 0


def test_unavailable_vehicle_after_preview_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, vehicle_id = preview_for_save(session_factory)
    with session_factory.begin() as session:
        session.get(Vehicle, vehicle_id).status = VehicleStatus.MAINTENANCE

    with pytest.raises(StaleRoutingPlanError, match="no longer available"):
        service.save_plan(plan)

    with session_factory() as session:
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.PENDING
        assert session.scalar(select(func.count()).select_from(Route)) == 0


def test_repeated_save_cannot_assign_shipment_twice(
    session_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _ = preview_for_save(session_factory)
    service.save_plan(plan)

    with pytest.raises(StaleRoutingPlanError, match="no longer pending"):
        service.save_plan(plan)

    with session_factory() as session:
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.PLANNED
        assert session.scalar(select(func.count()).select_from(Route)) == 1


def test_changed_package_weight_requires_new_preview(
    session_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _ = preview_for_save(session_factory)
    with session_factory.begin() as session:
        session.scalar(select(Package).where(Package.shipment_id == shipment_id)).weight += 1

    with pytest.raises(StaleRoutingPlanError, match="routing inputs changed"):
        service.save_plan(plan)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Route)) == 0


@pytest.mark.parametrize("invalid", ["depot", "customer"])
def test_structurally_invalid_route_is_not_persisted(
    session_factory: sessionmaker[Session], invalid: str
) -> None:
    service, plan, _, _ = preview_for_save(session_factory)
    route = plan.routes[0]
    if invalid == "depot":
        bad_stops = [
            route.stops[1].model_copy(update={"stop_order": 0}),
            route.stops[1].model_copy(update={"stop_order": 1}),
        ]
    else:
        bad_stops = [
            route.stops[0],
            route.stops[1].model_copy(update={"customer_id": route.stops[1].customer_id + 1}),
            route.stops[2],
        ]
    bad_plan = plan.model_copy(update={"routes": [route.model_copy(update={"stops": bad_stops})]})

    with pytest.raises(InvalidRoutingPlanError):
        service.save_plan(bad_plan)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Route)) == 0


@pytest.mark.parametrize(
    ("leg_distances", "total_distance"),
    [
        ((Decimal("0.0004"), Decimal("0.0004")), Decimal("0.0008")),
        ((Decimal("-1"), Decimal("1")), Decimal("0")),
    ],
)
def test_unrepresentable_or_negative_legs_are_rejected_before_persistence(
    session_factory: sessionmaker[Session],
    leg_distances: tuple[Decimal, Decimal],
    total_distance: Decimal,
) -> None:
    service, plan, _, _ = preview_for_save(session_factory)
    route = plan.routes[0]
    stops = [
        route.stops[0],
        route.stops[1].model_copy(update={"distance_from_previous": leg_distances[0]}),
        route.stops[2].model_copy(update={"distance_from_previous": leg_distances[1]}),
    ]
    changed = route.model_copy(update={"stops": stops, "total_distance": total_distance})
    invalid_plan = plan.model_copy(update={"routes": [changed], "total_distance": total_distance})

    with pytest.raises(InvalidRoutingPlanError, match="invalid route preview"):
        service.save_plan(invalid_plan)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Route)) == 0


@pytest.mark.parametrize("level", ["route", "fleet"])
def test_negative_route_or_fleet_distance_is_rejected(
    session_factory: sessionmaker[Session], level: str
) -> None:
    service, plan, _, _ = preview_for_save(session_factory)
    if level == "route":
        invalid = plan.model_copy(
            update={"routes": [plan.routes[0].model_copy(update={"total_distance": Decimal("-1")})]}
        )
    else:
        invalid = plan.model_copy(update={"total_distance": Decimal("-1")})

    with pytest.raises(InvalidRoutingPlanError, match="invalid route preview"):
        service.save_plan(invalid)
