"""Dormant one-page backend; shared secure startup and Linux cleanup, no retry."""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
)
from app.simulation.openttd.tile_facts_evidence import parse_tile_facts_evidence

from .harness import sha256, write_json
from .structural_native import StructuralNativeBackend
from .terrain_preparation import REQUEST, SinglePageFrames, budget


class SinglePageSession(GameScriptSession):
    def __init__(self, secure):
        super().__init__(secure.reader, secure._writer)
        self.secure = secure
        self.requests = 0

    async def send(self, *frames):
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.requests or decode_gamescript(frame[3:]) != REQUEST.to_bytes():
                    raise ValueError("Exactly one frozen tile request; no retry")
                self.requests += 1
        await self.secure.send(*frames)

    async def receive(self, size=4096):
        return await self.secure.receive(size)

    async def close(self, *, quit=False):
        await self.secure.close(quit=quit)


class SinglePageNativeBackend(StructuralNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.accounting = SinglePageFrames()
        self.page_session = None
        self._capture_tasks = []
        self._capture_failed = False
        self.authorization = None
        self.claim = None
        self.popen_invoked = False
        self.failure_stage = "preflight"

    def preflight(self, prepared):
        """Reuse terrain asset admission; its seal has no generic graphics receipt."""
        from app.simulation.openttd.admin_crypto import AuthorizedKey

        from .native import matching_processes
        from .terrain_preparation import TerrainCandidate

        seal = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        directory = Path(seal["candidate_path"])
        candidate = TerrainCandidate(
            directory, json.loads((directory / "CANDIDATE.json").read_text())
        )
        candidate.preflight()  # Exact executable/graphics/package/config/key/source bytes.
        from .terrain_capture import capture_paths, validate_captures

        if (prepared.spec.stdout_path, prepared.spec.stderr_path) != capture_paths(
            prepared.spec.workspace.root
        ):
            raise ValueError("Launch specification capture paths mismatch")
        validate_captures(prepared.spec.workspace.root)
        if matching_processes(prepared.spec.identity.executable):
            raise ValueError("Pinned executable/process ownership mismatch")
        self._key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())
        if self._key.public_hex != prepared.public_key:
            raise ValueError("Proof key identity mismatch")

    @property
    def launches(self):
        return int(self.process is not None)

    def bind_authorization(self, authorization, claim):
        from .terrain_authorization import (
            FailureCode,
            LocalOperatorAuthorization,
            LocalProofFailure,
        )
        from .terrain_seal import AttemptClaim

        if (
            not isinstance(authorization, LocalOperatorAuthorization)
            or not isinstance(claim, AttemptClaim)
            or self._launched
        ):
            raise LocalProofFailure(FailureCode.AUTHORIZATION_INVALID, "Typed grant/claim required")
        authorization.require_process(native=True)
        self.authorization, self.claim = authorization, claim

    @property
    def connections(self):
        return int(self._connection_claimed)

    @property
    def requests(self):
        return 0 if self.page_session is None else self.page_session.requests

    def validate_launch(self, prepared):
        from .terrain_attempt import validate_final_prelaunch

        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        validate_final_prelaunch(
            prepared,
            Path(metadata["attempt_directory"]),
            native=True,
            authorization=self.authorization,
            claim=self.claim,
            capture_phase="prepared" if self._logs else "absent",
        )
        claim = json.loads((Path(metadata["attempt_directory"]) / "launch-claim.json").read_text())
        if claim != dict(
            mode="REAL",
            prepared_directory=str(prepared.directory),
            request_sha256=sha256(prepared.directory / "request.json"),
            no_retry=True,
        ):
            raise PermissionError("Owned one-shot launch claim required")
        super().validate_launch(prepared)

    async def launch(self, prepared):
        from .terrain_authorization import (
            FailureCode,
            LocalOperatorAuthorization,
            LocalProofFailure,
        )
        from .terrain_seal import AttemptClaim

        if self._launched:
            raise LocalProofFailure(FailureCode.ATTEMPT_ALREADY_CONSUMED, "No launch retry")
        if not isinstance(self.authorization, LocalOperatorAuthorization) or not isinstance(
            self.claim, AttemptClaim
        ):
            raise LocalProofFailure(FailureCode.AUTHORIZATION_INVALID, "Typed grant/claim required")
        self.failure_stage = "initial_launch_validation"
        self.validate_launch(prepared)
        self._prepared = prepared
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        write_json(
            Path(metadata["attempt_directory"]) / "native-launch-claimed.json",
            dict(
                mode="REAL",
                launch_invocations=1,
                no_retry=True,
                seal_sha256=self.authorization.seal_sha256,
                attempt_identity=self.authorization.attempt_identity,
                owner_nonce=self.authorization.owner_nonce,
                owner_pid=self.authorization.owner_pid,
                owner_start=self.authorization.owner_start,
                consumed_record_sha256=self.claim.record_sha256,
            ),
        )
        from .terrain_seal import _fsync_directory

        marker = Path(metadata["attempt_directory"]) / "native-launch-claimed.json"
        with marker.open("rb") as stream:
            os.fsync(stream.fileno())
        _fsync_directory(marker.parent)
        self._launched = True  # invocation burned even if source validation/Popen fails
        from .terrain_capture import open_capture, validate_captures

        root = prepared.spec.workspace.root
        self.failure_stage = "capture_setup"
        stdout = open_capture(root, prepared.spec.stdout_path)
        self._logs.append(stdout)
        stderr = open_capture(root, prepared.spec.stderr_path)
        self._logs.append(stderr)
        self.failure_stage = "final_pre_popen_validation"
        # Last source/grant/claim check after durable invocation marker and log setup.
        self.validate_launch(prepared)
        validate_captures(root, phase="prepared", streams=self._logs)
        self.failure_stage = "popen"
        self.popen_invoked = True
        try:
            self.process = subprocess.Popen(
                prepared.spec.argv,
                cwd=prepared.spec.cwd,
                env=dict(prepared.spec.environment),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as error:
            from .terrain_authorization import FailureCode, LocalProofFailure

            raise LocalProofFailure(
                FailureCode.LAUNCH_FAILED, "Popen failed; claim retained"
            ) from error
        prepared.spec.lifecycle.process = self.process
        assert self.process.stdout is not None and self.process.stderr is not None
        self._capture_tasks = [
            asyncio.create_task(self._capture(self.process.stdout, stdout)),
            asyncio.create_task(self._capture(self.process.stderr, stderr)),
        ]
        self.health()

    async def _capture(self, pipe, output):
        size = 0
        try:
            while True:
                raw = await asyncio.to_thread(pipe.read1, 4096)
                if not raw:
                    break
                remaining = budget()["capture_bytes"] - size
                output.write(raw[:remaining])
                output.flush()
                size += min(len(raw), remaining)
                if len(raw) > remaining:
                    self._capture_failed = True
                    break
        except Exception:
            self._capture_failed = True

    async def cleanup(self, prepared):
        logs, self._logs = self._logs, []
        try:
            result = await super().cleanup(prepared)
            if self._capture_tasks:
                await asyncio.wait_for(asyncio.gather(*self._capture_tasks), 2)
            try:
                self._check_logs()
            except RuntimeError:
                result["cleanup_error"].append(
                    dict(stage="post_capture_log_health", type="LogHealthFailure")
                )
            if self._capture_failed:
                result["cleanup_error"].append(dict(stage="bounded_capture", type="CaptureFailure"))
            return result
        finally:
            for task in self._capture_tasks:
                if not task.done():
                    task.cancel()
            for log in logs:
                log.close()
            if self.process is not None:
                for pipe in (self.process.stdout, self.process.stderr):
                    if pipe is not None:
                        pipe.close()

    def _check_logs(self):
        if self._capture_failed:
            raise RuntimeError("Bounded capture failed")
        if self._prepared is not None:
            for p in (self._prepared.spec.stdout_path, self._prepared.spec.stderr_path):
                if p.exists() and p.stat().st_size > budget()["capture_bytes"]:
                    raise RuntimeError("Bounded capture exhausted")
        super()._check_logs()

    def configure_transport(self, prepared, protocol):
        if prepared.request != REQUEST or self.session is None or self.accounting.total_frames != 2:
            raise ValueError("Frozen request/secure establishment required")
        self.page_session = SinglePageSession(self.session)
        self.transport = GameScriptTransport(self.page_session, protocol)

    async def tile_facts_page(self, request):
        self.health()
        if self._sent or request != REQUEST or self.session is not self.secure_connection:
            raise ValueError("One continuous connection and one request only")
        self._sent = True
        assert self.transport is not None
        return await self.transport.tile_facts_page(request, timeout=15, operation_budget=8)

    async def page_evidence(self, prepared, exchange):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            assert self.secure_connection is not None
            await self.secure_connection.require_quiescent()
            raw = prepared.spec.stderr_path.read_bytes()
            evidence = parse_tile_facts_evidence(raw, REQUEST.request_id)
            if len(evidence.ordered_sequence) == 4:
                evidence.require_complete(exchange)
                return raw
            if time.monotonic() >= deadline:
                raise TimeoutError("Command-specific native read/liveness deadline")
            await asyncio.sleep(0.01)  # File observation only, no network/query retry.
