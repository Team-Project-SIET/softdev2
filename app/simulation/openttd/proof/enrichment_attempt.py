"""One owned real proof, two phases, retained partial evidence and bounded cleanup."""

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_cargo import CARGO_NETWORK_SEQUENCE, IndustryCargoRequest
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
from app.simulation.openttd.industry_enrichment import IndustryEnrichmentSession
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.industry_page import IndustryPageExchange, IndustryPageRequest
from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

from .attempt import Gate, Gates
from .enrichment_contract import (
    ENRICHMENT_ATTEMPT_DIRECTORY,
    ENRICHMENT_FIRST_REQUEST,
    ENRICHMENT_MODEL,
)
from .enrichment_lineage import retain_attempt_identity
from .harness import PROJECT, EndpointReservation, manifest, sha256, verify_freeze, write_json
from .historical_protection import protection_base, validate_protection
from .industry_contract import INDUSTRY_NETWORK_CHAIN
from .inventory_attempt import json_lines
from .preflight import preflight_prepared
from .world_attempt import record_prelaunch_failure


class EnrichmentProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    ENRICHMENT_SESSION_STARTED = auto()
    INVENTORY_COMPLETED = auto()
    CAPABILITY_PHASE_STARTED = auto()
    CAPABILITY_COMPLETED = auto()
    ENRICHMENT_ASSEMBLED = auto()
    ENRICHMENT_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class EnrichmentLifecycle:
    states: list[EnrichmentProofState] = field(
        default_factory=lambda: [EnrichmentProofState.PREPARED]
    )

    def advance(self, state):
        if (
            state is EnrichmentProofState.FAILED
            or state is not list(EnrichmentProofState)[len(self.states)]
        ):
            raise ValueError("Invalid enrichment lifecycle transition")
        self.states.append(state)

    def fail(self):
        if self.states[-1] is not EnrichmentProofState.FAILED:
            self.states.append(EnrichmentProofState.FAILED)


