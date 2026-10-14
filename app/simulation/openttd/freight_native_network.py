"""Bounded multi-service sequencing and receipt replay through the existing freight executor."""

import asyncio
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import ExecutionPlan, PlanningScenario, PreparedWorldManifest
from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
from app.planning.p08_network import generate_freight_network
from app.simulation.openttd.freight_delivery import (
    DeliveryPlan,
    DeliveryReadback,
    DeliveryRequest,
    admit,
    verify_delivery,
    verify_observation,
    verify_snapshot,
)
from app.simulation.openttd.freight_planning import (
    PlanningSelectionRequest,
    compile_freight_network,
)
from app.simulation.openttd.freight_runtime_planning import (
    capture_planning_facts,
    collect_qualified_world,
    native_correspondence,
)
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.proof.harness import manifest, sha256, write_json


def bounded_relationships(world):
    caps = world.structural.capability.observation.capabilities
    positive = {
        (r.industry_id, r.cargo_id) for r in world.production.records if r.last_month_produced > 0
    }
    freight = {r.cargo_id for r in world.structural.catalog.observation.records if r.is_freight}
    records = {r.id: r for r in world.structural.inventory.observation.records}
    selected, rejected = [], []
    for src, dst, cargo in sorted(
        {
            (s.industry_id, d.industry_id, c)
            for s in caps
            for c in s.produces
            for d in caps
            if (s.industry_id, c) in positive
            and c in freight
            and s.industry_id != d.industry_id
            and c in d.accepts
        }
    ):
        a, b = records[src], records[dst]
        x, y = min(a.x, b.x) - 2, min(a.y, b.y) - 2
        w, h = abs(a.x - b.x) + 4, abs(a.y - b.y) + 4
        if x < 1 or y < 1 or x + w >= 63 or y + h >= 63 or w * h > 256:
            rejected.append(
                dict(source=src, destination=dst, cargo=cargo, reason="CAPTURE_REGION_BOUND")
            )
        else:
            selected.append((src, dst, cargo))
    if not 2 <= len(selected) <= 4:
        raise ValueError("native network requires 2..4 bounded qualified relationships")
    return tuple(selected), rejected


def network_from_facts(world, facts, source, policy, *, max_vehicles=2):
    # Each raw package is retained separately. The combined bracket encompasses
    # every read, without inventing simultaneous capture or upgrading its trust.
    before = min(f.capture_economy_date_before for f in facts)
    after = max(f.capture_economy_date_after for f in facts)
    month = world.production.qualification.current_month
    if not month.start_date <= before <= after < month.end_date:
        raise ValueError("network facts crossed the qualified economy month")
    packages = tuple(
        adapt_planning_facts(
            ValidatedPlanningFactInput(
                world,
                f.model_copy(
                    update={
                        "capture_economy_date_before": before,
                        "capture_economy_date_after": after,
                    }
                ),
                source,
            ),
            policy,
        )
        for f in facts
    )
    return generate_freight_network(packages, max_vehicles=max_vehicles)


async def plan_network_world(backend, prepared, session, accounting, before, batch_limit):
    from app.simulation.openttd.proof.road_mutation import save

    world = await collect_qualified_world(backend, prepared, session, accounting)
    relationships, rejected = bounded_relationships(world)
    write_json(
        prepared.directory / "network-candidates.json",
        dict(relationships=relationships, rejected=rejected),
    )
    facts, count = [], 0
    for n, relationship in enumerate(relationships):
        value = await capture_planning_facts(
            backend, prepared, world, relationship=relationship, prefix=f"n{n}-", retain=False
        )
        count += backend.planning_read_count
        facts.append(value)
        write_json(prepared.directory / f"network-facts-{n}.json", value.model_dump(mode="json"))
    backend.planning_read_count = count
    final = await save(backend, prepared, "qualified")
    source_manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=final,
        openttd_version="15.3",
        base_set_name="OpenGFX",
        base_set_version="8.0",
        width_tiles=64,
        height_tiles=64,
        seed=42,
        resolved_sites=(),
        cargo_types=(),
        vehicle_types=(),
        buildable_tiles=(),
    )
    source = native_correspondence(backend, prepared, world, source_manifest, before, final)
    policy = MonthlyBatchPolicy(
        start_date=date(1950, 1, 1),
        budget_gbp=Decimal(
            json.loads((prepared.directory / "PRELAUNCH.json").read_bytes()).get(
                "planning_budget_gbp", "100000"
            )
        ),
        delivery_batch_limit=batch_limit,
    )
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_bytes())
    network = network_from_facts(
        world, facts, source, policy, max_vehicles=metadata.get("network_service_limit", 2)
    )
    optimized = optimize_candidate_network(network.scenario)
    services = compile_freight_network(network, optimized.plan)
    write_json(prepared.directory / "world-planning-observation.json", json.loads(world.to_bytes()))
    write_json(
        prepared.directory / "prepared-source-links.json", source.links.model_dump(mode="json")
    )
    write_json(prepared.directory / "planning-policy.json", policy.model_dump(mode="json"))
    write_json(
        prepared.directory / "planning-scenario.json", network.scenario.model_dump(mode="json")
    )
    write_json(prepared.directory / "execution-plan.json", optimized.plan.model_dump(mode="json"))
    return network, optimized.plan, services, final


