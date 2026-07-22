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
  document registrations, bounded context-usage signals, adaptive-memory
  provenance, typed document relations, and deletion tombstones.
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

Memory has three distinguishable layers. Redacted session and handoff pages are
short-term evidence with a 90-day default retention period. Explicit requests
such as “기억해” or “remember this” create `memory_kind: explicit` long-term
pages. Repeatedly useful short-term evidence can create a separate
`memory_kind: adaptive` long-term page; this is retained context, not an
automatic assertion that its content is true.

Schema v9 records at most one context-usage row per source, UTC day, consumer
provider, and consumer session. Within a rolling 60-day window, raw session or
handoff evidence becomes eligible after three distinct consumer provider/session
pairs, three distinct UTC days, and two provider/session/day injections. Only
records rendered into the final `<memory-data>` count. Same-provider/session/day
replays are idempotent, and manual recalls without a consumer identity do not
count. Explicit and adaptive memory pages do not feed their own counters, superseded
sources are excluded, and each source's workspace remains the counting scope.
Passing the hard gates is necessary but not sufficient. An explainable score must
also meet `adaptive_memory_min_score` (default `0.65`). Its weighted contributions
are session diversity `0.30`, UTC-day persistence `0.25`, final-context injection
recurrence `0.25`, query-backed session ratio `0.10`, and provider diversity
`0.10`. The first three ratios saturate at twice their configured hard minimum;
provider diversity saturates at two providers. Search-only rows with
`injected = 0` contribute to no count or score. Only direct search hits contribute
to the query-backed ratio; one-hop related and recent-fallback records do not.
The score, threshold, and weighted components are persisted in both the adaptive
Markdown evidence block and document metadata, so promotion remains auditable
without rerunning historical queries. Adaptive publication is first-writer-wins:
the SQLite transaction selects one winner and only its in-transaction publication
callback writes the deterministic Markdown path. If publication or commit fails,
filesystem compensation runs before the SQLite write lock is released; it performs
filesystem-only work to avoid self-deadlock and prolonged writer starvation. This
prevents concurrent writers from mixing file evidence and metadata or deleting a
later winner's file.
The default score is an initial deterministic policy, not a learned probability.
Legacy config files receive `0.65`; setting the threshold to `0` restores
hard-gate-only behavior, and pending candidates are reconsidered on their next use.
This score measures repeated utility, not truth or correctness.
A later source supersession is propagated to its adaptive derivative so stale
retained evidence remains hidden. Old usage rows are pruned as new usage arrives.

Promotion copies at most 2,000 redacted characters from the source-backed
evidence into a new Markdown page and records source ID, usage counts, and
promotion time. Adaptive filenames depend only on the source ID under
`memories/adaptive/`, so concurrent promoters converge on one registered path
instead of leaving title-derived plaintext orphans. SQLite keeps
source-to-adaptive provenance without a foreign
key to the short-term source: ordinary retention may remove that source while
the adaptive page remains. An explicit source forget removes its derived page,
including when the source already expired under retention. Source tombstones
and a registration-time existence check prevent an in-flight promotion from
recreating forgotten data. Promotion failure is fail-open for recall and is
retried when qualifying evidence is next injected.

A durable memory may link to same-workspace evidence with `relates-to` or
replace stale guidance with `supersedes`; recall follows supporting links one
hop and omits superseded memories. If a newer memory is forgotten, a compact
SQLite supersession tombstone keeps its stale predecessor suppressed.
Forgetting a relation target also removes the dangling ID from surviving
Markdown frontmatter. Schema v6 queues that cleanup in a durable SQLite outbox
in the same transaction as the deletion; YAML-aware atomic edits are
acknowledged only after success, so an interrupted retention run retries the
cleanup instead of leaving permanent SQLite/Markdown drift. Promotion into
system instructions, `AGENTS.md`, `CLAUDE.md`, or skills is never automatic.

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
from restoring pruned plaintext. Both adaptive and explicit long-term memory
pages are excluded; explicit forget remains authoritative over their derived
provenance.
