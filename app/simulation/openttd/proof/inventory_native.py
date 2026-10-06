"""One owned runtime/secure connection; bounded cursor requests without retry."""

import asyncio
import hashlib
import time

from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
)
from app.simulation.openttd.industry_inventory import IndustryInventoryBudget
from app.simulation.openttd.industry_page import IndustryPageReceipt, IndustryPageResponse
from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence

from .industry_evidence import parse_industry_proof_evidence
from .industry_native import IndustryNativeBackend
from .inventory_contract import INVENTORY_FIRST_REQUEST, inventory_request


class InventoryRecordedSession(GameScriptSession):
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
        if self.operations > IndustryInventoryBudget().max_operations:
            raise ValueError("Inventory Admin frame budget exhausted")

    async def send(self, *frames):
        for frame in frames:
            self.count()
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.terminal or (
                    self.pages and self.pages[-1]["events"][-1] != "PAGE_VALIDATED"
                ):
                    raise ValueError("No extra/in-flight inventory request or retry")
                request = inventory_request(len(self.pages) + 1, self.after_id)
                if decode_gamescript(frame[3:]) != request.to_bytes():
                    raise ValueError("Frozen inventory request sequence required")
                self.pages.append(
                    {
                        "request": request.to_bytes(),
                        "response": None,
                        "receipt": None,
                        "events": ["INDUSTRY_PAGE_REQUEST_SENT"],
                    }
                )
        await self.session.send(*frames)

    async def receive(self, size=4096):
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self.count()
            if kind == SERVER_GAMESCRIPT:
                if not self.pages or self.pages[-1]["response"] is not None:
                    raise ValueError("Duplicate/unrequested inventory response")
                page = self.pages[-1]
                page["response"] = body[:-1] if body.endswith(b"\0") else body
                page["events"].append("INDUSTRY_PAGE_RESPONSE_RECEIVED")
                response = decode_gamescript(body)
                page["receipt"] = IndustryPageReceipt.correlate(page["request"], response)
                page["events"].append("TRANSPORT_RECEIPT_CREATED")
                parsed = IndustryPageResponse.parse(response)
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
            raise ValueError("Inventory recorded transaction mismatch")
        page["events"].append("PAGE_VALIDATED")

    def snapshot(self) -> list[dict]:
        return [
            dict(
                request_id=inventory_request(i, None).request_id,
                ordered_sequence=p["events"],
                request_sha256=hashlib.sha256(p["request"]).hexdigest(),
                response_sha256=None
                if p["response"] is None
                else hashlib.sha256(p["response"]).hexdigest(),
            )
            for i, p in enumerate(self.pages, 1)
        ]


class InventoryNativeBackend(IndustryNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.inventory_session: InventoryRecordedSession | None = None

    def configure_transport(self, prepared, protocol):
        if prepared.request != INVENTORY_FIRST_REQUEST or self.session is None:
            raise ValueError("Frozen inventory preparation required")
        self.inventory_session = InventoryRecordedSession(self.session)
        self.transport = GameScriptTransport(self.inventory_session, protocol)

    async def wait_inventory_startup(self, prepared):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            raw = prepared.spec.stderr_path.read_bytes()
            evidence = parse_industry_proof_evidence(raw, INVENTORY_FIRST_REQUEST.request_id)
            if evidence.ordered_sequence == ("BRIDGE_STARTED",):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit inventory startup deadline")
            await asyncio.sleep(0.01)

    async def inventory_evidence(self, prepared, request, exchange):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            page = parse_industry_page_evidence(
                prepared.spec.stderr_path.read_bytes(), request.request_id
            )
            if len(page.ordered_sequence) == 4:
                page.require_complete(request, exchange.response)
                assert self.inventory_session is not None
                self.inventory_session.validated(exchange)
                return page
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit per-page inventory liveness deadline")
            await asyncio.sleep(0.01)

    def inventory_network_evidence(self):
        return [] if self.inventory_session is None else self.inventory_session.snapshot()

    async def industry_page(self, request):
        raise ValueError("Inventory runner uses bounded session only")
