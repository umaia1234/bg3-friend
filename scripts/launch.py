"""Start the WSL Codex runner and a native Windows companion window."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.model import CodexModel, ReplayModel
from companion.runner import Runner
from companion.protocol import write_json


def claim_runner(folder):
    handle = (folder / "runner.lock").open("a+b")
    if handle.tell() == 0:
        handle.write(b"0"); handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("BG3 Friend is already running. Use the existing window.")
    return handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--io", type=Path)
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    args = parser.parse_args()
    if args.io:
        folder = args.io
    elif os.name == "nt":
        folder = Path(os.environ["LOCALAPPDATA"]) / "Larian Studios/Baldur's Gate 3/Script Extender/BG3Friend"
    else:
        candidates = list(Path("/mnt/c/Users").glob("*/AppData/Local/Larian Studios/Baldur's Gate 3"))
        if len(candidates) != 1:
            parser.error("Pass --io with the game's Script Extender/BG3Friend folder")
        folder = candidates[0] / "Script Extender/BG3Friend"
    folder.mkdir(parents=True, exist_ok=True)
    ownership = claim_runner(folder)
    gui = None
    close_file = folder / ("close-gui-" + uuid.uuid4().hex + ".json")
    stop_file = folder / ("stop-runner-" + uuid.uuid4().hex + ".json")
    if not args.no_gui:
        if os.name == "nt":
            command = [sys.executable, str(ROOT / "companion/gui.py"), "--io", str(folder),
                       "--close-file", str(close_file), "--stop-file", str(stop_file)]
        else:
            user_root = next(p for p in folder.parents if p.parent == Path("/mnt/c/Users"))
            py = user_root / "AppData/Local/Programs/Python/Python311/pythonw.exe"
            to_win = lambda p: subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()
            command = [str(py), to_win(ROOT / "companion/gui.py"), "--io", to_win(folder),
                       "--close-file", to_win(close_file), "--stop-file", to_win(stop_file)]
        gui = subprocess.Popen(command)
    try:
        Runner(folder, ReplayModel() if args.offline else CodexModel(), max_calls=args.max_calls).run(stop_file)
    except KeyboardInterrupt:
        pass
    finally:
        if gui and not stop_file.exists():
            # Terminating a WSL interop wrapper leaves pythonw.exe orphaned.
            # Ask this exact GUI instance to close itself instead.
            write_json(close_file, {"close": True})
            try:
                gui.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        ownership.close()
        stop_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
