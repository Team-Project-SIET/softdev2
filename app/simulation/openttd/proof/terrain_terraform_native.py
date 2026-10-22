"""D3 bounded clearing and terraforming native-proof preparation (offline).

Stages the reviewed Seed 17 bounded-levelling chain as fresh save-load
candidate compositions that reuse the proven D2 native-clearing machinery
exactly: the same operator authorization, runtime freeze, dependency
identity, immutable launch environment, one-shot claim and signed replay
boundaries. No second security framework is introduced; the shared
machinery is parameterized at call time (closure root, lineage schema,
census pin) so the D2 ceremony is untouched.

The staged chain binds the compiled ``p08-terraform`` levelling
specification byte-exactly:

1. ``D3-CLEARING-1`` (tile 45999) clears the first compiled tree from the
   retained ``before.sav`` world — the D2 clearing ceremony on a new tile,
   staged from the sealed census page of the retained Seed 17 world.
2. ``D3-CLEARING-2`` (tile 49326) clears the second compiled tree, staged
   from candidate 1's retained ``after.sav`` so both clears persist in one
   world state.
3. ``D3-TERRAFORMING-1`` executes the sixteen S-corner raises of the
   compiled specification (its two clear operations are the completed
   prerequisites bound through the chain), staged from candidate 2's
   retained ``after.sav``, with prefix-preserving halt per
   :func:`app.simulation.openttd.terrain_terraform.terraform_phase_outcome`.

Nothing here launches OpenTTD, connects to any port, or mutates any tile;
the staged pre-launch claim is never written, so nothing can launch until a
separate operator authorization creates it.
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

from app.planning.p08_terraform import (
    TerraformSpec,
    TerraformSpecRejection,
    compile_terraform_spec,
    intent_expectation,
)
from app.planning.p08_terrain import TerrainProposal
from app.planning.p08_v2_snapshot import _load_census, build_v2_snapshot_assessment
from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_quit
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
    MAX_CLEARING_COST,
    REQUEST_BUDGET,
    STAGED_AI_DIRECTORY,
    WELCOME_ORDER,
    ClearingNativeBackend,
    ClearingStagingError,
    d2_dependency_inventory,
    d2_source_closure,
    execute_attempt,
    launch_critical_identity,
    launch_environment,
    replay_authorization_state,
    require_frozen_d2_closure,
    require_frozen_d2_dependencies,
    retained_welcome,
    staged_save_binding,
    verify_directory_manifest,
)
from app.simulation.openttd.proof.terrain_clearing import (
    reopen as reopen_candidate,
)
from app.simulation.openttd.proof.terrain_clearing import (
    verify_attempt as verify_clearing_attempt_record,
)
from app.simulation.openttd.proof.world_correspondence import (
    SOURCE_SAVE_GS_NAME,
    verify_staged_source_save,
)
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState, SecureAdminSession
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts
from app.simulation.openttd.terrain_terraform import (
    TerraformExpectation,
    TerraformIntent,
    TerraformReadback,
    TerraformRequest,
    TerraformShareState,
    admit_terraform,
    terraform_phase_outcome,
    verify_terraform,
)
from app.simulation.openttd.tile_classification import TileClassificationResponse

PACKAGES = Path(__file__).resolve().parents[1]
CLEAR_PACKAGE = PACKAGES / "terrain_clearing_package"
TERRAFORM_PACKAGE = PACKAGES / "terrain_terraform_package"
AI_PACKAGE = PACKAGES / "road_company_package"
RETAINED_NETWORK_FACTS = SEED17_RUN / "network-facts-0.json"
D3_CLOSURE_ROOT = "app.simulation.openttd.proof.terrain_terraform_native"

KINDS = ("clear", "terraform")
MILESTONE_CLEARING = "D3-CLEARING"
MILESTONE_TERRAFORMING = "D3-TERRAFORMING"
MILESTONES = (MILESTONE_CLEARING, MILESTONE_TERRAFORMING)

# Versioned prelaunch evidence for every D3 native candidate (additive sister
# record of the D2 prelaunch machinery; the claim, launch boundary, freeze and
# replay gates are the shared D2 implementations parameterized at call time).
D3_PRELAUNCH_SCHEMA = "d3-clearing-terraform-native-prelaunch-v1"
D3_PREREQUISITE_SCHEMA = "d3-native-prerequisite-attempt-v1"
D3_LAUNCH_CONSUMED_SCHEMA = "d3-native-launch-consumed"

# The pinned reviewed levelling evidence (independently re-pinned by
# tests/test_p08_terraform.py; any drift refuses staging before any run).
PINNED_PROPOSAL_DIGEST = "4d698a9d748922efac8041af909428cd91d3c26409e30f2e698c62dfef8d644c"
PINNED_SPEC_DIGEST = "9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d"

# One independently classified eligible tree tile per clearing candidate, from
# the SEALED census page of the retained Seed 17 world. The two clears are
# never combined in one candidate: each is one operator-authorized attempt.
CLEARING_TARGETS: tuple[int, ...] = (45999, 49326)
CLEARING_ATTEMPTS = {45999: f"{MILESTONE_CLEARING}-1", 49326: f"{MILESTONE_CLEARING}-2"}
TERRAFORM_ATTEMPT = f"{MILESTONE_TERRAFORMING}-1"
REQUIRED_PREREQUISITES = {45999: False, 49326: True}

# The compiled levelling inventory (pinned again independently by
# tests/test_p08_terraform.py): the two D2-style clearing ceremonies are hoisted
# ahead of every corner write and the sixteen S-corner raises follow.
RAISE_OP_COUNT = 16
MAX_TERRAFORM_COST = 1000
# Wire exchange accounting per scheduled corner operation:
# inspect + 3 admission neighbor reads + 1 terraform + 4 intent-scoped
# independent verification reads. The dispatcher's own cap stays 296.
REQUESTS_PER_OP = 9
PLANNED_TERRAFORM_REQUESTS = RAISE_OP_COUNT * REQUESTS_PER_OP
# Diagnostics read slack on top of the 144 planned exchanges.
TERRAFORM_REQUEST_BUDGET = PLANNED_TERRAFORM_REQUESTS + 8

# The staged running AI announces its own readiness marker (identical to D2).
TERRAFORM_READY_MARKER = "TERRAFORM_READY"
ROAD_PROOF_COMPANY_READY_MARKER = "ROAD_PROOF_COMPANY_READY"


class TerraformStagingError(ClearingStagingError):
    """Offline D3 staging or pin derivation failed; nothing was launched."""


def staged_composition(kind: str) -> tuple[dict[str, bytes], str, int]:
    """Byte-exact save-restore composition for one D3 candidate kind.

    The retained staged ``info.nut`` announces the save's stored GameScript
    identity (name/version); the staged main is the kind's bounded handler
    with the save-restore bridge class (NetworkFreightProof) defined inline
    after the kind's proof class. No separate identity.nut is needed.
    """
    package = CLEAR_PACKAGE if kind == "clear" else TERRAFORM_PACKAGE
    parent = "TerrainClearingProof" if kind == "clear" else "TerrainTerraformProof"
    with zipfile.ZipFile(SEED17_RUN / "frozen-source.zip") as archive:
        info_bytes = archive.read("staged/info.nut")
    text = info_bytes.decode()
    create_instance = re.search(r'CreateInstance\(\)\s*\{\s*return\s+"([^"]+)"', text)
    version = re.search(r"GetVersion\(\)\s*\{\s*return\s+(\d+)", text)
    if create_instance is None or version is None or SOURCE_SAVE_GS_NAME not in text:
        raise TerraformStagingError("retained staged GameScript identity incomplete")
    main_text = (package / "main.nut").read_text()
    bridge_class = create_instance.group(1)
    if f"class {bridge_class} extends {parent}" not in main_text:
        raise TerraformStagingError(
            f"staged main.nut missing required bridge class {bridge_class}"
        )
    return (
        {"info.nut": info_bytes, "main.nut": (package / "main.nut").read_bytes()},
        bridge_class,
        int(version.group(1)),
    )


# --- Sealed census evidence: clearing pins per candidate --------------------


@lru_cache(maxsize=1)
def _retained_census() -> tuple[SupplementalPlanningFacts, dict[int, Any], tuple[int, int], int]:
    """Receipt-bound re-parse of the sealed census; fail-closed and read-only."""
    verify_directory_manifest(CENSUS_DIRECTORY)
    return _load_census(RETAINED_NETWORK_FACTS, CENSUS_DIRECTORY)


def census_pin(tile_id: int) -> dict:
    """Derive a clearing pin from the sealed census page that classifies it.

    The pin is evidence, not assume-and-clear: the native runner re-observes
    the tile immediately before admission and stops without any command when
    the live tile does not match this pinned classification and geometry.
    """
    _, tiles, _, _ = _retained_census()
    pinned = tiles.get(tile_id)
    if pinned is None:
        raise TerraformStagingError("pinned clearing tile absent from the sealed census")
    page_path = CENSUS_DIRECTORY / f"classification-p{pinned.page_ordinal:03d}-response.json"
    response = TileClassificationResponse.parse(page_path.read_bytes())
    classes = {
        tile: (tile_class, industry, owner)
        for tile, tile_class, industry, owner in response.classification
    }
    if tile_id not in response.geometry or tile_id not in classes:
        raise TerraformStagingError("pinned clearing tile absent from the census page")
    elevation, slope, flags = response.geometry[tile_id]
    tile_class, industry, owner = classes[tile_id]
    if tile_class.value != "TREES":
        raise TerraformStagingError("pinned clearing target is not an eligible tree tile")
    if industry is not None or owner != -1:
        raise TerraformStagingError("pinned clearing tile is occupied or owned")
    return dict(
        tile=tile_id,
        classification=tile_class.value,
        flags=flags,
        elevation=elevation,
        slope=slope,
        owner=owner,
        page=pinned.page_ordinal,
        page_sha256=sha256(page_path),
        verification=f"sealed census classification-p{pinned.page_ordinal:03d} byte evidence",
    )


def clearing_pins() -> dict[str, dict]:
    """The two independently classified clearing pins of the staged chain."""
    return {str(tile): census_pin(tile) for tile in CLEARING_TARGETS}


# --- The compiled levelling specification (sealed, deterministic) ------------


@lru_cache(maxsize=1)
def compiled_levelling() -> tuple[TerrainProposal, SupplementalPlanningFacts, TerraformSpec]:
    """Compile and pin the retained levelling specification offline.

    Mirrors tests/test_p08_terraform.retained(): the sealed census snapshot
    assessment replayed receipt-by-receipt, the retained proposal digest and
    the compiled specification digest pinned, and the census rows rebuilt
    into the planning-only census facts document.
    """
    assessment = build_v2_snapshot_assessment(
        RETAINED_NETWORK_FACTS, CENSUS_DIRECTORY, project_root=PROJECT
    )
    if not isinstance(assessment.levelling, TerrainProposal):
        raise TerraformStagingError("the retained levelling proposal did not compile")
    if assessment.levelling.digest != PINNED_PROPOSAL_DIGEST:
        raise TerraformStagingError("retained levelling proposal digest drifted")
    retained, census, bracket, _pages = _retained_census()
    doc = SupplementalPlanningFacts(
        schema_version=1,
        transport_mode="road",
        source=retained.source,
        region=retained.region,
        settings=retained.settings,
        road=retained.road,
        tiles=tuple(tile.fact() for tile in census.values()),
        coverage_scopes=(),
        coverage=(),
        engines=(),
        capture_economy_date_before=bracket[0],
        capture_economy_date_after=bracket[1],
    )
    spec = compile_terraform_spec(assessment.levelling, doc)
    if isinstance(spec, TerraformSpecRejection):
        raise TerraformStagingError(f"levelling specification refused: {spec.code}")
    if spec.digest != PINNED_SPEC_DIGEST:
        raise TerraformStagingError("compiled levelling specification digest drifted")
    if spec.corner_op_count != RAISE_OP_COUNT or spec.clearing_op_count != len(
        CLEARING_TARGETS
    ):
        raise TerraformStagingError("compiled specification inventory drifted")
    raises = [op for op in spec.ops if op.kind != "clear"]
    if [op.tile_id for op in spec.ops if op.kind == "clear"] != list(CLEARING_TARGETS):
        raise TerraformStagingError("compiled clear operations drifted from the staged chain")
    if any(op.corner != "S" or op.corner_mask != 0x2 or op.direction != "up" for op in raises):
        raise TerraformStagingError("compiled corner operations are not the reviewed S raises")
    return assessment.levelling, doc, spec


def terraform_schedule() -> list[dict]:
    """The staged operation schedule: the compiled raises in execution order.

    Each entry is the compiler's own payload for one S-corner raise. The
    two clearing operations of the compiled specification are NOT part of
    this schedule: they are separately authorized clearing candidates whose
    completed receipts bind the terraforming candidate's source world.
    """
    _proposal, _doc, spec = compiled_levelling()
    schedule = [op.to_payload() for op in spec.ops if op.kind != "clear"]
    if len(schedule) != RAISE_OP_COUNT:
        raise TerraformStagingError("scheduled operation count drifted")
    indexes = [entry["index"] for entry in schedule]
    if indexes != list(range(len(CLEARING_TARGETS), len(CLEARING_TARGETS) + RAISE_OP_COUNT)):
        raise TerraformStagingError("scheduled operation order drifted from the compiled spec")
    return schedule


def plan_digest_of(schedule: list[dict]) -> str:
    """The additive plan-digest key: canonical bytes of the staged schedule."""
    return hashlib.sha256(
        json.dumps(schedule, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def expectation_from_payload(payload: dict) -> TerraformExpectation:
    """Rebuild the wire-contract expectation from one staged schedule entry."""
    if payload.get("kind") != "raise" or payload.get("direction") != "up":
        raise TerraformStagingError("a scheduled corner operation is not an S raise")
    states = []
    for shift in payload.get("shifts") or ():
        states.append(
            TerraformShareState(
                tile=shift["tile"],
                corner=shift["corner"],
                before_min_height=shift["before_min"],
                before_slope=shift["before_slope"],
                after_min_height=shift["after_min"],
                after_slope=shift["after_slope"],
            )
        )
    point = payload.get("point")
    sharing = payload.get("sharing")
    if point is None or sharing is None:
        raise TerraformStagingError("scheduled corner operation lacks compiled geometry")
    return TerraformExpectation(
        host_tile=payload["tile"],
        corner=payload["corner"],
        direction=payload["direction"],
        corner_mask=payload["mask"],
        shared_point_x=point[0],
        shared_point_y=point[1],
        sharing_tiles=tuple(sharing),
        tiles=tuple(states),
    )

# --- Prerequisite-attempt source worlds -------------------------------------


def read_prelaunch(directory: Path) -> dict:
    """The prelaunch record of a staged candidate (fail-closed and read-only)."""
    path = directory / "PRELAUNCH.json"
    if not path.is_file():
        raise TerraformStagingError("staged prelaunch record missing")
    return json.loads(path.read_text())


def prerequisite_source_binding(prerequisite: Path) -> dict:
    """The fail-closed binding of a prerequisite attempt's retained after-save.

    The prerequisite must be a consumed, replay-verified D3 native clearing
    attempt on the launch-capable lineage whose receipt survives full replay
    verification, since the next candidate's world state is built from its
    retained ``after.sav`` bytes.
    """
    prerequisite = Path(prerequisite).resolve()
    if not prerequisite.is_dir() or any(part == ".." for part in prerequisite.parts):
        raise TerraformStagingError("prerequisite attempt directory is not a real directory")
    prelaunch = prerequisite / "PRELAUNCH.json"
    if not prelaunch.is_file():
        raise TerraformStagingError("prerequisite attempt has no prelaunch record")
    if any(entry.is_symlink() for entry in prerequisite.iterdir()) or prelaunch.is_symlink():
        raise TerraformStagingError("prerequisite attempt carries a symlinked artifact")
    metadata = read_prelaunch(prerequisite)
    if metadata.get("schema") != D3_PRELAUNCH_SCHEMA:
        raise TerraformStagingError("prerequisite attempt is not the D3 native lineage")
    if metadata.get("milestone") not in MILESTONES:
        raise TerraformStagingError("prerequisite attempt milestone is unknown")
    seal = sha256(prelaunch)
    if (prerequisite / "PRELAUNCH.sha256").read_text().strip() != seal:
        raise TerraformStagingError("prerequisite prelaunch seal mismatch")
    if metadata.get("kind") != "clear":
        raise TerraformStagingError("the prerequisite attempt must be a clearing attempt")
    claim_path = prerequisite / "CLAIM.json"
    if not claim_path.is_file():
        raise TerraformStagingError("the prerequisite attempt was never consumed")
    claim = json.loads(claim_path.read_text())
    if claim.get("prelaunch_digest") != seal or claim.get("consumed") is not True:
        raise TerraformStagingError("the prerequisite attempt claim is incomplete")
    after_save = prerequisite / "after.sav"
    if not after_save.is_file():
        raise TerraformStagingError("the prerequisite attempt retained no after world state")
    save_digest = sha256(after_save)
    receipt_path = prerequisite / "receipt.json"
    if not receipt_path.is_file():
        raise TerraformStagingError("the prerequisite attempt retained no receipt")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("after_save_sha256") != save_digest:
        raise TerraformStagingError("the prerequisite receipt does not bind its after save")
    verdict = verify_clearing_attempt_record(
        prerequisite,
        lineage_schema=D3_PRELAUNCH_SCHEMA,
        sealed_pin=metadata["plan_policy"]["pinned"],
    )
    if verdict.get("verification") != "RECEIPT_VERIFIED":
        raise TerraformStagingError(
            "the prerequisite attempt replay is not a verified receipt: "
            f"{verdict.get('verification')}"
        )
    return dict(
        schema=D3_PREREQUISITE_SCHEMA,
        role="PREREQUISITE_ATTEMPT",
        retained_directory=str(prerequisite),
        save="after.sav",
        save_sha256=save_digest,
        qualified_save_sha256=None,
        prelaunch_digest=seal,
        attempt=metadata["attempt"],
        milestone=metadata.get("milestone"),
        expected_welcome=metadata["world"]["expected_welcome"],
        verification="full replay verification of the consumed prerequisite attempt receipt",
    )


def prerequisite_chain_links(prerequisite: Path) -> list[dict]:
    """Walk an additive prerequisite chain, nearest attempt first.

    Every entry re-states its own pinned facts straight from the retained
    prelaunch record, so chained candidates never trust a single receipt
    alone: the full chain evidence joins the staged prelaunch record.
    """
    entries: list[dict] = []
    current = Path(prerequisite).resolve()
    while True:
        path = current / "PRELAUNCH.json"
        if not path.is_file() or path.is_symlink():
            raise TerraformStagingError("the prerequisite chain is broken")
        metadata = read_prelaunch(current)
        if metadata.get("schema") != D3_PRELAUNCH_SCHEMA:
            raise TerraformStagingError("the prerequisite chain leaves the D3 lineage")
        if metadata.get("kind") not in KINDS:
            raise TerraformStagingError("the prerequisite chain carries an unknown kind")
        entries.append(
            dict(
                attempt=metadata["attempt"],
                directory=str(current),
                kind=metadata["kind"],
                milestone=metadata.get("milestone"),
                prelaunch_sha256=sha256(path),
                target_tile=metadata["plan_policy"]["target_tile"],
            )
        )
        entry = metadata.get("prerequisite")
        if entry is None:
            return entries
        current = Path(entry["directory"]).resolve()
        if not current.is_dir():
            raise TerraformStagingError("the prerequisite chain directory is missing")


def prerequisite_chain_cleared_tiles(prerequisite: Path) -> set[int]:
    """The transitive set of clearing targets along a staged prerequisite chain."""
    links = prerequisite_chain_links(prerequisite)
    return {
        link["target_tile"]
        for link in links
        if link["kind"] == "clear"
    }


def chain_world_welcome(prerequisite: Path) -> dict:
    """Every chain member must stage the same retained world identity."""
    welcome = retained_welcome()
    for link in prerequisite_chain_links(prerequisite):
        metadata = read_prelaunch(Path(link["directory"]))
        if metadata["world"]["expected_welcome"] != welcome:
            raise TerraformStagingError("the prerequisite chain world identity drifted")
    return welcome


def stage_world_metadata(
    prerequisite: Path | None, welcome: dict
) -> tuple[dict, dict | None]:
    """The ``world`` metadata block plus prerequisite binding for one candidate.

    Without a prerequisite the candidate stages from the retained Seed 17
    ``before.sav`` world; with one, it stages from the prerequisite attempt's
    replay-verified ``after.sav`` through a fully bound record.
    """
    if prerequisite is None:
        binding = staged_save_binding()
        return (
            dict(
                mode="RETAINED_SOURCE_SAVE_LOAD",
                retained_directory=str(SEED17_RUN),
                source_save="before.sav",
                save_sha256=binding["save_sha256"],
                qualified_save_sha256=binding.get("qualified_save_sha256"),
                expected_welcome=welcome,
            ),
            None,
        )
    binding = prerequisite_source_binding(prerequisite)
    return (
        dict(
            mode="PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD",
            retained_directory=binding["retained_directory"],
            source_save=binding["save"],
            save_sha256=binding["save_sha256"],
            qualified_save_sha256=binding.get("qualified_save_sha256"),
            expected_welcome=welcome,
        ),
        binding,
    )


def source_save_path(world: dict) -> Path:
    """The staged world's source save file (the pinned retained artifact)."""
    return Path(world["retained_directory"]) / world["source_save"]


