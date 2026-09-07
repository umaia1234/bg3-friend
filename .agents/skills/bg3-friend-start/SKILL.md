---
name: bg3-friend-start
description: Prepare Baldur's Gate 3 with BG3 Friend from setup checks through the playable companion chat, using Computer Use for Windows UI. Use for "발더스3 하자", "발더스 게이트3 하자", "발더스 게이트 3 하자", "발게3 하자", "발더스 시작", "BG3 Friend 켜 줘", or connection checks. Ask first about missing setup, then complete the approved setup. Do not start gameplay for strategy questions or requests only to edit/publish the project.
---

# 발더스 3 함께하기

사용자님께 존댓말로 안내합니다. 게임과 BG3 Friend를 실제 플레이 가능한 상태로 준비합니다. 화면에서 할 수 있는 작업은 Codex가 Computer Use로 이어서 수행하고, 사용자 선택·추가 설치·직접 인증이 필요할 때만 해당 정보를 요청합니다.

## 먼저 구분할 것

- **하자 / 시작:** 점검 → 필요한 설정 승인 → 게임 → 세이브 → 모드 → 친구 채팅 → 동료 연결까지 진행합니다. 런처나 `waiting_save`에서 작업을 마치지 않습니다.
- **상태 확인:** 읽기 전용 점검만 합니다. 게임을 시작하거나 중단·연결 선택을 바꾸지 않습니다.
- **친구 채팅만 켜기:** 기존 게임을 사용하며 세이브를 다시 불러오지 않습니다.
- **지침 작성·스킬화·배포:** 문서·스킬 작업만 수행합니다. 별도의 플레이 요청 없이 진행 중인 게임을 조작하지 않습니다.

## 이 설치 찾기

이 스킬 폴더의 `project.local.json`이 확인된 프로젝트·Windows 경로를 담습니다. 현재 작업 폴더를 게임 설치라고 가정하지 않습니다.

파일이 없으면 저장소 안의 스킬인지 확인합니다. 이 저장소의 원본 위치는 `.agents/skills/bg3-friend-start`이며, 루트의 `scripts/install_skill.py`와 `docs/CODEX-SKILL.ko.md`가 등록 절차입니다. 개인 스킬에서 원본 위치도 모르면 기존 작업 문맥·알려진 프로젝트부터 찾고, 결정할 수 없을 때 프로젝트 위치를 물어봅니다. 예제 경로를 실제 값으로 실행하지 않습니다.

**새 경로 등록도 미설정 항목입니다.** 현재 PC에서 확인한 경로와 등록할 스킬 위치를 보여주고 먼저 물어본 뒤 적용합니다. 이미 승인된 스킬 생성·갱신 요청 중에는 다시 묻지 않습니다.

## 점검과 준비

Windows에서는 **로컬 디스크에 등록된 개인 스킬의 스크립트**를 사용합니다. 저장소가 WSL UNC 경로라면 `.ps1` 직접 실행이 Windows 서명 정책에 막힐 수 있습니다. 원본만 있고 로컬 등록이 없다면 `docs/CODEX-SKILL.ko.md`의 미리보기·승인·등록을 먼저 수행합니다. 정책을 해제하거나 실행 우회 옵션을 추가하지 않습니다. 이 저장소 안에서는 원본 스킬 지침을 따르되 실행 코드는 갱신된 로컬 사본을 사용합니다.

```powershell
& "<이 스킬 폴더>/scripts/start.ps1" -Action Check
```

상태만 확인할 때는 `-Action Status`입니다. 이 명령들은 모델을 호출하거나 게임 제어 파일을 수정하지 않습니다. 누락 목록을 읽은 뒤 [references/playbook.ko.md](references/playbook.ko.md)의 **미설정 항목 처리**를 따릅니다. 설치 명령을 실행하기 전에 실제로 필요한 변경을 먼저 물어봅니다.

Computer Use 도구가 사용 가능한지도 확인하고, 제공되는 `computer-use` 스킬과 필수 지침을 읽습니다. 이 프로젝트가 도구를 설치하거나 Windows 접근 권한을 자동으로 부여하지는 않습니다. 화면 조작 수단이 없으면 필요한 연결을 먼저 안내합니다. 브라우저 전용 도구로 네이티브 게임을 조작할 수 있다고 가정하지 않습니다.

