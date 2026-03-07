"""Terminal channel — wraps TUI for I/O."""

from __future__ import annotations

from typing import Optional, Callable, Awaitable

from .base import Channel, Message


TERMINAL_CHAT_ID = "terminal:main"


class TerminalChannel(Channel):
    """Terminal channel using the TUI for I/O.

    Chat ID: 'terminal:main' (hardcoded, single session).
    """

    name = "terminal"

    def __init__(self):
        self._connected = False
        self._on_message: Optional[Callable[[Message], Awaitable[None]]] = None

    async def connect(self) -> None:
        self._connected = True

    async def send_message(self, chat_id: str, text: str) -> None:
        if not self._connected:
            return
        # In practice, this is handled by the TUI socket protocol
        # The daemon sends JSON-lines directly to the TUI client

    def is_connected(self) -> bool:
        return self._connected

    def owns_chat(self, chat_id: str) -> bool:
        return chat_id == TERMINAL_CHAT_ID

    async def disconnect(self) -> None:
        self._connected = False

    async def set_typing(self, chat_id: str, is_typing: bool) -> None:
        # Handled by TUI processing indicator
        pass

    def set_on_message(self, callback: Callable[[Message], Awaitable[None]]) -> None:
        self._on_message = callback
