"""D4 native road/station/depot corridor construction proof preparation.

Stages the reviewed Seed 17 corridor as one fresh save-load candidate that
reuses the proven D2/D3 native machinery exactly: the same operator
authorization, runtime freeze, dependency identity, immutable launch
environment, one-shot claim, signed replay and cleanup boundaries. No second
security framework is introduced; the shared machinery is parameterized at
call time (closure root, prerequisite lineage, sealed corridor pins) so the
D3 ceremony is untouched.

The staged candidate ``D4-CORRIDOR-1`` binds the compiled ``p08-terraform``
levelling lineage byte-exactly:

1. Its source world is the replay-verified retained ``after.sav`` of the
   consuming D3 terraforming candidate (``D3-TERRAFORMING-1``) — the corridor
   tiles' post-D3 geometry is the compiled final levelling projection whose
   native readbacks reconciled 27/27 at zero mismatch.
2. Its schedule is seven bounded native road ops: run A, the compiled 17-tile
   run B split into its two contiguous collinear ``BuildRoadFull`` segments,
   the historical perpendicular corner ``BuildRoad`` join, two
   ``BuildRoadStation`` truck stops fronting the run ends and one
   ``BuildRoadDepot`` depoting the run A end, plus one corridor ``route`` read.
   OpenTTD's scripted ``BuildRoadFull`` builds both straight road bits at both
   span endpoints, so the two collinear run-B segments auto-connect; the
   perpendicular corner does not auto-connect and remains its own scheduled
   op. The geometry stays two straight runs joined by one corner.
3. Wire contract v4: every op runs inspect → command → independent read (the
   command presenting the prelaunch seal, the read the admitted intent
   digest), and the final route read is pure observation of the ordered
   witness path — which only ever proves the connected, usable infrastructure
   the constructed world actually holds.

Road buildability is never inferred here: catchment/acceptance re-checks and
every structural admission happen natively at construction admission through
``app.simulation.openttd.corridor_construction.admit_corridor``.

Nothing in this module launches OpenTTD, connects to any port, or mutates any
tile; the staged pre-launch claim is never written, so nothing can launch
until a separate operator authorization creates it.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import struct
import zipfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.planning.p08_road import find_depot
from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
from app.simulation.openttd.corridor_construction import (
    MAX_CORRIDOR_RESPONSE_BYTES,
    MAX_FULL_SPAN,
    CorridorIntent,
    CorridorReadback,
    CorridorRequest,
    admit_corridor,
    corridor_phase_outcome,
    verify_corridor,
    verify_corridor_route,
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
    CENSUS_DIRECTORY,
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
    verify_directory_manifest,
)
from app.simulation.openttd.proof.terrain_clearing import (
    reopen as reopen_candidate,
)
from app.simulation.openttd.proof.terrain_terraform_native import (
    D3_PRELAUNCH_SCHEMA,
    MILESTONE_TERRAFORMING,
    ROAD_PROOF_COMPANY_READY_MARKER,
    WELCOME_ORDER,
    chain_world_welcome,
    compiled_levelling,
    plan_digest_of,
    prerequisite_chain_links,
    read_prelaunch,
    verify_terraform_attempt,
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
CORRIDOR_PACKAGE = PACKAGES / "d4_corridor_package"
AI_PACKAGE = PACKAGES / "road_company_package"
RETAINED_NETWORK_FACTS = SEED17_RUN / "network-facts-0.json"
D4_CLOSURE_ROOT = "app.simulation.openttd.proof.corridor_construction_native"

KIND = "corridor"
MILESTONE_CONSTRUCTION = "D4-CONSTRUCTION"
CORRIDOR_ATTEMPT = "D4-CORRIDOR-5"

# Versioned prelaunch evidence for the D4 native candidate (additive sister
# record of the shared prelaunch machinery; the claim, launch boundary, freeze
# and replay gates are the shared D2 implementations parameterized at call
# time).
D4_PRELAUNCH_SCHEMA = "d4-corridor-native-prelaunch-v1"
D4_PREREQUISITE_SCHEMA = "d4-native-prerequisite-attempt-v1"
D4_LAUNCH_CONSUMED_SCHEMA = "d4-native-launch-consumed"

# The corridor candidate's prerequisite lineage: the D3 terraforming attempt
# whose replay-verified retained after.sav is the staged source world. The
# receipt-bound digest is authoritative: the distinct after-diagnostic save is
# never an acceptable substitute.
PINNED_PREREQUISITE = Path(
    PROJECT / "artifacts/experiments/d3-terraform-native-candidate-1"
).resolve()
PINNED_PREREQUISITE_AFTER_SAVE = (
    "fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e"
)

# One per-operation native ceiling; every op is quoted against it natively at
# its own admission and the historical reference costs (road piece £71, truck
# stop £150, depot £375) stay controlled references, never authorization.
MAX_CORRIDOR_COST = 2000

# Scheduled road ops for fresh staging: run A, the two compiled run-B segments,
# the perpendicular corner join, both truck stops and the depot. The consumed
# attempts' 17-tile run B is staged as two contiguous collinear ``BuildRoadFull``
# segments so every op is quoted natively again at its own admission inside the
# unchanged per-operation ceiling. Scripted full runs build both straight road
# bits at both endpoints, so the collinear segments already connect; scheduling
# an interior join was the candidate-3 defect.
ROAD_OP_COUNT = 7

# Schedule-derivation version of the staged corridor plan. Version 3 is the
# current split-run-B derivation above; version 2 preserves the consumed
# ``D4-CORRIDOR-3`` record (which still scheduled the redundant interior join)
# and version 1 preserves the consumed ``D4-CORRIDOR-1`` record, both only so
# their read-only replays stay re-derivable. No fresh candidate may be staged
# from a v1/v2 derivation.
SCHEDULE_VERSION = 3

# Exchange accounting per scheduled op: inspect + command + independent read,
# plus the one final route read purely after the phase completes.
PLANNED_CORRIDOR_REQUESTS = ROAD_OP_COUNT * 3 + 1
# Dispatcher slack on top of the 22 planned exchanges; the package's own
# request cap is the same 28.
CORRIDOR_REQUEST_BUDGET = PLANNED_CORRIDOR_REQUESTS + 6

# The staged running AI announces its own readiness marker (identical to D2/D3).
CORRIDOR_READY_MARKER = "D4_READY"

CORRIDOR_WIDTH = 256


class CorridorStagingError(ClearingStagingError):
    """Offline D4 staging or pin derivation failed; nothing was launched."""


def staged_composition() -> tuple[dict[str, bytes], str, int]:
    """Byte-exact save-restore composition for the D4 corridor candidate.

    The retained staged ``info.nut`` announces the save's stored GameScript
    identity (name/version); the staged main is the bounded corridor handler
    with the save-restore bridge class (NetworkFreightProof) defined inline
    after the proof class. No separate identity.nut is needed.
    """
    with zipfile.ZipFile(SEED17_RUN / "frozen-source.zip") as archive:
        info_bytes = archive.read("staged/info.nut")
    text = info_bytes.decode()
    create_instance = re.search(r'CreateInstance\(\)\s*\{\s*return\s+"([^"]+)"', text)
    version = re.search(r"GetVersion\(\)\s*\{\s*return\s+(\d+)", text)
    if create_instance is None or version is None or SOURCE_SAVE_GS_NAME not in text:
        raise CorridorStagingError("retained staged GameScript identity incomplete")
    main_text = (CORRIDOR_PACKAGE / "main.nut").read_text()
    bridge_class = create_instance.group(1)
    if f"class {bridge_class} extends D4CorridorProof" not in main_text:
        raise CorridorStagingError(
            f"staged main.nut missing required bridge class {bridge_class}"
        )
    return (
        {
            "info.nut": info_bytes,
            "main.nut": (CORRIDOR_PACKAGE / "main.nut").read_bytes(),
        },
        bridge_class,
        int(version.group(1)),
    )


# --- Sealed anchor-coverage evidence for the two corridor stops -------------


@lru_cache(maxsize=1)
def _retained_network_facts() -> dict:
    """Receipt-bound re-parse of the sealed network facts; read-only."""
    verify_directory_manifest(CENSUS_DIRECTORY)
    return json.loads(RETAINED_NETWORK_FACTS.read_text())


@lru_cache(maxsize=1)
def coverage_pins() -> tuple[dict[str, dict], ...]:
    """The anchor coverage facts of the two corridor stop pins.

    Pick-up coverage for tile 45748 (industry 0, cargo 1, producer 1) and
    delivery coverage for tile 50351 (industry 1, cargo 1). These are planning
    evidence only: native catchment and acceptance re-checks happen at
    construction admission, and a zero-cost native refusal there is terminal.
    """
    facts = _retained_network_facts()
    anchors = {45748: "pickup", 50351: "delivery"}
    pins: dict[str, dict] = {}
    for entry in facts.get("coverage", ()):
        role = anchors.get(entry.get("tile_id"))
        if role is None or entry.get("role") != role or entry.get("industry_covered") is not True:
            continue
        pins[f"{role}-{entry.get('tile_id')}-{entry.get('cargo_id')}"] = dict(
            tile=entry.get("tile_id"),
            role=role,
            industry_id=entry.get("industry_id"),
            cargo_id=entry.get("cargo_id"),
            industry_covered=entry.get("industry_covered"),
            producer_count=entry.get("producer_count"),
            acceptance_eighths=entry.get("acceptance_eighths"),
        )
    if len(pins) != len(anchors) or any(
        f"{role}-{tile}-{1}" not in pins for tile, role in anchors.items()
    ):
        raise CorridorStagingError("corridor stop anchor coverage pins are incomplete")
    return tuple(pins[k] for k in sorted(pins))


# --- The compiled corridor schedule (sealed, deterministic) ------------------


@lru_cache(maxsize=1)
def corridor_facts() -> dict:
    """Derive the staged corridor's bounded facts from the pinned compile.

    Deterministic offline derivation over the compiled levelling proposal
    (pinned together with the D3 module) and the sealed census document:
    the ordered witness path, the two straight runs, the single corner
    between them and the depot-adjacent interior entry, with the post-D3
    floor facts reconstructed from the compiled final shifts. Any drift in
    the compiled shape refuses staging before any run.
    """
    _proposal, doc, compiled_spec = compiled_levelling()
    corridor = tuple(int(tile) for tile in _proposal.corridor)
    width = CORRIDOR_WIDTH
    tiles = {int(t.tile_id): t for t in doc.tiles}
    if len(corridor) > 49:
        raise CorridorStagingError("the corridor witness path exceeds the staged schedule bounds")
    if len(set(corridor)) != len(corridor):
        raise CorridorStagingError("corridor witness path repeats a tile")
    for a, b in zip(corridor, corridor[1:]):
        if abs(tiles[a].x - tiles[b].x) + abs(tiles[a].y - tiles[b].y) != 1:
            raise CorridorStagingError("corridor witness path is not tile-adjacent")

    # Post-D3 floor facts: every compiled original clear (the corridor trees)
    # reads tree-free, every compiled raise shift's final geometry is honored,
    # in last-in-order.
    post = dict(tiles)
    for op in compiled_spec.ops:
        if op.kind == "clear":
            tile_id = int(op.tile_id)
            if tile_id not in post:
                raise CorridorStagingError("compiled clear target absent from the census")
            post[tile_id] = post[tile_id].model_copy(update={"tree": False})
            continue
        for shift in op.to_payload()["shifts"]:
            tile_id = int(shift["tile"])
            if tile_id not in post:
                raise CorridorStagingError("compiled raise tile absent from the census")
            post[tile_id] = post[tile_id].model_copy(
                update={"min_height": shift["after_min"], "slope": shift["after_slope"]}
            )

    interior = corridor[1:-1]
    runs: list[list[int]] = []
    current: list[int] = [interior[0]]
    axis: str | None = None
    for a, b in zip(interior, interior[1:]):
        kind = "x" if tiles[a].y == tiles[b].y else "y"
        if axis is not None and kind != axis:
            runs.append(current)
            current = [b]
        else:
            current.append(b)
        axis = kind
    runs.append(current)
    if len(runs) != 2:
        raise CorridorStagingError(
            "the staged corridor must be two straight runs joined by one corner"
        )
    run_a, run_b = (list(run) for run in runs)
    corner = (run_a[-1], run_b[0])
    if (
        abs(tiles[corner[0]].x - tiles[corner[1]].x)
        + abs(tiles[corner[0]].y - tiles[corner[1]].y)
        != 1
    ):
        raise CorridorStagingError("the corner endpoints are not adjacent")
    for run in (run_a, run_b):
        span = len(run) - 1
        if not 1 <= span <= MAX_FULL_SPAN:
            raise CorridorStagingError("a straight run exceeds the bounded span")
    if min(corridor) < 0 or max(corridor) > 0xFFFF:
        raise CorridorStagingError("corridor pins exceed the 256x256-safe tile bound")

    depot = find_depot(corridor, post, width)
    if depot is None:
        raise CorridorStagingError("no depot-adjacent interior exists for the corridor")
    depot_facility = dict(
        tile_id=int(depot.tile_id),
        front_tile_id=int(depot.front_tile_id),
        orientation=depot.orientation,
    )
    if depot_facility["tile_id"] in corridor:
        raise CorridorStagingError("the depot pin overlaps the corridor footprint")
    if int(depot_facility["front_tile_id"]) not in interior:
        raise CorridorStagingError("the depot front is not a corridor interior tile")
    a, b = tiles[depot_facility["tile_id"]], tiles[depot_facility["front_tile_id"]]
    if abs(a.x - b.x) + abs(a.y - b.y) != 1:
        raise CorridorStagingError("the depot front is not adjacent to the depot pin")
    return dict(
        corridor=corridor,
        width=width,
        run_a=run_a,
        run_b=run_b,
        corner=corner,
        depot=depot_facility,
        stops=(corridor[0], corridor[-1]),
        fronts=(corridor[1], corridor[-2]),
    )


def corridor_schedule_v2() -> list[dict]:
    """The consumed candidate-3 derivation: eight ops with an interior join.

    This derivation is retained unchanged so the read-only replay of the
    consumed, failed-cleanup ``D4-CORRIDOR-3`` record remains re-derivable. It
    is not a fresh-staging derivation: its interior join is redundant because
    the two collinear full-run endpoints already carry connecting road bits.
    """
    facts = corridor_facts()
    corridor = facts["corridor"]
    run_a, run_b = facts["run_a"], facts["run_b"]
    corner = facts["corner"]
    depot = facts["depot"]
    split = (len(run_b) + 1) // 2
    segment_a, segment_b = run_b[:split], run_b[split:]
    if len(segment_a) < 2 or len(segment_b) < 2:
        raise CorridorStagingError("a run-B segment is too short to schedule")
    if segment_a + segment_b != run_b:
        raise CorridorStagingError("the run-B segments do not reassemble the compiled run")
    interior = (segment_a[-1], segment_b[0])
    if segment_b[0] - segment_a[-1] not in (-1, 1, -CORRIDOR_WIDTH, CORRIDOR_WIDTH):
        raise CorridorStagingError("the interior join endpoints are not adjacent")
    if (run_a[-1], run_b[0]) != tuple(corner):
        raise CorridorStagingError("the corner join drifted from the compiled corner")
    schedule = [
        dict(
            kind="full",
            index=0,
            start=run_a[0],
            end=run_a[-1],
            run_len=len(run_a),
            tiles=list(run_a),
        ),
        dict(
            kind="full",
            index=1,
            start=segment_a[0],
            end=segment_a[-1],
            run_len=len(segment_a),
            tiles=list(segment_a),
        ),
        dict(
            kind="full",
            index=2,
            start=segment_b[0],
            end=segment_b[-1],
            run_len=len(segment_b),
            tiles=list(segment_b),
        ),
        dict(
            kind="road",
            index=3,
            start=interior[0],
            end=interior[1],
            run_len=2,
            tiles=list(interior),
        ),
        dict(
            kind="road",
            index=4,
            start=corner[0],
            end=corner[1],
            run_len=2,
            tiles=list(corner),
        ),
        dict(
            kind="station",
            index=5,
            tile=int(corridor[0]),
            front=int(corridor[1]),
            stop_role="pickup",
        ),
        dict(
            kind="station",
            index=6,
            tile=int(corridor[-1]),
            front=int(corridor[-2]),
            stop_role="delivery",
        ),
        dict(
            kind="depot",
            index=7,
            tile=depot["tile_id"],
            front=depot["front_tile_id"],
            orientation=depot["orientation"],
        ),
    ]
    indexes = [entry["index"] for entry in schedule]
    if indexes != list(range(8)):
        raise CorridorStagingError("scheduled operation order drifted")
    for entry in schedule:
        run_len = entry.get("run_len")
        if run_len is not None and not 1 <= run_len - 1 <= MAX_FULL_SPAN:
            raise CorridorStagingError("a scheduled road op exceeds the bounded span")
    for entry in schedule[:5]:
        if (
            entry["start"] is None
            or entry["start"] < 0
            or entry["end"] is None
            or entry["end"] > 0xFFFF
        ):
            raise CorridorStagingError("scheduled road operation pins exceed the tile bound")
    return schedule


def corridor_schedule() -> list[dict]:
    """The current staged operation schedule: seven bounded road ops.

    Run A first, then the compiled run B split into two contiguous collinear
    ``BuildRoadFull`` segments (the first carries ``ceil(n/2)`` tiles so a
    fresh native quote prices a bounded span inside the per-op ceiling). The
    scripted full build gives both straight road bits at both span endpoints,
    so these collinear segments auto-connect; no interior join op is needed.
    Only the perpendicular corner between run A and run B remains a separate
    ``BuildRoad`` op. Then both truck stops front the run ends and the depot
    backs the run-A end. The route read is pure observation after the phase.
    """
    facts = corridor_facts()
    corridor = facts["corridor"]
    run_a, run_b = facts["run_a"], facts["run_b"]
    corner = facts["corner"]
    depot = facts["depot"]
    split = (len(run_b) + 1) // 2
    segment_a, segment_b = run_b[:split], run_b[split:]
    if len(segment_a) < 2 or len(segment_b) < 2:
        raise CorridorStagingError("a run-B segment is too short to schedule")
    if segment_a + segment_b != run_b:
        raise CorridorStagingError("the run-B segments do not reassemble the compiled run")
    if segment_b[0] - segment_a[-1] not in (
        -1,
        1,
        -CORRIDOR_WIDTH,
        CORRIDOR_WIDTH,
    ):
        raise CorridorStagingError("the run-B segments are not adjacent")
    if (run_a[-1], run_b[0]) != tuple(corner):
        raise CorridorStagingError("the corner join drifted from the compiled corner")
    schedule = [
        dict(
            kind="full",
            index=0,
            start=run_a[0],
            end=run_a[-1],
            run_len=len(run_a),
            tiles=list(run_a),
        ),
        dict(
            kind="full",
            index=1,
            start=segment_a[0],
            end=segment_a[-1],
            run_len=len(segment_a),
            tiles=list(segment_a),
        ),
        dict(
            kind="full",
            index=2,
            start=segment_b[0],
            end=segment_b[-1],
            run_len=len(segment_b),
            tiles=list(segment_b),
        ),
        dict(
            kind="road",
            index=3,
            start=corner[0],
            end=corner[1],
            run_len=2,
            tiles=list(corner),
        ),
        dict(
            kind="station",
            index=4,
            tile=int(corridor[0]),
            front=int(corridor[1]),
            stop_role="pickup",
        ),
        dict(
            kind="station",
            index=5,
            tile=int(corridor[-1]),
            front=int(corridor[-2]),
            stop_role="delivery",
        ),
        dict(
            kind="depot",
            index=6,
            tile=depot["tile_id"],
            front=depot["front_tile_id"],
            orientation=depot["orientation"],
        ),
    ]
    indexes = [entry["index"] for entry in schedule]
    if indexes != list(range(ROAD_OP_COUNT)):
        raise CorridorStagingError("scheduled operation order drifted")
    for entry in schedule:
        run_len = entry.get("run_len")
        if run_len is not None and not 1 <= run_len - 1 <= MAX_FULL_SPAN:
            raise CorridorStagingError("a scheduled road op exceeds the bounded span")
    for entry in schedule[:4]:
        if (
            entry["start"] is None
            or entry["start"] < 0
            or entry["end"] is None
            or entry["end"] > 0xFFFF
        ):
            raise CorridorStagingError("scheduled road operation pins exceed the tile bound")
    return schedule


def corridor_schedule_v1() -> list[dict]:
    """The historical derivation of the consumed ``D4-CORRIDOR-1`` schedule.

    The consumed candidate staged the compiled run B as ONE 17-tile full op
    before its admission refusal; its retained record binds that v1 plan
    digest. This derivation is compiled from the same pinned corridor facts —
    never hand-retold — and exists only so ``verify_corridor_attempt`` keeps
    re-deriving the consumed candidate's binding; fresh staging always carries
    the current v3 schedule (``plan_policy()`` pins ``schedule_version``).
    """
    facts = corridor_facts()
    corridor = facts["corridor"]
    run_a, run_b = facts["run_a"], facts["run_b"]
    corner = facts["corner"]
    depot = facts["depot"]
    schedule = [
        dict(
            kind="full",
            index=0,
            start=run_a[0],
            end=run_a[-1],
            run_len=len(run_a),
            tiles=list(run_a),
        ),
        dict(
            kind="full",
            index=1,
            start=run_b[0],
            end=run_b[-1],
            run_len=len(run_b),
            tiles=list(run_b),
        ),
        dict(
            kind="road",
            index=2,
            start=corner[0],
            end=corner[1],
            run_len=2,
            tiles=list(corner),
        ),
        dict(
            kind="station",
            index=3,
            tile=int(corridor[0]),
            front=int(corridor[1]),
            stop_role="pickup",
        ),
        dict(
            kind="station",
            index=4,
            tile=int(corridor[-1]),
            front=int(corridor[-2]),
            stop_role="delivery",
        ),
        dict(
            kind="depot",
            index=5,
            tile=depot["tile_id"],
            front=depot["front_tile_id"],
            orientation=depot["orientation"],
        ),
    ]
    indexes = [entry["index"] for entry in schedule]
    if indexes != list(range(6)):
        raise CorridorStagingError("scheduled operation order drifted")
    first = schedule[0]
    if first["start"] is None or first["start"] < 0 or first["end"] > 0xFFFF:
        raise CorridorStagingError("scheduled operation pins exceed the tile bound")
    return schedule


def staged_plan_schedule(plan: dict) -> list[dict]:
    """The staged schedule a plan record binds its schedule digest to.

    Fresh v3 records bind the current split-run-B derivation; consumed v2 and
    v1 records bind their historical derivations exactly. Any other versioning
    is a refused plan record, never a best-effort guess.
    """
    version = plan.get("schedule_version", 1)
    if version == SCHEDULE_VERSION:
        return corridor_schedule()
    if version == 2:
        return corridor_schedule_v2()
    if version == 1:
        return corridor_schedule_v1()
    raise ValueError(f"plan record names an unknown corridor schedule version: {version}")


def route_policy() -> dict:
    """The staged corridor route read's pure-observation scope."""
    facts = corridor_facts()
    corridor = facts["corridor"]
    depot = facts["depot"]
    pins = {pin["tile"]: pin for pin in coverage_pins()}
    pickup = next(pin for pin in pins.values() if pin["tile"] == corridor[0])
    delivery = next(pin for pin in pins.values() if pin["tile"] == corridor[-1])
    return dict(
        witness_path=list(corridor),
        expected_pairs=len(corridor) - 1,
        pickup=int(corridor[0]),
        pickup_front=int(corridor[1]),
        delivery=int(corridor[-1]),
        delivery_front=int(corridor[-2]),
        depot=depot["tile_id"],
        depot_front=depot["front_tile_id"],
        depot_orientation=depot["orientation"],
        pickup_coverage=pickup,
        delivery_coverage=delivery,
        statement=(
            "the route read is pure observation: every adjacent pair along the "
            "ordered witness path joined by this company's road, both stops "
            "non-drive-through truck stops with valid station ids, and the depot "
            "joined to its pinned front; it never issues a build assertion"
        ),
    )


