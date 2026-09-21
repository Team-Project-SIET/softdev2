import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.markup import escape
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    Select,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)

from app.integrations.line.exceptions import LineApiError, LineNetworkError
from app.integrations.line.schemas import LineRouteCandidate, LineSendIntent, SentLineRoute
from app.integrations.line.service import LineService
from app.packing.schemas import LoadingPlanDraft
from app.packing.service import PackingService
from app.routing.schemas import RoutingPlan
from app.routing.service import RoutingService
from app.shipment.service import ShipmentService
from app.vehicle.service import VehicleService


async def run_in_worker_thread[T](
    function: Callable[..., T], *args: object, finish_on_cancel: bool = False
) -> T:
    """Run blocking work off the UI loop; optionally track it through cancellation."""

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="logistics-tui")
    future = loop.run_in_executor(executor, function, *args)
    try:
        if not finish_on_cancel:
            return await future
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A Python thread cannot be killed safely. Keep the single-flight
            # lock until it finishes, while allowing the UI loop to run.
            try:
                await asyncio.shield(future)
            except Exception:
                pass
            raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


class LogisticsApp(App[None]):
    """Operations dashboard, route planning and package loading."""

    TITLE = "Logistics Optimizer"
    SUB_TITLE = "Operations, CVRP and loading"
    BINDINGS = [("r", "refresh_data", "Refresh"), ("q", "quit", "Quit")]

    CSS = """
    Screen {
        background: $surface;
    }

    VerticalScroll {
        padding: 1 2;
    }

    SelectionList {
        height: 9;
        margin-bottom: 1;
        border: round $primary;
    }

    Horizontal {
        height: auto;
        margin-bottom: 1;
    }

    Button {
        margin-right: 1;
    }

    .section-title {
        color: $accent;
        text-style: bold;
        margin-top: 1;
    }

    DataTable {
        height: auto;
        min-height: 7;
        margin-bottom: 1;
        border: round $primary;
    }

    #status, #routing-status, #line-status {
        height: 1;
        color: $text-muted;
    }

    #loading-status, #loading-metrics, #loading-guide {
        height: auto;
        margin-bottom: 1;
    }

    #route-results, #route-stops {
        min-height: 8;
    }
    """

    def __init__(
        self,
        shipment_service: ShipmentService | None = None,
        vehicle_service: VehicleService | None = None,
        routing_service: RoutingService | None = None,
        packing_service: PackingService | None = None,
        line_service: LineService | None = None,
    ) -> None:
        super().__init__()
        self.shipment_service = shipment_service or ShipmentService()
        self.vehicle_service = vehicle_service or VehicleService()
        self.routing_service = routing_service or RoutingService()
        self.current_plan: RoutingPlan | None = None
        self.packing_service = packing_service or PackingService()
        self.line_service = line_service or LineService()
        self.current_loading_plan: LoadingPlanDraft | None = None
        self._line_routes: dict[int, LineRouteCandidate] = {}
        self._line_retry_intents: dict[int, LineSendIntent] = {}
        self._line_busy = False
        self._optimization_lock = asyncio.Lock()
        self._routing_request = 0
        self._routing_cancel_event: Event | None = None
        self._packing_request = 0
        self._packing_busy = False
        self._packing_cancel_event: Event | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Operations", id="operations-tab"):
                with VerticalScroll():
                    yield Label("Shipments", classes="section-title")
                    yield DataTable(id="shipments")
                    yield Label("Vehicles", classes="section-title")
                    yield DataTable(id="vehicles")
                    yield Static("Ready", id="status")
            with TabPane("Route Optimization", id="routing-tab"):
                with VerticalScroll():
                    yield Label("Pending shipments", classes="section-title")
                    yield SelectionList[int](id="routing-shipments")
                    yield Label("Available vehicles (select 1–3)", classes="section-title")
                    yield SelectionList[int](id="routing-vehicles")
                    with Horizontal():
                        yield Button("Optimize routes", id="optimize-routes", variant="primary")
                        yield Button("Save route plan", id="save-routes", disabled=True)
                    yield Static("Select shipments and vehicles.", id="routing-status")
                    yield Label("Vehicle routes", classes="section-title")
                    yield DataTable(id="route-results")
                    yield Label("Ordered stops", classes="section-title")
                    yield DataTable(id="route-stops")
                    yield Label("Send saved route", classes="section-title")
                    yield Select[int]([], prompt="Select a saved route", id="line-route")
                    with Horizontal():
                        yield Button("Refresh saved routes", id="refresh-line-routes")
                        yield Button(
                            "Send to LINE", id="send-line", variant="success", disabled=True
                        )
                    yield Static("Select a saved route.", id="line-status")
            with TabPane("Loading Optimization", id="loading-tab"):
                with VerticalScroll():
                    yield Label("Saved route", classes="section-title")
                    yield Select[int]([], prompt="Select a saved route", id="loading-route")
                    with Horizontal():
                        yield Button("Refresh routes", id="refresh-loading-routes")
                        yield Button("Optimize loading", id="optimize-loading", variant="primary")
                        yield Button("Save loading plan", id="save-loading", disabled=True)
                    yield Static("Select a saved route.", id="loading-status")
                    yield Static(
                        "Coordinates in cm: x across width, y inward from rear door (y=0), "
                        "z above floor. Orientation gives original W/L/H along x/y/z. "
                        "Orders start at 1. Review partial plans before saving.",
                        id="loading-guide",
                    )
                    yield Static("No loading plan yet.", id="loading-metrics")
                    yield Label("Packages by delivery stop", classes="section-title")
                    yield DataTable(id="loading-packages")
                    yield Label("Loading order", classes="section-title")
                    yield DataTable(id="loading-order")
                    yield Label("Unloading order", classes="section-title")
                    yield DataTable(id="unloading-order")
                    yield Label("Unplaced packages", classes="section-title")
                    yield DataTable(id="unplaced-packages")
        yield Footer()

    def on_mount(self) -> None:
        shipments = self.query_one("#shipments", DataTable)
        shipments.cursor_type = "row"
        shipments.add_columns(
            "ID", "Customer", "Delivery date", "Priority", "Status", "Packages", "Weight"
        )

        vehicles = self.query_one("#vehicles", DataTable)
        vehicles.cursor_type = "row"
        vehicles.add_columns("ID", "Name", "Status", "Cargo W × L × H (cm)", "Max weight (kg)")

        route_results = self.query_one("#route-results", DataTable)
        route_results.add_columns("Vehicle", "Route", "Distance", "Payload")
        route_stops = self.query_one("#route-stops", DataTable)
        route_stops.add_columns("Vehicle", "Order", "Stop", "From previous")
        self.query_one("#loading-packages", DataTable).add_columns(
            "Stop",
            "Shipment",
            "Package",
            "W × L × H (cm)",
            "Weight (kg)",
            "x",
            "y",
            "z",
            "Orientation",
            "Load #",
            "Unload #",
            "Result",
        )
        for table_id in ("loading-order", "unloading-order"):
            self.query_one(f"#{table_id}", DataTable).add_columns(
                "Order", "Stop", "Package", "x, y, z (cm)", "Orientation"
            )
        self.query_one("#unplaced-packages", DataTable).add_columns("Stop", "Package", "Reason")
        self.refresh_data()
        self.refresh_routing_candidates()
        self.refresh_loading_routes()
        self.refresh_line_routes()

    def action_refresh_data(self) -> None:
        self.refresh_data()
        self.refresh_routing_candidates()
        self.refresh_loading_routes()
        self.refresh_line_routes()

    def on_unmount(self) -> None:
        self._cancel_optimizations()

    def _cancel_optimizations(self) -> None:
        if self._routing_cancel_event is not None:
            self._routing_cancel_event.set()
        if self._packing_cancel_event is not None:
            self._packing_cancel_event.set()

    async def action_quit(self) -> None:
        self._cancel_optimizations()
        await super().action_quit()

    def refresh_data(self) -> None:
        shipment_table = self.query_one("#shipments", DataTable)
        vehicle_table = self.query_one("#vehicles", DataTable)
        status = self.query_one("#status", Static)
        shipment_table.clear()
        vehicle_table.clear()

        try:
            shipments = self.shipment_service.list_shipments()
            vehicles = self.vehicle_service.list_vehicles()
        except Exception as exc:  # The dashboard should remain usable when the DB is unavailable.
            status.update(f"[red]Could not load PostgreSQL data:[/red] {escape(str(exc))}")
            return

        for shipment in shipments:
            shipment_table.add_row(
                str(shipment.id),
                shipment.customer_name,
                shipment.delivery_date.isoformat(),
                shipment.priority.value,
                shipment.status.value,
                str(shipment.package_count),
                f"{shipment.total_weight:.2f} kg",
                key=str(shipment.id),
            )

        for vehicle in vehicles:
            vehicle_table.add_row(
                str(vehicle.id),
                vehicle.name,
                vehicle.status.value,
                f"{vehicle.width} × {vehicle.length} × {vehicle.height}",
                f"{vehicle.max_weight} kg",
                key=str(vehicle.id),
            )

        status.update(f"Loaded {len(shipments)} shipments and {len(vehicles)} vehicles.")

    def refresh_routing_candidates(self) -> None:
        shipment_list = self.query_one("#routing-shipments", SelectionList)
        vehicle_list = self.query_one("#routing-vehicles", SelectionList)
        status = self.query_one("#routing-status", Static)
        shipment_list.clear_options()
        vehicle_list.clear_options()
        try:
            candidates = self.routing_service.list_candidates()
        except Exception as exc:
            status.update(f"[red]Could not load routing candidates:[/red] {escape(str(exc))}")
            return

        for shipment in candidates.shipments:
            shipment_list.add_option(
                (
                    f"#{shipment.id} · {shipment.customer_name} · "
                    f"{shipment.delivery_date.isoformat()} · {shipment.demand_kg:.2f} kg",
                    shipment.id,
                )
            )
        for vehicle in candidates.vehicles:
            vehicle_list.add_option(
                (f"#{vehicle.id} · {vehicle.name} · {vehicle.capacity_kg:.2f} kg", vehicle.id)
            )
        status.update(
            f"Loaded {len(candidates.shipments)} pending shipments and "
            f"{len(candidates.vehicles)} available vehicles."
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "optimize-routes":
            if self._routing_cancel_event is not None:
                self._routing_cancel_event.set()
            cancel_event = Event()
            self._routing_cancel_event = cancel_event
            self._routing_request += 1
            shipment_ids = list(self.query_one("#routing-shipments", SelectionList).selected)
            vehicle_ids = list(self.query_one("#routing-vehicles", SelectionList).selected)
            self.query_one("#routing-status", Static).update("Optimizing routes…")
            self.query_one("#save-routes", Button).disabled = True
            self.query_one("#optimize-routes", Button).disabled = True
            self.run_route_optimization(
                shipment_ids, vehicle_ids, self._routing_request, cancel_event
            )
        elif event.button.id == "save-routes":
            self.save_route_plan()
        elif event.button.id == "refresh-line-routes":
            self.refresh_line_routes()
        elif event.button.id == "send-line":
            self.start_line_send()
        elif event.button.id == "refresh-loading-routes":
            self.refresh_loading_routes()
        elif event.button.id == "optimize-loading":
            self.start_loading_optimization()
        elif event.button.id == "save-loading":
            self.save_loading_plan()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        if event.selection_list.id not in {"routing-shipments", "routing-vehicles"}:
            return
        if self.current_plan is None and self._routing_cancel_event is None:
            return
        if self._routing_cancel_event is not None:
            self._routing_cancel_event.set()
        self._routing_request += 1
        self.current_plan = None
        self.query_one("#route-results", DataTable).clear()
        self.query_one("#route-stops", DataTable).clear()
        self.query_one("#save-routes", Button).disabled = True
        self.query_one("#optimize-routes", Button).disabled = False
        self.query_one("#routing-status", Static).update(
            "Selection changed; optimize routes again."
        )

    @work(exclusive=True, group="routing-optimization")
    async def run_route_optimization(
        self,
        shipment_ids: list[int],
        vehicle_ids: list[int],
        request: int,
        cancel_event: Event,
    ) -> None:
        try:
            plan = await self._run_optimization(
                lambda: self.routing_service.optimize(
                    shipment_ids, vehicle_ids, cancel_event=cancel_event
                )
            )
        except Exception as exc:
            if request == self._routing_request:
                self.show_routing_error(str(exc))
            return
        finally:
            if self._routing_cancel_event is cancel_event:
                self._routing_cancel_event = None
        if request == self._routing_request and not cancel_event.is_set():
            self.display_route_plan(plan)

    async def _run_optimization[T](self, function: Callable[..., T], *args: object) -> T:
        # Route and packing jobs share one gate. Cancelled workers retain the
        # gate until their underlying thread finishes.
        async with self._optimization_lock:
            return await run_in_worker_thread(function, *args, finish_on_cancel=True)

    def display_route_plan(self, plan: RoutingPlan) -> None:
        self.query_one("#optimize-routes", Button).disabled = False
        self.current_plan = plan
        results = self.query_one("#route-results", DataTable)
        stops_table = self.query_one("#route-stops", DataTable)
        results.clear()
        stops_table.clear()

        for route in plan.routes:
            route_labels = [
                "Depot" if stop.is_depot else f"Shipment #{stop.shipment_id}"
                for stop in route.stops
            ]
            results.add_row(
                str(route.vehicle_id),
                " → ".join(route_labels),
                f"{route.total_distance:.3f} km",
                f"{route.total_weight:.3f} kg",
            )
            for stop in route.stops:
                stop_label = (
                    "Depot"
                    if stop.is_depot
                    else f"Customer #{stop.customer_id} / Shipment #{stop.shipment_id}"
                )
                stops_table.add_row(
                    str(route.vehicle_id),
                    str(stop.stop_order),
                    stop_label,
                    f"{stop.distance_from_previous:.3f} km",
                )

        self.query_one("#routing-status", Static).update(
            f"Optimized {sum(len(route.stops) - 2 for route in plan.routes)} shipments; "
            f"fleet distance {plan.total_distance:.3f} km."
        )
        self.query_one("#save-routes", Button).disabled = False

    def show_routing_error(self, message: str) -> None:
        self.query_one("#optimize-routes", Button).disabled = False
        self.current_plan = None
        self.query_one("#routing-status", Static).update(
            f"[red]Optimization failed:[/red] {escape(message)}"
        )
        self.query_one("#save-routes", Button).disabled = True

    def save_route_plan(self) -> None:
        if self.current_plan is None:
            self.show_routing_error("run optimization before saving")
            return
        try:
            saved = self.routing_service.save_plan(self.current_plan)
        except Exception as exc:
            self.show_routing_error(f"could not save plan: {exc}")
            return
        self.query_one("#routing-status", Static).update(
            f"Saved routes {saved.route_ids} with {saved.shipment_count} shipments."
        )
        self.query_one("#save-routes", Button).disabled = True
        self.current_plan = None
        self.refresh_data()
        self.refresh_routing_candidates()
        self.refresh_loading_routes()
        self.refresh_line_routes()

    def refresh_line_routes(self) -> None:
        selector = self.query_one("#line-route", Select)
        selected_route = selector.value
        self.query_one("#send-line", Button).disabled = True
        try:
            routes = self.line_service.list_routes()
        except Exception as exc:
            retry_available = (
                isinstance(selected_route, int)
                and selected_route in self._line_retry_intents
                and not self._line_busy
            )
            self.query_one("#send-line", Button).disabled = not retry_available
            self.query_one("#line-status", Static).update(
                f"[red]Could not load saved routes:[/red] {escape(str(exc))}"
                + (" The pending LINE send can still be retried." if retry_available else "")
            )
            return

        self._line_routes = {route.route_id: route for route in routes}
        with self.prevent(Select.Changed):
            selector.set_options(
                [
                    (
                        f"Route #{route.route_id} · {route.vehicle_name} · "
                        f"Driver: {route.driver_name or 'Unassigned'} · "
                        f"{route.stop_count} stops",
                        route.route_id,
                    )
                    for route in routes
                ]
            )
            if isinstance(selected_route, int) and selected_route in self._line_routes:
                selector.value = selected_route
        if isinstance(selector.value, int):
            self.show_selected_line_route(selector.value)
        else:
            self.query_one("#line-status", Static).update(
                "Select a saved route." if routes else "No saved routes. Save a route plan first."
            )

    def show_selected_line_route(self, route_id: int) -> None:
        candidate = self._line_routes.get(route_id)
        retry_intent = self._line_retry_intents.get(route_id)
        button = self.query_one("#send-line", Button)
        status = self.query_one("#line-status", Static)
        if self._line_busy:
            button.disabled = True
            status.update("Sending a route to LINE…")
        elif candidate is None:
            button.disabled = True
            status.update("Select a saved route.")
        elif retry_intent is not None:
            button.disabled = False
            status.update(
                f"Delivery of route #{route_id} is uncertain. Retry with the original "
                "recipient and message."
            )
        elif candidate.driver_name is None:
            button.disabled = True
            status.update(
                f"[yellow]Route #{route_id} has no assigned driver and cannot be sent.[/yellow]"
            )
        elif not candidate.has_line_user_id:
            button.disabled = True
            status.update(
                f"[yellow]Assigned driver {escape(candidate.driver_name)} has no LINE user "
                "ID.[/yellow]"
            )
        else:
            button.disabled = False
            status.update(
                f"Assigned driver: {escape(candidate.driver_name)}. "
                f"Ready to send route #{route_id}."
            )

    def start_line_send(self) -> None:
        if self._line_busy:
            return
        route_id = self.query_one("#line-route", Select).value
        if not isinstance(route_id, int):
            self.query_one("#line-status", Static).update(
                "[red]LINE send failed:[/red] select a saved route first"
            )
            return
        self._line_busy = True
        self.query_one("#send-line", Button).disabled = True
        self.query_one("#line-status", Static).update(f"Sending route #{route_id} to LINE…")
        self.send_route_to_line(route_id, self._line_retry_intents.get(route_id))

    @work(exclusive=True, group="line-send")
    async def send_route_to_line(self, route_id: int, intent: LineSendIntent | None = None) -> None:
        try:
            if intent is None:
                intent = await run_in_worker_thread(self.line_service.prepare_send_intent, route_id)
            sent = await run_in_worker_thread(self.line_service.send_intent, intent)
        except Exception as exc:
            ambiguous = isinstance(exc, LineNetworkError) or (
                isinstance(exc, LineApiError)
                and exc.status_code is not None
                and (exc.status_code == 409 or exc.status_code >= 500)
            )
            self.finish_line_send(route_id, None, str(exc), intent if ambiguous else None)
            return
        self.finish_line_send(route_id, sent, None, None)

    def finish_line_send(
        self,
        route_id: int,
        sent: SentLineRoute | None,
        error: str | None,
        retry_intent: LineSendIntent | None,
    ) -> None:
        self._line_busy = False
        if retry_intent is not None:
            self._line_retry_intents[route_id] = retry_intent
        else:
            self._line_retry_intents.pop(route_id, None)
        selected = self.query_one("#line-route", Select).value
        if selected != route_id:
            if isinstance(selected, int):
                self.show_selected_line_route(selected)
            return
        if error is not None:
            self.query_one("#line-status", Static).update(
                f"[red]LINE send failed:[/red] {escape(error)}"
                + (" Delivery is uncertain; retry this send." if retry_intent else "")
            )
            candidate = self._line_routes.get(route_id)
            self.query_one("#send-line", Button).disabled = not (
                retry_intent or (candidate and candidate.driver_name and candidate.has_line_user_id)
            )
        elif sent is not None:
            self.query_one("#line-status", Static).update(
                f"[green]Sent route #{sent.route_id} to {escape(sent.driver_name)} on LINE.[/green]"
            )
            self.query_one("#send-line", Button).disabled = False

    def refresh_loading_routes(self) -> None:
        self.clear_loading_plan()
        selector = self.query_one("#loading-route", Select)
        with self.prevent(Select.Changed):
            selector.set_options([])
        try:
            routes = self.packing_service.list_routes()
        except Exception as exc:
            self.show_loading_error(f"could not load saved routes: {exc}")
            return
        with self.prevent(Select.Changed):
            selector.set_options(
                [
                    (
                        f"Route #{route.route_id} · {route.vehicle_name} · "
                        f"{route.stop_count} stops · {route.package_count} packages",
                        route.route_id,
                    )
                    for route in routes
                ]
            )
        self.query_one("#loading-status", Static).update(
            "Select a saved route." if routes else "No saved routes. Save a route plan first."
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "loading-route":
            self.clear_loading_plan()
        elif event.select.id == "line-route" and isinstance(event.value, int):
            self.show_selected_line_route(event.value)

    def clear_loading_plan(self) -> None:
        if self._packing_cancel_event is not None:
            self._packing_cancel_event.set()
            self._packing_cancel_event = None
        self._packing_request += 1
        self._packing_busy = False
        self.current_loading_plan = None
        self.query_one("#save-loading", Button).disabled = True
        self.query_one("#optimize-loading", Button).disabled = False
        self.query_one("#loading-status", Static).update("Select a route and optimize loading.")
        self.query_one("#loading-metrics", Static).update("No loading plan yet.")
        for table_id in (
            "loading-packages",
            "loading-order",
            "unloading-order",
            "unplaced-packages",
        ):
            self.query_one(f"#{table_id}", DataTable).clear()

    def start_loading_optimization(self) -> None:
        route_id = self.query_one("#loading-route", Select).value
        self.clear_loading_plan()
        if not isinstance(route_id, int):
            self.show_loading_error("select a saved route first")
            return
        cancel_event = Event()
        self._packing_cancel_event = cancel_event
        self._packing_busy = True
        self.query_one("#optimize-loading", Button).disabled = True
        self.query_one("#loading-status", Static).update(
            f"Optimizing loading for route #{route_id}…"
        )
        self.run_loading_optimization(route_id, self._packing_request, cancel_event)

    @work(exclusive=True, group="loading-optimization")
    async def run_loading_optimization(
        self, route_id: int, request: int, cancel_event: Event
    ) -> None:
        try:
            plan = await self._run_optimization(
                lambda: self.packing_service.optimize(route_id, cancel_event=cancel_event)
            )
        except Exception as exc:
            self.finish_loading_optimization(request, None, str(exc))
            return
        finally:
            if self._packing_cancel_event is cancel_event:
                self._packing_cancel_event = None
        if not cancel_event.is_set():
            self.finish_loading_optimization(request, plan, None)

    def finish_loading_optimization(
        self, request: int, plan: LoadingPlanDraft | None, error: str | None
    ) -> None:
        if request != self._packing_request:
            return  # Route selection changed while this worker was running.
        self._packing_busy = False
        self.query_one("#optimize-loading", Button).disabled = False
        if error is not None:
            self.show_loading_error(error)
        elif plan is not None:
            self.display_loading_plan(plan)

    def display_loading_plan(self, plan: LoadingPlanDraft) -> None:
        self.current_loading_plan = plan
        result = plan.result
        for table_id in (
            "loading-packages",
            "loading-order",
            "unloading-order",
            "unplaced-packages",
        ):
            self.query_one(f"#{table_id}", DataTable).clear()
        placements = {p.package_id: p for p in result.placements}
        unplaced = {p.package_id: p for p in result.unplaced_packages}
        stop_orders = {stop.shipment_id: stop.stop_order for stop in plan.problem.delivery_sequence}
        for package in sorted(
            plan.problem.packages, key=lambda p: (stop_orders[p.shipment_id], p.package_id)
        ):
            p = placements.get(package.package_id)
            self.query_one("#loading-packages", DataTable).add_row(
                str(stop_orders[package.shipment_id]),
                str(package.shipment_id),
                str(package.package_id),
                f"{package.width} × {package.length} × {package.height}",
                f"{package.weight:.2f}",
                str(p.x) if p else "—",
                str(p.y) if p else "—",
                str(p.z) if p else "—",
                p.orientation.value if p else "—",
                str(p.loading_order) if p else "—",
                str(p.unloading_order) if p else "—",
                "Placed" if p else unplaced[package.package_id].reason,
            )
        for table_id, order_attr in (
            ("loading-order", "loading_order"),
            ("unloading-order", "unloading_order"),
        ):
            for p in sorted(result.placements, key=lambda p: getattr(p, order_attr)):
                self.query_one(f"#{table_id}", DataTable).add_row(
                    str(getattr(p, order_attr)),
                    str(p.stop_order),
                    str(p.package_id),
                    f"{p.x}, {p.y}, {p.z}",
                    p.orientation.value,
                )
        for p in result.unplaced_packages:
            self.query_one("#unplaced-packages", DataTable).add_row(
                str(p.stop_order), str(p.package_id), p.reason
            )
        self.query_one("#loading-metrics", Static).update(
            f"Package volume: {result.total_package_volume:.2f} cm³ | "
            f"Used cargo: {result.used_cargo_volume:.2f} / {result.cargo_volume:.2f} cm³ "
            f"({result.volume_utilization_percentage:.2f}%)\n"
            f"Payload: {result.total_loaded_weight:.2f} / {plan.problem.vehicle.max_weight:.2f} kg "
            f"({result.payload_utilization_percentage:.2f}%)"
        )
        self.query_one("#loading-status", Static).update(
            f"Route #{plan.route_id}: {result.status.value}; {len(result.placements)} placed, "
            f"{len(result.unplaced_packages)} unplaced."
        )
        self.query_one("#save-loading", Button).disabled = False

    def show_loading_error(self, message: str) -> None:
        self.current_loading_plan = None
        self.query_one("#save-loading", Button).disabled = True
        self.query_one("#loading-status", Static).update(
            f"[red]Loading failed:[/red] {escape(message)}"
        )

    def save_loading_plan(self) -> None:
        if self.current_loading_plan is None or self._packing_busy:
            self.show_loading_error("run loading optimization before saving")
            return
        try:
            saved = self.packing_service.save_plan(self.current_loading_plan)
        except Exception as exc:
            self.show_loading_error(f"could not save plan: {exc}")
            return
        self.current_loading_plan = None
        self.query_one("#save-loading", Button).disabled = True
        self.query_one("#loading-status", Static).update(
            f"Saved loading plan #{saved.loading_plan_id} for route #{saved.route_id}: "
            f"{saved.placement_count} placements ({saved.status.value})."
        )


def main() -> None:
    LogisticsApp().run()


if __name__ == "__main__":
    main()
