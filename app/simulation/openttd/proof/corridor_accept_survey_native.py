"""D5-ACCEPT-SURVEY-1 native staging pipeline (offline preparation only).

The consumed ``D5-FREIGHT-1`` attempt closed with the zero-native-acceptance
finding of record and the survey wire contract
(``app.simulation.openttd.corridor_accept_survey``, protocol 6) plus its
GameScript handler already review-verified. The previous gap stated in
``docs/d5-acceptance-survey-1-preparation.md`` §6 is closed here: the
staging/claim machinery in ``corridor_freight_native`` is plan-bound to the
D5 freight ``FreightPlan``, so the survey gets its own narrow pipeline bound
explicitly to ``AcceptSurveyPlan`` and the fixed eight-exchange schedule,
reusing the proven shared ceremony by import rather than copy (the same
pattern ``corridor_freight_native`` uses for the D4 machinery). This is not a
generic abstraction layer: survey staging, preflight, sealing, execution and
replay keep the freight pipeline untouched and cannot accept a
``FreightPlan``, and the freight pipeline still cannot accept an
``AcceptSurveyPlan`` ( disjoint wire schemas on both sessions refuse the
foreign request before it reaches any handler).

The survey is strictly read-only: its schedule admits only the ``radius``,
``accept`` and ``prod`` observation ops (every mutation-capable freight op is
outside the survey contract entirely), ``max_cost`` is 0 on every exchange,
funds are read back per exchange and cleanup is certified before any
completion verdict. Nothing here launches OpenTTD, connects to a port,
writes a claim or mutates any world or retained artifact.
"""

import argparse
import asyncio
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
from app.simulation.openttd.corridor_accept_survey import (
    FUNDS_AT_D4_CLOSE,
    MAX_SURVEY_REQUEST_BYTES,
    MAX_SURVEY_RESPONSE_BYTES,
    PLANNED_SURVEY_EXCHANGES,
    SURVEY_CARGO_ID,
    SURVEY_CONTROL_TILE,
    SURVEY_EXCHANGE_IDS,
    SURVEY_OPS,
    SURVEY_PICKUP_TILE,
    SURVEY_REQUEST_BUDGET,
    AcceptSurveyPlan,
    SurveyReadback,
    SurveyRequest,
    survey_phase_outcome,
    survey_plan,
    verify_request_against_survey_plan,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
    gamescript_subscription,
)
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
from app.simulation.openttd.secure_admin import AuthState, SecureAdminSession

PACKAGES = Path(__file__).resolve().parents[1]
FREIGHT_PACKAGE = PACKAGES / "d5_freight_package"
AI_PACKAGE = PACKAGES / "road_company_package"
SURVEY_CLOSURE_ROOT = "app.simulation.openttd.proof.corridor_accept_survey_native"

KIND = "accept-survey"
MILESTONE_SURVEY = "D5-ACCEPT-SURVEY"
SURVEY_ATTEMPT = "D5-ACCEPT-SURVEY-1"
D5_SURVEY_PRELAUNCH_SCHEMA = "d5-accept-survey-prelaunch-v1"
# The survey candidate keeps the shared native consumed-launch marker family.
D5_SURVEY_LAUNCH_CONSUMED_SCHEMA = freight_native.D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA
# The prerequisite lineage record is the same shared schema the freight
# candidate binds (the same pinned D4 candidate-5 after-save world).
D5_SURVEY_PREREQUISITE_SCHEMA = freight_native.D5_FREIGHT_PREREQUISITE_SCHEMA
PINNED_PREREQUISITE = freight_native.PINNED_PREREQUISITE
PINNED_PREREQUISITE_AFTER_SAVE = freight_native.PINNED_PREREQUISITE_AFTER_SAVE
FREIGHT_READY_MARKER = "D5_READY"

SURVEY_SCHEDULE_VERSION = 1
SURVEY_EXCHANGE_MARGIN_SECONDS = freight_native.FREIGHT_EXCHANGE_MARGIN_SECONDS


class SurveyStagingError(freight_native.FreightStagingError):
    """Offline survey staging or pin derivation failed; nothing was launched."""


# --- Migration-safety: the survey pipeline is survey-plan typed -------------


def _require_survey_plan(plan) -> AcceptSurveyPlan:
    """Refuse anything that is not the one pinned AcceptSurveyPlan.

    A ``FreightPlan`` shares several field names with ``AcceptSurveyPlan``;
    every survey entry point guards here so a freight plan can never be
    staged, sealed, executed or replayed as a survey.
    """
    if not isinstance(plan, AcceptSurveyPlan):
        raise SurveyStagingError("the survey pipeline accepts an AcceptSurveyPlan only")
    if plan.digest != survey_plan().digest:
        raise SurveyStagingError("the survey plan drifted from the pinned observations")
    return plan


# --- The pinned survey schedule ---------------------------------------------


