"""P07 financial attribution and cost accounting over retained offline evidence.

This layer consumes an already-verified P07 document (a continuous ``summary.json``
or a network ``evaluation.json``) plus optional read-only retained native records
(``service-receipt-*.json``, ``financial-reconciliation.json``,
``capital-read-response.json``) and produces one deterministic financial
attribution document:

- a normalized ledger of OBSERVED / DERIVED / UNKNOWN amounts per category,
- explicit CAPEX/OPEX category separation only where evidence supports it,
- company-level reconciliation statements with explicit known and unknown terms,
- per-service attribution where the retained evidence binds amounts per service,
- unexplained (unattributed) cash residuals left unclassified,
- coverage and completeness indicators,
- period-based financial rows for comparisons,
- explicit UNSUPPORTED claims for operating profit, net profit, ROI, payback
  period, cost per cargo unit, service profitability and network financial
  efficiency, each with the native observations that would be required.

The reconciliation identity reuses the pinned semantics of
``app.simulation.openttd.freight_finance.reconcile_cash`` (unattributed residual =
closing cash − (opening cash + revenue + identified movements − known outflows))
and never recomputes that identity differently: amounts are normalized from the
retained document's own values and the residual is re-checked against them.
Missing amounts stay UNKNOWN; missing transactions are never manufactured; an
unattributed residual is never renamed into an expense category.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from app.planning.domain import Contract
from app.simulation.openttd.freight_finance import reconcile_cash

SCHEMA_VERSION = 1
EVIDENCE = Literal["OBSERVED", "DERIVED", "HYPOTHESIS", "UNKNOWN"]

OUTPUT_NAMES = (
    "financial-attribution.json",
    "financial-attribution.md",
    "financial-attribution-summary.txt",
    "financial-comparison.json",
)

UNKNOWN_NOTE = "UNKNOWN is not zero; missing transactions are never manufactured."

# Closed ledger category set. Amounts are signed GBP movements from the company
# cash perspective: inflows positive, outflows negative.
CATEGORY_FUNDING = "FUNDING_CAPITAL"
CATEGORY_INITIAL_CASH = "COMPANY_INITIAL_CASH"
CATEGORY_CAPEX_ROAD = "CAPEX_CONSTRUCTION_ROAD"
CATEGORY_CAPEX_FACILITY = "CAPEX_CONSTRUCTION_FACILITY"
CATEGORY_CAPEX_OTHER = "CAPEX_CONSTRUCTION_OTHER"
CATEGORY_CAPEX_UNSPLIT = "CAPEX_CONSTRUCTION_UNSPLIT"
CATEGORY_CAPEX_VEHICLE = "CAPEX_VEHICLE_PURCHASE"
CATEGORY_REVENUE = "REVENUE_TRANSPORT"
CATEGORY_EXPENSE_AGGREGATE = "EXPENSE_AGGREGATE_UNALLOCATED"
CATEGORY_OPEX_VEHICLE_RUNNING = "OPEX_VEHICLE_RUNNING"
CATEGORY_OPEX_LOAN_INTEREST = "OPEX_LOAN_INTEREST"
CATEGORY_OPEX_PROPERTY = "OPEX_PROPERTY_MAINTENANCE"
CATEGORY_LOAN_MOVEMENT = "LOAN_PRINCIPAL_MOVEMENT"
CATEGORY_UNATTRIBUTED = "UNATTRIBUTED_CASH_MOVEMENT"

CAPEX_CATEGORIES = (
    CATEGORY_CAPEX_ROAD,
    CATEGORY_CAPEX_FACILITY,
    CATEGORY_CAPEX_OTHER,
    CATEGORY_CAPEX_UNSPLIT,
    CATEGORY_CAPEX_VEHICLE,
)
# Native quarterly expense counters cover exactly these categories as one
# aggregate (vehicle running costs, property, loan interest); the read API
# cannot split them, so each stays UNKNOWN in the retained evidence.
OPEX_CATEGORIES = (
    CATEGORY_OPEX_VEHICLE_RUNNING,
    CATEGORY_OPEX_LOAN_INTEREST,
    CATEGORY_OPEX_PROPERTY,
)
UNKNOWN_CATEGORIES = OPEX_CATEGORIES

CLASSIFICATION_COMPLETE = "COMPLETE_FINANCIAL_ATTRIBUTION"
CLASSIFICATION_PARTIAL = "PARTIAL_FINANCIAL_ATTRIBUTION"
CLASSIFICATION_NO_EVIDENCE = "NO_FINANCIAL_EVIDENCE"

CAPITAL_READ_FILE = "capital-read-response.json"
NATIVE_RECONCILIATION_FILE = "financial-reconciliation.json"
RECEIPT_PREFIX = "service-receipt-"
RECEIPT_SUFFIX = ".json"
MAX_RECEIPTS = 8

CLAIM_METRICS = (
    "operating_profit",
    "net_profit",
    "roi",
    "payback_period",
    "cost_per_cargo_unit",
    "service_profitability",
    "network_financial_efficiency",
)

_REQUIRED_NATIVE_OBSERVATIONS = (
    "Native company expense-category amounts (vehicle running costs, property, "
    "loan interest, other) for exactly the observed window; the retained "
    "quarterly aggregate cannot be split through the GameScript read API.",
    "Company cash sampled synchronously at quarter boundaries so cash windows "
    "and quarter counters align and the unattributed residual isolates only "
    "engine movements outside the aggregate.",
    "Per-service revenue or a declared engine basis to attribute company income "
    "to individual services (cargo monitors count units, not revenue).",
    "Mid-window construction/purchase CAPEX bound to the same window as the "
    "revenue it is compared against.",
)


def _number(value) -> int | float | None:
    """Native and evaluated JSON values may arrive as Decimal strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _fmt(value) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class LedgerEntry(Contract):
    entry_id: str
    category: str
    scope: str
    amount_gbp: int | float | None
    status: EVIDENCE
    period: str
    source: str
    derivation: str
    missing_data_behavior: str
    limitations: str = ""


class ReconciliationTerm(Contract):
    term_id: str
    role: Literal["OPENING_CASH", "INFLOW", "OUTFLOW", "CLOSING_CASH", "UNKNOWN_TERM", "RESIDUAL"]
    category: str
    amount_gbp: int | float | None
    status: EVIDENCE
    source: str


class ReconciliationStatement(Contract):
    statement_id: str
    period: str
    scope: str
    equation: str
    terms: list[ReconciliationTerm]
    residual_gbp: int | float | None
    residual_is_zero: bool | None
    identity_verified: bool | None = None
    notes: list[str] = []


class ServiceAttribution(Contract):
    scope: str
    label: str
    capex_gbp: int | float | None
    capex_status: EVIDENCE
    capex_categories: dict[str, int | float | None]
    revenue_gbp: int | float | None
    revenue_status: EVIDENCE
    vehicle_profit_delta_gbp: int | float | None
    vehicle_profit_status: EVIDENCE
    operating_expenses_status: Literal["UNKNOWN"]
    missing: list[str]


class PeriodFinancialRow(Contract):
    period: str
    kind: str
    index: int
    scope: str
    start_economy_date: int
    end_economy_date: int
    elapsed_economy_days: int | None
    revenue_gbp: int | float | None
    observed_aggregate_expenses_gbp: int | float | None
    vehicle_operating_expenses_gbp: int | float | None
    revenue_growth_vs_previous: int | float | None
    coverage: str


class CoverageIndicator(Contract):
    indicator: str
    value: bool | int | float | str | None
    status: EVIDENCE
    detail: str


class AttributionClaim(Contract):
    metric: str
    status: Literal["UNSUPPORTED"]
    reason: str
    required_observations: list[str]


class FinancialAttribution(Contract):
    schema_version: Literal[1]
    classification: str
    source_kind: Literal["continuous", "network-evaluation"]
    source_ref: str
    source_sha256: str | None = None
    native_terminal_status: str | None = None
    world_identity: dict[str, str] | None = None
    ledger: list[LedgerEntry]
    reconciliations: list[ReconciliationStatement]
    services: list[ServiceAttribution]
    coverage: list[CoverageIndicator]
    period_rows: list[PeriodFinancialRow]
    claims: list[AttributionClaim]
    limitations: list[str]


# ---------------------------------------------------------------------------
# Retained-evidence readers (strictly read-only)
# ---------------------------------------------------------------------------


def _evidence_roots(source: Path, document: dict) -> tuple[Path, ...]:
    """Report directory first, then retained original/evidence directories."""
    roots = [source]
    recovery = (document.get("offline_recovery") or {}).get("original_directory")
    if recovery:
        candidate = Path(recovery)
        roots.append(candidate if candidate.is_absolute() else source / candidate)
    evidence_directory = document.get("evidence_directory")
    if evidence_directory:
        candidate = Path(evidence_directory)
        roots.append(candidate if candidate.is_absolute() else source / candidate)
    return tuple(roots)


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"retained native record {path} is not a JSON object")
    return payload


