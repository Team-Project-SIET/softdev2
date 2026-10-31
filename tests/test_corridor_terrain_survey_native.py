"""Controlled offline tests for the corridor-extension-3 terrain-survey native
staging pipeline (successor of the consumed D5-TERRAIN-SURVEY-1).

The pipeline under test is
``app/simulation/openttd/proof/corridor_terrain_survey_native.py``, staged as
a fresh candidate from the pinned D4 candidate-5 prerequisite. Everything
here is strictly offline: no OpenTTD launch, no AdminPort connection, no
claim, no authorization artifact, and no mutation of any retained attempt
record or authoritative save. Replay behavior is exercised with real
production verdict paths (claim-absent, tampered seals, synthetic retained
evidence without operator authorization), so every refusal is the real
fail-closed outcome, never a mock of the verifier.

The remediation sections below additionally exercise the claim lifecycle,
stage journal, handshake evidence and replay ingestion with fully scripted
backend doubles inside isolated temporary candidates: no scripted scenario
can ever spawn a process, open a port or touch the live candidate-2
directory; authorization always uses the synthetic RFC 8032 test anchor that
never verifies against the production anchor.
"""

from __future__ import annotations

import asyncio
import json
import threading
import shutil
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.simulation.openttd.proof.corridor_accept_survey_native as survey_native
import app.simulation.openttd.proof.corridor_freight_native as d5
import app.simulation.openttd.proof.corridor_terrain_survey_native as terrain_native
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.secure_admin import (
    AuthDisconnected,
    AuthRejected,
    AuthState,
    AuthTimeout,
)
from app.simulation.openttd.corridor_freight import FreightRequest
from app.simulation.openttd.corridor_terrain_survey import (
    PLANNED_TERRAIN_EXCHANGES,
    TERRAIN_ACCEPT_TILES,
    TERRAIN_REQUEST_BUDGET,
    TERRAIN_TILES,
    TerrainSurveyPlan,
    terrain_survey_plan,
)
from app.simulation.openttd.proof.corridor_freight_native import FreightStagingError
from app.simulation.openttd.proof.harness import sha256
from app.simulation.openttd.proof.operator_authorization import (
    ClearingAuthorizationError,
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_clearing import (
    claim_status,
    record_boundary_consumption,
    replay_authorization_state,
)
from tests.test_corridor_accept_survey import SEAL as SURVEY_SEAL
from tests.test_corridor_freight import PRELAUNCH as FREIGHT_SEAL

SEAL = "b" * 64


def terrain_request_for(exchange: str) -> terrain_native.TerrainRequest:
    op = {"radius-00": "radius", "accept-00": "accept", "accept-01": "accept"}.get(exchange, "tile")
    tile_by_exchange = {
        **{f"tile-{index:02d}": tile for index, tile in enumerate(TERRAIN_TILES)},
        "accept-00": TERRAIN_ACCEPT_TILES[0],
        "accept-01": TERRAIN_ACCEPT_TILES[1],
    }
    return terrain_native.TerrainRequest(
        op=op,
        request_id=exchange,
        plan=SEAL,
        company=0,
        max_cost=0,
        pickup=45748,
        delivery=50351,
        depot=45487,
        tile=tile_by_exchange.get(exchange),
    )


def freight_site_request() -> FreightRequest:
    plan = d5.freight_plan()
    return FreightRequest(
        op="site",
        request_id="site-00",
        plan=FREIGHT_SEAL,
        company=plan.company,
        max_cost=plan.max_cost,
        pickup=plan.pickup,
        delivery=plan.delivery,
        depot=plan.depot,
        route=plan.witness,
        route_digest=plan.route_digest,
    )


def terrain_reply_bytes(
    request: terrain_native.TerrainRequest,
    *,
    status: str = "READY",
    radius: int = 8,
    accept: int | None = 0,
    facts: dict | None = None,
    funds: int = 492149,
) -> bytes:
    body: dict = {
        "protocol": 7,
        "op": request.op,
        "request_id": request.request_id,
        "plan": request.plan,
        "company": request.company,
        "max_cost": 0,
        "pickup": request.pickup,
        "delivery": request.delivery,
        "depot": request.depot,
        "status": status,
        "funds": funds,
        "cost": 0,
    }
    if request.tile is not None:
        body["tile"] = request.tile
    if request.op == "radius":
        body["radius"] = radius
    elif request.op == "accept" and status == "READY":
        body["accept"] = 0 if accept is None else accept
        body["radius"] = radius
    elif request.op == "tile" and status == "READY":
        tile_facts = dict(
            slope=0,
            min_height=1,
            max_height=1,
            buildable=True,
            owner=-1,
            tree=False,
            water=False,
            coast=False,
            farm=False,
            rock=False,
            rough=False,
            road=False,
            rail=False,
            water_transport=False,
            air_transport=False,
        )
        tile_facts.update(facts or {})
        body.update(tile_facts)
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    prepared = terrain_native.prepare_terrain_survey_candidate(
        tmp_path_factory.mktemp("terrain-staging") / "candidate"
    )
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(prepared) -> dict:
    return json.loads((prepared.directory / "PRELAUNCH.json").read_text())


# --- the plan-bound pipeline and the cross-session guards ---------------------


def test_terrain_pipeline_accepts_a_terrainsurveyplan_only():
    plan = terrain_survey_plan()
    assert terrain_native._require_terrain_survey_plan(plan).digest == plan.digest
    with pytest.raises(terrain_native.TerrainSurveyStagingError, match="TerrainSurveyPlan"):
        terrain_native._require_terrain_survey_plan(d5.freight_plan())
    with pytest.raises(terrain_native.TerrainSurveyStagingError, match="TerrainSurveyPlan"):
        terrain_native._require_terrain_survey_plan(survey_native.survey_plan())
    with pytest.raises(terrain_native.TerrainSurveyStagingError, match="TerrainSurveyPlan"):
        terrain_native._require_terrain_survey_plan(dict(digest=plan.digest))


def test_terrain_plan_is_the_pinned_model():
    plan = terrain_native.terrain_survey_plan()
    assert plan.schema_version == 1
    assert plan.company == 0 and plan.cargo == 1
    assert plan.expected_funds == 492149
    assert plan.schedule == terrain_native.TERRAIN_EXCHANGE_IDS
    with pytest.raises(Exception, match="drifted|pinned|schedule"):
        TerrainSurveyPlan(**(plan.model_dump() | {"schedule": tuple(plan.schedule)[:-1]}))


def test_sibling_sessions_refuse_terrain_frames_and_terrain_session_refuses_siblings():
    """A terrain request fails the freight and protocol-6 survey sessions and
    both sibling frames fail the terrain session; all before any handler."""
    terrain = object.__new__(terrain_native.TerrainSecureSession)
    terrain._state = d5.AuthState.ACTIVE
    terrain_frame = terrain_native.encode_terrain_request(terrain_request_for("tile-03").to_bytes())
    terrain.validate_outbound(terrain_frame)
    sibling_frames = {
        "freight": d5.encode_freight_request(freight_site_request().to_bytes()),
        "survey": survey_native.encode_survey_request(
            _survey_accept_request("accept-00", 50351).to_bytes()
        ),
    }
    for frame in sibling_frames.values():
        with pytest.raises(Exception):
            terrain.validate_outbound(frame)
    with pytest.raises(Exception):
        terrain.validate_outbound(b"garbage")
    freight = object.__new__(d5.FreightSecureSession)
    freight._state = d5.AuthState.ACTIVE
    freight.validate_outbound(sibling_frames["freight"])
    with pytest.raises(Exception):
        freight.validate_outbound(terrain_frame)
    survey = object.__new__(survey_native.SurveySecureSession)
    survey._state = d5.AuthState.ACTIVE
    survey.validate_outbound(sibling_frames["survey"])
    with pytest.raises(Exception):
        survey.validate_outbound(terrain_frame)


def _survey_accept_request(exchange: str, tile: int | None):
    from app.simulation.openttd.corridor_accept_survey import SurveyRequest

    return SurveyRequest(
        op="accept" if exchange.startswith("accept") else "radius",
        request_id=exchange,
        plan=SURVEY_SEAL,
        company=0,
        max_cost=0,
        pickup=45748,
        delivery=50351,
        depot=45487,
        tile=tile,
    )


def test_terrain_schedule_is_the_pinned_read_only_ten():
    schedule = terrain_native.terrain_schedule()
    assert [row["exchange"] for row in schedule] == [
        "radius-00",
        "tile-00",
        "tile-01",
        "tile-02",
        "tile-03",
        "tile-04",
        "tile-05",
        "tile-06",
        "accept-00",
        "accept-01",
    ]
    assert all(row["op"] in ("radius", "tile", "accept") for row in schedule)
    assert [row.get("observation_tile") for row in schedule[1:8]] == list(TERRAIN_TILES)
    assert [row.get("observation_tile") for row in schedule[8:10]] == [
        50351,
        50862,
    ]
    for foreign in ("site", "purchase", "order", "start", "load-watch", "prod"):
        with pytest.raises(Exception):
            terrain_native.terrain_exchange_timeout_seconds(
                budget_table=terrain_native.terrain_budgets(), op=foreign
            )


def test_terrain_exchange_budgets_are_pinned(staged):
    metadata = metadata_of(staged)
    assert metadata["budgets"]["requests"] == TERRAIN_REQUEST_BUDGET == 32
    assert metadata["budgets"]["planned_exchanges"] == PLANNED_TERRAIN_EXCHANGES == 10
    assert metadata["budgets"]["max_cost"] == 0
    assert metadata["budgets"]["gsadmin_bytes"] == 512
    assert metadata["budgets"]["response_bytes"] == 512


# --- staging correctness -------------------------------------------------------


def test_staged_candidate_binds_the_terrain_lineage(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == terrain_native.D5_TERRAIN_PRELAUNCH_SCHEMA
    assert metadata["attempt"] == terrain_native.TERRAIN_SURVEY_ATTEMPT
    assert metadata["milestone"] == terrain_native.MILESTONE_TERRAIN_SURVEY
    assert metadata["kind"] == terrain_native.KIND == "terrain-survey"
    assert metadata["budgets"]["max_cost"] == 0
    assert metadata["budgets"]["planned_exchanges"] == PLANNED_TERRAIN_EXCHANGES
    assert metadata["plan_policy"]["max_cost"] == 0
    assert metadata["plan_policy"]["plan_model_digest"] == terrain_survey_plan().digest
    assert metadata["prerequisite"]["after_save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert metadata["world"]["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    read_only = metadata["plan_policy"]["read_only"]
    assert read_only["permitted_ops"] == ["radius", "tile", "accept"]
    assert read_only["max_cost"] == 0 and read_only["funds_readback_required"] is True
    cross = metadata["cross_schedule_guard"]
    assert cross["terrain_ops"] == ["radius", "tile", "accept"]


def test_terrain_prerequisite_binding_must_be_the_pinned_candidate5(staged):
    binding = terrain_native.terrain_prerequisite_binding()
    assert binding["attempt"] == "D4-CORRIDOR-5"
    assert binding["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    other = Path("artifacts/experiments/d4-corridor-native-candidate-4")
    if other.is_dir():
        with pytest.raises(FreightStagingError, match="not the pinned"):
            terrain_native.terrain_prerequisite_binding(other)


def test_staged_source_save_is_the_authoritative_after_save(staged):
    metadata = metadata_of(staged)
    staged_save = Path(metadata["workspace"]) / "source.sav"
    assert sha256(staged_save) == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert d5.PINNED_PREREQUISITE_AFTER_SAVE == (
        "a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261"
    )


def test_authorization_payload_rebuilds_and_no_claim_exists(staged):
    import hashlib

    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    digest = terrain_native.staged_terrain_authorization_payload_digest(staged.directory)
    rebuilt = hashlib.sha256(
        canonical_authorization_bytes(authorization_payload(metadata, seal))
    ).hexdigest()
    assert (
        rebuilt
        == digest
        == terrain_native.staged_terrain_authorization_payload_digest(staged.directory)
    )
    assert not (staged.directory / "CLAIM.json").exists()
    assert not (staged.directory / "AUTHORIZATION.json").exists()
    assert claim_status(staged.directory) == "ABSENT"


def test_terrain_preflight_re_derives_every_binding(staged):
    metadata = terrain_native.terrain_survey_preflight(staged)
    assert metadata["attempt"] == terrain_native.TERRAIN_SURVEY_ATTEMPT


def test_staged_attempt_identity_is_join_secure_encodable(staged):
    """The compact D5CE3-SURVEY-3 identity fits JOIN_SECURE's 24-byte payload
    and is validated by the shared production rule, not just by equality."""
    from app.simulation.openttd.secure_admin import JOIN_SECURE_CLIENT_NAME_CAPACITY
    from app.simulation.openttd.secure_admin import validate_join_secure_string

    metadata = metadata_of(staged)
    assert metadata["attempt"] == "D5CE3-SURVEY-3"
    assert len(metadata["attempt"].encode("utf-8")) == 14
    assert len(metadata["attempt"].encode("utf-8")) <= JOIN_SECURE_CLIENT_NAME_CAPACITY - 1
    validate_join_secure_string(
        metadata["attempt"], capacity=JOIN_SECURE_CLIENT_NAME_CAPACITY
    )
    # the preflight gate re-derives the same check from the sealed bytes
    terrain_native.terrain_survey_preflight(staged)


def test_oversized_attempt_identity_refused_before_candidate_artifacts(tmp_path, monkeypatch):
    """A 25-byte attempt identity is unencodable by the pinned encoder and is
    refused before staging writes a single candidate artifact."""
    from app.simulation.openttd.proof.corridor_freight_native import (
        FreightStagingError as FreightStagingErrorAlias,
    )

    directory = tmp_path / "oversized-candidate"
    monkeypatch.setattr(terrain_native, "TERRAIN_SURVEY_ATTEMPT", "x" * 25)
    with pytest.raises(
        (terrain_native.TerrainSurveyStagingError, FreightStagingError), match="JOIN_SECURE"
    ):
        terrain_native.prepare_terrain_survey_candidate(directory)
    assert not directory.exists()
    monkeypatch.setattr(terrain_native, "TERRAIN_SURVEY_ATTEMPT", "")
    empty = tmp_path / "empty-candidate"
    with pytest.raises(
        (terrain_native.TerrainSurveyStagingError, FreightStagingError), match="JOIN_SECURE"
    ):
        terrain_native.prepare_terrain_survey_candidate(empty)
    assert not empty.exists()
    # the accepted identity passes the preparation validator
    terrain_native.require_join_secure_attempt_identity("D5CE3-SURVEY-3")


def test_terrain_preflight_re_refuses_unencodable_attempt_identity(staged):
    """PREFLIGHT re-derives JOIN_SECURE capacity from the staged bytes alone:
    even a re-sealed, oversized identity is refused independently."""
    from app.simulation.openttd.secure_admin import InvalidSecureIdentity
    from app.simulation.openttd.secure_admin import validate_join_secure_string

    oversized = "x" * 25
    with pytest.raises(InvalidSecureIdentity):
        validate_join_secure_string(oversized, capacity=25)

    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    original_seal = (target / "PRELAUNCH.sha256").read_text()
    metadata = json.loads(original)
    metadata["attempt"] = oversized
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="JOIN_SECURE"):
            terrain_native.terrain_survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(original_seal)
        terrain_native.terrain_survey_preflight(staged)


def test_terrain_preflight_refuses_seal_tampering(staged):
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    metadata = json.loads(original)
    metadata["budgets"]["max_cost"] = 7
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    restamp = (target / "PRELAUNCH.sha256").read_text()
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="budget|max_cost|budget pins drifted"):
            terrain_native.terrain_survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(restamp)


def test_terrain_schedule_and_plan_drift_refuse_preflight(staged):
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    seal_text = (target / "PRELAUNCH.sha256").read_text()
    metadata = json.loads(original)
    metadata["plan_policy"]["schedule"] = metadata["plan_policy"]["schedule"][1:]
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="drifted"):
            terrain_native.terrain_survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(seal_text)


def test_terrain_world_pins_drift_refuse_preflight(staged):
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    seal_text = (target / "PRELAUNCH.sha256").read_text()
    metadata = json.loads(original)
    metadata["plan_policy"]["world"]["terra_tiles"] = list(TERRAIN_TILES[1:])
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="terra_tiles"):
            terrain_native.terrain_survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(seal_text)


