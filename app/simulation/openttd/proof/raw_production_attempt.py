"""Public combined proof owner; acceptance follows cleanup and persistent integrity."""

import json
import shutil
from dataclasses import asdict, dataclass, field, replace
from enum import Enum, auto
from types import SimpleNamespace

from app.simulation.openttd.production_observation import production_pairs
from app.simulation.openttd.raw_production_session import CompleteRawProductionSession

from .attempt import Gate, Gates
from .endpoints import verify_cleanup_endpoints
from .harness import EndpointReservation, manifest, verify_freeze, write_json
from .ownership import finalize_cleanup
from .raw_production_contract import (
    RAW_PRODUCTION_ATTEMPT_DIRECTORY,
    RAW_PRODUCTION_MODEL,
    RAW_PRODUCTION_SESSION_ID,
    RawProductionFrameBudget,
)
from .raw_production_lineage import retain_attempt_identity
from .structural_attempt import retain_structural
from .world_attempt import record_prelaunch_failure


class RawProductionProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    COMBINED_SESSION_STARTED = auto()
    STRUCTURAL_COLLECTION_STARTED = auto()
    STRUCTURAL_WORLD_COMPLETED = auto()
    PRODUCTION_TARGETS_FINALIZED = auto()
    RAW_PRODUCTION_STARTED = auto()
    RAW_PRODUCTION_COMPLETED = auto()
    COMBINED_OBSERVATION_VERIFIED = auto()
    CLEANUP_STARTED = auto()
    PROCESS_REAPED = auto()
    ENDPOINTS_CLOSED = auto()
    CREDENTIAL_REMOVED = auto()
    WORKSPACE_DISPOSED = auto()
    POSTRUN_INTEGRITY_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class RawProductionLifecycle:
    states: list[RawProductionProofState] = field(
        default_factory=lambda: [RawProductionProofState.PREPARED]
    )

    def advance(self, state):
        order = list(RawProductionProofState)
        current = self.states[-1]
        if current in (RawProductionProofState.COMPLETED, RawProductionProofState.FAILED):
            raise ValueError("Terminal combined lifecycle; no resume")
        cleanup = state is RawProductionProofState.CLEANUP_STARTED
        if (
            state is RawProductionProofState.FAILED
            or (cleanup and order.index(current) >= order.index(state))
            or (not cleanup and order.index(state) != order.index(current) + 1)
            or (state is RawProductionProofState.COMPLETED and self.states != order[:-2])
        ):
            raise ValueError("Combined lifecycle barrier not passed")
        self.states.append(state)

    def fail(self):
        # A terminal evidence-write failure may invalidate an otherwise completed
        # candidate before its final immutable manifest has been retained.
        if self.states[-1] is RawProductionProofState.COMPLETED:
            self.states.pop()
        if self.states[-1] is not RawProductionProofState.FAILED:
            self.states.append(RawProductionProofState.FAILED)