def _find_in_roots(roots: Iterable[Path], name: str) -> Path | None:
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def discover_receipts(roots: Iterable[Path]) -> tuple[Path, ...]:
    """Retained per-service receipt files, ordered, from the first root that has any."""
    for root in roots:
        found = tuple(
            root / f"{RECEIPT_PREFIX}{index}{RECEIPT_SUFFIX}"
            for index in range(MAX_RECEIPTS)
            if (root / f"{RECEIPT_PREFIX}{index}{RECEIPT_SUFFIX}").is_file()
        )
        if found:
            return found
    return ()


def read_capital_gift(roots: Iterable[Path]) -> int | float | None:
    """OBSERVED scenario-capital gift delta from a retained completed capital readback."""
    path = _find_in_roots(roots, CAPITAL_READ_FILE)
    if path is None:
        return None
    capital = _read_json(path)
    if capital.get("status") != "READ" or not capital.get("completed"):
        raise ValueError(f"retained capital readback {path} is not a completed READ")
    return _number(capital.get("delta"))


def read_native_reconciliation(roots: Iterable[Path]) -> dict | None:
    """Retained native-network-financial-reconciliation-v1 payload, when present."""
    path = _find_in_roots(roots, NATIVE_RECONCILIATION_FILE)
    if path is None:
        return None
    payload = _read_json(path)
    if payload.get("schema") != "native-network-financial-reconciliation-v1":
        raise ValueError(f"unsupported native financial reconciliation schema at {path}")
    return payload


# ---------------------------------------------------------------------------
# Ledger construction
# ---------------------------------------------------------------------------


def _entry(
    category: str,
    scope: str,
    amount,
    status: str,
    period: str,
    source: str,
    derivation: str,
    missing_data_behavior: str,
    limitations: str = "",
) -> LedgerEntry:
    if amount is None and status in {"OBSERVED", "DERIVED"}:
        status = "UNKNOWN"
    return LedgerEntry(
        entry_id="",  # assigned deterministically after sorting
        category=category,
        scope=scope,
        amount_gbp=amount if status != "UNKNOWN" else None,
        status=status,
        period=period,
        source=source,
        derivation=derivation,
        missing_data_behavior=missing_data_behavior,
        limitations=limitations,
    )


def _final_entries(rows: list[LedgerEntry]) -> list[LedgerEntry]:
    ordered = sorted(rows, key=lambda row: (row.category, row.scope, row.period, row.source))
    return [
        row.model_copy(update={"entry_id": f"led-{index:03d}-{row.category}"})
        for index, row in enumerate(ordered, 1)
    ]


def _kind_split(receipt: dict) -> tuple[int | None, int | None, int | None]:
    """OBSERVED road/facility sums from succeeded construction command readbacks."""
    road = facility = other = 0
    seen = False
    for readback in receipt.get("construction_command_readbacks") or ():
        if readback.get("classification") != "COMMAND_SUCCEEDED":
            continue
        spent = _number(readback.get("spent"))
        kind = readback.get("kind")
        if spent is None or not kind:
            continue
        seen = True
        if kind == "ROAD":
            road += int(spent)
        elif kind == "FACILITY":
            facility += int(spent)
        else:
            other += int(spent)
    return (road, facility, other) if seen else (None, None, None)


def _receipt_capex(receipt: dict) -> tuple[int | None, int | None, int | None]:
    """Pinned receipt CAPEX semantics from the committed native network module.

    ``freight_native_network.financial_reconciliation`` classifies
    ``sum(mutation_costs[:6])`` as infrastructure and ``mutation_costs[6]`` as the
    vehicle purchase for ``first-freight-delivery-receipt-v1`` receipts.
    """
    costs = receipt.get("mutation_costs") or ()
    numbers = [_number(cost) for cost in costs]
    if len(numbers) < 7:
        return None, None, _number(receipt.get("construction_purchase_spending"))
    return (
        sum(number for number in numbers[:6] if number is not None),
        numbers[6],
        _number(receipt.get("construction_purchase_spending")),
    )


def _receipt_entries(
    receipts: tuple[tuple[Path, dict], ...], source_ref: str
) -> tuple[list[LedgerEntry], list[ServiceAttribution]]:
    """Per-service CAPEX ledger entries and attributions from retained receipts."""
    entries: list[LedgerEntry] = []
    services: list[ServiceAttribution] = []
    for position, (path, receipt) in enumerate(receipts, 1):
        scope = str(receipt.get("route_id") or "UNKNOWN_ROUTE")
        infrastructure, vehicle, total = _receipt_capex(receipt)
        road, facility, other = _kind_split(receipt)
        kind_total = None
        if road is not None:
            kind_total = road + facility + other
        source = f"{source_ref} {path.name}"
        per_kind: dict[str, int | None] = {
            CATEGORY_CAPEX_ROAD: road,
            CATEGORY_CAPEX_FACILITY: facility,
            CATEGORY_CAPEX_OTHER: other,
        }
        if infrastructure is not None and kind_total is None:
            # No succeeded readbacks are retained, so the whole observed
            # infrastructure total stays unsplit in the ledger (still OBSERVED).
            per_kind[CATEGORY_CAPEX_UNSPLIT] = infrastructure
        elif infrastructure is not None and kind_total is not None and kind_total <= infrastructure:
            per_kind[CATEGORY_CAPEX_UNSPLIT] = infrastructure - kind_total
        elif infrastructure is not None:
            per_kind[CATEGORY_CAPEX_UNSPLIT] = None
        for category, amount in per_kind.items():
            if amount is None:
                continue
            entries.append(
                _entry(
                    category,
                    scope,
                    -amount,
                    "OBSERVED",
                    "setup window",
                    source,
                    "Retained receipt construction command readbacks; outflows are "
                    "signed negative. ALREADY_SATISFIED commands are not spending.",
                    "UNKNOWN when the receipt or the command kind is not retained; "
                    "UNKNOWN is never zero.",
                    "Construction commands only; the vehicle purchase is a separate category.",
                )
            )
        if infrastructure is not None and kind_total is not None and kind_total > infrastructure:
            entries.append(
                _entry(
                    CATEGORY_CAPEX_OTHER,
                    scope,
                    None,
                    "UNKNOWN",
                    "setup window",
                    source,
                    "Command kind split exceeds the pinned infrastructure total; the "
                    "difference is reported as a coverage gap, not reclassified.",
                    "Ledger keeps the pinned totals and flags the inconsistency.",
                )
            )
        entries.append(
            _entry(
                CATEGORY_CAPEX_VEHICLE,
                scope,
                -vehicle if vehicle is not None else None,
                "OBSERVED",
                "setup window",
                source,
                "Vehicle purchase cost from the retained receipt mutation ledger "
                "(mutation_costs slot 6, the committed native classification).",
                "UNKNOWN when the purchase cost is not retained.",
            )
        )
        if None not in (infrastructure, vehicle, total) and infrastructure + vehicle != total:
            entries.append(
                _entry(
                    CATEGORY_CAPEX_UNSPLIT,
                    scope,
                    None,
                    "UNKNOWN",
                    "setup window",
                    source,
                    "Receipt infrastructure + vehicle purchase does not equal the "
                    "retained construction_purchase_spending; inconsistency retained.",
                    "Coverage reports the gap; no amount is invented.",
                )
            )
        revenue = _number(receipt.get("payment_income"))
        profit = _number(receipt.get("vehicle_profit_delta"))
        services.append(
            ServiceAttribution(
                scope=scope,
                label=f"Service {position}",
                capex_gbp=total,
                capex_status="OBSERVED" if total is not None else "UNKNOWN",
                capex_categories={
                    CATEGORY_CAPEX_ROAD: road,
                    CATEGORY_CAPEX_FACILITY: facility,
                    CATEGORY_CAPEX_OTHER: other,
                    CATEGORY_CAPEX_VEHICLE: vehicle,
                },
                revenue_gbp=revenue,
                revenue_status="OBSERVED" if revenue is not None else "UNKNOWN",
                vehicle_profit_delta_gbp=profit,
                vehicle_profit_status="OBSERVED" if profit is not None else "UNKNOWN",
                operating_expenses_status="UNKNOWN",
                missing=[
                    "Retained operating-expense attribution for this service's window.",
                ],
            )
        )
    return entries, services


def _capital_entries(capital_gift, source: str, financed_opening) -> list[LedgerEntry]:
    """Funding-capital and pre-existing company cash entries where observed."""
    entries: list[LedgerEntry] = []
    if capital_gift is not None:
        entries.append(
            _entry(
                CATEGORY_FUNDING,
                "network",
                capital_gift,
                "OBSERVED",
                "funding window",
                source,
                "Scenario-capital gift delta from the retained completed capital readback.",
                "UNKNOWN when no completed capital readback is retained.",
                "An identified capital inflow, not transport revenue.",
            )
        )
        opening = _number(financed_opening)
        if opening is not None:
            initial = opening - capital_gift
            if initial:
                entries.append(
                    _entry(
                        CATEGORY_INITIAL_CASH,
                        "network",
                        initial,
                        "DERIVED",
                        "funding window",
                        source,
                        "Retained funded balance minus the gift delta; the company "
                        "pre-funding cash visible to the capital readback.",
                        "UNKNOWN when either endpoint is missing.",
                    )
                )
    return entries


