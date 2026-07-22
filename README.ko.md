# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain: 소년과 친근한 뇌 마스코트가 빛나는 연결 지식 지도를 탐색하는 모습">
</p>

<p align="center"><strong>오픈소스 · 로컬 우선 · 사용자 소유 · Markdown 기반</strong></p>

<p align="center">
  <a href="README.md">English</a> ·
  <strong>한국어</strong> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

WikiBrain은 Claude Code, Codex, Grok Build가 함께 쓰는
[MIT 라이선스](LICENSE) 기반의 제2두뇌입니다. 라이프사이클 hook으로 받은
대화에서 민감정보를 제거해 읽을 수 있는 Markdown으로 보관하고,
[Wikimap](https://github.com/dhha22/wikimap)으로 로컬에서 출처와 함께
회상합니다.

## 목차

- [WikiBrain을 쓰는 이유](#why-wikibrain)
- [시작하기](#getting-started)
- [작동 방식](#how-it-works)
- [단기기억과 장기기억](#memory-lifecycle)
- [검증된 벤치마크](#verified-benchmark)
- [설치와 신뢰](#installation-and-trust)
- [자주 쓰는 명령](#daily-commands)
- [데이터와 개인정보 보호](#data-and-privacy)
- [프로젝트 문서](#project-documentation)

<a id="why-wikibrain"></a>

## WikiBrain을 쓰는 이유

| 필요한 것 | WikiBrain이 제공하는 것 |
| --- | --- |
| 에이전트 사이에서 작업 이어가기 | Claude, Codex, Grok이 같은 프로젝트 맥락을 회상합니다. |
| 근거와 장기 기억 구분하기 | 90일 근거, 적응형 기억, 명시적 장기기억을 서로 구분합니다. |
| 데이터 소유권 지키기 | Markdown이 영구 원본이며 Wikimap 인덱스는 언제든 다시 만듭니다. |
| 일시적 장애에서 복구하기 | 보관·기억 승격·관계 정리 outbox가 중단된 작업을 재시도합니다. |
| 사용자가 통제하기 | 수집 범위를 제한하고 일시정지·검사·미리보기·삭제할 수 있습니다. |

WikiBrain은 저장소를 크롤링하지 않으며 모든 대화를 자동으로 영구 사실로
취급하지 않습니다. 에이전트가 전달한 라이프사이클 payload만 수집합니다.
“기억해”라고 명시한 요청은 사용자 지정 장기기억이 되고, 반복해서 실제 맥락에
포함된 근거는 별도로 표시된 적응형 장기기억이 될 수 있습니다.

<a id="getting-started"></a>

## 시작하기

### 1. 설치하고 초기화하기

macOS 또는 Linux:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

네이티브 Windows에서는 검토 가능한 [PowerShell 설치 스크립트](#native-windows)를
사용하세요. `brainctl init`이 명시적인 동의 지점이며, 프로그램만 설치하면
Claude나 Codex 설정은 바뀌지 않습니다.

### 2. 새 에이전트 세션 시작하기

| 사용 방식 | `brainctl init` 이후 | 처음 한 번 할 일 |
| --- | --- | --- |
| Claude Code 자동 기억 | 새 세션에서 바로 사용 가능 | 없음. 필요하면 `/hooks`에서 확인합니다. |
| Codex 수동 기억 | 즉시 사용 가능 | `brainctl remember`와 `brainctl recall`을 사용합니다. |
| Codex 자동 수집·회상 | 정의는 설치되지만 처음에는 신뢰되지 않음 | 새 세션에서 `/hooks`를 열고 WikiBrain hook 다섯 개를 검토한 뒤 현재 해시를 신뢰합니다. |
| Grok 자동 수집 | Grok의 Claude hook 호환 기능으로 사용 가능하며 native 설치도 지원 | 기본 설치에는 추가 작업이 없습니다. Grok 전용 설치일 때만 `brainctl setup --clients grok`을 사용합니다. |
| Grok 회상 | 설치된 skill과 `brainctl recall` 사용 가능 | Grok은 passive hook의 stdout을 무시하므로 hook 기반 자동 문맥 주입은 지원하지 않습니다. |

### 3. 간단히 동작 확인하기

```bash
brainctl remember --global --title "WikiBrain 동작 확인" \
  "내 WikiBrain 확인 표식은 Cobalt-719다."
brainctl recall "Cobalt-719"
```

결과에 `Cobalt-719`와 로컬 Markdown 출처가 표시되어야 합니다. `remember`가
반환한 문서 ID로 테스트 페이지를 삭제할 수 있습니다.

```bash
brainctl forget --document DOCUMENT_ID --apply
```

<a id="how-it-works"></a>

## 작동 방식

```text
Claude Code hooks ─┐
Codex hooks ───────┼─ brainctl ─┬─ SQLite WAL: 영수증, 큐, 관계
Grok hooks ────────┘            ├─ Markdown vault: 읽을 수 있는 영구 원본
                                └─ Wikimap: 다시 만들 수 있는 로컬 검색 인덱스
```

1. `UserPromptSubmit`이 프롬프트의 민감정보를 제거해 기록하고 프로젝트 관련
   기억을 회상합니다.
2. `Stop`이 최종 응답과 프롬프트를 묶어 변경 불가능한 Markdown handoff로
   보관합니다.
3. 명시적인 “기억해” 요청은 독립적인 재시도 큐를 거쳐 장기기억 페이지가 됩니다.
   반복해서 주입된 단기 근거는 사용 기준을 충족하면 별도의 적응형 기억 페이지가
   됩니다.
4. `SessionStart`가 같은 Git workspace의 최근 맥락과 검색 관련 맥락을 복원합니다.
5. `relates-to`, `supersedes` 관계가 근거를 연결하고, 출처를 지우지 않은 채
   폐기된 지침을 기본 회상에서 제외합니다.

[Grok Build 공식 hook 문서](https://docs.x.ai/build/features/hooks)는
`SessionStart`, `UserPromptSubmit`, `PostToolUse`,
`Stop`, `PostCompact`를 지원하며 Claude Code hook과 skill도 자동으로 읽습니다.
WikiBrain은 Grok hook 환경을 감지해 Claude 호환 경로에서 실행된 이벤트도 provider
`grok`으로 기록합니다. 다만 Grok은 passive hook의 stdout을 무시합니다. 따라서
Grok의 근거는 자동 수집하지만, 전달되지 않은 회상을 문맥 주입으로 계산하거나
자동 회상이라고 주장하지 않습니다. 이전 맥락이 필요하면 Grok에게 WikiBrain
skill을 사용하도록 요청하거나 `brainctl recall`을 실행합니다.
실측 runtime payload의 event 값은 `user_prompt_submit`, `stop`처럼
lowercase이며 WikiBrain이 내부 lifecycle 이름으로 정규화합니다. `UserPromptSubmit`은
`prompt`와 `promptId`를 제공합니다. 실측 `Stop` payload에는 `transcriptPath`,
`promptId`, `reason`이 있지만 assistant 본문은 없습니다. 따라서 WikiBrain은 본문을
사용할 수 없다는 placeholder를 보관하며 외부 transcript를 자동으로 읽지 않습니다.

Grok만 사용한다면 먼저 [Grok Build overview](https://docs.x.ai/build/overview)에
따라 공식 `grok` 실행 파일을 설치합니다. xAI의 현재 명령은
`curl -fsSL https://x.ai/cli/install.sh | bash`이며 원격 설치 script는 실행 전에
검토해야 합니다. 그다음 `brainctl init --clients grok`을 사용합니다. Grok의
Claude hook scanner를 끄지 않았다면 native Grok hook과 Claude hook을 함께 설치하지
마세요. 같은 이벤트에서 두 정의가 모두 실행될 수 있습니다.

각 Git 저장소는 서로 격리된 기억 범위입니다. `brainctl remember --global`만
의도적으로 프로젝트 경계를 넘습니다. Hook은 fail-open 방식이라 잘못된 이벤트,
바쁜 데이터베이스, 누락된 Wikimap 실행 파일, timeout이 코딩 에이전트를 막지
않습니다.

영속성, 삭제, 재시도, 신뢰 경계의 세부 계약은
[ARCHITECTURE.md](ARCHITECTURE.md)를 참고하세요.

<a id="memory-lifecycle"></a>

## 단기기억과 장기기억

| 계층 | 저장하는 내용 | 수명 |
| --- | --- | --- |
| 단기기억 근거 | 민감정보를 제거한 session turn과 compaction handoff | 기본 90일 |
| 적응형 장기기억 | 에이전트 맥락에 반복해서 전달된 근거의 제한된 정제본 | 일반 retention 후에도 보존하며 `adaptive`로 표시 |
| 명시적 장기기억 | “기억해” 또는 `brainctl remember`로 사용자가 지정한 사실·선호 | 일반 retention 후에도 보존하며 `explicit`로 표시 |

### 적응형 승격 조건과 점수

자동 승격 대상은 `session`과 `handoff` 근거뿐입니다. 사용자가 “기억해”라고 명시한
내용은 이 점수를 거치지 않고 `explicit` 장기기억이 됩니다. 적응형 승격 후보는 먼저
최근 60일 안에 다음 hard gate를 모두 통과해야 합니다.

| Hard gate | 기본값 |
| --- | ---: |
| 근거가 전달된 서로 다른 consumer provider/session pair | 3 |
| 근거가 주입된 서로 다른 UTC 날짜 | 3 |
| 중복을 제거한 provider/session/day 단위 주입 | 2 |

Hard gate를 통과하는 것만으로는 승격되지 않습니다. WikiBrain은 다음 공식을 계산합니다.

```text
score = 0.30 * min(S / 6, 1)
      + 0.25 * min(D / 6, 1)
      + 0.25 * min(I / 4, 1)
      + 0.10 * (Q / S)
      + 0.10 * min(P / 2, 1)
```

| 기호 | 의미 |
| --- | --- |
| `S` | 근거가 전달된 서로 다른 consumer provider/session pair 수 |
| `D` | 근거가 주입된 서로 다른 UTC 날짜 수 |
| `I` | 중복을 제거한 provider/session/day 단위 주입 수 |
| `Q` | 명시적 query의 direct hit로 근거가 주입된 서로 다른 consumer session 수 |
| `P` | 서로 다른 consumer provider 수 |

분모 `6`, `6`, `4`는 각 기본 hard minimum의 두 배입니다. 따라서 반복 관련 점수는
사용량에 따라 점진적으로 증가하다가 포화합니다. Provider 다양성은 두 provider에서
포화합니다. 기본 승격 조건은 `score >= 0.65`입니다. `adaptive_memory_min_score`로
threshold를 0부터 1 사이에서 조정할 수 있으며, `0`으로 설정하면 hard gate만 사용하던
이전 동작을 유지합니다.

같은 provider/session pair가 같은 UTC 날짜에 근거를 다시 받아도 한 번만 셉니다. 실제
consumer session identity가 없는 수동 `brainctl recall`은 세지 않습니다. 최종
`<memory-data>`에 들어간 근거만 점수에 기여하며, query-backed 점수는 명시적 검색의
direct hit에만 줍니다. Related 및 recent fallback 결과는 포함하지 않습니다. Memory
페이지는 자신의 승격 점수를 높일 수 없고, workspace 사이의 사용량도 합치지 않습니다.
Superseded 근거는 승격 대상에서 제외하며, 승격 후 source가 superseded되면 파생된
adaptive memory도 recall에서 숨깁니다.

이 공식은 학습된 확률이 아니라 결정적인 초기 정책입니다. 승격된 페이지와 document
metadata에는 총점, threshold, 가중 component를 함께 기록합니다. Threshold에 미달한
후보는 pending 상태로 남고 다음 사용 시 다시 평가됩니다.

승격 시 source에서 확인한 근거를 최대 2,000자만 새 Markdown 페이지에 저장하고,
source 문서 ID, 사용 횟수, 승격 시각, `memory_kind: adaptive`를 함께 기록합니다.
이는 반복해서 유용했던 맥락이지 내용이 참이라는 자동 판정이 아닙니다. 원래의
90일 근거가 만료돼도 작은 적응형 기억은 남습니다. 일반 retention은 이를 지우지
않지만 source를 명시적으로 forget하면 파생된 적응형 기억도 함께 삭제합니다.

<a id="verified-benchmark"></a>

## 검증된 벤치마크

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain 최종 맥락 벤치마크: 맥락 계약 8개 중 8개 통과, 필수 맥락 atom recall 100%, clean context 100%, 금지 atom 노출 0%">
</p>

고정 corpus 계약 벤치마크는 검색 지연시간이 아니라 에이전트에게 전달되는 최종
`<memory-data>`를 검사합니다. Query 검사는 최근 문서 fallback을 끄고, 별도의
handoff 검사는 `SessionStart`를 통한 최근 맥락 복원을 확인합니다. 모든 필수 사실이
포함되고 폐기된 지침, 비밀정보, 다른 workspace의 내용이 없어야 통과합니다.

| 최종 맥락 계약 | 값 |
| --- | ---: |
| 맥락 검사 | **8/8 통과** |
| 필수 맥락 atom | **21/21 · 100.00%** |
| Clean context | **8/8 · 100.00%** |
| 금지 atom 노출 | **0/4 · 0.00%** |
| 환경 | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

### 정답 label 기반 최종 맥락 품질

<p align="center">
  <img src="docs/assets/benchmark-retrieval-quality-v1.svg" width="920" alt="WikiBrain 맥락 회상 벤치마크: Context Recall 87.50%, Context Precision 79.17%, Context F1 80.56%, 필수 사실 recall 90.91%, query 12개에서 금지 맥락 노출 0%">
</p>

별도의 문서 14개·query 12개 corpus는 production `RecallService.context()`가 실제로
주입하는 내용을 측정합니다. 각 query에는 관련 record, 최소 필수 사실, stale·삭제·
타 workspace 금지 record를 표시합니다. Query와 최종 context 원문은 채점 후 버립니다.

| 최종 맥락 품질 | 값 |
| --- | ---: |
| Context Recall / Precision | **87.50% / 79.17%** |
| Context F1 / 필수 사실 recall | **80.56% / 90.91%** |
| 금지 맥락 노출 | **0/12 query · 0.00%** |
| 적재 수락률 | **14/14 · 100.00%** |
| Retrieval Recall@1 / Recall@3 *(진단용)* | **69.44% / 87.50%** |
| MRR / nDCG@3 *(진단용)* | **87.50% / 81.35%** |

Context Recall은 필요한 record가 최종 prompt까지 도달했는지 측정합니다. Context
Precision은 주입된 record 중 관련 record의 비율입니다. 필수 사실 recall은 선택된
문서의 유용한 근거가 누락되거나 잘렸는지도 따로 잡아냅니다. 검색 순위 지표는
검색·ranking 원인을 찾는 진단값이며 제2두뇌 품질의 대표 지표가 아닙니다.

<details>
<summary><strong>검사 8개가 확인하는 계약</strong></summary>

| 검사 | 확인하는 내용 |
| --- | --- |
| 최신 결정 | 새 `uv` 지침이 폐기된 `pip` 지침을 기본 회상에서 제외하는가 |
| 근거 연결 | `relates-to`, `supersedes` 관계가 회상 결과에 남는가 |
| 사람과 프로젝트 | 담당자와 예비 검토자 맥락을 찾을 수 있는가 |
| 출처 추적 | 문서 ID, Markdown 경로, 수집 시각이 근거와 함께 나오는가 |
| Workspace 격리 | 다른 저장소의 표식이 범위를 넘어오지 않는가 |
| 비밀정보 제거 | 합성 API 비밀값이 영구 저장과 회상에서 사라지는가 |
| 전역 선호 | 의도적으로 저장한 전역 선호가 프로젝트 범위에서 보이는가 |
| Claude → Codex | Claude 세션의 사실이 Codex 시작 시 전달되는가 |

</details>

소스 checkout에서 재현합니다.

```bash
uv run --locked python -m benchmarks.second_brain \
  --format json \
  --output benchmarks/results/second-brain-v1.json
uv run --locked python scripts/render_benchmark_chart.py

uv run --locked python -m benchmarks.retrieval_quality \
  --corpus benchmarks/corpora/retrieval-quality-v1.json \
  --output benchmarks/results/retrieval-quality-v1.json
uv run --locked python scripts/render_retrieval_quality_chart.py
```

기계가 읽을 수 있는 원본 결과는
[`second-brain-v1.json`](benchmarks/results/second-brain-v1.json)과
[`retrieval-quality-v1.json`](benchmarks/results/retrieval-quality-v1.json)에
있습니다. 두 그래프 모두 각 JSON에서 생성되며, SVG가 오래되면 CI가 실패합니다.

내가 적재한 데이터의 품질은
[정답 label corpus](benchmarks/corpora/retrieval-quality-v1.json)를 저장소 밖으로
복사한 뒤 합성 문서와 relevance label을 교체해 로컬에서 측정할 수 있습니다.

```bash
cp benchmarks/corpora/retrieval-quality-v1.json /tmp/my-brain-quality.json
# /tmp 파일의 documents, queries, relevant, required_context, forbidden을 수정합니다.
uv run --locked python -m benchmarks.retrieval_quality \
  --corpus /tmp/my-brain-quality.json \
  --output /tmp/my-brain-quality-result.json
```

결과에는 문서 원문과 query 원문이 기록되지 않지만 ID도 민감할 수 있습니다.
개인 corpus와 결과를 커밋하지 마세요.

> **측정 범위:** 이 수치는 작은 합성 회귀 corpus의 결과이지 개인 vault의 성능
> 보장이 아닙니다. OCR 추출, 동시 쓰기, 검색 맥락을 LLM이 사용한 뒤의 답변
> 근거 충실성, 다단계 그래프 추론은 측정하지 않습니다. 내 데이터의 정확도를
> 주장하려면 직접 정답 label을 붙인 개인 corpus가 필요합니다.

<a id="installation-and-trust"></a>

## 설치와 신뢰

### macOS 또는 Linux

위 [시작하기](#getting-started)의 명령을 사용하세요. Apple Silicon macOS,
Intel macOS, x86_64 Linux용 bottle을 제공합니다.

<a id="native-windows"></a>

### 네이티브 Windows

가장 쉬운 방법은 AI 코딩 도구에 공식 저장소 링크를 주고 설치와 검증을 요청하는
것입니다. Windows PC에서 명령을 실행할 수 있는 Claude Code, Codex 등의
에이전트에 아래 내용을 그대로 붙여 넣으세요.

```text
Install WikiBrain on this Windows machine from https://github.com/hungrytech/wikibrain.
Read the repository's Native Windows instructions first. Before changing anything,
tell me whether native Windows or WSL is the correct path for where my agents and
repositories run. Use the version-pinned installer from the README. Download it,
show me the full PowerShell script, explain the settings changed by initialization,
then stop and wait for my explicit approval before running the script or initializing
WikiBrain. After I approve, install it and finish by running brainctl doctor.
Do not bypass Codex hook trust.
```

AI가 제시한 계획과 권한 요청을 확인한 뒤 진행하세요. 직접 설치하려면 PowerShell에서
버전이 고정된 설치 스크립트를 내려받아 검토한 뒤 실행합니다.

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.5/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

설치 스크립트는 Python 3.11 이상을 사용하고 격리된 `pipx` 환경에 설치합니다.
`-Initialize`를 명시했을 때만 `brainctl init`을 실행합니다. 이 옵션을 빼면
에이전트 설정을 바꾸지 않고 CLI만 설치합니다. 네이티브 Windows의 기본 저장
위치는 `%LOCALAPPDATA%\WikiBrain`입니다. 에이전트와 저장소가 WSL 안에서
실행된다면 WSL 내부의 Linux 설치 방법을 사용하세요.

<details>
<summary><strong>Codex hook 신뢰 경계</strong></summary>

수동 `brainctl remember`와 `brainctl recall`에는 hook 승인이 필요 없습니다.
하지만 자동 프롬프트 수집과 문맥 주입은 다릅니다. Codex는 사용자가 `/hooks`에서
현재 정의의 해시를 검토하기 전까지 관리되지 않는 command hook을 건너뜁니다.

WikiBrain은 `--dangerously-bypass-hook-trust`를 alias, wrapper, 실행 설정에
추가하지 않습니다. 영구적으로 검토가 필요 없는 경로는 시스템, MDM, cloud 또는
`requirements.toml`로 배포하는 관리자 관리 hook 정책뿐입니다.

대기 중인 hook 경고가 없는 수동 전용 설치:

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "오래 보관할 사실"
brainctl recall "그 사실"
```

호스트의 전체 신뢰 모델은 공식
[Codex hook 문서](https://learn.chatgpt.com/docs/hooks)를 참고하세요.

</details>

### `brainctl init`이 바꾸는 내용

`brainctl init`은 여러 번 실행해도 중복 항목을 만들지 않습니다. 기존 설정을
백업하고 WikiBrain 소유 항목만 구조적으로 병합하며, 관계없는 hook과 skill은
보존합니다.

| 용도 | macOS/Linux | 네이티브 Windows |
| --- | --- | --- |
| 두뇌 데이터 | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| Claude hook | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex hook | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Grok hook (Grok 전용 opt-in) | `${GROK_HOME:-~/.grok}/hooks/wikibrain.json` | `%GROK_HOME%\hooks\wikibrain.json` 또는 `%USERPROFILE%\.grok\hooks\wikibrain.json` |
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Grok skill (Grok 전용 opt-in) | `${GROK_HOME:-~/.grok}/skills/wikibrain/` | `%GROK_HOME%\skills\wikibrain\` 또는 `%USERPROFILE%\.grok\skills\wikibrain\` |
| Codex/Agents skill | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |

| 이벤트 | WikiBrain이 하는 일 |
| --- | --- |
| `SessionStart` | 세션을 등록하고 관련 프로젝트 기억을 전달합니다. |
| `UserPromptSubmit` | 프롬프트를 정제해 저장하고 관련 맥락을 회상합니다. |
| `PostToolUse` | 안전한 도구·파일·작업 디렉터리 포인터만 저장합니다. |
| `Stop` | 완료된 턴을 보관하고 명시적인 기억을 승격한 뒤 검색을 갱신합니다. |
| `PostCompact` | 사용 가능한 압축 요약을 handoff로 보관합니다. |

WikiBrain 소유 연동만 검토하거나 제거할 수 있습니다.

```bash
brainctl init --dry-run --json
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

### 개발용 설치

```bash
uv sync --locked
uv run brainctl init
uv run python -m unittest discover -s tests -v
```

<a id="daily-commands"></a>

## 자주 쓰는 명령

```bash
brainctl status
brainctl recall "인증 구조에 대해 어떤 결정을 내렸지?"
brainctl remember --title "선호 패키지 관리자" "Python 도구에는 uv를 사용한다."
brainctl remember --global "한국어로 간결하게 답하는 것을 선호한다."
brainctl remember --title "uv 사용" \
  --relates-to 근거-ID --supersedes 이전-ID "uv를 사용한다."
brainctl pause
brainctl resume
brainctl forget --document memory-ID            # 미리보기
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade  # 원본 세션 미리보기
brainctl forget --document memory-ID --cascade --apply
brainctl retention                               # 90일 지난 근거 정리 미리보기
brainctl retention --apply
```

<a id="data-and-privacy"></a>

## 데이터와 개인정보 보호

- SQLite나 Markdown에 쓰기 전에 비밀정보를 제거합니다.
- 전체 도구 출력과 shell 명령은 보관하지 않고 안전한 포인터만 저장합니다.
- 저장 내용은 민감정보를 제거한 일반 텍스트이지 애플리케이션 수준 암호문이
  아닙니다. FileVault, BitLocker, LUKS를 사용하세요.
- `remember`는 기본적으로 프로젝트 범위입니다. `--global`은 의도적으로만
  사용하세요.
- 보존 기간 정리는 만료된 세션과 handoff 근거만 제거하고 적응형·명시적 장기기억은
  보존합니다. `--apply`가 없으면 미리보기만 합니다. 기준 시각은 나중의 문서 등록
  시각이 아니라 근거의 `captured_at`이며, 오래 실패한 promotion 작업은 만료 turn을
  무기한 보호하지 않습니다.
- 완료된 handoff 행은 문서 metadata로 압축합니다. 삭제된 source마다 replay 방지용
  canonical tombstone 하나를 유지하고, retention은 내용이 모두 사라진 session의
  tombstone을 session tombstone 하나로 다시 압축합니다. 이를 만료시키면 replay된
  내용이 부활할 수 있어 fingerprint는 만료하지 않습니다. forget 영수증은 최신
  100개, installer backup은 대상별 최신 3개만 유지하고 retention 후 빈 날짜
  디렉터리를 제거합니다.
- 단기 근거를 명시적으로 forget하면 여기서 파생된 적응형 기억도 함께 지웁니다.
  일반 memory 삭제는 해당 페이지만 지웁니다. source session 전체도 지우려면
  `--cascade`로 영향을 확인한 뒤 같은 명령에 `--apply`를 추가하세요.
- `WIKIBRAIN_HOME` 또는 `brainctl --home PATH`로 저장 위치를 바꿀 수 있습니다.

Homebrew나 pipx에서 프로그램을 제거해도 별도 두뇌 디렉터리는 삭제되지 않습니다.

<a id="project-documentation"></a>

## 프로젝트 문서

- [구조와 신뢰 경계](ARCHITECTURE.md)
- [명령어 참고서](plugins/wikibrain/skills/wikibrain/references/command-reference.md)
- [보안 정책](SECURITY.md)
- [기여 방법](CONTRIBUTING.md)
- [변경 기록](CHANGELOG.md)

WikiBrain은 [MIT License](LICENSE)로 배포됩니다.
