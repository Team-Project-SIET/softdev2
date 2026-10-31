"""D5-CORRIDOR-EXTENSION-1 native staging pipeline (offline preparation only).

The terrain-aware D5 corridor-extension recovery design extends the built D4
corridor with a south branch OUTSIDE the corner influence the D3 terraforming
raised along the delivery terrace: the halted predecessor attempt proved the
delivery-edge ground live-sloped (native slope 9 at the planned stop 50607
and 8 at its front 50608, while the retained census graded both flat), so
the moved branch is a vertical ``full`` run 50096..50864 (run_len 4, east of
the delivery front, past the corner points (175..176, 190..197) the D3
raise receipts lifted), with live escarpment slopes 12/12/8 on
50096/50352/50608 fixed by the consumed D5-TERRAIN-SURVEY-1 evidence of
record (admission facts for the native previews, never census-flat claims),
a horizontal ``road`` join 50095-50096 ties the
branch head to the delivery front's company road, and a NEW truck stop
50863 fronts the branch end 50864 built with ``GSStation.STATION_NEW``
— a new distinct station that must never merge into the corridor's station
``sid`` 0 (pickup 45748) or ``sid`` 1 (delivery 50351). The GameScript
package (``app/simulation/openttd/d5_extension_package``) is already
review-verified by the VM tests; this module is its staging/execution/replay
pipeline, built by import — never copy — from the proven ceremony modules
(``corridor_construction_native`` for the protocol-4 exchange groups and the
shared D2 gates, ``corridor_freight_native`` for the shared D4 candidate-5
after-save prerequisite binding, ``corridor_accept_survey_native``'s shape
for the staged-candidate staging).

The ``D5-FREIGHT-1``, ``D5-ACCEPT-SURVEY-1`` and the consumed
D5-CORRIDOR-EXTENSION-1 candidate identities are consumed forever; this
pipeline derives from the same authoritative D4 candidate-5 after-save as a
NEW derived candidate: the source save is copied fresh per staging and never
mutated. Nothing here launches OpenTTD, connects to a port, writes a claim
or mutates any world or retained artifact. The module implements no
acceptance logic at all: the prelaunch/policy state, and the verified
receipt carries verbatim, that "acceptance recheck happens in a separate
read-only survey session on this attempt's after-save, before any freight
order or vehicle purchase" — the survey pipeline is that separate instrument.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.corridor_accept_survey import FUNDS_AT_D4_CLOSE
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
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
    encode_gamescript,
)
from app.simulation.openttd.proof import corridor_construction_native as d4
from app.simulation.openttd.proof import corridor_freight_native as freight_native
from app.simulation.openttd.proof.classification_capture import script_log_health_findings
from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints
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
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthState

PACKAGES = Path(__file__).resolve().parents[1]
EXTENSION_PACKAGE = PACKAGES / "d5_extension_package"
AI_PACKAGE = PACKAGES / "road_company_package"
EXTENSION_CLOSURE_ROOT = "app.simulation.openttd.proof.corridor_extension_native"

KIND = "corridor-extension"
MILESTONE_EXTENSION = "D5-CORRIDOR-EXTENSION"
EXTENSION_ATTEMPT = "D5-CORRIDOR-EXTENSION-2"
D5_EXTENSION_PRELAUNCH_SCHEMA = "d5-corridor-extension-prelaunch-v1"
# The shared prerequisite/launch lineage records (same D4 candidate-5 world,
# same one-launch consumed marker family).
D5_EXTENSION_PREREQUISITE_SCHEMA = freight_native.D5_FREIGHT_PREREQUISITE_SCHEMA
D5_EXTENSION_LAUNCH_CONSUMED_SCHEMA = freight_native.D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA
PINNED_PREREQUISITE = freight_native.PINNED_PREREQUISITE
PINNED_PREREQUISITE_AFTER_SAVE = freight_native.PINNED_PREREQUISITE_AFTER_SAVE

# Funds pin: the D4 close-out balance is the only authorized starting bank
# balance; every exchange is cross-checked against 492149 minus the sum of the
# verified prefix's native costs.
FUNDS_PIN = FUNDS_AT_D4_CLOSE

# --- Retained D5-TERRAIN-SURVEY-1 evidence of record (fail-closed reader) ----
#
# The consumed D5-TERRAIN-SURVEY-1 native survey candidate observed, with
# zero world mutation and a byte-bound receipt per exchange, the same D4
# candidate-5 after-save world this extension stages on. Its identity is
# consumed forever and is never reused; this module reads its retained
# ``result.json`` as EVIDENCE OF RECORD only. The survey never proves road
# or station buildability: it fixes the live facts the pre-admission gate's
# native test-mode previews are quoted against.
PINNED_TERRAIN_SURVEY = (
    PROJECT / "artifacts/experiments/d5-terrain-survey-native-candidate-1"
).resolve()
TERRAIN_SURVEY_PLAN_DIGEST = "be3be5570181f16948cb60c090ca831861eb244856d191156eb14de6e48a5324"
TERRAIN_SURVEY_SEAL = "ee0f21af5c8360476fd004c32ac4a3841eb070a457280fc2c735100cc1a88751"
TERRAIN_SURVEY_RADIUS = 3
# The receipt-bound terrain frame of record per pinned branch tile. The
# escarpment ramp slopes 12/12/8 on 50096/50352/50608 are the survey's own
# findings (the census graded the whole band flat): 15.3 admits a straight
# road over such tiles with a foundation price, so they are priced by the
# native previews, never folded into a census-flat claim. 50095 is the built
# company road (hence road=True and buildable=False exactly as observed).
TERRAIN_SURVEY_TILES: dict[int, dict] = {
    50095: dict(slope=0, min_height=2, max_height=2, buildable=False, road=True),
    50096: dict(slope=12, min_height=1, max_height=2, buildable=True, road=False),
    50352: dict(slope=12, min_height=1, max_height=2, buildable=True, road=False),
    50608: dict(slope=8, min_height=1, max_height=2, buildable=True, road=False),
    50864: dict(slope=0, min_height=1, max_height=1, buildable=True, road=False),
    50863: dict(slope=0, min_height=1, max_height=1, buildable=True, road=False),
}
TERRAIN_SURVEY_OWNER = {tile: 0 if tile == 50095 else -1 for tile in TERRAIN_SURVEY_TILES}
TERRAIN_SURVEY_ACCEPTANCE = {50351: 0, 50863: 8}


def terrain_survey_facts(survey: Path | None = None) -> dict:
    """The fail-closed reader of the retained terrain-survey receipts.

    Consumed D5-TERRAIN-SURVEY-1 identity only (never reused): the retained
    ``result.json`` must be a verified zero-mutation observation on the
    pinned plan digest/seal/world, and every receipted fact must equal the
    tile frame of record above; any drift, absence or re-label refuses
    :class:`ExtensionStagingError`. Returns the digestible evidence record
    bound into the staged prelaunch pins.
    """
    survey = PINNED_TERRAIN_SURVEY if survey is None else survey
    result_path = Path(survey) / "result.json"
    if not result_path.is_file():
        raise ExtensionStagingError("the retained terrain-survey evidence is absent")
    try:
        result = json.loads(result_path.read_text())
    except (ValueError, UnicodeDecodeError) as error:
        raise ExtensionStagingError(
            "the retained terrain-survey evidence is not parseable"
        ) from error
    if (
        result.get("status") != "NATIVE_TERRAIN_COMPLETE"
        or result.get("verified") is not True
        or result.get("state_changed") is not False
        or result.get("cleanup_complete") is not True
        or result.get("preflight") != "PASS"
    ):
        raise ExtensionStagingError(
            "the retained terrain-survey outcome is not a verified zero-mutation observation"
        )
    phase = result.get("phase") or {}
    if (
        phase.get("verification") != "SURVEY_COMPLETE"
        or phase.get("failed") is not None
        or phase.get("pending") != []
        or phase.get("plan_digest") != TERRAIN_SURVEY_PLAN_DIGEST
        or phase.get("seal") != TERRAIN_SURVEY_SEAL
        or phase.get("radius") != TERRAIN_SURVEY_RADIUS
        or phase.get("funds") != FUNDS_PIN
    ):
        raise ExtensionStagingError("the retained terrain-survey identity drifted")
    terra = phase.get("terra") or {}
    tiles = {}
    for tile, expected in TERRAIN_SURVEY_TILES.items():
        entry = terra.get(str(tile))
        if not isinstance(entry, dict) or entry.get("request_id") is None:
            raise ExtensionStagingError(
                f"the retained terrain-survey tile {tile} is not a receipted observation"
            )
        drifted = {
            key: (entry.get(key), value)
            for key, value in {**expected, "owner": TERRAIN_SURVEY_OWNER[tile]}.items()
            if entry.get(key) != value
        }
        if drifted:
            raise ExtensionStagingError(
                f"the retained terrain-survey facts for {tile} drifted: {drifted}"
            )
        # The road-tile premise on 50095 never lowers the flag bar: a road
        # tile of record that nonetheless receipts a tree is still an
        # obstructing world, so `tree` is checked on every tile.
        flags = ("tree", "water", "coast", "farm", "rock", "rough", "rail", "air_transport")
        if any(entry.get(flag) is not False for flag in flags):
            raise ExtensionStagingError(
                f"the retained terrain-survey tile {tile} carries an obstructing flag"
            )
        tiles[str(tile)] = dict(expected, owner=TERRAIN_SURVEY_OWNER[tile])
    observations = {}
    acceptance = phase.get("observations") or {}
    for tile, value in TERRAIN_SURVEY_ACCEPTANCE.items():
        entry = acceptance.get(str(tile))
        if not isinstance(entry, dict) or entry.get("value") != value:
            raise ExtensionStagingError(
                f"the retained terrain-survey acceptance for {tile} drifted"
            )
        observations[str(tile)] = int(entry["value"])
    return dict(
        schema="d5-terrain-survey-evidence-v1",
        directory=str(Path(survey)),
        plan_digest=TERRAIN_SURVEY_PLAN_DIGEST,
        seal=TERRAIN_SURVEY_SEAL,
        world_save=PINNED_PREREQUISITE_AFTER_SAVE,
        tiles=tiles,
        acceptance=observations,
        statement=(
            "the consumed read-only survey is evidence of record only: it "
            "never proves road or station buildability; the branch run "
            "tiles' measured escarpment slopes (12/12/8) are admission "
            "facts for the native test-mode previews, never census-flat "
            "claims"
        ),
    )


EXTENSION_READY_MARKER = "D5_EXT_READY"
EXTENSION_SCHEDULE_VERSION = 1
PER_OP_MAX_COST = 2000

# Wire bounds stay the D4 protocol-4 gates: requests at 512 bytes, responses
# at 640 (the 30-tile route echo is the largest legal reply).
PLANNED_EXTENSION_REQUESTS = 10
EXTENSION_REQUEST_BUDGET = 16

ACCEPTANCE_RECHECK_STATEMENT = (
    "acceptance recheck happens in a separate read-only survey session on "
    "this attempt's after-save, before any freight order or vehicle purchase"
)

# The pinned approved design (the terrain-aware D5 recovery spec's own
# schedule; the delivery terrace's raised corner evidence excluded the
# halted predecessor's stop tile 50607 and moved the branch stop to 50608's
# south neighbour row). The staged derivation must equal this exactly or
# staging refuses.
PINNED_WITNESS = (
    45748,
    45747,
    45746,
    45745,
    45744,
    45743,
    45999,
    46255,
    46511,
    46767,
    47023,
    47279,
    47535,
    47791,
    48047,
    48303,
    48559,
    48815,
    49071,
    49327,
    49583,
    49839,
    50095,
    50351,
    50095,
    50096,
    50352,
    50608,
    50864,
    50863,
)


class ExtensionStagingError(d4.CorridorStagingError):
    """Offline D5 extension staging or pin derivation failed; nothing ran."""


# --- Schedule derivation: never hand-written -------------------------------

D4_ROUTE_READ_EVIDENCE = PINNED_PREREQUISITE / "corridor-route-read.json"


def corridor_station_sids() -> tuple[int, ...]:
    """The station sids the built D4 corridor evidence reports.

    The dataset of record for the station-merge defect class: the pickup stop
    (45748) and the delivery stop (50351) hold these sids in the built
    corridor; the extension's NEW station must read a sid outside them.
    """
    evidence = json.loads(D4_ROUTE_READ_EVIDENCE.read_text())
    sids = tuple(sorted({int(evidence["pickup_sid"]), int(evidence["delivery_sid"])}))
    if len(sids) != 2 or any(sid < 0 for sid in sids):
        raise ExtensionStagingError("the built corridor station ids are not the pinned pair")
    return sids


def built_route_witness() -> tuple[int, ...]:
    """The built corridor's witnessed path from its own retained evidence."""
    return tuple(int(tile) for tile in json.loads(D4_ROUTE_READ_EVIDENCE.read_text())["tiles"])


