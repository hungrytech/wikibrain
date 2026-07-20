# Changelog

All notable changes to WikiBrain are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-07-20

### Added

- Native Windows installation through a reviewable PowerShell bootstrap that
  installs Python when needed, uses pipx, and requires explicit initialization
  consent.
- Native Windows hook integration through a fail-open PowerShell shim, Claude
  PowerShell exec-form handlers, and Codex `commandWindows` overrides.
- A complete Korean README and copyable installation prompts for
  non-developers using a local coding agent.
- Windows CI covering the full test suite, the actual Wikimap CLI, the
  PowerShell installer, hook registration, and hook execution.

### Changed

- Expanded the English and Korean setup guides with every installed hook
  event, matcher, timeout, data action, settings path, backup rule, merge rule,
  trust step, refresh command, and uninstall command.
- Windows now stores default application state under
  `%LOCALAPPDATA%\WikiBrain`.

## [0.1.1] - 2026-07-20

### Changed

- `brainctl init` now defaults the workspace allowlist to the current user's
  home directory, so first-time setup no longer requires `--workspace`.
- Git repositories inside the default root remain isolated recall scopes, and
  WikiBrain continues to capture only agent lifecycle events rather than
  scanning home-directory files.
- Repeatable `--workspace PATH` options remain available when a narrower
  allowlist is preferred.

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