def retain_transactions(attempt, prepared, session, backend, complete):
    raw = prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
    (attempt / "gamescript-supporting.log").write_bytes(raw)
    inventory = () if session is None else session.inventory_session.page_exchanges
    cargo = (
        ()
        if session is None or session.capability_session is None
        else session.capability_session.evidence.exchanges
    )
    network_page = backend.inventory_network_evidence()
    network_cargo = backend.capability_network_evidence()
    native_all = []
    request_ids = []
    ledger = getattr(backend, "inventory_session", None)
    for kind, exchanges, network, chain in (
        ("page", inventory, network_page, INDUSTRY_NETWORK_CHAIN),
        ("capability", cargo, network_cargo, CARGO_NETWORK_SEQUENCE),
    ):
        observed = getattr(ledger, "pages" if kind == "page" else "cargos", [])
        rows: list[dict[str, Any]] = []
        for i, item in enumerate(observed):
            rows.append(
                dict(
                    request=json.loads(item["request"]),
                    response=None
                    if item["response"] is None
                    else item["response"].decode("utf-8", errors="replace"),
                    receipt=None if item["receipt"] is None else asdict(item["receipt"]),
                )
            )
        if not observed:
            rows = [
                dict(
                    request=json.loads(e.request_payload),
                    response=e.response_payload.decode(),
                    receipt=asdict(e.receipt),
                )
                for e in exchanges
            ]
        json_lines(
            attempt / ("page-requests.jsonl" if kind == "page" else "capability-requests.jsonl"),
            (r["request"] for r in rows),
        )
        json_lines(
            attempt / ("page-responses.jsonl" if kind == "page" else "capability-responses.jsonl"),
            (
                dict(request_id=r["request"]["request_id"], raw_payload=r["response"])
                for r in rows
                if r["response"] is not None
            ),
        )
        json_lines(
            attempt / ("page-receipts.jsonl" if kind == "page" else "capability-receipts.jsonl"),
            (r["receipt"] for r in rows if r["receipt"] is not None),
        )
        json_lines(
            attempt
            / ("page-verifications.jsonl" if kind == "page" else "capability-verifications.jsonl"),
            network,
        )
        natives = []
        for exchange in exchanges:
            request_id = exchange.receipt.request_id
            request_ids.append(request_id)
            try:
                native = (
                    parse_industry_page_evidence(raw, request_id)
                    if kind == "page"
                    else parse_industry_cargo_evidence(raw, request_id)
                )
            except ValueError as error:
                if complete:
                    raise
                natives.append(dict(request_id=request_id, verified=False, error=str(error)))
                continue
            value = asdict(native)
            value.pop("raw_log")
            value["response_digest"] = exchange.receipt.response_payload_sha256
            natives.append(value)
            native_all.append((kind, native))
            if complete:
                if isinstance(exchange, IndustryPageExchange):
                    parse_industry_page_evidence(raw, request_id).require_complete(
                        IndustryPageRequest.parse(exchange.request_payload), exchange.response
                    )
                else:
                    parse_industry_cargo_evidence(raw, request_id).require_complete(
                        IndustryCargoRequest.parse(exchange.request_payload), exchange.response
                    )
        json_lines(
            attempt
            / (
                "gamescript-page-evidence.jsonl"
                if kind == "page"
                else "gamescript-capability-evidence.jsonl"
            ),
            natives,
        )
        if complete:
            if len(network) != len(exchanges):
                raise ValueError("network transaction count mismatch")
            for exchange, event in zip(exchanges, network, strict=True):
                if (
                    tuple(event["ordered_sequence"]) != chain
                    or event["request_id"] != exchange.receipt.request_id
                    or event["request_sha256"] != exchange.receipt.request_payload_sha256
                    or event["response_sha256"] != exchange.receipt.response_payload_sha256
                ):
                    raise ValueError("ordered/digest-bound per-request network evidence mismatch")
    if complete:
        if raw.count(b"BRIDGE_STARTED protocol=1 api=15") != 1:
            raise ValueError("startup count mismatch")
        ids = set(re.findall(rb"(?:BRIDGE_|INDUSTRY_)\w+ request_id=([^\s]+)", raw))
        if ids != {i.encode() for i in request_ids}:
            raise ValueError("unrelated/missing GameScript transaction")
        pages = [n for k, n in native_all if k == "page"]
        cargos = [n for k, n in native_all if k == "capability"]
        if cargos and pages[-1].line_numbers[-1] >= cargos[0].line_numbers[0]:
            raise ValueError("capability evidence before inventory completion")


