<p align="center">
  <img src="longxiaclaw/assets/longxiaclaw_icon.png" alt="LongxiaClaw" width="128">
</p>

<h1 align="center">龙虾客（LongxiaClaw）</h1>

**一个认证无关的个人AI智能体。**
**基于轻量、大模型命令行工具驱动、技能可扩展的设计。**

- **认证无关设计** — 零凭证管理；用户自行登录大模型命令行工具（CLI Tools）。
- **轻量部署** — 无编译扩展、无 Docker，仅需 Python venv（一次安装）。
- **大模型命令行工具驱动大脑** — 通过子进程调用任意大模型命令行工具（如 Qwen Code）作为推理引擎。
- **可定制身份** — 可自定义智能体的个性和行为。
- **文件式记忆** — 短期会话归档和长期记忆在启动时全量加载。
- **可扩展技能** — 纯提示词技能始终加载到大模型提示中；工具技能由后台服务（daemon）触发并注入结果。
- **内置调度器** — 支持基于日期、间隔和一次性任务的调度模式。
- **后台服务（daemon） + 命令行图形界面（TUI）** — 后台智能体，命令行界面断开后仍持续运行。

---

## 为什么选择龙虾客？

几乎所有其他个人 AI 智能体都以某种方式管理你的凭证：将认证信息（OAuth）注入容器、在配置文件中存储按量计费的 API 密钥、或代理认证流程。一旦提供商修改条款，你的智能体就会崩溃或账号被标记。

龙虾客采取了不同的方式：**你自己手动登录大模型命令行（CLI）工具，智能体系统不为你存储任何凭证！** 智能体只是以子进程方式运行类似 `qwen [prompt]` 的命令。就这么简单。没有 API 调用、没有按量计费、没有凭证存储。只要你能在终端运行你的 CLI 工具，龙虾客就能使用它。