def network_route_readback(log_path, native, service):
    selection = service.selection_request(require_native=False)
    path = selection.path
    expected = {(a, b) for a, b in zip(path, path[1:])}
    expected |= {
        (native.a[4], native.a[5]),
        (native.a[6], native.a[7]),
        (native.a[8], selection.depot_front),
    }
    expected = {tuple(sorted(e)) for e in expected}
    edges = {}
    fronts = []
    for line in log_path.read_text().splitlines():
        match = re.search(r"FREIGHT_ROUTE_(EDGE|FRONTS) (.+)$", line)
        if not match:
            continue
        data = dict(item.split("=", 1) for item in match[2].split())
        if data.pop("plan", None) != native.digest:
            continue
        if match[1] == "FRONTS":
            fronts.append({k: int(v) for k, v in data.items()})
        else:
            row = {k: int(v) for k, v in data.items()}
            edges[tuple(sorted((row["a"], row["b"])))] = row
    if (
        set(edges) != expected
        or len(fronts) != 1
        or fronts[0]
        != dict(origin=native.a[5], destination=native.a[7], depot=selection.depot_front)
    ):
        raise ValueError("network independently logged route topology differs from P05")
    if any(
        any(
            row[k] != v
            for k, v in dict(
                roadtype=0, owner_a=0, owner_b=0, type_a=1, type_b=1, forward=1, reverse=1
            ).items()
        )
        for row in edges.values()
    ):
        raise ValueError("network route ownership/type/bidirectional readback failed")
    return dict(
        route_edge_readbacks=[edges[k] for k in sorted(edges)], route_front_readback=fronts[0]
    )


def service_construction(plan, records, reused_stages=(), *, log_path=None, network_plans=()):
    from app.simulation.openttd.proof.freight_delivery import (
        command_readback_evidence,
        construction_evidence,
    )

    commands = (
        command_readback_evidence(log_path, plan, records, network_plans=network_plans)
        if log_path is not None
        else {}
    )
    return {
        **construction_evidence(
            plan,
            records,
            planner=True,
            reused_stages=reused_stages,
            command_stage_readbacks=commands.get("construction_stage_readbacks", ()),
        ),
        **commands,
    }


def stage_assets(plan, route_id):
    from app.planning.domain import ConstructionKind

    route = next(r for r in plan.routes if r.route_id == route_id)
    actions = {a.construction_id: a for a in plan.infrastructure.actions}
    by_kind = {}
    for identity in route.infrastructure_ids:
        action = actions[identity]
        if action.kind is ConstructionKind.STATION:
            by_kind[3 if action.candidate_id == "build-" + route.stops[0].location_id else 4] = (
                identity
            )
        elif action.kind is ConstructionKind.DEPOT:
            by_kind[2] = identity
            by_kind[5] = identity
        elif action.kind is ConstructionKind.SEGMENT:
            by_kind[0] = identity
            by_kind[1] = identity
    if set(by_kind) != {0, 1, 2, 3, 4, 5}:
        raise ValueError("network construction stage mapping incomplete")
    return by_kind


def shared_stages(plan, services, n):
    previous = {
        asset for route_id, _ in services[:n] for asset in stage_assets(plan, route_id).values()
    }
    return tuple(
        stage for stage, asset in stage_assets(plan, services[n][0]).items() if asset in previous
    )


