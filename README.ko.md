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

WikiBrain은 Claude Code와 Codex가 함께 쓰는
[MIT 라이선스](LICENSE) 기반의 제2두뇌입니다. 라이프사이클 hook으로 받은
대화에서 민감정보를 제거해 읽을 수 있는 Markdown으로 보관하고,
[Wikimap](https://github.com/dhha22/wikimap)으로 로컬에서 출처와 함께
회상합니다.

## 목차

- [WikiBrain을 쓰는 이유](#why-wikibrain)
- [시작하기](#getting-started)
- [작동 방식](#how-it-works)
- [검증된 벤치마크](#verified-benchmark)
- [설치와 신뢰](#installation-and-trust)
- [자주 쓰는 명령](#daily-commands)
- [데이터와 개인정보 보호](#data-and-privacy)
- [프로젝트 문서](#project-documentation)

<a id="why-wikibrain"></a>

## WikiBrain을 쓰는 이유

| 필요한 것 | WikiBrain이 제공하는 것 |
| --- | --- |
| 에이전트 사이에서 작업 이어가기 | Claude와 Codex가 같은 프로젝트 맥락을 회상합니다. |
| 근거와 장기 기억 구분하기 | 검색 가능한 대화 handoff와 명시적인 장기 기억을 분리합니다. |
| 데이터 소유권 지키기 | Markdown이 영구 원본이며 Wikimap 인덱스는 언제든 다시 만듭니다. |
| 일시적 장애에서 복구하기 | 보관·기억 승격·관계 정리 outbox가 중단된 작업을 재시도합니다. |
| 사용자가 통제하기 | 수집 범위를 제한하고 일시정지·검사·미리보기·삭제할 수 있습니다. |

WikiBrain은 저장소를 크롤링하지 않으며 모든 대화를 자동으로 영구 사실로
취급하지 않습니다. 에이전트가 전달한 라이프사이클 payload만 수집하고,
“기억해”라고 명시한 요청만 장기 기억으로 승격합니다.

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
                   ├─ brainctl ─┬─ SQLite WAL: 영수증, 큐, 관계
Codex hooks ───────┘            ├─ Markdown vault: 읽을 수 있는 영구 원본
                                └─ Wikimap: 다시 만들 수 있는 로컬 검색 인덱스
```

1. `UserPromptSubmit`이 프롬프트의 민감정보를 제거해 기록하고 프로젝트 관련
   기억을 회상합니다.
2. `Stop`이 최종 응답과 프롬프트를 묶어 변경 불가능한 Markdown handoff로
   보관합니다.
3. 명시적인 “기억해” 요청은 독립적인 재시도 큐를 거쳐 장기 기억 페이지가 됩니다.
4. `SessionStart`가 같은 Git workspace의 최근 맥락과 검색 관련 맥락을 복원합니다.
5. `relates-to`, `supersedes` 관계가 근거를 연결하고, 출처를 지우지 않은 채
   폐기된 지침을 기본 회상에서 제외합니다.

각 Git 저장소는 서로 격리된 기억 범위입니다. `brainctl remember --global`만
의도적으로 프로젝트 경계를 넘습니다. Hook은 fail-open 방식이라 잘못된 이벤트,
바쁜 데이터베이스, 누락된 Wikimap 실행 파일, timeout이 코딩 에이전트를 막지
않습니다.

영속성, 삭제, 재시도, 신뢰 경계의 세부 계약은
[ARCHITECTURE.md](ARCHITECTURE.md)를 참고하세요.

<a id="verified-benchmark"></a>

## 검증된 벤치마크

<p align="center">
  <img src="docs/assets/benchmark-second-brain-v1.svg" width="920" alt="WikiBrain 벤치마크: 기능 검사 8개 중 8개 통과, 80회 회상에서 지연시간 p50 24.31밀리초와 p95 28.14밀리초">
</p>

고정 corpus 벤치마크의 query 기반 검색 검사는 최근 문서 fallback을 끕니다.
별도의 handoff 검사는 `SessionStart`를 통한 최근 맥락 복원을 확인합니다.
Query 검사는 기대한 근거를 포함하면서 폐기된 지침, 비밀정보, 다른 workspace의
내용을 제외해야만 통과합니다.

| 결과 | 값 |
| --- | ---: |
| 기능 검사 | **8/8 통과** |
| 회상 측정 | **80회** (query 4개 × 20회) |
| 지연시간 | **p50 24.31ms · p95 28.14ms** |
| 환경 | macOS arm64 · Python 3.13.11 · Wikimap 1.1.0 |

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
  --iterations 20 \
  --format json \
  --output benchmarks/results/second-brain-v1.json
uv run --locked python scripts/render_benchmark_chart.py
```

기계가 읽을 수 있는 원본 결과는
[`benchmarks/results/second-brain-v1.json`](benchmarks/results/second-brain-v1.json)에
있습니다. 그래프는 이 JSON에서 생성되며, SVG가 오래되면 CI 검사가 실패합니다.
지연시간은 컴퓨터와 실행 시점에 따라 달라지는 값이지 고정 성능 보장이 아닙니다.

> **측정 범위:** 100%는 작고 합성된 고정 회귀 corpus를 모두 통과했다는 뜻입니다.
> 장기간 쌓인 잡음 많은 vault, 의미적 바꿔 말하기, OCR·문서 인입, 동시 쓰기,
> 답변의 근거 충실성, 다단계 그래프 추론은 측정하지 않습니다.

<a id="installation-and-trust"></a>

## 설치와 신뢰

### macOS 또는 Linux

위 [시작하기](#getting-started)의 명령을 사용하세요. Apple Silicon macOS,
Intel macOS, x86_64 Linux용 bottle을 제공합니다.

<a id="native-windows"></a>

### 네이티브 Windows

PowerShell에서 버전이 고정된 설치 스크립트를 내려받아 검토한 뒤 실행합니다.

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
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
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
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
- 보존 기간 정리는 만료된 세션과 handoff 근거만 제거하고 명시적인 장기 기억은
  지우지 않습니다. `--apply`가 없으면 미리보기만 합니다.
- 일반 문서 삭제는 해당 페이지만 지웁니다. 원본 대화도 지우려면 `--cascade`로
  영향을 확인한 뒤 같은 명령에 `--apply`를 추가해 둘 다 삭제하세요.
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