def _loan_movement_entry(finance: dict, period: str, source: str) -> LedgerEntry:
    amount = _number(finance.get("other_identified_movements"))
    return _entry(
        CATEGORY_LOAN_MOVEMENT,
        "network",
        amount,
        "OBSERVED",
        period,
        source,
        "Loan-principal movement retained as an identified cash movement "
        "(opening→closing loan balance delta).",
        "UNKNOWN when no loan balances were retained.",
        "Financing movement, not an operating expense and not revenue.",
    )


# ---------------------------------------------------------------------------
# Reconciliation statements
# ---------------------------------------------------------------------------


def _operating_identity(finance: dict) -> tuple[int | float | None, bool | None]:
    """Deterministic residual via the pinned ``reconcile_cash`` identity.

    Returns ``(residual, identity_verified)``. ``capex`` is pinned to 0: the
    operating window opens after construction and CAPEX is reconciled in the
    setup statement (never deducted twice). The residual prefers the retained
    ``unknown_cash_movements`` field; when the field is absent it is recomputed
    from retained terms (never estimated). ``identity_verified`` is True/False
    only when both a recomputation and a retained field exist, so a drift
    between this module and a retained field is a finding, not a repair.
    """
    opening = _number(finance.get("opening_cash"))
    closing = _number(finance.get("closing_cash"))
    revenue = _number(finance.get("freight_revenue"))
    aggregate = _number(finance.get("known_unallocated_expenses"))
    document_residual = _number(finance.get("unknown_cash_movements"))
    recomputed = None
    if None not in (opening, closing, revenue, aggregate):
        recomputed = reconcile_cash(
            opening,
            closing,
            revenue,
            capex=0,
            vehicle_operating_expenses=_number(finance.get("vehicle_operating_expenses")),
            loan_interest=_number(finance.get("loan_interest")),
            other_expenses=_number(finance.get("other_expenses")),
            other_identified_movements=_number(finance.get("other_identified_movements")) or 0,
            known_unallocated_expenses=aggregate,
        )["unknown_cash_movements"]
    residual = document_residual if document_residual is not None else recomputed
    identity_verified = (
        recomputed == document_residual
        if recomputed is not None and document_residual is not None
        else None
    )
    return residual, identity_verified


def _operating_statement(
    finance: dict, period: str, source_ref: str, statement_id: str
) -> ReconciliationStatement:
    """Deterministic cash identity over the operating window from the document.

    Runs the pinned ``reconcile_cash`` identity (see `_operating_identity`) and
    verifies it against the retained field. CAPEX is not a term here: the
    operating window opens after construction, and CAPEX is reconciled in the
    setup statement instead (never deducted twice).
    """
    opening = _number(finance.get("opening_cash"))
    closing = _number(finance.get("closing_cash"))
    revenue = _number(finance.get("freight_revenue"))
    aggregate = _number(finance.get("known_unallocated_expenses"))
    loan_movement = _number(finance.get("other_identified_movements"))
    opex = _number(finance.get("vehicle_operating_expenses"))
    interest = _number(finance.get("loan_interest"))
    other = _number(finance.get("other_expenses"))
    residual, identity_verified = _operating_identity(finance)
    terms = [
        ReconciliationTerm(
            term_id="opening_cash",
            role="OPENING_CASH",
            category=CATEGORY_INITIAL_CASH,
            amount_gbp=opening,
            status="OBSERVED" if opening is not None else "UNKNOWN",
            source=f"{source_ref} finance.opening_cash",
        ),
        ReconciliationTerm(
            term_id="freight_revenue",
            role="INFLOW",
            category=CATEGORY_REVENUE,
            amount_gbp=revenue,
            status="OBSERVED" if revenue is not None else "UNKNOWN",
            source=f"{source_ref} finance.freight_revenue",
        ),
        ReconciliationTerm(
            term_id="loan_principal_movement",
            role="INFLOW",
            category=CATEGORY_LOAN_MOVEMENT,
            amount_gbp=loan_movement,
            status="OBSERVED" if loan_movement is not None else "UNKNOWN",
            source=f"{source_ref} finance.other_identified_movements",
        ),
        ReconciliationTerm(
            term_id="aggregate_expenses",
            role="OUTFLOW",
            category=CATEGORY_EXPENSE_AGGREGATE,
            amount_gbp=-aggregate if aggregate is not None else None,
            status="OBSERVED" if aggregate is not None else "UNKNOWN",
            source=f"{source_ref} finance.known_unallocated_expenses (signed outflow)",
        ),
        ReconciliationTerm(
            term_id="vehicle_operating_expenses",
            role="UNKNOWN_TERM",
            category=CATEGORY_OPEX_VEHICLE_RUNNING,
            amount_gbp=opex,
            status="UNKNOWN" if opex is None else "OBSERVED",
            source=f"{source_ref} finance.vehicle_operating_expenses",
        ),
        ReconciliationTerm(
            term_id="loan_interest",
            role="UNKNOWN_TERM",
            category=CATEGORY_OPEX_LOAN_INTEREST,
            amount_gbp=interest,
            status="UNKNOWN" if interest is None else "OBSERVED",
            source=f"{source_ref} finance.loan_interest",
        ),
        ReconciliationTerm(
            term_id="other_expenses",
            role="UNKNOWN_TERM",
            category=CATEGORY_OPEX_PROPERTY,
            amount_gbp=other,
            status="UNKNOWN" if other is None else "OBSERVED",
            source=f"{source_ref} finance.other_expenses",
        ),
        ReconciliationTerm(
            term_id="closing_cash",
            role="CLOSING_CASH",
            category=CATEGORY_INITIAL_CASH,
            amount_gbp=closing,
            status="OBSERVED" if closing is not None else "UNKNOWN",
            source=f"{source_ref} finance.closing_cash",
        ),
        ReconciliationTerm(
            term_id="unknown_residual",
            role="RESIDUAL",
            category=CATEGORY_UNATTRIBUTED,
            amount_gbp=residual,
            status="UNKNOWN" if residual is None else "DERIVED",
            source="deterministic residual of this statement's known terms",
        ),
    ]
    notes = [
        "CAPEX is outside the operating window and is reconciled in the setup "
        "statement; it is never deducted from this window twice.",
        "The unattributed residual is a cash-movement remainder, never an expense "
        "category; it is not used to compute profit.",
    ]
    if identity_verified is False:
        notes.append(
            "Recomputed residual differs from the retained residual; both are "
            "reported and neither is reclassified."
        )
    return ReconciliationStatement(
        statement_id=statement_id,
        period=period,
        scope="network",
        equation=(
            "closing_cash = opening_cash + freight_revenue + loan_principal_movement "
            "- aggregate_expenses + unknown_residual"
        ),
        terms=terms,
        residual_gbp=residual,
        residual_is_zero=None if residual is None else residual == 0,
        identity_verified=identity_verified,
        notes=notes,
    )


def _setup_statement(setup: dict, capital_gift, source_ref: str) -> ReconciliationStatement | None:
    """Setup-window identity: funding → operation opening cash (CAPEX inside)."""
    funding = _number(setup.get("funding_cash"))
    opening = _number(setup.get("operation_opening_cash"))
    capex = _number(setup.get("construction_capex"))
    measured = _number(setup.get("measured_setup_aggregate_expenses"))
    unattributed = _number(setup.get("unattributed_setup_cash_decrease"))
    # Retained records express "decrease" magnitudes positively; this ledger
    # signs cash movements, so an unattributed decrease is a negative movement.
    signed_unattributed = -unattributed if unattributed is not None else None
    if funding is None or opening is None:
        return None
    pre_funding = None if capital_gift in (None, 0) else funding - capital_gift
    terms = [
        ReconciliationTerm(
            term_id="pre_funding_company_cash",
            role="OPENING_CASH",
            category=CATEGORY_INITIAL_CASH,
            amount_gbp=pre_funding,
            status="OBSERVED" if pre_funding is not None else "UNKNOWN",
            source=f"{source_ref} capital readback balance_before",
        ),
        ReconciliationTerm(
            term_id="funding_capital_gift",
            role="INFLOW",
            category=CATEGORY_FUNDING,
            amount_gbp=capital_gift,
            status="OBSERVED" if capital_gift is not None else "UNKNOWN",
            source=f"{source_ref} capital gift delta",
        ),
        ReconciliationTerm(
            term_id="construction_and_vehicle_capex",
            role="OUTFLOW",
            category=CATEGORY_CAPEX_UNSPLIT,
            amount_gbp=-capex if capex is not None else None,
            status="OBSERVED" if capex is not None else "UNKNOWN",
            source=f"{source_ref} setup_cash_coverage.construction_capex",
        ),
        ReconciliationTerm(
            term_id="setup_aggregate_expenses",
            role="OUTFLOW",
            category=CATEGORY_EXPENSE_AGGREGATE,
            amount_gbp=-measured if measured is not None else None,
            status="OBSERVED" if measured is not None else "UNKNOWN",
            source=f"{source_ref} setup_cash_coverage.measured_setup_aggregate_expenses",
        ),
        ReconciliationTerm(
            term_id="unattributed_setup_movement",
            role="RESIDUAL",
            category=CATEGORY_UNATTRIBUTED,
            amount_gbp=signed_unattributed,
            status="UNKNOWN" if signed_unattributed is None else "DERIVED",
            source=f"{source_ref} setup_cash_coverage.unattributed_setup_cash_decrease",
        ),
        ReconciliationTerm(
            term_id="operation_opening_cash",
            role="CLOSING_CASH",
            category=CATEGORY_INITIAL_CASH,
            amount_gbp=opening,
            status="OBSERVED",
            source=f"{source_ref} setup_cash_coverage.operation_opening_cash",
        ),
    ]
    recomputed = (
        opening - (funding - capex - (measured or 0))
        if None not in (funding, capex, opening)
        else None
    )
    identity_verified = (
        recomputed == signed_unattributed
        if recomputed is not None and signed_unattributed is not None
        else None
    )
    return ReconciliationStatement(
        statement_id="recon-setup-window",
        period="funding-to-operation window",
        scope="network",
        equation=(
            "operation_opening_cash = pre_funding_company_cash + funding_capital_gift "
            "- construction_and_vehicle_capex - setup_aggregate_expenses "
            "+ unattributed_setup_movement"
        ),
        terms=terms,
        residual_gbp=signed_unattributed,
        residual_is_zero=None if unattributed is None else unattributed == 0,
        identity_verified=identity_verified,
        notes=[
            "Retained records store an unattributed setup cash decrease as a "
            "positive magnitude; the ledger signs this movement negative.",
            "The funding-to-opening setup window precedes the operating window; its "
            "CAPEX and expenses are excluded from operating-window deltas.",
            "Opening quarter counters are context samples, not attributed costs.",
        ],
    )


