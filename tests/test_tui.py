import asyncio
import io
import time
from concurrent.futures import CancelledError
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from threading import Event, Lock
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from textual.widgets import Button, DataTable, Select, SelectionList, Static, TabbedContent

from app.integrations.line.client import LINE_PUSH_URL, LineClient
from app.integrations.line.exceptions import LineNetworkError
from app.integrations.line.schemas import (
    LineRouteCandidate,
    LineRoutePlan,
    LineSendIntent,
    SentLineRoute,
)
from app.integrations.line.service import LineService
from app.packing.optimizer import PackingOptimizer
from app.packing.schemas import (
    DeliveryStop,
    LoadingPlanDraft,
    PackingPackage,
    PackingProblem,
    PackingVehicle,
    SavedLoadingPlan,
    SavedRouteCandidate,
)
from app.routing.schemas import (
    Coordinates,
    RouteStopPlan,
    RoutingCandidates,
    RoutingPlan,
    SavedRoutingPlan,
    ShipmentCandidate,
    VehicleCandidate,
    VehicleRoutePlan,
)
from app.shipment.model import ShipmentPriority, ShipmentStatus
from app.shipment.schema import ShipmentSummary
from app.tui.app import LogisticsApp, run_in_worker_thread
from app.vehicle.model import VehicleStatus
from app.vehicle.schema import VehicleRead


async def wait_until(predicate, timeout: float = 2) -> None:
    async def check() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(check(), timeout=timeout)


class FakeShipmentService:
    def list_shipments(self) -> list[ShipmentSummary]:
        return [
            ShipmentSummary(
                id=1,
                customer_name="Demo Customer",
                delivery_date=date(2026, 1, 2),
                priority=ShipmentPriority.NORMAL,
                status=ShipmentStatus.PENDING,
                package_count=2,
                total_weight=Decimal("12.50"),
            )
        ]


class FakeVehicleService:
    def list_vehicles(self) -> list[VehicleRead]:
        return [
            VehicleRead(
                id=1,
                name="Demo Van",
                width=178,
                length=320,
                height=185,
                max_weight=1200,
                status=VehicleStatus.AVAILABLE,
            )
        ]


class FakeRoutingService:
    def list_candidates(self) -> RoutingCandidates:
        return RoutingCandidates(
            shipments=[
                ShipmentCandidate(
                    id=1,
                    customer_name="Demo Customer",
                    delivery_date=date(2026, 1, 2),
                    demand_kg=Decimal("12.50"),
                )
            ],
            vehicles=[VehicleCandidate(id=1, name="Demo Van", capacity_kg=1200)],
        )

    def optimize(
        self, shipment_ids: list[int], vehicle_ids: list[int], *, cancel_event: Event | None = None
    ) -> RoutingPlan:
        return self.plan()

    def save_plan(self, plan: RoutingPlan) -> SavedRoutingPlan:
        return SavedRoutingPlan(route_ids=[10], shipment_count=1)

    @staticmethod
    def plan() -> RoutingPlan:
        return RoutingPlan(
            depot=Coordinates(latitude=0, longitude=0),
            routes=[
                VehicleRoutePlan(
                    vehicle_id=1,
                    stops=[
                        RouteStopPlan(
                            stop_order=0,
                            distance_from_previous=0,
                            is_depot=True,
                        ),
                        RouteStopPlan(
                            shipment_id=1,
                            customer_id=1,
                            stop_order=1,
                            distance_from_previous=1,
                        ),
                        RouteStopPlan(
                            stop_order=2,
                            distance_from_previous=1,
                            is_depot=True,
                        ),
                    ],
                    total_distance=2,
                    total_weight=Decimal("12.50"),
                )
            ],
            total_distance=2,
        )


