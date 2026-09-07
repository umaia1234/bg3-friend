"""Real local subprocesses exercise cancellation and the structured response boundary."""
from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from companion.model import CodexModel, ModelFailure, classify_failure, probe_cli


SCENE = {"session": "test", "companion": {"id": "friend", "name": "게일", "position": [0, 0, 0]},
         "nearby": [], "blocked": None}
DECISION = {"say": "기다릴게.", "action": "wait", "target": "", "reason": "test", "remember": "", "stance": "hold"}


@pytest.mark.skipif(os.name != "nt", reason="Windows PATH and current-directory lookup semantics")
def test_windows_codex_discovery_ignores_cwd_and_relative_path_entries(tmp_path, monkeypatch):
    from companion.model import find_codex
    current = tmp_path / "current"
    relative = current / "relative"
    relative.mkdir(parents=True)
    (current / "codex.exe").write_bytes(b"desktop app, never execute")
    (relative / "codex.exe").write_bytes(b"untrusted relative path, never execute")
    monkeypatch.chdir(current)
    monkeypatch.setattr("companion.model.local_appdata", lambda: tmp_path / "absent-local-appdata")
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "relative", str(current)]))
    monkeypatch.setattr("companion.model.shutil.which", lambda *args, **kwargs: pytest.fail("implicit CWD lookup"))
    monkeypatch.setattr("companion.model.subprocess.Popen", lambda *args, **kwargs: pytest.fail("discovery executes a candidate"))
    assert find_codex() is None


@pytest.mark.skipif(os.name != "nt", reason="Windows executable discovery")
def test_windows_codex_discovery_returns_absolute_path_candidate(tmp_path, monkeypatch):
    from companion.model import find_codex
    cli_dir = tmp_path / "CLI 경로"
    cli_dir.mkdir()
    executable = cli_dir / "codex.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("companion.model.local_appdata", lambda: tmp_path / "absent-local-appdata")
    monkeypatch.setenv("PATH", os.pathsep.join([".", f'"{cli_dir}"']))
    assert find_codex() == str(executable.resolve())


@pytest.mark.skipif(os.name != "nt", reason="Windows managed CLI distribution")
def test_windows_codex_discovery_prefers_managed_cli_to_path_namesake(tmp_path, monkeypatch):
    from companion.model import find_codex
    local = tmp_path / "local"
    managed = local / "OpenAI/Codex/bin/version-1/codex.exe"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"fixture")
    namesake = tmp_path / "desktop/Codex.exe"
    namesake.parent.mkdir()
    namesake.write_bytes(b"fixture")
    monkeypatch.setattr("companion.model.local_appdata", lambda: local)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "redirected-msix-cache"))
    monkeypatch.setenv("PATH", str(namesake.parent))
    assert find_codex() == str(managed.resolve())


@pytest.mark.skipif(os.name != "nt", reason="Windows Known Folder fallback")
def test_windows_codex_discovery_uses_absolute_path_if_known_folder_fails(tmp_path, monkeypatch):
    from companion.model import find_codex
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    executable = cli_dir / "codex.exe"
    executable.write_bytes(b"fixture")

    def unavailable():
        raise OSError("fixture known folder unavailable")

    monkeypatch.setattr("companion.model.local_appdata", unavailable)
    monkeypatch.setenv("PATH", str(cli_dir))
    assert find_codex() == str(executable.resolve())


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell PATH result")
def test_posix_codex_discovery_makes_relative_which_result_absolute(tmp_path, monkeypatch):
    from companion.model import find_codex
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("companion.model.shutil.which", lambda name: "./codex")
    assert find_codex() == str(tmp_path / "codex")