# --- Prerequisite-attempt source world ---------------------------------------


def prerequisite_binding(directories: Path) -> dict:
    """The fail-closed binding of the D3 terraforming attempt's after-save.

    The prerequisite must be the pinned, consumed, replay-verified D3
    terraforming attempt on the launch-capable lineage: its receipt survives
    full replay verification, its retained ``after.sav`` binds the pinned
    authoritative digest, and its own prerequisite chain is the completed D3
    clearing chain.
    """
    prerequisite = Path(directories).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise CorridorStagingError("the D4 prerequisite is not the pinned D3 attempt")
    if not prerequisite.is_dir() or any(part == ".." for part in prerequisite.parts):
        raise CorridorStagingError("prerequisite attempt directory is not a real directory")
    metadata = read_prelaunch(prerequisite)
    if metadata.get("schema") != D3_PRELAUNCH_SCHEMA:
        raise CorridorStagingError("prerequisite attempt is not the D3 native lineage")
    if metadata.get("kind") != "terraform" or metadata.get("milestone") != MILESTONE_TERRAFORMING:
        raise CorridorStagingError("prerequisite attempt is not the D3 terraforming phase")
    seal = sha256(prerequisite / "PRELAUNCH.json")
    if (prerequisite / "PRELAUNCH.sha256").read_text().strip() != seal:
        raise CorridorStagingError("prerequisite prelaunch seal mismatch")
    if metadata.get("attempt") != "D3-TERRAFORMING-1":
        raise CorridorStagingError("prerequisite attempt identity drifted")
    claim_path = prerequisite / "CLAIM.json"
    if not claim_path.is_file():
        raise CorridorStagingError("the prerequisite attempt was never consumed")
    claim = json.loads(claim_path.read_text())
    if claim.get("prelaunch_digest") != seal or claim.get("consumed") is not True:
        raise CorridorStagingError("the prerequisite attempt claim is incomplete")
    after_save = prerequisite / "after.sav"
    if not after_save.is_file():
        raise CorridorStagingError("the prerequisite attempt retained no after world state")
    save_digest = sha256(after_save)
    if save_digest != PINNED_PREREQUISITE_AFTER_SAVE:
        raise CorridorStagingError(
            "the prerequisite after-save digest is not the receipt-bound authoritative world"
        )
    receipt_path = prerequisite / "receipt.json"
    if not receipt_path.is_file():
        raise CorridorStagingError("the prerequisite attempt retained no receipt")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("after_save_sha256") != save_digest:
        raise CorridorStagingError("the prerequisite receipt does not bind its after save")
    verdict = verify_terraform_attempt(prerequisite)
    if verdict.get("verification") != "RECEIPT_VERIFIED":
        raise CorridorStagingError(
            "the prerequisite attempt replay is not a verified receipt: "
            f"{verdict.get('verification')}"
        )
    chain = prerequisite_chain_links(prerequisite)
    return dict(
        schema=D4_PREREQUISITE_SCHEMA,
        role="PREREQUISITE_ATTEMPT",
        retained_directory=str(prerequisite),
        save="after.sav",
        save_sha256=save_digest,
        qualified_save_sha256=None,
        prelaunch_digest=seal,
        attempt=metadata["attempt"],
        milestone=metadata.get("milestone"),
        expected_welcome=metadata["world"]["expected_welcome"],
        cleared_chain_tiles=sorted(
            link["target_tile"] for link in chain if link["kind"] == "clear"
        ),
        verification=(
            "full replay verification of the consumed prerequisite attempt "
            "receipt plus the pinned authoritative after-save digest"
        ),
    )


