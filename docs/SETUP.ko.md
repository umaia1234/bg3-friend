# BG3 Friend — 처음 설치부터 동료 연결까지

2026-09-07 기준. Windows에서 BG3를 실행하고, WSL의 Codex CLI로 동료 한 명을 맡기는 로컬 프로토타입 안내입니다. **처음 설치한다면 2번부터, 설치와 로그인이 끝났다면 5번부터 진행하세요.**

이 저장소는 소스 배포본입니다. 게임·Script Extender·LSLib·Python은 별도로 준비합니다. 자동 설치 프로그램은 아직 없고, 빈 컴퓨터에서 전체 설치 과정을 새로 수행한 검증도 아직 하지 않았습니다. 경로와 여러 사용자 환경은 8번을 확인하세요.

Codex에게 화면 조작과 시작 준비를 맡기려면 [스킬 등록·실행 지침](CODEX-SKILL.ko.md)을 사용하세요. **“발더스3 하자”** 요청에서 빠진 설정을 먼저 물어보고, 승인 뒤 아래 설치 절차와 세이브·동료 연결을 이어가도록 구성되어 있습니다.

## 1. 캐릭터를 만났을 때 연결할지 선택할 수 있나요?

**동료를 처음 만나 대화를 끝내면 미니맵 아래 채팅에 “함께할까?”가 나타납니다.** **함께하기**를 누르면 Codex에 맡기고, **직접 할게**를 누르면 직접 조작합니다. 한 번에 한 명을 맡길 수 있습니다. 채팅 프로그램을 실행해 둬야 선택 카드가 보입니다.

| 원하는 동작 | 현재 상태 |
|---|---|
| 합류한 레이젤을 Codex에 맡기기 | 가능: ··· → 레이젤 |
| 다른 동료는 직접 조작하기 | 가능: 선택한 한 명만 맡깁니다 |
| 맡기던 동료를 다시 직접 조작하기 | 가능: ··· → 잠깐 쉬기 |
| 나중에 다른 동료로 바꾸기 | 가능: ··· → 다른 동료 이름 |
| 첫 만남에 자동으로 연결 여부 묻기 | 대화가 끝난 뒤 채팅 안에 표시 |
| 게임의 원래 대화 선택지에 연결 버튼 넣기 | 아직 없음 |
| 동료마다 함께하기·직접 조작 선택 기억하기 | 게임 세이브에 함께 저장 |
| 이전 연결 선택 바꾸기 | ··· → 연결 선택 바꾸기 → 동료 이름 |
| 여러 명을 동시에 맡기기 | 아직 없음 |

파티 합류 전에도 선택은 할 수 있지만 **실제 제어는 합류한 뒤** 시작합니다. 전투·대화 중이거나 채팅을 쓰는 동안에는 선택 카드를 기다렸다가 보여줍니다. 중간에 설치했다면 현재 파티원부터 물어봅니다. 다른 동료를 이미 맡기고 있을 때 함께하기를 누르면 새 동료로 바뀝니다. 게임 내 캐릭터 초상화를 클릭하는 것과 채팅의 동료 선택은 별개입니다.

선택은 **그 뒤에 저장한 게임 파일**에 남습니다. 선택하기 전 세이브를 불러오면 다시 물을 수 있습니다. 합류를 기다리면 채팅 위에 **합류 기다리는 중**이 표시됩니다. **··· → 합류 기다리기 취소**로 대기를 취소할 수 있습니다. 다른 동료가 이미 활동 중이면 **잠깐 쉬기**로 멈춥니다. 다른 동료 선택·대화 종료·세이브 재로드도 자동 연결 대기를 취소합니다. 이후 파티에 합류한 동료를 ··· 메뉴에서 직접 선택해 시작하세요.

Codex 계정 로그인은 한 번 준비하고 그 로그인을 사용합니다. 캐릭터별로 계정을 연결하는 방식은 아닙니다. 연결된 친구가 상황을 이해하도록 **파티와 주변 인물의 이름·상태도 모델에 전달**됩니다. 제어 대상으로 선택하지 않은 캐릭터의 정보까지 제외하는 기능은 없습니다.

