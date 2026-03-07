"""Entry point, orchestrator, daemon, and CLI commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

VENV_DIR = ".longxia_venv"

logger = logging.getLogger("longxiaclaw")


# ---------------------------------------------------------------------------
# Venv Bootstrap
# ---------------------------------------------------------------------------

def _find_project_root() -> Path:
    """Find the project root. If inside .longxia_venv, derive from venv path."""
    venv_path = Path(sys.prefix).resolve()
    if venv_path.name == VENV_DIR:
        return venv_path.parent

    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


def _in_venv(project_root: Path) -> bool:
    """Check if currently running inside .longxia_venv."""
    venv_path = (project_root / VENV_DIR).resolve()
    return Path(sys.prefix).resolve() == venv_path


def _find_suitable_python() -> str:
    """Find a suitable Python 3 interpreter (prefer Homebrew over system)."""
    import shutil

    # Prefer explicit versioned Homebrew binaries (newest first)
    candidates = [
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3.10",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # Fall back to whatever python3 is on PATH, but skip Xcode's
    python3 = shutil.which("python3")
    if python3 and "Xcode" not in python3 and "CommandLineTools" not in python3:
        return python3

    # Last resort: sys.executable (may be Xcode's, but it's all we have)
    return sys.executable


def _ensure_venv(project_root: Path) -> Path:
    """Auto-create venv and install dependencies on first start."""
    venv_path = project_root / VENV_DIR
    venv_python = venv_path / "bin" / "python"
    marker = venv_path / ".installed"

    if not venv_python.exists():
        host_python = _find_suitable_python()
        print(f"Creating .longxia_venv (using {host_python})...")
        subprocess.run(
            [host_python, "-m", "venv", str(venv_path)],
            check=True,
        )

    if not marker.exists():
        print("Installing dependencies...")
        # Upgrade pip so editable installs from pyproject.toml work
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
        )
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-e", str(project_root)],
            check=True,
        )
        marker.write_text("ok")
        print("Done.")

    return venv_python


def _relaunch_in_venv(venv_python: Path) -> None:
    """Re-exec the current command under the venv python."""
    os.execv(str(venv_python), [str(venv_python), "-m", "longxiaclaw"] + sys.argv[1:])


# ---------------------------------------------------------------------------
# Agent Daemon
# ---------------------------------------------------------------------------

class LongxiaClawDaemon:
    """Agent daemon. Runs as background process.
    One agent at a time, one session at a time. Strictly sequential."""

    def __init__(self, config):
        from .system import LogManager
        from .memory import MemoryManager
        from .scheduler import StateManager
        from .skills.skill_manager import SkillManager
        from .backends.qwen_cli import QwenCodeBackend

        self._config = config
        self._agent_busy = False
        self._running = False
        self._server = None

        # Subsystems
        self._log_manager = LogManager(config.logs_dir)
        self._logger = self._log_manager.setup(config.log_level)
        self._state_manager = StateManager(config.state_file)
        self._memory = MemoryManager(
            config.memory_dir,
            max_context_chars=config.max_context_chars,
            archive_retention_hours=config.archive_retention_hours,
        )
        self._skill_registry = SkillManager(config.skills_dir)

        # Backend
        self._backend = QwenCodeBackend(
            binary=config.backend_binary,
            model=config.backend_model,
            approval_mode=config.backend_approval_mode,
            timeout=config.backend_timeout,
        )

        # Identity context
        self._system_context = ""

        # Patterns for structured memory tags
        self._MEMORY_SAVE_RE = re.compile(
            r"<memory_save>(.*?)</memory_save>", re.DOTALL
        )
        self._MEMORY_FORGET_RE = re.compile(
            r"<memory_forget>(.*?)</memory_forget>", re.DOTALL
        )

    async def run(self) -> None:
        """Daemon main loop."""
        self._running = True

        # 1. Ensure directories
        self._config.ensure_dirs()

        # 2. Rotate old logs
        self._log_manager.rotate_logs()
        self._logger.info("Old logs rotated")

        # 3. Write PID file
        self._config.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self._logger.info("PID file written: %s (PID %d)", self._config.pid_file, os.getpid())

        # 4. Crash recovery: restore current session from current.md
        recovered = self._memory.load_current_session()
        if recovered:
            self._logger.info("Recovered %d turns from current.md", recovered)

        # 5. Load identity + memory into system context
        self._system_context = self._load_wakeup()
        prev_sessions = self._memory.load_previous_sessions()
        if prev_sessions:
            self._system_context += f"\n\n# Previous Sessions (last 24h)\n{prev_sessions}"
            self._logger.info("Loaded previous sessions into system context")
        context = self._memory.load_context()
        if context:
            self._system_context += f"\n\n# Long-term Memory\n{context}"
            self._logger.info("Loaded long-term memory (%d chars)", len(context))
        pruned = self._memory.prune_old_sessions()
        if pruned:
            self._logger.info("Pruned %d old session archives", pruned)

        # 6. Log startup
        self._logger.info(
            "Daemon starting. Skills: %d",
            self._skill_registry.count,
        )

        # 7. Check backend
        if not self._backend.is_supported_binary():
            supported = ", ".join(sorted(self._backend.SUPPORTED_BINARIES))
            self._logger.warning(
                "Unsupported BACKEND_BINARY '%s'. Supported: %s",
                self._config.backend_binary, supported,
            )
        available = await self._backend.check_available()
        if available:
            version = await self._backend.get_version()
            self._logger.info("Backend available: %s", version)
        else:
            self._logger.warning(
                "Backend binary not found: %s. Install it and ensure it is on PATH.",
                self._config.backend_binary,
            )

        # 8. Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self._shutdown()))

        # 9. Start Unix socket server
        socket_path = str(self._config.socket_path)
        # Remove stale socket
        if os.path.exists(socket_path):
            os.unlink(socket_path)
            self._logger.info("Removed stale socket: %s", socket_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=socket_path,
        )
        self._logger.info("Listening on %s", socket_path)

        # 10. Start scheduler
        from .scheduler import TaskScheduler
        self._scheduler = TaskScheduler(
            state_manager=self._state_manager,
            run_task_fn=self._run_scheduled_task,
            is_busy_fn=lambda: self._agent_busy,
            poll_interval=self._config.scheduler_poll_interval,
        )
        _scheduler_task = asyncio.create_task(self._scheduler.start())  # noqa: F841
        self._logger.info("Scheduler started (poll interval: %.1fs)", self._config.scheduler_poll_interval)

        # 11. Wait until shutdown
        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            self._scheduler.stop()

    def _load_wakeup(self) -> str:
        """Read WAKEUP.md if it exists."""
        wakeup_path = self._config.project_root / "WAKEUP.md"
        if wakeup_path.exists():
            content = wakeup_path.read_text(encoding="utf-8")
            self._logger.info("WAKEUP.md loaded (%d chars)", len(content))
            return content
        self._logger.warning("WAKEUP.md not found at %s", wakeup_path)
        return ""

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single TUI connection. Read JSON-lines, dispatch."""
        self._logger.info("TUI client connected")
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self._logger.warning("Invalid JSON received from TUI: %s", line[:200])
                    await self._send(writer, {"type": "output", "output_type": "error", "content": "Invalid JSON"})
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await self._send(writer, {"type": "pong"})

                elif msg_type == "message":
                    text = msg.get("text", "")
                    if text:
                        await self._process_message(text, writer)

                elif msg_type == "command":
                    cmd = msg.get("cmd", "")
                    if cmd:
                        await self._handle_command(cmd, writer)

                elif msg_type == "status_request":
                    self._logger.info("Status request from TUI")
                    await self._send(writer, {
                        "type": "status",
                        "agent_busy": self._agent_busy,
                        "skills_count": self._skill_registry.count,
                    })
                    # Send session history so reconnecting TUI can display it
                    if self._memory._window:
                        turns = [
                            {
                                "user": t["user"],
                                "agent": t["agent"],
                                "timestamp": t["timestamp"],
                            }
                            for t in self._memory._window
                        ]
                        await self._send(writer, {
                            "type": "history",
                            "turns": turns,
                        })
                        self._logger.info("Sent %d history turns to reconnecting TUI", len(turns))

                else:
                    self._logger.warning("Unknown message type from TUI: %s", msg_type)

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError) as e:
            self._logger.warning("TUI connection lost: %s", type(e).__name__)
        finally:
            self._logger.info("TUI client disconnected")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_message(self, text: str, writer: asyncio.StreamWriter) -> None:
        """Handle a user message from TUI."""
        if self._agent_busy:
            self._logger.warning("Message rejected (agent busy): %s", text[:200])
            await self._send(writer, {
                "type": "output", "output_type": "error",
                "content": "Agent is busy. Please wait.",
            })
            return

        self._agent_busy = True
        start_time = time.monotonic()
        self._logger.info("User message received: %s", text[:200])

        try:
            from .backends.base import AgentInput, AgentOutput
            from .tools.web_search import DuckDuckGoSearch, format_search_results

            # 1. Check tool skill triggers
            triggered_skills = self._skill_registry.get_triggered_skills(text)
            if triggered_skills:
                self._logger.info("Tool skills triggered: %s", [s.name for s in triggered_skills])

            # 2. Run tool-side actions for triggered skills
            tool_context = ""
            for skill in triggered_skills:
                if skill.name == "web_search":
                    try:
                        search_provider = DuckDuckGoSearch()
                        results = await search_provider.search(text, max_results=5)
                        tool_context = format_search_results(results)
                        self._logger.info("Web search completed: %d results", len(results))
                    except Exception as e:
                        self._logger.error("Web search failed: %s", e)
                        tool_context = "<web_search_results><error>Search failed</error></web_search_results>"
                    break

            # 3. Assemble prompt
            parts = []
            if self._system_context:
                parts.append(self._system_context)

            window_text = self._memory.get_window_text()
            if window_text:
                parts.append(f"# Recent conversation\n{window_text}")

            # Prompt-only skills (no triggers) — always included
            prompt_skills = self._skill_registry.get_prompt_skills()
            if prompt_skills:
                ctx = self._skill_registry.format_skills_context(prompt_skills)
                parts.append(f"# Available Skills\n{ctx}")

            # Triggered tool skills — only inject results
            if tool_context:
                parts.append(tool_context)

            parts.append(text)
            assembled_prompt = "\n\n".join(parts)

            # 5. Validate backend before running
            if not self._backend.is_supported_binary():
                supported = ", ".join(sorted(self._backend.SUPPORTED_BINARIES))
                error_msg = (
                    f"Unsupported BACKEND_BINARY '{self._config.backend_binary}'. "
                    f"Supported: {supported}. Update BACKEND_BINARY in .env and run: longxia restart"
                )
                await self._send(writer, {
                    "type": "output", "output_type": "error",
                    "content": error_msg,
                })
                self._memory.push_turn(text, f"[Error: {error_msg}]")
                return

            # 6. Run backend (stateless — no CLI session resume)
            self._logger.info("Prompt assembled (%d chars), invoking backend (timeout: %ds)",
                              len(assembled_prompt), self._config.backend_timeout)
            agent_input = AgentInput(
                prompt=assembled_prompt,
                working_dir=str(self._config.agent_workspace_dir),
                timeout=self._config.backend_timeout,
            )
            self._log_manager.log_prompt(assembled_prompt)

            collected_text = []

            async def on_output(output: AgentOutput):
                if output.type == "text":
                    collected_text.append(output.content)
                    await self._send(writer, {
                        "type": "output", "output_type": "text",
                        "content": output.content,
                    })
                elif output.type == "thinking":
                    await self._send(writer, {
                        "type": "output", "output_type": "thinking",
                        "content": output.content,
                    })

            result = await self._backend.run(agent_input, on_output=on_output)
            self._log_manager.log_response(result.result)
            self._logger.info("Backend returned: status=%s, result_len=%d, duration=%dms",
                              result.status, len(result.result), result.duration_ms)

            if result.status == "error":
                self._logger.error("Backend returned error: %s", result.result[:500])
                elapsed = int((time.monotonic() - start_time) * 1000)
                await self._send(writer, {
                    "type": "output", "output_type": "error",
                    "content": f"{result.result}\nRun: longxia health --repair",
                })
                self._memory.push_turn(text, f"[Error: {result.result}]")
                self._log_manager.log_action("message_processed", {
                    "duration_ms": elapsed,
                    "skills_triggered": [s.name for s in triggered_skills],
                    "status": result.status,
                })
                return

            # 5b. Process memory tags — daemon-enforced writes/deletes
            cleaned_result, save_entries, forget_queries = self._process_memory_tags(result.result)
            for entry in save_entries:
                save_msg = self._memory.remember(entry)
                self._logger.info("Memory save: %s", save_msg)
            for query in forget_queries:
                forget_msg = self._memory.forget_by_content(query)
                self._logger.info("Memory forget: %s", forget_msg)
            if save_entries or forget_queries:
                # Reload long-term memory into system context so next turn sees it
                self._system_context = self._load_wakeup()
                prev_sessions = self._memory.load_previous_sessions()
                if prev_sessions:
                    self._system_context += f"\n\n# Previous Sessions (last 24h)\n{prev_sessions}"
                context = self._memory.load_context()
                if context:
                    self._system_context += f"\n\n# Long-term Memory\n{context}"
                self._logger.info("System context reloaded after memory update")

            elapsed = int((time.monotonic() - start_time) * 1000)

            # 6. Send final result (tags stripped)
            await self._send(writer, {
                "type": "output", "output_type": "result",
                "content": cleaned_result,
                "duration_ms": elapsed,
            })

            # 7. Update memory (store cleaned version without tags)
            self._memory.push_turn(text, cleaned_result)
            self._logger.info("Turn saved to session memory")

            self._log_manager.log_action("message_processed", {
                "duration_ms": elapsed,
                "skills_triggered": [s.name for s in triggered_skills],
                "status": result.status,
            })

        except Exception as e:
            self._logger.error("Error processing message: %s", e, exc_info=True)
            error_msg = f"Error: {str(e)}"
            await self._send(writer, {
                "type": "output", "output_type": "error",
                "content": error_msg,
            })
            self._memory.push_turn(text, f"[{error_msg}]")
        finally:
            self._agent_busy = False

    def _process_memory_tags(self, text: str) -> tuple[str, list[str], list[str]]:
        """Extract <memory_save> and <memory_forget> tags.

        Returns (cleaned_text, save_entries, forget_queries).
        The daemon calls MemoryManager for each, guaranteeing the
        write/delete happens regardless of backend behavior.
        """
        save_entries = []
        for match in self._MEMORY_SAVE_RE.finditer(text):
            content = match.group(1).strip()
            if content:
                save_entries.append(content)

        forget_queries = []
        for match in self._MEMORY_FORGET_RE.finditer(text):
            content = match.group(1).strip()
            if content:
                forget_queries.append(content)

        cleaned = self._MEMORY_SAVE_RE.sub("", text)
        cleaned = self._MEMORY_FORGET_RE.sub("", cleaned).strip()
        return cleaned, save_entries, forget_queries

    async def _handle_command(self, cmd: str, writer: asyncio.StreamWriter) -> None:
        """Handle /commands from TUI."""
        self._logger.info("Command received: %s", cmd)
        if cmd == "/new":
            self._memory.start_new_session()
            self._logger.info("Session archived and reset")
            self._system_context = self._load_wakeup()
            prev_sessions = self._memory.load_previous_sessions()
            if prev_sessions:
                self._system_context += f"\n\n# Previous Sessions (last 24h)\n{prev_sessions}"
            context = self._memory.load_context()
            if context:
                self._system_context += f"\n\n# Long-term Memory\n{context}"
            self._logger.info("System context reloaded for new session")
            pruned = self._memory.prune_old_sessions()
            if pruned:
                self._logger.info("Pruned %d old session archives", pruned)
            await self._send(writer, {
                "type": "output", "output_type": "result",
                "content": "New session started. Previous session archived.",
            })

        elif cmd == "/skills":
            skills = self._skill_registry.get_active_skills()
            if skills:
                lines = [
                    "**Active skills:**\n",
                ]
                for s in skills:
                    kind = "tool" if s.is_tool_skill else "prompt"
                    lines.append(f"- **{s.name}** ({kind}) — {s.description}")
                lines.append(
                    "\n*Tip: Copy skills/_template.md to create new skills. Set enabled: true. Restart the daemon to load them.*"
                )
                text = "\n".join(lines)
            else:
                text = (
                    "No active skills.\n\n"
                    "*Tip: Copy skills/_template.md to create new skills. Set enabled: true. Restart the daemon to load them.*"
                )
            await self._send(writer, {
                "type": "output", "output_type": "result",
                "content": text,
            })

        elif cmd == "/help":
            help_text = (
                "**Built-in commands:**\n\n"
                "- `/help` — Show this help\n"
                "- `/skills` — List active skills\n"
                "- `/new` — Archive session, reload identity, start fresh\n"
                "- `/clear` — Clear screen\n"
                "- `/quit` — Exit TUI (agent keeps running)\n"
            )
            await self._send(writer, {
                "type": "output", "output_type": "result",
                "content": help_text,
            })

        else:
            self._logger.warning("Unknown command: %s", cmd)
            await self._send(writer, {
                "type": "output", "output_type": "error",
                "content": f"Unknown command: {cmd}",
            })

    async def _run_scheduled_task(self, task) -> str:
        """Run a scheduled task through the backend."""
        from .backends.base import AgentInput

        agent_input = AgentInput(
            prompt=task.prompt,
            working_dir=str(self._config.agent_workspace_dir),
            timeout=self._config.backend_timeout,
        )
        self._log_manager.log_prompt(task.prompt)
        result = await self._backend.run(agent_input)
        self._log_manager.log_response(result.result)
        if result.status == "error":
            self._logger.error("Scheduled task backend error: %s", result.result[:500])
        return result.result

    async def _shutdown(self) -> None:
        """Graceful shutdown."""
        self._logger.info("Shutting down...")
        self._running = False

        # Archive session
        archive_path = self._memory.archive_session()
        if archive_path:
            self._logger.info("Session archived to %s", archive_path)

        # Save state
        state = self._state_manager.load()
        self._state_manager.save(state)
        self._logger.info("State saved")

        # Stop server
        if self._server:
            self._server.close()
            self._logger.info("Server closed")

        # Clean up files
        try:
            if self._config.pid_file.exists():
                self._config.pid_file.unlink()
                self._logger.info("PID file removed")
        except OSError as e:
            self._logger.warning("Failed to remove PID file: %s", e)
        try:
            if self._config.socket_path.exists():
                self._config.socket_path.unlink()
                self._logger.info("Socket file removed")
        except OSError as e:
            self._logger.warning("Failed to remove socket file: %s", e)

        # Flush and stop background log writer
        self._log_manager.shutdown()

        self._logger.info("Shutdown complete.")

    async def _send(self, writer: asyncio.StreamWriter, data: dict) -> None:
        """Send a JSON-line to the TUI client."""
        try:
            writer.write((json.dumps(data) + "\n").encode("utf-8"))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._logger.debug("Send failed (TUI disconnected), msg type: %s", data.get("type", "unknown"))


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def _cmd_start(project_root: Path) -> None:
    """Start agent daemon."""
    from .system import Config

    config = Config.from_env()
    config.project_root = project_root
    config.ensure_dirs()

    # Check if already running
    pid_file = config.pid_file
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process is alive
            print(f"Agent already running (PID {pid}). Use 'longxia stop' first.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Stale PID file
            pid_file.unlink(missing_ok=True)

    # Fork and daemonize
    pid = os.fork()
    if pid > 0:
        # Parent — wait briefly, then report
        time.sleep(0.5)
        if pid_file.exists():
            print(f"Agent started (PID {pid}).")
        else:
            print("Agent started.")
        sys.exit(0)

    # Child — become daemon
    os.setsid()

    # Second fork to fully detach
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Redirect stdio
    sys.stdin.close()
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull

    # Run daemon
    daemon = LongxiaClawDaemon(config)
    try:
        asyncio.run(daemon.run())
    except Exception as e:
        try:
            daemon._logger.critical("Daemon crashed: %s", e, exc_info=True)
        except Exception:
            pass
    finally:
        os._exit(0)


def _cmd_stop(project_root: Path) -> None:
    """Stop agent daemon."""
    from .system import Config

    config = Config.from_env()
    config.project_root = project_root

    pid_file = config.pid_file
    if not pid_file.exists():
        print("Agent not running.")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        print("Invalid PID file. Cleaning up.")
        pid_file.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}. Waiting for shutdown...")

        # Wait for process to exit
        for _ in range(30):  # 3 second timeout
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                print("Agent stopped.")
                return
        print("Agent did not stop in time. You may need to kill it manually.")
    except ProcessLookupError:
        print("Agent process not found. Cleaning up PID file.")
        pid_file.unlink(missing_ok=True)