def stage_world(binding: dict, welcome: dict) -> dict:
    """The ``world`` metadata block for one D4 corridor candidate."""
    return dict(
        mode="PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD",
        retained_directory=binding["retained_directory"],
        source_save=binding["save"],
        save_sha256=binding["save_sha256"],
        qualified_save_sha256=binding.get("qualified_save_sha256"),
        expected_welcome=welcome,
    )


def source_save_path(world: dict) -> Path:
    """The staged world's source save file (the pinned retained artifact)."""
    return Path(world["retained_directory"]) / world["source_save"]


# --- Candidate planning facts -------------------------------------------------


def plan_policy() -> dict:
    """The corridor's authorized plan policy for the staged candidate.

    The scalar ``target_tile`` keeps the proven D2 authorization payload
    shape: the first scheduled run's start tile. The complete ordered
    operation scope joins the payload additively through the same shared
    authorization builder keys the D3 levelling milestone uses
    (``schedule`` + ``plan_digest``; the ``route`` scope stays a staged
    readback contract of its own). ``schedule_version`` names the schedule
    derivation the plan digest binds: the current split-run-B derivation for
    fresh staging, with the consumed candidate's v1 derivation retained for
    its read-only replay.
    """
    schedule = corridor_schedule()
    route = route_policy()
    if schedule[0]["kind"] != "full" or schedule[0]["index"] != 0:
        raise CorridorStagingError("the staged schedule must begin with run A")
    commands = (
        "GSRoad.BuildRoadFull",
        "GSRoad.BuildRoad",
        "GSRoad.BuildRoadStation",
        "GSRoad.BuildRoadDepot",
    )
    if any(entry["kind"] not in ("full", "road", "station", "depot") for entry in schedule):
        raise CorridorStagingError("a scheduled operation carries an unknown kind")
    return dict(
        company=0,
        target_tile=int(schedule[0]["start"]),
        max_cost=MAX_CORRIDOR_COST,
        command=" + ".join(commands),
        stale_rule=(
            "re-observe every pin of each op immediately before admission; "
            "any mismatch stops the phase without any command and preserves "
            "the verified prefix"
        ),
        identity=(
            "wire contract v4: the command request presents the prelaunch "
            "seal the inspect latched; the independent verification read "
            "presents the admitted intent digest, and the final route read "
            "carries the prelaunch seal as pure observation"
        ),
        schedule=schedule,
        plan_digest=plan_digest_of(schedule),
        schedule_version=SCHEDULE_VERSION,
        route=route,
        prerequisite_world=dict(
            schema=D4_PREREQUISITE_SCHEMA,
            statement=(
                "the corridor candidate's source world is the completed D3 "
                "levelling lineage: every corridor tile must read classified "
                "CLEAR unowned flat ground at native admission time, with "
                "historical costs kept as controlled references only"
            ),
        ),
    )


