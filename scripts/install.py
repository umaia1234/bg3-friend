"""Reversible Windows BG3 developer installation, callable from Windows or WSL."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UUID = "cfd9c54e-3884-47ed-9b40-82b8747194de"


def windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path.resolve())
    return subprocess.check_output(["wslpath", "-w", str(path.resolve())], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="Baldur's Gate 3 LocalAppData folder")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if not args.build_only:
        ps = "powershell.exe" if os.name == "nt" else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        running = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command",
                                  "if(Get-Process bg3,bg3_dx11 -ErrorAction SilentlyContinue){exit 10}"],
                                 capture_output=True)
        if running.returncode == 10:
            parser.error("Close BG3 before installing; use --build-only to package while playing")
    divine = ROOT / ".tools/lslib/Packed/Tools/Divine.exe"
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    pak = dist / "BG3Friend.pak"
    subprocess.run([str(divine), "-g", "bg3", "-a", "create-package", "-s",
                    windows_path(ROOT / "mod"), "-d", windows_path(pak), "-c", "lz4"], check=True)
    if args.build_only:
        return
    backup = ROOT / ".runtime/backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True)
    manifest: list[dict] = []

    def replace(path: Path, data: bytes):
        if path.exists() and path.read_bytes() == data:
            return
        original = backup / str(len(manifest))
        if path.exists():
            shutil.copy2(path, original)
        manifest.append({"path": str(path), "backup": str(original) if original.exists() else None,
                         "installed_sha256": hashlib.sha256(data).hexdigest()})
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".bg3friend-install.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    dll = args.game / "bin/DWrite.dll"
    if not dll.exists():
        replace(dll, (ROOT / ".tools/bg3se/DWrite.dll").read_bytes())
    settings = args.game / "bin/ScriptExtenderSettings.json"
    config = json.loads(settings.read_text()) if settings.exists() else {}
    config.update({"CreateConsole": True, "LogRuntime": True})
    replace(settings, json.dumps(config, indent=2).encode())
    replace(args.profile / "Mods/BG3Friend.pak", pak.read_bytes())
    modsettings = args.profile / "PlayerProfiles/Public/modsettings.lsx"
    tree = ET.fromstring(modsettings.read_bytes())
    root_children = tree.find("./region/node/children")
    if root_children is None:
        raise RuntimeError("Unrecognized modsettings layout; backup retained")
    mods = root_children.find("./node[@id='Mods']/children")
    if mods is None:
        raise RuntimeError("Missing Mods node")
    for entry in list(mods):
        uid = entry.find("./attribute[@id='UUID']")
        if uid is not None and uid.get("value") == UUID:
            mods.remove(entry)
    info = ET.SubElement(mods, "node", id="ModuleShortDesc")
    for name, kind, value in [("Folder", "LSString", "BG3Friend"), ("MD5", "LSString", ""),
                              ("Name", "LSString", "BG3 Friend"), ("UUID", "guid", UUID),
                              ("Version64", "int64", "36028797018963968"), ("PublishHandle", "uint64", "0")]:
        ET.SubElement(info, "attribute", id=name, type=kind, value=value)
    # Patch 7+ uses the ordered Mods list (same format as current BG3 Mod Manager).
    # Remove the obsolete node written by early development installs.
    order = root_children.find("./node[@id='ModOrder']")
    if order is not None:
        root_children.remove(order)
    ET.indent(tree)
    replace(modsettings, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
    print("Installed:", pak)
    print("Rollback manifest:", backup / "manifest.json")


if __name__ == "__main__":
    main()