# --- Candidate planning facts -----------------------------------------------


def plan_policy(kind: str, target_tile: int) -> dict:
    """The kind's authorized plan policy for the staged candidate.

    The scalar ``target_tile`` keeps the proven D2 authorization payload
    shape. For the terraforming candidate it is the FIRST scheduled raise
    host; the complete ordered operation scope joins the payload additively
    (``operation_schedule`` + ``plan_digest`` keys in the same shared
    authorization builder).
    """
    if kind == "clear":
        pin = census_pin(target_tile)
        return dict(
            company=0,
            target_tile=target_tile,
            pinned=pin,
            max_cost=MAX_CLEARING_COST,
            command="GSTile.DemolishTile(tile)",
            stale_rule=(
                "re-observe the target immediately before admission; any "
                "pin mismatch stops the attempt without any command"
            ),
            identity=(
                "wire contract v2: the clear request plan must equal the "
                "inspect plan that latched its admission; the handler "
                "compares it at the mutation boundary before DemolishTile"
            ),
        )
    schedule = terraform_schedule()
    if target_tile != schedule[0]["tile"]:
        raise TerraformStagingError("the terraforming attempt host is not the first scheduled op")
    _proposal, _doc, spec = compiled_levelling()
    if [op.tile_id for op in spec.ops if op.kind != "clear"] != [
        entry["tile"] for entry in schedule
    ]:
        raise TerraformStagingError("scheduled hosts drifted from the compiled specification")
    if any(entry["command"] != "GSTile.RaiseTile" for entry in schedule):
        raise TerraformStagingError("a scheduled corner operation carries an unbound command")
    compiled = {op.tile_id for op in spec.ops if op.kind == "clear"}
    return dict(
        company=0,
        target_tile=target_tile,
        max_cost=MAX_TERRAFORM_COST,
        command="GSTile.RaiseTile",
        stale_rule=(
            "re-observe each host corner and every directly sharing tile "
            "immediately before admission; any mismatch stops the phase "
            "without any command and preserves the verified prefix"
        ),
        identity=(
            "wire contract v3: the terraform request presents the "
            "prelaunch seal the inspect latched; the four independent "
            "verification reads present the admitted intent digest"
        ),
        schedule=schedule,
        plan_digest=plan_digest_of(schedule),
        prerequisite_world=dict(
            schema=D3_PREREQUISITE_SCHEMA,
            cleared_tiles=sorted(compiled),
            statement=(
                "the terraforming candidate's source world is a completed "
                "clearing chain: every compiled clear operation's tile must "
                "read classified CLEAR unowned at admission time"
            ),
        ),
    )


