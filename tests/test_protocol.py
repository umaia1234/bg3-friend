import copy
import json
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from companion.protocol import command_for, validate_decision, write_json, read_json
from companion.model import ReplayModel
from companion.runner import BridgeIOError, Runner


def scene():
    return {"protocol": 1, "session": "s1", "seq": 10, "player": {"id": "player", "position": [0, 0, 0]},
            "companion": {"id": "friend", "position": [4, 0, 0], "selected": False},
            "nearby": [{"id": "box", "position": [6, 0, 0], "hostile": False, "dead": False}]}


def decision(action="approach", target="box"):
    return {"say": "저쪽 좀 볼게.", "action": action, "target": target, "reason": "가까운 관찰 대상", "remember": "", "stance": "keep"}


@pytest.mark.parametrize("change", [
    {"action": "execute_lua"}, {"target": "unseen"}, {"say": 42}, {"say": "x" * 301}, {"extra": "bad"},
])
def test_rejects_untrusted_decisions(change):
    with pytest.raises(ValueError):
        validate_decision(decision() | change, scene())


@pytest.mark.parametrize("change", [{"hostile": True}, {"dead": True}, {"position": [80, 0, 0]}])
def test_rejects_unavailable_exploration_target(change):
    s = scene()
    s["nearby"][0].update(change)
    with pytest.raises(ValueError):
        validate_decision(decision(), s)


def test_blocked_movement_but_conversation_can_wait():
    s = scene() | {"blocked": "combat"}
    with pytest.raises(ValueError):
        validate_decision(decision(), s)
    assert validate_decision(decision("wait", ""), s)["action"] == "wait"


def test_command_binds_actor_session_and_observation():
    c = command_for(decision(), scene(), 7)
    assert (c["actor"], c["session"], c["observed_seq"], c["control_revision"]) == ("friend", "s1", 10, 7)


