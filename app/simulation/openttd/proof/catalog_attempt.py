"""Owned one-attempt catalog lifecycle, with independently ordered page evidence."""

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path

from app.simulation.openttd.cargo_catalog import CargoCatalogSession
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence

from .attempt import Gate, Gates
from .cargo_page_contract import PAGE_NETWORK_CHAIN
from .cargo_page_evidence import parse_page_proof_evidence
from .catalog_contract import (
    CATALOG_ATTEMPT_DIRECTORY,
    CATALOG_BUDGET,
    CATALOG_FIRST_REQUEST,
    CATALOG_MODEL,
    CATALOG_PAGE_SIZE,
    CATALOG_SESSION_ID,
    verify_catalog,
)
from .catalog_lineage import retain_attempt_identity
from .endpoints import verify_cleanup_endpoints
from .harness import PROJECT, EndpointReservation, manifest, sha256, verify_freeze, write_json
from .historical_protection import protection_base, validate_protection
from .preflight import preflight_prepared
from .world_attempt import record_prelaunch_failure


class CatalogProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    CATALOG_SESSION_STARTED = auto()
    FINAL_PAGE_VALIDATED = auto()
    CATALOG_ASSEMBLED = auto()
    CATALOG_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class CatalogLifecycle:
    states: list[CatalogProofState] = field(default_factory=lambda: [CatalogProofState.PREPARED])
    page_cycles: list[dict] = field(default_factory=list)

    def advance(self, state: CatalogProofState) -> None:
        if (
            state is CatalogProofState.FAILED
            or state is not list(CatalogProofState)[len(self.states)]
        ):
            raise ValueError("Invalid catalog proof transition")
        self.states.append(state)

    def page(self, request_id: str, response_digest: str) -> None:
        if self.states[-1] is not CatalogProofState.CATALOG_SESSION_STARTED or any(
            p["request_id"] == request_id for p in self.page_cycles
        ):
            raise ValueError("Invalid catalog page lifecycle")
        self.page_cycles.append(
            dict(
                request_id=request_id,
                response_sha256=response_digest,
                ordered_sequence=[
                    "CARGO_PAGE_REQUEST_SENT",
                    "CARGO_PAGE_RESPONSE_RECEIVED",
                    "TRANSPORT_RECEIPT_CREATED",
                    "CARGO_PAGE_VALIDATED",
                ],
            )
        )


def json_lines(path: Path, values) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in values)
    )


