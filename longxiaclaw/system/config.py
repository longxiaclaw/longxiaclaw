"""Configuration management for LongxiaClaw."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    assistant_name: str = "LongxiaClaw"
    default_backend: str = "qwen"
    backend_timeout: int = 300
    scheduler_poll_interval: float = 60.0
    backend_binary: str = "qwen"
    backend_model: str = ""
    backend_approval_mode: str = "yolo"
    log_level: str = "INFO"
    max_context_chars: int = 50000
    archive_retention_hours: int = 24
    project_root: Path = field(default_factory=lambda: Path("."))
    agent_workspace: str = "./agent_workspace"
    read_global: bool = True
    write_global: bool = False

    @classmethod
    def from_env(cls, path: Optional[Path] = None) -> Config:
        """Load configuration from .env file and environment variables.

        Args:
            path: Optional path to .env file. If None, searches project root.
        """
        if path is not None:
            load_dotenv(path)
        else:
            load_dotenv()

        project_root = Path(os.getenv("PROJECT_ROOT", ".")).resolve()

        return cls(
            assistant_name=os.getenv("ASSISTANT_NAME", "LongxiaClaw"),
            default_backend=os.getenv("DEFAULT_BACKEND", "qwen"),
            backend_timeout=int(os.getenv("BACKEND_TIMEOUT", "300")),
            scheduler_poll_interval=float(os.getenv("SCHEDULER_POLL_INTERVAL", "60.0")),
            backend_binary=os.getenv("BACKEND_BINARY", "qwen"),
            backend_model=os.getenv("BACKEND_MODEL", ""),
            backend_approval_mode=os.getenv("BACKEND_APPROVAL_MODE", "yolo"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            max_context_chars=int(os.getenv("MAX_CONTEXT_CHARS", "50000")),
            archive_retention_hours=int(os.getenv("ARCHIVE_RETENTION_HOURS", "24")),
            project_root=project_root,
            agent_workspace=os.getenv("AGENT_WORKSPACE", "./agent_workspace"),
            read_global=os.getenv("READ_GLOBAL", "true").lower() in ("true", "1", "yes"),
            write_global=os.getenv("WRITE_GLOBAL", "false").lower() in ("true", "1", "yes"),
        )

    def ensure_dirs(self) -> None:
        """Create daemon/, logs/, skills/, agent_workspace/memory/, agent_workspace/scheduler/ directories if missing."""
        for dirname in ("daemon", "logs", "skills"):
            (self.project_root / dirname).mkdir(parents=True, exist_ok=True)
        self.agent_workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.scheduler_dir.mkdir(parents=True, exist_ok=True)

    @property
    def daemon_dir(self) -> Path:
        return self.project_root / "daemon"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    @property
    def skills_dir(self) -> Path:
        return self.project_root / "skills"

    @property
    def memory_dir(self) -> Path:
        return self.agent_workspace_dir / "memory"

    @property
    def sessions_dir(self) -> Path:
        return self.memory_dir / "sessions"

    @property
    def context_path(self) -> Path:
        return self.memory_dir / "CONTEXT.md"

    @property
    def agent_workspace_dir(self) -> Path:
        return (self.project_root / self.agent_workspace).resolve()

    @property
    def scheduler_dir(self) -> Path:
        return self.agent_workspace_dir / "scheduler"

    @property
    def pid_file(self) -> Path:
        return self.daemon_dir / "longxiaclaw.pid"

    @property
    def socket_path(self) -> Path:
        return self.daemon_dir / "longxiaclaw.sock"

    @property
    def state_file(self) -> Path:
        return self.scheduler_dir / "state.yaml"
