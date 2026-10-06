"""One secure connection for two bounded phases; GameScript remains unchanged."""

import asyncio
import hashlib
import time

from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptTransport,
    decode_gamescript,
)
from app.simulation.openttd.industry_capability import capability_request_id
from app.simulation.openttd.industry_cargo import IndustryCargoReceipt, IndustryCargoRequest
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
from app.simulation.openttd.industry_enrichment import ENRICHMENT_SESSION_ID

from .enrichment_contract import ENRICHMENT_FIRST_REQUEST
from .inventory_native import InventoryNativeBackend, InventoryRecordedSession


class EnrichmentRecordedSession(InventoryRecordedSession):
    def __init__(self, session):
        super().__init__(session)
        self.cargos = []
        self.inventory = None
        self.phase = "inventory"
        self.phase_operations = {"inventory": 0, "capability": 0}

    def count(self):
        self.operations += 1
        self.phase_operations[self.phase] += 1
        if self.operations > 512 or self.phase_operations[self.phase] > 256:
            raise ValueError("Enrichment Admin frame budget exhausted")

    def begin_capability(self, inventory):
        if (
            self.phase != "inventory"
            or not self.terminal
            or len(self.pages) != inventory.page_count
        ):
            raise ValueError("complete same-run inventory required before capability phase")
        for recorded, page in zip(self.pages, inventory.pages, strict=True):
            if recorded["events"][-1] != "PAGE_VALIDATED" or (
                recorded["request"],
                recorded["response"],
                recorded["receipt"],
            ) != (
                page.exchange.request_payload,
                page.exchange.response_payload,
                page.exchange.receipt,
            ):
                raise ValueError("source inventory differs from continuous connection ledger")
        self.inventory = inventory
        self.phase = "capability"

    async def send(self, *frames):
        if self.phase == "inventory":
            if any(f[2] == ADMIN_GAMESCRIPT for f in frames) and len(self.pages) >= 32:
                raise ValueError("inventory page budget exhausted")
            return await super().send(*frames)
        for frame in frames:
            self.count()
            if frame[2] == ADMIN_GAMESCRIPT:
                if (
                    self.inventory is None
                    or len(self.cargos) >= len(self.inventory.records)
                    or (self.cargos and self.cargos[-1]["events"][-1] != "CAPABILITY_VALIDATED")
                ):
                    raise ValueError("No extra/in-flight capability query or retry")
                id = self.inventory.records[len(self.cargos)].id
                request = IndustryCargoRequest(capability_request_id(ENRICHMENT_SESSION_ID, id), id)
                if decode_gamescript(frame[3:]) != request.to_bytes():
                    raise ValueError("ordered same-inventory capability request required")
                self.cargos.append(
                    dict(
                        request=request.to_bytes(),
                        response=None,
                        receipt=None,
                        events=["INDUSTRY_CARGO_REQUEST_SENT"],
                    )
                )
        await self.session.send(*frames)

    async def receive(self, size=4096):
        if self.phase == "inventory":
            return await super().receive(size)
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self.count()
            if kind == SERVER_GAMESCRIPT:
                if not self.cargos or self.cargos[-1]["response"] is not None:
                    raise ValueError("Duplicate/unrequested capability response")
                cargo = self.cargos[-1]
                cargo["response"] = body[:-1] if body.endswith(b"\0") else body
                cargo["events"].append("INDUSTRY_CARGO_RESPONSE_RECEIVED")
                cargo["receipt"] = IndustryCargoReceipt.correlate_transport(
                    cargo["request"], decode_gamescript(body)
                )
                cargo["events"].append("TRANSPORT_RECEIPT_CREATED")
        return raw

    def cargo_validated(self, exchange):
        cargo = self.cargos[-1]
        if (cargo["request"], cargo["response"], cargo["receipt"]) != (
            exchange.request_payload,
            exchange.response_payload,
            exchange.receipt,
        ):
            raise ValueError("capability ledger/transaction mismatch")
        cargo["events"].append("CAPABILITY_VALIDATED")

    def cargo_snapshot(self):
        return [
            dict(
                request_id=IndustryCargoRequest.parse(c["request"]).request_id,
                industry_id=IndustryCargoRequest.parse(c["request"]).industry_id,
                ordered_sequence=c["events"],
                request_sha256=hashlib.sha256(c["request"]).hexdigest(),
                response_sha256=None
                if c["response"] is None
                else hashlib.sha256(c["response"]).hexdigest(),
            )
            for c in self.cargos
        ]


class EnrichmentNativeBackend(InventoryNativeBackend):
    def configure_transport(self, prepared, protocol):
        if prepared.request != ENRICHMENT_FIRST_REQUEST or self.session is None:
            raise ValueError("Frozen enrichment preparation required")
        self.inventory_session = EnrichmentRecordedSession(self.session)
        self.transport = GameScriptTransport(self.inventory_session, protocol)

    def begin_capability(self, inventory):
        assert isinstance(self.inventory_session, EnrichmentRecordedSession)
        self.inventory_session.begin_capability(inventory)

    async def capability_evidence(self, prepared, request, exchange):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            native = parse_industry_cargo_evidence(
                prepared.spec.stderr_path.read_bytes(), request.request_id
            )
            if len(native.ordered_sequence) == 4:
                native.require_complete(request, exchange.response)
                assert isinstance(self.inventory_session, EnrichmentRecordedSession)
                self.inventory_session.cargo_validated(exchange)
                return native
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit capability liveness deadline")
            await asyncio.sleep(0.01)

    def capability_network_evidence(self):
        return (
            self.inventory_session.cargo_snapshot()
            if isinstance(self.inventory_session, EnrichmentRecordedSession)
            else []
        )
