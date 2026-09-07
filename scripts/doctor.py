"""Read-only, scoped diagnostics. Only explicit --probe makes one model request."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion import __version__
from companion.diagnostics import Check, bundle_package
from companion.installation import MOD_UUID, MOD_VERSION64, InstallationError
from companion.model import CodexModel, ModelFailure, find_codex, probe_cli
from companion.protocol import PROTOCOL, read_json, validate_decision
from scripts.install import game_is_running, package_metadata


def account_checks(executable: str | None) -> list[Check]:
    found = bool(executable) and Path(executable).is_file()
    checks = [Check("codex", found, "Codex CLI 실행 파일" if found else "Codex CLI가 없습니다. --codex에 실행 파일 전체 경로를 지정해 주세요")]
    if not found:
        return checks + [Check("login", False, "선택한 운영체제의 Codex CLI에 먼저 로그인해 주세요")]
    try:
        code, _ = probe_cli(executable, ["login", "status"], timeout=10)
        checks.append(Check("login", code == 0,
                            "Codex 로그인 상태 · 모델 사용 권한과 남은 사용량은 별도" if code == 0 else
                            "Codex 로그인이 필요합니다. 선택한 실행 파일로 login을 실행해 주세요"))
    except (ModelFailure, OSError, subprocess.SubprocessError):
        checks.append(Check("login", False, "Codex 로그인 상태를 확인하지 못했습니다. 실행 파일과 응답 시간을 확인해 주세요"))
    return checks


def package_details(args) -> tuple[str, str]:
    if args.package is not None or args.manifest is not None or args.package_sha256:
        package, checksum, _, mod_version = package_metadata(args)
    else:
        package, manifest = bundle_package()
        checksum, mod_version = manifest["package"]["sha256"], manifest.get("mod_version64")
    data = package.read_bytes()
    if package.suffix.lower() != ".pak" or len(data) < 8 or not data.startswith(b"LSPK"):
        raise ValueError("invalid package")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("invalid checksum")
    if hashlib.sha256(data).hexdigest() != checksum.lower():
        raise ValueError("package checksum mismatch")
    version = str(mod_version) if mod_version is not None else MOD_VERSION64
    if not version.isdecimal():
        raise ValueError("invalid mod version")
    return checksum.lower(), version


def registration_ok(path: Path, version: str) -> bool:
    """Check our exact registration without requiring/changing other mod entries."""
    root = ET.fromstring(path.read_bytes())
    lists = root.findall("./region[@id='ModuleSettings']/node[@id='root']/children")
    if len(lists) != 1:
        return False
    mod_nodes = lists[0].findall("./node[@id='Mods']")
    if len(mod_nodes) != 1:
        return False
    mods = mod_nodes[0].findall("./children")
    if len(mods) != 1:
        return False

    def own(container):
        return [node for node in container.findall("./node")
                if node.find(f"attribute[@id='UUID'][@value='{MOD_UUID}']") is not None]

    entries = own(mods[0])
    if len(entries) != 1 or entries[0].get("id") != "ModuleShortDesc":
        return False
    for name, value in (("UUID", MOD_UUID), ("Folder", "BG3Friend"), ("Version64", version)):
        attrs = entries[0].findall(f"attribute[@id='{name}']")
        if len(attrs) != 1 or attrs[0].get("value") != value:
            return False
    orders = lists[0].findall("./node[@id='ModOrder']")
    if len(orders) > 1:
        return False
    if orders:
        children = orders[0].findall("./children")
        if len(children) != 1 or len(own(children[0])) != 1:
            return False
        entry = own(children[0])[0]
        if entry.get("id") != "Module" or len(entry.findall("attribute[@id='UUID']")) != 1:
            return False
    return True


def installation_checks(args) -> list[Check]:
    checks = []
    valid_game = args.game is not None and args.game.is_absolute()
    checks.append(Check("game_path", valid_game, "게임 폴더 경로" if valid_game else "--game에 게임 설치 폴더 전체 경로가 필요합니다"))
    if valid_game:
        try:
            game_ok = any((args.game / "bin" / name).is_file() and (args.game / "bin" / name).stat().st_size > 0
                          for name in ("bg3_dx11.exe", "bg3.exe"))
            dll = args.game / "bin/DWrite.dll"
            extender_ok = dll.is_file() and dll.stat().st_size > 0
        except OSError:
            game_ok = extender_ok = False
        checks += [Check("game_executable", game_ok, "게임 실행 파일"),
                   Check("extender", extender_ok, "Script Extender DLL 존재 · 실제 로드는 게임 범위에서 확인")]
    valid_io = (args.io is not None and args.io.is_absolute() and args.io.name.casefold() == "bg3friend"
                and args.io.parent.name.casefold() == "script extender")
    checks.append(Check("io_path", valid_io, "게임 프로필의 통신 경로" if valid_io else
                        "--io에 게임 프로필/Script Extender/BG3Friend 전체 경로가 필요합니다"))
    checksum, version = None, MOD_VERSION64
    try:
        checksum, version = package_details(args)
        checks.append(Check("release_package", True, "배포 PAK 헤더·SHA-256 명세"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, InstallationError):
        checks.append(Check("release_package", False, "배포 PAK·명세를 확인하지 못했습니다. --manifest 또는 --package와 --package-sha256을 지정해 주세요"))
    if valid_io:
        profile = args.io.parent.parent
        installed = profile / "Mods/BG3Friend.pak"
        try:
            installed_ok = checksum is not None and installed.is_file() and hashlib.sha256(installed.read_bytes()).hexdigest() == checksum
        except OSError:
            installed_ok = False
        checks.append(Check("installed_package", installed_ok, "설치된 PAK가 검사한 배포본과 일치"))
        try:
            registered = registration_ok(profile / "PlayerProfiles/Public/modsettings.lsx", version)
        except (OSError, ValueError, ET.ParseError):
            registered = False
        checks.append(Check("registration", registered, "BG3 Friend UUID·폴더·버전·모드 순서 등록"))
    return checks


def gui_runtime(executable: Path) -> bool:
    code = ("import sys, tkinter; "
            "print(tkinter.Tcl().call('info', 'patchlevel')); "
            "sys.exit(0 if sys.platform == 'win32' and sys.version_info >= (3, 11) else 2)")
    try:
        status, _ = probe_cli(str(executable), ["-c", code], timeout=8)
        return status == 0
    except (ModelFailure, OSError, subprocess.SubprocessError):
        return False


def gui_checks(args) -> list[Check]:
    executable = args.windows_python or (Path(sys.executable) if os.name == "nt" else None)
    if executable is None:
        return [Check("gui_runtime", False, "WSL GUI 검사에는 --windows-python <WSL에서 실행 가능한 Windows python.exe 경로>가 필요합니다")]
    ok = executable.is_absolute() and executable.is_file() and gui_runtime(executable)
    return [Check("gui_runtime", ok, "Windows Python 3.11 이상·Tcl/Tk 로딩 · 실제 오버레이 표시는 별도" if ok else
                  "Windows Python 3.11 이상과 Tcl/Tk를 실행하지 못했습니다. --windows-python을 확인해 주세요")]


def live_checks(args) -> list[Check]:
    try:
        running = game_is_running()
    except (InstallationError, OSError, subprocess.SubprocessError):
        running = None
    checks = [Check("game_running", running is True, "게임 프로세스 실행" if running is not None else "게임 실행 여부를 확인하지 못했습니다")]
    if args.io is None:
        return checks + [Check("snapshot", False, "게임 연결 검사에는 --io가 필요합니다")]
    snapshot = read_json(args.io / "snapshot.json") or {}
    try:
        age = time.time() - (args.io / "snapshot.json").stat().st_mtime
    except OSError:
        age = float("inf")
    valid = (snapshot.get("protocol") == PROTOCOL and isinstance(snapshot.get("session"), str)
             and bool(snapshot["session"]) and isinstance(snapshot.get("player"), dict)
             and bool(snapshot["player"].get("id")))
    fresh = valid and -2 <= age <= args.snapshot_max_age
    checks.append(Check("snapshot", fresh, "현재 게임 관찰 수신" if fresh else
                        "최근 게임 관찰이 없습니다. BG3 Friend를 켠 세이브를 불러오고 --io를 확인해 주세요"))
    runner = read_json(args.io / "runner.json") or {}
    try:
        runner_age = time.time() - (args.io / "runner.json").stat().st_mtime
    except OSError:
        runner_age = float("inf")
    connected = (fresh and -2 <= runner_age < 8 and runner.get("runner") not in (None, "stopped")
                 and runner.get("session") == snapshot.get("session"))
    checks.append(Check("runner_connection", connected, "실행 중 대화 프로그램과 게임 세션 일치" if connected else
                        "대화 프로그램이 현재 세션에 연결되지 않았습니다. 파티 대화를 시작해 주세요"))
    return checks


def probe(executable: str, model: str) -> dict:
    # Synthetic scene only: no actual game observation, chat, memory or save is sent.
    scene = {"protocol": PROTOCOL, "session": "probe", "seq": 1,
             "player": {"id": "human", "position": [0, 0, 0]},
             "companion": {"id": "friend", "name": "카를라크", "position": [2, 0, 0], "selected": False},
             "nearby": [], "capabilities": ["wait", "follow", "look", "approach"]}
    result, duration = CodexModel(model=model, executable=executable).decide(
        scene, [], [{"role": "user", "text": "잠깐 기다려줘."}])
    validate_decision(result, scene)
    return {"seconds": round(duration, 2), "response": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("installation", "account", "game"), default="installation")
    parser.add_argument("--game", type=Path)
    parser.add_argument("--io", type=Path)
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--package-sha256")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--require-gui", action="store_true")
    parser.add_argument("--windows-python", "--gui-python", type=Path, dest="windows_python")
    parser.add_argument("--snapshot-max-age", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--probe", action="store_true", help="Make one explicitly requested model call with synthetic data")
    parser.add_argument("--model", default="gpt-6-astra", help="Used only by --probe")
    args = parser.parse_args(argv)
    # Reuse the install manifest parser strictly in its read-only, prebuilt branch.
    args.version, args.dry_run, args.divine = __version__, True, None
    executable = str(args.codex) if args.codex else find_codex()
    checks = [Check("python", sys.version_info >= (3, 11), "Python 3.11 이상")]
    checks.extend(account_checks(executable))
    if args.scope != "account":
        checks.extend(installation_checks(args))
    if args.require_gui or args.windows_python is not None:
        checks.extend(gui_checks(args))
    if args.scope == "game":
        if not math.isfinite(args.snapshot_max_age) or not 0 < args.snapshot_max_age <= 60:
            checks.append(Check("snapshot_max_age", False, "--snapshot-max-age는 0초 초과 60초 이하이어야 합니다"))
        else:
            checks.extend(live_checks(args))
    report = {"schema": 1, "version": __version__, "scope": args.scope, "model_called": False,
              "checks": [], "ok": False}
    if args.probe:
        if all(check.ok for check in checks if check.required):
            report["model_called"] = True
            try:
                report["probe"] = probe(executable, args.model)
                checks.append(Check("model_response", True, "합성 장면으로 모델 응답 1회 확인 · 실제 게임 동작은 별도"))
            except Exception:
                checks.append(Check("model_response", False, "모델 응답 시험이 실패했습니다. 모델 접근 권한·계정 사용량·CLI 버전을 확인해 주세요"))
        else:
            checks.append(Check("model_response", False, "선택한 범위의 필수 검사 실패로 모델을 호출하지 않았습니다"))
    report["checks"] = [asdict(check) for check in checks]
    report["ok"] = all(check.ok for check in checks if check.required)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"BG3 Friend {__version__} · 검사 범위: {args.scope}")
        for check in checks:
            print(f"{'OK' if check.ok else 'FAIL'} {check.id}: {check.detail}")
        print("이 결과는 선택한 검사 범위에만 해당합니다. 계정 성공은 설치·실제 플레이 성공을 뜻하지 않습니다.")
        print("모델 호출: " + ("명시한 1회 시험" if report["model_called"] else "없음"))
        if "probe" in report:
            print(json.dumps(report["probe"], ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
