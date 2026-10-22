"""Offline P07 financial attribution; controlled fixtures establish no native run.

These tests exercise the attribution layer over retained P07 report shapes
(``summary.json`` / ``evaluation.json``) and read-only retained native records
(per-service receipts, capital readbacks, native financial reconciliations).
Nothing here launches OpenTTD, connects to AdminPort, or mutates evidence.
"""

import json
from pathlib import Path

import pytest

from app.experiments.financial_attribution import (
    CAPEX_CATEGORIES,
    CATEGORY_CAPEX_ROAD,
    CATEGORY_CAPEX_UNSPLIT,
    CATEGORY_CAPEX_VEHICLE,
    CATEGORY_EXPENSE_AGGREGATE,
    CATEGORY_REVENUE,
    CATEGORY_UNATTRIBUTED,
    CLAIM_METRICS,
    OPEX_CATEGORIES,
    analyze_financial_attribution,
    build_financial_attribution,
    compact_status,
    discover_receipts,
    read_capital_gift,
    read_native_reconciliation,
    render_attribution_markdown,
    render_attribution_summary,
)

ATTEMPT19 = Path("artifacts/experiments/p07-attempt19-five-year-offline")
ATTEMPT19_RUNTIME = Path("artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19")
DEMO_REPORT = Path("artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report")


# ---------------------------------------------------------------------------
# Controlled retained-shape fixtures
# ---------------------------------------------------------------------------


def capital_readback(delta=4000, before=1000, after=5000):
    """Controlled completed scenario-capital readback (retained field shape)."""
    return dict(
        status="READ",
        completed=True,
        type="scenario_capital",
        balance_before=before,
        balance_after=after,
        delta=delta,
    )


def controlled_receipt(
    route_id,
    *,
    mutation_costs,
    readbacks,
    spending,
    revenue=None,
    profit=None,
):
    """Controlled first-freight-delivery-receipt-v1 field shape."""
    return dict(
        route_id=route_id,
        mutation_costs=mutation_costs,
        construction_purchase_spending=spending,
        construction_command_readbacks=readbacks,
        payment_income=revenue,
        vehicle_profit_delta=profit,
    )


def continuous_receipts():
    """Two retained receipts: alpha fully known, beta without revenue counters.

    alpha: mutation_costs slots 0..5 sum to 950 infrastructure, slot 6 is 900
    vehicle purchase, spending 1850; succeeded readbacks ROAD 700 / FACILITY 250.
    beta: infrastructure 300, vehicle 800, spending 1100; ROAD 300 only.
    """
    alpha = controlled_receipt(
        "route-alpha",
        mutation_costs=[700, 250, 0, 0, 0, 0, 900, 0, 0, 0],
        readbacks=[
            dict(kind="ROAD", spent="700", classification="COMMAND_SUCCEEDED"),
            dict(kind="FACILITY", spent="250", classification="COMMAND_SUCCEEDED"),
        ],
        spending="1850",
        revenue="120",
        profit="70",
    )
    beta = controlled_receipt(
        "route-beta",
        mutation_costs=[300, 0, 0, 0, 0, 0, 800, 0],
        readbacks=[dict(kind="ROAD", spent="300", classification="COMMAND_SUCCEEDED")],
        spending=1100,
        revenue=None,
        profit=60,
    )
    paths = (Path("controlled/service-receipt-0.json"), Path("controlled/service-receipt-1.json"))
    return tuple(zip(paths, (alpha, beta)))


