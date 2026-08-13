# OpenJiuWen iCode

> 终端交互式 Agentic 编程助手（产品名：**OpenJiuWen iCode**；CLI 入口仍为 `openjiuwen`）

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-64%20passed-brightgreen.svg)](../../tests/cli/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

## 项目简介

**OpenJiuWen iCode** 是基于 [openJiuwen agent-core SDK](https://gitcode.com/openJiuwen/agent-core) 构建的终端 AI 编程助手。在终端中启动 `openjiuwen`（或 `openjiuwen tui`），即可进入智能编程对话环境：

- 用自然语言描述需求，Agent 自动调用工具完成任务
- 支持多轮对话，Agent 保持上下文理解
- 支持流式输出，逐字渲染到终端
- 支持 OPENJIUWEN.md 项目记忆文件
- 支持交互式（TUI / REPL）和非交互式两种模式

```
┌─── OpenJiuWen iCode v0.1.0 ────────────────────────────────────────────────┐
│                                │ Tips for getting started                   │
│         Welcome to             │ Create an OPENJIUWEN.md for project rules  │
│      OpenJiuWen iCode          │ ──────────────────────────────────────     │
│           ████                 │ Commands                                   │
│          ██  ██                │   /help      Show available commands       │
│           ████                 │   /status    Token usage & model info      │
│                                │   /exit      Exit OpenJiuWen iCode         │
│   GLM-5 (OpenAI)              │   ! <cmd>    Run a shell command           │
│   ~/my-project                │                                            │
╰────────────────────────────────────────────────────────────────────────────╯
```

## 安装

### 方式 1: 一键安装（推荐）

自动安装 `openjiuwen[cli]` 并配置全局 `openjiuwen` 命令：

```bash
# Linux / macOS
curl -fsSL https://gitcode.com/michaelling/iCode/raw/main/openjiuwen_icode/install.sh | bash

# Windows（以管理员权限运行 PowerShell）
irm https://gitcode.com/michaelling/iCode/raw/main/openjiuwen_icode/install.ps1 | iex
```

### 方式 2: pip install

```bash
# 从 PyPI 安装（产品包；依赖 openjiuwen SDK）
pip install -U openjiuwen-icode

# 或从源码安装（开发模式；需与 agent-core 同级）
git clone https://gitcode.com/michaelling/iCode.git
git clone https://gitcode.com/openJiuwen/agent-core.git
cd iCode
uv sync   # 或: pip install -e ../agent-core && pip install -e .

# 验证安装
openjiuwen --version
# 或
icode --version
```

### 方式 3: 直接运行（无需全局安装）

```bash
# 在 iCode 项目根目录（已 uv sync）
uv run python -m openjiuwen_icode --version
uv run python -m openjiuwen_icode chat
uv run openjiuwen run "What is 2+2?"
```

### 系统要求

| 要求 | 说明 |
|------|------|
| **Python** | 3.11+ (推荐 3.11.4) |
| **操作系统** | Linux / macOS / Windows 10+ |
| **终端** | 支持 ANSI 颜色（Windows 推荐使用 Windows Terminal） |

## 配置

配置从 `~/.icode/settings.json` 加载，首次启动时交互式向导会自动引导完成配置。

### settings.json（推荐）

配置文件位于 `~/.icode/settings.json`：

```json
{
  "provider": "OpenAI",
  "model": "gpt-4o",
  "apiKey": "sk-...",
  "apiBase": "https://api.openai.com/v1",
  "maxTokens": 8192,
  "maxIterations": 30
}
```

首次运行 `openjiuwen` 时，如果未检测到 API Key，会自动启动交互式配置向导，将配置写入此文件。

### 配置项说明

| settings.json 字段 | 环境变量 | 说明 | 默认值 |
|---|---|---|---|
| `apiKey` | `ICODE_API_KEY` / `OPENJIUWEN_API_KEY` | API 密钥（必需） | — |
| `model` | `ICODE_MODEL` / `OPENJIUWEN_MODEL` | 模型名称 | `gpt-4o` |
| `provider` | `ICODE_PROVIDER` / `OPENJIUWEN_PROVIDER` | LLM 提供商 | `OpenAI` |
| `apiBase` | `ICODE_API_BASE` / `OPENJIUWEN_API_BASE` | API 基础地址 | `https://api.openai.com/v1` |
| `maxTokens` | `OPENJIUWEN_MAX_TOKENS` | 最大 token 数 | `8192` |
| `maxIterations` | `OPENJIUWEN_MAX_ITERATIONS` | 最大迭代次数 | `30` |
| `serverUrl` | `OPENJIUWEN_SERVER_URL` | 远程 Agent Server 地址 | — |

iCode **project** 用 CLI `-p` / 环境变量 `ICODE_PROJECT`（默认 `~/.icode/projects/default`）。Agent workspace 固定为 `<project>/workspace`。

### 配置优先级

```
CLI 参数 > 环境变量 > ~/.icode/settings.json > 默认值
```

### CLI 参数（优先级最高）

```bash
openjiuwen -p ~/my_icode_project --model GLM-5 --provider OpenAI --api-key "your-key"
```

### 路径术语（iCode）

详见 `docs/design/icode-path-layout-rfc.md`。

| 术语 | 含义 | 典型路径 |
|------|------|----------|
| **Agents home** | 跨 harness 共享（skills 等） | `~/.agents/` |
| **iCode home** | 本机产品配置 | `~/.icode/` |
| **iCode project** | 一次工作 setup | `~/…` 或 `~/.icode/projects/default` |
| **directories** | 外部代码/文档根（`directories.json`） | 如 `~/gitcode/agent-core` |
| **agent workspace** | IDENTITY / memory / todo | `<project>/workspace/` |
| **session** | 对话 | `<project>/sessions/<id>/` |

TUI：`/cwd`、`/directories`。CLI：`openjiuwen -p <project>`。

**路径与多仓场景（用户向）**：见 [`docs/zh/openjiuwen-icode-user-guide.md`](../../../docs/zh/openjiuwen-icode-user-guide.md)。

### `~/.icode/` 目录结构（iCode home）

| 路径 | 说明 |
|------|------|
| `settings.json` | 主配置文件（provider、model、apiKey 等） |
| `mcp.json` | MCP 服务器配置 |
| `OPENJIUWEN.md` | 用户级系统提示词 / 记忆文件 |
| `models/` | 模型 profile |
| `agents/` | agent profile |
| `projects/default/` | 默认 iCode project |

## 使用方式

### 交互式模式（默认 · EventBus TUI）

```bash
$ openjiuwen
# 或
$ openjiuwen tui
$ openjiuwen -p ~/chrys_2_icode_porting_project
$ openjiuwen chat          # 与 tui 相同

# 无 API Key 时可用 demo 验契约
$ openjiuwen tui --demo

# 浏览器托管 TUI（textual-serve，每 tab 一个会话进程）
$ openjiuwen serve --demo
$ openjiuwen serve --host 0.0.0.0 --port 8000 --public-url http://127.0.0.1:8000

# 编辑器 ACP（stdout 仅 JSON-RPC）
$ openjiuwen acp --demo

# 仅当需要旧版 Rich REPL 时：
$ openjiuwen chat --repl
```

TUI 需要：`pip install "openjiuwen[tui]"`（含 `textual` + `textual-serve`；未安装时会回退到 legacy REPL 并提示）。

在 TUI 中：Enter 发送、Busy 时输入为 inject、Ctrl+C 中断、Ctrl+R 重试、Ctrl+Q 退出。

常用 slash（经 EventBus `UserCommand`）：

| 命令 | 说明 |
|------|------|
| `/help` | 帮助 |
| `/status` | 模型与 token |
| `/models [id]` | 列出 / 切换模型；TUI 下 bare `/models` 或 **F4** 打开 Models Modal |
| `/sessions` | 已保存会话列表（标题 · 按更新时间） |
| `/title [text]` | 查看 / 设置当前会话标题 |
| `/new` | 新会话 |
| `/resume <id>` | 恢复会话元数据 |
| `/compact` | 触发 compaction 事件 |
| `/mcp` `/cwd` `/clear` | MCP 说明 / cwd / 清屏 |
| `/directories` | 登记与切换外部代码根（见[用户指南](../../../docs/zh/openjiuwen-icode-user-guide.md)） |

### 非交互式模式

```bash
# 直接运行
openjiuwen run "分析 src/ 下所有 Python 文件，列出未使用的 import"

# 管道模式
echo "检查代码风格问题" | openjiuwen run -

# JSON 输出（适合 CI/CD 集成）
openjiuwen run -f json "What is 2+2?"

# 流式 JSONL
openjiuwen run -f stream-json "分析这个项目" >> build.jsonl
```

### 项目记忆（OPENJIUWEN.md）

在项目根目录创建 `OPENJIUWEN.md`，Agent 会自动加载其中的规则：

```markdown
# 项目约定
- 使用 pytest 进行测试
- 所有函数必须有类型注解
- 提交消息使用 conventional commits 格式
- 代码风格遵循 ruff 规范
```

支持两层记忆：
1. **用户级**: `~/.icode/OPENJIUWEN.md` — 全局偏好
2. **项目级**: `{directory_root}/OPENJIUWEN.md` — 目录/仓库规范（优先级更高）

## Auto-Harness

CLI 内置了 `auto-harness` 能力，既可以通过命令行子命令使用，也可以在交互式 REPL 中直接输入 `/auto-harness <自然语言目标>`。

在终端输入：

```bash
openjiuwen
```

auto-harness 的配置和运行目录在当前 iCode project 的 agent workspace 下：

```text
<icode-project>/workspace/auto_harness/
```

### 交互式示例

在交互式模式里，可以直接这样输入：

```text
/auto-harness 调研当前和 Claude Code 在批量修复 lint/type error 上的能力差距
/auto-harness 调研当前和 Claude Code 在自动生成修复计划上的能力差距
/auto-harness 调研当前和 Claude Code 在 PR 级别自动修改上的能力差距
/auto-harness 调研当前和 Claude Code 在工作区隔离执行上的能力差距
/auto-harness 调研当前和 Claude Code 在子任务调度上的能力差距
/auto-harness 调研当前和 Claude Code 在 agent 协作编排上的能力差距
/auto-harness 调研当前和 Claude Code 在失败恢复上的能力差距
/auto-harness 调研当前和 Claude Code 在 fix loop 自动修复上的能力差距
```

### 本地配置示例（脱敏）

下面这份示例按本地实际 `config.yaml` 结构整理，并做了脱敏处理：

```yaml
local_repo: "/home/<user>/code/gitcode/agent-core"

git:
  remote: "autoharness"
  base_branch: "develop"
  user_name: "auto-harness"
  user_email: "auto-harness@<masked-domain>"
  fork_owner: "auto-harness"
  upstream_owner: "openJiuwen"
  upstream_repo: "agent-core"

gitcode:
  username: "auto-harness"
  access_token: "<redacted>"

budget:
  session_secs: 3600
  cost_limit_usd: 10.0
  task_timeout_secs: 1200
  max_tasks_per_session: 3

ci_gate:
  config_path: ""
  python_executable: "/home/<user>/code/openJiuwen/test-agentcore/python11venv/bin/python3.11"
  install_command: "uv sync --active --group dev --extra cli"

fix_loop:
  phase1_max_retries: 10
  phase2_max_retries: 9
```

如果你不想把 token 放进配置文件，推荐改成环境变量：

```bash
export GITCODE_ACCESS_TOKEN=xxxx
```

## 能力全景

CLI Agent 集成了丰富的工具、Rail 插件和子 Agent，开箱即用。

### 5.1 内置工具（Tools）

#### 文件系统工具（SysOperationRail 提供）

| 工具名 | 功能 | 说明 |
|--------|------|------|
| `bash` | Shell 执行 | 运行 shell 命令，支持超时控制 |
| `read_file` | 读取文件 | 读取文件内容，支持行号范围 |
| `write_file` | 写入文件 | 完全覆盖写入，文件不存在时自动创建 |
| `edit_file` | 智能编辑 | 基于字符串替换的精确编辑，保留格式 |
| `glob` | 文件匹配 | 支持 `**/*` 等 glob 模式查找文件 |
| `grep` | 内容搜索 | 优先使用 iCode 内置 ripgrep；支持正则 / type / glob |
| `list_files` | 目录列表 | 列出指定目录下的文件和子目录 |
| `code` | 代码执行 | 执行 Python 或 JavaScript 代码片段 |

#### 网络工具（手动注册）

| 工具名 | 功能 | 说明 |
|--------|------|------|
| `free_search` | 网络搜索 | 通过 DuckDuckGo 免费搜索，返回排序 URL 和摘要 |
| `fetch_webpage` | 网页抓取 | 获取网页文本内容，返回状态码/标题/正文 |

#### Todo 工具（DeepAgent 内置）

| 工具名 | 功能 | 说明 |
|--------|------|------|
| `todo_create` | 创建待办 | 创建 Todo 列表 |
| `todo_list` | 查看待办 | 获取并展示所有 Todo 项 |
| `todo_modify` | 修改待办 | 更新、删除、取消、追加、插入 Todo 项 |

#### 任务调度工具（DeepAgent 内置）

| 工具名 | 功能 | 说明 |
|--------|------|------|
| `task` | 子任务派发 | 启动临时子 Agent 处理复杂多步独立任务，隔离上下文窗口 |
| `cron` | 定时任务 | 使用 cron 表达式调度周期或一次性任务 |

#### 工具发现（DeepAgent 内置）

| 工具名 | 功能 | 说明 |
|--------|------|------|
| `search_tools` | 搜索工具 | 按能力、名称、描述或参数搜索候选工具（仅发现，不直接调用） |
| `load_tools` | 加载工具 | 动态加载/注册新工具 |

#### 多模态工具（需环境变量配置）

| 工具名 | 功能 | 前置条件 |
|--------|------|----------|
| `image_ocr` | 图片 OCR | 设置 `VISION_API_KEY` 或复用主模型凭据 |
| `visual_question_answering` | 图片问答 | 同上 |
| `audio_transcription` | 语音转文字 | 设置 `AUDIO_API_KEY` 或复用主模型凭据 |
| `audio_question_answering` | 音频问答 | 同上 |
| `audio_metadata` | 音频元数据 | 同上 |
| `video_understanding` | 视频理解 | 同上 |

### 5.2 Rail 插件

Rail 是 Agent 运行时的拦截器/增强器，在工具调用前���自动执行。

| Rail | 功能 | 注入的工具 |
|------|------|-----------|
| **SysOperationRail** | 注册文件系统工具集（bash、read_file 等） | 8 个文件系统工具 |
| **TokenTrackingRail** | 统计每轮 LLM 调用的 Token 用量 | 无 |
| **ToolTrackingRail** | 追踪工具调用事件，生成 chunk 供 UI 渲染 | 无 |
| **AskUserRail** | 中断执行流，向用户提问并等待回答 | `ask_user` |
| **ConfirmInterruptRail** | 对危险工具（bash、write_file、edit_file）进行人工确认拦截 | 无 |
| **SkillUseRail** | 扫描并加载 `<icode-project>/workspace/skills/` 等技能根 | `list_skill` |
| **ContextEngineeringRail** | 上下文窗口管理，含 DialogueCompressor 支持 `/compact` | 无 |
| **MemoryRail** | 向量记忆工具（需 Embedding 模型配置） | `memory_search`、`memory_get`、`write_memory`、`edit_memory`、`read_memory` |
| **SessionRail** | 异步子 Agent 任务管理（有子 Agent 时自动注入） | `sessions_list`、`sessions_spawn`、`sessions_cancel` |

#### MemoryRail 配置

MemoryRail 需要 Embedding 模型支持，通过环境变量配置：

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `EMBEDDING_MODEL_NAME` | Embedding 模型名 | `text-embedding-3-small` |
| `EMBEDDING_BASE_URL` | Embedding API 地址 | 复用主模型 `apiBase` |
| `EMBEDDING_API_KEY` | Embedding API 密钥 | 复用主模型 `apiKey` |

### 5.3 子 Agent（Subagents）

CLI Agent 可以将复杂任务委派给专用子 Agent（Chrys Code 风格），通过 `sessions_spawn` 在后台异步执行。

| 子 Agent | 功能 | 说明 |
|----------|------|------|
| **general-purpose** | 通用委托 | 与主 Agent 相近的工具面，适合杂项多步任务 |
| **explore_agent** | 只读探索代码库 | glob/grep/read_file；禁止写文件 |
| **plan_agent** | 只读架构与计划 | 产出实现方案，禁止改仓库 |
| **browser_agent** | 浏览器自动化 | Playwright（未安装时自动跳过） |
| **research_agent** | 研究调查 | 设置 `OPENJIUWEN_CLI_RESEARCH_SUBAGENT=1` 启用 |

默认并发上限：同时 2 个子任务（`OPENJIUWEN_SUBAGENT_MAX_TOTAL` / `OPENJIUWEN_SUBAGENT_MAX_PER_TYPE`，或 `settings.json` 的 `subagents` 块，或 `~/.icode/agents/<profile>.yaml` 内 `sub_agents.max_total_concurrency`）。可选 `subagents.roster` 或 profile 内 `sub_agents.agents[].tool_name` 限制启用的子 Agent。后台任务：`/subagents` 查看；`cancel`/`abort`/`retry <task_id>` 控制。瞬时失败自动重试：`OPENJIUWEN_SUBAGENT_MAX_RETRIES`（默认 2）或 `subagents.max_retries`；TUI 卡片显示 `↻ Retrying…` 横幅。

### 5.4 Browser 子 Agent

**前置条件：** 需要安装 Playwright 相关依赖。

```bash
pip install playwright
playwright install chromium
```

> **注意：** 如果未安装 Playwright，browser_agent 会被自动跳过，不影响其他功能使用。

### 5.5 MCP 服务器扩展

通过 `~/.icode/mcp.json` 配置外部 MCP（Model Context Protocol）服务器，动态扩展 Agent 工具集。格式兼容 Claude Code：

```json
{
  "mcpServers": {
    "my-server": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@mcp/my-server"],
      "env": {}
    }
  }
}
```

支持的传输方式：`stdio`、`sse`、`streamable-http`。

### 5.6 技能系统（Skills）

SkillUseRail 会扫描以下目录（优先级从高到低）：

1. `<icode-project>/workspace/skills/`
2. `~/.claude/skills/`
3. `~/.codex/skills/`
4. `~/.jiuwenclaw/workspace/skills/`
5. `~/.chrys/skills/`（Chrys 兼容）
6. `~/.agents/skills/`（Agents Skills 用户目录）
7. `<cwd>/.agents/skills/`（随 `/directories use` 热解析）

额外路径与 inline skills 见 `~/.icode/skills.json`（或 `settings.json` 的 `skills` 字段）。

工具：`skill_tool`（加载 SKILL.md / 资源）、`run_skill_script`（技能包脚本）。
TUI：`/skills` 列表；`/<skill-name>` 注入技能正文。

在技能目录中放置含 `SKILL.md` 的子目录（最多 2 层）即可被 Agent 自动发现和调用。

## 命令参考

### CLI 命令

```bash
openjiuwen                          # EventBus TUI（默认交互）
openjiuwen tui                      # 同上
openjiuwen chat                     # 同上（`--repl` 走 legacy Rich REPL）
openjiuwen tui --demo               # 无 API Key 的契约演示
openjiuwen serve [--demo]           # 浏览器托管 TUI（textual-serve）
openjiuwen acp [--demo]             # ACP JSON-RPC（编辑器接入）
openjiuwen run "prompt"             # 非交互式（经 EventBus，auto-approve）
openjiuwen run -a code -C ~/proj "p"  # Chrys 对齐：agent / workdir
openjiuwen run -t task.md --json    # 从文件读 prompt；最终 JSON
openjiuwen run -s cli-xxx "cont"    # 恢复 session 后继续
openjiuwen agents [--json]          # 列出 agent profiles
openjiuwen models [--json]          # 列出 model profiles
openjiuwen run -f json "prompt"     # JSON 输出（含 session_id/duration）
openjiuwen run -f stream-json "p"   # 流式 JSONL（EventBus 事件）
openjiuwen run -                    # 从 stdin 读取 prompt
openjiuwen bus-run --demo "hello"   # demo 别名（无 API Key）
openjiuwen --version                # 显示版本
openjiuwen --help                   # 显示帮助
```

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/exit` | 退出 OpenJiuWen iCode |
| `/quit` | `/exit` 别名 |
| `/clear` | 清屏 |
| `/status` | 显示 Token 用量和模型信息 |
| `/cost` | 显示 Token 费用统计 |
| `/compact` | 压缩对话历史 |
| `/sessions` | 列出历史会话（标题 · 按更新时间） |
| `/title [text]` | 查看 / 设置当前会话标题 |
| `! <cmd>` | 直接执行 shell 命令（不经过 Agent） |

### 快捷键

| 快捷键 | 行为 |
|--------|------|
| `Ctrl+C` (1次) | 中止当前流式输出 |
| `Ctrl+C` (2次, 2秒内) | 提示即将退出 |
| `Ctrl+C` (3次, 2秒内) | 退出程序 |

## 支持的 LLM 提供商

| 提供商 | `provider` 值 | 说明 |
|--------|---------------|------|
| OpenAI | `OpenAI` | GPT-4o, GPT-4o-mini 等 |
| OpenRouter | `OpenRouter` | 多模型路由 |
| DashScope | `DashScope` | 通义千问系列 |
| SiliconFlow | `SiliconFlow` | GLM, DeepSeek 等 |
| ModelArts | `OpenAI` | 华为云 ModelArts（OpenAI 兼容） |

## 项目结构

```
openjiuwen_icode/
├── __init__.py              # 包定义 + 版本号
├── __main__.py              # python -m 入口
├── cli.py                   # Click CLI 入口（chat / run）
├── install.sh               # Linux/macOS 一键安装脚本
├── install.ps1              # Windows 一键安装脚本
├── agent/
│   ├── config.py            # 配置管理（settings.json + 三层优先级）
│   └── factory.py           # Agent 工厂 + LocalBackend
├── prompts/
│   └── builder.py           # 系统提示词构建
├── rails/
│   ├── token_tracker.py     # Token 用量追踪
│   └── tool_tracker.py      # 工具调用追踪
├── storage/
│   └── session_store.py     # JSON 会话持久化
└── ui/
    ├── renderer.py          # 流式渲染器（8 种 chunk 类型）
    ├── repl.py              # 交互式 REPL + slash 命令
    ├── runner.py            # 非交互模式（text/json/stream-json）
    ├── tool_display.py      # 工具名称映射 + 参数格式化
    └── todo_render.py       # Todo 渲染
```

## 测试

```bash
# 运行全部 CLI 测试
pytest tests/cli/ -v -o "addopts="

# 仅单元测试（快速，无需 API Key）
pytest tests/cli/unit/ -v -o "addopts="

# 仅集成测试
pytest tests/cli/integration/ -v -o "addopts="

# E2E 测试（需要 API Key）
pytest tests/cli/e2e/ -v -o "addopts="
```

## 架构

```
用户终端
    │
    ▼
cli.py (Click)  →  chat / run 子命令
    │
    ├── repl.py (交互式)     →  prompt_toolkit + rich
    └── runner.py (非交互式)  →  text / json / stream-json
            │
            ▼
    AgentBackend (Protocol)
    └── LocalBackend  →  SDK Runner.run_agent_streaming()
            │
            ▼
    agent-core SDK
    ├── DeepAgent + ReActAgent
    ├── 内置工具 (Bash/File/Grep/Web)
    └── Rail 插件 (Security/TokenTracking)
            │
            ▼
    LLM Provider (OpenAI / DashScope / SiliconFlow / ...)
```
