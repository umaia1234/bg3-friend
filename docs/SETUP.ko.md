# BG3 Friend 설치와 사용 안내

0.2.0-rc.1 후보판 기준입니다. **휴대용 ZIP을 받은 분은 아래 앱 설치 순서**, 코드를 실행·수정하는 분은 뒤의 **소스에서 실행하기**를 따르세요. Windows x64 ZIP에는 Python·Tcl/Tk·모드 PAK가 들어 있습니다. 일반 사용에 WSL이나 PAK 제작 도구는 필요하지 않습니다.

이 RC는 서명되지 않았습니다. 새 PC 전체 설치, 모든 모드 조합과 장시간 플레이의 검증을 뜻하지 않으며, 확인한 조건과 결과는 [검증 기록](VALIDATION.md)을 따릅니다. 공개 ZIP 게시 여부와 코드 서명은 별도입니다.

## 준비할 것

| 항목 | 확인 방법 |
|---|---|
| Windows의 BG3 | 실제 게임 폴더 안에 `bin/bg3_dx11.exe` 또는 `bin/bg3.exe`가 있어야 합니다 |
| 게임 프로필 | BG3를 한 번 주 메뉴까지 실행하고 종료하면 `PlayerProfiles/Public/modsettings.lsx`가 만들어집니다 |
| Script Extender | 기존 설치를 사용하거나 [Norbyte 공식 배포](https://github.com/Norbyte/bg3se/releases)의 `DWrite.dll`을 준비합니다 |
| Windows Codex CLI와 본인 로그인 | [OpenAI 공식 CLI 안내](https://learn.chatgpt.com/docs/codex/cli)에 따라 준비합니다 |
| 휴대용 ZIP과 해시 | 같은 배포의 ZIP, `SHA256SUMS`, 검증 기록과 고지를 함께 확인합니다 |

기존 세이브가 있다면 게임을 닫은 상태에서 백업합니다. 기본 위치는 `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\PlayerProfiles\Public\Savegames\Story`입니다. 이 폴더를 사용자가 정한 별도 백업 위치로 복사합니다. 모드 설치의 파일 백업은 세이브 백업을 대신하지 않습니다.

게임·Codex CLI·Extender 설치와 로그인이 끝나 있으면 다시 준비하지 않습니다. BG3 Friend가 게임 또는 계정 인증을 대신 설치하지는 않습니다. Steam이 아닌 설치는 게임 폴더를 직접 지정하고 게임을 직접 실행합니다. 앱의 **게임 실행** 버튼은 Steam용입니다.

## 휴대용 앱 설치

1. PowerShell에서 ZIP 해시와 제공된 목록을 비교합니다. 파일명이 다르면 받은 파일명으로 바꿉니다.

   ```powershell
   Get-FileHash -LiteralPath '.\BG3Friend-0.2.0-rc.1-windows-x64.zip' -Algorithm SHA256
   Get-Content -LiteralPath '.\SHA256SUMS'
   ```

   대소문자를 제외한 64자리 해시가 같아야 합니다. 체크섬은 파일 일치 검사이며 제작자의 신원이나 악의적 변경을 검증하는 전자서명이 아닙니다. 출처가 불명확하거나 해시가 다르면 실행하지 말고 전달자에게 확인합니다. Windows 보안 경고가 나오면 출처와 검증 범위를 확인한 뒤 사용자가 실행 여부를 판단합니다.

2. ZIP을 본인에게 쓰기 권한이 있는 새 폴더에 **전부 압축 해제**합니다. `BG3Friend.exe`와 `_internal` 폴더를 분리하지 않습니다. 압축 파일 안에서 직접 실행하지 않습니다.
3. 게임과 기존 파티 대화를 종료한 뒤 `BG3Friend.exe`를 엽니다. **자동 찾기** 결과를 확인하고 필요한 경로를 **찾기**로 지정합니다.

   | 앱 항목 | 선택할 위치 |
   |---|---|
   | 게임 폴더 | `bin`을 포함하는 `Baldurs Gate 3` 폴더. 드라이브는 설치 위치에 맞춥니다 |
   | 게임 프로필 | `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3` 전체 폴더. `Public`이나 `Savegames` 자체를 고르지 않습니다 |
   | Codex 실행 파일 | 현재 Windows 사용자로 실행할 실제 `codex.exe` |
   | 모델 | 기본값 `gpt-6-astra`. 계정에서 허용되는 모델인지 별도로 확인합니다 |
   | Extender DLL | 게임 `bin/DWrite.dll`이 없을 때만 준비한 `DWrite.dll`을 선택합니다 |

   여러 게임 설치나 사용자 프로필이 있으면 직접 고릅니다. 다른 사용자의 프로필로 설치하지 않도록 확인합니다. 현재 설치 경로는 `Public` 프로필을 사용하며 다른 게임 프로필 형식은 자동으로 변환하지 않습니다. 기존 `DWrite.dll`은 교체하지 않으므로 실제로 사용하던 Script Extender 설치인지 확인합니다.

4. **설정 저장**, **모드 설치·업데이트**를 누릅니다. 먼저 PAK 해시, 필수 파일, 모드 XML과 변경 대상이 검사됩니다. **모드 변경 확인** 창에서 추가·교체·제거 파일과 백업 위치를 검토한 뒤 **적용하기**를 누릅니다. 취소하면 설치 대상은 변경하지 않습니다.
5. 완료 뒤 **상태 확인**으로 설치와 로그인을 확인합니다. BG3 Friend 패키지와 등록이 준비됐다는 의미이며, 아직 게임 로드나 모델 응답까지 확인한 것은 아닙니다.

기존 다른 모드의 등록과 순서를 보존하고 BG3 Friend 등록만 갱신합니다. 일반 설치는 `ScriptExtenderSettings.json`을 바꾸거나 Console·LogRuntime 옵션을 켜지 않습니다. 잘못된 XML, 충돌, 실행 중인 게임 또는 실행 여부 확인 실패가 있으면 설치가 거부됩니다.

## 로그인·전송 동의와 첫 연결

앱에서 선택한 **Windows Codex CLI**에 본인 계정으로 로그인해야 합니다. PowerShell에서 확인할 때도 같은 실행 파일을 사용합니다. 다음 경로는 실제 선택한 값으로 바꿉니다.

```powershell
& 'C:\선택한 Codex 폴더\codex.exe' login status
& 'C:\선택한 Codex 폴더\codex.exe' login
```

두 번째 명령은 로그인이 필요할 때만 실행합니다. 브라우저의 인증은 본인이 완료합니다. 계정·워크스페이스가 지원한다면 공식 인증 문서의 기기 코드 방법도 사용할 수 있습니다. 인증 파일을 프로젝트에 복사하거나 문의에 첨부하지 않습니다. [OpenAI 인증 안내](https://learn.chatgpt.com/docs/auth).

BG3 Friend는 선택한 CLI의 기존 로그인을 사용합니다. 연결을 켜면 파티·동료·주변 대상·전투 상태의 관찰, 최근 대화와 공유 메모가 Codex로 전송되고 **본인 계정 사용량**에 반영됩니다. 대화를 보내지 않아도 상황 변화에 모델 요청이 생길 수 있습니다. 로그인 성공은 모델 접근 권한이나 남은 사용량을 보장하지 않습니다.

1. 앱의 전송·저장 안내를 읽고 **Codex 연결에 동의합니다**를 선택합니다. 설정을 저장하고 **상태 확인**을 누릅니다.
2. **파티 대화 시작**을 누릅니다. 게임이 아직 없으면 세이브를 기다립니다. 앱 창을 최소화해 두어도 됩니다.
3. **게임 실행** 또는 평소 방법으로 BG3를 엽니다. Larian 런처의 **플레이**를 누르고 본인이 원하는 세이브를 불러옵니다. 모드 확인 화면에서는 **BG3 Friend가 켜진 상태**인지 확인합니다.
4. 게임으로 돌아와 미니맵 아래 채팅을 확인합니다. 다른 앱이 전면에 있거나 게임이 최소화되면 채팅은 숨습니다.
5. 동료와 대화를 끝낸 뒤 나오는 **함께하기 / 직접 할게** 카드에서 선택합니다. 합류 전에는 선택만 기억하고 실제 제어는 파티에 합류한 뒤 시작합니다. 이미 합류한 동료는 **··· → 동료 이름**으로 선택할 수도 있습니다.
6. 채팅을 클릭하고 “잠깐 기다려줘”처럼 입력한 뒤 **Enter**로 보냅니다. **Esc**는 초안을 남기고 게임으로 돌아갑니다. 답변과 실제 동료 동작을 확인합니다.

일반 NPC 모두에게 연결 카드가 뜨지는 않습니다. 연결 선택은 이후 저장한 게임에 남으며 선택 전 세이브를 불러오면 다시 물을 수 있습니다. 재로드하면 이전 대화 기억을 지우고 쉬는 상태로 돌아갑니다. 한 번에 한 동료만 맡깁니다. 야영지는 대화와 관찰만 지원합니다.

탐험을 맡기면 해당 동료의 파티 초상화 연결을 잠시 해제해 기본 자동 추종이 기다리기 명령을 방해하지 않게 합니다. 쉬기·종료·직접 선택 시 원래 함께 있던 파티원에게 다시 연결합니다. 원래 따로 움직이던 동료와 사용자가 직접 바꾼 연결은 유지합니다. 원래 파티원이 아직 로드되지 않았다면 복구를 기다립니다. 게임에서 직접 다시 묶으면 AI는 이동을 멈추며, 다시 맡길 때는 채팅의 **··· → 동료 이름**을 선택합니다. 이 제어는 Larian의 [DetachFromPartyGroup](https://docs.baldursgate3.game/index.php?title=DetachFromPartyGroup)과 [AttachToPartyGroup](https://docs.baldursgate3.game/index.php?title=AttachToPartyGroup)을 사용합니다.

## 쉬기와 종료

| 원하는 동작 | 조작 |
|---|---|
| 맡긴 동료를 잠시 직접 조작 | 채팅 **··· → 잠깐 쉬기** |
| 영입 후 연결하기로 한 선택 취소 | **··· → 합류 기다리기 취소** |
| 다시 함께하기 | **··· → 다시 함께하기** 또는 새 채팅 |
| 전투를 직접 조작 | **··· → 전투도 맡기기** 해제 |
| 다른 동료에게 맡기기 | **··· → 다른 동료 이름** |
| 이전 연결 선택 다시 보기 | **··· → 연결 선택 바꾸기** |
| 연결 프로그램과 채팅 종료 | **··· → 대화 종료**, 또는 앱의 **대화 중지** |

쉬기·세션 변경·종료 시 진행 중 모델 작업을 취소하고 새 판단을 멈추도록 구현되어 있습니다. 이미 게임에 전달된 행동의 해제는 게임 상태 반영을 기다릴 수 있습니다. 정지 표시와 동료 제어를 확인한 뒤 앱을 닫습니다. 연결을 끄기 위해 Codex 계정에서 로그아웃할 필요는 없습니다.

## 업데이트·제거와 충돌 처리

**업데이트:** 대화를 중지하고 BG3와 기존 앱을 닫습니다. 새 ZIP을 새 폴더에 전부 풀고 같은 Windows 사용자로 실행합니다. 같은 설정 위치의 **모드 설치·업데이트 → 변경 검토 → 적용하기**를 사용합니다. 옛 `_internal` 폴더에 새 파일을 섞지 않습니다. 자동 다운로드·백그라운드 업데이트는 하지 않습니다.

**제거:** **대화 중지 → 게임 종료 → 모드 제거 → 변경 검토 → 적용하기** 순서입니다. 설치기가 처음 관리하기 전의 PAK·모드 등록을 복원합니다. 그 이전에 BG3 Friend가 이미 있었다면 이전 모드가 복원될 수 있습니다. 기존 공용 `DWrite.dll`은 유지하며, 이번 설치가 새로 놓은 DLL은 변경되지 않았을 때 최초 상태로 복원합니다. 앱 설정·대화·세이브는 제거 대상에 포함되지 않습니다.

설치·업데이트·제거 모두 같은 설치 상태를 계속 사용해야 합니다.

| 실행 환경 | 기본 설치 기록 |
|---|---|
| Windows 휴대용 앱·Windows 소스 CLI | Saved Games 사용자 폴더 아래 `BG3Friend/install` — 보통 `%USERPROFILE%\Saved Games\BG3Friend\install` |
| Unix/WSL 소스 CLI | `$XDG_STATE_HOME/bg3-friend/install`, 미설정이면 `~/.local/state/bg3-friend/install` |
| 앱의 별도 `--config-root` | 지정한 폴더 아래 `install` |
| CLI의 별도 `--state-root` | 지정한 폴더 자체 |

다른 PC·사용자에 설치 기록을 옮겨 기존 기록처럼 사용하지 않습니다. Windows와 WSL 설치기는 서로 다른 경로 형식을 기록하므로 같은 게임에 번갈아 설치·제거하지 않습니다. 기존 환경에서 관리하던 설치를 마친 뒤 새 환경으로 전환하는 절차를 별도로 정합니다. 실행 프로그램만 WSL에서 쓰는 것과 설치 관리자를 바꾸는 것은 구분합니다.

앱 설정·설치 백업의 위치는 Windows Saved Games 사용자 폴더 API로 구합니다. 게임 세이브 자체는 위에서 설명한 BG3 프로필 위치에 남습니다. 앱 컨테이너가 LocalAppData 환경변수를 다른 캐시로 연결하는 경우에도 동일한 앱 상태 위치를 사용하도록 분리했습니다. 설치 계획에 표시된 실제 백업 경로를 확인하세요. 별도 `--state-root`를 지정했다면 그 값을 계속 사용합니다.

- `conflicts`가 나오면 설치 이후 관리 파일이나 BG3 Friend 등록이 변경된 것입니다. **충돌한 경로·변경 내용과 최초 백업을 먼저 확인**합니다. 다른 모드 관리자와 앱을 닫고 현재 파일도 별도 보관한 뒤 어느 버전을 유지할지 결정합니다. 강제 덮어쓰기 옵션은 없습니다. 충돌을 해결한 후 계획을 다시 확인합니다.
- 적용 중 파일 작업이 실패하면 이번 거래에서 바꾼 파일을 역순으로 복원합니다. `rolled_back: true`이면 복구된 파일 상태에서 원인을 해결하고 다시 계획합니다. 여러 업데이트 뒤에도 처음 관리하기 전의 원본 백업을 유지합니다.
- `rollback_errors`, `pending.json` 또는 복구 필요 오류가 남으면 원본·거래 기록을 보존하고 복구가 필요한 파일부터 확인합니다. `install/transactions/<ID>/journal.json`과 거래 전 파일이 근거입니다. 표식이 없어도 미완료·손상·누락 저널을 발견하면 다음 설치·제거를 거부합니다. **자동 복구 명령은 아직 없으며**, 기록을 지워 재시도를 강제하면 안 됩니다. 전원 손실·강제 프로세스 종료 이후의 실제 복구는 별도 확인이 필요합니다.
- 설치 전에 있던 다른 모드는 유지하며, 설치 후 추가한 다른 모드 등록도 제거 과정에서 보존합니다. 세이브 안에 남은 모드 상태를 정리하는 도구는 아니므로 자동 전투 상태를 저장한 세이브의 제거 후 복원은 [검증 한계](VALIDATION.md)를 확인합니다.

새 엔진은 옛 `.runtime/backups` 형식의 설치 기록을 자동으로 이관하지 않습니다. 기존 모드가 있는 상태에서 RC를 처음 설치하면 그 시점의 파일을 최초 원본으로 보관합니다. 원본·기록이 불명확하면 파일을 임의 삭제하지 말고 기존 백업과 설치 경로를 먼저 확인합니다.

## 진단과 문의

휴대용 앱에서는 **상태 확인** 후 **진단 저장**을 사용합니다. 저장된 JSON에는 허용된 앱·Python 버전, 검사 결과와 실행 상태·오류 코드만 포함됩니다. 대화·계정 진단 원문·세이브·개인 경로를 넣지 않습니다. 자동 업로드는 하지 않습니다.

| 증상 | 확인할 순서 |
|---|---|
| 앱이 열리지 않음 | ZIP 해시 → 전체 압축 해제 → `_internal` 포함 → Windows 보안 알림·사용자 권한 |
| Codex 실행 파일을 찾지 못함 | Windows에 설치한 실제 `codex.exe`를 **찾기**로 선택 → 같은 파일의 로그인 확인 |
| 로그인은 됐지만 답변 실패 | 모델 이름·계정 접근 권한·사용량·CLI 버전과 오류 코드 확인 |
| 설치 파일·명세 오류 | 맞는 버전 ZIP을 새 폴더에 다시 풀기. 다른 버전 파일을 섞지 않기 |
| `modsettings.lsx` 없음 | BG3를 주 메뉴까지 한 번 실행 후 종료 → 게임 프로필 전체 경로 확인 |
| 설치·제거가 실행 중 오류로 거부됨 | 대화 중지와 BG3 종료 확인. 실행 확인 실패면 PowerShell/WSL 상호 운용 문제부터 해결 |
| 채팅이 보이지 않음 | 파티 대화 시작 → 모드 활성 세이브 로드 → 게임 전면 → 최근 관찰 확인 |
| 함께하기 이후 아직 조작하지 않음 | 파티 합류·대화 종료·선택 동료·쉬기 상태 확인 |
| 오래된 연결 상태·중복 실행 | 기존 앱/대화를 정상 종료하고 상태 확인. `runner.lock`을 지워 강제로 실행하지 않기 |

### 런처의 데이터 불일치

이 경고만으로 세이브나 게임 파일이 손상됐다고 판단하지 않습니다. **파일 목록 열기**를 확인하고, 열리지 않으면 `%LOCALAPPDATA%\Larian Studios\Launcher\Cache`의 현재 게임 버전에 해당하는 `steam_<버전>_alteredFiles.txt`를 읽습니다. 런처는 예상과 다른 설치 파일과 Mods 폴더의 파일을 이 목록에 기록합니다. [Larian 공식 진단 안내](https://baldursgate3.game/support/how-to-submit-a-bug-report_85).

이 RC의 개발 PC에서는 `bin\DWrite.dll`, `bin\ScriptExtenderSettings.json`, 프로필의 `Mods\BG3Friend.pak`만 목록에 있었습니다. 이 세 항목은 준비한 모드·Extender 파일과 대조할 수 있습니다. 확인된 추가 모드 파일만 나열됐고 설치 진단이 통과했다면 안내를 닫고 승인된 모드 플레이를 이어갑니다. 모르는 파일이나 기본 게임 파일 변경도 나열되면 해당 파일부터 확인합니다. 경고를 없애기 위해 필요한 DLL·PAK를 지우거나 **다시 보지 않음**을 자동 선택하지 않습니다.

소스의 `doctor.py`도 읽기 전용 진단을 제공합니다. `--scope account`는 계정만, 기본 `installation`은 계정과 설치 파일·해시·등록을, `game`은 현재 게임과 연결까지 검사합니다. 성공 종료 코드는 **선택한 범위에서 필수 검사가 통과했다는 뜻**입니다. 설치 상태가 준비돼도 실제 모델·게임 동작은 별도입니다.

## 소스에서 실행하기

이 절은 저장소를 받은 개발자용입니다. 소스 파일은 휴대용 ZIP에 포함되지 않습니다. Python 3.11 이상과 Tcl/Tk가 필요합니다. 경로 예시는 실제 값으로 바꾸고 해당 저장소 폴더에서 실행합니다.

### Windows 소스 앱

PowerShell에서 가상 환경을 만듭니다. Windows Python은 Tcl/Tk 구성 요소를 포함해야 하며 특정 사용자 폴더·드라이브·Python 마이너 버전에 고정되지 않습니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

검증된 배포본의 `_internal\bundle\BG3Friend.pak`와 `manifest.json`을 저장소의 `dist`에 함께 복사합니다. 다음 `C:\Tools\BG3Friend`는 본인이 풀어 둔 폴더로 바꿉니다.

```powershell
$friendBundle = 'C:\Tools\BG3Friend\_internal\bundle'
New-Item -ItemType Directory -Force -Path '.\dist'
Copy-Item -LiteralPath (Join-Path $friendBundle 'BG3Friend.pak') -Destination '.\dist\BG3Friend.pak'
Copy-Item -LiteralPath (Join-Path $friendBundle 'manifest.json') -Destination '.\dist\manifest.json'
.\.venv\Scripts\python.exe scripts/app.py
```

이 앱의 설정·설치·시작 방법은 위 휴대용 앱과 같습니다. 이미 설치된 native 앱과 같은 기본 사용자 설정을 사용합니다. 하나의 설치에 두 앱을 동시에 실행하지 않습니다.

### CLI에서 설치 계획 검토 후 적용

다음은 **Windows 소스 CLI** 예시입니다. `$friendGame`은 실제 게임 폴더로 바꾸세요. `--dry-run`은 읽기 전용 계획 JSON이며, 같은 인수에서 이를 빼고 실행하는 명령은 **설치를 적용하겠다는 명시적 실행**입니다. 별도 확인 질문을 표시하지 않습니다.

```powershell
$friendGame = 'D:\SteamLibrary\steamapps\common\Baldurs Gate 3'
$friendLocal = .\.venv\Scripts\python.exe -c 'from companion.windows_paths import local_appdata; print(local_appdata())'
$friendProfile = Join-Path $friendLocal "Larian Studios\Baldur's Gate 3"
$friendState = .\.venv\Scripts\python.exe -c 'from scripts.install import default_state_root; print(default_state_root())'
$friendInstallArgs = @('--game', $friendGame, '--profile', $friendProfile, '--manifest', '.\dist\manifest.json', '--state-root', $friendState)
.\.venv\Scripts\python.exe scripts/install.py @friendInstallArgs --dry-run
```

게임·대화를 종료하고 출력의 경로·변경·백업을 검토합니다. Extender가 없다면 위 인수에 `--script-extender '<준비한 DWrite.dll>'`을 더해 다시 미리 봅니다. 적용하기로 결정한 뒤 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts/install.py @friendInstallArgs
```

명세 대신 `--package '<PAK 전체 경로>' --package-sha256 '<검토한 SHA-256>' --version '0.2.0-rc.1'`을 사용할 수 있습니다. 사전 제작 PAK 설치에는 LSLib나 .NET이 필요하지 않습니다. 반환 JSON의 `ok`, `mode`, `plan`, `result` 또는 `conflicts`·복구 오류를 확인합니다.

같은 상태 위치로 제거를 미리 보고, 파일 변경에 동의한 뒤 두 번째 명령을 실행합니다. 대화·게임이 실행 중이면 제거를 거부하며 제어 파일을 사후 수정하지 않습니다.

```powershell
.\.venv\Scripts\python.exe scripts/uninstall.py --state-root $friendState --dry-run
.\.venv\Scripts\python.exe scripts/uninstall.py --state-root $friendState
```

### WSL 소스 실행

WSL은 기존 Linux Codex 설치를 계속 사용할 때의 대체 경로입니다. 배포판 이름은 `wsl --list --verbose`에서 확인하고 **실제 준비한 배포판의 터미널**에서 명령을 실행합니다. WSL 전체 설치 안내는 [Microsoft 공식 문서](https://learn.microsoft.com/en-us/windows/wsl/install)를 따릅니다. Windows Python/Tk는 채팅 표시용으로 별도 필요합니다.

Ubuntu에 필요한 모듈이 없다면 `python3`, `python3-venv`, `python3-tk`를 준비합니다. 프로젝트에서 환경을 만들고 해당 WSL 안의 Codex CLI에 본인 계정으로 로그인합니다. Windows 인증 파일을 복사하지 않습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
codex login status
# 로그인할 때만 실행합니다.
codex login
.venv/bin/python scripts/doctor.py --scope account --json
```

게임 프로필과 Windows Python의 **WSL에서 실행 가능한 경로**를 지정합니다. 아래 두 값은 예시이며 실제 사용자·드라이브·Python 경로로 바꿉니다. `wslpath -u '<Windows 전체 경로>'`로 변환할 수 있습니다.

```bash
friendIO="/mnt/c/Users/YOUR_USER/AppData/Local/Larian Studios/Baldur's Gate 3/Script Extender/BG3Friend"
friendWindowsPython='/mnt/d/Programs/Python/pythonw.exe'
.venv/bin/python scripts/launch.py --io "$friendIO" --gui-python "$friendWindowsPython"
```

`--gui-python`을 생략하면 실행기가 Windows Python을 탐색하지만 여러 설치가 있는 PC에서는 명시하는 편이 분명합니다. `--no-gui`는 개발용으로 채팅창을 생략합니다. `Start-Friend.cmd`/VBS는 기존 WSL 소스 실행기로 남아 있으며, 준비한 배포판·경로를 확정하려면 위 직접 명령 또는 등록된 Codex 스킬을 사용합니다.

WSL에서 설치를 관리하는 경우에도 Windows와 같은 `install.py --game --profile --manifest --state-root --dry-run` 순서를 사용하되 모든 인수는 WSL 경로로 줍니다. 이후 업데이트·제거를 같은 WSL과 상태 위치에서 수행합니다. Windows에서 이미 관리 중인 설치에는 별도의 WSL 설치 기록을 만들지 않습니다.

### 범위를 지정한 소스 진단

아래 명령은 WSL 예시입니다. `friendGame`, `friendIO`, `friendWindowsPython`을 실제 값으로 설정하고 저장소 `dist`에 검증한 PAK·manifest를 준비한 뒤 실행합니다. Windows에서는 `.venv\Scripts\python.exe`와 Windows 경로를 사용하며 `--windows-python`을 생략할 수 있습니다.

```bash
friendGame='/mnt/d/SteamLibrary/steamapps/common/Baldurs Gate 3'
.venv/bin/python scripts/doctor.py --scope installation --game "$friendGame" --io "$friendIO" --manifest dist/manifest.json --require-gui --windows-python "$friendWindowsPython" --json
.venv/bin/python scripts/doctor.py --scope game --game "$friendGame" --io "$friendIO" --manifest dist/manifest.json --json
```

기본값은 `installation`이며 `--game`과 `--io`가 빠지면 성공하지 않습니다. `game` 검사는 기본 5초 이내 관찰과 8초 이내 실행 상태, 같은 세션을 요구합니다. GUI 검사는 Windows Python/Tcl/Tk 로딩 확인으로, 실제 오버레이 표시를 대신하지 않습니다. 모델·게임 동작을 실행하거나 파일을 고치지 않습니다. 원시 대화·계정 출력은 JSON에 포함하지 않습니다.

실제 모델 연결을 **한 번 시험하기로 결정했을 때만** 실행합니다. 실제 게임 자료 대신 합성 장면과 “잠깐 기다려줘” 메시지를 보내며 계정 사용량이 발생합니다. 자동 시작·반복 점검에 넣지 않습니다.

```bash
.venv/bin/python scripts/doctor.py --scope account --probe --json
```

### PAK·ZIP 제작과 검사

직접 수정한 모드를 PAK로 만들 때만 [LSLib 공식 배포](https://github.com/Norbyte/lslib/releases)의 `Divine.exe`와 그 배포에서 요구하는 Windows .NET 런타임을 준비합니다. 다음 명령은 PAK를 `dist`에 제작하며 게임에 설치하지 않습니다.

```powershell
.\.venv\Scripts\python.exe scripts/install.py --build-only --divine 'D:\Tools\LSLib\Packed\Tools\Divine.exe'
```

출력 PAK를 검토하고 출력된 해시로 설치 계획을 만듭니다. 앱용 `manifest.json`과 Python/Tk 포함 ZIP을 제작하는 계약은 [RELEASE.ko.md](RELEASE.ko.md)를 따릅니다. 배포 제작기는 도구·게임·계정 정보를 내려받거나 실제 PC에 모드를 설치하지 않습니다.

오프라인 검사에는 `pip install -e '.[test]'`와 `python -m pytest -q`를 사용합니다. 실제 Lua를 모의 엔진에서 실행하는 검사, 설치·복구 fixture, Windows 동결 실행과 실제 게임 관찰은 서로 다른 증거입니다. 어느 결과가 확인됐는지는 [VALIDATION.md](VALIDATION.md)를 확인하세요. Codex에 시작 준비를 맡기는 별도 등록 절차는 [스킬 안내](https://github.com/umaia1234/bg3-friend/blob/main/docs/CODEX-SKILL.ko.md)에 있습니다.
