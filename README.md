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
[Wikimap](https://github.com/dhha22/wikimap) for fast source-aware recall.

## Why it is useful

- Claude and Codex can continue each other's work.
- A fresh session starts with relevant recent context.
- Searchable conversation evidence stays separate from trusted long-term
  memory, reducing memory pollution.
- Explicit “remember this” requests have their own durable retry queue, so a
  transient archive failure does not silently lose the promoted memory.
- Wikimap keeps indexing local and low-cost, and its index is disposable.
- Capture is allowlisted, pauseable, inspectable, and deletable.
- Markdown remains yours even if you switch models or coding agents.

## Verified second-brain benchmark

WikiBrain ships a fixed-corpus local regression benchmark for the behaviors that
matter before it can be trusted as a work-context second brain. Query checks run
without recent-document fallback, so a PASS must come from query retrieval (plus
an explicitly linked evidence document), not accidental recency. The eight-document
corpus includes two projects, a changed decision, supporting evidence,
people/ownership context, a global preference, a synthetic secret, and a
Claude-to-Codex handoff.

Run from a source checkout:

```bash
uv run python -m benchmarks.second_brain \
  --iterations 20 \
  --format json \
  --output benchmarks/results/second-brain-v1.json
```

Measured on macOS arm64 with Python 3.13.11 and Wikimap 1.1.0:

| Check | What it verifies | Result |
|---|---|---:|
| Current decision recall | a newer `uv` decision replaces stale `pip` guidance | PASS |
| Decision/evidence link | typed `relates-to` and `supersedes` edges survive recall | PASS |
| Person/project context | ownership and backup-reviewer facts remain recoverable | PASS |
| Source provenance | document ID, Markdown path, and capture time accompany evidence | PASS |
| Workspace isolation | a marker from another project does not cross the scope boundary | PASS |
| Secret redaction | a synthetic API secret is removed before durable storage/recall | PASS |
| Global preference | a user preference is available inside a project scope | PASS |
| Claude → Codex handoff | a Claude session fact appears at Codex session start | PASS |

**Result: 8/8 checks (100%).** For 80 measured recall calls over the fixed
corpus, latency was **24.35 ms p50** and **26.78 ms p95**. The committed
functional result records Python 3.13.11 and Wikimap 1.1.0; supported Wikimap 1.x
versions may rank differently. Latency is a machine- and run-dependent
measurement, not a stable performance guarantee. The machine-readable result is
stored at
[`benchmarks/results/second-brain-v1.json`](benchmarks/results/second-brain-v1.json).
CI verifies its corpus version, iteration count, runner SHA-256, source-manifest
SHA-256, Git commit, generation time, and portable reproduction command.

### What this benchmark exposed and changed

The initial implementation stored provenance-rich Markdown, but each memory was
still an isolated text document. Old and new decisions could both be recalled,
and there was no executable quality gate for relationships, temporal freshness,
scope isolation, or cross-agent continuity. This work added:

- typed `relates-to` and `supersedes` links in Markdown frontmatter and SQLite;
- same-workspace validation before a relationship can be persisted;
- stale-memory suppression when a newer memory supersedes it;
- relationship IDs in the recalled evidence envelope; and
- source-body excerpts when a search engine returns only a frontmatter match.

### Limits of the result

The 100% score is a regression result, not a claim of general intelligence. The
corpus is small and synthetic. It does not yet measure noisy long-running vaults,
semantic paraphrase quality, OCR/document ingestion, concurrent writers,
answer-generation faithfulness, or multi-hop graph reasoning. Relationships are
currently typed links between documents—not yet a first-class graph of people,
projects, tasks, decisions, and validity intervals. Those are the next gaps to
close before treating WikiBrain as a complete organizational brain.

## Getting Started

This is the shortest safe path from installation to a working second brain.
The detailed platform installers and every file they change are documented
below.

### 1. Install and initialize

On macOS or Linux:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

On native Windows, use the reviewable PowerShell installer in
[Native Windows](#native-windows), including its explicit `-Initialize`
switch.

`brainctl init` creates the private brain, installs the WikiBrain skills, and
registers the selected lifecycle hooks. `brainctl doctor` verifies the files,
executables, database, and Wikimap index. It does not inspect or change
Codex's separate hook-trust decision.

### 2. Start a fresh agent session

| Client mode | Ready after `brainctl init`? | One-time next step |
|---|---|---|
| Claude Code automatic memory | Yes, in a new session | None. `/hooks` is available for optional inspection. |
| Codex manual memory | CLI commands work immediately; the skill loads in a new session | `brainctl remember`/`recall` and the installed WikiBrain skill need no hook trust. |
| Codex automatic capture and recall | Definitions are installed, but an untrusted definition is skipped | Start a new Codex session, open `/hooks`, inspect the five WikiBrain definitions, and trust their current hash. |

### 3. Run a smoke test

Save and retrieve a harmless marker without depending on either agent:

```bash
brainctl remember --global --title "WikiBrain smoke test" "My WikiBrain verification marker is Cobalt-719."
brainctl recall "Cobalt-719"
```

The recall result should contain `Cobalt-719` and a local Markdown source. The
`remember` result includes a document ID; remove the test afterward if desired:

```bash
brainctl forget --document DOCUMENT_ID --apply
```

After opening a new Claude session, or a Codex session whose hooks you trusted,
say “remember that my preferred test command is `make check`.” Complete the
turn, start another session in the same repository, and ask which test command
you prefer. This verifies conversational capture, promotion, indexing, and
cross-session recall together.

### Can Codex run from `init` without hook trust?

Partly:

- **Manual commands work immediately.** `brainctl init` installs the shared
  WikiBrain skill for the next Codex session, and both `brainctl remember` and
  `brainctl recall` work before hook approval.
- **Automatic mode cannot be safely enabled by a normal personal installer.**
  Codex requires review of every non-managed command-hook definition and stores
  trust against its current hash. Until then, Codex skips the hook, so
  automatic prompt capture, turn archival, and context injection do not run.
- Codex documents `--dangerously-bypass-hook-trust`, but it applies only to
  that invocation and Codex labels it dangerous. WikiBrain does not add this
  flag to aliases, wrappers, or launch settings.
- The only persistent no-review route is an administrator-managed hook policy
  delivered through system, MDM, cloud, or `requirements.toml` configuration.
  Those hooks are policy-enforced and cannot be disabled in the user hook
  browser. WikiBrain intentionally does not claim or modify that administrator
  trust boundary.

For an explicit trust-free, manual-only Codex setup with no pending hook
warning:

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "A durable fact"
brainctl recall "that durable fact"
```

This installs the Codex/Agents skill but disables automatic lifecycle capture
and recall. See the official [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks)
for the host-enforced trust model.

## Install

Installation and initialization are deliberately separate:

- The package installer adds `brainctl` and Wikimap.
- `brainctl init` is the explicit consent boundary that creates the private
  brain and edits Claude/Codex hook settings.

### macOS or Linux with Homebrew

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

Prebuilt bottles are published for Apple Silicon macOS, Intel macOS, and
x86_64 Linux. Installing the bottle does not require `xcrun`, an SDK lookup, or
a local source build.

### Native Windows

Open PowerShell. The following downloads the versioned installer, lets you
review it, then installs and initializes WikiBrain:

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

The installer:

1. uses an existing Python 3.11 or newer, or installs Python 3.13 for the
   current user with `winget`;
2. installs `pipx`;
3. installs WikiBrain in an isolated environment directly from the versioned
   GitHub source archive, so Git and developer tools are not required;
4. runs `brainctl init` and `brainctl doctor` only because `-Initialize` was
   explicitly supplied.

Omit `-Initialize` to install the CLI without changing Claude or Codex
settings. The installer prints the exact `brainctl init` command to run later.
Native Windows stores the brain under `%LOCALAPPDATA%\WikiBrain`.

If your agents and repositories run inside WSL, use the Homebrew/Linux path
inside WSL instead. Native Windows and WSL have different home directories, so
choose the environment where Claude Code or Codex actually runs.

### Ask a local coding agent to install it

If terminal setup is unfamiliar, give this public repository link to Claude
Code, Codex, or another coding agent that has shell access to your computer:

```text
Install this for me and verify it: https://github.com/hungrytech/wikibrain
```

For a review-first installation, paste:

```text
Install WikiBrain from https://github.com/hungrytech/wikibrain on this
computer. Read the README first and use the supported installer for my
operating system. Before running brainctl init, show me the settings files,
hook events, backup paths, and commands it will add. Preserve all unrelated
Claude and Codex settings. Then initialize it, run brainctl doctor, and report
the result. Do not bypass Codex hook trust; tell me to review it with /hooks.
```

This requires a local coding agent with permission to run commands. A normal
web chat that cannot access your computer cannot perform the installation.

### Local development

macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/brainctl init
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\brainctl.exe init
```

## Exactly what `brainctl init` changes

`brainctl init` is idempotent: running it again refreshes WikiBrain-owned
entries without duplicating them. It performs these operations:

1. Creates the private SQLite state, Markdown vault, logs, receipts, and a
   durable hook shim.
2. Backs up an existing settings JSON before changing it.
3. Structurally merges five WikiBrain handlers into each selected client.
4. Preserves unrelated settings, hooks, and custom skills.
5. Installs the WikiBrain skill for Claude and the shared Agents skill location
   used by Codex.
6. Records the exact settings and executable paths in `installations.json` so
   `brainctl doctor` checks the files that were actually configured.

### Files created or updated

| Purpose | macOS/Linux | Native Windows |
|---|---|---|
| Brain state | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| Fail-open hook shim | `.../bin/wikibrain-hook` | `...\bin\wikibrain-hook.ps1` |
| Claude user hooks | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex user hooks | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Codex/Agents skill | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |
| Installation ledger | `.../installations.json` | `...\installations.json` |

Before changing an existing JSON file, WikiBrain creates a sibling backup such
as:

```text
settings.json.wikibrain.20260720T142305123456Z.bak
hooks.json.wikibrain.20260720T142305123456Z.bak
```

No backup is necessary when the file did not exist or the desired definitions
are already current.

### Hook events installed

| Event | Matcher | Timeout | WikiBrain action |
|---|---|---:|---|
| `SessionStart` | `startup\|resume\|clear\|compact` | 5 s | Registers the session and injects relevant project memory as `additionalContext`. |
| `UserPromptSubmit` | all prompts | 8 s | Redacts and captures the prompt, recalls relevant memory, and injects it before the model responds. |
| `PostToolUse` | `Bash\|Edit\|Write\|NotebookEdit\|apply_patch` | 5 s | Stores only the tool name and safe file/workdir pointers; full tool output and shell commands are omitted. |
| `Stop` | every completed turn | 20 s | Redacts the final response, archives the turn as Markdown, promotes explicit “remember” requests, and refreshes Wikimap. |
| `PostCompact` | `manual\|auto` | 20 s | Archives an available compaction summary as a handoff and refreshes Wikimap. |

Every event also attempts a small, bounded drain of any durable archive retry
queue. A pending background Claude task prevents `Stop` from archiving a
partial response; the later final `Stop` captures it.

The hook process is fail-open. Invalid input, timeout, a busy database, a
missing executable, or a Wikimap failure returns valid empty JSON and exit code
zero so WikiBrain cannot block the coding agent.

### How the JSON merge works

WikiBrain owns only handlers that invoke its persistent shim (or a previous
`brainctl` handler) and end in `hook --provider claude` or
`hook --provider codex`. During setup it:

- replaces stale WikiBrain-owned handlers;
- adds exactly one owned handler for each event;
- retains other handlers in the same event group;
- retains unrelated top-level settings;
- writes the result atomically after making a timestamped backup.

On macOS/Linux the handler calls the POSIX shim. On Windows, Claude uses its
documented PowerShell exec form (`powershell.exe` plus an argument array), and
Codex receives a `commandWindows` override. Both call the same fail-open
PowerShell shim, which then invokes the stable `brainctl.exe` installed by
`pipx`.

### Review and trust

- Claude Code loads user hooks from `~/.claude/settings.json`. Open `/hooks` to
  inspect the registered event, matcher, source, and command.
- Codex discovers user hooks from `~/.codex/hooks.json`, but non-managed
  command hooks do not run until you review and trust their current definition
  hash. Start a new Codex session, open `/hooks`, inspect the five definitions,
  and trust them. A later definition change requires review again.
- `brainctl doctor` verifies that the configured definitions and executable are
  valid. WikiBrain intentionally does not read or change Codex's internal
  persisted trust state, so an `ok` doctor result does not replace `/hooks`
  review.

See the official [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
and [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks) for the
host applications' full hook contracts.

Preview custom locations or a narrower capture boundary before applying:

```bash
brainctl init --dry-run --json
brainctl init --workspace /path/to/project
brainctl init --workspace /path/one --workspace /path/two
```

On first initialization, the workspace allowlist defaults to the current
user's home directory. Each Git repository remains an isolated memory scope.
This is a capture boundary, not a crawler: WikiBrain processes only lifecycle
event payloads emitted by Claude Code and Codex and does not scan home files.

Refresh or remove only WikiBrain-owned integration:

```bash
brainctl setup
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

Homebrew or pipx uninstall does not delete the separate brain directory.

## Daily commands

```bash
brainctl status
brainctl recall "what did we decide about the auth architecture?"
brainctl remember --title "Preferred package manager" "Use uv for Python tools."
brainctl remember --global "I prefer concise Korean answers."
brainctl remember --title "Use uv" --relates-to evidence-ID --supersedes old-ID "Use uv."
brainctl pause
brainctl resume
brainctl forget --document memory-ID        # preview
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade        # preview source session
brainctl forget --document memory-ID --cascade --apply
brainctl forget --session session-ID --provider claude
brainctl forget --session session-ID --provider claude --apply
brainctl retention                          # preview 90-day evidence pruning
brainctl retention --apply
```

## Data and privacy

The default brain layout is:

```text
config.json
installations.json
state.db
vault/
  sessions/
  handoffs/
  memories/
logs/
receipts/
bin/
```

Override it with `WIKIBRAIN_HOME` or `brainctl --home PATH`.

The archive is secret-redacted plaintext, not application-level encrypted.
Enable FileVault, BitLocker, or LUKS and review data before sharing the
directory. POSIX installs use private directory/file modes; Windows data stays
under the current user's local application-data profile and inherits its ACL.

Retention removes only expired session/handoff evidence; explicit durable
memories are never pruned by that command. It also clears expired evidence that
was still waiting in SQLite after an archive failure. It is preview-only unless
`--apply` is supplied.

`remember` is project-scoped by default. Use `--global` only for a preference
that should intentionally appear in every allowed project.

Prompts that begin with an explicit “기억해”/“remember” intent are promoted by
the `Stop` hook. The installed skill avoids issuing a second manual save for
the same request.

Recall records include document and session IDs. Plain `forget --document`
removes only that page; add `--cascade` when the underlying fact must also be
removed from its source conversation. Cascade previews every affected path and
then erases the full source session only with `--apply`.

If Claude and Codex happen to reuse the same session ID, session deletion
requires `--provider` and affects only that client. A cascade is refused when a
page has no source-session lineage, rather than silently performing a partial
deletion.

See [ARCHITECTURE.md](ARCHITECTURE.md) for trust boundaries.