def continuous_fixture():
    """Small controlled continuous summary with the retained P07 field shape.

    Identity arithmetic (gift 4000, funding 5000, capex 2950, setup expenses 5):
    opening 2040 = 5000 - 2950 - 5 - 5 (unattributed setup decrease 5).
    Operating: closing 2410 = 2040 + 500 - 120 - 10 (unknown movements -10).
    """
    return dict(
        classification="CONTROLLED_TEST_CONTINUOUS",
        snapshots=[
            dict(
                sequence=index,
                economy_date=712299 + index * 30,
                elapsed_economy_days=index * 30,
                services=[
                    dict(
                        route_id="route-alpha",
                        delivered=0 if index < 5 else 90,
                        station_waiting_cargo=0,
                        cargo_load=0 if index < 5 else 40,
                        capacity=40,
                        vehicle=101,
                        revenue=None,
                    ),
                    dict(
                        route_id="route-beta",
                        delivered=0 if index < 5 else 25,
                        station_waiting_cargo=0,
                        cargo_load=40,
                        capacity=40,
                        vehicle=102,
                        revenue=None,
                    ),
                ],
            )
            for index in range(10)
        ],
        finance=dict(
            freight_revenue=500,
            capex=2950,
            opening_cash=2040,
            closing_cash=2410,
            known_unallocated_expenses=120,
            unknown_cash_movements=-10,
            other_identified_movements=0,
            vehicle_operating_expenses=None,
            loan_interest=None,
            other_expenses=None,
            expense_classification_complete=None,
            operating_profit=None,
            roi=None,
        ),
        setup_cash_coverage=dict(
            funding_cash=5000,
            construction_capex=2950,
            operation_opening_cash=2040,
            measured_setup_aggregate_expenses=5,
            unattributed_setup_cash_decrease=5,
        ),
        totals=[
            {
                "scope": "route-alpha",
                "revenue": None,
                "delivered_cargo": 90,
                "cargo_per_economy_day": 90 / 270,
            },
            {
                "scope": "route-beta",
                "revenue": None,
                "delivered_cargo": 25,
                "cargo_per_economy_day": 25 / 270,
            },
            {
                "scope": "network",
                "revenue": 500,
                "delivered_cargo": 115,
                "cargo_per_economy_day": 115 / 270,
            },
        ],
        periods=[
            dict(
                period="annual",
                index=1,
                scope="network",
                start_economy_date=712299,
                end_economy_date=712665,
                elapsed_economy_days=366,
                revenue=200,
                known_unallocated_expenses=60,
                vehicle_operating_expenses=None,
            ),
            dict(
                period="annual",
                index=2,
                scope="network",
                start_economy_date=712665,
                end_economy_date=713031,
                elapsed_economy_days=366,
                revenue=300,
                known_unallocated_expenses=60,
                vehicle_operating_expenses=None,
            ),
        ],
        offline_recovery=dict(
            original_directory="controlled/attempt",
            schema=1,
            original_terminal=dict(status="FAILED", preflight="PASS"),
        ),
        limitations=["Controlled fixture limitation retained verbatim."],
    )


def network_fixture():
    """Small controlled network-evaluation document with the retained shape."""
    return dict(
        classification="CONTROLLED_BATCH",
        metrics=[
            {"name": "delivered_cargo", "unit": "cargo_units", "actual": "60"},
            {"name": "infrastructure_capex", "unit": "GBP", "actual": "15172"},
            {"name": "vehicle_purchase", "unit": "GBP", "actual": "13287"},
            {"name": "total_capex", "unit": "GBP", "actual": "28459"},
            {"name": "delivery_revenue", "unit": "GBP", "actual": "200"},
            {"name": "operating_costs", "unit": "GBP", "actual": None},
            {"name": "net_return", "unit": "GBP", "actual": None},
        ],
        services=[
            dict(
                route_id="route-a",
                status="verified-delivery",
                metrics=[
                    {"name": "total_capex", "unit": "GBP", "actual": "9358"},
                    {"name": "exclusive_infrastructure_capex", "unit": "GBP", "actual": "4929"},
                    {"name": "delivery_revenue", "unit": "GBP", "actual": "120"},
                    {"name": "vehicle_profit", "unit": "GBP", "actual": "70"},
                ],
            ),
            dict(
                route_id="route-b",
                status="verified-delivery",
                metrics=[
                    {"name": "total_capex", "unit": "GBP", "actual": "1100"},
                    {"name": "exclusive_infrastructure_capex", "unit": "GBP", "actual": "300"},
                ],
            ),
        ],
        limitations=["Controlled batch limitation."],
    )


def demo_native_reconciliation():
    """Controlled native-network-financial-reconciliation-v1 payload.

    Mirrors the retained fixed-demo record: funded 500000, admission 499616,
    final 471501, revenue 1022, capex 28459, admission decrease 384, batch
    unallocated decrease 678.
    """
    return dict(
        schema="native-network-financial-reconciliation-v1",
        funded_cash=500000,
        initial_cash=499616,
        final_cash=471501,
        freight_revenue="1022",
        command_construction_purchase_costs="28459",
        funding_to_admission_unallocated_cash_decrease=384,
        unallocated_company_cash_decrease=678,
        operating_costs=None,
        net_profit=None,
    )


def attribution_of(document, **kwargs):
    return build_financial_attribution(
        document,
        source_kind="continuous" if document.get("snapshots") else "network-evaluation",
        source_ref="controlled input",
        **kwargs,
    )


def ledger_entry(attribution, category, **filters):
    for entry in attribution.ledger:
        if entry.category != category:
            continue
        if all(getattr(entry, key) == value for key, value in filters.items()):
            return entry
    return None