def budgets() -> dict:
    """The staged budget table for the corridor candidate.

    ``road_ops`` and the request accounting stay bound to the staged schedule
    derivation; there is deliberately no aggregate phase-spending budget — the
    per-operation ``max_cost`` ceiling remains the only cost contract.
    """
    return dict(
        launches=1,
        connection_attempts=1,
        requests=CORRIDOR_REQUEST_BUDGET,
        real_clears=0,
        real_raises=0,
        road_ops=len(corridor_schedule()),
        gsadmin_bytes=1450,
        response_bytes=640,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        total_seconds=900,
    )


def expected_readback_policy() -> dict:
    """The receipt contract's observable readback story for the corridor."""
    return dict(
        before=(
            "per op: inspect returns READY with the op's own admission "
            "pre-state (roadless unowned run, or company-road join endpoints "
            "with no link, or unplanned footprint fronting the company road) "
            "and a positive tested quote within the ceiling"
        ),
        execution=(
            "the command request presents the prelaunch seal; the handler "
            "re-observes the whole admission, re-quotes equal, and executes "
            "the single native build command exactly once"
        ),
        after=(
            "per op: the independent intent-scoped read returns READ at the "
            "observed post-state (endpoint ownership/road/path summary or "
            "the exact stop/depot footprint vs its front)"
        ),
        route=(
            "the final route read observes the ordered witness path: every "
            "adjacent pair joined by company road, both stops classified "
            "truck stops with valid station ids, the depot joined to its "
            "pinned front; no build assertion follows from it"
        ),
        receipt=(
            "plan-bound only after the execution result and independent "
            "readback agree per operation, in execution order, with the "
            "route receipt verified last"
        ),
    )


