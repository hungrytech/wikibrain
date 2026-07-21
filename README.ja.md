# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain：光り輝く相互接続された知識マップの下にいる若い研究者と親しみやすい脳のマスコット">
</p>

<p align="center"><strong>オープンソース · ローカルファースト · ユーザー所有 · Markdown ネイティブ</strong></p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.ko.md">한국어</a> ·
  <strong>日本語</strong> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

WikiBrain は、Claude Code と Codex のための [MIT ライセンス](LICENSE)の共有セカンドブレインです。ライフサイクルフックを通じて機密情報をマスキングした会話の引き継ぎを取得し、永続的なコンテキストを読みやすい Markdown として保存し、ローカルで出典を認識した情報の呼び出しに [Wikimap](https://github.com/dhha22/wikimap) を使用します。

## 目次

- [WikiBrain を選ぶ理由](#why-wikibrain)
- [はじめに](#getting-started)
- [仕組み](#how-it-works)
- [検証済みベンチマーク](#verified-benchmark)
- [インストールと信頼](#installation-and-trust)
- [日常的に使うコマンド](#daily-commands)
- [データとプライバシー](#data-and-privacy)
- [プロジェクトドキュメント](#project-documentation)

<a id="why-wikibrain"></a>

## WikiBrain を選ぶ理由

| ニーズ | WikiBrain が提供するもの |
| --- | --- |
| エージェントをまたいで作業を継続 | Claude と Codex が同じプロジェクトスコープのコンテキストを復元できます。 |
| 証拠と記憶を分離 | 検索可能な会話の引き継ぎを、明示的な長期記憶とは別に保持します。 |
| ユーザーの所有権を維持 | Markdown が永続的な正本であり、Wikimap インデックスは破棄して再生成できます。 |
| 一時的な障害から復旧 | アーカイブ、昇格、リレーション整理の各アウトボックスが中断した処理を再試行します。 |
| ユーザー自身が制御 | 取得対象は許可リストで制限でき、一時停止、確認、プレビュー、削除が可能です。 |

WikiBrain はリポジトリをクロールせず、すべての会話を自動的に永続的な事実へ変換することもありません。取得されるのはライフサイクルのペイロードだけであり、永続的な記憶になるのは明示的な「これを覚えて」というリクエストだけです。

<a id="getting-started"></a>

## はじめに

### 1. インストールと初期化

macOS または Linux：

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

ネイティブ Windows では、内容を確認できる [PowerShell インストーラー](#native-windows)を使用してください。`brainctl init` は明示的な同意の境界です。インストールしただけでは Claude や Codex の設定は変更されません。

### 2. 新しいエージェントセッションを開始

| クライアントモード | `brainctl init` 実行後 | 一度だけ必要な操作 |
| --- | --- | --- |
| Claude Code の自動記憶 | 新しいセッションで利用可能 | なし。確認には `/hooks` を使用できます。 |
| Codex の手動記憶 | すぐに利用可能 | `brainctl remember` と `brainctl recall` を使用します。 |
| Codex の自動取得と呼び出し | 定義はインストールされますが、最初は信頼されていません | 新しいセッションを開始し、`/hooks` を開いて、WikiBrain の 5 つのフックを確認し、現在のハッシュを信頼してください。 |

### 3. スモークテストを実行

```bash
brainctl remember --global --title "WikiBrain smoke test" \
  "My WikiBrain verification marker is Cobalt-719."
brainctl recall "Cobalt-719"
```

結果には `Cobalt-719` とローカルの Markdown ソースが含まれるはずです。`remember` が返したドキュメント ID を使ってテストページを削除します：

```bash
brainctl forget --document DOCUMENT_ID --apply
```

<a id="how-it-works"></a>

## 仕組み

```text
Claude Code hooks ─┐
                   ├─ brainctl ─┬─ SQLite WAL: receipts, queues, relations
Codex hooks ───────┘            ├─ Markdown vault: durable readable truth
                                └─ Wikimap: disposable local search index
```

1. `UserPromptSubmit` はプロンプトをマスキングして記録し、関連するプロジェクトの記憶を呼び出します。
2. `Stop` は最終応答をプロンプトと組み合わせ、そのターンを変更不可の Markdown 引き継ぎとしてアーカイブします。
3. 明示的な「覚えて」というリクエストは、独立した再試行キューを通じて永続的な記憶ページを作成します。
4. `SessionStart` は同じ Git ワークスペースについて、最近のコンテキストとクエリに関連するコンテキストを復元します。
5. 型付きの `relates-to` および `supersedes` リンクは証拠を接続し、その出所を削除することなく古いガイダンスを抑制します。

各 Git リポジトリは独立した記憶スコープです。プロジェクトの境界を意図的に越えるのは `brainctl remember --global` だけです。フックはフェイルオープンです。不正な形式のイベント、ビジー状態のデータベース、Wikimap 実行ファイルの欠落、タイムアウトがコーディングエージェントを妨げることはありません。

永続化、削除、再試行、信頼境界の詳細は [ARCHITECTURE.md](ARCHITECTURE.md) を参照してください。

<a id="verified-benchmark"></a>

## 検証済みベンチマーク

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain ベンチマーク：8 件中 8 件の機能チェックに合格。80 サンプルにおける呼び出しレイテンシは p50 が 24.31 ミリ秒、p95 が 28.14 ミリ秒">
</p>

固定コーパスベンチマークのクエリ検索チェックでは、最近の項目へのフォールバックを無効にします。別の引き継ぎチェックでは、`SessionStart` による最近のコンテキスト復元を検証します。クエリ検索チェックは、期待される証拠を返し、禁止された古い内容、機密情報、または別ワークスペースの内容を除外した場合にのみ合格します。

| 結果 | 値 |
| --- | ---: |
| 機能チェック | **8/8 passed** |
| 呼び出しサンプル | **80** (4 queries × 20 iterations) |
| レイテンシ | **24.31 ms p50 · 28.14 ms p95** |
| 環境 | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

### 検索品質と取り込みの完全性

<p align="center">
  <img src="docs/assets/benchmark-retrieval-quality-v1.svg" width="920" alt="WikiBrain 検索品質ベンチマーク：Recall@1 69.44%、Recall@3 87.50%、nDCG@3 81.35%、MRR 87.50%、Top-1 出典一致率 83.33%、14 件中 14 件の文書を受理、禁止文書の露出率 0%">
</p>

レイテンシとは別に、正解ラベル付きコーパスで検索順位を測定します。14 件の合成文書を取り込み、インデックス作成後に 1 件を削除してから、完全一致、言い換え、複数正解、グローバル設定、ワークスペーススコープを含む 12 件のクエリを実行します。

| 品質結果 | 値 |
| --- | ---: |
| 取り込み受理率 | **14/14 · 100.00%** |
| 保存内容の存在率 | **100.00%** |
| Recall@1 / Recall@3 | **69.44% / 87.50%** |
| MRR / nDCG@3 | **87.50% / 81.35%** |
| Top-1 出典一致率 | **83.33%** |
| 禁止文書の露出 | **0/12 queries · 0.00%** |

`forbidden` ラベルには、別ワークスペース、置き換え済みの決定、削除済みの記憶が含まれます。検索スコアが完全でないのは意図的です。言い換えと順位付けの弱点を表面化し、8/8 の機能チェックを検索精度として誇張しません。

<details>
<summary><strong>8 件のチェックの対象</strong></summary>

| チェック | 契約 |
| --- | --- |
| 現在の決定 | 新しい `uv` ガイダンスが、置き換えられた `pip` ガイダンスを抑制します。 |
| 証拠リンク | `relates-to` と `supersedes` のエッジが呼び出し後も維持されます。 |
| 人とプロジェクト | オーナーと予備レビュアーのコンテキストを引き続き復元できます。 |
| 出典の来歴 | ドキュメント ID、Markdown パス、取得時刻が証拠に付随します。 |
| ワークスペースの分離 | 別のリポジトリのマーカーがスコープを越えません。 |
| シークレットのマスキング | 合成 API シークレットが永続ストレージにも呼び出し結果にも存在しません。 |
| グローバル設定 | 意図的に設定したグローバル設定をプロジェクトスコープで利用できます。 |
| Claude → Codex | Claude セッションの事実が Codex のセッション開始時に表示されます。 |

</details>

ソースをチェックアウトした環境で再現するには：

```bash
uv run --locked python -m benchmarks.second_brain \
  --iterations 20 \
  --format json \
  --output benchmarks/results/second-brain-v1.json
uv run --locked python scripts/render_benchmark_chart.py

uv run --locked python -m benchmarks.retrieval_quality \
  --corpus benchmarks/corpora/retrieval-quality-v1.json \
  --output benchmarks/results/retrieval-quality-v1.json
uv run --locked python scripts/render_retrieval_quality_chart.py
```

機械可読な結果は [`second-brain-v1.json`](benchmarks/results/second-brain-v1.json) と [`retrieval-quality-v1.json`](benchmarks/results/retrieval-quality-v1.json) にあります。どちらのグラフも対応する JSON から生成され、古い SVG は CI によって拒否されます。レイテンシはマシンや実行ごとに変動するため、安定した性能を保証するものではありません。

自分が保存したデータの品質を測るには、[正解ラベル付きコーパス](benchmarks/corpora/retrieval-quality-v1.json)をリポジトリ外にコピーし、合成文書と relevance ラベルを置き換えて、結果をローカルに保存します：

```bash
cp benchmarks/corpora/retrieval-quality-v1.json /tmp/my-brain-quality.json
# /tmp の documents、queries、relevant、forbidden を編集します。
uv run --locked python -m benchmarks.retrieval_quality \
  --corpus /tmp/my-brain-quality.json \
  --output /tmp/my-brain-quality-result.json
```

結果には文書本文とクエリ本文は記録されませんが、ID も機密になり得ます。個人用コーパスや結果をコミットしないでください。

> **範囲：** これは小規模な合成回帰コーパスの結果であり、個人用 Vault の性能を保証するものではありません。OCR 抽出、同時書き込み、検索コンテキストを LLM が使用した後の回答の忠実性、マルチホップのグラフ推論は測定していません。自分のデータに対する精度を主張するには、自分で正解ラベルを付けた個人用コーパスが必要です。

<a id="installation-and-trust"></a>

## インストールと信頼

### macOS または Linux

上の [はじめに](#getting-started) にあるコマンドを使用してください。ビルド済みの bottle は Apple Silicon macOS、Intel macOS、x86_64 Linux に対応しています。

<a id="native-windows"></a>

### ネイティブ Windows

PowerShell を開き、バージョンが固定されたインストーラーをダウンロードして内容を確認した後、実行します：

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

インストーラーは Python 3.11 以降を使用し、分離された `pipx` を通じてインストールします。`brainctl init` を実行するのは `-Initialize` が指定された場合だけです。エージェント設定を変更せずに CLI をインストールするには、このスイッチを省略してください。ネイティブ Windows では Brain は `%LOCALAPPDATA%\WikiBrain` に保存されます。エージェントとリポジトリを WSL 内で実行する場合は、Linux のパスを使用してください。

<details>
<summary><strong>Codex フックの信頼境界</strong></summary>

手動の `brainctl remember` と `brainctl recall` は、フックを承認しなくても動作します。一方、自動的なプロンプトの取得とコンテキスト注入は動作しません。Codex は、現在の定義ハッシュが `/hooks` で確認されるまで、管理対象外のコマンドフックをスキップします。

WikiBrain がエイリアス、ラッパー、起動設定に `--dangerously-bypass-hook-trust` を追加することはありません。永続的にレビューを不要にする唯一の方法は、システム、MDM、クラウド、または `requirements.toml` を通じて配布される、管理者が管理するフックポリシーです。

保留中のフック警告がない、信頼承認不要の手動専用セットアップ：

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "A durable fact"
brainctl recall "that durable fact"
```

公式の [Codex フックドキュメント](https://learn.chatgpt.com/docs/hooks)を参照してください。

</details>

### `brainctl init` による変更

`brainctl init` は冪等です。既存の設定をバックアップし、WikiBrain が所有するエントリだけを構造的にマージし、無関係なフックとスキルを保持します。

| 用途 | macOS/Linux | ネイティブ Windows |
| --- | --- | --- |
| Brain の状態 | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| Claude フック | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex フック | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Claude スキル | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Codex/Agents スキル | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |

| イベント | WikiBrain の動作 |
| --- | --- |
| `SessionStart` | セッションを登録し、関連するプロジェクトの記憶を注入します。 |
| `UserPromptSubmit` | プロンプトをマスキングして取得した後、コンテキストを呼び出します。 |
| `PostToolUse` | 安全なツール、ファイル、作業ディレクトリへのポインターだけを保存します。 |
| `Stop` | 完了したターンをアーカイブし、明示的な記憶を昇格させ、検索を更新します。 |
| `PostCompact` | 利用可能なコンパクション要約を引き継ぎとしてアーカイブします。 |

WikiBrain が所有する連携だけを確認または削除するには：

```bash
brainctl init --dry-run --json
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

### ローカル開発

```bash
uv sync --locked
uv run brainctl init
uv run python -m unittest discover -s tests -v
```

<a id="daily-commands"></a>

## 日常的に使うコマンド

```bash
brainctl status
brainctl recall "what did we decide about the auth architecture?"
brainctl remember --title "Preferred package manager" "Use uv for Python tools."
brainctl remember --global "I prefer concise Korean answers."
brainctl remember --title "Use uv" \
  --relates-to evidence-ID --supersedes old-ID "Use uv."
brainctl pause
brainctl resume
brainctl forget --document memory-ID            # preview
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade  # preview source session
brainctl forget --document memory-ID --cascade --apply
brainctl retention                               # preview 90-day evidence pruning
brainctl retention --apply
```

<a id="data-and-privacy"></a>

## データとプライバシー

- 機密情報は SQLite または Markdown への書き込み前にマスキングされます。
- ツールの完全な出力とシェルコマンドはアーカイブされません。安全なポインターだけが保存されます。
- アーカイブはマスキング済みの平文であり、アプリケーションレベルでは暗号化されていません。FileVault、BitLocker、または LUKS を使用してください。
- `remember` はデフォルトでプロジェクトスコープです。`--global` は意図した場合にだけ使用してください。
- 保持処理は期限切れのセッションと引き継ぎの証拠を削除しますが、明示的な永続記憶は削除しません。また、`--apply` を付けない限りプレビューのみです。
- 通常のドキュメント削除ではそのページだけを削除します。`--cascade` でソース会話への影響をプレビューし、同じコマンドに `--apply` を追加して両方を削除してください。
- 状態の保存場所は `WIKIBRAIN_HOME` または `brainctl --home PATH` で上書きできます。

Homebrew または pipx をアンインストールしても、別に保存されている Brain ディレクトリは削除されません。

<a id="project-documentation"></a>

## プロジェクトドキュメント

- [アーキテクチャと信頼境界](ARCHITECTURE.md)
- [コマンドリファレンス](plugins/wikibrain/skills/wikibrain/references/command-reference.md)
- [セキュリティポリシー](SECURITY.md)
- [コントリビューション](CONTRIBUTING.md)
- [変更履歴](CHANGELOG.md)

WikiBrain は [MIT License](LICENSE) の下で配布されています。