def survey_schedule() -> list[dict]:
    """The fixed eight read-only survey exchanges as staged plan rows.

    Order refuses drift (`radius` first, control accept, five candidate
    accepts in the pinned order, pickup production control last) and every
    row carries its own observation tile where the schedule has one. No
    mutation-capable op can enter a survey schedule: a foreign op is a
    staging error, never a rejection at run time that is benignly retried.
    """
    schedule = [dict(exchange="radius-00", op="radius")]
    for exchange in SURVEY_EXCHANGE_IDS[1:7]:
        tile = (
            SURVEY_CONTROL_TILE
            if exchange == "accept-00"
            else survey_plan().observations[SURVEY_EXCHANGE_IDS.index(exchange) - 1]
        )
        schedule.append(dict(exchange=exchange, op="accept", observation_tile=tile))
    schedule.append(dict(exchange="prod-00", op="prod"))
    ids = [row["exchange"] for row in schedule]
    if ids != list(SURVEY_EXCHANGE_IDS) or len(schedule) != PLANNED_SURVEY_EXCHANGES:
        raise SurveyStagingError("the staged survey schedule drifted from the wire contract")
    if any(row["op"] not in SURVEY_OPS for row in schedule):
        raise SurveyStagingError("a survey schedule row carries a non-observation op")
    return schedule


def _survey_exchange_ids(schedule: list[dict]) -> set[str]:
    ids = {row["exchange"] for row in schedule}
    if ids != set(SURVEY_EXCHANGE_IDS):
        raise SurveyStagingError("the staged survey schedule drifted from the wire contract")
    return ids


# --- Hypotheses (retained census), never facts -------------------------------


def census_hypotheses() -> dict:
    """The retained pre-construction census acceptances, as hypotheses only.

    Re-parsed offline from the same retained demo network facts the survey
    preparation record bounds. Absent retained evidence (a fresh clone) is
    recorded as ``CENSUS_ABSENT`` — staged planning stays honest instead of
    inventing hypotheses. Values are never treated as measured facts or as
    admission floors; a native value differing from a hypothesis is a real
    finding, not a fault.
    """
    facts_path = (
        PROJECT
        / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
    )
    if not facts_path.is_file():
        return dict(
            state="CENSUS_ABSENT",
            hypotheses=[],
            statement=(
                "the retained pre-construction census is absent from this checkout; "
                "no hypothesis is invented and the survey proceeds without one"
            ),
        )
    facts = json.loads(facts_path.read_text())
    coverage = {
        (entry["tile_id"], entry["role"], entry["cargo_id"]): entry for entry in facts["coverage"]
    }
    rows = []
    plan = survey_plan()
    for index, tile in enumerate(plan.observations):
        entry = coverage.get((tile, "delivery", SURVEY_CARGO_ID))
        if entry is None:
            raise SurveyStagingError(
                f"the retained census lacks a delivery cargo-1 row for observation tile {tile}"
            )
        rows.append(
            dict(
                observation_index=index,
                tile=int(tile),
                role=entry["role"],
                cargo_id=entry["cargo_id"],
                hypothesis_acceptance_eighths=int(entry["acceptance_eighths"]),
                kind="HYPOTHESIS",
            )
        )
    digest = hashlib.sha256(facts_path.read_bytes()).hexdigest()
    return dict(
        state="RETAINED_CENSUS_REBOUND",
        hypotheses=rows,
        source="artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json",
        source_sha256=digest,
        statement=(
            "pre-construction census values are hypotheses only; a "
            "native measurement differing from a hypothesis is a "
            "recorded survey finding, never normalized or refused"
        ),
    )


def compare_census_findings(observations: dict, hypotheses: dict) -> list[dict]:
    """Record native measurements that differ from the census hypotheses.

    Findings are facts of record, never protocol errors: no observation is
    rejected, normalized or dropped because it disagreed with a hypothesis.
    """
    if hypotheses.get("state") != "RETAINED_CENSUS_REBOUND":
        return []
    findings = []
    for row in hypotheses["hypotheses"]:
        measured = observations.get(row["tile"])
        if not isinstance(measured, dict) or "value" not in measured:
            continue
        if int(measured["value"]) != int(row["hypothesis_acceptance_eighths"]):
            findings.append(
                dict(
                    tile=row["tile"],
                    census_hypothesis=row["hypothesis_acceptance_eighths"],
                    measured=measured["value"],
                    request_id=measured.get("request_id"),
                    statement="the native value differs from the census hypothesis",
                )
            )
    return findings


# --- The survey plan policy, budgets and readback story ----------------------


