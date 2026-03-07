"""Two-tier memory: session archives (short-term) + CONTEXT.md (long-term)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class MemoryManager:
    """Two-tier memory: session archives (short-term) + CONTEXT.md (long-term)."""

    MAX_CONTEXT_CHARS = 50000
    ARCHIVE_RETENTION_HOURS = 24  # default archive retention
    _CONTEXT_HEADER = "<!-- Long-term memory. The agent manages this file automatically. -->"

    def __init__(
        self,
        memory_dir: Path,
        max_context_chars: Optional[int] = None,
        archive_retention_hours: Optional[int] = None,
    ):
        self._sessions_dir = memory_dir / "sessions"
        self._current_path = self._sessions_dir / "current.md"
        self._context_path = memory_dir / "CONTEXT.md"
        self._window: deque = deque()  # unlimited current session
        if max_context_chars is not None:
            self.MAX_CONTEXT_CHARS = max_context_chars
        if archive_retention_hours is not None:
            self.ARCHIVE_RETENTION_HOURS = archive_retention_hours

    # --- Short-term ---

    def load_previous_sessions(self) -> str:
        """Load all turns from 24h archives.

        Parses individual turns from all recent archives and returns them
        as formatted text. Returns empty string if none found.
        """
        archives = self._get_recent_archives()
        if not archives:
            return ""

        all_turns = []
        for _ts, path in archives:
            try:
                content = path.read_text(encoding="utf-8")
                all_turns.extend(self._split_archive_turns(content))
            except OSError:
                continue

        if not all_turns:
            return ""

        return "\n\n---\n\n".join(all_turns)

    def push_turn(self, user_input: str, agent_response: str) -> None:
        """Add turn to in-memory window and persist to current.md."""
        self._window.append({
            "user": user_input,
            "agent": agent_response,
            "timestamp": datetime.now().isoformat(),
        })
        self._flush_current()

    def _flush_current(self) -> None:
        """Write the full _window to sessions/current.md (overwrite).

        Creates sessions/ dir lazily. Deletes current.md if window is empty.
        """
        if not self._window:
            if self._current_path.exists():
                self._current_path.unlink()
            return

        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        lines = ["# Session History\n"]
        for turn in self._window:
            lines.append(f"**User** ({turn['timestamp']}):")
            lines.append(f"{turn['user']}\n")
            lines.append("**Agent**:")
            lines.append(f"{turn['agent']}\n")
            lines.append("---\n")

        self._current_path.write_text("\n".join(lines), encoding="utf-8")

    def load_current_session(self) -> int:
        """Load turns from sessions/current.md into _window (crash recovery).

        Returns the number of turns loaded (0 if no file or empty).
        """
        if not self._current_path.exists():
            return 0

        try:
            content = self._current_path.read_text(encoding="utf-8")
        except OSError:
            return 0

        if not content.strip():
            return 0

        turn_blocks = self._split_archive_turns(content)
        loaded = 0
        for block in turn_blocks:
            turn = self._parse_turn_block(block)
            if turn:
                self._window.append(turn)
                loaded += 1

        return loaded

    @staticmethod
    def _parse_turn_block(block: str) -> Optional[dict]:
        """Parse a single turn text block back into a turn dict."""
        # Expected format:
        # **User** (2026-01-01T12:00:00):
        # user text
        #
        # **Agent**:
        # agent text
        lines = block.strip().splitlines()
        if not lines:
            return None

        # Find user line: **User** (timestamp):
        user_text_lines = []
        agent_text_lines = []
        timestamp = ""
        in_agent = False

        for line in lines:
            if line.startswith("**User**"):
                # Extract timestamp from parentheses
                paren_start = line.find("(")
                paren_end = line.find(")")
                if paren_start >= 0 and paren_end > paren_start:
                    timestamp = line[paren_start + 1:paren_end]
                in_agent = False
            elif line.startswith("**Agent**"):
                in_agent = True
            elif in_agent:
                agent_text_lines.append(line)
            else:
                user_text_lines.append(line)

        user_text = "\n".join(user_text_lines).strip()
        agent_text = "\n".join(agent_text_lines).strip()

        if not user_text and not agent_text:
            return None

        return {
            "user": user_text,
            "agent": agent_text,
            "timestamp": timestamp or datetime.now().isoformat(),
        }

    def archive_session(self) -> Optional[Path]:
        """Save all turns to sessions/session_YYYYMMDD_HHMMSS.md.

        If current.md exists, renames it to the timestamped archive.
        Otherwise falls back to writing from _window directly.
        Returns path or None if no data to archive.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self._sessions_dir / f"session_{timestamp}.md"

        if self._current_path.exists():
            # Rename current.md to timestamped archive (no rewrite needed)
            self._current_path.rename(archive_path)
            return archive_path

        if not self._window:
            return None

        # Fallback: write from _window if current.md doesn't exist
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        lines = ["# Session History\n"]
        for turn in self._window:
            lines.append(f"**User** ({turn['timestamp']}):")
            lines.append(f"{turn['user']}\n")
            lines.append("**Agent**:")
            lines.append(f"{turn['agent']}\n")
            lines.append("---\n")

        archive_path.write_text("\n".join(lines), encoding="utf-8")
        return archive_path

    def start_new_session(self) -> Optional[Path]:
        """Archive current session then clear window. Returns archive path."""
        path = self.archive_session()
        self._window.clear()
        return path

    def prune_old_sessions(self) -> int:
        """Delete archive files older than ARCHIVE_RETENTION_HOURS. Returns count deleted."""
        if not self._sessions_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(hours=self.ARCHIVE_RETENTION_HOURS)
        deleted = 0

        for path in list(self._sessions_dir.iterdir()):
            if not path.is_file() or not path.name.startswith("session_"):
                continue
            ts = self._parse_archive_timestamp(path.name)
            if ts is not None and ts < cutoff:
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass

        return deleted

    def get_window_text(self) -> str:
        """Get current window as formatted text for prompt assembly."""
        if not self._window:
            return ""
        lines = []
        for turn in self._window:
            lines.append(f"User: {turn['user']}")
            lines.append(f"Agent: {turn['agent']}")
        return "\n".join(lines)

    @staticmethod
    def _parse_archive_timestamp(filename: str) -> Optional[datetime]:
        """Parse timestamp from archive filename like session_YYYYMMDD_HHMMSS.md."""
        # Strip prefix and suffix
        stem = filename.replace("session_", "").replace(".md", "")
        try:
            return datetime.strptime(stem, "%Y%m%d_%H%M%S")
        except ValueError:
            return None

    def _get_recent_archives(self) -> list[tuple[datetime, Path]]:
        """Get archive files from last 24h, sorted chronologically (oldest first)."""
        if not self._sessions_dir.exists():
            return []

        cutoff = datetime.now() - timedelta(hours=self.ARCHIVE_RETENTION_HOURS)
        archives = []

        for path in self._sessions_dir.iterdir():
            if not path.is_file() or not path.name.startswith("session_"):
                continue
            ts = self._parse_archive_timestamp(path.name)
            if ts is not None and ts >= cutoff:
                archives.append((ts, path))

        archives.sort(key=lambda x: x[0])
        return archives

    @staticmethod
    def _split_archive_turns(content: str) -> list[str]:
        """Split archive content into individual turn text blocks."""
        blocks = content.split("\n---\n")
        turns = []
        for block in blocks:
            stripped = block.strip()
            if not stripped or "**User**" not in stripped:
                continue
            # Remove leading "# Session History" header if present
            if stripped.startswith("# Session History"):
                idx = stripped.find("**User**")
                stripped = stripped[idx:] if idx >= 0 else stripped
            turns.append(stripped)
        return turns

    # --- Long-term ---

    def load_context(self) -> str:
        """Read and return full CONTEXT.md text. Empty string if missing."""
        if not self._context_path.exists():
            return ""
        try:
            return self._context_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def remember(self, entry: str) -> str:
        """Append entry to CONTEXT.md with timestamp.
        If at MAX_CONTEXT_CHARS, return warning.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_entry = f"[{timestamp}] {entry}"

        if self._context_path.exists():
            existing = self._context_path.read_text(encoding="utf-8")
        else:
            existing = ""

        if not existing:
            existing = self._CONTEXT_HEADER + "\n"

        if len(existing) + len(new_entry) + 2 > self.MAX_CONTEXT_CHARS:
            return (
                f"WARNING: CONTEXT.md is at {len(existing)}/{self.MAX_CONTEXT_CHARS} characters. "
                f"Cannot add {len(new_entry)} more characters. Ask the user what to remove first."
            )

        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing:
            existing += "\n"

        self._context_path.write_text(existing + new_entry + "\n", encoding="utf-8")
        return f"Remembered: {entry}"

    def forget_by_content(self, query: str) -> str:
        """Remove entries from CONTEXT.md that contain *query* (case-insensitive).

        Returns a summary of what was removed, or a message if nothing matched.
        """
        if not self._context_path.exists():
            return "CONTEXT.md does not exist."

        content = self._context_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        query_lower = query.lower()
        kept: list[str] = []
        removed: list[str] = []

        for line in lines:
            if query_lower in line.lower() and line.strip() and not line.startswith("<!--"):
                removed.append(line)
            else:
                kept.append(line)

        if not removed:
            return f"No entries matching '{query}' found in CONTEXT.md."

        self._context_path.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
        summary = "; ".join(r.strip()[:80] for r in removed)
        return f"Forgot {len(removed)} entry(s): {summary}"

    def _check_capacity(self) -> bool:
        """Return True if CONTEXT.md has room for more entries."""
        if not self._context_path.exists():
            return True
        char_count = len(self._context_path.read_text(encoding="utf-8"))
        return char_count < self.MAX_CONTEXT_CHARS
