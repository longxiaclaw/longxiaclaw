<p align="center">
  <img src="longxiaclaw/assets/longxiaclaw_icon.png" alt="LongxiaClaw" width="128">
</p>

<h1 align="center">LongxiaClaw</h1>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT">
  <a href="README_CN.md"><img src="https://img.shields.io/badge/文档-中文-red" alt="中文"></a>
</p>

**An OAuth-agnostic personal AI agent.**
**Designed for lightweight, LLM CLI-powered, skill-extensible operation.**

- **OAuth-agnostic design** — zero credential management; manually login to your CLI tool by yourself.
- **Lightweight deployment** — no compiled extensions, no Docker, only Python venv (installed once).
- **CLI-powered brain** — uses any LLM CLI (e.g., Qwen Code) as the inference engine via subprocess.
- **Configurable identity** — define your agent's personality and behavior.
- **File-based memory** — short-term session archives and long-term memory fully loaded at startup.
- **Extensible skills** — prompt-only skills always loaded into the LLM prompt; tool skills triggered by the daemon with results injected.
- **Built-in scheduler** — cron, interval, and one-shot task scheduling.
- **Daemon + TUI** — background agent that survives TUI disconnects.

---

## Why LongxiaClaw?

Every other personal AI agent manages your credentials in some way: injecting OAuth tokens into containers, storing API keys in config files with per-token billing, or proxying authentication flows. If the provider changes their terms, your agent breaks or your account gets flagged.

LongxiaClaw takes a different approach: **You login to your CLI tools manually by yourself. Your agent system does not store any credentials for you!** Your agent just runs something like `qwen [prompt]` as a subprocess. That's it. No API calls, no per-token cost, no credential storage. If you can run your CLI tool from a terminal, LongxiaClaw can use it.

