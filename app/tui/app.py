"""Textual application for retained OpenTTD demo evidence.

The app is a read-only operator console: it reads catalog/report JSON that the
Python demo already wrote and renders runs, services, planned-vs-actual metrics,
derived charts and the evidence file list. Starting a game, opening an Admin
connection or mutating artifacts stays outside this UI.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from app.tui.data import (
    ArtifactEntry,
    MetricRow,
    PointRow,
    RunDetail,
    catalog,
    load_detail,
    money,
    number,
)

HELP_TEXT = """# OpenTTD evidence TUI

Read-only view of runs and P07 reports written by the Python demo.

## Keys

| Key | Action |
| --- | --- |
| Up / Down | Move through the artifact list |
| Tab | Move focus into the detail tabs |
| r | Rescan the artifact root |
| ? | Show this help |
| q | Quit |

## What is shown

* **Summary** — identity, world, finance readback and explicit limitations.
* **Services** — per-service delivered cargo, revenue and CAPEX where retained.
* **Metrics** — P07 planned-versus-actual values and their scope.
* **Charts** — derived milestones and CAPEX bars from retained readbacks.
* **Evidence** — files in the artifact directory and manifest hashes.

## Evidence rules

* `UNKNOWN` means the retained evidence does not establish the value. It is not zero.
* Per-service revenue stays `UNKNOWN` unless the evaluation records a comparable value.
* OPEX, net profit and ROI stay `UNKNOWN` unless the evidence records them.

