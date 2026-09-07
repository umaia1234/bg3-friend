# Codex에서 “발더스3 하자”로 준비하기

이 공개 저장소의 [.agents/skills/bg3-friend-start](../.agents/skills/bg3-friend-start/SKILL.md)와 [AGENTS.md](../AGENTS.md)가 시작 절차의 원본입니다. Windows 앱 ZIP에는 실행에 필요한 앱·PAK·안내가 들어가며, Codex 스킬 등록은 **이 저장소의 공개 소스**에서 수행합니다. 앱을 다른 폴더에 풀었어도 확인한 실행 파일을 스킬에 등록할 수 있습니다.

**“발더스3 하자” → 설치·연결 점검 → 빠진 설정만 먼저 질문 → 승인된 앱 설정·설치 → 게임·세이브·모드 → 친구 채팅·동료 연결** 순서입니다. Codex가 Computer Use로 실제 창을 확인하며 계속 진행합니다. 새 설치·전송 동의·직접 인증과 미정 세이브·동료 선택은 먼저 묻고, 답을 받으면 그 단계부터 마칩니다. 이 스킬이 Windows 제어 도구를 설치하거나 인증·UAC를 대신 처리하지는 않습니다.

## 실행 방식

| 등록 | 동작 |
|---|---|
| `nativeExe`에 확인된 `BG3Friend.exe` 경로가 있음 | Windows 앱을 기본으로 사용합니다. 앱에 Python/Tk가 포함되므로 앱 실행용 WSL·별도 Python은 필요하지 않습니다. Codex CLI와 본인 로그인은 별도로 확인합니다. |
| `nativeExe`가 없는 기존 소스 등록 | 확인된 WSL 프로젝트·프로필·Codex CLI를 사용합니다. Windows 오버레이용 Python 3.11 이상과 Tk는 별도로 필요합니다. |

등록된 native 앱을 찾지 못하면 누락을 보고하며 WSL로 자동 전환하지 않습니다. 실행 파일 이동·업데이트·방식 전환은 확인한 변경으로 처리합니다. 같은 게임 프로필의 기존 helper가 실행 중이면 중복 실행하지 않습니다.

## 등록 절차

1. 공개 저장소와 실제 앱/소스 설치를 찾습니다. 새 등록이라면 확인한 경로와 사용할 개인 스킬 폴더를 설명하고 먼저 승인받습니다. 이미 스킬 생성·갱신을 요청받았다면 그 승인으로 진행합니다.
2. 확인한 값으로 저장소에 `config.local.json`을 만듭니다. 아래 Windows 앱 설정은 WSL 경로 없이 등록할 수 있습니다. 예제 자리표시자를 실제 값으로 실행하지 않습니다.
3. `scripts/install_skill.py`를 미리보기로 실행하고 원본·대상·변경 파일을 확인합니다.
4. 승인된 내용이면 `--apply`를 붙여 등록합니다. 기존 추가 필드·`preferences`는 유지되고, 바뀌는 기존 설치는 저장소의 `.runtime/skill-backups/`에 백업됩니다. 원본 스킬에도 무시되는 `project.local.json`이 기록됩니다.
5. Windows 로컬 사본의 `scripts/start.ps1 -Action Check`로 진단합니다. 스킬 등록 성공은 게임·오버레이·모델 응답 성공과 별개입니다.

### Windows 앱 등록 필드

| 키 | 실제 값 |
|---|---|
| `repository` | `https://github.com/umaia1234/bg3-friend` |
| `steamAppId` | 문자열 `1086940` |
| `nativeExe` | 확인한 Windows 앱의 `BG3Friend.exe` 절대 경로 |
| `nativeConfigRoot` | 선택 사항. 앱의 `settings.json`이 있는 Windows 폴더. 생략하면 실제 Windows Saved Games 폴더 아래 `BG3Friend` |
| `steamExe` | 선택 사항. 확인한 `steam.exe` 절대 경로. 생략하면 등록된 Steam 게임 실행 URI를 사용합니다. |

개인 경로는 공개 파일에 채워 넣지 않습니다. 앱 실행 파일은 EXE 하나만 따로 옮기지 말고 배포 폴더 전체를 유지합니다. `C:/...`와 `C:\...` 형식 모두 지원합니다. `nativeConfigRoot`는 파일 경로가 아니라 **폴더 경로**입니다.

