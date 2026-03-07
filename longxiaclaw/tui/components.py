"""UI widgets for the TUI: header, processing indicator, response renderer."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from io import StringIO
from typing import Callable, Optional

import psutil
from rich.color import Color
from rich.console import Console
from rich.markdown import Markdown
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .theme import GRADIENT_COLORS, STYLES


_LONGXIA_ASCII = [
    "█      ███  █   █  ████ █   █ ███  ███ ",
    "█     █   █ ██  █ █      █ █   █  █   █",
    "█     █   █ █ █ █ █  ██   █    █  █████",
    "█     █   █ █  ██ █   █  █ █   █  █   █",
    "█████  ███  █   █  ████ █   █ ███ █   █",
]


def _make_gradient_text(text: str, bold: bool = True) -> Text:
    """Create a Rich Text object with per-character gradient coloring."""
    result = Text()
    chars = [c for c in text if not c.isspace()]
    n = max(len(chars) - 1, 1)
    stops = len(GRADIENT_COLORS) - 1

    char_idx = 0
    for ch in text:
        if ch.isspace():
            result.append(ch)
        else:
            t = char_idx / n
            seg = min(int(t * stops), stops - 1)
            local_t = (t * stops) - seg
            r0, g0, b0 = GRADIENT_COLORS[seg]
            r1, g1, b1 = GRADIENT_COLORS[seg + 1]
            r = int(r0 + (r1 - r0) * local_t)
            g = int(g0 + (g1 - g0) * local_t)
            b = int(b0 + (b1 - b0) * local_t)
            style = Style(color=Color.from_rgb(r, g, b), bold=bold)
            result.append(ch, style=style)
            char_idx += 1
    return result


def _make_gradient_banner(bold: bool = True) -> Text:
    """Create a multi-line gradient banner from the ASCII art."""
    all_chars = [c for line in _LONGXIA_ASCII for c in line if not c.isspace()]
    n = max(len(all_chars) - 1, 1)
    stops = len(GRADIENT_COLORS) - 1

    result = Text()
    char_idx = 0
    for i, line in enumerate(_LONGXIA_ASCII):
        if i > 0:
            result.append("\n")
        for ch in line:
            if ch.isspace():
                result.append(ch)
            else:
                t = char_idx / n
                seg = min(int(t * stops), stops - 1)
                local_t = (t * stops) - seg
                r0, g0, b0 = GRADIENT_COLORS[seg]
                r1, g1, b1 = GRADIENT_COLORS[seg + 1]
                r = int(r0 + (r1 - r0) * local_t)
                g = int(g0 + (g1 - g0) * local_t)
                b = int(b0 + (b1 - b0) * local_t)
                style = Style(color=Color.from_rgb(r, g, b), bold=bold)
                result.append(ch, style=style)
                char_idx += 1
    return result


class HeaderBar:
    """Top panel: gradient LONGXIA banner + status info box."""

    def __init__(
        self,
        backend: str = "qwen",
        version: str = "0.1.0",
        workspace_path: str = "",
        pid: int = 0,
    ):
        self.backend = backend
        self.version = version
        self.workspace_path = workspace_path or os.getcwd()
        self._pid = pid or os.getpid()
        self._cpu: str = "N/A"
        self._ram: str = "N/A"
        self._process: Optional[psutil.Process] = None
        try:
            self._process = psutil.Process(self._pid)
            self._process.cpu_percent()  # prime the first call
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def refresh_stats(self) -> None:
        """Update CPU and RAM stats from psutil."""
        if self._process is None:
            return
        try:
            self._cpu = f"{self._process.cpu_percent():.1f}%"
            mem = self._process.memory_info().rss
            total = psutil.virtual_memory().total
            self._ram = f"{mem / (1024 ** 3):.2f} / {total / (1024 ** 3):.1f} GB"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._cpu = "N/A"
            self._ram = "N/A"

    def render_ansi(self, width: int) -> str:
        """Render the full header block (panel + hint + separator) as raw ANSI."""
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=width, color_system="truecolor")

        banner = _make_gradient_banner(bold=True)
        banner_width = max(len(line) for line in _LONGXIA_ASCII) + 2

        table = Table(show_header=False, box=None, expand=True, padding=(0, 1))
        table.add_column(min_width=banner_width, no_wrap=True)
        table.add_column(ratio=1)

        now = datetime.now().strftime("%H:%M:%S")
        status_lines = [
            f"Time: {now}",
            f"Version: {self.version}",
            f"Backend: {self.backend}",
            f"Workspace: {self.workspace_path}",
            f"CPU: {self._cpu} | RAM: {self._ram}",
        ]
        status_text = Text("\n".join(status_lines), style=STYLES["header.status"])

        separator = Text("─" * width, style=STYLES["separator"])
        console.print(separator)

        table.add_row(banner, status_text)
        console.print(table)

        hint = Text(
            "Try /help for all available commands.\n"
            "Edit .env to configure system arguments.\n"
            "Add new skills based on skills/_template.md and set enabled: true.\n"
            "Run `longxia restart` to apply changes.",
            style=STYLES["header.hint"],
        )
        console.print(hint)

        separator = Text("─" * width, style=STYLES["separator"])
        console.print(separator)

        return buf.getvalue()


class ProcessingIndicator:
    """Animated processing indicator using callbacks for full-screen TUI.

    Instead of writing directly to stdout, calls ``on_update`` and ``on_done``
    callbacks so that the Application can refresh the display.
    """

    _DOT_FRAMES = (".", "..", "...")

    def __init__(
        self,
        on_update: Callable[[str], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ):
        self._on_update = on_update or (lambda s: None)
        self._on_done = on_done or (lambda s: None)
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._start_time: float = 0.0
        self._elapsed: float = 0.0

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._stopped = False
        self._task = asyncio.create_task(self._animate())

    async def _animate(self) -> None:
        frame = 0
        try:
            while not self._stopped:
                dots = self._DOT_FRAMES[frame % len(self._DOT_FRAMES)]
                elapsed = int(time.monotonic() - self._start_time)
                text = f"Processing {dots} ({elapsed}s)"
                self._on_update(text)
                frame += 1
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the animation without emitting a summary."""
        self._stopped = True
        self._elapsed = time.monotonic() - self._start_time
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def emit_summary(self) -> None:
        """Call on_done with the 'Processed in Xs' summary."""
        summary = f"Processed in {int(self._elapsed)}s"
        self._on_done(summary)


class ResponseRenderer:
    """Rich markdown rendering for agent output."""

    @staticmethod
    def render(console: Console, text: str, style: str = "response") -> None:
        try:
            md = Markdown(text)
            console.print(md)
        except Exception:
            console.print(Text(text, style=STYLES.get(style, "white")))

    @staticmethod
    def render_to_ansi(text: str, width: int) -> str:
        """Render markdown text to ANSI string for embedding in full-screen TUI."""
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=width, color_system="truecolor")
        try:
            md = Markdown(text)
            console.print(md)
        except Exception:
            console.print(Text(text, style=STYLES.get("response", "white")))
        return buf.getvalue()
