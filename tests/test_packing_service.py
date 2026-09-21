from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database import seed
from app.packing.model import LoadingPlan, PackagePlacement
from app.packing.schemas import LoadingStatus
from app.packing.service import PackingService
from app.routing.model import Route
from app.routing.optimizer import CVRPOptimizer
from app.routing.schemas import Coordinates
from app.routing.service import RoutingService
from app.shipment.model import Package
from app.vehicle.model import Vehicle


class GridDistanceProvider:
    def distance(self, origin: Coordinates, destination: Coordinates) -> float:
        return abs(origin.latitude - destination.latitude) + abs(
            origin.longitude - destination.longitude
        )


@pytest.fixture
def saved_route_id(session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(seed, "create_session", session_factory)
    seed.seed_database()
    service = RoutingService(
        session_factory=session_factory,
        optimizer=CVRPOptimizer(GridDistanceProvider(), time_limit_seconds=1),
        depot=Coordinates(latitude=0, longitude=0),
    )
    candidates = service.list_candidates()
    routing_plan = service.optimize(
        [s.id for s in candidates.shipments], [candidates.vehicles[0].id]
    )
    return service.save_plan(routing_plan).route_ids[0]


def test_saved_cvrp_route_to_persisted_loading_plan(
    session_factory: sessionmaker[Session], saved_route_id: int
) -> None:
    service = PackingService(session_factory=session_factory)
    candidates = service.list_routes()
    assert [(c.route_id, c.stop_count, c.package_count) for c in candidates] == [
        (saved_route_id, 2, 3)
    ]

    draft = service.optimize(saved_route_id)
    assert len(draft.result.placements) == 3
    assert not draft.result.unplaced_packages
    assert draft.result.status is LoadingStatus.COMPLETE
    saved = service.save_plan(draft)

    with session_factory() as session:
        plan = session.scalar(
            select(LoadingPlan)
            .options(selectinload(LoadingPlan.placements))
            .where(LoadingPlan.id == saved.loading_plan_id)
        )
        route = session.get(Route, saved_route_id)
        assert plan is not None and route is not None
        assert plan.route is route
        assert plan.vehicle is route.vehicle
        assert plan in route.loading_plans
        assert plan.created_at is not None
        assert plan.status is LoadingStatus.COMPLETE
        assert plan.total_loaded_weight == Decimal("32.25")
        assert plan.used_cargo_volume == draft.result.used_cargo_volume
        assert plan.volume_utilization_percentage == draft.result.volume_utilization_percentage
        assert plan.payload_utilization_percentage == draft.result.payload_utilization_percentage
        assert plan.source_snapshot == draft.problem.model_dump(mode="json")
        assert plan.unplaced_packages == []
        assert len(plan.placements) == saved.placement_count == 3
        stops = {s.shipment_id: s.stop_order for s in route.stops if not s.is_depot}
        for record, expected in zip(plan.placements, draft.result.placements, strict=True):
            assert record.package.shipment_id in stops
            assert record.stop_order == stops[record.package.shipment_id]
            for field in (
                "x",
                "y",
                "z",
                "width",
                "length",
                "height",
                "orientation",
                "loading_order",
                "unloading_order",
                "package_id",
            ):
                assert getattr(record, field) == getattr(expected, field)
            assert record in record.package.loading_placements


def test_partial_plan_persists_unplaced_packages_and_metrics(
    session_factory: sessionmaker[Session], saved_route_id: int
) -> None:
    with session_factory.begin() as session:
        package = session.get(Package, 1)
        assert package is not None
        package.width = package.length = package.height = Decimal("9999")
    service = PackingService(session_factory=session_factory)
    draft = service.optimize(saved_route_id)
    assert draft.result.status is LoadingStatus.PARTIAL
    saved = service.save_plan(draft)

    with session_factory() as session:
        plan = session.get(LoadingPlan, saved.loading_plan_id)
        assert plan is not None
        assert plan.status is LoadingStatus.PARTIAL
        assert plan.unplaced_packages == [p.model_dump() for p in draft.result.unplaced_packages]
        assert plan.unplaced_packages[0]["package_id"] == 1
        assert len(plan.placements) == 2
        assert plan.total_package_volume > plan.used_cargo_volume


def test_missing_route_is_reported(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        PackingService(session_factory=session_factory).optimize(999)


@pytest.mark.parametrize("changed", ["package", "vehicle", "stop"])
def test_changed_input_requires_reoptimization(
    session_factory: sessionmaker[Session], saved_route_id: int, changed: str
) -> None:
    service = PackingService(session_factory=session_factory)
    draft = service.optimize(saved_route_id)
    with session_factory.begin() as session:
        if changed == "package":
            record = session.get(Package, draft.problem.packages[0].package_id)
            record.weight += 1
        elif changed == "vehicle":
            record = session.get(Vehicle, draft.problem.vehicle.vehicle_id)
            record.length += 1
        else:
            record = session.get(Route, saved_route_id)
            next(s for s in record.stops if not s.is_depot).stop_order = 99

    with pytest.raises(ValueError, match="changed"):
        service.save_plan(draft)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(LoadingPlan)) == 0
        assert session.scalar(select(func.count()).select_from(PackagePlacement)) == 0


def test_modified_result_is_not_persisted(
    session_factory: sessionmaker[Session], saved_route_id: int
) -> None:
    service = PackingService(session_factory=session_factory)
    draft = service.optimize(saved_route_id)
    draft = draft.model_copy(update={"result": draft.result.model_copy(update={"placements": []})})

    with pytest.raises(ValueError, match="result changed"):
        service.save_plan(draft)