class FakePackingService:
    def __init__(self) -> None:
        self.saved: list[LoadingPlanDraft] = []
        self.optimized: list[int] = []

    def list_routes(self) -> list[SavedRouteCandidate]:
        return [
            SavedRouteCandidate(
                route_id=10, vehicle_id=1, vehicle_name="Demo Van", stop_count=2, package_count=3
            ),
            SavedRouteCandidate(
                route_id=11, vehicle_id=2, vehicle_name="Demo Truck", stop_count=1, package_count=1
            ),
        ]

    def optimize(self, route_id: int, *, cancel_event: Event | None = None) -> LoadingPlanDraft:
        self.optimized.append(route_id)
        problem = PackingProblem(
            vehicle=PackingVehicle(vehicle_id=1, width=4, length=4, height=4, max_weight=10),
            packages=[
                PackingPackage(package_id=1, shipment_id=1, width=2, length=2, height=2, weight=1),
                PackingPackage(package_id=2, shipment_id=2, width=2, length=2, height=2, weight=2),
                PackingPackage(package_id=3, shipment_id=2, width=9, length=9, height=9, weight=1),
            ],
            delivery_sequence=[
                DeliveryStop(shipment_id=1, stop_order=1),
                DeliveryStop(shipment_id=2, stop_order=2),
            ],
        )
        return LoadingPlanDraft(
            route_id=route_id,
            problem=problem,
            result=PackingOptimizer().solve(
                problem.vehicle, problem.packages, problem.delivery_sequence
            ),
        )

    def save_plan(self, draft: LoadingPlanDraft) -> SavedLoadingPlan:
        self.saved.append(draft)
        return SavedLoadingPlan(
            loading_plan_id=20,
            route_id=draft.route_id,
            placement_count=len(draft.result.placements),
            status=draft.result.status,
        )


class FakeLineService:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.sent: list[int] = []
        self.intents: list[LineSendIntent] = []

    def list_routes(self) -> list[LineRouteCandidate]:
        return [
            LineRouteCandidate(
                route_id=10,
                vehicle_name="Demo Van",
                driver_name="Demo Driver",
                stop_count=2,
                has_line_user_id=True,
            )
        ]

    def prepare_send_intent(self, route_id: int) -> LineSendIntent:
        return LineSendIntent(
            route_id=route_id,
            line_user_id="U" + "a" * 32,
            route_plan=LineRoutePlan(
                route_id=route_id,
                driver_name="Demo Driver",
                vehicle_name="Demo Van",
                total_distance=Decimal("1"),
                stops=[],
            ),
            retry_key=uuid4(),
        )

    def send_intent(self, intent: LineSendIntent) -> SentLineRoute:
        self.intents.append(intent)
        self.sent.append(intent.route_id)
        if self.failure:
            raise RuntimeError(self.failure)
        return SentLineRoute(route_id=intent.route_id, driver_name="Demo Driver")


def test_tui_renders_service_data() -> None:
    async def run_test() -> None:
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test():
            assert app.query_one("#shipments", DataTable).row_count == 1
            assert app.query_one("#vehicles", DataTable).row_count == 1
            assert app.query_one("#routing-shipments", SelectionList).option_count == 1
            assert app.query_one("#routing-vehicles", SelectionList).option_count == 1
            assert "Loaded 1 shipments" in str(app.query_one("#status", Static).render())

            app.display_route_plan(FakeRoutingService.plan())
            assert app.query_one("#route-results", DataTable).row_count == 1
            assert app.query_one("#route-stops", DataTable).row_count == 3

    asyncio.run(run_test())


def test_loading_tab_optimizes_displays_partial_plan_and_saves() -> None:
    async def run_test() -> None:
        service = FakePackingService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=service,  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test(size=(150, 55)) as pilot:
            app.query_one(TabbedContent).active = "loading-tab"
            app.query_one("#loading-route", Select).value = 10
            await pilot.pause()
            assert await pilot.click("#optimize-loading")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert service.optimized == [10]
            assert app.query_one("#loading-packages", DataTable).row_count == 3
            assert app.query_one("#loading-order", DataTable).row_count == 2
            assert app.query_one("#unloading-order", DataTable).row_count == 2
            assert app.query_one("#unplaced-packages", DataTable).row_count == 1
            assert "partial; 2 placed, 1 unplaced" in str(
                app.query_one("#loading-status", Static).render()
            )
            metrics = str(app.query_one("#loading-metrics", Static).render())
            assert "25.00%" in metrics and "30.00%" in metrics
            assert app.query_one("#loading-order", DataTable).get_row_at(0)[2] == "2"
            assert app.query_one("#unloading-order", DataTable).get_row_at(0)[2] == "1"
            assert not app.query_one("#save-loading", Button).disabled

            assert await pilot.click("#save-loading")
            await pilot.pause()
            assert len(service.saved) == 1
            assert service.saved[0].route_id == 10
            assert "Saved loading plan #20" in str(
                app.query_one("#loading-status", Static).render()
            )
            assert app.query_one("#save-loading", Button).disabled

    asyncio.run(run_test())


