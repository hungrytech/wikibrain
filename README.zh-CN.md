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

WikiBrain 是一个采用 [MIT 许可证](LICENSE)的共享第二大脑，供 Claude Code、
Codex 和 Grok Build 使用。它通过生命周期钩子捕获经过脱敏的对话交接信息，
将持久上下文存储为可读的 Markdown，并使用
[Wikimap](https://github.com/dhha22/wikimap) 在本地进行可感知来源的检索。

## 目录

- [为什么选择 WikiBrain](#why-wikibrain)
- [快速开始](#getting-started)
- [工作原理](#how-it-works)
- [短期记忆与长期记忆](#memory-lifecycle)
- [经验证的基准测试](#verified-benchmark)
- [安装与信任](#installation-and-trust)
- [日常命令](#daily-commands)
- [数据与隐私](#data-and-privacy)
- [项目文档](#project-documentation)

<a id="why-wikibrain"></a>

## 为什么选择 WikiBrain

| 需求 | WikiBrain 提供的能力 |
| --- | --- |
| 跨智能体继续工作 | Claude、Codex 和 Grok 可以恢复同一项目范围内的上下文。 |
| 将证据与记忆分开 | 90 天证据、自适应记忆和显式长期记忆彼此可区分。 |
| 保障用户所有权 | Markdown 是持久的数据源；Wikimap 索引可以随时丢弃。 |
| 从暂时性故障中恢复 | 归档、提升和关系清理发件箱会重试中断的工作。 |
| 保持掌控 | 捕获范围采用允许列表，并且可以暂停、检查、预览和删除。 |

WikiBrain 不会抓取你的代码仓库，也不会自动将每次对话都转化为永久事实。
它只捕获生命周期载荷。明确提出的“记住这个”请求会成为用户指定的长期记忆；
反复实际注入上下文的证据则可能成为另行标记的自适应长期记忆。

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
| Grok 自动捕获 | 可通过 Grok 的 Claude 钩子兼容功能使用，也支持原生设置 | 默认设置无需额外操作。仅在 Grok 专用安装中使用 `brainctl setup --clients grok`。 |
| Grok 检索 | 可使用已安装的技能和 `brainctl recall` | Grok 会忽略 passive hook 的 stdout，因此不支持通过钩子自动注入上下文。 |

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
Codex hooks ───────┼─ brainctl ─┬─ SQLite WAL: receipts, queues, relations
Grok hooks ────────┘            ├─ Markdown vault: durable readable truth
                                └─ Wikimap: disposable local search index
```

1. `UserPromptSubmit` 对提示词进行脱敏和记录，然后检索相关的项目记忆。
2. `Stop` 将最终响应与提示词配对，并将本轮对话归档为不可变的 Markdown 交接记录。
3. 明确提出的“记住”请求通过独立的重试队列创建持久记忆页面。反复注入的短期
   证据在达到使用门槛后，会创建单独的自适应记忆页面。
4. `SessionStart` 为同一 Git 工作区恢复近期上下文以及与查询相关的上下文。
5. 带类型的 `relates-to` 和 `supersedes` 链接连接证据并抑制过时指导，
   同时不会删除其出处。

[Grok Build 官方钩子文档](https://docs.x.ai/build/features/hooks)支持
`SessionStart`、`UserPromptSubmit`、`PostToolUse`、`Stop`
和 `PostCompact`，并会自动读取 Claude Code 的钩子与技能。WikiBrain 会检测 Grok
的钩子环境，因此通过 Claude 兼容路径运行的事件也会记录为 provider `grok`。
但是，Grok 会忽略 passive hook 的 stdout。因此 WikiBrain 会自动捕获 Grok
证据，但不会把未实际交付的检索结果计为上下文注入，也不会声称支持自动检索。
需要以前的上下文时，请让 Grok 使用 WikiBrain 技能或运行 `brainctl recall`。
实测 runtime payload 的 event 值为 `user_prompt_submit`、`stop` 等小写形式，
WikiBrain 会将其规范化为内部 lifecycle 名称。`UserPromptSubmit` 提供 `prompt` 和
`promptId`。实测 `Stop` payload 提供 `transcriptPath`、`promptId` 和 `reason`，
但不含 assistant 正文。因此 WikiBrain 会归档“正文不可用”的 placeholder，且不会
自动读取外部 transcript。

若只使用 Grok，请先按照 [Grok Build overview](https://docs.x.ai/build/overview)
安装官方 `grok` 可执行文件。xAI 当前发布的命令是
`curl -fsSL https://x.ai/cli/install.sh | bash`；执行远程安装脚本前应先审阅。
然后运行 `brainctl init --clients grok`。除非已禁用 Grok 的 Claude
钩子扫描器，否则不要同时安装原生 Grok 钩子和 Claude 钩子；同一事件可能会执行
两套定义。

每个 Git 仓库都是相互隔离的记忆范围。只有 `brainctl remember --global`
会有意跨越项目边界。钩子采用故障开放机制：格式错误的事件、繁忙的数据库、
缺失的 Wikimap 可执行文件或超时都不会阻塞编码智能体。

有关持久化、删除、重试和信任边界的详细信息，请参阅
[ARCHITECTURE.md](ARCHITECTURE.md)。

<a id="memory-lifecycle"></a>

## 短期记忆与长期记忆

| 层级 | 保存内容 | 生命周期 |
| --- | --- | --- |
| 短期记忆证据 | 已脱敏的 session turn 与 compaction handoff | 默认 90 天 |
| 自适应长期记忆 | 反复交付给智能体上下文的证据的限长、脱敏快照 | 普通 retention 后仍保留，并标记为 `adaptive` |
| 显式长期记忆 | 用户通过“记住”或 `brainctl remember` 指定的事实或偏好 | 普通 retention 后仍保留，并标记为 `explicit` |

### 自适应提升条件与评分

只有 `session` 和 `handoff` 证据可以自动提升。用户明确要求“记住”的内容不经过此
评分，而是直接成为 `explicit` 长期记忆。自适应候选项必须先在最近 60 天内满足全部
硬门槛：

| 硬门槛 | 默认值 |
| --- | ---: |
| 收到该证据的不同 consumer provider/session pair | 3 |
| 证据被注入的不同 UTC 日期 | 3 |
| 去重后的 provider/session/day 注入次数 | 2 |

仅满足硬门槛还不会提升。WikiBrain 接着计算：

```text
score = 0.30 * min(S / 6, 1)
      + 0.25 * min(D / 6, 1)
      + 0.25 * min(I / 4, 1)
      + 0.10 * (Q / S)
      + 0.10 * min(P / 2, 1)
```

| 符号 | 含义 |
| --- | --- |
| `S` | 收到该证据的不同 consumer provider/session pair 数量 |
| `D` | 证据被注入的不同 UTC 日期数量 |
| `I` | 去重后的 provider/session/day 注入次数 |
| `Q` | 通过显式 query 的 direct hit 注入证据的不同 consumer session 数量 |
| `P` | 不同 consumer provider 数量 |

分母 `6`、`6` 和 `4` 分别是默认硬门槛的两倍，因此重复相关分项会随使用逐步增加，
并在这些值处饱和。Provider 多样性在两个 provider 处饱和。默认提升条件为
`score >= 0.65`。可使用 `adaptive_memory_min_score` 在 0 到 1 之间调整阈值；将其
设为 `0` 可恢复仅使用硬门槛的旧行为。

同一 provider/session pair 在同一 UTC 日期再次收到该证据时只计一次。没有真实
consumer session identity 的手动 `brainctl recall` 不计数。只有进入最终
`<memory-data>` 的证据才贡献分数，query-backed 分数只授予显式搜索的 direct hit；
related 和 recent fallback 结果不计入。Memory 页面不能提高自身的提升分数，使用量
不会跨 workspace 合并，superseded 证据也不具备提升资格。若 source 在提升后被
superseded，其派生的 adaptive memory 也会从 recall 中隐藏。

该公式是确定性的初始策略，而不是学习得到的概率。提升页面和 document metadata
会记录总分、阈值及各加权分项。低于阈值的候选项会保持 pending，并在下次使用时
重新评估。

提升时只把经 source 验证的证据中最多 2,000 个字符写入新的 Markdown 页面，并
记录 source 文档 ID、使用次数、提升时间及 `memory_kind: adaptive`。它表示反复
有用的上下文，不代表系统自动断言其内容为真。原始的 90 天证据过期后，这个较小
的自适应记忆仍会保留。普通 retention 不会删除它；显式 forget source 时，派生的
自适应记忆也会一并删除。

<a id="verified-benchmark"></a>

## 经验证的基准测试

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain 最终上下文基准：8 项上下文契约全部通过；必需上下文 atom recall 为 100%，clean context 为 100%，禁止 atom 暴露为 0%">
</p>

固定语料库契约基准检查的是交给智能体的最终 `<memory-data>`，而不是搜索延迟。查询检查会禁用近期条目回退，另一项交接检查验证 `SessionStart` 的近期上下文恢复。只有当所有必需事实都存在，且没有过时指令、机密信息或跨工作区内容时，检查才算通过。

| 最终上下文契约 | 数值 |
| --- | ---: |
| 上下文检查 | **8/8 通过** |
| 必需上下文 atom | **21/21 · 100.00%** |
| Clean context | **8/8 · 100.00%** |
| 禁止 atom 暴露 | **0/4 · 0.00%** |
| 环境 | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

### 带真值标签的最终上下文质量

<p align="center">
  <img src="docs/assets/benchmark-retrieval-quality-v1.svg" width="920" alt="WikiBrain 上下文召回基准：Context Recall 87.50%，Context Precision 79.17%，Context F1 80.56%，必需事实 recall 90.91%，12 个查询中的禁止上下文暴露为 0%">
</p>

另一个包含 14 份文档和 12 个查询的语料库，衡量生产路径 `RecallService.context()` 实际注入的内容。每个查询都标注相关记录、最低必需事实，以及禁止的 stale、已删除或跨工作区记录。查询正文和最终上下文正文在评分后即被丢弃。

| 最终上下文质量 | 数值 |
| --- | ---: |
| Context Recall / Precision | **87.50% / 79.17%** |
| Context F1 / 必需事实 recall | **80.56% / 90.91%** |
| 禁止上下文暴露 | **0/12 个查询 · 0.00%** |
| 摄取接受率 | **14/14 · 100.00%** |
| Retrieval Recall@1 / Recall@3 *（诊断）* | **69.44% / 87.50%** |
| MRR / nDCG@3 *（诊断）* | **87.50% / 81.35%** |

Context Recall 衡量必需记录是否到达最终提示词；Context Precision 衡量注入记录中相关记录的比例。必需事实 recall 还能发现文档虽被选中，但有用证据缺失或被截断的情况。检索排序指标仅用于定位搜索或排序原因，不再作为第二大脑质量的主指标。

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
  --format json \
  --output benchmarks/results/second-brain-v1.json
uv run --locked python scripts/render_benchmark_chart.py

uv run --locked python -m benchmarks.retrieval_quality \
  --corpus benchmarks/corpora/retrieval-quality-v1.json \
  --output benchmarks/results/retrieval-quality-v1.json
uv run --locked python scripts/render_retrieval_quality_chart.py
```

机器可读的结果位于
[`second-brain-v1.json`](benchmarks/results/second-brain-v1.json) 和
[`retrieval-quality-v1.json`](benchmarks/results/retrieval-quality-v1.json)。
两张图表都由相应的 JSON 生成；过时的 SVG 会被 CI 拒绝。

若要衡量你自己存储的数据，请将
[带真值标签的语料库](benchmarks/corpora/retrieval-quality-v1.json)复制到仓库之外，
替换合成文档和 relevance 标签，并把结果保留在本地：

```bash
cp benchmarks/corpora/retrieval-quality-v1.json /tmp/my-brain-quality.json
# 编辑 /tmp 文件中的 documents、queries、relevant、required_context 和 forbidden。
uv run --locked python -m benchmarks.retrieval_quality \
  --corpus /tmp/my-brain-quality.json \
  --output /tmp/my-brain-quality-result.json
```

结果不会记录文档正文或查询正文，但 ID 仍可能敏感；请勿提交个人语料库或结果。

> **范围：** 这些数值来自小型合成回归语料库，并不保证个人知识库的性能。
> 它不衡量 OCR 提取、并发写入、LLM 使用检索上下文后的答案忠实度或多跳图推理。
> 若要声明对你自己数据的准确率，必须使用由你标注真值的个人语料库。

<a id="installation-and-trust"></a>

## 安装与信任

### macOS 或 Linux

请使用上方[快速开始](#getting-started)中的命令。预构建的二进制包覆盖
Apple Silicon macOS、Intel macOS 和 x86_64 Linux。

<a id="native-windows"></a>

### 原生 Windows

最简单的方法是把官方仓库链接交给 AI 编程助手，请它完成安装并进行验证。将以下提示原样粘贴到能够在你的 Windows 电脑上执行命令的 Claude Code、Codex 或其他智能体中：

```text
Install WikiBrain on this Windows machine from https://github.com/hungrytech/wikibrain.
Read the repository's Native Windows instructions first. Before changing anything,
tell me whether native Windows or WSL is the correct path for where my agents and
repositories run. Use the version-pinned installer from the README. Download it,
show me the full PowerShell script, explain the settings changed by initialization,
then stop and wait for my explicit approval before running the script or initializing
WikiBrain. After I approve, install it and finish by running brainctl doctor.
Do not bypass Codex hook trust.
```

确认 AI 给出的计划和所有权限请求后再继续。如果你希望手动安装，请打开 PowerShell，下载指定版本的安装程序，审查后再运行：

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.4/scripts/install-windows.ps1" `
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
| Grok 钩子（仅 Grok 安装时选择） | `${GROK_HOME:-~/.grok}/hooks/wikibrain.json` | `%GROK_HOME%\hooks\wikibrain.json` 或 `%USERPROFILE%\.grok\hooks\wikibrain.json` |
| Claude 技能 | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Grok 技能（仅 Grok 安装时选择） | `${GROK_HOME:-~/.grok}/skills/wikibrain/` | `%GROK_HOME%\skills\wikibrain\` 或 `%USERPROFILE%\.grok\skills\wikibrain\` |
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
- 保留机制会移除过期的会话和交接证据，但会保留自适应和显式长期记忆；
  不带 `--apply` 时只会预览。截止时间依据证据的 `captured_at`，而不是稍后的
  文档注册时间；长期失败的 promotion 不会无限期保护过期 turn。
- 已完成的 handoff 行会压缩到文档 metadata 中。每个已删除 source 只保留一条
  用于防止 replay 的 canonical tombstone；当 session 已无任何内容时，retention
  会把其 tombstone 再压缩为一条 session tombstone。若使 fingerprint 过期，
  重放内容可能复活，因此它们不会过期。forget 回执只保留最新 100 个，
  installer backup 每个目标只保留最新 3 个，并在 retention 后移除空的日期目录。
- 显式 forget 短期证据时，也会删除由其派生的自适应记忆。普通 memory 删除只会
  移除该页面。先用 `--cascade` 预览对完整 source session 的影响，再在同一命令中
  添加 `--apply` 进行删除。
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
