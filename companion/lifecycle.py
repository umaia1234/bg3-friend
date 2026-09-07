"""Own one runner and its overlay, including clean shutdown after desktop failure."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from .configuration import Settings, load_settings
from .diagnostics import file_age, runtime_status
from .installation import check_recovery
from .model import CodexModel, ReplayModel
from .protocol import read_json, write_json


class AlreadyRunning(RuntimeError):
    pass


def process_alive(pid: int, platform: str | None = None, distro: str = "") -> bool | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        return None
    platform = platform or os.name
    if platform != os.name:
        if os.name == "nt" and platform == "posix" and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", distro):
            try:
                result = subprocess.run(["wsl.exe", "-d", distro, "--exec", "python3", "-c",
                    "import os,sys\ntry: os.kill(int(sys.argv[1]),0)\nexcept ProcessLookupError: sys.exit(3)", str(pid)],
                    capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                return {0: True, 3: False}.get(result.returncode)
            except (OSError, subprocess.SubprocessError):
                return None
        if os.name == "posix" and platform == "nt":
            try:
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                    f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 3 }}"],
                    capture_output=True, timeout=5)
                return {0: True, 3: False}.get(result.returncode)
            except (OSError, subprocess.SubprocessError):
                return None
        return None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            return code.value == 259 if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
        finally:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        # An exited process can remain in /proc until its parent reaps it.
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_bytes().rsplit(b")", 1)[1].split()[0] == b"Z":
            return False
        return True
    except (FileNotFoundError, ProcessLookupError):
        return False
    except OSError:
        return None


def _process_stamp(pid):
    """A PID alone can refer to a different process after a crash/restart."""
    try:
        if os.name != "nt":
            start = Path(f"/proc/{pid}/stat").read_bytes().rsplit(b")", 1)[1].split()[19].decode("ascii")
            return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() + ":" + start
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [ctypes.c_uint64() for _ in range(4)]
            return str(times[0].value) if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)) else None
        finally:
            kernel.CloseHandle(handle)
    except (OSError, IndexError):
        return None


def _owner_alive(owner):
    alive = process_alive(owner.get("pid"), owner.get("platform"), owner.get("distro", ""))
    if alive and owner.get("platform") == os.name and owner.get("process_start"):
        current = _process_stamp(owner["pid"])
        if current and current != owner["process_start"]:
            return False
    return alive


def runner_claim_active(folder: Path) -> bool:
    """Read-only cross-OS install guard, including the pre-heartbeat startup gap."""
    for name in ("runner-claim", "runner-claim-recovery"):
        directory = folder / name
        if directory.is_symlink():
            return True
        if directory.exists():
            owner = read_json(directory / "owner.json") or {}
            if not owner or _owner_alive(owner) is not False:
                return True
    return False


def _retire(directory, token):
    retired = directory.with_name(directory.name + "-retired-" + token)
    directory.rename(retired)
    (retired / "owner.json").unlink(missing_ok=True)
    try:
        retired.rmdir()
    except OSError:
        pass  # Never recursively delete unexpected files from a retired claim.


def _stale_claim(directory):
    if directory.is_symlink():
        return False
    owner = read_json(directory / "owner.json") or {}
    if owner:
        return _owner_alive(owner) is False
    # Legacy versions could crash between mkdir and the owner write. New claims
    # below publish a complete nonempty directory in one rename.
    return file_age(directory) > 10


class RunnerLease:
    """mkdir is shared by native Windows and WSL; their advisory file locks are not."""

    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        # Keep the previous source launcher's OS lock for its entire lifetime too.
        # Directory ownership adds the native Windows/WSL boundary it cannot cover.
        self._legacy_handle = (folder / "runner.lock").open("a+b")
        if self._legacy_handle.tell() == 0:
            self._legacy_handle.write(b"0")
            self._legacy_handle.flush()
        self._legacy_handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._legacy_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._legacy_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._claim(folder)
        except BaseException as exc:
            self._legacy_handle.close()
            self._legacy_handle = None
            if isinstance(exc, OSError):
                raise AlreadyRunning("BG3 Friend의 실행 잠금을 얻지 못했습니다. 기존 앱의 종료 상태를 확인해 주세요.") from exc
            raise

    def _claim(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.folder, self.directory = folder, folder / "runner-claim"
        self.token = uuid.uuid4().hex
        self.stop_file = folder / f"stop-runner-{self.token}.json"
        self.close_file = folder / f"close-gui-{self.token}.json"
        guard = folder / "runner-claim-recovery"
        proposed = folder / f"runner-claim-proposed-{self.token}"
        owner = {"pid": os.getpid(), "platform": os.name,
                 "distro": os.environ.get("WSL_DISTRO_NAME", ""), "token": self.token,
                 "process_start": _process_stamp(os.getpid()),
                 "stop_file": self.stop_file.name, "close_file": self.close_file.name}
        candidate = folder / f"runner-claim-recovery-proposed-{self.token}"
        candidate.mkdir()
        try:
            write_json(candidate / "owner.json", owner)
            if guard.exists():
                if not _stale_claim(guard):
                    raise AlreadyRunning("다른 BG3 Friend가 시작 중이거나 이전 프로세스 종료를 확인하지 못했습니다. 잠시 후 상태를 다시 확인해 주세요.")
                _retire(guard, self.token)
            try:
                candidate.rename(guard)
            except OSError as exc:
                raise AlreadyRunning("다른 BG3 Friend가 먼저 시작했습니다. 기존 앱을 확인해 주세요.") from exc
        finally:
            if candidate.exists():
                (candidate / "owner.json").unlink(missing_ok=True)
                candidate.rmdir()
        try:
            reclaimed = False
            if self.directory.exists():
                if not _stale_claim(self.directory):
                    raise AlreadyRunning("BG3 Friend가 이미 실행 중이거나 이전 프로세스 종료를 확인하지 못했습니다. 기존 앱에서 중지해 주세요.")
                _retire(self.directory, self.token)
                reclaimed = True
            if not reclaimed and runtime_status(folder)["running"]:
                raise AlreadyRunning("기존 BG3 Friend가 연결되어 있습니다. 기존 파티 대화 메뉴에서 먼저 종료해 주세요.")
            proposed.mkdir()
            try:
                write_json(proposed / "owner.json", owner)
                proposed.rename(self.directory)
            except OSError as exc:
                raise AlreadyRunning("다른 BG3 Friend가 먼저 연결되었습니다. 기존 앱을 확인해 주세요.") from exc
        finally:
            if proposed.exists():
                (proposed / "owner.json").unlink(missing_ok=True)
                proposed.rmdir()
            if (read_json(guard / "owner.json") or {}).get("token") == self.token:
                (guard / "owner.json").unlink(missing_ok=True)
                guard.rmdir()

    def close(self) -> None:
        try:
            owner = read_json(self.directory / "owner.json") or {}
            if owner.get("token") == self.token:
                (self.directory / "owner.json").unlink(missing_ok=True)
                self.directory.rmdir()
        finally:
            if self._legacy_handle:
                self._legacy_handle.close()
                self._legacy_handle = None


def request_stop(folder: Path) -> bool:
    owner = read_json(folder / "runner-claim/owner.json") or {}
    token = owner.get("token", "")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        return False
    # Stopping the owned worker must not depend on parsing/writing control state.
    # Its normal shutdown and the game's heartbeat expiry also return control.
    write_json(folder / f"stop-runner-{token}.json", {"stop": True})
    control = read_json(folder / "control.json") or {}
    if control.get("enabled"):
        revision = control.get("revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            revision = 0
        control.update(enabled=False, revision=revision + 1)
        try:
            write_json(folder / "control.json", control)
        except OSError:
            pass  # The token-bound stop request was already delivered.
    return True


def app_command(*arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    python = Path(sys.executable)
    if os.name == "nt" and python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    return [str(python), str(Path(__file__).resolve().parents[1] / "scripts/app.py"), *arguments]


def start_worker(root: Path) -> subprocess.Popen:
    return subprocess.Popen(app_command("--worker", "--config-root", str(root), "--parent-pid", str(os.getpid())),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def run_worker(root: Path, parent_pid: int = 0, *, offline: bool = False, no_gui: bool = False) -> None:
    check_recovery(root / "install")
    settings = load_settings(root)
    if not offline and not settings.consent:
        raise ValueError("설정에서 게임 관찰·대화 전송에 동의해 주세요.")
    if parent_pid and process_alive(parent_pid) is False:
        return
    parent_stamp = _process_stamp(parent_pid) if parent_pid else None
    folder = settings.io
    lease = RunnerLease(folder)
    gui = None
    finished = threading.Event()
    stop_requested = threading.Event()

    class StopSignal:
        def exists(self):
            return stop_requested.is_set() or lease.stop_file.exists()

    try:
        if not no_gui:
            gui = subprocess.Popen(app_command("--overlay", "--io", str(folder), "--close-file", str(lease.close_file),
                                               "--stop-file", str(lease.stop_file)),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        def supervise():
            while not finished.wait(.5):
                parent_changed = parent_stamp and _process_stamp(parent_pid) not in (None, parent_stamp)
                # A saved consent withdrawal must stop even if another process
                # currently prevents writing the bridge's token stop file.
                authorization_lost = not offline and (read_json(root / "settings.json") or {}).get("consent") is not True
                if ((gui and gui.poll() is not None) or (parent_pid and process_alive(parent_pid) is False)
                        or parent_changed or authorization_lost):
                    stop_requested.set()
                    try:
                        write_json(lease.stop_file, {"stop": True})
                    except OSError:
                        pass  # The in-process stop signal still reaches Runner.run().
                    return

        threading.Thread(target=supervise, name="bg3-friend-supervisor", daemon=True).start()
        from .runner import Runner
        model = ReplayModel() if offline else CodexModel(settings.model, settings.timeout, settings.codex or None)
        Runner(folder, model).run(StopSignal())
    finally:
        finished.set()
        try:
            if gui and gui.poll() is None:
                try:
                    write_json(lease.close_file, {"close": True})
                    gui.wait(3)
                except (OSError, subprocess.TimeoutExpired):
                    gui.kill()
                    gui.wait(2)
        finally:
            lease.close()
            lease.stop_file.unlink(missing_ok=True)
            lease.close_file.unlink(missing_ok=True)
