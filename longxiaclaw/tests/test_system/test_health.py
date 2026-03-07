"""Tests for the health check module."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from unittest import mock

import pytest
import yaml

from longxiaclaw.system.health import (
    CheckResult,
    run_health,
    _check_venv_integrity,
    _check_core_deps,
    _check_stale_pid,
    _check_stale_socket,
    _check_backend_binary,
    _check_state_file,
    _check_stuck_tasks,
    _check_log_cleanup,
    _check_session_archives,
    _check_context_capacity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Minimal project directory with daemon/, logs/, agent_workspace/memory/, agent_workspace/scheduler/."""
    for d in ("daemon", "logs"):
        (tmp_path / d).mkdir()
    (tmp_path / "agent_workspace" / "memory").mkdir(parents=True)
    (tmp_path / "agent_workspace" / "scheduler").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def memory_dir(project: Path) -> Path:
    return project / "agent_workspace" / "memory"


@pytest.fixture
def pid_file(project: Path) -> Path:
    return project / "daemon" / "longxiaclaw.pid"


@pytest.fixture
def socket_path(project: Path) -> Path:
    return project / "daemon" / "longxiaclaw.sock"


@pytest.fixture
def state_file(project: Path) -> Path:
    return project / "agent_workspace" / "scheduler" / "state.yaml"


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

class TestCheckResult:
    def test_defaults(self):
        r = CheckResult("test", True, "OK")
        assert r.passed is True
        assert r.repairable is False
        assert r.repaired is False
        assert r.repair_message == ""


# ---------------------------------------------------------------------------
# Venv integrity
# ---------------------------------------------------------------------------