def test_loading_selection_invalidates_preview_and_ignores_stale_worker() -> None:
    async def run_test() -> None:
        service = FakePackingService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=service,  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            app.start_loading_optimization()
            assert "select a saved route first" in str(
                app.query_one("#loading-status", Static).render()
            )
            assert not service.optimized
            app.query_one("#loading-route", Select).value = 10
            await pilot.pause()
            draft = service.optimize(10)
            app.display_loading_plan(draft)
            old_request = app._packing_request
            app.query_one("#loading-route", Select).value = 11
            await pilot.pause()
            app.finish_loading_optimization(old_request, draft, None)
            assert app.current_loading_plan is None
            assert app.query_one("#save-loading", Button).disabled
            assert app.query_one("#loading-packages", DataTable).row_count == 0

    asyncio.run(run_test())


@pytest.mark.parametrize("unavailable", [False, True])
def test_loading_route_refresh_preserves_empty_or_error_message(unavailable: bool) -> None:
    class EmptyPackingService(FakePackingService):
        def list_routes(self) -> list[SavedRouteCandidate]:
            if unavailable:
                raise RuntimeError("database unavailable")
            return []

    async def run_test() -> None:
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            app.query_one("#loading-route", Select).value = 10
            await pilot.pause()
            app.packing_service = EmptyPackingService()  # type: ignore[assignment]
            app.refresh_loading_routes()
            await pilot.pause()
            status = str(app.query_one("#loading-status", Static).render())
            assert ("database unavailable" if unavailable else "No saved routes") in status
            assert app.query_one("#save-loading", Button).disabled

    asyncio.run(run_test())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "Sent route #10 to Demo Driver on LINE"),
        ("LINE_CHANNEL_ACCESS_TOKEN is not configured", "LINE send failed"),
        ("LINE API returned HTTP 500", "LINE send failed"),
        ("could not reach LINE Messaging API", "LINE send failed"),
    ],
)
def test_line_route_selection_and_send_feedback(failure: str | None, expected: str) -> None:
    async def run_test() -> None:
        service = FakeLineService(failure)
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=service,  # type: ignore[arg-type]
        )
        async with app.run_test(size=(150, 55)) as pilot:
            app.query_one(TabbedContent).active = "routing-tab"
            app.query_one("#line-route", Select).value = 10
            await pilot.pause()
            assert "Assigned driver: Demo Driver" in str(
                app.query_one("#line-status", Static).render()
            )
            assert not app.query_one("#send-line", Button).disabled

            app.start_line_send()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert service.sent == [10]
            assert expected in str(app.query_one("#line-status", Static).render())
            assert not app.query_one("#send-line", Button).disabled

    asyncio.run(run_test())


def test_line_route_without_user_id_cannot_be_sent() -> None:
    class MissingLineIdService(FakeLineService):
        def list_routes(self) -> list[LineRouteCandidate]:
            return [
                LineRouteCandidate(
                    route_id=10,
                    vehicle_name="Demo Van",
                    driver_name="Demo Driver",
                    stop_count=2,
                    has_line_user_id=False,
                )
            ]

    async def run_test() -> None:
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=MissingLineIdService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            app.query_one("#line-route", Select).value = 10
            await pilot.pause()
            assert "has no LINE user ID" in str(app.query_one("#line-status", Static).render())
            assert app.query_one("#send-line", Button).disabled

    asyncio.run(run_test())


