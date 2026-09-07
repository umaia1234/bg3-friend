---
name: bg3-friend-start
description: Prepare Baldur's Gate 3 and BG3 Friend through its Windows app, approved setup, saves, and companion chat; retain the WSL source launcher when configured. Use for "발더스3 하자", "발더스 게이트3 하자", "발더스 게이트 3 하자", "발게3 하자", "발더스 시작", "BG3 Friend 켜 줘", or connection checks. Ask first about missing setup, then finish approved setup through Computer Use. Do not start gameplay for strategy questions or requests only to edit/publish the project.
---

# 발더스 3 함께하기

사용자님께 존댓말로 안내합니다. 게임과 BG3 Friend를 실제 플레이 가능한 상태로 준비합니다. 설치·설정·직접 인증·미정 선택이 필요할 때 그 항목만 물어보고, 승인받은 준비는 Codex가 끝까지 수행합니다.

## 요청과 설치 구분

- **하자 / 시작:** 점검 → 필요한 설정 승인 → 앱 설정 → 게임 → 세이브 → 모드 → 친구 채팅 → 동료 연결을 이어갑니다. 런처나 `waiting_save`에서 끝내지 않습니다.
- **상태 확인:** 읽기 전용 진단만 합니다. 앱·게임을 시작하거나 연결 선택을 바꾸지 않습니다.
- **친구 채팅만 켜기:** 기존 게임과 세이브를 유지합니다.
- **연결 복구:** 게임 연결과 모델 오류를 구분하고 기존 앱에서 복구합니다. 새 앱·runner를 중복 실행하지 않습니다.
- **지침 작성·스킬화·배포:** 문서·코드 작업입니다. 별도 플레이 요청 없이 실제 게임을 조작하지 않습니다.

이 스킬의 `project.local.json`에서 설치를 찾습니다. **`nativeExe`가 있으면 등록된 Windows `BG3Friend.exe`가 기본**이며 Python/Tk를 포함합니다. `nativeConfigRoot`를 생략하면 Windows의 실제 **Saved Games 폴더/BG3Friend** 설정을 사용합니다. 보통 `%USERPROFILE%/Saved Games/BG3Friend`이지만 등록된 사용자 폴더 위치를 조회합니다. 앱은 그 폴더의 `settings.json`에 게임·프로필·Codex 경로, 모델, 전송 동의를 저장합니다. 개인 스킬의 `preferences`는 사용자 선택 기록이며 앱 설정이나 게임 저장을 덮어쓰는 명령이 아닙니다.

`nativeExe`가 없는 기존 등록은 `projectWindows`/`projectLinux`의 WSL 소스 실행 경로를 사용합니다. 등록된 native 앱이 없거나 고장났다고 WSL로 몰래 전환하지 않습니다. 설치 폴더 이동·업데이트·방식 전환이 필요하면 확인한 경로와 변경을 먼저 설명합니다.

등록 파일이 없으면 알려진 BG3 Friend 설치·저장소를 찾고 `docs/CODEX-SKILL.ko.md`를 따릅니다. 저장소 원본 스킬은 `.agents/skills/bg3-friend-start`입니다. 현재 작업 폴더나 예제 경로를 실제 설치라고 가정하지 않습니다. 결정할 수 없을 때 필요한 설치 위치만 묻습니다. 새 등록 경로는 먼저 확인받되, 이미 요청받은 스킬 생성·갱신은 그 승인으로 진행합니다.

## 읽기 전용 점검

Windows 로컬 디스크에 등록된 사본을 실행합니다. WSL UNC 경로의 `.ps1`이 서명 정책에 막히면 등록기로 로컬 사본을 만듭니다. 실행 정책 변경·우회 플래그는 사용하지 않습니다.

```powershell
& "<등록한 스킬 폴더>/scripts/start.ps1" -Action Check
```

`-Action Status`는 현재 상태만 읽습니다. `Check`는 모델을 호출하지 않으며 native 앱의 `--diagnose --report`로 만든 임시 보고서만 기록하고 지웁니다. 게임 제어·앱 설정은 바꾸지 않습니다. WSL에서 실행할 때도 `wslpath -w`로 관찰한 로컬 스킬 경로를 변환해 `powershell.exe -NoProfile -File <Windows 스크립트 경로> -Action Check`를 사용합니다.

`preflight.ready=false`라면 [플레이북의 미설정 항목 처리](references/playbook.ko.md)를 읽고 **실제 누락 항목과 적용할 변경**을 먼저 묻습니다. Native 계정 점검은 앱에 선택된 Windows Codex CLI의 로그인입니다. 기존 WSL 로그인 성공을 native 로그인 성공으로 확대하지 않습니다. 소스 실행은 지정한 WSL 배포판의 계정을 확인합니다.