当前默认推荐的 CLI 工具是 [Qwen Code CLI](https://github.com/QwenLM/qwen-code) — 基于 Apache 2.0 开源协议，免费使用。

---

## 最新更新

**v0.1.0** — 首个发布版本：后台服务（daemon） + 命令行图形界面（TUI）、基于文件的短期和长期记忆、基于提示词和工具的技能系统、内置任务调度器。

---

## 快速开始

### 前置要求

- Python 3.10+
- 已安装并认证的 CLI 工具（如 [Qwen Code CLI](https://github.com/QwenLM/qwen-code)）

### 安装与运行

```bash
git clone https://github.com/longxiaclaw/longxiaclaw.git && cd longxiaclaw

python -m longxiaclaw install     # 创建 venv，安装依赖（仅首次需要）
python -m longxiaclaw activate    # 进入 venv + 启动智能体 daemon
longxia                           # 打开 TUI — 开始对话
/quit                             # 退出 TUI（智能体在后台继续运行）
exit                              # 离开 venv 子 shell
```

TUI 界面效果：

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

## 命令行命令

| 命令 | 说明 |
|---|---|
| `python -m longxiaclaw install` | 创建 venv 并安装依赖（首次安装） |
| `python -m longxiaclaw update` | `git pull`；如有变更，重新检查 venv 并安装依赖 |
| `python -m longxiaclaw uninstall` | 移除 venv、运行时文件，可选删除用户数据 |
| `python -m longxiaclaw activate` | 进入 venv + 自动启动 daemon |
| `longxia start` | 启动智能体 daemon（后台进程） |
| `longxia stop` | 停止智能体 daemon |
| `longxia restart` | 重启智能体 daemon |
| `longxia status` | 检查智能体是否在运行 |
| `longxia health` | 检查环境健康状态（`--repair` 修复问题） |
| `longxia tui` | 打开 TUI 客户端 |
| `longxia` | `longxia tui` 的快捷方式 |

---

## 命令行图形界面（TUI）命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示可用命令 |
| `/skills` | 列出已激活的技能 |
| `/new` | 开始新会话（归档当前对话） |
| `/clear` | 清屏 |
| `/quit` | 退出 TUI（智能体继续运行） |

> 关闭 TUI（`/quit` 或 Ctrl+C）**不会**停止智能体。只有 `longxia stop` 才会终止 daemon。

---

## 配置

`.env` 文件在 `install` 时自动从 `.env.example` 创建。编辑它来自定义配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AGENT_WORKSPACE` | `./agent_workspace` | 智能体生成文件的沙盒目录（相对于项目根目录） |
| `READ_GLOBAL` | `true` | 建议性：智能体可读取工作区外的文件 |
| `WRITE_GLOBAL` | `false` | 建议性：关闭时智能体写入限制在工作区内 |
| `ASSISTANT_NAME` | `LongxiaClaw` | 智能体显示名称 |
| `DEFAULT_BACKEND` | `qwen` | 使用的 CLI 后端 |
| `BACKEND_BINARY` | `qwen` | 后端 CLI 二进制文件路径 |
| `BACKEND_MODEL` | *（空）* | 模型名称（如 `qwen3-coder`） |
| `BACKEND_APPROVAL_MODE` | `yolo` | 工具使用的审批模式 |
| `BACKEND_TIMEOUT` | `300` | 后端超时时间（秒） |
| `SCHEDULER_POLL_INTERVAL` | `60.0` | 检查定时任务的间隔 |
| `MAX_CONTEXT_CHARS` | `50000` | CONTEXT.md 最大字符数（长期记忆） |
| `ARCHIVE_RETENTION_HOURS` | `24` | 会话归档保留时长（小时） |
| `LOG_LEVEL` | `INFO` | 日志级别（`DEBUG`、`INFO`、`WARNING`、`ERROR`） |

---

## 记忆系统

龙虾客使用两层文件式记忆系统，支持可定制身份。

**身份**（`WAKEUP.md`）— 智能体的系统提示词，在启动或 `/new` 时加载一次。定义智能体的个性、能力和行为准则。编辑此文件来自定义智能体的行为方式。

**短期记忆**（`agent_workspace/memory/sessions/`）— 当前会话将所有对话轮次保存在内存中，每次智能体回复后持久化到 `memory/sessions/current.md`。如果 daemon 崩溃，重启时从此文件恢复会话。执行 `/new` 或正常关闭时，`current.md` 被重命名为带时间戳的归档文件。启动时，最近 24 小时的所有对话轮次被全量加载到系统提示中。重连 TUI 会显示当前会话历史。

**长期记忆**（`agent_workspace/memory/CONTEXT.md`）— 跨会话持久化的永久记忆。智能体在对话中积极保存事实、偏好和经验教训。当用户要求遗忘某些内容时，智能体会删除匹配的条目。在启动和 `/new` 时全量加载到系统提示中。默认 50,000 字符上限。不会自动清理。

```
每条消息的提示词组装：

  [WAKEUP.md + 所有归档轮次 + CONTEXT.md]    ← 系统上下文（启动时加载）
  + [当前会话窗口]                            ← 本次会话的所有轮次
  + [纯提示词技能指令]                        ← 始终包含（如总结、翻译）
  + [工具技能结果]                            ← 触发时注入（如网页搜索结果）
  + [用户消息]                               ← 用户在对话中的输入
```

---

## 技能

技能是 `skills/` 目录下带有 YAML frontmatter 的 Markdown 文件。

龙虾客使用**两层技能系统**：

**纯提示词技能**（无触发器）— 始终加载到大模型提示中。大模型根据用户意图决定何时应用。示例：`summarize`、`translate`。

**工具技能**（有触发器）— daemon 将触发短语与用户消息进行匹配，运行 daemon 端的操作（代码位于 `tools/`），并将结果注入提示中。只注入结果，不注入技能的 Markdown 正文。示例：`web_search`。

```markdown
---
name: my_skill
description:             # 这个技能做什么
version: "1.0"
# triggers:              # 纯提示词技能省略；工具技能需要添加
#   - "trigger phrase"
enabled: true
author: your_name
---

# My Skill               # 技能描述

## Instructions          # 技能具体执行步骤

- Step 1
- Step 2
```

基于模板添加新技能：`cp skills/_template.md skills/my_skill.md`。设置 `enabled: true` 并运行 `longxia restart` 使其生效。使用 `/skills` 验证是否已加载。

以 `_` 开头的文件会被忽略。触发器为大小写不敏感的子串匹配。

**内置技能：**
- **summarize**（基于纯提示词）— 将文本总结为要点、结论和行动项
- **translate**（基于纯提示词）— 中英互译，附术语注释
- **web_search**（基于工具）— 通过 DuckDuckGo 搜索网页，无需 API 密钥

---

## 调度器

龙虾客内置任务调度器，支持三种模式：

| 类型 | 调度参数 | 行为 |
|---|---|---|
| `cron` | Cron 表达式（`0 9 * * *`） | 按日期计划重复执行 |
| `interval` | 秒数（`3600`） | 每 N 秒重复执行 |
| `once` | ISO 时间戳 | 执行一次后标记为完成 |

任务存储在 `agent_workspace/scheduler/state.yaml` 中，遵循单智能体设计 — 智能体正在处理用户消息时，定时任务会被跳过。

---

## 路线图

龙虾客正在积极开发中。计划方向包括：

- **更多大模型命令行工具** — 免费使用、灵活许可（如 MIT、Apache 2.0 等）。
- **更智能的记忆** — 从短期记忆到长期记忆的自动整合。
- **更丰富的技能系统** — 参数化技能、技能链式调用、技能市场。
- **更多通信渠道** — Discord、Telegram、Slack。
- **多智能体编排** — 在独立分支上探索，不替代轻量级单智能体核心。

---

## 许可证

龙虾客基于 MIT 许可证开源。它以子进程方式调用外部大模型命令行工具，但不安装或分发其源代码。每个工具是独立项目，拥有自己的许可证（如 Qwen Code CLI 基于 Apache 2.0 许可证）。
