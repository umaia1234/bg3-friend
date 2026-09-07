"""Preview or register the repository skill with private, per-PC configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
NAME = "bg3-friend-start"
FILES = ("SKILL.md", "agents/openai.yaml", "references/playbook.ko.md", "scripts/start.ps1")
BASE_FIELDS = ("repository", "steamAppId")
SOURCE_FIELDS = ("distro", "projectLinux", "projectWindows", "ioLinux",
                 "profileWindows", "gameWindows", "steamExe")
WINDOWS_FIELDS = ("projectWindows", "profileWindows", "windowsPython", "gameWindows",
                  "steamExe", "nativeExe", "nativeConfigRoot")
FIELDS = BASE_FIELDS + SOURCE_FIELDS + ("windowsPython", "nativeExe", "nativeConfigRoot")


def read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object")
    return data


def validate_config(data: dict) -> None:
    required = BASE_FIELDS if data.get("nativeExe") else BASE_FIELDS + SOURCE_FIELDS
    missing = [key for key in required if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise ValueError("Missing configuration: " + ", ".join(missing))
    if data["repository"] != "https://github.com/umaia1234/bg3-friend" or data["steamAppId"] != "1086940":
        raise ValueError("Configuration must identify BG3 Friend and Steam app 1086940")
    for key in FIELDS:
        if key in data and not isinstance(data[key], str):
            raise ValueError(key + " must be a string")
    if data.get("distro") and not re.fullmatch(r"[A-Za-z0-9_.-]+", data["distro"]):
        raise ValueError("Use a WSL distribution name containing letters, digits, dots, underscores or hyphens")
    for key in ("projectLinux", "ioLinux"):
        if data.get(key) and not PurePosixPath(data[key]).is_absolute():
            raise ValueError(key + " must be an absolute WSL path")
    for key in WINDOWS_FIELDS:
        if data.get(key) and not PureWindowsPath(data[key]).is_absolute():
            raise ValueError(key + " must be an absolute Windows path")
    for key in FIELDS:
        if any(token in data.get(key, "") for token in ("YOUR_", "<", ">", "\n", "\r", '"', "\x00")):
            raise ValueError(key + " contains an unresolved placeholder or invalid argument")
    if data.get("nativeExe") and PureWindowsPath(data["nativeExe"]).suffix.lower() != ".exe":
        raise ValueError("nativeExe must identify the Windows BG3 Friend .exe")


def write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def register(config_path: Path, target: Path, *, apply: bool = False, root: Path = ROOT) -> dict:
    source = (root / ".agents/skills" / NAME).resolve()
    if target.is_symlink():
        raise ValueError("Choose a real skill directory, not a symlink")
    target = target.resolve()
    if target.name != NAME or target == source or target in source.parents or source in target.parents:
        raise ValueError("Target must be a separate directory named " + NAME)
    if target.exists() and not target.is_dir():
        raise ValueError("Target exists and is not a directory")
    config = read_config(config_path)
    previous = target / "project.local.json"
    if previous.exists():
        old = read_config(previous)
        preferences = dict(old.get("preferences") or {}) | dict(config.get("preferences") or {})
        config = old | config
        if preferences:
            config["preferences"] = preferences
    validate_config(config)
    payload = {name: (source / name).read_bytes() for name in FILES}
    payload["project.local.json"] = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    changes = []
    for name, content in payload.items():
        path = target / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != target.parent):
            raise ValueError("Refusing to overwrite a linked skill path")
        if not path.exists() or path.read_bytes() != content:
            changes.append(name)
    source_config = source / "project.local.json"
    if source_config.is_symlink():
        raise ValueError("Refusing to overwrite a linked project configuration")
    source_changed = not source_config.exists() or source_config.read_bytes() != payload["project.local.json"]
    report = {"mode": "apply" if apply else "preview", "source": str(source), "target": str(target),
              "changed_files": changes, "project_config_changed": source_changed, "backup": None}
    if not apply or not (changes or source_changed):
        return report
    # Backups stay outside the discoverable skills and are ignored by Git.
    if target.exists() or source_config.exists():
        backup = root / ".runtime/skill-backups" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        if target.exists():
            shutil.copytree(target, backup / NAME, symlinks=True)
        if source_config.exists():
            shutil.copy2(source_config, backup / "project-source.local.json")
        report["backup"] = str(backup)
    for name in changes:
        write_atomic(target / name, payload[name])
    if source_changed:
        write_atomic(source_config, payload["project.local.json"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Confirmed local JSON configuration; never commit it")
    parser.add_argument("--target", type=Path, required=True, help="Exact personal skill folder, ending in bg3-friend-start")
    parser.add_argument("--apply", action="store_true", help="Write after the user authorizes this setup/update; default is read-only")
    args = parser.parse_args()
    try:
        result = register(args.config, args.target, apply=args.apply)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
