# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain: a young researcher and friendly brain mascot beneath a glowing connected knowledge map">
</p>

<p align="center"><strong>Open source · Local-first · User-owned · Markdown-native</strong></p>

<p align="center">
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

WikiBrain is an [MIT-licensed](LICENSE) shared second brain for Claude Code and
Codex. It captures redacted conversation handoffs through lifecycle hooks,
stores durable context as readable Markdown, and uses
[Wikimap](https://github.com/dhha22/wikimap) for local, source-aware recall.

## Contents

- [Why WikiBrain](#why-wikibrain)
- [Getting Started](#getting-started)
- [How it works](#how-it-works)
- [Verified benchmark](#verified-benchmark)
- [Installation and trust](#installation-and-trust)
- [Daily commands](#daily-commands)
- [Data and privacy](#data-and-privacy)
- [Project documentation](#project-documentation)

<a id="why-wikibrain"></a>

## Why WikiBrain

| Need | What WikiBrain provides |
| --- | --- |
| Continue across agents | Claude and Codex can recover the same project-scoped context. |
| Keep evidence separate from memory | Searchable conversation handoffs stay distinct from explicit long-term memories. |
| Preserve user ownership | Markdown is the durable source; the Wikimap index is disposable. |
| Recover from transient failures | Archive, promotion, and relation-cleanup outboxes retry interrupted work. |
| Stay in control | Capture is allowlisted, pauseable, inspectable, previewable, and deletable. |

WikiBrain does not crawl your repositories or automatically turn every
conversation into permanent truth. Only lifecycle payloads are captured, and
only explicit “remember this” requests become durable memories.

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
                   ├─ brainctl ─┬─ SQLite WAL: receipts, queues, relations
Codex hooks ───────┘            ├─ Markdown vault: durable readable truth
                                └─ Wikimap: disposable local search index
```

1. `UserPromptSubmit` redacts and records the prompt, then recalls relevant
   project memory.
2. `Stop` pairs the final response with the prompt and archives the turn as an
   immutable Markdown handoff.
3. Explicit “remember” requests create durable memory pages through an
   independent retry queue.
4. `SessionStart` restores recent and query-relevant context for the same Git
   workspace.
5. Typed `relates-to` and `supersedes` links connect evidence and suppress stale
   guidance without deleting its provenance.

Each Git repository is an isolated memory scope. Only
`brainctl remember --global` deliberately crosses project boundaries. Hooks are
fail-open: a malformed event, busy database, missing Wikimap executable, or
timeout cannot block the coding agent.

See [ARCHITECTURE.md](ARCHITECTURE.md) for persistence, deletion, retry, and
trust-boundary details.

<a id="verified-benchmark"></a>

## Verified benchmark

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain benchmark: 8 of 8 functional checks passed; recall latency was 24.29 milliseconds p50 and 26.88 milliseconds p95 across 80 samples">
</p>

The committed fixed-corpus benchmark runs query-only retrieval with recent-item
fallback disabled. A check passes only when search returns the expected evidence
and excludes forbidden stale, secret, or cross-workspace content.

| Result | Value |
| --- | ---: |
| Functional checks | **8/8 passed** |
| Recall samples | **80** (4 queries × 20 iterations) |
| Latency | **24.29 ms p50 · 26.88 ms p95** |
| Environment | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

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
  --iterations 20 \
  --format json \
  --output benchmarks/results/second-brain-v1.json
python scripts/render_benchmark_chart.py
```

The machine-readable result is
[`benchmarks/results/second-brain-v1.json`](benchmarks/results/second-brain-v1.json).
The chart is generated from that file; CI rejects a stale SVG. Latency varies by
machine and run and is not a stable performance guarantee.

> **Scope:** 100% means only that this small synthetic regression corpus passed.
> It does not measure noisy long-lived vaults, semantic paraphrases, OCR or
> document ingestion, concurrent writers, answer faithfulness, or multi-hop
> graph reasoning.

<a id="installation-and-trust"></a>

## Installation and trust

### macOS or Linux

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

Prebuilt bottles cover Apple Silicon macOS, Intel macOS, and x86_64 Linux.

<a id="native-windows"></a>

### Native Windows

Open PowerShell, download the versioned installer, review it, then run it:

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
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
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
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
- Retention removes expired session and handoff evidence, never explicit durable
  memories, and is preview-only without `--apply`.
- A plain document deletion removes that page. Add `--cascade` to preview and
  erase its source conversation as well.
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
