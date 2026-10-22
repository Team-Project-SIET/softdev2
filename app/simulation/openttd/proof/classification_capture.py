"""Bounded Tile Classification V2 capture runner (one authorized attempt).

Executes the sealed PENDING_AUTHORIZATION execution candidate from
:mod:`proof.classification_execution`: one launch, one secure AdminPort
connection, one correlation receipt per census page, zero retries, zero
reconnects and zero world mutations. Controlled peers may implement the same
backend seam for offline rehearsal; the native backend mirrors the proven
retained-runner launch/connect/cleanup choreography (:mod:`proof.native`, the
freight runner) without adding runtime surfaces.

Fail-closed rules (never silently expanded):
- every page exchange is bounded (per-page timeout, receipt correlation,
  duplicate-response barrier, 8-operation protocol cap) and its exact
  request/response bytes are retained on disk,
- budgets (pages, response bytes, session requests, observation deadline) are
  enforced before each request and again in the roll-up,
- partial captures persist their evidence and diagnostics with explicit
  failure codes, run the full owned cleanup, and never retry or reconnect,
- fusion with the retained corridor happens only through
  :meth:`TileClassificationSweep.record` plus
  :func:`evaluate_correspondence` — the fail-closed correspondence gates. A
  mismatch stays recorded, is never repaired, and leaves the historical
  unknown tiles UNKNOWN.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import IO

from ..admin_crypto import AuthorizedKey
from ..gamescript_transport import GameScriptTransport, TransportProtocolError
from ..secure_admin import AuthDisconnected, AuthState, SecureAdminSession
from ..tile_classification import (
    CLASSIFICATION_PAGE_LIMIT,
    TileClassificationExchange,
    TileClassificationRequest,
    TileClassificationSweep,
)
from ..tile_facts import TileQueryError
from .classification_execution import (
    GSADMIN_BYTES,
    load_execution,
)
from .endpoints import verify_cleanup_endpoints
from .harness import BINARY, BINARY_SHA256, manifest, sha256, write_json
from .native import matching_processes
from .road_mutation import save, wait_log
from .terrain_classification_preparation import (
    WELCOME_IDENTITY_KEYS,
    request_plan,
    retained_facts,
)
from .world_correspondence import (
    SOURCE_SAVE_MODE,
    evaluate_correspondence,
    retained_save_binding,
)

CAPTURE_RESULT_SCHEMA = "tile-classification-capture-result-v1"
GS_READINESS_MARKER = "BRIDGE_STARTED protocol=1 api=15"
SECURE_CONNECT_DEADLINE_SECONDS = 30.0
PAGE_TIMEOUT_SECONDS = 15.0
PAGE_OPERATION_BUDGET = 8

# The OpenTTD 15.3 built-in dummy AI "instant dies" by design when no AI is
# installed (verified against the 15.3 sources: Script_CreateDummy builds a
# DummyAIController whose Start() only logs the three STR_ERROR_AI_NO_AI_FOUND
# lines and returns, and ScriptInstance::GameLoop then reaches
# `!CallMethod("Start") || !IsSuspended()` and calls Died(), which logs the
# unattributed death line at [script:0]). The dummy's three lines are the last
# script-log lines before that death line, so a death line immediately
# preceded by the sequence's final line is the engine's designed fallback
# death — not a GameScript failure. Every other death line stays fatal.
GAME_SCRIPT_DIED_MARKER = "The script died unexpectedly"
DUMMY_AI_INSTANT_DEATH_SEQUENCE = (
    "No suitable AI found to load.",
    "This AI is a dummy AI and won't do anything.",
    "You can download several AIs via the 'Online Content' system",
)
LOG_SQ_ERROR_PATTERN = re.compile(r"dbg: \[script:\d+\] \[\d+\] \[S\](?: |$)", re.MULTILINE)
# Save-load fallback texts: "no longer found" is the legacy reload-scenario
# wording; "which is no longer available" is the actual OpenTTD 15.3
# save-load fallback (saveload/ai_sl.cpp, game_sl.cpp) printed whenever the
# staged runtime cannot resolve a save-stored AI or GameScript identity. It
# means the loaded world did not reproduce a stored script identity, so the
# source-save correspondence cannot proceed — recognized, never silently
# tolerated.
FATAL_LOG_MARKERS = (
    "Error compiling",
    "Fatal error",
    "Script is not started",
    "no longer found",
    "which is no longer available",
    "corrupted or missing",
    "but it is incomplete",
    "illegal packet",
    "not supported update frequency",
)


def script_log_health_findings(text: str) -> list[str]:
    """Recognized native fatal signals in the captured openttd logs.

    Fail-closed: every recognized marker is fatal, every script-death line is
    fatal unless it is the engine's designed dummy-AI instant death (the only
    accepted death — at most one per captured log, only with the full dummy
    sequence present and no Squirrel error evidence anywhere).
    """
    findings: list[str] = []
    if LOG_SQ_ERROR_PATTERN.search(text):
        findings.append("squirrel_error_line")
    for marker in FATAL_LOG_MARKERS:
        if marker.lower() in text.lower():
            findings.append(f"marker:{marker}")
    script_lines = [line for line in text.splitlines() if "dbg: [script" in line]
    exempted_deaths = 0
    for index, line in enumerate(script_lines):
        if GAME_SCRIPT_DIED_MARKER not in line:
            continue
        previous = script_lines[index - 1] if index else ""
        attributed = previous.endswith(DUMMY_AI_INSTANT_DEATH_SEQUENCE[-1]) and all(
            fragment in text for fragment in DUMMY_AI_INSTANT_DEATH_SEQUENCE
        )
        if attributed and exempted_deaths == 0:
            # The engine's designed dummy-AI instant death; at most one per
            # process (a second ScriptInstance only ever dies once). Excluded
            # from the fatal findings: it is survival evidence, not an error,
            # and it must not fail a healthy capture.
            exempted_deaths += 1
        else:
            findings.append(f"script_died:{line}")
    return findings


class CaptureBudgetError(RuntimeError):
    """An explicitly sealed budget line was reached; fail closed."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class CaptureWorldIdentityError(ValueError):
    """The observed native world contradicts the retained identity."""

    def __init__(self, observed: dict, missing: list[str]) -> None:
        detail = "Unexpected native world identity: " + (
            ",".join(sorted(missing)) if missing else "identity keys disagree"
        )
        super().__init__(detail)
        self.observed_welcome = dict(observed)