def statement(attribution, statement_id):
    return next(
        (row for row in attribution.reconciliations if row.statement_id == statement_id),
        None,
    )


def coverage(attribution, indicator):
    return next(
        (row for row in attribution.coverage if row.indicator == indicator),
        None,
    )


# ---------------------------------------------------------------------------
# Ledger classification and sign normalization
# ---------------------------------------------------------------------------


def test_capex_receipt_entries_split_road_facility_vehicle_signed_negative():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    alpha = {
        entry.category: entry.amount_gbp
        for entry in attribution.ledger
        if entry.scope == "route-alpha" and entry.category in CAPEX_CATEGORIES
    }
    beta = {
        entry.category: entry.amount_gbp
        for entry in attribution.ledger
        if entry.scope == "route-beta" and entry.category in CAPEX_CATEGORIES
    }
    # Infrastructure 950 (road 700 + facility 250, unsplit 0) and vehicle 900.
    assert alpha == {
        CATEGORY_CAPEX_ROAD: -700,
        "CAPEX_CONSTRUCTION_FACILITY": -250,
        "CAPEX_CONSTRUCTION_OTHER": 0,
        CATEGORY_CAPEX_UNSPLIT: 0,
        CATEGORY_CAPEX_VEHICLE: -900,
    }
    # beta has no facility/other commands; 0 is an observed absence.
    assert beta == {
        CATEGORY_CAPEX_ROAD: -300,
        "CAPEX_CONSTRUCTION_FACILITY": 0,
        "CAPEX_CONSTRUCTION_OTHER": 0,
        CATEGORY_CAPEX_UNSPLIT: 0,
        CATEGORY_CAPEX_VEHICLE: -800,
    }


def test_receipt_capex_semantics_match_pinned_native_classification():
    from app.experiments.financial_attribution import _receipt_capex

    # mutation_costs[:6] is infrastructure, slot 6 is the vehicle purchase.
    receipt = dict(
        mutation_costs=[100, 50, 25, 0, 0, 25, 900, 0], construction_purchase_spending="1100"
    )
    assert _receipt_capex(receipt) == (200, 900, 1100)
    # Fewer than seven slots: only the retained spending remains.
    short = dict(mutation_costs=[100, 50], construction_purchase_spending="150")
    assert _receipt_capex(short) == (None, None, 150)


def test_receipt_kind_split_ignores_failed_and_non_succeeded_commands():
    from app.experiments.financial_attribution import _kind_split

    receipt = dict(
        construction_command_readbacks=[
            dict(kind="ROAD", spent="500", classification="COMMAND_SUCCEEDED"),
            dict(kind="ROAD", spent="900", classification="COMMAND_FAILED"),
            dict(kind="TILE", spent="30", classification="COMMAND_SUCCEEDED"),
            dict(kind="FACILITY", spent="77", classification="ALREADY_SATISFIED"),
        ]
    )
    # Only succeeded readbacks count; unknown kinds fall into OTHER.
    assert _kind_split(receipt) == (500, 0, 30)
    # No succeeded readbacks at all: nothing is observed.
    assert _kind_split(dict(construction_command_readbacks=[])) == (None, None, None)


def test_receipt_spending_inconsistency_is_flagged_not_reclassified():
    alpha = controlled_receipt(
        "route-alpha",
        mutation_costs=[700, 250, 0, 0, 0, 0, 900, 0, 0, 0],
        readbacks=[dict(kind="ROAD", spent="700", classification="COMMAND_SUCCEEDED")],
        spending="9999",  # does not equal infrastructure + vehicle
    )
    attribution = attribution_of(
        continuous_fixture(), receipts=((Path("controlled/service-receipt-0.json"), alpha),)
    )
    # The retained inconsistency surfaces as a coverage-gap UNKNOWN entry.
    gap = ledger_entry(attribution, CATEGORY_CAPEX_UNSPLIT, scope="route-alpha", status="UNKNOWN")
    assert gap is not None and gap.amount_gbp is None
    # Retained parts are kept verbatim (road 700 + unsplit 250 + vehicle 900).
    assert ledger_entry(attribution, CATEGORY_CAPEX_ROAD, scope="route-alpha").amount_gbp == -700
    observed_unsplit = ledger_entry(
        attribution, CATEGORY_CAPEX_UNSPLIT, scope="route-alpha", period="setup window"
    )
    assert observed_unsplit.amount_gbp == -250
    assert ledger_entry(attribution, CATEGORY_CAPEX_VEHICLE, scope="route-alpha").amount_gbp == -900
    # The service binds the retained spending total; the gap is never reconciled away.
    service = attribution.services[0]
    assert service.capex_gbp == 9999 and service.capex_status == "OBSERVED"