def test_line_tui_reuses_ambiguous_intent_then_starts_new_intent() -> None:
    class AmbiguousLineService(FakeLineService):
        def send_intent(self, intent: LineSendIntent) -> SentLineRoute:
            self.intents.append(intent)
            self.sent.append(intent.route_id)
            if len(self.intents) == 1:
                raise LineNetworkError("response timed out")
            return SentLineRoute(route_id=intent.route_id, driver_name="Demo Driver")

    async def run_test() -> None:
        service = AmbiguousLineService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=service,  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            app.query_one("#line-route", Select).value = 10
            await pilot.pause()
            for _ in range(3):
                app.start_line_send()
                await app.workers.wait_for_complete()
                await pilot.pause()
            assert len(service.intents) == 3
            assert service.intents[0] == service.intents[1]
            assert service.intents[2].retry_key != service.intents[1].retry_key

    asyncio.run(run_test())


@pytest.mark.parametrize("transition", ["refresh", "refresh_error", "change_route"])
def test_line_unresolved_intent_survives_refresh_or_route_change(transition: str) -> None:
    class AmbiguousLineService(FakeLineService):
        fail_refresh = False

        def list_routes(self) -> list[LineRouteCandidate]:
            if self.fail_refresh:
                raise RuntimeError("database temporarily unavailable")
            return [
                LineRouteCandidate(
                    route_id=route_id,
                    vehicle_name=f"Van {route_id}",
                    driver_name=f"Driver {route_id}",
                    stop_count=1,
                    has_line_user_id=True,
                )
                for route_id in (10, 11)
            ]

        def prepare_send_intent(self, route_id: int) -> LineSendIntent:
            intent = super().prepare_send_intent(route_id)
            return intent.model_copy(update={"line_user_id": "U" + str(route_id % 10) * 32})

        def send_intent(self, intent: LineSendIntent) -> SentLineRoute:
            self.intents.append(intent)
            if len(self.intents) == 1:
                raise LineNetworkError("response timed out")
            return SentLineRoute(route_id=intent.route_id, driver_name="Demo Driver")

    async def run_test() -> None:
        service = AmbiguousLineService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=service,  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            selector = app.query_one("#line-route", Select)
            selector.value = 10
            await pilot.pause()
            app.start_line_send()
            await app.workers.wait_for_complete()
            assert app._line_retry_intents[10] == service.intents[0]

            if transition in {"refresh", "refresh_error"}:
                service.fail_refresh = transition == "refresh_error"
                app.refresh_line_routes()
                assert selector.value == 10
                assert not app.query_one("#send-line", Button).disabled
            else:
                selector.value = 11
                await pilot.pause()
                app.start_line_send()
                await app.workers.wait_for_complete()
                assert service.intents[1].route_id == 11
                assert service.intents[1].retry_key != service.intents[0].retry_key
                assert service.intents[1].line_user_id != service.intents[0].line_user_id
                selector.value = 10
                await pilot.pause()

            app.start_line_send()
            await app.workers.wait_for_complete()
            assert service.intents[-1] == service.intents[0]
            assert service.intents[-1].route_plan == service.intents[0].route_plan
            assert 10 not in app._line_retry_intents

    asyncio.run(run_test())


def test_line_timeout_after_selection_changes_still_retains_intent() -> None:
    started = Event()
    release = Event()

    class DelayedLineService(FakeLineService):
        def list_routes(self) -> list[LineRouteCandidate]:
            return [
                LineRouteCandidate(
                    route_id=route_id,
                    vehicle_name="Van",
                    driver_name="Driver",
                    stop_count=1,
                    has_line_user_id=True,
                )
                for route_id in (10, 11)
            ]

        def send_intent(self, intent: LineSendIntent) -> SentLineRoute:
            self.intents.append(intent)
            if len(self.intents) == 1:
                started.set()
                if not release.wait(timeout=3):
                    raise RuntimeError("timed out waiting for LINE test release")
                raise LineNetworkError("response timed out")
            return SentLineRoute(route_id=intent.route_id, driver_name="Demo Driver")

    async def run_test() -> None:
        service = DelayedLineService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=service,  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            selector = app.query_one("#line-route", Select)
            selector.value = 10
            await pilot.pause()
            app.start_line_send()
            assert await asyncio.to_thread(started.wait, 2)
            selector.value = 11
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            assert app._line_retry_intents[10] == service.intents[0]
            selector.value = 10
            await pilot.pause()
            app.start_line_send()
            await app.workers.wait_for_complete()
            assert service.intents[1] == service.intents[0]

    asyncio.run(run_test())


