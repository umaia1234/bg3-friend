"""Read-only health check. --probe makes one explicit Codex model request."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.protocol import read_json, validate_decision
from companion.model import find_codex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--io", type=Path)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    print("Python:", sys.version.split()[0])
    codex = find_codex()
    print("Codex:", codex or "unavailable")
    print("Mod package:", "present" if (ROOT / "dist/BG3Friend.pak").exists() else "not built")
    available = False
    if codex:
        result = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=10)
        available = result.returncode == 0
        print("Codex login:", "available" if result.returncode == 0 else "login required")
    if args.io:
        snapshot = read_json(args.io / "snapshot.json")
        if snapshot:
            print("Game session:", snapshot.get("session"))
            print("Snapshot age:", round(time.time()-(args.io / "snapshot.json").stat().st_mtime, 1), "seconds")
            print("Party:", [x.get("name") for x in snapshot.get("party", [])])
            print("Assigned companion:", (snapshot.get("companion") or {}).get("name", "none"))
            print("Game blocker:", snapshot.get("blocked", "none"))
        else:
            print("Game snapshot: unavailable (load a save with BG3 Friend enabled)")
    if args.probe:
        if not available:
            raise SystemExit("A logged-in Codex CLI is required for --probe")
        from companion.model import CodexModel
        scene = {"protocol": 1, "session": "probe", "seq": 1,
                 "player": {"id": "human", "position": [0, 0, 0]},
                 "companion": {"id": "friend", "name": "카를라크", "position": [2, 0, 0], "selected": False},
                 "nearby": [], "capabilities": ["wait", "follow", "look", "approach"]}
        result, duration = CodexModel().decide(scene, [], [{"role": "user", "text": "잠깐 기다려줘."}])
        validate_decision(result, scene)
        print("Astra structured response:", json.dumps(result, ensure_ascii=False))
        print("Response seconds:", round(duration, 2))
    if not available:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
