"""Tests for memory module."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


from longxiaclaw.memory import MemoryManager


def _memory_dir(tmp_project: Path) -> Path:
    """Return the memory_dir path for a tmp_project."""
    return tmp_project / "agent_workspace" / "memory"


def _make_archive(sessions_dir: Path, ts: datetime, turns: list[tuple[str, str]]) -> Path:
    """Helper: write an archive file with the given turns."""
    lines = ["# Session History\n"]
    for user, agent in turns:
        lines.append(f"**User** ({ts.isoformat()}):")
        lines.append(f"{user}\n")
        lines.append("**Agent**:")
        lines.append(f"{agent}\n")
        lines.append("---\n")
    fname = f"session_{ts.strftime('%Y%m%d_%H%M%S')}.md"
    path = sessions_dir / fname
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestSessionArchive:
    def test_push_turn(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        mm.push_turn("hello", "world")
        assert len(mm._window) == 1
        assert mm._window[0]["user"] == "hello"
        assert mm._window[0]["agent"] == "world"

    def test_push_turn_unlimited(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        for i in range(50):
            mm.push_turn(f"user-{i}", f"agent-{i}")
        # No maxlen — all 50 turns kept
        assert len(mm._window) == 50
        assert mm._window[0]["user"] == "user-0"
        assert mm._window[-1]["user"] == "user-49"

    def test_get_window_text(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        mm.push_turn("question", "answer")
        text = mm.get_window_text()
        assert "User: question" in text
        assert "Agent: answer" in text

    def test_get_window_text_empty(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        assert mm.get_window_text() == ""

    def test_archive_session_creates_file(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        mm.push_turn("hi", "hello")
        mm.push_turn("how are you", "great")
        path = mm.archive_session()

        assert path is not None
        assert path.exists()
        assert path.parent == mem_dir / "sessions"
        assert path.name.startswith("session_")
        assert path.name.endswith(".md")

        content = path.read_text(encoding="utf-8")
        assert "hi" in content
        assert "hello" in content
        assert "how are you" in content
        assert "great" in content

    def test_archive_session_saves_all_turns(self, tmp_project):
        """Archive saves ALL turns (no cap)."""
        mm = MemoryManager(_memory_dir(tmp_project))
        for i in range(30):
            mm.push_turn(f"user-{i}", f"agent-{i}")
        path = mm.archive_session()

        assert path is not None
        content = path.read_text(encoding="utf-8")
        # All 30 turns should be in archive
        assert "user-0" in content
        assert "user-9" in content
        assert "user-10" in content
        assert "user-29" in content

    def test_archive_session_empty_window(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        path = mm.archive_session()

        assert path is None
        # sessions/ dir should NOT be created
        assert not (mem_dir / "sessions").exists()

    def test_start_new_session(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        mm.push_turn("hi", "hello")
        path = mm.start_new_session()

        assert path is not None
        assert path.exists()
        assert len(mm._window) == 0

    def test_load_previous_sessions_no_dir(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        assert mm.load_previous_sessions() == ""

    def test_load_previous_sessions_with_archives(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        sessions_dir = mem_dir / "sessions"
        sessions_dir.mkdir()

        ts = datetime.now()
        _make_archive(sessions_dir, ts, [("hello", "world")])

        result = mm.load_previous_sessions()
        assert "hello" in result
        assert "world" in result

    def test_load_previous_sessions_ignores_old(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        sessions_dir = mem_dir / "sessions"
        sessions_dir.mkdir()

        old_ts = datetime.now() - timedelta(hours=25)
        _make_archive(sessions_dir, old_ts, [("old_question", "old_answer")])

        new_ts = datetime.now()
        _make_archive(sessions_dir, new_ts, [("new_question", "new_answer")])

        result = mm.load_previous_sessions()
        assert "new_question" in result
        assert "old_question" not in result

    def test_load_previous_sessions_sorted(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        sessions_dir = mem_dir / "sessions"
        sessions_dir.mkdir()

        ts1 = datetime.now() - timedelta(hours=2)
        ts2 = datetime.now() - timedelta(hours=1)

        _make_archive(sessions_dir, ts1, [("FIRST_Q", "FIRST_A")])
        _make_archive(sessions_dir, ts2, [("SECOND_Q", "SECOND_A")])

        result = mm.load_previous_sessions()
        # Oldest first
        assert result.index("FIRST_Q") < result.index("SECOND_Q")

    def test_load_previous_sessions_loads_all(self, tmp_project):
        """Loading returns ALL turns from archives (no cap)."""
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        sessions_dir = mem_dir / "sessions"
        sessions_dir.mkdir()

        ts = datetime.now()
        turns = [(f"user-{i}", f"agent-{i}") for i in range(30)]
        _make_archive(sessions_dir, ts, turns)

        result = mm.load_previous_sessions()
        # All 30 should be present
        assert "user-0" in result
        assert "user-9" in result
        assert "user-10" in result
        assert "user-29" in result

    def test_prune_old_sessions(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        sessions_dir = mem_dir / "sessions"
        sessions_dir.mkdir()

        old_ts = (datetime.now() - timedelta(hours=25)).strftime("%Y%m%d_%H%M%S")
        old_archive = sessions_dir / f"session_{old_ts}.md"
        old_archive.write_text("old", encoding="utf-8")

        new_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_archive = sessions_dir / f"session_{new_ts}.md"
        new_archive.write_text("new", encoding="utf-8")

        deleted = mm.prune_old_sessions()
        assert deleted == 1
        assert not old_archive.exists()
        assert new_archive.exists()

    def test_prune_old_sessions_no_dir(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        assert mm.prune_old_sessions() == 0

    def test_split_archive_turns(self, tmp_project):
        """Verify turn parsing from archive content."""
        mm = MemoryManager(_memory_dir(tmp_project))
        mm.push_turn("q1", "a1")
        mm.push_turn("q2", "a2")
        path = mm.archive_session()
        content = path.read_text(encoding="utf-8")

        turns = mm._split_archive_turns(content)
        assert len(turns) == 2
        assert "q1" in turns[0]
        assert "a1" in turns[0]
        assert "q2" in turns[1]
        assert "a2" in turns[1]


class TestLongTermMemory:
    def test_load_context_no_file(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        assert mm.load_context() == ""

    def test_load_context_empty_file(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        (mem_dir / "CONTEXT.md").write_text("", encoding="utf-8")
        mm = MemoryManager(mem_dir)
        assert mm.load_context() == ""

    def test_load_context_returns_full_content(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        content = (
            "[2026-01-01] User prefers Python for scripting\n\n"
            "[2026-01-02] Rust is used for performance-critical code\n\n"
            "[2026-01-03] Python FastAPI for web services\n"
        )
        (mem_dir / "CONTEXT.md").write_text(content, encoding="utf-8")
        mm = MemoryManager(mem_dir)
        result = mm.load_context()
        assert result == content

    def test_remember(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        result = mm.remember("User likes dark mode")
        assert "Remembered" in result
        content = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert "User likes dark mode" in content

    def test_remember_creates_header(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        mm.remember("First entry")
        content = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert content.startswith(
            "<!-- Long-term memory. The agent manages this file automatically. -->"
        )

    def test_remember_restores_header_after_empty_file(self, tmp_project):
        """Header is re-added when CONTEXT.md exists but is empty (e.g. after forget-all)."""
        mem_dir = _memory_dir(tmp_project)
        (mem_dir / "CONTEXT.md").write_text("", encoding="utf-8")
        mm = MemoryManager(mem_dir)
        mm.remember("New entry")
        content = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert content.startswith(
            "<!-- Long-term memory. The agent manages this file automatically. -->"
        )
        assert "New entry" in content

    def test_remember_appends(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir)
        mm.remember("First entry")
        mm.remember("Second entry")
        content = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert "First entry" in content
        assert "Second entry" in content

    def test_remember_capacity_warning(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        # Fill up to near capacity (use a small cap for testing)
        mm = MemoryManager(mem_dir, max_context_chars=100)
        (mem_dir / "CONTEXT.md").write_text("x" * 90, encoding="utf-8")
        result = mm.remember("This entry pushes over the character limit easily")
        assert "WARNING" in result

    def test_forget_by_content_removes_matching(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        content = (
            "<!-- Long-term memory. -->\n"
            "\n"
            "[2026-01-01 12:00] User likes Rust\n"
            "\n"
            "[2026-01-02 12:00] User prefers dark mode\n"
        )
        (mem_dir / "CONTEXT.md").write_text(content, encoding="utf-8")
        mm = MemoryManager(mem_dir)
        result = mm.forget_by_content("Rust")
        assert "Forgot 1" in result
        remaining = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert "Rust" not in remaining
        assert "dark mode" in remaining

    def test_forget_by_content_case_insensitive(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        (mem_dir / "CONTEXT.md").write_text(
            "[2026-01-01 12:00] User likes RUST\n", encoding="utf-8"
        )
        mm = MemoryManager(mem_dir)
        result = mm.forget_by_content("rust")
        assert "Forgot 1" in result

    def test_forget_by_content_no_match(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        (mem_dir / "CONTEXT.md").write_text(
            "[2026-01-01 12:00] User likes Python\n", encoding="utf-8"
        )
        mm = MemoryManager(mem_dir)
        result = mm.forget_by_content("Rust")
        assert "No entries matching" in result

    def test_forget_by_content_no_file(self, tmp_project):
        mm = MemoryManager(_memory_dir(tmp_project))
        result = mm.forget_by_content("anything")
        assert "does not exist" in result

    def test_forget_by_content_protects_header(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        content = (
            "<!-- Long-term memory. The agent manages this file automatically. -->\n"
            "\n"
            "[2026-01-01 12:00] User likes memory games\n"
        )
        (mem_dir / "CONTEXT.md").write_text(content, encoding="utf-8")
        mm = MemoryManager(mem_dir)
        # "memory" matches both the header comment and the entry
        mm.forget_by_content("memory")
        remaining = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        # Header preserved, entry removed
        assert remaining.startswith("<!--")
        assert "memory games" not in remaining

    def test_forget_by_content_removes_multiple(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        content = (
            "[2026-01-01 12:00] User likes Rust\n"
            "[2026-01-02 12:00] Rust is fast\n"
            "[2026-01-03 12:00] User likes Python\n"
        )
        (mem_dir / "CONTEXT.md").write_text(content, encoding="utf-8")
        mm = MemoryManager(mem_dir)
        result = mm.forget_by_content("Rust")
        assert "Forgot 2" in result
        remaining = (mem_dir / "CONTEXT.md").read_text(encoding="utf-8")
        assert "Rust" not in remaining
        assert "Python" in remaining

    def test_check_capacity(self, tmp_project):
        mem_dir = _memory_dir(tmp_project)
        mm = MemoryManager(mem_dir, max_context_chars=100)
        assert mm._check_capacity() is True

        (mem_dir / "CONTEXT.md").write_text("x" * 100, encoding="utf-8")
        assert mm._check_capacity() is False
