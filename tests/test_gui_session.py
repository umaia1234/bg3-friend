"""Exercise the real chat handler and runner without creating a desktop window."""
from types import SimpleNamespace

import pytest

from companion.gui import FriendWindow
from companion.model import ReplayModel
from companion.protocol import read_json, write_json
from companion.runner import Runner


def invitation_ui(tmp_path):
    chat = FriendWindow.__new__(FriendWindow)
    chat.folder, chat.session, chat.choice = tmp_path, 'current', 'friend'
    chat.members = {'friend': '레이젤'}
    chat.review_actor = chat.connection_pending = None
    chat.editing = chat.intro_visible = False
    chat.game = SimpleNamespace(focus=lambda: None)
    widget = lambda: SimpleNamespace(configure=lambda **_: None, pack=lambda **_: None, pack_forget=lambda: None)
    chat.chat, chat.intro_card, chat.intro_title, chat.intro_body, chat.intro_yes, chat.intro_no = [widget() for _ in range(6)]
    chat.snapshot = {'session': 'current', 'introductions': {
        'ready': True, 'candidates': [{'id': 'new', 'name': '새 동료', 'in_party': False}], 'choices': {}}}
    chat.intro_item = chat.snapshot['introductions']['candidates'][0]
    write_json(tmp_path / 'snapshot.json', chat.snapshot)
    write_json(tmp_path / 'control.json', {'session': 'current', 'companion': 'friend', 'enabled': False, 'revision': 1})
    return chat


def test_invitation_accepts_only_after_join_and_leaves_typing_undisturbed(tmp_path):
    chat = invitation_ui(tmp_path)
    chat.choose_introduction('friend')
    request = read_json(tmp_path / 'connection-request.json')
    assert request['actor'] == 'new' and request['activate']
    assert not chat.control()['enabled']
    intro = chat.snapshot['introductions']
    intro.update(choices={'new': 'friend'}, result={'id': request['id'], 'status': 'stored'},
                 deferred={'actor': 'new', 'revision': 1, 'session': 'current'})
    chat.sync_introductions(chat.snapshot, chat.control())
    assert chat.control()['companion'] == 'friend'
    chat.members['new'] = '새 동료'
    intro['candidates'][0]['in_party'] = True
    chat.editing = True
    chat.sync_introductions(chat.snapshot, chat.control())
    assert not chat.control()['enabled']
    chat.editing = False
    chat.sync_introductions(chat.snapshot, chat.control())
    assert chat.control()['enabled'] and chat.control()['companion'] == 'new'


def test_decline_does_not_start_model_or_stop_a_different_friend(tmp_path):
    chat = invitation_ui(tmp_path)
    before = chat.control() | {'enabled': True}
    write_json(tmp_path / 'control.json', before)
    chat.choose_introduction('manual')
    assert chat.control() == before
    assert not (tmp_path / 'inbox').exists() and not (tmp_path / 'command.json').exists()
    request = read_json(tmp_path / 'connection-request.json')
    chat.snapshot['introductions'].update(choices={'new': 'manual'}, result={'id': request['id'], 'status': 'stored'})
    chat.sync_introductions(chat.snapshot, chat.control())
    assert not chat.intro_visible
    chat.review_introduction('new')
    chat.sync_introductions(chat.snapshot, chat.control())
    assert chat.intro_visible


def test_pending_recruitment_can_be_canceled_without_any_party_companion(tmp_path):
    chat = invitation_ui(tmp_path)
    chat.choice, chat.members = None, {}
    chat.snapshot['introductions']['deferred'] = {'actor': 'new', 'revision': 1, 'session': 'current'}
    assert chat.waiting_introduction(chat.control())['id'] == 'new'
    chat.set_enabled(False)
    assert chat.control()['revision'] == 2 and not chat.control()['enabled']
    assert chat.waiting_introduction(chat.control()) is None
    chat.members['new'] = '새 동료'
    chat.snapshot['introductions']['candidates'][0]['in_party'] = True
    chat.sync_introductions(chat.snapshot, chat.control())
    assert not chat.control()['enabled']


@pytest.mark.parametrize('steer', ['reload', 'dialogue', 'left_scene', 'stale_file'])
def test_old_or_blocked_card_click_cannot_connect(tmp_path, steer):
    import os
    chat = invitation_ui(tmp_path)
    latest = read_json(tmp_path / 'snapshot.json')
    if steer == 'reload':
        latest['session'] = 'different'
    elif steer == 'dialogue':
        latest['introductions']['ready'] = False
    elif steer == 'left_scene':
        latest['introductions']['candidates'] = []
    write_json(tmp_path / 'snapshot.json', latest)
    if steer == 'stale_file':
        os.utime(tmp_path / 'snapshot.json', (1, 1))
    chat.choose_introduction('friend')
    assert not (tmp_path / 'connection-request.json').exists()
    assert not chat.control()['enabled']


@pytest.mark.parametrize("control", [
    {},
    {"session": "before-reload", "enabled": True, "companion": "friend", "revision": 8},
    {"session": "current", "enabled": False, "companion": "friend", "revision": 8},
    {"session": "current", "enabled": True, "companion": "friend", "revision": 8},
])
def test_first_chat_reaches_runner_in_current_game_session(tmp_path, control):
    write_json(tmp_path / "control.json", control)
    write_json(tmp_path / "snapshot.json", {
        "protocol": 1, "session": "current", "seq": 1,
        "player": {"id": "human", "position": [0, 0, 0]},
        "companion": {"id": "friend", "name": "레이젤", "position": [3, 0, 0]},
        "nearby": [],
    })
    chat = FriendWindow.__new__(FriendWindow)
    chat.folder, chat.session, chat.choice = tmp_path, "current", "friend"
    chat.placeholder = False
    chat.entry = SimpleNamespace(get=lambda: "같이 가자", delete=lambda *_: None)
    chat.leave_typing = lambda: None
    assert chat.send() == "break"

    runner = Runner(tmp_path, ReplayModel(), max_calls=1)
    try:
        runner.tick()
        assert runner.pending is not None, "First message must resume the current session"
        runner.pending.result(timeout=2)
        runner.tick()
        assert read_json(tmp_path / "command.json")["session"] == "current"
        assert [e["role"] for e in runner.history if e["role"] in ("user", "friend")] == ["user", "friend"]
    finally:
        runner.pool.shutdown(wait=True)
