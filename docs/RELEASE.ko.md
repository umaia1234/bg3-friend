# Windows 배포본 제작과 검증

이 문서는 개발자가 이미 제작한 BG3 Friend PAK와 현재 앱 소스를 Windows 휴대용 ZIP으로 묶는 절차입니다. 제작 명령은 게임·모드 설치·로그인·모델 호출을 하지 않습니다. 실제 게임용 PAK의 출처와 검증은 제작자가 먼저 확인합니다.

## 제작 계약

- 앱 버전은 `companion.__version__`을 사용합니다. PAK 메타데이터의 `Version64`와 `companion.installation.MOD_VERSION64`를 함께 갱신합니다.
- `scripts/app.py`를 Windows x64 Python에서 **PyInstaller 6.22.2**로 `onedir`, `windowed`, `_internal` 구조로 만듭니다. Python·Tcl/Tk는 결과물에 들어갑니다. PyInstaller는 Windows에서 Windows 실행 파일을 만드는 방식이며 교차 컴파일 도구가 아닙니다. [공식 6.22.2 배포](https://pypi.org/project/pyinstaller/6.22.2/), [공식 제작 옵션](https://pyinstaller.org/en/v6.22.2/usage.html).
- 코드 폴더 전체를 데이터로 복사하지 않습니다. 명시된 PAK와 그 명세만 `--add-data`로 넣습니다. 개인 설정·대화·인증·세이브·원시 검증 기록·다운로드 도구·원본 Python 소스 파일은 ZIP에 넣지 않습니다.
- Codex CLI, Script Extender의 `DWrite.dll`, LSLib, Steam, BG3는 별도 사용자 설치를 사용합니다. 이 제작기는 해당 파일들을 번들하지 않습니다.
- 현재 제작 결과는 **서명되지 않은 실행 파일**입니다. SHA-256 목록은 파일 일치 확인용이며, 제작자 신원이나 변조 방지를 보증하는 전자서명이 아닙니다.

## 준비와 실행

Windows x64 Python과 Tk를 준비한 개발 환경에서, 검토한 의존성을 설치합니다. 제작기 자체는 설치나 다운로드를 자동 실행하지 않습니다.

```powershell
python -m pip install 'PyInstaller==6.22.2'
python scripts/build_release.py --package '<제작·검증한 BG3Friend.pak>' --package-sha256 '<해당 PAK의 SHA-256>' --output-dir '<새 배포 출력 폴더>'
```

`--package-sha256`을 생략하면 명시된 PAK에서 SHA-256을 계산합니다. 이 경우에도 파일의 실제 게임 검증이나 신뢰할 출처 확인을 대신하지 않습니다. LSLib를 사용하는 소스 PAK 제작은 별도 `scripts/install.py --build-only --divine <Divine.exe>` 명령입니다. 일반 사용자에게 PAK 제작 도구를 요구하는 절차가 아닙니다.

작업 중간 파일은 기본 `.runtime/release-build/<고유 ID>`에 생성됩니다. 기존 배포 ZIP이나 `SHA256SUMS`가 있는 출력 폴더는 덮어쓰지 않습니다. 재제작할 때는 새 출력 폴더를 지정하세요.

## 실제 런타임 라이선스

제작기는 실제 사용 중인 Python의 `LICENSE.txt`, Tcl/Tk의 `license.terms`, 설치된 PyInstaller의 `COPYING.txt`를 수집합니다. Python 고지에는 그 Windows 배포본의 외부 구성 요소와 Microsoft Distributable Code 조건이 포함될 수 있으므로 전체 텍스트를 보존합니다.

일부 Windows Python 설치는 Tcl의 별도 `license.terms`를 포함하지 않고 Python의 결합 라이선스에 조건을 넣습니다. 제작기는 해당 Tcl 원문이 확인되는 경우 Python 라이선스 전체를 Tcl 고지로도 복제합니다. 그 조건도 없다면 실제 Tcl 버전에 맞는 공식 원문을 확인해서 준비한 뒤 전달합니다. 예를 들어 Tcl 8.6.12의 원문은 [공식 소스 태그](https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms)에 있습니다.

```powershell
python scripts/build_release.py --package '<검증한 PAK>' --license-file 'Tcl=<확인한 Tcl 라이선스 파일>' --output-dir '<새 배포 출력 폴더>'
```

`--license-file Component=<파일>`은 여러 번 사용할 수 있습니다. 실제 수집된 DLL·확장 모듈 목록을 검사하며, 알려진 Python/Tcl/Tk 런타임 외의 바이너리는 해당 파일 이름의 라이선스가 명시되지 않으면 제작을 중단합니다. 추가 바이너리가 예상하지 않은 의존성인지도 확인하세요. 단순히 임의의 라이선스 파일을 붙이는 것으로 검토가 끝나지는 않습니다.

OpenSSL 버전은 실제 `ssl.OPENSSL_VERSION`으로 기록합니다. OpenSSL 3용 Apache 2.0 조건이 현재 Python의 라이선스 파일에 포함되면 그 전체 파일을 `OpenSSL-LICENSE.txt`로도 보존합니다. 조건이 없으면 `--license-file OpenSSL=<일치하는 원문>`이 필요합니다. Windows Python 3.11.9의 결합 고지를 [OpenSSL 3.0.13 공식 LICENSE](https://github.com/openssl/openssl/blob/openssl-3.0.13/LICENSE.txt) 및 Tcl 8.6.12 원문과 공백을 정규화해 대조했으며 양쪽의 전체 조건이 포함되어 있음을 확인했습니다. 다른 Python 배포판은 해당 런타임 고지를 다시 확인합니다.

PyInstaller의 전체 고지는 bootloader 예외와 런타임 hook 조건을 포함합니다. 제작된 실행 파일의 조건과 PyInstaller 자체를 별도 재배포하는 조건을 혼동하지 않도록 원문을 보존합니다. [공식 COPYING.txt](https://github.com/pyinstaller/pyinstaller/blob/v6.22.2/COPYING.txt), [Python 공식 라이선스 안내](https://docs.python.org/3.11/license.html).

## ZIP 내용

```text
BG3Friend/
  BG3Friend.exe
  _internal/
    ... Python, Tcl/Tk runtime files ...
    bundle/
      BG3Friend.pak
      manifest.json
  README.ko.md
  THIRD-PARTY.md
  BUILD-MANIFEST.json
  SHA256SUMS
  licenses/
  docs/
```

`_internal/bundle/manifest.json`의 계약은 다음과 같습니다. 앱은 PAK 해시를 확인한 뒤 설치 계획에 전달합니다.

```json
{
  "version": "0.2.0-rc.1",
  "mod_version64": "36028797018963969",
  "package": {
    "path": "BG3Friend.pak",
    "sha256": "<제작한 PAK의 SHA-256>"
  },
  "fixture": false
}
```

ZIP 옆의 `SHA256SUMS`는 ZIP 전체 해시를 기록합니다. ZIP 안의 목록은 내부 파일의 해시를 기록하고, `BUILD-MANIFEST.json`은 실제 런타임 버전·바이너리 목록·서명 여부를 기록합니다. 절대 개발자 경로나 개인 환경값을 명세에 쓰지 않습니다.

## 검증 구분

`.github/workflows/check.yml`은 Linux Python 검사와 모의 Lua 엔진 검사를 실행합니다. Windows에서는 같은 오프라인 검사·코드 컴파일을 수행하고, 게임용이 아닌 PAK fixture로 휴대용 ZIP을 제작한 뒤 다른 경로에서 `--smoke-test --report <json> --config-root <임시 폴더>`를 실행합니다. 게임·로그인·사용자 설정을 사용하지 않고, Python/Tk 생성·동결 실행·PAK 해시만 검사합니다. CI fixture는 `fixture: true`와 `-fixture.zip` 이름으로 구분하며 공개 릴리스 생성이나 artifact 업로드를 하지 않습니다.

실제 배포 PAK를 포함한 ZIP도 새 폴더에서 같은 검사를 수행하고 ZIP 해시를 다시 확인해야 합니다. 이후 새 PC의 도구 준비, 실제 게임 로드, 오버레이, 동료 연결, 모델 응답은 별도 시험입니다. 오프라인 검사나 휴대용 실행 성공을 실제 게임 성공 또는 새 PC 전체 설치 검증으로 확대하지 않습니다. 현재 플레이 근거와 한계는 [VALIDATION.md](VALIDATION.md)를 따릅니다.

제작 스크립트는 GitHub 릴리스를 생성·업로드하지 않습니다. 게시가 필요한 경우에는 완성된 ZIP·해시·고지·검증 결과를 별도로 검토하고 게시 범위를 확정합니다.