This TUI never launches OpenTTD, opens an Admin connection, consumes a claim or
writes into an evidence directory.
"""


class HelpScreen(ModalScreen[None]):
    """Keyboard help overlay."""

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close"),
        Binding("question_mark", "dismiss_help", "Close"),
        Binding("q", "dismiss_help", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Markdown(HELP_TEXT)
            yield Static("Press Esc to close.", id="help-hint")

    def action_dismiss_help(self) -> None:
        self.dismiss()


def _status_style(status: str) -> str:
    upper = status.upper()
    if "FAILED" in upper or "REJECTED" in upper:
        return "bold red"
    if "UNKNOWN" in upper or "PENDING" in upper or "AUTHORIZATION" in upper:
        return "bold yellow"
    if "VERIFIED" in upper or "PROVEN" in upper:
        return "bold green"
    return "white"


def _size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _md(value: object) -> str:
    """Escape a value for a Markdown table cell."""

    return str(value).replace("|", "\\|").replace("\n", " ")


def _bars(rows: list[tuple[str, float | None]], unit: str, *, width: int = 28) -> Text:
    """Render a small deterministic ASCII/block bar chart."""

    rendered = Text()
    known = [(label, value) for label, value in rows if value is not None]
    if not known:
        rendered.append("UNKNOWN (no retained values)\n", style="yellow")
        return rendered
    peak = max(abs(value) for _, value in known)
    for label, value in rows:
        rendered.append(f"  {label:<16}", style="dim")
        if value is None:
            rendered.append(f"{'UNKNOWN':>12}\n", style="yellow")
            continue
        filled = int(round(abs(value) / peak * width)) if peak else 0
        rendered.append("█" * filled, style="cyan")
        rendered.append("░" * (width - filled), style="grey37")
        shown = money(value) if unit == "GBP" else f"{value:,.2f}" if value % 1 else f"{value:,.0f}"
        rendered.append(f"  {shown:>14} {unit}\n")
    return rendered


def _chart_text(detail: RunDetail) -> Text:
    text = Text()
    text.append("Derived charts from retained readbacks\n", style="bold")
    text.append("Missing values stay UNKNOWN; nothing is interpolated.\n\n", style="dim")

    text.append(f"Delivery milestones ({len(detail.points)} retained)\n", style="bold")
    if detail.points:
        text.append(
            _bars([(_point_label(point), point.revenue) for point in detail.points], "GBP")
        )
        text.append("\nCumulative delivered cargo\n", style="bold")
        text.append(
            _bars([(_point_label(point), point.cargo) for point in detail.points], "cargo")
        )
        text.append("\nThroughput between milestones\n", style="bold")
        text.append(
            _bars(
                [(_point_label(point), point.throughput) for point in detail.points],
                "cargo/tick",
            )
        )
    else:
        text.append(
            "UNKNOWN (no operational-history.json delivery points in this artifact)\n",
            style="yellow",
        )

    capex_rows = [
        (metric.name.replace("_", " "), number(metric.actual))
        for metric in detail.metrics
        if metric.scope == "network_batch"
        and metric.name in ("infrastructure_capex", "vehicle_purchase", "total_capex")
    ]
    text.append("\nNetwork CAPEX (actual from native commands)\n", style="bold")
    if capex_rows:
        text.append(_bars(capex_rows, "GBP"))
    else:
        text.append("UNKNOWN (no network CAPEX metrics in this artifact)\n", style="yellow")

    text.append(
        "\nOperating expenses, net profit and ROI remain UNKNOWN unless listed above.\n",
        style="dim",
    )
    return text


def _point_label(point: PointRow) -> str:
    return f"tick {point.tick}" if point.tick is not None else f"svc {point.service}"


class OpenTTDTui(App[None]):
    """Read-only operator console for retained freight evidence."""

    CSS_PATH = "tui.tcss"
    TITLE = "OpenTTD evidence TUI"
    SUB_TITLE = "read-only · no native launch"

    BINDINGS = [
        Binding("r", "refresh_catalog", "Refresh"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        root: Path | None = None,
        *,
        include_sample: bool = True,
    ) -> None:
        super().__init__()
        self.root = Path(root) if root is not None else None
        self.include_sample = include_sample
        self.entries: list[ArtifactEntry] = []
        self.current: RunDetail | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("RETAINED EVIDENCE", id="runs-title")
                yield DataTable(id="runs", cursor_type="row", zebra_stripes=True)
            with Vertical(id="detail"):
                yield Static("Select an artifact", id="detail-title")
                with TabbedContent(initial="tab-summary"):
                    with TabPane("Summary", id="tab-summary"):
                        yield VerticalScroll(Markdown("Loading…", id="summary"))
                    with TabPane("Services", id="tab-services"):
                        yield DataTable(id="services", cursor_type="row", zebra_stripes=True)
                    with TabPane("Metrics", id="tab-metrics"):
                        yield DataTable(id="metrics", cursor_type="row", zebra_stripes=True)
                    with TabPane("Charts", id="tab-charts"):
                        yield VerticalScroll(Static(id="charts"))
                    with TabPane("Evidence", id="tab-evidence"):
                        yield DataTable(id="evidence", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#runs", DataTable).focus()
        self.refresh_catalog(force=True)

    # -- catalog ---------------------------------------------------------

    def refresh_catalog(self, *, force: bool = False) -> None:
        selected = self.current.entry.path if self.current else None
        try:
            entries = catalog(self.root, include_sample=self.include_sample)
        except OSError as error:
            self.notify(f"Cannot scan artifacts: {error}", severity="error")
            entries = []

        self.entries = entries
        table = self.query_one("#runs", DataTable)
        table.clear(columns=True)
        if not entries:
            self.current = None
            table.add_columns("Artifact")
            table.add_row("No retained artifacts found")
            for table_id in ("#services", "#metrics", "#evidence"):
                self.query_one(table_id, DataTable).clear(columns=True)
            self.query_one("#charts", Static).update("No retained artifacts.")
            self.query_one("#detail-title", Static).update(
                "No artifacts. Run the demo, then press r to rescan."
            )
            self.query_one("#summary", Markdown).update(
                "# No retained artifacts\n\n"
                "The TUI looked in the configured artifact root. Run a demo or point "
                "the app at retained evidence with `--root`.\n\n"
                f"Root: `{_md(self.root or 'artifacts/demos')}`\n"
            )
            return

        table.add_columns("Artifact", "Kind", "Status", "Svc", "Cargo", "Revenue")
        for index, entry in enumerate(entries):
            table.add_row(
                entry.name,
                entry.kind,
                Text(entry.status, style=_status_style(entry.status)),
                _unknown(entry.services_count),
                _unknown(entry.delivered),
                money(entry.revenue),
                key=str(index),
            )

        target = 0
        if selected is not None:
            for index, entry in enumerate(entries):
                if entry.path == selected:
                    target = index
                    break
        table.move_cursor(row=target)
        self.show_entry(target, force=force)
        self.sub_title = f"read-only · {len(entries)} artifact(s)"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "runs":
            return
        try:
            index = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        self.show_entry(index)

    # -- detail ----------------------------------------------------------

    def show_entry(self, index: int, *, force: bool = False) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        if not force and self.current is not None and self.current.entry.path == entry.path:
            return
        try:
            detail = load_detail(entry)
        except (OSError, ValueError) as error:
            self.notify(f"Cannot read {entry.name}: {error}", severity="error")
            return
        self.current = detail
        self.query_one("#detail-title", Static).update(
            f"{entry.name}  ·  {entry.kind}  ·  {entry.status}"
        )
        self.query_one("#summary", Markdown).update(self._summary_markdown(detail))
        self._fill_services(detail)
        self._fill_metrics(detail)
        self.query_one("#charts", Static).update(_chart_text(detail))
        self._fill_evidence(detail)

    def _summary_markdown(self, detail: RunDetail) -> str:
        entry = detail.entry
        lines = [
            f"## {_md(entry.name)}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Path | `{_md(entry.path)}` |",
            f"| Kind | {_md(entry.kind)} |",
            f"| Status | {_md(entry.status)} |",
            f"| World | {_md(entry.world)} |",
            f"| Experiment | {_md(entry.experiment)} |",
            f"| Services | {_unknown(entry.services_count)} |",
            f"| Delivered cargo | {_md(_unknown(entry.delivered))} |",
            f"| Freight revenue | {_md(money(entry.revenue))} |",
            f"| Command CAPEX | {_md(money(entry.capex))} |",
            "",
            "### Finance readback",
            "",
        ]
        if detail.finance:
            lines.extend(["| Metric | Value |", "| --- | --- |"])
            for row in detail.finance:
                lines.append(f"| {_md(row.label)} | {_md(row.value)} |")
        else:
            lines.append("_No financial readback in this artifact._")
        lines.extend(["", "### Notes", ""])
        lines.extend(f"- {_md(note)}" for note in detail.notes)
        lines.append("")
        return "\n".join(lines)

    def _fill_services(self, detail: RunDetail) -> None:
        table = self.query_one("#services", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Service",
            "Status",
            "Vehicle",
            "Delivered",
            "Revenue",
            "CAPEX",
            "Backlog",
            "Delivery date",
        )
        if not detail.services:
            table.add_row("No service rows in this artifact", *[""] * 7)
            return
        for row in detail.services:
            table.add_row(
                row.service,
                Text(row.status, style=_status_style(row.status)),
                row.vehicle,
                row.delivered,
                row.revenue,
                row.capex,
                row.backlog,
                row.delivered_date,
            )

    def _fill_metrics(self, detail: RunDetail) -> None:
        table = self.query_one("#metrics", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Scope", "Metric", "Planned", "Actual", "Difference", "Unit", "Comparison"
        )
        if not detail.metrics:
            table.add_row("No P07 evaluation metrics in this artifact", *[""] * 6)
            return
        for metric in detail.metrics:
            table.add_row(*self._metric_cells(metric))

    @staticmethod
    def _metric_cells(metric: MetricRow) -> tuple[str, ...]:
        return (
            metric.scope,
            metric.name.replace("_", " "),
            metric.planned,
            metric.actual,
            metric.difference,
            metric.unit or "UNKNOWN",
            metric.comparison or "UNKNOWN",
        )

    def _fill_evidence(self, detail: RunDetail) -> None:
        table = self.query_one("#evidence", DataTable)
        table.clear(columns=True)
        table.add_columns("File", "Size", "SHA-256 (manifest)")
        if not detail.files:
            table.add_row("No files in this artifact", "", "")
            return
        for row in detail.files:
            digest = f"{row.digest[:12]}..." if row.digest else "UNKNOWN"
            table.add_row(row.name, _size(row.size), digest)

    # -- actions ---------------------------------------------------------

    def action_refresh_catalog(self) -> None:
        self.refresh_catalog(force=True)
        self.notify("Catalog refreshed.")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def _unknown(value: object) -> str:
    if value is None or value == "" or value == "null":
        return "UNKNOWN"
    return str(value)