def test_tui_timeout_then_accepted_retry_reuses_exact_http_request() -> None:
    requests = []

    def http_open(request: object, *, timeout: float) -> object:
        requests.append(request)
        if len(requests) == 1:
            raise URLError("response timed out")
        raise HTTPError(
            LINE_PUSH_URL,
            409,
            "Conflict",
            {"x-line-accepted-request-id": "accepted-request"},
            io.BytesIO(b'{"message":"The retry key is already accepted"}'),
        )

    customer = SimpleNamespace(
        name="Customer", address="Address", latitude=Decimal("1"), longitude=Decimal("2")
    )
    route = SimpleNamespace(
        id=10,
        vehicle=SimpleNamespace(name="Van"),
        driver=SimpleNamespace(name="Driver", line_user_id="U" + "a" * 32),
        total_distance=Decimal("1.000"),
        stops=[
            SimpleNamespace(is_depot=True, stop_order=0),
            SimpleNamespace(
                is_depot=False,
                stop_order=1,
                customer=customer,
                shipment=SimpleNamespace(packages=[SimpleNamespace(id=7)]),
            ),
        ],
    )

    class FakeRepository:
        def list_routes(self, session: object) -> list[SimpleNamespace]:
            return [route]

        def get_route(self, session: object, route_id: int) -> SimpleNamespace:
            assert route_id == route.id
            return route

    async def run_test() -> None:
        line_service = LineService(
            session_factory=lambda: nullcontext(None),  # type: ignore[arg-type]
            repository=FakeRepository(),  # type: ignore[arg-type]
            client=LineClient("mock-token", http_open=http_open),
        )
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=line_service,
        )
        async with app.run_test() as pilot:
            app.query_one("#line-route", Select).value = 10
            await pilot.pause()
            app.start_line_send()
            await app.workers.wait_for_complete()
            retry_key = app._line_retry_intents[10].retry_key
            route.driver.line_user_id = "U" + "b" * 32
            route.total_distance = Decimal("99")
            app.refresh_line_routes()
            app.start_line_send()
            await app.workers.wait_for_complete()

            first, second = requests
            assert first.data == second.data
            assert first.get_header("X-line-retry-key") == str(retry_key)
            assert second.get_header("X-line-retry-key") == str(retry_key)
            assert b'"to": "Uaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"' in second.data
            assert 10 not in app._line_retry_intents
            assert "Sent route #10" in str(app.query_one("#line-status", Static).render())

    asyncio.run(run_test())


def test_replaced_loading_optimizations_run_one_at_a_time_and_ignore_old_result() -> None:
    started = Event()
    release = Event()

    class BlockingPackingService(FakePackingService):
        def __init__(self) -> None:
            super().__init__()
            self.lock = Lock()
            self.active = 0
            self.max_active = 0

        def optimize(self, route_id: int, *, cancel_event: Event | None = None) -> LoadingPlanDraft:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                if route_id == 10:
                    started.set()
                    if not release.wait(timeout=3):
                        raise RuntimeError("timed out waiting for packing test release")
                return super().optimize(route_id, cancel_event=cancel_event)
            finally:
                with self.lock:
                    self.active -= 1

    async def run_test() -> None:
        service = BlockingPackingService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=service,  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            selector = app.query_one("#loading-route", Select)
            selector.value = 10
            await pilot.pause()
            app.start_loading_optimization()
            assert await asyncio.to_thread(started.wait, 2)
            selector.value = 11
            await pilot.pause()
            app.start_loading_optimization()
            await asyncio.sleep(0.05)
            assert service.active == 1
            assert service.optimized == []
            release.set()
            await wait_until(
                lambda: (
                    app.current_loading_plan is not None and app.current_loading_plan.route_id == 11
                )
            )
            assert service.max_active == 1
            assert service.optimized == [10, 11]
            assert app.current_loading_plan is not None
            assert app.current_loading_plan.route_id == 11

    asyncio.run(run_test())


