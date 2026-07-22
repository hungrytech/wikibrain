# Changelog

All notable changes to WikiBrain are documented in this file.

The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.8] - 2026-07-23

### Security

- Bound official release-policy retrieval by a monotonic 2.0-second request budget
  plus a 0.5-second native cleanup reserve in a directly managed subprocess. The
  worker also has a self-deadline, and timeout cleanup verifies OS-native
  releases descriptors/handles only after OS-confirmed process death, and redirects are
  rejected before urllib can contact any target while retaining the socket timeout and
  response-size cap.
- Validate cached policy files before reading them: POSIX caches must be non-symlink
  regular files owned by the current user, free of extended ACLs, and not group/other
  writable; Windows opens the cache with a non-following kernel handle and validates
  the same handle's regular-file/reparse state, final configured-home containment,
  owner SID, and DACL.
- Reject policy timestamps before the schema-v1 epoch or more than five minutes in
  the future, and reject rollback below the last accepted `updated_at`. Cache schema
  v2 preserves that rollback floor across negative-cache entries and system-clock
  regressions while reading and migrating existing schema-v1 caches.

## [0.1.7] - 2026-07-22

### Added

- A remotely managed `minimum_supported_version` policy for clients that include
  the version check, with strict schema and SemVer validation, a private 24-hour
  cache with bounded reads and an exact internal schema, exact-URL HTTPS retrieval
  from the official repository, duplicate-key/parser-depth/timestamp-overflow
  rejection, and platform-specific Homebrew or native-Windows/pipx remediation
  when operational commands are blocked.
- Regression coverage for supported, unsupported, offline, malformed, stale/future
  cache, redirect, strict-schema, dry-run, and safety-command behavior.

### Security

- Version-policy network and parsing failures, including truncated HTTP response
  bodies, fail open and are negatively cached to preserve local-first offline
  operation without repeated hook latency. Version, diagnosis, setup, pause, forget, retention, and owned hook/skill removal remain
  available even when the installed release is below the minimum; no workspace,
  prompt, or memory content is sent by the policy check.

## [0.1.6] - 2026-07-22

### Fixed

- Reject empty `--clients` values instead of silently returning or applying an
  empty client set.
- Deduplicate comma-separated clients while preserving their input order.

## [0.1.5] - 2026-07-22

### Fixed

- Include native Grok skills in `brainctl status` and let `brainctl hooks status`
  default to Claude-compatible clients while supporting explicit
  `--clients grok` inspection.
- Vendor Cython and PyYAML in the Homebrew formula, declare `libyaml`, and make
  bottle CI reject unrelated dependency artifacts while testing Intel macOS
  source installs explicitly.

## [0.1.4] - 2026-07-22

### Added

- Official Grok Build CLI support with native lifecycle-hook installation,
  provider/session/workspace provenance, a Grok skill target, and explicit
  `brainctl recall` and `brainctl remember` workflows.
- Runtime-verified Grok payload normalization for lowercase event values such as
  `user_prompt_submit` and `stop`, including `promptId`, `transcriptPath`,
  timestamp, and termination-reason provenance.
- English, Korean, Japanese, and Simplified Chinese Grok setup documentation,
  including the official executable installer, native and Claude-compatible
  hook paths, duplicate-hook avoidance, and passive-stdout limitations.
- Adaptive long-term memory promotion for session and handoff evidence actually
  injected across three distinct consumer provider/session pairs, three UTC
  days, and two provider/session/day uses within a rolling 60-day window.
- Schema v9 bounded usage accounting and source-to-adaptive provenance, with
  same-provider/session/day replay deduplication, workspace isolation, supersession
  exclusion, registration-time stale-promotion blocking, and propagation of later
  source supersession to the adaptive derivative. Source-ID-only adaptive paths
  prevent concurrent title variants from leaving unregistered plaintext files.
- English, Korean, Japanese, and Simplified Chinese documentation distinguishing
  90-day short-term evidence, adaptive long-term memory, and explicit long-term
  memory.
- Explainable adaptive-promotion scoring with a default `0.65` threshold across
  session diversity, UTC-day persistence, final-context injection recurrence,
  query-backed use, and provider diversity. Hard safety gates remain mandatory;
  non-injected search hits contribute nothing, and each promoted Markdown page
  and document metadata records the score, threshold, and weighted components.
- Direct-search provenance for query-backed scoring; related and recent-fallback
  context no longer receives search credit.
- First-writer-wins adaptive publication keeps concurrent Markdown evidence and
  SQLite promotion metadata from different attempts from being mixed; rollback
  compensation runs before releasing the SQLite writer lock.

### Changed

- Grok passive hooks now skip automatic recall computation and injection-usage
  accounting because Grok ignores passive stdout. This prevents undelivered
  evidence from contributing to adaptive-memory promotion. Grok `Stop` archives
  an explicit unavailable-response placeholder rather than reading the external
  transcript without a bounded redaction contract.
- Retention now uses conversation capture/completion time rather than Markdown
  registration time and no longer lets stale promotion work protect expired
  turns indefinitely.
- Pending prompt deduplication without a provider turn ID now remains idempotent
  for the full lifetime of the open turn instead of only five seconds.
- Completed handoff outbox rows migrate into document metadata; forget and
  retention compact replay fingerprints into one canonical tombstone per source
  and then one tombstone per otherwise empty session.
- Forget receipts, installer backups, and managed-skill backups are bounded, and
  retention removes empty calendar directories.
- Retention preserves adaptive memory after its raw source expires, while an
  explicit source forget also deletes the derived adaptive page and reports it
  in dry-run output and the deletion receipt.

## [0.1.3] - 2026-07-21

### Added

- English and Korean Getting Started guides covering installation,
  initialization, first-session activation, a reversible memory smoke test,
  and conversational cross-session verification.
- An explicit trust-free Codex manual mode using the installed WikiBrain skill
  and `brainctl remember`/`recall`, including a `--no-hooks` setup example.

### Changed

- `brainctl init` now reports manual-command, skill, and automatic-hook
  readiness separately instead of implying that installed Codex hooks are
  already active.
- `brainctl doctor` now states that it validates Codex hook files and
  executables without inspecting or changing Codex's persisted hook trust.
- Documented why normal Codex automatic hooks require `/hooks` review, why the
  one-invocation dangerous bypass is not installed, and why administrator
  managed hooks are outside WikiBrain's personal-install trust boundary.

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
