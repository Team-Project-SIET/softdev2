"""Owned structural transport; the secure session supplies all frame accounting."""

import asyncio
import time

from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.cargo_catalog import catalog_request_id
from app.simulation.openttd.cargo_page import CargoPageReceipt, CargoPageRequest
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
)
from app.simulation.openttd.industry_capability import capability_request_id
from app.simulation.openttd.industry_cargo import IndustryCargoReceipt, IndustryCargoRequest
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld, inventory_request_id
from app.simulation.openttd.industry_page import IndustryPageReceipt, IndustryPageRequest
from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
from app.simulation.openttd.secure_admin import SecureAdminSession
from app.simulation.openttd.structural_world import StructuralWorldContext
from app.simulation.openttd.structural_world_session import STRUCTURAL_WORLD_SESSION_ID

from .cargo_page_native import CargoPageNativeBackend
from .gamescript_evidence import parse_gamescript_evidence
from .industry_native import owned_admin_listener
from .native import NativeBackend
from .structural_contract import StructuralFrameBudget, StructuralFrameBudgetExceeded


class StructuralRecordedSession(GameScriptSession):
    """Transaction ledger only; counting belongs exclusively to SecureAdminSession."""

    def __init__(self, session):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.decoder = AdminFrameDecoder()
        self.transactions: list[dict] = []
        self.expected = None

    def expect(self, request):
        if self.expected is not None or (
            self.transactions and not self.transactions[-1]["validated"]
        ):
            raise ValueError("Unvalidated/in-flight structural transaction; no retry")
        self.expected = request

    async def send(self, *frames):
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                q = self.expected
                if q is None or decode_gamescript(frame[3:]) != q.to_bytes():
                    raise ValueError("Only one expected structural query may be sent")
                kind = (
                    "INDUSTRY_PAGE"
                    if isinstance(q, IndustryPageRequest)
                    else "INDUSTRY_CARGO"
                    if isinstance(q, IndustryCargoRequest)
                    else "CARGO_PAGE"
                )
                self.transactions.append(
                    dict(
                        request=q,
                        request_payload=q.to_bytes(),
                        response_payload=None,
                        receipt=None,
                        validated=False,
                        events=[kind + "_REQUEST_SEND_ATTEMPTED"],
                        delivery="ATTEMPTED",
                        kind=kind,
                    )
                )
                self.expected = None
        try:
            await self.session.send(*frames)
        except BaseException as error:
            if any(f[2] == ADMIN_GAMESCRIPT for f in frames):
                self.transactions[-1]["delivery"] = (
                    "NOT_SENT" if isinstance(error, StructuralFrameBudgetExceeded) else "AMBIGUOUS"
                )
            raise
        if any(f[2] == ADMIN_GAMESCRIPT for f in frames):
            row = self.transactions[-1]
            row["delivery"] = "SENT"
            row["events"] = [row["kind"] + "_REQUEST_SENT"]

    async def receive(self, size=4096):
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            if kind == SERVER_GAMESCRIPT:
                if not self.transactions or self.transactions[-1]["response_payload"] is not None:
                    raise ValueError("Duplicate/unrequested structural response")
                row = self.transactions[-1]
                row["response_payload"] = body[:-1] if body.endswith(b"\0") else body
                row["events"].append(row["kind"] + "_RESPONSE_RECEIVED")
                if isinstance(row["request"], IndustryPageRequest):
                    row["receipt"] = IndustryPageReceipt.correlate(
                        row["request_payload"], decode_gamescript(body)
                    )
                elif isinstance(row["request"], IndustryCargoRequest):
                    row["receipt"] = IndustryCargoReceipt.correlate_transport(
                        row["request_payload"], decode_gamescript(body)
                    )
                else:
                    row["receipt"] = CargoPageReceipt.correlate_transport(
                        row["request_payload"], decode_gamescript(body)
                    )
                row["events"].append("TRANSPORT_RECEIPT_CREATED")
        return raw

    def validated(self, exchange):
        row = self.transactions[-1]
        if row["validated"] or (
            row["request_payload"],
            row["response_payload"],
            row["receipt"],
        ) != (exchange.request_payload, exchange.response_payload, exchange.receipt):
            raise ValueError("Structural transaction/receipt mismatch")
        row["events"].append(
            "PAGE_VALIDATED"
            if row["kind"] == "INDUSTRY_PAGE"
            else "CAPABILITY_VALIDATED"
            if row["kind"] == "INDUSTRY_CARGO"
            else "CARGO_PAGE_VALIDATED"
        )
        row["validated"] = True

    async def close(self, *, quit=False):
        await self.session.close(quit=quit)