def _adjacent(a: int, b: int) -> bool:
    return abs(a % 256 - b % 256) + abs(a // 256 - b // 256) == 1


def _compiled_corridor() -> tuple[int, ...]:
    """The compiled D4 corridor witness, hard-checked against its pins."""
    corridor = tuple(int(tile) for tile in d4.corridor_facts()["corridor"])
    if corridor[:2] != (45748, 45747) or corridor[-2:] != (50095, 50351) or len(corridor) != 24:
        raise ExtensionStagingError("the corridor witness is not the pinned D4 corridor")
    if built_route_witness() != corridor:
        raise ExtensionStagingError("the built route evidence drifted from the compiled corridor")
    return corridor


def _vacant_census_pin(tile: int, entry: dict) -> dict:
    """The census Vacant-equivalent predicates for one derived pin."""
    facts = dict(
        tile_id=int(entry["tile_id"]),
        x=int(entry["x"]),
        y=int(entry["y"]),
        buildable=entry["buildable"] is True,
        slope=int(entry["slope"]),
        tree=entry["tree"] is True,
        water=entry["water"] is True,
        water_transport=entry["water_transport"] is True,
        coast=entry["coast"] is True,
        farm=entry["farm"] is True,
        rock=entry["rock"] is True,
        rough=entry["rough"] is True,
        road=entry["road"] is True,
    )
    if not facts["buildable"] or facts["slope"] != 0:
        raise ExtensionStagingError(
            f"the derived branch pin {tile} is not buildable flat census ground"
        )
    if any(
        facts[name]
        for name in ("tree", "water", "water_transport", "coast", "farm", "rock", "rough")
    ):
        raise ExtensionStagingError(f"the derived branch pin {tile} carries an obstructing fact")
    return facts


def network_pins() -> dict:
    """Arithmetic derivation of the south branch pins with its evidence gates.

    Every number comes from the compiled corridor witness and the map width;
    the derived pins are then validated against the retained census vacancy
    predicates and the built-corridor exclusion facts. Any drift is an
    :class:`ExtensionStagingError` — the branch is never hand-pinned.
    """
    corridor = _compiled_corridor()
    depot = dict(d4.corridor_facts()["depot"])
    delivery_front = corridor[-2]
    delivery_stop = corridor[-1]
    branch_full_start = delivery_front + 1
    # Terrain-aware recovery: the terraform-receipt corner arithmetic drove a
    # live native slope onto the delivery terrace's old stop tile, so the stop
    # moves one full tile row further south (south-front row). The stop's own
    # live slope is a native UNKNOWN until the zero-mutation pre-admission
    # chain proves the station op buildable; the census pin below stays a
    # census predicate only, never a live-slope claim.
    branch_stop = delivery_stop + 512
    branch_front = branch_stop + 1
    branch_run = [branch_full_start + i * 256 for i in range(4)]
    run_len = (branch_front - branch_full_start) // 256 + 1
    if run_len != 4 or branch_run[-1] != branch_front:
        raise ExtensionStagingError("the derived branch run does not tie the stop front")
    census = d4._retained_network_facts()
    facts_by_id = {int(entry["tile_id"]): entry for entry in census["tiles"]}
    pins: dict[int, dict] = {}
    for tile in [delivery_front, *branch_run, branch_stop]:
        if tile not in facts_by_id:
            raise ExtensionStagingError(f"the derived branch pin {tile} lacks its census row")
        pins[tile] = _vacant_census_pin(tile, facts_by_id[tile])
    built = set(corridor) | set(built_route_witness())
    for tile in (*branch_run, branch_stop, branch_front):
        if tile in built:
            raise ExtensionStagingError(
                f"the derived branch pin {tile} overlaps the built D4 corridor"
            )
    return dict(
        delivery_front=delivery_front,
        delivery_stop=delivery_stop,
        depot=int(depot["tile_id"]),
        depot_front=int(depot["front_tile_id"]),
        branch_full_start=branch_full_start,
        branch_full_end=branch_front,
        branch_stop=branch_stop,
        branch_front=branch_front,
        branch_run=tuple(branch_run),
        run_len=run_len,
        census_pins={
            tile: dict(facts, x=tile % 256, y=tile // 256) for tile, facts in pins.items()
        },
    )


def extension_witness() -> tuple[int, ...]:
    """The ordered 30-tile extended-corridor witness path.

    The D4 witness first (verified equal to the compiled corridor and to the
    built route-read evidence), then the retraced delivery front and the
    branch run tiles, standing on the new branch stop last.
    """
    pins = network_pins()
    witness = tuple(
        list(_compiled_corridor())
        + [pins["delivery_front"], *pins["branch_run"], pins["branch_stop"]]
    )
    for a, b in zip(witness, witness[1:]):
        if not _adjacent(a, b):
            raise ExtensionStagingError(f"the extended witness pair {a}->{b} is not adjacent")
    return witness


# --- Derived schedule (validated against the approved design) ----------------


def extension_schedule() -> list[dict]:
    """The staged three-op extension schedule, derived from evidence.

    Op-0 is the branch ``full`` run 50096..50864 (east of the delivery
    front, on vacant census ground); op-1 the ``road`` join 50095-50096
    (second because ``road`` eligibility requires both endpoints to be
    company road already); op-2 the branch truck stop 50863 fronting
    50864. The production wire contract's own adjacency semantics are the
    schedule's gates; the derived schedule must also equal the pinned
    approved design exactly.
    """
    pins = network_pins()
    corridor = list(_compiled_corridor())
    schedule = [
        dict(
            kind="full",
            index=0,
            start=pins["branch_full_start"],
            end=pins["branch_full_end"],
            run_len=int(pins["run_len"]),
            tiles=list(pins["branch_run"]),
        ),
        dict(
            kind="road",
            index=1,
            start=pins["delivery_front"],
            end=pins["branch_full_start"],
            run_len=2,
            tiles=[pins["delivery_front"], pins["branch_full_start"]],
        ),
        dict(
            kind="station",
            index=2,
            tile=pins["branch_stop"],
            front=pins["branch_front"],
            stop_role="delivery",
        ),
    ]
    _validate_schedule_shape(schedule, corridor=corridor)
    if tuple(extension_witness()) != PINNED_WITNESS:
        raise ExtensionStagingError(
            "the derived extended witness drifted from the pinned approved witness"
        )
    if schedule != [
        dict(
            kind="full",
            index=0,
            start=50096,
            end=50864,
            run_len=4,
            tiles=[50096, 50352, 50608, 50864],
        ),
        dict(kind="road", index=1, start=50095, end=50096, run_len=2, tiles=[50095, 50096]),
        dict(kind="station", index=2, tile=50863, front=50864, stop_role="delivery"),
    ]:
        raise ExtensionStagingError("the derived schedule drifted from the approved design")
    return schedule


def _validate_schedule_shape(schedule: list[dict], *, corridor: list[int]) -> None:
    indexes = [entry["index"] for entry in schedule]
    if indexes != list(range(len(schedule))):
        raise ExtensionStagingError("the extension schedule order drifted")
    for entry in schedule:
        if entry["kind"] not in ("full", "road", "station", "depot"):
            raise ExtensionStagingError("a scheduled extension op carries an unknown kind")
        if entry["kind"] in ("full", "road"):
            start, end = entry["start"], entry["end"]
            if start is None or end is None or not 0 <= start <= 0xFFFF or not 0 <= end <= 0xFFFF:
                raise ExtensionStagingError("an extension road pin exceeds the tile bound")
            dx = abs(start % 256 - end % 256)
            dy = abs(start // 256 - end // 256)
            if entry["kind"] == "full":
                if (dx != 0 and dy != 0) or not 1 <= dx + dy <= MAX_FULL_SPAN:
                    raise ExtensionStagingError(
                        "the branch full run is not a bounded straight axis"
                    )
                if entry["run_len"] != dx + dy + 1:
                    raise ExtensionStagingError("the branch run length drifted from its span")
                if any(tile in corridor for tile in entry["tiles"]):
                    raise ExtensionStagingError("the branch run overlaps the built corridor")
            else:
                if dx + dy != 1:
                    raise ExtensionStagingError("the join endpoints are not adjacent")
        else:
            tile, front = entry["tile"], entry["front"]
            if not _adjacent(tile, front):
                raise ExtensionStagingError("an extension site front is not adjacent")
            if tile in corridor or front in corridor:
                raise ExtensionStagingError("the branch stop overlaps the built corridor")
    if schedule[1]["end"] != schedule[0]["start"]:
        raise ExtensionStagingError("the join does not tie the delivery front to the branch head")
    if schedule[2]["front"] != schedule[0]["end"]:
        raise ExtensionStagingError("the branch stop does not front the branch run end")


def extension_route_policy() -> dict:
    """The pure-observation scope of the final extended route read."""
    witness = extension_witness()
    pins = network_pins()
    return dict(
        witness_path=list(witness),
        expected_pairs=len(witness) - 1,
        pickup=int(witness[0]),
        pickup_front=int(witness[1]),
        delivery=int(witness[23]),
        delivery_front=int(witness[22]),
        depot=pins["depot"],
        depot_front=pins["depot_front"],
        branch_full_start=pins["branch_full_start"],
        branch_stop=pins["branch_stop"],
        statement=(
            "the route read is pure observation of the ordered 30-tile witness, "
            "never a build assertion; only consecutive-pair connectivity counts"
        ),
    )


# --- Plan policy / budgets / readback discipline -----------------------------


def extension_plan_policy() -> dict:
    """The authorized plan policy of the staged extension candidate."""
    schedule = extension_schedule()
    if schedule[0]["kind"] != "full" or schedule[0]["index"] != 0:
        raise ExtensionStagingError("the staged schedule must begin with the branch full run")
    pins = network_pins()
    return dict(
        company=0,
        target_tile=int(schedule[0]["start"]),
        max_cost=PER_OP_MAX_COST,
        command="GSRoad.BuildRoadFull + GSRoad.BuildRoad + GSRoad.BuildRoadStation",
        stale_rule=(
            "re-observe every pin of each op immediately before admission; "
            "any mismatch stops the phase without any command and preserves "
            "the verified prefix"
        ),
        identity=(
            "wire contract protocol 4: the command request presents the "
            "prelaunch seal the inspect latched; the independent verification "
            "read presents the admitted intent digest, and the final route "
            "read carries the prelaunch seal as pure observation"
        ),
        schedule=schedule,
        plan_digest=plan_digest_of(schedule),
        schedule_version=EXTENSION_SCHEDULE_VERSION,
        route=extension_route_policy(),
        station=dict(
            statement=(
                "the branch stop build pins GSStation.STATION_NEW: a distinct "
                "new station is the pinned design; a readback sid equal to the "
                "existing station ids 0 or 1 is a FAIL-CLOSED station-merge "
                "defect and refuses the whole attempt"
            ),
            existing_sids=list(corridor_station_sids()),
        ),
        acceptance_recheck=dict(
            statement=ACCEPTANCE_RECHECK_STATEMENT,
            instrument="app.simulation.openttd.proof.corridor_accept_survey_native",
        ),
        funds_initial=FUNDS_PIN,
        funds_rule=(
            "funds are read back on every exchange and cross-checked against "
            f"{FUNDS_PIN} minus the verified prefix's native costs; any drift "
            "is a prefix-preserving halt"
        ),
        world=dict(
            pickup=int(PINNED_WITNESS[0]),
            pickup_front=int(PINNED_WITNESS[1]),
            delivery=int(PINNED_WITNESS[23]),
            delivery_front=int(PINNED_WITNESS[22]),
            depot=pins["depot"],
            depot_front=pins["depot_front"],
            branch_full_start=int(PINNED_WITNESS[25]),
            branch_run=[int(tile) for tile in PINNED_WITNESS[25:29]],
            branch_stop=int(PINNED_WITNESS[29]),
            expected_funds=FUNDS_PIN,
            per_op_max_cost=PER_OP_MAX_COST,
            request_budget=EXTENSION_REQUEST_BUDGET,
            statement=(
                "the staged extension world is the D4 candidate-5 close-out; the "
                "branch pins are the derived census-vacant tiles and the built "
                "corridor is never rebuilt, reordered or touched"
            ),
        ),
        coverage=d4.coverage_pins(),
    )


def extension_budgets() -> dict:
    """The staged budget table for the extension candidate."""
    return dict(
        launches=1,
        connection_attempts=1,
        requests=EXTENSION_REQUEST_BUDGET,
        planned_exchanges=PLANNED_EXTENSION_REQUESTS,
        gsadmin_bytes=512,
        response_bytes=MAX_CORRIDOR_RESPONSE_BYTES,
        retries=0,
        reconnects=0,
        readiness_seconds=45,
        request_seconds=10,
        total_seconds=600,
        per_op_max_cost=PER_OP_MAX_COST,
        expected_funds=FUNDS_PIN,
    )


def _require_extension_policy(policy: dict) -> dict:
    """The extension-specific fail-closed fields every policy record carries."""
    needed = ("station", "acceptance_recheck", "funds_initial", "world", "route")
    if any(name not in policy for name in needed):
        raise ExtensionStagingError("a policy record lacks an extension-specific key")
    if policy["station"]["statement"] != extension_plan_policy()["station"]["statement"]:
        raise ExtensionStagingError("the station-merge discipline sentence drifted")
    if policy["station"]["existing_sids"] != list(corridor_station_sids()):
        raise ExtensionStagingError("the station-merge dataset drifted from the built evidence")
    if policy["acceptance_recheck"]["statement"] != ACCEPTANCE_RECHECK_STATEMENT:
        raise ExtensionStagingError("the acceptance-recheck statement drifted")
    if policy["funds_initial"] != FUNDS_PIN:
        raise ExtensionStagingError("the funds pin drifted")
    if policy["schedule_version"] != EXTENSION_SCHEDULE_VERSION:
        raise ExtensionStagingError("the extension schedule version drifted")
    return policy


# --- Staged composition -------------------------------------------------------


def staged_extension_composition() -> tuple[dict[str, bytes], str, int]:
    """Byte-exact save-restore composition for the extension candidate.

    The same retained ``info.nut`` identity family as the proven packages;
    the staged main is the D5 extension handler whose bridge class satisfies
    the save's stored ``CreateInstance`` identity without touching any
    retained byte.
    """
    with zipfile.ZipFile(d4.SEED17_RUN / "frozen-source.zip") as archive:
        info_bytes = archive.read("staged/info.nut")
    text = info_bytes.decode()
    create_instance = re.search(r'CreateInstance\(\)\s*\{\s*return\s+"([^"]+)"', text)
    version = re.search(r"GetVersion\(\)\s*\{\s*return\s+(\d+)", text)
    if create_instance is None or version is None or SOURCE_SAVE_GS_NAME not in text:
        raise ExtensionStagingError("retained staged GameScript identity incomplete")
    main_bytes = (EXTENSION_PACKAGE / "main.nut").read_bytes()
    bridge_class = create_instance.group(1)
    if f"class {bridge_class} extends D5CorridorExtensionProof" not in main_bytes.decode():
        raise ExtensionStagingError(
            f"staged extension main.nut missing required bridge class {bridge_class}"
        )
    return (
        {"info.nut": info_bytes, "main.nut": main_bytes},
        bridge_class,
        int(version.group(1)),
    )


def extension_prerequisite_binding(prerequisite: Path = PINNED_PREREQUISITE) -> dict:
    """The shared, fail-closed D4 candidate-5 after-save binding.

    Reused by import (never copied): the freight binding re-verifies the
    pinned prerequisite path, the prelaunch seal integrity, the consumed
    CLAIM, the ``after.sav`` digest against
    :data:`PINNED_PREREQUISITE_AFTER_SAVE`, the receipt binding the save, the
    D4 replay verdict, the corridor witness/depot pins and the retained
    welcome. The extension adds its own derived-pin cross-check so the same
    authoritative world is proven to still pin the corridor and the branch
    facts.
    """
    binding = freight_native.prerequisite_binding(Path(prerequisite).resolve())
    if [int(tile) for tile in binding["provenance"]["route"]["witness_path"]] != list(
        _compiled_corridor()
    ):
        raise ExtensionStagingError("the prerequisite witness drifted from the compiled corridor")
    if binding["provenance"]["plan_digest"] != d4.plan_policy()["plan_digest"]:
        raise ExtensionStagingError("the prerequisite plan digest drifted from the D4 derivation")
    return binding


def extension_staging_pins() -> dict:
    """The hypothesis-free design facts bound into the prelaunch record."""
    pins = network_pins()
    return dict(
        schema="d5-corridor-extension-design-pins-v1",
        corridor_front=pins["delivery_front"],
        corridor_delivery_stop=pins["delivery_stop"],
        depot=pins["depot"],
        depot_front=pins["depot_front"],
        branch_full_start=pins["branch_full_start"],
        branch_run=list(pins["branch_run"]),
        branch_stop=pins["branch_stop"],
        branch_front=pins["branch_front"],
        run_len=pins["run_len"],
        witness=list(extension_witness()),
        existing_station_sids=list(corridor_station_sids()),
        census_facts={str(tile): pin for tile, pin in pins["census_pins"].items()},
        terrain_survey=terrain_survey_facts(),
        statement=(
            "design facts only, no acceptance hypotheses: the branch sits on "
            "census ground whose live escarpment slopes (12/12/8 on "
            "50096/50352/50608, per the consumed D5-TERRAIN-SURVEY-1 "
            "evidence of record) are facts for the native test-mode "
            "previews, never census-flat claims; every acceptance story is "
            "the separate survey session's instrument"
        ),
    )


# --- Candidate staging ---------------------------------------------------------


def prepare_extension_candidate(
    directory: Path, *, prerequisite: Path = PINNED_PREREQUISITE
) -> PreparedProof:
    """Stage the fresh save-load composition; no process or connection."""
    prerequisite = Path(prerequisite).resolve()
    if prerequisite != PINNED_PREREQUISITE:
        raise ExtensionStagingError("the source world requires the pinned D4 prerequisite")
    schedule = extension_schedule()
    policy = _require_extension_policy(extension_plan_policy())
    if policy["schedule"] != schedule or policy["plan_digest"] != plan_digest_of(schedule):
        raise ExtensionStagingError("the staged extension schedule/policy digest drifted")
    if [row["index"] for row in schedule] != [0, 1, 2]:
        raise ExtensionStagingError("the staged extension schedule order drifted")
    if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
        raise ExtensionStagingError("pinned binary / exclusive runtime gate failed")
    directory = directory.resolve()
    binding = extension_prerequisite_binding(prerequisite)
    welcome = binding["expected_welcome"]
    world = d4.stage_world(binding, welcome)
    if sha256(d4.source_save_path(world)) != world["save_sha256"]:
        raise ExtensionStagingError("the staged source-save digest mismatch")
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
        # A fresh copy of the authoritative after-save is the staged source;
        # the retained save itself is never opened for writing or moved.
        staged_save = workspace.root / "source.sav"
        shutil.copyfile(d4.source_save_path(world), staged_save)
        verify_staged_source_save({"save_sha256": world["save_sha256"]}, staged_save)
        (workspace.game / SOURCE_SAVE_GS_NAME).mkdir()
        composition, create_instance, version = staged_extension_composition()
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
        for source in (EXTENSION_PACKAGE, AI_PACKAGE):
            for path in sorted(source.glob("*.nut")):
                frozen[str(path.resolve())] = sha256(path)
        frozen.update(
            {
                str(path): sha256(path)
                for path in sorted(workspace.root.rglob("*"))
                if path.is_file() and path.name != ".admin-secret"
            }
        )
        frozen.update(freight_native.d2_source_closure(EXTENSION_CLOSURE_ROOT))
        frozen.update(freight_native.d2_dependency_inventory(EXTENSION_CLOSURE_ROOT))
        prepared = PreparedProof(
            directory,
            spec,
            key_path,
            key.public_hex,
            (reservation.game_port, reservation.admin_port),
        )
        metadata = dict(
            schema=D5_EXTENSION_PRELAUNCH_SCHEMA,
            milestone=MILESTONE_EXTENSION,
            kind=KIND,
            attempt=EXTENSION_ATTEMPT,
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
                    "GameScript name/version; the D5 extension handler runs as "
                    "the retained CreateInstance subclass"
                ),
            ),
            save_policy=(
                "owned session-before.sav and after.sav over a fresh copy of "
                "the authoritative after-save only; the source save, the "
                "prerequisite attempt record and every historical artifact "
                "stay untouched"
            ),
            plan_policy=policy,
            expected_readback=d4.expected_readback_policy(),
            design_pins=extension_staging_pins(),
            bootstrap_command=f"start_ai {STAGED_AI_DIRECTORY}",
            execution_command=[
                str(PROJECT / ".venv/bin/python"),
                "-m",
                "app.simulation.openttd.proof.corridor_extension_native",
                "run",
                str(directory),
            ],
            budgets=extension_budgets(),
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
                source=d4.RETAINED_NETWORK_FACTS.parent.name,
                manifest_verified=True,
                statement=(
                    "the schedule derives arithmetically from the compiled D4 "
                    "corridor witness plus the retained census vacancy facts "
                    "and the built route-read evidence; the derived schedule "
                    "must equal the approved pinned design exactly"
                ),
            ),
            environment=freight_native.launch_environment(prepared),
            environment_overrides=dict(spec.environment),
            frozen=frozen,
            acceptance_recheck=dict(
                statement=ACCEPTANCE_RECHECK_STATEMENT,
                instrument="app.simulation.openttd.proof.corridor_accept_survey_native",
            ),
            station_merge=dict(
                schema="d5-corridor-extension-station-merge-v1",
                existing_sids=list(corridor_station_sids()),
                statement=(
                    "STATION_NEW is the pinned design: a readback sid equal to "
                    "the existing station ids 0 or 1 is a FAIL-CLOSED "
                    "station-merge defect"
                ),
            ),
        )
        metadata["prerequisite"] = dict(
            schema=D5_EXTENSION_PREREQUISITE_SCHEMA,
            attempt=binding["attempt"],
            milestone=binding["milestone"],
            directory=binding["retained_directory"],
            prelaunch_sha256=binding["prelaunch_digest"],
            after_save_sha256=binding["save_sha256"],
            verification=binding["verification"],
        )
        write_json(directory / "PRELAUNCH.json", metadata)
        (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
        return prepared
    finally:
        reservation.close()


def extension_preflight(prepared: PreparedProof) -> dict:
    """Offline launch-boundary rehearsal: re-derive everything, trust nothing."""
    directory = prepared.directory
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("the extension prelaunch seal mismatch")
    metadata = read_prelaunch(directory)
    if (directory / "CLAIM.json").exists():
        raise ValueError("the one native attempt already consumed")
    if metadata.get("schema") != D5_EXTENSION_PRELAUNCH_SCHEMA:
        raise ValueError("the staged prelaunch record is not the extension lineage")
    if metadata.get("kind") != KIND or metadata.get("milestone") != MILESTONE_EXTENSION:
        raise ValueError("the staged extension lineage drifted")
    if metadata.get("attempt") != EXTENSION_ATTEMPT:
        raise ValueError("the staged attempt identity drifted from its own scope")
    verify_freeze(metadata["frozen"])
    freight_native.require_frozen_d2_closure(metadata["frozen"], EXTENSION_CLOSURE_ROOT)
    freight_native.require_frozen_d2_dependencies(metadata["frozen"], EXTENSION_CLOSURE_ROOT)
    policy = metadata["plan_policy"]
    _require_extension_policy(policy)
    schedule = extension_schedule()
    if policy["schedule"] != schedule or policy["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("the staged extension schedule drifted from the compiled derivation")
    for entry in schedule:
        if entry.get("run_len") is not None and not 1 <= entry["run_len"] <= MAX_FULL_SPAN + 1:
            raise ValueError("a scheduled extension run exceeds the bounded span")
        if entry["kind"] in ("station", "depot") and not _adjacent(entry["tile"], entry["front"]):
            raise ValueError("a scheduled extension site front is not adjacent")
    if metadata.get("budgets") != extension_budgets():
        raise ValueError("the staged extension budget pins drifted")
    if metadata.get("design_pins") != extension_staging_pins():
        raise ValueError("the staged design pins drifted from the derived evidence")
    if metadata.get("acceptance_recheck", {}).get("statement") != ACCEPTANCE_RECHECK_STATEMENT:
        raise ValueError("the acceptance-recheck record drifted")
    if metadata.get("station_merge", {}).get("existing_sids") != list(corridor_station_sids()):
        raise ValueError("the station-merge dataset drifted from the built evidence")
    world_pins = policy.get("world", {})
    for name, expected in (
        ("expected_funds", FUNDS_PIN),
        ("per_op_max_cost", PER_OP_MAX_COST),
        ("request_budget", EXTENSION_REQUEST_BUDGET),
        ("branch_stop", int(PINNED_WITNESS[29])),
        ("branch_full_start", int(PINNED_WITNESS[25])),
    ):
        if world_pins.get(name) != expected:
            raise ValueError(f"the staged extension world pin {name} drifted")
    if policy.get("target_tile") != int(PINNED_WITNESS[25]):
        raise ValueError("the staged extension target tile drifted")
    if policy.get("route", {}).get("witness_path") != list(PINNED_WITNESS):
        raise ValueError("the staged extension route scope drifted")
    binding = extension_prerequisite_binding(Path(metadata["prerequisite"]["directory"]))
    required = ("attempt", "milestone", "directory", "prelaunch_sha256", "after_save_sha256")
    if {name: metadata["prerequisite"][name] for name in required} != dict(
        attempt=binding["attempt"],
        milestone=binding["milestone"],
        directory=binding["retained_directory"],
        prelaunch_sha256=binding["prelaunch_digest"],
        after_save_sha256=binding["save_sha256"],
    ):
        raise ValueError("the staged prerequisite binding drifted from its verified record")
    stored_world = metadata["world"]
    if (
        stored_world.get("save_sha256") != binding["save_sha256"]
        or stored_world.get("save_sha256") != PINNED_PREREQUISITE_AFTER_SAVE
    ):
        raise ValueError("the staged world is not the pinned prerequisite after-save")
    if stored_world.get("expected_welcome") != retained_welcome():
        raise ValueError("the retained world identity requirements drifted")
    verify_staged_source_save(
        {"save_sha256": stored_world["save_sha256"]},
        Path(metadata["workspace"]) / "source.sav",
    )
    composition, _, _ = staged_extension_composition()
    staged_identity = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME
    if staged_identity.joinpath("info.nut").read_bytes() != composition["info.nut"]:
        raise ValueError("the staged GameScript identity drifted from the retained composition")
    if staged_identity.joinpath("main.nut").read_bytes() != composition["main.nut"]:
        raise ValueError("the staged extension handler drifted from its bounded package")
    if not prepared.spec.workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("the workspace ownership mismatch")
    ClearingNativeBackend(authorized_one_launch=True).preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    reservation.close()
    return metadata


# --- Protocol-4 session/backend (reuse the D4 ceremony classes) ----------------


class ExtensionNativeBackend(d4.CorridorNativeBackend):
    """One-launch backend carrying the shared consumed marker, D4 session."""

    launch_marker_schema = D5_EXTENSION_LAUNCH_CONSUMED_SCHEMA


def _extension_request(
    op: str,
    request_id: str,
    plan: str,
    company: int,
    max_cost: int,
    entry: dict,
) -> CorridorRequest:
    return d4._corridor_request(op, request_id, plan, company, max_cost, entry)


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
                raise ConnectionError("extension proof stream disconnected")
            for kind, payload in decoder.feed_frames(chunk):
                if kind != SERVER_GAMESCRIPT:
                    raise ValueError("unexpected extension packet")
                response = decode_gamescript(payload, max_payload_bytes=MAX_CORRIDOR_RESPONSE_BYTES)
                (directory / (request.request_id + "-response.json")).write_bytes(response)
                return CorridorReadback.parse_for(request, response)


def _expected_funds(spent: int) -> int:
    """The exact pinned funds arithmetic after ``spent`` verified native cost."""
    return FUNDS_PIN - spent


def _funds_gate(readback: CorridorReadback, spent: int, label: str) -> None:
    expected = _expected_funds(spent)
    if int(readback.funds) != expected:
        raise ValueError(
            f"native funds drift beyond the pinned arithmetic at {label}: "
            f"expected {expected}, read {readback.funds}"
        )


def _station_gate(readback: CorridorReadback, label: str) -> None:
    """The FAIL-CLOSED station-merge / drive-through / linkage refusals."""
    if readback.op != "station":
        return
    if readback.sid is not None and readback.sid >= 0 and readback.sid in corridor_station_sids():
        raise ValueError(
            f"station-merge defect at {label}: the readback sid {readback.sid} equals "
            f"the existing corridor station ids {list(corridor_station_sids())}"
        )
    if readback.drive_through is True:
        raise ValueError(
            f"drive-through stop refused at {label}: the pinned design is a truck stop"
        )
    if readback.linked is False:
        raise ValueError(f"the branch stop is not linked to its front at {label}")


# --- Extension execution (authorized one-attempt path only) --------------------


async def execute_extension_attempt(prepared: PreparedProof, backend) -> dict:
    """Execute the authorized one-attempt extension phase (never offline).

    Three exchange groups in schedule order plus the final route read, over
    the production ``_corridor_request``/``CorridorSecureSession`` machinery;
    funds are cross-checked on every exchange against ``492149 − Σ verified
    prefix cost``; any defect halts the phase prefix-preservingly, no retry.
    """
    directory = prepared.directory
    extension_preflight(prepared)
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
    spent = 0
    attempts: list[tuple[str, dict]] = []
    try:
        async with asyncio.timeout(metadata["budgets"]["total_seconds"]):
            await backend.launch(prepared, authorization=grant)
            result["native_launches"] = 1
            await wait_log(backend, prepared, EXTENSION_READY_MARKER)
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
            for position, entry in enumerate(schedule):
                label = f"op-{entry['index']:02d}"
                evidence: dict[str, Any] = {}
                try:
                    before = await exchange(
                        session,
                        _extension_request(
                            "inspect", f"inspect-{position:02d}", seal, 0, max_cost, entry
                        ),
                        directory,
                    )
                    result["requests"] += 1
                    evidence["before"] = before
                    _funds_gate(before, spent, label + " inspect")
                    write_json(
                        directory / f"ext-{position:02d}-before.json",
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
                        directory / f"ext-{position:02d}-intent.json",
                        intent.model_dump(mode="json"),
                    )
                    evidence["intent"] = intent
                    result["dispatch_state"] = "DISPATCHED_UNKNOWN"
                    result["dispatched_op"] = label
                    built = await exchange(
                        session,
                        _extension_request(
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
                    # built.funds is the post-debit balance (main.nut reports
                    # post.funds and enforces funds - r.funds == r.cost), while
                    # spent only accrues after verify_corridor below; the gate
                    # must therefore expect the pin minus spent plus this op's
                    # own cost, never the pre-debit balance.
                    _funds_gate(built, spent + int(built.cost), label + " command")
                    _station_gate(built, label)
                    result["dispatch_state"] = "CONFIRMED"
                    result["last_status"] = built.status
                    evidence["built"] = built
                    write_json(
                        directory / f"ext-{position:02d}-built.json",
                        built.model_dump(mode="json"),
                    )
                    independent = await exchange(
                        session,
                        _extension_request(
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
                    # The independent read observes the same post-debit world
                    # state as the command readback (verify_corridor pins
                    # independent.funds == built.funds), so it is gated on the
                    # identical expected balance.
                    _funds_gate(independent, spent + int(built.cost), label + " read")
                    _station_gate(independent, label)
                    evidence["independent"] = independent
                    write_json(
                        directory / f"ext-{position:02d}-independent.json",
                        independent.model_dump(mode="json"),
                    )
                    verify_corridor(intent, before, built, independent)
                    spent += int(built.cost)
                    attempts.append((label, evidence))
                    result["built_ops"].append(label)
                    result["command_accepted"] = True
                    result["state_changed"] = True
                except Exception as error:  # noqa: BLE001 - fail-closed halt
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
                write_json(directory / "ext-route-read.json", route.model_dump(mode="json"))
                _funds_gate(route, spent, "route-00")
                route_receipt = verify_corridor_route(
                    route,
                    prelaunch_digest=seal,
                    expected_pairs=int(route_scope["expected_pairs"]),
                    expected_path=tuple(route_scope["witness_path"]),
                )
                if int(route.delivery_sid) in corridor_station_sids():
                    raise ValueError("station-merge defect: the route delivery sid is not new")
                station_receipt = dict(
                    schema="extension-station-new-receipt-v1",
                    existing_sids=list(corridor_station_sids()),
                    route_pickup_sid=int(route.pickup_sid),
                    route_delivery_sid=int(route.delivery_sid),
                    verdict="DISTINCT_NEW_STATION",
                )
                result["route"] = route_receipt
                after_save = await save(backend, prepared, "after")
                write_json(
                    directory / "receipt.json",
                    dict(
                        json.loads(json.dumps(phase)),
                        route=route_receipt,
                        station_receipt=station_receipt,
                        before_save_sha256=before_save,
                        after_save_sha256=after_save,
                        acceptance_recheck=ACCEPTANCE_RECHECK_STATEMENT,
                    ),
                )
                result["verified"] = True
                result["status"] = "NATIVE_EXTENSION_VERIFIED"
            else:
                result["status"] = "PHASE_HALTED_PREFIX_PRESERVED"
    except Exception as error:  # noqa: BLE001 - abort the phase with evidence
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if result.get("dispatch_state") in ("DISPATCHED_UNKNOWN", "CONFIRMED"):
            try:
                result["after_diagnostic_save_sha256"] = await save(
                    backend, prepared, "after-diagnostic", diagnostic=True
                )
            except Exception as save_error:  # noqa: BLE001
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
        if findings and result["status"] == "NATIVE_EXTENSION_VERIFIED":
            result["verified"] = False
            result["status"] = "FAILED"
            result["error"] = (
                "ValueError: retained script log health findings deny the verified receipt"
            )
        if (
            result["returncode"] not in (None, 0)
            and result["status"] == "NATIVE_EXTENSION_VERIFIED"
        ):
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
        except Exception as error:  # noqa: BLE001
            cleanup["verification_error"] = str(error)
            result["status"] = "FAILED_CLEANUP"
        write_json(directory / "cleanup.json", cleanup)
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


# --- Extension replay verification ---------------------------------------------


def _staged_extension_schedule(plan: dict) -> list[dict]:
    version = plan.get("schedule_version", 0)
    if version != EXTENSION_SCHEDULE_VERSION:
        raise ValueError(f"plan record names an unknown extension schedule version: {version}")
    return extension_schedule()


def verify_extension_attempt_identity(metadata: dict) -> dict:
    """Re-bind one retained extension attempt to its pinned prerequisite."""
    if metadata.get("attempt") != EXTENSION_ATTEMPT:
        raise ValueError("the retained attempt identity drifted from the staged scope")
    if (
        metadata.get("schema") != D5_EXTENSION_PRELAUNCH_SCHEMA
        or metadata.get("kind") != KIND
        or metadata.get("milestone") != MILESTONE_EXTENSION
    ):
        raise ValueError("the retained attempt is not the extension lineage")
    staged_prerequisite = metadata.get("prerequisite")
    if not isinstance(staged_prerequisite, dict):
        raise ValueError("the retained attempt lacks its prerequisite binding")
    binding = extension_prerequisite_binding(Path(staged_prerequisite.get("directory", "")))
    if staged_prerequisite.get("after_save_sha256") != binding["save_sha256"]:
        raise ValueError("the retained prerequisite binding drifted from the pinned D4 attempt")
    stored_world = metadata.get("world")
    if not isinstance(stored_world, dict):
        raise ValueError("the retained attempt lacks its world binding")
    if stored_world.get("save_sha256") != PINNED_PREREQUISITE_AFTER_SAVE:
        raise ValueError("the retained world is not the pinned prerequisite after-save")
    if stored_world.get("expected_welcome") != retained_welcome():
        raise ValueError("the retained world welcome drifted from the pinned identity")
    verify_staged_source_save(
        {"save_sha256": binding["save_sha256"]},
        d4.source_save_path(stored_world),
    )
    policy = metadata.get("plan_policy")
    if not isinstance(policy, dict):
        raise ValueError("the retained attempt lacks its plan policy")
    _require_extension_policy(policy)
    return binding


def extension_request_sequence(schedule: list[dict]) -> list[str]:
    """The exact scheduled request-id order for a completed extension phase."""
    ordered: list[str] = []
    for position, entry in enumerate(schedule):
        ordered.append(f"inspect-{position:02d}")
        ordered.append(f"{entry['kind']}-{position:02d}")
        ordered.append(f"confirm-{position:02d}")
    ordered.append("route-00")
    return ordered


def verify_extension_attempt(directory: Path) -> dict:
    """Replay retained protocol-4 extension semantics; never trust a label.

    The replay re-derives every retained fact independently — the operator
    authorization evidence, the staged schedule, the captured session frames
    and every per-op exchange — then re-verifies the whole phase with the
    production :func:`corridor_phase_outcome` and :func:`verify_corridor_route`.
    The completion additionally requires the exact exchange-id order, no
    duplicates or out-of-schedule frames, the pinned funds arithmetic exact,
    per-op cost ceilings honored, a distinct-new-station sid, the certified
    cleanup, and the verbatim acceptance recheck requirement in the receipt.
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
                "the extension candidate was never consumed by an operator "
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
    if metadata.get("schema") != D5_EXTENSION_PRELAUNCH_SCHEMA:
        return dict(
            verification="AUTHORIZATION_UNVERIFIED",
            authorization_state="UNKNOWN_PRELAUNCH_SCHEMA",
            statement=(
                "the prelaunch record is not the launch-capable "
                f"{D5_EXTENSION_PRELAUNCH_SCHEMA} lineage; no verified "
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
    plan = metadata["plan_policy"]
    schedule = _staged_extension_schedule(plan)
    if plan["schedule"] != schedule or plan["plan_digest"] != plan_digest_of(schedule):
        raise ValueError("the staged extension schedule drifted from the compiled derivation")
    verify_extension_attempt_identity(metadata)
    result = json.loads((directory / "result.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["encrypted"] is not True or runtime["welcome"]["revision"] != "15.3":
        raise ValueError("owned single-runtime encrypted execution evidence missing")
    outbound, outbound_requests, replies, request_positions, reply_positions = (
        d4._parse_phase_frames(directory)
    )
    if len(outbound_requests) > metadata["budgets"]["requests"]:
        raise ValueError("extension request budget exceeded (outbound frames)")
    paths = sorted(directory.glob("*-request.json"))
    file_queries = [CorridorRequest.model_validate_json(path.read_bytes()) for path in paths]
    for path, query in zip(paths, file_queries, strict=True):
        if query.request_id != path.name[: -len("-request.json")]:
            raise ValueError("the retained request file identity does not match its payload")
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
    scheduled_ids = d4._scheduled_request_ids(schedule)
    unknown = {query.request_id for query in file_queries} - scheduled_ids
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
            raise ValueError("the retained response file identity does not match its payload")
        if not (directory / (request_id + "-request.json")).is_file():
            raise ValueError("the retained response file lacks its request")
    for raw, response in response_map.items():
        if outbound.count(encode_gamescript(raw)) != 1 or replies.count(response) != 1:
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
    attempts: list[tuple[str, dict]] = []
    ordered_exchange_ids: list[str] = []
    route_position = None
    for position, entry in enumerate(schedule):
        label = f"op-{entry['index']:02d}"
        if (
            halted_position is None
            and isinstance(halt_record, dict)
            and halt_record.get("label") == label
        ):
            halted_position = position
        pending = halted_position is not None and position > halted_position
        evidence: dict[str, Any] = {}
        if not pending:
            for name in ("before", "intent", "built", "independent"):
                path = directory / f"ext-{position:02d}-{name}.json"
                if not path.is_file():
                    continue
                try:
                    evidence[name] = (
                        CorridorIntent.model_validate_json(path.read_bytes())
                        if name == "intent"
                        else CorridorReadback.model_validate_json(path.read_bytes())
                    )
                except ValueError:
                    continue
            intent = evidence.get("intent")
            if (
                position == 0
                and evidence.get("before") is not None
                and int(evidence["before"].funds) != FUNDS_PIN
            ):
                raise ValueError("the opening funds pin is not the D4 close-out")
            if intent is not None:
                if intent.prelaunch_digest != seal:
                    raise ValueError("an admitted intent does not bind its candidate seal")
                if intent.source_save_digest != sha256(directory / "session-before.sav"):
                    raise ValueError("an admitted intent does not bind the session-before save")
                if intent.kind != entry["kind"] or d4._pins(entry) != d4._pins(
                    entry, intent=intent
                ):
                    raise ValueError("an admitted intent drifted from the staged schedule")
                if intent.kind in ("full", "road") and intent.run_len != entry.get("run_len"):
                    raise ValueError("an admitted intent run length drifted")
                if int(intent.max_cost) > PER_OP_MAX_COST:
                    raise ValueError("an admitted intent exceeds the per-op cost ceiling")
                query = next(
                    (item for item in file_queries if item.request_id == f"inspect-{position:02d}"),
                    None,
                )
                raw = response_map.get(query.to_bytes()) if query is not None else None
                if raw is None:
                    raise ValueError("an admitted intent lacks its retained inspect exchange")
                if CorridorReadback.parse_for(query, raw).digest != intent.before_digest:
                    raise ValueError("retained admission evidence does not bind its exchange")
            for name in ("built", "independent"):
                readback = evidence.get(name)
                if readback is not None:
                    _station_gate(readback, label)
            for exchange_id in (
                f"inspect-{position:02d}",
                f"{entry['kind']}-{position:02d}",
                f"confirm-{position:02d}",
            ):
                for item in file_queries:
                    if item.request_id == exchange_id and exchange_id not in ordered_exchange_ids:
                        ordered_exchange_ids.append(exchange_id)
        attempts.append((label, evidence))
    route_query = next((query for query in file_queries if query.request_id == "route-00"), None)
    if route_query is not None:
        route_position = request_positions.get(route_query.to_bytes())
    else:
        route_position = None
    phase = corridor_phase_outcome(attempts)
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
    if result["status"] == "NATIVE_EXTENSION_VERIFIED":
        if phase["verification"] != "PHASE_COMPLETE":
            raise ValueError("the verified receipt contradicts its phase outcome")
        if result.get("halt") is not None or not result.get("command_accepted"):
            raise ValueError("the verified receipt contradicts its retained attempt record")
        if (result.get("native_launches"), result.get("connections")) != (
            metadata["budgets"]["launches"],
            metadata["budgets"]["connection_attempts"],
        ):
            raise ValueError("the verified receipt contradicts its launch/connection seal")
        if len(result.get("built_ops", [])) != len(schedule) or not cleanup_complete:
            raise ValueError("the verified receipt cleanup or built inventory incomplete")
        if len(outbound_requests) != PLANNED_EXTENSION_REQUESTS:
            raise ValueError("the verified receipt request inventory drifted from the schedule")
        if ordered_exchange_ids + ["route-00"] != extension_request_sequence(schedule):
            raise ValueError("the exchange-id order drifted from the staged schedule")
        if route_position is None or route_position != max(request_positions.values()):
            raise ValueError("the route read is not the last scheduled exchange")
        raw = response_map.get(route_query.to_bytes())
        route_readback = CorridorReadback.parse_for(route_query, raw) if raw is not None else None
        if route_readback is None:
            raise ValueError("verified route evidence missing from the retained exchange")
        route_scope = plan["route"]
        route_receipt = verify_corridor_route(
            route_readback,
            prelaunch_digest=seal,
            expected_pairs=int(route_scope["expected_pairs"]),
            expected_path=tuple(route_scope["witness_path"]),
        )
        if int(route_readback.delivery_sid) in corridor_station_sids():
            raise ValueError(
                "station-merge defect: the route delivery sid is an existing corridor station id"
            )
        if int(route_readback.funds) != _expected_funds(
            sum(int(receipt["cost"]) for receipt in phase["completed"])
        ):
            raise ValueError("the retained funds arithmetic drifted from the pinned rule")
        receipt_path = directory / "receipt.json"
        if not receipt_path.is_file():
            raise ValueError("the verified receipt record missing")
        expected_receipt = dict(
            json.loads(json.dumps(phase)),
            route=route_receipt,
            station_receipt=dict(
                schema="extension-station-new-receipt-v1",
                existing_sids=list(corridor_station_sids()),
                route_pickup_sid=int(route_readback.pickup_sid),
                route_delivery_sid=int(route_readback.delivery_sid),
                verdict="DISTINCT_NEW_STATION",
            ),
            before_save_sha256=sha256(directory / "session-before.sav"),
            after_save_sha256=sha256(directory / "after.sav"),
            acceptance_recheck=ACCEPTANCE_RECHECK_STATEMENT,
        )
        if json.loads(receipt_path.read_text()) != json.loads(json.dumps(expected_receipt)):
            raise ValueError("retained extension receipt replay mismatch")
        return dict(verification="EXTENSION_COMPLETION_VERIFIED", receipt=expected_receipt)
    if result["status"] == "FAILED_CLEANUP":
        return dict(
            verification="ATTEMPT_FAILED_EVIDENCE_PRESERVED",
            result_status="FAILED_CLEANUP",
            error=result.get("error") or "cleanup was not certified",
            cleanup_complete=False,
        )
    if result["status"] in ("PHASE_HALTED_PREFIX_PRESERVED", "FAILED"):
        if result["status"] == "PHASE_HALTED_PREFIX_PRESERVED" and (
            phase["verification"] != "PARTIAL_EXECUTION_EVIDENCE"
            or phase["failed"] is None
            or not isinstance(halt_record, dict)
            or phase["failed"].get("label") != halt_record.get("label")
            or len(result.get("built_ops", [])) != len(phase["completed"])
        ):
            raise ValueError("halted extension evidence contradicts its retained record")
        if not cleanup_complete:
            raise ValueError("the halted extension attempt cleanup incomplete")
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


def staged_extension_authorization_payload_digest(directory: Path) -> str:
    """The RFC-canonical digest of the candidate's own authorization payload."""
    directory = directory.resolve()
    metadata = read_prelaunch(directory)
    seal = sha256(directory / "PRELAUNCH.json")
    return hashlib.sha256(
        canonical_authorization_bytes(authorization_payload(metadata, seal))
    ).hexdigest()


def exit_status(result: dict) -> int:
    return 0 if result.get("verified") is True else 1


def verdict_exit_status(verdict: dict) -> int:
    return 0 if verdict.get("verification") == "EXTENSION_COMPLETION_VERIFIED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("prepare", "preflight", "authorization-payload-digest", "run", "verify"),
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prerequisite", type=Path, default=PINNED_PREREQUISITE)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == "prepare":
        prepared = prepare_extension_candidate(directory, prerequisite=args.prerequisite)
        extension_preflight(prepared)
        print("PRELAUNCH PASS", directory)
    elif args.command == "preflight":
        extension_preflight(freight_native.reopen_candidate(directory))
        print("PREFLIGHT PASS")
    elif args.command == "authorization-payload-digest":
        print(staged_extension_authorization_payload_digest(directory))
    elif args.command == "verify":
        verdict = verify_extension_attempt(directory)
        print(json.dumps(verdict, sort_keys=True))
        raise SystemExit(verdict_exit_status(verdict))
    else:
        read_prelaunch(directory)  # fail fast on any drifted prelaunch record
        result = asyncio.run(
            execute_extension_attempt(
                freight_native.reopen_candidate(directory),
                ExtensionNativeBackend(authorized_one_launch=True),
            )
        )
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(exit_status(result))


if __name__ == "__main__":
    main()
