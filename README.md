# BG3 Friend

발더스 게이트 3에서 동료 한 명과 한국어로 대화하고, 기다리기·합류·주변 관찰을 함께하는 실험적 모드입니다. 대화와 탐험 판단은 로그인한 Codex CLI, 선택한 동료의 전투 행동은 BG3의 기존 AI가 처리합니다. 미니맵 아래에 붙는 Windows 채팅창을 사용합니다.

현재 버전은 **0.2.0-rc.1 후보판**입니다. 기본 사용 형태는 **Windows x64 휴대용 ZIP**이며 Python과 Tcl/Tk, 제작된 모드 PAK를 포함합니다. 게임, Script Extender, Codex CLI와 본인 계정은 별도로 준비합니다. 일반 ZIP 사용에 WSL·별도 Python·LSLib는 필요하지 않습니다. 공개 릴리스 게시와 실행 파일 서명은 별도 절차입니다.

**[처음 설치부터 업데이트·제거까지](docs/SETUP.ko.md)** · [검증 범위](docs/VALIDATION.md) · [배포본 제작](docs/RELEASE.ko.md)

## 휴대용 앱으로 시작하기

1. 전달받은 ZIP의 SHA-256을 함께 제공된 `SHA256SUMS`와 비교하고 압축을 전부 풉니다. `BG3Friend.exe`와 `_internal` 폴더를 함께 유지합니다. 이 RC는 **서명되지 않았으며**, 체크섬 일치는 제작자 신원이나 변조 방지를 보증하는 서명이 아닙니다.
2. BG3를 한 번 주 메뉴까지 실행한 뒤 종료합니다. 기존 세이브를 백업하고, 현재 Windows 사용자의 Codex CLI에 본인 계정으로 로그인합니다.
3. `BG3Friend.exe`를 열고 게임 폴더, 게임 프로필, Codex 실행 파일을 확인합니다. 자동으로 찾지 못했거나 여러 설치가 있으면 **찾기**로 지정합니다. Script Extender가 없으면 공식 배포에서 준비한 `DWrite.dll`을 선택합니다.
4. **모드 설치·업데이트**에서 변경 파일과 백업 위치를 검토하고 **적용하기**를 누릅니다. 설치·업데이트·제거는 게임과 파티 대화를 종료한 상태에서 진행합니다.
5. 전송 안내를 읽고 Codex 연결에 동의한 뒤 **상태 확인**, **파티 대화 시작**을 누릅니다. **게임 실행**은 Steam 실행 요청입니다. 런처의 플레이와 세이브 선택은 직접 이어갑니다.
6. BG3 Friend가 켜진 세이브를 불러오고 게임으로 돌아갑니다. 채팅의 **함께하기** 또는 **··· → 동료 이름**으로 맡길 동료를 선택합니다.

설치 상태 확인, 게임 관찰 수신, 실제 모델 응답은 각각 다른 단계입니다. 세이브를 기다리는 상태를 플레이 준비 완료로 표시하지 않습니다. 버튼별 절차와 문제 해결은 [설치 안내](docs/SETUP.ko.md)를 확인하세요.

## 함께하는 방식