def attempt_name() -> str:
    """The candidate's one attempt name, bound to its own staged scope."""
    return CORRIDOR_ATTEMPT


# --- Candidate staging ---------------------------------------------------------


def prepare_candidate(
    directory: Path, *, prerequisite: Path = PINNED_PREREQUISITE
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise CorridorStagingError("the staged world requires the pinned D3 prerequisite")
    links = prerequisite_chain_links(prerequisite)
    cleared_tiles = {link["target_tile"] for link in links if link["kind"] == "clear"}
    _, _doc, compiled_spec = compiled_levelling()
    compiled = {int(op.tile_id) for op in compiled_spec.ops if op.kind == "clear"}
    if cleared_tiles != compiled:
        raise CorridorStagingError(
            "the prerequisite chain does not bind the compiled clearing operations"
        )
    schedule = corridor_schedule()
    if (
        len(schedule) != ROAD_OP_COUNT
        or [entry["index"] for entry in schedule] != list(range(ROAD_OP_COUNT))
        or plan_policy()["schedule_version"] != SCHEDULE_VERSION
    ):
        raise CorridorStagingError("the staged corridor schedule drifted")
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise CorridorStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    welcome = chain_world_welcome(prerequisite)
    binding = prerequisite_binding(prerequisite)
    if binding["cleared_chain_tiles"] != sorted(compiled):
        raise CorridorStagingError("prerequisite chain clearing inventory drifted")
    world = stage_world(binding, welcome)
    plan = plan_policy()
    if sha256(source_save_path(world)) != world["save_sha256"]:
        raise CorridorStagingError("staged world source save digest mismatch")
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
        for source in (CORRIDOR_PACKAGE, AI_PACKAGE):
            for path in sorted(source.glob("*.nut")):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(path): sha256(path)
                for path in sorted(workspace.root.rglob("*"))
                if path.is_file() and path.name != ".admin-secret"
            }
        )
        # The exact runtime closure of the D4 execution path (including the
        # offline corridor schedule chain) and the exact installed dependency
        # bytes join the shared source_freeze() contract through the same
        # parameterized D2 machinery — never weakening it.
        frozen.update(d2_source_closure(D4_CLOSURE_ROOT))
        frozen.update(d2_dependency_inventory(D4_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D4_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_CONSTRUCTION,
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
                    "D4 corridor handler runs as the retained CreateInstance subclass"
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
                "app.simulation.openttd.proof.corridor_construction_native",
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
                source=CENSUS_DIRECTORY.name,
                manifest_verified=True,
                statement=(
                    "plan derives from the compiled sealed levelling lineage's "
                    "corridor plus the deterministic depot entry over the "
                    "compiled post-D3 facts; the proposal, specification and "
                    "prerequisite after-save digests are pinned"
                ),
            ),
            environment=launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
        )
        metadata["prerequisite"] = dict(
            schema=D4_PREREQUISITE_SCHEMA,
            attempt=binding["attempt"],
            milestone=binding["milestone"],
            directory=binding["retained_directory"],
            prelaunch_sha256=binding["prelaunch_digest"],
            after_save_sha256=binding["save_sha256"],
            verification=binding["verification"],
        )
        if links:
            metadata["prerequisite_chain"] = links
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return prepared
    finally:
        reservation.close()


def preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal of the staged D4 candidate.

    Opens nothing, consumes nothing: the seal, the frozen runtime closure,
    the schedule pins, the route scope, the world binding and the endpoint
    reservation are re-checked exactly like the D3 preflight, with the D4
    lineage gates for the staged chain.
    """
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (
        directory / "PRELAUNCH.sha256"
    ).read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    if metadata.get("schema") != D4_PRELAUNCH_SCHEMA:
        raise ValueError("staged prelaunch record is not the D4 corridor lineage")
    verify_freeze(metadata["frozen"])
    require_frozen_d2_closure(metadata["frozen"], D4_CLOSURE_ROOT)
    require_frozen_d2_dependencies(metadata["frozen"], D4_CLOSURE_ROOT)
    plan = metadata["plan_policy"]
    if metadata["attempt"] != attempt_name():
        raise ValueError("staged attempt identity drifted from its own scope")
    staged = corridor_schedule()
    if plan["schedule"] != staged or plan["plan_digest"] != plan_digest_of(staged):
        raise ValueError(
            "staged corridor schedule drifted from the compiled derivation"
        )
    for entry in staged:
        if entry.get("run_len") is not None and not 1 <= entry["run_len"] <= MAX_FULL_SPAN + 1:
            raise ValueError("a scheduled run exceeds the bounded span")
        if entry["kind"] in ("station", "depot"):
            if entry["front"] is None or abs(
                (entry["tile"] % CORRIDOR_WIDTH) - (entry["front"] % CORRIDOR_WIDTH)
            ) + abs(
                (entry["tile"] // CORRIDOR_WIDTH) - (entry["front"] // CORRIDOR_WIDTH)
            ) != 1:
                raise ValueError("a scheduled site front is not adjacent")
    route = route_policy()
    if plan["route"] != route or route["expected_pairs"] != len(route["witness_path"]) - 1:
        raise ValueError("staged corridor route scope drifted from the compiled derivation")
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
        raise ValueError(
            "the staged prerequisite binding drifted from its replay-verified record"
        )
    if metadata["world"]["expected_welcome"] != retained_welcome():
        raise ValueError("retained world identity requirements drifted")
    world = metadata["world"]
    binding_gate = {"save_sha256": world["save_sha256"]}
    verify_staged_source_save(binding_gate, Path(metadata["workspace"]) / "source.sav")
    composition, _, _ = staged_composition()
    staged_identity = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME
    if staged_identity.joinpath("info.nut").read_bytes() != composition["info.nut"]:
        raise ValueError("staged GameScript identity drifted from the retained composition")
    if staged_identity.joinpath("main.nut").read_bytes() != composition["main.nut"]:
        raise ValueError("staged corridor handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- Wire protocol 4: secure session and one-launch backend --------------------


class CorridorSecureSession(SecureAdminSession):
    """Only the corridor operations extend the secure write policy."""

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = CorridorRequest.model_validate_json(decode_gamescript(frame[3:]))
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class CorridorNativeBackend(ClearingNativeBackend):
    """One-launch backend carrying the D4 lineage launch marker."""

    launch_marker_schema = D4_LAUNCH_CONSUMED_SCHEMA

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> CorridorSecureSession:
        """Bind the staged runtime's Admin listener to one owned secure session."""
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await CorridorSecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


async def exchange(session, request: CorridorRequest, directory: Path) -> CorridorReadback:
    """One sealed protocol-4 exchange; every frame and file is retained."""
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    async with asyncio.timeout(10):
        while True:
            chunk = await session.receive()
            if not chunk:
                raise ConnectionError("corridor proof stream disconnected")
            for kind, payload in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected corridor-proof packet")
                response = decode_gamescript(payload, max_payload_bytes=MAX_CORRIDOR_RESPONSE_BYTES)
                (directory / (request.request_id + "-response.json")).write_bytes(response)
                return CorridorReadback.parse_for(request, response)


def _pins(entry: dict, *, intent: CorridorIntent | None = None) -> dict:
    """The wire pins of one staged op (or of one admitted intent)."""
    if intent is not None:
        entry = {
            "kind": intent.kind,
            "start": intent.start,
            "end": intent.end,
            "tile": intent.tile,
            "front": intent.front,
        }
    kind = entry["kind"]
    if kind in ("full", "road", "spur"):
        return dict(start=entry["start"], end=entry["end"])
    return dict(tile=entry["tile"], front=entry["front"])


def _corridor_request(
    op: str,
    request_id: str,
    plan: str,
    company: int,
    max_cost: int,
    entry: dict,
    *,
    tiles: tuple[int, ...] | None = None,
) -> CorridorRequest:
    pins = dict(target=entry["kind"] if op in ("inspect", "read") else None)
    pins.update(_pins(entry))
    return CorridorRequest(
        op=op,
        request_id=request_id,
        plan=plan,
        company=company,
        max_cost=max_cost,
        tiles=tiles,
        **pins,
    )


