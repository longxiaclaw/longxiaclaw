"""Tests for TUI command handling.

Each test verifies that a TUI command produces the correct response type
so that the TUI client's message display loop terminates and returns
the > prompt to the user.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from longxiaclaw.main import LongxiaClawDaemon
from longxiaclaw.tests.conftest import FakeWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def daemon(sample_config, mock_backend) -> "LongxiaClawDaemon":
    """Create an AgentDaemon with mocked dependencies."""
    d = LongxiaClawDaemon.__new__(LongxiaClawDaemon)
    d._config = sample_config
    d._backend = mock_backend
    d._logger = MagicMock()
    d._agent_busy = False

    # Memory tag regexes (normally set in __init__)
    d._MEMORY_SAVE_RE = re.compile(r"<memory_save>(.*?)</memory_save>", re.DOTALL)
    d._MEMORY_FORGET_RE = re.compile(r"<memory_forget>(.*?)</memory_forget>", re.DOTALL)

    # Minimal memory mock
    d._memory = MagicMock()
    d._memory.start_new_session = MagicMock()
    d._memory.load_previous_sessions = MagicMock(return_value="")
    d._memory.load_context = MagicMock(return_value="")
    d._memory.prune_old_sessions = MagicMock()
    d._memory.remember = MagicMock(return_value="Remembered: test")
    d._memory.forget_by_content = MagicMock(return_value="Forgot 1 entry(s): test")

    # Minimal state manager mock
    d._state_manager = MagicMock()

    # Minimal skill registry mock
    d._skill_registry = MagicMock()
    d._skill_registry.get_active_skills = MagicMock(return_value=[])
    d._skill_registry.count = 0

    d._system_context = ""

    # Stub _load_wakeup
    d._load_wakeup = MagicMock(return_value="")

    return d


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_returns_result(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/help", writer)

        assert len(writer.messages) == 1
        msg = writer.messages[0]
        assert msg["output_type"] == "result", (
            "/help must send output_type='result' so TUI prompt returns"
        )

    @pytest.mark.asyncio
    async def test_help_contains_builtin_commands(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/help", writer)

        content = writer.messages[0]["content"]
        for cmd in ("/help", "/skills", "/new", "/clear", "/quit"):
            assert cmd in content, f"/help output should mention {cmd}"


# ---------------------------------------------------------------------------
# /new
# ---------------------------------------------------------------------------

class TestNewCommand:
    @pytest.mark.asyncio
    async def test_new_returns_result(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/new", writer)

        assert len(writer.messages) == 1
        msg = writer.messages[0]
        assert msg["output_type"] == "result", (
            "/new must send output_type='result' so TUI prompt returns"
        )

    @pytest.mark.asyncio
    async def test_new_starts_new_session(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/new", writer)

        daemon._memory.start_new_session.assert_called_once()


# ---------------------------------------------------------------------------
# /skills
# ---------------------------------------------------------------------------

class TestSkillsCommand:
    @pytest.mark.asyncio
    async def test_skills_returns_result(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/skills", writer)

        assert len(writer.messages) == 1
        msg = writer.messages[0]
        assert msg["output_type"] == "result", (
            "/skills must send output_type='result' so TUI prompt returns"
        )

    @pytest.mark.asyncio
    async def test_skills_no_skills(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/skills", writer)

        content = writer.messages[0]["content"]
        assert "No active skills" in content
        assert "Tip" in content

    @pytest.mark.asyncio
    async def test_skills_with_active_skills(self, daemon):
        skill = MagicMock()
        skill.name = "greet"
        skill.description = "Say hello"
        skill.is_tool_skill = False
        daemon._skill_registry.get_active_skills.return_value = [skill]

        writer = FakeWriter()
        await daemon._handle_command("/skills", writer)

        content = writer.messages[0]["content"]
        assert "greet" in content
        assert "prompt" in content
        assert "Say hello" in content
        assert "Tip" in content


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_returns_error(self, daemon):
        writer = FakeWriter()
        await daemon._handle_command("/nonexistent", writer)

        assert len(writer.messages) == 1
        msg = writer.messages[0]
        assert msg["output_type"] == "error", (
            "Unknown command must send output_type='error' so TUI prompt returns"
        )
        assert "/nonexistent" in msg["content"]
