# Codex에서 “발더스3 하자”로 준비하기

이 저장소에는 [.agents/skills/bg3-friend-start](../.agents/skills/bg3-friend-start/SKILL.md)와 루트 [AGENTS.md](../AGENTS.md)가 있습니다. 저장소를 작업 폴더로 사용하는 Codex는 게임 시작 요청을 이 절차로 연결합니다. 다른 작업에서도 사용하려면 아래 방법으로 개인 스킬에 등록합니다. [공식 스킬 검색 경로](https://learn.chatgpt.com/ko-KR/docs/build-skills)와 [프로젝트 지침](https://learn.chatgpt.com/ko-KR/docs/agent-configuration/agents-md)을 기준으로 구성했습니다.

## 사용자에게 제공하는 흐름

**“발더스3 하자” → 설치·연결 상태 확인 → 빠진 설정만 먼저 질문 → 승인한 설정 적용 → 게임·세이브·모드 확인 → 친구 채팅·동료 연결** 순서입니다.

Codex가 Computer Use로 런처, 게임 메뉴, 세이브 불러오기, 모드 확인, 채팅 메뉴를 조작합니다. 경로·설치 점검과 WSL·Python 명령은 명령 실행 도구로 수행합니다. 이 스킬은 Computer Use 도구 자체를 설치하거나 로그인·관리자 권한 창을 대신 처리하지 않습니다. 필요한 도구 연결이나 직접 인증 단계가 있으면 먼저 설명하고 사용자에게 그 단계만 요청합니다.

이미 정한 세이브·동료·전투 제어는 재사용합니다. 정해지지 않았다면 실제 후보를 확인한 뒤 물어보고 답을 받아 계속 진행합니다. 새 설정에 대한 승인 없이 패키지를 설치하거나 게임 파일을 변경하지 않습니다. 실행 프로세스만 켜고 사용자에게 나머지 설정을 맡기는 절차가 아닙니다.

## 처음 등록하는 Codex의 작업

1. 원본 저장소와 사용 중인 Windows 사용자·WSL 배포판·Steam 라이브러리를 확인합니다. [기본 설치 안내](SETUP.ko.md) 2–4절에 필요한 도구와 확인 방법이 있습니다. 아직 도구나 모드가 없으면 누락 목록과 적용할 변경을 먼저 사용자에게 묻습니다.
2. 아래 필드의 **실제 경로**를 확인하여 `config.local.json`을 원본 저장소에 만듭니다. 새 등록 전에는 어떤 경로와 개인 스킬 폴더를 사용할지 설명하고 승인을 받습니다. 이미 스킬 생성·갱신을 요청받은 작업에서는 그 승인으로 진행합니다.
3. `scripts/install_skill.py`를 **미리보기**로 실행합니다. 원본 스킬 파일, 등록 대상, 바뀔 파일을 확인합니다.
4. 승인된 등록을 `--apply`로 적용합니다. 설치기는 공개 스킬을 개인 폴더로 복사하고 원본 스킬에도 무시되는 `project.local.json`을 기록합니다. 기존 개인 설정의 추가 필드·`preferences`를 유지하고 바뀌는 기존 설치는 `.runtime/skill-backups/`에 백업합니다.
5. 등록된 `scripts/start.ps1 -Action Check`로 경로·설치·로그인을 점검하고, 스킬의 실행 절차로 이어갑니다. 등록 성공과 게임 준비 성공은 별개입니다.

### 로컬 설정 필드

| 키 | 채울 실제 값 |
|---|---|
| `repository` | `https://github.com/umaia1234/bg3-friend` |
| `distro` | 이 프로젝트의 Codex CLI를 준비한 WSL 배포판 이름 |
| `projectLinux` | WSL에서 본 저장소 절대 경로 |
| `projectWindows` | 같은 저장소의 Windows 절대 경로; WSL에서 `wslpath -w`로 확인 |
| `ioLinux` | 해당 게임 프로필의 `Script Extender/BG3Friend`를 WSL에서 본 절대 경로 |
| `profileWindows` | Windows의 `Larian Studios/Baldur's Gate 3` 프로필 루트 |
| `windowsPython` | 현재 런처가 사용하는 해당 프로필 사용자의 `Python311/pythonw.exe` |
| `gameWindows` | `bin/bg3_dx11.exe`가 있는 BG3 설치 루트 |
| `steamExe` | 설치된 `steam.exe`의 절대 경로 |
| `steamAppId` | 문자열 `1086940` |

프로필은 `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3`가 기본입니다. Steam 위치는 `HKCU\Software\Valve\Steam`, 게임 위치는 Steam의 `steamapps/libraryfolders.vdf`와 각 라이브러리의 `appmanifest_1086940.acf`로 확인할 수 있습니다. 원본과 설치된 스킬이 **같은 저장소·게임 프로필**을 가리키게 합니다. 별도 Windows 사용자 프로필이 여러 개면 현재 자동 런처의 선택 제한을 먼저 확인하고 [설치 안내 8절](SETUP.ko.md#8-경로와-다른-컴퓨터-설정)을 따릅니다.

Windows에서 다른 개인 작업에도 보이게 하려면 해당 Codex가 실제로 읽는 개인 스킬 폴더를 사용합니다. 공식 사용자 경로는 `%USERPROFILE%\.agents\skills`이며, 기존 설치가 `%USERPROFILE%\.codex\skills` 또는 별도 `CODEX_HOME`의 `skills`에 있다면 같은 설치를 갱신합니다. 같은 이름의 스킬을 여러 개인 폴더에 중복 등록하지 않습니다. 사용자별 경로를 공개 파일에 채워 넣지 않습니다.

### 등록 명령

아래 예시는 **WSL 프로젝트 터미널/명령 실행 도구**에서 실행합니다. `YOUR_WINDOWS_USER`와 대상 폴더는 확인한 실제 값으로 바꿉니다. `--target`은 상위 `skills` 폴더가 아니라 **bg3-friend-start 폴더 전체 경로**입니다.

```bash
python3 scripts/install_skill.py --config config.local.json --target '/mnt/c/Users/YOUR_WINDOWS_USER/.agents/skills/bg3-friend-start'
```

미리보기의 변경이 승인된 내용과 맞으면 같은 명령에 `--apply`를 붙입니다.

```bash
python3 scripts/install_skill.py --config config.local.json --target '/mnt/c/Users/YOUR_WINDOWS_USER/.agents/skills/bg3-friend-start' --apply
```

Windows Python으로도 같은 스크립트를 실행할 수 있습니다. 그 경우 `--config`와 `--target`에는 Windows 절대 경로를 전달합니다. 초기 등록은 표준 라이브러리만 사용하며 게임·모델·패키지 설치를 실행하지 않습니다. 스킬 업데이트는 원본 저장소를 확인한 후 같은 미리보기·적용 절차를 반복합니다. 공개 코드 갱신 때문에 실행 중인 게임을 다시 시작할 필요는 없습니다.

WSL UNC 경로의 `.ps1`을 직접 실행하면 Windows 서명 정책에 막힐 수 있습니다. 이 경우 위 등록기로 Windows 로컬 디스크에 개인 스킬을 등록하고 그 사본을 실행합니다. 실행 정책 변경·우회 플래그는 사용하지 않습니다. 현재 PC에서도 로컬 개인 스킬을 통해 검사했습니다.

설치 뒤 Windows PowerShell의 명령 실행 도구에서 확인합니다.

```powershell
& "<등록한 스킬 폴더>/scripts/start.ps1" -Action Check
```

스킬 변경은 Codex가 자동 감지합니다. 목록이 갱신되지 않으면 새 작업 또는 Codex 재시작 후 확인합니다. 프로젝트 스킬과 개인 스킬이 함께 보일 수 있으므로 이 저장소 안에서는 원본 스킬을 기준으로 진행합니다. 명시적 호출은 `$bg3-friend-start`입니다.

## 유지할 동작과 검증

실행 절차의 단일 원본은 [스킬](../.agents/skills/bg3-friend-start/SKILL.md)과 [상세 플레이 절차](../.agents/skills/bg3-friend-start/references/playbook.ko.md)입니다. 메뉴 이름·런처·상태 필드가 바뀌면 이 파일과 스크립트를 함께 갱신합니다. 개인 설치만 고치고 저장소 지침을 그대로 두지 않습니다.

변경 시 등록 미리보기의 무변경, 실제 등록·백업·설정 보존, 반복 등록의 무변경, 빠진 설정의 진단, 실행 상태 재사용을 확인합니다. 사용자 선택 없는 세이브/동료 결정이나 동의 없는 설치가 생기지 않는지도 실제 시나리오로 확인합니다. 테스트는 임시 폴더를 사용하고 게임·세이브·모델에 접근하지 않는 범위와 실제 게임 확인을 구분합니다. 자세한 증거 범위는 [VALIDATION.md](VALIDATION.md)에 기록합니다.
