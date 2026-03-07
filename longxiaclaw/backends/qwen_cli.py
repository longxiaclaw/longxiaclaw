"""Qwen Code CLI backend implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from typing import AsyncIterator, Awaitable, Callable, Optional

from .base import AgentInput, AgentOutput, AgentResult, CLIBackend

logger = logging.getLogger("longxiaclaw")
response_logger = logging.getLogger("longxiaclaw.responses")


class QwenCodeBackend(CLIBackend):
    """Backend for Qwen Code CLI.

    Command: qwen -p "prompt" --output-format stream-json --approval-mode yolo
    Optional flags: -m <model>

    Each invocation is stateless (no --resume). LongxiaClaw manages all memory.
    """

    SUPPORTED_BINARIES = {"qwen"}

    def __init__(
        self,
        binary: str = "qwen",
        model: str = "",
        approval_mode: str = "yolo",
        timeout: int = 300,
    ):
        self._binary = binary
        self._model = model
        self._approval_mode = approval_mode
        self._timeout = timeout

    def is_supported_binary(self) -> bool:
        """Check if the configured binary is a known supported backend."""
        return self._binary in self.SUPPORTED_BINARIES

    async def check_available(self) -> bool:
        """Check if the qwen binary is available on PATH."""
        return shutil.which(self._binary) is not None

    async def get_version(self) -> str:
        """Get qwen CLI version."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return stdout.decode().strip()
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return "unknown"

    def build_command(self, input: AgentInput) -> list[str]:
        """Build the qwen CLI command.

        NOTE: We intentionally do NOT pass --resume. LongxiaClaw manages its
        own memory (sessions/ + CONTEXT.md) and injects conversation history
        into each prompt. Using --resume would create a redundant, conflicting
        memory layer inside the CLI backend.
        """
        cmd = [
            self._binary,
            "-p", input.prompt,
            "--output-format", "stream-json",
            "--approval-mode", self._approval_mode,
        ]
        if self._model:
            cmd.extend(["-m", self._model])
        return cmd

    def _parse_stream_event(self, line: str) -> Optional[AgentOutput]:
        """Parse a single stream-json line from qwen output."""
        line = line.strip()
        if not line:
            return None

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None

        event_type = event.get("type", "")
        subtype = event.get("subtype", "")

        # Init event (ignored — we don't track CLI session IDs)
        if event_type == "system" and subtype == "init":
            return AgentOutput(type="init")

        # Assistant text
        if event_type == "assistant":
            message = event.get("message", {})
            content_parts = message.get("content", [])
            text_parts = []
            for part in content_parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            if text_parts:
                return AgentOutput(
                    type="text",
                    content="".join(text_parts),
                )

        # Result event
        if event_type == "result":
            return AgentOutput(
                type="result",
                content=event.get("result", ""),
                is_final=True,
            )

        return None

    async def run(
        self,
        input: AgentInput,
        on_output: Optional[Callable[[AgentOutput], Awaitable[None]]] = None,
    ) -> AgentResult:
        """Spawn qwen subprocess, parse stream-json, collect result."""
        cmd = self.build_command(input)
        timeout = input.timeout or self._timeout
        start_time = time.monotonic()
        # Log command without the prompt (which can be huge)
        cmd_summary = [c for c in cmd if c != input.prompt]
        logger.info("Spawning backend: %s (timeout: %ds)", " ".join(cmd_summary), timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=input.working_dir,
            )
            logger.info("Backend process started (PID %d)", proc.pid)

            final_result = ""
            raw_lines: list[str] = []

            async def _read_output():
                nonlocal final_result
                assert proc.stdout is not None
                async for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace")
                    raw_lines.append(line.rstrip("\n"))
                    output = self._parse_stream_event(line)
                    if output is None:
                        continue

                    if output.is_final:
                        final_result = output.content

                    if on_output:
                        await on_output(output)

            await asyncio.wait_for(_read_output(), timeout=timeout)
            await proc.wait()

            elapsed = int((time.monotonic() - start_time) * 1000)

            # Log all raw backend output to the response log
            if raw_lines:
                response_logger.debug("--- RAW BACKEND OUTPUT (PID %d) ---\n%s\n--- END RAW OUTPUT ---",
                                      proc.pid, "\n".join(raw_lines))

            if proc.returncode != 0:
                stderr_bytes = await proc.stderr.read() if proc.stderr else b""
                stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
                logger.error("Backend process exited with code %d (PID %d)", proc.returncode, proc.pid)
                if stderr_text:
                    logger.error("Backend stderr: %s", stderr_text[:500])
                return AgentResult(
                    status="error",
                    result=stderr_text or f"Backend process exited unexpectedly (code {proc.returncode}).",
                    duration_ms=elapsed,
                )

            if not final_result:
                logger.error("Backend produced no result (PID %d). Is BACKEND_BINARY set correctly?", proc.pid)
                return AgentResult(
                    status="error",
                    result=f"Backend '{self._binary}' produced no result. Check BACKEND_BINARY in .env.",
                    duration_ms=elapsed,
                )

            logger.info("Backend process completed (PID %d, exit code 0, %dms)", proc.pid, elapsed)
            return AgentResult(
                status="success",
                result=final_result,
                duration_ms=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start_time) * 1000)
            logger.error("Backend timed out after %ds, killing process", timeout)
            if proc:
                await self.kill(proc)
            return AgentResult(
                status="error",
                result=f"Backend timed out after {timeout}s.",
                duration_ms=elapsed,
            )
        except FileNotFoundError:
            logger.error("Backend binary not found: %s", self._binary)
            return AgentResult(
                status="error",
                result=f"Backend binary '{self._binary}' not found. Install it and ensure it is on PATH.",
                duration_ms=0,
            )

    async def stream(self, input: AgentInput) -> AsyncIterator[AgentOutput]:
        """Async generator yielding parsed stream events."""
        cmd = self.build_command(input)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=input.working_dir,
        )

        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            output = self._parse_stream_event(line)
            if output is not None:
                yield output

        await proc.wait()

    async def kill(self, process: asyncio.subprocess.Process) -> None:
        """Send SIGTERM, wait 5s, then SIGKILL."""
        try:
            logger.info("Sending SIGTERM to backend process (PID %d)", process.pid)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
                logger.info("Backend process (PID %d) terminated gracefully", process.pid)
            except asyncio.TimeoutError:
                logger.warning("Backend process (PID %d) did not respond to SIGTERM, sending SIGKILL", process.pid)
                process.kill()
                await process.wait()
                logger.info("Backend process (PID %d) killed", process.pid)
        except ProcessLookupError:
            logger.info("Backend process (PID %d) already exited", process.pid)