class RawProductionRunner:
    def __init__(self, prepared, backend):
        if not isinstance(backend.accounting, RawProductionFrameBudget):
            raise ValueError("Shared combined native accounting authority required")
        self.prepared, self.backend = prepared, backend
        self.lifecycle = RawProductionLifecycle()
        self.coordinator = None
        self._targets = None

    @property
    def targets(self):
        return self._targets

    def semantic_complete(self):
        return self.coordinator is not None and self.coordinator.evidence.complete

    def launch_boundary(self):
        self.backend.validate_launch(self.prepared)
        if self.backend.accounting.total_frames or self.backend.accounting.failed:
            raise ValueError("Fresh continuous accounting instance required")
        return dict(
            production_runner_loaded=True,
            combined_runner_loaded=True,
            accounting_wired=True,
            launch_boundary_reached=True,
            max_query_operations=5120,
            max_total_post_auth_frames=5126,
        )

    def require_owner(self):
        c, b = self.coordinator, self.backend
        if c is None:
            raise ValueError("Combined coordinator unavailable")
        c.check(b.transport)
        if (
            b.session is not b.secure_connection
            or b.structural_session is not c.context.connection_identity
            or b.structural_session.session is not b.secure_connection
            or b.process is not c.context.process_identity
        ):
            raise ValueError("Combined process/continuous connection replaced")

    def phase_started(self, phase):
        c, b = self.coordinator, self.backend
        if (
            c is None
            or b.session is not b.secure_connection
            or b.structural_session is not c.context.connection_identity
            or b.process is not c.context.process_identity
        ):
            raise ValueError("Combined process/continuous connection replaced")
        c.context.require_same_run(b.transport.context)
        if any(not r["validated"] for r in b.structural_session.transactions):
            raise ValueError("Unvalidated native transaction before phase transition")
        if phase == "PRODUCTION":
            if c.structural is None or not c.structural.complete:
                raise ValueError("Complete structural world required before production")
            replace(c.structural)
            if not c.structural.structural_world_digest:
                raise ValueError("Finalized structural digest required")
            self.lifecycle.advance(RawProductionProofState.STRUCTURAL_WORLD_COMPLETED)
            return
        child = c.structural_session
        preceding = {
            "CAPABILITY": (child.inventory, "inventory_digest"),
            "CATALOG": (child.capability, "capability_digest"),
            "ASSEMBLY": (child.catalog, "catalog_digest"),
        }
        if phase == "INVENTORY":
            self.lifecycle.advance(RawProductionProofState.STRUCTURAL_COLLECTION_STARTED)
        else:
            observation, digest = preceding[phase]
            if observation is None or not observation.complete or not getattr(observation, digest):
                raise ValueError("Complete preceding phase digest required")
        if phase != "ASSEMBLY":
            b.accounting.enter(phase.lower())

    def targets_finalized(self, targets):
        c = self.coordinator
        if (
            c is None
            or c.structural is None
            or c.production_session is None
            or self._targets is not None
            or type(targets) is not tuple
            or targets != production_pairs(c.structural)
            or targets != c.production_session.targets
        ):
            raise ValueError("Exact immutable same-run produced target set required")
        self._targets = targets
        self.lifecycle.advance(RawProductionProofState.PRODUCTION_TARGETS_FINALIZED)
        self.backend.accounting.enter("production")
        self.lifecycle.advance(RawProductionProofState.RAW_PRODUCTION_STARTED)

    async def collect(self):
        b = self.backend
        self.coordinator = CompleteRawProductionSession(
            b.transport.context,
            b.economy_month,
            session_id=RAW_PRODUCTION_SESSION_ID,
            timeout=15,
            phase_started=self.phase_started,
            targets_finalized=self.targets_finalized,
        )
        b.combined_coordinator = self.coordinator
        b.coordinator = self.coordinator.structural_session
        self.lifecycle.advance(RawProductionProofState.COMBINED_SESSION_STARTED)

        async def evidence(request, exchange):
            self.require_owner()
            result = await b.evidence(self.prepared, request, exchange)
            self.require_owner()
            return result

        structural, production = await self.coordinator.collect(
            b.transport, evidence, evidence, evidence, evidence
        )
        self.require_owner()
        replace(structural)
        replace(production)
        structural.inventory.context.require_same_run(production.context)
        if (
            not structural.complete
            or not production.complete
            or production.source is not structural
            or production.source_structural_world_digest != structural.structural_world_digest
            or production.qualified_for_planning
            or production.qualification.rollover_count
            or self.targets != tuple(r.pair for r in production.records)
            or b.accounting.query_operations != self.coordinator.evidence.protocol_operations
            or b.query_operation_baseline != b.accounting.query_operations
        ):
            raise ValueError(
                "Complete unqualified same-run semantic/accounting verification failed"
            )
        self.lifecycle.advance(RawProductionProofState.RAW_PRODUCTION_COMPLETED)
        self.lifecycle.advance(RawProductionProofState.COMBINED_OBSERVATION_VERIFIED)
        return structural, production


def retain_combined(attempt, runner, backend, successful):
    c = runner.coordinator
    child = None if c is None else c.structural_session
    # Retain completed structural facts even if the later dynamic phase failed.
    retain_structural(
        attempt,
        SimpleNamespace(coordinator=child),
        backend,
        child is not None and child.observation is not None,
    )
    production_session = None if c is None else c.production_session
    evidence = None if production_session is None else production_session.evidence
    production = None if c is None else c.production
    write_json(
        attempt / "production-session.json",
        dict(
            complete=successful,
            qualified_for_planning=False,
            rollovers_observed=0,
            targets=runner.targets,
            events=[] if evidence is None else evidence.events,
            request_attempts=0 if evidence is None else evidence.request_attempts,
            validated_records=0 if evidence is None else len(evidence.transactions),
            failure=None if evidence is None else evidence.failure,
        ),
    )
    write_json(
        attempt / "production-observation.json",
        dict(
            complete=successful,
            qualified_for_planning=False,
            source_structural_world_digest=None
            if c is None or c.structural is None
            else c.structural.structural_world_digest,
            records=[]
            if evidence is None
            else [asdict(t.exchange.response.record) for t in evidence.transactions],
            production_digest=production.production_digest
            if successful and production is not None
            else None,
            same_process=successful,
            same_connection=successful,
        ),
    )
    if successful and production is not None:
        (attempt / "production-canonical.json").write_bytes(production.to_bytes())
    write_json(
        attempt / "combined-session.json",
        dict(
            complete=successful,
            qualified_for_planning=False,
            semantic_evidence=None if c is None else asdict(c.evidence),
            lifecycle=[s.name for s in runner.lifecycle.states],
            final_acceptance_pending=True,
        ),
    )