기본 설정 폴더는 Windows에 등록된 Saved Games 위치를 조회하며 보통 `%USERPROFILE%/Saved Games/BG3Friend`입니다. Codex 같은 패키지 앱이 물려준 `LocalCache/Local` 환경변수 경로를 새 설정 위치로 사용하지 않습니다. 실제 사용자 폴더를 확인할 수 없으면 명시적인 `nativeConfigRoot`를 확인받아 등록합니다. 이전 설정 위치에 관리 중인 설치가 있으면 해당 `nativeConfigRoot`를 명시해 기록을 유지하고, 새 위치로의 전환은 별도 변경으로 확인합니다.

앱 설정은 `nativeConfigRoot/settings.json`에 있으며 `version`, `game`, `profile`, `codex`, `model`, `timeout`, `consent` 필드를 사용합니다. 시작 스킬은 이를 읽기만 합니다. 경로·전송 동의는 승인 후 앱 UI에서 저장하며, 계정 인증 파일을 등록 설정에 넣지 않습니다. Native 앱은 그 설정에서 선택한 **Windows Codex CLI**를 사용합니다. WSL의 로그인과 같은 것으로 가정하지 않습니다.

### 기존 WSL 소스 등록 필드

`repository`, `steamAppId`와 함께 다음 필드를 사용합니다. native 등록에 기존 소스 필드가 남아 있어도 실행은 native가 우선합니다.

| 키 | 실제 값 |
|---|---|
| `distro` | Codex CLI를 준비한 WSL 배포판 이름 |
| `projectLinux` | WSL에서 본 저장소 절대 경로 |
| `projectWindows` | 같은 저장소의 Windows 절대 경로; `wslpath -w`로 확인 |
| `ioLinux` | 선택한 게임 프로필의 `Script Extender/BG3Friend`를 WSL에서 본 절대 경로 |
| `profileWindows` | 같은 게임 프로필의 Windows `Baldur's Gate 3` 루트 |
| `gameWindows` | `bin/bg3_dx11.exe` 또는 `bin/bg3.exe`가 있는 게임 루트 |
| `steamExe` | 확인한 `steam.exe` 절대 경로 |
| `windowsPython` | 선택 사항. 확인한 Windows `pythonw.exe` 경로. 없으면 소스 실행기의 자동 검색 결과를 점검합니다. |

소스 시작은 `--io`와 확인한 `--gui-python`을 명시합니다. 여러 Windows 사용자나 프로필을 하나로 가정하지 않으며 Python을 특정 `Python311` 폴더에 제한하지 않습니다. `ioLinux`를 Windows로 변환한 경로가 `profileWindows/Script Extender/BG3Friend`와 같아야 합니다. 승인된 소스 방식으로 되돌릴 때는 완전한 소스 필드를 유지하고 새 등록 입력에 `nativeExe`를 빈 문자열로 명시합니다. 필드를 단순히 생략하면 기존 설정 보존 때문에 이전 native 값이 남습니다.

### 명령 실행

다음은 **저장소의 WSL 명령 실행 도구**에서 사용하는 형식입니다. `YOUR_WINDOWS_USER`와 대상 폴더를 실제 값으로 바꾸며, `--target`은 상위 `skills`가 아니라 **bg3-friend-start 폴더 전체**입니다.

```bash
python3 scripts/install_skill.py --config config.local.json --target '/mnt/c/Users/YOUR_WINDOWS_USER/.agents/skills/bg3-friend-start'
python3 scripts/install_skill.py --config config.local.json --target '/mnt/c/Users/YOUR_WINDOWS_USER/.agents/skills/bg3-friend-start' --apply
```

등록 작업을 맡은 Codex 환경에 Windows Python이 있다면 같은 등록기에 Windows 절대 `--config`, `--target` 경로를 전달해 실행할 수도 있습니다. 등록기는 표준 라이브러리만 사용하며 앱·게임·모델·패키지를 시작하거나 설치하지 않습니다. 등록기의 Python과 Windows 앱의 내장 런타임은 구분합니다.

현재 Codex가 읽는 개인 스킬 폴더를 사용합니다. 사용자 경로 `%USERPROFILE%/.agents/skills` 또는 기존 `%USERPROFILE%/.codex/skills`·별도 `CODEX_HOME/skills` 중 실제 사용 중인 설치를 갱신하고, 같은 이름을 여러 개인 폴더에 중복 등록하지 않습니다.

