import copy
import pytest
from companion.director import Director
from companion.protocol import validate_decision
from test_protocol import scene, decision


def test_waiting_agreement_survives_idle_thoughts_and_restart():
    d = Director()
    d.apply(decision('wait', '') | {'stance': 'hold'}, True)
    restored = Director(d.saved())
    for next_decision in [decision('follow', ''), decision('wait', '') | {'stance': 'together'}]:
        with pytest.raises(ValueError):
            restored.apply(next_decision, False)
    assert not restored.regroup(scene() | {'player': {'position': [50, 0, 0]}})
    restored.apply(decision('follow', '') | {'stance': 'together'}, True)
    assert restored.stance == 'together'


def test_no_repeat_attention_in_an_unchanged_scene():
    d = Director()
    d.observe(scene())
    d.trigger = None
    for _ in range(100):
        d.observe(scene())
    assert d.trigger is None
    moved = copy.deepcopy(scene())
    moved['player']['position'] = [8, 0, 0]
    d.observe(moved)
    assert d.trigger == 'human_moved'


def test_reflex_does_not_override_blocked_selected_or_waiting():
    s = scene(); s['player']['position'] = [20, 0, 0]
    d = Director()
    assert d.regroup(s)
    assert not d.regroup(s | {'blocked': 'combat'})
    s['companion']['selected'] = True
    assert not d.regroup(s)


def test_waiting_plan_cannot_dispatch_movement():
    with pytest.raises(ValueError):
        validate_decision(decision() | {'stance': 'hold'}, scene())


def test_only_observed_completion_marks_a_target_visited():
    d = Director()
    d.apply(decision(), False)
    assert d.visited == []
    d.completed({'action': 'approach', 'target': 'box'})
    assert Director(d.saved()).visited == ['box']