def budgets_for(kind: str) -> dict:
    """The staged budget table for one candidate kind."""
    if kind == "clear":
        return dict(
            launches=1,
            connection_attempts=1,
            requests=REQUEST_BUDGET,
            real_clears=1,
            gsadmin_bytes=1450,
            response_bytes=512,
            retries=0,
            reconnects=0,
            readiness_seconds=45,
            request_seconds=10,
            total_seconds=180,
        )
    return dict(
        launches=1,
        connection_attempts=1,
        requests=TERRAFORM_REQUEST_BUDGET,
        real_clears=0,
        real_raises=RAISE_OP_COUNT,
        gsadmin_bytes=1450,
        response_bytes=512,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        total_seconds=900,
    )


def expected_readback_policy(kind: str) -> dict:
    """The receipt contract's observable readback story, per candidate kind."""
    if kind == "clear":
        return dict(
            before=(
                "read-0 observes; inspect-1 returns READY with the pinned "
                "TREES classification, geometry and unowned owner"
            ),
            after=(
                "read-2 returns READ with CLEAR classification, unchanged "
                "geometry, unowned owner and no industry pointer"
            ),
            independent_query="read operation after the single clear request",
            receipt="plan-bound only after the clear result and independent readback agree",
        )
    return dict(
        before=(
            "per op: inspect returns READY for the classified-clear unowned "
            "host and the three neighbor reads return READ at the derived "
            "expected before geometry"
        ),
        execution=(
            "the terraform request presents the prelaunch seal and the "
            "handler re-observes the whole admission before RaiseTile"
        ),
        after=(
            "per op: four independent intent-scoped reads return READ at the "
            "derived after geometry for all four sharing tiles"
        ),
        receipt=(
            "plan-bound only after the execution result and independent "
            "readbacks agree, per operation, in execution order"
        ),
    )


