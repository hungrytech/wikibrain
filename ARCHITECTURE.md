# WikiBrain architecture

WikiBrain is deliberately a bridge, not a fourth knowledge database.

```text
Claude Code hooks ─┐
                   ├─ brainctl ─ SQLite WAL (events and evidence)
Codex hooks ───────┘       │
                           ├─ owned Markdown vault (durable truth)
                           └─ wikimap CLI (disposable index and recall)
```

## Boundaries

- SQLite owns hook receipts, sessions, turns, selected tool pointers,
  document registrations, typed document relations, and deletion tombstones.
- Markdown owns readable durable memory, including `relates_to` and `supersedes`
  frontmatter. Conversation turns are immutable handoff pages, so later edits
  cannot silently rewrite the evidence.
- Wikimap owns indexing and search. WikiBrain only invokes `update`, `search
  --json`, and `doctor`; it never opens Wikimap's internal database or semantic
  log.
- The existing `knowledge-wiki` repository remains an optional read-only source
  until an explicit migration is reviewed.

## Capture and recall

1. `UserPromptSubmit` redacts and stores a prompt.
2. `Stop` pairs `last_assistant_message` with that prompt, writes an immutable
   Markdown handoff atomically, then updates Wikimap.
3. `SessionStart` loads recent handoffs for the same workspace.
4. `UserPromptSubmit` also searches Wikimap with the current prompt.
5. Claude and Codex encode context with the same
   `hookSpecificOutput.additionalContext` contract.

Workspace identity is the nearest Git root inside an allowlisted root. This
keeps two repositories isolated even when the allowlist is the user's home
directory. Only a manual `brainctl remember --global` crosses that boundary.
Zero-argument `brainctl init` uses the current user's home as that allowlisted
root. This is a capture boundary, not a file crawler: WikiBrain receives only
agent lifecycle payloads and never walks the home directory for content.
Repeatable `--workspace` arguments replace the default when narrower roots are
preferred.

Hooks are fail-open. Invalid input, a busy database, a missing Wikimap command,
or a timeout produces valid empty JSON and cannot block the coding agent.
macOS and Linux use a POSIX shim; native Windows uses a PowerShell shim,
Claude's PowerShell exec form, and Codex's `commandWindows` override.
Completed turns and redacted compaction summaries are first persisted as SQLite
outbox work. If Markdown archiving fails, the next hook—including a fresh
`SessionStart`—drains that work before recall, so fail-open does not mean
silent memory loss. Explicit “remember” promotion has an independent outbox, so
a successful session archive cannot mask a failed durable-memory promotion.

Conversation evidence is first-write-wins per provider/session/turn. A variant
retry cannot rewrite SQLite after its immutable Markdown evidence was created.
Claude Stop events with active background tasks are deferred until the later
final Stop.

Every Markdown page must have a live SQLite document registration before recall
will expose it. Writes and erases mark the Wikimap index dirty first; while
dirty, recall searches live Markdown instead of trusting stale index results.
An index generation counter prevents an update that raced with a newer write
from clearing that dirty state. Source-specific deletion tombstones reject late
prompt, response, and compaction retries, so an erased page cannot silently
recreate itself. Session tombstones are keyed by provider plus session ID, so a
Claude deletion cannot erase an unrelated Codex session with the same ID.

## Memory quality

All redacted turns are searchable evidence, but they are not automatically
treated as permanent truth. Only explicit requests such as “기억해” or
“remember this” produce a durable memory page in V1. A durable memory may link
to same-workspace evidence with `relates-to` or replace stale guidance with
`supersedes`; recall follows supporting links one hop and omits superseded
memories. If a newer memory is forgotten, a compact SQLite supersession
tombstone keeps its stale predecessor suppressed. Forgetting a relation target
also removes the dangling ID from surviving Markdown frontmatter. Promotion
into system instructions, `AGENTS.md`, `CLAUDE.md`, or skills is never
automatic.

## Privacy

Capture is limited to configured workspace roots and can be paused. The
zero-configuration root is the user's home directory, while Git repositories
inside it remain separate recall scopes. Secrets are redacted before SQLite or
Markdown writes, full tool results and shell commands are omitted (only
file/workdir pointers remain), files are mode `0600`, and state directories
are mode `0700` on POSIX. Native Windows stores state under the user's local
application-data profile and inherits that profile's ACL.

The archive is redacted plaintext; SQLite WAL is not encryption. Full-disk
encryption is recommended until an optional Keychain-backed encryption layer is
added.

Retention covers registered session/handoff pages and unarchived SQLite turns,
handoffs, and orphan lifecycle events. Source tombstones prevent a late replay
from restoring pruned plaintext. Durable memory pages are excluded.
