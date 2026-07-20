# WikiBrain

<p align="center">
  <img src="docs/assets/wikibrain-hero.png" width="920" alt="WikiBrain: 소년과 친근한 뇌 마스코트가 빛나는 연결 지식 지도를 탐색하는 모습">
</p>

<p align="center"><strong>오픈소스 · 로컬 우선 · 사용자 소유 · Markdown 기반</strong></p>

<p align="center">
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>

WikiBrain은 Claude Code와 Codex가 함께 쓰는
[MIT 라이선스](LICENSE) 기반의 제2두뇌입니다. 라이프사이클 hook으로
대화의 핵심 흐름을 받아 민감정보를 제거한 뒤, 읽을 수 있는 Markdown으로
보관합니다. 빠르고 출처를 확인할 수 있는 검색에는
[Wikimap](https://github.com/dhha22/wikimap)을 사용합니다.

## 어떤 점이 좋은가요?

- Claude에서 하던 일을 Codex가 이어받거나, 그 반대로 이어갈 수 있습니다.
- 새 세션을 시작해도 최근 작업과 관련 지식을 다시 불러옵니다.
- 검색용 대화 기록과 검증된 장기 기억을 구분해 기억이 오염되는 일을 줄입니다.
- “이것을 기억해”라고 명시한 내용은 별도 재시도 큐에 남으므로, 일시적인
  저장 실패가 발생해도 장기 기억이 사라지지 않습니다.
- Wikimap 검색은 로컬에서 동작하며, 검색 인덱스는 언제든 다시 만들 수 있습니다.
- 수집 범위를 제한하거나 잠시 멈추고, 내용을 확인하거나 삭제할 수 있습니다.
- 나중에 모델이나 코딩 에이전트를 바꾸더라도 Markdown 데이터는 그대로 남습니다.

## 시작하기

설치부터 실제 제2두뇌 동작 확인까지 가장 짧고 안전한 순서입니다. 운영체제별
상세 설치 과정과 변경되는 파일은 아래에서 더 자세히 설명합니다.

### 1. 설치하고 초기화하기

macOS 또는 Linux:

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

네이티브 Windows에서는 [Windows: 네이티브 PowerShell](#windows-네이티브-powershell)의
검토 가능한 설치 스크립트와 명시적인 `-Initialize` 옵션을 사용하세요.

`brainctl init`은 개인 두뇌를 만들고 WikiBrain skill과 선택한 라이프사이클
hook을 설치합니다. `brainctl doctor`는 파일, 실행 파일, 데이터베이스,
Wikimap 인덱스를 검사합니다. 다만 Codex가 별도로 관리하는 hook 신뢰 상태를
조회하거나 변경하지 않습니다.

### 2. 새 에이전트 세션 시작하기

| 사용 방식 | `brainctl init` 직후 사용 가능 여부 | 처음 한 번 할 일 |
|---|---|---|
| Claude Code 자동 기억 | 새 세션에서 바로 사용 가능 | 없음. 필요하면 `/hooks`에서 내용을 확인할 수 있습니다. |
| Codex 수동 기억 | CLI 명령은 즉시 동작하고 skill은 새 세션에서 로드됩니다 | `brainctl remember`/`recall`과 설치된 WikiBrain skill에는 hook 신뢰가 필요 없습니다. |
| Codex 자동 수집·회상 | 정의는 설치되지만 신뢰하지 않은 정의는 건너뜁니다 | 새 Codex 세션에서 `/hooks`를 열고 WikiBrain 정의 다섯 개를 검토한 뒤 현재 해시를 신뢰하세요. |

### 3. 간단히 동작 확인하기

에이전트 hook에 의존하지 않고 안전한 테스트 문구를 저장하고 찾아봅니다.

```bash
brainctl remember --global --title "WikiBrain 동작 확인" "내 WikiBrain 확인 표식은 Cobalt-719다."
brainctl recall "Cobalt-719"
```

검색 결과에 `Cobalt-719`와 로컬 Markdown 출처가 표시되어야 합니다.
`remember` 결과에 문서 ID가 나오며, 테스트 후 필요 없다면 삭제할 수 있습니다.

```bash
brainctl forget --document DOCUMENT_ID --apply
```

새 Claude 세션 또는 hook을 신뢰한 Codex 세션에서 “내가 선호하는 테스트
명령은 `make check`라고 기억해”라고 말하고 턴을 끝내세요. 같은 저장소에서
새 세션을 시작한 뒤 선호하는 테스트 명령을 물어보면 대화 수집, 기억 승격,
인덱싱, 세션 간 회상을 한 번에 확인할 수 있습니다.

### Codex를 hook 신뢰 없이 `init`만으로 쓸 수 있나요?

일부 기능은 가능합니다.

- **수동 명령은 즉시 사용할 수 있습니다.** `brainctl init`이 다음 Codex
  세션에서 사용할 공용 WikiBrain skill을 설치하며, hook 승인 전에도
  `brainctl remember`와 `brainctl recall`이 동작합니다.
- **일반 개인 설치로 자동 모드까지 안전하게 켤 수는 없습니다.** Codex는
  관리되지 않는 모든 명령 hook의 정의를 검토하도록 강제하고 현재 해시에
  신뢰를 저장합니다. 신뢰하기 전에는 hook을 건너뛰므로 프롬프트 자동 수집,
  턴 보관, 문맥 자동 주입이 실행되지 않습니다.
- Codex에는 `--dangerously-bypass-hook-trust` 옵션이 있지만 해당 실행 한
  번에만 적용되며 Codex도 위험한 옵션으로 표시합니다. WikiBrain은 이 옵션을
  alias, wrapper, 실행 설정 어디에도 자동으로 넣지 않습니다.
- 신뢰 검토가 영구적으로 필요 없는 유일한 경로는 시스템, MDM, cloud 또는
  `requirements.toml`로 배포하는 관리자 관리 hook 정책입니다. 이 hook은
  정책으로 강제되며 사용자 hook 화면에서 끌 수 없습니다. WikiBrain은 이
  관리자 신뢰 경계를 차지하거나 수정하지 않습니다.

대기 중인 hook 경고조차 없는, 명시적인 Codex 수동 전용 설치는 다음과
같습니다.

```bash
brainctl init --clients codex --no-hooks
brainctl remember --global "오래 보관할 사실"
brainctl recall "그 사실"
```

이 방식은 Codex/Agents skill은 설치하지만 라이프사이클 기반 자동 수집과
회상은 사용하지 않습니다. 호스트가 강제하는 신뢰 모델은 공식
[Codex hook 문서](https://learn.chatgpt.com/docs/hooks)에서 확인할 수 있습니다.

## 설치

프로그램 설치와 초기 설정은 의도적으로 분리되어 있습니다.

- 패키지 설치 단계에서는 `brainctl`과 Wikimap만 설치합니다.
- `brainctl init`을 실행해야 비로소 개인 두뇌를 만들고 Claude/Codex hook
  설정을 수정합니다. 이 명령이 사용자의 명시적인 동의 지점입니다.

### macOS 또는 Linux: Homebrew

```bash
brew install hungrytech/tap/wikibrain
brainctl init
brainctl doctor
```

Apple Silicon macOS, Intel macOS, x86_64 Linux용 bottle이 제공됩니다.
bottle 설치에는 `xcrun`, SDK 조회, 로컬 소스 빌드가 필요하지 않습니다.

### Windows: 네이티브 PowerShell

PowerShell을 열고 아래 명령을 실행합니다. 버전이 고정된 설치 스크립트를
다운로드하고 내용을 확인한 다음 WikiBrain을 설치하고 초기화합니다.

```powershell
$installer = Join-Path $env:TEMP "install-wikibrain.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/hungrytech/wikibrain/v0.1.3/scripts/install-windows.ps1" `
  -OutFile $installer
Get-Content $installer
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File $installer -Initialize
```

설치 스크립트가 하는 일은 다음과 같습니다.

1. Python 3.11 이상이 있으면 그대로 사용합니다. 없다면 `winget`으로 현재
   사용자에게 Python 3.13을 설치합니다.
2. `pipx`를 설치합니다.
3. GitHub의 버전 고정 소스 압축 파일에서 WikiBrain을 격리된 환경에
   설치합니다. Git이나 개발 도구는 필요하지 않습니다.
4. 사용자가 `-Initialize`를 명시했을 때만 `brainctl init`과
   `brainctl doctor`를 실행합니다.

Claude나 Codex 설정을 아직 바꾸고 싶지 않다면 `-Initialize`를 빼고
실행하세요. 설치가 끝나면 나중에 사용할 정확한 `brainctl init` 명령을
출력합니다. Windows의 기본 두뇌 저장 위치는
`%LOCALAPPDATA%\WikiBrain`입니다.

에이전트와 프로젝트가 WSL 안에서 실행된다면 WSL 내부에서 Linux/Homebrew
설치 방법을 사용하세요. 네이티브 Windows와 WSL은 홈 디렉터리가 다르므로,
Claude Code나 Codex를 실제로 실행하는 쪽에 설치해야 합니다.

### 코딩 에이전트에게 설치를 맡기는 방법

터미널 사용이 익숙하지 않다면 컴퓨터에서 명령을 실행할 수 있는 Claude Code,
Codex 등의 코딩 에이전트에게 공개 저장소 링크와 함께 이렇게 요청하세요.

```text
이걸 설치하고 정상 동작까지 확인해줘:
https://github.com/hungrytech/wikibrain
```

설정 내용을 먼저 검토하고 싶다면 아래 요청문을 그대로 붙여 넣으면 됩니다.

```text
https://github.com/hungrytech/wikibrain 저장소의 WikiBrain을 이 컴퓨터에
설치해줘. 먼저 README를 읽고 현재 운영체제에서 지원하는 설치 방법을 사용해.
brainctl init을 실행하기 전에 수정할 설정 파일, 추가할 hook 이벤트와 명령,
백업 파일 경로를 보여줘. 기존 Claude와 Codex 설정은 그대로 보존해야 해.
확인 후 초기화하고 brainctl doctor까지 실행해서 결과를 알려줘.
Codex hook 신뢰 절차는 우회하지 말고, 내가 /hooks에서 검토하도록 안내해줘.
```

이 방법은 로컬 명령 실행 권한이 있는 코딩 에이전트에서만 가능합니다. 컴퓨터에
접근할 수 없는 일반 웹 채팅은 설치를 대신할 수 없습니다.

### 개발용 설치

macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/brainctl init
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\brainctl.exe init
```

## `brainctl init`이 바꾸는 내용

`brainctl init`은 여러 번 실행해도 같은 항목을 중복으로 만들지 않습니다.
이미 설치된 WikiBrain 항목만 최신 상태로 갱신합니다.

1. 개인용 SQLite 상태 저장소, Markdown vault, 로그, 영수증, 고정된 hook
   shim을 만듭니다.
2. 기존 설정 JSON을 수정하기 전에 백업합니다.
3. 선택한 클라이언트마다 WikiBrain 소유의 hook 다섯 개를 구조적으로
   병합합니다.
4. 관계없는 설정과 hook, 사용자가 만든 커스텀 skill은 그대로 둡니다.
5. Claude용 WikiBrain skill과 Codex가 사용하는 공용 Agents skill을
   설치합니다.
6. 실제로 설정한 파일과 실행 파일 경로를 `installations.json`에 기록합니다.
   `brainctl doctor`는 이 기록을 기준으로 설치 상태를 검사합니다.

### 생성하거나 수정하는 파일

| 용도 | macOS/Linux | 네이티브 Windows |
|---|---|---|
| 두뇌 데이터 | `~/.local/share/wikibrain/` | `%LOCALAPPDATA%\WikiBrain\` |
| 장애 허용 hook shim | `.../bin/wikibrain-hook` | `...\bin\wikibrain-hook.ps1` |
| Claude 사용자 hook | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` |
| Codex 사용자 hook | `~/.codex/hooks.json` | `%USERPROFILE%\.codex\hooks.json` |
| Claude skill | `~/.claude/skills/wikibrain/` | `%USERPROFILE%\.claude\skills\wikibrain\` |
| Codex/Agents skill | `~/.agents/skills/wikibrain/` | `%USERPROFILE%\.agents\skills\wikibrain\` |
| 설치 기록 | `.../installations.json` | `...\installations.json` |

기존 JSON을 수정할 때는 같은 디렉터리에 아래와 같은 백업을 먼저 만듭니다.

```text
settings.json.wikibrain.20260720T142305123456Z.bak
hooks.json.wikibrain.20260720T142305123456Z.bak
```

파일이 원래 없었거나 원하는 설정이 이미 들어 있다면 불필요한 백업은 만들지
않습니다.

### 설치되는 hook 이벤트

| 이벤트 | matcher | 제한 시간 | WikiBrain이 하는 일 |
|---|---|---:|---|
| `SessionStart` | `startup\|resume\|clear\|compact` | 5초 | 세션을 등록하고 현재 프로젝트와 관련된 기억을 `additionalContext`로 전달합니다. |
| `UserPromptSubmit` | 모든 프롬프트 | 8초 | 프롬프트의 민감정보를 제거해 저장하고, 관련 기억을 찾아 모델이 답하기 전에 전달합니다. |
| `PostToolUse` | `Bash\|Edit\|Write\|NotebookEdit\|apply_patch` | 5초 | 도구 이름과 안전한 파일·작업 디렉터리 포인터만 저장합니다. 전체 도구 출력과 셸 명령은 저장하지 않습니다. |
| `Stop` | 완료된 모든 턴 | 20초 | 최종 응답의 민감정보를 제거하고 Markdown으로 보관합니다. 명시적인 기억 요청을 승격하고 Wikimap 인덱스를 갱신합니다. |
| `PostCompact` | `manual\|auto` | 20초 | 압축 요약이 있으면 handoff로 보관하고 Wikimap 인덱스를 갱신합니다. |

각 이벤트는 저장에 실패해 재시도 대기 중인 항목도 제한된 범위 안에서
처리합니다. Claude에서 백그라운드 작업이 진행 중이면 `Stop` hook이 중간
응답을 저장하지 않고, 실제 작업이 끝난 뒤 발생하는 마지막 `Stop`에서
기록합니다.

Hook은 장애가 나더라도 에이전트 실행을 막지 않는 fail-open 방식입니다.
입력이 잘못됐거나 시간이 초과된 경우, 데이터베이스가 바쁜 경우, 실행 파일이
없거나 Wikimap이 실패한 경우에도 올바른 빈 JSON과 종료 코드 0을 반환합니다.

### 기존 JSON과 병합하는 방식

WikiBrain은 고정 shim 또는 이전 `brainctl`을 호출하면서 명령 끝이
`hook --provider claude` 또는 `hook --provider codex`인 handler만
자신의 항목으로 판단합니다. 초기 설정 과정에서는:

- 오래된 WikiBrain handler만 교체하고,
- 이벤트마다 WikiBrain handler를 정확히 하나씩 두며,
- 같은 이벤트에 등록된 다른 handler는 유지하고,
- 관계없는 최상위 설정도 유지한 뒤,
- 타임스탬프 백업을 만들고 JSON을 원자적으로 교체합니다.

macOS/Linux에서는 POSIX shim을 호출합니다. Windows의 Claude 설정에는
공식 PowerShell exec-form인 `powershell.exe`와 인자 배열을 사용합니다.
Codex 설정에는 Windows 전용 `commandWindows`도 함께 기록합니다. 두
클라이언트 모두 같은 fail-open PowerShell shim을 거쳐 `pipx`가 설치한
안정적인 `brainctl.exe`를 실행합니다.

### Hook 검토와 신뢰

- Claude Code는 `~/.claude/settings.json`의 사용자 hook을 읽습니다.
  `/hooks`를 열면 이벤트, matcher, 원본 파일, 실행 명령을 확인할 수 있습니다.
- Codex는 `~/.codex/hooks.json`에서 사용자 hook을 찾지만, 관리되지 않는
  명령 hook은 사용자가 현재 정의의 해시를 검토하고 신뢰하기 전까지
  실행하지 않습니다. 새 Codex 세션을 시작하고 `/hooks`를 열어 다섯 개
  정의를 확인한 뒤 신뢰하세요. 나중에 정의가 바뀌면 다시 검토해야 합니다.
- `brainctl doctor`는 설정된 정의와 실행 파일이 올바른지 검사하지만 Codex의
  내부 저장 신뢰 상태를 의도적으로 읽거나 변경하지 않습니다. 따라서
  doctor가 `ok`여도 `/hooks` 검토를 대신하지는 않습니다.

호스트 프로그램의 전체 hook 규격은 공식
[Claude Code hook 가이드](https://code.claude.com/docs/ko/hooks-guide)와
[Codex hook 문서](https://learn.chatgpt.com/docs/hooks)에서 확인할 수 있습니다.

적용 전에 내용을 미리 보거나 수집 범위를 좁힐 수도 있습니다.

```bash
brainctl init --dry-run --json
brainctl init --workspace /path/to/project
brainctl init --workspace /path/one --workspace /path/two
```

처음 초기화할 때 workspace 허용 범위는 현재 사용자의 홈 디렉터리입니다.
홈 아래의 각 Git 저장소는 서로 다른 기억 범위로 분리됩니다. 이 경로는 수집
경계일 뿐 파일 크롤링 대상이 아닙니다. WikiBrain은 Claude Code와 Codex가
보낸 라이프사이클 이벤트만 처리하며 홈 파일을 스캔하지 않습니다.

WikiBrain이 소유한 연동만 갱신하거나 제거할 수 있습니다.

```bash
brainctl setup
brainctl hooks status
brainctl hooks uninstall
brainctl skills uninstall
```

Homebrew나 pipx에서 프로그램을 제거해도 별도로 보관된 두뇌 데이터는 삭제되지
않습니다.

## 자주 쓰는 명령

```bash
brainctl status
brainctl recall "인증 구조에 대해 어떤 결정을 내렸지?"
brainctl remember --title "선호 패키지 관리자" "Python 도구에는 uv를 사용한다."
brainctl remember --global "한국어로 간결하게 답하는 것을 선호한다."
brainctl pause
brainctl resume
brainctl forget --document memory-ID        # 미리보기
brainctl forget --document memory-ID --apply
brainctl forget --document memory-ID --cascade        # 원본 세션 미리보기
brainctl forget --document memory-ID --cascade --apply
brainctl forget --session session-ID --provider claude
brainctl forget --session session-ID --provider claude --apply
brainctl retention                          # 90일이 지난 대화 기록 미리보기
brainctl retention --apply
```

## 데이터와 개인정보 보호

기본 두뇌 디렉터리 구조는 다음과 같습니다.

```text
config.json
installations.json
state.db
vault/
  sessions/
  handoffs/
  memories/
logs/
receipts/
bin/
```

`WIKIBRAIN_HOME` 환경 변수나 `brainctl --home PATH`로 위치를 바꿀 수
있습니다.

저장 내용은 민감정보를 제거한 일반 텍스트이며 애플리케이션 수준으로 암호화되지
않습니다. FileVault, BitLocker, LUKS 같은 디스크 암호화를 켜고 디렉터리를
공유하기 전에 내용을 확인하세요. POSIX 환경에서는 디렉터리와 파일 권한을
비공개 모드로 설정합니다. Windows에서는 현재 사용자의 로컬 앱 데이터
디렉터리에 저장하고 해당 ACL을 상속합니다.

보존 기간 정리는 오래된 세션과 handoff 기록만 제거합니다. 사용자가 명시적으로
남긴 장기 기억은 이 명령으로 삭제되지 않습니다. 저장 실패로 SQLite에서
대기하던 오래된 기록도 함께 정리하며, `--apply`를 붙이지 않으면 미리보기만
합니다.

`remember`로 남긴 기억은 기본적으로 프로젝트 범위에 속합니다. 허용된 모든
프로젝트에 나타나야 하는 개인 선호에만 `--global`을 사용하세요.

“기억해” 또는 “remember”로 시작하는 명시적인 요청은 `Stop` hook이 장기
기억으로 승격합니다. 설치된 skill은 같은 요청을 수동 명령으로 한 번 더
저장하지 않도록 안내합니다.

검색 결과에는 문서 ID와 세션 ID가 포함됩니다. 일반
`forget --document`는 해당 문서만 지웁니다. 원본 대화에 남은 사실까지
지우려면 `--cascade`를 추가하세요. Cascade는 영향을 받는 모든 경로를 먼저
보여주고, `--apply`를 붙였을 때만 원본 세션 전체를 삭제합니다.

Claude와 Codex가 우연히 같은 세션 ID를 사용했다면 `--provider`를 지정해야
하며 선택한 클라이언트의 세션만 삭제합니다. 문서에 원본 세션 계보가 없으면
일부만 삭제하지 않고 cascade 자체를 거부합니다.

신뢰 경계와 내부 구조는 [ARCHITECTURE.md](ARCHITECTURE.md)를 참고하세요.