def _failure_code(error: BaseException) -> str:
    if isinstance(error, CaptureBudgetError):
        return error.code
    if isinstance(error, CaptureWorldIdentityError):
        return "WORLD_IDENTITY"
    if isinstance(error, TileQueryError):
        return "TILE_QUERY_" + error.code.name
    if isinstance(error, TransportProtocolError):
        return "TRANSPORT_PROTOCOL"
    if isinstance(error, TimeoutError):
        return "TIMEOUT"
    if isinstance(error, PermissionError):
        return "PERMISSION"
    return error.__class__.__name__.upper()


def diagnose_failure(error: BaseException, *, connected: bool, pages: int, elapsed: float) -> dict:
    record = {
        "code": _failure_code(error),
        "detail": str(error)[:400],
        "connected": connected,
        "pages_exchanged": pages,
        "elapsed_seconds": round(elapsed, 3),
    }
    if isinstance(error, CaptureWorldIdentityError):
        record["observed_welcome_diagnostic"] = {
            key: error.observed_welcome.get(key) for key in WELCOME_IDENTITY_KEYS
        }
    return record


class NativeCaptureBackend:
    """The real one-launch backend; mirrors the retained runner choreography."""

    kind = "NATIVE"

    def __init__(self, *, authorized_one_launch: bool = False) -> None:
        if not authorized_one_launch:
            raise PermissionError(
                "classification capture requires an explicit operator authorization "
                "for exactly one launch and one connection"
            )
        self.process: subprocess.Popen[bytes] | None = None
        self.session: SecureAdminSession | None = None
        self.transport: GameScriptTransport | None = None
        self.proof = None
        self._launched = False
        self._logs: list[IO[bytes]] = []

    def health(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("OpenTTD exited early")
        self._check_logs()

    def _check_logs(self) -> None:
        assert self.proof is not None
        text = "\n".join(
            path.read_text(errors="replace")
            for path in (self.proof.spec.stdout_path, self.proof.spec.stderr_path)
        )
        findings = script_log_health_findings(text)
        if findings:
            raise RuntimeError("Native script/asset error: " + "; ".join(findings))

    async def launch(self, prepared) -> dict:
        if self._launched:
            raise RuntimeError("No launch retry")
        proof = prepared.spec()
        metadata = prepared.metadata()
        if tuple(proof.spec.argv) != tuple(metadata["argv"]):
            raise ValueError("argv drifted from the sealed executable path")
        if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
            raise ValueError("Pinned executable/process ownership mismatch")
        self.proof = proof
        self._launched = True
        stdout = proof.spec.stdout_path.open("xb")
        self._logs.append(stdout)
        stderr = proof.spec.stderr_path.open("xb")
        self._logs.append(stderr)
        env = os.environ.copy()
        env.update(dict(proof.spec.environment))
        self.process = subprocess.Popen(
            proof.spec.argv,
            cwd=proof.spec.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        proof.spec.lifecycle.process = self.process
        self.health()
        return {
            "pid": self.process.pid,
            "argv": list(proof.spec.argv),
            "cwd": str(proof.spec.cwd),
        }

    async def connect(self, prepared, expected_welcome: dict) -> dict:
        """One readiness window, one secure connection, then the identity gate."""
        assert self.proof is not None
        key = AuthorizedKey.from_bytes(self.proof.key_path.read_bytes())
        deadline = time.monotonic() + SECURE_CONNECT_DEADLINE_SECONDS
        while self.session is None:
            self.health()
            if time.monotonic() >= deadline:
                raise TimeoutError("Admin readiness deadline")
            try:
                self.session = await SecureAdminSession.connect_secure(
                    "127.0.0.1", self.proof.endpoints[1], 0.25, key=key
                )
            except AuthDisconnected:
                # A refused TCP connection is a readiness probe, not an auth retry.
                await asyncio.sleep(0.05)
        await self.session.authenticate("classification-capture", "1", timeout=10)
        self.health()
        if self.session.state is not AuthState.ACTIVE:
            raise RuntimeError("Secure stream not active")
        protocol = self.session.protocol
        welcome = self.session.welcome
        if protocol is None or welcome is None:
            raise RuntimeError("Handshake incomplete")
        observed = asdict(welcome)
        missing = [
            key for key in WELCOME_IDENTITY_KEYS if observed.get(key) != expected_welcome.get(key)
        ]
        if missing or not welcome.dedicated:
            raise CaptureWorldIdentityError(observed, missing)
        text = self.proof.spec.stderr_path.read_text(
            errors="replace"
        ) + self.proof.spec.stdout_path.read_text(errors="replace")
        if "Using the OpenGFX base graphics set" not in text:
            raise ValueError("No native OpenGFX load evidence")
        self.health()
        self.transport = GameScriptTransport(self.session, protocol)
        await self.transport.subscribe(token=0x153, timeout=5)
        self.health()
        return {
            "welcome": observed,
            "protocol": asdict(protocol),
            "auth": {
                "method": "X25519_AuthorizedKey",
                "public_key": key.public_hex,
                "public_key_sha256": key.public_sha256,
                "encrypted": True,
                "state": self.session.state.name,
            },
        }

    async def exchange(self, request: TileClassificationRequest) -> TileClassificationExchange:
        if self.transport is None:
            raise RuntimeError("capture transport not connected")
        return await self.transport.tile_classification_page(
            request, timeout=PAGE_TIMEOUT_SECONDS, operation_budget=PAGE_OPERATION_BUDGET
        )

    async def cleanup(self) -> dict:
        pid = None if self.process is None else self.process.pid
        errors: list[dict] = []
        if self.session is not None:
            try:
                await self.session.close(quit=True)
            except BaseException as first:
                errors.append({"stage": "admin_close", "type": type(first).__name__})
                try:
                    await self.session.close()
                except BaseException as second:
                    errors.append({"stage": "admin_force_close", "type": type(second).__name__})
        graceful = self.process is not None and self.process.poll() is None
        try:
            if self.proof is not None:
                await asyncio.to_thread(self.proof.spec.lifecycle.close)
        except BaseException as error:
            errors.append({"stage": "process_cleanup", "type": type(error).__name__})
        finally:
            for log in self._logs:
                try:
                    log.close()
                except OSError as error:
                    errors.append({"stage": "log_close", "type": type(error).__name__})
            self._logs.clear()
            if self.proof is not None:
                self.proof.key_path.unlink(missing_ok=True)
        if self.proof is not None:
            try:
                self._check_logs()
            except RuntimeError as error:
                errors.append({"stage": "final_log_health", "type": type(error).__name__})
        return {
            "pid": pid,
            "graceful_attempted": graceful,
            "quit_command": "quit",
            "returncode": None if self.process is None else self.process.returncode,
            "reaped": self.process is None or self.process.poll() is not None,
            "remaining_processes": matching_processes(BINARY),
            "events": [] if self.proof is None else list(self.proof.spec.lifecycle.events),
            "cleanup_error": errors,
        }


def _request_files(index: int) -> tuple[str, str]:
    stem = f"classification-p{index:03d}"
    return stem + "-request.json", stem + "-response.json"


def _classification_requests() -> list[tuple[int, TileClassificationRequest]]:
    """Exact pinned plan payloads, re-verified request-by-request."""
    requests: list[tuple[int, TileClassificationRequest]] = []
    for index, payload in enumerate(request_plan()):
        request = TileClassificationRequest.parse(payload)
        if request.to_bytes() != payload:
            raise ValueError("pinned plan payload does not round-trip")
        requests.append((index, request))
    return requests


async def execute_capture(prepared, backend) -> dict:
    """Run the sealed classification capture; fail closed on every deviation."""
    directory = prepared.directory
    candidate = prepared.candidate()
    mode = candidate["correspondence_mode"]
    if mode != SOURCE_SAVE_MODE:
        raise ValueError("unsupported correspondence mode for this runner: " + mode)
    if (directory / "CLAIM.json").is_file():
        raise ValueError("one-shot claim already written for this execution")
    prepared.preflight()  # The full read-only gate; its seal is re-checked on disk.
    budget = candidate["budgets"]
    if budget["requests"] > CLASSIFICATION_PAGE_LIMIT:
        raise ValueError("sealed request budget contradicts the deterministic plan")
    write_json(
        directory / "CLAIM.json",
        dict(
            consumed=True,
            prelaunch_digest=sha256(directory / "PRELAUNCH.json"),
            launches_allowed=1,
            retries=0,
        ),
    )
    # Everything after the consumed claim is guarded: any raise must still
    # produce failure evidence and the full owned cleanup. The result stub is
    # built before the guarded block so the handlers never see undefined names.
    result: dict = dict(
        schema=CAPTURE_RESULT_SCHEMA,
        attempt_identity=prepared.attempt_identity,
        correspondence_mode=mode,
        requested_pages=len(candidate["plan"]["pages"]),
        pages=0,
        response_bytes=0,
        status="FAILED",
    )
    started = time.monotonic()
    exchanges: list[TileClassificationExchange] = []
    requests: list[TileClassificationRequest] = []
    receipts: list[dict] = []
    launch_record: dict | None = None
    connect_record: dict | None = None
    proof = None
    try:
        world_binding = retained_save_binding()
        async with asyncio.timeout(float(budget["observation_seconds"])):
            launch_record = await backend.launch(prepared)
            result["launch"] = launch_record
            proof = backend.proof
            await wait_log(backend, proof, GS_READINESS_MARKER)
            expected_welcome = candidate["world_identity_requirements"]["retained_welcome"]
            connect_record = await backend.connect(prepared, expected_welcome)
            result["protocol"] = connect_record["protocol"]
            result["auth"] = connect_record["auth"]
            observed_welcome = connect_record["welcome"]
            write_json(
                directory / "runtime-identity.json",
                {"encrypted": True, "welcome": observed_welcome},
            )
            for index, request in _classification_requests():
                if time.monotonic() - started > float(budget["observation_seconds"]):
                    raise CaptureBudgetError(
                        "OBSERVATION_DEADLINE", "census exceeded its observation budget"
                    )
                if len(exchanges) >= budget["requests"]:
                    raise CaptureBudgetError(
                        "PAGE_BUDGET_EXCEEDED", "census exceeded its page budget"
                    )
                backend.health()
                exchange = await backend.exchange(request)
                if len(exchange.response_payload) > GSADMIN_BYTES:
                    raise CaptureBudgetError(
                        "RESPONSE_BYTE_BUDGET_EXCEEDED",
                        "page response envelope exceeds the wire budget",
                    )
                total_bytes = sum(len(item.response_payload) for item in exchanges) + len(
                    exchange.response_payload
                )
                if total_bytes > budget["total_response_bytes_limit"]:
                    raise CaptureBudgetError(
                        "RESPONSE_BYTE_BUDGET_EXCEEDED",
                        "cumulative response bytes exceed the sealed census budget",
                    )
                exchanges.append(exchange)
                requests.append(request)
                request_name, response_name = _request_files(index)
                (directory / request_name).write_bytes(exchange.request_payload)
                (directory / response_name).write_bytes(exchange.response_payload)
                receipts.append(
                    {
                        "index": index,
                        "request_id": exchange.receipt.request_id,
                        "schema": exchange.receipt.schema,
                        "request_payload_sha256": exchange.receipt.request_payload_sha256,
                        "response_payload_sha256": exchange.receipt.response_payload_sha256,
                        "protocol_operations": exchange.protocol_operations,
                    }
                )
            sweep = TileClassificationSweep.record(
                tuple(requests),
                tuple(exchanges),
                retained_facts=retained_facts(),
                retained_facts_digest=candidate["world_identity_requirements"][
                    "retained_facts_sha256"
                ],
                retained_welcome=expected_welcome,
                observed_welcome=observed_welcome,
            )
            (directory / "classification-completeness.json").write_text(
                sweep.completeness_summary() + "\n"
            )
            write_json(directory / "classification-receipts.json", {"receipts": receipts})
            verdict = evaluate_correspondence(
                SOURCE_SAVE_MODE,
                bound=sweep.bound,
                coherence_failures=sweep.coherence_failures,
                save_binding=world_binding,
            )
            write_json(directory / "correspondence-verdict.json", verdict)
            result["verdict"] = verdict
            result["pages"] = len(exchanges)
            result["response_bytes"] = sum(len(item.response_payload) for item in exchanges)
            result["status"] = (
                "TILE_CLASSIFICATION_V2_CAPTURED"
                if sweep.bound
                else "TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT"
            )
    except Exception as error:
        failure = diagnose_failure(
            error,
            connected=connect_record is not None,
            pages=len(exchanges),
            elapsed=time.monotonic() - started,
        )
        write_json(directory / "capture-failure.json", failure)
        result["failure"] = failure
        if exchanges:
            result["status"] = "PARTIAL_CLASSIFICATION_CAPTURE"
            result["pages"] = len(exchanges)
            result["response_bytes"] = sum(len(item.response_payload) for item in exchanges)
        if proof is not None and backend.process is not None and backend.process.poll() is None:
            try:
                await save(backend, proof, "failure")
            except Exception as failure_save:
                result["failure_save_error"] = str(failure_save)
    finally:
        # A launch failure can leave backend.proof bound even when this local
        # reference never saw it (assignment happens before Popen); the
        # cleanup evidence must describe the actual owned spec.
        proof = proof if proof is not None else backend.proof
        result["launches"] = int(backend.process is not None)
        result["connections"] = 1 if connect_record is not None else 0
        result["requests"] = len(exchanges)
        result["mutations"] = 0
        cleanup = await backend.cleanup()
        for name in ("stdout.log", "stderr.log"):
            source = proof.spec.workspace.logs / name if proof is not None else None
            if source is not None and source.is_file():
                (directory / name).write_bytes(source.read_bytes())
        try:
            if proof is not None:
                cleanup.update(verify_cleanup_endpoints(proof, cleanup))
            if not cleanup["reaped"] or cleanup["cleanup_error"]:
                raise ValueError("incomplete cleanup")
            if proof is not None:
                proof.spec.workspace.close()
            cleanup["workspace_disposed"] = proof is None or (
                not proof.spec.workspace.root.exists()
            )
            cleanup["credential_removed"] = proof is None or not proof.key_path.exists()
        except Exception as cleanup_error:
            cleanup["verification_error"] = str(cleanup_error)
            result["status"] = "FAILED_CLEANUP"
        write_json(directory / "cleanup.json", cleanup)
        result["cleanup"] = cleanup
        write_json(directory / "result.json", result)
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return result


def preflight_only(directory: Path) -> dict:
    """The read-only preparation gate; consumes nothing."""
    return load_execution(directory).preflight()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="run the sealed Tile Classification V2 capture after explicit authorization"
    )
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("directory")
    parser.add_argument(
        "--authorize-one-launch",
        action="store_true",
        help="consume the one-shot claim of a freshly staged execution candidate",
    )
    args = parser.parse_args()
    prepared = load_execution(Path(args.directory))
    if args.command == "preflight":
        metadata = preflight_only(Path(args.directory))
        print(json.dumps({"argv": list(metadata["argv"]), "status": "PREFLIGHT_PASS"}))
        return
    backend = NativeCaptureBackend(authorized_one_launch=args.authorize_one_launch)
    result = asyncio.run(execute_capture(prepared, backend))
    print(json.dumps({"status": result.get("status"), "pages": result.get("pages")}))


if __name__ == "__main__":
    main()