def retain_pages(attempt, prepared, session, backend, require_complete) -> list[str]:
    exchanges = () if session is None else session.evidence.exchanges
    observed = getattr(getattr(backend, "catalog_session", None), "pages", [])
    errors: list[str] = []

    def retain(action):
        try:
            action()
        except BaseException as error:
            errors.append(f"Evidence retention failure: {error}")

    receipts = [dict(**asdict(e.receipt), response_semantics_valid=True) for e in exchanges]
    requests = [json.loads(e.request_payload) for e in exchanges]
    responses = [
        dict(request_id=e.response.request_id, raw_json=e.response_payload.decode("ascii"))
        for e in exchanges
    ]
    for page in observed[len(exchanges) :]:
        requests.append(json.loads(page["request"]))
        if page.get("receipt") is not None:
            receipts.append(dict(**asdict(page["receipt"]), response_semantics_valid=False))
        if page["response"] is not None:
            responses.append(dict(raw_hex=page["response"].hex(), validated=False))
    retain(lambda: json_lines(attempt / "page-requests.jsonl", requests))
    retain(lambda: json_lines(attempt / "page-responses.jsonl", responses))
    retain(lambda: json_lines(attempt / "page-receipts.jsonl", receipts))
    raw = prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
    retain(lambda: (attempt / "gamescript-supporting.log").write_bytes(raw))
    native: list[dict] = []
    verifications: list[dict] = []
    for exchange in exchanges:
        from app.simulation.openttd.cargo_page import CargoPageRequest

        value = dict(
            request_id=exchange.response.request_id,
            correlated=False,
            response_sha256=exchange.receipt.response_payload_sha256,
        )
        try:
            page = parse_cargo_page_evidence(raw, exchange.response.request_id)
            value.update(asdict(page))
            value.pop("raw_log")
            page.require_complete(
                CargoPageRequest.parse(exchange.request_payload), exchange.response
            )
            value["correlated"] = True
        except ValueError as error:
            value["error"] = str(error)
        native.append(value)
        verifications.append(
            dict(
                request_id=exchange.response.request_id,
                network_chain=exchange.ordered_sequence,
                response_sha256=exchange.receipt.response_payload_sha256,
                protocol_operations=exchange.protocol_operations,
                record_semantics_valid=True,
                gamescript_correlated=value["correlated"],
                page_valid=value["correlated"],
            )
        )
    retain(lambda: json_lines(attempt / "gamescript-page-evidence.jsonl", native))
    retain(lambda: json_lines(attempt / "page-verifications.jsonl", verifications))
    network = backend.catalog_network_evidence()
    retain(lambda: json_lines(attempt / "network-page-evidence.jsonl", network))
    if require_complete:
        try:
            ids = [e.response.request_id for e in exchanges]
            matches = re.findall(rb"(?:BRIDGE_|CARGO_PAGE_)\w+ request_id=([^\s]+)", raw)
            if any(identity.decode("ascii") not in ids for identity in matches):
                raise ValueError("Unrelated GameScript transaction in catalog proof")
            if raw.count(b"BRIDGE_STARTED protocol=1 api=15") != 1:
                raise ValueError("Duplicate/missing catalog startup")
            first_request_line = min(p["line_numbers"][0] for p in native)
            prefix = b"".join(raw.splitlines(keepends=True)[: first_request_line - 1])
            if parse_page_proof_evidence(
                prefix, CATALOG_FIRST_REQUEST.request_id
            ).ordered_sequence != ("BRIDGE_STARTED",):
                raise ValueError("Missing catalog bridge startup")
            if len(network) != len(exchanges):
                raise ValueError("Catalog network transaction count mismatch")
            for exchange, page in zip(exchanges, network, strict=True):
                if (
                    tuple(page.get("ordered_sequence", ())) != PAGE_NETWORK_CHAIN
                    or page.get("request_id") != exchange.response.request_id
                    or page.get("request_sha256") != exchange.receipt.request_payload_sha256
                    or page.get("response_sha256") != exchange.receipt.response_payload_sha256
                ):
                    raise ValueError(
                        "Catalog independently ordered/digest-bound network chain mismatch"
                    )
            if not all(p["correlated"] for p in native):
                raise ValueError("Catalog native page correlation failure")
        except (ValueError, KeyError, IndexError) as error:
            errors.append(str(error))
    return errors


