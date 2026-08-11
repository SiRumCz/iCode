# OpenJiuWen iCode 用户使用指南

> 面向终端 TUI/CLI 的**路径、目录登记与多仓协作**说明。  
> 设计细节见 [iCode 四层路径 RFC](../design/icode-path-layout-rfc.md)；安装与命令全集见 [CLI README](../../openjiuwen_icode/README.md)。

## 1. 五类路径（先建立心智模型）

iCode 把「本机配置」「一次工作 setup」「要改的代码仓」分开，避免以前的 workspace / workdir 混用。

| 名称 | 是什么 | 典型位置 | Agent 会不会在这里写东西 |
|------|--------|----------|---------------------------|
| **Agents home** | 跨产品共享（如 skills） | `~/.agents/` | 默认只读 |
| **iCode home** | 本机 iCode 配置 | `~/.icode/` | 安装/设置写入，非代码仓 |
| **iCode project** | 一次工作 setup | `-p` 指定，默认 `~/.icode/projects/default` | 拥有 `directories.json`、sessions |
| **directories** | 外部代码/文档根（可多个） | 写在 project 的 `directories.json` | 你要改的 git 仓在这里登记 |
| **agent workspace** | Agent 身份与持久记忆 | `<project>/workspace/` | IDENTITY、memory、todo 等 |
| **session** | 单次对话 | `<project>/sessions/<id>/` |  transcript、导出、子 Agent 审计 |

**记住两条硬规则：**

1. **改代码、跑 shell、相对路径** → 看 **primary directory**（`directories.json` 里带 `*` 的那一项），不是 agent workspace。  
2. **Agent 的 IDENTITY / 项目级 todo** → 始终在 **iCode project 的 `workspace/`**，切换 primary **不会**改掉这里。

环境变量：`ICODE_HOME`、`ICODE_PROJECT`、`AGENTS_HOME`（见 RFC）。

```bash
openjiuwen -p ~/icode/my-setup    # 打开或创建一次工作 setup
```

TUI 里用 **`/cwd`** 一次看清上述层次；用 **`/directories`** 管理外部目录。

---

## 2. Primary（`*`）和「其它已登记目录」有什么区别？

`/directories` 列表里，**`*` = primary（主目录）**。它们都在同一个 project 的 `directories.json` 的 `dirs` 里，但运行时角色不同。

### Primary 负责什么

| 能力 | 说明 |
|------|------|
| **Tool cwd** | Shell、`read_file` 等**相对路径**默认相对于 primary |
| **系统 prompt 里的 CWD / git 分支** | 从 primary 取当前目录与 `git rev-parse` |
| **项目级 OPENJIUWEN.md** | 从 **primary** 向上找 `.git`、`pyproject.toml` 等根标记后加载 |
| **`<cwd>/.agents/skills` 解析** | TUI 技能扫描里的 `<cwd>` 指 primary |
| **导出元数据** | `/export` 里的 `directory` 字段用 primary |

切换 primary：**`/directories use <路径|序号>`**（别名 **`/workdirs use`**）。会更新 `cfg.cwd` 与 pending tool cwd，**下一回合**相对路径按新 primary 生效；**agent workspace 不变**。

### 其它已登记目录（无 `*`）

- 表示「这次 setup 还会用到这些外部根」，便于多仓任务**登记、切换、同一会话**。
- **默认不是** tool cwd；Agent 的「当前项目上下文」仍按 **primary** 理解。
- 不能直接 **`/directories rm`** 掉 primary，需先 **`use`** 到别的目录。
- 设计方向（RFC）：仅允许访问已登记目录；**当前最稳定的行为差异仍是 primary 驱动 cwd**，跨目录访问建议在任务里写**绝对路径**或先 **`use`**。

---

## 3. 典型场景

### 场景 A：日常单仓库开发

1. 进入仓库：`cd ~/gitcode/my-app`  
2. 启动：`openjiuwen -p ~/icode/my-app`（或共用 default project，见场景 B）  
3. 若 `directories.json` 为空，启动时会用**进程 cwd** seed 一条目录并设为 primary。  
4. 单仓规范写在仓库根 **`OPENJIUWEN.md`**；全局习惯写在 **`~/.icode/OPENJIUWEN.md`**。

**适用**：一个 git 根、一个会话、相对路径即可。

---

### 场景 B：长期使用「默认 project」

不指定 `-p` 时使用 **`~/.icode/projects/default`**。

- 适合：总在同一台机器上随手开 iCode、目录靠 **`/directories add`** 管理。  
- 注意：default 里 sessions 与 directories 会累积；多类无关工作建议**拆多个 `-p` project**（见场景 D 对比）。

---

### 场景 C：Monorepo（单 git 根、多包）

仓库本身是一个根（如 `packages/api`、`packages/web` 在同一 git 下）。

- **只登记 monorepo 根目录**为一个 directory，并设为 primary 即可。  
- 不必为每个子包各 add 一条，除非子包是**独立路径、独立 git**（那就回到场景 D）。