class StructuralNativeTransport(GameScriptTransport):
    def __init__(self, recorded, protocol, context, backend):
        super().__init__(recorded, protocol)
        self.context, self.backend = context, backend
        self.recorded = recorded

    def expect(self, phase, request):
        backend = self.backend
        backend.health()
        owner = backend.coordinator
        if owner is None or owner.phase != phase or backend.accounting.phase != phase.lower():
            raise ValueError("Structural phase barrier not passed")
        owner.context.require_same_run(self.context)
        if (
            backend.session is not backend.secure_connection
            or self.recorded.session is not backend.secure_connection
            or backend.process is not self.context.process_identity
        ):
            raise ValueError("Structural process/connection replaced; no resume")
        rows = [r for r in self.recorded.transactions if isinstance(r["request"], type(request))]
        session_id = STRUCTURAL_WORLD_SESSION_ID
        if phase == "CAPABILITY":
            if (
                owner.inventory is None
                or not owner.inventory.complete
                or len(rows) >= len(owner.inventory.records)
            ):
                raise ValueError("Exactly one capability per same-run industry")
            id = owner.inventory.records[len(rows)].id
            expected = IndustryCargoRequest(capability_request_id(session_id + "-cap", id), id)
        else:
            after = None if not rows else rows[-1]["exchange"].response.next_after_id
            if rows and not rows[-1]["exchange"].response.has_more:
                raise ValueError("No query after terminating page")
            expected = (
                IndustryPageRequest(
                    inventory_request_id(session_id + "-inv", len(rows) + 1), after, 2
                )
                if phase == "INVENTORY"
                else CargoPageRequest(
                    catalog_request_id(session_id + "-cat", len(rows) + 1), after, 2
                )
            )
        if request != expected:
            raise ValueError("Frozen deterministic same-run query sequence required")
        self.recorded.expect(request)

    async def industry_page(self, request, world, *, timeout=5, operation_budget=None):
        self.expect("INVENTORY", request)
        return await super().industry_page(
            request, world, timeout=timeout, operation_budget=operation_budget
        )

    async def industry_cargo(self, request, *, timeout=5, operation_budget=None):
        self.expect("CAPABILITY", request)
        return await super().industry_cargo(
            request, timeout=timeout, operation_budget=operation_budget
        )

    async def cargo_page(self, request, *, timeout=5, operation_budget=None):
        self.expect("CATALOG", request)
        return await super().cargo_page(request, timeout=timeout, operation_budget=operation_budget)


class StructuralNativeBackend(CargoPageNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.accounting = StructuralFrameBudget()
        self.coordinator = None
        self.secure_connection = None
        self.structural_session = None
        self.query_operation_baseline = 0

    async def authenticate(self, prepared, gates):
        if self._connection_claimed or self.session is not None:
            raise ValueError("One continuous structural Admin connection; no retry")
        deadline = time.monotonic() + 30
        while True:
            self.health()
            assert self.process is not None
            if owned_admin_listener(self.process.pid, prepared.endpoints[1]):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned Admin listener deadline")
            await asyncio.sleep(0.01)
        self._connection_claimed = True
        if self._key is None:
            raise ValueError("Prepared credential missing")
        self.session = await SecureAdminSession.connect_secure(
            "127.0.0.1",
            prepared.endpoints[1],
            5,
            key=self._key,
            frame_observer=self.accounting.observe,
        )
        self.secure_connection = self.session
        return await NativeBackend.authenticate(self, prepared, gates)

    def configure_transport(self, prepared, protocol):
        from .structural_contract import structural_first_request

        if (
            prepared.request != structural_first_request()
            or self.session is None
            or self.accounting.total_frames != 2
        ):
            raise ValueError("Structural secure establishment/frozen request required")
        world = IndustryInventoryWorld.from_welcome(
            STRUCTURAL_WORLD_SESSION_ID, prepared.spec.identity, self.welcome
        )
        import json

        bridge = json.loads((prepared.directory / "bridge-package-identity.json").read_text())
        config = json.loads((prepared.directory / "structural-context.json").read_text())
        self.structural_session = StructuralRecordedSession(self.session)
        context = StructuralWorldContext(
            world,
            BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", bridge["sha256"]),
            config["configuration_digest"],
            self.process,
            self.structural_session,
        )
        self.transport = StructuralNativeTransport(self.structural_session, protocol, context, self)

    async def setup(self, prepared):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            if parse_gamescript_evidence(
                prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
            ).startup_observed:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Structural bridge startup deadline")
            await asyncio.sleep(0.01)
        assert self.secure_connection is not None
        await self.secure_connection.require_quiescent()
        self.accounting.enter("setup")
        assert self.transport is not None
        await self.transport.subscribe(token=0x153, timeout=5)
        await self.secure_connection.require_quiescent()
        if self.accounting.total_frames != 5:
            raise ValueError("Exact establishment/subscription accounting required")

    async def evidence(self, prepared, request, exchange):
        parser = (
            parse_industry_page_evidence
            if isinstance(request, IndustryPageRequest)
            else parse_industry_cargo_evidence
            if isinstance(request, IndustryCargoRequest)
            else parse_cargo_page_evidence
        )
        assert self.secure_connection is not None
        await self.secure_connection.require_quiescent()
        deadline = time.monotonic() + 10
        while True:
            self.health()
            raw = prepared.spec.stderr_path.read_bytes()
            evidence = parser(raw, request.request_id)
            if len(evidence.ordered_sequence) == 4:
                await self.secure_connection.require_quiescent()
                evidence.require_complete(request, exchange.response)
                assert self.structural_session is not None
                self.structural_session.validated(exchange)
                self.structural_session.transactions[-1]["exchange"] = exchange
                self.structural_session.transactions[-1]["gamescript"] = evidence
                actual = self.accounting.query_operations
                if actual - self.query_operation_baseline != exchange.protocol_operations:
                    raise ValueError("Secure stream/query receipt frame accounting mismatch")
                self.query_operation_baseline = actual
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Structural per-request GameScript liveness deadline")
            await asyncio.sleep(0.01)

    async def cleanup(self, prepared):
        result = await super().cleanup(prepared)
        result["admin_frame_accounting"] = self.accounting.snapshot()
        return result