class TestVenvIntegrity:
    def test_pass_when_python_exists(self, project: Path):
        venv_python = project / ".longxia_venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        result = _check_venv_integrity(project, repair=False)
        assert result.passed is True

    def test_fail_when_missing(self, project: Path):
        result = _check_venv_integrity(project, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_fail_broken_symlink(self, project: Path):
        venv_python = project / ".longxia_venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.symlink_to("/nonexistent/python3")
        result = _check_venv_integrity(project, repair=False)
        assert result.passed is False
        assert result.repairable is True


# ---------------------------------------------------------------------------
# Core dependencies
# ---------------------------------------------------------------------------

class TestCoreDeps:
    def test_pass_when_all_importable(self, project: Path):
        result = _check_core_deps(project, repair=False)
        # In the test environment, all deps should be installed
        assert result.passed is True

    def test_fail_when_import_fails(self, project: Path):
        with mock.patch("builtins.__import__", side_effect=ImportError("no")):
            result = _check_core_deps(project, repair=False)
        assert result.passed is False
        assert result.repairable is True
        assert "Missing" in result.message


# ---------------------------------------------------------------------------
# Stale PID file
# ---------------------------------------------------------------------------

class TestStalePid:
    def test_pass_no_pid_file(self, pid_file: Path):
        result = _check_stale_pid(pid_file, repair=False)
        assert result.passed is True

    def test_pass_process_alive(self, pid_file: Path):
        pid_file.write_text(str(os.getpid()))
        result = _check_stale_pid(pid_file, repair=False)
        assert result.passed is True

    def test_fail_stale_pid(self, pid_file: Path):
        pid_file.write_text("99999999")
        result = _check_stale_pid(pid_file, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_stale_pid(self, pid_file: Path):
        pid_file.write_text("99999999")
        result = _check_stale_pid(pid_file, repair=True)
        assert result.repaired is True
        assert not pid_file.exists()

    def test_fail_invalid_pid(self, pid_file: Path):
        pid_file.write_text("not-a-number")
        result = _check_stale_pid(pid_file, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_invalid_pid(self, pid_file: Path):
        pid_file.write_text("not-a-number")
        result = _check_stale_pid(pid_file, repair=True)
        assert result.repaired is True
        assert not pid_file.exists()


# ---------------------------------------------------------------------------
# Stale socket
# ---------------------------------------------------------------------------

class TestStaleSocket:
    def test_pass_no_socket(self, socket_path: Path):
        result = _check_stale_socket(socket_path, repair=False)
        assert result.passed is True

    def test_fail_stale_socket(self, socket_path: Path):
        # Create a file that looks like a socket but isn't connectable
        socket_path.write_text("")
        result = _check_stale_socket(socket_path, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_stale_socket(self, socket_path: Path):
        socket_path.write_text("")
        result = _check_stale_socket(socket_path, repair=True)
        assert result.repaired is True
        assert not socket_path.exists()

    def test_pass_live_socket(self, tmp_path: Path):
        """A socket accepting connections should pass."""
        import tempfile
        # Use a short path to avoid AF_UNIX path length limit
        tmpdir = tempfile.mkdtemp(prefix="lx_")
        sock_path = Path(tmpdir) / "test.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(sock_path))
            server.listen(1)
            result = _check_stale_socket(sock_path, repair=False)
            assert result.passed is True
        finally:
            server.close()
            sock_path.unlink(missing_ok=True)
            os.rmdir(tmpdir)


# ---------------------------------------------------------------------------
# Backend binary
# ---------------------------------------------------------------------------

class TestBackendBinary:
    def test_pass_found(self):
        result = _check_backend_binary("python3")
        assert result.passed is True

    def test_fail_not_found(self):
        result = _check_backend_binary("nonexistent_binary_12345")
        assert result.passed is False
        assert result.repairable is False


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

class TestStateFile:
    def test_pass_no_file(self, state_file: Path):
        result = _check_state_file(state_file, repair=False)
        assert result.passed is True

    def test_pass_valid_yaml(self, state_file: Path):
        state_file.write_text(yaml.dump({"scheduled_tasks": []}))
        result = _check_state_file(state_file, repair=False)
        assert result.passed is True

    def test_fail_corrupt_yaml(self, state_file: Path):
        state_file.write_text("{{{{invalid yaml: [")
        result = _check_state_file(state_file, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_corrupt_yaml(self, state_file: Path):
        state_file.write_text("{{{{invalid yaml: [")
        result = _check_state_file(state_file, repair=True)
        assert result.repaired is True
        assert not state_file.exists()
        assert state_file.with_suffix(".yaml.bak").exists()

    def test_fail_non_dict_yaml(self, state_file: Path):
        state_file.write_text("- just\n- a\n- list\n")
        result = _check_state_file(state_file, repair=False)
        assert result.passed is False
        assert result.repairable is True


# ---------------------------------------------------------------------------
# Stuck tasks
# ---------------------------------------------------------------------------

class TestStuckTasks:
    def test_pass_no_file(self, state_file: Path):
        result = _check_stuck_tasks(state_file, repair=False)
        assert result.passed is True

    def test_pass_no_stuck(self, state_file: Path):
        data = {"scheduled_tasks": [{"id": "t1", "status": "active"}]}
        state_file.write_text(yaml.dump(data))
        result = _check_stuck_tasks(state_file, repair=False)
        assert result.passed is True

    def test_fail_stuck(self, state_file: Path):
        data = {"scheduled_tasks": [
            {"id": "t1", "status": "running"},
            {"id": "t2", "status": "active"},
        ]}
        state_file.write_text(yaml.dump(data))
        result = _check_stuck_tasks(state_file, repair=False)
        assert result.passed is False
        assert result.repairable is True
        assert "t1" in result.message

    def test_repair_stuck(self, state_file: Path):
        data = {"scheduled_tasks": [
            {"id": "t1", "status": "running"},
            {"id": "t2", "status": "running"},
        ]}
        state_file.write_text(yaml.dump(data))
        result = _check_stuck_tasks(state_file, repair=True)
        assert result.repaired is True

        # Verify file was updated
        with open(state_file) as f:
            updated = yaml.safe_load(f)
        for task in updated["scheduled_tasks"]:
            assert task["status"] == "active"


# ---------------------------------------------------------------------------
# Log cleanup
# ---------------------------------------------------------------------------

class TestLogCleanup:
    def test_pass_no_dir(self, tmp_path: Path):
        result = _check_log_cleanup(tmp_path / "nonexistent", repair=False)
        assert result.passed is True

    def test_pass_recent_logs(self, project: Path):
        logs_dir = project / "logs"
        (logs_dir / "recent.log").write_text("log data")
        result = _check_log_cleanup(logs_dir, repair=False)
        assert result.passed is True

    def test_fail_old_logs(self, project: Path):
        logs_dir = project / "logs"
        old_log = logs_dir / "old.log"
        old_log.write_text("old log data")
        # Set mtime to 5 days ago
        old_mtime = time.time() - (5 * 86400)
        os.utime(old_log, (old_mtime, old_mtime))
        result = _check_log_cleanup(logs_dir, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_old_logs(self, project: Path):
        logs_dir = project / "logs"
        old_log = logs_dir / "old.log"
        old_log.write_text("old log data")
        old_mtime = time.time() - (5 * 86400)
        os.utime(old_log, (old_mtime, old_mtime))
        result = _check_log_cleanup(logs_dir, repair=True)
        assert result.repaired is True
        assert not old_log.exists()


# ---------------------------------------------------------------------------
# CONTEXT.md capacity
# ---------------------------------------------------------------------------

class TestSessionArchivesHealth:
    def test_pass_no_dir(self, memory_dir: Path):
        result = _check_session_archives(memory_dir, repair=False)
        assert result.passed is True

    def test_pass_recent_archives(self, memory_dir: Path):
        sessions_dir = memory_dir / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "session_20260228_120000.md").write_text("recent")
        result = _check_session_archives(memory_dir, repair=False)
        assert result.passed is True

    def test_fail_old_archives(self, memory_dir: Path):
        sessions_dir = memory_dir / "sessions"
        sessions_dir.mkdir()
        old_archive = sessions_dir / "session_20200101_120000.md"
        old_archive.write_text("old session data")
        # Set mtime to 2 days ago so it's beyond 24h
        old_mtime = time.time() - (2 * 86400)
        os.utime(old_archive, (old_mtime, old_mtime))
        result = _check_session_archives(memory_dir, repair=False)
        assert result.passed is False
        assert result.repairable is True

    def test_repair_old_archives(self, memory_dir: Path):
        sessions_dir = memory_dir / "sessions"
        sessions_dir.mkdir()
        old_archive = sessions_dir / "session_20200101_120000.md"
        old_archive.write_text("old session data")
        old_mtime = time.time() - (2 * 86400)
        os.utime(old_archive, (old_mtime, old_mtime))
        result = _check_session_archives(memory_dir, repair=True)
        assert result.repaired is True
        assert not old_archive.exists()


class TestContextCapacity:
    def test_pass_no_file(self, memory_dir: Path):
        result = _check_context_capacity(memory_dir)
        assert result.passed is True

    def test_pass_under_threshold(self, memory_dir: Path):
        # 1000 chars is well under 80% of 50000
        (memory_dir / "CONTEXT.md").write_text("x" * 1000)
        result = _check_context_capacity(memory_dir)
        assert result.passed is True

    def test_fail_at_threshold(self, memory_dir: Path):
        # 40000 chars = 80% of 50000
        (memory_dir / "CONTEXT.md").write_text("x" * 40000)
        result = _check_context_capacity(memory_dir)
        assert result.passed is False
        assert result.repairable is False

    def test_fail_over_max(self, memory_dir: Path):
        (memory_dir / "CONTEXT.md").write_text("x" * 50000)
        result = _check_context_capacity(memory_dir)
        assert result.passed is False


# ---------------------------------------------------------------------------
# run_health integration
# ---------------------------------------------------------------------------

class TestRunHealth:
    def test_healthy_output_and_return_code(self, project: Path, capsys):
        # Create a valid venv python (just a file, not a real interpreter)
        venv_python = project / ".longxia_venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")

        code = run_health(project, repair=False)
        captured = capsys.readouterr()
        # Output format
        assert "LongxiaClaw Health Check" in captured.out
        assert "========" in captured.out
        assert "PASS" in captured.out
        assert "[+]" in captured.out or "[!]" in captured.out
        assert "passed" in captured.out
        # Backend binary (qwen) likely missing in CI, so code may be 1
        assert code in (0, 1)

    def test_unhealthy_returns_one(self, project: Path):
        # No venv → will fail venv check
        # Write a corrupt state file
        (project / "agent_workspace" / "scheduler" / "state.yaml").write_text("{{bad yaml")
        code = run_health(project, repair=False)
        assert code == 1

    def test_repair_mode(self, project: Path):
        # Write stale PID
        pid_file = project / "daemon" / "longxiaclaw.pid"
        pid_file.write_text("99999999")
        run_health(project, repair=True)
        assert not pid_file.exists()