def _native_reconciliation_statements(
    payload: dict, source_ref: str
) -> list[ReconciliationStatement]:
    """Statements mirroring the retained native-network-financial-reconciliation-v1."""
    funded = _number(payload.get("funded_cash"))
    initial = _number(payload.get("initial_cash"))
    final = _number(payload.get("final_cash"))
    revenue = _number(payload.get("freight_revenue"))
    capex = _number(payload.get("command_construction_purchase_costs"))
    statements = []
    admission_decrease = _number(payload.get("funding_to_admission_unallocated_cash_decrease"))
    if None not in (funded, initial) and initial != funded:
        statements.append(
            ReconciliationStatement(
                statement_id="recon-funding-to-admission",
                period="funding-to-admission window",
                scope="network",
                equation="initial_cash = funded_cash - funding_to_admission_unallocated_decrease",
                terms=[
                    ReconciliationTerm(
                        term_id="funded_cash",
                        role="OPENING_CASH",
                        category=CATEGORY_INITIAL_CASH,
                        amount_gbp=funded,
                        status="OBSERVED",
                        source=f"{source_ref} funded_cash",
                    ),
                    ReconciliationTerm(
                        term_id="unattributed_admission_movement",
                        role="RESIDUAL",
                        category=CATEGORY_UNATTRIBUTED,
                        amount_gbp=-admission_decrease if admission_decrease is not None else None,
                        status="UNKNOWN" if admission_decrease is None else "DERIVED",
                        source=f"{source_ref} funding_to_admission_unallocated_cash_decrease",
                    ),
                    ReconciliationTerm(
                        term_id="admission_cash",
                        role="CLOSING_CASH",
                        category=CATEGORY_INITIAL_CASH,
                        amount_gbp=initial,
                        status="OBSERVED",
                        source=f"{source_ref} initial_cash",
                    ),
                ],
                residual_gbp=-admission_decrease if admission_decrease is not None else None,
                residual_is_zero=None if admission_decrease is None else admission_decrease == 0,
                identity_verified=(
                    funded - (admission_decrease or 0) == initial
                    if None not in (funded, initial, admission_decrease)
                    else None
                ),
                notes=[
                    "Native record stores an unallocated decrease; the movement sign "
                    "is negative in this ledger.",
                ],
            )
        )
    unallocated_decrease = _number(payload.get("unallocated_company_cash_decrease"))
    residual = None if unallocated_decrease is None else -unallocated_decrease
    identity_verified = (
        final - (initial + revenue - capex) == residual
        if None not in (final, initial, revenue, capex, residual)
        else None
    )
    statements.append(
        ReconciliationStatement(
            statement_id="recon-batch-window",
            period="serial batch window",
            scope="network",
            equation=(
                "final_cash = initial_cash + freight_revenue "
                "- command_construction_purchase_costs + unknown_residual"
            ),
            terms=[
                ReconciliationTerm(
                    term_id="initial_cash",
                    role="OPENING_CASH",
                    category=CATEGORY_INITIAL_CASH,
                    amount_gbp=initial,
                    status="OBSERVED" if initial is not None else "UNKNOWN",
                    source=f"{source_ref} initial_cash",
                ),
                ReconciliationTerm(
                    term_id="freight_revenue",
                    role="INFLOW",
                    category=CATEGORY_REVENUE,
                    amount_gbp=revenue,
                    status="OBSERVED" if revenue is not None else "UNKNOWN",
                    source=f"{source_ref} freight_revenue",
                ),
                ReconciliationTerm(
                    term_id="construction_and_vehicle_capex",
                    role="OUTFLOW",
                    category=CATEGORY_CAPEX_UNSPLIT,
                    amount_gbp=-capex if capex is not None else None,
                    status="OBSERVED" if capex is not None else "UNKNOWN",
                    source=f"{source_ref} command_construction_purchase_costs",
                ),
                ReconciliationTerm(
                    term_id="vehicle_operating_expenses",
                    role="UNKNOWN_TERM",
                    category=CATEGORY_OPEX_VEHICLE_RUNNING,
                    amount_gbp=None,
                    status="UNKNOWN",
                    source=f"{source_ref} operating_costs=None",
                ),
                ReconciliationTerm(
                    term_id="closing_cash",
                    role="CLOSING_CASH",
                    category=CATEGORY_INITIAL_CASH,
                    amount_gbp=final,
                    status="OBSERVED" if final is not None else "UNKNOWN",
                    source=f"{source_ref} final_cash",
                ),
                ReconciliationTerm(
                    term_id="unknown_residual",
                    role="RESIDUAL",
                    category=CATEGORY_UNATTRIBUTED,
                    amount_gbp=residual,
                    status="UNKNOWN" if residual is None else "DERIVED",
                    source=f"{source_ref} unallocated_company_cash_decrease (sign normalized)",
                ),
            ],
            residual_gbp=residual,
            residual_is_zero=None if residual is None else residual == 0,
            identity_verified=identity_verified,
            notes=[
                "The batch window spans construction and delivery; CAPEX is inside "
                "this window per the retained native reconciliation.",
                "The unattributed residual is not an expense category and never becomes profit.",
            ],
        )
    )
    return statements


# ---------------------------------------------------------------------------
# Period rows
# ---------------------------------------------------------------------------


def _period_rows(document: dict) -> list[PeriodFinancialRow]:
    rows: list[PeriodFinancialRow] = []
    previous_annual: PeriodFinancialRow | None = None
    for row in document.get("periods") or []:
        if row.get("scope") != "network":
            continue
        revenue = _number(row.get("revenue"))
        aggregate = _number(row.get("known_unallocated_expenses"))
        growth = None
        if (
            row.get("period") == "annual"
            and previous_annual is not None
            and revenue is not None
            and previous_annual.revenue_gbp not in (None, 0)
        ):
            growth = round((revenue - previous_annual.revenue_gbp) / previous_annual.revenue_gbp, 6)
        current = PeriodFinancialRow(
            period=f"{row['period']}-{row['index']}",
            kind=str(row["period"]),
            index=int(row["index"]),
            scope="network",
            start_economy_date=int(row["start_economy_date"]),
            end_economy_date=int(row["end_economy_date"]),
            elapsed_economy_days=_number(row.get("elapsed_economy_days")),
            revenue_gbp=revenue,
            observed_aggregate_expenses_gbp=aggregate,
            vehicle_operating_expenses_gbp=_number(row.get("vehicle_operating_expenses")),
            revenue_growth_vs_previous=growth,
            coverage=(
                "PARTIAL_ATTRIBUTION"
                if revenue is not None and aggregate is not None
                else "INSUFFICIENT_DATA"
            ),
        )
        rows.append(current)
        if row.get("period") == "annual":
            previous_annual = current
    return rows


# ---------------------------------------------------------------------------
# Continuous builder
# ---------------------------------------------------------------------------


def _continuous_services(
    document: dict, receipts: tuple[tuple[Path, dict], ...]
) -> list[ServiceAttribution]:
    heads = (document.get("snapshots") or [{}])[0].get("services") or []
    receipt_by_index = {index: receipt for index, (_, receipt) in enumerate(receipts)}
    services: list[ServiceAttribution] = []
    for index, head in enumerate(heads):
        scope = str(head.get("route_id") or f"service-{index + 1}")
        receipt = receipt_by_index.get(index)
        if receipt is not None:
            _, vehicle, total = _receipt_capex(receipt)
            road, facility, other = _kind_split(receipt)
            revenue = _number(receipt.get("payment_income"))
            profit = _number(receipt.get("vehicle_profit_delta"))
            categories: dict[str, int | float | None] = {
                CATEGORY_CAPEX_ROAD: road,
                CATEGORY_CAPEX_FACILITY: facility,
                CATEGORY_CAPEX_OTHER: other,
                CATEGORY_CAPEX_VEHICLE: vehicle,
            }
            missing = (
                ["Per-service revenue counters are not retained (continuous shape)."]
                if revenue is None
                else []
            )
        else:
            total = road = facility = other = revenue = profit = None
            categories = {category: None for category in CAPEX_CATEGORIES}
            missing = ["Retained per-service construction/purchase receipt."]
        missing.append("Retained operating-expense attribution for this service's window.")
        services.append(
            ServiceAttribution(
                scope=scope,
                label=f"Service {index + 1}",
                capex_gbp=total,
                capex_status="OBSERVED" if total is not None else "UNKNOWN",
                capex_categories=categories,
                revenue_gbp=revenue,
                revenue_status="OBSERVED" if revenue is not None else "UNKNOWN",
                vehicle_profit_delta_gbp=profit,
                vehicle_profit_status="OBSERVED" if profit is not None else "UNKNOWN",
                operating_expenses_status="UNKNOWN",
                missing=missing,
            )
        )
    return services


