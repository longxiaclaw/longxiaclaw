"""Abstract base class for channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    chat_id: str
    sender: str
    text: str
    timestamp: str


class Channel(ABC):
    name: str = ""

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def owns_chat(self, chat_id: str) -> bool:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    async def set_typing(self, chat_id: str, is_typing: bool) -> None:
        """Default no-op."""
        pass
