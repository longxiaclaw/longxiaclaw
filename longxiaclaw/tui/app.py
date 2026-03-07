"""Main TUI layout and event loop — full-screen prompt_toolkit Application.

Connects to the agent daemon via Unix socket and displays a sticky header
with dynamic stats, scrollable conversation area, and bottom input line.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from io import StringIO
from typing import Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent
from prompt_toolkit.layout.layout import Layout
from rich.console import Console
from rich.text import Text

from .components import HeaderBar, ProcessingIndicator, ResponseRenderer
from .theme import STYLES


class _ScrollableWindow(Window):
    """Window that bypasses cursor-following scroll and supports auto-scroll.

    prompt_toolkit's default ``Window._scroll`` always constrains
    ``vertical_scroll`` to keep the cursor visible, which fights manual
    scrolling for non-editable content.  This subclass replaces that logic
    with simple clamping and an optional auto-scroll-to-bottom mode.
    """

    def __init__(self, *args, auto_scroll_ref=None, on_mouse_scroll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._auto_scroll_ref = auto_scroll_ref or (lambda: False)
        self._on_mouse_scroll = on_mouse_scroll

    # -- Override scroll: no cursor following, just clamp ----------------

    def _scroll(self, ui_content: UIContent, width: int, height: int) -> None:
        self.horizontal_scroll = 0

        if self._auto_scroll_ref():
            self.vertical_scroll = 999999

        if self.wrap_lines():
            topmost = self._topmost_visible(ui_content, width, height)
        else:
            topmost = max(0, ui_content.line_count - height)

        self.vertical_scroll = max(0, min(self.vertical_scroll, topmost))
        self.vertical_scroll_2 = 0

    def _topmost_visible(self, ui_content: UIContent, width: int, height: int) -> int:
        """Highest logical line that still shows the last line at the bottom."""
        prev = ui_content.line_count - 1
        used = 0
        for lineno in range(ui_content.line_count - 1, -1, -1):
            used += ui_content.get_height_for_line(lineno, width, self.get_line_prefix)
            if used > height:
                return prev
            prev = lineno
        return prev

    # -- Intercept mouse scroll to disable auto-scroll ------------------

    def _mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type in (
            MouseEventType.SCROLL_UP,
            MouseEventType.SCROLL_DOWN,
        ):
            if self._on_mouse_scroll:
                self._on_mouse_scroll()
        return super()._mouse_handler(mouse_event)


class LongxiaClawTUI:
    """TUI client using prompt_toolkit full-screen Application."""

    def __init__(self, config):
        self._config = config
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._busy = False

        self._conv_fragments: list[str] = []
        self._input_history: list[str] = []
        self._history_pos: int = -1
        self._saved_input: str = ""

        self._header_bar = HeaderBar(
            backend=config.default_backend,
            version="0.1.0",
            workspace_path=str(getattr(config, "agent_workspace_dir", config.project_root)),
            pid=self._read_daemon_pid(),
        )

        self._input_buffer = Buffer(multiline=False)
        self._auto_scroll = True
        self._app: Optional[Application] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._connection_lost = False

    def _read_daemon_pid(self) -> int:
        """Read daemon PID from pid file, fall back to current process."""
        pid_file = getattr(self._config, "pid_file", None)
        if pid_file and os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    return int(f.read().strip())
            except (ValueError, OSError):
                pass
        return os.getpid()

    # ------------------------------------------------------------------
    # Socket communication
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        socket_path = str(self._config.socket_path)
        try:
            self._reader, self._writer = await asyncio.open_unix_connection(socket_path)
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            return False

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def send(self, data: dict) -> bool:
        """Send JSON-line to daemon. Returns False if connection is dead."""
        if not self._writer:
            return False
        try:
            self._writer.write((json.dumps(data) + "\n").encode("utf-8"))
            await self._writer.drain()
            return True
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._writer = None
            self._reader = None
            return False

    async def receive(self) -> Optional[dict]:
        if not self._reader:
            return None
        try:
            raw = await self._reader.readline()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8", errors="replace").strip())
        except (json.JSONDecodeError, ConnectionResetError):
            return None

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _get_width(self) -> int:
        if self._app and self._app.output:
            try:
                w = self._app.output.get_size().columns
                if isinstance(w, int):
                    return w
            except (AttributeError, TypeError):
                pass
        return 80

    def _get_header_text(self) -> ANSI:
        width = self._get_width()
        ansi_str = self._header_bar.render_ansi(width)
        return ANSI(ansi_str)

    def _get_conversation_text(self) -> ANSI:
        if not self._conv_fragments:
            return ANSI("")
        return ANSI("\n".join(self._conv_fragments))

    def _get_separator_text(self) -> ANSI:
        width = self._get_width()
        return ANSI(self._render_ansi("─" * width, STYLES["separator"]))

    def _get_scroll_hint_text(self) -> ANSI:
        return ANSI(self._render_ansi(
            "Use mouse scroll to navigate conversation history.",
            STYLES["muted"],
        ))

    def _get_prompt_prefix(self, lineno: int, wrap_count: int) -> list[tuple[str, str]]:
        return [("bold", "> ")]

    def _invalidate(self) -> None:
        if self._app:
            self._app.invalidate()

    # ------------------------------------------------------------------
    # Conversation output helpers
    # ------------------------------------------------------------------

    def _append_conv(self, text: str) -> None:
        self._conv_fragments.append(text)
        self._auto_scroll = True
        self._invalidate()

    def _render_ansi(self, text: str, style: str = "") -> str:
        """Render Rich-styled text to ANSI string."""
        buf = StringIO()
        console = Console(
            file=buf, force_terminal=True,
            width=self._get_width(), color_system="truecolor",
        )
        console.print(Text(text, style=style))
        return buf.getvalue().rstrip("\n")

    def _render_md_ansi(self, text: str) -> str:
        """Render markdown to ANSI string."""
        return ResponseRenderer.render_to_ansi(text, self._get_width()).rstrip("\n")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def _handle_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        # Record in history
        self._input_history.append(text)
        self._history_pos = -1

        # Separate from previous response with a divider
        if self._conv_fragments:
            sep = self._render_ansi("─" * (self._get_width() - 1), STYLES["separator"])
            self._append_conv(sep)
        # Show user input highlighted
        self._append_conv(self._render_ansi(f"> {text}", STYLES["prompt"]))

        # Local commands
        if text == "/quit":
            if self._app:
                self._app.exit()
            return

        if text == "/clear":
            self._conv_fragments.clear()
            self._invalidate()
            return

        # Send to daemon
        self._busy = True
        try:
            if text.startswith("/"):
                await self._send_and_display({"type": "command", "cmd": text})
            else:
                await self._send_and_display({"type": "message", "text": text})
        finally:
            self._busy = False

    async def _send_and_display(self, data: dict) -> None:
        """Send a message and display streamed responses."""
        if not await self.send(data):
            self._connection_lost = True
            self._append_conv(self._render_ansi(
                "⚠ Lost connection to daemon. Run: longxia status", STYLES["error"],
            ))
            if self._app:
                self._app.exit()
            return

        indicator: ProcessingIndicator | None = None
        indicator_line_idx: int | None = None
        if data.get("type") in ("message", "command"):
            indicator_line_idx = len(self._conv_fragments)
            self._append_conv("")  # placeholder for indicator

            def on_update(s: str) -> None:
                if indicator_line_idx is not None:
                    rendered = self._render_ansi(s, STYLES["processing"])
                    self._conv_fragments[indicator_line_idx] = rendered
                    self._invalidate()

            def on_done(s: str) -> None:
                if indicator_line_idx is not None:
                    self._conv_fragments[indicator_line_idx] = ""
                self._append_conv(self._render_ansi(s, STYLES["processing"]))

            indicator = ProcessingIndicator(on_update=on_update, on_done=on_done)
            indicator.start()

        first_output_received = False

        while True:
            msg = await self.receive()
            if msg is None:
                if indicator and not first_output_received:
                    await indicator.stop()
                self._connection_lost = True
                self._append_conv(self._render_ansi(
                    "⚠ Lost connection to daemon. Run: longxia status", STYLES["error"],
                ))
                if self._app:
                    self._app.exit()
                break

            msg_type = msg.get("type", "")
            output_type = msg.get("output_type", "")

            if msg_type == "output":
                if indicator and not first_output_received:
                    await indicator.stop()
                    first_output_received = True

                if output_type == "thinking":
                    content = msg.get("content", "")
                    if content:
                        self._append_conv(self._render_ansi(content, STYLES["thinking"]))

                elif output_type == "text":
                    content = msg.get("content", "")
                    if content:
                        self._append_conv(self._render_ansi(content, STYLES["response"]))

                elif output_type == "result":
                    content = msg.get("content", "")
                    if content:
                        self._append_conv(self._render_md_ansi(content))
                    if indicator:
                        if not first_output_received:
                            await indicator.stop()
                            first_output_received = True
                        indicator.emit_summary()
                    break

                elif output_type == "error":
                    content = msg.get("content", "")
                    self._append_conv(
                        self._render_ansi(f"Error: {content}", STYLES["error"])
                    )
                    break

            elif msg_type == "status":
                pass  # status info now in header

            elif msg_type == "pong":
                break

    # ------------------------------------------------------------------
    # Background refresh
    # ------------------------------------------------------------------

    async def _refresh_loop(self) -> None:
        """Refresh header stats every second."""
        try:
            while True:
                self._header_bar.refresh_stats()
                self._invalidate()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Build Application
    # ------------------------------------------------------------------

    def _build_app(self) -> Application:
        kb = KeyBindings()

        @kb.add("enter")
        def on_enter(event):
            if self._busy:
                return
            text = self._input_buffer.text
            self._input_buffer.reset()

            async def process():
                await self._handle_input(text)

            asyncio.ensure_future(process())

        @kb.add("c-c")
        def on_ctrl_c(event):
            event.app.exit()

        @kb.add("up")
        def on_up(event):
            if not self._input_history:
                return
            if self._history_pos == -1:
                self._saved_input = self._input_buffer.text
                self._history_pos = len(self._input_history) - 1
            elif self._history_pos > 0:
                self._history_pos -= 1
            self._input_buffer.text = self._input_history[self._history_pos]
            self._input_buffer.cursor_position = len(self._input_buffer.text)

        @kb.add("down")
        def on_down(event):
            if self._history_pos == -1:
                return
            if self._history_pos < len(self._input_history) - 1:
                self._history_pos += 1
                self._input_buffer.text = self._input_history[self._history_pos]
            else:
                self._history_pos = -1
                self._input_buffer.text = self._saved_input
            self._input_buffer.cursor_position = len(self._input_buffer.text)

        header_window = Window(
            content=FormattedTextControl(self._get_header_text),
            dont_extend_height=True,
        )

        scroll_hint = Window(
            content=FormattedTextControl(self._get_scroll_hint_text),
            height=1,
            dont_extend_height=True,
        )

        separator_input_top = Window(
            content=FormattedTextControl(self._get_separator_text),
            height=1,
        )

        input_window = Window(
            content=BufferControl(
                buffer=self._input_buffer,
                input_processors=[],
            ),
            height=1,
            get_line_prefix=self._get_prompt_prefix,
        )

        separator_input_bottom = Window(
            content=FormattedTextControl(self._get_separator_text),
            height=1,
        )

        self._conversation_window = _ScrollableWindow(
            content=FormattedTextControl(
                self._get_conversation_text,
                focusable=False,
            ),
            wrap_lines=True,
            auto_scroll_ref=lambda: self._auto_scroll,
            on_mouse_scroll=lambda: setattr(self, "_auto_scroll", False),
        )

        # Input fixed at top below header; conversation fills remaining
        # space below and scrolls independently.
        layout = Layout(
            HSplit([
                header_window,
                scroll_hint,
                separator_input_top,
                input_window,
                separator_input_bottom,
                self._conversation_window,
            ]),
            focused_element=input_window,
        )

        app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            mouse_support=True,
        )
        return app

    # ------------------------------------------------------------------
    # Pre-populate history
    # ------------------------------------------------------------------

    async def _load_history(self) -> None:
        """Request status and load session history turns."""
        await self.send({"type": "status_request"})
        await self.receive()  # consume status response

        try:
            history_msg = await asyncio.wait_for(self.receive(), timeout=0.5)
        except asyncio.TimeoutError:
            history_msg = None

        if history_msg and history_msg.get("type") == "history":
            turns = history_msg.get("turns", [])
            if turns:
                self._append_conv(self._render_ansi("--- Session history ---", STYLES["muted"]))
                for turn in turns:
                    ts = turn.get("timestamp", "")
                    self._append_conv(self._render_ansi(f"> ({ts}) {turn.get('user', '')}", STYLES["muted"]))
                    agent_text = turn.get("agent", "")
                    if agent_text:
                        self._append_conv(self._render_md_ansi(agent_text))
                self._append_conv(self._render_ansi("--- End of history ---", STYLES["muted"]))

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect, build app, run full-screen TUI."""
        connected = await self.connect()
        if not connected:
            print("Could not connect to agent. Is it running?")
            sys.exit(1)

        await self._load_history()

        self._app = self._build_app()
        self._refresh_task = asyncio.create_task(self._refresh_loop())

        try:
            await self._app.run_async()
        finally:
            if self._refresh_task:
                self._refresh_task.cancel()
                try:
                    await self._refresh_task
                except asyncio.CancelledError:
                    pass
            await self.disconnect()
            if self._connection_lost:
                print("TUI closed. Agent is not running. Run: longxia status")
            else:
                print("TUI closed. Agent still running.")


def run_tui(config) -> None:
    """Entry point for the TUI client."""
    tui = LongxiaClawTUI(config)
    try:
        asyncio.run(tui.run())
    except KeyboardInterrupt:
        pass