def asset_costs(plan, services, receipts):
    costs = {}
    seen = set()
    for n, ((route_id, _), receipt) in enumerate(zip(services, receipts, strict=True)):
        mapped = stage_assets(plan, route_id)
        for stage, identity in mapped.items():
            amount = receipt["mutation_costs"][stage]
            if identity in seen and amount != 0:
                raise ValueError("shared infrastructure charged more than once")
            costs[identity] = costs.get(identity, 0) + amount
        seen.update(mapped.values())
    return costs


def aggregate_receipt(plan, services, receipts):
    if (
        not 1 <= len(services) <= 3
        or len(receipts) != len(services)
        or tuple(r["route_id"] for r in receipts) != tuple(i for i, _ in services)
    ):
        raise ValueError("exact selected network service receipts required")
    if len({r["vehicle"] for r in receipts}) != len(services):
        raise ValueError("independent network vehicles required")
    unique_costs = asset_costs(plan, services, receipts)
    capex = sum(r["construction_purchase_spending"] for r in receipts)
    if sum(unique_costs.values()) != sum(sum(r["mutation_costs"][:6]) for r in receipts):
        raise ValueError("network unique infrastructure ledger mismatch")
    return dict(
        schema="native-freight-network-receipt-v1",
        execution_plan_digest=plan_hash(plan),
        services=receipts,
        delivered=sum(r["delivered"] for r in receipts),
        payment_income=sum(r["payment_income"] for r in receipts),
        actual_capex=capex,
        infrastructure_capex=sum(sum(r["mutation_costs"][:6]) for r in receipts),
        vehicle_purchase=sum(r["mutation_costs"][6] for r in receipts),
        unique_construction_ids=[a.construction_id for a in plan.infrastructure.actions],
        shared_construction_ids=[
            a.construction_id for a in plan.infrastructure.actions if len(a.route_ids) > 1
        ],
        shared_infrastructure_capex=sum(
            asset_costs(plan, services, receipts)[a.construction_id]
            for a in plan.infrastructure.actions
            if len(a.route_ids) > 1
        ),
        operating_costs=None,
        net_profit=None,
        sequencing="SERIAL_SAME_SESSION_STOP_AFTER_DELIVERY",
    )


def financial_reconciliation(directory, records, aggregate):
    """Separate command CAPEX/payment proof from unclassified company cash movement."""
    count = len(aggregate["services"])
    first, last = records["select-0"], records[f"s{count - 1}-park-read"]
    if last.s[0] < first.s[0] or last.s[1] < first.s[1]:
        raise ValueError("network finance endpoint chronology mismatch")
    residual = first.s[3] - last.s[3] - aggregate["actual_capex"] + aggregate["payment_income"]
    result = dict(
        schema="native-network-financial-reconciliation-v1",
        initial_readback_digest=first.digest,
        final_readback_digest=last.digest,
        initial_tick=first.s[0],
        final_tick=last.s[0],
        initial_economy_date=first.s[1],
        final_economy_date=last.s[1],
        initial_cash=first.s[3],
        final_cash=last.s[3],
        command_construction_purchase_costs=aggregate["actual_capex"],
        freight_revenue=aggregate["payment_income"],
        unallocated_company_cash_decrease=residual,
        expense_category="UNKNOWN",
        operating_costs=None,
        net_profit=None,
        construction_cash_changes=[
            dict(route_id=receipt["route_id"], **change)
            for receipt in aggregate["services"]
            for change in receipt.get("unallocated_company_cash_changes", ())
        ],
    )
    capital_path = directory / "capital-read-response.json"
    if capital_path.exists():
        capital = json.loads(capital_path.read_bytes())
        if capital["status"] != "READ" or not capital["completed"]:
            raise ValueError("network finance funding readback incomplete")
        result.update(
            funding_readback_sha256=sha256(capital_path),
            funded_cash=capital["balance_after"],
            funding_to_admission_unallocated_cash_decrease=capital["balance_after"] - first.s[3],
            funded_to_final_unallocated_cash_decrease=capital["balance_after"]
            - first.s[3]
            + residual,
        )
    return result


def verify_financial_reconciliation(directory, records, aggregate):
    result = financial_reconciliation(directory, records, aggregate)
    if result != json.loads((directory / "financial-reconciliation.json").read_bytes()):
        raise ValueError("network financial reconciliation replay mismatch")
    return result


def validate_financial_reconciliation_version(metadata):
    version = metadata.get("financial_reconciliation_version")
    if version is not None and (type(version) is not int or version != 1):
        raise ValueError("unsupported financial reconciliation version")
    return version