## 2. 필요한 프로그램 준비

| 프로그램 | 역할 | 개발 중 확인한 구성 |
|---|---|---|
| Windows BG3 | 실제 게임 | Steam, DirectX 11, 4.1.1.7398727 |
| WSL 2 / Ubuntu-24.04 | Codex 연결 프로그램 실행 | 필요 |
| WSL Python 3 | 연결 프로그램 실행 | 필요 |
| Windows Python 3.11 | 게임 위 한국어 채팅 | 기본 사용자 경로의 Python311 |
| Codex CLI와 ChatGPT 로그인 | Astra 판단 | 개발 환경에서 실제 응답 확인 |
| Windows .NET 8 Runtime x64 | 모드 패키지 제작 도구 실행 | 준비된 LSLib의 요구 사항 |
| Script Extender와 LSLib | 게임 연결과 패키지 제작 | 아래 `.tools` 경로에 직접 준비 |

**이미 있는 프로그램은 다시 설치하지 않아도 됩니다.**

WSL이 없다면 Windows 시작 메뉴에서 **PowerShell을 관리자 권한으로 실행**해 아래 명령을 입력하고, 안내에 따라 재시작한 뒤 Ubuntu 사용자 이름과 비밀번호를 만드세요. 이때의 Windows 관리자 확인 창은 WSL 설치에 필요한 절차입니다. [Microsoft WSL 설치 안내](https://learn.microsoft.com/en-us/windows/wsl/install)

```powershell
wsl --install -d Ubuntu-24.04
```

설치 상태는 일반 PowerShell에서 확인합니다. Ubuntu-24.04 행의 VERSION이 2여야 합니다.

```powershell
wsl --list --verbose
```

Windows Python이 없다면 [Python 3.11.9 공식 배포 페이지](https://www.python.org/downloads/release/python-3119/)의 **Windows installer (64-bit)**로 설치하세요. `tcl/tk and IDLE` 구성 요소를 포함하고, 현재 실행기가 찾는 기본 사용자 경로 `%LOCALAPPDATA%\Programs\Python\Python311`에 설치합니다. 다른 Python 경로를 쓰려면 8번을 확인하세요.

패키지를 제작할 Windows .NET이 없다면 [.NET 8 공식 다운로드](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)에서 **.NET Runtime / Windows / x64**를 설치합니다. Linux용 런타임과 구분하세요.

Ubuntu를 열려면 일반 PowerShell에서 실행합니다.

```powershell
wsl -d Ubuntu-24.04
```

그 **Ubuntu 터미널**에서 필요한 기본 도구가 없을 때 설치합니다.

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk git curl unzip
```

## 3. 프로젝트 폴더와 모드 설치

먼저 BG3를 한 번 주 메뉴까지 실행한 뒤 닫습니다. 설치기는 이때 생기는 `PlayerProfiles/Public/modsettings.lsx`를 사용합니다. 기존 세이브가 있다면 게임이 꺼진 상태에서 백업하세요. 아래 **PowerShell** 명령은 바탕 화면에 날짜가 붙은 새 백업 폴더를 만듭니다.

```powershell
$bg3SaveSource = Join-Path $env:LOCALAPPDATA "Larian Studios\Baldur's Gate 3\PlayerProfiles\Public\Savegames\Story"
$bg3SaveBackup = Join-Path ([Environment]::GetFolderPath('Desktop')) ("BG3-Saves-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $bg3SaveSource) {
    Copy-Item -LiteralPath $bg3SaveSource -Destination $bg3SaveBackup -Recurse
}
```

앞서 연 **Ubuntu 터미널**에서 소스를 받습니다. 예시는 홈 폴더 아래 `projects/bg3-friend`를 사용하며 다른 위치에 받아도 됩니다.

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/umaia1234/bg3-friend.git
cd bg3-friend
```

다음 실행 때도 이 프로젝트 폴더에서 명령을 실행하세요. Ubuntu 터미널에서 `cd "$HOME/projects/bg3-friend"`로 돌아올 수 있습니다.

그 **Ubuntu 터미널**에서 다음 파일들이 있는지 확인합니다.

```bash
ls scripts/install.py mod/Mods/BG3Friend/meta.lsx
ls .tools/lslib/Packed/Tools/Divine.exe .tools/bg3se/DWrite.dll
```

첫 줄의 파일이 없다면 프로젝트 폴더 위치가 잘못됐거나 소스가 빠진 것입니다. `.pak` 파일만 받아서는 채팅 프로그램까지 실행할 수 없습니다. `companion`, `mod`, `scripts` 폴더와 `Start-Friend.cmd`, `Start-Friend.vbs`가 함께 필요합니다.

두 번째 줄의 도구가 없다면 공식 배포본으로 준비합니다. 현재 설치기는 다운로드를 자동으로 하지 않습니다.

1. [LSLib v1.20.4 공식 배포](https://github.com/Norbyte/lslib/releases/tag/v1.20.4)에서 **ExportTool-v1.20.4.zip**을 받습니다. 프로젝트에 `.tools/lslib` 폴더를 만들고 압축을 풉니다. 최종 파일 위치가 **`.tools/lslib/Packed/Tools/Divine.exe`**가 되어야 합니다. `Packed` 폴더 전체와 함께 들어온 파일들을 유지하세요.
2. [Script Extender 공식 배포](https://github.com/Norbyte/bg3se/releases)의 **Installation → from here**로 압축을 받습니다. 프로젝트에 `.tools/bg3se` 폴더를 만들고 **DWrite.dll**을 넣습니다. 실제 게임 `bin` 폴더로의 복사는 다음 설치 명령이 처리하며 기존 DLL이 있으면 유지합니다.
3. 파일 탐색기에서 프로젝트를 열려면 프로젝트의 **Ubuntu 터미널**에서 아래 명령을 실행합니다. 이 창에서 `.tools` 폴더를 만들거나 내려받은 파일을 복사할 수 있습니다.

```bash
explorer.exe .
```

BG3와 기존 BG3 Friend 채팅을 닫은 뒤, 프로젝트의 **Ubuntu 터미널**에서 설치합니다. **아래 명령의 `YOUR_WINDOWS_USER`는 실제 Windows 사용자 폴더 이름으로 바꾸세요.** Steam 라이브러리가 다른 드라이브에 있으면 `--game`도 맞춥니다. Windows 파일 탐색기에 `%LOCALAPPDATA%`를 입력하면 실제 사용자 경로를 확인할 수 있습니다.

```bash
python3 scripts/install.py --game '/mnt/c/Program Files (x86)/Steam/steamapps/common/Baldurs Gate 3' --profile "/mnt/c/Users/YOUR_WINDOWS_USER/AppData/Local/Larian Studios/Baldur's Gate 3"
```

성공하면 `Installed:`와 `Rollback manifest:`가 표시됩니다. 패키지는 게임 프로필의 `Mods/BG3Friend.pak`에 설치되고, 변경 전 파일은 프로젝트의 `.runtime/backups/날짜/`에 남습니다. 세이브 파일을 설치 대상으로 덮어쓰지 않습니다.

## 4. Codex 로그인과 모델 연결 확인

이 모드는 **Ubuntu 안의 Codex CLI**를 사용합니다. 현재 대화 중인 앱 창을 동료별로 연결하는 방식은 아닙니다.

CLI가 없다면 **Ubuntu 터미널**에서 공식 설치 명령을 실행합니다. 이미 설치되어 있으면 건너뜁니다. [OpenAI Docs — Codex CLI](https://learn.chatgpt.com/docs/codex/cli)

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

로그인 상태를 확인합니다. 기본 설치 위치를 직접 사용하므로 터미널 PATH에 등록되기 전에도 실행할 수 있습니다.

```bash
"$HOME/.local/bin/codex" login status
```

ChatGPT로 로그인되어 있으면 다음으로 진행합니다. 로그인이 필요하면 아래 명령을 실행하고 열린 브라우저에서 본인의 ChatGPT 계정으로 로그인하세요. API 키를 프로젝트에 붙여넣을 필요는 없습니다. [OpenAI Docs — 인증](https://learn.chatgpt.com/docs/auth)

```bash
"$HOME/.local/bin/codex" login
```

브라우저 로그인이 되지 않는 환경에서는 공식 인증 안내의 기기 코드 로그인을 사용할 수 있습니다. 계정 또는 워크스페이스에서 기기 코드 로그인이 허용되어 있어야 합니다.

```bash
"$HOME/.local/bin/codex" login --device-auth
```

다시 프로젝트 폴더의 **Ubuntu 터미널**에서 상태를 확인합니다.

```bash
python3 scripts/doctor.py
```

`Codex login: available`과 `Mod package: present`가 나오면 CLI 로그인과 빌드 파일이 확인된 것입니다. **이 명령만으로 게임 연결이나 Astra 응답까지 확인된 것은 아닙니다.**

실제 Astra 응답까지 시험하려면 아래 명령을 한 번 실행합니다. 모델 요청 한 번이 발생하며 사용량에 반영됩니다. 성공하면 `Astra structured response:`와 한국어 응답이 표시됩니다.

```bash
python3 scripts/doctor.py --probe
```

현재 버전은 `gpt-6-astra`로 고정되어 있으며 개발 환경의 로그인에서는 실제 응답을 확인했습니다. 각 계정에서 이 모델을 이용할 수 있는지는 별도 확인이 필요합니다. Codex 앱에서 대화 모델을 바꾸더라도 모드의 모델이 자동으로 바뀌지는 않습니다.

## 5. 게임에서 동료 연결하기

1. BG3를 실행하고 **게임 불러오기**에서 세이브를 선택합니다. **모드 확인** 창이 나오면 **BG3 Friend가 체크된 상태**로 **게임 시작**을 누릅니다.
2. Windows 파일 탐색기에서 프로젝트의 **Start-Friend.cmd**를 더블클릭합니다. 같은 게임에 한 번만 실행합니다. 이미 실행 중이면 기존 채팅을 사용하세요.
3. 게임 화면으로 돌아가면 **미니맵 아래 작은 반투명 채팅**이 나타납니다. 다른 앱을 보고 있거나 게임이 최소화되어 있으면 숨습니다.
4. 동료 연결 카드에서 **함께하기** 또는 **직접 할게**를 누릅니다. 처음 만난 동료는 대화가 끝난 뒤 카드가 나옵니다. 파티에 합류한 동료는 **··· → 맡길 동료 이름**으로 바로 시작할 수도 있습니다. 처음부터 표시된 동료에게 첫 메시지를 보내도 연결이 시작됩니다.
5. 채팅 아래 **클릭해서 말 걸기…**를 눌러 “잠깐 기다려줘” 같은 말을 쓰고 **Enter**를 누릅니다. 게임 조작으로 돌아가며 응답을 기다립니다. **Esc**는 작성 중인 글을 남겨둔 채 게임으로 돌아갑니다.
6. 사람 캐릭터를 움직여보고 “이제 같이 가자”라고 말해 보세요. 실제로 기다리고 합류하는지 볼 수 있습니다. 야영지에서는 대화와 관찰만 지원합니다.

일반 NPC 모두에게 카드가 뜨지는 않습니다. 게임이 동료로 지정한 캐릭터와 실제로 대화했거나 파티에 합류했을 때 표시합니다. 파티 합류 전에는 연결 카드로 선택만 기억하고, 바로 조작하는 ··· 동료 목록에는 합류한 뒤 나타납니다.

대화·탐험 판단은 Astra가 하고, **전투도 맡기기**가 켜져 있으면 선택한 동료의 전투 행동은 게임 AI가 처리합니다. 사용자의 캐릭터와 선택하지 않은 동료는 직접 조작합니다. 한 번의 간단한 실제 전투에서 자동 이동·공격·처치를 확인했으며 복잡한 전투의 전술 품질은 추가 확인이 필요합니다.

연결이 활성화되면 말하지 않아도 주변 상황 변화에 모델이 반응할 수 있습니다. 대화와 관찰이 Codex로 전송되어 사용량에 반영됩니다.

## 6. 쉬기, 전투만 해제하기, 종료하기

| 하고 싶은 일 | 조작 |
|---|---|
| 현재 동료의 대화·자동 행동을 쉬게 하기 | ··· → 잠깐 쉬기 |
| 영입 후 자동 연결하기로 한 선택 취소 | ··· → 합류 기다리기 취소 |
| 다시 맡기기 | ··· → 다시 함께하기, 또는 새 채팅 전송 |
| 대화는 계속하고 전투만 직접 하기 | ··· → 전투도 맡기기의 체크 해제 |
| 다른 동료에게 맡기기 | ··· → 다른 동료 이름 |
| 거절했던 동료의 연결 카드 다시 보기 | ··· → 연결 선택 바꾸기 → 동료 이름 |
| 채팅과 연결 프로그램을 모두 닫기 | ··· → 대화 종료 |

쉬는 동안 새 자동 판단을 시작하지 않습니다. 이미 시작한 모델 요청이나 판정 중인 공격은 끝날 수 있습니다. 세이브를 다시 불러오면 되돌리기 전의 대화·기억을 지우고 쉬는 상태로 돌아갑니다. 그 후 첫 채팅을 보내거나 동료를 선택해 재개합니다. 동료 연결을 끄기 위해 Codex 계정에서 로그아웃할 필요는 없습니다.

## 7. 안 될 때 확인할 것과 제거 방법

게임 상태를 확인하려면 프로젝트의 **Ubuntu 터미널**에서 실행합니다. `YOUR_WINDOWS_USER`를 본인의 폴더 이름으로 바꾸세요. 이 명령은 상태를 읽기만 하며 모델을 호출하지 않습니다.

```bash
python3 scripts/doctor.py --io "/mnt/c/Users/YOUR_WINDOWS_USER/AppData/Local/Larian Studios/Baldur's Gate 3/Script Extender/BG3Friend"
```

`Game session`, `Party`, 최근 몇 초 이내의 `Snapshot age`가 보이는지 확인하세요. 오래된 파일이 남아 있을 수 있으므로 세션 이름만으로 연결 성공을 판단하지 않습니다.

| 증상 | 확인 순서 |
|---|---|
| 채팅이 안 보임 | 게임 세이브 로드 → 모드 체크 → Start-Friend.cmd 실행 → 게임으로 돌아오기 |
| `Game snapshot: unavailable` | BG3 Friend가 체크됐는지, Script Extender가 로드됐는지 확인 |
| `Codex: unavailable` 또는 `login required` | 4번의 Ubuntu CLI 설치·로그인 확인 |
| `응답 연결 확인` 또는 Astra 시험 실패 | CLI 로그인과 계정의 Astra 사용 가능 여부를 확인. 로그인만 성공했다고 모델 이용도 보장되지는 않음 |
| 새 동료의 연결 카드가 안 보임 | 채팅 실행 → 실제 대화 종료 → 전투와 글쓰기 종료 확인. 이미 선택했다면 ··· → 연결 선택 바꾸기에서 다시 열기 |
| 함께하기를 눌렀는데 아직 조작하지 않음 | 파티 합류 전에는 선택만 기억함. 대화가 끝나고 실제 합류한 뒤 시작 |
| `Divine.exe` 또는 `DWrite.dll`을 찾지 못함 | 3번의 `.tools` 폴더 구조 확인 |
| `modsettings.lsx`가 없음 | BG3를 주 메뉴까지 한 번 실행한 뒤 종료. 다른 프로필을 쓰면 설치기의 경로 조정 필요 |
| `Close BG3 before installing` | 게임을 완전히 닫고 다시 설치 |
| 이미 실행 중이라는 안내 | 기존 채팅을 사용하거나 ··· → 대화 종료 후 다시 실행 |

제거하려면 먼저 채팅의 **대화 종료**를 누르고 BG3도 닫습니다. `YOUR_WINDOWS_USER`를 바꾼 뒤 프로젝트의 **Ubuntu 터미널**에서 실행합니다.

```bash
python3 scripts/uninstall.py --profile "/mnt/c/Users/YOUR_WINDOWS_USER/AppData/Local/Larian Studios/Baldur's Gate 3"
```

제거기는 BG3 Friend 패키지와 해당 모드 등록을 제거하고 제거 직전 파일을 백업합니다. 다른 모드·공용 Script Extender·세이브 파일은 유지합니다. 자동 전투 상태가 켜진 채 새로 저장한 파일의 제거·재로드는 실제 게임에서 별도 검증이 필요합니다.

## 8. 경로와 다른 컴퓨터 설정

실행기는 자신의 폴더를 기준으로 동작합니다. 파일 탐색기의 WSL 폴더에서 실행하면 해당 배포판을 선택하고, Windows 드라이브에 둔 폴더에서 실행하면 기본 WSL 배포판을 사용합니다. Windows 폴더를 쓴다면 그 기본 배포판에 Codex를 설치하고 로그인하세요.

WSL 배포판 이름에 영문·숫자·밑줄·마침표·하이픈 외의 문자가 있으면 해당 배포판의 터미널에서 `python3 scripts/launch.py`로 실행하세요.

| 항목 | 기본 동작 | 조정할 곳 |
|---|---|---|
| 프로젝트 위치 | 실행기와 같은 폴더 | `companion`, `scripts`, 실행기 파일들을 함께 유지 |
| WSL 배포판 | WSL 폴더의 배포판, 또는 기본 배포판 | 준비·로그인한 배포판과 일치해야 함 |
| BG3 설치 위치 | 사용자가 설치 명령에 지정 | `--game` |
| Windows 게임 프로필 | Windows 사용자 폴더에서 하나를 찾음 | 여러 개면 아래 `--io`로 직접 지정 |
| Windows Python | 게임 프로필 사용자 아래 `Python311/pythonw.exe` | 다른 위치라면 `scripts/launch.py`의 Windows Python 경로 |

게임 프로필을 자동으로 하나만 고를 수 없는 경우, 프로젝트의 **Ubuntu 터미널**에서 실행합니다. `YOUR_WINDOWS_USER`를 실제 이름으로 바꾸세요.

```bash
python3 scripts/launch.py --io "/mnt/c/Users/YOUR_WINDOWS_USER/AppData/Local/Larian Studios/Baldur's Gate 3/Script Extender/BG3Friend"
```

기본 `Public` 이외의 게임 프로필은 설치기 경로 조정이 필요합니다. 새 컴퓨터에서는 본인의 Codex 계정으로 로그인합니다. 개인 인증 파일을 프로젝트에 복사하지 마세요.

## 검증 범위

[검증 범위와 한계](VALIDATION.md)에 오프라인 검사와 개발 환경의 실제 게임 관찰을 구분해 정리했습니다. 섀도하트 해변 첫 만남·영입·저장 후 재로드와 간단한 자동 전투를 확인했으며, 모든 영입 경로나 복잡한 전투까지 검증한 것은 아닙니다. 실제 플레이 로그·스크린샷·세이브·개발자 작업 메모는 이 공개 저장소에 포함하지 않습니다.

이 안내의 외부 프로그램 설치 방식은 링크한 공식 문서와 준비된 파일을 확인해 작성했습니다. 기존 설치의 점검과 오프라인 검사는 새 컴퓨터 전체 설치 시험을 대신하지 않습니다.
