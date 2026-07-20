# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain: a young researcher and friendly brain mascot explore a linked knowledge map">
</p>

<p align="center"><strong>Open source · Local-first · User-owned · Markdown-native</strong></p>

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

The intended release path is:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

The source repository, `v0.1.1` tag, and
[`hungrytech/homebrew-tap`](https://github.com/hungrytech/homebrew-tap) are
public. The release-ready Formula generator is under `packaging/homebrew/`.

For local development:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/brainctl init
```

`brainctl init` is the explicit consent boundary: Homebrew itself never edits
Claude or Codex settings. The command backs up existing JSON, structurally
merges WikiBrain-owned hook entries, and preserves unrelated hooks.
On first initialization, the workspace allowlist defaults to the current
user's home directory, so projects work without another path argument. Each
Git repository remains an isolated memory scope, and WikiBrain does not scan
the home directory; it only handles lifecycle events emitted by Claude Code
and Codex. Use repeatable `--workspace PATH` options to replace the default
with narrower roots.

Codex requires one more trust step after hook installation: start a new
session, open `/hooks`, review the exact definitions, and trust them.

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
brainctl hooks uninstall
brainctl skills uninstall
```

## Data

By default state lives under `~/.local/share/wikibrain`:

```text
config.json
state.db
vault/
  sessions/
  handoffs/
  memories/
logs/
receipts/
```

Override it with `WIKIBRAIN_HOME` or `brainctl --home PATH`.

The archive is secret-redacted plaintext, not application-level encrypted.
Enable FileVault/LUKS and review data before sharing the directory.

Retention removes only expired session/handoff evidence; explicit durable
memories are never pruned by that command. It also clears expired evidence that
was still waiting in SQLite after an archive failure. It is preview-only unless
`--apply` is supplied.

`remember` is project-scoped by default. Use `--global` only for a preference
that should intentionally appear in every allowed project.

Prompts that begin with an explicit “기억해”/“remember” intent are promoted by
the Stop hook. The installed skill avoids issuing a second manual save for the
same request.

When current Claude Code reports active background work, WikiBrain waits for
the later final Stop instead of archiving a partial response.

Recall records include document and session IDs. Plain `forget --document`
removes only that page; add `--cascade` when the underlying fact must also be
removed from its source conversation. Cascade previews every affected path and
then erases the full source session only with `--apply`.
If Claude and Codex happen to reuse the same session ID, session deletion
requires `--provider` and affects only that client. A cascade is refused when a
page has no source-session lineage, rather than silently performing a partial
deletion.

See [ARCHITECTURE.md](ARCHITECTURE.md) for trust boundaries.