def validate_game_time_version(metadata):
    """Reject unsupported sealed receipt extensions; missing historical version is valid."""
    version = metadata.get("game_time_metrics_version")
    if version is not None and (type(version) is not int or version != 1):
        raise ValueError("unsupported game-time metrics version")
    return version


def receipt_game_time(directory, index, *, capture_start=False, log_path=None):
    """Replay correlated milestone readbacks; exact unsampled events remain unknown."""
    fields = (
        "simulation_start_date",
        "planning_completion_date",
        "construction_completion_date",
        "first_cargo_pickup_date",
        "final_cargo_delivery_date",
        "pickup_observed_by_date",
        "construction_observed_by_date",
        "total_elapsed_economy_days",
        "elapsed_calendar_days",
        "elapsed_script_ticks",
        "elapsed_wall_clock_seconds",
    )
    metrics = dict.fromkeys((*fields, "start_basis", "planning_completion_observed_by_date"))
    refs = []
    for stage, field, position in (
        ("read-9", "construction_observed_by_date", 1),
        ("observe-1", "pickup_observed_by_date", 1),
        ("finish", "final_cargo_delivery_date", 21),
    ):
        name = f"s{index}-{stage}-response.json"
        state = json.loads((directory / name).read_bytes())["s"]
        metrics[field] = state[position] if state[position] >= 0 else None
        refs.append(name)
    if capture_start:
        text = (log_path or directory / "stderr.log").read_text()
        starts = re.findall(r"FREIGHT_GAME_TIME_START date=(\d+) tick=(\d+)", text)
        plan_digest = DeliveryPlan.model_validate_json(
            (directory / f"native-plan-{index}.json").read_bytes()
        ).digest
        constructions = re.findall(
            r"FREIGHT_GAME_TIME_CONSTRUCTION plan="
            + re.escape(plan_digest)
            + r" date=(\d+) tick=(\d+)",
            text,
        )
        if len(starts) != 1 or len(constructions) != 1:
            raise ValueError("unique native game-time start/construction markers required")
        start_date, start_tick = map(int, starts[0])
        construction_date, construction_tick = map(int, constructions[0])
        final = json.loads((directory / f"s{index}-finish-response.json").read_bytes())["s"]
        if (
            not start_date <= construction_date <= final[21] <= final[1]
            or not start_tick <= construction_tick <= final[0]
        ):
            raise ValueError("native game-time marker chronology mismatch")
        metrics["start_basis"] = "bridge_start_before_world_preparation"
        metrics["planning_completion_observed_by_date"] = json.loads(
            (directory / f"select-{index}-response.json").read_bytes()
        )["s"][1]
        metrics["simulation_start_date"] = start_date
        metrics["construction_completion_date"] = construction_date
        metrics["total_elapsed_economy_days"] = final[21] - start_date
        refs.append("stderr.log")
    return dict(date_basis="economy", **metrics, evidence_refs=refs)


def aggregate_game_time(receipts):
    metrics = dict(receipts[0]["game_time"])
    for field in (
        "construction_completion_date",
        "construction_observed_by_date",
        "final_cargo_delivery_date",
    ):
        values = [r["game_time"][field] for r in receipts]
        metrics[field] = max(values) if all(v is not None for v in values) else None
    values = [r["game_time"]["pickup_observed_by_date"] for r in receipts]
    metrics["pickup_observed_by_date"] = min(values) if all(v is not None for v in values) else None
    if (
        metrics["simulation_start_date"] is not None
        and metrics["final_cargo_delivery_date"] is not None
    ):
        if any(
            r["game_time"]["simulation_start_date"] != metrics["simulation_start_date"]
            for r in receipts
        ):
            raise ValueError("network simulation start marker mismatch")
        metrics["total_elapsed_economy_days"] = (
            metrics["final_cargo_delivery_date"] - metrics["simulation_start_date"]
        )
    metrics["evidence_refs"] = [ref for r in receipts for ref in r["game_time"]["evidence_refs"]]
    return metrics


def require_selected_service_count(metadata, services):
    if metadata.get("network_service_limit", 2) == 3 and len(services) != 3:
        raise ValueError(
            f"THREE_SERVICE_ADMISSION_REQUIRES_EXACTLY_3_SELECTED: got {len(services)}"
        )