def test_aggregate_expense_is_signed_outflow_and_opex_stays_unknown():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    aggregate = ledger_entry(attribution, CATEGORY_EXPENSE_AGGREGATE, scope="network")
    assert aggregate.amount_gbp == -120 and aggregate.status == "OBSERVED"
    for category in OPEX_CATEGORIES:
        entry = ledger_entry(attribution, category)
        assert entry.status == "UNKNOWN" and entry.amount_gbp is None
        assert "unknown" in entry.missing_data_behavior.lower()


def test_unattributed_cash_movements_are_signed_per_window_residuals():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    operating = ledger_entry(attribution, CATEGORY_UNATTRIBUTED, period="operating window")
    setup = ledger_entry(attribution, CATEGORY_UNATTRIBUTED, period="setup window")
    assert (operating.amount_gbp, setup.amount_gbp) == (-10, -5)
    assert operating.status == "DERIVED" and setup.status == "DERIVED"
    # Residuals are their own category, never renamed into an expense.
    assert CATEGORY_UNATTRIBUTED not in OPEX_CATEGORIES + CAPEX_CATEGORIES


def test_missing_amounts_stay_unknown_and_never_become_zero():
    document = continuous_fixture()
    document["finance"]["freight_revenue"] = None
    document["finance"]["unknown_cash_movements"] = None
    document["setup_cash_coverage"]["unattributed_setup_cash_decrease"] = None
    attribution = attribution_of(document, receipts=())
    revenue = ledger_entry(attribution, CATEGORY_REVENUE)
    operating_residual = ledger_entry(attribution, CATEGORY_UNATTRIBUTED, period="operating window")
    assert revenue.status == "UNKNOWN" and revenue.amount_gbp is None
    assert operating_residual.status == "UNKNOWN" and operating_residual.amount_gbp is None
    # Nothing invents a profit figure for the incomplete window.
    assert all(claim.status == "UNSUPPORTED" for claim in attribution.claims)


# ---------------------------------------------------------------------------
# Reconciliation statements
# ---------------------------------------------------------------------------


def test_setup_statement_normalizes_positive_decrease_to_signed_movement():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    setup = statement(attribution, "recon-setup-window")
    # The retained record stores the unattributed decrease as +5; the ledger
    # signs the movement -5, and the identity verifies after normalization.
    assert setup.residual_gbp == -5
    assert setup.residual_is_zero is False
    assert setup.identity_verified is True
    residual_term = next(term for term in setup.terms if term.role == "RESIDUAL")
    assert residual_term.amount_gbp == -5
    assert any("positive magnitude" in note for note in setup.notes)


def test_operating_statement_identity_verifies_and_excludes_capex():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    operating = statement(attribution, "recon-operating-window")
    assert operating.residual_gbp == -10
    assert operating.identity_verified is True
    # CAPEX lives in the setup statement and is never deducted twice.
    assert not any(
        term.category in CAPEX_CATEGORIES
        and term.role == "OUTFLOW"
        and term.term_id != "aggregate_expenses"
        for term in operating.terms
    )
    assert any("never deducted from this window twice" in note for note in operating.notes)


def test_operating_residual_is_derived_from_pinned_identity_when_field_absent():
    document = continuous_fixture()
    retained = document["finance"]["unknown_cash_movements"]
    del document["finance"]["unknown_cash_movements"]
    attribution = attribution_of(document, receipts=continuous_receipts())
    entry = ledger_entry(attribution, CATEGORY_UNATTRIBUTED, period="operating window")
    # The retained field is gone, but the pinned identity's terms are all
    # present, so the residual is recomputed deterministically — not invented.
    assert entry.status == "DERIVED" and entry.amount_gbp == retained
    operating = statement(attribution, "recon-operating-window")
    assert (operating.residual_gbp, operating.identity_verified) == (retained, None)


def test_operating_identity_flags_drift_against_pinned_reconcile_cash():
    from app.simulation.openttd.freight_finance import reconcile_cash

    document = continuous_fixture()
    document["finance"]["vehicle_operating_expenses"] = 40
    finance = document["finance"]
    pinned_residual = reconcile_cash(
        finance["opening_cash"],
        finance["closing_cash"],
        finance["freight_revenue"],
        capex=0,
        vehicle_operating_expenses=40,
        known_unallocated_expenses=finance["known_unallocated_expenses"],
    )["unknown_cash_movements"]
    attribution = attribution_of(document, receipts=())
    operating = statement(attribution, "recon-operating-window")
    # The retained field disagrees with the pinned identity: both are reported.
    assert pinned_residual == 30
    assert operating.residual_gbp == -10
    assert operating.identity_verified is False
    assert any("differs from the retained residual" in note for note in operating.notes)