def _cmd_uninstall(project_root: Path) -> None:
    """Remove venv, runtime files, and optionally user data.

    Uses only stdlib so it works outside the venv (no third-party imports).
    """
    # 1. Stop the daemon if running (inline, no Config import)
    pid_file = project_root / "daemon" / "longxiaclaw.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to PID {pid}. Waiting for shutdown...")
            for _ in range(30):  # 3 second timeout
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    print("Agent stopped.")
                    break
            else:
                print("Agent did not stop in time. You may need to kill it manually.")
        except (ProcessLookupError, ValueError):
            print("Agent process not found. Cleaning up PID file.")
        pid_file.unlink(missing_ok=True)

    # 2. Remove generated directories without prompting
    removed: list[str] = []
    generated_dirs = [
        (VENV_DIR, "venv"),
        ("daemon", "daemon state"),
        ("logs", "log files"),
        ("agent_workspace", "agent workspace"),
        ("dist", "distribution packages"),
        ("build", "build artifacts"),
        (".pytest_cache", "pytest cache"),
        (".mypy_cache", "mypy cache"),
    ]
    for dirname, label in generated_dirs:
        dirpath = project_root / dirname
        if dirpath.is_dir():
            subprocess.run(["rm", "-rf", str(dirpath)])
            removed.append(f"  {dirname}/ ({label})")

    # 2b. Remove generated files/dirs matching glob patterns
    for pycache in project_root.rglob("__pycache__"):
        if pycache.is_dir():
            subprocess.run(["rm", "-rf", str(pycache)])
            removed.append(f"  {pycache.relative_to(project_root)}/ (bytecode cache)")
    for egg_info in project_root.glob("*.egg-info"):
        if egg_info.is_dir():
            subprocess.run(["rm", "-rf", str(egg_info)])
            removed.append(f"  {egg_info.name}/ (egg info)")
    for pyc in project_root.rglob("*.pyc"):
        if pyc.is_file():
            pyc.unlink()
            removed.append(f"  {pyc.relative_to(project_root)} (bytecode)")
    for ds in project_root.rglob(".DS_Store"):
        if ds.is_file():
            ds.unlink()
            removed.append(f"  {ds.relative_to(project_root)} (macOS metadata)")

    # 3. Prompt for user data files
    user_files = [
        (".env", "configuration"),
    ]
    for filename, label in user_files:
        filepath = project_root / filename
        if filepath.exists():
            answer = input(f"Remove {filename} ({label})? [y/N] ").strip().lower()
            if answer == "y":
                filepath.unlink()
                removed.append(f"  {filename} ({label})")

    # 4. Print summary
    print()
    if removed:
        print("Removed:")
        for entry in removed:
            print(entry)
    else:
        print("Nothing to remove.")