async def execute_network(backend, prepared, session, accounting, before, seal, metadata, result):
    validate_game_time_version(metadata)
    from app.simulation.openttd.proof.freight_delivery import exchange
    from app.simulation.openttd.proof.road_mutation import save

    network, execution, services, source_save = await plan_network_world(
        backend, prepared, session, accounting, before, metadata["delivery_batch_limit"]
    )
    result["supplemental_requests"] = backend.planning_read_count
    result["selected_services"] = [i for i, _ in services]
    require_selected_service_count(metadata, services)
    result["qualification_requests"] = sum(
        v[0] for _, v in services[0][1].road.input.admitted.world.qualification.evidence.phase_usage
    )
    admissions, plans, bindings = [], [], []
    for n, (route_id, service) in enumerate(services):
        request = service.selection_request(request_id=f"select-{n}")
        read = await exchange(session, request, prepared.directory)
        result["requests"] += 1
        native = admit(
            read,
            seal,
            source_save,
            None,
            executor_source=metadata["predecessor"]["executor_source_digest"],
            selection_digest=plan_hash(execution),
        )
        binding = service.validate_native_selection(native, read)
        bindings.append(binding)
        admissions.append(read)
        plans.append(native)
        write_json(prepared.directory / f"native-plan-{n}.json", native.model_dump(mode="json"))
    if sum(r.s[23] for r in admissions) > min(r.s[3] for r in admissions):
        raise ValueError("aggregate native quoted CAPEX exceeds actual available funds")
    write_json(prepared.directory / "network-bindings.json", bindings)
    receipts = []
    for n, ((route_id, service), native) in enumerate(zip(services, plans, strict=True)):

        async def query(op, name, arg=0):
            if result["requests"] >= metadata["budgets"]["requests"]:
                raise ValueError("network request budget exhausted")
            if op == "build" or (op == "finish" and arg == 1):
                result["mutations"] += 1
            result["requests"] += 1
            return await exchange(
                session,
                DeliveryRequest(op=op, request_id=name, plan=native.digest, arg=arg),
                prepared.directory,
            )

        activated = await query("read", f"activate-{n}", n)
        verify_snapshot(native, activated)
        if activated.s[22] != 0 or activated.s[4] != -1 or activated.status != "READ":
            raise ValueError("native service activation mismatch")
        records = {"inspect-1": activated}
        for i in range(10):
            built = await query("build", f"s{n}-build-{i}", i)
            # Always retain independent state even after a failed mutation. No retry.
            read = await query("read", f"s{n}-read-{i}", i)
            records[f"build-{i}"] = built
            records[f"read-{i}"] = read
            verify_snapshot(native, read)
            if built.status != "BUILT" or read.status != "READ" or read.s[22] != i + 1:
                raise ValueError(
                    f"service {route_id} mutation {i}: {built.status}; stage={read.s[22]}"
                )
        observations = []
        for i in range(4):
            observed = await query("observe", f"s{n}-observe-{i}", i)
            verify_observation(native, observed, i)
            observations.append(observed)
        final = await query("finish", f"s{n}-finish")
        receipt = verify_delivery(native, records["read-8"], observations, final)
        receipt.update(
            service_construction(
                native,
                records,
                reused_stages=shared_stages(execution, services, n),
                log_path=prepared.spec.workspace.logs / "stderr.log",
                network_plans=tuple(p.digest for p in plans),
            )
        )
        receipt.update(
            network_route_readback(prepared.spec.workspace.logs / "stderr.log", native, service)
        )
        receipt.update(route_id=route_id, planning_binding=bindings[n])
        parked = await query("finish", f"s{n}-park", 1)
        independent = await query("read", f"s{n}-park-read")
        verify_snapshot(native, independent)
        if (
            parked.status != "PARKED"
            or independent.s[9] != 1
            or independent.s[11] != 0
            or independent.s[4] != receipt["vehicle"]
        ):
            raise ValueError(f"service {route_id} did not stop empty after delivery")
        receipt["parked_digests"] = [parked.digest, independent.digest]
        if metadata.get("game_time_metrics_version") == 1:
            receipt["game_time"] = receipt_game_time(
                prepared.directory,
                n,
                capture_start=True,
                log_path=prepared.spec.workspace.logs / "stderr.log",
            )
        receipts.append(receipt)
        write_json(prepared.directory / f"service-receipt-{n}.json", receipt)
    aggregate = aggregate_receipt(execution, services, receipts)
    if metadata.get("game_time_metrics_version") == 1:
        aggregate["game_time"] = aggregate_game_time(receipts)
    aggregate.update(
        before_save_sha256=before,
        qualified_save_sha256=source_save,
        after_save_sha256=await save(backend, prepared, "after"),
    )
    finance_records = {
        name: DeliveryReadback.model_validate_json(
            (prepared.directory / f"{name}-response.json").read_bytes()
        )
        for name in ("select-0", f"s{len(services) - 1}-park-read")
    }
    write_json(
        prepared.directory / "financial-reconciliation.json",
        financial_reconciliation(prepared.directory, finance_records, aggregate),
    )
    write_json(prepared.directory / "receipt.json", aggregate)


