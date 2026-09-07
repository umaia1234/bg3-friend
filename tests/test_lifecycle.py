"""Runner ownership and supervision use isolated bridge files and local fixtures."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from companion import lifecycle
from companion.protocol import read_json, write_json


def dead_owner():
    return {"pid": 99999999, "platform": os.name, "token": "a" * 32}


def test_lease_refuses_duplicates_releases_and_can_restart(tmp_path):
    lease = lifecycle.RunnerLease(tmp_path)
    try:
        with pytest.raises(lifecycle.AlreadyRunning):
            lifecycle.RunnerLease(tmp_path)
        assert read_json(tmp_path / "runner-claim/owner.json")["token"] == lease.token
    finally:
        lease.close()
    second = lifecycle.RunnerLease(tmp_path)
    assert second.token != lease.token
    second.close()
    second.close()


@pytest.mark.parametrize("directory", ["runner-claim", "runner-claim-recovery"])
def test_dead_owner_and_recovery_guard_can_be_reclaimed(tmp_path, directory):
    write_json(tmp_path / directory / "owner.json", dead_owner())
    lease = lifecycle.RunnerLease(tmp_path)
    lease.close()
    assert not (tmp_path / "runner-claim").exists()
    assert not (tmp_path / "runner-claim-recovery").exists()


@pytest.mark.parametrize("directory", ["runner-claim", "runner-claim-recovery"])
def test_legacy_empty_claim_has_a_startup_grace_period(tmp_path, directory):
    path = tmp_path / directory
    path.mkdir()
    with pytest.raises(lifecycle.AlreadyRunning):
        lifecycle.RunnerLease(tmp_path)
    os.utime(path, (1, 1))
    lease = lifecycle.RunnerLease(tmp_path)
    lease.close()


def test_reused_pid_cannot_keep_a_dead_claim_alive(tmp_path):
    write_json(tmp_path / "runner-claim/owner.json", dead_owner() | {
        "pid": os.getpid(), "process_start": "previous-process-incarnation",
    })
    write_json(tmp_path / "runner.json", {"runner": "ready"})
    lease = lifecycle.RunnerLease(tmp_path)
    lease.close()


def test_unknown_foreign_owner_is_never_removed(tmp_path):
    owner = dead_owner() | {"platform": "unknown"}
    write_json(tmp_path / "runner-claim/owner.json", owner)
    with pytest.raises(lifecycle.AlreadyRunning):
        lifecycle.RunnerLease(tmp_path)
    assert read_json(tmp_path / "runner-claim/owner.json") == owner


def test_live_legacy_heartbeat_prevents_a_new_runner(tmp_path):
    write_json(tmp_path / "runner.json", {"runner": "thinking"})
    with pytest.raises(lifecycle.AlreadyRunning):
        lifecycle.RunnerLease(tmp_path)
    assert not (tmp_path / "runner-claim-recovery").exists()


def test_request_stop_uses_owned_token_and_returns_player_control(tmp_path):
    lease = lifecycle.RunnerLease(tmp_path)
    try:
        write_json(tmp_path / "control.json", {"enabled": True, "revision": 4})
        assert lifecycle.request_stop(tmp_path)
        assert read_json(lease.stop_file) == {"stop": True}
        assert read_json(tmp_path / "control.json") == {"enabled": False, "revision": 5}
    finally:
        lease.close()


@pytest.mark.parametrize("revision", [None, {}, "invalid", True, -1])
def test_invalid_control_revision_cannot_prevent_an_owned_stop(tmp_path, revision):
    lease = lifecycle.RunnerLease(tmp_path)
    try:
        write_json(tmp_path / "control.json", {"enabled": True, "revision": revision})
        assert lifecycle.request_stop(tmp_path)
        assert read_json(lease.stop_file) == {"stop": True}
        assert read_json(tmp_path / "control.json") == {"enabled": False, "revision": 1}
    finally:
        lease.close()


def test_control_write_failure_cannot_prevent_an_owned_stop(tmp_path, monkeypatch):
    lease = lifecycle.RunnerLease(tmp_path)
    original = lifecycle.write_json

    def blocked_control(path, value):
        if path.name == "control.json":
            raise PermissionError("fixture control file is locked")
        return original(path, value)

    try:
        write_json(tmp_path / "control.json", {"enabled": True, "revision": 4})
        monkeypatch.setattr(lifecycle, "write_json", blocked_control)
        assert lifecycle.request_stop(tmp_path)
        assert read_json(lease.stop_file) == {"stop": True}
    finally:
        lease.close()


def setup_worker(tmp_path, monkeypatch):
    settings = SimpleNamespace(consent=True, io=tmp_path, model="fixture", timeout=2, codex="")
    monkeypatch.setattr(lifecycle, "load_settings", lambda root: settings)
    write_json(tmp_path / "snapshot.json", {"protocol": 1, "session": "test", "seq": 1,
        "player": {"id": "human", "position": [0, 0, 0]},
        "companion": {"id": "friend", "position": [0, 0, 0]}, "nearby": []})
    write_json(tmp_path / "control.json", {"session": "test", "enabled": True, "companion": "friend", "revision": 1})


def test_dead_parent_stops_even_if_stop_file_write_fails(tmp_path, monkeypatch):
    setup_worker(tmp_path, monkeypatch)
    answers = iter([True, False])
    monkeypatch.setattr(lifecycle, "process_alive", lambda *args: next(answers, False))
    monkeypatch.setattr(lifecycle, "_process_stamp", lambda pid: None)
    original = lifecycle.write_json

    def write(path, value):
        if path.name.startswith("stop-runner-"):
            raise PermissionError("fixture stop file busy")
        return original(path, value)

    monkeypatch.setattr(lifecycle, "write_json", write)
    lifecycle.run_worker(tmp_path, parent_pid=123, offline=True, no_gui=True)
    assert read_json(tmp_path / "runner.json")["runner"] == "stopped"
    assert read_json(tmp_path / "control.json")["enabled"] is False
    assert not (tmp_path / "runner-claim").exists()


@pytest.mark.parametrize("permission", ["withdrawn", "unreadable", "missing"])
def test_saved_consent_loss_stops_online_worker_without_a_stop_file(tmp_path, monkeypatch, permission):
    setup_worker(tmp_path, monkeypatch)
    write_json(tmp_path / "settings.json", {"consent": True})
    # Exercise the online permission path using an entirely local replay model.
    monkeypatch.setattr(lifecycle, "CodexModel", lambda *args: lifecycle.ReplayModel())
    original = lifecycle.write_json

    def write(path, value):
        if path.name.startswith("stop-runner-"):
            raise PermissionError("fixture stop file locked")
        return original(path, value)

    monkeypatch.setattr(lifecycle, "write_json", write)
    failures = []

    def run():
        try:
            lifecycle.run_worker(tmp_path, no_gui=True)
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while not (tmp_path / "runner.json").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert worker.is_alive()
        if permission == "withdrawn":
            write_json(tmp_path / "settings.json", {"consent": False})
        elif permission == "unreadable":
            (tmp_path / "settings.json").write_text("{invalid", encoding="utf-8")
        else:
            (tmp_path / "settings.json").unlink()
        worker.join(2)
        assert not worker.is_alive() and not failures
        assert read_json(tmp_path / "runner.json")["runner"] == "stopped"
        assert read_json(tmp_path / "control.json")["enabled"] is False
    finally:
        owner = read_json(tmp_path / "runner-claim/owner.json") or {}
        if owner.get("token"):
            original(tmp_path / f"stop-runner-{owner['token']}.json", {"stop": True})
        worker.join(2)


def test_already_dead_parent_does_not_acquire_or_launch(tmp_path, monkeypatch):
    setup_worker(tmp_path, monkeypatch)
    monkeypatch.setattr(lifecycle, "process_alive", lambda *args: False)
    lifecycle.run_worker(tmp_path, parent_pid=123, offline=True)
    assert not (tmp_path / "runner-claim").exists()
    assert not (tmp_path / "runner.json").exists()


def test_overlay_start_failure_releases_lease(tmp_path, monkeypatch):
    setup_worker(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise OSError("fixture cannot start overlay")
    monkeypatch.setattr(lifecycle.subprocess, "Popen", fail)
    with pytest.raises(OSError):
        lifecycle.run_worker(tmp_path, offline=True)
    lease = lifecycle.RunnerLease(tmp_path)
    lease.close()


def test_overlay_exit_stops_runner_and_returns_player_control(tmp_path, monkeypatch):
    setup_worker(tmp_path, monkeypatch)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *a, **k: SimpleNamespace(poll=lambda: 1))
    lifecycle.run_worker(tmp_path, offline=True)
    assert read_json(tmp_path / "runner.json")["runner"] == "stopped"
    assert not read_json(tmp_path / "control.json")["enabled"]
    assert not (tmp_path / "runner-claim").exists()


def test_current_process_identity_is_readable():
    assert lifecycle.process_alive(os.getpid()) is True
    assert lifecycle._process_stamp(os.getpid())
    assert lifecycle.process_alive(True) is None


def source_launcher():
    spec = importlib.util.spec_from_file_location("friend_source_launch", Path(__file__).parents[1] / "scripts/launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_launcher_claim_uses_the_shared_lease(tmp_path):
    launch = source_launcher()
    owner = launch.claim_runner(tmp_path)
    try:
        with pytest.raises(lifecycle.AlreadyRunning):
            lifecycle.RunnerLease(tmp_path)
    finally:
        owner.close()


def test_source_launcher_retains_options_and_releases_after_gui_failure(tmp_path, monkeypatch):
    launch = source_launcher()
    monkeypatch.setattr(sys, "argv", ["launch.py", "--io", str(tmp_path), "--offline", "--max-calls", "1", "--gui-python", "missing.exe"])
    monkeypatch.setattr(launch, "gui_python", lambda value: (_ for _ in ()).throw(RuntimeError("prepare Windows Python")))
    with pytest.raises(RuntimeError, match="prepare Windows Python"):
        launch.main()
    lease = lifecycle.RunnerLease(tmp_path)
    lease.close()


def test_source_launcher_missing_tk_reports_the_required_setup(monkeypatch):
    launch = source_launcher()
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match="tkinter"):
        launch.check_gui_python(Path("fixture-python.exe"))