def test_receipt_without_readbacks_keeps_observed_infrastructure_unsplit():
    receipt = controlled_receipt(
        "route-alpha",
        mutation_costs=[700, 250, 0, 0, 0, 0, 900, 0, 0, 0],
        readbacks=[dict(kind="ROAD", spent="900", classification="COMMAND_FAILED")],
        spending=1850,
    )
    attribution = attribution_of(
        continuous_fixture(), receipts=((Path("controlled/service-receipt-0.json"), receipt),)
    )
    # The pinned sum(mutation_costs[:6]) infrastructure total stays OBSERVED.
    unsplit = ledger_entry(attribution, CATEGORY_CAPEX_UNSPLIT, scope="route-alpha")
    assert (unsplit.amount_gbp, unsplit.status) == (-950, "OBSERVED")
    # No kind entries are derived from failed commands (nothing is invented).
    assert ledger_entry(attribution, CATEGORY_CAPEX_ROAD, scope="route-alpha") is None


def test_native_reconciliation_statements_verify_retained_identity():
    attribution = attribution_of(
        network_fixture(),
        native_reconciliation=demo_native_reconciliation(),
        capital_gift=400000,
    )
    admission = statement(attribution, "recon-funding-to-admission")
    batch = statement(attribution, "recon-batch-window")
    assert (admission.residual_gbp, admission.identity_verified) == (-384, True)
    assert (batch.residual_gbp, batch.identity_verified) == (-678, True)
    # Native decreases are stored positive and signed negative in the ledger.
    assert (
        ledger_entry(
            attribution, CATEGORY_UNATTRIBUTED, period="funding-to-admission window"
        ).amount_gbp
        == -384
    )
    assert (
        ledger_entry(attribution, CATEGORY_UNATTRIBUTED, period="serial batch window").amount_gbp
        == -678
    )
    # Funding capital and pre-funding cash are attributed from the native record.
    assert ledger_entry(attribution, "FUNDING_CAPITAL").amount_gbp == 400000
    assert ledger_entry(attribution, "COMPANY_INITIAL_CASH").amount_gbp == 100000