- 동료와 첫 대화를 끝내면 **함께하기 / 직접 할게** 선택 카드가 나타납니다. 합류 전에는 선택을 기억하며, 실제 제어는 파티 합류와 대화 종료 뒤 시작합니다. 한 번에 한 동료만 맡깁니다.
- 채팅을 클릭하고 한국어를 입력한 뒤 **Enter**로 보냅니다. **Esc**는 초안을 남겨 두고 게임으로 돌아갑니다. 다른 앱이 전면에 있으면 오버레이는 숨습니다.
- **···**에서 동료, **잠깐 쉬기**, **전투도 맡기기**, **연결 선택 바꾸기**를 바꿉니다. **대화 종료** 또는 앱의 **대화 중지**로 연결을 마칩니다.
- “잠깐 기다려줘”, “이제 같이 가자”처럼 대화할 수 있습니다. 모델의 의도와 이동 명령, 실제 도착 결과를 구분합니다. 야영지는 대화와 관찰만 지원합니다.
- 탐험을 맡긴 동료는 파티 초상화 연결을 잠시 해제합니다. 쉬기·종료·직접 선택 시 원래 함께 있던 파티원에게 다시 연결하며, 이미 혼자였던 동료는 그대로 둡니다. 게임에서 직접 다시 묶으면 AI는 이동을 멈춥니다. 다시 맡길 때는 채팅의 **··· → 동료 이름**을 선택합니다.
- 연결 선택은 이후 저장한 게임 파일에 남습니다. 선택 이전 세이브를 불러오면 다시 물을 수 있습니다. 재로드하면 대화 기억을 초기화하고 쉬는 상태로 돌아갑니다.

계정과 모델의 응답 속도·사용 가능 여부는 환경에 따라 다릅니다. 음성, 아이템 획득, NPC 대화 선택, 여러 동료의 동시 LLM 제어는 구현하지 않았습니다. 모든 영입 경로, 복잡한 전투, 다른 모드 조합과 장시간 플레이를 검증한 상태는 아닙니다.

## 전송과 저장

연결을 켜면 파티·선택한 동료·주변 대상·전투 상태 같은 게임 관찰, 최근 대화와 공유 메모를 **선택한 Codex CLI**로 보냅니다. 말하지 않아도 상황 변화에 반응하는 요청이 생길 수 있으며 본인 계정의 사용량에 반영됩니다. 기본 모델은 `gpt-6-astra`이고 앱에서 변경할 수 있습니다. Codex 앱의 다른 대화에서 모델을 바꾸는 것으로 BG3 Friend 설정이 바뀌지는 않습니다.

