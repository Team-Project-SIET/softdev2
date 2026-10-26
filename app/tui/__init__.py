"""Read-only terminal UI over retained OpenTTD demo evidence.

The package is intentionally additive: no planner, executor or native runtime
module imports it, and the TUI never launches OpenTTD, opens an Admin connection
or writes into an evidence directory.
"""

from app.tui.data import (
    ArtifactEntry,
    MetricRow,
    RunDetail,
    ServiceRow,
    catalog,
    load_detail,
)

__all__ = [
    "ArtifactEntry",
    "MetricRow",
    "RunDetail",
    "ServiceRow",
    "catalog",
    "load_detail",
]