Windows 네이티브 창을 제어할 Computer Use가 실제로 제공되는지도 확인하고, 해당 `computer-use` 스킬과 필수 지침을 읽습니다. 브라우저 전용 도구를 게임 조작 수단으로 가정하지 않습니다. 필요한 연결·직접 인증은 사용자에게 그 단계만 요청합니다.

## 실행과 화면 준비

```powershell
& "<등록한 스킬 폴더>/scripts/start.ps1" -Action Start
```

친구만 켤 때는 `-HelperOnly`를 붙입니다. Native 설정이 빠졌으면 설정 창만 열고 exit 1과 누락 항목을 반환할 수 있습니다. 이것은 설치나 전송 동의가 완료됐다는 뜻이 아닙니다. 이미 메인 창이 열려 있으면 그 창을 재사용합니다. 설정을 마친 새 실행은 `--start`로 앱과 runner를 연결합니다. 기존 메인 창만 있고 runner가 없으면 화면의 **파티 대화 시작**을 사용합니다.

반드시 [상세 플레이북](references/playbook.ko.md)의 설정·화면 준비·복구 절차를 이어갑니다.

1. 승인된 경로·동의·모드 설치를 앱 화면에서 완료하고 **상태 확인**과 `Check`로 재점검합니다. 직접 인증·UAC만 사용자에게 넘깁니다.
2. 실제 Larian 런처의 **플레이**를 누르며 기존 DX11/Vulkan 선택을 유지합니다.
3. 이미 플레이 중이면 그 세션을 유지합니다. 주 메뉴라면 사용자에게 정해진 세이브를 직접 불러옵니다. 없으면 화면의 후보를 확인한 뒤 그 선택만 묻습니다.
4. BG3 Friend 모드 확인과 로드 완료, 게임 전면의 오버레이를 확인합니다.
5. 사용자에게 정해진 동료·전투 제어를 실제 친구 채팅에서 설정하고 최신 상태와 화면으로 완료를 확인합니다.

## 출력 해석

| 출력 | 다음 행동 |
|---|---|
| `needs_configuration=true` | 실제 등록·앱 설정 위치를 확인하고 필요한 변경만 먼저 묻습니다. |
| `preflight.ready=false` | `missing`, `setup_required`, 진단을 읽습니다. native `login`과 `consent`는 각각 직접 로그인과 사용자 전송 동의입니다. |
| `app_ready` / `app_running=true`, `helper_running=false` | 메인 설정 창은 열렸지만 파티 대화는 준비되지 않았습니다. 그 창에서 설정·파티 대화 시작을 이어갑니다. |
| `waiting_game` / `waiting_save` | 실제 런처·게임·세이브 화면을 계속 처리합니다. |
| `game_connected=true`, `paused` | 게임 연결은 확인됐지만 친구는 쉬는 중입니다. 명시적으로 쉬게 한 기존 세션은 재개 요청 없이 풀지 않습니다. |
| `ready/thinking/acting` | 기존 작업을 유지하고 오버레이·동료 선택을 확인합니다. |
| `model_error` / `model_connection=error,retrying` | `error_code`로 계정·모델·사용량·네트워크를 진단합니다. 게임 연결 상태와 별개입니다. |
| `partial` / `runner_error` | 실제 메인·worker·오버레이 프로세스와 최근 heartbeat를 확인합니다. 중복 실행·강제 종료·잠금 삭제로 덮지 않습니다. |

`game_connected`는 게임 프로세스, 4초 이내 snapshot, 8초 이내 runner 갱신, 일치하는 세션을 확인합니다. Native는 runner 프로세스 근거도 사용합니다. 메인 앱과 `--overlay`는 별개이며, 같은 프로필의 기존 WSL helper도 재사용합니다. `model_connection=not_verified`와 `calls`는 실제 응답 성공의 증거가 아닙니다. 모델 시험은 사용자 요청·승인이 있을 때만 현재 세션의 실제 응답으로 확인합니다.

가짜 시험 채팅, 세이브 덮어쓰기, 임의 캠페인·동료 선택, 인증 파일 열기, 직접 `control.json` 수정은 하지 않습니다. 게임·친구가 준비되면 그 상태만 짧게 보고합니다. 준비 뒤의 대기는 runner가 맡으므로 Codex 예약 자동화나 반복 모델 호출을 만들지 않습니다.