def d3_attempt_name(kind: str, tile: int) -> str:
    """The candidate's one attempt name, bound to its own staged scope."""
    if kind == "clear":
        name = CLEARING_ATTEMPTS.get(tile)
        if name is None:
            raise TerraformStagingError("a staged clearing target is not the reviewed chain tile")
        return name
    if tile != terraform_schedule()[0]["tile"]:
        raise TerraformStagingError("the terraforming attempt host is not the first scheduled op")
    return TERRAFORM_ATTEMPT


# --- Candidate staging -------------------------------------------------------


def prepare_candidate(
    directory: Path, *, kind: str = "clear", prerequisite: Path | None = None
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    if kind not in KINDS:
        raise TerraformStagingError("unknown D3 candidate kind")
    prerequisite = None if prerequisite is None else Path(prerequisite).resolve()
    if kind == "clear":
        tile = CLEARING_TARGETS[0] if prerequisite is None else CLEARING_TARGETS[1]
    else:
        tile = terraform_schedule()[0]["tile"]
    links = prerequisite_chain_links(prerequisite) if prerequisite is not None else []
    cleared_tiles = {link["target_tile"] for link in links if link["kind"] == "clear"}
    if kind == "clear" and prerequisite is not None:
        if cleared_tiles != {CLEARING_TARGETS[0]}:
            raise TerraformStagingError(
                "the prerequisite chain is not the staged clearing chain prefix"
            )
    if kind == "terraform":
        if prerequisite is None:
            raise TerraformStagingError(
                "the terraforming candidate requires a prerequisite attempt"
            )
        compiled = {op.tile_id for op in compiled_levelling()[2].ops if op.kind == "clear"}
        if cleared_tiles != compiled:
            raise TerraformStagingError(
                "the prerequisite chain does not bind the compiled clearing operations"
            )
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise TerraformStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    welcome = chain_world_welcome(prerequisite) if prerequisite is not None else retained_welcome()
    world, binding = stage_world_metadata(prerequisite, welcome)
    plan = plan_policy(kind, tile)
    if sha256(source_save_path(world)) != world["save_sha256"]:
        raise TerraformStagingError("staged world source save digest mismatch")
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
        composition, create_instance, version = staged_composition(kind)
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
        package = CLEAR_PACKAGE if kind == "clear" else TERRAFORM_PACKAGE
        for source in (package, AI_PACKAGE):
            for path in sorted(source.glob("*.nut")):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(path): sha256(path)
                for path in sorted(workspace.root.rglob("*"))
                if path.is_file() and path.name != ".admin-secret"
            }
        )
        # The exact runtime closure of the D3 execution path (including the
        # offline levelling compiler chain) and the exact installed
        # dependency bytes join the shared source_freeze() contract through
        # the same parameterized D2 machinery — never weakening it.
        frozen.update(d2_source_closure(D3_CLOSURE_ROOT))
        frozen.update(d2_dependency_inventory(D3_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D3_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_CLEARING if kind == "clear" else MILESTONE_TERRAFORMING,
            kind=kind,
            attempt=d3_attempt_name(kind, tile),
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
                    f"D3 {kind} handler runs as the retained CreateInstance subclass"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after.sav only; the retained "
                "source save, the prerequisite attempt record and every "
                "historical artifact stay untouched"
            ),
            plan_policy=plan,
            expected_readback=expected_readback_policy(kind),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.terrain_terraform_native",
                "run",
                str(directory),
            ],
            budgets=budgets_for(kind),
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
                    "pin derives from the sealed census classification page "
                    f"(p{plan['pinned']['page']:03d}) of the retained Seed 17 world"
                    if kind == "clear"
                    else (
                        "plan derives from the compiled levelling specification "
                        "against the sealed retained census; the proposal and "
                        "specification digests are pinned"
                    )
                ),
            ),
            environment=launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
        )
        if binding is not None:
            metadata["prerequisite"] = dict(
                schema=D3_PREREQUISITE_SCHEMA,
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


def d3_preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal of one staged D3 candidate.

    Opens nothing, consumes nothing: the seal, the frozen runtime closure,
    the census/compile pins, the world binding and the endpoint reservation
    are re-checked exactly like the D2 preflight, with the D3 lineage gates
    for the staged chain.
    """
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (
        directory / "PRELAUNCH.sha256"
    ).read_text().strip():
        raise ValueError("prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("one native attempt already consumed")
    verify_freeze(metadata["frozen"])
    require_frozen_d2_closure(metadata["frozen"], D3_CLOSURE_ROOT)
    require_frozen_d2_dependencies(metadata["frozen"], D3_CLOSURE_ROOT)
    kind = metadata["kind"]
    plan = metadata["plan_policy"]
    if metadata["attempt"] != d3_attempt_name(kind, plan["target_tile"]):
        raise ValueError("staged attempt identity drifted from its own scope")
    if kind == "clear":
        # Both staged world sources are legitimate clear candidates: the
        # chain's first clear stages the retained `before.sav` world; the
        # second stages the prerequisite attempt's replay-verified
        # `after.sav`. The sealed pin evidence is bit-identical either way.
        if metadata["world"]["mode"] not in (
            "RETAINED_SOURCE_SAVE_LOAD",
            "PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD",
        ) or plan["pinned"] != (census_pin(plan["target_tile"])):
            raise ValueError("sealed clearing pin drifted from the census evidence")
    else:
        _proposal, doc, spec = compiled_levelling()
        staged = terraform_schedule()
        if plan["schedule"] != staged or plan["plan_digest"] != plan_digest_of(staged):
            raise ValueError(
                "staged terraforming schedule drifted from the compiled specification"
            )
        for entry in staged:
            bridge = expectation_from_payload(entry)
            derived = intent_expectation(spec, entry["index"], doc)
            if not isinstance(derived, TerraformExpectation) or derived != bridge:
                raise ValueError(
                    f"a staged operation expectation drifted from the compiled "
                    f"specification (operation index {entry['index']})"
                )
        binding = prerequisite_source_binding(Path(metadata["prerequisite"]["directory"]))
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
    if world["mode"] == "RETAINED_SOURCE_SAVE_LOAD":
        binding_gate = staged_save_binding()
        if world["save_sha256"] != binding_gate["save_sha256"]:
            raise ValueError("retained source save binding drifted")
    else:
        binding_gate = {"save_sha256": world["save_sha256"]}
    verify_staged_source_save(binding_gate, Path(metadata["workspace"]) / "source.sav")
    composition, _, _ = staged_composition(kind)
    staged_identity = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME
    if staged_identity.joinpath("info.nut").read_bytes() != composition["info.nut"]:
        raise ValueError("staged GameScript identity drifted from the retained composition")
    if staged_identity.joinpath("main.nut").read_bytes() != composition["main.nut"]:
        raise ValueError("staged kind handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- D3 clearing ceremony (shared D2 machinery, D3 scope) --------------------


async def run_clearing_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute one authorized D3 clearing attempt through the D2 ceremony.

    The ceremony itself is the proven D2 ``execute_attempt``: preflight, claim
    consumption, launch boundary, welcome identity, four sealed exchanges,
    receipt and cleanup are the shared implementation, with the candidate's
    own D3 scope resolved from its staged facts at call time.
    """
    return await execute_attempt(prepared, backend, preflight_fn=d3_preflight)


# --- Wire protocol 3: secure session and one-launch backend ------------------


class TerraformSecureSession(SecureAdminSession):
    """Only the terraform operations extend the secure write policy."""

    def validate_outbound(self, frame: bytes) -> None:
        if self.state is not AuthState.ACTIVE:
            raise ValueError("encrypted ACTIVE stream required")
        if len(frame) < 3 or struct.unpack_from("<H", frame)[0] != len(frame):
            raise ValueError("invalid frame")
        if frame[2] == ADMIN_GAMESCRIPT:
            request = TerraformRequest.model_validate_json(decode_gamescript(frame[3:]))
            request.to_bytes()
        elif frame not in (gamescript_subscription(), encode_admin_quit()):
            super().validate_outbound(frame)


class TerraformNativeBackend(ClearingNativeBackend):
    """One-launch backend carrying the D3 lineage launch marker."""

    launch_marker_schema = D3_LAUNCH_CONSUMED_SCHEMA

    async def connect(self, prepared: PreparedProof, *, frame_observer) -> TerraformSecureSession:
        """Bind the staged runtime's Admin listener to one owned secure session."""
        if not any(
            r["table"] == "tcp" and r["local_port"] == prepared.endpoints[1] and r["state"] == 10
            for r in kernel_socket_rows()
        ):
            raise ValueError("native Admin listener readiness absent")
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        session = await TerraformSecureSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=key,
            frame_observer=frame_observer,
        )
        self.session = session
        return session


