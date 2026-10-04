"""Interpret trusted parser fields and export ordered P04 observations for P07."""

import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.experiments.domain import ExperimentConfig
from app.experiments.model import TelemetryObservationRecord


def final_save_values(
    parsed: dict, config: ExperimentConfig
) -> tuple[tuple[str, Decimal, str], ...]:
    if parsed["configuration"] != config.model_dump(mode="json"):
        raise ValueError("parsed configuration differs")
    company = parsed["chunks"]["PLYR"]["0"]
    economy = company["cur_economy"][0]
    delivered = economy["delivered_cargo"]
    if not isinstance(delivered, list) or any(
        type(amount) is not int or amount < 0 for amount in delivered
    ):
        raise ValueError("invalid public cargo counts")
    values = (
        ("company_money", company["money"], "GBP"),
        ("company_loan", company["current_loan"], "GBP"),
        ("current_period_income", economy["income"], "GBP"),
        ("current_period_expenses", economy["expenses"], "GBP"),
        ("current_period_cargo_delivered", sum(delivered), "cargo_units"),
    )
    if any(type(amount) is not int for _, amount, _ in values):
        raise ValueError("public parser values must be exact integers")
    return tuple((name, Decimal(amount), unit) for name, amount, unit in values)


def telemetry_bytes(session: Session, run_id: int) -> bytes:
    rows = session.scalars(
        select(TelemetryObservationRecord)
        .where(TelemetryObservationRecord.experiment_run_id == run_id)
        .order_by(TelemetryObservationRecord.sequence)
    ).all()
    return json.dumps(
        [
            {
                "sequence": row.sequence,
                "epoch": row.connection_epoch,
                "source": row.source,
                "kind": row.kind,
                "company_id": row.company_id,
                "game_day": row.game_day,
                "schema_version": row.schema_version,
                "protocol_version": row.protocol_version,
                "date_quality": row.date_quality,
                "date_context_sequence": row.date_context_sequence,
                "received_at": row.received_at.isoformat(),
                "payload": row.payload,
            }
            for row in rows
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def observation_window(
    data: bytes, start_day: int | None, terminal_day: int | None
) -> tuple[int, bool]:
    """Conservatively require dated post-setup observations of all supported kinds."""
    if start_day is None or terminal_day is None:
        return 0, False
    rows = json.loads(data)
    window = [
        row
        for row in rows
        if row["game_day"] is not None
        and start_day <= row["game_day"] <= terminal_day
        and row["company_id"] in (None, 0)
    ]
    kinds = {row["kind"] for row in window}
    dates = [row["game_day"] for row in window if row["kind"] == "date"]
    distinct_days = sorted(set(dates))
    contiguous = all(right == left + 1 for left, right in zip(distinct_days, distinct_days[1:]))
    complete = (
        contiguous
        and bool(dates)
        and min(dates) <= start_day
        and max(dates) >= terminal_day
        and {"date", "company_info", "company_economy", "company_stats"} <= kinds
    )
    return len(window), complete
