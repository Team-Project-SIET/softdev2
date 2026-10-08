"""One owned encrypted session for qualification, using the shared native observer."""

import asyncio
import json
import time

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.qualification_clock import EconomyClockRequest, IndustryLifetimeRequest
from app.simulation.openttd.qualification_evidence import parse_native_read_evidence
from app.simulation.openttd.qualification_session import QualificationTransport
from app.simulation.openttd.structural_world import StructuralWorldContext

from .qualification_accounting import QualificationFrameBudget
from .qualification_contract import SESSION_ID, first_request
from .structural_native import StructuralNativeBackend, StructuralRecordedSession


class QualificationNativeTransport(QualificationTransport):
    def __init__(self, recorded, protocol, context, backend):
        super().__init__(recorded, protocol)
        self.context, self.backend = context, backend
        self.recorded: StructuralRecordedSession = recorded

    async def _read_query(self, request, **kwargs):
        b = self.backend
        b.health()
        owner = b.qualification_coordinator
        if (
            owner is None
            or b.session is not b.secure_connection
            or self.recorded.session is not b.secure_connection
            or b.process is not self.context.process_identity
        ):
            raise ValueError("Qualification continuous process/secure connection required")
        owner.context.require_same_run(self.context)
        category = owner._category(json.loads(request.to_bytes())["type"])
        if b.accounting.phase != category:
            raise ValueError("Qualification phase accounting barrier required")
        if isinstance(request, EconomyClockRequest) and request != EconomyClockRequest(
            f"{owner.session_id}-clock-{owner.clock.polls + 1}"
        ):
            raise ValueError("Canonical clock request required")
        if isinstance(request, IndustryLifetimeRequest):
            source = owner.anchor if category == "anchor_lifetime" else owner.final
            from app.simulation.openttd.production_observation import production_pairs

            ids = sorted({i for i, _ in production_pairs(source)})
            prefix = "anchor" if category == "anchor_lifetime" else "final"
            rows = [
                r
                for r in self.recorded.transactions
                if isinstance(r["request"], IndustryLifetimeRequest)
                and r["request"].request_id.startswith(owner.session_id + "-" + prefix)
            ]
            if len(rows) >= len(ids) or request != IndustryLifetimeRequest(
                f"{owner.session_id}-{prefix}-life-{ids[len(rows)]}", ids[len(rows)]
            ):
                raise ValueError("Canonical same-run lifetime target required")
        self.recorded.expect(request)
        return await super()._read_query(request, **kwargs)


class QualificationNativeBackend(StructuralNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.accounting = QualificationFrameBudget()
        self.qualification_coordinator = None

    def configure_transport(self, prepared, protocol):
        if (
            prepared.request != first_request()
            or self.session is None
            or self.accounting.total_frames != 2
        ):
            raise ValueError("Qualification frozen clock/secure establishment required")
        bridge = json.loads((prepared.directory / "bridge-package-identity.json").read_text())
        config = json.loads((prepared.directory / "structural-context.json").read_text())
        self.structural_session = StructuralRecordedSession(self.session)
        context = StructuralWorldContext(
            IndustryInventoryWorld.from_welcome(SESSION_ID, prepared.spec.identity, self.welcome),
            BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", bridge["sha256"]),
            config["configuration_digest"],
            self.process,
            self.structural_session,
        )
        self.transport = QualificationNativeTransport(
            self.structural_session, protocol, context, self
        )

    async def evidence(self, prepared, request, exchange):
        if not isinstance(request, (EconomyClockRequest, IndustryLifetimeRequest)):
            return await super().evidence(prepared, request, exchange)
        assert self.secure_connection is not None and self.structural_session is not None
        deadline = time.monotonic() + 5
        while True:
            self.health()
            await self.secure_connection.require_quiescent()
            evidence = parse_native_read_evidence(
                prepared.spec.stderr_path.read_bytes(), request.request_id, request.command
            )
            if len(evidence.sequence) == 4:
                evidence.require_complete(exchange)
                self.structural_session.validated(exchange)
                row = self.structural_session.transactions[-1]
                row.update(exchange=exchange, gamescript=evidence)
                actual = self.accounting.query_operations
                if actual - self.query_operation_baseline != exchange.protocol_operations:
                    raise ValueError("Qualification shared native receipt accounting mismatch")
                self.query_operation_baseline = actual
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Native qualification read/liveness deadline")
            await asyncio.sleep(0.01)