def test_partial_snapshot_is_retried(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text('{"session":')
    assert read_json(p) is None
    write_json(p, scene())
    assert read_json(p)["session"] == "s1"


@pytest.mark.parametrize("steer", ["reload", "pause", "reassign", "new_message", "combat"])
def test_inflight_decision_never_overrides_new_situation(tmp_path, steer):
    s = scene()
    control = {"session": "s1", "enabled": True, "revision": 1, "companion": "friend"}
    write_json(tmp_path / "snapshot.json", s)
    write_json(tmp_path / "control.json", control)
    r = Runner(tmp_path, ReplayModel(), max_calls=1)
    r.session = "s1"
    r.last_control_revision = 1
    r.pending_context = {"session": "s1", "revision": 1, "message_revision": 0, "actor": "friend"}
    r.pending = Future()
    r.pending.set_result((decision(), 1))
    r.calls = 1
    if steer == "reload":
        s["session"] = "s2"
    elif steer == "pause":
        control.update(enabled=False, revision=2)
    elif steer == "reassign":
        s["companion"]["id"] = "someone_else"
    elif steer == "new_message":
        write_json(tmp_path / "inbox/1.json", {"session": "s1", "text": "잠깐 기다려"})
    elif steer == "combat":
        s["blocked"] = "combat"
    write_json(tmp_path / "snapshot.json", s)
    write_json(tmp_path / "control.json", control)
    r.tick()
    assert not (tmp_path / "command.json").exists()
    r.pool.shutdown()


def test_reload_drops_future_memories(tmp_path):
    r = Runner(tmp_path, ReplayModel())
    r.memory = [{"text": "This happened after the save"}]
    r.switch_session(scene())
    assert r.memory == []
    assert read_json(tmp_path / "memory.json")["notes"] == []
    r.pool.shutdown()


def test_restarting_runner_keeps_only_same_game_session_memory(tmp_path):
    write_json(tmp_path / "conversation.json", {"session": "s1", "events": [{"role": "user", "text": "Wait for me"}]})
    write_json(tmp_path / "memory.json", {"session": "s1", "notes": [{"text": "Human prefers to scout first"}]})
    r = Runner(tmp_path, ReplayModel())
    r.switch_session(scene())
    assert r.memory == [{"text": "Human prefers to scout first"}]
    assert r.history[0]["text"] == "Wait for me"
    r.switch_session(scene() | {"session": "s2"})
    assert r.memory == []
    assert all(event.get("text") != "Wait for me" for event in r.history)
    r.pool.shutdown()


def start_runner(tmp_path, model=None, **kwargs):
    write_json(tmp_path / "snapshot.json", scene())
    write_json(tmp_path / "control.json", {
        "session": "s1", "enabled": True, "revision": 1, "companion": "friend",
    })
    return Runner(tmp_path, model or ReplayModel(), **kwargs)


def test_combat_round_trip_invalidates_the_precombat_decision(tmp_path):
    r = start_runner(tmp_path, max_calls=1)
    r.tick()
    # Keep a genuinely running future in flight through both transitions.
    r.pending.result(timeout=2)
    r.pending = Future()
    r.pending.set_running_or_notify_cancel()
    write_json(tmp_path / "snapshot.json", scene() | {"blocked": "combat"})
    r.tick()
    write_json(tmp_path / "snapshot.json", scene())
    r.pending.set_result((decision(), 12))
    r.tick()
    assert not (tmp_path / "command.json").exists()
    assert not any(event["role"] == "friend" for event in r.history)
    r.pool.shutdown()


class CancellableFixture:
    model = "cancellable-fixture"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_event = None
        self.cancel_requests = 0
        self.active = 0
        self.maximum_active = 0
        self.invocations = 0

    def decide_cancellable(self, snapshot, memory, messages, cancel_event):
        self.cancel_event = cancel_event
        self.active += 1
        self.invocations += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.started.set()
        try:
            assert self.release.wait(5), "test must release its local fixture"
            if cancel_event.is_set():
                raise CancelledError()
            return decision("wait", ""), 0
        finally:
            self.active -= 1

    def cancel_pending(self):
        self.cancel_requests += 1


@pytest.mark.parametrize("steer", ["pause", "reload", "reassign", "combat", "new_message", "missing_snapshot", "stale_snapshot"])
def test_runtime_changes_cancel_the_model_without_overlapping_calls(tmp_path, steer):
    model = CancellableFixture()
    r = start_runner(tmp_path, model)
    try:
        r.tick()
        assert model.started.wait(2)
        state = scene()
        control = read_json(tmp_path / "control.json")
        if steer == "pause":
            control.update(enabled=False, revision=2)
        elif steer == "reload":
            state["session"] = "s2"
        elif steer == "reassign":
            state["companion"]["id"] = "other"
            control.update(companion="other", revision=2)
        elif steer == "combat":
            state["blocked"] = "combat"
        elif steer == "new_message":
            write_json(tmp_path / "inbox/1.json", {"session": "s1", "actor": "friend", "text": "잠깐 기다려"})
        write_json(tmp_path / "control.json", control)
        write_json(tmp_path / "snapshot.json", state)
        if steer == "missing_snapshot":
            (tmp_path / "snapshot.json").unlink()
        elif steer == "stale_snapshot":
            import os
            os.utime(tmp_path / "snapshot.json", (1, 1))
        r.tick()
        r.tick()
        assert model.cancel_event.is_set()
        assert model.cancel_requests == 1
        assert model.invocations == 1 and model.maximum_active == 1
        assert not (tmp_path / "command.json").exists()
        model.release.set()
        with pytest.raises(CancelledError):
            r.pending.result(timeout=2)
        r.tick()
        if steer in ("pause", "reload", "missing_snapshot", "stale_snapshot"):
            assert model.invocations == 1
        assert model.maximum_active == 1
    finally:
        model.release.set()
        r.pool.shutdown()


class FixtureFailure(RuntimeError):
    code = "fixture_failure"

    def __init__(self, retryable=True):
        super().__init__("local failure")
        self.retryable = retryable


class FailingFixture:
    model = "failing-fixture"

    def __init__(self, retryable=True):
        self.retryable = retryable
        self.observations = []

    def decide(self, snapshot, memory, messages):
        self.observations.append(copy.deepcopy(snapshot))
        raise FixtureFailure(self.retryable)


@pytest.mark.parametrize("human_message", [False, True])
def test_transient_failure_retries_original_reason_with_a_finite_budget(tmp_path, monkeypatch, human_message):
    model = FailingFixture()
    r = start_runner(tmp_path, model)
    clock = [100.0]
    monkeypatch.setattr("companion.runner.time.monotonic", lambda: clock[0])
    if human_message:
        write_json(tmp_path / "inbox/1.json", {"session": "s1", "text": "기다려 줘"})
    try:
        r.tick()
        for attempt, delay in enumerate((1, 5, 15, None), start=1):
            with pytest.raises(FixtureFailure):
                r.pending.result(timeout=2)
            r.tick()
            assert r.calls == attempt
            if delay is None:
                assert r.status["runner"] == "error"
                break
            assert r.status["runner"] == "retrying"
            clock[0] += delay - .1
            r.tick()
            assert r.calls == attempt
            clock[0] += .1
            r.tick()
        clock[0] += 100
        r.tick()
        assert r.calls == 4 and r.pending is None
        reasons = [item["attention"]["trigger"] for item in model.observations]
        assert len(set(reasons)) == 1
        assert reasons[0] == ("human_message" if human_message else "joined")
        assert r.unanswered is human_message
    finally:
        r.pool.shutdown()


def test_nonretryable_error_stays_visible_until_explicit_steering(tmp_path, monkeypatch):
    r = start_runner(tmp_path, FailingFixture(retryable=False))
    clock = [100.0]
    monkeypatch.setattr("companion.runner.time.monotonic", lambda: clock[0])
    try:
        r.tick()
        with pytest.raises(FixtureFailure):
            r.pending.result(timeout=2)
        r.tick()
        clock[0] += 100
        r.tick()
        assert r.calls == 1 and r.status["runner"] == "error"
        assert r.status["error_code"] == "fixture_failure"
        control = read_json(tmp_path / "control.json")
        write_json(tmp_path / "control.json", control | {"enabled": False, "revision": 2})
        r.tick()
        clock[0] += 100
        r.tick()
        assert r.calls == 1 and r.status["runner"] == "paused"
        write_json(tmp_path / "control.json", control | {"revision": 3})
        write_json(tmp_path / "inbox/1.json", {"session": "s1", "text": "다시 얘기해 줘"})
        r.tick()
        assert r.calls == 2 and r.pending is not None
        assert r.failures == 0
    finally:
        r.pool.shutdown()


@pytest.mark.parametrize("change", [
    {"companion": "other", "revision": 2}, {"revision": 2}, {"enabled": False, "revision": 2},
])
def test_new_control_cannot_submit_from_an_unacknowledged_game_snapshot(tmp_path, change):
    r = start_runner(tmp_path)
    control = read_json(tmp_path / "control.json")
    write_json(tmp_path / "snapshot.json", scene() | {"control_revision": 1})
    write_json(tmp_path / "control.json", control | change)
    try:
        r.tick()
        assert r.calls == 0 and r.pending is None
        assert not (tmp_path / "command.json").exists()
    finally:
        r.pool.shutdown()


def test_stop_cancels_model_and_returns_game_control(tmp_path):
    model = CancellableFixture()
    r = start_runner(tmp_path, model)
    stop = tmp_path / "stop.json"

    def stop_after_started():
        assert model.started.wait(2)
        write_json(stop, {"stop": True})

    stopper = threading.Thread(target=stop_after_started, daemon=True)
    stopper.start()
    try:
        r.run(stop)
        assert model.cancel_event.is_set()
        assert model.cancel_requests == 1
        assert not read_json(tmp_path / "control.json")["enabled"]
        assert read_json(tmp_path / "runner.json")["runner"] == "stopped"
        r.tick()
        assert model.invocations == 1
    finally:
        model.release.set()
        stopper.join(timeout=2)
        r.pool.shutdown()


def test_uncancellable_fixture_cannot_keep_stopped_runner_process_alive(tmp_path):
    write_json(tmp_path / "snapshot.json", scene())
    write_json(tmp_path / "control.json", {"session": "s1", "enabled": True, "revision": 1, "companion": "friend"})
    script = tmp_path / "stop_probe.py"
    script.write_text(textwrap.dedent('''
        import sys, threading, time
        from pathlib import Path
        sys.path.insert(0, sys.argv[2])
        from companion.protocol import write_json
        from companion.runner import Runner
        class Slow:
            model = "local-slow-fixture"
            def decide(self, *args):
                time.sleep(10)
        folder = Path(sys.argv[1])
        runner = Runner(folder, Slow())
        stop = folder / "stop.json"
        def request_stop():
            while runner.pending is None:
                time.sleep(.01)
            write_json(stop, {"stop": True})
        threading.Thread(target=request_stop, daemon=True).start()
        runner.run(stop)
        print("stopped", flush=True)
    '''), encoding="utf-8")
    # The original ThreadPoolExecutor keeps this child alive for ten seconds.
    completed = subprocess.run([sys.executable, str(script), str(tmp_path), str(Path(__file__).parents[1])], capture_output=True,
                               text=True, timeout=4, check=True, cwd=Path(__file__).parents[1])
    assert completed.stdout.strip() == "stopped"


@contextmanager
def windows_reader_without_delete_sharing(path):
    """A real Windows reader permits reads/writes but blocks atomic replacement."""
    import ctypes as C
    from ctypes import wintypes as W
    api = C.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    api.CreateFileW.restype = W.HANDLE
    api.CloseHandle.argtypes = [W.HANDLE]
    api.CloseHandle.restype = W.BOOL
    handle = api.CreateFileW(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        yield
    finally:
        assert api.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows non-delete-sharing file handle")
def test_locked_atomic_command_preserves_the_previous_complete_document(tmp_path):
    path = tmp_path / "command.json"
    original = command_for(decision("wait", ""), scene(), 1)
    write_json(path, original)
    before = path.read_bytes()
    started = time.monotonic()
    with windows_reader_without_delete_sharing(path):
        with pytest.raises(PermissionError) as failure:
            write_json(path, original | {"id": "new-command", "session": "other"})
        assert failure.value.winerror in (5, 32, 33)
        assert path.read_bytes() == before
    assert time.monotonic() - started < 2
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Real Windows non-delete-sharing file handle")
def test_runner_survives_a_windows_reader_holding_status_past_the_short_retry(tmp_path):
    runner = Runner(tmp_path, ReplayModel())
    path = tmp_path / "runner.json"
    original = {"runner": "waiting_game", "updated": 0}
    write_json(path, original)
    stop, failures = threading.Event(), []

    def run():
        try:
            runner.run(SimpleNamespace(exists=stop.is_set))
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    try:
        with windows_reader_without_delete_sharing(path):
            worker.start()
            time.sleep(1.2)
            assert worker.is_alive(), repr(failures)
            assert read_json(path) == original
            assert runner.calls == 0
        deadline = time.monotonic() + 3
        latest = None
        while time.monotonic() < deadline:
            latest = read_json(path)
            if latest and latest.get("updated") != 0:
                break
            time.sleep(.02)
        assert latest and latest.get("updated") != 0
        assert worker.is_alive() and not failures
    finally:
        stop.set()
        worker.join(4)
    assert not worker.is_alive() and not failures
    assert read_json(path)["runner"] == "stopped"


@pytest.mark.parametrize("steer", ["reload", "reassign", "pause", "combat_round_trip"])
def test_status_recovery_discards_cancelled_decision_and_rechecks_current_context(tmp_path, monkeypatch, steer):
    model = CancellableFixture()
    runner = start_runner(tmp_path, model, max_calls=2, interval=0)
    old_command = command_for(decision("wait", ""), scene(), 1)
    write_json(tmp_path / "command.json", old_command)
    locked = [True]
    original = write_json

    def status_contention(path, value):
        if path.name == "runner.json" and locked[0]:
            raise PermissionError("fixture reader has not released the file")
        return original(path, value)

    monkeypatch.setattr("companion.runner.write_json", status_contention)
    try:
        runner.tick()
        assert model.started.wait(2)
        assert runner.publish_status() is False
        assert model.cancel_event.is_set() and model.cancel_requests == 1
        state, control = scene(), read_json(tmp_path / "control.json")
        if steer == "reload":
            state["session"] = control["session"] = "s2"
        elif steer == "reassign":
            state["companion"]["id"] = control["companion"] = "other"
        elif steer == "pause":
            control["enabled"] = False
        else:
            write_json(tmp_path / "snapshot.json", state | {"blocked": "combat"})
            runner.tick()
        if steer != "combat_round_trip":
            control["revision"] = 2
        state["control_revision"] = control["revision"]
        state["seq"] += 1
        write_json(tmp_path / "control.json", control)
        write_json(tmp_path / "snapshot.json", state)
        runner.tick()
        runner.tick()
        assert runner.calls == 1 and model.invocations == 1
        assert read_json(tmp_path / "command.json") == old_command
        model.release.set()
        with pytest.raises(CancelledError):
            runner.pending.result(timeout=2)
        locked[0] = False
        assert runner.publish_status() is True
        runner.tick()
        assert read_json(tmp_path / "command.json") == old_command
        if steer == "pause":
            assert runner.calls == 1 and runner.pending is None
        else:
            runner.pending.result(timeout=2)
            runner.tick()
            command = read_json(tmp_path / "command.json")
            assert command["id"] != old_command["id"]
            assert (command["session"], command["actor"], command["control_revision"], command["observed_seq"]) == (
                state["session"], state["companion"]["id"], control["revision"], state["seq"])
            assert runner.calls == 2 and model.maximum_active == 1
    finally:
        model.release.set()
        runner.pool.shutdown()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows non-delete-sharing file handle")
def test_permanent_status_lock_stops_with_a_safe_error_and_returns_control(tmp_path):
    runner = start_runner(tmp_path, max_calls=1)
    runner.STATUS_WRITE_GRACE = .3
    path = tmp_path / "runner.json"
    write_json(path, {"runner": "ready", "session": "s1", "updated": 0})
    started = time.monotonic()
    with windows_reader_without_delete_sharing(path):
        with pytest.raises(BridgeIOError) as failure:
            runner.run()
    assert time.monotonic() - started < 3
    assert failure.value.code == "local_io_failed" and str(tmp_path) not in str(failure.value)
    assert not read_json(tmp_path / "control.json")["enabled"]
    assert runner.stopping and runner.pool.closed
    assert not (tmp_path / "command.json").exists()


def test_nonpermission_status_error_is_not_silently_retried(tmp_path, monkeypatch):
    runner = start_runner(tmp_path, max_calls=1)
    original, writes = write_json, []

    def full_disk(path, value):
        if path.name == "runner.json":
            writes.append(value["runner"])
            raise OSError(28, "private fixture disk path")
        return original(path, value)

    monkeypatch.setattr("companion.runner.write_json", full_disk)
    with pytest.raises(BridgeIOError) as failure:
        runner.run()
    assert writes[-1] == "stopped" and len(writes) == 2
    assert "private" not in str(failure.value)
    assert not read_json(tmp_path / "control.json")["enabled"]
    assert runner.pool.closed


def test_failed_control_return_does_not_prevent_stopped_status_and_worker_cleanup(tmp_path, monkeypatch):
    runner = start_runner(tmp_path)
    runner.session = "s1"
    original = write_json

    def blocked_control(path, value):
        if path.name == "control.json":
            raise PermissionError("private fixture control path")
        return original(path, value)

    monkeypatch.setattr("companion.runner.write_json", blocked_control)
    with pytest.raises(BridgeIOError):
        runner.run(SimpleNamespace(exists=lambda: True))
    assert read_json(tmp_path / "runner.json")["runner"] == "stopped"
    assert runner.pool.closed


def test_waiting_agreement_is_validated_before_atomic_command_publication(tmp_path):
    runner = start_runner(tmp_path, max_calls=1)
    try:
        runner.tick()
        runner.pending.result(timeout=2)
        runner.director.stance = "hold"
        runner.pending = Future()
        runner.pending.set_result((decision("approach", "box"), 0))
        runner.tick()
        assert not (tmp_path / "command.json").exists()
        assert runner.director.stance == "hold"
        assert runner.status["runner"] == "error"
    finally:
        runner.pool.shutdown()


def test_blocked_command_publication_does_not_commit_the_new_plan(tmp_path, monkeypatch):
    runner = start_runner(tmp_path, max_calls=1)
    original = write_json

    def blocked_command(path, value):
        if path.name == "command.json":
            raise PermissionError("fixture command reader")
        return original(path, value)

    monkeypatch.setattr("companion.runner.write_json", blocked_command)
    try:
        runner.tick()
        runner.pending.result(timeout=2)
        runner.director.stance = "scout"
        runner.pending = Future()
        runner.pending.set_result((decision("wait", "") | {"stance": "hold"}, 0))
        runner.tick()
        assert not (tmp_path / "command.json").exists()
        assert runner.director.stance == "scout"
        assert runner.command_pending is None
    finally:
        runner.pool.shutdown()
