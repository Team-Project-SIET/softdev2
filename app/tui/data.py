"""Read-only artifact catalog for the OpenTTD terminal UI.

Everything here reads retained evidence and formats it for display. There is no
Textual import in this module, so the catalog can be inspected and tested on a
host that has not installed the optional TUI dependency.

Evidence rules kept by design:

* missing values stay ``UNKNOWN``; they are never rendered as zero;
* paths are only read, never written;
* a partial or half-written JSON file makes that field unknown, not a crash;
* run directories and P07 report directories are separate catalog entries.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT / "artifacts/demos"
SAMPLE_REPORT = PROJECT / "examples/openttd-demo/sample-report"

MAX_JSON_BYTES = 4 * 1024 * 1024
MANIFEST_NAMES = ("artifact-manifest.sha256", "manifest.sha256")
UNKNOWN = "UNKNOWN"

RUN_MARKERS = (
    "result.json",
    "receipt.json",
    "PRELAUNCH.json",
    "planning-scenario.json",
    "execution-plan.json",
)
REPORT_MARKERS = ("evaluation.json", "operational-history.json", "results.md")


# ---------------------------------------------------------------------------
# small value helpers
# ---------------------------------------------------------------------------


def display(value: Any) -> str:
    """Render a retained value without inventing one for missing data."""

    if value is None or value == "" or value == "null":
        return UNKNOWN
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return UNKNOWN
        return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def money(value: Any) -> str:
    """Render a GBP amount, or ``UNKNOWN`` when the evidence has no value."""

    if value is None or value == "" or value == "null":
        return UNKNOWN
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return display(value)
    if not amount.is_finite():
        return UNKNOWN
    if amount == amount.to_integral_value():
        return f"£{amount:,.0f}"
    return f"£{amount:,.2f}"


def plain(value: Any) -> str:
    """Render an identifier/date without thousands separators."""

    if value is None or value == "" or value == "null":
        return UNKNOWN
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def number(value: Any) -> float | None:
    """Return a finite float for chart math, else ``None``."""

    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


# ---------------------------------------------------------------------------
# tolerant readers
# ---------------------------------------------------------------------------


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> dict[str, Any] | None:
    """Read a bounded JSON object, returning ``None`` for missing/bad data."""

    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        return None
    if len(raw) > limit:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _metric_map(metrics: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for metric in _rows(metrics):
        name = metric.get("name")
        if isinstance(name, str):
            result[name] = metric
    return result


def _actual(metrics: dict[str, dict[str, Any]], *names: str) -> Any:
    for name in names:
        if name in metrics:
            return metrics[name].get("actual")
    return None


def _sum_actual(metrics: dict[str, dict[str, Any]], names: Iterable[str]) -> Any:
    values = []
    for name in names:
        value = number(_actual(metrics, name))
        if value is not None:
            values.append(value)
    if not values:
        return None
    total = sum(values)
    return int(total) if total == int(total) else total


def _world_text(prelaunch: dict[str, Any], history: dict[str, Any]) -> str:
    world = _first(history, "world")
    if not isinstance(world, dict):
        world = _first(prelaunch, "world")
    world = _dict(world)
    if not world:
        experiment = _dict(_first(prelaunch, "experiment"))
        world = _dict(experiment.get("world"))
    parts = []
    for key in ("source", "seed", "width", "height", "climate", "terrain", "towns", "industries"):
        if key in world and world[key] is not None:
            parts.append(f"{key}={display(world[key])}")
    return ", ".join(parts) if parts else UNKNOWN


def _experiment_text(prelaunch: dict[str, Any], history: dict[str, Any]) -> str:
    experiment = _first(history, "experiment")
    if not isinstance(experiment, dict):
        experiment = _first(prelaunch, "experiment")
    experiment = _dict(experiment)
    parts = []
    for key in ("scenario", "planner", "budget_gbp", "planner_seconds"):
        if key in experiment and experiment[key] is not None:
            parts.append(f"{key}={display(experiment[key])}")
    if parts:
        return ", ".join(parts)
    key = _first(history, "experiment_key") or _first(prelaunch, "experiment_key")
    if key is not None:
        return display(key)
    for field in ("proof_kind", "mode", "attempt_id"):
        value = _first(prelaunch, field)
        if value is not None:
            return f"{field}={display(value)}"
    return UNKNOWN


# ---------------------------------------------------------------------------
# catalog entries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactEntry:
    """Lightweight row shown in the run list."""

    path: Path
    name: str
    kind: str
    status: str
    world: str
    experiment: str
    services_count: int | None
    delivered: Any
    revenue: Any
    capex: Any


@dataclass(frozen=True)
class ServiceRow:
    service: str
    status: str
    vehicle: str
    delivered: str
    revenue: str
    capex: str
    backlog: str
    delivered_date: str


@dataclass(frozen=True)
class MetricRow:
    scope: str
    name: str
    planned: str
    actual: str
    difference: str
    unit: str
    comparison: str


@dataclass(frozen=True)
class FinanceRow:
    label: str
    value: str


@dataclass(frozen=True)
class PointRow:
    tick: int | None
    service: str
    cargo: float | None
    revenue: float | None
    throughput: float | None
    revenue_rate: float | None


@dataclass(frozen=True)
class FileRow:
    name: str
    size: int
    digest: str | None


@dataclass(frozen=True)
class RunDetail:
    entry: ArtifactEntry
    services: tuple[ServiceRow, ...]
    metrics: tuple[MetricRow, ...]
    points: tuple[PointRow, ...]
    finance: tuple[FinanceRow, ...]
    files: tuple[FileRow, ...]
    notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def _kind(path: Path) -> str | None:
    if not path.is_dir():
        return None
    if any((path / name).is_file() for name in REPORT_MARKERS):
        return "report"
    if any((path / name).is_file() for name in RUN_MARKERS):
        return "run"
    return None


def _candidate_paths(root: Path) -> list[Path]:
    """Find artifact directories at the root or up to two levels below it."""

    if not root.exists():
        return []
    if _kind(root) is not None:
        return [root]

    found: list[Path] = []
    frontier: list[tuple[Path, int]] = [(root, 0)]
    while frontier:
        parent, depth = frontier.pop(0)
        try:
            children = sorted(parent.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if _kind(child) is not None:
                found.append(child)
            elif depth < 1:
                # One extra level lets `--root artifacts` find artifacts/runtime/<run>.
                frontier.append((child, depth + 1))
    return sorted(set(found), key=lambda path: str(path).lower())


def _receipt_services(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    services = _rows(receipt.get("services"))
    if services:
        return services
    return _rows(receipt.get("service_receipts"))


def _status(path: Path, kind: str) -> str:
    result = read_json(path / "result.json")
    if result and result.get("status"):
        return str(result["status"])
    evaluation = read_json(path / "evaluation.json")
    if evaluation and evaluation.get("classification"):
        return str(evaluation["classification"])
    proof = read_json(path / "proof-attempt.json")
    if proof and proof.get("classification"):
        return str(proof["classification"])
    if kind == "report" and (path / "operational-history.json").is_file():
        return "OPERATIONAL_REPORT"
    return UNKNOWN


def _summary_values(
    *,
    result: dict[str, Any] | None,
    evaluation: dict[str, Any] | None,
    history: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> tuple[int | None, Any, Any, Any]:
    services: list[dict[str, Any]] = []
    if evaluation:
        services = _rows(evaluation.get("services"))
    if not services and history:
        services = _rows(history.get("services"))
    if not services and receipt:
        services = _receipt_services(receipt)

    count = len(services) if services else None
    delivered = _first(history or {}, "derived_completed_delivered_cargo")
    revenue = _first(history or {}, "derived_completed_revenue_gbp")
    capex = _first(history or {}, "derived_completed_command_expenses_gbp")

    metrics = _metric_map((evaluation or {}).get("metrics"))
    delivered = delivered if delivered is not None else _actual(metrics, "delivered_cargo")
    revenue = revenue if revenue is not None else _actual(metrics, "delivery_revenue")
    capex = capex if capex is not None else _actual(metrics, "total_capex")

    if receipt:
        rows = _receipt_services(receipt)
        if rows:
            if delivered is None:
                delivered = _sum(rows, "delivered")
            if revenue is None:
                revenue = _sum(rows, "payment_income")
            if capex is None:
                capex = _sum(rows, "construction_purchase_spending")

    if result:
        count = count or result.get("services")
        delivered = delivered if delivered is not None else result.get("delivered")
        revenue = revenue if revenue is not None else result.get("payment_income")
        capex = capex if capex is not None else result.get("construction_purchase_spending")

    return count, delivered, revenue, capex


def _sum(rows: list[dict[str, Any]], key: str) -> Any:
    values = []
    for row in rows:
        value = number(row.get(key))
        if value is not None:
            values.append(value)
    if not values:
        return None
    total = sum(values)
    return int(total) if total == int(total) else total


def _entry(path: Path, kind: str, *, name: str | None = None) -> ArtifactEntry:
    result = read_json(path / "result.json")
    evaluation = read_json(path / "evaluation.json")
    history = read_json(path / "operational-history.json")
    receipt = read_json(path / "receipt.json", limit=8 * 1024 * 1024)
    prelaunch = read_json(path / "PRELAUNCH.json", limit=2 * 1024 * 1024)
    count, delivered, revenue, capex = _summary_values(
        result=result,
        evaluation=evaluation,
        history=history,
        receipt=receipt,
    )
    return ArtifactEntry(
        path=path,
        name=name or path.name,
        kind=kind,
        status=_status(path, kind),
        world=_world_text(prelaunch or {}, history or {}),
        experiment=_experiment_text(prelaunch or {}, history or {}),
        services_count=count,
        delivered=delivered,
        revenue=revenue,
        capex=capex,
    )


def discover(root: Path, *, include_sample: bool = False) -> list[ArtifactEntry]:
    """Return catalog entries below ``root``, ordered by directory name.

    ``root`` may be a single run/report directory or a parent directory. The
    bundled sample report is appended only when requested and when it is not
    already part of the discovered set.
    """

    entries: list[ArtifactEntry] = []
    seen: set[Path] = set()
    for path in _candidate_paths(root):
        kind = _kind(path)
        if kind is None:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            entries.append(_entry(path, kind))
        except OSError:
            continue

    if include_sample and SAMPLE_REPORT.is_dir():
        resolved = SAMPLE_REPORT.resolve()
        if resolved not in seen:
            entries.append(_entry(SAMPLE_REPORT, "report", name="sample-report"))

    return entries


def catalog(root: Path | None = None, *, include_sample: bool = True) -> list[ArtifactEntry]:
    """Discover real artifacts, falling back to the bundled sample when empty."""

    root = root or DEFAULT_ROOT
    entries = discover(root)
    if entries or not include_sample:
        return entries
    sample = discover(SAMPLE_REPORT)
    return [replace(entry, kind="sample", name="sample-report (bundled)") for entry in sample]


# ---------------------------------------------------------------------------
# detail projection
# ---------------------------------------------------------------------------


def _service_rows(
    evaluation: dict[str, Any] | None,
    history: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> tuple[ServiceRow, ...]:
    verified_network = (evaluation or {}).get("classification") == (
        "NATIVE_MULTI_SERVICE_EVALUATION"
    )

    rows: list[ServiceRow] = []
    if evaluation:
        for index, service in enumerate(_rows(evaluation.get("services")), 1):
            metrics = _metric_map(service.get("metrics"))
            delivered = _actual(metrics, "delivered_cargo")
            revenue = metrics.get("delivery_revenue")
            game_time = _dict(service.get("game_time"))
            rows.append(
                ServiceRow(
                    service=str(service.get("demand_id") or f"service-{index}"),
                    status=(
                        "VERIFIED_BATCH"
                        if verified_network and number(delivered) is not None
                        else UNKNOWN
                    ),
                    vehicle=display(_actual(metrics, "vehicles")),
                    delivered=display(delivered),
                    revenue=(
                        money(revenue.get("actual"))
                        if revenue is not None and revenue.get("comparison") == "comparable"
                        else UNKNOWN
                    ),
                    capex=money(
                        _sum_actual(metrics, ("vehicle_purchase", "exclusive_infrastructure_capex"))
                    ),
                    backlog=UNKNOWN,
                    delivered_date=plain(game_time.get("final_cargo_delivery_date")),
                )
            )

    if not rows and history:
        for index, service in enumerate(_rows(history.get("services")), 1):
            rows.append(
                ServiceRow(
                    service=f"service-{index}",
                    status=display(service.get("status")),
                    vehicle=display(service.get("vehicle")),
                    delivered=display(service.get("delivered_cargo")),
                    revenue=money(service.get("revenue_gbp")),
                    capex=money(service.get("command_expenses_gbp")),
                    backlog=display(service.get("cargo_backlog")),
                    delivered_date=UNKNOWN,
                )
            )

    if not rows and receipt:
        for index, service in enumerate(_receipt_services(receipt), 1):
            label = f"{display(service.get('source'))} -> {display(service.get('destination'))}"
            rows.append(
                ServiceRow(
                    service=label if label != f"{UNKNOWN} -> {UNKNOWN}" else f"service-{index}",
                    status="RECEIPT",
                    vehicle=display(service.get("vehicle")),
                    delivered=display(service.get("delivered")),
                    revenue=money(service.get("payment_income")),
                    capex=money(service.get("construction_purchase_spending")),
                    backlog=UNKNOWN,
                    delivered_date=UNKNOWN,
                )
            )
    return tuple(rows)


def _metric_rows(evaluation: dict[str, Any] | None) -> tuple[MetricRow, ...]:
    if not evaluation:
        return ()
    rows: list[MetricRow] = []
    for scope, key in (
        ("network", "metrics"),
        ("verified_batch_subtotal", "verified_batch_subtotals"),
    ):
        for metric in _rows(evaluation.get(key)):
            rows.append(
                MetricRow(
                    scope=str(metric.get("scope") or scope),
                    name=str(metric.get("name") or UNKNOWN),
                    planned=display(metric.get("planned")),
                    actual=display(metric.get("actual")),
                    difference=display(metric.get("difference")),
                    unit=str(metric.get("unit") or ""),
                    comparison=str(metric.get("comparison") or ""),
                )
            )
    return tuple(rows)


def _point_rows(history: dict[str, Any] | None) -> tuple[PointRow, ...]:
    rows = []
    for point in _rows((history or {}).get("points")):
        tick = point.get("tick")
        rows.append(
            PointRow(
                tick=tick if isinstance(tick, int) else None,
                service=display(point.get("service")),
                cargo=number(point.get("cumulative_delivered_cargo")),
                revenue=number(point.get("cumulative_revenue_gbp")),
                throughput=number(point.get("throughput_cargo_per_script_tick")),
                revenue_rate=number(point.get("revenue_gbp_per_script_tick")),
            )
        )
    return tuple(rows)


def _finance_rows(
    path: Path,
    evaluation: dict[str, Any] | None,
    history: dict[str, Any] | None,
) -> tuple[FinanceRow, ...]:
    rows: list[FinanceRow] = []
    reconciliation = read_json(path / "financial-reconciliation.json")
    if reconciliation:
        labels = (
            ("initial_cash", "Initial cash"),
            ("final_cash", "Final cash"),
            ("funded_cash", "Funded cash"),
            ("command_construction_purchase_costs", "Command construction/purchase"),
            ("freight_revenue", "Freight revenue"),
            ("unallocated_company_cash_decrease", "Unallocated cash decrease"),
            ("expense_category", "Expense category"),
            ("operating_costs", "Operating costs"),
            ("net_profit", "Net profit"),
        )
        for key, label in labels:
            if key in reconciliation:
                value = reconciliation[key]
                rows.append(
                    FinanceRow(
                        label=label,
                        value=display(value) if key == "expense_category" else money(value),
                    )
                )
        return tuple(rows)

    if history:
        for key, label in (
            ("observed_company_cash_gbp", "Observed company cash"),
            ("derived_completed_revenue_gbp", "Delivered revenue"),
            ("derived_completed_command_expenses_gbp", "Command expenses"),
        ):
            if key in history:
                rows.append(FinanceRow(label=label, value=money(history[key])))
        if rows:
            return tuple(rows)

    metrics = _metric_map((evaluation or {}).get("metrics"))
    for key, label in (
        ("delivery_revenue", "Delivery revenue"),
        ("total_capex", "Total CAPEX"),
        ("infrastructure_capex", "Infrastructure CAPEX"),
        ("vehicle_purchase", "Vehicle purchase"),
    ):
        if key in metrics:
            rows.append(FinanceRow(label=label, value=money(metrics[key].get("actual"))))
    return tuple(rows)


def _manifest_digests(path: Path) -> dict[str, str]:
    for name in MANIFEST_NAMES:
        manifest = path / name
        if not manifest.is_file():
            continue
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result = {}
        for line in text.splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            digest, filename = parts[0], parts[1].strip().lstrip("*")
            if len(digest) == 64:
                result[Path(filename).name] = digest
        return result
    return {}


def _file_rows(path: Path) -> tuple[FileRow, ...]:
    digests = _manifest_digests(path)
    rows: list[FileRow] = []
    try:
        children = sorted(
            (child for child in path.iterdir() if child.is_file()),
            key=lambda item: item.name,
        )
    except OSError:
        return ()
    for child in children:
        try:
            size = child.stat().st_size
        except OSError:
            size = 0
        rows.append(FileRow(name=child.name, size=size, digest=digests.get(child.name)))
    return tuple(rows)


def _notes(
    entry: ArtifactEntry,
    evaluation: dict[str, Any] | None,
    history: dict[str, Any] | None,
) -> tuple[str, ...]:
    notes = [
        "Read-only: this view never launches OpenTTD, opens an Admin connection, "
        "or writes into evidence.",
        "UNKNOWN means the retained evidence does not establish the value. It is not zero.",
    ]
    if entry.kind == "run" and not (entry.path / "evaluation.json").is_file():
        notes.append(
            "No P07 report in this directory. Generate one offline with "
            "'python -m app.openttd_demo report --source <this directory>'."
        )
    for limitation in (evaluation or {}).get("limitations") or ():
        notes.append(str(limitation))
    trend = (history or {}).get("trend_basis")
    if trend:
        notes.append(str(trend))
    if not (entry.path / "artifact-manifest.sha256").is_file():
        notes.append("No artifact manifest in this directory; file hashes are unavailable.")
    return tuple(notes)


def load_detail(entry: ArtifactEntry | Path) -> RunDetail:
    """Build the display projection for one catalog entry."""

    if isinstance(entry, Path):
        kind = _kind(entry) or "run"
        entry = _entry(entry, kind)
    path = entry.path
    evaluation = read_json(path / "evaluation.json")
    history = read_json(path / "operational-history.json")
    receipt = read_json(path / "receipt.json", limit=8 * 1024 * 1024)
    return RunDetail(
        entry=entry,
        services=_service_rows(evaluation, history, receipt),
        metrics=_metric_rows(evaluation),
        points=_point_rows(history),
        finance=_finance_rows(path, evaluation, history),
        files=_file_rows(path),
        notes=_notes(entry, evaluation, history),
    )