# --- the census hypothesis / finding semantics --------------------------------


def test_census_hypotheses_are_hypothesis_grade_for_the_pinned_tiles():
    hypotheses = terrain_native.terrain_census_hypotheses()
    assert hypotheses["state"] == "RETAINED_CENSUS_REBOUND"
    rows = hypotheses["hypotheses"]
    assert len(rows) == 9  # seven terra hypothesis rows + two acceptance rows
    assert all(row["kind"] == "HYPOTHESIS" for row in rows)
    assert [row["tile"] for row in rows[:7]] == list(TERRAIN_TILES)
    assert [row["tile"] for row in rows[7:]] == list(TERRAIN_ACCEPT_TILES)
    for row in rows[:7]:
        assert set(row["terrain"]) <= set(terrain_native.HYPOTHESIZED_TERRAIN_FIELDS)
        assert int(row["terrain"]["slope"]) == 0
        assert row["terrain"]["buildable"] is True
    # the acceptance rows hypothesize acceptance only, never terrain fields
    assert not any("terrain" in row for row in rows[7:])


def test_census_findings_record_real_measured_terrain_divergence():
    hypotheses = terrain_native.terrain_census_hypotheses()
    measured = {
        str(tile): dict(
            slope=9,
            min_height=1,
            max_height=1,
            buildable=True,
            owner=-1,
            tree=False,
            water=False,
            coast=False,
            farm=False,
            rock=False,
            rough=False,
            road=True,
            rail=False,
            water_transport=False,
            air_transport=False,
            request_id=f"tile-{index:02d}",
        )
        for index, tile in enumerate(TERRAIN_TILES)
    }
    findings = terrain_native.compare_terrain_census_findings(measured, hypotheses)
    slope_findings = [f for f in findings if f["field"] == "slope"]
    road_findings = [f for f in findings if f["field"] == "road"]
    assert [f["tile"] for f in slope_findings] == list(TERRAIN_TILES)
    assert [f["tile"] for f in road_findings] == list(TERRAIN_TILES)
    assert all(f["statement"].startswith("the native terrain value") for f in findings)
    assert all(f["field"] in ("slope", "road") for f in findings)
    # A non-hypothesized measured field (max_height, owner) is never a finding
    # premise; the census never stated max_height or owner.
    assert not any(f["field"] in ("max_height", "owner") for f in findings)
    assert terrain_native.compare_terrain_census_findings({}, {"state": "CENSUS_ABSENT"}) == []
    identical = {
        str(row["tile"]): dict(row["terrain"]) | {"request_id": "x"}
        for row in hypotheses["hypotheses"][:7]
    }
    assert terrain_native.compare_terrain_census_findings(identical, hypotheses) == []


