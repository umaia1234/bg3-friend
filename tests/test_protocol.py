import copy
import json
from concurrent.futures import CancelledError, Future
from pathlib import Path
import subprocess
import sys
import textwrap
import threading

import pytest

from companion.protocol import command_for, validate_decision, write_json, read_json
from companion.model import ReplayModel
from companion.runner import Runner


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