def verify_network_receipt(directory: Path, *, return_network=False):
    """Independent retained readback replay; never creates a process or connection."""
    from app.simulation.openttd.freight_planning_replay import replay_qualified_world
    from app.simulation.openttd.freight_runtime_planning import _ISSUER, NativeSaveCorrespondence
    from app.simulation.openttd.prepared_source_correspondence import (
        ControlledSourceLinks,
        PreparedSourceCorrespondence,
    )
    from app.simulation.openttd.proof.endpoints import verify_retained_endpoints
    from app.simulation.openttd.proof.freight_delivery import (
        network_budgets,
    )

    directory = directory.resolve()
    if manifest(directory) != (directory / "artifact-manifest.sha256").read_text():
        raise ValueError("network artifact manifest mismatch")
    metadata = json.loads((directory / "PRELAUNCH.json").read_bytes())
    validate_game_time_version(metadata)
    validate_financial_reconciliation_version(metadata)
    seal = sha256(directory / "PRELAUNCH.json")
    if (
        not metadata.get("network")
        or metadata["budgets"] != network_budgets(metadata.get("network_service_limit", 2))
        or seal != (directory / "PRELAUNCH.sha256").read_text().strip()
    ):
        raise ValueError("network seal or budgets mismatch")
    if json.loads((directory / "CLAIM.json").read_bytes()) != dict(
        consumed=True, prelaunch_digest=seal, launches_allowed=1, retries=0
    ):
        raise ValueError("network one-launch claim mismatch")
    runtime = json.loads((directory / "runtime-identity.json").read_bytes())
    world = asyncio.run(replay_qualified_world(directory, metadata, runtime))
    if json.loads(world.to_bytes()) != json.loads(
        (directory / "world-planning-observation.json").read_bytes()
    ):
        raise ValueError("network qualified observation mismatch")
    relationships, rejected = bounded_relationships(world)
    if json.loads((directory / "network-candidates.json").read_bytes()) != dict(
        relationships=[list(r) for r in relationships], rejected=rejected
    ):
        raise ValueError("network candidate identity mismatch")

    async def retained_read(session, request, root, *, response_type):
        if (root / (request.request_id + "-request.json")).read_bytes() != request.to_bytes():
            raise ValueError("network retained planning request mismatch")
        return response_type.parse_for(
            request, (root / (request.request_id + "-response.json")).read_bytes()
        )

    facts = []
    for n, relationship in enumerate(relationships):
        f = asyncio.run(
            capture_planning_facts(
                SimpleNamespace(health=lambda: None, session=None),
                SimpleNamespace(directory=directory),
                world,
                relationship=relationship,
                prefix=f"n{n}-",
                read_exchange=retained_read,
                retain=False,
            )
        )
        if f.model_dump(mode="json") != json.loads(
            (directory / f"network-facts-{n}.json").read_bytes()
        ):
            raise ValueError("network facts differ from actual readbacks")
        facts.append(f)
    links = ControlledSourceLinks.model_validate_json(
        (directory / "prepared-source-links.json").read_bytes()
    )
    if (
        links.original_save_digest != sha256(directory / "before.sav")
        or links.post_qualification_save_digest != sha256(directory / "qualified.sav")
        or links.evidence_kind != "owned-native-save-snapshots"
    ):
        raise ValueError("network native source/save mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_bytes())
    authority_record = dict(
        schema="owned-freight-save-correspondence-v1",
        pid=cleanup["pid"],
        prelaunch_digest=seal,
        runtime_digest=world.context.world.runtime_identity.sha256,
        configuration_digest=world.context.configuration_digest,
        bridge_digest=world.context.bridge.sha256,
        world_observation_digest=world.composition_digest,
        before_save_digest=links.original_save_digest,
        qualified_save_digest=links.post_qualification_save_digest,
        qualification_frames_digest=sha256(directory / "qualification-prefix-frames.json"),
        admin_port=metadata["admin_port"],
        encrypted=True,
    )
    if authority_record != json.loads((directory / "native-save-correspondence.json").read_bytes()):
        raise ValueError("network native authority mismatch")
    source_manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=links.post_qualification_save_digest,
        openttd_version="15.3",
        base_set_name="OpenGFX",
        base_set_version="8.0",
        width_tiles=64,
        height_tiles=64,
        seed=42,
        resolved_sites=(),
        cargo_types=(),
        vehicle_types=(),
        buildable_tiles=(),
    )
    source = PreparedSourceCorrespondence(
        world,
        source_manifest,
        links,
        NativeSaveCorrespondence(
            _ISSUER,
            world=world,
            original_digest=links.original_save_digest,
            final_digest=links.post_qualification_save_digest,
            configuration_digest=links.configuration_digest,
        ),
    )
    policy = MonthlyBatchPolicy.model_validate_json(
        (directory / "planning-policy.json").read_bytes()
    )
    if policy.delivery_batch_limit != metadata[
        "delivery_batch_limit"
    ] or policy.budget_gbp != Decimal(metadata.get("planning_budget_gbp", "100000")):
        raise ValueError("network batch differs from prelaunch")
    network = network_from_facts(
        world, facts, source, policy, max_vehicles=metadata.get("network_service_limit", 2)
    )
    plan = ExecutionPlan.model_validate_json((directory / "execution-plan.json").read_bytes())
    scenario = PlanningScenario.model_validate_json(
        (directory / "planning-scenario.json").read_bytes()
    )
    if scenario_hash(scenario) != scenario_hash(network.scenario) or plan_hash(plan) != plan_hash(
        optimize_candidate_network(network.scenario).plan
    ):
        raise ValueError("network P08/P05 decision replay mismatch")
    services = compile_freight_network(network, plan)
    require_selected_service_count(metadata, services)
    records, wire_ids = verified_exchanges(directory)
    expected = [f"select-{n}" for n in range(len(services))]
    receipts = []
    bindings = []
    for n, (route_id, service) in enumerate(services):
        selection = service.selection_request(request_id=f"select-{n}")
        if selection.to_bytes() != (directory / f"select-{n}-request.json").read_bytes():
            raise ValueError("network selected identity changed")
        native = admit(
            records[f"select-{n}"],
            seal,
            links.post_qualification_save_digest,
            None,
            executor_source=metadata["predecessor"]["executor_source_digest"],
            selection_digest=plan_hash(plan),
        )
        if native != DeliveryPlan.model_validate_json(
            (directory / f"native-plan-{n}.json").read_bytes()
        ):
            raise ValueError("network native plan mismatch")
        binding = service.validate_native_selection(native, records[f"select-{n}"])
        bindings.append(binding)
        expected += (
            [f"activate-{n}"]
            + [x for i in range(10) for x in (f"s{n}-build-{i}", f"s{n}-read-{i}")]
            + [f"s{n}-observe-{i}" for i in range(4)]
            + [f"s{n}-finish", f"s{n}-park", f"s{n}-park-read"]
        )
        service_records = {"inspect-1": records[f"activate-{n}"]}
        for i in range(10):
            for op in ("build", "read"):
                service_records[f"{op}-{i}"] = records[f"s{n}-{op}-{i}"]
        receipt = verify_delivery(
            native,
            service_records["read-8"],
            [records[f"s{n}-observe-{i}"] for i in range(4)],
            records[f"s{n}-finish"],
        )
        all_plans = tuple(
            DeliveryPlan.model_validate_json(
                (directory / f"native-plan-{j}.json").read_bytes()
            ).digest
            for j in range(len(services))
        )
        receipt.update(
            service_construction(
                native,
                service_records,
                reused_stages=shared_stages(plan, services, n),
                log_path=directory / "stderr.log",
                network_plans=all_plans,
            )
        )
        receipt.update(network_route_readback(directory / "stderr.log", native, service))
        receipt.update(route_id=route_id, planning_binding=binding)
        parked, independent = records[f"s{n}-park"], records[f"s{n}-park-read"]
        verify_snapshot(native, independent)
        if (
            parked.status != "PARKED"
            or independent.status != "READ"
            or independent.s[9] != 1
            or independent.s[11] != 0
            or independent.s[4] != receipt["vehicle"]
        ):
            raise ValueError("network independent stopped-vehicle readback mismatch")
        receipt["parked_digests"] = [parked.digest, independent.digest]
        if metadata.get("game_time_metrics_version") == 1:
            receipt["game_time"] = receipt_game_time(directory, n, capture_start=True)
        if receipt != json.loads((directory / f"service-receipt-{n}.json").read_bytes()):
            raise ValueError("network service receipt mismatch")
        receipts.append(receipt)
    if (
        wire_ids != expected
        or set(records) != set(expected)
        or bindings != json.loads((directory / "network-bindings.json").read_bytes())
    ):
        raise ValueError("network bounded deterministic sequence mismatch")
    aggregate = aggregate_receipt(plan, services, receipts)
    if metadata.get("game_time_metrics_version") == 1:
        aggregate["game_time"] = aggregate_game_time(receipts)
    aggregate.update(
        before_save_sha256=sha256(directory / "before.sav"),
        qualified_save_sha256=sha256(directory / "qualified.sav"),
        after_save_sha256=sha256(directory / "after.sav"),
    )
    if aggregate != json.loads((directory / "receipt.json").read_bytes()):
        raise ValueError("network aggregate receipt mismatch")
    if (
        metadata.get("financial_reconciliation_version") == 1
        or (directory / "financial-reconciliation.json").exists()
    ):
        verify_financial_reconciliation(directory, records, aggregate)
    result = json.loads((directory / "result.json").read_bytes())
    if metadata.get("scenario") and (
        result.get("funding_requests"),
        result.get("funding_mutations"),
    ) != (2, 1):
        raise ValueError("network funding accounting mismatch")
    if (
        (
            result["launches"],
            result["connections"],
            result["requests"],
            result["mutations"],
            result["status"],
        )
        != (1, 1, 29 * len(services), 11 * len(services), "NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED")
        or not cleanup.get("reaped")
        or not cleanup.get("workspace_disposed")
        or not cleanup.get("credential_removed")
        or cleanup.get("cleanup_error")
        or cleanup.get("verification_error")
    ):
        raise ValueError("network execution or cleanup incomplete")
    verify_retained_endpoints(
        cleanup["endpoint_verification"],
        metadata | {"endpoints": [metadata["game_port"], metadata["admin_port"]]},
    )
    logs = (directory / "stdout.log").read_text() + (directory / "stderr.log").read_text()
    for name in ("before", "qualified", "after"):
        if logs.count("Map successfully saved to '" + str(directory / (name + ".sav"))) != 1:
            raise ValueError("network unique native save completion missing")
    return (aggregate, network) if return_network else aggregate