def survey_plan_policy() -> dict:
    """The authorized read-only plan policy for the staged survey candidate."""
    plan = _require_survey_plan(survey_plan())
    schedule = survey_schedule()
    plan_digest = plan_digest_of(schedule)
    if schedule[0]["exchange"] != SURVEY_EXCHANGE_IDS[0] or schedule[0]["op"] != "radius":
        raise SurveyStagingError("the survey schedule must begin with the radius observation")
    return dict(
        company=plan.company,
        target_tile=int(SURVEY_CONTROL_TILE),
        max_cost=0,
        command="none",
        command_statement=(
            "the staged survey contains no mutation-capable command of any "
            "kind; building, orders, purchases, vehicles, saves and any "
            "cost-bearing operation are outside this candidate forever"
        ),
        stale_rule=(
            "re-observe every pin of each exchange immediately before its "
            "one dispatch; any mismatch stops the phase without any command "
            "and preserves the verified prefix"
        ),
        identity=(
            "wire contract protocol 6: every exchange presents one uniform "
            "prelaunch seal digest; the survey records measurements only "
            "(one read-only session, one company, zero commands)"
        ),
        schedule=schedule,
        plan_digest=plan_digest,
        plan_model_digest=plan.digest,
        schedule_version=SURVEY_SCHEDULE_VERSION,
        observations=[
            dict(tile=int(tile), kind="CONTROL" if tile == SURVEY_CONTROL_TILE else "CANDIDATE")
            for tile in plan.observations
        ],
        hypotheses=census_hypotheses(),
        world=dict(
            pickup=int(SURVEY_PICKUP_TILE),
            pickup_front=int(plan.pickup_front),
            delivery=int(plan.delivery),
            delivery_front=int(plan.delivery_front),
            depot=int(plan.depot),
            depot_front=int(plan.depot_front),
            company=plan.company,
            cargo=plan.cargo,
            pickup_industry=int(plan.pickup_industry),
            control_tile=int(SURVEY_CONTROL_TILE),
            observation_tiles=[int(tile) for tile in plan.observations],
            expected_funds=FUNDS_AT_D4_CLOSE,
            request_budget=SURVEY_REQUEST_BUDGET,
            statement=(
                "the staged survey world is the D4 candidate-5 close-out: "
                "both stops must read company truck stops with their pinned "
                "fronts, the depot joined to its pinned front; the survey "
                "only queries the pinned observation tiles"
            ),
        ),
        read_only=dict(
            schema="d5-accept-survey-readonly-v1",
            permitted_ops=list(SURVEY_OPS),
            max_cost=0,
            funds_readback_required=True,
            statement=(
                "every exchange is a pure observation; a mutation-capable "
                "op cannot enter the schedule, the session surface or the "
                "replay"
            ),
        ),
    )


def survey_budgets() -> dict:
    """The staged budget table for the survey candidate (no cost budget)."""
    return dict(
        launches=1,
        connection_attempts=1,
        requests=SURVEY_REQUEST_BUDGET,
        planned_exchanges=PLANNED_SURVEY_EXCHANGES,
        gsadmin_bytes=MAX_SURVEY_REQUEST_BYTES,
        response_bytes=MAX_SURVEY_RESPONSE_BYTES,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        total_seconds=300,
        max_cost=0,
        expected_funds=FUNDS_AT_D4_CLOSE,
    )


def survey_expected_readback_policy() -> dict:
    return dict(
        radius=(
            "the radius exchange returns READY with the native truck-stop "
            "coverage radius (0..255); no acceptance observation is possible "
            "before this exchange verifies"
        ),
        accept=(
            "each accept exchange returns READY with the measured native "
            "acceptance (0..8 eighths) for exactly its pinned tile plus the "
            "radius echo; a value outside 0..8 can never parse and a zero is "
            "only a measured zero under a correlated READY frame"
        ),
        prod=(
            "the prod exchange returns READY with the pickup industry's "
            "last-month production of cargo 1 (the production control)"
        ),
        receipt=(
            "SURVEY_COMPLETE only after all eight exchanges verify in "
            "execution order with certified cleanup; a refused, missing, "
            "malformed, out-of-range, stale or inconclusive observation "
            "leaves the survey incomplete forever"
        ),
    )


def survey_attempt_name() -> str:
    return SURVEY_ATTEMPT