async def execute_corridor_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt corridor phase (never offline).

    Bounded protocol-4 ceremony against an authorized backend seam: preflight,
    operator claim consumption, launch boundary, world identity, session
    saves, then the staged corridor schedule in order. Every operation runs
    the three bounded exchanges — inspection, the prelaunch-sealed build
    command, the intent-scoped independent verification read — admission
    latches per operation, execution happens exactly once per scheduled op,
    and the first verification failure halts the phase: earlier verified
    receipts are preserved, later operations never execute, and the world
    state after a failed attempt is explicitly uncertain (nothing compensates
    or retries). The corridor route read is pure observation, scheduled only
    after the phase completes.
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
    route_scope: dict = metadata["plan_policy"]["route"]
    max_cost = metadata["plan_policy"]["max_cost"]
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        requests=0,
        built_ops=[],
        last_status="NOT_DISPATCHED",
        command_accepted=False,
        state_changed=False,
        verified=False,
        status="FAILED",
        halt=None,
    )
    frames = []
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared, authorization=grant)
            result["native_launches"] = 1
            await wait_log(backend, prepared, CORRIDOR_READY_MARKER)
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
            attempts: list[tuple[str, dict]] = []
            for position, entry in enumerate(schedule):
                label = f"op-{entry['index']:02d}"
                evidence: dict[str, Any] = {}
                try:
                    before = await exchange(
                        session,
                        _corridor_request(
                            "inspect",
                            f"inspect-{position:02d}",
                            seal,
                            0,
                            max_cost,
                            entry,
                        ),
                        directory,
                    )
                    result["requests"] += 1
                    evidence["before"] = before
                    write_json(
                        directory / f"corridor-{position:02d}-before.json",
                        before.model_dump(mode="json"),
                    )
                    intent = admit_corridor(
                        before,
                        prelaunch_digest=seal,
                        source_save_digest=before_save,
                        staged_run_len=entry.get("run_len"),
                        max_cost=max_cost,
                    )
                    write_json(
                        directory / f"corridor-{position:02d}-intent.json",
                        intent.model_dump(mode="json"),
                    )
                    evidence["intent"] = intent
                    if intent.kind not in ("full", "road", "station", "depot"):
                        raise ValueError(
                            "dispatch refused: the intent carries no admissible command"
                        )
                    result["dispatch_state"] = "DISPATCHED_UNKNOWN"
                    result["dispatched_op"] = label
                    built = await exchange(
                        session,
                        _corridor_request(
                            intent.kind,
                            f"{intent.kind}-{position:02d}",
                            intent.prelaunch_digest,
                            intent.company,
                            intent.max_cost,
                            dict(entry, **{"kind": intent.kind}),
                        ),
                        directory,
                    )
                    result["requests"] += 1
                    result["dispatch_state"] = "CONFIRMED"
                    result["last_status"] = built.status
                    evidence["built"] = built
                    write_json(
                        directory / f"corridor-{position:02d}-built.json",
                        built.model_dump(mode="json"),
                    )
                    independent = await exchange(
                        session,
                        _corridor_request(
                            "read",
                            f"confirm-{position:02d}",
                            intent.digest,
                            intent.company,
                            intent.max_cost,
                            dict(entry, **{"kind": intent.kind}),
                        ),
                        directory,
                    )
                    result["requests"] += 1
                    evidence["independent"] = independent
                    write_json(
                        directory / f"corridor-{position:02d}-independent.json",
                        independent.model_dump(mode="json"),
                    )
                    verify_corridor(intent, before, built, independent)
                    attempts.append((label, evidence))
                    result["built_ops"].append(label)
                    result["command_accepted"] = True
                    result["state_changed"] = True
                except Exception as error:
                    attempts.append((label, evidence))
                    result["halt"] = dict(
                        label=label, error=type(error).__name__ + ": " + str(error)
                    )
                    break
            phase = corridor_phase_outcome(attempts)
            result["phase"] = phase
            if phase["verification"] == "PHASE_COMPLETE":
                if len(attempts) != len(schedule):
                    raise ValueError("phase completion evidence drifted from the staged schedule")
                route = await exchange(
                    session,
                    CorridorRequest(
                        op="route",
                        request_id="route-00",
                        plan=seal,
                        company=0,
                        max_cost=0,
                        tiles=tuple(route_scope["witness_path"]),
                    ),
                    directory,
                )
                result["requests"] += 1
                write_json(
                    directory / "corridor-route-read.json",
                    route.model_dump(mode="json"),
                )
                route_receipt = verify_corridor_route(
                    route,
                    prelaunch_digest=seal,
                    expected_pairs=int(route_scope["expected_pairs"]),
                    expected_path=tuple(route_scope["witness_path"]),
                )
                result["route"] = route_receipt
                after_save = await save(backend, prepared, "after")
                write_json(
                    directory / "receipt.json",
                    dict(
                        phase,
                        route=route_receipt,
                        before_save_sha256=before_save,
                        after_save_sha256=after_save,
                    ),
                )
                result["verified"] = True
                result["status"] = "NATIVE_CORRIDOR_VERIFIED"
            else:
                result["status"] = "PHASE_HALTED_PREFIX_PRESERVED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if result.get("dispatch_state") in ("DISPATCHED_UNKNOWN", "CONFIRMED"):
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
            if result["status"] == "NATIVE_CORRIDOR_VERIFIED":
                result["verified"] = False
                result["status"] = "FAILED"
                result["error"] = (
                    "ValueError: retained script log health findings deny the verified receipt"
                )
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_CORRIDOR_VERIFIED":
                result["verified"] = False
                result["status"] = "FAILED"
                result["error"] = (
                    "ValueError: native runtime exited abnormally after receipt "
                    f"(return code {result['returncode']})"
                )
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("cleanup incomplete")
            prepared.spec.workspace.close()
            cleanup["workspace_disposed"] = not prepared.spec.workspace.root.exists()
            cleanup["credential_removed"] = not prepared.key_path.exists()
        except Exception as error:
            cleanup["verification_error"] = str(error)
            result["status"] = "FAILED_CLEANUP"
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


# --- D4 phase replay verification ------------------------------------------------


def _scheduled_request_ids(schedule: list[dict]) -> set[str]:
    """Every request id the staged schedule can legitimately produce."""
    ids: set[str] = set()
    for position, entry in enumerate(schedule):
        ids.add(f"inspect-{position:02d}")
        ids.add(f"{entry['kind']}-{position:02d}")
        ids.add(f"confirm-{position:02d}")
    ids.add("route-00")
    return ids


def _parse_phase_frames(directory: Path):
    """Parse the retained frame stream of the owned secure session."""
    frames = json.loads((directory / "frames.json").read_text())
    outbound: list[bytes] = []
    replies: list[bytes] = []
    outbound_requests: list[CorridorRequest] = []
    request_positions: dict[bytes, int] = {}
    reply_positions: dict[bytes, int] = {}
    for index, (direction, frame_hex) in enumerate(frames):
        frame = bytes.fromhex(frame_hex)
        if direction == "outbound":
            outbound.append(frame)
            if frame[2] != ADMIN_GAMESCRIPT:
                continue
            payload = decode_gamescript(frame[3:])
            try:
                query = CorridorRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("outbound frame contains invalid CorridorRequest") from None
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                # The retained session stream also carries the handshake and
                # keepalive frames; only the gamescript exchanges are proof
                # material (the shared D2 chronology semantics).
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body, max_payload_bytes=MAX_CORRIDOR_RESPONSE_BYTES)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)
    return outbound, outbound_requests, replies, request_positions, reply_positions