def _cmd_restart(project_root: Path) -> None:
    """Stop agent (if running) then start it again."""
    from .system import Config

    config = Config.from_env()
    config.project_root = project_root

    pid_file = config.pid_file
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if alive
            # Process is running — stop it
            os.kill(pid, signal.SIGTERM)
            print(f"Stopping agent (PID {pid})...")
            for _ in range(30):  # 3 second timeout
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            else:
                print("Agent did not stop in time. Aborting restart.")
                sys.exit(1)
            print("Agent stopped.")
        except (ProcessLookupError, ValueError):
            # Stale PID file
            pid_file.unlink(missing_ok=True)

    _cmd_start(project_root)


def _cmd_status(project_root: Path) -> None:
    """Check agent status."""
    from .system import Config

    config = Config.from_env()
    config.project_root = project_root

    pid_file = config.pid_file
    if not pid_file.exists():
        print("Agent not running.")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        print(f"Agent running (PID {pid})")
    except (ProcessLookupError, ValueError):
        print("Agent not running (stale PID file).")
        pid_file.unlink(missing_ok=True)


def _cmd_tui(project_root: Path) -> None:
    """Open TUI to chat with running agent."""
    from .system import Config

    config = Config.from_env()
    config.project_root = project_root

    # Check if agent running
    pid_file = config.pid_file
    socket_path = config.socket_path

    if not pid_file.exists():
        print("Agent not running. Use: longxia start")
        sys.exit(1)

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        print("Agent not running (stale PID file). Use: longxia start")
        pid_file.unlink(missing_ok=True)
        sys.exit(1)

    if not socket_path.exists():
        print("Agent socket not found. Try restarting: longxia stop && longxia start")
        sys.exit(1)

    # Launch TUI
    from .tui.app import run_tui
    run_tui(config)