def build_continuous_attribution(
    document: dict,
    *,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
    receipts: tuple[tuple[Path, dict], ...] = (),
    capital_gift: int | float | None = None,
) -> FinancialAttribution:
    """Build financial attribution from a P07 continuous summary document."""
    finance = document.get("finance") or {}
    setup = document.get("setup_cash_coverage") or {}
    source = f"{source_ref} finance reconciliation"
    ledger: list[LedgerEntry] = [
        _entry(
            CATEGORY_REVENUE,
            "network",
            _number(finance.get("freight_revenue")),
            "OBSERVED",
            "operating window",
            source,
            "Retained company quarter-income deltas attributed to freight delivery.",
            "UNKNOWN when no revenue counter was retained; UNKNOWN is never zero.",
            "Gross company income, not profit.",
        ),
        _entry(
            CATEGORY_EXPENSE_AGGREGATE,
            "network",
            -_number(finance.get("known_unallocated_expenses"))
            if _number(finance.get("known_unallocated_expenses")) is not None
            else None,
            "OBSERVED",
            "operating window",
            source,
            "Retained company quarterly expense aggregate (vehicle running costs, "
            "property and loan interest as one counter), normalized to a signed "
            "outflow.",
            "UNKNOWN when no expense counters were retained.",
            "Category split is unavailable through the read API; the counter is an "
            "aggregate, not attributed OPEX.",
        ),
        _loan_movement_entry(finance, "operating window", source),
        _entry(
            CATEGORY_UNATTRIBUTED,
            "network",
            _operating_identity(finance)[0],
            "DERIVED",
            "operating window",
            source,
            "Residual of the pinned reconcile_cash identity over the retained "
            "cash terms; prefers the retained unknown_cash_movements field and "
            "recomputes from retained terms only when the field is absent.",
            "UNKNOWN when the identity cannot be evaluated.",
            "Not renamed into an expense category; not profit.",
        ),
    ]
    ledger.extend(
        _entry(
            category,
            "network",
            None,
            "UNKNOWN",
            "operating window",
            source,
            "Not independently attributable in the retained evidence.",
            "UNKNOWN; never inferred from aggregate counters or residual cash.",
            "Missing native category observation.",
        )
        for category in OPEX_CATEGORIES
    )
    setup_unattributed = _number(setup.get("unattributed_setup_cash_decrease"))
    if setup_unattributed not in (None, 0):
        ledger.append(
            _entry(
                CATEGORY_UNATTRIBUTED,
                "network",
                -setup_unattributed,
                "DERIVED",
                "setup window",
                f"{source_ref} setup_cash_coverage.unattributed_setup_cash_decrease",
                "Unexplained setup-window cash decrease after funding, construction "
                "CAPEX and measured setup expenses; the retained decrease magnitude "
                "is signed negative as a cash movement.",
                "UNKNOWN when the retained setup coverage lacks the amount.",
                "Not an expense category; not profit; excluded from operating-window deltas.",
            )
        )
    ledger.extend(
        _capital_entries(capital_gift, f"{source_ref} capital readback", setup.get("funding_cash"))
    )
    if receipts:
        capex_entries, services = _receipt_entries(receipts, source_ref)
        ledger.extend(capex_entries)
    else:
        services = _continuous_services(document, receipts)
        setup_capex = _number(setup.get("construction_capex"))
        ledger.append(
            _entry(
                CATEGORY_CAPEX_UNSPLIT,
                "network",
                -setup_capex if setup_capex is not None else None,
                "OBSERVED",
                "setup window",
                f"{source_ref} setup_cash_coverage.construction_capex",
                "Construction and vehicle purchase CAPEX combined; road/facility "
                "split requires retained per-service receipts.",
                "UNKNOWN when the setup coverage is absent.",
            )
        )
    statements: list[ReconciliationStatement] = []
    setup_statement = _setup_statement(setup, capital_gift, source_ref)
    if setup_statement is not None:
        statements.append(setup_statement)
    statements.append(
        _operating_statement(finance, "operating window", source, "recon-operating-window")
    )
    revenue = _number(finance.get("freight_revenue"))
    closing_cash = _number(finance.get("closing_cash"))
    opening_cash = _number(finance.get("opening_cash"))
    residual = _operating_identity(finance)[0]
    coverage = [
        CoverageIndicator(
            indicator="expense_classification_complete",
            value=finance.get("expense_classification_complete"),
            status=(
                "OBSERVED"
                if finance.get("expense_classification_complete") is not None
                else "UNKNOWN"
            ),
            detail="Retained finance reconciliation completeness flag.",
        ),
        CoverageIndicator(
            indicator="capex_category_separation",
            value="ROAD_FACILITY_VEHICLE" if receipts else "UNKNOWN",
            status="OBSERVED" if receipts else "UNKNOWN",
            detail="Road/facility/vehicle split from retained per-service receipts.",
        ),
        CoverageIndicator(
            indicator="per_service_capex_attribution",
            value=(
                "OBSERVED" if any(s.capex_status == "OBSERVED" for s in services) else "UNKNOWN"
            ),
            status="DERIVED",
            detail="Per-service construction and purchase amounts from retained receipts.",
        ),
        CoverageIndicator(
            indicator="per_service_revenue_attribution",
            value=(
                "OBSERVED"
                if services and all(s.revenue_status == "OBSERVED" for s in services)
                else "UNKNOWN"
            ),
            status="DERIVED" if services else "UNKNOWN",
            detail=(
                "Per-service payment income from the retained receipts."
                if services and all(s.revenue_status == "OBSERVED" for s in services)
                else "Continuous observation retains no per-service revenue counter; "
                "company income stays at network level."
            ),
        ),
        CoverageIndicator(
            indicator="unattributed_cash_movement_gbp",
            value=residual,
            status="DERIVED" if residual is not None else "UNKNOWN",
            detail="Operating-window residual; UNKNOWN when the identity is incomplete.",
        ),
        CoverageIndicator(
            indicator="unattributed_fraction_of_gross_inflows",
            value=(
                round(abs(residual) / revenue, 6)
                if residual is not None and revenue not in (None, 0)
                else None
            ),
            status="DERIVED",
            detail="Descriptive exposure of the residual against retained revenue.",
        ),
        CoverageIndicator(
            indicator="service_receipts_retained",
            value=f"{len(receipts)} of {len(services)}" if services else "ABSENT",
            status="OBSERVED" if receipts else "UNKNOWN",
            detail="Retained per-service receipt files discoverable read-only.",
        ),
        CoverageIndicator(
            indicator="net_cash_flow_gbp",
            value=(
                closing_cash - opening_cash if None not in (closing_cash, opening_cash) else None
            ),
            status="DERIVED",
            detail="Closing minus opening cash over the operating window.",
        ),
    ]
    return FinancialAttribution(
        schema_version=SCHEMA_VERSION,
        classification=_classify(ledger, statements),
        source_kind="continuous",
        source_ref=source_ref,
        source_sha256=source_sha256,
        native_terminal_status=_native_terminal(document),
        world_identity=world_identity,
        ledger=_final_entries(ledger),
        reconciliations=statements,
        services=services,
        coverage=coverage,
        period_rows=_period_rows(document),
        claims=_claims(),
        limitations=_limitations(document),
    )


# ---------------------------------------------------------------------------
# Network-evaluation builder (fixed demo)
# ---------------------------------------------------------------------------


def _network_services(document: dict) -> list[ServiceAttribution]:
    services = []
    for position, service in enumerate(document.get("services") or [], 1):
        metrics = {metric["name"]: metric for metric in service.get("metrics") or []}

        def actual(name: str, metrics=metrics):
            row = metrics.get(name)
            return _number(row.get("actual")) if row is not None else None

        capex = actual("total_capex")
        purchase = actual("vehicle_purchase")
        exclusive_infrastructure = actual("exclusive_infrastructure_capex")
        revenue = actual("delivery_revenue")
        profit = actual("vehicle_profit")
        missing = ["Retained operating-expense attribution for this service's window."]
        if capex is None:
            missing.append("Retained per-service CAPEX metrics.")
        services.append(
            ServiceAttribution(
                scope=str(service.get("route_id") or f"service-{position}"),
                label=f"Service {position}",
                capex_gbp=capex,
                capex_status="OBSERVED" if capex is not None else "UNKNOWN",
                capex_categories={
                    CATEGORY_CAPEX_UNSPLIT: exclusive_infrastructure,
                    CATEGORY_CAPEX_VEHICLE: purchase,
                },
                revenue_gbp=revenue,
                revenue_status="OBSERVED" if revenue is not None else "UNKNOWN",
                vehicle_profit_delta_gbp=profit,
                vehicle_profit_status="OBSERVED" if profit is not None else "UNKNOWN",
                operating_expenses_status="UNKNOWN",
                missing=missing,
            )
        )
    return services


