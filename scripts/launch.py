"""Start the WSL Codex runner and a native Windows companion window."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.model import CodexModel, ReplayModel
from companion.runner import Runner
from companion.protocol import write_json
from companion.lifecycle import AlreadyRunning, RunnerLease


def claim_runner(folder):
    try:
        return RunnerLease(folder)
    except AlreadyRunning as exc:
        raise SystemExit(str(exc)) from exc


def wsl_path(value, direction):
    return Path(subprocess.check_output(["wslpath", direction, str(value)], text=True, timeout=5).strip())


def gui_python(explicit=None):
    if explicit:
        candidate = Path(explicit)
        if os.name != "nt" and not candidate.is_file():
            candidate = wsl_path(explicit, "-u")
        if candidate.is_file() and (os.name == "nt" or candidate.suffix.lower() == ".exe"):
            return candidate
        raise RuntimeError("--gui-python으로 지정한 Windows Python 실행 파일을 찾지 못했습니다.")
    if os.name == "nt":
        candidate = Path(sys.executable).with_name("pythonw.exe")
        return candidate if candidate.is_file() else Path(sys.executable)
    try:
        executable = subprocess.check_output(
            ["py.exe", "-3", "-X", "utf8", "-c", "import sys; print(sys.executable)"],
            text=True, encoding="utf-8", timeout=5).strip()
        candidate = wsl_path(executable, "-u")
        windowed = candidate.with_name("pythonw.exe")
        if windowed.is_file():
            return windowed
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        local = subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;[Console]::Write($env:LOCALAPPDATA)"],
            text=True, encoding="utf-8-sig", timeout=5).strip()
        candidates = list(wsl_path(local, "-u").glob("Programs/Python/Python*/pythonw.exe"))
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime)
    except (OSError, subprocess.SubprocessError):
        pass
    raise RuntimeError("Windows Python을 찾지 못했습니다. Python 3.11 이상과 tkinter를 준비한 뒤 "
                       "--gui-python <pythonw.exe 경로>를 지정하거나 --no-gui를 사용해 주세요.")


def check_gui_python(python):
    try:
        result = subprocess.run([str(python), "-c", "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 11) else 2)"],
                                capture_output=True, timeout=5,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Windows Python을 실행하지 못했습니다. --gui-python 경로를 확인해 주세요.") from exc
    if result.returncode:
        raise RuntimeError("파티 대화에는 tkinter가 포함된 Windows Python 3.11 이상이 필요합니다. "
                           "--gui-python 경로를 확인하거나 --no-gui를 사용해 주세요.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--io", type=Path)
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--gui-python", type=Path)
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
    close_file, stop_file = ownership.close_file, ownership.stop_file
    finished, stop_requested = threading.Event(), threading.Event()

    class StopSignal:
        def exists(self):
            return stop_requested.is_set() or stop_file.exists()

    try:
        if not args.no_gui:
            py = gui_python(args.gui_python)
            check_gui_python(py)
            translate = (lambda p: str(p)) if os.name == "nt" else (lambda p: str(wsl_path(p, "-w")))
            command = [str(py), translate(ROOT / "companion/gui.py"), "--io", translate(folder),
                       "--close-file", translate(close_file), "--stop-file", translate(stop_file)]
            gui = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        def supervise():
            while not finished.wait(.5):
                if gui and gui.poll() is not None:
                    stop_requested.set()
                    return

        threading.Thread(target=supervise, name="friend-source-supervisor", daemon=True).start()
        Runner(folder, ReplayModel() if args.offline else CodexModel(), max_calls=args.max_calls).run(StopSignal())
    except KeyboardInterrupt:
        pass
    finally:
        finished.set()
        try:
            if gui and gui.poll() is None:
                # The token addresses this overlay even through WSL's interop wrapper.
                write_json(close_file, {"close": True})
                try:
                    gui.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        gui.kill()
                        gui.wait(timeout=2)
        finally:
            ownership.close()
            stop_file.unlink(missing_ok=True)
            if not gui or gui.poll() is not None:
                close_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