def test_acceptance_findings_record_real_measured_divergence():
    hypotheses = terrain_native.terrain_census_hypotheses()
    # The consumed attempt's delivery stop hypothesizes zero (E36 finding of
    # record); the proposed station ground 50862 hypothesizes acceptance 8/8.
    observations = {
        "50351": dict(value=0, request_id="accept-00"),
        "50862": dict(value=3, request_id="accept-01"),
    }
    findings = terrain_native.compare_terrain_acceptance_findings(observations, hypotheses)
    assert [f["tile"] for f in findings] == [50862]
    assert findings[0]["census_hypothesis"] == 8
    assert findings[0]["statement"].startswith("the native acceptance differs")
    assert terrain_native.compare_terrain_acceptance_findings({}, {"state": "CENSUS_ABSENT"}) == []


# --- the exchange helper and terrain frame replay parsing ---------------------


class _FakeSession:
    def __init__(self, reply: bytes) -> None:
        self._reply = reply
        self.sent: list[bytes] = []
        self._read = False

    async def send(self, frame: bytes) -> None:
        self.sent.append(frame)

    async def receive(self) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._reply


def _admin_frame(payload: bytes) -> bytes:
    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT

    return encode_admin_frame(SERVER_GAMESCRIPT, payload)


def test_terrain_exchange_persists_request_and_response_pair(tmp_path):
    request = terrain_request_for("tile-00")
    facts = dict(slope=9, max_height=2, owner=-1)
    reply = _admin_frame(terrain_reply_bytes(request, facts=facts) + b"\0")
    readback = asyncio.run(terrain_native.terrain_exchange(_FakeSession(reply), request, tmp_path))
    assert (readback.status, readback.slope, readback.tile) == ("READY", 9, 50095)
    assert (tmp_path / "tile-00-request.json").read_bytes() == request.to_bytes()
    assert (tmp_path / "tile-00-response.json").read_bytes() == terrain_reply_bytes(
        request, facts=facts
    )
    from app.simulation.openttd.corridor_terrain_survey import TerrainReadback

    parsed = TerrainReadback.parse_for(request, (tmp_path / "tile-00-response.json").read_bytes())
    assert parsed.digest == readback.digest


def test_terrain_exchange_refuses_malformed_truncated_and_stale_replies(tmp_path):
    from app.simulation.openttd.corridor_terrain_survey import TerrainReadback

    request = terrain_request_for("accept-01")

    class Broken:
        async def send(self, frame):
            pass

        async def receive(self):
            return b""

    with pytest.raises(ConnectionError):
        asyncio.run(terrain_native.terrain_exchange(Broken(), request, tmp_path))
    stale = _admin_frame(terrain_reply_bytes(request, accept=8) + b"\0")
    stale_request = terrain_request_for("accept-00")
    with pytest.raises(ValueError):
        asyncio.run(terrain_native.terrain_exchange(_FakeSession(stale), stale_request, tmp_path))
    # A truncated body can never parse as a measured observation.
    with pytest.raises(Exception):
        TerrainReadback.parse_for(request, terrain_reply_bytes(request)[:-6])


def test_terrain_response_bounds_are_exactly_512(tmp_path):
    request = terrain_request_for("radius-00")
    assert len(request.to_bytes()) <= terrain_native.MAX_TERRAIN_REQUEST_BYTES
    reply = _admin_frame(terrain_reply_bytes(request) + b"\0")
    readback = asyncio.run(terrain_native.terrain_exchange(_FakeSession(reply), request, tmp_path))
    assert readback.radius == 8
    over = json.dumps(
        {
            "protocol": 7,
            "op": "radius",
            "request_id": "radius-00",
            "plan": SEAL,
            "company": 0,
            "max_cost": 0,
            "pickup": 45748,
            "delivery": 50351,
            "depot": 45487,
            "status": "READY",
            "funds": 492149,
            "cost": 0,
            "radius": 8,
            "pad": "x" * 700,
        },
        sort_keys=True,
    ).encode()
    from app.simulation.openttd.gamescript_transport import encode_gamescript

    with pytest.raises(ValueError):
        encode_gamescript(over)
    with pytest.raises(ValueError):
        terrain_native.decode_terrain_request(over)


def test_terrain_frame_replay_parser(tmp_path):
    request = terrain_request_for("tile-02")
    reply = _admin_frame(terrain_reply_bytes(request) + b"\0")
    frames = [
        ["outbound", terrain_native.encode_terrain_request(request.to_bytes()).hex()],
        ["inbound", reply.hex()],
    ]
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    outbound, requests, replies, request_positions, reply_positions = (
        terrain_native._parse_terrain_frames(tmp_path)
    )
    assert requests == [request]
    assert replies == [terrain_reply_bytes(request)]
    assert request_positions[request.to_bytes()] == 0
    assert set(reply_positions) == {terrain_reply_bytes(request)}
    with pytest.raises(ValueError, match="invalid TerrainRequest"):
        from app.simulation.openttd.gamescript_transport import encode_gamescript

        junk = [["outbound", encode_gamescript(b'{"op":"site"}').hex()]]
        (tmp_path / "frames.json").write_text(json.dumps(junk))
        terrain_native._parse_terrain_frames(tmp_path)


def test_mutation_ops_cannot_enter_the_terrain_run(tmp_path):
    """Any op outside radius/tile/accept can never become a terrain request:
    the wire Literal refuses it at the model boundary, and even a foreign
    wire frame fails the terrain session's protocol-7 validation."""
    with pytest.raises(Exception):
        terrain_native.TerrainRequest(
            op="site",
            request_id="site-00",
            plan=SEAL,
            company=0,
            max_cost=0,
            pickup=45748,
            delivery=50351,
            depot=45487,
            tile=None,
        )
    junk_frame = terrain_native.encode_terrain_request(b'{"protocol":5,"op":"site"}')
    terrain = object.__new__(terrain_native.TerrainSecureSession)
    terrain._state = d5.AuthState.ACTIVE
    with pytest.raises(ValueError, match="ACTIVE|invalid|protocol|missing"):
        terrain.validate_outbound(junk_frame)


# --- replay verification fail-closed behavior ---------------------------------


def test_unconsumed_terrain_candidate_verifies_fail_closed(staged):
    verdict = terrain_native.verify_terrain_attempt(staged.directory)
    assert verdict == {
        "verification": "AUTHORIZATION_UNVERIFIED",
        "authorization_state": "CLAIM_ABSENT",
        "statement": (
            "the terrain candidate was never consumed by an operator "
            "authorization; no verified completion is possible"
        ),
    }
    assert claim_status(staged.directory) == "ABSENT"


