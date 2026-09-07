# BG3 Friend

발더스 게이트 3에서 플레이어와 함께 동료 한 명을 맡는 AI 친구를 만드는 실험적 모드입니다. 대화와 탐험 판단은 Codex CLI의 `gpt-6-astra`, 전투 행동은 BG3의 기존 AI가 처리합니다.

Windows BG3 + WSL + Windows Python으로 구성됩니다. 미니맵 아래에 붙는 반투명 Windows 채팅 오버레이이며, 게임의 원래 채팅 UI를 교체하지는 않습니다. 현재 한 번에 한 동료를 맡길 수 있습니다.

**[처음 설치부터 Codex 연결까지 — 한국어 가이드](docs/SETUP.ko.md)**

## Codex에게 준비 맡기기

이 저장소를 연결한 Codex 작업에서 **“발더스3 하자”** 또는 **`$bg3-friend-start`**로 요청할 수 있습니다. [프로젝트 지침](AGENTS.md)과 [시작 스킬](.agents/skills/bg3-friend-start/SKILL.md)은 현재 설정을 점검하고, 누락 항목을 먼저 물어본 뒤 승인된 준비를 진행하도록 작성되어 있습니다. Computer Use로 게임·세이브·모드·친구 채팅·동료 선택까지 이어갑니다. 도구 접근과 실제 설치 상태에 따라 사용자 인증이나 선택이 필요한 단계는 먼저 안내합니다.

다른 작업에서도 호출하려면 [개인 스킬 등록·갱신 안내](docs/CODEX-SKILL.ko.md)를 따라 현재 PC의 경로를 등록합니다. 개인 경로·선택은 공개 저장소에 포함하지 않습니다. 이 절차는 기존 설치와 승인된 도구를 사용하는 Codex 지침이며, 별도의 무인 전체 설치 프로그램은 아닙니다.

## 플레이 흐름

1. 모드를 설치하고 WSL의 Codex CLI에 본인 계정으로 로그인합니다.
2. BG3에서 모드가 켜진 세이브를 연 뒤 `Start-Friend.cmd`를 실행합니다.
3. 동료와 첫 대화를 끝내면 채팅에 **함께하기 / 직접 할게**가 나타납니다. 합류 전에는 선택만 기억하고, 실제 제어는 파티에 합류한 뒤 시작합니다. 기존 파티원에게도 선택을 표시합니다.
4. 채팅을 클릭해서 입력하고 **Enter**로 전송합니다. **Esc**는 초안을 남겨둔 채 게임으로 돌아갑니다.
5. **···** 메뉴에서 맡길 동료, **잠깐 쉬기**, **전투도 맡기기**를 바꿉니다. **연결 선택 바꾸기**로 이전 선택을 다시 열고, **대화 종료**로 채팅과 연결 프로그램을 닫습니다.

연결 선택은 이후 저장한 게임 파일에 남습니다. 선택 전 세이브를 불러오면 다시 물을 수 있습니다. 세이브 재로드 후에는 대화 기억을 초기화하고 쉬는 상태로 돌아가며, 첫 채팅이나 동료 선택으로 재개합니다.

탐험에서는 기다리기·함께 이동하기·주변 관찰을 지원합니다. 모델의 의도, 게임에 보낸 명령, 실제 도착 결과를 구분합니다. 같은 장면에서 주기적으로 말을 만들지 않으며, 함께 이동하다 거리가 벌어지면 말없이 합류할 수도 있습니다. **야영지는 대화와 관찰만 지원합니다.**

## 설치와 실행

이 저장소는 소스 배포본입니다. 게임, Script Extender, LSLib, Windows Python, WSL과 Codex CLI는 직접 준비해야 합니다. 자동 설치 프로그램이나 게임 파일은 포함하지 않습니다.

[설치 가이드](docs/SETUP.ko.md)에서 도구 준비 → 세이브 백업 → 패키지 제작·설치 → CLI 로그인 → 실제 연결 확인을 진행하세요. Windows에서 파일 탐색기로 WSL 프로젝트 폴더를 열고 `Start-Friend.cmd`를 실행하거나, 해당 폴더의 WSL 터미널에서 실행합니다.

```bash
python3 scripts/launch.py
```

실행기는 자신의 폴더와 WSL 배포판을 찾습니다. 여러 Windows 사용자에게 게임 프로필이 있거나 기본 설치 경로를 쓰지 않으면 가이드의 경로 설정을 확인하세요.