def _cmd_install(project_root: Path) -> None:
    """First-time setup: create venv, install dependencies, copy .env."""
    _ensure_venv(project_root)

    # Copy .env.example → .env if .env doesn't exist yet
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"
    if not env_file.exists() and env_example.exists():
        import shutil
        shutil.copy2(env_example, env_file)
        print("Created .env from .env.example (edit to customize).")

    print()
    print("Venv ready. Next, activate:")
    print()
    print("  python -m longxiaclaw activate")


def _cmd_update(project_root: Path) -> None:
    """Pull latest changes and re-install dependencies if needed."""
    # 1. Git pull
    result = subprocess.run(
        ["git", "pull"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip())
        sys.exit(1)

    if "Already up to date." in result.stdout:
        return

    # 2. Ensure venv exists (recreate if missing)
    venv_python = _ensure_venv(project_root)

    # 3. Upgrade pip and re-install dependencies
    print("Upgrading pip...")
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )
    print("Re-installing dependencies...")
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-e", str(project_root)],
        check=True,
    )
    # Refresh marker
    (project_root / VENV_DIR / ".installed").write_text("ok")
    print("Done. Dependencies are up to date.")


def _cmd_health(project_root: Path) -> None:
    """Run health checks (and optionally repair)."""
    from .system import run_health

    repair = "--repair" in sys.argv[2:]
    code = run_health(project_root, repair=repair)
    sys.exit(code)


