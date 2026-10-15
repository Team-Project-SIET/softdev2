"""One owned encrypted stream for structural collection and raw production."""

import json

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.industry_production import IndustryProductionRequest
from app.simulation.openttd.production_observation import production_pairs
from app.simulation.openttd.structural_world import StructuralWorldContext

from .economy_authority import initial_month
from .raw_production_contract import (
    RAW_PRODUCTION_SESSION_ID,
    RawProductionFrameBudget,
    raw_production_first_request,
)
from .structural_native import (
    StructuralNativeBackend,
    StructuralNativeTransport,
    StructuralRecordedSession,
)


class RawProductionNativeTransport(StructuralNativeTransport):
    async def industry_production(self, request, *, timeout=5, operation_budget=None):
        backend = self.backend
        backend.health()
        owner = backend.combined_coordinator
        if (
            owner is None
            or owner.phase != "PRODUCTION"
            or backend.accounting.phase != "production"
            or owner.structural is None
            or not owner.structural.complete
            or owner.production_session is None
        ):
            raise ValueError("Complete structural digest/target barrier required")
        owner.context.require_same_run(self.context)
        owner.structural.inventory.context.require_same_run(self.context)
        if (
            backend.session is not backend.secure_connection
            or self.recorded.session is not backend.secure_connection
            or self.context.connection_identity is not self.recorded
            or backend.process is not self.context.process_identity
            or owner.production_session.targets != production_pairs(owner.structural)
        ):
            raise ValueError("Same-run production process/connection/targets changed")
        targets = owner.production_session.targets
        index = sum(
            isinstance(r["request"], IndustryProductionRequest) for r in self.recorded.transactions
        )
        if index >= len(targets):
            raise ValueError("No extra production request or retry")
        industry, cargo = targets[index]
        expected = IndustryProductionRequest(
            owner.production_session.session_id + f"-p{index + 1:03d}", industry, cargo
        )
        if request != expected:
            raise ValueError("Canonical same-run produced-pair request required")
        self.recorded.expect(request)
        return await super().industry_production(
            request, timeout=timeout, operation_budget=operation_budget
        )


class RawProductionNativeBackend(StructuralNativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self.accounting = RawProductionFrameBudget()
        self.combined_coordinator = None
        self.economy_month = None

    def configure_transport(self, prepared, protocol):
        if (
            prepared.request != raw_production_first_request()
            or self.session is None
            or self.accounting.total_frames != 2
        ):
            raise ValueError("Frozen combined request/secure establishment required")
        config = json.loads((prepared.directory / "structural-context.json").read_text())
        bridge = json.loads((prepared.directory / "bridge-package-identity.json").read_text())
        self.structural_session = StructuralRecordedSession(self.session)
        world = IndustryInventoryWorld.from_welcome(
            RAW_PRODUCTION_SESSION_ID, prepared.spec.identity, self.welcome
        )
        context = StructuralWorldContext(
            world,
            BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", bridge["sha256"]),
            config["configuration_digest"],
            self.process,
            self.structural_session,
        )
        self.economy_month = initial_month(self.welcome)
        self.transport = RawProductionNativeTransport(
            self.structural_session, protocol, context, self
        )
