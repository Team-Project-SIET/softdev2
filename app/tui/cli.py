"""Command line entry point for the read-only evidence TUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.tui.data import DEFAULT_ROOT, catalog, display, money

MISSING_TUI = (
    "The optional TUI dependency is not installed. From the repository root run:\n"
    "  uv sync --locked --group tui\n"
    "or install Textual directly with:\n"
    "  python -m pip install 'textual>=8.0'\n"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openttd-tui",
        description=(
            "Read-only terminal view of retained OpenTTD demo evidence. "
            "This command never launches OpenTTD or opens an Admin connection."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="artifact directory or single run/report directory (default: artifacts/demos)",
    )
    parser.add_argument(
        "--no-sample",
        action="store_true",
        help="do not fall back to the bundled sample report when the root is empty",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="print the catalog as text instead of starting the TUI",
    )
    return parser


def _dump(root: Path, *, include_sample: bool) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    entries = catalog(root, include_sample=include_sample)
    if not entries:
        print(f"No retained artifacts found below {root}")
        return 0
    print(f"{'NAME':<44} {'KIND':<10} {'STATUS':<44} {'SVC':>3} {'CARGO':>7} {'REVENUE':>10}")
    for entry in entries:
        print(
            f"{entry.name[:44]:<44} {entry.kind:<10} {entry.status[:44]:<44} "
            f"{display(entry.services_count):>3} {display(entry.delivered):>7} "
            f"{money(entry.revenue).replace('£', 'GBP '):>10}"
        )
    print(f"\n{len(entries)} artifact(s) below {root}")
    print("Read-only: no native launch, Admin connection or evidence mutation.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    include_sample = not args.no_sample
    if args.dump:
        return _dump(args.root, include_sample=include_sample)

    try:
        from app.tui.app import OpenTTDTui
    except ModuleNotFoundError as error:
        if error.name in {"textual", "rich"}:
            sys.stderr.write(MISSING_TUI)
            return 2
        raise

    OpenTTDTui(args.root, include_sample=include_sample).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
