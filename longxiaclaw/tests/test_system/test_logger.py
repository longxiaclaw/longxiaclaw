"""Tests for LogManager: setup, rotation, structured logging."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from longxiaclaw.system import LogManager, LOG_RETENTION_DAYS


@pytest.fixture
def log_manager(tmp_path: Path) -> LogManager:
    """LogManager pointing at a temp directory."""
    return LogManager(tmp_path)


class TestSetup:
    def test_setup_creates_log_dir(self, tmp_path: Path):
        logs_dir = tmp_path / "logs"
        manager = LogManager(logs_dir)
        logger = manager.setup("INFO")
        assert logs_dir.exists()
        assert logger is not None

    def test_setup_creates_log_files(self, log_manager: LogManager, tmp_path: Path):
        log_manager.setup("INFO")
        log_files = list(tmp_path.glob("*.log"))
        assert len(log_files) == 4  # regular + error + prompts + responses
        names = {f.name for f in log_files}
        assert any("longxiaclaw-" in n for n in names)
        assert any("errors-" in n for n in names)
        assert any("prompts-" in n for n in names)
        assert any("responses-" in n for n in names)

    def test_setup_returns_logger(self, log_manager: LogManager):
        logger = log_manager.setup("DEBUG")
        assert logger.name == "longxiaclaw"

    def test_setup_sets_level(self, log_manager: LogManager):
        logger = log_manager.setup("WARNING")
        assert logger.level == logging.WARNING

    def test_setup_clears_previous_handlers(self, log_manager: LogManager):
        logger1 = log_manager.setup("INFO")
        handler_count_1 = len(logger1.handlers)
        logger2 = log_manager.setup("DEBUG")
        assert len(logger2.handlers) == handler_count_1


class TestRotateLogs:
    def test_rotate_no_dir(self, tmp_path: Path):
        manager = LogManager(tmp_path / "nonexistent")
        manager.rotate_logs()  # should not raise

    def test_rotate_keeps_recent(self, log_manager: LogManager, tmp_path: Path):
        recent = tmp_path / "longxiaclaw-recent.log"
        recent.write_text("recent log")
        log_manager.rotate_logs()
        assert recent.exists()

    def test_rotate_deletes_old(self, log_manager: LogManager, tmp_path: Path):
        old = tmp_path / "longxiaclaw-old.log"
        old.write_text("old log")
        # Set mtime to 10 days ago
        old_time = time.time() - (10 * 86400)
        os.utime(old, (old_time, old_time))
        log_manager.rotate_logs()
        assert not old.exists()

    def test_rotate_respects_retention_days(self, log_manager: LogManager, tmp_path: Path):
        # File just within retention window
        borderline = tmp_path / "borderline.log"
        borderline.write_text("borderline log")
        recent_time = time.time() - ((LOG_RETENTION_DAYS - 1) * 86400)
        os.utime(borderline, (recent_time, recent_time))
        log_manager.rotate_logs()
        assert borderline.exists()


class TestStructuredLogging:
    def test_log_action(self, log_manager: LogManager, tmp_path: Path):
        log_manager.setup("INFO")
        log_manager.log_action("test_action", {"key": "value"})
        # Verify it was written to the log file
        log_files = list(tmp_path.glob("longxiaclaw-*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert "test_action" in content
        assert "key" in content

    def test_log_action_without_setup(self):
        manager = LogManager(Path("/tmp/nonexistent"))
        # Should not raise when logger is None
        manager.log_action("test", {})

    def test_log_error(self, log_manager: LogManager, tmp_path: Path):
        log_manager.setup("INFO")
        log_manager.log_error("something broke", {"detail": "info"})
        # Verify it was written to the error log file
        error_files = list(tmp_path.glob("errors-*.log"))
        assert len(error_files) == 1
        content = error_files[0].read_text()
        assert "something broke" in content

    def test_log_error_without_setup(self):
        manager = LogManager(Path("/tmp/nonexistent"))
        # Should not raise when logger is None
        manager.log_error("test", {})

    def test_log_prompt(self, log_manager: LogManager, tmp_path: Path):
        log_manager.setup("INFO")
        log_manager.log_prompt("What is the meaning of life?")
        log_manager.shutdown()  # flush background queue before reading
        prompt_files = list(tmp_path.glob("prompts-*.log"))
        assert len(prompt_files) == 1
        content = prompt_files[0].read_text()
        assert "What is the meaning of life?" in content
        assert "─" * 80 in content

    def test_log_prompt_without_setup(self):
        manager = LogManager(Path("/tmp/nonexistent"))
        manager.log_prompt("test")

    def test_log_response(self, log_manager: LogManager, tmp_path: Path):
        log_manager.setup("INFO")
        log_manager.log_response("The answer is 42.")
        log_manager.shutdown()  # flush background queue before reading
        response_files = list(tmp_path.glob("responses-*.log"))
        assert len(response_files) == 1
        content = response_files[0].read_text()
        assert "The answer is 42." in content
        assert "─" * 80 in content

    def test_log_response_without_setup(self):
        manager = LogManager(Path("/tmp/nonexistent"))
        manager.log_response("test")
