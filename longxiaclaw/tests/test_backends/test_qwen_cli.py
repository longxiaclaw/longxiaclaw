"""Tests for Qwen Code CLI backend."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from longxiaclaw.backends.base import AgentInput, AgentOutput
from longxiaclaw.backends.qwen_cli import QwenCodeBackend


class TestQwenCodeBackendValidation:
    def test_supported_binary_qwen(self):
        backend = QwenCodeBackend(binary="qwen")
        assert backend.is_supported_binary() is True

    def test_unsupported_binary(self):
        backend = QwenCodeBackend(binary="curl")
        assert backend.is_supported_binary() is False

    def test_unsupported_binary_empty(self):
        backend = QwenCodeBackend(binary="")
        assert backend.is_supported_binary() is False


class TestQwenCodeBackend:
    def test_build_command_basic(self):
        backend = QwenCodeBackend(binary="qwen", approval_mode="yolo")
        cmd = backend.build_command(AgentInput(prompt="hello world"))
        assert cmd == [
            "qwen", "-p", "hello world",
            "--output-format", "stream-json",
            "--approval-mode", "yolo",
        ]

    def test_build_command_no_resume(self):
        """--resume is never passed; LongxiaClaw manages its own memory."""
        backend = QwenCodeBackend()
        cmd = backend.build_command(AgentInput(prompt="hi"))
        assert "--resume" not in cmd

    def test_build_command_with_model(self):
        backend = QwenCodeBackend(model="qwen3-coder")
        cmd = backend.build_command(AgentInput(prompt="hi"))
        assert "-m" in cmd
        assert "qwen3-coder" in cmd

    def test_build_command_no_model_when_empty(self):
        backend = QwenCodeBackend(model="")
        cmd = backend.build_command(AgentInput(prompt="hi"))
        assert "-m" not in cmd

    def test_parse_stream_event_init(self):
        backend = QwenCodeBackend()
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc-123"})
        output = backend._parse_stream_event(line)
        assert output is not None
        assert output.type == "init"

    def test_parse_stream_event_text(self):
        backend = QwenCodeBackend()
        line = json.dumps({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Hello, I can help!"}]
            }
        })
        output = backend._parse_stream_event(line)
        assert output is not None
        assert output.type == "text"
        assert output.content == "Hello, I can help!"

    def test_parse_stream_event_result(self):
        backend = QwenCodeBackend()
        line = json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "Done!",
            "session_id": "sess-xyz",
        })
        output = backend._parse_stream_event(line)
        assert output is not None
        assert output.type == "result"
        assert output.content == "Done!"
        assert output.is_final is True

    def test_parse_stream_event_empty_line(self):
        backend = QwenCodeBackend()
        assert backend._parse_stream_event("") is None
        assert backend._parse_stream_event("   ") is None

    def test_parse_stream_event_invalid_json(self):
        backend = QwenCodeBackend()
        assert backend._parse_stream_event("not json at all") is None

    def test_parse_stream_event_unknown_type(self):
        backend = QwenCodeBackend()
        line = json.dumps({"type": "unknown", "data": "something"})
        assert backend._parse_stream_event(line) is None

    @pytest.mark.asyncio
    async def test_check_available_found(self):
        backend = QwenCodeBackend(binary="python3")
        assert await backend.check_available() is True

    @pytest.mark.asyncio
    async def test_check_available_not_found(self):
        backend = QwenCodeBackend(binary="nonexistent_binary_xyz_123")
        assert await backend.check_available() is False

    @pytest.mark.asyncio
    async def test_run_file_not_found(self):
        backend = QwenCodeBackend(binary="nonexistent_binary_xyz_123")
        result = await backend.run(AgentInput(prompt="hello"))
        assert result.status == "error"
        assert "not found" in result.result

    @pytest.mark.asyncio
    async def test_run_empty_result_returns_error(self):
        """Binary exists but produces no parseable result → error."""
        backend = QwenCodeBackend(binary="echo")
        result = await backend.run(AgentInput(prompt="hello"))
        assert result.status == "error"
        assert "no result" in result.result.lower()
        assert "BACKEND_BINARY" in result.result

    @pytest.mark.asyncio
    async def test_run_with_mock_process(self):
        backend = QwenCodeBackend()

        init_line = json.dumps({"type": "system", "subtype": "init", "session_id": "s1"})
        text_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "thinking..."}]}
        })
        result_line = json.dumps({
            "type": "result", "subtype": "success",
            "result": "final answer", "session_id": "s1"
        })
        mock_stdout = (init_line + "\n" + text_line + "\n" + result_line + "\n").encode()

        mock_proc = AsyncMock()
        mock_proc.stdout = asyncio.StreamReader()
        mock_proc.stdout.feed_data(mock_stdout)
        mock_proc.stdout.feed_eof()
        mock_proc.stderr = asyncio.StreamReader()
        mock_proc.stderr.feed_eof()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)

        outputs = []
        async def on_output(out: AgentOutput):
            outputs.append(out)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await backend.run(AgentInput(prompt="test"), on_output=on_output)

        assert result.status == "success"
        assert result.result == "final answer"
        assert len(outputs) == 3  # init, text, result

    @pytest.mark.asyncio
    async def test_run_process_error(self):
        backend = QwenCodeBackend()

        mock_proc = AsyncMock()
        mock_proc.stdout = asyncio.StreamReader()
        mock_proc.stdout.feed_eof()
        mock_proc.stderr = asyncio.StreamReader()
        mock_proc.stderr.feed_data(b"some error occurred")
        mock_proc.stderr.feed_eof()
        mock_proc.returncode = 1
        mock_proc.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await backend.run(AgentInput(prompt="test"))

        assert result.status == "error"
        assert "some error occurred" in result.result

    @pytest.mark.asyncio
    async def test_kill_process(self):
        backend = QwenCodeBackend()
        mock_proc = AsyncMock()
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        await backend.kill(mock_proc)
        mock_proc.terminate.assert_called_once()
