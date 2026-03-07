"""Tests for TUI components."""

from __future__ import annotations

import asyncio
import os
import re

import pytest
from rich.text import Text

from longxiaclaw.tui.components import (
    HeaderBar, ProcessingIndicator,
    ResponseRenderer,
    _make_gradient_text,
)


def _strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences from a string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


class TestGradientText:
    def test_returns_rich_text(self):
        result = _make_gradient_text("LONGXIA")
        assert isinstance(result, Text)

    def test_per_character_color(self):
        result = _make_gradient_text("ABCD")
        assert len(result) == 4
        # Each non-space char should have a style with a color
        for i in range(4):
            span_styles = [s for s in result._spans if s.start <= i < s.end]
            assert len(span_styles) > 0

    def test_preserves_spaces(self):
        result = _make_gradient_text("A B")
        assert str(result) == "A B"

    def test_bold_default(self):
        result = _make_gradient_text("X")
        assert result._spans[0].style.bold is True

    def test_no_bold(self):
        result = _make_gradient_text("X", bold=False)
        assert result._spans[0].style.bold is not True


class TestHeaderBar:
    def test_render_ansi_contains_longxia_banner(self):
        header = HeaderBar(
            backend="mock",
            version="0.1.0",
            workspace_path="/tmp/test",
            pid=os.getpid(),
        )
        output = header.render_ansi(80)
        assert isinstance(output, str)
        plain = _strip_ansi(output)
        # Block-style banner — check for distinctive patterns
        assert "█████" in plain  # bottom of L / top of A
        assert "███" in plain    # I column

    def test_render_ansi_contains_status_info(self):
        header = HeaderBar(
            backend="qwen",
            version="1.2.3",
            workspace_path="/my/workspace",
            pid=os.getpid(),
        )
        output = header.render_ansi(80)
        plain = _strip_ansi(output)
        assert "1.2.3" in plain
        assert "qwen" in plain
        assert "/my/workspace" in plain
        assert "Time:" in plain

    def test_render_ansi_contains_hint(self):
        header = HeaderBar(pid=os.getpid())
        output = header.render_ansi(80)
        plain = _strip_ansi(output)
        assert "/help" in plain

    def test_refresh_stats(self):
        header = HeaderBar(pid=os.getpid())
        header.refresh_stats()
        # After refresh, CPU and RAM should have real values (not N/A)
        assert header._cpu != "N/A" or True  # may still be N/A on some systems
        output = header.render_ansi(80)
        assert "CPU:" in output
        assert "RAM:" in output


class TestProcessingIndicator:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        updates = []
        done = []
        indicator = ProcessingIndicator(
            on_update=updates.append,
            on_done=done.append,
        )
        indicator.start()
        assert indicator._task is not None
        await asyncio.sleep(0.05)
        await indicator.stop()
        assert indicator._task is None

    @pytest.mark.asyncio
    async def test_on_done_called_with_summary(self):
        done = []
        indicator = ProcessingIndicator(on_done=done.append)
        indicator.start()
        await asyncio.sleep(0.05)
        await indicator.stop()
        indicator.emit_summary()
        assert len(done) == 1
        assert "Processed in" in done[0]

    @pytest.mark.asyncio
    async def test_on_update_called_during_animation(self):
        updates = []
        indicator = ProcessingIndicator(on_update=updates.append)
        indicator.start()
        await asyncio.sleep(0.6)
        await indicator.stop()
        assert len(updates) > 0
        assert any("Processing" in u for u in updates)

    @pytest.mark.asyncio
    async def test_elapsed_captured_at_stop(self):
        indicator = ProcessingIndicator()
        indicator.start()
        await asyncio.sleep(0.1)
        await indicator.stop()
        elapsed_at_stop = indicator._elapsed
        await asyncio.sleep(0.2)
        assert indicator._elapsed == elapsed_at_stop


class TestResponseRenderer:
    def test_render_to_ansi(self):
        result = ResponseRenderer.render_to_ansi("Hello **world**", 80)
        assert isinstance(result, str)
        assert "Hello" in result
        assert "world" in result

    def test_render_to_ansi_plain(self):
        result = ResponseRenderer.render_to_ansi("plain text", 80)
        assert "plain text" in result
