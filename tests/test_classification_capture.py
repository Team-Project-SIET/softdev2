"""Offline rehearsal of the bounded capture runner against a controlled peer.

No OpenTTD launch, no AdminPort connection, no authorization consumption
occurs: the controlled backend answers the deterministic census through the
same seam(:meth:`execute_capture`) the native runner binds. Evidence flow,
budget enforcement, cleanup and fail-closed failure handling are verified on
temp directories only.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from test_p08_controlled_road import world_for
from test_tile_classification_receipt import (
    CENSUS_REQUEST_ID,
    census_dict,
    exchanges_for,
    retained_welcome,
)

from app.simulation.openttd.proof import classification_capture as capture
from app.simulation.openttd.proof.classification_capture import (
    CaptureWorldIdentityError,
    NativeCaptureBackend,
    _failure_code,
    execute_capture,
    script_log_health_findings,
)
from app.simulation.openttd.proof.world_correspondence import SOURCE_SAVE_MODE
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts


@pytest.fixture(scope="module")
def census():
    """The controlled 64x64 world projected into the retained census shape."""
    raw = census_dict(world_for(accepts=(1,)))
    facts = SupplementalPlanningFacts.model_validate_json(json.dumps(raw))
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    requests, exchanges = exchanges_for(facts, facts.source.map_width, facts.source.map_height)
    return facts, digest, requests, exchanges


class ControlledCaptureBackend:
    """Controlled seam backend: plan-ordered exchanges plus injection pins."""

    kind = "CONTROLLED"

    def __init__(self, exchanges, welcome, *, failure_at=None, failure=None):
        self._exchanges = list(exchanges)
        self._welcome = dict(welcome)
        self.failure_at = failure_at
        self.failure = failure
        self.calls = 0
        self.process = None
        self.session = None
        self.proof = None
        self.cleaned = 0

    async def launch(self, prepared):
        self.proof = prepared.proof_stub()
        return {"pid": -1, "argv": ["/controlled/fake"], "cwd": str(prepared.directory)}

    def health(self):
        pass

    async def connect(self, prepared, expected_welcome):
        missing = [
            key for key in expected_welcome if self._welcome.get(key) != expected_welcome.get(key)
        ]
        if missing:
            raise CaptureWorldIdentityError(dict(self._welcome), missing)
        return {
            "welcome": dict(self._welcome),
            "protocol": {"version": 3},
            "auth": {"encrypted": True, "method": "controlled"},
        }

    async def exchange(self, request):
        index = self.calls
        self.calls += 1
        if self.failure_at is not None and index == self.failure_at:
            raise self.failure
        return self._exchanges[index]

    async def cleanup(self):
        self.cleaned += 1
        return {
            "pid": -1,
            "graceful_attempted": False,
            "quit_command": "quit",
            "returncode": 0,
            "reaped": True,
            "remaining_processes": [],
            "events": [],
            "cleanup_error": [],
        }


class FakePrepared:
    """Duck-typed execution candidate for the runner rehearsal."""

    def __init__(self, directory, facts, digest, *, requests=90, response_bytes=103 * 508):
        self.directory = directory
        self.attempt_identity = "controlled-rehearsal-identity"
        self._facts = facts
        self._digest = digest
        self._requests = requests
        self._response_bytes = response_bytes
        self._bands = facts_plan(facts)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "PRELAUNCH.json").write_text("{}\n")
        (directory / "PRELAUNCH.sha256").write_text(
            hashlib.sha256((directory / "PRELAUNCH.json").read_bytes()).hexdigest() + "\n"
        )

    def candidate(self):
        pages = [
            dict(index=i, request_payload_sha256=hashlib.sha256(p).hexdigest())
            for i, p in enumerate(self.payloads)
        ]
        return dict(
            kind="tile-classification-execution",
            correspondence_mode=SOURCE_SAVE_MODE,
            plan=dict(
                region=[
                    self._facts.region.x,
                    self._facts.region.y,
                    self._facts.region.width,
                    self._facts.region.height,
                ],
                bands=[
                    [b.region.x, b.region.y, b.region.width, b.region.height] for b in self._bands
                ],
                pages_count=len(pages),
                tiles=len(self._facts.tiles),
                pages=pages,
            ),
            budgets=dict(
                requests=self._requests,
                session_requests=self._requests,
                observation_seconds=600,
                total_response_bytes_limit=self._response_bytes,
            ),
            world_identity_requirements=dict(
                retained_welcome=dict(self.welcome()),
                retained_facts_sha256=self._digest,
            ),
        )

    def metadata(self):
        # Mirrors the real PRELAUNCH seal: plan facts only, no per-page digests.
        return dict(
            plan=dict(
                region=[
                    self._facts.region.x,
                    self._facts.region.y,
                    self._facts.region.width,
                    self._facts.region.height,
                ],
                pages_count=len(self.payloads),
                tiles=len(self._facts.tiles),
            ),
            argv=("/controlled/fake",),
            correspondence_mode=SOURCE_SAVE_MODE,
        )

    def preflight(self):
        return self.metadata()

    def welcome(self):
        return retained_welcome(self._facts.source.map_width, self._facts.source.map_height)

    @property
    def payloads(self):
        return tuple(request.to_bytes() for request in self._requests_plan)

    @property
    def _requests_plan(self):
        from app.simulation.openttd.tile_classification import classification_plan

        return classification_plan(self._facts.region, CENSUS_REQUEST_ID)

    def proof_stub(self):
        root = self.directory / "isolated" / "disposed"
        return SimpleNamespace(
            directory=self.directory,
            endpoints=(-1, -1),
            key_path=self.directory / "credential",
            spec=SimpleNamespace(
                stdout_path=self.directory / "stdout.log",
                stderr_path=self.directory / "stderr.log",
                lifecycle=SimpleNamespace(events=[], close=lambda: None),
                workspace=SimpleNamespace(logs=self.directory, root=root, close=lambda: None),
            ),
        )


def stage(monkeypatch, facts, digest):
    payloads = tuple(request.to_bytes() for request in facts_plan(facts))
    monkeypatch.setattr(capture, "request_plan", lambda: payloads)
    monkeypatch.setattr(capture, "retained_facts", lambda: facts)
    monkeypatch.setattr(capture, "retained_save_binding", lambda: {"controlled": "peer"})
    monkeypatch.setattr(
        capture, "verify_cleanup_endpoints", lambda proof, cleanup: {"controlled": True}
    )

    async def fast_wait_log(backend, proof, marker):
        return None

    monkeypatch.setattr(capture, "wait_log", fast_wait_log)
    return payloads


def facts_plan(facts):
    from app.simulation.openttd.tile_classification import classification_plan

    return classification_plan(facts.region, CENSUS_REQUEST_ID)


def test_controlled_capture_binds_to_retained_projection(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)
    backend = ControlledCaptureBackend(exchanges, prepared.welcome())
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["status"] == "TILE_CLASSIFICATION_V2_CAPTURED"
    assert result["verdict"]["status"] == "CORRESPONDENCE_ESTABLISHED"
    assert result["pages"] == 90
    assert backend.calls == 90  # exactly one exchange per planned page
    receipts = json.loads((prepared.directory / "classification-receipts.json").read_bytes())
    assert len(receipts["receipts"]) == 90
    assert receipts["receipts"][17]["request_id"] == CENSUS_REQUEST_ID
    # Exact request/response bytes retained per page.
    for index in range(90):
        stem = f"classification-p{index:03d}"
        assert (prepared.directory / f"{stem}-request.json").read_bytes() == (
            exchanges[index].request_payload
        )
        assert (prepared.directory / f"{stem}-response.json").read_bytes() == (
            exchanges[index].response_payload
        )
    completeness = (prepared.directory / "classification-completeness.json").read_text()
    assert "90" in completeness
    assert not (prepared.directory / "capture-failure.json").exists()
    cleanup = json.loads((prepared.directory / "cleanup.json").read_bytes())
    assert cleanup["reaped"] and not cleanup["cleanup_error"]
    assert cleanup["workspace_disposed"] and cleanup["credential_removed"]
    verdict = json.loads((prepared.directory / "correspondence-verdict.json").read_bytes())
    assert verdict["status"] == "CORRESPONDENCE_ESTABLISHED"
    result_on_disk = json.loads((prepared.directory / "result.json").read_bytes())
    assert result_on_disk["status"] == result["status"]
    assert "result.json" in (prepared.directory / "artifact-manifest.sha256").read_text()


def test_mid_census_failure_keeps_evidence_and_never_retries(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)
    backend = ControlledCaptureBackend(
        exchanges,
        prepared.welcome(),
        failure_at=18,
        failure=TimeoutError("controlled stale page"),
    )
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["status"] == "PARTIAL_CLASSIFICATION_CAPTURE"
    assert result["pages"] == 18
    assert backend.calls == 19  # the failed exchange was never retried
    failure = json.loads((prepared.directory / "capture-failure.json").read_bytes())
    assert failure["code"] == "TIMEOUT"
    assert failure["pages_exchanged"] == 18
    for index in range(18):
        assert (prepared.directory / f"classification-p{index:03d}-request.json").is_file()
    assert not (prepared.directory / "classification-p018-request.json").is_file()
    assert not (prepared.directory / "correspondence-verdict.json").exists()
    cleanup = json.loads((prepared.directory / "cleanup.json").read_bytes())
    assert cleanup["reaped"]


def test_welcome_mismatch_fails_before_any_page(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)
    wrong = dict(prepared.welcome(), seed=21)
    backend = ControlledCaptureBackend(exchanges, wrong)
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["status"] == "FAILED"
    assert result["pages"] == 0
    failure = json.loads((prepared.directory / "capture-failure.json").read_bytes())
    assert failure["code"] == "WORLD_IDENTITY"
    assert failure["observed_welcome_diagnostic"]["seed"] == 21
    assert not (prepared.directory / "runtime-identity.json").exists()
    assert not (prepared.directory / "classification-p000-request.json").exists()


def test_page_budget_fails_closed(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest, requests=10)
    backend = ControlledCaptureBackend(exchanges, prepared.welcome())
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["status"] == "PARTIAL_CLASSIFICATION_CAPTURE"
    assert result["pages"] == 10
    failure = json.loads((prepared.directory / "capture-failure.json").read_bytes())
    assert failure["code"] == "PAGE_BUDGET_EXCEEDED"
    assert backend.calls == 10  # budget is enforced before the next request


def test_response_byte_budget_before_rollup(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest, response_bytes=103)
    backend = ControlledCaptureBackend(exchanges, prepared.welcome())
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["status"] == "FAILED"
    failure = json.loads((prepared.directory / "capture-failure.json").read_bytes())
    assert failure["code"] == "RESPONSE_BYTE_BUDGET_EXCEEDED"


def test_consumed_claim_refuses_second_run(tmp_path, monkeypatch, census):
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)
    (prepared.directory / "CLAIM.json").write_text("{}\n")
    backend = ControlledCaptureBackend(exchanges, prepared.welcome())
    with pytest.raises(ValueError) as refused:
        asyncio.run(execute_capture(prepared, backend))
    assert "claim" in str(refused.value)
    assert backend.calls == 0


def test_native_backend_requires_explicit_authorization():
    with pytest.raises(PermissionError):
        NativeCaptureBackend()


def test_launch_failure_after_proof_still_runs_owned_cleanup(tmp_path, monkeypatch, census):
    """A launch failure must not consume the claim with zero evidence: the
    actual owned spec backs the cleanup record even when the local reference
    never saw it (review finding regression)."""
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)

    class FailingLaunchBackend(ControlledCaptureBackend):
        async def launch(self, prepared):
            self.proof = prepared.proof_stub()
            proof_root = self.proof.spec.workspace.root
            proof_root.parent.mkdir(parents=True, exist_ok=True)
            proof_root.mkdir(exist_ok=True)  # the workspace exists when exit happens
            raise RuntimeError("controlled native exit")

    backend = FailingLaunchBackend(exchanges, prepared.welcome())
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["pages"] == 0
    assert result["launches"] == 0
    failure = json.loads((prepared.directory / "capture-failure.json").read_bytes())
    assert failure["code"] == "RUNTIMEERROR"
    cleanup = json.loads((prepared.directory / "cleanup.json").read_bytes())
    # The stub proof's endpoints were verified: the finally block used the
    # backend's actual spec, not the never-assigned local reference.
    assert cleanup.get("controlled") is True
    assert cleanup["workspace_disposed"] is False  # root existed; disposed honestly
    result_on_disk = json.loads((prepared.directory / "result.json").read_bytes())
    assert result_on_disk["status"] == "FAILED"
    assert "capture-failure.json" in (prepared.directory / "artifact-manifest.sha256").read_text()


def test_post_claim_gate_never_keyerrors_on_real_prelaunch_shape(tmp_path, monkeypatch, census):
    """The real PRELAUNCH seal has no per-page list: requested_pages must come
    from the candidate plan (review finding regression)."""
    facts, digest, requests, exchanges = census
    stage(monkeypatch, facts, digest)
    prepared = FakePrepared(tmp_path / "attempt", facts, digest)
    assert "pages" not in prepared.metadata()["plan"]  # true real-record shape
    backend = ControlledCaptureBackend(exchanges, prepared.welcome())
    result = asyncio.run(execute_capture(prepared, backend))
    assert result["requested_pages"] == 90


def test_failure_codes_bounded():
    assert _failure_code(TimeoutError()) == "TIMEOUT"
    world_error = CaptureWorldIdentityError({"seed": 1}, ["seed"])
    assert _failure_code(world_error) == "WORLD_IDENTITY"
    assert _failure_code(RuntimeError("odd")) == "RUNTIMEERROR"


# The verified OpenTTD 15.3 dummy-AI fallback lifecycle, replayed verbatim
# (abbreviated to the script-relevant lines, byte-exact) from the consumed
# attempt's immutable stderr log
# (artifacts/demos/classification-exec-seed17-e71c95a3/stderr.log lines 45-63;
# timestamps are preserved so the reader sees the same record the runner
# health-checks are applied to).
CONSUMED_ATTEMPT_SCRIPT_LOG = "\n".join(
    (
        "[2026-10-18 11:32:09] dbg: [script:0] The savegame has an AI by the name"
        " 'RoadProofCompany', version 1 which is no longer available.",
        "[2026-10-18 11:32:09] dbg: [script:0] Configuration switched to Random AI.",
        "[2026-10-18 11:32:09] dbg: [script:0] The savegame has an AI by the name"
        " 'RoadProofCompany', version 1 which is no longer available.",
        "[2026-10-18 11:32:09] dbg: [script:0] A random other AI will be loaded in its place.",
        "[2026-10-18 11:32:09] dbg: [grf:1] GRFInfo: Loaded GRFv8 set FFFFFFFE"
        " - OpenTTD's default and fallback extra graphics (palette: DOS, version: 0)",
        "[2026-10-18 11:32:10] dbg: [script:0] No suitable AI found, loading 'dummy' AI.",
        "[2026-10-18 11:32:10] dbg: [script:3] [18] [W] Loading failed: there was data"
        " for the script to load, but the script does not have a Load() function.",
        "[2026-10-18 11:32:10] dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15",
        "[2026-10-18 11:32:10] dbg: [script:1] [0] [E] No suitable AI found to load.",
        "[2026-10-18 11:32:10] dbg: [script:1] [0] [E] This AI is a dummy AI"
        " and won't do anything.",
        "[2026-10-18 11:32:10] dbg: [script:1] [0] [E] You can download several AIs"
        " via the 'Online Content' system",
        "[2026-10-18 11:32:10] dbg: [script:0] The script died unexpectedly.",
        "[2026-10-18 11:32:10] dbg: [script:3] [18] [W] Save function is not implemented",
        "[2026-10-18 11:32:10] dbg: [script:3] [18] [W] Save function is not implemented",
    )
)

# The working-run shape (playable-demo-25d891bc9f…): the GameScript logs as
# [18], the AI as [0]; "Save function is not implemented" warnings come from
# the AI only. This is a healthy capture, not a failure.
HEALTHY_NATIVE_SCRIPT_LOG = "\n".join(
    [
        "[2026-10-17 07:41:16] dbg: [script:3] [0] [W] Save function is not implemented",
        "[2026-10-17 07:45:36] dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15",
        "[2026-10-17 07:46:42] dbg: [script:3] [0] [W] Save function is not implemented",
        "[2026-10-17 07:46:42] dbg: [script:3] [0] [W] Save function is not implemented",
    ]
)


def native_log_backend(tmp_path, stdout: str, stderr: str) -> NativeCaptureBackend:
    """A locally constructed native backend whose proof spec points at the
    given captured logs (no launch, no authorization consumption)."""
    backend = NativeCaptureBackend(authorized_one_launch=True)
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)
    backend.proof = SimpleNamespace(
        spec=SimpleNamespace(stdout_path=stdout_path, stderr_path=stderr_path)
    )
    return backend


def test_consumed_attempt_script_log_attribution():
    """Replay of the consumed attempt's stderr script section: the engine's
    designed dummy-AI instant death is no longer misattributed to the
    GameScript, and the genuinely fatal OpenTTD 15.3 save-load fallback (the
    staged runtime could not resolve the save's stored AI identity) is
    recognized instead — the consumed run's exit then has an exact cause."""
    findings = script_log_health_findings(CONSUMED_ATTEMPT_SCRIPT_LOG)
    assert findings == ["marker:which is no longer available"]


def test_healthy_native_log_has_no_findings():
    """The working-run shape (GameScript at [18], AI at [0], AI-only save
    warnings) proves script survival and must stay healthy."""
    assert script_log_health_findings(HEALTHY_NATIVE_SCRIPT_LOG) == []


def test_check_logs_passes_on_healthy_native_log(tmp_path):
    backend = native_log_backend(tmp_path, HEALTHY_NATIVE_SCRIPT_LOG, "")
    backend._check_logs()  # does not raise


def test_check_logs_fails_closed_with_exact_cause(tmp_path):
    backend = native_log_backend(tmp_path, "", CONSUMED_ATTEMPT_SCRIPT_LOG)
    with pytest.raises(RuntimeError) as fatal:
        backend._check_logs()
    message = str(fatal.value)
    assert message.startswith("Native script/asset error: ")
    assert "which is no longer available" in message
    # The death line itself is attributed, not echoed as an unexplained death.
    assert "script_died" not in message


def test_genuine_gamescript_death_is_fatal():
    """A death line whose previous script line is not the dummy-AI fallback's
    final line stays fatal — e.g. the GameScript itself dying on a compile
    error is never excused."""
    text = "\n".join(
        [
            "dbg: [script:4] [18] [E] comp: syntax error in terrain_classification.nut",
            "dbg: [script:0] The script died unexpectedly.",
        ]
    )
    assert script_log_health_findings(text) == [
        "script_died:dbg: [script:0] The script died unexpectedly."
    ]


def test_save_identity_fallback_texts_fail_closed():
    """Every OpenTTD 15.3 save-load fallback wording (and the legacy reload
    wording) contradicts the staged world identity and must be fatal."""
    for marker in ("no longer found", "which is no longer available"):
        text = f"dbg: [script:0] {marker} and stopped"
        assert script_log_health_findings(text) == [f"marker:{marker}"]


def test_squirrel_error_line_fails_closed():
    """Any [S]-severity script line is a Squirrel error, fatal regardless of
    the script that raised it."""
    text = "dbg: [script:1] [0] [S] wrong parameter count in main.nut"
    assert script_log_health_findings(text) == ["squirrel_error_line"]


def test_dummy_death_exemption_is_single_and_strict():
    """The designed dummy-AI death is exempt at most once, only with the full
    three-line sequence in the captured text and the death line directly after
    its final line. Every weakened variant stays fatal."""
    sequence = [
        "dbg: [script:1] [0] [E] No suitable AI found to load.",
        "dbg: [script:1] [0] [E] This AI is a dummy AI and won't do anything.",
        "dbg: [script:1] [0] [E] You can download several AIs via the 'Online Content' system",
    ]
    death = "dbg: [script:0] The script died unexpectedly."
    # Exact designed shape: exempt.
    assert script_log_health_findings("\n".join(sequence + [death])) == []
    # Missing the first sequence line: fatal.
    assert script_log_health_findings("\n".join(sequence[1:] + [death])) == [f"script_died:{death}"]
    # Another script line between the sequence and the death: fatal. (The
    # adjacency rule compares consecutive script-log lines; non-script
    # network/graphics lines are filtered by design, as in the real log.)
    assert script_log_health_findings(
        "\n".join(sequence + ["dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15", death])
    ) == [f"script_died:{death}"]
    # A second death line after the exempted one is never exempted.
    findings = script_log_health_findings(
        "\n".join(sequence + [death, "dbg: [script:0] loop", death])
    )
    assert findings == [f"script_died:{death}"]


def test_dummy_death_exemption_is_capped_at_one_per_log():
    """Even two perfectly shaped dummy-AI deaths (each directly after its own
    full sequence) exempt only the first: the second death in one captured
    log is fatal — the cap exists because a second ScriptInstance death must
    never ride along on the first exemption."""
    sequence = [
        "dbg: [script:1] [0] [E] No suitable AI found to load.",
        "dbg: [script:1] [0] [E] This AI is a dummy AI and won't do anything.",
        "dbg: [script:1] [0] [E] You can download several AIs via the 'Online Content' system",
    ]
    death = "dbg: [script:0] The script died unexpectedly."
    findings = script_log_health_findings(
        "\n".join(sequence + [death] + ["dbg: [script:0] loop"] + sequence + [death])
    )
    assert findings == [f"script_died:{death}"]
