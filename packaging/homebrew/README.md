# Homebrew release

WikiBrain follows Homebrew's Python virtualenv application pattern with a
supported versioned Python and pinned resources. Wikimap `1.1.0` and the
setuptools build backend are fixed to official PyPI artifacts and SHA-256
digests. The Formula disables networked build isolation after installing that
pinned backend.

## First public release

1. Publish `OWNER/wikibrain` and tag `v0.1.0`.
2. Download the GitHub-generated source archive and calculate its SHA-256.
3. Render the Formula:

   ```bash
   python3 scripts/render_homebrew_formula.py \
     --owner OWNER \
     --version 0.1.0 \
     --source-url https://github.com/OWNER/wikibrain/archive/refs/tags/v0.1.0.tar.gz \
     --source-sha256 64_HEX_CHARACTERS
   ```

4. Create `OWNER/homebrew-tap` with:

   ```bash
   brew tap-new OWNER/tap --github-packages
   ```

5. Copy `Formula/wikibrain.rb` into that tap and run:

   ```bash
   brew audit --strict OWNER/tap/wikibrain
   brew install --build-from-source OWNER/tap/wikibrain
   brew test OWNER/tap/wikibrain
   ```

6. Let the tap's BrewTestBot workflow publish bottles. Do not hand-author the
   `bottle do` block.

The user-facing flow becomes:

```bash
brew install OWNER/tap/wikibrain
brainctl init --workspace /path/to/project
brainctl doctor
```

Homebrew installation never edits `~/.claude` or `~/.codex`. `brainctl init`
is the explicit, backed-up configuration step and requires at least one
allowlisted workspace.

## Upgrade and uninstall

```bash
brew update
brew upgrade OWNER/tap/wikibrain
brainctl setup
brainctl doctor
```

`brainctl setup` refreshes the managed hook commands and generated agent skills
to the newly linked Homebrew version while preserving unrelated configuration.
Codex users should review `/hooks` again after an upgrade if Codex asks them to
trust the refreshed definitions.

Before uninstalling the executable:

```bash
brainctl hooks uninstall
brainctl skills uninstall
brew uninstall OWNER/tap/wikibrain
```

The private vault is intentionally preserved outside the Cellar.

References:

- [Python for Formula Authors](https://docs.brew.sh/Python-for-Formula-Authors)
- [How to Create and Maintain a Tap](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
- [Formula tests](https://docs.brew.sh/Formula-Cookbook#add-a-test-to-the-formula)
- [Bottles](https://docs.brew.sh/Bottles)
