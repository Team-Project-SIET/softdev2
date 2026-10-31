"""Controlled offline tests for the D5-ACCEPT-SURVEY-1 native staging pipeline.

The pipeline under test is
``app/simulation/openttd/proof/corridor_accept_survey_native.py``, staged as a
fresh candidate from the pinned D4 candidate-5 prerequisite. Everything here
is strictly offline: no OpenTTD launch, no AdminPort connection, no claim, no
authorization artifact, and no mutation of any retained attempt record or
authoritative save. Replay behavior is exercised with real production
verdict paths (claim-absent, tampered seals, synthetic retained evidence
without operator authorization), so every refusal is the real fail-closed
outcome, never a mock of the verifier.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import app.simulation.openttd.proof.corridor_accept_survey_native as survey_native
import app.simulation.openttd.proof.corridor_freight_native as d5
from app.simulation.openttd.corridor_accept_survey import (
    PLANNED_SURVEY_EXCHANGES,
    SURVEY_OBSERVATION_TILES,
    SurveyRequest,
    survey_plan,
)
from app.simulation.openttd.corridor_freight import FreightRequest
from app.simulation.openttd.proof.corridor_freight_native import FreightStagingError
from app.simulation.openttd.proof.harness import sha256
from app.simulation.openttd.proof.operator_authorization import (
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_clearing import (
    claim_status,
    replay_authorization_state,
)
from tests.test_corridor_accept_survey import SEAL as SURVEY_SEAL
from tests.test_corridor_freight import PRELAUNCH as FREIGHT_SEAL


def survey_request(exchange: str, tile: int | None) -> SurveyRequest:
    return SurveyRequest(
        op={"radius-00": "radius", "prod-00": "prod"}.get(exchange, "accept"),
        request_id=exchange,
        plan=SURVEY_SEAL,
        company=0,
        max_cost=0,
        pickup=45748,
        delivery=50351,
        depot=45487,
        tile=tile,
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


def survey_reply_bytes(
    request: SurveyRequest,
    *,
    status: str = "READY",
    radius: int = 8,
    accept: int | None = 0,
    prod: int | None = None,
    funds: int = 492149,
) -> bytes:
    body: dict = {
        "protocol": 6,
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
    elif request.op == "prod":
        body["prod"] = 104 if prod is None else prod
    elif status == "READY":
        body["accept"] = 0 if accept is None else accept
        body["radius"] = radius
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    prepared = survey_native.prepare_survey_candidate(
        tmp_path_factory.mktemp("survey-staging") / "candidate"
    )
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(prepared) -> dict:
    return json.loads((prepared.directory / "PRELAUNCH.json").read_text())


# --- the plan-bound pipeline and the cross-session guards --------------------


def test_survey_pipeline_accepts_an_acceptsurveyplan_only():
    plan = survey_plan()
    assert survey_native._require_survey_plan(plan).digest == plan.digest
    with pytest.raises(survey_native.SurveyStagingError, match="AcceptSurveyPlan"):
        survey_native._require_survey_plan(d5.freight_plan())
    with pytest.raises(survey_native.SurveyStagingError, match="AcceptSurveyPlan"):
        survey_native._require_survey_plan(dict(digest=plan.digest))


def test_freight_and_survey_requests_cannot_cross_the_sessions():
    """A freight request fails the survey session check and a survey request
    fails the freight session check; both before any handler can run."""
    survey = object.__new__(survey_native.SurveySecureSession)
    survey._state = d5.AuthState.ACTIVE
    survey_frame = survey_native.encode_survey_request(
        survey_request("accept-00", 50351).to_bytes()
    )
    survey.validate_outbound(survey_frame)
    with pytest.raises(Exception):
        survey.validate_outbound(d5.encode_freight_request(freight_site_request().to_bytes()))
    with pytest.raises(Exception):
        survey.validate_outbound(b"garbage")
    freight = object.__new__(d5.FreightSecureSession)
    freight._state = d5.AuthState.ACTIVE
    freight.validate_outbound(d5.encode_freight_request(freight_site_request().to_bytes()))
    with pytest.raises(Exception, match="protocol|missing"):
        freight.validate_outbound(survey_frame)


def test_survey_schedule_is_the_pinned_read_only_eight():
    schedule = survey_native.survey_schedule()
    assert [row["exchange"] for row in schedule] == [
        "radius-00",
        "accept-00",
        "accept-01",
        "accept-02",
        "accept-03",
        "accept-04",
        "accept-05",
        "prod-00",
    ]
    assert all(row["op"] in ("radius", "accept", "prod") for row in schedule)
    assert [row.get("observation_tile") for row in schedule[1:7]] == list(SURVEY_OBSERVATION_TILES)
    for foreign in ("site", "purchase", "order", "start", "load-watch"):
        with pytest.raises(Exception):
            survey_native.survey_exchange_timeout_seconds(
                budget_table=survey_native.survey_budgets(), op=foreign
            )


# --- staging correctness ------------------------------------------------------


def test_staged_candidate_binds_the_survey_lineage(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == survey_native.D5_SURVEY_PRELAUNCH_SCHEMA
    assert metadata["attempt"] == survey_native.SURVEY_ATTEMPT
    assert metadata["milestone"] == survey_native.MILESTONE_SURVEY
    assert metadata["kind"] == survey_native.KIND
    assert metadata["budgets"]["max_cost"] == 0
    assert metadata["budgets"]["planned_exchanges"] == PLANNED_SURVEY_EXCHANGES
    assert metadata["plan_policy"]["max_cost"] == 0
    assert metadata["plan_policy"]["plan_model_digest"] == survey_plan().digest
    assert metadata["prerequisite"]["after_save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert metadata["world"]["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    read_only = metadata["plan_policy"]["read_only"]
    assert read_only["permitted_ops"] == ["radius", "accept", "prod"]
    assert read_only["max_cost"] == 0 and read_only["funds_readback_required"] is True


def test_survey_prerequisite_binding_must_be_the_pinned_candidate5(staged):
    binding = survey_native.survey_prerequisite_binding()
    assert binding["attempt"] == "D4-CORRIDOR-5"
    assert binding["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    other = Path("artifacts/experiments/d4-corridor-native-candidate-4")
    if other.is_dir():
        with pytest.raises(FreightStagingError, match="not the pinned"):
            survey_native.survey_prerequisite_binding(other)


def test_staged_source_save_is_the_authoritative_after_save(staged):
    metadata = metadata_of(staged)
    staged_save = Path(metadata["workspace"]) / "source.sav"
    assert sha256(staged_save) == d5.PINNED_PREREQUISITE_AFTER_SAVE


def test_authorization_payload_rebuilds_and_no_claim_exists(staged):
    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    digest = survey_native.staged_survey_authorization_payload_digest(staged.directory)
    rebuilt = (
        __import__("hashlib")
        .sha256(canonical_authorization_bytes(authorization_payload(metadata, seal)))
        .hexdigest()
    )
    assert (
        rebuilt
        == digest
        == survey_native.staged_survey_authorization_payload_digest(staged.directory)
    )
    assert not (staged.directory / "CLAIM.json").exists()
    assert not (staged.directory / "AUTHORIZATION.json").exists()
    assert claim_status(staged.directory) == "ABSENT"


def test_survey_preflight_re_derives_every_binding(staged):
    metadata = survey_native.survey_preflight(staged)
    assert metadata["attempt"] == survey_native.SURVEY_ATTEMPT


def test_survey_preflight_refuses_seal_tampering(staged):
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    metadata = json.loads(original)
    metadata["budgets"]["max_cost"] = 7
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    restamp = (target / "PRELAUNCH.sha256").read_text()
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="budget|max_cost|max_cost drift|budget pins drifted"):
            survey_native.survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(restamp)


def test_survey_schedule_and_plan_drift_refuse_preflight(staged):
    target = staged.directory
    original = (target / "PRELAUNCH.json").read_bytes()
    seal_text = (target / "PRELAUNCH.sha256").read_text()
    # A schedule whose first exchange lost the radius-first observation:
    metadata = json.loads(original)
    metadata["plan_policy"]["schedule"] = metadata["plan_policy"]["schedule"][1:]
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    try:
        with pytest.raises(ValueError, match="drifted"):
            survey_native.survey_preflight(staged)
    finally:
        (target / "PRELAUNCH.json").write_bytes(original)
        (target / "PRELAUNCH.sha256").write_text(seal_text)


def test_hypotheses_stay_hypotheses_and_control_is_first(staged):
    hypotheses = metadata_of(staged)["plan_policy"]["hypotheses"]
    assert hypotheses["state"] == "RETAINED_CENSUS_REBOUND"
    rows = hypotheses["hypotheses"]
    assert rows[0]["tile"] == 50351 and rows[0]["hypothesis_acceptance_eighths"] == 0
    assert all(row["kind"] == "HYPOTHESIS" for row in rows)
    assert [row["tile"] for row in rows] == list(SURVEY_OBSERVATION_TILES)


def test_census_findings_record_real_measured_divergence():
    hypotheses = survey_native.census_hypotheses()
    observations = {
        tile: dict(value=0, request_id=f"accept-{index:02d}")
        for index, tile in enumerate(SURVEY_OBSERVATION_TILES)
    }
    findings = survey_native.compare_census_findings(observations, hypotheses)
    assert sorted(f["tile"] for f in findings) == sorted([50607, 50863, 51119, 51375, 50605])
    assert findings[0]["statement"].startswith("the native value differs")
    assert survey_native.compare_census_findings({}, {"state": "CENSUS_ABSENT"}) == []
    complete = {
        tile: dict(value=h["hypothesis_acceptance_eighths"], request_id="x")
        for h in hypotheses["hypotheses"]
        for tile in (h["tile"],)
    }
    assert survey_native.compare_census_findings(complete, hypotheses) == []


# --- the exchange helper and survey frame replay parsing ---------------------


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


def test_survey_exchange_persists_request_and_response_pair(tmp_path):
    request = survey_request("accept-01", 50607)
    reply = _admin_frame(survey_reply_bytes(request, accept=8) + b"\0")
    readback = asyncio.run(survey_native.survey_exchange(_FakeSession(reply), request, tmp_path))
    assert (readback.status, readback.accept, readback.tile) == ("READY", 8, 50607)
    assert (tmp_path / "accept-01-request.json").read_bytes() == request.to_bytes()
    assert (tmp_path / "accept-01-response.json").read_bytes() == (
        survey_reply_bytes(request, accept=8)
    )
    # The retained pair re-parses through the wire contract.
    from app.simulation.openttd.corridor_accept_survey import SurveyReadback

    parsed = SurveyReadback.parse_for(request, (tmp_path / "accept-01-response.json").read_bytes())
    assert parsed.digest == readback.digest


def test_survey_exchange_refuses_malformed_truncated_and_stale_replies(tmp_path):
    from app.simulation.openttd.corridor_accept_survey import SurveyReadback

    request = survey_request("accept-02", 50863)

    class Broken:
        async def send(self, frame):
            pass

        async def receive(self):
            return b""

    with pytest.raises(ConnectionError):
        asyncio.run(survey_native.survey_exchange(Broken(), request, tmp_path))
    stale = _admin_frame(survey_reply_bytes(request, accept=8) + b"\0")
    stale_request = survey_request("accept-03", 51119)
    with pytest.raises(ValueError):
        asyncio.run(survey_native.survey_exchange(_FakeSession(stale), stale_request, tmp_path))
    # A truncated body can never parse as a measured observation.
    with pytest.raises(Exception):
        SurveyReadback.parse_for(request, survey_reply_bytes(request)[:-6])


def test_survey_response_bounds_are_exactly_512(tmp_path):
    request = survey_request("radius-00", None)
    assert len(request.to_bytes()) < survey_native.MAX_SURVEY_REQUEST_BYTES
    reply = _admin_frame(survey_reply_bytes(request) + b"\0")
    readback = asyncio.run(survey_native.survey_exchange(_FakeSession(reply), request, tmp_path))
    assert readback.radius == 8
    over = json.dumps(
        {
            "protocol": 6,
            "op": "radius",
            "request_id": "radius-00",
            "plan": SURVEY_SEAL,
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
        survey_native.decode_survey_request(over)


def test_survey_frame_replay_parser(tmp_path):
    request = survey_request("radius-00", None)
    reply = _admin_frame(survey_reply_bytes(request) + b"\0")
    frames = [
        ["outbound", survey_native.encode_survey_request(request.to_bytes()).hex()],
        ["inbound", reply.hex()],
    ]
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    outbound, requests, replies, request_positions, reply_positions = (
        survey_native._parse_survey_frames(tmp_path)
    )
    assert requests == [request]
    assert replies == [survey_reply_bytes(request)]
    assert request_positions[request.to_bytes()] == 0
    assert set(reply_positions) == {survey_reply_bytes(request)}
    with pytest.raises(ValueError, match="invalid SurveyRequest"):
        from app.simulation.openttd.gamescript_transport import encode_gamescript

        junk = [["outbound", encode_gamescript(b'{"op":"site"}').hex()]]
        (tmp_path / "frames.json").write_text(json.dumps(junk))
        survey_native._parse_survey_frames(tmp_path)


# --- replay verification fail-closed behavior --------------------------------


def test_unconsumed_survey_candidate_verifies_fail_closed(staged):
    verdict = survey_native.verify_survey_attempt(staged.directory)
    assert verdict == {
        "verification": "AUTHORIZATION_UNVERIFIED",
        "authorization_state": "CLAIM_ABSENT",
        "statement": (
            "the survey candidate was never consumed by an operator "
            "authorization; no verified completion is possible"
        ),
    }
    assert claim_status(staged.directory) == "ABSENT"


@pytest.fixture()
def claimed(tmp_path, staged):
    """A retained-evidence directory with a self-consistent one-shot claim and
    a forced NATIVE_SURVEY_COMPLETE result label — but no operator
    authorization record. The candidate carries the real staged seal; the
    synthetic evidence (result, cleanup, runtime identity, frames, manifest)
    is written here and never by an execution."""
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
                status="NATIVE_SURVEY_COMPLETE",
                exchanges=[
                    "radius-00",
                    "accept-00",
                    "accept-01",
                    "accept-02",
                    "accept-03",
                    "accept-04",
                    "accept-05",
                    "prod-00",
                ],
                requests=8,
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
    verdict = survey_native.verify_survey_attempt(claimed)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"
    assert verdict["authorization_state"] not in (None, "CLAIM_ABSENT")


def test_replay_refuses_a_claim_mismatched_to_its_seal(staged):
    target = staged.directory
    (target / "CLAIM.json").write_text(json.dumps(dict(prelaunch_digest="0" * 64)))
    try:
        with pytest.raises(ValueError, match="claim does not match"):
            survey_native.verify_survey_attempt(target)
    finally:
        (target / "CLAIM.json").unlink()


def test_replay_refuses_an_unreferenced_stray_file(claimed):
    target = claimed
    (target / "stray.txt").write_text("not in the manifest")
    with pytest.raises(ValueError, match="exhaustive"):
        survey_native.verify_survey_attempt(target)
    (target / "stray.txt").unlink()
    verdict = survey_native.verify_survey_attempt(target)
    assert verdict["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_replay_refuses_an_unknown_prelaunch_schema(tmp_path, staged):
    target = tmp_path / "alien"
    target.mkdir()
    metadata = metadata_of(staged)
    metadata["schema"] = d5.D5_FREIGHT_PRELAUNCH_SCHEMA  # the freight lineage, not the survey
    (target / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    (target / "PRELAUNCH.sha256").write_text(sha256(target / "PRELAUNCH.json") + "\n")
    (target / "CLAIM.json").write_text(
        json.dumps(dict(prelaunch_digest=sha256(target / "PRELAUNCH.json"), consumed=True))
    )
    from app.simulation.openttd.proof.harness import manifest

    (target / "artifact-manifest.sha256").write_text(manifest(target))
    verdict = survey_native.verify_survey_attempt(target)
    assert verdict["authorization_state"] == "UNKNOWN_PRELAUNCH_SCHEMA"


# --- exit-status discipline ---------------------------------------------------


def test_survey_exit_status_zero_only_for_the_verified_completion():
    assert (
        survey_native.survey_exit_status(
            dict(
                verified=True,
                status="NATIVE_SURVEY_COMPLETE",
                cleanup_complete=True,
                state_changed=False,
            )
        )
        == 0
    )
    for bad in (
        dict(
            verified=True,
            status="NATIVE_SURVEY_COMPLETE",
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
            status="NATIVE_SURVEY_COMPLETE",
            cleanup_complete=True,
            state_changed=True,
        ),
        dict(verified=False, status="FAILED", cleanup_complete=True, state_changed=False),
    ):
        assert survey_native.survey_exit_status(bad) == 1
    assert (
        survey_native.survey_verdict_exit_status(dict(verification="SURVEY_COMPLETION_VERIFIED"))
        == 0
    )
    assert (
        survey_native.survey_verdict_exit_status(
            dict(verification="PHASE_HALTED_EVIDENCE_PRESERVED")
        )
        == 1
    )
    # The freight pipeline's own exit discipline is unchanged.
    assert (
        d5.exit_status(dict(verified=True, status="NATIVE_FREIGHT_VERIFIED", cleanup_complete=True))
        == 0
    )


# --- Consumed-frame replay: synthetic packed survey attempt fixture ----------
#
# Explicitly synthetic: it stages a real candidate (prerequisite = the pinned
# D4 candidate-5) and fabricates only the missing post-launch artifacts —
# eight correlated protocol-6 frames, the runtime welcome, cleanup
# certification and the flat retained receipt exactly as the execution
# writes it. No native process, AdminPort session, claim, signature or
# authorization is created. Because no authorized survey run exists under
# the tests, the operator-authorization gate is the one seam monkeypatched;
# every prerequisite, identity, digest, phase, frame and cleanup fact is
# otherwise verified by the production replay path.

SURVEY_EXCHANGES_EFFECTS = {
    "radius-00": dict(status="READY", radius=3),
    "accept-00": dict(status="READY", radius=3, accept=0),
    "accept-01": dict(status="READY", radius=3, accept=8),
    "accept-02": dict(status="READY", radius=3, accept=8),
    "accept-03": dict(status="READY", radius=3, accept=8),
    "accept-04": dict(status="READY", radius=3, accept=8),
    "accept-05": dict(status="READY", radius=3, accept=8),
    "prod-00": dict(status="READY", prod=104),
}


def _consumed_survey_exchanges(seal: str, schedule):
    plan = survey_native.survey_plan()
    exchanges = []
    for entry in schedule:
        request = survey_native._survey_exchange_request(entry, seal, plan)
        effects = SURVEY_EXCHANGES_EFFECTS[entry["exchange"]]
        response = survey_reply_bytes(request, **effects)
        readback = survey_native.SurveyReadback.parse_for(request, response)
        exchanges.append((request, readback))
    return exchanges, plan


@pytest.fixture(scope="module")
def consumed_survey_attempt(tmp_path_factory):
    prepared = survey_native.prepare_survey_candidate(
        tmp_path_factory.mktemp("survey-consumed") / "candidate"
    )
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    exchanges, plan = _consumed_survey_exchanges(seal, metadata["plan_policy"]["schedule"])
    frames = []
    for request, readback in exchanges:
        response = json.dumps(
            readback.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (directory / (request.request_id + "-request.json")).write_bytes(request.to_bytes())
        (directory / (request.request_id + "-response.json")).write_bytes(response)
        frames.append(["outbound", survey_native.encode_survey_request(request.to_bytes()).hex()])
        frames.append(["inbound", _admin_frame(response + b"\0").hex()])
    (directory / "frames.json").write_text(json.dumps(frames))
    phase = survey_native.survey_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
    (directory / "session-before.sav").write_bytes(b"synthetic session-before fixture")
    (directory / "receipt.json").write_text(
        json.dumps(
            dict(
                phase,
                before_save_sha256="9" * 64,
                census_findings=survey_native.compare_census_findings(
                    phase["observations"], metadata["plan_policy"]["hypotheses"]
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
                requests=8,
                exchanges=[request.request_id for request, _ in exchanges],
                last_status="READY",
                command_accepted=True,
                state_changed=False,
                verified=True,
                status="NATIVE_SURVEY_COMPLETE",
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


def test_replay_verifies_a_fully_consumed_survey_frame_sequence(
    consumed_survey_attempt, monkeypatch
):
    directory, exchanges, _, _ = consumed_survey_attempt
    monkeypatch.setattr(survey_native, "replay_authorization_state", lambda *a, **k: None)
    verdict = survey_native.verify_survey_attempt(directory)
    assert verdict["verification"] == "SURVEY_COMPLETION_VERIFIED"
    assert verdict["receipt"]["phase"]["verification"] == "SURVEY_COMPLETE"
    assert verdict["receipt"]["phase"]["radius"] == 3
    assert verdict["receipt"]["phase"]["production"] == 104
    assert verdict["receipt"]["phase"]["observations"]["50351"]["value"] == 0
    assert all(
        verdict["receipt"]["phase"]["observations"][str(tile)]["value"] == 8
        for tile in (50607, 50863, 51119, 51375, 50605)
    )
    assert len(verdict["receipt"]["phase"]["observations"]) == 6
    assert survey_native.survey_verdict_exit_status(verdict) == 0


def test_replay_fails_closed_on_a_tampered_retained_receipt(consumed_survey_attempt, monkeypatch):
    directory, _, _, _ = consumed_survey_attempt
    monkeypatch.setattr(survey_native, "replay_authorization_state", lambda *a, **k: None)
    before = json.loads((directory / "receipt.json").read_text())
    (directory / "receipt.json").write_text(
        json.dumps(dict(before, production=105), sort_keys=True, indent=2) + "\n"
    )
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))
    with pytest.raises(ValueError, match="receipt replay mismatch"):
        survey_native.verify_survey_attempt(directory)
    (directory / "receipt.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")


def test_replay_fails_closed_on_tampered_retained_census_findings(
    consumed_survey_attempt, monkeypatch
):
    directory, _, _, _ = consumed_survey_attempt
    monkeypatch.setattr(survey_native, "replay_authorization_state", lambda *a, **k: None)
    before = json.loads((directory / "receipt.json").read_text())
    before["census_findings"] = [{"invented": "finding"}]
    (directory / "receipt.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))
    with pytest.raises(ValueError, match="census findings replay mismatch"):
        survey_native.verify_survey_attempt(directory)