@pytest.fixture()
def claimed(tmp_path, staged):
    """A retained-evidence directory with a self-consistent one-shot claim and
    a forced NATIVE_TERRAIN_COMPLETE result label — but no operator
    authorization record. The candidate carries the real staged seal; the
    synthetic evidence is written here and never by an execution."""
    from app.simulation.openttd.proof.harness import manifest

    target = tmp_path / "forced"
    target.mkdir()
    for name in ("PRELAUNCH.json", "PRELAUNCH.sha256"):
        (target / name).write_bytes((staged.directory / name).read_bytes())
    (target / "CLAIM.json").write_text(
        json.dumps(dict(prelaunch_digest=sha256(target / "PRELAUNCH.json"), consumed=True))
    )
    (target / "result.json").write_text(
        json.dumps(
            dict(
                verified=True,
                status="NATIVE_TERRAIN_COMPLETE",
                exchanges=[
                    "radius-00",
                    "tile-00",
                    "tile-01",
                    "tile-02",
                    "tile-03",
                    "tile-04",
                    "tile-05",
                    "tile-06",
                    "accept-00",
                    "accept-01",
                ],
                requests=10,
                native_launches=1,
                connections=1,
                command_accepted=True,
                last_status="READY",
                returncode=0,
                state_changed=False,
                cleanup_complete=True,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (target / "cleanup.json").write_text(
        json.dumps(
            dict(
                reaped=True,
                sockets_closed=True,
                workspace_disposed=True,
                credential_removed=True,
                returncode=0,
            ),
            sort_keys=True,
        )
    )
    welcome = json.loads((staged.directory / "PRELAUNCH.json").read_text())["world"][
        "expected_welcome"
    ]
    (target / "runtime-identity.json").write_text(
        json.dumps(
            dict(auth="X25519_AuthorizedKey", encrypted=True, welcome=welcome, pid=None),
            sort_keys=True,
        )
    )
    (target / "frames.json").write_text("[]")
    (target / "artifact-manifest.sha256").write_text(manifest(target))
    return target


def test_replay_never_verifies_a_forced_label_without_authorization(claimed):
    metadata = json.loads((claimed / "PRELAUNCH.json").read_text())
    seal = sha256(claimed / "PRELAUNCH.json")
    claims = json.loads((claimed / "CLAIM.json").read_text())
    assert replay_authorization_state(claimed, metadata, seal, claims) is not None
    verdict = terrain_native.verify_terrain_attempt(claimed)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] not in (None, "CLAIM_ABSENT")


def test_replay_refuses_a_claim_mismatched_to_its_seal(staged):
    target = staged.directory
    (target / "CLAIM.json").write_text(json.dumps(dict(prelaunch_digest="0" * 64)))
    try:
        with pytest.raises(ValueError, match="claim does not match"):
            terrain_native.verify_terrain_attempt(target)
    finally:
        (target / "CLAIM.json").unlink()


def test_replay_refuses_an_unreferenced_stray_file(claimed):
    target = claimed
    (target / "stray.txt").write_text("not in the manifest")
    with pytest.raises(ValueError, match="exhaustive"):
        terrain_native.verify_terrain_attempt(target)
    (target / "stray.txt").unlink()
    verdict = terrain_native.verify_terrain_attempt(target)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_replay_refuses_an_unknown_prelaunch_schema(tmp_path, staged):
    target = tmp_path / "alien"
    target.mkdir()
    metadata = metadata_of(staged)
    metadata["schema"] = d5.D5_FREIGHT_PRELAUNCH_SCHEMA  # the freight lineage, not terrain
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    (target / "CLAIM.json").write_text(
        json.dumps(dict(prelaunch_digest=sha256(target / "PRELAUNCH.json"), consumed=True))
    )
    from app.simulation.openttd.proof.harness import manifest

    (target / "artifact-manifest.sha256").write_text(manifest(target))
    verdict = terrain_native.verify_terrain_attempt(target)
    assert verdict["authorization_state"] == "UNKNOWN_PRELAUNCH_SCHEMA"


def test_replay_refuses_a_tampered_prelaunch_seal(tmp_path, staged):
    target = tmp_path / "tampered"
    target.mkdir()
    for name in ("PRELAUNCH.json", "PRELAUNCH.sha256"):
        (target / name).write_bytes((staged.directory / name).read_bytes())
    from app.simulation.openttd.proof.harness import manifest

    (target / "artifact-manifest.sha256").write_text(manifest(target))
    (target / "CLAIM.json").write_text(json.dumps(dict(prelaunch_digest="f" * 64, consumed=True)))
    with pytest.raises(ValueError, match="claim does not match"):
        terrain_native.verify_terrain_attempt(target)


def test_terrain_schedule_correspondence_pins_the_six_and_two(staged):
    """The staged schedule's six tile rows and two accept rows must land on
    exactly the pinned observation tiles, control-first."""
    policy = metadata_of(staged)["plan_policy"]
    schedule = policy["schedule"]
    tile_rows = [(row["exchange"], row["observation_tile"]) for row in schedule[1:8]]
    accept_rows = [(row["exchange"], row["observation_tile"]) for row in schedule[8:10]]
    assert tile_rows == [
        ("tile-00", 50095),
        ("tile-01", 50096),
        ("tile-02", 50352),
        ("tile-03", 50608),
        ("tile-04", 50864),
        ("tile-05", 50863),
        ("tile-06", 50862),
    ]
    assert accept_rows == [("accept-00", 50351), ("accept-01", 50862)]
    assert policy["world"]["terra_tiles"] == list(TERRAIN_TILES)
    assert policy["world"]["accept_tile_control"] == 50351
    assert policy["world"]["accept_tile_stop"] == 50862
    assert policy["world"]["expected_funds"] == 492149


# --- exit-status discipline -----------------------------------------------------


def test_terrain_exit_status_zero_only_for_the_verified_completion():
    assert (
        terrain_native.terrain_exit_status(
            dict(
                verified=True,
                status="NATIVE_TERRAIN_COMPLETE",
                cleanup_complete=True,
                state_changed=False,
            )
        )
        == 0
    )
    for bad in (
        dict(
            verified=True,
            status="NATIVE_TERRAIN_COMPLETE",
            cleanup_complete=False,
            state_changed=False,
        ),
        dict(
            verified=True,
            status="PHASE_HALTED_PREFIX_PRESERVED",
            cleanup_complete=True,
            state_changed=False,
        ),
        dict(
            verified=True,
            status="NATIVE_TERRAIN_COMPLETE",
            cleanup_complete=True,
            state_changed=True,
        ),
        dict(verified=False, status="FAILED", cleanup_complete=True, state_changed=False),
    ):
        assert terrain_native.terrain_exit_status(bad) == 1
    assert (
        terrain_native.terrain_verdict_exit_status(dict(verification="SURVEY_COMPLETION_VERIFIED"))
        == 0
    )
    assert (
        terrain_native.terrain_verdict_exit_status(
            dict(verification="PHASE_HALTED_EVIDENCE_PRESERVED")
        )
        == 1
    )
    # The sibling pipelines' own exit discipline is unchanged.
    assert (
        d5.exit_status(dict(verified=True, status="NATIVE_FREIGHT_VERIFIED", cleanup_complete=True))
        == 0
    )
    assert (
        survey_native.survey_verdict_exit_status(dict(verification="SURVEY_COMPLETION_VERIFIED"))
        == 0
    )


# --- Consumed-frame replay: synthetic packed terrain attempt fixture ------------
#
# Explicitly synthetic: it stages a real candidate (prerequisite = the pinned
# D4 candidate-5) and fabricates only the missing post-launch artifacts —
# nine correlated protocol-7 frames, the runtime welcome, cleanup
# certification and the flat retained receipt exactly as the execution
# writes it. No native process, AdminPort session, claim, signature or
# authorization is created. Because no authorized terrain run exists under
# the tests, the operator-authorization gate is the one seam monkeypatched;
# every prerequisite, identity, digest, phase, frame and cleanup fact is
# otherwise verified by the production replay path.

TERRAIN_EXCHANGES_EFFECTS = {
    "radius-00": dict(status="READY", radius=8),
    "tile-00": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-01": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-02": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-03": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-04": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-05": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "tile-06": dict(status="READY", facts=dict(slope=0, max_height=1, owner=-1)),
    "accept-00": dict(status="READY", radius=8, accept=0),
    "accept-01": dict(status="READY", radius=8, accept=0),
}


def _consumed_terrain_exchanges(seal: str, schedule):
    plan = terrain_native.terrain_survey_plan()
    exchanges = []
    for entry in schedule:
        request = terrain_native._terrain_exchange_request(entry, seal, plan)
        effects = TERRAIN_EXCHANGES_EFFECTS[entry["exchange"]]
        response = terrain_reply_bytes(request, **effects)
        readback = terrain_native.TerrainReadback.parse_for(request, response)
        exchanges.append((request, readback))
    return exchanges, plan


@pytest.fixture(scope="module")
def consumed_terrain_attempt(tmp_path_factory):
    prepared = terrain_native.prepare_terrain_survey_candidate(
        tmp_path_factory.mktemp("terrain-consumed") / "candidate"
    )
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    exchanges, plan = _consumed_terrain_exchanges(seal, metadata["plan_policy"]["schedule"])
    frames = []
    for request, readback in exchanges:
        response = json.dumps(
            readback.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (directory / (request.request_id + "-request.json")).write_bytes(request.to_bytes())
        (directory / (request.request_id + "-response.json")).write_bytes(response)
        frames.append(["outbound", terrain_native.encode_terrain_request(request.to_bytes()).hex()])
        frames.append(["inbound", _admin_frame(response + b"\0").hex()])
    (directory / "frames.json").write_text(json.dumps(frames))
    phase = terrain_native.terrain_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
    assert phase["verification"] == "SURVEY_COMPLETE"
    (directory / "session-before.sav").write_bytes(b"synthetic session-before fixture")
    (directory / "receipt.json").write_text(
        json.dumps(
            dict(
                phase,
                before_save_sha256="9" * 64,
                census_findings=terrain_native.census_findings_for(
                    phase, metadata["plan_policy"]["hypotheses"]
                ),
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "runtime-identity.json").write_text(
        json.dumps(
            dict(
                auth="X25519_AuthorizedKey",
                encrypted=True,
                welcome=dict(metadata["world"]["expected_welcome"], dedicated=True),
                pid=4242,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    # The run's own durable pre-welcome handshake evidence and stage journal,
    # exactly the documents the execution path writes at these boundaries.
    (directory / "handshake-evidence.json").write_text(
        json.dumps(
            dict(
                schema=terrain_native.TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA,
                attempt=terrain_native.TERRAIN_SURVEY_ATTEMPT,
                prelaunch_digest=seal,
                join_secure="AUTHENTICATED",
                welcome="VERIFIED",
                encrypted=True,
                protocol_version=3,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    journal_stages = [
        dict(stage=name, state="COMPLETED")
        for name in (
            "RUN_PREFLIGHT",
            "AUTHORIZATION_VERIFIED",
            "CLAIM_CREATED",
            "BACKEND_PREFLIGHT",
            "PROCESS_STARTED",
            "PROCESS_READY",
            "ADMINPORT_CONNECTED",
            "JOIN_SECURE_STARTED",
            "AUTHENTICATED",
            "WELCOME_RECEIVED",
            "WELCOME_VERIFIED",
            "RUNTIME_IDENTITY_WRITTEN",
            "SUBSCRIPTION_ESTABLISHED",
        )
    ]
    for entry in metadata["plan_policy"]["schedule"]:
        exchange_id = entry["exchange"] if isinstance(entry, dict) else entry
        for phase_name in ("STARTED", "COMPLETED"):
            journal_stages.append(
                dict(
                    stage="SURVEY_EXCHANGE_" + phase_name,
                    state="COMPLETED",
                    label=exchange_id,
                )
            )
    journal_stages += [
        dict(stage="CLEANUP_STARTED", state="COMPLETED"),
        dict(stage="CLEANUP_COMPLETED", state="COMPLETED"),
        dict(stage="TERMINAL_SUCCESS", state="COMPLETED"),
    ]
    (directory / "attempt-progress.json").write_text(
        json.dumps(
            dict(
                schema=terrain_native.TERRAIN_PROGRESS_SCHEMA,
                attempt=terrain_native.TERRAIN_SURVEY_ATTEMPT,
                prelaunch_digest=seal,
                stages=journal_stages,
                write_errors=[],
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "cleanup.json").write_text(
        json.dumps(
            dict(
                reaped=True,
                sockets_closed=True,
                workspace_disposed=True,
                credential_removed=True,
                returncode=0,
            ),
            sort_keys=True,
        )
        + "\n"
    )
    (directory / "CLAIM.json").write_text(
        json.dumps(
            dict(
                prelaunch_digest=seal,
                consumed=True,
                releases=0,
                launches_allowed=1,
                retries=0,
                requests_allowed=32,
                authorization_schema="d2-clearing-claim-authorization-v2",
                authorization_sha256="f" * 64,
                operator_key_identity="synthetic-test-fixture",
            ),
            sort_keys=True,
        )
        + "\n"
    )
    (directory / "result.json").write_text(
        json.dumps(
            dict(
                preflight="PASS",
                native_launches=1,
                connections=1,
                requests=10,
                exchanges=[request.request_id for request, _ in exchanges],
                last_status="READY",
                command_accepted=True,
                state_changed=False,
                verified=True,
                status="NATIVE_TERRAIN_COMPLETE",
                halt=None,
                returncode=0,
                cleanup_complete=True,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))
    yield directory, exchanges, seal, plan
    prepared.spec.workspace.close()


def test_replay_verifies_a_fully_consumed_terrain_frame_sequence(
    consumed_terrain_attempt, monkeypatch
):
    directory, exchanges, _, _ = consumed_terrain_attempt
    monkeypatch.setattr(terrain_native, "replay_authorization_state", lambda *a, **k: None)
    verdict = terrain_native.verify_terrain_attempt(directory)
    assert verdict["verification"] == "SURVEY_COMPLETION_VERIFIED"
    assert verdict["receipt"]["phase"]["verification"] == "SURVEY_COMPLETE"
    assert verdict["receipt"]["phase"]["radius"] == 8
    assert verdict["receipt"]["phase"]["observations"]["50351"]["value"] == 0
    assert verdict["receipt"]["phase"]["observations"]["50862"]["value"] == 0
    assert len(verdict["receipt"]["phase"]["terra"]) == 7
    assert verdict["receipt"]["phase"]["funds"] == 492149
    assert terrain_native.terrain_verdict_exit_status(verdict) == 0


def test_replay_fails_closed_on_tampered_retained_phase_in_receipt(
    consumed_terrain_attempt, monkeypatch
):
    directory, _, _, _ = consumed_terrain_attempt
    monkeypatch.setattr(terrain_native, "replay_authorization_state", lambda *a, **k: None)
    original = (directory / "receipt.json").read_text()
    before = json.loads(original)
    before["radius"] = 7
    (directory / "receipt.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))
    with pytest.raises(ValueError, match="receipt replay mismatch"):
        terrain_native.verify_terrain_attempt(directory)
    (directory / "receipt.json").write_text(original)


def test_replay_fails_closed_on_tampered_retained_census_findings(
    consumed_terrain_attempt, monkeypatch
):
    directory, _, _, _ = consumed_terrain_attempt
    monkeypatch.setattr(terrain_native, "replay_authorization_state", lambda *a, **k: None)
    before = json.loads((directory / "receipt.json").read_text())
    before["census_findings"] = [{"invented": "finding"}]
    (directory / "receipt.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))
    with pytest.raises(ValueError, match="census findings replay mismatch"):
        terrain_native.verify_terrain_attempt(directory)


def test_replay_verdict_refuses_a_forced_success_even_with_synthetic_auth(
    consumed_terrain_attempt,
):
    """Without the monkeypatched gate the synthetic authorization never
    verifies: the forced label cannot become a completion."""
    directory, _, _, _ = consumed_terrain_attempt
    verdict = terrain_native.verify_terrain_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


# --- Remediation: the claim-classification model and the audit's lifecycle ----
#
# Two irreversible candidate-level facts exist and are never conflated:
#   * ``CLAIM.json``  — the operator-authorized, candidate-level one-shot
#     claim (created once, exclusive-creation only; it makes any second
#     ``grant_launch`` impossible forever).
#   * ``LAUNCH-CONSUMED.json`` — the process-boundary consumption marker
#     written atomically inside the backend launch immediately before
#     ``Popen``; no process can exist without it.
# A launched-never-attempted failure (for example a backend-preflight
# failure) is reversible: the candidate is NOT consumed and may not ever
# leak the one-shot claim. The scenarios below drive each lifecycle
# boundary with a fully scripted backend double inside isolated fresh
# candidates: no scripted scenario can ever spawn a process, open a port
# or touch any retained attempt record; every post-claim failure is
# replayed through the production verdict paths and must name the exact
# stage that was reached, never a groundless success.


# --- synthetic anchors and scripted execution doubles ------------------------

# The production anchor, captured before any session patching: the runner
# never swaps the seeded operator key, and the identity check below refuses
# an unseeded or malformed anchor for every test (the sibling suites pin
# the same facts).
_PROD_ANCHOR = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
assert _PROD_ANCHOR is not None
operator_authorization.operator_key_identity(_PROD_ANCHOR)
# The real prerequisite binding, captured before any fixture patching.
_REAL_PREREQUISITE_BINDING = terrain_native.terrain_prerequisite_binding

# RFC 8032 §7.1 TEST 1 identity — synthetic only, never the production anchor.
_TEST_OPERATOR_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_TEST_OPERATOR_PUBLIC = (
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)


@pytest.fixture()
def synthetic_operator_anchor(monkeypatch):
    """Module execution under a synthetic operator anchor (the candidate's
    own gates only).

    The synthetic RFC 8032 §7.1 TEST 1 key anchors this candidate's own
    authorization story: record verification at ``grant_launch``, the
    one-shot claim and the launch-boundary re-verification all consume the
    TEST-key-signed record exclusively. The pinned D4 candidate-5
    prerequisite lineage is production history: its retained authorization
    record is signed by the production anchor and therefore re-verifies
    under exactly that anchor (the wrapper restores it for the prerequisite
    binding call only), which is also how a real launch executes. The TEST
    key can never verify the production record and the production anchor
    can never verify the synthetic one — both refusals stay enforced.
    """
    monkeypatch.setattr(operator_authorization, "OPERATOR_PUBLIC_KEY_HEX", _TEST_OPERATOR_PUBLIC)
    _pin_prerequisite_binding_under_production_anchor(monkeypatch)
    return _TEST_OPERATOR_PUBLIC


@pytest.fixture()
def fresh_candidate(tmp_path):
    """A freshly staged terrain candidate per execution-boundary scenario."""
    prepared = terrain_native.prepare_terrain_survey_candidate(tmp_path / "candidate")
    yield prepared
    prepared.spec.workspace.close()


# RFC 8032 §7.1 TEST 2 seed — synthetic only, never the production anchor and
# never the TEST 1 seed above, so a foreign-signature scenario is a real
# second key, not a self-signature.
_OTHER_OPERATOR_SEED = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"


def _pin_prerequisite_binding_under_production_anchor(monkeypatch) -> None:
    """The pinned D4 candidate-5 lineage replays under the production anchor.

    The prerequisite's retained authorization record was signed by the
    production anchor, so its replay verification must use exactly that
    anchor whatever synthetic key the candidate's own gates are using;
    the wrapper restores the anchor only for the binding call itself.
    """
    real_binding = _REAL_PREREQUISITE_BINDING

    def _binding_under_production_anchor(prerequisite=terrain_native.PINNED_PREREQUISITE):
        saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
        try:
            operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _PROD_ANCHOR
            return real_binding(prerequisite)
        finally:
            operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved

    monkeypatch.setattr(
        terrain_native, "terrain_prerequisite_binding", _binding_under_production_anchor
    )


def _authorize_candidate(prepared) -> None:
    """Issue and persist one synthetic-operator authorization record.

    The record is signed by the synthetic TEST 1 seed and verifies only
    under the synthetic anchor the ``synthetic_operator_anchor`` fixture
    pins; the production anchor (unseeded in offline tests) can never
    verify it. Purely local: no grant, no claim, no launch.
    """
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    payload = operator_authorization.authorization_payload(metadata, seal)
    record = operator_authorization.sign_authorization_record(payload, _TEST_OPERATOR_SEED)
    operator_authorization.write_authorization_record(directory, record)


def _seed_ready_logs(prepared) -> None:
    """Seed the staged workspace logs with the two native readiness markers.

    Only the log files the owned ``wait_log`` readiness reader looks at are
    written; no process, port or world is involved.
    """
    prepared.spec.workspace.logs.mkdir(parents=True, exist_ok=True)
    ready = (
        f"{terrain_native.FREIGHT_READY_MARKER} synthetic\n"
        f"{terrain_native.ROAD_PROOF_COMPANY_READY_MARKER} synthetic"
    )
    prepared.spec.stdout_path.write_text(ready)
    prepared.spec.stderr_path.write_text("")


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass


class _FakeProcess:
    pid = 4242
    stdin = _FakeStdin()

    def __init__(self, *, running: bool = True, returncode: int = 0) -> None:
        self._running = running
        self.returncode = None if running else returncode

    def poll(self):
        return None if self._running else self.returncode


class _SessionDouble:
    """A session never connected to anything: scripted auth outcomes only."""

    def __init__(
        self,
        *,
        auth_error: Exception | None = None,
        auth_ok: bool = False,
        welcome: object = None,
        protocol_version: int | None = 3,
        active: AuthState | None = None,
    ) -> None:
        self._auth_error = auth_error
        self._auth_ok = auth_ok
        self.welcome = welcome
        self.protocol = (
            None if protocol_version is None else SimpleNamespace(version=protocol_version)
        )
        self.state = active

    async def authenticate(self, name: str, version: str, *, timeout: float = 1) -> None:
        if self._auth_error is not None:
            raise self._auth_error
        assert self._auth_ok


def _world_welcome(metadata: dict, **overrides) -> object:
    """A synthetic welcome object bound to the staged world identity.

    The received welcome is re-ordered by the production ``WELCOME_ORDER``
    inside the execution path; only a deliberately mutated well-typed field
    can therefore produce a pinned mismatch, never a shape difference.
    """
    expected = dict(metadata["world"]["expected_welcome"])
    expected["dedicated"] = True
    expected.update(overrides)
    welcome = make_dataclass(
        "SyntheticWelcome",
        [(name, type(expected[name])) for name in terrain_native.WELCOME_ORDER],
    )
    return welcome(**expected)


class _ScriptedBackend:
    """A fully scripted backend double; never a process, never a port.

    Every ``launch`` behavior is a controlled failure that reproduces exactly
    the scenario's boundary facts: the real consumption marker is written
    (once, through the production ``record_boundary_consumption``) only when
    the scripted run actually reaches the process seam, and the fake process
    never exists. ``cleanup`` certifies offline by default or scripts the
    exact failure families under test.
    """

    def __init__(
        self,
        *,
        preflight_error: Exception | None = None,
        launch_behavior: object = None,
        session: _SessionDouble | None = None,
        cleanup_extra: dict | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        self.preflight_error = preflight_error
        self._launch_behavior = launch_behavior
        self.session = session
        self._cleanup_extra = cleanup_extra
        self._cleanup_error = cleanup_error
        self.process = None

    def preflight(self, prepared) -> None:
        if self.preflight_error is not None:
            raise self.preflight_error
        # The real read-only backend preflight: credentials, pins, ownership.
        # It creates no external state, reserves nothing and is repeatable.
        object.__new__(terrain_native.TerrainNativeBackend).preflight(prepared)

    def consumed_boundary(self, prepared, authorization) -> None:
        """The real process-boundary consumption, exactly at the scripted seam."""
        record_boundary_consumption(
            prepared,
            authorization,
            sha256(prepared.directory / "PRELAUNCH.json"),
            marker_schema=terrain_native.D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA,
        )

    async def launch(self, prepared, *, authorization=None) -> None:
        assert authorization is not None
        behavior = self._launch_behavior
        if behavior == "boundary_refusal":
            raise ValueError("scripted launch boundary refusal")
        if behavior == "process_creation_failure":
            self.consumed_boundary(prepared, authorization)
            raise OSError("scripted process creation failure")
        if behavior == "ready_failure":
            self.consumed_boundary(prepared, authorization)
            self.process = _FakeProcess(running=False, returncode=1)
            return
        if behavior == "auth_failure":
            self.consumed_boundary(prepared, authorization)
            _seed_ready_logs(prepared)
            self.process = _FakeProcess(running=True)
            return
        raise ValueError("an unscripted launch behavior cannot execute")

    def health(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("OpenTTD exited early")

    async def connect(self, prepared, *, frame_observer):
        assert frame_observer is not None
        return self.session

    async def cleanup(self, prepared) -> dict:
        record = dict(
            pid=None if self.process is None else self.process.pid,
            graceful_attempted=self.process is not None and self.process.poll() is None,
            quit_command="quit",
            returncode=None if self.process is None else self.process.returncode,
            reaped=self.process is None or self.process.poll() is not None,
            remaining_processes=[],
            events=[],
            cleanup_error=[],
        )
        error = self._cleanup_error
        prepared.key_path.unlink(missing_ok=True)
        if error is not None:
            raise error
        record.update(self._cleanup_extra or {})
        return record


# --- scripted lifecycle evidence helpers -------------------------------------


def _journal_entries(directory: Path) -> list[dict]:
    """The retained stage journal of a scripted attempt, schema-checked."""
    document = json.loads((directory / "attempt-progress.json").read_text())
    assert document["schema"] == terrain_native.TERRAIN_PROGRESS_SCHEMA
    assert document.get("write_errors") == []
    return list(document["stages"])


def _stage_names(directory: Path) -> list[str]:
    return [entry["stage"] for entry in _journal_entries(directory)]


def _claim_of(directory: Path) -> dict:
    return json.loads((directory / "CLAIM.json").read_text())


def _marker_of(directory: Path) -> dict:
    marker = json.loads((directory / "LAUNCH-CONSUMED.json").read_text())
    assert marker["schema"] == terrain_native.D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA
    return marker


def _replay_verdict(monkeypatch, directory: Path) -> dict:
    """Replay through the production verifier with synthetic authorization."""
    monkeypatch.setattr(terrain_native, "replay_authorization_state", lambda *a, **k: None)
    return terrain_native.verify_terrain_attempt(directory)


def _reseal(directory: Path) -> None:
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))


def _copy_consumed(consumed_terrain_attempt, tmp_path: Path) -> Path:
    """An independent copy of the fully consumed synthetic attempt record."""
    directory, _, _, _ = consumed_terrain_attempt
    target = tmp_path / "consumed-copy"
    shutil.copytree(directory, target)
    return target


# --- the fully reversible region: everything before the claim -----------------


def execute_fresh(prepared, backend):
    return asyncio.run(terrain_native.execute_terrain_attempt(prepared, backend))


def test_backend_preflight_failure_stays_fully_reversible(
    fresh_candidate, synthetic_operator_anchor
):
    """A backend preflight refusal never reaches any irreversible transition."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    with pytest.raises(RuntimeError, match="backend scripts missing"):
        execute_fresh(
            prepared,
            _ScriptedBackend(preflight_error=RuntimeError("backend scripts missing")),
        )
    directory = prepared.directory
    assert not (directory / "CLAIM.json").exists()
    assert not (directory / "LAUNCH-CONSUMED.json").exists()
    assert not (directory / "attempt-progress.json").exists()
    assert claim_status(directory) == "ABSENT"
    verdict = terrain_native.verify_terrain_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "CLAIM_ABSENT"


def test_missing_authorization_record_refuses_before_the_claim(
    fresh_candidate, synthetic_operator_anchor
):
    """grant_launch refuses a candidate without an operator-issued record."""
    prepared = fresh_candidate
    with pytest.raises(ClearingAuthorizationError, match="no operator authorization record"):
        execute_fresh(prepared, _ScriptedBackend())
    directory = prepared.directory
    assert not (directory / "CLAIM.json").exists()
    assert not (directory / "LAUNCH-CONSUMED.json").exists()
    assert claim_status(directory) == "ABSENT"
    verdict = terrain_native.verify_terrain_attempt(directory)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] == "CLAIM_ABSENT"


def test_unseeded_anchor_refuses_every_launch_gate(fresh_candidate, monkeypatch):
    """Before any record exists, an unseeded anchor refuses any launch gate."""
    prepared = fresh_candidate
    _pin_prerequisite_binding_under_production_anchor(monkeypatch)
    monkeypatch.setattr(operator_authorization, "OPERATOR_PUBLIC_KEY_HEX", None)
    with pytest.raises(ClearingAuthorizationError, match="unseeded"):
        execute_fresh(prepared, _ScriptedBackend())
    directory = prepared.directory
    assert not (directory / "CLAIM.json").exists()
    with pytest.raises(ClearingAuthorizationError, match="unseeded"):
        operator_authorization.grant_launch(
            directory,
            json.loads((directory / "PRELAUNCH.json").read_text()),
            sha256(directory / "PRELAUNCH.json"),
        )


def test_foreign_authorization_signature_refuses_the_claim(
    fresh_candidate, synthetic_operator_anchor
):
    """An authorization signed by another key can never bind this candidate."""
    prepared = fresh_candidate
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    payload = operator_authorization.authorization_payload(metadata, seal)
    record = operator_authorization.sign_authorization_record(payload, _OTHER_OPERATOR_SEED)
    operator_authorization.write_authorization_record(directory, record)
    with pytest.raises(
        ClearingAuthorizationError, match="not signed by the seeded operator anchor"
    ):
        execute_fresh(prepared, _ScriptedBackend())
    assert not (directory / "CLAIM.json").exists()
    assert not (directory / "LAUNCH-CONSUMED.json").exists()
    assert claim_status(directory) == "ABSENT"


def test_binary_identity_mismatch_refuses_read_only_preflight(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """A drift of the pinned executable identity is refused at preflight."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    monkeypatch.setattr(terrain_native, "BINARY_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="staged identity pins drifted"):
        execute_fresh(prepared, _ScriptedBackend())
    directory = prepared.directory
    assert not (directory / "CLAIM.json").exists()
    assert not (directory / "LAUNCH-CONSUMED.json").exists()
    assert claim_status(directory) == "ABSENT"


# --- the irreversible region: claim, marker, and preserved failures ----------


def test_claim_arrives_only_after_every_reversible_gate(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """A refused launch keeps its claim but never writes the process marker."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    result = execute_fresh(prepared, _ScriptedBackend(launch_behavior="boundary_refusal"))
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    assert result["status"] == "FAILED"
    assert result["native_launches"] == 0
    assert result["connections"] == 0
    assert "scripted launch boundary refusal" in result["error"]
    claim = _claim_of(directory)
    assert claim["consumed"] is True and claim["launches_allowed"] == 1
    assert claim["prelaunch_digest"] == seal
    assert not (directory / "LAUNCH-CONSUMED.json").exists()
    names = _stage_names(directory)
    for stage in ("RUN_PREFLIGHT", "BACKEND_PREFLIGHT", "AUTHORIZATION_VERIFIED"):
        assert stage in names
    assert names.index("CLAIM_CREATED") < names.index("TERMINAL_FAILURE")
    assert "PROCESS_STARTED" not in names
    last = _journal_entries(directory)[-1]
    assert last["stage"] == "TERMINAL_FAILURE" and last["state"] == "FAILED"
    # the one-shot claim makes any second operator grant impossible forever
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    with pytest.raises(ClearingAuthorizationError, match="already consumed"):
        operator_authorization.grant_launch(directory, metadata, seal)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED"
    assert verdict["reached_stage"]["stage"] == "TERMINAL_FAILURE"
    assert verdict["handshake"]["state"] == "ABSENT"


def test_process_boundary_is_the_launch_consumption_point(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """Marker consumption happens at the seam; no process was ever created."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    result = execute_fresh(
        prepared, _ScriptedBackend(launch_behavior="process_creation_failure")
    )
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    assert result["status"] == "FAILED"
    assert result["error"].startswith("OSError: scripted process creation failure")
    claim = _claim_of(directory)
    marker = _marker_of(directory)
    assert claim["prelaunch_digest"] == marker["prelaunch_digest"] == seal
    assert marker["authorization_sha256"] == operator_authorization.record_digest(directory)
    assert marker["operator_key_identity"] == claim["operator_key_identity"]
    names = _stage_names(directory)
    assert "PROCESS_STARTED" not in names
    last = _journal_entries(directory)[-1]
    assert last["stage"] == "TERMINAL_FAILURE" and last["state"] == "FAILED"
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["reached_stage"]["stage"] == "TERMINAL_FAILURE"


def test_runtime_exit_before_readiness_preserves_the_failed_stage(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """An exited runtime is preserved: the process started, readiness failed."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    result = execute_fresh(prepared, _ScriptedBackend(launch_behavior="ready_failure"))
    directory = prepared.directory
    assert result["status"] == "FAILED"
    assert result["error"].startswith("RuntimeError: OpenTTD exited early")
    assert (_marker_of(directory))["prelaunch_digest"] == sha256(
        directory / "PRELAUNCH.json"
    )
    names = _stage_names(directory)
    assert names.index("PROCESS_STARTED") < names.index("TERMINAL_FAILURE")
    assert "PROCESS_READY" not in names
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED"
    assert verdict["error"].startswith("RuntimeError")
    assert verdict["reached_stage"]["state"] == "FAILED"


@pytest.mark.parametrize(
    ("join_failure", "evidence_state"),
    (
        (AuthRejected("join refused"), "REJECTED"),
        (AuthTimeout("no join reply"), "TIMED_OUT"),
        (AuthDisconnected("join stream dropped"), "IO_FAILED"),
    ),
)
def test_join_refusals_are_preserved_as_handshake_evidence(
    fresh_candidate, synthetic_operator_anchor, monkeypatch, join_failure, evidence_state
):
    """Every JOIN_SECURE refusal writes durable pre-welcome handshake facts."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    result = execute_fresh(
        prepared,
        _ScriptedBackend(
            launch_behavior="auth_failure",
            session=_SessionDouble(auth_error=join_failure),
        ),
    )
    directory = prepared.directory
    assert result["status"] == "FAILED"
    assert result["error"].startswith(type(join_failure).__name__ + ":")
    # The AdminPort TCP connection itself was established before the refused
    # JOIN_SECURE exchange; the durable stages and handshake evidence pin
    # exactly that lifecycle (connected, started, refused, never welcomed).
    assert result["connections"] == 1
    handshake = json.loads((directory / "handshake-evidence.json").read_text())
    assert handshake["schema"] == terrain_native.TERRAIN_HANDSHAKE_EVIDENCE_SCHEMA
    assert handshake["join_secure"] == evidence_state
    assert handshake["welcome"] == "NOT_RECEIVED"
    assert handshake["encrypted"] is False
    names = _stage_names(directory)
    assert names.index("ADMINPORT_CONNECTED") < names.index("JOIN_SECURE_STARTED")
    assert "AUTHENTICATED" not in names
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["handshake"]["join_secure"] == evidence_state
    assert verdict["reached_stage"]["stage"] == "TERMINAL_FAILURE"


def test_welcome_mismatch_after_an_authenticated_join(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """A welcome received but wrong is never a handshake success."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    result = execute_fresh(
        prepared,
        _ScriptedBackend(
            launch_behavior="auth_failure",
            session=_SessionDouble(
                auth_ok=True,
                active=AuthState.ACTIVE,
                welcome=_world_welcome(metadata, width=1),
            ),
        ),
    )
    directory = prepared.directory
    assert result["status"] == "FAILED"
    assert "the retained world identity mismatch" in result["error"]
    assert not (directory / "runtime-identity.json").exists()
    handshake = json.loads((directory / "handshake-evidence.json").read_text())
    assert handshake["join_secure"] == "AUTHENTICATED"
    assert handshake["encrypted"] is True
    assert handshake["protocol_version"] == 3
    assert handshake["welcome"] == "MISMATCH"
    names = _stage_names(directory)
    assert names.index("WELCOME_RECEIVED") < names.index("TERMINAL_FAILURE")
    assert "WELCOME_VERIFIED" not in names
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["handshake"]["join_secure"] == "AUTHENTICATED"
    assert verdict["handshake"]["welcome"] == "MISMATCH"


# --- cleanup certification and its evidence classes ---------------------------


def test_cleanup_crash_after_the_claim_preserves_partial_stages(
    fresh_candidate, synthetic_operator_anchor
):
    """A cleanup crash keeps every earlier stage and stays fully refused."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    with pytest.raises(RuntimeError, match="scripted cleanup crash"):
        execute_fresh(
            prepared,
            _ScriptedBackend(
                launch_behavior="boundary_refusal",
                cleanup_error=RuntimeError("scripted cleanup crash"),
            ),
        )
    directory = prepared.directory
    assert (directory / "CLAIM.json").is_file()
    assert not (directory / "result.json").exists()
    assert not (directory / "cleanup.json").exists()
    assert not (directory / "artifact-manifest.sha256").exists()
    assert (directory / "attempt-progress.json").is_file()
    last = _journal_entries(directory)[-1]
    assert last["stage"] == "CLEANUP_STARTED" and last["state"] == "COMPLETED"
    verdict = _replay_verdict(pytest.MonkeyPatch(), directory)
    assert verdict["verification"] == "EVIDENCE_INCOMPLETE"
    assert verdict["evidence_states"]["claim"]["consumed"] is True
    assert verdict["reached_stage"]["stage"] == "CLEANUP_STARTED"


def test_uncertified_cleanup_fails_the_attempt_closed(
    fresh_candidate, synthetic_operator_anchor, monkeypatch
):
    """A cleanup that cannot certify ownership refuses the attempt outright."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    result = execute_fresh(
        prepared,
        _ScriptedBackend(
            launch_behavior="boundary_refusal",
            cleanup_extra=dict(remaining_processes=["stray-openttd"]),
        ),
    )
    directory = prepared.directory
    assert result["status"] == "FAILED"
    assert result["cleanup_complete"] is False
    assert result["cleanup_failure"] is True
    cleanup = json.loads((directory / "cleanup.json").read_text())
    assert "unambiguous owned process reap" in cleanup["verification_error"]
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED"


# --- the exclusive one-shot claim ---------------------------------------------


def test_exclusive_claim_refuses_a_second_claim(fresh_candidate, synthetic_operator_anchor):
    """The claim is O_EXCL-created once; a second creation always refuses."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    grant = operator_authorization.grant_launch(directory, metadata, seal)
    terrain_native.write_terrain_claim(directory, seal, grant)
    claim = _claim_of(directory)
    assert claim["consumed"] is True
    assert claim["launches_allowed"] == 1
    assert claim["retries"] == 0
    assert claim["operator_key_identity"] == grant.operator_key_identity
    assert claim_status(directory) == "CONSUMED"
    with pytest.raises(terrain_native.TerrainSurveyStagingError, match="already claimed"):
        terrain_native.write_terrain_claim(directory, seal, grant)


def test_concurrent_claims_produce_exactly_one_winner(
    fresh_candidate, synthetic_operator_anchor
):
    """Concurrent claim creation names exactly one winner and three refusals."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    grant = operator_authorization.grant_launch(directory, metadata, seal)
    outcomes: list[str] = []

    def attempt() -> None:
        try:
            terrain_native.write_terrain_claim(directory, seal, grant)
            outcomes.append("claimed")
        except terrain_native.TerrainSurveyStagingError:
            outcomes.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("claimed") == 1
    assert outcomes.count("refused") == 3
    assert claim_status(directory) == "CONSUMED"


def test_boundary_marker_opens_exactly_once(fresh_candidate, synthetic_operator_anchor):
    """The process-boundary marker itself is exclusive across launches."""
    prepared = fresh_candidate
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    authorization = SimpleNamespace(
        authorization_sha256=sha256(directory / "PRELAUNCH.json"),
        operator_key_identity="synthetic-boundary-test-identity",
    )
    record_boundary_consumption(
        prepared, authorization, seal, marker_schema=terrain_native.D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA
    )
    marker = _marker_of(directory)
    assert marker["prelaunch_digest"] == seal
    assert marker["authorization_sha256"] == authorization.authorization_sha256
    with pytest.raises(ClearingAuthorizationError, match="already consumed at the process boundary"):
        record_boundary_consumption(
            prepared,
            authorization,
            seal,
            marker_schema=terrain_native.D5_TERRAIN_LAUNCH_CONSUMED_SCHEMA,
        )


# --- the launch boundary refuses drift before the seam ------------------------


def test_launch_critical_identity_mismatch_refuses_before_the_process_seam(
    fresh_candidate, synthetic_operator_anchor
):
    """A grant whose stat identity cannot match refuses without consuming."""
    prepared = fresh_candidate
    _authorize_candidate(prepared)
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    grant = operator_authorization.grant_launch(directory, metadata, seal)
    grant.launch_identity = None
    terrain_native.write_terrain_claim(directory, seal, grant)
    backend = terrain_native.TerrainNativeBackend(authorized_one_launch=True)
    with pytest.raises(ClearingAuthorizationError, match="launch-critical files changed"):
        asyncio.run(backend.launch(prepared, authorization=grant))
    assert not (directory / "LAUNCH-CONSUMED.json").exists()


# --- replay reliability of the structured evidence classes --------------------


def test_replay_fails_incomplete_when_the_terminal_evidence_never_survived(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A claimed attempt without its result artifact is always a refusal."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "result.json").unlink()
    (directory / "artifact-manifest.sha256").unlink()
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INCOMPLETE"
    assert verdict["evidence_states"]["result"]["state"] == "ABSENT"
    assert verdict["evidence_states"]["claim"]["consumed"] is True
    assert verdict["reached_stage"]["stage"] == "TERMINAL_SUCCESS"
    assert verdict["reached_stage"]["state"] == "COMPLETED"


def test_replay_fails_closed_on_an_unsupported_stage_journal_schema(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A stage journal of an unknown schema version can never confirm stages."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    document = json.loads((directory / "attempt-progress.json").read_text())
    document["schema"] = "d5-terrain-survey-attempt-progress-v9"
    (directory / "attempt-progress.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n"
    )
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INVALID"
    assert (
        verdict["evidence_states"]["attempt_progress"]["state"]
        == "UNSUPPORTED_SCHEMA_VERSION"
    )


def test_replay_refuses_a_completed_attempt_without_handshake_evidence(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """Without its durable handshake evidence a completion can never verify."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "handshake-evidence.json").unlink()
    _reseal(directory)
    with pytest.raises(ValueError, match="lacks its handshake evidence"):
        _replay_verdict(monkeypatch, directory)


def test_replay_refuses_a_completed_attempt_without_its_stage_journal(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """Without its stage journal the terminal state is unconfirmable."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "attempt-progress.json").unlink()
    _reseal(directory)
    with pytest.raises(ValueError, match="lacks its stage journal"):
        _replay_verdict(monkeypatch, directory)


# --- R2 remediation: replay reads every artifact fail-closed ------------------


def test_replay_fails_incomplete_without_runtime_identity_and_records_the_stage(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A pre-welcome failure with no runtime identity is preserved, not a crash."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "runtime-identity.json").unlink()
    document = json.loads((directory / "result.json").read_text())
    document["status"] = "FAILED"
    document["verified"] = False
    document["error"] = "ImportError: the demo network never observed the survey"
    (directory / "result.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n"
    )
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED"
    assert verdict["evidence_states"]["runtime_identity"]["state"] == "ABSENT"
    assert verdict["reached_stage"]["stage"] == "TERMINAL_SUCCESS"


def test_replay_never_verifies_a_completion_without_runtime_identity(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A claimed completion whose runtime evidence is missing is a refusal."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "runtime-identity.json").unlink()
    _reseal(directory)
    with pytest.raises(ValueError, match="missing; no completion is possible"):
        _replay_verdict(monkeypatch, directory)


def test_replay_names_malformed_runtime_identity_evidence_invalid(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A malformed runtime identity can neither verify nor crash replay."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "runtime-identity.json").write_text("{not json")
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INVALID"
    assert verdict["evidence_states"]["runtime_identity"]["state"] == "MALFORMED"


def test_replay_names_malformed_result_evidence_invalid(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A malformed attempt record names itself in the structured refusal."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "result.json").write_text("null")
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INVALID"
    assert verdict["evidence_states"]["result"]["state"] == "MALFORMED"


def test_replay_names_malformed_frames_evidence_invalid(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A malformed frame stream can never carry the retained exchanges."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "frames.json").write_text("[truncated")
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INVALID"
    assert verdict["evidence_states"]["frames"]["state"] == "MALFORMED"


def test_replay_fails_incomplete_when_its_frame_stream_never_survived(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """Without frames a completed record cannot prove its exchanges ran."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    (directory / "frames.json").unlink()
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "EVIDENCE_INCOMPLETE"
    assert verdict["evidence_states"]["frames"]["state"] == "ABSENT"


def test_replay_refuses_a_completion_its_handshake_contradicts(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A completion with a mismatching handshake record refuses outright."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    document = json.loads((directory / "handshake-evidence.json").read_text())
    document["welcome"] = "MISMATCH"
    (directory / "handshake-evidence.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n"
    )
    _reseal(directory)
    with pytest.raises(ValueError, match="handshake evidence"):
        _replay_verdict(monkeypatch, directory)


def test_replay_refuses_a_failed_result_its_journal_calls_terminal_success(
    consumed_terrain_attempt, tmp_path, monkeypatch
):
    """A failed attempt record is never promoted by its journal's last stage."""
    directory = _copy_consumed(consumed_terrain_attempt, tmp_path)
    document = json.loads((directory / "result.json").read_text())
    document["status"] = "FAILED"
    document["verified"] = False
    (directory / "result.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n"
    )
    _reseal(directory)
    verdict = _replay_verdict(monkeypatch, directory)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED"
    # the journal's TERMINAL_SUCCESS label never promotes the failed record
    assert verdict["reached_stage"]["stage"] == "TERMINAL_SUCCESS"