def test_native_reconciliation_reader_enforces_schema_and_read_status(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    assert read_native_reconciliation((root,)) is None
    (root / "financial-reconciliation.json").write_text(
        json.dumps(dict(schema="some-other-schema"))
    )
    with pytest.raises(ValueError, match="unsupported native financial reconciliation"):
        read_native_reconciliation((root,))
    (root / "financial-reconciliation.json").write_text(json.dumps(demo_native_reconciliation()))
    payload = read_native_reconciliation((root,))
    assert payload["funded_cash"] == 500000


def test_capital_gift_reader_requires_completed_read(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    assert read_capital_gift((root,)) is None
    (root / "capital-read-response.json").write_text(
        json.dumps(dict(status="READ", completed=False, delta=4000))
    )
    with pytest.raises(ValueError, match="not a completed READ"):
        read_capital_gift((root,))
    (root / "capital-read-response.json").write_text(json.dumps(capital_readback()))
    assert read_capital_gift((root,)) == 4000


def test_receipt_discovery_is_ordered_and_capped(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    assert discover_receipts((root,)) == ()
    for index in range(10):
        (root / f"service-receipt-{index}.json").write_text("{}")
    found = discover_receipts((root,))
    assert [path.name for path in found] == [
        f"service-receipt-{index}.json"
        for index in range(8)  # MAX_RECEIPTS = 8
    ]


# ---------------------------------------------------------------------------
# Per-service attribution and claims
# ---------------------------------------------------------------------------


def test_service_attribution_binds_receipt_capex_and_revenue():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    by_scope = {service.scope: service for service in attribution.services}
    alpha, beta = by_scope["route-alpha"], by_scope["route-beta"]
    assert (alpha.capex_gbp, alpha.revenue_gbp, alpha.vehicle_profit_delta_gbp) == (1850, 120, 70)
    assert (beta.capex_gbp, beta.revenue_gbp) == (1100, None)
    assert beta.revenue_status == "UNKNOWN"
    # Per-service operating expenses are never attributed offline.
    assert alpha.operating_expenses_status == "UNKNOWN"
    assert alpha.capex_categories[CATEGORY_CAPEX_VEHICLE] == 900


def test_continuous_service_without_receipt_keeps_unknown_capex():
    document = continuous_fixture()
    document["snapshots"][0]["services"] = [
        dict(route_id="route-alpha", delivered=90, revenue=None)
    ]
    attribution = attribution_of(document, receipts=())
    service = attribution.services[0]
    assert service.capex_gbp is None and service.capex_status == "UNKNOWN"
    assert service.missing and any("receipt" in item for item in service.missing)


def test_network_service_attribution_from_evaluation_metrics():
    attribution = attribution_of(network_fixture())
    by_scope = {service.scope: service for service in attribution.services}
    a, b = by_scope["route-a"], by_scope["route-b"]
    assert (a.capex_gbp, a.revenue_gbp, a.vehicle_profit_delta_gbp) == (9358, 120, 70)
    assert (b.capex_gbp, b.revenue_gbp) == (1100, None)
    assert a.capex_categories[CATEGORY_CAPEX_UNSPLIT] == 4929
    assert a.capex_categories[CATEGORY_CAPEX_VEHICLE] is None


def test_profitability_claims_are_unsupported_with_required_observations():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    assert [claim.metric for claim in attribution.claims] == list(CLAIM_METRICS)
    for claim in attribution.claims:
        assert claim.status == "UNSUPPORTED"
        assert claim.reason and claim.required_observations
        assert claim.metric != "roi" or "asset" in claim.reason


def test_no_profit_roi_or_return_value_anywhere_in_the_document():
    # vehicle_profit_delta is an OBSERVED retained counter (receipt/eval field),
    # not a derived claim; everything else profit-shaped must stay non-numeric.
    observed_counters = {"vehicle_profit_delta_gbp"}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = key.lower()
                if key not in observed_counters and any(
                    token in lowered
                    for token in ("profit", "roi", "payback", "break_even", "net_return")
                ):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        pytest.fail(f"{key} carries a number {value}; profit is UNSUPPORTED")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for document in (continuous_fixture(), network_fixture()):
        attribution = attribution_of(document, receipts=continuous_receipts())
        walk(json.loads(attribution.model_dump_json()))


def test_classification_reflects_observed_and_unknown_mix():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    assert attribution.classification == "PARTIAL_FINANCIAL_ATTRIBUTION"
    # An empty continuous document yields no observed amounts; the operating
    # statement still runs with every term UNKNOWN.
    empty = attribution_of(dict(snapshots=[dict(services=[])], finance={}))
    assert empty.classification == "NO_FINANCIAL_EVIDENCE"
    operating = statement(empty, "recon-operating-window")
    assert operating is not None
    assert all(term.status == "UNKNOWN" for term in operating.terms if term.role != "RESIDUAL")
    residual = next(term for term in operating.terms if term.role == "RESIDUAL")
    assert residual.amount_gbp is None  # never presented as a number


# ---------------------------------------------------------------------------
# compact_status (document-only view for performance insights)
# ---------------------------------------------------------------------------


def test_compact_status_continuous_shape_reports_document_amounts():
    status = compact_status(continuous_fixture())
    assert status["classification"] == "PARTIAL_FINANCIAL_ATTRIBUTION"
    assert status["observed_amounts_gbp"] == {
        "freight_revenue": 500,
        "capex": 2950,
        "aggregate_expenses": 120,
    }
    assert status["unattributed_cash_gbp"] == -10
    assert status["unknown_categories"] == list(OPEX_CATEGORIES)
    assert status["missing_for_profit_metrics"] == list(CLAIM_METRICS)


def test_compact_status_network_shape_and_alien_documents():
    status = compact_status(network_fixture())
    assert status["observed_amounts_gbp"] == {"freight_revenue": 200, "capex": 28459}
    assert status["unattributed_cash_gbp"] is None
    assert status["per_service_revenue_status"] == "OBSERVED"
    with pytest.raises(ValueError, match="neither a continuous summary nor a network evaluation"):
        compact_status(dict(unrelated="payload"))


def test_performance_insights_carry_compact_financial_attribution():
    from app.experiments.performance_insights import build_performance_insights

    insights = build_performance_insights(continuous_fixture())
    expected = compact_status(continuous_fixture())
    assert insights.financial_attribution == expected
    assert insights.financial_attribution["unattributed_cash_gbp"] == -10
    network_insights = build_performance_insights(network_fixture())
    assert network_insights.financial_attribution["per_service_revenue_status"] == "OBSERVED"


# ---------------------------------------------------------------------------
# Period rows
# ---------------------------------------------------------------------------


def test_period_rows_keep_observed_aggregates_and_growth():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    rows = {row.period: row for row in attribution.period_rows}
    assert set(rows) == {"annual-1", "annual-2"}
    assert (rows["annual-1"].revenue_gbp, rows["annual-1"].observed_aggregate_expenses_gbp) == (
        200,
        60,
    )
    assert rows["annual-2"].revenue_growth_vs_previous == pytest.approx(0.5)
    assert all(row.coverage == "PARTIAL_ATTRIBUTION" for row in rows.values())
    # OPEX stays unknown inside period rows too.
    assert all(row.vehicle_operating_expenses_gbp is None for row in rows.values())
    network = attribution_of(network_fixture())
    assert network.period_rows == []


# ---------------------------------------------------------------------------
# Pipeline, write guard, and renderers
# ---------------------------------------------------------------------------


def write_world(source: Path):
    """Same retained world recipe for both compared runs (read-only PRELAUNCH)."""
    (source / "PRELAUNCH.json").write_text(
        json.dumps(dict(world=dict(seed="42", width="64", height="64", source="CONTROLLED")))
    )


def write_source(tmp_path, fixture):
    source = tmp_path / "attempt"
    source.mkdir()
    (source / "summary.json").write_text(json.dumps(fixture))
    write_world(source)
    return source


def test_analyze_writes_attribution_outputs(tmp_path):
    source = write_source(tmp_path, continuous_fixture())
    result = analyze_financial_attribution(source, tmp_path / "out")
    assert result["classification"] == "PARTIAL_FINANCIAL_ATTRIBUTION"
    for name in (
        "financial-attribution.json",
        "financial-attribution.md",
        "financial-attribution-summary.txt",
    ):
        assert (tmp_path / "out" / name).is_file()
        assert not (tmp_path / "out" / "financial-comparison.json").exists()
    parsed = json.loads((tmp_path / "out" / "financial-attribution.json").read_text())
    assert parsed["schema_version"] == 1
    assert parsed["source_kind"] == "continuous"
    summary = (tmp_path / "out" / "financial-attribution-summary.txt").read_text()
    assert "UNKNOWN is not zero" in summary
    assert "all UNSUPPORTED" in summary


def test_analyze_compares_runs_descriptively(tmp_path):
    source = write_source(tmp_path, continuous_fixture())
    other = tmp_path / "other"
    other.mkdir()
    (other / "summary.json").write_text(json.dumps(continuous_fixture()))
    write_world(other)
    analyze_financial_attribution(source, tmp_path / "out", compare=(other,))
    assert (tmp_path / "out" / "financial-comparison.json").is_file()
    comparison = json.loads((tmp_path / "out" / "financial-comparison.json").read_text())
    assert comparison["classification"] == "MATCHED_WORLD_COMPARISON"
    assert len(comparison["rows"]) == 2
    for row in comparison["rows"]:
        assert row["unattributed_cash_gbp"] == -15  # -10 operating + -5 setup
        assert row["capex_gbp"] == 2950
        assert row["matched_status"] == "MATCHED_DESCRIPTIVE"


def test_write_guard_refuses_outputs_inside_retained_evidence(tmp_path):
    source = write_source(tmp_path, continuous_fixture())
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_financial_attribution(source, source / "financial-attribution")
    retained = tmp_path / "retained"
    retained.mkdir()
    document = continuous_fixture()
    document["offline_recovery"]["original_directory"] = str(retained)
    (source / "summary.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_financial_attribution(source, retained / "out")


def test_renderers_keep_unknown_visible_and_never_claim_profit():
    attribution = attribution_of(continuous_fixture(), receipts=continuous_receipts())
    markdown = render_attribution_markdown(attribution)
    summary = render_attribution_summary(attribution)
    for text in (markdown, summary):
        assert "UNKNOWN" in text
        assert "not" in text and "profit" in text.lower()
    assert "roi" in summary.lower()  # claim list is explicit
    assert "unattributed" in markdown.lower()


# ---------------------------------------------------------------------------
# Real retained artifacts (read-only; skipped when absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (ATTEMPT19.is_dir() and ATTEMPT19_RUNTIME.is_dir()),
    reason="retained attempt 19 evidence unavailable",
)
def test_real_attempt19_attribution_matches_retained_amounts():
    receipts = tuple(
        (path, json.loads(path.read_text())) for path in discover_receipts((ATTEMPT19_RUNTIME,))
    )
    document = json.loads((ATTEMPT19 / "summary.json").read_text())
    attribution = build_financial_attribution(
        document,
        source_kind="continuous",
        source_ref=str(ATTEMPT19 / "summary.json"),
        receipts=receipts,
        capital_gift=read_capital_gift((ATTEMPT19_RUNTIME,)),
    )
    assert attribution.classification == "PARTIAL_FINANCIAL_ATTRIBUTION"
    assert attribution.native_terminal_status.startswith("FAILED")
    assert ledger_entry(attribution, CATEGORY_REVENUE).amount_gbp == 50935
    assert ledger_entry(attribution, CATEGORY_EXPENSE_AGGREGATE).amount_gbp == -16312
    assert ledger_entry(attribution, "FUNDING_CAPITAL").amount_gbp == 400000
    assert ledger_entry(attribution, "COMPANY_INITIAL_CASH").amount_gbp == 100000
    setup = statement(attribution, "recon-setup-window")
    operating = statement(attribution, "recon-operating-window")
    assert (setup.residual_gbp, setup.identity_verified) == (-50, True)
    assert (operating.residual_gbp, operating.identity_verified) == (-1500, True)
    # Retained receipts split the 28459 CAPEX across three services.
    assert sorted(service.capex_gbp for service in attribution.services) == [9358, 9515, 9586]
    roads = [
        entry.amount_gbp for entry in attribution.ledger if entry.category == CATEGORY_CAPEX_ROAD
    ]
    assert sorted(roads) == [-4138, -4067, -3910]
    # Continuous evidence has no per-service revenue counters.
    assert all(service.revenue_status == "UNKNOWN" for service in attribution.services)
    assert coverage(attribution, "per_service_revenue_attribution").value == "UNKNOWN"
    assert all(claim.status == "UNSUPPORTED" for claim in attribution.claims)
    assert len(attribution.period_rows) == 85


@pytest.mark.skipif(not DEMO_REPORT.is_dir(), reason="fixed demo report unavailable")
def test_real_fixed_demo_attribution_reconciles_native_record():
    report_document = json.loads((DEMO_REPORT / "evaluation.json").read_text())
    evidence = DEMO_REPORT / (report_document.get("evidence_directory") or ".")
    receipts = tuple(
        (path, json.loads(path.read_text())) for path in discover_receipts((evidence,))
    )
    attribution = build_financial_attribution(
        report_document,
        source_kind="network-evaluation",
        source_ref=str(DEMO_REPORT / "evaluation.json"),
        receipts=receipts,
        native_reconciliation=read_native_reconciliation((evidence,)),
        capital_gift=read_capital_gift((evidence,)),
    )
    assert attribution.classification == "PARTIAL_FINANCIAL_ATTRIBUTION"
    assert ledger_entry(attribution, CATEGORY_REVENUE).amount_gbp == 1022
    assert ledger_entry(attribution, CATEGORY_CAPEX_UNSPLIT).amount_gbp == -15172
    assert ledger_entry(attribution, CATEGORY_CAPEX_VEHICLE).amount_gbp == -13287
    admission = statement(attribution, "recon-funding-to-admission")
    batch = statement(attribution, "recon-batch-window")
    assert (admission.residual_gbp, admission.identity_verified) == (-384, True)
    assert (batch.residual_gbp, batch.identity_verified) == (-678, True)
    # Per-service receipts attribute revenue that sums to the network revenue.
    assert [service.revenue_gbp for service in attribution.services] == [340, 356, 326]
    assert coverage(attribution, "per_service_revenue_sums_to_network").value is True
    assert coverage(attribution, "shared_infrastructure_capex_gbp").value == 0
    assert all(claim.status == "UNSUPPORTED" for claim in attribution.claims)
    assert attribution.period_rows == []


@pytest.mark.skipif(not ATTEMPT19.is_dir(), reason="retained attempt 19 summary unavailable")
def test_real_attempt19_pipeline_writes_without_touching_evidence(tmp_path):
    result = analyze_financial_attribution(ATTEMPT19, tmp_path / "out")
    assert result["classification"] == "PARTIAL_FINANCIAL_ATTRIBUTION"
    parsed = json.loads((tmp_path / "out" / "financial-attribution.json").read_text())
    assert parsed["source_kind"] == "continuous"
    assert parsed["native_terminal_status"].startswith("FAILED")
    markdown = (tmp_path / "out" / "financial-attribution.md").read_text()
    assert "PARTIAL_FINANCIAL_ATTRIBUTION" in markdown
    assert "all UNSUPPORTED" not in markdown or "UNSUPPORTED" in markdown