def verify_corridor_attempt(directory: Path) -> dict:
    """Replay retained protocol-4 phase semantics; never trust a success label.

    The replay re-derives every retained fact independently: the operator
    authorization evidence, the staged corridor schedule, the captured
    session frames and every per-operation exchange, then re-verifies the
    whole phase (including the route receipt after it) with the production
    :func:`app.simulation.openttd.corridor_construction.corridor_phase_outcome`
    and :func:`verify_corridor_route`. A success label alone is never
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
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError("artifact manifest mismatch")
        if sha256(directory / name) != digest:
            raise ValueError("artifact manifest mismatch")
    if metadata.get("schema") != D4_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D4_PRELAUNCH_SCHEMA} lineage; no verified receipt is possible"
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
    plan = metadata["plan_policy"]
    schedule = staged_plan_schedule(plan)
    if plan["schedule"] != schedule or plan["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("staged corridor schedule drifted from the compiled derivation")
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["encrypted"] is not True or runtime["welcome"]["revision"] != "15.3":
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    outbound, outbound_requests, replies, request_positions, reply_positions = (
        _parse_phase_frames(directory)
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("corridor request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [CorridorRequest.model_validate_json(path.read_bytes()) for path in paths]
    for path, query in zip(paths, file_queries, strict=True):
        if query.request_id != path.name[: -len("-request.json")]:
            raise ValueError("retained request file identity does not match its payload")
    if len(outbound_requests) < len(file_queries):
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            command_accepted=result.get("command_accepted", False),
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
    unknown = {query.request_id for query in file_queries} - _scheduled_request_ids(schedule)
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
        request_id = path.name[: -len("-response.json")]
        try:
            readback = CorridorReadback.model_validate_json(path.read_bytes())
        except ValueError:
            continue
        if readback.request_id != request_id:
            raise ValueError("retained response file identity does not match its payload")
        if not (directory / (request_id + "-request.json")).is_file():
            raise ValueError("retained response file lacks its request")
    for raw, response in response_map.items():
        if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
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
    attempts: list[tuple[str, dict]] = []
    route_scope = plan["route"]
    route_position = None
    for position, entry in enumerate(schedule):
        label = f"op-{entry['index']:02d}"
        if halted_position is None and isinstance(halt_record, dict) and (
            halt_record.get("label") == label
        ):
            halted_position = position
        pending = halted_position is not None and position > halted_position
        evidence: dict[str, Any] = {}
        if not pending:
            for name in ("before", "intent", "built", "independent"):
                path = directory / f"corridor-{position:02d}-{name}.json"
                if not path.is_file():
                    continue
                try:
                    # The shared D2/D3 retained-file parsing semantics: both
                    # evidence file families are `Contract` JSON documents.
                    # Strict contracts refuse raw text feeds (a str is no
                    # dict model) and JSON arrays cannot strict-coerce into
                    # the contract fields, so the retained bytes load
                    # through pydantic's own JSON parser — for the intent
                    # and the readback families alike. A file that does
                    # not parse is absent evidence (verified absence is
                    # the surrounding phase recomputation's own input,
                    # never a silent success).
                    if name == "intent":
                        evidence[name] = CorridorIntent.model_validate_json(path.read_bytes())
                    else:
                        evidence[name] = CorridorReadback.model_validate_json(path.read_bytes())
                except ValueError:
                    continue
            intent = evidence.get("intent")
            if intent is not None:
                if intent.prelaunch_digest != seal:
                    raise ValueError("an admitted intent does not bind its candidate seal")
                if intent.source_save_digest != sha256(directory / "session-before.sav"):
                    raise ValueError("an admitted intent does not bind the session-before save")
                if intent.kind != entry["kind"] or _pins(entry) != _pins(entry, intent=intent):
                    raise ValueError("an admitted intent drifted from the staged schedule")
                if intent.kind in ("full", "road"):
                    if intent.run_len != entry.get("run_len"):
                        raise ValueError("an admitted intent run length drifted")
                # Frame-boundity: each evidence model must be the digest of the
                # retained response its exchange produced.
                inspection = evidence.get("before")
                query = next(
                    (item for item in file_queries if item.request_id == f"inspect-{position:02d}"),
                    None,
                )
                raw = response_map.get(query.to_bytes()) if query is not None else None
                if raw is None:
                    raise ValueError("an admitted intent lacks its retained inspect exchange")
                if CorridorReadback.parse_for(query, raw).digest != intent.before_digest:
                    raise ValueError("retained admission evidence does not bind its exchange")
                if inspection is not None and inspection.digest != intent.before_digest:
                    raise ValueError("retained inspection evidence drifted from its exchange")
        attempts.append((label, evidence))
    route_query = next(
        (item for item in file_queries if item.request_id == "route-00"),
        None,
    )
    if route_query is not None:
        route_position = request_positions.get(route_query.to_bytes())
    phase = corridor_phase_outcome(attempts)
    cleanup_record = json.loads((directory / "cleanup.json").read_text())
    exit_codes = (result.get("returncode"), cleanup_record.get("returncode"))
    cleanup_complete = all(
        cleanup_record.get(name) is True
        for name in ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")
    )
    if any(code not in (None, 0) for code in exit_codes):
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status=result.get("status", "UNKNOWN"),
            error=result.get("error", "process exited abnormally"),
            exit_evidence=dict(returncode=exit_codes[0], cleanup_returncode=exit_codes[1]),
        )
    if result["status"] == "NATIVE_CORRIDOR_VERIFIED":
        if phase["verification"] != "PHASE_COMPLETE":
            raise ValueError("verified receipt contradicts its phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("verified receipt contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("verified receipt contradicts its launch/connection seal")
        if len(result.get("built_ops", [])) != len(schedule) or not cleanup_complete:
            raise ValueError("verified receipt cleanup or built inventory incomplete")
        if len(outbound_requests) != PLANNED_CORRIDOR_REQUESTS:
            raise ValueError("verified receipt request inventory drifted from the schedule")
        route_readback = None
        if route_query is not None:
            raw = response_map.get(route_query.to_bytes())
            if raw is not None:
                route_readback = CorridorReadback.parse_for(route_query, raw)
        if route_readback is None or route_position is None:
            raise ValueError("verified route evidence missing from the retained exchange")
        if route_position != max(request_positions.values()):
            raise ValueError("the route read is not the last scheduled exchange")
        route_receipt = verify_corridor_route(
            route_readback,
            prelaunch_digest=seal,
            expected_pairs=int(route_scope["expected_pairs"]),
            expected_path=tuple(route_scope["witness_path"]),
        )
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            raise ValueError("verified receipt record missing")
        expected = dict(
            phase,
            route=route_receipt,
            before_save_sha256=sha256(directory / "session-before.sav"),
            after_save_sha256=sha256(directory / "after.sav"),
        )
        # JSON round-trip both sides: the retained record stores serialized
        # arrays where the recomputed receipts hold python tuples; identity
        # semantics (not container type) define the replay match.
        if json.loads(receipt_path.read_text()) != json.loads(json.dumps(expected)):
            raise ValueError("retained corridor receipt replay mismatch")
        return dict(verification="RECEIPT_VERIFIED", receipt=expected)
    if result["status"] in ("PHASE_HALTED_PREFIX_PRESERVED", "FAILED", "FAILED_CLEANUP"):
        if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED" and (
            phase["verification"] != "PARTIAL_EXECUTION_EVIDENCE"
            or phase["failed"] is None
            or not isinstance(halt_record, dict)
            or phase["failed"].get("label") != halt_record.get("label")
            or len(result.get("built_ops", [])) != len(phase["completed"])
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
            completed=[receipt.get("kind") for receipt in phase["completed"]],
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
    """The runner CLI exit code: zero only for the verified native outcome."""
    return 0 if result.get("verified") is True else 1


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
        verdict = verify_corridor_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
    else:
        read_prelaunch(directory)  # fail fast on any drifted prelaunch record
        result = asyncio.run(
            execute_corridor_attempt(
                reopen_candidate(directory),
                CorridorNativeBackend(authorized_one_launch=True),
            )
        )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_status(result))


if __name__ == "__main__":
    main()
