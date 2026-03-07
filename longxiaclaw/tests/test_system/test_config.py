"""Tests for config module."""

from __future__ import annotations

import os


from longxiaclaw.system import Config


class TestConfig:
    def test_default_values(self):
        config = Config()
        assert config.assistant_name == "LongxiaClaw"
        assert config.default_backend == "qwen"
        assert config.backend_timeout == 300
        assert config.scheduler_poll_interval == 60.0
        assert config.backend_binary == "qwen"
        assert config.backend_model == ""
        assert config.backend_approval_mode == "yolo"
        assert config.log_level == "INFO"
        assert config.max_context_chars == 50000
        assert config.archive_retention_hours == 24

    def test_from_env_with_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ASSISTANT_NAME", "MyClaw")
        monkeypatch.setenv("DEFAULT_BACKEND", "custom")
        monkeypatch.setenv("BACKEND_TIMEOUT", "60")
        monkeypatch.setenv("SCHEDULER_POLL_INTERVAL", "120.0")
        monkeypatch.setenv("BACKEND_BINARY", "/usr/local/bin/qwen")
        monkeypatch.setenv("BACKEND_MODEL", "qwen3-coder")
        monkeypatch.setenv("BACKEND_APPROVAL_MODE", "suggest")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

        config = Config.from_env()
        assert config.assistant_name == "MyClaw"
        assert config.default_backend == "custom"
        assert config.backend_timeout == 60
        assert config.scheduler_poll_interval == 120.0
        assert config.backend_binary == "/usr/local/bin/qwen"
        assert config.backend_model == "qwen3-coder"
        assert config.backend_approval_mode == "suggest"
        assert config.log_level == "DEBUG"
        assert config.project_root == tmp_path

    def test_from_env_with_dotenv_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ASSISTANT_NAME=EnvFileClaw\nBACKEND_TIMEOUT=42\n",
            encoding="utf-8",
        )
        # Clean env to avoid interference
        for key in ("ASSISTANT_NAME", "BACKEND_TIMEOUT"):
            os.environ.pop(key, None)

        config = Config.from_env(path=env_file)
        assert config.assistant_name == "EnvFileClaw"
        assert config.backend_timeout == 42

    def test_ensure_dirs(self, tmp_path):
        config = Config(project_root=tmp_path)
        # Remove dirs if they exist
        for d in ("daemon", "logs", "skills"):
            p = tmp_path / d
            if p.exists():
                p.rmdir()

        config.ensure_dirs()

        assert (tmp_path / "daemon").is_dir()
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "skills").is_dir()
        assert config.memory_dir.is_dir()
        assert config.scheduler_dir.is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path):
        config = Config(project_root=tmp_path)
        config.ensure_dirs()
        config.ensure_dirs()  # Should not raise
        assert (tmp_path / "daemon").is_dir()

    def test_property_paths(self, tmp_path):
        config = Config(project_root=tmp_path)
        assert config.daemon_dir == tmp_path / "daemon"
        assert config.logs_dir == tmp_path / "logs"
        assert config.skills_dir == tmp_path / "skills"
        assert config.memory_dir == config.agent_workspace_dir / "memory"
        assert config.sessions_dir == config.memory_dir / "sessions"
        assert config.context_path == config.memory_dir / "CONTEXT.md"
        assert config.scheduler_dir == config.agent_workspace_dir / "scheduler"
        assert config.pid_file == tmp_path / "daemon" / "longxiaclaw.pid"
        assert config.socket_path == tmp_path / "daemon" / "longxiaclaw.sock"
        assert config.state_file == config.scheduler_dir / "state.yaml"
