"""Abstract base class for CLI backends."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional


@dataclass
class AgentInput:
    prompt: str
    working_dir: Optional[str] = None
    timeout: int = 300


@dataclass
class AgentOutput:
    type: str  # "text", "thinking", "result", "error", "init"
    content: str = ""
    is_final: bool = False


@dataclass
class AgentResult:
    status: str  # "success", "error"
    result: str = ""
    duration_ms: int = 0


class CLIBackend(ABC):
    SUPPORTED_BINARIES: set[str] = set()

    @abstractmethod
    def is_supported_binary(self) -> bool:
        """Check if the configured binary is a known supported backend."""
        ...

    @abstractmethod
    async def check_available(self) -> bool:
        ...

    @abstractmethod
    async def get_version(self) -> str:
        ...

    @abstractmethod
    async def run(
        self,
        input: AgentInput,
        on_output: Optional[Callable[[AgentOutput], Awaitable[None]]] = None,
    ) -> AgentResult:
        ...

    @abstractmethod
    async def stream(self, input: AgentInput) -> AsyncIterator[AgentOutput]:
        ...

    @abstractmethod
    def build_command(self, input: AgentInput) -> list[str]:
        ...

    @abstractmethod
    async def kill(self, process: asyncio.subprocess.Process) -> None:
        ...
