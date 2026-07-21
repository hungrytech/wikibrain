# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain：一位年轻的研究者和友好的大脑吉祥物位于一幅发光的互联知识地图下方">
</p>

<p align="center"><strong>开源 · 本地优先 · 用户所有 · Markdown 原生</strong></p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.ja.md">日本語</a> ·
  <strong>简体中文</strong>
</p>

WikiBrain 是一个采用 [MIT 许可证](LICENSE)的共享第二大脑，供 Claude Code 和
Codex 使用。它通过生命周期钩子捕获经过脱敏的对话交接信息，
将持久上下文存储为可读的 Markdown，并使用
[Wikimap](https://github.com/dhha22/wikimap) 在本地进行可感知来源的检索。

## 目录

- [为什么选择 WikiBrain](#why-wikibrain)
- [快速开始](#getting-started)
- [工作原理](#how-it-works)
- [经验证的基准测试](#verified-benchmark)
- [安装与信任](#installation-and-trust)
- [日常命令](#daily-commands)
- [数据与隐私](#data-and-privacy)
- [项目文档](#project-documentation)

<a id="why-wikibrain"></a>

## 为什么选择 WikiBrain

| 需求 | WikiBrain 提供的能力 |
| --- | --- |
| 跨智能体继续工作 | Claude 和 Codex 可以恢复同一项目范围内的上下文。 |
| 将证据与记忆分开 | 可搜索的对话交接信息与明确的长期记忆相互独立。 |
| 保障用户所有权 | Markdown 是持久的数据源；Wikimap 索引可以随时丢弃。 |
| 从暂时性故障中恢复 | 归档、提升和关系清理发件箱会重试中断的工作。 |
| 保持掌控 | 捕获范围采用允许列表，并且可以暂停、检查、预览和删除。 |

WikiBrain 不会抓取你的代码仓库，也不会自动将每次对话都转化为永久事实。
它只捕获生命周期载荷，而且只有明确提出的“记住这个”请求才会成为持久记忆。

<a id="getting-started"></a>

## 快速开始

### 1. 安装并初始化

macOS 或 Linux：

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

对于原生 Windows，请使用可供审查的 [PowerShell 安装程序](#native-windows)。
`brainctl init` 是明确的同意边界：仅安装程序不会更改 Claude 或 Codex 的设置。

### 2. 启动新的智能体会话

| 客户端模式 | 执行 `brainctl init` 后 | 一次性操作 |
| --- | --- | --- |
| Claude Code 自动记忆 | 在新会话中即可使用 | 无；可以使用 `/hooks` 进行检查。 |
| Codex 手动记忆 | 立即可用 | 使用 `brainctl remember` 和 `brainctl recall`。 |
| Codex 自动捕获和检索 | 定义已安装，但最初不受信任 | 启动新会话，打开 `/hooks`，检查五个 WikiBrain 钩子，并信任其当前哈希。 |

### 3. 运行冒烟测试

```bash
brainctl remember --global --title "WikiBrain smoke test" \
  "My WikiBrain verification marker is Cobalt-719."
brainctl recall "Cobalt-719"
```

结果应包含 `Cobalt-719` 和一个本地 Markdown 来源。使用 `remember` 返回的文档 ID
删除测试页面：

```bash
brainctl forget --document DOCUMENT_ID --apply
```

<a id="how-it-works"></a>

## 工作原理

```text
Claude Code hooks ─┐
                   ├─ brainctl ─┬─ SQLite WAL: receipts, queues, relations
Codex hooks ───────┘            ├─ Markdown vault: durable readable truth
                                └─ Wikimap: disposable local search index
```

1. `UserPromptSubmit` 对提示词进行脱敏和记录，然后检索相关的项目记忆。
2. `Stop` 将最终响应与提示词配对，并将本轮对话归档为不可变的 Markdown 交接记录。
3. 明确提出的“记住”请求通过独立的重试队列创建持久记忆页面。
4. `SessionStart` 为同一 Git 工作区恢复近期上下文以及与查询相关的上下文。
5. 带类型的 `relates-to` 和 `supersedes` 链接连接证据并抑制过时指导，
   同时不会删除其出处。

每个 Git 仓库都是相互隔离的记忆范围。只有 `brainctl remember --global`
会有意跨越项目边界。钩子采用故障开放机制：格式错误的事件、繁忙的数据库、
缺失的 Wikimap 可执行文件或超时都不会阻塞编码智能体。

有关持久化、删除、重试和信任边界的详细信息，请参阅
[ARCHITECTURE.md](ARCHITECTURE.md)。

<a id="verified-benchmark"></a>

## 经验证的基准测试

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain 基准测试：8 项功能检查中 8 项全部通过；在 80 个样本中，检索延迟为 p50 24.31 毫秒、p95 28.14 毫秒">
</p>

固定语料库基准测试的查询检索检查会禁用近期条目回退。另一项交接检查
单独验证 `SessionStart` 的近期上下文恢复。只有当查询检索返回预期证据，
并排除被禁止的过时内容、机密信息或跨工作区内容时，查询检查才算通过。

| 结果 | 数值 |
| --- | ---: |
| 功能检查 | **8/8 通过** |
| 检索样本 | **80**（4 个查询 × 20 次迭代） |
| 延迟 | **24.31 ms p50 · 28.14 ms p95** |
| 环境 | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

<details>
<summary><strong>八项检查涵盖的内容</strong></summary>

| 检查 | 契约 |
| --- | --- |
| 当前决策 | 新的 `uv` 指导会抑制已被取代的 `pip` 指导。 |
| 证据链接 | `relates-to` 和 `supersedes` 边在检索后仍然保留。 |
| 人员与项目 | 所有者和备用审查者的上下文仍可恢复。 |
| 来源出处 | 文档 ID、Markdown 路径和捕获时间会随证据一同提供。 |
| 工作区隔离 | 来自另一个仓库的标记不会跨越范围。 |
| 机密信息脱敏 | 合成的 API 机密不会出现在持久存储和检索结果中。 |
| 全局偏好 | 有意设置的全局偏好可在项目范围内使用。 |
| Claude → Codex | Claude 会话中的事实会在 Codex 会话启动时出现。 |

</details>

从源代码检出版本中复现：

```bash
uv run --locked python -m benchmarks.second_brain \
  --iterations 20 \
  --format json \
  --output benchmarks/results/second-brain-v1.json
uv run --locked python scripts/render_benchmark_chart.py
```

机器可读的结果位于
[`benchmarks/results/second-brain-v1.json`](benchmarks/results/second-brain-v1.json)。
图表由该文件生成；如果 SVG 已过时，CI 会拒绝它。延迟会因机器和运行而异，
并非稳定的性能保证。

> **范围：** 100% 仅表示这个小型合成回归语料库通过了测试。
> 它并不衡量充满噪声的长期保险库、语义改写、OCR 或文档摄取、并发写入、
> 答案忠实度或多跳图推理。

<a id="installation-and-trust"></a>

## 安装与信任

### macOS 或 Linux

请使用上方[快速开始](#getting-started)中的命令。预构建的二进制包覆盖
Apple Silicon macOS、Intel macOS 和 x86_64 Linux。

<a id="native-windows"></a>

### 原生 Windows

打开 PowerShell，下载指定版本的安装程序，审查后再运行：

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

安装程序使用 Python 3.11+，通过隔离的 `pipx` 进行安装，并且仅在提供
`-Initialize` 时运行 `brainctl init`。省略该开关即可安装 CLI 而不更改智能体设置。
原生 Windows 将大脑数据存储在 `%LOCALAPPDATA%\WikiBrain` 下。如果你的智能体和
代码仓库在 WSL 中运行，请使用 WSL 内的 Linux 路径。

<details>
<summary><strong>Codex 钩子信任边界</strong></summary>

手动执行 `brainctl remember` 和 `brainctl recall` 无需批准钩子。
自动捕获提示词和注入上下文则不然：在通过 `/hooks` 审查当前定义的哈希之前，
Codex 会跳过不受管理的命令钩子。

WikiBrain 绝不会将 `--dangerously-bypass-hook-trust` 添加到别名、包装器或启动设置中。
唯一无需持续审查的持久路径，是由管理员通过系统、MDM、云或
`requirements.toml` 下发的钩子策略。

对于没有待处理钩子警告、完全无需信任的纯手动设置：

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "A durable fact"
brainctl recall "that durable fact"
```

请参阅官方 [Codex 钩子文档](https://learn.chatgpt.com/docs/hooks)。

</details>

### `brainctl init` 会更改的内容

`brainctl init` 是幂等的。它会备份现有设置，仅以结构化方式合并 WikiBrain
拥有的条目，并保留无关的钩子和技能。

| 用途 | macOS/Linux | 原生 Windows |
| --- | --- | --- |
| 大脑状态 | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| Claude 钩子 | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex 钩子 | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Claude 技能 | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Codex/Agents 技能 | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |

| 事件 | WikiBrain 操作 |
| --- | --- |
| `SessionStart` | 注册会话并注入相关的项目记忆。 |
| `UserPromptSubmit` | 对提示词进行脱敏和捕获，然后检索上下文。 |
| `PostToolUse` | 只存储安全的工具、文件和工作目录指针。 |
| `Stop` | 归档已完成的一轮对话，提升明确记忆，并刷新搜索。 |
| `PostCompact` | 将可用的压缩摘要归档为交接记录。 |

检查或仅移除 WikiBrain 拥有的集成：

```bash
brainctl init --dry-run --json
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

### 本地开发

```bash
uv sync --locked
uv run brainctl init
uv run python -m unittest discover -s tests -v
```

<a id="daily-commands"></a>

## 日常命令

```bash
brainctl status
brainctl recall "what did we decide about the auth architecture?"
brainctl remember --title "Preferred package manager" "Use uv for Python tools."
brainctl remember --global "I prefer concise Korean answers."
brainctl remember --title "Use uv" \
  --relates-to evidence-ID --supersedes old-ID "Use uv."
brainctl pause
brainctl resume
brainctl forget --document memory-ID            # preview
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade  # preview source session
brainctl forget --document memory-ID --cascade --apply
brainctl retention                               # preview 90-day evidence pruning
brainctl retention --apply
```

<a id="data-and-privacy"></a>

## 数据与隐私

- 机密信息会在写入 SQLite 或 Markdown 之前进行脱敏。
- 不会归档完整的工具输出和 shell 命令；只会归档安全指针。
- 归档是经过脱敏的明文，并未在应用层加密。请使用 FileVault、BitLocker 或 LUKS。
- `remember` 默认限定在项目范围内。仅在确有需要时使用 `--global`。
- 保留机制会移除过期的会话和交接证据，但绝不会移除明确的持久记忆；
  不带 `--apply` 时只会预览。
- 普通文档删除只会移除该页面。先用 `--cascade` 预览对源对话的影响，
  再在同一命令中添加 `--apply` 以同时删除两者。
- 使用 `WIKIBRAIN_HOME` 或 `brainctl --home PATH` 覆盖状态数据的位置。

通过 Homebrew 或 pipx 卸载不会删除单独的大脑目录。

<a id="project-documentation"></a>

## 项目文档

- [架构与信任边界](ARCHITECTURE.md)
- [命令参考](plugins/wikibrain/skills/wikibrain/references/command-reference.md)
- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [变更日志](CHANGELOG.md)

WikiBrain 采用 [MIT 许可证](LICENSE)分发。