async def execute_raw_production_attempt(prepared, backend, *, qualification=False):
    from .preflight import preflight_prepared

    if qualification:
        from .qualification_attempt import (
            QualificationProofState,
            QualificationRunner,
            retain_qualification,
        )
        from .qualification_contract import ATTEMPT_DIRECTORY, KIND, MODEL
        from .qualification_lineage import retain_attempt_identity as retain_identity

        runner_type, state_type, retain = (
            QualificationRunner,
            QualificationProofState,
            retain_qualification,
        )
        maximum_requests = 1072
    else:
        ATTEMPT_DIRECTORY, KIND, MODEL = (
            RAW_PRODUCTION_ATTEMPT_DIRECTORY,
            "complete-raw-production",
            RAW_PRODUCTION_MODEL,
        )
        runner_type, state_type, retain = (
            RawProductionRunner,
            RawProductionProofState,
            retain_combined,
        )
        retain_identity = retain_attempt_identity
        maximum_requests = 608
    attempt = prepared.directory.with_name(ATTEMPT_DIRECTORY)
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if metadata.get("mode") != KIND or metadata.get("proof_model") != MODEL:
            raise ValueError("Dedicated combined immutable preparation required")
        preflight_prepared(prepared, backend)
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        secret = prepared.key_path.read_bytes()
        reservation = EndpointReservation.allocate(*prepared.endpoints)
    except Exception as error:
        record_prelaunch_failure(prepared.directory, error)
        raise
    try:
        attempt.mkdir()
    except BaseException:
        reservation.close()
        raise
    runner = runner_type(prepared, backend)
    result: dict = dict(
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        reconnects=0,
        error=None,
        proof_kind=KIND,
        freeze_revision=metadata["prelaunch_revision"],
        attempt_id=metadata["attempt_id"],
        preparation=str(prepared.directory),
        qualified_for_planning=False,
    )
    cleanup = {}

    def capture(action):
        try:
            return action()
        except BaseException as error:
            result["error"] = result["error"] or f"Finalization failure: {error}"
            return None

    try:
        for path in prepared.directory.iterdir():
            if path.is_file() and path.name != "artifact-manifest.sha256":
                shutil.copyfile(path, attempt / path.name)
        verify_freeze(frozen)
        runner.launch_boundary()
        reservation.close()
        await backend.launch(prepared)
        runner.lifecycle.advance(state_type.LAUNCHED)
        gates = Gates()
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        if (
            not auth["auth"].get("encrypted")
            or auth["auth"].get("method") != "X25519_AuthorizedKey"
            or auth["protocol"].get("version") != 3
            or auth["welcome"] != asdict(backend.welcome)
        ):
            raise ValueError("Encrypted X25519/Protocol 3/native WELCOME required")
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        runner.lifecycle.advance(state_type.ADMIN_ACTIVE)
        await backend.setup(prepared)
        await runner.collect()
        await backend.secure_connection.require_quiescent()
        backend.health()
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        reservation.close()
        runner.lifecycle.advance(state_type.CLEANUP_STARTED)
        try:
            cleanup = await backend.cleanup(prepared)
            if (
                not cleanup.get("reaped")
                or cleanup.get("remaining_processes")
                or cleanup.get("cleanup_error")
                or (
                    backend.launches
                    and (not cleanup.get("graceful_attempted") or cleanup.get("returncode") != 0)
                )
            ):
                raise ValueError("Clean shutdown/process reap not proved")
            runner.lifecycle.advance(state_type.PROCESS_REAPED)

            def endpoints_closed():
                cleanup.update(verify_cleanup_endpoints(prepared, cleanup, reservation))
                return True

            cleanup["sockets_closed"] = endpoints_closed()
            runner.lifecycle.advance(state_type.ENDPOINTS_CLOSED)
            prepared.key_path.unlink(missing_ok=True)
            runner.lifecycle.advance(state_type.CREDENTIAL_REMOVED)
        except BaseException as error:
            result["error"] = result["error"] or str(error)
        finally:
            capture(lambda: prepared.key_path.unlink(missing_ok=True))
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():

                def log(source=source, name=name):
                    raw = source.read_bytes()
                    clean = raw.replace(secret.hex().encode(), b"<REDACTED>").replace(
                        secret, b"<REDACTED>"
                    )
                    if clean != raw:
                        result["error"] = result["error"] or "Private credential appeared in log"
                    (attempt / name).write_bytes(clean)

                capture(log)
        try:
            if not cleanup.get("sockets_closed"):
                raise ValueError("Closed endpoints not proved")
            finalize_cleanup(prepared, frozen, cleanup)
            runner.lifecycle.advance(state_type.WORKSPACE_DISPOSED)
            runner.lifecycle.advance(state_type.POSTRUN_INTEGRITY_VERIFIED)
        except BaseException as error:
            result["error"] = result["error"] or str(error)
        rows = getattr(backend.structural_session, "transactions", ())
        result.update(
            launches=backend.launches,
            connections=int(backend.session is not None),
            requests_sent=sum(r["delivery"] == "SENT" for r in rows),
            requests_attempted=len(rows),
            ambiguous_requests=sum(r["delivery"] == "AMBIGUOUS" for r in rows),
            source_integrity=cleanup.get("postrun_integrity_verified", False),
            accounting=backend.accounting.snapshot(),
        )
        if backend.accounting.failed:
            result["error"] = result["error"] or "Shared native frame budget failed"
        semantic = capture(runner.semantic_complete)
        successful = (
            result["error"] is None
            and semantic
            and result["launches"] == result["connections"] == 1
            and 1 <= result["requests_sent"] <= maximum_requests
        )
        capture(lambda: retain(attempt, runner, backend, successful))
        capture(
            lambda: write_json(
                attempt / "admin-frame-accounting.json", backend.accounting.snapshot()
            )
        )
        capture(lambda: write_json(attempt / "process-lifecycle.json", cleanup))
        capture(
            lambda: write_json(
                attempt / "source-freeze-post.json", dict(unchanged=result["source_integrity"])
            )
        )
        private = capture(
            lambda: any(
                secret in p.read_bytes() or secret.hex().encode() in p.read_bytes()
                for p in attempt.rglob("*")
                if p.is_file()
            )
        )
        if private is not False:
            result["error"] = result["error"] or "Private credential retained in evidence"
        if successful and result["error"] is None:
            runner.lifecycle.advance(state_type.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
            result["qualified_for_planning"] = qualification
        else:
            runner.lifecycle.fail()
            if not result["launches"]:
                result["status"] = "PRELAUNCH_FAILED"
        result["states"] = [s.name for s in runner.lifecycle.states]

        def terminal():
            combined = attempt / (
                "qualification-session.json" if qualification else "combined-session.json"
            )
            if combined.exists():
                value = json.loads(combined.read_text())
                value.update(
                    qualified_for_planning=qualification and result["status"].endswith("_SUCCESS"),
                    complete=result["status"].endswith("_SUCCESS"),
                    final_acceptance_pending=False,
                    lifecycle=result["states"],
                )
                combined.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
            if not result["status"].endswith("_SUCCESS"):
                for name in ("production-session.json", "production-observation.json"):
                    path = attempt / name
                    if path.exists():
                        value = json.loads(path.read_text())
                        value.update(
                            complete=False, qualified_for_planning=False, failure=result["error"]
                        )
                        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
                (attempt / "production-canonical.json").unlink(missing_ok=True)
            write_json(attempt / "proof-evidence.json", result)
            (attempt / "final-report.md").write_text(
                f"# {result['status']}\n\n"
                f"Complete raw production: {result['status'].endswith('_SUCCESS')}.\n"
                "Qualified history: "
                f"{'PROVEN' if result['qualified_for_planning'] else 'NOT PROVEN'}. "
                "Independent production source: NONE.\n"
                "NON-ATOMIC, PRE-DECISION; station allocation is not vehicle delivery.\n"
                f"Error: {result['error']}\nP08 completion: NO.\n"
            )
            retain_identity(attempt, metadata, result)
            (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))

        try:
            terminal()
        except BaseException as error:
            result["error"] = result["error"] or f"Terminal evidence retention failure: {error}"
            result["qualified_for_planning"] = False
            result["status"] = (
                backend.kind + "_FAILED" if result["launches"] else "PRELAUNCH_FAILED"
            )
            runner.lifecycle.fail()
            result["states"] = [s.name for s in runner.lifecycle.states]
            # These are this active attempt's output files, not historical evidence.
            # No partial success can survive a terminal persistence failure.
            for name in (
                "production-session.json",
                "production-observation.json",
                "qualification-session.json" if qualification else "combined-session.json",
            ):
                path = attempt / name
                if path.exists():

                    def normalize(path=path):
                        value = json.loads(path.read_text())
                        value.update(
                            complete=False, qualified_for_planning=False, failure=result["error"]
                        )
                        if path.name in ("combined-session.json", "qualification-session.json"):
                            value.update(lifecycle=result["states"], final_acceptance_pending=False)
                        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

                    capture(normalize)
            capture(lambda: (attempt / "production-canonical.json").unlink(missing_ok=True))
            if qualification:
                capture(lambda: (attempt / "qualified-month.json").unlink(missing_ok=True))
            capture(lambda: (attempt / "proof-attempt.json").unlink(missing_ok=True))
            capture(
                lambda: (attempt / "proof-evidence.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "final-report.md").write_text(
                    f"# {result['status']}\n\n{result['error']}\n"
                )
            )
            capture(lambda: retain_identity(attempt, metadata, result))
            capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
    return result
