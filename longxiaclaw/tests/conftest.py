"""Shared test fixtures for LongxiaClaw."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional, Callable, Awaitable, AsyncIterator

import pytest

from longxiaclaw.system import Config
from longxiaclaw.backends.base import CLIBackend, AgentInput, AgentOutput, AgentResult


class FakeWriter:
    """Collects JSON-line messages sent via daemon._send() for assertion."""

    def __init__(self):
        self.messages: list[dict] = []

    def write(self, data: bytes) -> None:
        for line in data.decode("utf-8").strip().splitlines():
            if line:
                self.messages.append(json.loads(line))

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class MockBackend(CLIBackend):
    """Mock backend that returns canned responses and tracks all calls."""

    SUPPORTED_BINARIES = {"mock"}

    def __init__(self, canned_result: Optional[AgentResult] = None):
        self.calls: list[AgentInput] = []
        self.available = True
        self.version = "mock-1.0"
        self._canned_result = canned_result or AgentResult(
            status="success",
            result="Mock response",
            duration_ms=100,
        )

    async def check_available(self) -> bool:
        return self.available

    async def get_version(self) -> str:
        return self.version

    async def run(
        self,
        input: AgentInput,
        on_output: Optional[Callable[[AgentOutput], Awaitable[None]]] = None,
    ) -> AgentResult:
        self.calls.append(input)
        if on_output:
            await on_output(AgentOutput(type="text", content="Mock thinking..."))
            await on_output(
                AgentOutput(
                    type="result",
                    content=self._canned_result.result,
                    is_final=True,
                )
            )
        return self._canned_result

    async def stream(self, input: AgentInput) -> AsyncIterator[AgentOutput]:
        self.calls.append(input)
        yield AgentOutput(type="text", content="Mock thinking...")
        yield AgentOutput(
            type="result",
            content=self._canned_result.result,
            is_final=True,
        )

    def build_command(self, input: AgentInput) -> list[str]:
        return ["mock-cli", "-p", input.prompt]

    async def kill(self, process: asyncio.subprocess.Process) -> None:
        pass

    def is_supported_binary(self) -> bool:
        return True


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temp project directory with daemon/, logs/, skills/, agent_workspace/memory/, agent_workspace/scheduler/."""
    for dirname in ("daemon", "logs", "skills"):
        (tmp_path / dirname).mkdir()
    (tmp_path / "agent_workspace" / "memory").mkdir(parents=True)
    (tmp_path / "agent_workspace" / "scheduler").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def sample_config(tmp_project: Path) -> Config:
    """Config pointing at tmp_project."""
    return Config(
        project_root=tmp_project,
        assistant_name="TestClaw",
        default_backend="mock",
        backend_timeout=30,
        log_level="DEBUG",
    )


@pytest.fixture
def mock_backend() -> MockBackend:
    """MockBackend that returns canned AgentResult. Tracks all calls."""
    return MockBackend()


@pytest.fixture
def sample_skill_file(tmp_project: Path) -> Path:
    """Create a temp .md skill file with valid YAML frontmatter."""
    skill_path = tmp_project / "skills" / "test_skill.md"
    skill_path.write_text(
        """---
name: test_skill
description: A test skill for unit tests
version: "1.0"
enabled: true
author: test
---

# Test Skill

This is the body of the test skill.
When triggered, do something useful.
""",
        encoding="utf-8",
    )
    return skill_path
