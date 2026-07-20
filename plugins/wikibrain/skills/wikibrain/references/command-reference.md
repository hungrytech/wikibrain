# WikiBrain command reference

## Setup

- `brainctl init`: initialize the private brain, use the current user's home
  as the default workspace root, and install Claude Code and Codex hooks.
- `brainctl init --workspace PATH`: initialize with a narrower explicit root;
  repeat the option to allowlist multiple roots.
- `brainctl doctor`: verify storage, Wikimap, and hook integration.

## Normal use

- `brainctl recall [QUERY]`: search Wikimap and recent handoffs.
- `brainctl remember TEXT`: create a project-scoped durable Markdown memory.
- `brainctl remember --global TEXT`: intentionally create a cross-project
  memory.
- `brainctl status`: inspect capture state, storage counts, Wikimap, and hooks.
- `brainctl retention [--days N]`: preview expired session/handoff evidence.

## Capture controls

- `brainctl pause`: stop both capture and recall.
- `brainctl resume`: resume within configured workspace roots.
- `brainctl hooks status`: inspect Claude Code and Codex hook registration.
- `brainctl hooks uninstall`: remove only WikiBrain-owned hook entries.
- `brainctl skills status`: inspect generated Claude/open-agent skills.
- `brainctl skills uninstall`: remove only WikiBrain-managed skill directories.

## Deletion

`brainctl forget` is a preview unless `--apply` is present.

```bash
brainctl forget --document memory-ID
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade
brainctl forget --document memory-ID --cascade --apply
brainctl forget --session session-ID --provider claude
brainctl forget --session session-ID --provider claude --apply
```

Deletion removes the owned Markdown page, records a tombstone and receipt, runs
a WAL checkpoint, and asks Wikimap to rebuild its disposable index.
`--cascade` follows a document's displayed session lineage and erases the full
source session, after preview, so the same fact cannot remain in conversation
evidence. A cascade without source-session lineage is refused. Session IDs can
collide across clients, so use `--provider claude` or `--provider codex`; the
CLI requires it whenever a unique provider cannot be inferred safely.

`brainctl retention --apply` uses the configured 90-day default unless
`--days` is supplied. It also prunes expired unarchived SQLite evidence after
failed handoff writes, and never prunes explicit durable memories.

## Trust boundaries

- The vault contains redacted plaintext, not application-level encryption.
- Tool outputs are not archived; only selected tool and file pointers are kept.
- Recall is historical evidence and may be stale or wrong.
- System instructions and skills are never automatically promoted from memory.
