"""The D5 corridor-extension-3 terrain survey native staging pipeline (offline
preparation only).

The halted ``D5-CORRIDOR-EXTENSION-1`` attempt (2026-10-29) proved live slope
9/8 at the predecessor's delivery-terrace stop; the terrain-aware recovery
design answers with a read-only instrument, the protocol-7 terrain survey
(``app.simulation.openttd.corridor_terrain_survey``, already review-verified
with its additive ``TerrainHandle`` inside the shipped ``d5_freight_package``).
The staging/claim machinery in ``corridor_freight_native`` stays plan-bound to
the D5 freight ``FreightPlan`` and the ``corridor_accept_survey_native``
pipeline to ``AcceptSurveyPlan``, so the terrain survey gets its own narrow
pipeline bound explicitly to ``TerrainSurveyPlan`` and the fixed
ten-exchange schedule of the
follow-up ``D5-CORRIDOR-EXTENSION-3-SURVEY-1`` attempt, reusing the proven
shared ceremony by import rather
than copy (the same pattern both sibling ceremonies use). This is not a
generic abstraction layer: terrain staging, preflight, sealing, execution and
replay keep both sibling pipelines untouched and cannot accept a
``FreightPlan`` or an ``AcceptSurveyPlan`` (disjoint wire schemas on all three
sessions refuse the foreign request before it reaches any handler).

The survey is strictly read-only: its schedule admits only the ``radius``,
``tile`` and ``accept`` observation ops (every mutation-capable freight op and
every protocol-6 survey op is outside the terrain contract entirely),
``max_cost`` is 0 on every exchange, funds are read back per exchange, and the
survey mutates nothing. The retained census grade of the pinned branch tiles
is hypothesis-grade only: a measured nonzero slope or an occupied tile is a
recorded FINDING of record, never normalized, never a refusal. Nothing here
launches OpenTTD, connects to a port, writes a claim or mutates any world or
retained artifact.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import struct
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
from app.simulation.openttd.corridor_accept_survey import FUNDS_AT_D4_CLOSE
from app.simulation.openttd.corridor_terrain_survey import (
    MAX_TERRAIN_REQUEST_BYTES,
    MAX_TERRAIN_RESPONSE_BYTES,
    PLANNED_TERRAIN_EXCHANGES,
    TERRAIN_ACCEPT_CONTROL_TILE,
    TERRAIN_ACCEPT_STOP_TILE,
    TERRAIN_CARGO_ID,
    TERRAIN_DELIVERY_TILE,
    TERRAIN_EXCHANGE_IDS,
    TERRAIN_OPS,
    TERRAIN_PICKUP_TILE,
    TERRAIN_REQUEST_BUDGET,
    TERRAIN_TILES,
    TerrainReadback,
    TerrainRequest,
    TerrainSurveyPlan,
    terrain_phase_outcome,
    terrain_survey_plan,
    verify_request_against_terrain_survey_plan,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.proof import corridor_construction_native as d4
from app.simulation.openttd.proof import corridor_freight_native as freight_native
from app.simulation.openttd.proof.classification_capture import script_log_health_findings
from app.simulation.openttd.proof.corridor_construction_native import (
    source_save_path,
    stage_world,
    verify_corridor_attempt,
)
from app.simulation.openttd.proof.endpoints import (
    kernel_socket_rows,
    verify_cleanup_endpoints,
)
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
from app.simulation.openttd.proof.terrain_clearing import (
    STAGED_AI_DIRECTORY,
    ClearingNativeBackend,
    replay_authorization_state,
    retained_welcome,
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
from app.simulation.openttd.secure_admin import (
    AuthDisconnected,
    AuthRejected,
    AuthState,
    AuthTimeout,
    InvalidSecureIdentity,
    SecureAdminSession,
    validate_join_secure_string,
    JOIN_SECURE_CLIENT_NAME_CAPACITY,
)
from app.simulation.openttd.secure_admin import JOIN_SECURE_VERSION_CAPACITY

PACKAGES = Path(__file__).resolve().parents[1]
FREIGHT_PACKAGE = PACKAGES / "d5_freight_package"
AI_PACKAGE = PACKAGES / "road_company_package"
TERRAIN_CLOSURE_ROOT = "app.simulation.openttd.proof.corridor_terrain_survey_native"

KIND = "terrain-survey"
# The consumed D5-TERRAIN-SURVEY-1 attempt is never reused; the follow-up
# survey for the corrected D5-CORRIDOR-EXTENSION-3 terminal design carries a
# fresh, unique identity.
MILESTONE_TERRAIN_SURVEY = "D5-CORRIDOR-EXTENSION-3"
# D5-CORRIDOR-EXTENSION-3-SURVEY-1 (32 UTF-8 bytes) exceeded JOIN_SECURE's
# 24-byte client-name payload and failed before any survey request; the
# follow-up attempt identity is compact and distinct from the consumed one.
TERRAIN_SURVEY_ATTEMPT = "D5CE3-SURVEY-2"
D5_TERRAIN_PRELAUNCH_SCHEMA = "d5-terrain-survey-prelaunch-v1"
# The terrain candidate keeps the shared native consumed-launch marker family
# and prerequisite lineage record (the same pinned D4 candidate-5 after-save
# world as protocols 5 and 6).
D5_TERRAIN_PREREQUISITE_SCHEMA = freight_native.D5_FREIGHT_PREREQUISITE_SCHEMA
D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA = freight_native.D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA
PINNED_PREREQUISITE = freight_native.PINNED_PREREQUISITE
PINNED_PREREQUISITE_AFTER_SAVE = freight_native.PINNED_PREREQUISITE_AFTER_SAVE
FREIGHT_READY_MARKER = "D5_READY"

# The census terrain fields the survey hypothesizes from the same retained
# pre-construction census the D5 extension module bounds. A census field the
# document does not carry (the D4 census records no ``max_height`` and no
# owner identity) is never invented here; it is simply never hypothesized, so
# a measured value can never be compared against an invented premise.
HYPOTHESIZED_TERRAIN_FIELDS = (
    "slope",
    "min_height",
    "buildable",
    "tree",
    "water",
    "coast",
    "farm",
    "rock",
    "rough",
    "road",
    "rail",
    "water_transport",
    "air_transport",
)
TERRAIN_OBSTRUCTIONS = (
    "tree",
    "water",
    "coast",
    "farm",
    "rock",
    "rough",
)

TERRAIN_SCHEDULE_VERSION = 1
TERRAIN_EXCHANGE_MARGIN_SECONDS = freight_native.FREIGHT_EXCHANGE_MARGIN_SECONDS

# Versioned evidence artifacts written by the authorized execution path and
# re-verified by replay. The stage journal attributes the lifecycle stage
# actually reached by the run (surviving failures that happen before
# ``result.json`` exists); the handshake evidence records the pre-welcome
# JOIN_SECURE lifecycle without any secret, credential or raw payload.
TERRAIN_PROGRESS_SCHEMA = "d5-terrain-survey-attempt-progress-v1"
TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA = "d5-terrain-survey-handshake-evidence-v1"
TERRAIN_ATTEMPT_STAGES = (
    "RUN_PREFLIGHT",
    "AUTHORIZATION_VERIFIED",
    "CLAIM_CREATED",
    "BACKEND_PREFLIGHT",
    "LAUNCH_BOUNDARY",
    "PROCESS_STARTED",
    "PROCESS_READY",
    "ADMINPORT_CONNECTED",
    "JOIN_SECURE_STARTED",
    "AUTHENTICATED",
    "WELCOME_RECEIVED",
    "WELCOME_VERIFIED",
    "RUNTIME_IDENTITY_WRITTEN",
    "SUBSCRIPTION_ESTABLISHED",
    "SURVEY_EXCHANGE_STARTED",
    "SURVEY_EXCHANGE_COMPLETED",
    "CLEANUP_STARTED",
    "CLEANUP_COMPLETED",
    "TERMINAL_SUCCESS",
    "TERMINAL_FAILURE",
)
JOIN_SECURE_EVIDENCE_STATES = (
    "NOT_ATTEMPTED",
    "STARTED",
    "REJECTED",
    "TIMED_OUT",
    "IO_FAILED",
    "INTERRUPTED",
    "AUTHENTICATED",
)
WELCOME_EVIDENCE_STATES = ("NOT_RECEIVED", "RECEIVED", "MISMATCH", "VERIFIED")


class TerrainSurveyStagingError(freight_native.FreightStagingError):
    """Offline terrain-survey staging or pin derivation failed; nothing was launched."""


# --- Migration-safety: the terrain pipeline is terrain-plan typed -------------


def _require_terrain_survey_plan(plan) -> TerrainSurveyPlan:
    """Refuse anything that is not the one pinned TerrainSurveyPlan.

    A ``FreightPlan`` and an ``AcceptSurveyPlan`` share several field names
    with ``TerrainSurveyPlan``; every terrain entry point guards here so no
    sibling plan can ever be staged, sealed, executed or replayed as a
    terrain survey.
    """
    if not isinstance(plan, TerrainSurveyPlan):
        raise TerrainSurveyStagingError("the terrain pipeline accepts a TerrainSurveyPlan only")
    if plan.digest != terrain_survey_plan().digest:
        raise TerrainSurveyStagingError("the terrain plan drifted from the pinned observations")
    return plan


# --- The pinned terrain-survey schedule ---------------------------------------


def terrain_schedule() -> list[dict]:
    """The fixed ten read-only terrain-survey exchanges as staged plan rows.

    Order refuses drift (``radius`` first, the pinned terra tiles in the
    pinned quantum order, then the acceptance pair with the consumed
    attempt's delivery stop control first), and every row carries its own
    observation tile where the schedule has one. No mutation-capable op can
    enter a terrain schedule: a foreign op is a staging error, never a
    run-time rejection that is benignly retried.
    """
    schedule = [dict(exchange="radius-00", op="radius")]
    for exchange in TERRAIN_EXCHANGE_IDS[1 : 1 + len(TERRAIN_TILES)]:
        schedule.append(
            dict(
                exchange=exchange,
                op="tile",
                observation_tile=TERRAIN_TILES[TERRAIN_EXCHANGE_IDS.index(exchange) - 1],
            )
        )
    schedule.append(
        dict(
            exchange="accept-00",
            op="accept",
            observation_tile=TERRAIN_ACCEPT_CONTROL_TILE,
        )
    )
    schedule.append(
        dict(
            exchange="accept-01",
            op="accept",
            observation_tile=TERRAIN_ACCEPT_STOP_TILE,
        )
    )
    ids = [row["exchange"] for row in schedule]
    if ids != list(TERRAIN_EXCHANGE_IDS) or len(schedule) != PLANNED_TERRAIN_EXCHANGES:
        raise TerrainSurveyStagingError(
            "the staged terrain schedule drifted from the wire contract"
        )
    if any(row["op"] not in TERRAIN_OPS for row in schedule):
        raise TerrainSurveyStagingError("a terrain schedule row carries a non-observation op")
    return schedule


def _terrain_exchange_ids(schedule: list[dict]) -> set[str]:
    ids = {row["exchange"] for row in schedule}
    if ids != set(TERRAIN_EXCHANGE_IDS):
        raise TerrainSurveyStagingError(
            "the staged terrain schedule drifted from the wire contract"
        )
    return ids


# --- Hypotheses (retained census), never facts --------------------------------


def terrain_census_hypotheses() -> dict:
    """The retained pre-construction census terrain facts, as hypotheses only.

    Re-parsed offline from the same retained demo network facts the D5
    extension module bounds (``d4._retained_network_facts()``). Each of the
    six pinned terra tiles contributes its hypothesized slope, height floor,
    buildability, obstruction and transport fields, and each of the two
    acceptance tiles its hypothesized acceptance; every row is
    ``HYPOTHESIS`` and stays one. Absent retained evidence (a fresh clone, or
    a census missing one pinned row) is recorded as ``CENSUS_ABSENT`` —
    staged planning stays honest instead of inventing hypotheses. A native
    value differing from a hypothesis is a real finding, not a fault.
    """
    facts_path = d4.RETAINED_NETWORK_FACTS
    if not facts_path.is_file():
        return dict(
            state="CENSUS_ABSENT",
            hypotheses=[],
            statement=(
                "the retained pre-construction census is absent from this checkout; "
                "no hypothesis is invented and the terrain survey proceeds without one"
            ),
        )
    facts = d4._retained_network_facts()
    tiles = {int(entry["tile_id"]): entry for entry in facts["tiles"]}
    coverage = {
        (entry["tile_id"], entry["role"], entry["cargo_id"]): entry for entry in facts["coverage"]
    }
    plan = terrain_survey_plan()
    rows: list[dict] = []
    for index, tile in enumerate(plan.terra_tiles):
        entry = tiles.get(int(tile))
        if entry is None:
            return dict(
                state="CENSUS_ABSENT",
                hypotheses=[],
                statement=(
                    "the retained census lacks the pinned terra tiles; no hypothesis "
                    "is invented and the terrain survey proceeds without one"
                ),
            )
        hypotheses = dict(
            (name, entry[name]) for name in HYPOTHESIZED_TERRAIN_FIELDS if name in entry
        )
        rows.append(
            dict(
                observation_index=index,
                tile=int(tile),
                origin="TERRA_TILES",
                terrain=hypotheses,
                kind="HYPOTHESIS",
            )
        )
    for index, tile in enumerate(plan.accept_tiles):
        entry = coverage.get((int(tile), "delivery", TERRAIN_CARGO_ID))
        if entry is None:
            return dict(
                state="CENSUS_ABSENT",
                hypotheses=[],
                statement=(
                    "the retained census lacks a delivery cargo-1 row for an "
                    "acceptance tile; no hypothesis is invented"
                ),
            )
        rows.append(
            dict(
                observation_index=len(plan.terra_tiles) + index,
                tile=int(tile),
                origin="TERRAIN_ACCEPT_TILES",
                hypothesis_acceptance_eighths=int(entry["acceptance_eighths"]),
                kind="HYPOTHESIS",
            )
        )
    digest = hashlib.sha256(facts_path.read_bytes()).hexdigest()
    return dict(
        state="RETAINED_CENSUS_REBOUND",
        hypotheses=rows,
        source=str(
            facts_path.relative_to(PROJECT) if facts_path.is_relative_to(PROJECT) else facts_path
        ),
        source_sha256=digest,
        statement=(
            "pre-construction census terrain facts are hypotheses only; a "
            "native measurement differing from a hypothesis is a recorded "
            "terrain finding, never normalized or refused"
        ),
    )


def compare_terrain_census_findings(terra: dict, hypotheses: dict) -> list[dict]:
    """Record native terrain measurements that differ from the census hypotheses.

    Findings are facts of record, never protocol errors: no measurement is
    rejected, normalized or dropped because it disagreed with a hypothesis.
    Only the fields the retained census actually hypothesizes are compared —
    a field the census never stated (``max_height``, ``owner``) can never
    become a finding premise.
    """
    if hypotheses.get("state") != "RETAINED_CENSUS_REBOUND":
        return []
    findings = []
    for row in hypotheses["hypotheses"]:
        if row.get("origin") != "TERRA_TILES":
            continue
        measured = terra.get(str(row["tile"]), terra.get(row["tile"]))
        if not isinstance(measured, dict):
            continue
        for field, hypothesis in row["terrain"].items():
            if field not in measured:
                continue
            value = measured[field]
            if (isinstance(hypothesis, bool) and bool(value) is not hypothesis) or (
                not isinstance(hypothesis, bool) and int(value) != int(hypothesis)
            ):
                findings.append(
                    dict(
                        tile=row["tile"],
                        field=field,
                        census_hypothesis=hypothesis,
                        measured=value,
                        request_id=measured.get("request_id"),
                        statement="the native terrain value differs from the census hypothesis",
                    )
                )
    return findings


def compare_terrain_acceptance_findings(observations: dict, hypotheses: dict) -> list[dict]:
    """Record native acceptance readings that differ from the census hypotheses."""
    if hypotheses.get("state") != "RETAINED_CENSUS_REBOUND":
        return []
    findings = []
    for row in hypotheses["hypotheses"]:
        if row.get("origin") != "TERRAIN_ACCEPT_TILES":
            continue
        measured = observations.get(str(row["tile"]), observations.get(row["tile"]))
        if not isinstance(measured, dict) or "value" not in measured:
            continue
        if int(measured["value"]) != int(row["hypothesis_acceptance_eighths"]):
            findings.append(
                dict(
                    tile=row["tile"],
                    census_hypothesis=row["hypothesis_acceptance_eighths"],
                    measured=measured["value"],
                    request_id=measured.get("request_id"),
                    statement="the native acceptance differs from the census hypothesis",
                )
            )
    return findings


# --- The terrain plan policy, budgets and readback story ---------------------


def terrain_plan_policy() -> dict:
    """The authorized read-only plan policy for the staged terrain candidate."""
    plan = _require_terrain_survey_plan(terrain_survey_plan())
    schedule = terrain_schedule()
    plan_digest = plan_digest_of(schedule)
    if schedule[0]["exchange"] != TERRAIN_EXCHANGE_IDS[0] or schedule[0]["op"] != "radius":
        raise TerrainSurveyStagingError("the terrain schedule must begin with the radius exchange")
    return dict(
        company=plan.company,
        target_tile=int(TERRAIN_DELIVERY_TILE),
        max_cost=0,
        command="none",
        command_statement=(
            "the staged terrain survey contains no mutation-capable command of "
            "any kind; building, terraforming, orders, purchases, vehicles, "
            "saves and any cost-bearing operation are outside this candidate "
            "forever"
        ),
        stale_rule=(
            "re-observe every pin of each exchange immediately before its "
            "one dispatch; any mismatch stops the phase without any command "
            "and preserves the verified prefix"
        ),
        identity=(
            "wire contract protocol 7: every exchange presents one uniform "
            "prelaunch seal digest; the terrain survey records measurements "
            "only (one read-only session, one company, zero commands)"
        ),
        schedule=schedule,
        plan_digest=plan_digest,
        plan_model_digest=plan.digest,
        schedule_version=TERRAIN_SCHEDULE_VERSION,
        terra_tiles=[int(tile) for tile in plan.terra_tiles],
        observations=[
            dict(
                tile=int(tile),
                kind="CONTROL" if tile == TERRAIN_ACCEPT_CONTROL_TILE else "CANDIDATE",
            )
            for tile in plan.accept_tiles
        ],
        hypotheses=terrain_census_hypotheses(),
        world=dict(
            pickup=int(TERRAIN_PICKUP_TILE),
            delivery=int(TERRAIN_DELIVERY_TILE),
            depot=int(plan.depot),
            company=plan.company,
            cargo=plan.cargo,
            terra_tiles=[int(tile) for tile in plan.terra_tiles],
            accept_tile_control=int(TERRAIN_ACCEPT_CONTROL_TILE),
            accept_tile_stop=int(TERRAIN_ACCEPT_STOP_TILE),
            expected_funds=FUNDS_AT_D4_CLOSE,
            request_budget=TERRAIN_REQUEST_BUDGET,
            statement=(
                "the staged terrain world is the D4 candidate-5 close-out: "
                "the survey only queries the pinned terra observation tiles "
                "and the pinned acceptance pair"
            ),
        ),
        read_only=dict(
            schema="d5-terrain-survey-readonly-v1",
            permitted_ops=list(TERRAIN_OPS),
            max_cost=0,
            funds_readback_required=True,
            statement=(
                "every exchange is a pure observation; a mutation-capable "
                "op cannot enter the schedule, the session surface or the "
                "replay"
            ),
        ),
    )


def terrain_budgets() -> dict:
    """The staged budget table for the terrain candidate (no cost budget)."""
    return dict(
        launches=1,
        connection_attempts=1,
        requests=TERRAIN_REQUEST_BUDGET,
        planned_exchanges=PLANNED_TERRAIN_EXCHANGES,
        gsadmin_bytes=MAX_TERRAIN_REQUEST_BYTES,
        response_bytes=MAX_TERRAIN_RESPONSE_BYTES,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        total_seconds=300,
        max_cost=0,
        expected_funds=FUNDS_AT_D4_CLOSE,
    )


def terrain_expected_readback_policy() -> dict:
    return dict(
        radius=(
            "the radius exchange returns READY with the native truck-stop "
            "coverage radius (0..255); no acceptance observation is possible "
            "before this exchange verifies"
        ),
        tile=(
            "each tile exchange returns READY with the pinned branch tile's "
            "native fact set (slope 0..255, heights, buildable, owner, the "
            "obstruction predicates and the four transport facts); a "
            "nonzero live slope or an occupied tile is a recorded FINDING, "
            "never a survey failure"
        ),
        accept=(
            "each accept exchange returns READY with the measured native "
            "acceptance (0..8 eighths) for exactly its pinned tile plus the "
            "radius echo; a zero is only a measured zero under a "
            "correlated READY frame"
        ),
        receipt=(
            "SURVEY_COMPLETE only after every scheduled exchange verifies in "
            "execution order with certified cleanup; a refused, missing, "
            "malformed, out-of-range, stale or inconclusive observation "
            "leaves the survey incomplete forever"
        ),
    )


def terrain_attempt_name() -> str:
    return TERRAIN_SURVEY_ATTEMPT


def require_join_secure_attempt_identity(attempt: str) -> None:
    """Fail closed on any attempt identity the pinned encoder cannot encode.

    Everything a PRELAUNCH or PREFLIGHT gate declares about the native
    authentication route is invalid the moment the identity exceeds the
    15.3 JOIN_SECURE client-name capacity, so the check succeeds only when
    the shared production validator accepts the exact name the candidate
    will send.
    """
    try:
        validate_join_secure_string(
            attempt, capacity=JOIN_SECURE_CLIENT_NAME_CAPACITY
        )
    except InvalidSecureIdentity as error:
        raise TerrainSurveyStagingError(
            f"the attempt identity is not encodable by JOIN_SECURE: {error}"
        ) from error


def terrain_prerequisite_binding(prerequisite: Path = PINNED_PREREQUISITE) -> dict:
    """Re-bind the pinned D4 candidate-5 prerequisite, terrain-scoped.

    Reuse: the freight prerequisite binding is byte-for-byte the same
    fail-closed verification over the same pinned directory (seal, consumed
    claim, after-save digest, receipt, replay verdict, welcome); the terrain
    adds only the corridor-pin cross-checks the sibling ceremonies bound
    through their own plans. Re-importing it here guarantees the terrain
    source world is exactly the authoritative D4 close-out and nothing else.
    """
    binding = freight_native.prerequisite_binding(prerequisite)
    metadata = read_prelaunch(Path(binding["retained_directory"]))
    if metadata.get("attempt") != "D4-CORRIDOR-5":
        raise TerrainSurveyStagingError("the terrain prerequisite is not D4-CORRIDOR-5")
    if (
        verify_corridor_attempt(Path(binding["retained_directory"])).get("verification")
        != "RECEIPT_VERIFIED"
    ):
        raise TerrainSurveyStagingError("the terrain prerequisite replay is not a verified receipt")
    plan = _require_terrain_survey_plan(terrain_survey_plan())
    facts = freight_native.freight_facts()
    if [plan.delivery, plan.depot] != [int(facts["stops"][1]), int(facts["depot"]["tile_id"])]:
        raise TerrainSurveyStagingError(
            "the terrain corridor pins drifted from the compiled corridor"
        )
    return dict(
        schema=D5_TERRAIN_PREREQUISITE_SCHEMA,
        role="PREREQUISITE_ATTEMPT",
        retained_directory=binding["retained_directory"],
        save=binding["save"],
        save_sha256=binding["save_sha256"],
        qualified_save_sha256=None,
        prelaunch_digest=binding["prelaunch_digest"],
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        expected_welcome=binding["expected_welcome"],
        verification=(
            "full replay verification of the consumed prerequisite attempt "
            "receipt plus the pinned authoritative after-save digest "
            "(shared with the D5 freight candidate's own binding)"
        ),
        provenance=binding["provenance"],
    )


# --- Terrain candidate staging -------------------------------------------------


def prepare_terrain_survey_candidate(
    directory: Path, *, prerequisite: Path = PINNED_PREREQUISITE
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    _require_terrain_survey_plan(terrain_survey_plan())
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise TerrainSurveyStagingError(
            "the terrain source world requires the pinned D4 prerequisite"
        )
    schedule = terrain_schedule()
    policy = terrain_plan_policy()
    if len(schedule) != PLANNED_TERRAIN_EXCHANGES:
        raise TerrainSurveyStagingError("the scheduled terrain exchanges drifted")
    if policy["schedule_version"] != TERRAIN_SCHEDULE_VERSION:
        raise TerrainSurveyStagingError("the staged terrain schedule derivation drifted")
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise TerrainSurveyStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    # Fail closed before any candidate artifact is written: an unencodable
    # attempt identity invalidates the whole preparation, never truncates.
    require_join_secure_attempt_identity(terrain_attempt_name())
    binding = terrain_prerequisite_binding(prerequisite)
    welcome = binding["expected_welcome"]
    world = stage_world(binding, welcome)
    if sha256(source_save_path(world)) != world["save_sha256"]:
        raise TerrainSurveyStagingError("the staged source-save digest mismatch")
    directory.mkdir(parents=True, exist_ok=False)
    workspace = freight_native.RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = EndpointReservation.allocate()
    try:
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        with os.fdopen(
            os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as stream:
            stream.write(key._secret)
        workspace.write_config(
            freight_native.AdminSettings(
                password="",
                port=reservation.admin_port,
                game_port=reservation.game_port,
                authorized_public_key_hex=key.public_hex,
            )
        )
        config = workspace.config.read_text().replace(
            "pause_on_newgame = true", "pause_on_newgame = false"
        )
        config += (
            "\n[ai]\nai_in_multiplayer = true\n[misc]\ngraphicsset = OpenGFX\n"
            f"[game_scripts]\n{SOURCE_SAVE_GS_NAME} = \n"
        )
        workspace.config.write_text(config)
        graphics = freight_native.stage_opengfx(
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
        composition, create_instance, version = freight_native.staged_composition()
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
        spec = freight_native.LaunchSpecification(
            workspace,
            freight_native.RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256),
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
        frozen.update(freight_native.d2_source_closure(TERRAIN_CLOSURE_ROOT))
        frozen.update(freight_native.d2_dependency_inventory(TERRAIN_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D5_TERRAIN_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_TERRAIN_SURVEY,
            kind=KIND,
            attempt=terrain_attempt_name(),
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
                    "the staged composition announces the save's stored "
                    "GameScript name/version; the additive protocol-7 "
                    "TerrainHandle ships inside the same reviewed package"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after-diagnostic.sav only; the "
                "authoritative source save, the prerequisite attempt record "
                "and every historical artifact stay untouched; the terrain "
                "survey saves nothing itself"
            ),
            plan_policy=policy,
            expected_readback=terrain_expected_readback_policy(),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.corridor_terrain_survey_native",
                "run",
                str(directory),
            ],
            budgets=terrain_budgets(),
            cleanup=[
                "close secure session",
                "quit and reap process",
                "verify endpoints",
                "retain session logs and the pre-survey save",
                "remove credential",
                "dispose owned workspace",
                "never modify the retained save or any historical artifact",
            ],
            authorization=(
                "PENDING — requires ONE fresh operator authorization after "
                "all preflight gates; offline staging consumed no claim and "
                "no authorization file exists"
            ),
            pin_provenance=dict(
                source=int(TERRAIN_DELIVERY_TILE),
                manifest_verified=True,
                statement=(
                    "the terrain survey binds the authoritative D4 candidate-5 "
                    "after-save and the pinned OpenTTD 15.3 binary; the "
                    "pinned ten-exchange observation schedule is the "
                    "wire contract module's own guarded derivation"
                ),
            ),
            environment=freight_native.launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
            cross_schedule_guard=dict(
                schema="d5-terrain-survey-cross-guard-v1",
                terrain_ops=list(TERRAIN_OPS),
                statement=(
                    "this candidate refuses every mutation-capable and "
                    "foreign-protocol op: a freight request (any protocol-5 "
                    "op) or a protocol-6 survey request fails the terrain "
                    "session schema check with protocol 7 required, and any "
                    "terrain request fails the freight and protocol-6 "
                    "survey sessions' own checks before any handler can run"
                ),
            ),
        )
        metadata["prerequisite"] = dict(
            schema=D5_TERRAIN_PREREQUISITE_SCHEMA,
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


def terrain_survey_preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal: re-derive every binding, trust nothing."""
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("the terrain prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("the one native attempt already consumed")
    if metadata.get("schema") != D5_TERRAIN_PRELAUNCH_SCHEMA:
        raise ValueError("the staged prelaunch record is not the D5 terrain survey lineage")
    if metadata.get("kind") != KIND or metadata.get("milestone") != MILESTONE_TERRAIN_SURVEY:
        raise ValueError("the staged terrain lineage drifted")
    verify_freeze(metadata["frozen"])
    freight_native.require_frozen_d2_closure(metadata["frozen"], TERRAIN_CLOSURE_ROOT)
    freight_native.require_frozen_d2_dependencies(metadata["frozen"], TERRAIN_CLOSURE_ROOT)
    policy = metadata["plan_policy"]
    # Independent re-derivation first: validate the staged identity by its
    # own bytes against the pinned capacity, not merely by equality with
    # the staging constant, so an invalid identity is named by capacity.
    try:
        validate_join_secure_string(
            metadata["attempt"], capacity=JOIN_SECURE_CLIENT_NAME_CAPACITY
        )
    except InvalidSecureIdentity as error:
        raise ValueError(
            f"the staged attempt identity is not encodable by JOIN_SECURE: {error}"
        ) from error
    if metadata["attempt"] != terrain_attempt_name():
        raise ValueError("the staged attempt identity drifted from its own scope")
    _require_terrain_survey_plan(terrain_survey_plan())
    schedule = terrain_schedule()
    if policy["schedule"] != schedule or policy["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("the staged terrain schedule drifted from the compiled derivation")
    if policy["plan_model_digest"] != terrain_survey_plan().digest:
        raise ValueError("the staged terrain plan digest drifted from the pinned plan")
    if policy["schedule_version"] != TERRAIN_SCHEDULE_VERSION:
        raise ValueError("the staged terrain schedule version drifted")
    for row in schedule:
        if row["op"] not in TERRAIN_OPS:
            raise ValueError("a scheduled terrain row carries a mutation-capable or foreign op")
    if policy.get("max_cost") != 0:
        raise ValueError("the staged terrain survey must budget zero cost")
    if policy["read_only"]["permitted_ops"] != list(TERRAIN_OPS):
        raise ValueError("the staged terrain survey's read-only op set drifted")
    world_pins = policy["world"]
    plan = terrain_survey_plan()
    expected_world = dict(
        pickup=int(TERRAIN_PICKUP_TILE),
        delivery=int(TERRAIN_DELIVERY_TILE),
        depot=int(plan.depot),
        company=plan.company,
        cargo=plan.cargo,
        terra_tiles=[int(tile) for tile in plan.terra_tiles],
        accept_tile_control=int(TERRAIN_ACCEPT_CONTROL_TILE),
        accept_tile_stop=int(TERRAIN_ACCEPT_STOP_TILE),
        expected_funds=FUNDS_AT_D4_CLOSE,
        request_budget=TERRAIN_REQUEST_BUDGET,
    )
    for name, expected in expected_world.items():
        if world_pins.get(name) != expected:
            raise ValueError(f"the staged terrain world pin {name} drifted")
    if policy["target_tile"] != int(TERRAIN_DELIVERY_TILE):
        raise ValueError("the staged terrain target tile drifted")
    staged_hypotheses = policy["hypotheses"]
    if staged_hypotheses.get("state") == "RETAINED_CENSUS_REBOUND":
        for row in staged_hypotheses["hypotheses"]:
            if row["kind"] != "HYPOTHESIS":
                raise ValueError("a census row stopped being a hypothesis")
            expected_row = terrain_census_hypotheses()["hypotheses"][row["observation_index"]]
            if row != expected_row:
                raise ValueError("the staged census hypothesis row drifted from the retained bytes")
    if metadata.get("budgets") != terrain_budgets():
        raise ValueError("the staged terrain budget pins drifted")
    if metadata["public_key"] != prepared.public_key or metadata["binary_sha256"] != BINARY_SHA256:
        raise ValueError("the staged identity pins drifted")
    binding = terrain_prerequisite_binding(Path(metadata["prerequisite"]["directory"]))
    required = ("attempt", "milestone", "directory", "prelaunch_sha256", "after_save_sha256")
    if {name: metadata["prerequisite"][name] for name in required} != dict(
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
    ):
        raise ValueError("the staged prerequisite binding drifted from its verified record")
    if metadata["prerequisite"].get("schema") != D5_TERRAIN_PREREQUISITE_SCHEMA:
        raise ValueError("the staged prerequisite schema drifted")
    stored_world = metadata["world"]
    if (
        stored_world.get("retained_directory") != binding["retained_directory"]
        or stored_world.get("source_save") != binding["save"]
        or stored_world.get("save_sha256") != binding["save_sha256"]
        or stored_world.get("save_sha256") != PINNED_PREREQUISITE_AFTER_SAVE
    ):
        raise ValueError("the staged world is not the pinned prerequisite after-save")
    if metadata["world"]["expected_welcome"] != retained_welcome():
        raise ValueError("the retained world identity requirements drifted")
    verify_staged_source_save(
        {"save_sha256": metadata["world"]["save_sha256"]},
        Path(metadata["workspace"]) / "source.sav",
    )
    composition, _, _ = freight_native.staged_composition()
    staged_identity = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME
    if staged_identity.joinpath("info.nut").read_bytes() != composition["info.nut"]:
        raise ValueError("the staged GameScript identity drifted from the retained composition")
    if staged_identity.joinpath("main.nut").read_bytes() != composition["main.nut"]:
        raise ValueError("the staged terrain handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("the workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- Wire protocol 7: secure session and one-launch backend --------------------


def encode_terrain_request(payload: bytes) -> bytes:
    return encode_gamescript(payload, max_payload_bytes=MAX_TERRAIN_REQUEST_BYTES)


def decode_terrain_request(payload: bytes) -> bytes:
    return decode_gamescript(payload, max_payload_bytes=MAX_TERRAIN_REQUEST_BYTES)


class TerrainSecureSession(SecureAdminSession):
    """Only the terrain-survey operations extend the secure write policy.

    A freight request cannot parse as a ``TerrainRequest`` (protocol 7
    required, and the freight op set is outside the terrain Literal), and a
    protocol-6 survey request likewise fails the protocol-7 field check, so
    a sibling exchange can never travel on the terrain session.
    """

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = TerrainRequest.model_validate_json(decode_terrain_request(frame[3:]))
            if request.op not in TERRAIN_OPS:
                raise ValueError("a mutation-capable op cannot ride the terrain session")
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class TerrainNativeBackend(freight_native.FreightNativeBackend):
    """One-launch backend carrying the shared consumed marker, terrain session."""

    launch_marker_schema = D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> TerrainSecureSession:
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("the native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await TerrainSecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


def terrain_exchange_timeout_seconds(*, budget_table: dict, op: str) -> float:
    """Every terrain op is a bounded immediate request/readback; no windows."""
    if op not in TERRAIN_OPS:
        raise ValueError("no terrain budget exists for a foreign op")
    return float(budget_table["request_seconds"])


def event_loop_deadline(seconds: float) -> float:
    return time.monotonic() + seconds


# --- Durable attempt evidence: stage journal, one-shot claim, handshake -------


def _replace_json_atomically(path: Path, document: dict) -> None:
    """Atomic JSON artifact replacement shared by the attempt evidence writers.

    The complete document is written to its own temporary sibling, flushed to
    stable storage and then renamed over the destination, so a crash between
    transitions can never leave a half-written artifact that replay could
    mistake for valid evidence. The temporary name is process-unique; a
    leftover ``*.partial`` can only coexist with the candidate before
    ``result.json``/its manifest exist, so replay's exhaustive manifest check
    never observes one beside a sealed artifact set.
    """
    tmp = path.with_name(path.name + f".{os.getpid()}.partial")
    try:
        with open(tmp, "wb") as stream:
            stream.write((json.dumps(document, sort_keys=True, indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


class TerrainAttemptJournal:
    """The durable stage journal of one authorized attempt execution.

    Every recorded transition rewrites ``attempt-progress.json`` atomically;
    an abrupt process death therefore preserves the last confirmed stage. An
    entry is one ordered fact: its lifecycle stage, a state of
    ``COMPLETED``/``FAILED`` and a public detail (an exchange label or an
    error type name) — never a secret, never a credential, never an error
    message that could carry authentication material. A write failure is
    itself fail-closed: it raises, so an attempt can never quietly continue
    without its evidence trail.
    """

    def __init__(self, directory: Path, prelaunch_digest: str) -> None:
        self._path = directory / "attempt-progress.json"
        self.document: dict[str, Any] = dict(
            schema=TERRAIN_PROGRESS_SCHEMA,
            attempt=terrain_attempt_name(),
            prelaunch_digest=prelaunch_digest,
            stages=[],
            write_errors=[],
        )
        # Stage writes that failed after the irreversible transitions; replay
        # treats a journal write failure as evidence loss (EVIDENCE_INCOMPLETE).
        self.flush_failures: list[str] = []

    def stage(
        self, name: str, *, state: str = "COMPLETED", detail: dict | None = None
    ) -> None:
        """Record one lifecycle fact; the whole document is rewritten flush."""
        if name not in TERRAIN_ATTEMPT_STAGES:
            raise ValueError(f"an unknown lifecycle stage cannot be recorded: {name}")
        if state not in ("COMPLETED", "FAILED"):
            raise ValueError("a journal stage state is COMPLETED or FAILED only")
        entry: dict[str, Any] = dict(stage=name, state=state)
        if detail:
            if set(detail) - {"label", "error_type"}:
                raise ValueError("journal details carry a public label or error type only")
            entry.update(detail)
        self.document["stages"].append(entry)
        self._flush()
        return None

    def _flush(self) -> None:
        try:
            _replace_json_atomically(self._path, self.document)
        except OSError as error:
            failure = f"stage journal write failed: {type(error).__name__}: {error}"
            self.flush_failures.append(failure)
            raise TerrainSurveyStagingError(
                "the durable attempt stage journal is not writable: the attempt "
                "cannot proceed without its evidence trail"
            ) from error

    def fail(self, name: str, error_type: str, label: str | None = None) -> None:
        """Record a FAILED transition; never a secret-bearing error message."""
        detail: dict[str, Any] = {"error_type": error_type}
        if label is not None:
            detail["label"] = label
        try:
            self.stage(name, state="FAILED", detail=detail)
        except TerrainSurveyStagingError as error:
            self.flush_failures.append(str(error))


def record_terrain_handshake(
    directory: Path,
    prelaunch_digest: str,
    *,
    join_secure: str | None = None,
    welcome: str | None = None,
    encrypted: bool | None = None,
    protocol_version: int | None = None,
) -> None:
    """Merge-update the durable pre-welcome handshake evidence artifact.

    The artifact classifies the JOIN_SECURE lifecycle join state
    (``JOIN_SECURE_EVIDENCE_STATES``) and the welcome state
    (``WELCOME_EVIDENCE_STATES``) with safe metadata only: the public attempt
    identity, the encryption and protocol facts the frame observer could see
    anyway and nothing more. No private key, seed, admin secret, password,
    session credential or raw authentication payload is ever recorded, and
    replay verifies this artifact against the retained runtime identity
    instead of trusting its own success label.
    """
    path = directory / "handshake-evidence.json"
    document: dict[str, Any]
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise TerrainSurveyStagingError(
                "the retained handshake evidence is unreadable: refusing to overwrite"
            ) from error
        if (
            not isinstance(existing, dict)
            or existing.get("schema") != TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA
            or existing.get("attempt") != terrain_attempt_name()
            or existing.get("prelaunch_digest") != prelaunch_digest
        ):
            raise TerrainSurveyStagingError(
                "the retained handshake evidence drifted from this attempt"
            )
        document = existing
    else:
        document = dict(
            schema=TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA,
            attempt=terrain_attempt_name(),
            prelaunch_digest=prelaunch_digest,
            join_secure="NOT_ATTEMPTED",
            welcome="NOT_RECEIVED",
            encrypted=None,
            protocol_version=None,
        )
    if join_secure is not None:
        if join_secure not in JOIN_SECURE_EVIDENCE_STATES:
            raise ValueError("an unknown join_secure evidence state cannot be recorded")
        document["join_secure"] = join_secure
    if welcome is not None:
        if welcome not in WELCOME_EVIDENCE_STATES:
            raise ValueError("an unknown welcome evidence state cannot be recorded")
        document["welcome"] = welcome
    if encrypted is not None:
        document["encrypted"] = bool(encrypted)
    if protocol_version is not None:
        document["protocol_version"] = int(protocol_version)
    _replace_json_atomically(path, document)


def write_terrain_claim(directory: Path, seal: str, grant) -> None:
    """Create the candidate's one-shot claim atomically and durably.

    Exclusive creation (``O_CREAT | O_EXCL``) is the candidate-wide claim
    gate: a second concurrent ``run`` on the same staged directory refuses
    here instead of racing the launch boundary. The claim is a single
    fsynced short write, so a torn claim can only ever fail closed at
    replay (no half-claim is ever a valid authorization story).
    """
    payload = json.dumps(
        dict(
            prelaunch_digest=seal,
            consumed=True,
            launches_allowed=1,
            retries=0,
            authorization_schema=CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
            authorization_sha256=grant.authorization_sha256,
            operator_key_identity=grant.operator_key_identity,
        ),
        sort_keys=True,
        indent=2,
    ) + "\n"
    path = directory / "CLAIM.json"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise TerrainSurveyStagingError(
            "the one native attempt is already claimed"
        ) from None
    with os.fdopen(fd, "w") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _terrain_exchange_request(entry: dict, seal: str, plan: TerrainSurveyPlan) -> TerrainRequest:
    """Build one fixed terrain request: pins, zero cost, its tile if tile/accept."""
    index = TERRAIN_EXCHANGE_IDS.index(entry["exchange"])
    tile = None
    if entry["op"] == "tile":
        tile = plan.terra_tiles[index - 1]
    elif entry["op"] == "accept":
        tile = plan.accept_tiles[index - (PLANNED_TERRAIN_EXCHANGES - len(plan.accept_tiles))]
    return TerrainRequest(
        op=entry["op"],
        request_id=entry["exchange"],
        plan=seal,
        company=plan.company,
        max_cost=0,
        pickup=TERRAIN_PICKUP_TILE,
        delivery=plan.delivery,
        depot=plan.depot,
        tile=tile,
    )


async def terrain_exchange(
    session,
    request: TerrainRequest,
    directory: Path,
    *,
    budget_table: dict | None = None,
    overall_deadline: float | None = None,
    clock=time.monotonic,
    timeout_factory=asyncio.timeout,
) -> TerrainReadback:
    """One sealed protocol-7 exchange; every frame and file is retained.

    Bounded request bytes, per-exchange timeout clamped to the overall
    attempt budget, duplicate/stale frame refusal and fail-closed parsing —
    the terrain-specific twin of the sibling ceremonies' exchange, over the
    512-byte protocol-7 bounds.
    """
    budget_table = budget_table if budget_table is not None else terrain_budgets()
    permitted = terrain_exchange_timeout_seconds(budget_table=budget_table, op=request.op)
    if overall_deadline is not None:
        remaining = overall_deadline - clock()
        if remaining <= 0:
            raise TimeoutError("the terrain attempt overall budget exhausted")
        permitted = min(permitted, remaining)
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_terrain_request(raw))
    decoder = AdminFrameDecoder()
    try:
        async with timeout_factory(permitted):
            while True:
                chunk = await session.receive()
                if not chunk:
                    raise ConnectionError("the terrain survey stream disconnected")
                game_frames = []
                for kind, payload in decoder.feed_frames(chunk):
                    if kind != SERVER_GAMESCRIPT:
                        raise ValueError("an unexpected terrain packet")
                    game_frames.append(payload)
                if len(game_frames) > 1:
                    raise ValueError("a duplicate terrain response frame")
                if game_frames:
                    body = game_frames[0]
                    if (directory / (request.request_id + "-response.json")).exists():
                        raise ValueError("a duplicate terrain response file")
                    response = decode_gamescript(body, max_payload_bytes=MAX_TERRAIN_RESPONSE_BYTES)
                    readback = TerrainReadback.parse_for(request, response)
                    (directory / (request.request_id + "-response.json")).write_bytes(response)
                    return readback
    except TimeoutError:
        raise TimeoutError(
            f"the terrain exchange {request.request_id} exceeded its {permitted:.1f}s budget"
        ) from None


# --- Terrain execution (authorized one-attempt path only) ---------------------


def apply_terrain_cleanup_outcome(result: dict, *, complete: bool) -> None:
    """Fail closed on the terrain survey's final cleanup verdict."""
    result["cleanup_complete"] = bool(complete)
    if complete:
        return
    result["cleanup_failure"] = True
    if result.get("verified") is True or result.get("status") == "NATIVE_TERRAIN_COMPLETE":
        freight_native.deny_verification(
            result,
            status="FAILED_CLEANUP",
            message=(
                "ValueError: cleanup was not certified; no verified terrain completion is possible"
            ),
        )


def census_findings_for(phase: dict, hypotheses: dict) -> list[dict]:
    """The combined census findings of one re-derived terrain phase."""
    return compare_terrain_census_findings(
        phase["terra"], hypotheses
    ) + compare_terrain_acceptance_findings(phase["observations"], hypotheses)


async def execute_terrain_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt terrain phase (never offline).

    One launch, one connection, the fixed ten read-only exchanges in the
    pinned order, every exchange verified against the accumulated terrain
    state by the production ``terrain_phase_outcome``; the first verification
    failure halts the phase prefix-preservingly, and cleanup is certified
    before any completion verdict can stand.

    Lifecycle order (R1 remediation): every safely reversible preparation
    runs before the permanent one-shot claim — ``terrain_survey_preflight``
    first, then ``backend.preflight`` (read-only: reads credentials, pins
    and executable ownership; creates no external state, reserves nothing
    and is safely repeatable), then the operator-authorization verification,
    and only then the atomic exclusive-creation claim. The claim is the
    last irreversible preparation; the process boundary inside the backend
    writes ``LAUNCH-CONSUMED.json`` authoritatively right at the Popen seam.
    Every durable stage, handshake and authorization fact is journaled, so
    a failure after an irreversible transition always leaves structured
    evidence naming the exact stage that was reached.
    """
    directory = prepared.directory
    terrain_survey_preflight(prepared)
    # The stage journal opens with run-scoped, non-consumable facts only; none
    # of its entries authorizes a launch, and it exists before any irreversible
    # transition so even a pre-claim failure stays attributed and non-consuming.
    journal = TerrainAttemptJournal(directory, sha256(directory / "PRELAUNCH.json"))
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    backend.preflight(prepared)
    journal.stage("RUN_PREFLIGHT")
    journal.stage("BACKEND_PREFLIGHT")
    grant = grant_launch(directory, metadata, seal)
    grant.launch_identity = freight_native.launch_critical_identity(prepared, metadata)
    journal.stage("AUTHORIZATION_VERIFIED")
    write_terrain_claim(directory, seal, grant)
    journal.stage("CLAIM_CREATED")
    schedule: list[dict] = metadata["plan_policy"]["schedule"]
    plan = _require_terrain_survey_plan(terrain_survey_plan())
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
    exchanges: list[tuple[TerrainRequest, TerrainReadback]] = []
    overall_deadline = event_loop_deadline(metadata["budgets"]["total_seconds"])
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared, authorization=grant)
            result["native_launches"] = 1
            journal.stage("PROCESS_STARTED")
            await wait_log(backend, prepared, FREIGHT_READY_MARKER)
            console(backend, metadata["bootstrap_command"])
            await wait_log(backend, prepared, ROAD_PROOF_COMPANY_READY_MARKER)
            journal.stage("PROCESS_READY")
            session = await backend.connect(
                prepared, frame_observer=lambda d, f: frames.append((d, f.hex()))
            )
            result["connections"] = 1
            journal.stage("ADMINPORT_CONNECTED")
            record_terrain_handshake(
                directory, seal, join_secure="NOT_ATTEMPTED", welcome="NOT_RECEIVED"
            )
            journal.stage("JOIN_SECURE_STARTED")
            try:
                await session.authenticate(metadata["attempt"], "1", timeout=10)
            except AuthRejected as error:
                journal.fail("JOIN_SECURE_STARTED", type(error).__name__)
                record_terrain_handshake(
                    directory, seal, join_secure="REJECTED", encrypted=False
                )
                raise
            except AuthTimeout as error:
                journal.fail("JOIN_SECURE_STARTED", type(error).__name__)
                record_terrain_handshake(
                    directory, seal, join_secure="TIMED_OUT", encrypted=False
                )
                raise
            except AuthDisconnected as error:
                journal.fail("JOIN_SECURE_STARTED", type(error).__name__)
                record_terrain_handshake(
                    directory, seal, join_secure="IO_FAILED", encrypted=False
                )
                raise
            except Exception as error:
                journal.fail("JOIN_SECURE_STARTED", type(error).__name__)
                record_terrain_handshake(
                    directory, seal, join_secure="INTERRUPTED", encrypted=False
                )
                raise
            journal.stage("AUTHENTICATED")
            record_terrain_handshake(
                directory,
                seal,
                join_secure="AUTHENTICATED",
                encrypted=session.state is AuthState.ACTIVE,
                protocol_version=None if session.protocol is None else session.protocol.version,
            )
            welcome = session.welcome
            expected = metadata["world"]["expected_welcome"]
            received = None
            if welcome is not None:
                received = tuple(getattr(welcome, field) for field in WELCOME_ORDER)
                record_terrain_handshake(directory, seal, welcome="RECEIVED")
                journal.stage("WELCOME_RECEIVED")
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
                if welcome is not None:
                    record_terrain_handshake(directory, seal, welcome="MISMATCH")
                raise ValueError("the retained world identity mismatch")
            record_terrain_handshake(directory, seal, welcome="VERIFIED")
            journal.stage("WELCOME_VERIFIED")
            write_json(
                directory / "runtime-identity.json",
                dict(
                    auth="X25519_AuthorizedKey",
                    encrypted=session.state is AuthState.ACTIVE,
                    welcome=asdict(welcome),
                    pid=backend.process.pid if backend.process else None,
                ),
            )
            journal.stage("RUNTIME_IDENTITY_WRITTEN")
            await GameScriptTransport(session, session.protocol).subscribe()
            journal.stage("SUBSCRIPTION_ESTABLISHED")
            before_save = await save(backend, prepared, "session-before")
            write_json(directory / "session-before-identity.json", dict(sha256=before_save))
            for entry in schedule:
                label = entry["exchange"]
                journal.stage("SURVEY_EXCHANGE_STARTED", detail={"label": label})
                try:
                    request = _terrain_exchange_request(entry, seal, plan)
                    if request.op not in TERRAIN_OPS:
                        raise ValueError("a mutation-capable op cannot enter the terrain run")
                    verify_request_against_terrain_survey_plan(request, plan=plan, seal=seal)
                    readback = await terrain_exchange(
                        session,
                        request,
                        directory,
                        budget_table=metadata["budgets"],
                        overall_deadline=overall_deadline,
                    )
                    result["requests"] += 1
                    probe = terrain_phase_outcome(
                        exchanges + [(request, readback)], prelaunch_digest=seal, plan=plan
                    )
                    if probe["failed"] is not None:
                        raise ValueError(
                            f"the terrain exchange {label} failed verification: "
                            f"{probe['failed']['error']}"
                        )
                    exchanges.append((request, readback))
                    result["exchanges"].append(label)
                    result["last_status"] = readback.status
                    result["command_accepted"] = True
                    result["state_changed"] = False  # the terrain survey mutates nothing
                    journal.stage("SURVEY_EXCHANGE_COMPLETED", detail={"label": label})
                except Exception as error:
                    result["halt"] = dict(
                        label=label, error=type(error).__name__ + ": " + str(error)
                    )
                    journal.fail("SURVEY_EXCHANGE_STARTED", type(error).__name__, label=label)
                    break
            phase = terrain_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
            result["phase"] = phase
            if phase["verification"] == "SURVEY_COMPLETE":
                if len(exchanges) != PLANNED_TERRAIN_EXCHANGES:
                    raise ValueError(
                        "the terrain completion evidence drifted from the staged schedule"
                    )
                if phase["radius"] is None or not phase["observations"]:
                    raise ValueError("the native radius or acceptance observation is missing")
                if len(phase["terra"]) != len(plan.terra_tiles):
                    raise ValueError("the re-derived terra fact inventory is incomplete")
                write_json(
                    directory / "receipt.json",
                    dict(
                        phase,
                        before_save_sha256=before_save,
                        census_findings=census_findings_for(
                            phase, metadata["plan_policy"]["hypotheses"]
                        ),
                    ),
                )
                result["verified"] = True
                result["status"] = "NATIVE_TERRAIN_COMPLETE"
            else:
                result["status"] = "PHASE_HALTED_PREFIX_PRESERVED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
        journal.fail("TERMINAL_FAILURE", type(error).__name__)
    finally:
        _soft_stage(journal, "CLEANUP_STARTED", result)
        if result.get("last_status") not in ("NOT_DISPATCHED",):
            try:
                await save(backend, prepared, "after-diagnostic", diagnostic=True)
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
            if result["status"] == "NATIVE_TERRAIN_COMPLETE":
                freight_native.deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: the retained script log health findings "
                        "deny the verified terrain completion"
                    ),
                )
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_TERRAIN_COMPLETE":
                freight_native.deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: the native runtime exited abnormally after "
                        f"the terrain survey (return code {result['returncode']})"
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
        apply_terrain_cleanup_outcome(result, complete=cleanup_complete)
        if cleanup_complete:
            _soft_stage(journal, "CLEANUP_COMPLETED", result)
        else:
            _soft_stage_fail(journal, "CLEANUP_COMPLETED", result)
        if result["status"] == "NATIVE_TERRAIN_COMPLETE" and not result.get("error"):
            _soft_stage(journal, "TERMINAL_SUCCESS", result)
        else:
            _soft_stage_fail(journal, "TERMINAL_FAILURE", result)
        if journal.flush_failures:
            result["stage_journal_write_errors"] = list(journal.flush_failures)
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


def _soft_stage(journal: TerrainAttemptJournal, name: str, result: dict) -> None:
    """Record a journal stage inside the finally block without losing evidence.

    A journal write failure this late must never drop ``result.json`` or the
    artifact manifest; the failure is preserved as structured evidence on the
    result instead (fail closed, never silently suppressed).
    """
    try:
        journal.stage(name)
    except TerrainSurveyStagingError as error:
        result.setdefault("stage_write_errors", []).append(str(error))


def _soft_stage_fail(journal: TerrainAttemptJournal, name: str, result: dict) -> None:
    try:
        journal.fail(name, "CLEANUP_OR_TERMINAL_ERROR")
    except TerrainSurveyStagingError as error:
        result.setdefault("stage_write_errors", []).append(str(error))


# --- Terrain replay verification -----------------------------------------------


def _load_evidence_json(path: Path) -> tuple[str, Any]:
    """Load one retained JSON evidence artifact for fail-closed replay.

    Returns ``(state, document)`` with one of:

    - ``"PRESENT"`` — the file exists and parses as JSON.
    - ``"ABSENT"`` — the file does not exist.
    - ``"MALFORMED"`` — the file exists but is unreadable or not valid JSON.

    A missing or malformed artifact can never be interpreted as a successful
    stage by any caller; replay decides per-artifact whether it is evidence
    of a stage not reached or of an internally inconsistent attempt.
    """
    if not path.is_file():
        return "ABSENT", None
    try:
        return "PRESENT", json.loads(path.read_text())
    except (OSError, ValueError):
        return "MALFORMED", None


def _invalid_terrain_verdict(states: dict, *, statement: str) -> dict:
    """The structured verdict for present-but-untrustworthy evidence.

    ``verification="EVIDENCE_INVALID"`` names the artifacts that are
    unreadable, malformed or of an unsupported schema. It is always a
    refusal: a malformed artifact can never become a verified stage.
    """
    verdict = dict(verification="EVIDENCE_INVALID", evidence_states=states)
    reached = _reached_stage(states.get("attempt_progress", {}).get("document"))
    if reached is not None:
        verdict["reached_stage"] = reached
    verdict["statement"] = statement
    return verdict


def _evidence_states_view(states: dict) -> dict:
    """The verdict-facing per-artifact state map of one attempt's evidence."""
    return dict(
        result=dict(state=states["result_state"]),
        runtime_identity=dict(state=states["runtime_identity_state"]),
        cleanup=dict(state=states["cleanup_state"]),
        frames=dict(state=states["frames_state"]),
        attempt_progress=dict(
            state=states["journal_state"],
            document=states["attempt_progress"],
        ),
        handshake=dict(
            state=states["handshake_state"],
            document=states["handshake"],
        ),
    )


def _incomplete_terrain_verdict(states: dict, *, statement: str) -> dict:
    """The structured fail-closed verdict for an attempt with missing evidence.

    ``verification="EVIDENCE_INCOMPLETE"`` never verifies anything: it names
    exactly which artifacts are present or unavailable and, when the stage
    journal survived, the last lifecycle stage the run actually reached,
    including whether a process was even started. It is always a refusal.
    """
    verdict = dict(verification="EVIDENCE_INCOMPLETE", evidence_states=states)
    reached = _reached_stage(states.get("attempt_progress"))
    if reached is not None:
        verdict["reached_stage"] = reached
    verdict["statement"] = statement
    return verdict


def _reached_stage(journal_view: Any) -> dict | None:
    """The last recorded journal entry, or None when no journal survived."""
    document = journal_view
    if isinstance(journal_view, dict):
        document = journal_view.get("document", journal_view)
    if not isinstance(document, dict) or not isinstance(document.get("stages"), list):
        return None
    stages = [entry for entry in document["stages"] if isinstance(entry, dict)]
    if not stages or "stage" not in stages[-1]:
        return None
    return dict(stages[-1])


def _versioned_evidence(path: Path, schema: str, seal: str) -> tuple[str, Any]:
    """Load one schema-versioned evidence artifact for fail-closed replay.

    Beyond :func:`_load_evidence_json`, the document must be an object with
    the expected schema string and this attempt's prelaunch digest; an
    unsupported schema version or a foreign attempt binding is named
    explicitly and can never verify.
    """
    state, document = _load_evidence_json(path)
    if state != "PRESENT":
        return state, None
    if not isinstance(document, dict) or "schema" not in document:
        return "MALFORMED", None
    if document.get("schema") != schema:
        return "UNSUPPORTED_SCHEMA_VERSION", None
    if document.get("prelaunch_digest") != seal:
        return "INVALID", None
    return "PRESENT", document


def _attempt_evidence(directory: Path, seal: str) -> dict:
    """The structured load of every post-claim evidence artifact of an attempt."""
    states: dict[str, Any] = {}
    states["result_state"], states["result"] = _load_evidence_json(
        directory / "result.json"
    )
    if states["result_state"] == "PRESENT" and not isinstance(states["result"], dict):
        states["result_state"], states["result"] = "MALFORMED", None
    states["runtime_identity_state"], states["runtime_identity"] = _load_evidence_json(
        directory / "runtime-identity.json"
    )
    if states["runtime_identity_state"] == "PRESENT" and not isinstance(
        states["runtime_identity"], dict
    ):
        states["runtime_identity_state"], states["runtime_identity"] = "MALFORMED", None
    states["cleanup_state"], states["cleanup"] = _load_evidence_json(
        directory / "cleanup.json"
    )
    if states["cleanup_state"] == "PRESENT" and not isinstance(states["cleanup"], dict):
        states["cleanup_state"], states["cleanup"] = "MALFORMED", None
    states["frames_state"], _ = _load_evidence_json(directory / "frames.json")
    states["journal_state"], states["attempt_progress"] = _versioned_evidence(
        directory / "attempt-progress.json", TERRAIN_PROGRESS_SCHEMA, seal
    )
    states["handshake_state"], states["handshake"] = _versioned_evidence(
        directory / "handshake-evidence.json", TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA, seal
    )
    return states


def _attempt_evidence_incomplete(directory: Path, seal: str, claims: dict) -> dict:
    """A claimed attempt whose terminal evidence set is not exhaustive.

    The manifest survived but the durable result evidence did not: the run
    stopped before its ``finally`` block completed. Nothing is verified and
    no stage is claimed beyond what the stage journal itself records.
    """
    states = _attempt_evidence(directory, seal)
    view = _evidence_states_view(states)
    view["claim"] = dict(consumed=claims.get("consumed") is True)
    return _incomplete_terrain_verdict(
        view,
        statement=(
            "the retained attempt consumed its one-shot claim but its durable "
            "terminal evidence is incomplete; the run stopped before its own "
            "finally block completed and nothing can be verified"
        ),
    )


def _parse_terrain_frames(directory: Path):
    """Parse the retained frame stream of the owned secure terrain session."""
    frames = json.loads((directory / "frames.json").read_text())
    outbound: list[bytes] = []
    replies: list[bytes] = []
    outbound_requests: list[TerrainRequest] = []
    request_positions: dict[bytes, int] = {}
    reply_positions: dict[bytes, int] = {}
    for index, (direction, frame_hex) in enumerate(frames):
        frame = bytes.fromhex(frame_hex)
        if direction == "outbound":
            outbound.append(frame)
            if frame[2] != ADMIN_GAMESCRIPT:
                continue
            payload = decode_terrain_request(frame[3:])
            try:
                query = TerrainRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("an outbound frame contains an invalid TerrainRequest") from None
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body, max_payload_bytes=MAX_TERRAIN_RESPONSE_BYTES)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)
    return outbound, outbound_requests, replies, request_positions, reply_positions


def verify_terrain_attempt_identity(metadata: dict, *, plan: TerrainSurveyPlan) -> dict:
    """Re-bind one retained terrain attempt to its pinned prerequisite and plan.

    Replay never trusts the staged record's own declarations: the pinned
    prerequisite is re-verified, the source-save digest, welcome, schedule,
    plan digests, read-only scope and census hypotheses are all re-derived.
    """
    if metadata.get("attempt") != terrain_attempt_name():
        raise ValueError("the retained attempt identity drifted from the staged scope")
    if (
        metadata.get("schema") != D5_TERRAIN_PRELAUNCH_SCHEMA
        or metadata.get("kind") != KIND
        or metadata.get("milestone") != MILESTONE_TERRAIN_SURVEY
    ):
        raise ValueError("the retained attempt is not the D5 terrain survey lineage")
    staged_prerequisite = metadata.get("prerequisite")
    if not isinstance(staged_prerequisite, dict):
        raise ValueError("the retained attempt lacks its prerequisite binding")
    binding = terrain_prerequisite_binding(Path(staged_prerequisite.get("directory", "")))
    expected_prerequisite = dict(
        schema=D5_TERRAIN_PREREQUISITE_SCHEMA,
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
        verification=binding["verification"],
    )
    if staged_prerequisite != expected_prerequisite:
        raise ValueError("the retained prerequisite binding drifted from the pinned D4 attempt")
    stored_world = metadata.get("world")
    if not isinstance(stored_world, dict):
        raise ValueError("the retained attempt lacks its world binding")
    expected_world_binding = dict(
        retained_directory=binding["retained_directory"],
        source_save=binding["save"],
        save_sha256=binding["save_sha256"],
        qualified_save_sha256=binding.get("qualified_save_sha256"),
    )
    for name, expected in expected_world_binding.items():
        if stored_world.get(name) != expected:
            raise ValueError(f"the retained world {name} drifted from the pinned prerequisite")
    if stored_world.get("save_sha256") != PINNED_PREREQUISITE_AFTER_SAVE:
        raise ValueError("the retained world is not the pinned prerequisite after-save")
    expected_welcome = stored_world.get("expected_welcome")
    if expected_welcome != binding["expected_welcome"] or expected_welcome != retained_welcome():
        raise ValueError("the retained world welcome drifted from the pinned identity")
    verify_staged_source_save(
        {"save_sha256": binding["save_sha256"]},
        source_save_path(stored_world),
    )
    staged_source = Path(metadata.get("workspace", "")) / "source.sav"
    if staged_source.is_file():
        verify_staged_source_save({"save_sha256": binding["save_sha256"]}, staged_source)
    _require_terrain_survey_plan(plan)
    policy = metadata.get("plan_policy")
    if not isinstance(policy, dict):
        raise ValueError("the retained attempt lacks its plan policy")
    schedule = terrain_schedule()
    if policy.get("schedule") != schedule or policy.get("plan_digest") != plan_digest_of(schedule):
        raise ValueError("the retained terrain schedule drifted from the compiled derivation")
    if policy.get("plan_model_digest") != plan.digest:
        raise ValueError("the retained plan digest drifted from the pinned terrain plan")
    if metadata.get("budgets") != terrain_budgets():
        raise ValueError("the retained budget contract drifted")
    if policy.get("max_cost") != 0:
        raise ValueError("the retained budget floated off the zero-cost contract")
    if policy["read_only"]["permitted_ops"] != list(TERRAIN_OPS):
        raise ValueError("the retained read-only op set drifted")
    world_pins = policy.get("world")
    if not isinstance(world_pins, dict):
        raise ValueError("the retained plan policy lacks its world pins")
    expected_pins = dict(
        pickup=int(TERRAIN_PICKUP_TILE),
        delivery=int(TERRAIN_DELIVERY_TILE),
        depot=int(plan.depot),
        company=plan.company,
        cargo=plan.cargo,
        terra_tiles=[int(tile) for tile in plan.terra_tiles],
        accept_tile_control=int(TERRAIN_ACCEPT_CONTROL_TILE),
        accept_tile_stop=int(TERRAIN_ACCEPT_STOP_TILE),
        expected_funds=FUNDS_AT_D4_CLOSE,
        request_budget=TERRAIN_REQUEST_BUDGET,
    )
    for name, expected in expected_pins.items():
        if world_pins.get(name) != expected:
            raise ValueError(f"the retained terrain world pin {name} drifted")
    if (
        policy.get("company") != plan.company
        or policy.get("target_tile") != int(TERRAIN_DELIVERY_TILE)
        or policy.get("plan_model_digest") != plan.digest
    ):
        raise ValueError("the retained terrain plan pins drifted")
    staged_hypotheses = policy.get("hypotheses")
    if not isinstance(staged_hypotheses, dict) or "state" not in staged_hypotheses:
        raise ValueError("the retained plan policy lacks its census hypothesis record")
    return binding


def verify_terrain_attempt(directory: Path) -> dict:
    """Replay the retained protocol-7 phase; never trust a success label.

    The replay re-derives every retained fact independently — operator
    authorization evidence, the staged terrain schedule, the captured session
    frames, every per-exchange request/response pair — then re-verifies the
    whole ten-exchange schedule with the production
    :func:`app.simulation.openttd.corridor_terrain_survey.terrain_phase_outcome`
    and the certified-cleanup gate. A forced or invented ``SURVEY_COMPLETE``
    label alone can never verify; a refused, missing, malformed, out-of-range
    or stale exchange always leaves the verdict incomplete.
    """
    directory = directory.resolve()
    prelaunch_path = directory / "PRELAUNCH.json"
    if not prelaunch_path.is_file():
        return _incomplete_terrain_verdict(
            dict(result=dict(state="ABSENT")),
            statement=(
                "the prelaunch record is absent; no staged terrain candidate "
                "exists here and nothing can be verified"
            ),
        )
    metadata = read_prelaunch(directory)
    seal = sha256(prelaunch_path)
    claims_path = directory / "CLAIM.json"
    if not claims_path.is_file():
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="CLAIM_ABSENT",
            statement=(
                "the terrain candidate was never consumed by an operator "
                "authorization; no verified completion is possible"
            ),
        )
    claims_state, claims = _load_evidence_json(claims_path)
    if claims_state != "PRESENT" or not isinstance(claims, dict):
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="CLAIM_INVALID",
            statement=(
                "the retained one-shot claim is missing or malformed; a torn or "
                "tampered claim can never carry an authorization or a verdict"
            ),
        )
    if claims.get("prelaunch_digest") != seal:
        raise ValueError("the attempt claim does not match its prelaunch seal")
    manifest_path = directory / "artifact-manifest.sha256"
    if not manifest_path.is_file():
        return _attempt_evidence_incomplete(directory, seal, claims)
    manifest_names: set[str] = set()
    for line in manifest_path.read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError("the artifact manifest mismatch")
        if sha256(directory / name) != digest:
            raise ValueError("the artifact manifest mismatch")
        manifest_names.add(name)
    present_names = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != "artifact-manifest.sha256"
    }
    if present_names != manifest_names:
        raise ValueError("the artifact manifest is not exhaustive")
    if metadata.get("schema") != D5_TERRAIN_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D5_TERRAIN_PRELAUNCH_SCHEMA} lineage; no verified "
                "completion is possible"
            ),
        )
    authorization_state = replay_authorization_state(directory, metadata, seal, claims)
    if authorization_state is not None:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state=authorization_state,
            statement=(
                "the retained authorization evidence does not match the "
                "operator-verified record; no verified completion is possible"
            ),
        )
    policy_replay = metadata["plan_policy"]
    schedule = policy_replay["schedule"]
    if schedule != terrain_schedule() or policy_replay["plan_digest"] != plan_digest_of(
        terrain_schedule()
    ):
        raise ValueError("the staged terrain schedule drifted from the compiled derivation")
    _terrain_exchange_ids(schedule)
    plan = _require_terrain_survey_plan(terrain_survey_plan())
    verify_terrain_attempt_identity(metadata, plan=plan)
    states = _attempt_evidence(directory, seal)
    result, runtime = states["result"], states["runtime_identity"]
    handshake, journal_doc = states["handshake"], states["attempt_progress"]
    malformed = {
        name[: -len("_state")]
        for name in (
            "result_state",
            "runtime_identity_state",
            "cleanup_state",
            "frames_state",
            "journal_state",
            "handshake_state",
        )
        if states[name] in ("MALFORMED", "UNSUPPORTED_SCHEMA_VERSION", "INVALID")
    }
    if malformed:
        return _invalid_terrain_verdict(
            _evidence_states_view(states),
            statement=(
                "the retained artifacts "
                f"{sorted(malformed)} are unreadable, malformed or carry an "
                "unsupported schema version; no stage can be trusted and "
                "nothing can be verified"
            ),
        )
    if states["result_state"] != "PRESENT":
        return _attempt_evidence_incomplete(directory, seal, claims)
    expected_welcome = metadata["world"]["expected_welcome"]
    if states["runtime_identity_state"] != "PRESENT":
        if result.get("status") == "NATIVE_TERRAIN_COMPLETE":
            raise ValueError(
                "the verified completion's retained runtime execution evidence "
                "is missing; no completion is possible without it"
            )
        if result.get("verified") is True:
            raise ValueError(
                "the retained attempt claims verification without its runtime "
                "execution evidence"
            )
        if result.get("status") == "FAILED":
            # A pre-welcome failure: the run reached a terminal status and its
            # handshake/journal evidence names the failed stage. A stage that
            # was reached and failed is never reported as missing evidence.
            return dict(
                verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
                evidence_states=_evidence_states_view(states),
                result_status=result.get("status"),
                error=result.get("error"),
                reached_stage=_reached_stage(journal_doc),
                handshake=terrain_handshake_view(handshake, states),
            )
        return _attempt_evidence_incomplete(directory, seal, claims)
    welcome = runtime.get("welcome")
    if runtime.get("encrypted") is not True or not isinstance(welcome, dict):
        raise ValueError("the owned single-runtime encrypted execution evidence missing")
    for field in WELCOME_ORDER:
        expected = True if field == "dedicated" else expected_welcome[field]
        if welcome.get(field) != expected:
            raise ValueError(f"the retained world welcome {field} drifted")
    if states["frames_state"] != "PRESENT":
        return _attempt_evidence_incomplete(directory, seal, claims)
    outbound, outbound_requests, replies, request_positions, reply_positions = (
        _parse_terrain_frames(directory)
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("the terrain request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [TerrainRequest.model_validate_json(path.read_bytes()) for path in paths]
    for path, query in zip(paths, file_queries, strict=True):
        if query.request_id != path.name[: -len("-request.json")]:
            raise ValueError("the retained request file identity does not match its payload")
    if len(outbound_requests) < len(file_queries):
        return dict(
            verification="UNRESOLVED_ATTEMPT_EVIDENCE_PRESERVED",
            exchanges=result.get("exchanges", []),
            state_changed=result.get("state_changed", False),
            result_status=result.get("status", "UNKNOWN"),
            statement="an incomplete retained exchange (fewer outbound frames); no completion claimed",  # noqa: E501
        )
    if len(outbound_requests) > len(file_queries):
        raise ValueError("the outbound frame count exceeds the request file count (tampering)")
    if sorted(q.to_bytes() for q in outbound_requests) != sorted(
        q.to_bytes() for q in file_queries
    ):
        raise ValueError("the outbound frame payloads do not match request file payloads")
    unknown = {q.request_id for q in file_queries} - _terrain_exchange_ids(schedule)
    if unknown:
        raise ValueError(f"the request identity is outside the staged schedule: {sorted(unknown)}")
    seen_ids: set[str] = set()
    for query in outbound_requests:
        if query.request_id in seen_ids:
            raise ValueError(f"a duplicate terrain request_id: {query.request_id}")
        seen_ids.add(query.request_id)
    response_map = {}
    for path in paths:
        response_path = path.with_name(path.name.replace("-request.json", "-response.json"))
        if response_path.is_file():
            response_map[path.read_bytes()] = response_path.read_bytes()
    for path in sorted(directory.glob("*-response.json")):
        exchange_id = path.name[: -len("-response.json")]
        try:
            readback = TerrainReadback.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise ValueError(
                f"the retained response file is not a parseable readback: {path.name}"
            ) from error
        if readback.request_id != exchange_id:
            raise ValueError("the retained response file identity does not match its payload")
        if not (directory / (exchange_id + "-request.json")).is_file():
            raise ValueError("the retained response file lacks its request")
    for raw, response in response_map.items():
        if outbound.count(encode_terrain_request(raw)) != 1 or replies.count(response) != 1:
            raise ValueError("the retained exchange lacks unique secure-session frame evidence")
    retained_responses = set(response_map.values())
    for reply in replies:
        if reply not in retained_responses:
            raise ValueError("the retained gateway response lacks its durable response file")
    for raw, response in response_map.items():
        if reply_positions[response] < request_positions[raw]:
            raise ValueError("a retained response precedes its own request in the frame stream")

    halted_position = None
    halt_record = result.get("halt")
    exchanges: list[tuple[TerrainRequest, TerrainReadback]] = []
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
            query = TerrainRequest.model_validate_json(request_path.read_bytes())
            raw = response_map.get(query.to_bytes())
            if raw is not None:
                exchanges.append((query, TerrainReadback.parse_for(query, raw)))
        if pending:
            break
    phase = terrain_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
    if states["cleanup_state"] != "PRESENT":
        return _attempt_evidence_incomplete(directory, seal, claims)
    cleanup_record = states["cleanup"]
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
            error=result.get("error", "the process exited abnormally"),
            exit_evidence=dict(returncode=exit_codes[0], cleanup_returncode=exit_codes[1]),
            reached_stage=_reached_stage(journal_doc),
            handshake=terrain_handshake_view(handshake, states),
        )
    if result["status"] == "NATIVE_TERRAIN_COMPLETE":
        if states["handshake_state"] != "PRESENT" or not isinstance(handshake, dict):
            raise ValueError("the verified completion lacks its handshake evidence")
        if (
            handshake.get("join_secure") != "AUTHENTICATED"
            or handshake.get("welcome") != "VERIFIED"
        ):
            raise ValueError("the verified completion contradicts its handshake evidence")
        if states["journal_state"] != "PRESENT":
            raise ValueError("the verified completion lacks its stage journal")
        reached = _reached_stage(journal_doc)
        if reached is None or reached.get("stage") != "TERMINAL_SUCCESS":
            raise ValueError(
                "the verified completion's stage journal does not confirm its terminal state"
            )
        required_stages = {
            "RUN_PREFLIGHT",
            "AUTHORIZATION_VERIFIED",
            "CLAIM_CREATED",
            "BACKEND_PREFLIGHT",
            "PROCESS_STARTED",
            "ADMINPORT_CONNECTED",
            "AUTHENTICATED",
            "WELCOME_VERIFIED",
            "RUNTIME_IDENTITY_WRITTEN",
            "SUBSCRIPTION_ESTABLISHED",
            "SURVEY_EXCHANGE_COMPLETED",
            "CLEANUP_COMPLETED",
        }
        recorded = {entry.get("stage") for entry in journal_doc["stages"]}
        if not required_stages <= recorded:
            raise ValueError(
                "the verified completion's stage journal is incomplete: "
                f"missing {sorted(required_stages - recorded)}"
            )
        if phase["verification"] != "SURVEY_COMPLETE":
            raise ValueError("the verified completion contradicts its terrain phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("the verified completion contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("the verified completion contradicts its launch seal")
        if len(result.get("exchanges", [])) != PLANNED_TERRAIN_EXCHANGES or not cleanup_complete:
            raise ValueError("the verified completion's cleanup or exchange inventory incomplete")
        if result.get("state_changed", False) is not False:
            raise ValueError("the terrain survey claimed a world change it cannot make")
        if len(outbound_requests) != PLANNED_TERRAIN_EXCHANGES:
            raise ValueError("the verified completion's request inventory drifted")
        if phase["radius"] is None or not phase["observations"] or not phase["terra"]:
            raise ValueError("the verified completion lacks its own re-derived observations")
        if len(phase["terra"]) != len(plan.terra_tiles):
            raise ValueError("the verified completion's terra inventory drifted")
        census_findings = census_findings_for(phase, policy_replay["hypotheses"])
        if result.get("cleanup_failure") is not None or result.get("verified") is not True:
            raise ValueError("the verified completion label contradicts its own result flags")
        receipt_path = directory / "receipt.json"
        if receipt_path.is_file():
            retained_receipt = json.loads(receipt_path.read_text())
            replay_phase = json.loads(json.dumps(phase)) if phase is not None else None
            # The run writes the phase fields flat together with its
            # before-save digest and census findings; the replay must read
            # exactly that shape and shrink nothing.
            if any(
                name not in retained_receipt or retained_receipt[name] != replay_phase[name]
                for name in replay_phase
            ):
                raise ValueError("the retained terrain receipt replay mismatch")
            expected_findings = census_findings_for(phase, policy_replay["hypotheses"])
            if retained_receipt.get("census_findings") != expected_findings:
                raise ValueError("the retained terrain census findings replay mismatch")
        return dict(
            verification="SURVEY_COMPLETION_VERIFIED",
            receipt=dict(
                phase=json.loads(json.dumps(phase)),
                census_findings=census_findings,
            ),
            handshake=terrain_handshake_view(handshake, states),
        )
    if result["status"] == "FAILED_CLEANUP":
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status="FAILED_CLEANUP",
            exchanges=result.get("exchanges", []),
            error=result.get("error") or "cleanup was not certified",
            cleanup_complete=False,
            cleanup_error=cleanup_record.get("cleanup_error"),
            cleanup_verification_error=cleanup_record.get("verification_error"),
            reached_stage=_reached_stage(journal_doc),
            handshake=terrain_handshake_view(handshake, states),
        )
    if result["status"] in ("PHASE_HALTED_PREFIX_PRESERVED", "FAILED"):
        if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED" and (
            phase["verification"] != "SURVEY_INCOMPLETE"
            or not isinstance(halt_record, dict)
            or len(result.get("exchanges", [])) != len(phase["receipts"])
            or (
                phase["failed"] is not None
                and phase["failed"].get("label") != halt_record.get("label")
            )
        ):
            raise ValueError("the halted terrain evidence contradicts its retained record")
        if not cleanup_complete:
            raise ValueError("the halted terrain attempt cleanup incomplete")
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
            reached_stage=_reached_stage(journal_doc),
            handshake=terrain_handshake_view(handshake, states),
        )
    return dict(
        verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
        result_status=result.get("status", "UNKNOWN"),
        error=result.get("error"),
        reached_stage=_reached_stage(journal_doc),
        handshake=terrain_handshake_view(handshake, states),
    )