BG3 Friend는 CLI의 기존 로그인을 사용합니다. 인증 파일이나 API 키를 배포본·저장소·문의에 넣지 마세요. 로그인 성공은 해당 모델의 접근 권한이나 남은 사용량을 보증하지 않습니다. [OpenAI 공식 CLI 안내](https://learn.chatgpt.com/docs/codex/cli), [인증 안내](https://learn.chatgpt.com/docs/auth).

Windows 앱 설정은 Saved Games 사용자 폴더 아래 `BG3Friend/settings.json`, 설치 원본과 거래 기록은 그 아래 `install`에 있습니다. 일반적으로 `%USERPROFILE%\Saved Games\BG3Friend`이며 Windows의 실제 사용자 폴더 위치를 조회합니다. 게임 관찰·대화·제어 파일은 게임 프로필의 `Script Extender\BG3Friend`에 저장됩니다. 앱의 **진단 저장**은 허용된 버전·검사 결과·상태 코드만 내보냅니다. 설치 계획 JSON은 실제 경로를 포함하므로 공유 전에 확인하세요.

## 업데이트와 제거

새 ZIP은 새 폴더에 전부 풀고 기존 앱과 대화를 닫은 뒤 실행합니다. 같은 Windows 사용자와 설정 위치에서 **모드 설치·업데이트**를 사용하면 첫 관리 시점의 원본 백업을 이어갑니다. 기존 `DWrite.dll`과 Script Extender 설정을 덮어쓰지 않으며 일반 설치에서 콘솔·실행 로그 옵션을 강제로 켜지 않습니다.

제거는 먼저 **대화 중지 → 게임 종료 → 모드 제거 → 변경 검토 → 적용하기** 순서로 진행합니다. 이 설치기가 관리하기 전의 PAK·등록 상태로 복원하므로 예전 BG3 Friend가 이미 있었다면 그 버전이 복원될 수 있습니다. 설정·대화·세이브를 삭제하지 않습니다. 설치 뒤 사용자가 바꾼 관리 파일과 충돌하면 변경 전에 멈춥니다. 백업 폴더나 `pending.json`을 지워 강제 진행하지 마세요. 자세한 [복구·충돌 처리](docs/SETUP.ko.md#업데이트제거와-충돌-처리)를 따르세요.

## 소스 실행과 개발

휴대용 ZIP을 사용할 수 없거나 코드를 수정한다면 [Windows 소스 실행과 WSL 경로](docs/SETUP.ko.md#소스에서-실행하기)를 사용합니다. `scripts/app.py`는 같은 설정 앱의 Python 진입점이며, `scripts/launch.py`와 `Start-Friend.cmd`는 기존 소스 실행 경로입니다. PAK는 별도로 제작하거나 검증된 배포본에서 준비합니다.

Python 3.11 이상과 Tcl/Tk가 필요합니다. Linux에서는 테스트가 GUI 처리 함수도 불러오므로 `python3-tk`를 준비합니다. 아래 검사는 실제 게임이나 모델을 호출하지 않습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Windows에서는 `.venv\Scripts\python.exe`를 사용합니다. CI는 Linux/Windows 오프라인 검사와 Windows fixture ZIP의 동결 실행을 검사합니다. **Fixture 성공은 실제 게임이나 새 PC 전체 설치 성공의 근거가 아닙니다.** 실제 관찰의 버전·조건·남은 한계는 [VALIDATION.md](docs/VALIDATION.md)에 따로 기록합니다.

읽기 전용 계정 검사와 설치 검사는 범위를 명시합니다. 기본 진단은 모델을 호출하지 않습니다.

```bash
python3 scripts/doctor.py --scope account --json
python3 scripts/doctor.py --scope installation --game '<게임 전체 경로>' --io '<게임 프로필>/Script Extender/BG3Friend' --manifest '<배포 manifest.json>' --json
```

`--scope game`은 게임 프로세스, 최근 관찰, 실행 프로그램의 세션 일치를 추가합니다. `--require-gui`는 Windows Python/Tk를 검사합니다. 실제 모델 시험은 사용자가 원할 때만 `--scope account --probe`로 한 번 실행하며 사용량이 발생합니다.

## Codex에게 준비 맡기기

저장소를 연결한 Codex 작업에서 **“발더스3 하자”** 또는 **`$bg3-friend-start`**로 준비를 요청할 수 있습니다. [시작 스킬](.agents/skills/bg3-friend-start/SKILL.md)은 확인된 설치와 화면 조작 도구를 사용하고, 필요한 설정·인증·선택을 안내합니다. 다른 작업에서 사용할 등록 방법은 [Codex 스킬 안내](docs/CODEX-SKILL.ko.md)를 확인하세요.

## 주요 코드

| 경로 | 역할 |
|---|---|
| `scripts/app.py`, `companion/app.py` | Windows 설정, 설치 계획 확인, 대화 시작·중지 |
| `companion/installation.py` | 선검증, 원본 보관, 업데이트·제거, 실패 복구 |
| `companion/configuration.py`, `companion/diagnostics.py` | 사용자 설정·경로 탐색·범위별 상태 |
| `companion/model.py`, `companion/runner.py`, `companion/lifecycle.py` | 제한된 JSON 응답, 취소·연결 수명 관리 |
| `companion/gui.py`, `companion/game_window.py` | 한국어 채팅 오버레이 |
| `mod/` | Script Extender 브리지와 전투 제어 상태 |
| `scripts/build_release.py` | 사전 제작 PAK를 포함한 Windows ZIP·해시·고지 제작 |

외부 도구와 API 참고: [Script Extender](https://github.com/Norbyte/bg3se), [LSLib](https://github.com/Norbyte/lslib), [Brawl](https://github.com/tinybike/Brawl), [BG3 MCM](https://github.com/AtilioA/BG3-MCM), [UTAC](https://github.com/Vercadi/Ultimate-Tactical-AI-Companions). 외부 모드의 전술 알고리즘·게임 파일은 배포본에 포함하지 않습니다.
