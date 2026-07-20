# Changelog

All notable changes to WikiBrain are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-07-20

### Added

- Shared local memory for Claude Code and Codex lifecycle hooks.
- Redacted SQLite WAL capture with durable Markdown archives.
- Project-scoped recall through Wikimap with a live-file fallback.
- Explicit long-term memory promotion and durable retry outboxes.
- Pause, status, doctor, recall, remember, forget, cascade, and retention
  commands.
- Safe hook and skill installers that preserve unrelated user configuration.
- Explicit workspace consent on first initialization.
- Release-ready Homebrew Formula template and tap publishing guide.
- Regression coverage for replay, deletion, retention, index races, hook
  failures, secret redaction, and cross-agent recall.
