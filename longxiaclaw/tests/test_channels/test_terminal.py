"""Tests for terminal channel."""

from __future__ import annotations

import pytest

from longxiaclaw.channels.terminal import TerminalChannel, TERMINAL_CHAT_ID


class TestTerminalChannel:
    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        ch = TerminalChannel()
        assert not ch.is_connected()
        await ch.connect()
        assert ch.is_connected()
        await ch.disconnect()
        assert not ch.is_connected()

    def test_owns_chat(self):
        ch = TerminalChannel()
        assert ch.owns_chat(TERMINAL_CHAT_ID)
        assert not ch.owns_chat("other:chat")

    def test_name(self):
        ch = TerminalChannel()
        assert ch.name == "terminal"

    @pytest.mark.asyncio
    async def test_send_message_while_connected(self):
        ch = TerminalChannel()
        await ch.connect()
        # Should not raise
        await ch.send_message(TERMINAL_CHAT_ID, "hello")

    @pytest.mark.asyncio
    async def test_send_message_while_disconnected(self):
        ch = TerminalChannel()
        # Should not raise
        await ch.send_message(TERMINAL_CHAT_ID, "hello")

    @pytest.mark.asyncio
    async def test_set_typing(self):
        ch = TerminalChannel()
        # Should not raise (no-op)
        await ch.set_typing(TERMINAL_CHAT_ID, True)
        await ch.set_typing(TERMINAL_CHAT_ID, False)