대화와 파티·주변 인물의 상태는 Codex로 전송되며 사용량에 반영됩니다. CLI의 기존 로그인을 사용하고, 프로젝트에 인증 파일이나 API 키를 넣지 않습니다. 기본 모델을 사용할 수 있는지는 각 계정에서 확인해야 합니다. Codex 앱의 모델 선택이 이 모드의 설정을 바꾸지는 않습니다.

## 검증과 현재 한계

개발 환경에서 한국어 채팅, 실제 Astra 응답, 독립적인 대기·합류·도착, 동료 한 명의 자동 전투, 섀도하트 첫 만남 선택과 영입 후 연결·저장 후 재로드를 확인했습니다. **오프라인 검사 81개**와 실제 게임 관찰은 별개입니다. [검증 범위](docs/VALIDATION.md)에 조건과 한계를 정리했습니다.

- 전투 전술을 Astra가 직접 선택하는 단계는 아닙니다. 게임의 AI가 동료의 기존 능력·자원으로 싸웁니다.
- 음성, 상자 열기·아이템 획득, NPC 대화 선택, 캠페인 전체 이해, 여러 동료의 동시 LLM 제어는 아직 없습니다.
- 모든 영입 경로, 복잡하고 긴 전투, 여러 사람·다른 모드와의 조합, 자동 전투 상태를 포함한 세이브 복원은 추가 시험이 필요합니다.
- 새 컴퓨터 전체 설치와 장시간 플레이에서의 친구 같은 타이밍·주도성은 아직 충분히 검증하지 않았습니다.

공개 저장소에는 소스·테스트·안내만 포함합니다. 개인 세이브, 실제 대화 로그·스크린샷, 인증 정보, 로컬 작업 메모와 내려받은 외부 도구는 제외합니다.

## 개발용 오프라인 검사

프로젝트의 WSL 터미널에서 실행합니다. 이 검사는 게임이나 모델을 호출하지 않습니다.

Python 3.11 이상과 `venv`, `tkinter`가 필요합니다. Ubuntu에서 없다면 `sudo apt install python3 python3-venv python3-tk`로 준비합니다. 테스트는 Linux에서도 GUI 처리 함수를 불러오므로, Windows Python의 Tk와 별도로 WSL의 Tk가 필요합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

CLI 로그인과 빌드 파일의 존재 여부를 확인하려면 아래 명령을 사용합니다. 기본 명령은 모델을 호출하지 않습니다.

```bash
python3 scripts/doctor.py
```

실제 모델 응답까지 한 번 확인하려면 `python3 scripts/doctor.py --probe`를 실행합니다. `--offline` 실행 옵션은 개발용 고정 응답 모델이며 실제 게임 엔진 검증을 대신하지 않습니다.

## 구조

| 경로 | 역할 |
|---|---|
| `mod/` | Script Extender Lua 브리지와 자동 전투 상태 정의 |
| `companion/model.py` | Codex의 제한된 JSON 판단과 동료 성격 |
| `companion/runner.py` | 관찰, 비동기 판단, 실행 전 재검증, 결과 기록 |
| `companion/gui.py`, `companion/game_window.py` | 미니맵에 붙는 한국어 채팅 |
| `companion/director.py` | 상황 변화, 기다리기·합류 약속, 방문 대상 |
| `scripts/install.py`, `scripts/uninstall.py` | 백업을 남기는 설치와 제거 |
| `tests/` | Python 검사와 모의 엔진에서 실제 Lua를 실행하는 검사 |

게임과 연결 프로그램은 `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\BG3Friend` 안의 JSON 파일로 통신합니다. 모델이 생성한 코드를 실행하지 않으며 게임에서도 허용된 행동·동료·대상·세션을 다시 검사합니다.

## 개발 참고 자료

- [Norbyte Script Extender API](https://github.com/Norbyte/bg3se/blob/main/Docs/API.md), [공식 배포](https://github.com/Norbyte/bg3se/releases)
- [Norbyte LSLib](https://github.com/Norbyte/lslib/releases): `.pak` 제작 도구
- [Brawl](https://github.com/tinybike/Brawl): Osiris 이동 함수의 사용 방식 참고
- [BG3 MCM](https://github.com/AtilioA/BG3-MCM): 모드 메타데이터 형식 참고
- [UTAC 상태 정의](https://github.com/Vercadi/Ultimate-Tactical-AI-Companions/blob/master/UTAC/Public/UTAC/Stats/Generated/Data/Status_Combat.txt): 우호적 자동 전투 상태의 게임 API 사용 방식 참고
- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)

외부 모드의 전술 알고리즘이나 데이터·게임 파일을 이 저장소에 포함하지 않습니다.