def survey_prerequisite_binding(prerequisite: Path = PINNED_PREREQUISITE) -> dict:
    """Re-bind the pinned D4 candidate-5 prerequisite, survey-scoped.

    Reuse: the freight prerequisite binding is byte-for-byte the same
    fail-closed verification over the same pinned directory (seal, consumed
    claim, after-save digest, receipt, replay verdict, welcome); the survey
    adds only the plan-route/witness cross-checks the freight ceremony bound
    through its own plan. Re-importing it here guarantees the survey source
    world is exactly the authoritative D4 close-out and nothing else.
    """
    binding = freight_native.prerequisite_binding(prerequisite)
    # A survey re-check the freight binding does not itself return: the
    # prerequisite replay must still be a verified receipt (it re-derives the
    # freight plan) and the corridor facts must pin the survey corridor pins.
    metadata = read_prelaunch(Path(binding["retained_directory"]))
    if metadata.get("attempt") != "D4-CORRIDOR-5":
        raise SurveyStagingError("the survey prerequisite is not D4-CORRIDOR-5")
    if (
        verify_corridor_attempt(Path(binding["retained_directory"])).get("verification")
        != "RECEIPT_VERIFIED"
    ):
        raise SurveyStagingError("the survey prerequisite replay is not a verified receipt")
    plan = _require_survey_plan(survey_plan())
    facts = freight_native.freight_facts()
    if [plan.pickup, plan.delivery] != [int(tile) for tile in facts["stops"]] or int(
        facts["depot"]["tile_id"]
    ) != plan.depot:
        raise SurveyStagingError("the survey corridor pins drifted from the compiled corridor")
    return dict(
        schema=D5_SURVEY_PREREQUISITE_SCHEMA,
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


# --- Survey candidate staging ------------------------------------------------


def prepare_survey_candidate(
    directory: Path, *, prerequisite: Path = PINNED_PREREQUISITE
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    _require_survey_plan(survey_plan())
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise SurveyStagingError("the survey source world requires the pinned D4 prerequisite")
    schedule = survey_schedule()
    policy = survey_plan_policy()
    if len(schedule) != PLANNED_SURVEY_EXCHANGES:
        raise SurveyStagingError("the scheduled survey exchanges drifted")
    if policy["schedule_version"] != SURVEY_SCHEDULE_VERSION:
        raise SurveyStagingError("the staged survey schedule derivation drifted")
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise SurveyStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    binding = survey_prerequisite_binding(prerequisite)
    welcome = binding["expected_welcome"]
    world = stage_world(binding, welcome)
    if sha256(source_save_path(world)) != world["save_sha256"]:
        raise SurveyStagingError("the staged source-save digest mismatch")
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
        frozen.update(freight_native.d2_source_closure(SURVEY_CLOSURE_ROOT))
        frozen.update(freight_native.d2_dependency_inventory(SURVEY_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D5_SURVEY_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_SURVEY,
            kind=KIND,
            attempt=survey_attempt_name(),
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
                    "GameScript name/version; the additive protocol-6 "
                    "SurveyHandle ships inside the same reviewed package"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after-diagnostic.sav only; the "
                "authoritative source save, the prerequisite attempt record "
                "and every historical artifact stay untouched; the survey "
                "saves nothing itself"
            ),
            plan_policy=policy,
            expected_readback=survey_expected_readback_policy(),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.corridor_accept_survey_native",
                "run",
                str(directory),
            ],
            budgets=survey_budgets(),
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
                source=int(SURVEY_CONTROL_TILE),
                manifest_verified=True,
                statement=(
                    "the survey binds the authoritative D4 candidate-5 "
                    "after-save and the pinned OpenTTD 15.3 binary; the "
                    "pinned observation schedule is the contract module's "
                    "own guarded derivation"
                ),
            ),
            environment=freight_native.launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
            cross_schedule_guard=dict(
                schema="d5-accept-survey-cross-guard-v1",
                survey_ops=list(SURVEY_OPS),
                statement=(
                    "this candidate refuses every mutation-capable op: a "
                    "freight request (any protocol-5 op) fails the survey "
                    "session schema check with protocol 6 required, and any "
                    "survey request fails the freight session check with "
                    "protocol 5 required"
                ),
            ),
        )
        metadata["prerequisite"] = dict(
            schema=D5_SURVEY_PREREQUISITE_SCHEMA,
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


def survey_preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal: re-derive every binding, trust nothing."""
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("the survey prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("the one native attempt already consumed")
    if metadata.get("schema") != D5_SURVEY_PRELAUNCH_SCHEMA:
        raise ValueError("the staged prelaunch record is not the D5 survey lineage")
    if metadata.get("kind") != KIND or metadata.get("milestone") != MILESTONE_SURVEY:
        raise ValueError("the staged survey lineage drifted")
    verify_freeze(metadata["frozen"])
    freight_native.require_frozen_d2_closure(metadata["frozen"], SURVEY_CLOSURE_ROOT)
    freight_native.require_frozen_d2_dependencies(metadata["frozen"], SURVEY_CLOSURE_ROOT)
    policy = metadata["plan_policy"]
    if metadata["attempt"] != survey_attempt_name():
        raise ValueError("the staged attempt identity drifted from its own scope")
    _require_survey_plan(survey_plan())
    schedule = survey_schedule()
    if policy["schedule"] != schedule or policy["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("the staged survey schedule drifted from the compiled derivation")
    if policy["plan_model_digest"] != survey_plan().digest:
        raise ValueError("the staged survey plan digest drifted from the pinned plan")
    if policy["schedule_version"] != SURVEY_SCHEDULE_VERSION:
        raise ValueError("the staged survey schedule version drifted")
    for row in schedule:
        if row["op"] not in SURVEY_OPS:
            raise ValueError("a scheduled survey row carries a mutation-capable or foreign op")
    if policy.get("max_cost") != 0:
        raise ValueError("the staged survey must budget zero cost")
    if policy["read_only"]["permitted_ops"] != list(SURVEY_OPS):
        raise ValueError("the staged survey's read-only op set drifted")
    world_pins = policy["world"]
    plan = survey_plan()
    expected_world = dict(
        pickup=int(SURVEY_PICKUP_TILE),
        pickup_front=int(plan.pickup_front),
        delivery=int(plan.delivery),
        delivery_front=int(plan.delivery_front),
        depot=int(plan.depot),
        depot_front=int(plan.depot_front),
        company=plan.company,
        cargo=plan.cargo,
        pickup_industry=int(plan.pickup_industry),
        control_tile=int(SURVEY_CONTROL_TILE),
        observation_tiles=[int(tile) for tile in plan.observations],
        expected_funds=FUNDS_AT_D4_CLOSE,
        request_budget=SURVEY_REQUEST_BUDGET,
    )
    for name, expected in expected_world.items():
        if world_pins.get(name) != expected:
            raise ValueError(f"the staged survey world pin {name} drifted")
    if policy["target_tile"] != int(SURVEY_CONTROL_TILE):
        raise ValueError("the staged survey control tile drifted")
    staged_hypotheses = policy["hypotheses"]
    if staged_hypotheses.get("state") == "RETAINED_CENSUS_REBOUND":
        for row in staged_hypotheses["hypotheses"]:
            if row["kind"] != "HYPOTHESIS":
                raise ValueError("a census row stopped being a hypothesis")
            expected_row = census_hypotheses()["hypotheses"][row["observation_index"]]
            if row != expected_row:
                raise ValueError("the staged census hypothesis row drifted from the retained bytes")
    if metadata.get("budgets") != survey_budgets():
        raise ValueError("the staged survey budget pins drifted")
    if metadata["public_key"] != prepared.public_key or metadata["binary_sha256"] != BINARY_SHA256:
        raise ValueError("the staged identity pins drifted")
    binding = survey_prerequisite_binding(Path(metadata["prerequisite"]["directory"]))
    required = ("attempt", "milestone", "directory", "prelaunch_sha256", "after_save_sha256")
    if {name: metadata["prerequisite"][name] for name in required} != dict(
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
    ):
        raise ValueError("the staged prerequisite binding drifted from its verified record")
    if metadata["prerequisite"].get("schema") != D5_SURVEY_PREREQUISITE_SCHEMA:
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
        raise ValueError("the staged survey handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("the workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- Wire protocol 6: secure session and one-launch backend ------------------


def encode_survey_request(payload: bytes) -> bytes:
    return encode_gamescript(payload, max_payload_bytes=MAX_SURVEY_REQUEST_BYTES)


def decode_survey_request(payload: bytes) -> bytes:
    return decode_gamescript(payload, max_payload_bytes=MAX_SURVEY_REQUEST_BYTES)


class SurveySecureSession(SecureAdminSession):
    """Only the survey operations extend the secure write policy.

    A freight request cannot parse as a SurveyRequest (protocol 6 required,
    and the freight op set is outside the survey Literal), so a freight
    exchange can never travel on the survey session.
    """

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = SurveyRequest.model_validate_json(decode_survey_request(frame[3:]))
            if request.op not in SURVEY_OPS:
                raise ValueError("a mutation-capable op cannot ride the survey session")
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class SurveyNativeBackend(freight_native.FreightNativeBackend):
    """One-launch backend carrying the shared consumed marker, survey session."""

    launch_marker_schema = D5_SURVEY_LAUNCH_CONSUMED_SCHEMA

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> SurveySecureSession:
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("the native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await SurveySecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


def survey_exchange_timeout_seconds(*, budget_table: dict, op: str) -> float:
    """Every survey op is a bounded immediate request/readback; no windows."""
    if op not in SURVEY_OPS:
        raise ValueError("no survey budget exists for a foreign op")
    return float(budget_table["request_seconds"])


def event_loop_deadline(seconds: float) -> float:
    return time.monotonic() + seconds


def _survey_exchange_request(entry: dict, seal: str, plan: AcceptSurveyPlan) -> SurveyRequest:
    """Build one fixed survey request: pins, zero cost, its tile if an accept."""
    tile = (
        plan.observations[SURVEY_EXCHANGE_IDS.index(entry["exchange"]) - 1]
        if entry["op"] == "accept"
        else None
    )
    return SurveyRequest(
        op=entry["op"],
        request_id=entry["exchange"],
        plan=seal,
        company=plan.company,
        max_cost=0,
        pickup=SURVEY_PICKUP_TILE,
        delivery=plan.delivery,
        depot=plan.depot,
        tile=tile,
    )


async def survey_exchange(
    session,
    request: SurveyRequest,
    directory: Path,
    *,
    budget_table: dict | None = None,
    overall_deadline: float | None = None,
    clock=time.monotonic,
    timeout_factory=asyncio.timeout,
) -> SurveyReadback:
    """One sealed protocol-6 exchange; every frame and file is retained.

    Bounded request bytes, per-exchange timeout clamped to the overall
    attempt budget, duplicate/stale frame refusal and fail-closed parsing —
    the survey-specific twin of the freight exchange, over the 512-byte
    protocol-6 bounds.
    """
    budget_table = budget_table if budget_table is not None else survey_budgets()
    permitted = survey_exchange_timeout_seconds(budget_table=budget_table, op=request.op)
    if overall_deadline is not None:
        remaining = overall_deadline - clock()
        if remaining <= 0:
            raise TimeoutError("the survey attempt overall budget exhausted")
        permitted = min(permitted, remaining)
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_survey_request(raw))
    decoder = AdminFrameDecoder()
    try:
        async with timeout_factory(permitted):
            while True:
                chunk = await session.receive()
                if not chunk:
                    raise ConnectionError("the survey proof stream disconnected")
                game_frames = []
                for kind, payload in decoder.feed_frames(chunk):
                    if kind != SERVER_GAMESCRIPT:
                        raise ValueError("an unexpected survey packet")
                    game_frames.append(payload)
                if len(game_frames) > 1:
                    raise ValueError("a duplicate survey response frame")
                if game_frames:
                    body = game_frames[0]
                    if (directory / (request.request_id + "-response.json")).exists():
                        raise ValueError("a duplicate survey response file")
                    response = decode_gamescript(body, max_payload_bytes=MAX_SURVEY_RESPONSE_BYTES)
                    readback = SurveyReadback.parse_for(request, response)
                    (directory / (request.request_id + "-response.json")).write_bytes(response)
                    return readback
    except TimeoutError:
        raise TimeoutError(
            f"the survey exchange {request.request_id} exceeded its {permitted:.1f}s budget"
        ) from None


# --- Survey execution (authorized one-attempt path only) ---------------------


def apply_survey_cleanup_outcome(result: dict, *, complete: bool) -> None:
    """Fail closed on the survey's final cleanup verdict."""
    result["cleanup_complete"] = bool(complete)
    if complete:
        return
    result["cleanup_failure"] = True
    if result.get("verified") is True or result.get("status") == "NATIVE_SURVEY_COMPLETE":
        freight_native.deny_verification(
            result,
            status="FAILED_CLEANUP",
            message=(
                "ValueError: cleanup was not certified; no verified survey completion is possible"
            ),
        )


async def execute_survey_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt survey phase (never offline).

    One launch, one connection, the fixed eight read-only exchanges in the
    pinned order, every exchange verified against the accumulated survey
    state by the production ``survey_phase_outcome``; the first verification
    failure halts the phase prefix-preservingly, and cleanup is certified
    before any completion verdict can stand.
    """
    directory = prepared.directory
    survey_preflight(prepared)
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    grant = grant_launch(directory, metadata, seal)
    grant.launch_identity = freight_native.launch_critical_identity(prepared, metadata)
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
    plan = _require_survey_plan(survey_plan())
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
    exchanges: list[tuple[SurveyRequest, SurveyReadback]] = []
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
                raise ValueError("the retained world identity mismatch")
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
                    request = _survey_exchange_request(entry, seal, plan)
                    if request.op not in SURVEY_OPS:
                        raise ValueError("a mutation-capable op cannot enter the survey run")
                    verify_request_against_survey_plan(request, plan=plan, seal=seal)
                    readback = await survey_exchange(
                        session,
                        request,
                        directory,
                        budget_table=metadata["budgets"],
                        overall_deadline=overall_deadline,
                    )
                    result["requests"] += 1
                    probe = survey_phase_outcome(
                        exchanges + [(request, readback)], prelaunch_digest=seal, plan=plan
                    )
                    if probe["failed"] is not None:
                        raise ValueError(
                            f"the survey exchange {label} failed verification: "
                            f"{probe['failed']['error']}"
                        )
                    exchanges.append((request, readback))
                    result["exchanges"].append(label)
                    result["last_status"] = readback.status
                    result["command_accepted"] = True
                    result["state_changed"] = False  # the survey mutates nothing
                except Exception as error:
                    result["halt"] = dict(
                        label=label, error=type(error).__name__ + ": " + str(error)
                    )
                    break
            phase = survey_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
            result["phase"] = phase
            if phase["verification"] == "SURVEY_COMPLETE":
                if len(exchanges) != PLANNED_SURVEY_EXCHANGES:
                    raise ValueError(
                        "the survey completion evidence drifted from the staged schedule"
                    )
                if phase["radius"] is None or phase["production"] is None:
                    raise ValueError(
                        "the native radius or production control observation is missing"
                    )
                write_json(
                    directory / "receipt.json",
                    dict(
                        phase,
                        before_save_sha256=before_save,
                        census_findings=compare_census_findings(
                            phase["observations"], metadata["plan_policy"]["hypotheses"]
                        ),
                    ),
                )
                result["verified"] = True
                result["status"] = "NATIVE_SURVEY_COMPLETE"
            else:
                result["status"] = "PHASE_HALTED_PREFIX_PRESERVED"
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
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
            if result["status"] == "NATIVE_SURVEY_COMPLETE":
                freight_native.deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: the retained script log health findings "
                        "deny the verified survey completion"
                    ),
                )
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_SURVEY_COMPLETE":
                freight_native.deny_verification(
                    result,
                    status="FAILED",
                    message=(
                        "ValueError: the native runtime exited abnormally after "
                        f"the survey (return code {result['returncode']})"
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
        apply_survey_cleanup_outcome(result, complete=cleanup_complete)
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


# --- Survey replay verification ----------------------------------------------


def _parse_survey_frames(directory: Path):
    """Parse the retained frame stream of the owned secure survey session."""
    frames = json.loads((directory / "frames.json").read_text())
    outbound: list[bytes] = []
    replies: list[bytes] = []
    outbound_requests: list[SurveyRequest] = []
    request_positions: dict[bytes, int] = {}
    reply_positions: dict[bytes, int] = {}
    for index, (direction, frame_hex) in enumerate(frames):
        frame = bytes.fromhex(frame_hex)
        if direction == "outbound":
            outbound.append(frame)
            if frame[2] != ADMIN_GAMESCRIPT:
                continue
            payload = decode_survey_request(frame[3:])
            try:
                query = SurveyRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("an outbound frame contains an invalid SurveyRequest") from None
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body, max_payload_bytes=MAX_SURVEY_RESPONSE_BYTES)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)
    return outbound, outbound_requests, replies, request_positions, reply_positions


def verify_survey_attempt_identity(metadata: dict, *, plan: AcceptSurveyPlan) -> dict:
    """Re-bind one retained survey attempt to its pinned prerequisite and plan.

    Replay never trusts the staged record's own declarations: the pinned
    prerequisite is re-verified, the source-save digest, welcome, schedule,
    plan digests, read-only scope and census hypotheses are all re-derived.
    """
    if metadata.get("attempt") != survey_attempt_name():
        raise ValueError("the retained attempt identity drifted from the staged scope")
    if (
        metadata.get("schema") != D5_SURVEY_PRELAUNCH_SCHEMA
        or metadata.get("kind") != KIND
        or metadata.get("milestone") != MILESTONE_SURVEY
    ):
        raise ValueError("the retained attempt is not the D5 survey lineage")
    staged_prerequisite = metadata.get("prerequisite")
    if not isinstance(staged_prerequisite, dict):
        raise ValueError("the retained attempt lacks its prerequisite binding")
    binding = survey_prerequisite_binding(Path(staged_prerequisite.get("directory", "")))
    expected_prerequisite = dict(
        schema=D5_SURVEY_PREREQUISITE_SCHEMA,
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
    _require_survey_plan(plan)
    policy = metadata.get("plan_policy")
    if not isinstance(policy, dict):
        raise ValueError("the retained attempt lacks its plan policy")
    schedule = survey_schedule()
    if policy.get("schedule") != schedule or policy.get("plan_digest") != plan_digest_of(schedule):
        raise ValueError("the retained survey schedule drifted from the compiled derivation")
    if policy.get("plan_model_digest") != plan.digest:
        raise ValueError("the retained plan digest drifted from the pinned survey plan")
    if metadata.get("budgets") != survey_budgets():
        raise ValueError("the retained budget contract drifted")
    if policy.get("max_cost") != 0:
        raise ValueError("the retained budget floated off the zero-cost contract")
    if policy["read_only"]["permitted_ops"] != list(SURVEY_OPS):
        raise ValueError("the retained read-only op set drifted")
    world_pins = policy.get("world")
    if not isinstance(world_pins, dict):
        raise ValueError("the retained plan policy lacks its world pins")
    expected_pins = dict(
        pickup=int(SURVEY_PICKUP_TILE),
        pickup_front=int(plan.pickup_front),
        delivery=int(plan.delivery),
        delivery_front=int(plan.delivery_front),
        depot=int(plan.depot),
        depot_front=int(plan.depot_front),
        company=plan.company,
        cargo=plan.cargo,
        pickup_industry=int(plan.pickup_industry),
        control_tile=int(SURVEY_CONTROL_TILE),
        observation_tiles=[int(tile) for tile in plan.observations],
        expected_funds=FUNDS_AT_D4_CLOSE,
        request_budget=SURVEY_REQUEST_BUDGET,
    )
    for name, expected in expected_pins.items():
        if world_pins.get(name) != expected:
            raise ValueError(f"the retained survey world pin {name} drifted")
    if (
        policy.get("company") != plan.company
        or policy.get("target_tile") != int(SURVEY_CONTROL_TILE)
        or policy.get("plan_model_digest") != plan.digest
    ):
        raise ValueError("the retained survey plan pins drifted")
    staged_hypotheses = policy.get("hypotheses")
    if not isinstance(staged_hypotheses, dict) or "state" not in staged_hypotheses:
        raise ValueError("the retained plan policy lacks its census hypothesis record")
    return binding


def verify_survey_attempt(directory: Path) -> dict:
    """Replay the retained protocol-6 phase; never trust a success label.

    The replay re-derives every retained fact independently — operator
    authorization evidence, the staged survey schedule, the captured session
    frames, every per-exchange request/response pair — then re-verifies the
    whole eight-exchange schedule with the production
    :func:`app.simulation.openttd.corridor_accept_survey.survey_phase_outcome`
    and the certified-cleanup gate. A forced or invented ``SURVEY_COMPLETE``
    label alone can never verify; a refused, missing, malformed, out-of-range
    or stale exchange always leaves the verdict incomplete.
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
                "the survey candidate was never consumed by an operator "
                "authorization; no verified completion is possible"
            ),
        )
    claims = json.loads(claims_path.read_text())
    if claims.get("prelaunch_digest") != seal:
        raise ValueError("the attempt claim does not match its prelaunch seal")
    manifest_names: set[str] = set()
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
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
    if metadata.get("schema") != D5_SURVEY_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D5_SURVEY_PRELAUNCH_SCHEMA} lineage; no verified "
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
    if schedule != survey_schedule() or policy_replay["plan_digest"] != plan_digest_of(
        survey_schedule()
    ):
        raise ValueError("the staged survey schedule drifted from the compiled derivation")
    _survey_exchange_ids(schedule)
    plan = _require_survey_plan(survey_plan())
    verify_survey_attempt_identity(metadata, plan=plan)
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    expected_welcome = metadata["world"]["expected_welcome"]
    welcome = runtime.get("welcome")
    if runtime.get("encrypted") is not True or not isinstance(welcome, dict):
        raise ValueError("the owned single-runtime encrypted execution evidence missing")
    for field in WELCOME_ORDER:
        expected = True if field == "dedicated" else expected_welcome[field]
        if welcome.get(field) != expected:
            raise ValueError(f"the retained world welcome {field} drifted")
    outbound, outbound_requests, replies, request_positions, reply_positions = _parse_survey_frames(
        directory
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("the survey request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [SurveyRequest.model_validate_json(path.read_bytes()) for path in paths]
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
    unknown = {q.request_id for q in file_queries} - _survey_exchange_ids(schedule)
    if unknown:
        raise ValueError(f"the request identity is outside the staged schedule: {sorted(unknown)}")
    seen_ids: set[str] = set()
    for query in outbound_requests:
        if query.request_id in seen_ids:
            raise ValueError(f"a duplicate survey request_id: {query.request_id}")
        seen_ids.add(query.request_id)
    response_map = {}
    for path in paths:
        response_path = path.with_name(path.name.replace("-request.json", "-response.json"))
        if response_path.is_file():
            response_map[path.read_bytes()] = response_path.read_bytes()
    for path in sorted(directory.glob("*-response.json")):
        exchange_id = path.name[: -len("-response.json")]
        try:
            readback = SurveyReadback.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise ValueError(
                f"the retained response file is not a parseable readback: {path.name}"
            ) from error
        if readback.request_id != exchange_id:
            raise ValueError("the retained response file identity does not match its payload")
        if not (directory / (exchange_id + "-request.json")).is_file():
            raise ValueError("the retained response file lacks its request")
    for raw, response in response_map.items():
        if outbound.count(encode_survey_request(raw)) != 1 or replies.count(response) != 1:
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
    exchanges: list[tuple[SurveyRequest, SurveyReadback]] = []
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
            query = SurveyRequest.model_validate_json(request_path.read_bytes())
            raw = response_map.get(query.to_bytes())
            if raw is not None:
                exchanges.append((query, SurveyReadback.parse_for(query, raw)))
        if pending:
            break
    phase = survey_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
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
            error=result.get("error", "the process exited abnormally"),
            exit_evidence=dict(returncode=exit_codes[0], cleanup_returncode=exit_codes[1]),
        )
    if result["status"] == "NATIVE_SURVEY_COMPLETE":
        if phase["verification"] != "SURVEY_COMPLETE":
            raise ValueError("the verified completion contradicts its survey phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("the verified completion contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("the verified completion contradicts its launch seal")
        if len(result.get("exchanges", [])) != PLANNED_SURVEY_EXCHANGES or not cleanup_complete:
            raise ValueError("the verified completion's cleanup or exchange inventory incomplete")
        if result.get("state_changed", False) is not False:
            raise ValueError("the survey claimed a world change it cannot make")
        if len(outbound_requests) != PLANNED_SURVEY_EXCHANGES:
            raise ValueError("the verified completion's request inventory drifted")
        if phase["radius"] is None or phase["production"] is None or not phase["observations"]:
            raise ValueError("the verified completion lacks its own re-derived observations")
        census_findings = compare_census_findings(
            phase["observations"], policy_replay["hypotheses"]
        )
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
                raise ValueError("the retained survey receipt replay mismatch")
            expected_findings = compare_census_findings(
                phase["observations"], policy_replay["hypotheses"]
            )
            if retained_receipt.get("census_findings") != expected_findings:
                raise ValueError("the retained survey census findings replay mismatch")
        return dict(
            verification="SURVEY_COMPLETION_VERIFIED",
            receipt=dict(
                phase=json.loads(json.dumps(phase)),
                census_findings=census_findings,
            ),
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
            raise ValueError("the halted survey evidence contradicts its retained record")
        if not cleanup_complete:
            raise ValueError("the halted survey attempt cleanup incomplete")
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


def staged_survey_authorization_payload_digest(directory: Path) -> str:
    """The RFC-canonical digest of the candidate's own authorization payload."""
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    return hashlib.sha256(
        canonical_authorization_bytes(authorization_payload(metadata, seal))
    ).hexdigest()


def survey_exit_status(result: dict) -> int:
    verified = (
        result.get("verified") is True
        and result.get("status") == "NATIVE_SURVEY_COMPLETE"
        and result.get("cleanup_complete") is True
        and result.get("state_changed") is False
    )
    return 0 if verified else 1


def survey_verdict_exit_status(verdict: dict) -> int:
    return 0 if verdict.get("verification") == "SURVEY_COMPLETION_VERIFIED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prerequisite", type=Path, default=PINNED_PREREQUISITE)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_survey_candidate(directory, prerequisite=args.prerequisite)
        survey_preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        survey_preflight(freight_native.reopen_candidate(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        verdict = verify_survey_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
        raise SystemExit(survey_verdict_exit_status(verdict))
    else:
        read_prelaunch(directory)  # fail fast on any drifted prelaunch record
        result = asyncio.run(
            execute_survey_attempt(
                freight_native.reopen_candidate(directory),
                SurveyNativeBackend(authorized_one_launch=True),
            )
        )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(survey_exit_status(result))


if __name__ == "__main__":
    main()
