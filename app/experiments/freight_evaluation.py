"""P07 evaluation of retained native freight evidence. No runtime operations."""

import hashlib
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypedDict

from app.planning.canonical import plan_hash
from app.planning.domain import Contract, Digest, ExecutionPlan, PlanningScenario, RoadFleetOption
from app.planning.realized import ArtifactReference
from app.simulation.openttd.proof.freight_delivery import consumed_identity, verify_receipt


def document_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FreightMetric(Contract):
    name: str
    unit: str
    scope: str
    actual: Decimal | None
    planned: Decimal | None = None
    comparison: Literal["comparable", "unavailable", "incompatible"] = "unavailable"
    difference: Decimal | None = None  # Actual minus planned; not an absolute error.
    provenance: str


class FreightEvaluation(Contract):
    schema_version: Literal[1] = 1
    run_name: str
    attempt: int
    mode: Literal["standalone", "planner-driven"]
    status: Literal["verified-delivery", "failed"]
    reason: str | None
    source_directory: str
    receipt: ArtifactReference | None
    artifact_manifest: ArtifactReference
    result: ArtifactReference
    native_plan_digest: Digest | None
    execution_plan_digest: Digest | None
    cohort_digest: Digest | None
    cohort_definition: dict
    metrics: tuple[FreightMetric, ...]
    findings: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def history_key(self) -> str:
        return self.receipt.sha256 if self.receipt else self.artifact_manifest.sha256


class _RunIdentity(TypedDict):
    run_name: str
    attempt: int
    mode: Literal["standalone", "planner-driven"]
    source_directory: str
    artifact_manifest: ArtifactReference
    result: ArtifactReference