def build_network_attribution(
    document: dict,
    *,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
    native_reconciliation: dict | None = None,
    capital_gift: int | float | None = None,
) -> FinancialAttribution:
    """Build financial attribution from a P07 network evaluation document."""
    metrics = {metric["name"]: metric for metric in document.get("metrics") or []}

    def actual(name: str):
        row = metrics.get(name)
        return _number(row.get("actual")) if row is not None else None

    revenue = actual("delivery_revenue")
    infrastructure = actual("infrastructure_capex")
    vehicle_purchase = actual("vehicle_purchase")
    total_capex = actual("total_capex")
    operating_costs = actual("operating_costs")
    source = f"{source_ref} metrics"
    ledger: list[LedgerEntry] = [
        _entry(
            CATEGORY_REVENUE,
            "network",
            revenue,
            "OBSERVED",
            "serial batch window",
            source,
            "Retained verified delivery payment income.",
            "UNKNOWN when the revenue counter was not retained.",
            "Batch revenue, not profit.",
        ),
        _entry(
            CATEGORY_CAPEX_UNSPLIT,
            "network",
            -infrastructure if infrastructure is not None else None,
            "OBSERVED",
            "setup window",
            source,
            "Verified infrastructure construction CAPEX (road and facility commands "
            "combined; per-command kinds are not part of this document).",
            "UNKNOWN when the metric was not retained.",
        ),
        _entry(
            CATEGORY_CAPEX_VEHICLE,
            "network",
            -vehicle_purchase if vehicle_purchase is not None else None,
            "OBSERVED",
            "setup window",
            source,
            "Verified vehicle purchase CAPEX.",
            "UNKNOWN when the metric was not retained.",
        ),
        _entry(
            CATEGORY_EXPENSE_AGGREGATE,
            "network",
            -operating_costs if operating_costs is not None else None,
            "OBSERVED",
            "serial batch window",
            source,
            "Retained operating-costs aggregate, normalized to a signed outflow.",
            "UNKNOWN when the operating_costs metric is absent.",
            "Category split is not retained; the aggregate is not attributed OPEX.",
        ),
        _entry(
            CATEGORY_OPEX_VEHICLE_RUNNING,
            "network",
            None,
            "UNKNOWN",
            "serial batch window",
            source,
            (
                "The retained evaluation records operating_costs=None."
                if operating_costs is None
                else "Operating costs are retained only as an aggregate; the "
                "category split is unavailable."
            ),
            "UNKNOWN; unknown is not zero.",
        ),
        _entry(
            CATEGORY_OPEX_LOAN_INTEREST,
            "network",
            None,
            "UNKNOWN",
            "serial batch window",
            source,
            "Not retained in the batch evaluation.",
            "UNKNOWN; unknown is not zero.",
        ),
        _entry(
            CATEGORY_OPEX_PROPERTY,
            "network",
            None,
            "UNKNOWN",
            "serial batch window",
            source,
            "Not retained in the batch evaluation.",
            "UNKNOWN; unknown is not zero.",
        ),
    ]
    if native_reconciliation is not None:
        ledger.extend(
            _capital_entries(
                capital_gift,
                f"{source_ref} native reconciliation",
                native_reconciliation.get("funded_cash"),
            )
        )
        ledger.extend(_native_unattributed_entries(native_reconciliation, source_ref))
    statements = (
        _native_reconciliation_statements(native_reconciliation, source_ref)
        if native_reconciliation is not None
        else []
    )
    services = _network_services(document)
    service_capex_sum = (
        sum(s.capex_categories[CATEGORY_CAPEX_UNSPLIT] or 0 for s in services)
        if services
        and all(s.capex_categories[CATEGORY_CAPEX_UNSPLIT] is not None for s in services)
        else None
    )
    shared_infrastructure = (
        infrastructure - service_capex_sum
        if infrastructure is not None and service_capex_sum is not None
        else None
    )
    service_revenue_sum = (
        sum(s.revenue_gbp for s in services)
        if services and all(s.revenue_gbp is not None for s in services)
        else None
    )
    coverage = [
        CoverageIndicator(
            indicator="capex_category_separation",
            value=(
                "INFRASTRUCTURE_VEHICLE"
                if infrastructure is not None and vehicle_purchase is not None
                else "UNKNOWN"
            ),
            status=(
                "OBSERVED"
                if infrastructure is not None and vehicle_purchase is not None
                else "UNKNOWN"
            ),
            detail="Infrastructure versus vehicle purchase split from verified metrics.",
        ),
        CoverageIndicator(
            indicator="capex_split_consistency",
            value=(
                infrastructure + vehicle_purchase == total_capex
                if None not in (infrastructure, vehicle_purchase, total_capex)
                else None
            ),
            status="DERIVED",
            detail="Infrastructure + vehicle purchase must equal retained total CAPEX.",
        ),
        CoverageIndicator(
            indicator="shared_infrastructure_capex_gbp",
            value=shared_infrastructure,
            status="DERIVED",
            detail="Network infrastructure CAPEX minus the sum of per-service "
            "exclusive infrastructure CAPEX; negative results flag inconsistent "
            "exclusivity accounting and are never reclassified.",
        ),
        CoverageIndicator(
            indicator="per_service_revenue_attribution",
            value=(
                "OBSERVED"
                if services and all(s.revenue_status == "OBSERVED" for s in services)
                else "UNKNOWN"
            ),
            status="DERIVED",
            detail="Per-service payment income from the retained batch receipts.",
        ),
        CoverageIndicator(
            indicator="per_service_revenue_sums_to_network",
            value=(
                service_revenue_sum == revenue
                if revenue is not None and service_revenue_sum is not None
                else None
            ),
            status="DERIVED",
            detail="Sum of retained per-service payment income versus network revenue.",
        ),
        CoverageIndicator(
            indicator="expense_classification_complete",
            value=False if operating_costs is None else None,
            status="OBSERVED" if operating_costs is None else "UNKNOWN",
            detail="The retained evaluation records operating_costs=None.",
        ),
        CoverageIndicator(
            indicator="unattributed_cash_movement_gbp",
            value=(
                -_number(native_reconciliation["unallocated_company_cash_decrease"])
                if native_reconciliation is not None
                and native_reconciliation.get("unallocated_company_cash_decrease") is not None
                else None
            ),
            status="DERIVED",
            detail="From the retained native financial reconciliation (native record "
            "stores an unallocated decrease; movement sign is negative here).",
        ),
    ]
    return FinancialAttribution(
        schema_version=SCHEMA_VERSION,
        classification=_classify(ledger, statements),
        source_kind="network-evaluation",
        source_ref=source_ref,
        source_sha256=source_sha256,
        native_terminal_status=None,
        world_identity=world_identity,
        ledger=_final_entries(ledger),
        reconciliations=statements,
        services=services,
        coverage=coverage,
        period_rows=[],
        claims=_claims(),
        limitations=_limitations(document),
    )