def test_repeated_route_optimizations_ignore_cancelled_result_without_overlap() -> None:
    started = Event()
    release = Event()

    class BlockingRoutingService(FakeRoutingService):
        def __init__(self) -> None:
            self.lock = Lock()
            self.active = 0
            self.max_active = 0
            self.calls = 0

        def optimize(
            self,
            shipment_ids: list[int],
            vehicle_ids: list[int],
            *,
            cancel_event: Event | None = None,
        ) -> RoutingPlan:
            with self.lock:
                self.active += 1
                self.calls += 1
                call = self.calls
                self.max_active = max(self.max_active, self.active)
            try:
                if call == 1:
                    started.set()
                    if not release.wait(timeout=3):
                        raise RuntimeError("timed out waiting for routing test release")
                return self.plan().model_copy(update={"total_distance": Decimal(call)})
            finally:
                with self.lock:
                    self.active -= 1

    async def run_test() -> None:
        service = BlockingRoutingService()
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=service,  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test():
            app._routing_request = 1
            first_cancel = Event()
            app._routing_cancel_event = first_cancel
            app.run_route_optimization([1], [1], 1, first_cancel)
            assert await asyncio.to_thread(started.wait, 2)
            app._routing_request = 2
            first_cancel.set()
            second_cancel = Event()
            app._routing_cancel_event = second_cancel
            app.run_route_optimization([1], [1], 2, second_cancel)
            await asyncio.sleep(0.05)
            assert service.active == 1
            release.set()
            await wait_until(lambda: app.current_plan is not None)
            assert service.max_active == 1
            assert service.calls == 2
            assert app.current_plan is not None
            assert app.current_plan.total_distance == Decimal(2)

    asyncio.run(run_test())


def test_changing_route_inputs_discard_in_flight_preview() -> None:
    started = Event()
    release = Event()

    class BlockingRoutingService(FakeRoutingService):
        def optimize(
            self,
            shipment_ids: list[int],
            vehicle_ids: list[int],
            *,
            cancel_event: Event | None = None,
        ) -> RoutingPlan:
            started.set()
            if not release.wait(timeout=3):
                raise RuntimeError("timed out waiting for route input change")
            return self.plan()

    async def run_test() -> None:
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=BlockingRoutingService(),  # type: ignore[arg-type]
            packing_service=FakePackingService(),  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            cancel_event = Event()
            app._routing_cancel_event = cancel_event
            app._routing_request = 1
            app.run_route_optimization([1], [1], 1, cancel_event)
            assert await asyncio.to_thread(started.wait, 2)
            app.query_one("#routing-shipments", SelectionList).select(1)
            await pilot.pause()
            assert cancel_event.is_set()
            release.set()
            await app.workers.wait_for_complete()
            assert app.current_plan is None
            assert app.query_one("#save-routes", Button).disabled

    asyncio.run(run_test())


def test_quit_cooperatively_signals_running_optimization() -> None:
    started = Event()
    stopped = Event()

    class CooperativePackingService(FakePackingService):
        def optimize(self, route_id: int, *, cancel_event: Event | None = None) -> LoadingPlanDraft:
            assert cancel_event is not None
            started.set()
            if not cancel_event.wait(timeout=3):
                raise RuntimeError("quit did not signal running optimization")
            stopped.set()
            raise CancelledError("loading optimization was replaced")

    async def run_test() -> None:
        app = LogisticsApp(
            shipment_service=FakeShipmentService(),  # type: ignore[arg-type]
            vehicle_service=FakeVehicleService(),  # type: ignore[arg-type]
            routing_service=FakeRoutingService(),  # type: ignore[arg-type]
            packing_service=CooperativePackingService(),  # type: ignore[arg-type]
            line_service=FakeLineService(),  # type: ignore[arg-type]
        )
        async with app.run_test() as pilot:
            app.query_one("#loading-route", Select).value = 10
            await pilot.pause()
            app.start_loading_optimization()
            assert await asyncio.to_thread(started.wait, 2)
            await app.action_quit()
            assert await asyncio.to_thread(stopped.wait, 2)

    asyncio.run(run_test())


def test_cancelled_thread_worker_keeps_event_loop_responsive() -> None:
    async def run_test() -> None:
        task = asyncio.create_task(run_in_worker_thread(time.sleep, 0.4))
        await asyncio.sleep(0.03)
        start = time.monotonic()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.01)
        assert time.monotonic() - start < 0.2

    asyncio.run(run_test())
