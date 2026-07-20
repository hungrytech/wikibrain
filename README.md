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
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.2/scripts/install-windows.ps1" `
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