async def execute_enrichment_attempt(prepared, backend):
    attempt = prepared.directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY)
    if attempt.exists():
        raise ValueError("Enrichment attempt already claimed or failed; no retry")
    try:
        m = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if (
            m["mode"] != "industry-enrichment"
            or m["proof_model"] != ENRICHMENT_MODEL
            or prepared.request != ENRICHMENT_FIRST_REQUEST
        ):
            raise ValueError("Dedicated frozen enrichment preparation required")
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
    lifecycle = EnrichmentLifecycle()
    gates = Gates()
    session = observation = None
    cleanup = {}
    result = dict(
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        reconnects=0,
        error=None,
        proof_model=ENRICHMENT_MODEL,
        preparation=str(prepared.directory),
        attempt_id=m["attempt_id"],
        freeze_revision=m["prelaunch_revision"],
    )

    def capture(action):
        try:
            return action()
        except BaseException as error:
            result["error"] = result["error"] or str(error)
            return None

    try:
        for name in (
            "source-freeze.json",
            "attempt-lineage.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "source-authority.json",
            "enrichment-contract.json",
            "checkpoint.json",
            "historical-integrity.json",
            "world-support.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        reservation.close()
        verify_freeze(frozen)
        await backend.launch(prepared)
        lifecycle.advance(EnrichmentProofState.LAUNCHED)
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
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
        lifecycle.advance(EnrichmentProofState.ADMIN_ACTIVE)
        await backend.wait_inventory_startup(prepared)
        bridge_data = json.loads((attempt / "bridge-package-identity.json").read_text())
        bridge = BridgePackage(
            prepared.spec.workspace.game / "NoMutationBridge", bridge_data["sha256"]
        )
        world = IndustryInventoryWorld.from_welcome(
            "enrichment-runtime-world", prepared.spec.identity, backend.welcome
        )
        session = IndustryEnrichmentSession(world, bridge)
        lifecycle.advance(EnrichmentProofState.ENRICHMENT_SESSION_STARTED)
        connection = backend.session

        def connection_check():
            if backend.session is not connection:
                raise ValueError("connection changed; no resume")

        async def page_evidence(request, exchange):
            connection_check()
            native = await backend.inventory_evidence(prepared, request, exchange)
            connection_check()
            return native

        def begin(inventory):
            connection_check()
            lifecycle.advance(EnrichmentProofState.INVENTORY_COMPLETED)
            backend.begin_capability(inventory)
            lifecycle.advance(EnrichmentProofState.CAPABILITY_PHASE_STARTED)

        async def cargo_evidence(request, exchange):
            connection_check()
            native = await backend.capability_evidence(prepared, request, exchange)
            connection_check()
            return native

        observation = await session.collect(backend.transport, page_evidence, cargo_evidence, begin)
        lifecycle.advance(EnrichmentProofState.CAPABILITY_COMPLETED)
        lifecycle.advance(EnrichmentProofState.ENRICHMENT_ASSEMBLED)
        retain_transactions(attempt, prepared, session, backend, True)
        lifecycle.advance(EnrichmentProofState.ENRICHMENT_VERIFIED)
        backend.health()
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()
        result["launches"] = backend.launches
        result["connections"] = int(
            getattr(backend, "_connection_claimed", False)
            or getattr(backend, "session", None) is not None
        )
        result["requests_sent"] = (
            capture(
                lambda: (
                    len(backend.inventory_network_evidence())
                    + len(backend.capability_network_evidence())
                )
            )
            or 0
        )
        if result["error"] or not (attempt / "gamescript-supporting.log").exists():
            capture(lambda: retain_transactions(attempt, prepared, session, backend, False))
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
        capture(lambda: prepared.key_path.unlink(missing_ok=True))

        def close_endpoints():
            ports = EndpointReservation.allocate(*prepared.endpoints)
            ports.close()
            return True

        cleanup["sockets_closed"] = bool(capture(close_endpoints))
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
        if capture(
            lambda: any(
                secret in p.read_bytes() or secret.hex().encode() in p.read_bytes()
                for p in attempt.iterdir()
                if p.is_file()
            )
        ):
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
            and observation is not None
            and result["launches"] == result["connections"] == 1
            and result["requests_sent"] == observation.total_requests
        )
        if success:
            lifecycle.advance(EnrichmentProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.fail()
        inventory = None if session is None else session.inventory
        capability = None if observation is None else observation.capability
        if inventory is None:
            partial_pages = () if session is None else session.inventory_session.page_exchanges
            capture(
                lambda: write_json(
                    attempt / "inventory-observation.json",
                    dict(
                        complete=False,
                        records=[asdict(r) for e in partial_pages for r in e.response.industries],
                        page_count=len(partial_pages),
                        inventory_digest=None,
                        claim="received partial records; final cursor chain not established",
                    ),
                )
            )
        if inventory is not None:
            capture(
                lambda: write_json(
                    attempt / "inventory-observation.json",
                    dict(
                        complete=True,
                        records=[asdict(r) for r in inventory.records],
                        page_count=inventory.page_count,
                        inventory_digest=inventory.inventory_digest,
                        map_width=world.map_width,
                        map_height=world.map_height,
                        runtime_identity=json.loads(
                            (attempt / "runtime-identity.json").read_text()
                        ),
                    ),
                )
            )
            capture(
                lambda: write_json(
                    attempt / "inventory-digest.json", dict(sha256=inventory.inventory_digest)
                )
            )
        cargos = (
            ()
            if session is None or session.capability_session is None
            else session.capability_session.evidence.exchanges
        )
        capture(
            lambda: write_json(
                attempt / "capability-observation.json",
                dict(
                    complete=capability is not None,
                    source_inventory_digest=None
                    if inventory is None
                    else inventory.inventory_digest,
                    records=[asdict(e.response.capability) for e in cargos],
                    result_count=len(cargos),
                ),
            )
        )
        if capability is not None:
            capture(
                lambda: write_json(
                    attempt / "capability-digest.json", dict(sha256=capability.capability_digest)
                )
            )
        value = dict(
            complete=success,
            source_inventory_digest=None if inventory is None else inventory.inventory_digest,
            capability_digest=None if capability is None else capability.capability_digest,
            enriched_digest=None if observation is None else observation.enriched_digest,
            industry_count=0 if inventory is None else len(inventory.records),
            capability_result_count=len(cargos),
            total_response_bytes=None if observation is None else observation.total_response_bytes,
            admin_frames=None if observation is None else observation.protocol_operations,
            ordered_industry_ids=[] if inventory is None else [r.id for r in inventory.records],
            runtime_identity=capture(
                lambda: json.loads((attempt / "runtime-identity.json").read_text())
            ),
            bridge_identity=capture(
                lambda: json.loads((attempt / "bridge-package-identity.json").read_text())
            ),
            independent_inventory_source=None,
            independent_capability_source=None,
            production_history="NOT INCLUDED",
            p08_completion=False,
        )
        capture(lambda: write_json(attempt / "enriched-observation.json", value))
        capture(
            lambda: write_json(
                attempt / "enrichment-session.json",
                dict(
                    session_id=m["session_id"],
                    complete=success,
                    events=[]
                    if session is None
                    else (
                        session.events
                        if success
                        else [e for e in session.events if e != "ENRICHMENT_SESSION_COMPLETED"]
                        + ["ENRICHMENT_SESSION_FAILED"]
                    ),
                    failure=result["error"],
                ),
            )
        )
        if session is not None:
            capture(
                lambda: write_json(
                    attempt / "inventory-session.json", asdict(session.inventory_session.evidence)
                )
            )
        result.update(
            states=[s.name for s in lifecycle.states],
            source_integrity=integrity,
            verification=value,
        )
        capture(lambda: write_json(attempt / "process-lifecycle.json", cleanup))
        capture(
            lambda: write_json(
                attempt / "source-freeze-post.json", dict(unchanged=integrity, hashes=post)
            )
        )
        capture(lambda: write_json(attempt / "proof-evidence.json", result))
        capture(
            lambda: (attempt / "final-report.md").write_text(
                f"# {result['status']}\n\nSame-run inventory and structural "
                f"capability; no independent second source or production "
                f"history.\nError: {result['error']}.\n"
            )
        )
        capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
        if result["error"] is not None:
            result["status"] = backend.kind + "_FAILED"
            lifecycle.fail()
            result["states"] = [s.name for s in lifecycle.states]
            value["complete"] = False
            capture(
                lambda: (attempt / "proof-evidence.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "enriched-observation.json").write_text(
                    json.dumps(value, sort_keys=True, indent=2) + "\n"
                )
            )
            failed_session = dict(
                session_id=m["session_id"],
                complete=False,
                events=[]
                if session is None
                else [e for e in session.events if e != "ENRICHMENT_SESSION_COMPLETED"]
                + ["ENRICHMENT_SESSION_FAILED"],
                failure=result["error"],
            )
            capture(
                lambda: (attempt / "enrichment-session.json").write_text(
                    json.dumps(failed_session, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "final-report.md").write_text(
                    f"# {result['status']}\n\nError: {result['error']}.\n"
                    "No retry or reconnect performed.\n"
                )
            )
            capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
        capture(lambda: retain_attempt_identity(attempt, m, result))
        if result["error"] is not None and result["status"] == backend.kind + "_SUCCESS":
            result["status"] = backend.kind + "_FAILED"
            lifecycle.fail()
            result["states"] = [s.name for s in lifecycle.states]
            value["complete"] = False
            capture(
                lambda: (attempt / "proof-evidence.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "enriched-observation.json").write_text(
                    json.dumps(value, sort_keys=True, indent=2) + "\n"
                )
            )
            failed_session = dict(
                session_id=m["session_id"],
                complete=False,
                failure=result["error"],
                events=[]
                if session is None
                else [e for e in session.events if e != "ENRICHMENT_SESSION_COMPLETED"]
                + ["ENRICHMENT_SESSION_FAILED"],
            )
            capture(
                lambda: (attempt / "enrichment-session.json").write_text(
                    json.dumps(failed_session, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "final-report.md").write_text(
                    f"# {result['status']}\n\nError: {result['error']}.\n"
                )
            )
        capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
    return result