def local_cli(tmp_path, monkeypatch, body):
    script = tmp_path / "fixture.py"
    script.write_text("import sys, json, time, pathlib\n" + body, encoding="utf-8")
    original = subprocess.Popen
    processes = []

    def start(args, **kwargs):
        process = original([sys.executable, "-X", "utf8", str(script), *args[1:]], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("companion.model.subprocess.Popen", start)
    return CodexModel(executable="local-fixture", timeout=3), processes


def test_real_process_structured_response_and_restricted_arguments(tmp_path, monkeypatch):
    model, processes = local_cli(tmp_path, monkeypatch,
        "assert '--ignore-user-config' in sys.argv and '--ephemeral' in sys.argv\n"
        "assert 'features.shell_tool=false' in sys.argv and 'features.apps=false' in sys.argv\n"
        "assert 'features.plugins=false' in sys.argv and 'web_search=\"disabled\"' in sys.argv\n"
        "data = sys.stdin.read()\nassert 'GAME_DATA' in data and '게일' in data\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        f"out.write_text({json.dumps(json.dumps(DECISION, ensure_ascii=False), ensure_ascii=False)}, encoding='utf-8')\n")
    result, elapsed = model.decide(SCENE, [], [])
    assert result == DECISION and elapsed < 3
    assert processes[0].poll() == 0 and model._process is None


def test_cancel_reaps_real_running_child(tmp_path, monkeypatch):
    model, processes = local_cli(tmp_path, monkeypatch, "sys.stdin.read()\ntime.sleep(30)\n")
    cancel = threading.Event()
    results = []

    def run():
        try:
            model.decide_cancellable(SCENE, [], [], cancel)
        except BaseException as exc:
            results.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 3
    while not processes and time.monotonic() < deadline:
        time.sleep(.01)
    assert processes
    started = time.monotonic()
    cancel.set()
    model.cancel_pending()
    worker.join(2)
    assert not worker.is_alive() and time.monotonic() - started < 2
    assert isinstance(results[0], CancelledError)
    assert processes[0].poll() is not None and model._process is None


def test_timeout_reaps_child_and_is_retryable(tmp_path, monkeypatch):
    model, processes = local_cli(tmp_path, monkeypatch, "sys.stdin.read()\ntime.sleep(30)\n")
    model.timeout = .2
    with pytest.raises(ModelFailure) as failure:
        model.decide(SCENE, [], [])
    assert failure.value.code == "timeout" and failure.value.retryable
    assert processes[0].poll() is not None


@pytest.mark.parametrize("body", [
    "sys.stdin.read()\n",
    "sys.stdin.read()\npathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{bad')\n",
    "sys.stdin.read()\npathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('{}')\n",
])
def test_bad_response_never_retries_automatically(tmp_path, monkeypatch, body):
    model, _ = local_cli(tmp_path, monkeypatch, body)
    with pytest.raises(ModelFailure) as failure:
        model.decide(SCENE, [], [])
    assert failure.value.code == "invalid_response" and not failure.value.retryable


def test_cli_error_does_not_expose_diagnostics(tmp_path, monkeypatch):
    model, _ = local_cli(tmp_path, monkeypatch,
        "sys.stdin.read()\nprint('401 unauthorized private-account@example.test secret', file=sys.stderr)\nsys.exit(1)\n")
    with pytest.raises(ModelFailure) as failure:
        model.decide(SCENE, [], [])
    assert failure.value.code == "login_required" and not failure.value.retryable
    assert "private-account" not in str(failure.value) and "secret" not in str(failure.value)


def test_precancelled_does_not_start_any_process(tmp_path, monkeypatch):
    model, processes = local_cli(tmp_path, monkeypatch, "raise AssertionError('must not start')\n")
    event = threading.Event()
    event.set()
    with pytest.raises(CancelledError):
        model.decide_cancellable(SCENE, [], [], event)
    assert not processes


@pytest.mark.parametrize("diagnostic,code,retryable", [
    ("429 rate limit", "usage_limit", False),
    ("model is not supported", "unsupported_model", False),
    ("unexpected argument --ephemeral", "cli_outdated", False),
    ("connection reset", "connection_failed", True),
])
def test_failure_categories(diagnostic, code, retryable):
    error = classify_failure(diagnostic)
    assert (error.code, error.retryable) == (code, retryable)


def is_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    try:
        # A killed grandchild may briefly remain as a zombie until its reaper runs.
        return Path(f"/proc/{pid}/stat").read_bytes().rsplit(b")", 1)[1].split()[0] != b"Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def wait_stopped(pid):
    deadline = time.monotonic() + 2
    while is_running(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    assert not is_running(pid)


@pytest.mark.parametrize("mode", ["normal_exit", "timeout", "cancel"])
def test_descendants_are_reaped_without_touching_unrelated_processes(tmp_path, monkeypatch, mode):
    original = subprocess.Popen
    unrelated = original([sys.executable, "-c", "import time; time.sleep(30)"],
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    marker = tmp_path / "descendant.json"
    body = ("import subprocess\nsys.stdin.read()\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n")
    if mode == "normal_exit":
        body += ("out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
                 f"out.write_text({json.dumps(json.dumps(DECISION))})\n")
    else:
        body += "time.sleep(30)\n"
    model, processes = local_cli(tmp_path, monkeypatch, body)
    cancel = threading.Event()
    results = []

    def run():
        try:
            results.append(model.decide_cancellable(SCENE, [], [], cancel))
        except BaseException as exc:
            results.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    try:
        model.timeout = .7 if mode == "timeout" else 3
        worker.start()
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists()
        child_pid = int(marker.read_text(encoding="ascii"))
        if mode == "cancel":
            cancel.set()
            model.cancel_pending()
        worker.join(3)
        assert not worker.is_alive()
        if mode == "normal_exit":
            if isinstance(results[0], BaseException):
                raise results[0]
            assert results[0][0] == DECISION
        elif mode == "cancel":
            assert isinstance(results[0], CancelledError)
        else:
            assert isinstance(results[0], ModelFailure) and results[0].code == "timeout"
        wait_stopped(child_pid)
        assert processes[0].poll() is not None and model._process is None
        assert unrelated.poll() is None
    finally:
        cancel.set()
        model.cancel_pending()
        worker.join(3)
        unrelated.kill()
        unrelated.wait(timeout=2)


def test_exited_parent_with_inherited_output_pipe_is_still_cleaned_up(tmp_path, monkeypatch):
    marker = tmp_path / "pipe-child.json"
    model, _ = local_cli(tmp_path, monkeypatch,
        "import subprocess\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n")
    process = model._launch(["fixture"], threading.Event(), subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE)
    try:
        assert process.wait(timeout=2) == 0
        child_pid = int(marker.read_text(encoding="ascii"))
        assert is_running(child_pid)
        model._kill(process)
        process.communicate(timeout=2)
        wait_stopped(child_pid)
    finally:
        model._reap(process)


def test_large_input_to_nonreading_cli_cannot_hide_the_timeout(tmp_path, monkeypatch):
    model, processes = local_cli(tmp_path, monkeypatch, "time.sleep(30)\n")
    model.timeout = .2
    started = time.monotonic()
    with pytest.raises(ModelFailure) as failure:
        model.decide(SCENE, [], [{"role": "user", "text": "x" * 1_000_000}])
    assert failure.value.code == "timeout" and time.monotonic() - started < 3
    assert processes[0].poll() is not None


def test_runner_stop_waits_for_owned_cli_cleanup(tmp_path, monkeypatch):
    from companion.protocol import read_json, write_json
    from companion.runner import Runner
    model, processes = local_cli(tmp_path, monkeypatch, "sys.stdin.read()\ntime.sleep(30)\n")
    write_json(tmp_path / "snapshot.json", SCENE | {
        "protocol": 1, "seq": 1, "player": {"id": "human", "position": [0, 0, 0]},
    })
    write_json(tmp_path / "control.json", {"session": "test", "enabled": True, "companion": "friend", "revision": 1})
    runner = Runner(tmp_path, model)
    stop_file = tmp_path / "stop.json"

    def stop_when_started():
        deadline = time.monotonic() + 2
        while not processes and time.monotonic() < deadline:
            time.sleep(.01)
        write_json(stop_file, {"stop": True})

    stopper = threading.Thread(target=stop_when_started, daemon=True)
    stopper.start()
    runner.run(stop_file)
    stopper.join(2)
    assert processes and processes[0].poll() is not None
    assert model._process is None and not runner.pool.thread.is_alive()
    assert read_json(tmp_path / "runner.json")["runner"] == "stopped"


def test_cli_probe_limits_stdout_and_never_returns_stderr(tmp_path, monkeypatch):
    _, processes = local_cli(tmp_path, monkeypatch,
        "assert sys.argv[1:] == ['--version']\n"
        "print('codex-cli ' + 'x' * 8000)\n"
        "print('private-token@example.test', file=sys.stderr)\n")
    code, output = probe_cli("local-fixture", ["--version"])
    assert code == 0 and output.startswith("codex-cli ") and len(output) <= 4096
    assert "private-token" not in output and processes[0].poll() == 0


@pytest.mark.parametrize("mode", ["normal_exit", "timeout"])
def test_cli_probe_reaps_descendants_inheriting_output(tmp_path, monkeypatch, mode):
    marker = tmp_path / "probe-child.json"
    body = ("import subprocess\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"pathlib.Path({str(marker)!r}).write_text(str(child.pid), encoding='ascii')\n"
            "print('private-token@example.test', file=sys.stderr)\n")
    body += "time.sleep(30)\n" if mode == "timeout" else "print('codex-cli fixture')\n"
    _, processes = local_cli(tmp_path, monkeypatch, body)
    started = time.monotonic()
    if mode == "timeout":
        with pytest.raises(ModelFailure) as failure:
            probe_cli("local-fixture", ["--version"], timeout=.7)
        assert failure.value.code == "timeout" and "private-token" not in str(failure.value)
    else:
        code, output = probe_cli("local-fixture", ["--version"], timeout=2)
        assert code == 0 and output.strip() == "codex-cli fixture"
    assert time.monotonic() - started < 3
    assert processes[0].poll() is not None
    wait_stopped(int(marker.read_text(encoding="ascii")))


def test_cli_probe_missing_executable_uses_safe_error(tmp_path):
    with pytest.raises(ModelFailure) as failure:
        probe_cli(str(tmp_path / "private-user-no-such-cli.exe"), ["--version"])
    assert failure.value.code == "cli_unavailable"
    assert str(tmp_path) not in str(failure.value) and "private-user" not in str(failure.value)


def test_temporary_file_failure_is_not_logged_as_a_private_path(tmp_path, monkeypatch):
    def cannot_create(**kwargs):
        raise PermissionError(f"private-user-path {tmp_path}")

    monkeypatch.setattr("companion.model.tempfile.TemporaryDirectory", cannot_create)
    with pytest.raises(ModelFailure) as failure:
        CodexModel(executable="unused").decide(SCENE, [], [])
    assert failure.value.code == "local_io_failed" and not failure.value.retryable
    assert "private-user" not in str(failure.value) and str(tmp_path) not in str(failure.value)


@pytest.mark.parametrize("persistent", [False, True])
def test_temporary_cleanup_retries_are_bounded_and_preserve_error_privacy(tmp_path, monkeypatch, persistent):
    import tempfile
    original = tempfile.TemporaryDirectory
    owned = []

    class LockedOnce:
        def __init__(self, **kwargs):
            self.inner = original(**kwargs)
            self.name, self.calls = self.inner.name, 0
            owned.append(self)

        def cleanup(self):
            self.calls += 1
            if persistent or self.calls == 1:
                raise PermissionError(f"private-user-path {self.name}")
            self.inner.cleanup()

    model, processes = local_cli(tmp_path, monkeypatch,
        "sys.stdin.read()\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        f"out.write_text({json.dumps(json.dumps(DECISION))}, encoding='utf-8')\n")
    monkeypatch.setattr("companion.model.tempfile.TemporaryDirectory", LockedOnce)
    started = time.monotonic()
    try:
        if persistent:
            with pytest.raises(ModelFailure) as failure:
                model.decide(SCENE, [], [])
            assert failure.value.code == "local_io_failed"
            assert "private-user" not in str(failure.value)
        else:
            assert model.decide(SCENE, [], [])[0] == DECISION
            assert not Path(owned[0].name).exists()
        assert time.monotonic() - started < 3 and 1 < owned[0].calls <= 4
        assert processes[0].poll() is not None and model._process is None
    finally:
        for directory in owned:
            directory.inner.cleanup()
