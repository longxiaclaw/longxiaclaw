"""Health check and repair for LongxiaClaw."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

VENV_DIR = ".longxia_venv"
LOG_RETENTION_DAYS = 3

# Mapping: (import_name, package_name) for core dependencies
CORE_DEPS = [
    ("yaml", "pyyaml"),
    ("croniter", "croniter"),
    ("dotenv", "python-dotenv"),
    ("ddgs", "ddgs"),
    ("rich", "rich"),
    ("prompt_toolkit", "prompt-toolkit"),
]


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    repairable: bool = False
    repaired: bool = False
    repair_message: str = ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_venv_integrity(project_root: Path, repair: bool) -> CheckResult:
    """Check that .longxia_venv/bin/python exists and is not a broken symlink."""
    venv_python = project_root / VENV_DIR / "bin" / "python"

    if venv_python.exists():
        return CheckResult("Venv integrity", True, "OK")

    # Broken symlink or missing
    if venv_python.is_symlink() or not venv_python.exists():
        if not repair:
            return CheckResult(
                "Venv integrity", False,
                f"{venv_python} is missing or a broken symlink",
                repairable=True,
            )

        # Repair: recreate venv
        from longxiaclaw.main import _find_suitable_python
        host_python = _find_suitable_python()
        venv_path = project_root / VENV_DIR
        try:
            subprocess.run(
                [host_python, "-m", "venv", "--clear", str(venv_path)],
                check=True, capture_output=True,
            )
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", "-e", str(project_root)],
                check=True, capture_output=True,
            )
            (venv_path / ".installed").write_text("ok")
            return CheckResult(
                "Venv integrity", False,
                f"{venv_python} was broken",
                repairable=True, repaired=True,
                repair_message="Recreated venv and reinstalled dependencies",
            )
        except Exception as e:
            return CheckResult(
                "Venv integrity", False,
                f"Repair failed: {e}",
                repairable=True, repaired=False,
                repair_message=f"Failed to recreate venv: {e}",
            )

    return CheckResult("Venv integrity", True, "OK")


def _check_core_deps(project_root: Path, repair: bool) -> CheckResult:
    """Check that all core dependencies are importable."""
    missing = []
    for import_name, package_name in CORE_DEPS:
        try:
            __import__(import_name)
        except ImportError:
            missing.append((import_name, package_name))

    if not missing:
        return CheckResult("Core dependencies", True, "OK")

    desc = ", ".join(f"{pkg} ({imp})" for imp, pkg in missing)

    if not repair:
        return CheckResult(
            "Core dependencies", False,
            f"Missing: {desc}",
            repairable=True,
        )

    # Repair: pip install -e .
    venv_python = project_root / VENV_DIR / "bin" / "python"
    try:
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-e", str(project_root)],
            check=True, capture_output=True,
        )
        return CheckResult(
            "Core dependencies", False,
            f"Missing: {desc}",
            repairable=True, repaired=True,
            repair_message="Ran pip install -e .",
        )
    except Exception as e:
        return CheckResult(
            "Core dependencies", False,
            f"Missing: {desc}",
            repairable=True, repaired=False,
            repair_message=f"pip install failed: {e}",
        )


def _check_stale_pid(pid_file: Path, repair: bool) -> CheckResult:
    """Check for stale PID file (process dead)."""
    if not pid_file.exists():
        return CheckResult("PID file", True, "OK (no PID file)")

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        if not repair:
            return CheckResult(
                "PID file", False, "Invalid PID file",
                repairable=True,
            )
        pid_file.unlink(missing_ok=True)
        return CheckResult(
            "PID file", False, "Invalid PID file",
            repairable=True, repaired=True,
            repair_message="Removed invalid PID file",
        )

    try:
        os.kill(pid, 0)
        return CheckResult("PID file", True, f"OK (PID {pid} alive)")
    except ProcessLookupError:
        if not repair:
            return CheckResult(
                "PID file", False,
                f"Stale PID file (PID {pid} not running)",
                repairable=True,
            )
        pid_file.unlink(missing_ok=True)
        return CheckResult(
            "PID file", False,
            f"Stale PID file (PID {pid} not running)",
            repairable=True, repaired=True,
            repair_message="Removed stale PID file",
        )
    except PermissionError:
        return CheckResult("PID file", True, f"OK (PID {pid} exists, no permission to signal)")


def _check_stale_socket(socket_path: Path, repair: bool) -> CheckResult:
    """Check for stale socket (exists but connection refused)."""
    if not socket_path.exists():
        return CheckResult("Socket file", True, "OK (no socket)")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        sock.connect(str(socket_path))
        sock.close()
        return CheckResult("Socket file", True, "OK (socket accepting connections)")
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        sock.close()
        if not repair:
            return CheckResult(
                "Socket file", False,
                "Stale socket (connection refused)",
                repairable=True,
            )
        try:
            socket_path.unlink()
        except OSError:
            pass
        return CheckResult(
            "Socket file", False,
            "Stale socket (connection refused)",
            repairable=True, repaired=True,
            repair_message="Removed stale socket file",
        )


def _check_backend_binary(backend_binary: str) -> CheckResult:
    """Check that the backend binary is on PATH."""
    if shutil.which(backend_binary):
        return CheckResult("Backend binary", True, f"OK ({backend_binary} found)")
    return CheckResult(
        "Backend binary", False,
        f"{backend_binary} not found on PATH",
        repairable=False,
    )


def _check_state_file(state_file: Path, repair: bool) -> CheckResult:
    """Check that state.yaml is valid YAML."""
    if not state_file.exists():
        return CheckResult("State file", True, "OK (no state file)")

    try:
        import yaml
    except ImportError:
        return CheckResult("State file", True, "OK (skipped, pyyaml not available)")

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is not None and not isinstance(data, dict):
            raise yaml.YAMLError("State file is not a YAML mapping")
        return CheckResult("State file", True, "OK")
    except (yaml.YAMLError, OSError) as e:
        if not repair:
            return CheckResult(
                "State file", False,
                f"Corrupt: {e}",
                repairable=True,
            )
        # Backup and remove
        backup = state_file.with_suffix(".yaml.bak")
        try:
            shutil.copy2(state_file, backup)
            state_file.unlink()
            return CheckResult(
                "State file", False,
                f"Corrupt: {e}",
                repairable=True, repaired=True,
                repair_message=f"Backed up to {backup.name} and removed original",
            )
        except OSError as e2:
            return CheckResult(
                "State file", False,
                f"Corrupt: {e}",
                repairable=True, repaired=False,
                repair_message=f"Backup failed: {e2}",
            )


def _check_stuck_tasks(state_file: Path, repair: bool) -> CheckResult:
    """Check for tasks stuck in 'running' status."""
    if not state_file.exists():
        return CheckResult("Stuck tasks", True, "OK (no state file)")

    try:
        import yaml
    except ImportError:
        return CheckResult("Stuck tasks", True, "OK (skipped, pyyaml not available)")

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        # State file corruption is handled by _check_state_file
        return CheckResult("Stuck tasks", True, "OK (skipped, state file unreadable)")

    if not data or not isinstance(data, dict):
        return CheckResult("Stuck tasks", True, "OK (no tasks)")

    tasks = data.get("scheduled_tasks", [])
    stuck = [t for t in tasks if isinstance(t, dict) and t.get("status") == "running"]

    if not stuck:
        return CheckResult("Stuck tasks", True, "OK")

    stuck_ids = [t.get("id", "?") for t in stuck]
    desc = f"{len(stuck)} stuck task(s): {', '.join(stuck_ids)}"

    if not repair:
        return CheckResult("Stuck tasks", False, desc, repairable=True)

    # Repair: reset running → active
    for task in tasks:
        if isinstance(task, dict) and task.get("status") == "running":
            task["status"] = "active"
    try:
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            dir=state_file.parent, suffix=".tmp", prefix="state_",
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        os.replace(tmp_path, state_file)
        return CheckResult(
            "Stuck tasks", False, desc,
            repairable=True, repaired=True,
            repair_message=f"Reset {len(stuck)} task(s) from 'running' to 'active'",
        )
    except Exception as e:
        return CheckResult(
            "Stuck tasks", False, desc,
            repairable=True, repaired=False,
            repair_message=f"Failed to reset tasks: {e}",
        )


def _check_log_cleanup(logs_dir: Path, repair: bool) -> CheckResult:
    """Check for log files older than LOG_RETENTION_DAYS."""
    if not logs_dir.exists():
        return CheckResult("Log cleanup", True, "OK (no logs directory)")

    cutoff = time.time() - (LOG_RETENTION_DAYS * 86400)
    old_files = []
    for f in logs_dir.iterdir():
        if f.is_file():
            try:
                if f.stat().st_mtime < cutoff:
                    old_files.append(f)
            except OSError:
                pass

    if not old_files:
        return CheckResult("Log cleanup", True, "OK")

    desc = f"{len(old_files)} log file(s) older than {LOG_RETENTION_DAYS} days"

    if not repair:
        return CheckResult("Log cleanup", False, desc, repairable=True)

    removed = 0
    for f in old_files:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass

    return CheckResult(
        "Log cleanup", False, desc,
        repairable=True, repaired=True,
        repair_message=f"Deleted {removed} old log file(s)",
    )


def _check_session_archives(memory_dir: Path, repair: bool) -> CheckResult:
    """Warn if session archives older than 24h exist; repair by pruning."""
    sessions_dir = memory_dir / "sessions"
    if not sessions_dir.exists():
        return CheckResult("Session archives", True, "OK (no sessions directory)")

    from longxiaclaw.memory import MemoryManager
    mm = MemoryManager(memory_dir)

    # Count old files by doing a dry check
    cutoff = time.time() - (24 * 3600)
    old_files = []
    for f in sessions_dir.iterdir():
        if f.is_file() and f.name.startswith("session_"):
            try:
                if f.stat().st_mtime < cutoff:
                    old_files.append(f)
            except OSError:
                pass

    if not old_files:
        return CheckResult("Session archives", True, "OK")

    desc = f"{len(old_files)} session archive(s) older than 24h"

    if not repair:
        return CheckResult("Session archives", False, desc, repairable=True)

    deleted = mm.prune_old_sessions()
    return CheckResult(
        "Session archives", False, desc,
        repairable=True, repaired=True,
        repair_message=f"Pruned {deleted} old session archive(s)",
    )


def _check_context_capacity(memory_dir: Path) -> CheckResult:
    """Warn if CONTEXT.md is approaching capacity (>= 80% of MAX_CONTEXT_CHARS)."""
    context_path = memory_dir / "CONTEXT.md"
    if not context_path.exists():
        return CheckResult("CONTEXT.md capacity", True, "OK (no CONTEXT.md)")

    try:
        char_count = len(context_path.read_text(encoding="utf-8"))
    except OSError:
        return CheckResult("CONTEXT.md capacity", True, "OK (unreadable, skipped)")

    max_chars = 50000  # MemoryManager.MAX_CONTEXT_CHARS
    threshold = int(max_chars * 0.8)  # 40000

    if char_count < threshold:
        return CheckResult(
            "CONTEXT.md capacity", True,
            f"OK ({char_count}/{max_chars} chars)",
        )

    return CheckResult(
        "CONTEXT.md capacity", False,
        f"{char_count}/{max_chars} chars (>= 80% full)",
        repairable=False,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_health(project_root: Path, repair: bool = False) -> int:
    """Run all health checks and print results.

    Returns 0 if all pass, 1 if any fail.
    """
    # Build config with fallback if imports are broken
    try:
        from .config import Config
        config = Config.from_env()
        config.project_root = project_root
    except Exception:
        # Fallback: construct paths manually
        config = None

    if config:
        pid_file = config.pid_file
        socket_path = config.socket_path
        state_file = config.state_file
        logs_dir = config.logs_dir
        backend_binary = config.backend_binary
        memory_dir = config.memory_dir
    else:
        daemon_dir = project_root / "daemon"
        pid_file = daemon_dir / "longxiaclaw.pid"
        socket_path = daemon_dir / "longxiaclaw.sock"
        scheduler_dir = (project_root / "agent_workspace" / "scheduler").resolve()
        state_file = scheduler_dir / "state.yaml"
        logs_dir = project_root / "logs"
        backend_binary = "qwen"
        memory_dir = (project_root / "agent_workspace" / "memory").resolve()

    # Run checks
    results: List[CheckResult] = [
        _check_venv_integrity(project_root, repair),
        _check_core_deps(project_root, repair),
        _check_stale_pid(pid_file, repair),
        _check_stale_socket(socket_path, repair),
        _check_backend_binary(backend_binary),
        _check_state_file(state_file, repair),
        _check_stuck_tasks(state_file, repair),
        _check_log_cleanup(logs_dir, repair),
        _check_session_archives(memory_dir, repair),
        _check_context_capacity(memory_dir),
    ]

    # Print results (plain text, no Rich)
    print()
    print("LongxiaClaw Health Check")
    print("=" * 40)
    print()

    for r in results:
        if r.passed:
            prefix = "  [+]"
        else:
            prefix = "  [!]"

        print(f"{prefix} {r.name}: {'PASS' if r.passed else 'FAIL'}")

        if not r.passed:
            print(f"      {r.message}")
            if r.repaired:
                print(f"      Repaired: {r.repair_message}")
            elif r.repairable and not repair:
                print("      (repairable with --repair)")
            elif r.repairable and repair and not r.repaired:
                print(f"      Repair failed: {r.repair_message}")

    passed = sum(1 for r in results if r.passed or r.repaired)
    total = len(results)
    failed = total - passed

    print()
    if failed == 0:
        print(f"{passed}/{total} passed, all healthy")
    else:
        print(f"{passed}/{total} passed, {failed} issue(s) remaining")
        repairable = [r for r in results if not r.passed and not r.repaired and r.repairable]
        if repairable and not repair:
            print("Run 'longxia health --repair' to fix repairable issues.")

    return 0 if failed == 0 else 1
