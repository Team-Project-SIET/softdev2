"""One owned runtime/secure connection; bounded cursor requests without retry."""

import asyncio
import hashlib
import time

from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.cargo_page import CargoPageReceipt, CargoPageResponse
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
)

from .cargo_page_evidence import parse_page_proof_evidence
from .cargo_page_native import CargoPageNativeBackend
from .catalog_contract import CATALOG_BUDGET, CATALOG_FIRST_REQUEST, catalog_request


class CatalogRecordedSession(GameScriptSession):
    def __init__(self, session):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.decoder = AdminFrameDecoder()
        self.pages: list[dict] = []
        self.after_id = None
        self.terminal = False
        self.operations = 0

    def count(self):
        self.operations += 1
        if self.operations > CATALOG_BUDGET.max_operations:
            raise ValueError("Catalog Admin frame budget exhausted")

    async def send(self, *frames):
        for frame in frames:
            self.count()
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.terminal or (
                    self.pages and self.pages[-1]["events"][-1] != "CARGO_PAGE_VALIDATED"
                ):
                    raise ValueError("No extra/in-flight catalog request or retry")
                request = catalog_request(len(self.pages) + 1, self.after_id)
                if decode_gamescript(frame[3:]) != request.to_bytes():
                    raise ValueError("Frozen catalog request sequence required")
                self.pages.append(
                    {
                        "request": request.to_bytes(),
                        "response": None,
                        "receipt": None,
                        "events": ["CARGO_PAGE_REQUEST_SENT"],
                    }
                )
        await self.session.send(*frames)

    async def receive(self, size=4096):
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self.count()
            if kind == SERVER_GAMESCRIPT:
                if not self.pages or self.pages[-1]["response"] is not None:
                    raise ValueError("Duplicate/unrequested catalog response")
                page = self.pages[-1]
                page["response"] = body[:-1] if body.endswith(b"\0") else body
                page["events"].append("CARGO_PAGE_RESPONSE_RECEIVED")
                response = decode_gamescript(body)
                page["receipt"] = CargoPageReceipt.correlate_transport(page["request"], response)
                page["events"].append("TRANSPORT_RECEIPT_CREATED")
                parsed = CargoPageResponse.parse(response)
                self.after_id = parsed.next_after_id
                self.terminal = not parsed.has_more
        return raw

    async def close(self, *, quit=False):
        await self.session.close(quit=quit)

    def validated(self, exchange):
        page = self.pages[-1]
        if (
            page["request"] != exchange.request_payload
            or page["response"] != exchange.response_payload
            or page["receipt"] != exchange.receipt
        ):
            raise ValueError("Catalog recorded transaction mismatch")
        page["events"].append("CARGO_PAGE_VALIDATED")

    def snapshot(self) -> list[dict]:
        return [
            dict(
                request_id=catalog_request(i, None).request_id,
                ordered_sequence=p["events"],
                request_sha256=hashlib.sha256(p["request"]).hexdigest(),
                response_sha256=None
                if p["response"] is None
                else hashlib.sha256(p["response"]).hexdigest(),
            )
            for i, p in enumerate(self.pages, 1)
        ]


class CatalogNativeBackend(CargoPageNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.catalog_session: CatalogRecordedSession | None = None

    def configure_transport(self, prepared, protocol):
        if prepared.request != CATALOG_FIRST_REQUEST or self.session is None:
            raise ValueError("Frozen catalog preparation required")
        self.catalog_session = CatalogRecordedSession(self.session)
        self.transport = CatalogProofTransport(self.catalog_session, protocol)

    async def wait_catalog_startup(self, prepared):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            raw = prepared.spec.stderr_path.read_bytes()
            evidence = parse_page_proof_evidence(raw, CATALOG_FIRST_REQUEST.request_id)
            if evidence.ordered_sequence == ("BRIDGE_STARTED",):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit catalog startup deadline")
            await asyncio.sleep(0.01)

    async def catalog_evidence(self, prepared, request, exchange):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            page = parse_cargo_page_evidence(
                prepared.spec.stderr_path.read_bytes(), request.request_id
            )
            if len(page.ordered_sequence) == 4:
                page.require_complete(request, exchange.response)
                assert self.catalog_session is not None
                self.catalog_session.validated(exchange)
                return page
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit per-page catalog liveness deadline")
            await asyncio.sleep(0.01)

    def catalog_network_evidence(self):
        return [] if self.catalog_session is None else self.catalog_session.snapshot()

    async def cargo_page(self, request):
        raise ValueError("Catalog runner uses bounded session only")


class CatalogProofTransport(GameScriptTransport):
    async def cargo_page(self, request, *, timeout=15, operation_budget=None):
        return await super().cargo_page(
            request,
            timeout=timeout,
            operation_budget=min(16, 512 if operation_budget is None else operation_budget),
        )
