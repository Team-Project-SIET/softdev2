"""Smoke tests for the optional Textual screen.

These skip when Textual is absent, so the core test suite keeps working without
the ``tui`` dependency group.
"""

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Markdown, Static  # noqa: E402

from app.tui.app import HelpScreen, OpenTTDTui  # noqa: E402
from app.tui.data import SAMPLE_REPORT  # noqa: E402


def test_app_renders_sample_and_opens_help() -> None:
    async def scenario() -> None:
        app = OpenTTDTui(SAMPLE_REPORT)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()

            runs = app.query_one("#runs", DataTable)
            assert runs.row_count == 1
            assert "sample-report" in str(app.query_one("#detail-title", Static).content)

            services = app.query_one("#services", DataTable)
            metrics = app.query_one("#metrics", DataTable)
            evidence = app.query_one("#evidence", DataTable)
            assert services.row_count == 3
            assert metrics.row_count == 15
            assert evidence.row_count > 0

            summary = app.query_one("#summary", Markdown)
            assert "Finance readback" in summary.source

            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(scenario())


def test_app_reports_an_empty_artifact_root(tmp_path) -> None:
    async def scenario() -> None:
        app = OpenTTDTui(tmp_path, include_sample=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#runs", DataTable).row_count == 1
            title = str(app.query_one("#detail-title", Static).content)
            assert "No artifacts" in title

    asyncio.run(scenario())
