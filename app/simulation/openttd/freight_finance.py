"""Native continuous freight readbacks and conservative cash accounting."""

import json
from typing import Literal

from pydantic import StrictBool, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract

KINDS = Literal["continuous-begin", "continuous-company", "continuous-service"]


class ContinuousRequest(Contract):
    protocol: Literal[1] = 1
    type: KINDS
    request_id: str
    service: StrictInt = -1

    def to_bytes(self):
        if not (
            1 <= len(self.request_id) <= 32
            and self.request_id.isascii()
            and self.request_id.replace("-", "").isalnum()
        ):
            raise ValueError("invalid continuous request identifier")
        if (self.type == "continuous-service" and not 0 <= self.service <= 2) or (
            self.type != "continuous-service" and self.service != -1
        ):
            raise ValueError("invalid continuous service")
        return canonical_bytes(self)


class ContinuousClock(Contract):
    economy_date: StrictInt
    economy_year: StrictInt
    economy_month: StrictInt
    economy_day: StrictInt
    calendar_date: StrictInt | None
    script_tick: StrictInt
    paused: StrictBool
    timekeeping_units: Literal[0, 1]

    @model_validator(mode="after")
    def valid_clock(self):
        if (
            self.economy_date < 0
            or self.script_tick < 0
            or not 1 <= self.economy_month <= 12
            or not 1 <= self.economy_day <= 31
        ):
            raise ValueError("invalid native economy clock")
        return self


class ContinuousReadback(Contract):
    protocol: Literal[1]
    type: Literal[
        "continuous-begin-result", "continuous-company-result", "continuous-service-result"
    ]
    request_id: str
    status: Literal["ok"]
    clock: ContinuousClock
    baseline_snapshots: tuple[tuple[StrictInt, ...], ...] | None = None
    baseline_delivered: tuple[StrictInt | None, ...] | None = None
    annual_targets: tuple[StrictInt, ...] | None = None
    start_economy_date: StrictInt | None = None
    cash: StrictInt | None = None
    loan_balance: StrictInt | None = None
    quarter_income: StrictInt | None = None
    quarter_expenses: StrictInt | None = None
    quarter_delivered: StrictInt | None = None
    previous_quarter_income: StrictInt | None = None
    previous_quarter_expenses: StrictInt | None = None
    previous_quarter_delivered: StrictInt | None = None
    loan_interest: StrictInt | None = None
    expense_categories: dict[str, StrictInt] | None = None
    vehicle_operating_expenses: StrictInt | None = None
    service: StrictInt | None = None
    plan: str | None = None
    vehicle: StrictInt | None = None
    snapshot: tuple[StrictInt, ...] | None = None
    profit_this_year: StrictInt | None = None
    profit_last_year: StrictInt | None = None
    running_cost_rate_per_year: StrictInt | None = None
    delivered: StrictInt | None = None
    revenue: StrictInt | None = None
    operating_costs: StrictInt | None = None
    completed_delivery_cycles: StrictInt | None = None
    station_waiting_cargo: StrictInt | None = None
    cargo_load: StrictInt | None = None
    capacity: StrictInt | None = None

    @classmethod
    def parse_for(cls, q, raw):
        if len(raw) > 1450:
            raise ValueError("continuous response exceeds 1450 bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate response key")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if isinstance(value, dict) and value.get("status") == "rejected":
            if (
                set(value) != {"protocol", "type", "request_id", "status", "error"}
                or type(value.get("protocol")) is not int
                or value["protocol"] != q.protocol
                or value["request_id"] != q.request_id
                or value["type"] != q.type + "-result"
                or not isinstance(value["error"], str)
                or not 1 <= len(value["error"]) <= 160
            ):
                raise ValueError("invalid continuous rejection identity or reason")
            raise ValueError("native continuous rejection: " + value["error"])
        r = cls.model_validate_json(raw)
        if r.protocol != q.protocol or r.request_id != q.request_id or r.type != q.type + "-result":
            raise ValueError("continuous response identity mismatch")
        if q.type == "continuous-service" and r.service != q.service:
            raise ValueError("continuous response service mismatch")
        return r

    @model_validator(mode="after")
    def required_observations(self):
        if self.type == "continuous-service-result":
            if (
                self.service not in (0, 1, 2)
                or self.plan is None
                or len(self.plan) != 64
                or self.vehicle is None
                or self.snapshot is None
                or len(self.snapshot) != 30
            ):
                raise ValueError("incomplete continuous service evidence")
            snap = self.snapshot
            if (
                self.vehicle != snap[4]
                or self.capacity != snap[7]
                or self.cargo_load != snap[11]
                or self.station_waiting_cargo != snap[15]
                or self.profit_this_year != snap[20]
                or self.clock.economy_date != snap[1]
                or snap[5] != 0
                or snap[12] != 2
                or snap[28] != 1
                or snap[29] != 1
            ):
                raise ValueError("service native snapshot mismatch")
            if (
                self.capacity is None
                or self.capacity <= 0
                or self.cargo_load is None
                or not 0 <= self.cargo_load <= self.capacity
            ):
                raise ValueError("invalid observed utilization")
        else:
            for name in (
                "cash",
                "loan_balance",
                "quarter_income",
                "quarter_expenses",
                "quarter_delivered",
                "previous_quarter_income",
                "previous_quarter_expenses",
                "previous_quarter_delivered",
            ):
                if getattr(self, name) is None:
                    raise ValueError("incomplete company financial evidence")
            if self.type == "continuous-begin-result" and (
                self.annual_targets is None
                or len(self.annual_targets) != 5
                or self.start_economy_date != self.clock.economy_date
            ):
                raise ValueError("incomplete annual target evidence")
        return self