def terrain_handshake_view(handshake: Any, states: dict) -> dict:
    """The verdict-facing handshake summary (no secrets, no raw payloads)."""
    view: dict[str, Any] = dict(state=states["handshake_state"])
    if isinstance(handshake, dict):
        for name in ("join_secure", "welcome", "encrypted", "protocol_version"):
            if name in handshake:
                view[name] = handshake[name]
    return view


def staged_terrain_authorization_payload_digest(directory: Path) -> str:
    """The RFC-canonical digest of the candidate's own authorization payload."""
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    return hashlib.sha256(
        canonical_authorization_bytes(authorization_payload(metadata, seal))
    ).hexdigest()


def terrain_exit_status(result: dict) -> int:
    verified = (
        result.get("verified") is True
        and result.get("status") == "NATIVE_TERRAIN_COMPLETE"
        and result.get("cleanup_complete") is True
        and result.get("state_changed") is False
    )
    return 0 if verified else 1


def terrain_verdict_exit_status(verdict: dict) -> int:
    return 0 if verdict.get("verification") == "SURVEY_COMPLETION_VERIFIED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prerequisite", type=Path, default=PINNED_PREREQUISITE)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_terrain_survey_candidate(directory, prerequisite=args.prerequisite)
        terrain_survey_preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        terrain_survey_preflight(freight_native.reopen_candidate(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        verdict = verify_terrain_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
        raise SystemExit(terrain_verdict_exit_status(verdict))
    else:
        read_prelaunch(directory)  # fail fast on any drifted prelaunch record
        result = asyncio.run(
            execute_terrain_attempt(
                freight_native.reopen_candidate(directory),
                TerrainNativeBackend(authorized_one_launch=True),
            )
        )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(terrain_exit_status(result))


if __name__ == "__main__":
    main()