async def execute_catalog_attempt(prepared, backend) -> dict:
    attempt = prepared.directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
    if attempt.exists():
        raise ValueError("Catalog attempt already claimed; no retry")
    if prepared.directory.with_name(prepared.directory.name + "-gate-failure").exists():
        raise ValueError("Previous catalog prelaunch failure; no retry")
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if (
            metadata.get("mode") != "cargo-catalog"
            or metadata.get("proof_model") != CATALOG_MODEL
            or prepared.request != CATALOG_FIRST_REQUEST
        ):
            raise ValueError("Dedicated frozen catalog preparation required")
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
    lifecycle, gates = CatalogLifecycle(), Gates()
    session = observation = None
    result: dict = dict(
        status=backend.kind + "_FAILED",
        proof_model=CATALOG_MODEL,
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        reconnects=0,
        error=None,
        verification=None,
    )
    cleanup = {}
    try:
        for name in (
            "source-freeze.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "catalog-contract.json",
            "source-authority.json",
            "world-support.json",
            "historical-integrity.json",
            "attempt-lineage.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        reservation.close()
        verify_freeze(frozen)
        await backend.launch(prepared)
        result["launches"] = backend.launches
        lifecycle.advance(CatalogProofState.LAUNCHED)
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        result["connections"] = 1
        if (
            auth["auth"].get("method") != "X25519_AuthorizedKey"
            or not auth["auth"].get("encrypted")
            or auth["protocol"].get("version") != 3
            or auth["welcome"] != asdict(backend.welcome)
        ):
            raise ValueError("Secure encrypted Admin Protocol 3/WELCOME required")
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        lifecycle.advance(CatalogProofState.ADMIN_ACTIVE)
        await backend.wait_catalog_startup(prepared)
        session = CargoCatalogSession(
            CATALOG_SESSION_ID,
            page_size=CATALOG_PAGE_SIZE,
            budget=CATALOG_BUDGET,
            timeout=15,
            runtime_identity=prepared.spec.identity,
        )
        lifecycle.advance(CatalogProofState.CATALOG_SESSION_STARTED)
        connection = backend.session

        async def page_evidence(request, exchange):
            if backend.session is not connection:
                raise ValueError("Catalog connection changed; no resume")
            native = await backend.catalog_evidence(prepared, request, exchange)
            if backend.session is not connection:
                raise ValueError("Catalog connection changed; no resume")
            native.require_complete(request, exchange.response)
            if request.after_id is None and not exchange.response.cargoes:
                raise ValueError("Frozen native first page must be nonempty")
            lifecycle.page(request.request_id, exchange.receipt.response_payload_sha256)
            return native

        observation = await session.collect(backend.transport, page_evidence)
        lifecycle.advance(CatalogProofState.FINAL_PAGE_VALIDATED)
        lifecycle.advance(CatalogProofState.CATALOG_ASSEMBLED)
        result["verification"] = verify_catalog(observation)
        if not result["verification"]["verified"]:
            raise ValueError(result["verification"]["status"])
        lifecycle.advance(CatalogProofState.CATALOG_VERIFIED)
        backend.health()
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()

        def capture(action):
            try:
                return action()
            except BaseException as error:
                result["error"] = result["error"] or f"Finalization failure: {error}"
                return None

        result["launches"] = backend.launches
        result.update(
            preparation=str(prepared.directory),
            freeze_revision=metadata["prelaunch_revision"],
            attempt_id=metadata["attempt_id"],
        )
        result["connections"] = int(getattr(backend, "session", None) is not None)
        network = capture(backend.catalog_network_evidence)
        result["requests_sent"] = 0 if network is None else len(network)
        retained = capture(
            lambda: retain_pages(attempt, prepared, session, backend, result["error"] is None)
        )
        if retained:
            result["error"] = result["error"] or retained[0]
        try:
            cleanup = await backend.cleanup(prepared)
            if (
                not cleanup.get("reaped")
                or cleanup.get("remaining_processes")
                or cleanup.get("cleanup_error")
                or not cleanup.get("graceful_attempted")
                or cleanup.get("returncode") != 0
            ):
                raise ValueError("Clean shutdown/reap not proven")
        except BaseException as error:
            result["error"] = result["error"] or str(error)
        finally:
            capture(lambda: prepared.key_path.unlink(missing_ok=True))

        def closed_endpoints():
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup, reservation))
            return True

        cleanup["sockets_closed"] = bool(capture(closed_endpoints))
        post = capture(lambda: {p: sha256(Path(p)) if Path(p).is_file() else None for p in frozen})
        history = capture(
            lambda: json.loads((prepared.directory / "historical-integrity.json").read_text())
        )
        current = capture(
            lambda: validate_protection(
                protection_base(PROJECT, prepared.directory.parent), history
            )
        )
        integrity = (
            post == frozen
            and history is not None
            and current is not None
            and current == history["unique_count"]
        )
        if not integrity:
            result["error"] = result["error"] or "Source/historical integrity mismatch"
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():
                capture(lambda source=source, name=name: shutil.copyfile(source, attempt / name))
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
            result["error"] = result["error"] or "Credential redaction failure"
        try:
            from .ownership import finalize_cleanup

            finalize_cleanup(prepared, frozen, cleanup)
            integrity = True
            result["source_integrity"] = True
        except Exception as error:
            integrity = False
            result["source_integrity"] = False
            result["error"] = result["error"] or str(error)
        success = (
            result["error"] is None
            and result["launches"] == result["connections"] == 1
            and 1 <= result["requests_sent"] <= CATALOG_BUDGET.max_pages
        )
        if success:
            lifecycle.advance(CatalogProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.states.append(CatalogProofState.FAILED)
        result.update(
            states=[s.name for s in lifecycle.states],
            page_cycles=lifecycle.page_cycles,
            source_integrity=integrity,
        )
        exchanges = () if session is None else session.evidence.exchanges
        value = dict(
            complete=success,
            cursor_chain_complete=observation is not None,
            session_id=CATALOG_SESSION_ID,
            records=[asdict(r) for e in exchanges for r in e.response.cargoes],
            page_count=len(exchanges),
            cargo_count=sum(len(e.response.cargoes) for e in exchanges),
            bridge_identity=capture(
                lambda: json.loads((attempt / "bridge-package-identity.json").read_text())
            ),
        )
        if observation is not None:
            value.update(
                first_cargo_id=observation.first_cargo_id,
                last_cargo_id=observation.last_cargo_id,
                total_response_bytes=observation.total_response_bytes,
                runtime_identity=capture(
                    lambda: json.loads((attempt / "runtime-identity.json").read_text())
                ),
                catalog_sha256=observation.catalog_digest,
            )
            capture(lambda: (attempt / "catalog-records.json").write_bytes(observation.to_bytes()))
            capture(
                lambda: write_json(
                    attempt / "catalog-digest.json",
                    dict(
                        sha256=observation.catalog_digest,
                        canonical_file="catalog-records.json",
                        verified=success,
                    ),
                )
            )
        capture(lambda: write_json(attempt / "catalog-observation.json", value))
        evidence: dict = (
            {}
            if session is None
            else dict(
                session_id=session.session_id,
                events=list(session.evidence.events),
                complete=session.evidence.complete,
                catalog_digest=session.evidence.catalog_digest,
                failure=session.evidence.failure,
            )
        )
        evidence["complete"] = success
        events = evidence.get("events", ())
        if success:
            evidence["events"] = [*events[:-1], "CARGO_CATALOG_VERIFIED", events[-1]]
        else:
            evidence["events"] = [e for e in events if e != "CARGO_CATALOG_SESSION_COMPLETED"]
            if not evidence["events"] or evidence["events"][-1] != "CARGO_CATALOG_SESSION_FAILED":
                evidence["events"].append("CARGO_CATALOG_SESSION_FAILED")
            evidence["failure"] = result["error"]
        capture(lambda: write_json(attempt / "catalog-session.json", evidence))
        # Artifact failures after otherwise valid cleanup still fail the formal proof.
        if result["error"] is not None:
            result["status"] = backend.kind + "_FAILED"
            if lifecycle.states[-1] is not CatalogProofState.FAILED:
                lifecycle.states.append(CatalogProofState.FAILED)
            result["states"] = [s.name for s in lifecycle.states]
        capture(lambda: write_json(attempt / "process-lifecycle.json", cleanup))
        capture(
            lambda: write_json(
                attempt / "source-freeze-post.json", dict(unchanged=integrity, hashes=post)
            )
        )
        capture(lambda: write_json(attempt / "proof-evidence.json", result))
        capture(
            lambda: (attempt / "final-report.md").write_text(
                f"# {result['status']}\n\nRead-only bounded cursor-chain traversal; "
                "no independent cargo catalog.\n"
                f"Launches: {result['launches']}; connections: {result['connections']}; "
                f"requests: {result['requests_sent']}; retries: 0.\nError: {result['error']}.\n"
            )
        )
        capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
        if result["error"] is not None:
            result["status"] = backend.kind + "_FAILED"
            if result["states"][-1] != "FAILED":
                result["states"].append("FAILED")
            value["complete"] = False
            evidence["complete"] = False
            evidence["failure"] = result["error"]
            evidence["events"] = [
                e
                for e in evidence["events"]
                if e not in ("CARGO_CATALOG_SESSION_COMPLETED", "CARGO_CATALOG_VERIFIED")
            ]
            if not evidence["events"] or evidence["events"][-1] != "CARGO_CATALOG_SESSION_FAILED":
                evidence["events"].append("CARGO_CATALOG_SESSION_FAILED")
            if result["verification"] is not None:
                result["verification"]["verified"] = False
                result["verification"]["failure"] = result["error"]
                result["verification"]["status"] = "FAILED"
            if observation is not None:
                capture(
                    lambda: (attempt / "catalog-digest.json").write_text(
                        json.dumps(
                            dict(
                                sha256=observation.catalog_digest,
                                canonical_file="catalog-records.json",
                                verified=False,
                            ),
                            sort_keys=True,
                            indent=2,
                        )
                        + "\n"
                    )
                )
            # Correct only this new attempt's public classifications after a late I/O failure.
            for name, content in (
                ("catalog-observation.json", value),
                ("catalog-session.json", evidence),
                ("proof-evidence.json", result),
            ):
                capture(
                    lambda name=name, content=content: (attempt / name).write_text(
                        json.dumps(content, sort_keys=True, indent=2) + "\n"
                    )
                )
            capture(
                lambda: (attempt / "final-report.md").write_text(
                    f"# {result['status']}\n\nError: {result['error']}. No retry.\n"
                )
            )
            capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
    retain_attempt_identity(attempt, metadata, result)
    (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result