WSL UNC의 스크립트가 Windows 서명 정책에 막힐 수 있으므로 Windows 로컬 디스크에 등록된 사본을 실행합니다. 실행 정책 변경이나 우회 플래그는 사용하지 않습니다.

```powershell
& "<등록한 스킬 폴더>/scripts/start.ps1" -Action Check
& "<등록한 스킬 폴더>/scripts/start.ps1" -Action Status
```

WSL에서는 `wslpath -w`로 관찰한 등록 스크립트 경로를 변환해 `powershell.exe -NoProfile -File <Windows 스크립트 경로> -Action Check`로 실행합니다. 스킬 목록이 갱신되지 않으면 새 작업 또는 Codex 재시작 후 확인합니다. 명시적 호출은 `$bg3-friend-start`입니다.

## 진단과 이어서 할 일

Native `Check`는 등록된 앱의 `--config-root <폴더> --diagnose --report <임시 JSON>`을 실행합니다. 진단 과정은 설정·게임 제어를 바꾸거나 모델을 호출하지 않으며 임시 보고서는 읽은 뒤 제거합니다. 앱 진단 exit 2의 미설정은 스킬의 `preflight.setup_required`와 exit 1로 전달됩니다. 스킬 등록 파일 자체가 없거나 형식이 잘못되면 `needs_configuration=true`, exit 2입니다.

| 항목·상태 | 다음 단계 |
|---|---|
| `native_executable`, `package` | 등록 앱과 ZIP 전체의 파일을 확인하고 필요한 복사·교체를 먼저 설명합니다. |
| `game`, `profile`, `extender`, `installed` | 실제 경로·현재 모드 상태를 확인하고 승인된 앱 설정·설치를 마칩니다. |
| `codex`, `login`, `consent` | CLI 경로·본인 로그인·전송 동의를 각각 확인합니다. 직접 인증은 사용자가 합니다. |
| `native_settings`, `native_diagnostic_report`, `native_diagnostic_failed` | 손상된 설정·배포·실행 오류를 진단하고 원본을 임의 삭제하지 않습니다. |
| `app_ready` | 기존 메인 창을 사용해 설정 또는 **파티 대화 시작**을 이어갑니다. |
| `waiting_save` | 실제 후보로 세이브 선택을 확인하고 Computer Use로 불러오기를 계속합니다. |
| `model_error`와 `game_connected=true` | 게임은 연결됐지만 모델 요청에 문제가 있습니다. 계정·모델·사용량 오류를 확인하며 세이브를 재로드하지 않습니다. |

`Start`는 이미 실행 중인 helper·앱을 재사용합니다. 미설정 native 앱은 설정 창만 열고, 준비된 새 앱은 `--start`로 파티 대화를 연결합니다. 기존 메인 창에 대해서는 화면의 **파티 대화 시작**을 사용합니다. 게임·런처·세이브·모드·오버레이·동료 선택까지의 단일 실행 절차는 [스킬](../.agents/skills/bg3-friend-start/SKILL.md)과 [플레이북](../.agents/skills/bg3-friend-start/references/playbook.ko.md)에 있습니다.

게임 프로세스, 신선한 snapshot·runner, 일치하는 세션을 연결 근거로 사용하고 native 메인 창과 worker·overlay를 구분합니다. 로그인 성공, 진단 성공, 배포 smoke 성공, `calls` 증가만으로 모델 응답이 성공했다고 말하지 않습니다. 실제 모델 시험은 사용자가 요청·승인한 경우에만 수행합니다.

## 갱신 시 확인할 것

원본 스킬·스크립트·안내를 함께 갱신한 뒤 같은 미리보기·등록을 반복합니다. 공개 코드가 바뀌었다는 이유로 진행 중 게임을 재시작하지 않습니다. 스킬 등록의 무변경·백업·설정 보존, native/source 분기, 설정 누락, JSON/한글 진단, 기존 프로세스 재사용, heartbeat·세션 불일치와 게임/모델 오류 분리를 격리 폴더에서 검사합니다. 게임 UI와 실제 모델 응답은 별도로 검증하고 범위를 구분해 보고합니다.