def _cmd_activate(project_root: Path) -> None:
    """Spawn an interactive subshell with the venv activated."""
    venv_path = project_root / VENV_DIR
    venv_bin = venv_path / "bin"

    if not venv_bin.exists():
        print(f"Venv not found at {venv_path}")
        print("Run 'python -m longxiaclaw install' first.")
        sys.exit(1)

    # Guard against nested activation
    if _in_venv(project_root) or os.environ.get("LONGXIA_ACTIVATED") == "1":
        print("Already inside the longxia venv.")
        return

    shell = os.environ.get("SHELL", "/bin/bash")

    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(venv_path)
    # Prepend venv bin to PATH
    env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    env["VIRTUAL_ENV_PROMPT"] = "(longxia) "
    # Mark that we've activated so repeated calls don't nest
    env["LONGXIA_ACTIVATED"] = "1"

    # Write a temp rcfile that sources the user's rc then auto-starts longxia
    import tempfile

    shell_name = os.path.basename(shell)

    if shell_name == "zsh":
        user_rc = os.path.expanduser("~/.zshrc")
        rc_content = (
            f'[ -f "{user_rc}" ] && source "{user_rc}"\n'
            f'export PATH="{venv_bin}:$PATH"\n'
            f'longxia start\n'
        )
        rc_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".zshrc", delete=False, prefix="longxia_"
        )
        rc_file.write(rc_content)
        rc_file.close()
        env["ZDOTDIR"] = os.path.dirname(rc_file.name)
        # zsh reads $ZDOTDIR/.zshrc, so rename the file
        target = os.path.join(os.path.dirname(rc_file.name), ".zshrc")
        os.rename(rc_file.name, target)
        print("Activating longxia venv... Type 'exit' to leave.")
        os.execve(shell, [shell, "-i"], env)
    elif shell_name == "bash":
        user_rc = os.path.expanduser("~/.bashrc")
        rc_content = (
            f'[ -f "{user_rc}" ] && source "{user_rc}"\n'
            f'export PATH="{venv_bin}:$PATH"\n'
            f'longxia start\n'
        )
        rc_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".bashrc", delete=False, prefix="longxia_"
        )
        rc_file.write(rc_content)
        rc_file.close()
        print("Activating longxia venv... Type 'exit' to leave.")
        os.execve(shell, [shell, "-i", "--rcfile", rc_file.name], env)
    else:
        # Fallback: launch shell without auto-start
        print("Activating longxia venv... Type 'exit' to leave.")
        print("Run 'longxia start' to start the agent.")
        os.execve(shell, [shell, "-i"], env)