The default CLI backend for now is [Qwen Code CLI](https://github.com/QwenLM/qwen-code) — open source under Apache 2.0 and free to use.

---

## What's New

**v0.1.0** — Initial release: daemon + TUI, file-based short-term and long-term memory, prompt-based and tool-based skill system, built-in task scheduler.

---

## Quick Start

### Prerequisites

- Python 3.10+
- A supported CLI backend installed and authenticated (e.g., [Qwen Code CLI](https://github.com/QwenLM/qwen-code))

### Install & Run

```bash
git clone https://github.com/longxiaclaw/longxiaclaw.git && cd longxiaclaw

python -m longxiaclaw install     # Creates venv, installs deps (first-time only)
python -m longxiaclaw activate    # Enters venv + starts agent daemon
longxia                           # Opens TUI — start chatting
/quit                             # Exits TUI (agent keeps running in background)
exit                              # Leaves the venv subshell
```

TUI in action:

```
─────────────────────────────────────────────────────────────────
 █      ███  █   █  ████ █   █ ███  ███    Time: 14:32:05
 █     █   █ ██  █ █      █ █   █  █   █   Version: 0.1.0
 █     █   █ █ █ █ █  ██   █    █  █████   Backend: qwen
 █     █   █ █  ██ █   █  █ █   █  █   █   Workspace: /path/to/ws
 █████  ███  █   █  ████ █   █ ███ █   █   CPU: 2.3%
                                           RAM: 0.01 / 36.0 GB
Try /help for all available commands.
Edit .env to configure system arguments.
Add new skills based on skills/_template.md and set enabled: true.
Run `longxia restart` to apply changes.
─────────────────────────────────────────────────────────────────
Use mouse scroll to navigate conversation history.
─────────────────────────────────────────────────────────────────
> _
─────────────────────────────────────────────────────────────────
> What can you do?

I can help you with various tasks:
  - Answer questions
  - Remember context across sessions
  - Perform Skills (e.g., Search the web)
  - Run scheduled tasks

Type /help to see all available commands.

Processed in 3s
```

---

## CLI Commands

| Command | Description |
|---|---|
| `python -m longxiaclaw install` | Create venv and install dependencies (first-time setup) |
| `python -m longxiaclaw update` | `git pull`; if changed, ensure venv and re-install deps |
| `python -m longxiaclaw uninstall` | Remove venv, runtime files, and optionally user data |
| `python -m longxiaclaw activate` | Enter the venv + auto-start daemon |
| `longxia start` | Start the agent daemon (background process) |
| `longxia stop` | Stop the agent daemon |
| `longxia restart` | Restart the agent daemon |
| `longxia status` | Check if the agent is running |
| `longxia health` | Check environment health (`--repair` to fix issues) |
| `longxia tui` | Open the TUI client |
| `longxia` | Shortcut for `longxia tui` |

---

## TUI Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/skills` | List active skills |
| `/new` | Start a fresh session (archives current conversation) |
| `/clear` | Clear screen |
| `/quit` | Exit TUI (agent keeps running) |

> Closing the TUI (`/quit` or Ctrl+C) does **not** stop the agent. Only `longxia stop` kills the daemon.

---

## Configuration

`.env` is created automatically from `.env.example` during `install`. Edit it to customize:

| Variable | Default | Description |
|---|---|---|
| `AGENT_WORKSPACE` | `./agent_workspace` | Sandboxed directory for agent-generated files (relative to project root) |
| `READ_GLOBAL` | `true` | Advisory: agent can read files outside workspace |
| `WRITE_GLOBAL` | `false` | Advisory: when off, agent writes stay within workspace |
| `ASSISTANT_NAME` | `LongxiaClaw` | Agent display name |
| `DEFAULT_BACKEND` | `qwen` | CLI backend to use |
| `BACKEND_BINARY` | `qwen` | Path to backend CLI binary |
| `BACKEND_MODEL` | *(empty)* | Model name (e.g., `qwen3-coder`) |
| `BACKEND_APPROVAL_MODE` | `yolo` | Approval mode for tool use |
| `BACKEND_TIMEOUT` | `300` | Backend timeout in seconds |
| `SCHEDULER_POLL_INTERVAL` | `60.0` | How often to check scheduled tasks |
| `MAX_CONTEXT_CHARS` | `50000` | Max characters in CONTEXT.md (long-term memory) |
| `ARCHIVE_RETENTION_HOURS` | `24` | Hours to keep session archives before pruning |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Memory System

LongxiaClaw uses a two-tier, file-based memory system with customizable identity.

**Identity** (`WAKEUP.md`) — The agent's system prompt, loaded once on startup or `/new`. Defines the agent's personality, capabilities, and behavioral guidelines. Edit this file to customize how your agent behaves.

**Short-term** (`agent_workspace/memory/sessions/`) — The current session keeps all turns in memory and persists them to `memory/sessions/current.md` after every response. If the daemon crashes, the session is recovered from this file on restart. On `/new` or graceful shutdown, `current.md` is renamed to a timestamped archive. On startup, all turns from the last 24 hours are fully loaded into the system prompt. Reconnecting the TUI displays the current session history.

**Long-term** (`agent_workspace/memory/CONTEXT.md`) — Permanent memory that survives across sessions. The agent aggressively saves facts, preferences, and lessons learned during conversation. When the user asks to forget something, the agent reactively removes matching entries. Fully loaded into the system prompt at startup and on `/new`. 50,000 character cap by default. Never auto-pruned.

```
Per-message prompt assembly:

  [WAKEUP.md + all archived turns + CONTEXT.md]  ← system context (loaded at startup)
  + [current session window]                     ← all turns this session
  + [prompt-only skill instructions]             ← always included (e.g., summarize, translate)
  + [tool skill results]                         ← if triggered (e.g., web search results)
  + [user message]                               ← user's prompt in the conversation line
```

---

## Skills

Skills are Markdown files with YAML frontmatter in the `skills/` directory. LongxiaClaw uses a **two-tier skill system**:

**Prompt-only skills** (no triggers) — Always loaded into the LLM prompt. The LLM decides when to apply them based on user intent. Examples: `summarize`, `translate`.

**Tool skills** (with triggers) — The daemon matches trigger phrases against the user's message, runs a daemon-side action (code in `tools/`), and injects the results into the prompt. Only results are injected, not the skill's markdown body. Examples: `web_search`.

```markdown
---
name: my_skill
description: What this skill does
version: "1.0"
# triggers:              # Omit for prompt-only; add for tool skills
#   - "trigger phrase"
enabled: true
author: your_name
---

# My Skill

## Instructions

- Step 1
- Step 2
```

Add new skills based on the template: `cp skills/_template.md skills/my_skill.md`. Set `enabled: true` and run `longxia restart` to apply. Use `/skills` to verify it loaded.

Files starting with `_` are ignored. Triggers are case-insensitive substring matches.

**Built-in skills:**
- **summarize** (prompt-only) — Summarize text into key points, conclusion, and action items
- **translate** (prompt-only) — Translate between Chinese and English with terminology notes
- **web_search** (tool) — Search the web via DuckDuckGo, no API key required

---

## Scheduler

LongxiaClaw includes a built-in task scheduler with three modes:

| Type | `schedule_value` | Behavior |
|---|---|---|
| `cron` | Cron expression (`0 9 * * *`) | Repeats on cron schedule |
| `interval` | Seconds (`3600`) | Repeats every N seconds |
| `once` | ISO timestamp | Runs once, then marks completed |

Tasks are stored in `agent_workspace/scheduler/state.yaml` and respect the single-agent design — scheduled tasks are skipped while the agent is busy processing a user message.

---

## Roadmap

LongxiaClaw is under active development. Planned directions include:

- **More LLM CLI backends** - free-to-use, flexible license (e.g., MIT license, Apache 2.0 License, etc).
- **Smarter memory** — automatic consolidation from short-term to long-term memory.
- **Richer skill system** — parameterized skills, skill chaining, skill market.
- **More channels** — Discord, Telegram, Slack.
- **Multi-agent orchestration** — explored on a separate branch, not replacing the lightweight single-agent core.

---

## License

LongxiaClaw is licensed under the MIT License. It invokes external CLI backends as subprocesses but does not install or distribute their source code. Each backend is a separate project with its own license (e.g., Qwen Code CLI is licensed under the Apache 2.0 License).