def _native_unattributed_entries(payload: dict, source_ref: str) -> list[LedgerEntry]:
    """Unattributed cash movements from the retained native reconciliation."""
    entries: list[LedgerEntry] = []
    admission = _number(payload.get("funding_to_admission_unallocated_cash_decrease"))
    if admission not in (None, 0):
        entries.append(
            _entry(
                CATEGORY_UNATTRIBUTED,
                "network",
                -admission,
                "DERIVED",
                "funding-to-admission window",
                f"{source_ref} funding_to_admission_unallocated_cash_decrease",
                "Unexplained decrease between the funded balance and the admission "
                "readback; sign normalized to a negative movement.",
                "UNKNOWN when the native record lacks the amount.",
                "Not an expense category; not profit.",
            )
        )
    unallocated = _number(payload.get("unallocated_company_cash_decrease"))
    if unallocated not in (None, 0):
        entries.append(
            _entry(
                CATEGORY_UNATTRIBUTED,
                "network",
                -unallocated,
                "DERIVED",
                "serial batch window",
                f"{source_ref} unallocated_company_cash_decrease",
                "Residual of the native batch-window cash identity; sign normalized "
                "to a negative movement.",
                "UNKNOWN when the native record lacks the amount.",
                "Not an expense category; not profit.",
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Shared assembly
# ---------------------------------------------------------------------------


def _native_terminal(document: dict) -> str | None:
    recovery = document.get("offline_recovery")
    if recovery is None:
        return None
    status = (recovery.get("original_terminal") or {}).get("status")
    if status:
        return f"{status} (historical native terminal; metadata derived offline)"
    return "historical native terminal status UNKNOWN (metadata derived offline)"


def _classify(ledger: list[LedgerEntry], statements: list[ReconciliationStatement]) -> str:
    observed = [entry for entry in ledger if entry.status in {"OBSERVED", "DERIVED"}]
    opex_unknown = (
        all(entry.status == "UNKNOWN" for entry in ledger if entry.category in OPEX_CATEGORIES)
        if any(entry.category in OPEX_CATEGORIES for entry in ledger)
        else True
    )
    residual_zero = (
        all(statement.residual_is_zero is not False for statement in statements)
        if statements
        else True
    )
    if observed and residual_zero and not opex_unknown:
        return CLASSIFICATION_COMPLETE
    if observed:
        return CLASSIFICATION_PARTIAL
    return CLASSIFICATION_NO_EVIDENCE


def _claims() -> list[AttributionClaim]:
    reasons = {
        "operating_profit": (
            "Operating expenses are not attributed by category and the observed "
            "unattributed cash residual is nonzero; revenue minus an incomplete "
            "cost subset would invent profit."
        ),
        "net_profit": (
            "Requires operating profit plus complete financing attribution "
            "(loan interest and any other engine movements); both are missing."
        ),
        "roi": (
            "Requires complete operating expenses and a verifiable residual asset "
            "value; neither is retained."
        ),
        "payback_period": (
            "Requires an attributed operating-cash-flow series over the full "
            "horizon; retained evidence has no attributed expense series."
        ),
        "cost_per_cargo_unit": (
            "Requires attributed operating expenses over the same window as the "
            "retained delivered-cargo counter; attribution is missing."
        ),
        "service_profitability": (
            "Batch receipts bind per-service revenue, but no per-service operating "
            "expense attribution exists; continuous evidence lacks per-service "
            "revenue entirely."
        ),
        "network_financial_efficiency": (
            "Requires revenue and complete attributed costs over matched windows; "
            "the expense aggregate is unallocated and residuals are nonzero."
        ),
    }
    return [
        AttributionClaim(
            metric=metric,
            status="UNSUPPORTED",
            reason=reasons[metric],
            required_observations=list(_REQUIRED_NATIVE_OBSERVATIONS),
        )
        for metric in CLAIM_METRICS
    ]


def _limitations(document: dict) -> list[str]:
    rows = [
        "Attribution consumes already-verified P07 documents; verification is not repeated.",
        UNKNOWN_NOTE,
        "Unattributed cash residuals are never classified as expenses or profit.",
        "Aggregate expense counters are company-level signed sums; the read API "
        "cannot split vehicle running costs, property and loan interest.",
    ]
    if document.get("offline_recovery") is not None:
        rows.append(
            "Historical native attempt terminal status is preserved separately; "
            "offline recovery never re-labels it."
        )
    return rows


def build_financial_attribution(
    document: dict,
    *,
    source_kind: str | None = None,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
    receipts: tuple[tuple[Path, dict], ...] = (),
    native_reconciliation: dict | None = None,
    capital_gift: int | float | None = None,
) -> FinancialAttribution:
    """Dispatch on the detected P07 document shape."""
    if source_kind is None:
        if document.get("snapshots"):
            source_kind = "continuous"
        elif document.get("services") or document.get("metrics"):
            source_kind = "network-evaluation"
        else:
            raise ValueError("document is neither a continuous summary nor a network evaluation")
    if source_kind == "continuous":
        return build_continuous_attribution(
            document,
            source_ref=source_ref,
            source_sha256=source_sha256,
            world_identity=world_identity,
            receipts=receipts,
            capital_gift=capital_gift,
        )
    if source_kind == "network-evaluation":
        return build_network_attribution(
            document,
            source_ref=source_ref,
            source_sha256=source_sha256,
            world_identity=world_identity,
            native_reconciliation=native_reconciliation,
            capital_gift=capital_gift,
        )
    raise ValueError(f"unknown source kind: {source_kind}")


def compact_status(document: dict) -> dict:
    """Compact attribution status over the passed document alone.

    Used by performance insights to expose financial attribution status inside
    its structured reports. Reads no evidence directories; per-service amounts
    come only from the passed document itself.
    """
    if document.get("snapshots"):
        finance = document.get("finance") or {}
        revenue = _number(finance.get("freight_revenue"))
        capex = _number(finance.get("capex"))
        aggregate = _number(finance.get("known_unallocated_expenses"))
        residual = _number(finance.get("unknown_cash_movements"))
        opex = _number(finance.get("vehicle_operating_expenses"))
        services = (document.get("snapshots") or [{}])[0].get("services") or []
        service_revenue_known = False
    elif document.get("services") or document.get("metrics"):
        metrics = {metric["name"]: metric for metric in document.get("metrics") or []}

        def actual(name):
            row = metrics.get(name)
            return _number(row.get("actual")) if row is not None else None

        revenue, capex = actual("delivery_revenue"), actual("total_capex")
        aggregate = None
        residual = None
        opex = actual("operating_costs")
        services = document.get("services") or []
        service_revenue_known = any(
            _number(
                next(
                    (
                        metric.get("actual")
                        for metric in service.get("metrics", [])
                        if metric["name"] == "delivery_revenue"
                    ),
                    None,
                )
            )
            is not None
            for service in services
        )
    else:
        raise ValueError("document is neither a continuous summary nor a network evaluation")
    observed = {
        name: amount
        for name, amount in (
            ("freight_revenue", revenue),
            ("capex", capex),
            ("aggregate_expenses", aggregate),
        )
        if amount is not None
    }
    return dict(
        classification=(CLASSIFICATION_PARTIAL if observed else CLASSIFICATION_NO_EVIDENCE),
        expense_classification_complete=None if opex is None else False,
        observed_amounts_gbp=observed,
        unknown_categories=list(OPEX_CATEGORIES) if opex is None else [],
        unattributed_cash_gbp=residual,
        per_service_revenue_status="OBSERVED" if service_revenue_known else "UNKNOWN",
        missing_for_profit_metrics=list(CLAIM_METRICS) if observed else [],
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_attribution_summary(attribution: FinancialAttribution) -> str:
    """Concise offline financial attribution summary; UNKNOWN stays visible."""
    observed = [entry for entry in attribution.ledger if entry.status in {"OBSERVED", "DERIVED"}]
    unknown = [entry for entry in attribution.ledger if entry.status == "UNKNOWN"]
    amounts = ", ".join(f"{entry.category} {_fmt(entry.amount_gbp)}" for entry in observed)
    lines = [
        f"P07 FINANCIAL ATTRIBUTION - {attribution.classification}",
        f"Source: {attribution.source_kind} {attribution.source_ref}"
        + (f" (sha256 {attribution.source_sha256[:12]}...)" if attribution.source_sha256 else ""),
        f"Ledger: {len(attribution.ledger)} entries "
        f"({len(observed)} OBSERVED/DERIVED, {len(unknown)} UNKNOWN)",
        "Ledger amounts: " + (amounts if amounts else "none observed"),
    ]
    residual_rows = [
        entry.amount_gbp
        for entry in attribution.ledger
        if entry.category == CATEGORY_UNATTRIBUTED and entry.amount_gbp is not None
    ]
    if residual_rows:
        lines.append(
            "Unattributed cash movements: "
            + ", ".join(_fmt(amount) for amount in residual_rows)
            + " GBP (residuals are never classified as expenses)"
        )
    for statement in attribution.reconciliations:
        lines.append(
            f"Reconciliation {statement.statement_id}: residual "
            f"{_fmt(statement.residual_gbp)} GBP (zero={_fmt(statement.residual_is_zero)}, "
            f"identity_verified={_fmt(statement.identity_verified)})"
        )
    for service in attribution.services:
        lines.append(
            f"  {service.label}: capex {_fmt(service.capex_gbp)} GBP "
            f"[{service.capex_status}], revenue {_fmt(service.revenue_gbp)} GBP "
            f"[{service.revenue_status}], operating expenses UNKNOWN"
        )
    lines.append(
        f"Period rows: {len(attribution.period_rows)} "
        "(period-based comparisons over observed aggregates only)"
    )
    lines.append(
        "Claims: " + ", ".join(claim.metric for claim in attribution.claims) + " — all UNSUPPORTED"
    )
    lines.append("Limitations apply; see financial-attribution.md. UNKNOWN is not zero.")
    return "\n".join(lines)


def render_attribution_markdown(attribution: FinancialAttribution) -> str:
    """Human-readable Markdown mirroring the machine-readable document."""
    lines = [
        f"# P07 financial attribution - {attribution.classification}",
        "",
        f"*Source*: `{attribution.source_kind}` `{attribution.source_ref}`"
        + (
            f" · canonical sha256 `{attribution.source_sha256}`"
            if attribution.source_sha256
            else ""
        ),
    ]
    if attribution.native_terminal_status:
        lines += [
            f"*Native terminal status*: {attribution.native_terminal_status}. Offline "
            "recovery provenance is separate and never re-labels the consumed attempt."
        ]
    if attribution.world_identity:
        identity = ", ".join(f"{k}={v}" for k, v in attribution.world_identity.items())
        lines += [f"*World identity*: {identity}"]
    lines += [
        "",
        "## Normalized financial ledger",
        "",
        "| Entry | Category | Scope | Amount GBP | Status |",
        "|---|---|---|---:|---|",
    ]
    for entry in attribution.ledger:
        scope = entry.scope if len(entry.scope) <= 36 else entry.scope[:36] + "…"
        lines.append(
            f"| `{entry.entry_id}` | `{entry.category}` | `{scope}` "
            f"| {_fmt(entry.amount_gbp)} | {entry.status} |"
        )
    lines += [
        "",
        "Every entry declares unit, period, source, derivation and missing-data "
        f"behaviour in `financial-attribution.json`; {UNKNOWN_NOTE}",
        "",
        "## Company reconciliation statements",
        "",
    ]
    for statement in attribution.reconciliations:
        lines += [
            f"### {statement.statement_id} ({statement.period})",
            "",
            f"- equation: `{statement.equation}`",
            f"- residual: {_fmt(statement.residual_gbp)} GBP "
            f"(zero={_fmt(statement.residual_is_zero)}, "
            f"identity_verified={_fmt(statement.identity_verified)})",
            "- terms: "
            + "; ".join(
                f"{term.term_id}={_fmt(term.amount_gbp)} [{term.status}/{term.role}]"
                for term in statement.terms
            ),
        ]
        lines += [f"- note: {note}" for note in statement.notes]
    lines += ["", "## Per-service attribution", ""]
    if attribution.services:
        lines += [
            "| Service | CAPEX GBP | CAPEX status | Revenue GBP | Revenue status | "
            "Vehicle profit delta GBP | Operating expenses |",
            "|---|---:|---|---:|---|---:|---|",
        ]
        for service in attribution.services:
            lines.append(
                f"| {service.label} | {_fmt(service.capex_gbp)} | {service.capex_status} "
                f"| {_fmt(service.revenue_gbp)} | {service.revenue_status} "
                f"| {_fmt(service.vehicle_profit_delta_gbp)} | UNKNOWN |"
            )
    else:
        lines.append("No per-service financial attribution is supported by the retained evidence.")
    lines += [
        "",
        "## Coverage and completeness",
        "",
        "| Indicator | Value | Status |",
        "|---|---|---|",
    ]
    for indicator in attribution.coverage:
        lines.append(f"| `{indicator.indicator}` | {_fmt(indicator.value)} | {indicator.status} |")
    lines += ["", "## Period-based financial rows", ""]
    if attribution.period_rows:
        lines += [
            "| Period | Window | Days | Revenue GBP | Aggregate expenses GBP | "
            "Revenue growth vs previous | Coverage |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
        for row in attribution.period_rows:
            lines.append(
                f"| {row.period} | {row.start_economy_date}..{row.end_economy_date} "
                f"| {_fmt(row.elapsed_economy_days)} | {_fmt(row.revenue_gbp)} "
                f"| {_fmt(row.observed_aggregate_expenses_gbp)} "
                f"| {_fmt(row.revenue_growth_vs_previous)} | {row.coverage} |"
            )
        lines += [
            "",
            "Vehicle operating expenses per period remain UNKNOWN; revenue growth is "
            "a descriptive delta, not a forecast and not profit.",
        ]
    else:
        lines.append("No period rows: batch evaluations retain endpoint measurements only.")
    lines += ["", "## Profitability claims (all UNSUPPORTED)", ""]
    for claim in attribution.claims:
        lines += [
            f"### {claim.metric}",
            "",
            f"- status: {claim.status}",
            f"- reason: {claim.reason}",
            "- required native observations: " + "; ".join(claim.required_observations),
        ]
    lines += ["", "## Limitations", ""]
    lines += [f"- {text}" for text in attribution.limitations]
    lines += [
        "",
        "Generated offline from existing P07 artifacts; no native launch, connection "
        "or claim. UNKNOWN is not zero.",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Pipeline over retained report directories
# ---------------------------------------------------------------------------


def analyze_financial_attribution(
    source: Path, output: Path, *, compare: tuple[Path, ...] = ()
) -> dict:
    """Build one attribution document (plus optional comparison) into the output.

    Retained evidence directories are read-only and never written to; the guard
    covers the passed sources and retained directories referenced inside the
    documents themselves.
    """
    from app.experiments.performance_insights import (
        _load_report,
        _world_identity,
        build_performance_insights,
        compare_performance_rows,
        comparison_row,
    )

    report_sources = tuple(report.resolve() for report in (source, *compare))
    destinations = [
        output.resolve(),
        *(output.resolve() / name for name in OUTPUT_NAMES),
    ]
    loaded = []
    referenced_roots: list[Path] = []
    for report_source in report_sources:
        document, kind, document_ref, digest = _load_report(report_source)
        loaded.append((report_source, document, kind, document_ref, digest))
        for referenced in (
            (document.get("offline_recovery") or {}).get("original_directory"),
            document.get("evidence_directory"),
        ):
            if referenced:
                candidate = Path(referenced)
                candidate = candidate if candidate.is_absolute() else report_source / candidate
                referenced_roots.append(candidate)
    try:
        roots = [root.resolve() for root in (*report_sources, *referenced_roots)]
    except OSError:
        roots = list(report_sources)
    if any(target.is_relative_to(root) for root in roots for target in destinations):
        raise ValueError("attribution output must not modify retained evidence")
    attributions = []
    for report_source, document, kind, document_ref, digest in loaded:
        evidence_roots = _evidence_roots(report_source, document)
        receipts = tuple((path, _read_json(path)) for path in discover_receipts(evidence_roots))
        attribution = build_financial_attribution(
            document,
            source_kind=kind,
            source_ref=document_ref,
            source_sha256=digest,
            world_identity=_world_identity(report_source, document),
            receipts=receipts,
            native_reconciliation=read_native_reconciliation(evidence_roots),
            capital_gift=read_capital_gift(evidence_roots),
        )
        attributions.append(attribution)
    comparison = None
    if len(attributions) > 1:
        insights_rows = []
        for report_source, document, kind, document_ref, digest in loaded:
            insights = build_performance_insights(
                document,
                source_kind=kind,
                source_ref=document_ref,
                source_sha256=digest,
                world_identity=_world_identity(report_source, document),
            )
            insights_rows.append(comparison_row(insights, run_id=report_source.name))
        insights_comparison = compare_performance_rows(insights_rows)
        statuses = {row["run_id"]: row["status"] for row in insights_comparison["rows"]}

        def ledger_amount(attribution, category, *, negate=False):
            return next(
                (
                    -entry.amount_gbp if negate else entry.amount_gbp
                    for entry in attribution.ledger
                    if entry.category == category
                    and entry.scope == "network"
                    and entry.amount_gbp is not None
                ),
                None,
            )

        def capex_total(attribution):
            amounts = [
                -entry.amount_gbp
                for entry in attribution.ledger
                if entry.category in CAPEX_CATEGORIES and entry.amount_gbp is not None
            ]
            return sum(amounts) if amounts and all(a is not None for a in amounts) else None

        def unattributed_total(attribution):
            amounts = [
                entry.amount_gbp
                for entry in attribution.ledger
                if entry.category == CATEGORY_UNATTRIBUTED and entry.amount_gbp is not None
            ]
            return sum(amounts) if amounts else None

        comparison = dict(
            schema_version=SCHEMA_VERSION,
            classification=insights_comparison["classification"],
            policy=(
                "Descriptive financial comparison only; matched worlds share a "
                "retained recipe and causality is never claimed. Financial "
                "attribution completeness and residuals are reported per run. "
                "unattributed_cash_gbp sums per-window unattributed movements; "
                "per-window values are in each run's ledger."
            ),
            insights_comparison=insights_comparison,
            rows=[
                dict(
                    run_id=report_source.name,
                    attribution_classification=attribution.classification,
                    revenue_gbp=ledger_amount(attribution, CATEGORY_REVENUE),
                    capex_gbp=capex_total(attribution),
                    aggregate_expenses_gbp=ledger_amount(
                        attribution, CATEGORY_EXPENSE_AGGREGATE, negate=True
                    ),
                    unattributed_cash_gbp=unattributed_total(attribution),
                    expense_classification_complete=next(
                        (
                            indicator.value
                            for indicator in attribution.coverage
                            if indicator.indicator == "expense_classification_complete"
                        ),
                        None,
                    ),
                    matched_status=statuses.get(report_source.name),
                )
                for (report_source, *_), attribution in zip(loaded, attributions)
            ],
        )
    primary = attributions[0]
    output.mkdir(parents=True, exist_ok=True)
    (output / "financial-attribution.json").write_text(primary.model_dump_json(indent=2) + "\n")
    (output / "financial-attribution.md").write_text(render_attribution_markdown(primary))
    (output / "financial-attribution-summary.txt").write_text(
        render_attribution_summary(primary) + "\n"
    )
    stale_comparison = output / "financial-comparison.json"
    if comparison is not None:
        (output / "financial-comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    elif stale_comparison.exists():
        stale_comparison.unlink()
    return dict(
        output=str(output),
        classification=primary.classification,
        ledger_entries=len(primary.ledger),
        reconciliations=len(primary.reconciliations),
        services=len(primary.services),
        period_rows=len(primary.period_rows),
        claims=len(primary.claims),
        attribution=str(output / "financial-attribution.json"),
        markdown=str(output / "financial-attribution.md"),
        summary=str(output / "financial-attribution-summary.txt"),
        comparison=str(output / "financial-comparison.json") if comparison is not None else None,
    )