def reconcile_cash(
    opening_cash,
    closing_cash,
    freight_revenue,
    capex=0,
    vehicle_operating_expenses=None,
    loan_interest=None,
    other_expenses=None,
    other_identified_movements=0,
    known_unallocated_expenses=0,
):
    """Residual is unknown cash movement, never a classification of spending."""
    costs = (vehicle_operating_expenses, loan_interest, other_expenses)
    known_costs = sum(c for c in costs if c is not None) + known_unallocated_expenses
    residual = closing_cash - (
        opening_cash + freight_revenue - capex - known_costs + other_identified_movements
    )
    complete = (
        all(c is not None for c in costs) and residual == 0 and known_unallocated_expenses == 0
    )
    return dict(
        opening_cash=opening_cash,
        closing_cash=closing_cash,
        freight_revenue=freight_revenue,
        capex=capex,
        vehicle_operating_expenses=vehicle_operating_expenses,
        loan_interest=loan_interest,
        other_expenses=other_expenses,
        other_identified_movements=other_identified_movements,
        known_unallocated_expenses=known_unallocated_expenses,
        unknown_cash_movements=residual,
        net_cash_flow=closing_cash - opening_cash,
        operating_profit=freight_revenue - known_costs if complete else None,
        roi=(freight_revenue - known_costs - capex) / capex if complete and capex else None,
        gross_revenue_to_capex_ratio=freight_revenue / capex if capex else None,
        cost_recovery=(freight_revenue - known_costs) / capex if complete and capex else None,
        break_even_time=None,
        expense_classification_complete=complete,
    )


def reconcile_snapshots(snapshots):
    """Sum native quarter deltas; reject missed history rather than estimating."""
    if not snapshots:
        raise ValueError("financial snapshots missing")
    rows = [s["finance"] for s in snapshots]
    totals = dict(income=0, expenses=0, delivered=0)
    for previous, current in zip(rows, rows[1:], strict=False):
        pc, cc = previous["clock"], current["clock"]
        pquarter = pc["economy_year"] * 4 + (pc["economy_month"] - 1) // 3
        cquarter = cc["economy_year"] * 4 + (cc["economy_month"] - 1) // 3
        if cquarter - pquarter not in (0, 1):
            raise ValueError("financial quarter observation gap")
        for key in totals:
            old, new = previous[f"quarter_{key}"], current[f"quarter_{key}"]
            if cquarter != pquarter:
                new += current[f"previous_quarter_{key}"]
            totals[key] += new - old
    first, last = rows[0], rows[-1]
    result = reconcile_cash(
        first["cash"],
        last["cash"],
        totals["income"],
        other_identified_movements=last["loan_balance"] - first["loan_balance"],
        known_unallocated_expenses=-totals["expenses"],
    )
    result.update(
        company_quarter_expenses_signed=totals["expenses"],
        delivered_cargo=totals["delivered"],
        accounting_residual_after_total_expenses=last["cash"]
        - first["cash"]
        - totals["income"]
        - totals["expenses"]
        - (last["loan_balance"] - first["loan_balance"]),
        revenue_per_economy_day=totals["income"]
        / (last["clock"]["economy_date"] - first["clock"]["economy_date"])
        if last["clock"]["economy_date"] > first["clock"]["economy_date"]
        else None,
    )
    return result
