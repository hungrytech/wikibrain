# Contributing

WikiBrain sits on a privacy-sensitive boundary between coding agents and a
personal knowledge vault. Changes should keep capture local, scoped, redacted,
inspectable, and fail-open.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
WIKIMAP_BIN=.venv/bin/wikimap \
  .venv/bin/python -m unittest tests.test_real_wikimap -v
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/pip check
```

Add a regression test for every capture, deletion, recovery, or trust-boundary
change. Never include a real credential in a fixture.

## Pull requests

- Keep each pull request focused on one user-visible outcome.
- Explain any new persisted field and its deletion behavior.
- Document changes to hooks, user settings, retention, or Homebrew packaging.
- Confirm that unrelated Claude and Codex configuration remains untouched.
