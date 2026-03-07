"""Structured logging with daily rotation and auto-cleanup."""

from __future__ import annotations

import logging
import logging.handlers
import queue
import time
from datetime import datetime
from pathlib import Path

LOG_RETENTION_DAYS = 3


class LogManager:
    """Four-layer logging: regular, error, prompt, and response logs. All auto-deleted after 3 days."""

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir
        self._logger: logging.Logger | None = None
        self._prompt_logger: logging.Logger | None = None
        self._response_logger: logging.Logger | None = None
        self._queue_listeners: list[logging.handlers.QueueListener] = []

    def setup(self, level: str = "INFO") -> logging.Logger:
        """Configure daily-rotating file handlers for regular, error, prompt, and response logs."""
        self._logs_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        bare_formatter = logging.Formatter("%(asctime)s\n%(message)s\n")

        # Main logger
        logger = logging.getLogger("longxiaclaw")
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.handlers.clear()

        # Regular log handler
        regular_path = self._logs_dir / f"longxiaclaw-{today}.log"
        regular_handler = logging.FileHandler(regular_path, encoding="utf-8")
        regular_handler.setLevel(logging.DEBUG)
        regular_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(regular_handler)

        # Error log handler
        error_path = self._logs_dir / f"errors-{today}.log"
        error_handler = logging.FileHandler(error_path, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(exc_info)s")
        )
        logger.addHandler(error_handler)

        self._logger = logger

        # Prompt and response loggers use QueueHandler + QueueListener so
        # large writes happen on a background thread without blocking the
        # asyncio event loop.  Each gets its own queue to keep files separate.
        for listener in self._queue_listeners:
            listener.stop()
        self._queue_listeners.clear()

        # Prompt logger
        prompt_queue: queue.Queue = queue.Queue(-1)
        prompt_path = self._logs_dir / f"prompts-{today}.log"
        prompt_file_handler = logging.FileHandler(prompt_path, encoding="utf-8")
        prompt_file_handler.setFormatter(bare_formatter)
        prompt_listener = logging.handlers.QueueListener(prompt_queue, prompt_file_handler)
        prompt_listener.start()
        self._queue_listeners.append(prompt_listener)

        prompt_logger = logging.getLogger("longxiaclaw.prompts")
        prompt_logger.setLevel(logging.DEBUG)
        prompt_logger.handlers.clear()
        prompt_logger.propagate = False
        prompt_logger.addHandler(logging.handlers.QueueHandler(prompt_queue))
        self._prompt_logger = prompt_logger

        # Response logger
        response_queue: queue.Queue = queue.Queue(-1)
        response_path = self._logs_dir / f"responses-{today}.log"
        response_file_handler = logging.FileHandler(response_path, encoding="utf-8")
        response_file_handler.setFormatter(bare_formatter)
        response_listener = logging.handlers.QueueListener(response_queue, response_file_handler)
        response_listener.start()
        self._queue_listeners.append(response_listener)

        response_logger = logging.getLogger("longxiaclaw.responses")
        response_logger.setLevel(logging.DEBUG)
        response_logger.handlers.clear()
        response_logger.propagate = False
        response_logger.addHandler(logging.handlers.QueueHandler(response_queue))
        self._response_logger = response_logger

        return logger

    def rotate_logs(self) -> None:
        """Delete log files older than LOG_RETENTION_DAYS. Synchronous, called on startup."""
        if not self._logs_dir.exists():
            return

        cutoff = time.time() - (LOG_RETENTION_DAYS * 86400)

        for log_file in self._logs_dir.glob("*.log"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
            except OSError:
                pass

    def log_action(self, action: str, details: dict) -> None:
        """Log a structured action."""
        if self._logger:
            self._logger.info("ACTION: %s | %s", action, details)

    def log_error(self, error: str, context: dict) -> None:
        """Log a structured error."""
        if self._logger:
            self._logger.error("ERROR: %s | %s", error, context)

    def shutdown(self) -> None:
        """Stop background queue listeners (flushes pending writes)."""
        for listener in self._queue_listeners:
            listener.stop()
        self._queue_listeners.clear()

    def log_prompt(self, prompt: str) -> None:
        """Log the full prompt sent to the LLM backend."""
        if self._prompt_logger:
            self._prompt_logger.debug("%s\n%s", prompt, "─" * 80)

    def log_response(self, response: str) -> None:
        """Log the raw LLM backend response before parsing."""
        if self._response_logger:
            self._response_logger.debug("%s\n%s", response, "─" * 80)
