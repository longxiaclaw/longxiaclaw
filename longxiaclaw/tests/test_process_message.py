"""Tests for LongxiaClawDaemon._process_message: the core message processing pipeline."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from longxiaclaw.main import LongxiaClawDaemon
from longxiaclaw.backends.base import AgentResult
from .conftest import FakeWriter, MockBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def daemon(sample_config, mock_backend) -> LongxiaClawDaemon:
    """Create a LongxiaClawDaemon with mocked dependencies for _process_message."""
    d = LongxiaClawDaemon.__new__(LongxiaClawDaemon)
    d._config = sample_config
    d._backend = mock_backend
    d._logger = MagicMock()
    d._agent_busy = False
    d._system_context = ""

    # Memory tag regexes (normally set in __init__)
    d._MEMORY_SAVE_RE = re.compile(r"<memory_save>(.*?)</memory_save>", re.DOTALL)
    d._MEMORY_FORGET_RE = re.compile(r"<memory_forget>(.*?)</memory_forget>", re.DOTALL)

    d._memory = MagicMock()
    d._memory.get_window_text = MagicMock(return_value="")
    d._memory.push_turn = MagicMock()
    d._memory.remember = MagicMock(return_value="Remembered: test")
    d._memory.forget_by_content = MagicMock(return_value="Forgot 1 entry(s): test")
    d._memory.load_context = MagicMock(return_value="")
    d._memory.load_previous_sessions = MagicMock(return_value="")

    d._state_manager = MagicMock()

    d._skill_registry = MagicMock()
    d._skill_registry.get_triggered_skills = MagicMock(return_value=[])
    d._skill_registry.get_prompt_skills = MagicMock(return_value=[])
    d._skill_registry.format_skills_context = MagicMock(return_value="")

    d._log_manager = MagicMock()

    return d


# ---------------------------------------------------------------------------
# Basic message flow
# ---------------------------------------------------------------------------

class TestBasicMessageFlow:
    @pytest.mark.asyncio
    async def test_sends_result(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        result_msgs = [m for m in writer.messages if m.get("output_type") == "result"]
        assert len(result_msgs) == 1
        assert result_msgs[0]["content"] == "Mock response"

    @pytest.mark.asyncio
    async def test_result_has_duration(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        result_msg = [m for m in writer.messages if m.get("output_type") == "result"][0]
        assert "duration_ms" in result_msg
        assert result_msg["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_pushes_turn_to_memory(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.push_turn.assert_called_once_with("hello", "Mock response")

    @pytest.mark.asyncio
    async def test_logs_action(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._log_manager.log_action.assert_called_once()
        call_args = daemon._log_manager.log_action.call_args
        assert call_args[0][0] == "message_processed"

    @pytest.mark.asyncio
    async def test_clears_busy_flag(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert daemon._agent_busy is False


# ---------------------------------------------------------------------------
# Busy guard
# ---------------------------------------------------------------------------

class TestBusyGuard:
    @pytest.mark.asyncio
    async def test_rejects_when_busy(self, daemon):
        daemon._agent_busy = True
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert len(writer.messages) == 1
        assert writer.messages[0]["output_type"] == "error"
        assert "busy" in writer.messages[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_busy_does_not_call_backend(self, daemon, mock_backend):
        daemon._agent_busy = True
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert len(mock_backend.calls) == 0


# ---------------------------------------------------------------------------
# Unsupported backend binary
# ---------------------------------------------------------------------------

class TestUnsupportedBackend:
    @pytest.mark.asyncio
    async def test_unsupported_binary_returns_error(self, daemon, mock_backend):
        mock_backend.is_supported_binary = lambda: False
        mock_backend.SUPPORTED_BINARIES = {"qwen"}
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        error_msgs = [m for m in writer.messages if m.get("output_type") == "error"]
        assert len(error_msgs) == 1
        assert "Unsupported BACKEND_BINARY" in error_msgs[0]["content"]
        assert "qwen" in error_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_unsupported_binary_does_not_call_backend(self, daemon, mock_backend):
        mock_backend.is_supported_binary = lambda: False
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert len(mock_backend.calls) == 0

    @pytest.mark.asyncio
    async def test_unsupported_binary_saves_error_turn(self, daemon, mock_backend):
        mock_backend.is_supported_binary = lambda: False
        mock_backend.SUPPORTED_BINARIES = {"qwen"}
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.push_turn.assert_called_once()
        stored = daemon._memory.push_turn.call_args[0][1]
        assert "Error" in stored


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

class TestPromptAssembly:
    @pytest.mark.asyncio
    async def test_includes_user_text(self, daemon, mock_backend):
        writer = FakeWriter()
        await daemon._process_message("what is Python?", writer)

        prompt = mock_backend.calls[0].prompt
        assert "what is Python?" in prompt

    @pytest.mark.asyncio
    async def test_includes_system_context(self, daemon, mock_backend):
        daemon._system_context = "You are a helpful assistant."
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        prompt = mock_backend.calls[0].prompt
        assert "You are a helpful assistant." in prompt

    @pytest.mark.asyncio
    async def test_includes_window_text(self, daemon, mock_backend):
        daemon._memory.get_window_text.return_value = "User: hi\nAssistant: hello"
        writer = FakeWriter()
        await daemon._process_message("follow up", writer)

        prompt = mock_backend.calls[0].prompt
        assert "Recent conversation" in prompt
        assert "User: hi" in prompt

    @pytest.mark.asyncio
    async def test_passes_working_dir_to_backend(self, daemon, mock_backend):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert mock_backend.calls[0].working_dir == str(daemon._config.agent_workspace_dir)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_backend_error_sends_error_message(self, daemon, mock_backend):
        mock_backend.run = AsyncMock(side_effect=RuntimeError("backend crashed"))
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        error_msgs = [m for m in writer.messages if m.get("output_type") == "error"]
        assert len(error_msgs) == 1
        assert "backend crashed" in error_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_backend_error_clears_busy_flag(self, daemon, mock_backend):
        mock_backend.run = AsyncMock(side_effect=RuntimeError("crash"))
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        assert daemon._agent_busy is False

    @pytest.mark.asyncio
    async def test_backend_exception_saves_error_turn(self, daemon, mock_backend):
        mock_backend.run = AsyncMock(side_effect=RuntimeError("crash"))
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.push_turn.assert_called_once()
        stored = daemon._memory.push_turn.call_args[0][1]
        assert "Error" in stored

    @pytest.mark.asyncio
    async def test_backend_error_status_sends_error_output(self, daemon):
        """When backend returns status='error', TUI should get output_type='error'."""
        backend = MockBackend(AgentResult(
            status="error",
            result="Backend timed out after 300s.",
            duration_ms=300000,
        ))
        daemon._backend = backend
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        error_msgs = [m for m in writer.messages if m.get("output_type") == "error"]
        assert len(error_msgs) == 1
        assert "timed out" in error_msgs[0]["content"]
        assert "longxia health" in error_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_backend_error_status_does_not_send_result(self, daemon):
        """Backend error should not produce a 'result' output — only 'error'."""
        backend = MockBackend(AgentResult(
            status="error",
            result="Backend process exited unexpectedly (code 1).",
            duration_ms=500,
        ))
        daemon._backend = backend
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        result_msgs = [m for m in writer.messages if m.get("output_type") == "result"]
        assert len(result_msgs) == 0

    @pytest.mark.asyncio
    async def test_backend_error_status_still_saves_turn(self, daemon):
        """Even on error, the turn should be recorded in session memory."""
        backend = MockBackend(AgentResult(
            status="error",
            result="Backend timed out after 300s.",
            duration_ms=300000,
        ))
        daemon._backend = backend
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.push_turn.assert_called_once()
        stored = daemon._memory.push_turn.call_args[0][1]
        assert "Error" in stored


# ---------------------------------------------------------------------------
# Memory tag processing
# ---------------------------------------------------------------------------

class TestMemoryTags:
    @pytest.mark.asyncio
    async def test_save_tag_calls_remember(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Noted! <memory_save>User likes Rust</memory_save>",
            duration_ms=50,
        ))
        daemon._backend = backend
        # _load_wakeup needs a file; create a minimal one
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("I like Rust", writer)

        daemon._memory.remember.assert_called_once_with("User likes Rust")

    @pytest.mark.asyncio
    async def test_save_tag_stripped_from_result(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Noted! <memory_save>User likes Rust</memory_save>",
            duration_ms=50,
        ))
        daemon._backend = backend
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("I like Rust", writer)

        result_msgs = [m for m in writer.messages if m.get("output_type") == "result"]
        assert len(result_msgs) == 1
        assert "<memory_save>" not in result_msgs[0]["content"]
        assert "Noted!" in result_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_save_tag_stripped_from_session_history(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Noted! <memory_save>User likes Rust</memory_save>",
            duration_ms=50,
        ))
        daemon._backend = backend
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("I like Rust", writer)

        stored = daemon._memory.push_turn.call_args[0][1]
        assert "<memory_save>" not in stored

    @pytest.mark.asyncio
    async def test_forget_tag_calls_forget_by_content(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Done! <memory_forget>Rust</memory_forget>",
            duration_ms=50,
        ))
        daemon._backend = backend
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("forget Rust", writer)

        daemon._memory.forget_by_content.assert_called_once_with("Rust")

    @pytest.mark.asyncio
    async def test_forget_tag_stripped_from_result(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Done! <memory_forget>Rust</memory_forget>",
            duration_ms=50,
        ))
        daemon._backend = backend
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("forget Rust", writer)

        result_msgs = [m for m in writer.messages if m.get("output_type") == "result"]
        assert "<memory_forget>" not in result_msgs[0]["content"]
        assert "Done!" in result_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_multiple_save_tags(self, daemon, sample_config):
        backend = MockBackend(AgentResult(
            status="success",
            result="Got it! <memory_save>likes Rust</memory_save> <memory_save>likes Go</memory_save>",
            duration_ms=50,
        ))
        daemon._backend = backend
        (sample_config.project_root / "WAKEUP.md").write_text("# Test", encoding="utf-8")

        writer = FakeWriter()
        await daemon._process_message("I like Rust and Go", writer)

        assert daemon._memory.remember.call_count == 2

    @pytest.mark.asyncio
    async def test_no_tags_skips_memory_ops(self, daemon):
        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.remember.assert_not_called()
        daemon._memory.forget_by_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_tag_ignored(self, daemon):
        backend = MockBackend(AgentResult(
            status="success",
            result="Hmm <memory_save>  </memory_save>",
            duration_ms=50,
        ))
        daemon._backend = backend

        writer = FakeWriter()
        await daemon._process_message("hello", writer)

        daemon._memory.remember.assert_not_called()
