"""Immutable observation types and validation; no execution dependencies."""

from dataclasses import dataclass
from typing import Literal

from app.simulation.openttd.cargo_page import CargoPageExchange
from app.simulation.openttd.industry_cargo import IndustryCargoExchange
from app.simulation.openttd.industry_page import IndustryPageExchange
from app.simulation.openttd.industry_production import IndustryProductionExchange
from app.simulation.openttd.industry_production_evidence import ProductionTransaction

type QueryExchange = IndustryPageExchange | IndustryCargoExchange | CargoPageExchange


@dataclass(frozen=True)
class StructuralWorldSessionEvidence:
    session_id: str
    events: tuple[str, ...]
    exchanges: tuple[QueryExchange, ...]
    request_attempts: int
    total_response_bytes: int
    protocol_operations: int
    complete: bool
    structural_world_digest: str | None
    failure: str | None
    retries: Literal[0] = 0
    reconnects: Literal[0] = 0


@dataclass(frozen=True)
class ProductionSessionEvidence:
    events: tuple[str, ...]
    transactions: tuple[ProductionTransaction, ...]
    exchanges: tuple[IndustryProductionExchange, ...]
    request_attempts: int
    total_response_bytes: int
    protocol_operations: int
    failure: str | None
    cleanup_failure: str | None
    complete: bool
    retries: int = 0
    reconnects: int = 0
