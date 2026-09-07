"""Separate installation, account and live-game evidence without collecting chat."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from . import __version__
from .configuration import Settings
from .installation import MOD_UUID
from .model import ModelFailure, probe_cli
from .protocol import read_json


def file_age(path: Path) -> float:
    try:
        # A shared file's mtime is measured by this OS, unlike the writer's clock.
        return max(0, time.time() - path.stat().st_mtime)
    except OSError:
        return float("inf")


def game_running() -> bool | None:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "if (Get-Process -Name bg3,bg3_dx11 -ErrorAction SilentlyContinue) { 'running' } else { 'stopped' }"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return {"running": True, "stopped": False}.get(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def bundle_package() -> tuple[Path, dict]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    for folder in (base / "bundle", base / "dist"):
        manifest = read_json(folder / "manifest.json")
        if manifest:
            path = folder / "BG3Friend.pak"
            package = manifest.get("package", {})
            if (package.get("path") == "BG3Friend.pak" and isinstance(package.get("sha256"), str)
                    and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == package["sha256"]):
                return path, manifest
    raise ValueError("배포 파일 또는 SHA-256 명세를 확인하지 못했습니다.")


@dataclass
class Check:
    id: str
    ok: bool
    detail: str
    required: bool = True


def setup_checks(settings: Settings, *, check_login: bool = True) -> list[Check]:
    game, profile = Path(settings.game), Path(settings.profile)
    checks = [Check("game", bool(settings.game) and any((game / "bin" / n).is_file() for n in ("bg3_dx11.exe", "bg3.exe")),
                    "게임 설치 폴더"),
              Check("profile", bool(settings.profile) and (profile / "PlayerProfiles/Public/modsettings.lsx").is_file(),
                    "게임 프로필 · 게임을 한 번 실행하면 만들어집니다"),
              Check("extender", bool(settings.game) and (game / "bin/DWrite.dll").is_file(), "Script Extender"),
              Check("codex", bool(settings.codex) and Path(settings.codex).is_file(), "Codex 실행 파일")]
    try:
        package, manifest = bundle_package()
        checks.append(Check("package", True, f"모드 배포 파일 · {manifest.get('version', __version__)}"))
        installed = profile / "Mods/BG3Friend.pak"
        package_ok = installed.is_file() and hashlib.sha256(installed.read_bytes()).hexdigest() == manifest["package"]["sha256"]
    except (OSError, ValueError):
        checks.append(Check("package", False, "배포 파일을 확인하지 못했습니다. ZIP 전체를 다시 풀어 주세요"))
        package_ok = False
    registered = False
    try:
        tree = ET.parse(profile / "PlayerProfiles/Public/modsettings.lsx")
        registered = any(node.find(f"attribute[@id='UUID'][@value='{MOD_UUID}']") is not None
                         for node in tree.findall(".//node[@id='Mods']/children/node[@id='ModuleShortDesc']"))
    except (OSError, ET.ParseError):
        pass
    checks.append(Check("installed", package_ok and registered, "현재 버전 모드 설치·등록"))
    if check_login and checks[3].ok:
        try:
            version_code, version_output = probe_cli(settings.codex, ["--version"], timeout=5)
            if version_code != 0 or not version_output.strip().startswith("codex-cli "):
                checks[3] = Check("codex", False, "선택한 파일이 Codex CLI가 아닙니다")
                checks.append(Check("login", False, "Codex CLI 실행 파일을 선택한 뒤 다시 확인해 주세요"))
                checks.append(Check("consent", settings.consent, "게임 관찰·대화 전송 동의"))
                return checks
            login_code, _ = probe_cli(settings.codex, ["login", "status"], timeout=10)
            checks.append(Check("login", login_code == 0, "Codex 로그인"))
        except (OSError, ModelFailure):
            checks.append(Check("login", False, "Codex 로그인 상태를 확인하지 못했습니다"))
    elif check_login:
        checks.append(Check("login", False, "Codex 설치 후 로그인을 확인해 주세요"))
    checks.append(Check("consent", settings.consent, "게임 관찰·대화 전송 동의"))
    return checks


def runtime_status(folder: Path) -> dict:
    runner = read_json(folder / "runner.json") or {}
    snapshot = read_json(folder / "snapshot.json") or {}
    control = read_json(folder / "control.json") or {}
    live_states = {"waiting_game", "waiting_save", "waiting_companion", "game_disconnected", "ready", "paused",
                   "thinking", "acting", "cancelling", "retrying", "error", "call_limit"}
    alive = file_age(folder / "runner.json") < 8 and runner.get("runner") in live_states
    connected = alive and bool(snapshot.get("session")) and runner.get("session") == snapshot.get("session") and file_age(folder / "snapshot.json") < 4
    return {"running": alive, "game_connected": connected,
            "status": runner.get("runner", "stopped") if alive else "stopped",
            "calls": runner.get("calls", 0), "error_code": runner.get("error_code"),
            "companion": (snapshot.get("companion") or {}).get("name", "") if connected else "",
            "enabled": bool(connected and control.get("enabled") and control.get("session") == snapshot.get("session")
                            and control.get("companion") == (snapshot.get("companion") or {}).get("id")
                            and control.get("revision") == snapshot.get("control_revision"))}


def support_report(settings: Settings, checks: list[Check]) -> dict:
    # Deliberate allowlist: no paths, identifiers, prompts, account diagnostics or save data.
    runtime = runtime_status(settings.io) if settings.profile else {}
    allowed_status = {"ready", "thinking", "acting", "cancelling", "waiting_game", "waiting_save", "waiting_companion", "paused", "retrying", "error", "stopped", "disconnected", "game_disconnected", "call_limit"}
    allowed_errors = {"cli_missing", "cli_unavailable", "login_required", "usage_limit", "unsupported_model", "cli_outdated", "connection_failed", "timeout", "invalid_response", "cleanup_failed", "local_io_failed"}
    return {"app_version": __version__, "platform": sys.platform,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "checks": [{"id": c.id, "ok": c.ok} for c in checks],
            "runtime": {"running": bool(runtime.get("running")), "game_connected": bool(runtime.get("game_connected")),
                        "status": runtime.get("status") if runtime.get("status") in allowed_status else "unknown",
                        "error_code": runtime.get("error_code") if runtime.get("error_code") in allowed_errors else None}}
