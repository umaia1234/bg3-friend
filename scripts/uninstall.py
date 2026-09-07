"""Remove this mod, preserving other mods, the shared extender, and saves."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UUID = "cfd9c54e-3884-47ed-9b40-82b8747194de"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    ps = "powershell.exe" if os.name == "nt" else "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command",
                             "if(Get-Process bg3,bg3_dx11 -ErrorAction SilentlyContinue){exit 10}"], capture_output=True)
    if result.returncode:
        parser.error("Close BG3 before uninstalling")
    settings = args.profile / "PlayerProfiles/Public/modsettings.lsx"
    tree = ET.fromstring(settings.read_bytes())
    for children in tree.findall(".//node[@id='Mods']/children") + tree.findall(".//node[@id='ModOrder']/children"):
        for entry in list(children):
            uid = entry.find("./attribute[@id='UUID']")
            if uid is not None and uid.get("value") == UUID:
                children.remove(entry)
    backup = ROOT / ".runtime/backups" / (time.strftime("%Y%m%d-%H%M%S") + "-uninstall")
    backup.mkdir(parents=True)
    shutil.copy2(settings, backup / "modsettings.lsx")
    pak = args.profile / "Mods/BG3Friend.pak"
    if pak.exists():
        shutil.copy2(pak, backup / pak.name)
    ET.indent(tree)
    temporary = settings.with_name(settings.name + ".bg3friend-uninstall.tmp")
    temporary.write_bytes(ET.tostring(tree, encoding="utf-8", xml_declaration=True))
    os.replace(temporary, settings)
    pak.unlink(missing_ok=True)
    control = args.profile / "Script Extender/BG3Friend/control.json"
    if control.exists():
        data = json.loads(control.read_text(encoding="utf-8-sig"))
        data.update(enabled=False, revision=data.get("revision", 0) + 1)
        control.write_text(json.dumps(data), encoding="utf-8")
    print("BG3 Friend removed. Other mods, Script Extender, and saves retained.")
    print("Backup:", backup)


if __name__ == "__main__":
    main()
