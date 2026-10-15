"""Same-run structural observation, separate from dynamic state and world preparation."""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace

from app.simulation.openttd.capability_observation import IndustryCapabilityObservation
from app.simulation.openttd.catalog_observation import (
    CargoCatalogObservation,
    validate_capability_catalog,
)
from app.simulation.openttd.industry_inventory import (
    IndustryInventoryObservation,
    IndustryInventoryWorld,
)
from app.simulation.openttd.observation_identity import BridgePackage, RuntimeIdentity
from app.simulation.openttd.observation_protocol import BridgeProtocolError


@dataclass(frozen=True)
class StructuralWorldBudget:
    """32 inventory + 32 capability + 32 catalog queries; existing phase ceilings."""

    max_requests: int = 96
    max_response_bytes: int = 49152  # (32 + 32 + 32) * 512.
    max_operations: int = 1024  # Inventory 256 + capability 256 + catalog 512.

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.max_requests, 96),
            (self.max_response_bytes, 49152),
            (self.max_operations, 1024),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid combined structural-world budget")


@dataclass(frozen=True)
class StructuralWorldContext:
    """Owner-supplied provenance, not a native snapshot epoch or a world fingerprint.

    Opaque process/connection handles identify live ownership by object identity.
    Configuration digest must describe stable world settings/content, excluding secrets
    and transient runtime paths. A future native owner supplies this context.
    """

    world: IndustryInventoryWorld
    bridge: BridgePackage
    configuration_digest: str
    process_identity: object = field(repr=False)
    connection_identity: object = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.world, IndustryInventoryWorld) or not isinstance(
            self.world.runtime_identity, RuntimeIdentity
        ):
            raise ValueError("typed world/runtime identity required")
        if not isinstance(self.bridge, BridgePackage):
            raise ValueError("typed bridge identity required")
        for digest in (
            self.configuration_digest,
            self.world.runtime_identity.sha256,
            self.bridge.sha256,
        ):
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("canonical SHA-256 identity required")
        for handle in (self.process_identity, self.connection_identity):
            if handle is None or isinstance(handle, (str, bytes, int, float, bool)):
                raise ValueError("opaque owned process/connection identity required")

    def require_same_run(self, other: StructuralWorldContext) -> None:
        if (
            not isinstance(other, StructuralWorldContext)
            or self.process_identity is not other.process_identity
            or self.connection_identity is not other.connection_identity
            or self.world != other.world
            or self.configuration_digest != other.configuration_digest
            or self.bridge.sha256 != other.bridge.sha256
        ):
            raise BridgeProtocolError(
                "structural components must share runtime/world/process/connection"
            )


@dataclass(frozen=True)
class ScopedObservation[T]:
    """An immutable observation plus the context captured by its collecting owner."""

    observation: T
    context: StructuralWorldContext

    def __post_init__(self) -> None:
        if not isinstance(self.context, StructuralWorldContext):
            raise ValueError("collecting-owner context required")


@dataclass(frozen=True)
class StructuralWorldObservation:
    inventory: ScopedObservation[IndustryInventoryObservation]
    capability: ScopedObservation[IndustryCapabilityObservation]
    catalog: ScopedObservation[CargoCatalogObservation]
    budget: StructuralWorldBudget = StructuralWorldBudget()

    def __post_init__(self) -> None:
        for source, expected in (
            (self.inventory, IndustryInventoryObservation),
            (self.capability, IndustryCapabilityObservation),
            (self.catalog, CargoCatalogObservation),
        ):
            if not isinstance(source, ScopedObservation) or not isinstance(
                source.observation, expected
            ):
                raise BridgeProtocolError("typed complete component observations required")
            self.inventory.context.require_same_run(source.context)
            if not source.observation.complete:
                raise BridgeProtocolError("complete component observations required")
            replace(source.observation)  # Revalidate the component's semantic/evidence contract.
        inventory, capability, catalog = (
            self.inventory.observation,
            self.capability.observation,
            self.catalog.observation,
        )
        if not capability.inventory.complete:
            raise BridgeProtocolError("complete capability source inventory required")
        replace(capability.inventory)
        world = self.inventory.context.world
        if (
            inventory.world != world
            or capability.inventory.world != world
            or catalog.runtime_identity != world.runtime_identity
            or catalog.world_id != world.world_id
        ):
            raise BridgeProtocolError("component world/runtime provenance mismatch")
        if capability.inventory.inventory_digest != inventory.inventory_digest:
            raise BridgeProtocolError("capability source inventory digest mismatch")
        if tuple(c.industry_id for c in capability.capabilities) != self.ordered_industry_ids:
            raise BridgeProtocolError("missing/extra/duplicate source industry capability")
        validate_capability_catalog(capability, catalog)
        if not isinstance(self.budget, StructuralWorldBudget) or (
            self.total_requests > self.budget.max_requests
            or self.total_response_bytes > self.budget.max_response_bytes
            or self.protocol_operations > self.budget.max_operations
        ):
            raise BridgeProtocolError("combined structural-world budget exhausted")

    @property
    def runtime_identity(self) -> RuntimeIdentity:
        return self.inventory.context.world.runtime_identity

    @property
    def map_width(self) -> int:
        return self.inventory.context.world.map_width

    @property
    def map_height(self) -> int:
        return self.inventory.context.world.map_height

    @property
    def ordered_industry_ids(self) -> tuple[int, ...]:
        return tuple(r.id for r in self.inventory.observation.records)

    @property
    def ordered_cargo_ids(self) -> tuple[int, ...]:
        return tuple(r.cargo_id for r in self.catalog.observation.records)

    @property
    def industry_count(self) -> int:
        return len(self.ordered_industry_ids)

    @property
    def capability_count(self) -> int:
        return len(self.capability.observation.capabilities)

    @property
    def cargo_count(self) -> int:
        return len(self.ordered_cargo_ids)

    @property
    def complete(self) -> bool:
        return True  # Invalid/partial input raises; a partial session has no observation.

    @property
    def inventory_digest(self) -> str:
        return self.inventory.observation.inventory_digest

    @property
    def source_inventory_digest(self) -> str:
        return self.inventory_digest

    @property
    def capability_digest(self) -> str:
        return self.capability.observation.capability_digest

    @property
    def cargo_catalog_digest(self) -> str:
        return self.catalog.observation.catalog_digest

    @property
    def total_requests(self) -> int:
        return (
            self.inventory.observation.page_count
            + self.capability_count
            + self.catalog.observation.page_count
        )

    @property
    def total_response_bytes(self) -> int:
        return sum(
            source.observation.total_response_bytes
            for source in (self.inventory, self.capability, self.catalog)
        )

    @property
    def protocol_operations(self) -> int:
        return sum(
            source.observation.protocol_operations
            for source in (self.inventory, self.capability, self.catalog)
        )

    def to_bytes(self) -> bytes:
        """Composition only: no paths, ownership handles, cursors or request identities."""
        runtime = self.runtime_identity
        return json.dumps(
            {
                "schema": "structural-world-v1",
                "runtime": {
                    "version": runtime.version,
                    "sha256": runtime.sha256,
                    "backend": runtime.backend,
                },
                "map_width": self.map_width,
                "map_height": self.map_height,
                "configuration_digest": self.inventory.context.configuration_digest,
                "bridge_digest": self.inventory.context.bridge.sha256,
                "inventory_digest": self.inventory_digest,
                "capability_digest": self.capability_digest,
                "cargo_catalog_digest": self.cargo_catalog_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    @property
    def structural_world_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()
