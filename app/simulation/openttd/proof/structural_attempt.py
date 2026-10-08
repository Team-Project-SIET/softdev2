"""One owned structural proof invocation; controlled preflight shares its launch gate."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto

from app.simulation.openttd.structural_world_session import StructuralWorldSession

from .attempt import Gate, Gates
from .endpoints import verify_cleanup_endpoints
from .harness import PROJECT, EndpointReservation, manifest, verify_freeze, write_json
from .historical_protection import protection_base, validate_protection
from .structural_contract import (
    STRUCTURAL_ATTEMPT_DIRECTORY,
    STRUCTURAL_MODEL,
    StructuralFrameBudget,
)
from .structural_lineage import retain_attempt_identity
from .world_attempt import record_prelaunch_failure


class StructuralProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    STRUCTURAL_SESSION_STARTED = auto()
    INDUSTRY_INVENTORY_STARTED = auto()
    INDUSTRY_INVENTORY_COMPLETED = auto()
    INDUSTRY_CAPABILITY_STARTED = auto()
    INDUSTRY_CAPABILITY_COMPLETED = auto()
    CARGO_CATALOG_STARTED = auto()
    CARGO_CATALOG_COMPLETED = auto()
    REFERENTIAL_INTEGRITY_VALIDATED = auto()
    STRUCTURAL_WORLD_ASSEMBLED = auto()
    STRUCTURAL_WORLD_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class StructuralLifecycle:
    states: list[StructuralProofState] = field(
        default_factory=lambda: [StructuralProofState.PREPARED]
    )

    def advance(self, state):
        if (
            self.states[-1] in (StructuralProofState.COMPLETED, StructuralProofState.FAILED)
            or state is not list(StructuralProofState)[len(self.states)]
            or state is StructuralProofState.FAILED
        ):
            raise ValueError("Invalid structural lifecycle transition")
        self.states.append(state)

    def fail(self):
        if self.states[-1] is not StructuralProofState.FAILED:
            self.states.append(StructuralProofState.FAILED)


class StructuralProductionRunner:
    def __init__(self, prepared, backend):
        self.prepared, self.backend = prepared, backend
        self.lifecycle = StructuralLifecycle()
        self.coordinator = None
        if not isinstance(backend.accounting, StructuralFrameBudget):
            raise ValueError("Shared secure frame accounting authority required")

    def launch_boundary(self) -> dict:
        """Same last read-only native launch check; never creates a subprocess."""
        self.backend.validate_launch(self.prepared)
        if self.backend.accounting.total_frames or self.backend.accounting.failed:
            raise ValueError("Fresh native frame accounting required")
        return dict(
            production_runner_loaded=True,
            accounting_wired=True,
            launch_boundary_reached=True,
            max_query_operations=1024,
            max_total_post_auth_frames=1030,
        )

    def phase_started(self, phase):
        c = self.coordinator
        b = self.backend
        if (
            c is None
            or b.session is not b.secure_connection
            or b.process is not c.context.process_identity
        ):
            raise ValueError("Owned structural process/connection required")
        checks = {
            "INVENTORY": (None, None, None, StructuralProofState.INDUSTRY_INVENTORY_STARTED),
            "CAPABILITY": (
                c.inventory,
                "inventory_digest",
                StructuralProofState.INDUSTRY_INVENTORY_COMPLETED,
                StructuralProofState.INDUSTRY_CAPABILITY_STARTED,
            ),
            "CATALOG": (
                c.capability,
                "capability_digest",
                StructuralProofState.INDUSTRY_CAPABILITY_COMPLETED,
                StructuralProofState.CARGO_CATALOG_STARTED,
            ),
            "ASSEMBLY": (
                c.catalog,
                "catalog_digest",
                StructuralProofState.CARGO_CATALOG_COMPLETED,
                None,
            ),
        }
        observation, digest_name, completed, started = checks[phase]
        if observation is not None:
            if (
                digest_name is None
                or not observation.complete
                or not getattr(observation, digest_name)
            ):
                raise ValueError("Complete semantic digest barrier required")
        elif phase != "INVENTORY":
            raise ValueError("Early structural phase transition")
        # Only validated same-connection transactions can advance a phase.
        if any(not row["validated"] for row in b.structural_session.transactions):
            raise ValueError("Unvalidated native evidence before phase barrier")
        if completed is not None:
            self.lifecycle.advance(completed)
        if started is not None:
            b.accounting.enter(phase.lower())
            self.lifecycle.advance(started)

    async def collect(self):
        b = self.backend
        self.coordinator = StructuralWorldSession(
            b.transport.context, timeout=15, phase_started=self.phase_started
        )
        b.coordinator = self.coordinator
        self.lifecycle.advance(StructuralProofState.STRUCTURAL_SESSION_STARTED)

        async def evidence(q, e):
            native = await b.evidence(self.prepared, q, e)
            assert self.coordinator is not None
            b.transport.context.require_same_run(self.coordinator.context)
            return native

        observation = await self.coordinator.collect(b.transport, evidence, evidence, evidence)
        for state in (
            StructuralProofState.REFERENTIAL_INTEGRITY_VALIDATED,
            StructuralProofState.STRUCTURAL_WORLD_ASSEMBLED,
            StructuralProofState.STRUCTURAL_WORLD_VERIFIED,
        ):
            self.lifecycle.advance(state)
        return observation


def retain_structural(attempt, runner, backend, successful):
    c = runner.coordinator
    rows = []
    for row in getattr(backend.structural_session, "transactions", ()):
        record = dict(
            request=json.loads(row["request_payload"]),
            response=None
            if row["response_payload"] is None
            else row["response_payload"].decode("ascii", errors="backslashreplace"),
            receipt=None if row["receipt"] is None else asdict(row["receipt"]),
            validated=row["validated"],
            events=row["events"],
            delivery=row["delivery"],
            gamescript=None if row.get("gamescript") is None else asdict(row["gamescript"]),
        )
        if record["gamescript"] is not None:
            record["gamescript"].pop("raw_log", None)
        rows.append(record)
    (attempt / "transactions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    value: dict[str, object] = dict(
        complete=False, inventory_complete=False, capability_complete=False, catalog_complete=False
    )
    if c is not None:
        for name, digest_name in (
            ("inventory", "inventory_digest"),
            ("capability", "capability_digest"),
            ("catalog", "catalog_digest"),
        ):
            observation = getattr(c, name)
            value[name + "_complete"] = observation is not None and observation.complete
            child = getattr(c, name + "_session")
            exchanges = (
                ()
                if child is None
                else child.page_exchanges
                if name == "inventory"
                else child.evidence.exchanges
            )
            payload = dict(complete=value[name + "_complete"], retained_transactions=len(exchanges))
            if observation is not None:
                payload.update(
                    semantic_observation=json.loads(observation.to_bytes()),
                    semantic_digest=getattr(observation, digest_name),
                )
                value[digest_name] = getattr(observation, digest_name)
            if name == "capability" and observation is not None:
                payload["source_inventory_digest"] = observation.inventory.inventory_digest
            write_json(attempt / (name + "-observation.json"), payload)
        ev = c.evidence
        write_json(
            attempt / "structural-session.json",
            dict(
                session_id=ev.session_id,
                events=ev.events
                if successful
                else tuple(e for e in ev.events if e != "STRUCTURAL_WORLD_SESSION_COMPLETED")
                + ("STRUCTURAL_WORLD_SESSION_FAILED",),
                complete=successful,
                request_attempts=ev.request_attempts,
                total_response_bytes=ev.total_response_bytes,
                query_operations=ev.protocol_operations,
                failure=ev.failure,
            ),
        )
        if successful and c.observation is not None:
            value.update(
                complete=True,
                industry_count=c.observation.industry_count,
                capability_count=c.observation.capability_count,
                cargo_count=c.observation.cargo_count,
                ordered_industry_ids=c.observation.ordered_industry_ids,
                ordered_cargo_ids=c.observation.ordered_cargo_ids,
                map_width=c.observation.map_width,
                map_height=c.observation.map_height,
                structural_world_digest=c.observation.structural_world_digest,
                session_id=c.session_id,
                same_process=True,
                same_connection=True,
                configuration_digest=c.context.configuration_digest,
                bridge_digest=c.context.bridge.sha256,
                runtime_identity_file="runtime-identity.json",
                process_identity_file="process-lifecycle.json",
                connection_identity_file="admin-auth-evidence.json",
            )
            (attempt / "structural-canonical.json").write_bytes(c.observation.to_bytes())
            write_json(
                attempt / "structural-digest.json",
                dict(sha256=c.observation.structural_world_digest),
            )
    write_json(attempt / "structural-observation.json", value)


async def execute_structural_attempt(prepared, backend):
    from .preflight import preflight_prepared

    attempt = prepared.directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY)
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if (
            metadata.get("mode") != "structural-world"
            or metadata.get("proof_model") != STRUCTURAL_MODEL
        ):
            raise ValueError("Dedicated frozen structural preparation required")
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
    runner = StructuralProductionRunner(prepared, backend)
    result: dict = dict(
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        reconnects=0,
        error=None,
        proof_kind="structural-world",
        freeze_revision=metadata["prelaunch_revision"],
        attempt_id=metadata["attempt_id"],
        preparation=str(prepared.directory),
    )
    cleanup = {}
    try:
        for path in prepared.directory.iterdir():
            if path.is_file() and path.name != "artifact-manifest.sha256":
                shutil.copyfile(path, attempt / path.name)
        reservation.close()
        verify_freeze(frozen)
        runner.launch_boundary()
        await backend.launch(prepared)
        runner.lifecycle.advance(StructuralProofState.LAUNCHED)
        gates = Gates()
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        if (
            not auth["auth"].get("encrypted")
            or auth["auth"].get("method") != "X25519_AuthorizedKey"
            or auth["protocol"].get("version") != 3
            or auth["welcome"] != asdict(backend.welcome)
        ):
            raise ValueError("Secure encrypted Protocol 3/WELCOME required")
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        runner.lifecycle.advance(StructuralProofState.ADMIN_ACTIVE)
        await backend.setup(prepared)
        observation = await runner.collect()
        if not observation.complete or not observation.structural_world_digest:
            raise ValueError("Complete structural observation required")
        await backend.secure_connection.require_quiescent()
        if backend.accounting.query_operations != observation.protocol_operations:
            raise ValueError("Secure accounting/component operations disagree")
        backend.health()
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        reservation.close()

        def capture(action):
            try:
                return action()
            except BaseException as error:
                result["error"] = result["error"] or f"Finalization failure: {error}"
                return None

        try:
            cleanup = await backend.cleanup(prepared)
            if (
                not cleanup.get("reaped")
                or cleanup.get("remaining_processes")
                or cleanup.get("cleanup_error")
                or not cleanup.get("graceful_attempted")
                or cleanup.get("returncode") != 0
            ):
                raise ValueError("Clean native shutdown/reap not proved")
        except BaseException as error:
            result["error"] = result["error"] or str(error)
        finally:
            capture(lambda: prepared.key_path.unlink(missing_ok=True))

        def endpoints_closed():
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup, reservation))
            return True

        cleanup["sockets_closed"] = bool(capture(endpoints_closed))
        integrity = capture(
            lambda: (
                verify_freeze(frozen),
                validate_protection(
                    protection_base(PROJECT, prepared.directory.parent),
                    json.loads((prepared.directory / "historical-integrity.json").read_text()),
                ),
                True,
            )[-1]
        )
        if not integrity or not cleanup["sockets_closed"]:
            result["error"] = (
                result["error"] or "Post-run source/historical/endpoint integrity failure"
            )
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():

                def sanitized_log(source=source, name=name):
                    raw = source.read_bytes()
                    clean = raw.replace(secret.hex().encode(), b"<REDACTED>").replace(
                        secret, b"<REDACTED>"
                    )
                    if clean != raw:
                        result["error"] = (
                            result["error"] or "Private credential appeared in runtime log"
                        )
                    (attempt / name).write_bytes(clean)

                capture(sanitized_log)
        result.update(
            launches=backend.launches,
            connections=int(backend.session is not None),
            requests_sent=sum(
                row["delivery"] == "SENT"
                for row in getattr(backend.structural_session, "transactions", ())
            ),
            requests_attempted=len(getattr(backend.structural_session, "transactions", ())),
            ambiguous_requests=sum(
                row["delivery"] == "AMBIGUOUS"
                for row in getattr(backend.structural_session, "transactions", ())
            ),
            source_integrity=bool(integrity),
            accounting=backend.accounting.snapshot(),
        )
        if backend.accounting.failed:
            result["error"] = result["error"] or "Native frame budget failed"
        try:
            from .ownership import finalize_cleanup

            finalize_cleanup(prepared, frozen, cleanup)
            integrity = True
            result["source_integrity"] = True
        except Exception as error:
            integrity = False
            result["source_integrity"] = False
            result["error"] = result["error"] or str(error)
        successful = (
            result["error"] is None
            and result["launches"] == result["connections"] == 1
            and 1 <= result["requests_sent"] <= 96
        )
        capture(
            lambda: write_json(
                attempt / "admin-frame-accounting.json", backend.accounting.snapshot()
            )
        )
        capture(lambda: write_json(attempt / "process-lifecycle.json", cleanup))
        capture(
            lambda: write_json(attempt / "source-freeze-post.json", dict(unchanged=bool(integrity)))
        )
        redacted = capture(
            lambda: (
                not any(
                    secret in p.read_bytes() or secret.hex().encode() in p.read_bytes()
                    for p in attempt.iterdir()
                    if p.is_file()
                )
            )
        )
        if not redacted:
            result["error"] = result["error"] or "Private credential retained in public evidence"
        successful = successful and result["error"] is None
        capture(lambda: retain_structural(attempt, runner, backend, successful))
        if result["error"] is not None:
            for name in ("structural-session.json", "structural-observation.json"):
                path = attempt / name
                value = json.loads(path.read_text()) if path.exists() else {}
                value["complete"] = False
                value["failure"] = str(result["error"])
                if name == "structural-session.json":
                    value["events"] = [
                        event
                        for event in value.get("events", [])
                        if event != "STRUCTURAL_WORLD_SESSION_COMPLETED"
                    ]
                    if "STRUCTURAL_WORLD_SESSION_FAILED" not in value["events"]:
                        value["events"].append("STRUCTURAL_WORLD_SESSION_FAILED")
                else:
                    value.pop("structural_world_digest", None)
                path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
            for name in ("structural-digest.json", "structural-canonical.json"):
                (attempt / name).unlink(missing_ok=True)
        if result["error"] is None and successful:
            runner.lifecycle.advance(StructuralProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            runner.lifecycle.fail()
        result["states"] = [s.name for s in runner.lifecycle.states]
        write_json(attempt / "proof-evidence.json", result)
        (attempt / "final-report.md").write_text(
            f"# {result['status']}\n\nSame-run structural observation; "
            f"no independent semantic sources.\nError: {result['error']}\n"
        )
        retain_attempt_identity(attempt, metadata, result)
        (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result