def verified_exchanges(directory):
    from app.simulation.openttd.admin_protocol import AdminFrameDecoder
    from app.simulation.openttd.gamescript_transport import (
        ADMIN_GAMESCRIPT,
        SERVER_GAMESCRIPT,
        decode_gamescript,
        encode_gamescript,
    )

    frames = json.loads((directory / "frames.json").read_bytes())
    sent = [bytes.fromhex(f) for d, f in frames if d == "outbound"]
    replies = []
    decoder = AdminFrameDecoder()
    for d, f in frames:
        if d == "inbound":
            replies += [
                decode_gamescript(b)
                for k, b in decoder.feed_frames(bytes.fromhex(f))
                if k == SERVER_GAMESCRIPT
            ]
    records = {}
    wire_ids = []
    for frame in sent:
        if frame[2] == ADMIN_GAMESCRIPT:
            value = json.loads(decode_gamescript(frame[3:]))
            if "type" not in value:
                wire_ids.append(value["request_id"])
    for path in directory.glob("*-request.json"):
        raw = path.with_name(path.name.replace("-request", "-response")).read_bytes()
        if sent.count(encode_gamescript(path.read_bytes())) != 1 or replies.count(raw) != 1:
            raise ValueError("network unique continuous secure exchange missing")
        value = json.loads(path.read_bytes())
        if "type" in value:
            continue
        q = (
            PlanningSelectionRequest.model_validate_json(path.read_bytes()).admission_request
            if value["op"] == "select"
            else DeliveryRequest.model_validate_json(path.read_bytes())
        )
        records[q.request_id] = DeliveryReadback.parse_for(q, raw)
    return records, wire_ids
