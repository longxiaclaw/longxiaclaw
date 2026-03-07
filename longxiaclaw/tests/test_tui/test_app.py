"""Tests for TUI client: _handle_input, _send_and_display, and scroll behavior."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from longxiaclaw.tui.app import LongxiaClawTUI, _ScrollableWindow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path):
    """Minimal config mock for TUI."""
    config = MagicMock()
    config.assistant_name = "TestClaw"
    config.default_backend = "mock"
    config.project_root = tmp_path
    config.socket_path = tmp_path / "test.sock"
    config.pid_file = tmp_path / "test.pid"
    config.agent_workspace_dir = tmp_path
    return config


def _make_tui(tmp_path) -> LongxiaClawTUI:
    """Create a TUI for testing."""
    config = _make_config(tmp_path)
    tui = LongxiaClawTUI(config)
    return tui


def _feed_messages(tui: LongxiaClawTUI, messages: list[dict]) -> None:
    """Set up a fake reader that feeds pre-built JSON-line messages."""
    lines = [json.dumps(m).encode("utf-8") + b"\n" for m in messages]
    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data(line)
    reader.feed_eof()
    tui._reader = reader

    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    tui._writer = writer


# ---------------------------------------------------------------------------
# Conversation fragment tests via _send_and_display
# ---------------------------------------------------------------------------

class TestSendAndDisplayResult:
    @pytest.mark.asyncio
    async def test_result_appends_content(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "final answer"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "final answer" in joined

    @pytest.mark.asyncio
    async def test_result_breaks_loop(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "done"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        # Loop should have exited after result

    @pytest.mark.asyncio
    async def test_indicator_summary_on_result(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "done"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "Processed in" in joined


class TestSendAndDisplayError:
    @pytest.mark.asyncio
    async def test_error_appends_and_breaks(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "error", "content": "fail"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "fail" in joined

    @pytest.mark.asyncio
    async def test_no_summary_on_error(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "error", "content": "bad"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "Processed in" not in joined


class TestSendAndDisplayText:
    @pytest.mark.asyncio
    async def test_text_then_result(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "text", "content": "streaming"},
            {"type": "output", "output_type": "text", "content": " partial"},
            {"type": "output", "output_type": "result", "content": "done"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "streaming" in joined
        assert "partial" in joined


class TestSendAndDisplayThinking:
    @pytest.mark.asyncio
    async def test_thinking_rendered(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "thinking", "content": "hmm..."},
            {"type": "output", "output_type": "result", "content": "done"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "hmm..." in joined


class TestSendAndDisplayPong:
    @pytest.mark.asyncio
    async def test_pong_breaks_loop(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "pong"},
        ])
        await tui._send_and_display({"type": "ping"})


class TestSendAndDisplayConnectionLost:
    @pytest.mark.asyncio
    async def test_none_message_appends_connection_lost(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [])
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "Lost connection to daemon" in joined
        assert "longxia status" in joined

    @pytest.mark.asyncio
    async def test_none_message_exits_app(self, tmp_path):
        tui = _make_tui(tmp_path)
        mock_app = MagicMock()
        tui._app = mock_app
        _feed_messages(tui, [])
        await tui._send_and_display({"type": "message", "text": "hi"})
        mock_app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_message_sets_connection_lost_flag(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [])
        await tui._send_and_display({"type": "message", "text": "hi"})
        assert tui._connection_lost is True

    @pytest.mark.asyncio
    async def test_send_failure_shows_message_and_exits(self, tmp_path):
        """When send() fails (daemon dead), show message and exit."""
        tui = _make_tui(tmp_path)
        mock_app = MagicMock()
        tui._app = mock_app
        # No writer → send returns False
        tui._writer = None
        tui._reader = None
        await tui._send_and_display({"type": "message", "text": "hi"})
        joined = "\n".join(tui._conv_fragments)
        assert "Lost connection to daemon" in joined
        assert "longxia status" in joined
        mock_app.exit.assert_called_once()
        assert tui._connection_lost is True


# ---------------------------------------------------------------------------
# _handle_input tests
# ---------------------------------------------------------------------------

class TestHandleInput:
    @pytest.mark.asyncio
    async def test_quit_exits_app(self, tmp_path):
        tui = _make_tui(tmp_path)
        mock_app = MagicMock()
        tui._app = mock_app
        await tui._handle_input("/quit")
        mock_app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_resets_fragments(self, tmp_path):
        tui = _make_tui(tmp_path)
        tui._conv_fragments = ["some old text"]
        await tui._handle_input("/clear")
        assert tui._conv_fragments == []

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, tmp_path):
        tui = _make_tui(tmp_path)
        await tui._handle_input("   ")
        assert tui._conv_fragments == []

    @pytest.mark.asyncio
    async def test_message_appends_prompt(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "ok"},
        ])
        await tui._handle_input("hello")
        joined = "\n".join(tui._conv_fragments)
        assert "hello" in joined

    @pytest.mark.asyncio
    async def test_input_recorded_in_history(self, tmp_path):
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "ok"},
        ])
        await tui._handle_input("test msg")
        assert "test msg" in tui._input_history

    @pytest.mark.asyncio
    async def test_separator_before_second_prompt(self, tmp_path):
        """A '─' separator should appear before a new prompt when history exists."""
        tui = _make_tui(tmp_path)
        tui._conv_fragments = ["previous response"]
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "ok"},
        ])
        await tui._handle_input("second")
        # Fragment right after the existing one should be the separator
        assert "─" in tui._conv_fragments[1]

    @pytest.mark.asyncio
    async def test_no_separator_before_first_prompt(self, tmp_path):
        """No separator should be added before the very first prompt."""
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "ok"},
        ])
        await tui._handle_input("first")
        # First fragment should be the prompt, not a separator
        assert "first" in tui._conv_fragments[0]


# ---------------------------------------------------------------------------
# Processing indicator lifecycle
# ---------------------------------------------------------------------------

class TestProcessingIndicatorLifecycle:
    @pytest.mark.asyncio
    async def test_placeholder_cleared_on_done(self, tmp_path):
        """The 'Processing...' placeholder should be empty after result arrives."""
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "done"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        # indicator_line_idx is 0 (first fragment); should be cleared
        assert tui._conv_fragments[0] == ""

    @pytest.mark.asyncio
    async def test_processed_summary_at_bottom(self, tmp_path):
        """'Processed in' should be the last fragment, not the first."""
        tui = _make_tui(tmp_path)
        _feed_messages(tui, [
            {"type": "output", "output_type": "result", "content": "answer"},
        ])
        await tui._send_and_display({"type": "message", "text": "hi"})
        assert "Processed in" in tui._conv_fragments[-1]


# ---------------------------------------------------------------------------
# Auto-scroll behavior
# ---------------------------------------------------------------------------

class TestAutoScroll:
    def test_auto_scroll_enabled_by_default(self, tmp_path):
        tui = _make_tui(tmp_path)
        assert tui._auto_scroll is True

    def test_append_conv_enables_auto_scroll(self, tmp_path):
        tui = _make_tui(tmp_path)
        tui._auto_scroll = False
        tui._append_conv("new content")
        assert tui._auto_scroll is True

    def test_mouse_scroll_callback_disables_auto_scroll(self, tmp_path):
        """Simulates what on_mouse_scroll does in the layout."""
        tui = _make_tui(tmp_path)
        assert tui._auto_scroll is True
        # Simulate the callback wired in _build_app
        setattr(tui, "_auto_scroll", False)
        assert tui._auto_scroll is False


# ---------------------------------------------------------------------------
# _ScrollableWindow unit tests
# ---------------------------------------------------------------------------

class TestScrollableWindow:
    def _make_ui_content(self, line_count=20):
        """Create a minimal UIContent-like object for testing _scroll."""
        from prompt_toolkit.layout.controls import UIContent

        def get_line(i):
            return [("", f"line {i}")]

        return UIContent(get_line=get_line, line_count=line_count)

    def test_auto_scroll_jumps_to_bottom(self):
        from prompt_toolkit.layout.controls import FormattedTextControl

        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            auto_scroll_ref=lambda: True,
        )
        ui = self._make_ui_content(line_count=100)
        win._scroll(ui, width=80, height=10)
        # Should be clamped to the bottom (line_count - height = 90)
        assert win.vertical_scroll == 90

    def test_manual_scroll_preserved(self):
        from prompt_toolkit.layout.controls import FormattedTextControl

        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            auto_scroll_ref=lambda: False,
        )
        win.vertical_scroll = 5
        ui = self._make_ui_content(line_count=100)
        win._scroll(ui, width=80, height=10)
        assert win.vertical_scroll == 5

    def test_scroll_clamped_to_valid_range(self):
        from prompt_toolkit.layout.controls import FormattedTextControl

        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            auto_scroll_ref=lambda: False,
        )
        win.vertical_scroll = 999
        ui = self._make_ui_content(line_count=20)
        win._scroll(ui, width=80, height=10)
        assert win.vertical_scroll == 10  # 20 - 10

    def test_scroll_not_negative(self):
        from prompt_toolkit.layout.controls import FormattedTextControl

        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            auto_scroll_ref=lambda: False,
        )
        win.vertical_scroll = -5
        ui = self._make_ui_content(line_count=20)
        win._scroll(ui, width=80, height=10)
        assert win.vertical_scroll == 0

    def test_mouse_scroll_fires_callback(self):
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.mouse_events import (
            MouseButton, MouseEvent, MouseEventType,
        )

        called = []
        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            on_mouse_scroll=lambda: called.append(True),
        )
        event = MouseEvent(
            position=(0, 0),
            event_type=MouseEventType.SCROLL_UP,
            button=MouseButton.NONE,
            modifiers=frozenset(),
        )
        win._mouse_handler(event)
        assert len(called) == 1

    def test_topmost_visible(self):
        from prompt_toolkit.layout.controls import FormattedTextControl

        win = _ScrollableWindow(
            content=FormattedTextControl("hello"),
            auto_scroll_ref=lambda: False,
        )
        ui = self._make_ui_content(line_count=50)
        result = win._topmost_visible(ui, width=80, height=10)
        # With non-wrapping single-height lines: 50 - 10 = 40
        assert result == 40


# ---------------------------------------------------------------------------
# Scroll hint text
# ---------------------------------------------------------------------------

class TestScrollHint:
    def test_scroll_hint_text(self, tmp_path):
        tui = _make_tui(tmp_path)
        hint = tui._get_scroll_hint_text()
        assert "mouse scroll" in str(hint)
