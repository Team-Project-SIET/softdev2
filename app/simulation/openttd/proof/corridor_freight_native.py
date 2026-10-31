"""D5 native corridor freight-cycle proof preparation.

Stages the reviewed corridor freight cycle as one fresh save-load candidate
that reuses the proven D2/D3/D4 native machinery exactly: the same operator
authorization, runtime freeze, dependency identity, immutable launch
environment, one-shot claim, signed replay and cleanup boundaries. No second
security framework is introduced; the shared machinery is parameterized at
call time (closure root, prerequisite lineage, sealed freight pins) so the
D4 ceremony is untouched.

The staged candidate ``D5-FREIGHT-1`` binds the candidate-5 corridor lineage
byte-exactly:

1. Its source world is the replay-verified retained ``after.sav`` of the
   consuming D4 corridor candidate (``D4-CORRIDOR-5``) — the route-receipt
   bound truck stops, depot and company road at the verified close-out
   geometry, with the pinned authoritative after-save digest.
2. Its schedule is the fixed fifteen-exchange freight cycle in exactly the
   order the wire contract pins (site, engine, purchase, vread, two order
   appends, order inventory, monitor arming, start, second vread, load
   window, transit window, delivery window, finance corroboration, finish).
3. Wire contract v5: every exchange presents one uniform prelaunch plan
   digest; per-op admission intents (site, engine) and per-op receipts are
   latched between exchanges and verified by the production freight
   verifiers — one attempt, one company, one vehicle.

Native buildability is never inferred here: site facts, engine enumeration,
the tested quote, the funds reconciliation, monitor arithmetic and the
finance corroboration happen natively at admission/exchange time through
``app.simulation.openttd.corridor_freight``.

Nothing in this module launches OpenTTD, connects to any port, or mutates
any tile; the staged pre-launch claim is never written, so nothing can
launch until a separate operator authorization creates it.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import struct
import time
import zipfile
from dataclasses import asdict
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
from app.simulation.openttd.corridor_freight import (
    DELIVERY_FRONT_TILE,
    DELIVERY_STOP_TILE,
    DEPOT_FRONT_TILE,
    DEPOT_TILE,
    FREIGHT_CARGO_ID,
    FREIGHT_COMPANY,
    FREIGHT_DELIVERY_INDUSTRY,
    FREIGHT_EXCHANGE_IDS,
    FREIGHT_MAX_COST,
    FREIGHT_OPS,
    FREIGHT_PICKUP_INDUSTRY,
    FREIGHT_REQUEST_BUDGET,
    FUNDS_AT_D4_CLOSE,
    LOAD_WATCH_MAX_DAYS,
    MAX_FREIGHT_REQUEST_BYTES,
    MAX_FREIGHT_RESPONSE_BYTES,
    MAX_FREIGHT_SEND_BYTES,
    PICKUP_FRONT_TILE,
    PICKUP_STOP_TILE,
    PLANNED_FREIGHT_EXCHANGES,
    WATCH_MAX_TICKS,
    FreightPlan,
    FreightReadback,
    FreightRequest,
    admit_freight_engine,
    admit_freight_site,
    freight_phase_outcome,
    freight_route_digest,
    verify_freight_cycle,
)
from app.simulation.openttd.corridor_route_optimizer import (
    MAX_OPTIMIZED_ROUTE_TILES,
    OptimizedRoute,
    route_from_d5_map,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.proof.classification_capture import script_log_health_findings
from app.simulation.openttd.proof.corridor_construction_native import (
    D4_PRELAUNCH_SCHEMA,
    MILESTONE_CONSTRUCTION,
    corridor_facts,
    coverage_pins,
    source_save_path,
    stage_world,
    verify_corridor_attempt,
)
from app.simulation.openttd.proof.endpoints import kernel_socket_rows, verify_cleanup_endpoints
from app.simulation.openttd.proof.graphics import stage_opengfx
from app.simulation.openttd.proof.harness import (
    BINARY,
    BINARY_SHA256,
    PROJECT,
    EndpointReservation,
    PreparedProof,
    manifest,
    sha256,
    source_freeze,
    verify_freeze,
    write_json,
)
from app.simulation.openttd.proof.native import matching_processes
from app.simulation.openttd.proof.operator_authorization import (
    CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
    authorization_payload,
    canonical_authorization_bytes,
    grant_launch,
)
from app.simulation.openttd.proof.road_mutation import console, save, wait_log
from app.simulation.openttd.proof.terrain_classification_preparation import SEED17_RUN
from app.simulation.openttd.proof.terrain_clearing import (
    STAGED_AI_DIRECTORY,
    ClearingNativeBackend,
    ClearingStagingError,
    d2_dependency_inventory,
    d2_source_closure,
    launch_critical_identity,
    launch_environment,
    replay_authorization_state,
    require_frozen_d2_closure,
    require_frozen_d2_dependencies,
    retained_welcome,
)
from app.simulation.openttd.proof.terrain_clearing import (
    reopen as reopen_candidate,
)
from app.simulation.openttd.proof.terrain_terraform_native import (
    ROAD_PROOF_COMPANY_READY_MARKER,
    WELCOME_ORDER,
    plan_digest_of,
    read_prelaunch,
)
from app.simulation.openttd.proof.world_correspondence import (
    SOURCE_SAVE_GS_NAME,
    verify_staged_source_save,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState, SecureAdminSession

PACKAGES = Path(__file__).resolve().parents[1]
FREIGHT_PACKAGE = PACKAGES / "d5_freight_package"
AI_PACKAGE = PACKAGES / "road_company_package"
D5_CLOSURE_ROOT = "app.simulation.openttd.proof.corridor_freight_native"

KIND = "freight"
MILESTONE_FREIGHT = "D5-FREIGHT"
FREIGHT_ATTEMPT = "D5-FREIGHT-1"

# Versioned prelaunch evidence for the D5 native candidate (additive sister
# record of the shared prelaunch machinery; the claim, launch boundary, freeze
# and replay gates are the shared D2 implementations parameterized at call
# time). The D5 prerequisite schema names one corridor lineage attempt; the
# consumed-launch marker uses the shared native consumed schema family.
D5_FREIGHT_PRELAUNCH_SCHEMA = "d5-freight-prelaunch-v1"
D5_FREIGHT_PREREQUISITE_SCHEMA = "d5-native-prerequisite-attempt-v1"
D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA = "d5-native-launch-consumed"

# The freight candidate's prerequisite lineage: the D4 corridor attempt whose
# replay-verified retained after.sav is the staged source world. The pinned
# authoritative digest is the receipt-bound close-out world of D4-CORRIDOR-5.
PINNED_PREREQUISITE = Path(
    PROJECT / "artifacts/experiments/d4-corridor-native-candidate-5"
).resolve()
PINNED_PREREQUISITE_AFTER_SAVE = "a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261"

# The staged running GameScript announces its own readiness marker (identical
# to the D2/D3/D4 staged machinery).
FREIGHT_READY_MARKER = "D5_READY"

# Schedule-derivation version of the staged freight plan. Version 1 is the
# fixed fifteen-exchange derivation the wire contract pins exactly.
SCHEDULE_VERSION = 1

# Exchange accounting: the fifteen planned exchanges and the package's own
# dispatcher request cap of 32 unique ids.
PLANNED_FREIGHT_REQUESTS = PLANNED_FREIGHT_EXCHANGES
FREIGHT_STAGED_REQUESTS_BUDGET = FREIGHT_REQUEST_BUDGET

# Protocol-5 timing contract. A non-window exchange is a bounded request /
# immediate readback and uses the staged ``request_seconds``. A watch-window
# exchange is permitted the design's full wall-clock window plus a small
# client margin, because the GameScript may legitimately spend the whole
# window before returning its bounded observation. Every exchange is further
# clamped to the remaining overall attempt budget, so fifteen fresh windows
# can never extend the attempt beyond its total wall clock.
FREIGHT_WATCH_WALL_SECONDS = 60
FREIGHT_EXCHANGE_MARGIN_SECONDS = 5
FREIGHT_WATCH_OPS = ("load-watch", "transit-watch", "deliver-watch")


class FreightStagingError(ClearingStagingError):
    """Offline D5 staging or pin derivation failed; nothing was launched."""


def staged_composition() -> tuple[dict[str, bytes], str, int]:
    """Byte-exact save-restore composition for the D5 freight candidate.

    The retained staged ``info.nut`` announces the save's stored GameScript
    identity (name/version); the staged main is the bounded freight handler
    with the save-restore bridge class defined inline after the proof class.
    No separate identity.nut is needed.
    """
    with zipfile.ZipFile(SEED17_RUN / "frozen-source.zip") as archive:
        info_bytes = archive.read("staged/info.nut")
    text = info_bytes.decode()
    create_instance = re.search(r'CreateInstance\(\)\s*\{\s*return\s+"([^"]+)"', text)
    version = re.search(r"GetVersion\(\)\s*\{\s*return\s+(\d+)", text)
    if create_instance is None or version is None or SOURCE_SAVE_GS_NAME not in text:
        raise FreightStagingError("retained staged GameScript identity incomplete")
    main_text = (FREIGHT_PACKAGE / "main.nut").read_text()
    bridge_class = create_instance.group(1)
    if f"class {bridge_class} extends D5FreightProof" not in main_text:
        raise FreightStagingError(f"staged main.nut missing required bridge class {bridge_class}")
    return (
        {
            "info.nut": info_bytes,
            "main.nut": (FREIGHT_PACKAGE / "main.nut").read_bytes(),
        },
        bridge_class,
        int(version.group(1)),
    )


# --- The pinned corridor freight world (sealed, deterministic) ---------------


@lru_cache(maxsize=1)
def freight_facts() -> dict:
    """Derive the staged freight world's pins from the pinned compile.

    The corridor stops, depot and witness come from the D4 candidate's own
    sealed derivation (``corridor_facts``); the anchor coverage facts come
    from the same sealed census document. Every D5 wire pin is compared
    against the compiled evidence here, so a drift refuses staging before
    any run.
    """
    facts = corridor_facts()
    corridor = [int(tile) for tile in facts["corridor"]]
    depot = facts["depot"]
    stops = facts["stops"]
    fronts = facts["fronts"]
    if (int(stops[0]), int(fronts[0])) != (PICKUP_STOP_TILE, PICKUP_FRONT_TILE):
        raise FreightStagingError("pickup stop pins drifted from the compiled corridor")
    if (int(stops[1]), int(fronts[1])) != (DELIVERY_STOP_TILE, DELIVERY_FRONT_TILE):
        raise FreightStagingError("delivery stop pins drifted from the compiled corridor")
    if (
        int(depot["tile_id"]),
        int(depot["front_tile_id"]),
    ) != (DEPOT_TILE, DEPOT_FRONT_TILE):
        raise FreightStagingError("depot pins drifted from the compiled corridor")
    if len(corridor) != 24 or len(set(corridor)) != len(corridor):
        raise FreightStagingError("the staged witness is not the 24 unique corridor tiles")
    coverage = {int(pin["tile"]): pin for pin in coverage_pins()}
    pickup = coverage.get(PICKUP_STOP_TILE)
    delivery = coverage.get(DELIVERY_STOP_TILE)
    if pickup is None or pickup.get("cargo_id") != FREIGHT_CARGO_ID:
        raise FreightStagingError("pickup stop anchor coverage absent for cargo 1")
    if delivery is None or delivery.get("cargo_id") != FREIGHT_CARGO_ID:
        raise FreightStagingError("delivery stop anchor coverage absent for cargo 1")
    return dict(
        witness=corridor,
        depot=dict(depot),
        stops=[int(stops[0]), int(stops[1])],
        fronts=[int(fronts[0]), int(fronts[1])],
        coverage=[dict(pickup), dict(delivery)],
    )


def freight_plan() -> FreightPlan:
    """The optimizer-derived freight plan the staged candidate drives.

    The retained D4 corridor survey is the bounded map input. The production
    P05 ``optimize_candidate_network`` path selects the route; the selected
    witness, fronts and depot are then bound into the D5 wire plan. The
    retained geometry must round-trip exactly, so a refactor that silently
    replaces the optimizer with a baked path refuses staging.
    """
    route = optimized_freight_route()
    return route.freight_plan(
        company=FREIGHT_COMPANY,
        expected_funds=FUNDS_AT_D4_CLOSE,
        max_cost=FREIGHT_MAX_COST,
        schedule=FREIGHT_EXCHANGE_IDS,
    )


# Planning-only economics for the bounded map. They select among candidate
# routes by CAPEX; the native engine quote, capacity, funds and schedule stay
# the live admission facts, never inferred here.
PLANNING_VEHICLE_TYPE = "road-truck"
PLANNING_CAPACITY_CARGO_UNITS = 20
PLANNING_PURCHASE_COST_GBP = Decimal(20)
PLANNING_RUNNING_COST_GBP_PER_DAY = Decimal(0)
PLANNING_SPEED_KM_PER_HOUR = Decimal(80)
PLANNING_ROAD_PIECE_COST_GBP = Decimal(1)
PLANNING_TRUCK_STOP_COST_GBP = Decimal(1)
PLANNING_DEPOT_COST_GBP = Decimal(1)


@lru_cache(maxsize=1)
def optimized_freight_route() -> OptimizedRoute:
    """Run the production optimizer over the retained D4 corridor survey."""
    facts = freight_facts()
    route = route_from_d5_map(
        map_width=256,
        map_height=256,
        witness_candidates=(tuple(facts["witness"]),),
        pickup=facts["stops"][0],
        delivery=facts["stops"][1],
        depot=facts["depot"]["tile_id"],
        vehicle_type=PLANNING_VEHICLE_TYPE,
        capacity_cargo_units=PLANNING_CAPACITY_CARGO_UNITS,
        purchase_cost_gbp=PLANNING_PURCHASE_COST_GBP,
        running_cost_gbp_per_day=PLANNING_RUNNING_COST_GBP_PER_DAY,
        speed_km_per_hour=PLANNING_SPEED_KM_PER_HOUR,
        road_piece_cost_gbp=PLANNING_ROAD_PIECE_COST_GBP,
        truck_stop_cost_gbp=PLANNING_TRUCK_STOP_COST_GBP,
        depot_cost_gbp=PLANNING_DEPOT_COST_GBP,
        cargo_type="cargo-1",
        cargo_id=FREIGHT_CARGO_ID,
        pickup_industry=FREIGHT_PICKUP_INDUSTRY,
        delivery_industry=FREIGHT_DELIVERY_INDUSTRY,
        source_digest=hashlib.sha256(",".join(map(str, facts["witness"])).encode()).hexdigest(),
        available_funds_gbp=Decimal(FUNDS_AT_D4_CLOSE),
        max_purchase_cost_gbp=Decimal(FREIGHT_MAX_COST),
    )
    if route.route != tuple(facts["witness"]):
        raise FreightStagingError(
            "the optimizer-selected route drifted from the retained corridor survey"
        )
    if (route.depot, route.depot_front) != (
        facts["depot"]["tile_id"],
        facts["depot"]["front_tile_id"],
    ):
        raise FreightStagingError("the optimizer-selected depot drifted from the survey")
    if len(route.route) > MAX_OPTIMIZED_ROUTE_TILES:
        raise FreightStagingError("the optimizer-selected route exceeds the wire bound")
    return route


def freight_schedule() -> list[dict]:
    """The fixed fifteen-exchange freight cycle, staged as plan rows.

    Each row carries the exchange id, its op, and the phase-budget echoes
    the windows present (bounded by the wire contract's own caps); order
    rows carry their stop index. A drift from the wire contract's own
    schedule refuses staging.
    """
    schedule = [
        dict(exchange="site-00", op="site"),
        dict(exchange="engine-00", op="engine"),
        dict(exchange="purchase-00", op="purchase"),
        dict(exchange="vread-00", op="vread"),
        dict(exchange="order-00", op="order", order_index=0),
        dict(exchange="order-01", op="order", order_index=1),
        dict(exchange="order-read-00", op="order-read"),
        dict(exchange="monitor-00", op="monitor"),
        dict(exchange="start-00", op="start"),
        dict(exchange="vread-01", op="vread"),
        dict(
            exchange="load-00",
            op="load-watch",
            watch_ticks=WATCH_MAX_TICKS,
            watch_days=LOAD_WATCH_MAX_DAYS,
        ),
        dict(exchange="transit-00", op="transit-watch", watch_ticks=WATCH_MAX_TICKS),
        dict(exchange="deliver-00", op="deliver-watch", watch_ticks=WATCH_MAX_TICKS),
        dict(exchange="finance-00", op="finance"),
        dict(exchange="finish-00", op="finish"),
    ]
    if [entry["exchange"] for entry in schedule] != list(FREIGHT_EXCHANGE_IDS):
        raise FreightStagingError("the staged freight schedule drifted from the wire contract")
    return schedule


def _scheduled_exchange_ids(schedule: list[dict]) -> set[str]:
    """Every request id the staged schedule can legitimately produce."""
    ids = {entry["exchange"] for entry in schedule}
    if ids != set(FREIGHT_EXCHANGE_IDS):
        raise FreightStagingError("the staged freight schedule drifted from the wire contract")
    return ids


# --- Prerequisite-attempt source world (candidate-5) --------------------------


def prerequisite_binding(prerequisite: Path = PINNED_PREREQUISITE) -> dict:
    """The fail-closed binding of the D4 corridor attempt's after-save.

    The prerequisite must be the pinned, consumed, replay-verified D4
    corridor attempt: its receipt survives full replay verification, its
    retained ``after.sav`` binds the pinned authoritative digest, and its
    own staged world welcome is the expected D5 source identity. The
    candidate-5 lineage record is embedded as provenance; no historical
    D3 chain walk is re-opened here.
    """
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise FreightStagingError("the D5 prerequisite is not the pinned D4 attempt")
    if not prerequisite.is_dir() or any(part == ".." for part in prerequisite.parts):
        raise FreightStagingError("prerequisite attempt directory is not a real directory")
    metadata = read_prelaunch(prerequisite)
    if metadata.get("schema") != D4_PRELAUNCH_SCHEMA:
        raise FreightStagingError("prerequisite attempt is not the D4 corridor lineage")
    if metadata.get("kind") != "corridor" or metadata.get("milestone") != MILESTONE_CONSTRUCTION:
        raise FreightStagingError("prerequisite attempt is not the D4 corridor phase")
    seal = sha256(prerequisite / "PRELAUNCH.json")
    if (prerequisite / "PRELAUNCH.sha256").read_text().strip() != seal:
        raise FreightStagingError("prerequisite prelaunch seal mismatch")
    if metadata.get("attempt") != "D4-CORRIDOR-5":
        raise FreightStagingError("prerequisite attempt identity drifted")
    claim_path = prerequisite / "CLAIM.json"
    if not claim_path.is_file():
        raise FreightStagingError("the prerequisite attempt was never consumed")
    claim = json.loads(claim_path.read_text())
    if claim.get("prelaunch_digest") != seal or claim.get("consumed") is not True:
        raise FreightStagingError("the prerequisite attempt claim is incomplete")
    after_save = prerequisite / "after.sav"
    if not after_save.is_file():
        raise FreightStagingError("the prerequisite attempt retained no after world state")
    save_digest = sha256(after_save)
    if save_digest != PINNED_PREREQUISITE_AFTER_SAVE:
        raise FreightStagingError(
            "the prerequisite after-save digest is not the receipt-bound authoritative world"
        )
    receipt_path = prerequisite / "receipt.json"
    if not receipt_path.is_file():
        raise FreightStagingError("the prerequisite attempt retained no receipt")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("after_save_sha256") != save_digest:
        raise FreightStagingError("the prerequisite receipt does not bind its after save")
    verdict = verify_corridor_attempt(prerequisite)
    if verdict.get("verification") != "RECEIPT_VERIFIED":
        raise FreightStagingError(
            "the prerequisite attempt replay is not a verified receipt: "
            f"{verdict.get('verification')}"
        )
    facts = freight_facts()
    plan_route = metadata["plan_policy"]["route"]
    if [int(tile) for tile in plan_route["witness_path"]] != facts["witness"]:
        raise FreightStagingError(
            "the prerequisite route witness drifted from the compiled corridor"
        )
    if int(plan_route["depot"]) != DEPOT_TILE or int(plan_route["depot_front"]) != DEPOT_FRONT_TILE:
        raise FreightStagingError("the prerequisite depot pins drifted from the compiled corridor")
    expected_welcome = metadata["world"]["expected_welcome"]
    if expected_welcome != retained_welcome():
        raise FreightStagingError("the prerequisite welcome is not the retained world identity")
    return dict(
        schema=D5_FREIGHT_PREREQUISITE_SCHEMA,
        role="PREREQUISITE_ATTEMPT",
        retained_directory=str(prerequisite),
        save="after.sav",
        save_sha256=save_digest,
        qualified_save_sha256=None,
        prelaunch_digest=seal,
        attempt=metadata["attempt"],
        milestone=metadata.get("milestone"),
        expected_welcome=expected_welcome,
        verification=(
            "full replay verification of the consumed prerequisite attempt "
            "receipt plus the pinned authoritative after-save digest"
        ),
        provenance=dict(
            schema=metadata["schema"],
            attempt=metadata["attempt"],
            milestone=metadata.get("milestone"),
            prelaunch_sha256=seal,
            after_save_sha256=save_digest,
            plan_digest=metadata["plan_policy"]["plan_digest"],
            route=metadata["plan_policy"]["route"],
            statement=(
                "the staged freight source world is the consumed D4 corridor "
                "candidate's receipt-bound close-out save; the candidate-5 "
                "lineage record is embedded as provenance, never as a "
                "re-opened chain walk"
            ),
        ),
    )


# --- Candidate planning facts -------------------------------------------------


def plan_policy() -> dict:
    """The freight cycle's authorized plan policy for the staged candidate.

    The scalar ``target_tile`` keeps the proven shared authorization payload
    shape: the pickup stop tile, where the only vehicle-carrying chain of the
    plan starts. The complete ordered exchange scope joins the payload
    additively through the same shared authorization builder keys (schedule
    + ``plan_digest``; per-op admission intents are receipts, not plan
    identities). ``schedule_version`` names the schedule derivation the plan
    digest binds: the fixed fifteen-exchange derivation.
    """
    schedule = freight_schedule()
    facts = freight_facts()
    plan_model = freight_plan()
    optimized = optimized_freight_route()
    if plan_model.schema_version != 2 or plan_model.witness != optimized.route:
        raise FreightStagingError("the staged plan is not the optimizer-selected route")
    if schedule[0]["exchange"] != FREIGHT_EXCHANGE_IDS[0] or schedule[0]["op"] != "site":
        raise FreightStagingError("the staged schedule must begin with the site admission")
    commands = ("GSVehicle.BuildVehicle", "GSOrder.AppendOrder", "GSVehicle.StartStopVehicle")
    if any(entry["op"] not in FREIGHT_OPS for entry in schedule):
        raise FreightStagingError("a scheduled exchange carries an unknown op")
    return dict(
        company=FREIGHT_COMPANY,
        target_tile=int(PICKUP_STOP_TILE),
        max_cost=FREIGHT_MAX_COST,
        command=" + ".join(commands),
        stale_rule=(
            "re-observe every pin of each exchange immediately before its "
            "one dispatch; any mismatch stops the phase without any command "
            "and preserves the verified prefix"
        ),
        identity=(
            "wire contract v5: every exchange presents one uniform prelaunch "
            "plan digest; per-op admission intents are receipts, not new plan "
            "identities (one attempt, one company, one vehicle)"
        ),
        schedule=schedule,
        plan_digest=plan_digest_of(schedule),
        plan_model_digest=plan_model.digest,
        schedule_version=SCHEDULE_VERSION,
        optimizer=dict(
            schema="d5-corridor-route-optimizer-v1",
            planner="candidate-network-optimizer",
            planner_version="1",
            objective="minimize-planned-capex",
            candidate_id=optimized.candidate_id,
            route=list(optimized.route),
            route_digest=freight_route_digest(optimized.route),
            depot=optimized.depot,
            depot_front=optimized.depot_front,
            pickup_front=optimized.pickup_front,
            delivery_front=optimized.delivery_front,
            execution_plan_digest=optimized.plan_digest,
            scenario_digest=optimized.scenario_digest,
            infrastructure_spend_gbp=str(optimized.metrics.infrastructure_spend_gbp),
            vehicle_purchase_cost_gbp=str(optimized.metrics.vehicle_purchase_cost_gbp),
            statement=(
                "the ordered witness, fronts and depot bound into the wire "
                "plan are the production P05 optimizer's selected decision "
                "over the retained bounded corridor survey, not a renamed "
                "hardcoded route"
            ),
        ),
        world=dict(
            pickup=int(PICKUP_STOP_TILE),
            pickup_front=int(PICKUP_FRONT_TILE),
            delivery=int(DELIVERY_STOP_TILE),
            delivery_front=int(DELIVERY_FRONT_TILE),
            depot=DEPOT_TILE,
            depot_front=int(DEPOT_FRONT_TILE),
            company=FREIGHT_COMPANY,
            cargo=FREIGHT_CARGO_ID,
            pickup_industry=FREIGHT_PICKUP_INDUSTRY,
            delivery_industry=FREIGHT_DELIVERY_INDUSTRY,
            expected_funds=FUNDS_AT_D4_CLOSE,
            witness=facts["witness"],
            coverage=facts["coverage"],
            expected_fleet=0,
            watch_ticks=WATCH_MAX_TICKS,
            watch_days=LOAD_WATCH_MAX_DAYS,
            max_watch_requests=32,
            statement=(
                "the staged freight world is the D4 corridor close-out: "
                "route-receipt-bound truck stops, company depot, one planned "
                "cycle vehicle on road fuel"
            ),
        ),
        prerequisite_world=dict(
            schema=D5_FREIGHT_PREREQUISITE_SCHEMA,
            statement=(
                "the freight candidate's source world is the D4 corridor "
                "close-out: both stops must read company truck stops with "
                "their pinned fronts, the depot joined to its pinned front "
                "and an unpaused company with zero vehicles at native "
                "admission time"
            ),
        ),
    )


def budgets() -> dict:
    """The staged budget table for the freight candidate.

    The request accounting stays bound to the staged schedule derivation
    (15 planned exchanges, 32 unique-id dispatcher cap); there is deliberately
    no aggregate phase-spending budget — the per-exchange ``max_cost`` ceiling
    plus the single realized purchase remain the only cost contract.
    """
    return dict(
        launches=1,
        connection_attempts=1,
        requests=FREIGHT_STAGED_REQUESTS_BUDGET,
        planned_exchanges=PLANNED_FREIGHT_REQUESTS,
        gsadmin_bytes=MAX_FREIGHT_SEND_BYTES,
        response_bytes=MAX_FREIGHT_RESPONSE_BYTES,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        watch_seconds=FREIGHT_WATCH_WALL_SECONDS,
        total_seconds=900,
        watch_ticks=WATCH_MAX_TICKS,
        watch_days=LOAD_WATCH_MAX_DAYS,
        max_cost=FREIGHT_MAX_COST,
        expected_funds=FUNDS_AT_D4_CLOSE,
    )


def expected_readback_policy() -> dict:
    """The receipt contract's observable readback story for the freight cycle."""
    return dict(
        admission=(
            "the site exchange returns READY with both stops as valid truck "
            "stop stations, the depot joined to its pinned front, the fully "
            "connected witness summary, the delivery acceptance catchment, "
            "the recorded production/waiting levels, a company with zero "
            "vehicles and the D4 close-out funds exactly"
        ),
        engine=(
            "the engine exchange returns READY with one enumerated buildable "
            "road truck at its tested positive quote within the ceiling"
        ),
        purchase=(
            "the purchase exchange re-quotes equal to the tested quote and "
            "builds the one vehicle in the pinned depot, funds moving by "
            "exactly the recorded quote"
        ),
        vehicle=(
            "each independent vehicle readback re-observes the admitted "
            "identity, capacity and cargo natively at zero cost"
        ),
        orders=(
            "the two append exchanges record the pickup full-load and the "
            "delivery no-load stop orders against the site-read station ids; "
            "the inventory exchange verifies the exact two-order set"
        ),
        drive=(
            "the three windows record their honest observations under their "
            "bounded tick/day budgets: the full load at the pickup stop, the "
            "full load read at the pinned delivery tile after the full "
            "witness progress, and the empty reload with reconciled monitor "
            "arithmetic (paired with one consumed delivery monitor)"
        ),
        finance=(
            "the finance exchange records the same-quarter income and "
            "delivered-cargo increases over the armed baselines plus the "
            "cargo acceptance date corroborating the delivery window"
        ),
        finish=(
            "the finish exchange records its issued stop and the vehicle's "
            "final enumerable state; the vehicle is never sold and no "
            "further authority is implied"
        ),
        receipt=(
            "cycle-bound only after every exchange verifies against the "
            "accumulated attempt state, in execution order, with the full "
            "cycle receipt re-verified from the retained exchanges"
        ),
    )


def attempt_name() -> str:
    """The candidate's one attempt name, bound to its own staged scope."""
    return FREIGHT_ATTEMPT


# --- Candidate staging ---------------------------------------------------------


def prepare_candidate(
    directory: Path, *, prerequisite: Path = PINNED_PREREQUISITE
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise FreightStagingError("the staged world requires the pinned D4 prerequisite")
    schedule = freight_schedule()
    if (
        len(schedule) != PLANNED_FREIGHT_EXCHANGES
        or [entry["exchange"] for entry in schedule] != list(FREIGHT_EXCHANGE_IDS)
        or plan_policy()["schedule_version"] != SCHEDULE_VERSION
    ):
        raise FreightStagingError("the staged freight schedule drifted")
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise FreightStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    binding = prerequisite_binding(prerequisite)
    welcome = binding["expected_welcome"]
    world = stage_world(binding, welcome)
    plan = plan_policy()
    if sha256(source_save_path(world)) != world["save_sha256"]:
        raise FreightStagingError("staged world source save digest mismatch")
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        with os.fdopen(
            os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as stream:
            stream.write(key._secret)
        workspace.write_config(
            AdminSettings(
                password="",
                port=reservation.admin_port,
                game_port=reservation.game_port,
                authorized_public_key_hex=key.public_hex,
            )
        )
        config = workspace.config.read_text().replace(
            "pause_on_newgame = true", "pause_on_newgame = false"
        )
        # Save-load composition: no [game_creation] block; the queued source
        # save provides the world. Staged scripts announce retained identities.
        config += (
            "\n[ai]\nai_in_multiplayer = true\n[misc]\ngraphicsset = OpenGFX\n"
            f"[game_scripts]\n{SOURCE_SAVE_GS_NAME} = \n"
        )
        workspace.config.write_text(config)
        graphics = stage_opengfx(
            PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip",
            workspace.root / "baseset/OpenGFX",
        )
        write_json(
            directory / "graphics-identity.json",
            dict(asdict(graphics), directory=str(graphics.directory)),
        )
        staged_save = workspace.root / "source.sav"
        shutil.copyfile(source_save_path(world), staged_save)
        verify_staged_source_save({"save_sha256": world["save_sha256"]}, staged_save)
        (workspace.game / SOURCE_SAVE_GS_NAME).mkdir()
        composition, create_instance, version = staged_composition()
        for name in ("info.nut", "main.nut"):
            (workspace.game / SOURCE_SAVE_GS_NAME / name).write_bytes(composition[name])
        (workspace.ai / STAGED_AI_DIRECTORY).mkdir()
        for name in ("info.nut", "main.nut"):
            shutil.copyfile(AI_PACKAGE / name, workspace.ai / STAGED_AI_DIRECTORY / name)
        argv = (
            str(BINARY),
            f"-D127.0.0.1:{reservation.game_port}",
            "-c",
            str(workspace.config),
            "-x",
            "-X",
            "-g",
            str(staged_save),
            "-dscript=4,grf=1,net=3",
        )
        spec = LaunchSpecification(
            workspace,
            RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        frozen = source_freeze()
        for source in (FREIGHT_PACKAGE, AI_PACKAGE):
            for path in sorted(source.glob("*.nut")):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(path): sha256(path)
                for path in sorted(workspace.root.rglob("*"))
                if path.is_file() and path.name != ".admin-secret"
            }
        )
        # The exact runtime closure of the D5 execution path (including the
        # offline freight schedule chain and the D4 corridor machinery it
        # imports) and the exact installed dependency bytes join the shared
        # source_freeze() contract through the same parameterized D2
        # machinery — never weakening it.
        frozen.update(d2_source_closure(D5_CLOSURE_ROOT))
        frozen.update(d2_dependency_inventory(D5_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D5_FREIGHT_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_FREIGHT,
            kind=KIND,
            attempt=attempt_name(),
            workspace=str(workspace.root),
            binary_sha256=BINARY_SHA256,
            argv=list(argv),
            public_key=key.public_hex,
            game_port=reservation.game_port,
            admin_port=reservation.admin_port,
            world=world,
            game_script_identity=dict(
                name=SOURCE_SAVE_GS_NAME,
                version=version,
                create_instance=create_instance,
                statement=(
                    "the staged composition announces the save's stored GameScript "
                    "name/version from the retained frozen-source evidence; the "
                    "D5 freight handler runs as the retained CreateInstance subclass"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after.sav only; the retained "
                "source save, the prerequisite attempt record and every "
                "historical artifact stay untouched"
            ),
            plan_policy=plan,
            expected_readback=expected_readback_policy(),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.corridor_freight_native",
                "run",
                str(directory),
            ],
            budgets=budgets(),
            cleanup=[
                "close secure session",
                "quit and reap process",
                "verify endpoints",
                "retain session logs and saves",
                "remove credential",
                "dispose owned workspace",
                "never modify the retained save or any historical artifact",
            ],
            authorization=(
                "PENDING — requires ONE fresh operator authorization after all "
                "preflight gates; offline staging consumed no claim and no "
                "authorization file exists"
            ),
            pin_provenance=dict(
                source=PICKUP_STOP_TILE,
                manifest_verified=True,
                statement=(
                    "plan derives from the replay-verified D4 corridor "
                    "candidate's close-out world cross-checked against the "
                    "compiled corridor derivation and the sealed census "
                    "coverage facts; the prerequisite after-save digest is "
                    "pinned"
                ),
            ),
            environment=launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
        )
        metadata["prerequisite"] = dict(
            schema=D5_FREIGHT_PREREQUISITE_SCHEMA,
            attempt=binding["attempt"],
            milestone=binding["milestone"],
            directory=binding["retained_directory"],
            prelaunch_sha256=binding["prelaunch_digest"],
            after_save_sha256=binding["save_sha256"],
            verification=binding["verification"],
        )
        metadata["prerequisite_provenance"] = binding["provenance"]
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return prepared
    finally:
        reservation.close()


def preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal of the staged D5 candidate.

    Opens nothing, consumes nothing: the seal, the frozen runtime closure,
    the schedule pins, the world binding and the endpoint reservation are
    re-checked exactly like the D4 preflight, with the D5 lineage gates for
    the staged chain.
    """
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    if metadata.get("schema") != D5_FREIGHT_PRELAUNCH_SCHEMA:
        raise ValueError("staged prelaunch record is not the D5 freight lineage")
    verify_freeze(metadata["frozen"])
    require_frozen_d2_closure(metadata["frozen"], D5_CLOSURE_ROOT)
    require_frozen_d2_dependencies(metadata["frozen"], D5_CLOSURE_ROOT)
    plan = metadata["plan_policy"]
    if metadata["attempt"] != attempt_name():
        raise ValueError("staged attempt identity drifted from its own scope")
    staged = freight_schedule()
    if plan["schedule"] != staged or plan["plan_digest"] != plan_digest_of(staged):
        raise ValueError("staged freight schedule drifted from the compiled derivation")
    world = plan["world"]
    pins = freight_plan()
    optimized = optimized_freight_route()
    if pins.schema_version != 2:
        raise ValueError("the staged plan is not the optimizer-derived schema")
    # Every execution-relevant world pin must match the compiled plan; a
    # re-sealed PRELAUNCH record is not a substitute for these derivations.
    expected_world = dict(
        pickup=pins.pickup,
        pickup_front=pins.pickup_front,
        delivery=pins.delivery,
        delivery_front=pins.delivery_front,
        depot=pins.depot,
        depot_front=pins.depot_front,
        company=pins.company,
        cargo=pins.cargo,
        pickup_industry=pins.pickup_industry,
        delivery_industry=pins.delivery_industry,
        expected_funds=pins.expected_funds,
        witness=list(pins.witness),
        expected_fleet=0,
        watch_ticks=WATCH_MAX_TICKS,
        watch_days=LOAD_WATCH_MAX_DAYS,
        max_watch_requests=FREIGHT_REQUEST_BUDGET,
    )
    for name, expected in expected_world.items():
        if world.get(name) != expected:
            raise ValueError(f"staged world pin {name} drifted from the compiled plan")
    for name, expected in (
        ("company", pins.company),
        ("target_tile", pins.pickup),
        ("max_cost", pins.max_cost),
        ("plan_model_digest", pins.digest),
    ):
        if plan.get(name) != expected:
            raise ValueError(f"staged plan pin {name} drifted from the compiled plan")
    if metadata.get("budgets") != budgets():
        raise ValueError("staged budget pins drifted from the compiled contract")
    optimizer = plan.get("optimizer")
    if not isinstance(optimizer, dict):
        raise ValueError("the staged plan lacks its optimizer provenance")
    expected_optimizer = dict(
        route=list(pins.witness),
        route_digest=pins.route_digest,
        candidate_id=optimized.candidate_id,
        depot=optimized.depot,
        depot_front=optimized.depot_front,
        pickup_front=optimized.pickup_front,
        delivery_front=optimized.delivery_front,
        execution_plan_digest=optimized.plan_digest,
        scenario_digest=optimized.scenario_digest,
    )
    for name, expected in expected_optimizer.items():
        if optimizer.get(name) != expected:
            raise ValueError(f"staged optimizer pin {name} drifted from the selected route")
    for entry in staged:
        if entry["op"] not in (
            "site",
            "engine",
            "purchase",
            "vread",
            "order",
            "order-read",
            "monitor",
            "start",
            "load-watch",
            "transit-watch",
            "deliver-watch",
            "finance",
            "finish",
        ):
            raise ValueError("a scheduled exchange carries an unknown op")
        if entry["op"] in ("transit-watch", "deliver-watch") and entry.get("watch_days"):
            raise ValueError("a delivery window presents no day budget")
        if entry["op"] == "load-watch" and (
            entry["watch_ticks"] > WATCH_MAX_TICKS or entry["watch_days"] != LOAD_WATCH_MAX_DAYS
        ):
            raise ValueError("the load window exceeds its bounded phase budget")
    binding = prerequisite_binding(Path(metadata["prerequisite"]["directory"]))
    required = ("attempt", "milestone", "directory", "prelaunch_sha256", "after_save_sha256")
    staged_prereq = {name: metadata["prerequisite"][name] for name in required}
    if staged_prereq != dict(
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
    ):
        raise ValueError("the staged prerequisite binding drifted from its replay-verified record")
    if metadata["prerequisite"].get("schema") != D5_FREIGHT_PREREQUISITE_SCHEMA:
        raise ValueError("the staged prerequisite schema drifted from the D5 lineage")
    world = metadata["world"]
    if (
        world.get("retained_directory") != binding["retained_directory"]
        or world.get("source_save") != binding["save"]
        or world.get("save_sha256") != binding["save_sha256"]
        or world.get("qualified_save_sha256") != binding.get("qualified_save_sha256")
    ):
        raise ValueError("the staged world is not the pinned prerequisite after-save")
    if world["save_sha256"] != PINNED_PREREQUISITE_AFTER_SAVE:
        raise ValueError("the staged world save digest is not the pinned authoritative world")
    if metadata["world"]["expected_welcome"] != retained_welcome():
        raise ValueError("retained world identity requirements drifted")
    verify_staged_source_save(
        {"save_sha256": metadata["world"]["save_sha256"]},
        Path(metadata["workspace"]) / "source.sav",
    )
    composition, _, _ = staged_composition()
    staged_identity = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME
    if staged_identity.joinpath("info.nut").read_bytes() != composition["info.nut"]:
        raise ValueError("staged GameScript identity drifted from the retained composition")
    if staged_identity.joinpath("main.nut").read_bytes() != composition["main.nut"]:
        raise ValueError("staged freight handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- Wire protocol 5: shared request bound for live and replay paths ----------


def encode_freight_request(payload: bytes) -> bytes:
    """Frame one protocol-5 request under its named application bound.

    Both the live exchange and the retained-frame replay call this helper, so
    the 640-byte request contract cannot silently fall back to the generic
    512-byte default on one path only.
    """
    return encode_gamescript(payload, max_payload_bytes=MAX_FREIGHT_REQUEST_BYTES)


def decode_freight_request(payload: bytes) -> bytes:
    """Decode one protocol-5 request body under the same named bound."""
    return decode_gamescript(payload, max_payload_bytes=MAX_FREIGHT_REQUEST_BYTES)


# --- Wire protocol 5: secure session and one-launch backend --------------------


class FreightSecureSession(SecureAdminSession):
    """Only the freight operations extend the secure write policy."""

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = FreightRequest.model_validate_json(decode_freight_request(frame[3:]))
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class FreightNativeBackend(ClearingNativeBackend):
    """One-launch backend carrying the D5 lineage launch marker."""

    launch_marker_schema = D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> FreightSecureSession:
        """Bind the staged runtime's Admin listener to one owned secure session."""
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await FreightSecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


def exchange_timeout_seconds(request: FreightRequest, *, budget_table: dict) -> float:
    """The wall-clock budget one exchange may consume.

    Window exchanges are bounded by the design's watch-window wall budget plus
    the client margin; every other exchange is an immediate request/readback
    bounded by the staged request budget. This replaces the previous blanket
    ten-second client timeout, which was shorter than the documented window.
    """
    request_seconds = float(budget_table["request_seconds"])
    if request.op in FREIGHT_WATCH_OPS:
        return float(budget_table["watch_seconds"]) + FREIGHT_EXCHANGE_MARGIN_SECONDS
    return request_seconds


def event_loop_deadline(seconds: float) -> float:
    """One monotonic event-loop deadline for the current exchange budget."""
    return time.monotonic() + seconds


async def exchange(
    session,
    request: FreightRequest,
    directory: Path,
    *,
    budget_table: dict | None = None,
    overall_deadline: float | None = None,
    clock=time.monotonic,
    timeout_factory=asyncio.timeout,
) -> FreightReadback:
    """One sealed protocol-5 exchange; every frame and file is retained.

    The per-exchange timeout is derived from the applicable phase budget and
    clamped to the attempt's remaining overall budget. Timeout, cancellation,
    disconnection, duplicate frames and stale frames all fail closed; a late
    response for another request can never be accepted as this exchange.
    """
    budget_table = budget_table if budget_table is not None else budgets()
    permitted = exchange_timeout_seconds(request, budget_table=budget_table)
    if overall_deadline is not None:
        remaining = overall_deadline - clock()
        if remaining <= 0:
            raise TimeoutError("freight attempt overall watch window exhausted")
        permitted = min(permitted, remaining)
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_freight_request(raw))
    decoder = AdminFrameDecoder()
    try:
        async with timeout_factory(permitted):
            while True:
                chunk = await session.receive()
                if not chunk:
                    raise ConnectionError("freight proof stream disconnected")
                game_frames = []
                for kind, payload in decoder.feed_frames(chunk):
                    if kind != SERVER_GAMESCRIPT:
                        raise ValueError("unexpected freight-proof packet")
                    game_frames.append(payload)
                if len(game_frames) > 1:
                    raise ValueError("duplicate freight-proof response frame")
                if game_frames:
                    response = decode_gamescript(
                        game_frames[0], max_payload_bytes=MAX_FREIGHT_RESPONSE_BYTES
                    )
                    (directory / (request.request_id + "-response.json")).write_bytes(response)
                    return FreightReadback.parse_for(request, response)
    except TimeoutError:
        raise TimeoutError(
            f"freight exchange {request.request_id} exceeded its {permitted:.1f}s budget"
        ) from None


def _freight_exchange_request(
    entry: dict, seal: str, plan: FreightPlan, state: dict
) -> FreightRequest:
    """Build one request whose op echoes are the latched admission facts."""
    op = entry["op"]
    engine = -1
    vehicle = -1
    expected_cost = 0
    order_index = -1
    watch_ticks = -1
    watch_days = -1
    if op == "purchase":
        engine = int(state["engine"].engine)
        expected_cost = int(state["engine"].quote)
    elif op in (
        "vread",
        "order",
        "order-read",
        "monitor",
        "start",
        "load-watch",
        "transit-watch",
        "deliver-watch",
        "finance",
        "finish",
    ):
        engine = int(state["engine"].engine)
        vehicle = int(state["vehicle"])
    if op == "order":
        order_index = int(entry["order_index"])
    if op == "load-watch":
        watch_ticks = int(entry["watch_ticks"])
        watch_days = int(entry["watch_days"])
    elif op in ("transit-watch", "deliver-watch"):
        watch_ticks = int(entry["watch_ticks"])
    return FreightRequest(
        op=op,
        request_id=entry["exchange"],
        plan=seal,
        company=plan.company,
        max_cost=plan.max_cost,
        pickup=plan.pickup,
        delivery=plan.delivery,
        depot=plan.depot,
        route=plan.witness if op == "site" else None,
        route_digest=plan.route_digest,
        engine=engine,
        vehicle=vehicle,
        expected_cost=expected_cost,
        order_index=order_index,
        watch_ticks=watch_ticks,
        watch_days=watch_days,
    )


def verify_request_against_plan(request: FreightRequest, *, plan: FreightPlan, seal: str) -> None:
    """Refuse a request that is not bound to the local planner plan.

    This is the trust anchor the GameScript cannot provide: Python owns the
    optimizer-derived witness and derives its digest, so a stale or tampered
    request is rejected before any byte reaches the Admin session.  The
    GameScript's ``route_digest`` latch then extends that binding across the
    attempt, refusing later drift before the purchase exchange.
    """
    if request.plan != seal:
        raise ValueError("request plan digest is not the staged prelaunch seal")
    if request.company != plan.company:
        raise ValueError("request company drifted from the planned company")
    if (request.pickup, request.delivery, request.depot) != (
        plan.pickup,
        plan.delivery,
        plan.depot,
    ):
        raise ValueError("request pins drifted from the planned corridor")
    if request.max_cost != plan.max_cost:
        raise ValueError("request ceiling drifted from the planned ceiling")
    if request.route_digest != plan.route_digest:
        raise ValueError("request route digest drifted from the planned witness")
    if request.op == "site":
        if request.route != plan.witness:
            raise ValueError("site request route drifted from the planned witness")
    elif request.route is not None:
        raise ValueError("only the site request may carry a route")


def deny_verification(result: dict, *, status: str, message: str) -> None:
    """Terminally deny a successful verdict while preserving its diagnostics.

    The previously successful status is retained under ``prior_status`` and an
    existing error (the original exception) is never overwritten; the denial
    message is recorded separately in that case. Repeated calls are idempotent.
    """
    prior = result.get("status")
    result["verified"] = False
    if prior != status:
        result["prior_status"] = prior
    result["status"] = status
    if result.get("error"):
        result.setdefault("denial_errors", []).append(message)
    else:
        result["error"] = message


def apply_cleanup_outcome(result: dict, *, complete: bool) -> None:
    """Fail closed on the final cleanup verdict, after every earlier mutation.

    A run whose verification succeeded but whose cleanup was not certified can
    never remain verified and can never report a successful terminal status.
    A run that was already unsuccessful keeps its own terminal status (the
    phase-halt evidence stays intact) but is still marked ``cleanup_failure``
    and ``cleanup_complete: false`` so the CLI exit and replay both fail closed.
    """
    result["cleanup_complete"] = bool(complete)
    if complete:
        return
    result["cleanup_failure"] = True
    if result.get("verified") is True or result.get("status") == "NATIVE_FREIGHT_VERIFIED":
        deny_verification(
            result,
            status="FAILED_CLEANUP",
            message=("ValueError: cleanup was not certified; no verified receipt is possible"),
        )


async def execute_freight_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt freight phase (never offline).

    Bounded protocol-5 ceremony against an authorized backend seam: preflight,
    operator claim consumption, launch boundary, world identity, session
    saves, then the fixed fifteen-exchange freight cycle in order. Every
    exchange runs one request whose readback is verified against the
    accumulated attempt state by the production freight state machine; the
    first verification failure halts the phase: earlier verified exchanges
    are preserved, later exchanges never execute, and the world state after a
    failed attempt is explicitly uncertain (nothing compensates or retries).
    """
    directory = prepared.directory
    preflight(prepared)
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    grant = grant_launch(directory, metadata, seal)
    grant.launch_identity = launch_critical_identity(prepared, metadata)
    write_json(
        directory / "CLAIM.json",
        dict(
            prelaunch_digest=seal,
            consumed=True,
            launches_allowed=1,
            retries=0,
            authorization_schema=CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
            authorization_sha256=grant.authorization_sha256,
            operator_key_identity=grant.operator_key_identity,
        ),
    )
    backend.preflight(prepared)
    schedule: list[dict] = metadata["plan_policy"]["schedule"]
    plan = freight_plan()
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        requests=0,
        exchanges=[],
        last_status="NOT_DISPATCHED",
        command_accepted=False,
        state_changed=False,
        verified=False,
        status="FAILED",
        halt=None,
    )
    frames = []
    exchanges: list[tuple[FreightRequest, FreightReadback]] = []
    state: dict[str, Any] = dict(site=None, engine=None, vehicle=-1)
    overall_deadline = event_loop_deadline(metadata["budgets"]["total_seconds"])
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared, authorization=grant)
            result["native_launches"] = 1
            await wait_log(backend, prepared, FREIGHT_READY_MARKER)
            console(backend, metadata["bootstrap_command"])
            await wait_log(backend, prepared, ROAD_PROOF_COMPANY_READY_MARKER)
            session = await backend.connect(
                prepared, frame_observer=lambda d, f: frames.append((d, f.hex()))
            )
            result["connections"] = 1
            await session.authenticate(metadata["attempt"], "1", timeout=10)
            welcome = session.welcome
            expected = metadata["world"]["expected_welcome"]
            received = None
            if welcome is not None:
                received = tuple(getattr(welcome, field) for field in WELCOME_ORDER)
            wanted = (
                expected["revision"],
                True,
                expected["seed"],
                expected["landscape"],
                expected["start_day"],
                expected["width"],
                expected["height"],
            )
            if session.protocol is None or welcome is None or received != wanted:
                raise ValueError("retained world identity mismatch")
            write_json(
                directory / "runtime-identity.json",
                dict(
                    auth="X25519_AuthorizedKey",
                    encrypted=session.state is AuthState.ACTIVE,
                    welcome=asdict(welcome),
                    pid=backend.process.pid if backend.process else None,
                ),
            )
            await GameScriptTransport(session, session.protocol).subscribe()
            before_save = await save(backend, prepared, "session-before")
            write_json(directory / "session-before-identity.json", dict(sha256=before_save))
            for entry in schedule:
                label = entry["exchange"]
                try:
                    request = _freight_exchange_request(entry, seal, plan, state)
                    verify_request_against_plan(request, plan=plan, seal=seal)
                    readback = await exchange(
                        session,
                        request,
                        directory,
                        budget_table=metadata["budgets"],
                        overall_deadline=overall_deadline,
                    )
                    result["requests"] += 1
                    probe = freight_phase_outcome(
                        exchanges + [(request, readback)], prelaunch_digest=seal, plan=plan
                    )
                    if probe["failed"] is not None:
                        raise ValueError(
                            f"freight exchange {label} failed verification: "
                            f"{probe['failed']['error']}"
                        )
                    receipt = probe["completed"][-1]
                    # The purchase group folds its independent read into one
                    # receipt, so the current exchange may be bound under an
                    # ``*request_id`` field other than ``request_id``.
                    receipt_ids = {
                        value for key, value in receipt.items() if key.endswith("request_id")
                    }
                    if label not in receipt_ids:
                        raise ValueError(f"freight exchange {label} drifted from its schedule")
                    exchanges.append((request, readback))
                    result["exchanges"].append(label)
                    result["last_status"] = readback.status
                    result["command_accepted"] = True
                    result["state_changed"] = True
                    if entry["op"] == "site":
                        state["site"] = admit_freight_site(
                            readback, prelaunch_digest=seal, plan=plan
                        )
                    elif entry["op"] == "engine":
                        state["engine"] = admit_freight_engine(
                            readback, prelaunch_digest=seal, plan=plan, site=state["site"]
                        )
                    elif entry["op"] == "purchase":
                        state["vehicle"] = readback.vehicle
                except Exception as error:
                    result["halt"] = dict(
                        label=label, error=type(error).__name__ + ": " + str(error)
                    )
                    break
            phase = freight_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
            result["phase"] = phase
            if phase["verification"] == "PHASE_COMPLETE":
                if len(exchanges) != PLANNED_FREIGHT_EXCHANGES:
                    raise ValueError("phase completion evidence drifted from the staged schedule")
                cycle = verify_freight_cycle(exchanges, prelaunch_digest=seal, plan=plan)
                after_save = await save(backend, prepared, "after")
                write_json(
                    directory / "receipt.json",
                    dict(
                        phase,
                        cycle,
                        before_save_sha256=before_save,
                        after_save_sha256=after_save,
                    ),
                )
                result["verified"] = True
                result["status"] = "NATIVE_FREIGHT_VERIFIED"
            else:
                result["status"] = "PHASE_HALTED_PREFIX_PRESERVED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if result.get("last_status") not in ("NOT_DISPATCHED",):
            try:
                result["after_diagnostic_save_sha256"] = await save(
                    backend,
                    prepared,
                    "after-diagnostic",
                    diagnostic=True,
                )
            except Exception as save_error:
                result["after_save_error"] = type(save_error).__name__ + ": " + str(save_error)
        write_json(directory / "frames.json", frames)
        cleanup = await backend.cleanup(prepared)
        result["returncode"] = cleanup.get("returncode")
        for name in ("stdout.log", "stderr.log"):
            path = prepared.spec.workspace.logs / name
            if path.is_file():
                shutil.copyfile(path, directory / name)
        findings = script_log_health_findings(
            "".join(
                (directory / name).read_text()
                for name in ("stdout.log", "stderr.log")
                if (directory / name).is_file()
            )
        )
        if findings:
            result["script_log_findings"] = findings
            if result["status"] == "NATIVE_FREIGHT_VERIFIED":
                deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: retained script log health findings deny the verified receipt"
                    ),
                )
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_FREIGHT_VERIFIED":
                deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: native runtime exited abnormally after receipt "
                        f"(return code {result['returncode']})"
                    ),
                )
        cleanup_complete = False
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup))
            prepared.spec.workspace.close()
            cleanup["workspace_disposed"] = not prepared.spec.workspace.root.exists()
            cleanup["credential_removed"] = not prepared.key_path.exists()
            cleanup_complete = bool(
                cleanup.get("reaped") is True
                and not cleanup.get("cleanup_error")
                and cleanup.get("workspace_disposed") is True
                and cleanup.get("credential_removed") is True
            )
            if not cleanup_complete:
                raise ValueError("cleanup incomplete")
        except Exception as error:
            cleanup["verification_error"] = str(error)
            cleanup_complete = False
        apply_cleanup_outcome(result, complete=cleanup_complete)
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


# --- D5 phase replay verification ------------------------------------------------


def _parse_phase_frames(directory: Path):
    """Parse the retained frame stream of the owned secure session."""
    frames = json.loads((directory / "frames.json").read_text())
    outbound: list[bytes] = []
    replies: list[bytes] = []
    outbound_requests: list[FreightRequest] = []
    request_positions: dict[bytes, int] = {}
    reply_positions: dict[bytes, int] = {}
    for index, (direction, frame_hex) in enumerate(frames):
        frame = bytes.fromhex(frame_hex)
        if direction == "outbound":
            outbound.append(frame)
            if frame[2] != ADMIN_GAMESCRIPT:
                continue
            payload = decode_freight_request(frame[3:])
            try:
                query = FreightRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("outbound frame contains invalid FreightRequest") from None
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                # The retained session stream also carries the handshake and
                # keepalive frames; only the gamescript exchanges are proof
                # material (the shared D2 chronology semantics).
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body, max_payload_bytes=MAX_FREIGHT_RESPONSE_BYTES)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)
    return outbound, outbound_requests, replies, request_positions, reply_positions


def verify_attempt_identity(metadata: dict, *, plan: FreightPlan) -> dict:
    """Re-bind one retained attempt to its pinned prerequisite and plan.

    Replay must not trust the staged record's own declarations: the pinned D4
    prerequisite is re-verified from its retained receipt, the staged world's
    source-save digest must equal that prerequisite's receipt-bound after-save
    digest, the full retained welcome must match, and every plan/route/scenario
    digest is re-derived. Returns the independently derived prerequisite
    binding for callers that need its provenance.
    """
    if metadata.get("attempt") != attempt_name():
        raise ValueError("retained attempt identity drifted from the staged scope")
    if (
        metadata.get("schema") != D5_FREIGHT_PRELAUNCH_SCHEMA
        or metadata.get("kind") != KIND
        or metadata.get("milestone") != MILESTONE_FREIGHT
    ):
        raise ValueError("retained attempt is not the D5 freight lineage")
    staged_prerequisite = metadata.get("prerequisite")
    if not isinstance(staged_prerequisite, dict):
        raise ValueError("retained attempt lacks its prerequisite binding")
    binding = prerequisite_binding(Path(staged_prerequisite.get("directory", "")))
    expected_prerequisite = dict(
        schema=D5_FREIGHT_PREREQUISITE_SCHEMA,
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
        verification=binding["verification"],
    )
    if staged_prerequisite != expected_prerequisite:
        raise ValueError("retained prerequisite binding drifted from the pinned D4 attempt")
    world = metadata.get("world")
    if not isinstance(world, dict):
        raise ValueError("retained attempt lacks its world binding")
    expected_world_binding = dict(
        retained_directory=binding["retained_directory"],
        source_save=binding["save"],
        save_sha256=binding["save_sha256"],
        qualified_save_sha256=binding.get("qualified_save_sha256"),
    )
    for name, expected in expected_world_binding.items():
        if world.get(name) != expected:
            raise ValueError(f"retained world {name} drifted from the pinned prerequisite")
    if world.get("save_sha256") != PINNED_PREREQUISITE_AFTER_SAVE:
        raise ValueError("retained world is not the pinned prerequisite after-save")
    expected_welcome = world.get("expected_welcome")
    if expected_welcome != binding["expected_welcome"] or expected_welcome != retained_welcome():
        raise ValueError("retained world welcome drifted from the pinned identity")
    source_save = source_save_path(world)
    if not source_save.is_file():
        raise ValueError("the pinned prerequisite source save is absent")
    verify_staged_source_save({"save_sha256": binding["save_sha256"]}, source_save)
    staged_source = Path(metadata.get("workspace", "")) / "source.sav"
    if staged_source.is_file():
        verify_staged_source_save({"save_sha256": binding["save_sha256"]}, staged_source)

    plan_policy = metadata.get("plan_policy")
    if not isinstance(plan_policy, dict):
        raise ValueError("retained attempt lacks its plan policy")
    schedule = freight_schedule()
    if plan_policy.get("schedule") != schedule or plan_policy.get("plan_digest") != plan_digest_of(
        schedule
    ):
        raise ValueError("retained freight schedule drifted from the compiled derivation")
    if metadata.get("budgets") != budgets():
        raise ValueError("retained budget contract drifted from the compiled contract")
    world_policy = plan_policy.get("world")
    if not isinstance(world_policy, dict):
        raise ValueError("retained plan policy lacks its world pins")
    expected_pins = dict(
        pickup=plan.pickup,
        pickup_front=plan.pickup_front,
        delivery=plan.delivery,
        delivery_front=plan.delivery_front,
        depot=plan.depot,
        depot_front=plan.depot_front,
        company=plan.company,
        cargo=plan.cargo,
        pickup_industry=plan.pickup_industry,
        delivery_industry=plan.delivery_industry,
        expected_funds=plan.expected_funds,
        witness=list(plan.witness),
    )
    for name, expected in expected_pins.items():
        if world_policy.get(name) != expected:
            raise ValueError(f"retained world pin {name} drifted from the replayed plan")
    for name, expected in (
        ("company", plan.company),
        ("target_tile", plan.pickup),
        ("max_cost", plan.max_cost),
        ("plan_model_digest", plan.digest),
    ):
        if plan_policy.get(name) != expected:
            raise ValueError(f"retained plan pin {name} drifted from the replayed plan")
    optimizer = plan_policy.get("optimizer")
    if not isinstance(optimizer, dict):
        raise ValueError("retained plan policy lacks its optimizer provenance")
    selected = optimized_freight_route()
    expected_optimizer = dict(
        route=list(plan.witness),
        route_digest=plan.route_digest,
        candidate_id=selected.candidate_id,
        depot=selected.depot,
        depot_front=selected.depot_front,
        pickup_front=selected.pickup_front,
        delivery_front=selected.delivery_front,
        execution_plan_digest=selected.plan_digest,
        scenario_digest=selected.scenario_digest,
    )
    for name, expected in expected_optimizer.items():
        if optimizer.get(name) != expected:
            raise ValueError(f"retained optimizer pin {name} drifted from the selected route")
    return binding


def verify_freight_attempt(directory: Path) -> dict:
    """Replay retained protocol-5 phase semantics; never trust a success label.

    The replay re-derives every retained fact independently: the operator
    authorization evidence, the staged freight schedule, the captured
    session frames and every per-exchange request/response pair, then
    re-verifies the whole cycle (receipt bound with the before/after save
    digests) with the production
    :func:`app.simulation.openttd.corridor_freight.freight_phase_outcome`
    and :func:`verify_freight_cycle`. A success label alone is never
    evidence.
    """
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    claims_path = directory / "CLAIM.json"
    if not claims_path.is_file():
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="CLAIM_ABSENT",
            statement=(
                "the candidate was never consumed by an operator authorization; "
                "no verified receipt is possible"
            ),
        )
    claims = json.loads(claims_path.read_text())
    if claims.get("prelaunch_digest") != seal:
        raise ValueError("attempt claim does not match its prelaunch seal")
    manifest_names: set[str] = set()
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError("artifact manifest mismatch")
        if sha256(directory / name) != digest:
            raise ValueError("artifact manifest mismatch")
        manifest_names.add(name)
    present_names = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != "artifact-manifest.sha256"
    }
    if present_names != manifest_names:
        raise ValueError("artifact manifest is not exhaustive for the attempt directory")
    if metadata.get("schema") != D5_FREIGHT_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D5_FREIGHT_PRELAUNCH_SCHEMA} lineage; no verified receipt is possible"
            ),
        )
    authorization_state = replay_authorization_state(directory, metadata, seal, claims)
    if authorization_state is not None:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state=authorization_state,
            statement=(
                "the retained authorization evidence does not match the "
                "operator-verified record; no verified receipt is possible"
            ),
        )
    plan_policy = metadata["plan_policy"]
    schedule = plan_policy["schedule"]
    if plan_policy["schedule"] != freight_schedule() or plan_policy["plan_digest"] != (
        plan_digest_of(freight_schedule())
    ):
        raise ValueError("staged freight schedule drifted from the compiled derivation")
    _scheduled_exchange_ids(schedule)
    plan = freight_plan()
    verify_attempt_identity(metadata, plan=plan)
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    expected_welcome = metadata["world"]["expected_welcome"]
    welcome = runtime.get("welcome")
    if runtime.get("encrypted") is not True or not isinstance(welcome, dict):
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    for field in WELCOME_ORDER:
        expected = True if field == "dedicated" else expected_welcome[field]
        if welcome.get(field) != expected:
            raise ValueError(f"retained world welcome {field} drifted from the pinned identity")
    outbound, outbound_requests, replies, request_positions, reply_positions = _parse_phase_frames(
        directory
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("freight request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [FreightRequest.model_validate_json(path.read_bytes()) for path in paths]
    for path, query in zip(paths, file_queries, strict=True):
        if query.request_id != path.name[: -len("-request.json")]:
            raise ValueError("retained request file identity does not match its payload")
    if len(outbound_requests) < len(file_queries):
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            exchanges=result.get("exchanges", []),
            state_changed=result.get("state_changed", False),
            result_status=result.get("status", "UNKNOWN"),
            statement="incomplete retained exchange (fewer outbound frames); no receipt claimed",
        )
    if len(outbound_requests) > len(file_queries):
        raise ValueError("outbound frame count exceeds request file count (tampering)")
    if sorted(query.to_bytes() for query in outbound_requests) != sorted(
        query.to_bytes() for query in file_queries
    ):
        raise ValueError("outbound frame payloads do not match request file payloads")
    unknown = {query.request_id for query in file_queries} - _scheduled_exchange_ids(schedule)
    if unknown:
        raise ValueError(f"request identity outside the staged schedule: {sorted(unknown)}")
    seen_ids: set[str] = set()
    for query in outbound_requests:
        if query.request_id in seen_ids:
            raise ValueError(f"duplicate request_id in outbound frames: {query.request_id}")
        seen_ids.add(query.request_id)
    response_map = {}
    for path in paths:
        response_path = path.with_name(path.name.replace("-request.json", "-response.json"))
        if response_path.is_file():
            response_map[path.read_bytes()] = response_path.read_bytes()
    for path in sorted(directory.glob("*-response.json")):
        exchange_id = path.name[: -len("-response.json")]
        try:
            readback = FreightReadback.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise ValueError(
                f"retained response file is not a parseable readback: {path.name}"
            ) from error
        if readback.request_id != exchange_id:
            raise ValueError("retained response file identity does not match its payload")
        if not (directory / (exchange_id + "-request.json")).is_file():
            raise ValueError("retained response file lacks its request")
    for raw, response in response_map.items():
        if outbound.count(encode_freight_request(raw)) != 1 or replies.count(response) != 1:
            raise ValueError("retained exchange lacks unique secure-session frame evidence")
    retained_responses = set(response_map.values())
    for reply in replies:
        if reply not in retained_responses:
            raise ValueError("retained gateway response lacks its durable response file")
    for raw, response in response_map.items():
        if reply_positions[response] < request_positions[raw]:
            raise ValueError("a retained response precedes its own request in the frame stream")

    halted_position = None
    halt_record = result.get("halt")
    exchanges: list[tuple[FreightRequest, FreightReadback]] = []
    for position, entry in enumerate(schedule):
        label = entry["exchange"]
        if (
            halted_position is None
            and isinstance(halt_record, dict)
            and (halt_record.get("label") == label)
        ):
            halted_position = position
        pending = halted_position is not None and position > halted_position
        if not pending:
            request_path = directory / (label + "-request.json")
            if not request_path.is_file():
                continue
            query = FreightRequest.model_validate_json(request_path.read_bytes())
            raw = response_map.get(query.to_bytes())
            # A halted exchange the wire never completed (no response file)
            # is absent evidence, not a verification defect: the attempt's
            # halt already records the stop, so the pending suffix — not the
            # missing reply — carries the story.
            if raw is not None:
                exchange = FreightReadback.parse_for(query, raw)
                exchanges.append((query, exchange))
        if pending:
            break
    phase = freight_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
    cleanup_record = json.loads((directory / "cleanup.json").read_text())
    exit_codes = (result.get("returncode"), cleanup_record.get("returncode"))
    cleanup_complete = (
        all(
            cleanup_record.get(name) is True
            for name in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
        )
        and not bool(cleanup_record.get("cleanup_error"))
        and not bool(cleanup_record.get("verification_error"))
    )
    if any(code not in (None, 0) for code in exit_codes):
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status=result.get("status", "UNKNOWN"),
            error=result.get("error", "process exited abnormally"),
            exit_evidence=dict(returncode=exit_codes[0], cleanup_returncode=exit_codes[1]),
        )
    if result["status"] == "NATIVE_FREIGHT_VERIFIED":
        if phase["verification"] != "PHASE_COMPLETE":
            raise ValueError("verified receipt contradicts its phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("verified receipt contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("verified receipt contradicts its launch/connection seal")
        if len(result.get("exchanges", [])) != PLANNED_FREIGHT_EXCHANGES or not cleanup_complete:
            raise ValueError("verified receipt cleanup or exchange inventory incomplete")
        if len(outbound_requests) != PLANNED_FREIGHT_EXCHANGES:
            raise ValueError("verified receipt request inventory drifted from the schedule")
        cycle = verify_freight_cycle(exchanges, prelaunch_digest=seal, plan=plan)
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            raise ValueError("verified receipt record missing")
        expected = dict(
            phase,
            cycle=cycle,
            before_save_sha256=sha256(directory / "session-before.sav"),
            after_save_sha256=sha256(directory / "after.sav"),
        )
        # JSON round-trip both sides: the retained record stores serialized
        # arrays where the recomputed receipts hold python tuples; identity
        # semantics (not container type) define the replay match.
        if json.loads(receipt_path.read_text()) != json.loads(json.dumps(expected)):
            raise ValueError("retained freight receipt replay mismatch")
        return dict(verification="RECEIPT_VERIFIED", receipt=expected)
    if result["status"] == "FAILED_CLEANUP":
        # A genuine cleanup failure necessarily leaves cleanup incomplete. It is
        # preserved as failed evidence and can never replay as a verified
        # receipt; the dedicated arm avoids mislabelling it as a halted phase.
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status="FAILED_CLEANUP",
            exchanges=result.get("exchanges", []),
            error=result.get("error") or "cleanup was not certified",
            cleanup_complete=False,
            cleanup_error=cleanup_record.get("cleanup_error"),
            cleanup_verification_error=cleanup_record.get("verification_error"),
        )
    if result["status"] in ("PHASE_HALTED_PREFIX_PRESERVED", "FAILED"):
        if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED" and (
            phase["verification"] != "PARTIAL_EXECUTION_EVIDENCE"
            or not isinstance(halt_record, dict)
            or len(result.get("exchanges", [])) != len(phase["completed"])
            or (
                phase["failed"] is not None
                and phase["failed"].get("label") != halt_record.get("label")
            )
        ):
            raise ValueError("halted phase evidence contradicts its retained record")
        if not cleanup_complete:
            raise ValueError("halted attempt cleanup incomplete")
        return dict(
            verification=(
                "PHASE_HALTED_EVIDENCE_PRESERVED"
                if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
                else "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
            ),
            result_status=result["status"],
            exchanges=result.get("exchanges", []),
            failed=phase["failed"],
            pending=phase["pending"],
            error=result.get("error") or (phase["failed"] or {}).get("error"),
        )
    return dict(
        verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
        result_status=result.get("status", "UNKNOWN"),
        error=result.get("error"),
    )


def staged_authorization_payload_digest(directory: Path) -> str:
    """The RFC-canonical digest of the candidate's own authorization payload.

    The exact operator-signing message, rebuildable offline from the staged
    prelaunch record alone through the shared D2 authorization builder.
    """
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    return hashlib.sha256(
        canonical_authorization_bytes(authorization_payload(metadata, seal))
    ).hexdigest()


def exit_status(result: dict) -> int:
    """The runner CLI exit code: zero only for the final validated success.

    A stale ``verified`` flag, a non-success terminal status, or an
    uncertified cleanup all deny zero.
    """
    verified = (
        result.get("verified") is True
        and result.get("status") == "NATIVE_FREIGHT_VERIFIED"
        and result.get("cleanup_complete") is True
    )
    return 0 if verified else 1


def verdict_exit_status(verdict: dict) -> int:
    """The read-only verifier CLI exit code: zero only for RECEIPT_VERIFIED."""
    return 0 if verdict.get("verification") == "RECEIPT_VERIFIED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prerequisite", type=Path, default=PINNED_PREREQUISITE)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_candidate(directory, prerequisite=args.prerequisite)
        preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        preflight(reopen_candidate(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        verdict = verify_freight_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
        raise SystemExit(verdict_exit_status(verdict))
    else:
        read_prelaunch(directory)  # fail fast on any drifted prelaunch record
        result = asyncio.run(
            execute_freight_attempt(
                reopen_candidate(directory),
                FreightNativeBackend(authorized_one_launch=True),
            )
        )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_status(result))


if __name__ == "__main__":
    main()
