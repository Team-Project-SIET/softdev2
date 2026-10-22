"""Controlled offline tests for the D3 native integration contract (Seed 17).

No OpenTTD launch, no AdminPort connection, no native mutation, and no native
success claim on any retained artifact: staging, chain bindings, pins,
budgets, authorization payload reuse, claim gates, freeze drift and the full
controlled-seam rehearsals (the two clearing candidates through the shared D2
ceremony; the terraforming phase through its protocol-3 ceremony) are
exercised against explicitly controlled evidence directories only.
"""

import asyncio
import hashlib
import json
import struct

import pytest
from test_p08_terraform import PINNED_PROPOSAL_DIGEST, PINNED_SPEC_DIGEST
from test_terrain_clearing_adversarial import (
    ControlledClearingBackend,
    ControlledClearingPeer,
    _ConsoleSink,
    issue_test_authorization,
    synthetic_operator_anchor,
)

import app.simulation.openttd.proof.terrain_terraform_native as d3
from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.admin_protocol import (
    AdminClientPacketType,
    encode_admin_frame,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    decode_gamescript,
)
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.proof.harness import PROJECT, sha256
from app.simulation.openttd.proof.operator_authorization import (
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_classification_preparation import SEED17_RUN
from app.simulation.openttd.proof.terrain_clearing import (
    ClearingNativeBackend,
    ClearingReadback,
    claim_status,
)
from app.simulation.openttd.terrain_terraform import (
    TerraformReadback,
    TerraformRequest,
    expected_corner_heights,
)

TREE, CLEAR = 0x0009, 0x0001

# The production anchor, captured before any session patching: the runner
# never swaps the seeded operator key, and the identity check below refuses
# an unseeded or malformed anchor for every test.
_PROD_ANCHOR = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
assert _PROD_ANCHOR is not None
operator_authorization.operator_key_identity(_PROD_ANCHOR)
# The synthetic RFC 8032 Ed25519 operator identity (RFC 8032 §7.1 TEST 1,
# identical to the D2 suites): these keys exist only inside isolated test
# environments and are never written to any real candidate.
_TEST_OPERATOR_PUBLIC = (
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)


@pytest.fixture(autouse=True)
def _synthetic_operator_anchor_fixture():
    """The whole module verifies under one synthetic RFC 8032 test anchor."""
    saved = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    operator_authorization.OPERATOR_PUBLIC_KEY_HEX = _TEST_OPERATOR_PUBLIC
    try:
        yield
    finally:
        operator_authorization.OPERATOR_PUBLIC_KEY_HEX = saved


@pytest.fixture()
def staged(tmp_path):
    prepared = d3.prepare_candidate(tmp_path / "candidate")
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(prepared) -> dict:
    return json.loads((prepared.directory / "PRELAUNCH.json").read_text())


def _restamp_prelaunch(directory):
    (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")


def _add_freeze_probe(directory, source):
    """Alias one extra frozen entry to a byte-identical in-candidate copy.

    Drift tests must stay read-only against real sources: the probe copy is
    byte-identical to the reviewed module at staging time, so any later byte
    change is exactly the "frozen source changed after preparation" condition
    the freeze contract guards.
    """
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    probe = directory / "freeze-probe" / source.name
    probe.parent.mkdir(exist_ok=True)
    probe.write_bytes(source.read_bytes())
    metadata["frozen"][str(probe.resolve())] = sha256(source)
    (directory / "PRELAUNCH.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    )
    _restamp_prelaunch(directory)
    return probe


# --- staging correctness and identity resolution ---------------------------


def test_staged_composition_is_evidence_bound(staged):
    gs = staged.spec.workspace.root / "game" / "RoadFreightProof"
    package = PROJECT / "app/simulation/openttd/terrain_clearing_package/main.nut"
    assert gs.joinpath("main.nut").read_bytes() == package.read_bytes()
    main_text = gs.joinpath("main.nut").read_text()
    assert "class NetworkFreightProof extends TerrainClearingProof" in main_text
    candidate = PROJECT / "artifacts/demos/classification-exec-seed17-3a8f9e46/CANDIDATE.json"
    ai = staged.spec.workspace.root / "ai" / "RoadProofCompany"
    for name, record in json.loads(candidate.read_text())["ai_package"]["files"].items():
        assert sha256(ai / name) == record["sha256"]


def test_first_clearing_candidate_binds_its_chain_scope(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == "d3-clearing-terraform-native-prelaunch-v1"
    assert metadata["milestone"] == "D3-CLEARING"
    assert metadata["kind"] == "clear"
    assert metadata["attempt"] == "D3-CLEARING-1"
    assert metadata["plan_policy"]["target_tile"] == 45999
    assert metadata["plan_policy"]["pinned"]["page"] == 25
    assert "prerequisite" not in metadata and "prerequisite_chain" not in metadata
    assert metadata["budgets"]["requests"] == 8
    assert metadata["budgets"]["real_clears"] == 1
    assert "no authorization file exists" in metadata["authorization"]
    assert claim_status(staged.directory) == "ABSENT"


def test_both_clearing_pins_match_their_sealed_census_pages():
    pins = d3.clearing_pins()
    first, second = pins["45999"], pins["49326"]
    assert (first["tile"], first["classification"], first["flags"], first["owner"]) == (
        45999,
        "TREES",
        9,
        -1,
    )
    assert (first["elevation"], first["slope"], first["page"]) == (2, 0, 25)
    assert first["verification"].endswith("classification-p025 byte evidence")
    assert (second["elevation"], second["slope"], second["page"]) == (1, 0, 63)
    assert second["verification"].endswith("classification-p063 byte evidence")


def test_staged_source_save_is_byte_identical_to_the_retained_save(staged):
    root = staged.spec.workspace.root
    assert sha256(root / "source.sav") == sha256(SEED17_RUN / "before.sav")
    config = root.joinpath("openttd.cfg").read_text()
    assert "[game_creation]" not in config
    assert "[game_scripts]\nRoadFreightProof = \n" in config


def test_terraform_schedule_matches_the_compiled_specification():
    schedule = d3.terraform_schedule()
    assert len(schedule) == 16
    assert [entry["index"] for entry in schedule] == list(range(2, 18))
    assert all(
        entry["corner"] == "S"
        and entry["mask"] == 0x2
        and entry["direction"] == "up"
        and entry["command"] == "GSTile.RaiseTile"
        for entry in schedule
    )
    hosts = [entry["tile"] for entry in schedule]
    assert hosts[0] == 48558 and hosts[-1] == 50351
    for entry in schedule:
        expectation = d3.expectation_from_payload(entry)
        assert entry["tile"] in expectation.sharing_tiles
        assert tuple(sorted(expectation.sharing_tiles)) == expectation.sharing_tiles
        assert expectation.direction == "up" and expectation.corner_mask == 0x2
        assert len({state.tile for state in expectation.tiles}) == 4
        for state in expectation.tiles:
            assert state.before_slope != state.after_slope


def test_compiled_plan_binds_the_pinned_reviewed_digests():
    """The staged plan derives from the reviewed Seed 17 proposal, byte-pinned."""
    proposal, _doc, spec = d3.compiled_levelling()
    assert proposal.digest == PINNED_PROPOSAL_DIGEST
    assert spec.digest == PINNED_SPEC_DIGEST
    assert [op.tile_id for op in spec.ops if op.kind == "clear"] == [45999, 49326]


def test_budgets_match_the_reviewed_contract():
    clear = d3.budgets_for("clear")
    terraform = d3.budgets_for("terraform")
    assert clear["requests"] == 8 and clear["real_clears"] == 1 and clear["total_seconds"] == 180
    assert terraform["requests"] == 152
    assert terraform["requests"] == 16 * 9 + 8
    assert terraform["real_raises"] == 16 and terraform["real_clears"] == 0
    assert terraform["total_seconds"] == 900


def test_authorization_payload_reuses_the_shared_builder(staged):
    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    payload = authorization_payload(metadata, seal)
    assert payload["milestone"] == "D3-CLEARING"
    assert payload["attempt"] == "D3-CLEARING-1"
    assert payload["schema"] == "d3-clearing-terraform-native-prelaunch-v1"
    assert payload["target_tile"] == 45999
    assert payload["source_world"]["source_save"] == "before.sav"
    assert "operation_schedule" not in payload and "plan_digest" not in payload
    digest = hashlib.sha256(canonical_authorization_bytes(payload)).hexdigest()
    assert digest == d3.staged_authorization_payload_digest(staged.directory)


def test_launch_marker_schema_continues_the_d2_lineage():
    """The shared D2 launch boundary keeps its proven consumption marker."""
    assert ClearingNativeBackend.launch_marker_schema == "d2-clearing-native-launch-consumed"


def test_staged_artifact_tamper_refuses_d3_preflight(staged):
    config = staged.spec.workspace.config
    config.write_text(config.read_text() + "# tampered\n")
    with pytest.raises(ValueError):
        d3.d3_preflight(staged)


def test_drifted_source_save_refuses_d3_preflight(staged):
    (staged.spec.workspace.root / "source.sav").write_bytes(b"tampered world bytes")
    with pytest.raises(ValueError):
        d3.d3_preflight(staged)


def test_frozen_source_drift_refuses_d3_preflight(staged):
    """Post-preparation frozen drift of the D3 module itself refuses preflight."""
    probe = _add_freeze_probe(
        staged.directory,
        PROJECT / "app/simulation/openttd/proof/terrain_terraform_native.py",
    )
    probe.write_bytes(probe.read_bytes() + b"\n# modified after preparation\n")
    with pytest.raises(ValueError, match="Frozen source"):
        d3.d3_preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_removed_closure_entry_refuses_d3_preflight(staged):
    target = str((PROJECT / "app/planning/canonical.py").resolve())
    metadata = json.loads((staged.directory / "PRELAUNCH.json").read_text())
    assert target in metadata["frozen"]
    del metadata["frozen"][target]
    (staged.directory / "PRELAUNCH.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    )
    _restamp_prelaunch(staged.directory)
    with pytest.raises(ValueError, match="closure is not frozen"):
        d3.d3_preflight(staged)
    assert not (staged.directory / "CLAIM.json").exists()


def test_exit_status_zero_only_for_the_verified_receipt():
    assert d3.exit_status(dict(verified=True, status="NATIVE_STATE_VERIFIED")) == 0
    for status in (
        "FAILED",
        "STOPPED_NO_MUTATION",
        "FAILED_CLEANUP",
        "PHASE_HALTED_PREFIX_PRESERVED",
        "NATIVE_TERRAFORM_VERIFIED",
    ):
        assert d3.exit_status(dict(verified=False, status=status)) == 1


# --- Controlled peers and backends (D3-scoped, shared D2 handshake) ---------


class _ControlledD3ClearingPeer(ControlledClearingPeer):
    """The controlled clearing gateway re-scoped to one candidate's own pin."""

    def __init__(self, reader, *, key, welcome, pin, case="ok", on_exchange=None):
        super().__init__(reader, key=key, welcome=welcome, case=case, on_exchange=on_exchange)
        self.pin = pin

    def _readback(self, query, *, op, status, flags, elevation, funds, cost):
        return ClearingReadback(
            op=op,
            request_id=query.request_id,
            plan=query.plan,
            company=0,
            tile=self.pin["tile"],
            status=status,
            flags=flags,
            industry=None,
            owner=-1,
            elevation=elevation,
            slope=self.pin["slope"],
            eligible=True,
            funds=funds,
            cost=cost,
        ).model_dump_json().encode()

    def _response_payload(self, query):
        pin = self.pin
        if self.case == "crash-after-clear" and query.request_id == "read-2":
            return None
        if query.op == "inspect":
            return self._readback(
                query,
                op="inspect",
                status="READY",
                flags=pin["flags"],
                elevation=pin["elevation"],
                funds=100000,
                cost=20,
            )
        if query.op == "read":
            flags, funds = CLEAR, 99980
            if self.case == "receipt-fail" and query.request_id == "read-2":
                flags, funds = TREE, 100000
            return self._readback(
                query,
                op="read",
                status="READ",
                flags=flags,
                elevation=pin["elevation"],
                funds=funds,
                cost=0,
            )
        if self.case == "malformed-clear":
            return b'{"broken"'
        if self.case == "lost-clear":
            return None
        return self._readback(
            query,
            op="clear",
            status="CLEARED",
            flags=CLEAR,
            elevation=pin["elevation"],
            funds=99980,
            cost=20,
        )


class _ControlledD3ClearingBackend(ControlledClearingBackend):
    """The D2 controlled seam re-scoped to one D3 candidate's staged pin."""

    def __init__(self, *, welcome, pin, **kwargs):
        super().__init__(welcome=welcome, **kwargs)
        self.pin = pin

    async def connect(self, prepared, *, frame_observer):
        from app.simulation.openttd.proof.terrain_clearing import ClearingSecureSession

        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        reader = asyncio.StreamReader()
        self.peer = _ControlledD3ClearingPeer(
            reader,
            key=key,
            welcome=self.welcome,
            pin=self.pin,
            case=self.case,
            on_exchange=self._on_exchange,
        )
        session = ClearingSecureSession(reader, self.peer, key=key, frame_observer=frame_observer)
        self.session = session
        return session


class _ControlledTerraformPeer(ControlledClearingPeer):
    """Controlled protocol-3 gateway: answers the terraforming ceremony.

    Handshake and PING handling are the exact D2 controlled clearing
    implementation; only the gamescript exchange speaks the terraforming
    protocol (TerraformRequest/TerraformReadback) with the candidate's own
    staged schedule as the canned native world: per-operation before/after
    geometry, unowned clear classification, bounded native quote and funds.
    """

    def __init__(self, reader, *, key, welcome, schedule, case="ok", on_exchange=None):
        super().__init__(reader, key=key, welcome=welcome, case=case, on_exchange=on_exchange)
        self.schedule = schedule
        self.expectations = [d3.expectation_from_payload(entry) for entry in schedule]

    def write(self, frame):
        # Pre-authentication handshake frames keep the exact D2 controlled
        # implementation; authenticated frames are dispatched once here (the
        # shared authentication-era policy: PONG answers the subscription
        # barrier, keepalives are ignored, gamescript frames serve the
        # staged protocol-3 schedule) — never re-decrypting a frame.
        if self.authenticated:
            plain = self._in_cipher.decrypt(frame)
            kind = plain[2]
            if kind == AdminClientPacketType.PING:
                token = struct.unpack("<I", plain[3:7])[0]
                self.reader.feed_data(
                    self._out_cipher.encrypt(encode_admin_frame(126, struct.pack("<I", token)))
                )
            elif kind == ADMIN_GAMESCRIPT:
                self._serve_exchange(plain[3:])
            elif kind in (AdminClientPacketType.UPDATE_FREQUENCY, AdminClientPacketType.QUIT):
                pass
            else:
                raise AssertionError(f"unexpected authenticated frame kind {kind}")
            return
        super().write(frame)

    def _serve_exchange(self, raw):
        query = TerraformRequest.model_validate_json(decode_gamescript(raw))
        self.exchanges.append(query)
        self.on_exchange(query)
        response = self._response_payload(query)
        if response is None:
            self.reader.feed_eof()
            return
        self.reader.feed_data(
            self._out_cipher.encrypt(encode_admin_frame(SERVER_GAMESCRIPT, response + b"\0"))
        )

    def _position_of(self, query) -> int:
        head, *rest = query.request_id.split("-")
        if head in ("inspect", "terraform") and len(rest) == 1 and rest[0].isdigit():
            position = int(rest[0])
        elif head in ("read", "verify") and len(rest) == 2 and rest[1].isdigit():
            position = int(rest[0])
        else:
            position = None
        if position is not None and 0 <= position < len(self.schedule):
            return position
        raise ValueError(f"controlled exchange outside the staged schedule: {query.request_id}")

    def _geometry(self, state, *, after: bool) -> tuple[int, int, dict[str, int]]:
        min_height = state.after_min_height if after else state.before_min_height
        slope = state.after_slope if after else state.before_slope
        return min_height, slope, expected_corner_heights(min_height, slope)

    def _readback(self, query, state, *, status, after, funds, cost) -> TerraformReadback:
        min_height, slope, heights = self._geometry(state, after=after)
        return TerraformReadback(
            protocol=3,
            op=query.op,
            request_id=query.request_id,
            plan=query.plan,
            company=query.company,
            tile=query.tile,
            corner=query.corner,
            direction=query.direction,
            status=status,
            flags=CLEAR,
            industry=None,
            owner=-1,
            min_height=min_height,
            slope=slope,
            h_n=heights["N"],
            h_e=heights["E"],
            h_s=heights["S"],
            h_w=heights["W"],
            eligible=True,
            funds=funds,
            cost=cost,
        )

    def _response_payload(self, query) -> bytes | None:
        position = self._position_of(query)
        expectation = self.expectations[position]
        states = {state.tile: state for state in expectation.tiles}
        state = states[query.tile]
        if query.op == "inspect":
            return (
                self._readback(query, state, status="READY", after=False, funds=100000, cost=20)
                .model_dump_json()
                .encode()
            )
        if query.op == "terraform":
            return (
                self._readback(query, state, status="RAISED", after=True, funds=99980, cost=20)
                .model_dump_json()
                .encode()
            )
        after = query.request_id.startswith("verify-")
        drifted = self.case == "verification-drift" and position == 3 and (
            query.request_id == "verify-03-0"
        )
        if drifted:
            after = False
        return (
            self._readback(
                query,
                state,
                status="READ",
                after=after,
                funds=100000 if not after else 99980,
                cost=0,
            )
            .model_dump_json()
            .encode()
        )


class _ControlledTerraformBackend:
    """Controlled seam backend for the terraforming ceremony rehearsal."""

    kind = "CONTROLLED"

    def __init__(self, *, welcome, schedule, case="ok", save_fail=False):
        self.welcome = welcome
        self.schedule = schedule
        self.case = case
        self.save_fail = save_fail
        self.session = None
        self.process = None
        self.peer = None

    def preflight(self, prepared) -> None:
        pass

    async def launch(self, prepared, *, authorization=None) -> dict:
        from io import BytesIO
        from types import SimpleNamespace

        logs = prepared.spec.workspace.logs
        logs.mkdir(parents=True, exist_ok=True)
        self._stdout_log = logs / "stdout.log"
        self._stderr_log = logs / "stderr.log"
        self._stdout_log.write_text("dbg: [script:4] [18] [I] TERRAFORM_READY\n")
        self._stderr_log.write_text("dbg: [script:4] [20] [I] ROAD_PROOF_COMPANY_READY\n")
        self.process = SimpleNamespace(
            pid=-1,
            returncode=None,
            stdin=_ConsoleSink(self),
            stdout=BytesIO(),
            stderr=BytesIO(),
            poll=lambda: None,
            wait=lambda timeout=None: 0,
        )
        return {"pid": -1, "argv": ["/controlled/terraform"], "cwd": str(prepared.directory)}

    def health(self) -> None:
        pass

    async def connect(self, prepared, *, frame_observer):
        key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        reader = asyncio.StreamReader()
        self.peer = _ControlledTerraformPeer(
            reader, key=key, welcome=self.welcome, schedule=self.schedule, case=self.case
        )
        session = d3.TerraformSecureSession(
            reader, self.peer, key=key, frame_observer=frame_observer
        )
        self.session = session
        return session

    async def cleanup(self, prepared) -> dict:
        if self.session is not None:
            await self.session.close(quit=True)
        if self.process is not None:
            self.process.returncode = 0
        prepared.key_path.unlink(missing_ok=True)
        return dict(
            pid=-1,
            graceful_attempted=True,
            quit_command="quit",
            returncode=0,
            reaped=True,
            remaining_processes=[],
            events=[],
            cleanup_error=[],
        )


# --- Chain staging fixtures and rehearsals ----------------------------------


def _rehearsed_clearing(root, name, *, prerequisite=None, case="ok"):
    """Stage, authorize and rehearse one D3 clearing attempt (controlled)."""
    prepared = d3.prepare_candidate(root / name, kind="clear", prerequisite=prerequisite)
    issue_test_authorization(prepared)
    metadata = metadata_of(prepared)
    backend = _ControlledD3ClearingBackend(
        welcome=metadata["world"]["expected_welcome"],
        pin=metadata["plan_policy"]["pinned"],
        case=case,
    )
    with synthetic_operator_anchor():
        result = asyncio.run(d3.run_clearing_attempt(prepared, backend))
    return prepared, backend, result


def _staged_terraform_probe(root, name, prerequisite):
    """Stage (never authorize) one terraforming candidate from a verified chain."""
    with synthetic_operator_anchor():
        prepared = d3.prepare_candidate(root / name, kind="terraform", prerequisite=prerequisite)
        d3.d3_preflight(prepared)
    return prepared


@pytest.fixture(scope="module")
def cleared_chain(tmp_path_factory):
    """The rehearsed two-clear chain, offline under controlled evidence only."""
    root = tmp_path_factory.mktemp("d3-chain")
    with synthetic_operator_anchor():
        prepared1, _, result1 = _rehearsed_clearing(root, "clearing-1")
        assert result1["status"] == "NATIVE_STATE_VERIFIED", result1
        prepared2, _, result2 = _rehearsed_clearing(
            root, "clearing-2", prerequisite=prepared1.directory
        )
        assert result2["status"] == "NATIVE_STATE_VERIFIED", result2
    return root, prepared1, prepared2


@pytest.fixture(scope="module")
def terraform_probe(cleared_chain):
    """One staged, preflighted (never authorized) terraforming candidate."""
    root, _prepared1, prepared2 = cleared_chain
    return _staged_terraform_probe(root, "terraform-probe", prepared2.directory)


def test_chain_rehearsals_carry_verified_clearing_receipts(cleared_chain):
    """Both chain attempts replay to verified receipts on the D3 lineage."""
    root, prepared1, prepared2 = cleared_chain
    for prepared, attempt in ((prepared1, "D3-CLEARING-1"), (prepared2, "D3-CLEARING-2")):
        metadata = metadata_of(prepared)
        assert metadata["attempt"] == attempt
        assert claim_status(prepared.directory) == "CONSUMED"
        verdict = d3.verify_script_attempt(metadata, prepared.directory)
        assert verdict["verification"] == "RECEIPT_VERIFIED", verdict
        result = json.loads((prepared.directory / "result.json").read_text())
        assert result["status"] == "NATIVE_STATE_VERIFIED" and result["verified"] is True
        assert result["dispatch_state"] == "CONFIRMED" and result["clearing"] == "CLEARED"
        assert result["requests"] == 4 and result["state_changed"] is True
        receipt = json.loads((prepared.directory / "receipt.json").read_text())
        assert receipt["after_save_sha256"] == sha256(prepared.directory / "after.sav")


def test_terraform_probe_stages_the_reviewed_scope_from_the_chain(terraform_probe):
    prepared = terraform_probe
    metadata = metadata_of(prepared)
    assert metadata["milestone"] == "D3-TERRAFORMING"
    assert metadata["kind"] == "terraform" and metadata["attempt"] == "D3-TERRAFORMING-1"
    assert metadata["prerequisite"]["attempt"] == "D3-CLEARING-2"
    schedule = d3.terraform_schedule()
    plan = metadata["plan_policy"]
    assert plan["schedule"] == schedule and plan["target_tile"] == 48558
    assert plan["plan_digest"] == d3.plan_digest_of(schedule)
    assert plan["max_cost"] == d3.MAX_TERRAFORM_COST
    assert plan["command"] == "GSTile.RaiseTile"
    assert plan["prerequisite_world"]["cleared_tiles"] == [45999, 49326]
    chain = metadata["prerequisite_chain"]
    assert [link["attempt"] for link in chain] == ["D3-CLEARING-2", "D3-CLEARING-1"]
    assert [link["target_tile"] for link in chain] == [49326, 45999]
    assert metadata["world"]["mode"] == "PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD"
    assert metadata["world"]["source_save"] == "after.sav"


def test_terraform_authorization_payload_adds_the_ordered_schedule_scope(terraform_probe):
    """The shared scalar builder gains schedule + digest keys, additively."""
    prepared = terraform_probe
    metadata = metadata_of(prepared)
    seal = sha256(prepared.directory / "PRELAUNCH.json")
    payload = authorization_payload(metadata, seal)
    schedule = d3.terraform_schedule()
    assert payload["milestone"] == "D3-TERRAFORMING"
    assert payload["attempt"] == "D3-TERRAFORMING-1"
    assert payload["target_tile"] == 48558
    assert payload["operation_schedule"] == schedule
    assert payload["plan_digest"] == d3.plan_digest_of(schedule)
    digest = hashlib.sha256(canonical_authorization_bytes(payload)).hexdigest()
    assert digest == d3.staged_authorization_payload_digest(prepared.directory)


@pytest.fixture(scope="module")
def terraformed_world(cleared_chain, terraform_probe):
    """Stage, authorize and rehearse-once the full terraforming phase."""
    prepared = terraform_probe
    issue_test_authorization(prepared)
    metadata = metadata_of(prepared)
    backend = _ControlledTerraformBackend(
        welcome=metadata["world"]["expected_welcome"],
        schedule=metadata["plan_policy"]["schedule"],
    )
    with synthetic_operator_anchor():
        result = asyncio.run(d3.execute_terraform_attempt(prepared, backend))
    return prepared, backend, result


def test_terraform_rehearsal_completes_the_compiled_phase(terraformed_world):
    """The full authorized 16-operation phase verifies under the controlled seam."""
    prepared, backend, result = terraformed_world
    assert result["status"] == "NATIVE_TERRAFORM_VERIFIED", result
    assert result["verified"] is True and result["command_accepted"] is True
    assert result["dispatch_state"] == "CONFIRMED" and result["last_status"] == "RAISED"
    assert result["requests"] == d3.PLANNED_TERRAFORM_REQUESTS == 144
    assert result["native_launches"] == 1 and result["connections"] == 1
    dispatched = [entry.tile for entry in backend.peer.exchanges if entry.op == "terraform"]
    assert dispatched == [entry["tile"] for entry in d3.terraform_schedule()]
    assert len(result["raised_ops"]) == 16 and result["halt"] is None
    receipt = json.loads((prepared.directory / "receipt.json").read_text())
    assert receipt["after_save_sha256"] == sha256(prepared.directory / "after.sav")
    verdict = d3.verify_terraform_attempt(prepared.directory)
    assert verdict["verification"] == "RECEIPT_VERIFIED", verdict
    assert json.loads(json.dumps(verdict["receipt"])) == receipt
    assert claim_status(prepared.directory) == "CONSUMED"
    assert result["returncode"] == 0
    cleanup = json.loads((prepared.directory / "cleanup.json").read_text())
    assert cleanup["workspace_disposed"] is True and cleanup["credential_removed"] is True


def test_drifted_verification_halts_preserving_the_verified_prefix(cleared_chain, tmp_path):
    """One drifted independent read halts the phase; the verified prefix stands."""
    _root, _prepared1, prepared2 = cleared_chain
    with synthetic_operator_anchor():
        prepared = d3.prepare_candidate(
            tmp_path / "drifted-terraform", kind="terraform", prerequisite=prepared2.directory
        )
    issue_test_authorization(prepared)
    metadata = metadata_of(prepared)
    backend = _ControlledTerraformBackend(
        welcome=metadata["world"]["expected_welcome"],
        schedule=metadata["plan_policy"]["schedule"],
        case="verification-drift",
    )
    with synthetic_operator_anchor():
        result = asyncio.run(d3.execute_terraform_attempt(prepared, backend))
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED", result
    assert result["verified"] is False and result["halt"]["label"] == "op-05"
    assert result["raised_ops"] == ["op-02", "op-03", "op-04"]
    # The drifted read is op-05's last independent verification read: its nine
    # bounded exchanges all completed before the verification verdict, so 27
    # verified requests + 9 discharged requests is the retained budget use.
    assert result["requests"] == 3 * 9 + 9 == 36
    assert result["dispatch_state"] == "CONFIRMED"
    assert result["after_diagnostic_save_sha256"]
    verdict = d3.verify_terraform_attempt(prepared.directory)
    assert verdict["verification"] == "PHASE_HALTED_EVIDENCE_PRESERVED", verdict
    assert verdict["result_status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert verdict["completed"] == [48558, 48559, 48814]
    assert verdict["failed"]["label"] == "op-05"
    # 16 staged operations = 3 verified + 1 failed + 12 never executed.
    assert len(verdict["pending"]) == 12
    assert d3.exit_status(result) == 1


def test_clearing_without_authorization_never_consumes_a_claim(tmp_path):
    """No operator record means refusal before any launch-capable step."""
    with synthetic_operator_anchor():
        prepared = d3.prepare_candidate(tmp_path / "no-auth")
        metadata = metadata_of(prepared)
        backend = _ControlledD3ClearingBackend(
            welcome=metadata["world"]["expected_welcome"],
            pin=metadata["plan_policy"]["pinned"],
        )
        with pytest.raises(ValueError, match="authorization"):
            asyncio.run(d3.run_clearing_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists(), "claim must not be consumed"
    assert backend.session is None and backend.process is None, "no launch-capable work"
    assert claim_status(prepared.directory) == "ABSENT"
    prepared.spec.workspace.close()


def test_terraform_without_authorization_never_consumes_a_claim(cleared_chain, tmp_path):
    """The terraforming phase refuses before consuming the one-shot claim too."""
    _root, _prepared1, prepared2 = cleared_chain
    with synthetic_operator_anchor():
        prepared = d3.prepare_candidate(
            tmp_path / "tf-no-auth", kind="terraform", prerequisite=prepared2.directory
        )
        metadata = metadata_of(prepared)
        backend = _ControlledTerraformBackend(
            welcome=metadata["world"]["expected_welcome"],
            schedule=metadata["plan_policy"]["schedule"],
        )
        with pytest.raises(ValueError, match="authorization"):
            asyncio.run(d3.execute_terraform_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None
    prepared.spec.workspace.close()


def test_forged_authorization_scope_refuses_the_launch(tmp_path):
    """A payload distorting the staged scope is not a verifiable authorization."""
    with synthetic_operator_anchor():
        prepared = d3.prepare_candidate(tmp_path / "forged")
        metadata = metadata_of(prepared)

        def mutate(payload):
            payload["target_tile"] = 12345
            return payload

        issue_test_authorization(prepared, mutate=mutate)
        backend = _ControlledD3ClearingBackend(
            welcome=metadata["world"]["expected_welcome"],
            pin=metadata["plan_policy"]["pinned"],
        )
        with pytest.raises(ValueError, match="authorization"):
            asyncio.run(d3.run_clearing_attempt(prepared, backend))
    assert not (prepared.directory / "CLAIM.json").exists()
    assert backend.session is None and backend.process is None
    prepared.spec.workspace.close()


def test_one_shot_claim_prevents_a_second_ceremony(tmp_path):
    """A consumed claim refuses both a second ceremony and a fresh preflight."""
    prepared, _backend, result = _rehearsed_clearing(tmp_path, "one-shot")
    assert result["status"] == "NATIVE_STATE_VERIFIED"
    metadata = metadata_of(prepared)
    second = _ControlledD3ClearingBackend(
        welcome=metadata["world"]["expected_welcome"],
        pin=metadata["plan_policy"]["pinned"],
    )
    with pytest.raises(ValueError, match="one native attempt already consumed"):
        asyncio.run(d3.run_clearing_attempt(prepared, second))
    with pytest.raises(ValueError, match="one native attempt already consumed"):
        d3.d3_preflight(prepared)
    assert claim_status(prepared.directory) == "CONSUMED"
