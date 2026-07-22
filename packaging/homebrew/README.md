# Homebrew release

WikiBrain follows Homebrew's Python virtualenv application pattern with a
supported versioned Python and pinned resources. Wikimap `1.1.0` and the
setuptools build backend are fixed to official PyPI artifacts and SHA-256
digests. The Formula disables networked build isolation after installing that
pinned backend.

## Release workflow

1. Publish `hungrytech/wikibrain` and tag the release, for example `v0.1.4`.
2. Download the GitHub-generated source archive and calculate its SHA-256.
3. Render the Formula:

   ```bash
     python3 scripts/render_homebrew_formula.py \
       --owner hungrytech \
       --version 0.1.4 \
       --source-url https://github.com/hungrytech/wikibrain/archive/refs/tags/v0.1.4.tar.gz \
       --source-sha256 64_HEX_CHARACTERS
   ```

4. Create `hungrytech/homebrew-tap` with:

   ```bash
   brew tap-new hungrytech/tap --github-packages
   ```

5. Copy `Formula/wikibrain.rb` into that tap and run:

   ```bash
   brew audit --strict hungrytech/tap/wikibrain
   brew install --build-from-source hungrytech/tap/wikibrain
   brew test hungrytech/tap/wikibrain
   ```

6. Let the tap's BrewTestBot workflow publish bottles. Do not hand-author the
   `bottle do` block.

The user-facing flow becomes:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

Homebrew installation never edits `~/.claude` or `~/.codex`. `brainctl init`
is the explicit, backed-up configuration step. It defaults the workspace
allowlist to the current user's home directory; pass repeatable
`--workspace PATH` options to use narrower roots.

## Upgrade and uninstall

```bash
brew update
brew upgrade hungrytech/tap/wikibrain
brainctl setup
brainctl doctor
```

`brainctl setup` refreshes the managed hook commands and generated agent skills
to the newly linked Homebrew version while preserving unrelated configuration.
Codex users should review `/hooks` again after an upgrade if Codex asks them to
trust the refreshed definitions. Manual `brainctl remember` and
`brainctl recall` remain usable before that review; automatic Codex lifecycle
capture and recall do not.

Before uninstalling the executable:

```bash
brainctl hooks uninstall
brainctl skills uninstall
brew uninstall hungrytech/tap/wikibrain
```

The private vault is intentionally preserved outside the Cellar.

References:

- [Python for Formula Authors](https://docs.brew.sh/Python-for-Formula-Authors)
- [How to Create and Maintain a Tap](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
- [Formula tests](https://docs.brew.sh/Formula-Cookbook#add-a-test-to-the-formula)
- [Bottles](https://docs.brew.sh/Bottles)
