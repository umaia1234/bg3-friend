import copy
import json
from concurrent.futures import Future
from pathlib import Path

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