async def exchange(session, request: TerraformRequest, directory: Path) -> TerraformReadback:
    """One sealed protocol-3 exchange; every frame and file is retained."""
    raw = request.to_bytes()
    (directory / (request.request_id + "-request.json")).write_bytes(raw)
    await session.send(encode_gamescript(raw))
    decoder = AdminFrameDecoder()
    async with asyncio.timeout(10):
        while True:
            chunk = await session.receive()
            if not chunk:
                raise ConnectionError("terraform proof stream disconnected")
            for kind, payload in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected terraform-proof packet")
                response = decode_gamescript(payload)
                (directory / (request.request_id + "-response.json")).write_bytes(response)
                return TerraformReadback.parse_for(request, response)


async def execute_terraform_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt terraforming phase (never offline).

    Bounded protocol-3 ceremony against an authorized backend seam: preflight,
    operator claim consumption, launch boundary, world identity, session
    saves, then the compiled S-corner schedule in order. Every operation runs
    the nine bounded exchanges — inspection, three neighbor reads, the
    prelaunch-sealed terraform command, four intent-scoped independent
    verification reads — admission latches per operation, execution happens
    exactly once per scheduled op, and the first verification failure halts
    the phase: earlier verified receipts are preserved, later operations never
    execute, and the world state after a failed attempt is explicitly
    uncertain (nothing compensates or retries).
    """
    directory = prepared.directory
    d3_preflight(prepared)
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
    max_cost = metadata["plan_policy"]["max_cost"]
    result: dict[str, Any] = dict(
        preflight="PASS",
        native_launches=0,
        connections=0,
        requests=0,
        raised_ops=[],
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
            await wait_log(backend, prepared, TERRAFORM_READY_MARKER)
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

            def request(op, request_id, plan, tile, corner, direction):
                return TerraformRequest(
                    op=op,
                    request_id=request_id,
                    plan=plan,
                    company=0,
                    tile=tile,
                    corner=corner,
                    direction=direction,
                    max_cost=max_cost,
                )

            attempts: list[tuple[str, dict]] = []
            for position, entry in enumerate(schedule):
                label = f"op-{entry['index']:02d}"
                evidence: dict[str, Any] = {}
                try:
                    expectation = expectation_from_payload(entry)
                    before = await exchange(
                        session,
                        request(
                            "inspect",
                            f"inspect-{position:02d}",
                            seal,
                            entry["tile"],
                            entry["corner"],
                            entry["direction"],
                        ),
                        directory,
                    )
                    result["requests"] += 1
                    evidence["before"] = before
                    write_json(
                        directory / f"terraform-{position:02d}-before.json",
                        before.model_dump(mode="json"),
                    )
                    neighbors = []
                    for neighbor_position, tile_local in enumerate(
                        [
                            tile
                            for tile in expectation.sharing_tiles
                            if tile != expectation.host_tile
                        ]
                    ):
                        neighbors.append(
                            await exchange(
                                session,
                                request(
                                    "read",
                                    f"read-{position:02d}-{neighbor_position}",
                                    seal,
                                    tile_local,
                                    entry["corner"],
                                    entry["direction"],
                                ),
                                directory,
                            )
                        )
                        result["requests"] += 1
                    evidence["neighbors"] = neighbors
                    write_json(
                        directory / f"terraform-{position:02d}-neighbors.json",
                        [readback.model_dump(mode="json") for readback in neighbors],
                    )
                    intent = admit_terraform(
                        before,
                        neighbors,
                        expectation,
                        prelaunch_digest=seal,
                        source_save_digest=before_save,
                        max_cost=max_cost,
                    )
                    write_json(
                        directory / f"terraform-{position:02d}-intent.json",
                        intent.model_dump(mode="json"),
                    )
                    evidence["intent"] = intent
                    terraform_query = TerraformRequest(
                        op="terraform",
                        request_id=f"terraform-{position:02d}",
                        plan=seal,
                        company=intent.company,
                        tile=intent.tile,
                        corner=intent.expectation.corner,
                        direction=intent.expectation.direction,
                        max_cost=intent.max_cost,
                    )
                    if terraform_query.plan != intent.prelaunch_digest:
                        raise ValueError(
                            "dispatch refused: the terraform plan does not bind this admission"
                        )
                    result["dispatch_state"] = "DISPATCHED_UNKNOWN"
                    result["dispatched_op"] = label
                    built = await exchange(session, terraform_query, directory)
                    result["requests"] += 1
                    result["dispatch_state"] = "CONFIRMED"
                    result["last_status"] = built.status
                    evidence["built"] = built
                    write_json(
                        directory / f"terraform-{position:02d}-built.json",
                        built.model_dump(mode="json"),
                    )
                    independent = []
                    for verify_position, tile_local in enumerate(expectation.sharing_tiles):
                        independent.append(
                            await exchange(
                                session,
                                TerraformRequest(
                                    op="read",
                                    request_id=f"verify-{position:02d}-{verify_position}",
                                    plan=intent.digest,
                                    company=intent.company,
                                    tile=tile_local,
                                    corner=intent.expectation.corner,
                                    direction=intent.expectation.direction,
                                    max_cost=intent.max_cost,
                                ),
                                directory,
                            )
                        )
                        result["requests"] += 1
                    evidence["independent"] = independent
                    write_json(
                        directory / f"terraform-{position:02d}-independent.json",
                        [readback.model_dump(mode="json") for readback in independent],
                    )
                    verify_terraform(intent, before, neighbors, built, independent)
                    attempts.append((label, evidence))
                    result["raised_ops"].append(label)
                    result["command_accepted"] = True
                    result["state_changed"] = True
                except Exception as error:
                    attempts.append((label, evidence))
                    result["halt"] = dict(
                        label=label, error=type(error).__name__ + ": " + str(error)
                    )
                    break
            phase = terraform_phase_outcome(attempts)
            result["phase"] = phase
            if phase["verification"] == "PHASE_COMPLETE":
                if len(attempts) != len(schedule):
                    raise ValueError("phase completion evidence drifted from the staged schedule")
                after_save = await save(backend, prepared, "after")
                write_json(
                    directory / "receipt.json",
                    dict(phase, before_save_sha256=before_save, after_save_sha256=after_save),
                )
                result["verified"] = True
                result["status"] = "NATIVE_TERRAFORM_VERIFIED"
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
            if result["status"] == "NATIVE_TERRAFORM_VERIFIED":
                result["verified"] = False
                result["status"] = "FAILED"
                result["error"] = (
                    "ValueError: retained script log health findings deny the verified receipt"
                )
        if result["returncode"] not in (None, 0):
            if result["status"] == "NATIVE_TERRAFORM_VERIFIED":
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


# --- D3 phase replay verification -------------------------------------------


def _scheduled_request_ids(schedule: list[dict]) -> set[str]:
    """Every request id the staged schedule can legitimately produce."""
    ids: set[str] = set()
    for position, entry in enumerate(schedule):
        ids.add(f"inspect-{position:02d}")
        ids.add(f"terraform-{position:02d}")
        expectation = expectation_from_payload(entry)
        for neighbor_position in range(len(expectation.sharing_tiles) - 1):
            ids.add(f"read-{position:02d}-{neighbor_position}")
        for verify_position in range(len(expectation.sharing_tiles)):
            ids.add(f"verify-{position:02d}-{verify_position}")
    return ids


def _parse_phase_frames(directory: Path):
    """Parse the retained frame stream of the owned secure session."""
    frames = json.loads((directory / "frames.json").read_text())
    outbound: list[bytes] = []
    replies: list[bytes] = []
    outbound_requests: list[TerraformRequest] = []
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
                query = TerraformRequest.model_validate_json(payload)
            except Exception:
                raise ValueError("outbound frame contains invalid TerraformRequest") from None
            outbound_requests.append(query)
            request_positions[payload] = index
        else:
            for kind, body in AdminFrameDecoder().feed_frames(frame):
                # The retained session stream also carries the handshake and
                # keepalive frames; only the gamescript exchanges are proof
                # material (the shared D2 chronology semantics).
                if kind != SERVER_GAMESCRIPT:
                    continue
                reply = decode_gamescript(body)
                if reply not in reply_positions:
                    reply_positions[reply] = index
                replies.append(reply)
    return outbound, outbound_requests, replies, request_positions, reply_positions


def verify_terraform_attempt(directory: Path) -> dict:
    """Replay retained protocol-3 phase semantics; never trust a success label.

    The replay re-derives every retained fact independently: the operator
    authorization evidence, the compiled schedule, the captured session
    frames and every per-operation exchange pair, then re-verifies the whole
    phase with the production
    :func:`app.simulation.openttd.terrain_terraform.terraform_phase_outcome`.
    A success label alone is never evidence.
    """
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    claims = json.loads((directory / "CLAIM.json").read_text())
    if claims.get("prelaunch_digest") != seal:
        raise ValueError("attempt claim does not match its prelaunch seal")
    for line in (directory / "artifact-manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError("artifact manifest mismatch")
        if sha256(directory / name) != digest:
            raise ValueError("artifact manifest mismatch")
    if metadata.get("schema") != D3_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D3_PRELAUNCH_SCHEMA} lineage; no verified receipt is possible"
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
    schedule = terraform_schedule()
    if plan["schedule"] != schedule or plan["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("staged terraforming schedule drifted from the compiled specification")
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["encrypted"] is not True or runtime["welcome"]["revision"] != "15.3":
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    outbound, outbound_requests, replies, request_positions, reply_positions = (
        _parse_phase_frames(directory)
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("terraform request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [TerraformRequest.model_validate_json(path.read_bytes()) for path in paths]
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
            readback = TerraformReadback.model_validate_json(path.read_bytes())
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
    for position, entry in enumerate(schedule):
        label = f"op-{entry['index']:02d}"
        if halted_position is None and isinstance(halt_record, dict) and (
            halt_record.get("label") == label
        ):
            halted_position = position
        pending = halted_position is not None and position > halted_position
        evidence: dict[str, Any] = {}
        if not pending:
            for name, resolve in (
                ("before", TerraformReadback.model_validate),
                ("intent", None),
                ("built", TerraformReadback.model_validate),
            ):
                path = directory / f"terraform-{position:02d}-{name}.json"
                if path.is_file():
                    try:
                        if name == "intent":
                            # JSON arrays cannot strict-coerce into the
                            # expectation tuples; the retained bytes load
                            # through pydantic's own JSON parser (the shared
                            # D2 retained-file parsing semantics).
                            evidence[name] = TerraformIntent.model_validate_json(path.read_bytes())
                        else:
                            evidence[name] = resolve(json.loads(path.read_text()))
                    except ValueError:
                        continue
            lists = {}
            for name in ("neighbors", "independent"):
                path = directory / f"terraform-{position:02d}-{name}.json"
                if not path.is_file():
                    continue
                try:
                    stored = json.loads(path.read_text())
                    lists[name] = tuple(TerraformReadback.model_validate(item) for item in stored)
                except ValueError:
                    continue
            evidence.update(lists)
            intent = evidence.get("intent")
            if intent is not None:
                if intent.prelaunch_digest != seal:
                    raise ValueError("an admitted intent does not bind its candidate seal")
                if intent.source_save_digest != sha256(directory / "session-before.sav"):
                    raise ValueError("an admitted intent does not bind the session-before save")
                if intent.expectation != expectation_from_payload(entry):
                    raise ValueError("an admitted intent drifted from the staged schedule")
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
                if TerraformReadback.parse_for(query, raw).digest != intent.before_digest:
                    raise ValueError("retained admission evidence does not bind its exchange")
                if inspection is not None and inspection.digest != intent.before_digest:
                    raise ValueError("retained inspection evidence drifted from its exchange")
        attempts.append((label, evidence))
    phase = terraform_phase_outcome(attempts)
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
    if result["status"] == "NATIVE_TERRAFORM_VERIFIED":
        if phase["verification"] != "PHASE_COMPLETE":
            raise ValueError("verified receipt contradicts its phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("verified receipt contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("verified receipt contradicts its launch/connection seal")
        if len(result.get("raised_ops", [])) != len(schedule) or not cleanup_complete:
            raise ValueError("verified receipt cleanup or raised inventory incomplete")
        if len(outbound_requests) != PLANNED_TERRAFORM_REQUESTS:
            raise ValueError("verified receipt request inventory drifted from the schedule")
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            raise ValueError("verified receipt record missing")
        expected = dict(
            phase,
            before_save_sha256=sha256(directory / "session-before.sav"),
            after_save_sha256=sha256(directory / "after.sav"),
        )
        # JSON round-trip both sides: the retained record stores serialized
        # arrays where the recomputed receipts hold python tuples; identity
        # semantics (not container type) define the replay match.
        if json.loads(receipt_path.read_text()) != json.loads(json.dumps(expected)):
            raise ValueError("retained terraforming receipt replay mismatch")
        return dict(verification="RECEIPT_VERIFIED", receipt=expected)
    if result["status"] in ("PHASE_HALTED_PREFIX_PRESERVED", "FAILED", "FAILED_CLEANUP"):
        if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED" and (
            phase["verification"] != "PARTIAL_EXECUTION_EVIDENCE"
            or phase["failed"] is None
            or not isinstance(halt_record, dict)
            or phase["failed"].get("label") != halt_record.get("label")
            or len(result.get("raised_ops", [])) != len(phase["completed"])
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
            completed=[receipt.get("tile") for receipt in phase["completed"]],
            failed=phase["failed"],
            pending=phase["pending"],
            error=result.get("error") or (phase["failed"] or {}).get("error"),
        )
    return dict(
        verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
        result_status=result.get("status", "UNKNOWN"),
        error=result.get("error"),
    )


def verify_script_attempt(metadata: dict, directory: Path) -> dict:
    """Dispatch one staged D3 clearing attempt to the shared replay verifier."""
    return verify_clearing_attempt_record(
        directory,
        lineage_schema=D3_PRELAUNCH_SCHEMA,
        sealed_pin=metadata["plan_policy"]["pinned"],
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
    parser.add_argument("--kind", choices=KINDS, default="clear")
    parser.add_argument("--prerequisite", type=Path, default=None)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_candidate(directory, kind=args.kind, prerequisite=args.prerequisite)
        d3_preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        d3_preflight(reopen_candidate(directory))
        print("PREFLIGHT PASS")
    elif args.command == "verify":
        metadata = read_prelaunch(directory)
        if metadata.get("kind") == "clear":
            verdict = verify_script_attempt(metadata, directory)
        else:
            verdict = verify_terraform_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
    else:
        metadata = read_prelaunch(directory)
        if metadata["kind"] == "clear":
            result = asyncio.run(
                run_clearing_attempt(
                    reopen_candidate(directory),
                    ClearingNativeBackend(authorized_one_launch=True),
                )
            )
        else:
            result = asyncio.run(
                execute_terraform_attempt(
                    reopen_candidate(directory),
                    TerraformNativeBackend(authorized_one_launch=True),
                )
            )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_status(result))


if __name__ == "__main__":
    main()
