# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain: a young researcher and friendly brain mascot beneath a glowing connected knowledge map">
</p>

<p align="center"><strong>Open source · Local-first · User-owned · Markdown-native</strong></p>

<p align="center">
  <strong>English</strong> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

WikiBrain is an [MIT-licensed](LICENSE) shared second brain for Claude Code,
Codex, and Grok Build. It captures redacted conversation handoffs through lifecycle hooks,
stores durable context as readable Markdown, and uses
[Wikimap](https://github.com/dhha22/wikimap) for local, source-aware recall.

## Contents

- [Why WikiBrain](#why-wikibrain)
- [Getting Started](#getting-started)
- [How it works](#how-it-works)
- [Short-term and long-term memory](#memory-lifecycle)
- [Verified benchmark](#verified-benchmark)
- [Installation and trust](#installation-and-trust)
- [Daily commands](#daily-commands)
- [Data and privacy](#data-and-privacy)
- [Project documentation](#project-documentation)

<a id="why-wikibrain"></a>

## Why WikiBrain

| Need | What WikiBrain provides |
| --- | --- |
| Continue across agents | Claude, Codex, and Grok can recover the same project-scoped context. |
| Separate evidence from memory | 90-day evidence, adaptive memory, and explicit long-term memory remain distinguishable. |
| Preserve user ownership | Markdown is the durable source; the Wikimap index is disposable. |
| Recover from transient failures | Archive, promotion, and relation-cleanup outboxes retry interrupted work. |
| Stay in control | Capture is allowlisted, pauseable, inspectable, previewable, and deletable. |

WikiBrain does not crawl your repositories or automatically turn every
conversation into permanent truth. Only lifecycle payloads are captured.
Explicit “remember this” requests become user-authored long-term memory;
repeatedly injected evidence can become separately labeled adaptive memory.

<a id="getting-started"></a>

## Getting Started

### 1. Install and initialize

macOS or Linux:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

For native Windows, use the reviewable [PowerShell installer](#native-windows).
`brainctl init` is the explicit consent boundary: installation alone does not
change Claude or Codex settings.

### 2. Start a new agent session

| Client mode | After `brainctl init` | One-time action |
| --- | --- | --- |
| Claude Code automatic memory | Ready in a new session | None; `/hooks` is available for inspection. |
| Codex manual memory | Ready immediately | Use `brainctl remember` and `brainctl recall`. |
| Codex automatic capture and recall | Definitions are installed but initially untrusted | Start a new session, open `/hooks`, inspect the five WikiBrain hooks, and trust their current hash. |
| Grok automatic capture | Ready through Grok's Claude-hook compatibility; native setup is also available | None for the default setup. Use `brainctl setup --clients grok` only for a Grok-only installation. |
| Grok recall | The installed skill and `brainctl recall` are available | Passive-hook stdout is ignored by Grok, so hook-based automatic context injection is not supported. |

### 3. Run a smoke test

```bash
brainctl remember --global --title "WikiBrain smoke test" \
  "My WikiBrain verification marker is Cobalt-719."
brainctl recall "Cobalt-719"
```

The result should contain `Cobalt-719` and a local Markdown source. Remove the
test page with the document ID returned by `remember`:

```bash
brainctl forget --document DOCUMENT_ID --apply
```

<a id="how-it-works"></a>

## How it works

```text
Claude Code hooks ─┐
Codex hooks ───────┼─ brainctl ─┬─ SQLite WAL: receipts, queues, relations
Grok hooks ────────┘            ├─ Markdown vault: durable readable truth
                                └─ Wikimap: disposable local search index
```

1. `UserPromptSubmit` redacts and records the prompt, then recalls relevant
   project memory.
2. `Stop` pairs the final response with the prompt and archives the turn as an
   immutable Markdown handoff.
3. Explicit “remember” requests create durable memory pages through an
   independent retry queue. Repeatedly injected short-term evidence can create a
   separate adaptive-memory page after it clears the usage gate.
4. `SessionStart` restores recent and query-relevant context for the same Git
   workspace.
5. Typed `relates-to` and `supersedes` links connect evidence and suppress stale
   guidance without deleting its provenance.

[Grok Build](https://docs.x.ai/build/features/hooks) officially supports `SessionStart`, `UserPromptSubmit`,
`PostToolUse`, `Stop`, and `PostCompact`, and automatically reads Claude Code
hooks and skills. WikiBrain detects Grok's hook environment so compatible
Claude hook calls are attributed to provider `grok`. Grok's passive-hook
contract ignores stdout, however, so WikiBrain captures Grok evidence
automatically but does not count or claim hook-injected recall. Ask Grok to use
the WikiBrain skill or run `brainctl recall` when prior context is needed.
Grok's observed runtime payload uses lowercase event values such as
`user_prompt_submit` and `stop`; WikiBrain normalizes them to its canonical
lifecycle names. `UserPromptSubmit` provides `prompt` and `promptId`. The
observed `Stop` payload provides `transcriptPath`, `promptId`, and `reason`, but
no assistant text, so WikiBrain archives an explicit unavailable placeholder
and does not parse the external transcript automatically.

For a Grok-only setup, first install the official `grok` executable as described
in the [Grok Build overview](https://docs.x.ai/build/overview); xAI currently
publishes `curl -fsSL https://x.ai/cli/install.sh | bash`. Review remote install
scripts before executing them. Then use `brainctl init --clients grok`. Do not
install both native Grok hooks and Claude hooks unless Grok's Claude-hook
scanner is disabled; otherwise Grok can execute both definitions for the same
event.

Each Git repository is an isolated memory scope. Only
`brainctl remember --global` deliberately crosses project boundaries. Hooks are
fail-open: a malformed event, busy database, missing Wikimap executable, or
timeout cannot block the coding agent.

See [ARCHITECTURE.md](ARCHITECTURE.md) for persistence, deletion, retry, and
trust-boundary details.

<a id="memory-lifecycle"></a>

## Short-term and long-term memory

| Layer | What it contains | Lifetime |
| --- | --- | --- |
| Short-term evidence | Redacted session turns and compaction handoffs | 90 days by default |
| Adaptive long-term memory | A bounded, redacted snapshot of evidence repeatedly delivered to agent context | Survives ordinary retention; remains labeled `adaptive` |
| Explicit long-term memory | A fact or preference created with “remember” or `brainctl remember` | Survives ordinary retention; remains labeled `explicit` |

### Adaptive promotion gate and score

Only `session` and `handoff` evidence can be promoted automatically. Explicit
"remember" requests bypass this score and create `explicit` memory instead.
Adaptive candidates first have to pass every hard gate within a rolling 60-day
window:

| Hard gate | Default |
| --- | ---: |
| Distinct consumer provider/session pairs that received the evidence | 3 |
| Distinct UTC days on which it was injected | 3 |
| Deduplicated provider/session/day injections | 2 |

Passing the hard gates is necessary but not sufficient. WikiBrain then computes:

```text
score = 0.30 * min(S / 6, 1)
      + 0.25 * min(D / 6, 1)
      + 0.25 * min(I / 4, 1)
      + 0.10 * (Q / S)
      + 0.10 * min(P / 2, 1)
```

| Symbol | Meaning |
| --- | --- |
| `S` | Distinct consumer provider/session pairs that received the evidence |
| `D` | Distinct UTC injection days |
| `I` | Deduplicated provider/session/day injections |
| `Q` | Distinct injected consumer sessions reached by a direct explicit-query hit |
| `P` | Distinct consumer providers |

The denominators `6`, `6`, and `4` are twice the default hard minimums, so those
repetition components rise gradually and then saturate. Provider diversity
saturates at two providers. Promotion requires `score >= 0.65` by default.
`adaptive_memory_min_score` changes that threshold from 0 to 1; setting it to
`0` restores hard-gate-only behavior.

A replay from the same provider/session pair on the same UTC day counts once.
Manual `brainctl recall` without a genuine consumer session identity does not
count. Only evidence that reaches the final `<memory-data>` contributes, and only
a direct search hit receives query-backed credit; related and recent-fallback
records do not. Memory pages cannot promote themselves, workspace counters never
mix, and superseded evidence is ineligible. If a promoted source is superseded
later, its adaptive derivative is hidden from recall too.

The formula is a deterministic initial policy, not a learned probability. The
promoted page and document metadata record the total score, threshold, and each
weighted component. A candidate below the threshold remains pending and is
reconsidered the next time it is used.

Promotion writes at most 2,000 characters of the source-verified evidence to a
new Markdown page with the source document ID, usage counts, promotion time,
and `memory_kind: adaptive`. It is retained context, not a declaration that the
content is true. The original 90-day evidence can expire while this smaller
page remains. Explicitly forgetting the source also removes its derived
adaptive page; normal retention does not.

<a id="verified-benchmark"></a>

## Verified benchmark

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain final-context benchmark: 8 of 8 context contracts passed, required context atom recall was 100 percent, clean-context rate was 100 percent, and forbidden atom exposure was zero">
</p>

The fixed-corpus contract benchmark inspects the final `<memory-data>` given to
the agent, not search latency. Query checks disable recent-item fallback; a
separate handoff check validates recent-context restoration through
`SessionStart`. A check passes only when every required fact is present and
stale, secret, or cross-workspace facts are absent.

| Final-context contract | Value |
| --- | ---: |
| Context checks | **8/8 passed** |
| Required context atoms | **21/21 · 100.00%** |
| Clean contexts | **8/8 · 100.00%** |
| Forbidden atom exposure | **0/4 · 0.00%** |
| Environment | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

### Labeled final-context quality

<p align="center">
  <img src="docs/assets/benchmark-retrieval-quality-v1.svg" width="920" alt="WikiBrain context recall benchmark: Context Recall 87.50 percent, Context Precision 79.17 percent, Context F1 80.56 percent, required-fact recall 90.91 percent, and zero forbidden-context exposure across 12 labeled queries">
</p>

A separate 14-document, 12-query corpus measures what production
`RecallService.context()` actually injects. Each query labels relevant records,
minimum required facts, and forbidden stale, deleted, or cross-workspace
records. The raw query and context text are discarded after scoring.

| Final-context quality | Value |
| --- | ---: |
| Context Recall / Precision | **87.50% / 79.17%** |
| Context F1 / required-fact recall | **80.56% / 90.91%** |
| Forbidden context exposure | **0/12 queries · 0.00%** |
| Ingestion acceptance | **14/14 · 100.00%** |
| Retrieval Recall@1 / Recall@3 *(diagnostic)* | **69.44% / 87.50%** |
| MRR / nDCG@3 *(diagnostic)* | **87.50% / 81.35%** |

Context Recall asks whether the required records reached the final prompt.
Context Precision asks how much of the injected record set was relevant. The
required-fact score separately catches a selected document whose useful
evidence was missing or truncated. Ranked retrieval metrics remain diagnostic:
they help locate a search/ranking cause, but they are not the headline measure
of second-brain quality.

<details>
<summary><strong>What the eight checks cover</strong></summary>

| Check | Contract |
| --- | --- |
| Current decision | New `uv` guidance suppresses superseded `pip` guidance. |
| Evidence links | `relates-to` and `supersedes` edges survive recall. |
| People and project | Owner and backup-reviewer context remains recoverable. |
| Source provenance | Document ID, Markdown path, and capture time accompany evidence. |
| Workspace isolation | A marker from another repository does not cross scope. |
| Secret redaction | A synthetic API secret is absent from durable storage and recall. |
| Global preference | An intentional global preference is available in project scope. |
| Claude → Codex | A Claude session fact appears at Codex session start. |

</details>

Reproduce it from a source checkout:

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

Machine-readable results are
[`second-brain-v1.json`](benchmarks/results/second-brain-v1.json) and
[`retrieval-quality-v1.json`](benchmarks/results/retrieval-quality-v1.json).
Both charts are generated from their JSON files; CI rejects stale SVGs.

To measure your own stored data, copy the
[labeled corpus](benchmarks/corpora/retrieval-quality-v1.json) outside the
repository, replace its synthetic documents and relevance labels, and keep the
result local:

```bash
cp benchmarks/corpora/retrieval-quality-v1.json /tmp/my-brain-quality.json
# Edit /tmp/my-brain-quality.json: documents, queries, relevant,
# required_context facts, and forbidden records.
uv run --locked python -m benchmarks.retrieval_quality \
  --corpus /tmp/my-brain-quality.json \
  --output /tmp/my-brain-quality-result.json
```

The result omits document text and query text, but IDs can still be sensitive;
do not commit a personal corpus or result.

> **Scope:** These are small synthetic regression corpora, not a guarantee for a
> personal vault. They do not measure OCR extraction, concurrent writers,
> answer faithfulness after an LLM consumes the retrieved context, or multi-hop
> graph reasoning. A personal labeled corpus is required to claim accuracy on
> your own data.

<a id="installation-and-trust"></a>

## Installation and trust

### macOS or Linux

Use the [Getting Started](#getting-started) commands above. Prebuilt bottles
cover Apple Silicon macOS, Intel macOS, and x86_64 Linux.

<a id="native-windows"></a>

### Native Windows

The easiest route is to give your AI coding assistant the official repository
link and ask it to perform and verify the installation. Paste this prompt into
Claude Code, Codex, or another agent that can run commands on your Windows PC:

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

Review the AI's plan and every permission prompt. If you prefer to install it
manually, open PowerShell, download the versioned installer, review it, then run it:

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.5/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

The installer uses Python 3.11+, installs through isolated `pipx`, and runs
`brainctl init` only when `-Initialize` is supplied. Omit that switch to install
the CLI without changing agent settings. Native Windows stores the brain under
`%LOCALAPPDATA%\WikiBrain`. Use the Linux path inside WSL if your agents and
repositories run there.

<details>
<summary><strong>Codex hook trust boundary</strong></summary>

Manual `brainctl remember` and `brainctl recall` work without hook approval.
Automatic prompt capture and context injection do not: Codex skips unmanaged
command hooks until their current definition hash is reviewed in `/hooks`.

WikiBrain never adds `--dangerously-bypass-hook-trust` to aliases, wrappers, or
launch settings. The only persistent no-review route is an administrator-managed
hook policy delivered through system, MDM, cloud, or `requirements.toml`.

For a trust-free, manual-only setup with no pending hook warning:

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "A durable fact"
brainctl recall "that durable fact"
```

See the official [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks).

</details>

### What `brainctl init` changes

`brainctl init` is idempotent. It backs up existing settings, structurally
merges only WikiBrain-owned entries, and preserves unrelated hooks and skills.

| Purpose | macOS/Linux | Native Windows |
| --- | --- | --- |
| Brain state | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| Claude hooks | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex hooks | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Grok hooks (Grok-only opt-in) | `${GROK_HOME:-~/.grok}/hooks/wikibrain.json` | `%GROK_HOME%\hooks\wikibrain.json` or `%USERPROFILE%\.grok\hooks\wikibrain.json` |
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Grok skill (Grok-only opt-in) | `${GROK_HOME:-~/.grok}/skills/wikibrain/` | `%GROK_HOME%\skills\wikibrain\` or `%USERPROFILE%\.grok\skills\wikibrain\` |
| Codex/Agents skill | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |

| Event | WikiBrain action |
| --- | --- |
| `SessionStart` | Register the session and inject relevant project memory. |
| `UserPromptSubmit` | Redact and capture the prompt, then recall context. |
| `PostToolUse` | Store only safe tool, file, and work-directory pointers. |
| `Stop` | Archive the completed turn, promote explicit memories, refresh search. |
| `PostCompact` | Archive an available compaction summary as a handoff. |

Review or remove only WikiBrain-owned integration:

```bash
brainctl init --dry-run --json
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

### Local development

```bash
uv sync --locked
uv run brainctl init
uv run python -m unittest discover -s tests -v
```

<a id="daily-commands"></a>

## Daily commands

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

## Data and privacy

- Secrets are redacted before SQLite or Markdown writes.
- Full tool output and shell commands are not archived; only safe pointers are.
- The archive is redacted plaintext, not application-level encrypted. Use
  FileVault, BitLocker, or LUKS.
- `remember` is project-scoped by default. Use `--global` only intentionally.
- Retention removes expired session and handoff evidence, but preserves both
  adaptive and explicit long-term memory. It is preview-only without `--apply`.
  The cutoff uses the evidence `captured_at` time, not its later registration
  time; stale promotion work does not protect expired turns indefinitely.
- Completed handoff rows are compacted into document metadata. Each forgotten
  source keeps one canonical anti-replay tombstone, and retention folds all
  tombstones from an otherwise empty session into one session tombstone. These
  fingerprints do not expire because doing so could resurrect replayed content.
  WikiBrain keeps the newest 100 forget receipts and three installer backups per
  target, and removes empty calendar directories after retention.
- Explicitly forgetting short-term evidence also removes its derived adaptive
  memory. A plain memory deletion removes that page. Use `--cascade` to preview
  the full source-session impact, then repeat it with `--apply` to erase it.
- Override the state location with `WIKIBRAIN_HOME` or `brainctl --home PATH`.

Homebrew or pipx uninstall does not delete the separate brain directory.

<a id="project-documentation"></a>

## Project documentation

- [Architecture and trust boundaries](ARCHITECTURE.md)
- [Command reference](plugins/wikibrain/skills/wikibrain/references/command-reference.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

WikiBrain is distributed under the [MIT License](LICENSE).