## 실행하고 화면에서 끝까지 이어가기

```powershell
& "<이 스킬 폴더>/scripts/start.ps1" -Action Start
```

친구만 시작할 때는 `-Action Start -HelperOnly`를 사용합니다. 실행기는 기존 프로세스를 재사용하고 새 친구 실행기를 숨겨서 시작합니다. 도구가 실행 세션 ID를 돌려주면 그 실행을 기다리며 같은 시작 명령을 중복 호출하지 않습니다.

WSL에서 작업하는 Codex는 Windows PowerShell로 **Windows 로컬 디스크에 등록된** 같은 스크립트를 실행합니다. `wslpath -w`로 **관찰한 개인 스킬 경로**를 변환하여 `powershell.exe -NoProfile -File <Windows 스크립트 경로> -Action Check` 형태로 명령 도구에 전달합니다. 입력·화면 확인은 Windows Computer Use가 실제로 제공되는 작업에서 수행해야 합니다.

다음에는 반드시 [references/playbook.ko.md](references/playbook.ko.md)의 **화면에서 플레이 준비**를 읽고 수행합니다. 핵심은 다음과 같습니다.

1. Larian 런처가 열렸다면 실제 **플레이** 버튼을 눌러 게임을 엽니다. 기존 DX11/Vulkan 선택을 유지합니다.
2. 이미 플레이 중이면 그 세션을 유지합니다. 주 메뉴라면 사용자가 정한 세이브를 직접 불러옵니다. 선택이 없으면 먼저 물어봅니다.
3. 요청한 세이브의 BG3 Friend 모드 확인과 로드 완료를 확인합니다.
4. 게임을 전면에 두고 미니맵 아래 채팅을 확인합니다. 사용자 선택에 따라 맡길 동료·전투 제어를 화면에서 설정합니다.
5. 최신 상태와 화면을 함께 확인하여 실제 준비된 상태를 짧게 보고합니다.

## 상태를 정확히 읽기

| 출력 | 다음 단계 |
|---|---|
| `needs_configuration: true` | 등록 가이드에 따라 실제 경로를 확인하고 승인 후 설정합니다. |
| `preflight.ready: false` | 누락 항목과 오류를 읽고 필요한 설정만 먼저 물어봅니다. |
| `waiting_game` | 실제 런처·게임 화면에서 다음 단계를 수행합니다. |
| `waiting_save` | 세이브 선택을 확인하고 Computer Use로 불러오기를 계속합니다. |
| `game_connected: true`, `paused` | 게임은 연결됐지만 친구 제어는 쉬는 중입니다. 현재 사용자 요청과 동료 선택에 맞게 진행합니다. |
| `ready/thinking/acting` | 기존 연결·작업을 유지하며 오버레이와 선택한 동료를 확인합니다. |
| `partial`, `runner_error`, `model_error` | 실제 오류를 진단합니다. 중복 실행·강제 종료로 덮지 않습니다. |

`game_connected`는 게임 프로세스, 4초 이내 게임 snapshot, 8초 이내 runner 파일 갱신, 일치하는 세션을 확인합니다. 이는 모델 답변의 증거가 아닙니다. `calls`는 호출 횟수입니다. 실제 응답 검증에는 성공한 현재 세션 결과가 필요합니다. `doctor.py --probe`는 유료 사용량에 반영되는 실제 모델 요청이므로 자동 시작 점검에 넣지 말고, 사용자가 연결 시험을 요청·승인했을 때만 사용합니다.

한 동료의 대화·탐험 판단은 기존 WSL Codex 로그인을, 전투는 BG3의 기존 AI를 사용합니다. 채팅과 파티·주변 상태가 Codex로 전달된다는 점은 첫 연결 설정 시 설명합니다. 현재 Codex 대화 자체가 동료 컨트롤러가 되는 것은 아닙니다.

시작 검사용 가짜 채팅, 세이브 덮어쓰기, 임의의 동료·캠페인 선택, 직접적인 `control.json`·게임 상태 조작을 하지 않습니다. 사용자가 이미 쉬게 한 진행 중 세션도 시작 확인 때문에 자동 재개하지 않습니다. 자연어 선택은 문맥에 따라 이루어지며 명시적 호출은 `$bg3-friend-start`입니다.