def evaluate_freight(directory: Path) -> FreightEvaluation:
    """Verify first, then evaluate. Failed attempts retain unknown delivery metrics."""
    directory = directory.resolve()

    def read(name):
        return json.loads((directory / name).read_bytes())

    def reference(name):
        return ArtifactReference(
            sha256=hashlib.sha256((directory / name).read_bytes()).hexdigest(), reference=name
        )

    consumed_identity(directory)  # Immutable package, claim and retained cleanup; no live probe.
    metadata, result = read("PRELAUNCH.json"), read("result.json")
    mode: Literal["standalone", "planner-driven"] = (
        "planner-driven" if metadata.get("planner") else "standalone"
    )
    common = _RunIdentity(
        run_name=directory.name,
        attempt=metadata["attempt"],
        mode=mode,
        source_directory=str(directory),
        artifact_manifest=reference("artifact-manifest.sha256"),
        result=reference("result.json"),
    )
    if result["status"] != "NATIVE_DELIVERY_VERIFIED":
        return FreightEvaluation(
            **common,
            status="failed",
            reason=result.get("error", result["status"]),
            receipt=None,
            native_plan_digest=None,
            execution_plan_digest=None,
            cohort_digest=None,
            cohort_definition={},
            metrics=(),
            findings=(),
            limitations=("No verified paid delivery; excluded from successful-run statistics.",),
        )
    receipt = verify_receipt(directory)
    native = read("plan.json")
    baseline = read("read-8-response.json")["s"]
    final = read("finish-1-response.json")["s"]
    loaded = read("observe-1-response.json")["s"]
    arrival = read("observe-2-response.json")["s"]
    costs = receipt["mutation_costs"]
    planned: dict[str, Decimal] = {}
    execution_digest = None
    policy = None
    corridor_tiles = (
        abs(native["a"][5] % 64 - native["a"][7] % 64)
        + abs(native["a"][5] // 64 - native["a"][7] // 64)
        + 1
    )
    if mode == "planner-driven":
        plan = ExecutionPlan.model_validate_json((directory / "execution-plan.json").read_bytes())
        scenario = PlanningScenario.model_validate_json(
            (directory / "planning-scenario.json").read_bytes()
        )
        execution_digest = plan_hash(plan)
        if receipt["planning_binding"]["execution_plan_digest"] != execution_digest:
            raise ValueError("P07 execution plan differs from verified receipt binding")
        options = {o.option_id: o for o in scenario.fleet_options}
        planned["delivered_cargo"] = Decimal(
            sum(c.quantity for route in plan.routes for c in route.cargo_assignments)
        )
        planned["vehicles"] = Decimal(sum(g.count for g in plan.fleet.groups))
        for kind, name in (("station", "stations"), ("depot", "depots")):
            planned[name] = Decimal(sum(a.kind == kind for a in plan.infrastructure.actions))
        planned["infrastructure_capex"] = sum(
            (a.estimated_build_cost_gbp for a in plan.infrastructure.actions), Decimal(0)
        )
        for kind, name in (
            ("segment", "road_capex"),
            ("station", "station_capex"),
            ("depot", "depot_capex"),
        ):
            planned[name] = sum(
                (a.estimated_build_cost_gbp for a in plan.infrastructure.actions if a.kind == kind),
                Decimal(0),
            )
        purchase = Decimal(0)
        for group in plan.fleet.groups:
            option = options[group.option_id]
            if not isinstance(option, RoadFleetOption):
                raise ValueError("freight evaluation requires the verified road MVP")
            purchase += group.count * option.vehicle.purchase_cost_gbp
        planned["vehicle_purchase"] = purchase
        planned["total_capex"] = purchase + planned["infrastructure_capex"]
        corridor_tiles = len(receipt["planning_binding"]["selection"]["path"])
        planned["corridor_tiles"] = Decimal(corridor_tiles)
        policy = read("planning-policy.json")

    metrics = []

    def metric(name, actual, unit, scope, provenance):
        estimate = planned.get(name)
        amount = Decimal(actual) if actual is not None else None
        metrics.append(
            FreightMetric(
                name=name,
                actual=amount,
                planned=estimate,
                unit=unit,
                scope=scope,
                comparison="comparable"
                if estimate is not None and amount is not None
                else "unavailable",
                difference=amount - estimate
                if estimate is not None and amount is not None
                else None,
                provenance=provenance,
            )
        )

    metric(
        "delivered_cargo",
        receipt["delivered"],
        "cargo_units",
        "first_paid_batch",
        "Verified destination-industry monitor and unloading; planned batch, not a rate forecast.",
    )
    metric("stations", 2, "facilities", "construction", "Two distinct owned station readbacks.")
    metric("depots", 1, "facilities", "construction", "Owned depot and connected front readback.")
    metric(
        "corridor_tiles",
        corridor_tiles,
        "tiles",
        "construction",
        "Verified connected corridor geometry; excludes station/depot footprints and spur bits.",
    )
    metric("vehicles", 1, "vehicles", "construction", "Single native vehicle ID, owner and orders.")
    metric(
        "infrastructure_capex",
        sum(costs[:6]),
        "GBP",
        "construction",
        "Native command accounting, stages 0..5; world preparation excluded.",
    )
    for name, amount, stages in (
        ("road_capex", sum(costs[:3]), "roads including station/depot entrance bits"),
        ("station_capex", sum(costs[3:5]), "two station commands"),
        ("depot_capex", costs[5], "depot command"),
    ):
        metric(name, amount, "GBP", "construction", "Native accounting for " + stages + ".")
    metric(
        "vehicle_purchase", costs[6], "GBP", "construction", "Native purchase accounting, stage 6."
    )
    metric(
        "total_capex",
        receipt["construction_purchase_spending"],
        "GBP",
        "construction",
        "Verified sum of service construction and purchase commands.",
    )
    metric(
        "delivery_revenue",
        receipt["payment_income"],
        "GBP",
        "observed_service_window",
        "Verified company income across explicitly retained economy periods.",
    )
    metric(
        "vehicle_profit",
        receipt["vehicle_profit_delta"],
        "GBP",
        "observed_service_window",
        "Native displayed vehicle profit delta; excludes company finance and infrastructure costs.",
    )
    metric(
        "revenue_profit_residual",
        receipt["payment_income"] - receipt["vehicle_profit_delta"],
        "GBP",
        "observed_service_window",
        "Derived revenue minus displayed vehicle profit; not authoritative operating costs.",
    )
    metric(
        "operating_costs",
        None,
        "GBP",
        "observed_service_window",
        "No complete itemized company/vehicle expense and financing ledger retained.",
    )
    metric(
        "net_return",
        None,
        "GBP",
        "observed_service_window",
        "Unknown full operating costs; CAPEX is not subtracted from vehicle profit as net return.",
    )
    metric(
        "cash_change",
        final[3] - baseline[3],
        "GBP",
        "observed_service_window",
        "Native bank balance delta after construction; "
        "unallocated financing flows may be included.",
    )
    metric(
        "load_fill",
        Decimal(loaded[11]) / loaded[7] * 100,
        "percent",
        "loaded_departure",
        "Measured cargo load / native capacity at source; not time utilization.",
    )
    metric(
        "source_waiting",
        final[15],
        "cargo_units",
        "terminal_snapshot",
        "Native cargo waiting at the source station after the paid delivery.",
    )
    metric(
        "time_utilization",
        None,
        "percent",
        "observed_service_window",
        "Sparse phase snapshots cannot measure moving/idle time fractions.",
    )
    metric(
        "observation_days",
        final[1] - baseline[1],
        "economy_days",
        "observed_service_window",
        "Economy date difference, not a complete planned-horizon evaluation.",
    )
    metric(
        "transit_ticks",
        arrival[0] - loaded[0],
        "script_ticks",
        "loaded_source_to_arrival",
        "Native phase timestamps include source dwell and travel; not pathfinder distance.",
    )
    findings = []
    if planned and sum(costs[:6]) > planned["infrastructure_capex"]:
        error = Decimal(sum(costs[:6])) - planned["infrastructure_capex"]
        findings.append(
            f"Infrastructure estimate understates native CAPEX by £{error}. "
            "Reconcile corridor, station and depot estimates with retained command quotes."
        )
    findings.append(
        f"The first paid load returned £{receipt['payment_income']} against "
        f"£{receipt['construction_purchase_spending']} service CAPEX. "
        "Measure repeat deliveries and full expenses before assessing capital recovery."
    )
    if loaded[11] == loaded[7]:
        findings.append(
            "Measured source load filled 100% of capacity; no capacity underfill is shown."
        )
    if final[15] > 0:
        findings.append(
            f"Source station retained {final[15]} waiting cargo units after delivery. "
            "Measure repeat-trip frequency and queue growth before expanding the fleet."
        )
    route_distance = abs(native["a"][4] % 64 - native["a"][6] % 64) + abs(
        native["a"][4] // 64 - native["a"][6] // 64
    )
    findings.append(
        f"Station separation is {route_distance} Manhattan tiles. "
        "Sparse snapshots do not establish actual distance, detours or routing inefficiency."
    )
    with zipfile.ZipFile(directory / "frozen-source.zip") as archive:
        bridge_names = sorted(
            name
            for name in archive.namelist()
            if name.endswith(".nut")
            and (
                name.startswith("staged/")
                if mode == "planner-driven"
                else name.startswith("app/simulation/openttd/freight_delivery_package/")
            )
        )
        bridge_digest = hashlib.sha256(
            b"".join(name.encode() + b"\0" + archive.read(name) for name in bridge_names)
        ).hexdigest()
    cohort = dict(
        mode=mode,
        binary_sha256=metadata["binary_sha256"],
        graphics_archive_sha256=read("graphics-identity.json")["archive_sha256"],
        world=metadata["world"],
        selection=native["a"],
        native_facts=native["f"],
        policy=policy,
        observed_economy_days=final[1] - baseline[1],
        measurement="one-paid-batch",
        orders=receipt["orders"],
        bridge_semantics_digest=bridge_digest,
    )
    return FreightEvaluation(
        **common,
        status="verified-delivery",
        reason=None,
        receipt=reference("receipt.json"),
        native_plan_digest=receipt["plan_digest"],
        execution_plan_digest=execution_digest,
        cohort_digest=document_digest(cohort),
        cohort_definition=cohort,
        metrics=tuple(metrics),
        findings=tuple(findings),
        limitations=(
            "One paid batch; no recurring reliability, "
            "whole-horizon forecast or long-run profitability.",
            "Full operating expenses, net return and time utilization are unknown.",
            "Only matching modes, runtime/content, geometry, supply, "
            "policy and measured windows compare.",
            "CAPEX excludes world preparation, loan principal, "
            "residual asset value and depreciation.",
        ),
    )