---

### 场景 D：多代码仓联合开发（推荐 workflow）

目标：API 仓 + 前端仓 + SDK 仓在同一对话里协作。

**1. 建一个「联合开发」iCode project（不要每仓一个 project）**

```bash
openjiuwen -p ~/icode/platform-all-repos
```

**2. 登记所有相关仓**

TUI：

```text
/directories add          # 打开目录树选择器（无参数时）
/directories add /path    # 或手输绝对路径
/directories              # 确认列表与 *
/cwd
```

**3. 跨仓说明写在哪里**

| 内容 | 建议位置 |
|------|----------|
| 各仓职责、依赖关系、「改 A 必改 B」 | `<project>/workspace/` 下 AGENT / memory（随 project 走） |
| 全局编码习惯 | `~/.icode/OPENJIUWEN.md` |
| 单个 git 仓的规范 | 该仓根目录 `OPENJIUWEN.md`（**仅当该仓为 primary 时**会按「项目级」进 prompt） |

系统**不会**自动合并所有已登记目录下的 OPENJIUWEN.md；多仓任务请在 **project workspace** 或任务描述里写清地图。

**4. 执行时的两种策略**

| 策略 | 何时用 | 做法 |
|------|--------|------|
| **按阶段换 primary** | 要在某仓里大量 bash、相对路径、跑测试 | `/directories use 2` 或 `/directories use ~/git/frontend`，做完再切回 |
| **primary 固定主仓** | 主仓为主，偶尔读/改其它仓 | 任务里写清绝对路径；或 spawn 子 Agent 时在描述里带路径 |

**5. 任务描述模板（建议开场一句）**

```text
多仓任务：primary 是 backend（*）；frontend、shared-sdk 已在 /directories。
改 API 在 backend；改客户端请先 /directories use frontend 或使用绝对路径。
```

**6. 何时不要硬用多 directory**

- 两个仓完全无关、也不共享会话 → 两个 `-p` project 更简单。  
- 所有代码已在 monorepo → 场景 C。

---

### 场景 E：从 A 仓切到 B 仓「接着聊」

- **同一 project、同一 session**：`/directories use B`，继续对话；history 在 `<project>/sessions/`。  
- **换 project**：`openjiuwen -p 另一个`；sessions 与 directories 各自独立。  
- **换 primary 不等于换 agent workspace**：IDENTITY/memory 仍在当前 project 的 `workspace/`。

---

## 4. 记忆与约定：放哪一层？

```
~/.icode/OPENJIUWEN.md          → 用户级，所有 project 共享
<primary 仓库根>/OPENJIUWEN.md  → 当前 primary 对应仓库的项目约定
<project>/workspace/            → 本次 setup 的 Agent 身份、跨仓说明、todo
```

构建系统 prompt 时，**Environment** 段里的 CWD、Git branch 来自 **primary**。多仓时勿只依赖某一个仓的 OPENJIUWEN.md。

---

## 5. TUI 命令速查（directories）

| 命令 | 作用 |
|------|------|
| `/directories` | 列出已登记目录（`*` = primary） |
| `/directories add` | TUI：**目录树选择器**；REPL：需带路径 |
| `/directories add <path>` | 手输路径登记 |
| `/directories use <路径\|序号>` | 设 primary，热更新 tool cwd |
| `/directories rm <路径\|序号>` | 删除非 primary 项 |
| `/workdirs …` | 与 `/directories` 相同（旧名） |
| `/cwd` | 显示 Agents home、iCode home、project、primary、tool cwd、workspace |

目录选择器：**Parent folder** 上跳；**Add folder** 或 **Ctrl+Enter** 确认；已登记目录会提示 `(already registered)`。

---

## 6. project 目录里有什么（便于备份/迁移）

```text
<icode-project>/
  project.json
  directories.json    # {"primary": "...", "dirs": [...]}
  workspace/          # agent workspace
  sessions/           # 会话与 sidecar
  .cache/
```

联合开发时备份 **`directories.json` + `workspace/` + `sessions/`** 即可恢复同一 setup。

---

## 7. 能力边界（使用时心里有数）

- **同一时刻只有一个 primary**，相对路径与「当前 git 分支」只反映 primary。  
- **已登记的多目录**主要用于登记、切换、同 project 下共享 session；跨仓改代码请 **`use`** 或 **绝对路径**。  
- **directories 访问 allow-list** 为 RFC 目标；以 `/cwd` 与 `/directories` 实际行为为准。  
- **无**从旧版 `~/.openjiuwen` 的自动迁移；新装请用 `~/.icode` 与 `-p` project。

---

## 8. 相关文档

| 文档 | 内容 |
|------|------|
| [icode-path-layout-rfc.md](../design/icode-path-layout-rfc.md) | 四层路径与 rollout |
| [openjiuwen_icode/README.md](../../openjiuwen_icode/README.md) | 安装、Rail、MCP、skills |
| [AGENTS.md](../../AGENTS.md) | 贡献者与 AI 助手的路径术语 |