def cli():
    """Entry point. Dispatches to subcommands."""
    project_root = _find_project_root()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tui"

    # install, update, uninstall, and activate work outside the venv
    if cmd == "install":
        _cmd_install(project_root)
    elif cmd == "update":
        _cmd_update(project_root)
    elif cmd == "uninstall":
        _cmd_uninstall(project_root)
    elif cmd == "activate":
        _cmd_activate(project_root)
    elif cmd == "help":
        print("Usage: longxia [install|update|uninstall|activate|start|stop|restart|status|health|tui|help]")
        print()
        print("Commands:")
        print("  install   Create venv and install dependencies (first-time setup)")
        print("  update    Pull latest changes and re-install dependencies")
        print("  uninstall Remove venv, runtime files, and optionally user data")
        print("  activate  Enter the venv (spawns a subshell)")
        print("  start     Start the agent daemon")
        print("  stop      Stop the agent daemon")
        print("  restart   Stop (if running) and start the agent daemon")
        print("  status    Check if agent is running")
        print("  health    Check environment health (--repair to fix issues)")
        print("  tui       Open TUI to chat (default)")
        print("  help      Show this help")
    elif cmd in ("start", "stop", "restart", "status", "tui", "health"):
        if not _in_venv(project_root):
            print("Not inside the longxia venv.")
            print("Run these commands first:")
            print()
            print("  python -m longxiaclaw install")
            print("  python -m longxiaclaw activate")
            sys.exit(1)

        if cmd == "start":
            _cmd_start(project_root)
        elif cmd == "stop":
            _cmd_stop(project_root)
        elif cmd == "restart":
            _cmd_restart(project_root)
        elif cmd == "status":
            _cmd_status(project_root)
        elif cmd == "tui":
            _cmd_tui(project_root)
        elif cmd == "health":
            _cmd_health(project_root)
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: longxia [install|update|uninstall|activate|start|stop|restart|status|health|tui|help]")
        sys.exit(1)
