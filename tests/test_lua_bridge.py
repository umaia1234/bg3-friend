"""Execute real Lua bridge against an adversarial fake engine, not translated logic."""
import json
from pathlib import Path

from lupa import LuaRuntime
import pytest

SOURCE = Path(__file__).parents[1] / "mod/Mods/BG3Friend/ScriptExtender/Lua/Server.lua"


@pytest.fixture
def bridge():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        clock = 1000; saved = {}; files = {}; events = {}; listeners = {}; moved = 0; flushed = 0; noFollow = 0; vars = {}
        host = "11111111-1111-1111-1111-111111111111"
        friend = "22222222-2222-2222-2222-222222222222"
        control = {enabled=true,session="",companion=friend,revision=1}
        function entity(uuid,x)
          return {Uuid={EntityUuid=uuid},Transform={Transform={Translate={x,0,0}}},
             Health={Hp=10,MaxHp=10},ServerCharacter={}}
        end
        entities = {[host]=entity(host,0),[friend]=entity(friend,6)}
        Ext = {
          Vars={RegisterModVariable=function() end,GetModVariables=function() return vars end},
          Timer={MonotonicTime=function() return clock end},
          IO={LoadFile=function(name) return files[name] end,
              SaveFile=function(name,value) saved[name]=value; return true end},
          Json={Parse=function(value) return value end,Stringify=function(value) return value end},
          Entity={Get=function(uuid) return entities[uuid] end,GetEntitiesAroundPosition=function() return {} end},
          Level={BeginPathfindingImmediate=function() return {} end,FindPath=function() return true end,ReleasePath=function() end},
          Debug={GenerateIdeHelpers=function() end},
          Events=setmetatable({}, {__index=function(t,key)
             local value={Subscribe=function(_,fn) events[key]=fn end}; rawset(t,key,value); return value
          end}),
          Osiris={RegisterListener=function(name,_,_,fn) listeners[name]=fn end}, RegisterConsoleCommand=function() end
        }
        Osi = {
          GetHostCharacter=function() return host end,
          DB_PartyMembers={Get=function() return {{host},{friend}} end},
          GetDisplayName=function(id) return id end,ResolveTranslatedString=function(id) return id end,
          IsDead=function() return 0 end,IsInCombat=function() return 0 end,
          IsEnemy=function() return 0 end,IsInForceTurnBasedMode=function() return 0 end,
          HasNoFollowFlag=function() return noFollow end,SetNoFollowFlag=function(_,value) noFollow=value end,
          FindValidPosition=function(x,y,z) return x,y,z end,IsInDangerousSurfaceFor=function() return 0 end,
          CharacterMoveToPosition=function() moved=moved+1 end,FlushOsirisQueue=function() flushed=flushed+1 end
        }
        files["BG3Friend/control.json"] = control
    ''')
    lua.execute(SOURCE.read_text(encoding="utf-8"))
    lua.execute('''events.SessionLoaded(); events.Tick(); state=saved["BG3Friend/snapshot.json"]; control.session=state.session
      files["BG3Friend/runner.json"]={session=state.session,updated=1000,runner="ready"}
    ''')
    return lua


def submit(lua, patch=""):
    lua.execute('''
      command={id="cmd1",protocol=1,session=state.session,actor=friend,control_revision=1,
          observed_seq=state.seq,action="follow",target=""}
    ''' + patch + '''
      files["BG3Friend/command.json"]=command;clock=clock+800;events.Tick()
    ''')


def test_dispatch_is_not_completion_and_duplicates_do_not_move_twice(bridge):
    submit(bridge)
    g = bridge.globals()
    assert g.moved == 1
    assert g.saved["BG3Friend/snapshot.json"]["result"]["status"] == "dispatched"
    bridge.execute('clock=clock+800;events.Tick()')
    assert g.moved == 1
    bridge.execute('entities[friend].Transform.Transform.Translate={0,0,0};clock=clock+800;events.Tick()')
    assert g.saved["BG3Friend/snapshot.json"]["result"]["status"] == "completed"


@pytest.mark.parametrize("patch", [
    'command.session="old";', 'command.actor=host;', 'command.observed_seq=-100;',
    'command.control_revision=2;', 'command.action="attack";',
    'Osi.GetHostCharacter=function() return friend end;', 'control.enabled=false;',
    'Osi.IsInCombat=function() return 1 end;',
    'command.action="approach";command.target="unseen";',
])
def test_game_rejects_invalid_command(bridge, patch):
    submit(bridge, patch)
    assert bridge.globals().moved == 0
    assert bridge.globals().saved["BG3Friend/snapshot.json"]["result"]["status"] == "rejected"


def test_pause_cancels_an_existing_move(bridge):
    submit(bridge)
    assert bridge.globals().noFollow == 1
    bridge.execute('control.enabled=false;clock=clock+800;events.Tick()')
    assert bridge.globals().flushed == 1
    assert bridge.globals().noFollow == 0
    assert bridge.globals().saved["BG3Friend/snapshot.json"]["result"]["status"] == "cancelled"


def test_runner_crash_releases_companion_and_stops_move(bridge):
    submit(bridge)
    bridge.execute('clock=clock+5000;events.Tick()')
    assert bridge.globals().noFollow == 0
    assert bridge.globals().flushed == 1
    assert bridge.globals().saved["BG3Friend/snapshot.json"]["result"]["status"] == "cancelled"


def test_reload_restores_flag_saved_with_ownership(bridge):
    submit(bridge)
    bridge.execute('events.SessionLoaded()')
    assert bridge.globals().noFollow == 0
    assert bridge.globals().vars.OwnedFollowFlag is None


def test_preexisting_no_follow_flag_is_preserved(bridge):
    bridge.execute('noFollow=1')
    submit(bridge)
    bridge.execute('control.enabled=false;clock=clock+800;events.Tick()')
    assert bridge.globals().noFollow == 1


def test_camp_routines_keep_movement_control(bridge):
    submit(bridge, 'Osi.DB_PlayerInCamp={Get=function() return {{host}} end};')
    assert bridge.globals().moved == 0
    assert bridge.globals().saved["BG3Friend/snapshot.json"]["blocked"] == "camp"


def combat(bridge):
    bridge.execute('''
      statuses={}; applied={}; removed={}
      Osi.IsInCombat=function() return 1 end
      Osi.HasActiveStatus=function(actor,status) return statuses[actor] and 1 or 0 end
      Osi.ApplyStatus=function(actor,status) statuses[actor]=true;applied[#applied+1]=actor end
      Osi.RemoveStatus=function(actor,status) statuses[actor]=nil;removed[#removed+1]=actor end
      clock=clock+800;events.Tick()
    ''')


def test_combat_owns_only_assigned_companion_and_leaves_host_alone(bridge):
    combat(bridge)
    g = bridge.globals()
    assert len(g.applied) == 1 and g.applied[1] == g.friend
    assert not g.statuses[g.host]
    assert g.saved['BG3Friend/snapshot.json']['combat']['controller'] == 'game_ai'


@pytest.mark.parametrize('change', [
    'control.enabled=false;', 'control.auto_combat=false;', 'control.session="old";',
    'Osi.IsInCombat=function() return 0 end;', 'clock=clock+5000;',
    'control.companion=host;', 'Osi.IsDead=function() return 1 end;',
])
def test_combat_returns_control_on_pause_exit_disconnect_or_invalid_actor(bridge, change):
    combat(bridge)
    bridge.execute(change + 'clock=clock+800;events.Tick()')
    assert not bridge.globals().statuses[bridge.globals().friend]
    assert bridge.globals().vars.OwnedCombat is None


def test_saved_combat_ownership_is_cleaned_up_on_reload(bridge):
    combat(bridge)
    bridge.execute('events.SessionLoaded()')
    assert not bridge.globals().statuses[bridge.globals().friend]
    assert bridge.globals().vars.OwnedCombat is None


def test_delayed_engine_status_application_does_not_churn_control(bridge):
    bridge.execute('''
      statuses={}; applied=0; removed=0
      Osi.IsInCombat=function() return 1 end
      Osi.HasActiveStatus=function(actor) return statuses[actor] and 1 or 0 end
      Osi.ApplyStatus=function(actor) applied=applied+1;queued=actor end
      Osi.RemoveStatus=function(actor) removed=removed+1;statuses[actor]=nil end
      clock=clock+800;events.Tick()
    ''')
    assert bridge.globals().applied == 1
    bridge.execute('statuses[queued]=true; clock=clock+800;events.Tick()')
    assert bridge.globals().removed == 0
    assert bridge.globals().saved['BG3Friend/snapshot.json']['combat']['controller'] == 'game_ai'
    bridge.execute('control.enabled=false;clock=clock+800;events.Tick()')
    assert bridge.globals().removed == 1


def delayed_combat(bridge):
    bridge.execute('''
      statuses={}; applied=0; removed=0
      Osi.IsInCombat=function() return 1 end
      Osi.HasActiveStatus=function(actor) return statuses[actor] and 1 or 0 end
      Osi.ApplyStatus=function(actor) applied=applied+1;queued=actor end
      Osi.RemoveStatus=function(actor) removed=removed+1;statuses[actor]=nil end
      clock=clock+800;events.Tick()
    ''')


@pytest.mark.parametrize('change', [
    'control.enabled=false;', 'control.auto_combat=false;',
    'listeners.DialogStarted("cutscene",77);', 'clock=clock+5000;',
    'events.SessionLoaded();',
])
def test_late_status_application_after_return_is_still_removed(bridge, change):
    delayed_combat(bridge)
    bridge.execute(change + 'clock=clock+800;events.Tick()')
    g = bridge.globals()
    assert g.vars.OwnedCombat.releasing[g.friend].awaiting_apply
    assert not g.statuses[g.friend]
    bridge.execute('statuses[queued]=true;clock=clock+800;events.Tick()')
    assert not g.statuses[g.friend]
    assert g.vars.OwnedCombat is None
    assert g.removed == 1


def test_unobserved_acquisition_never_queues_duplicate_statuses(bridge):
    delayed_combat(bridge)
    bridge.execute('''
      for i=1,8 do
        clock=clock+800;files["BG3Friend/runner.json"].updated=clock;events.Tick()
      end
    ''')
    assert bridge.globals().applied == 1
    bridge.execute('statuses[queued]=true;clock=clock+800;events.Tick()')
    assert bridge.globals().saved['BG3Friend/snapshot.json']['combat']['controller'] == 'game_ai'


def test_missing_companion_return_survives_lua_reload_and_entity_restoration(bridge):
    combat(bridge)
    bridge.execute('''
      savedEntity=entities[friend];entities[friend]=nil
      control.enabled=false;clock=clock+800;events.Tick()
    ''')
    assert bridge.globals().vars.OwnedCombat.releasing[bridge.globals().friend]
    # Recreate the script's local state while preserving only the fake save variables.
    bridge.execute(SOURCE.read_text(encoding="utf-8"))
    bridge.execute('events.SessionLoaded();clock=clock+800;events.Tick()')
    assert bridge.globals().vars.OwnedCombat.releasing[bridge.globals().friend]
    bridge.execute('entities[friend]=savedEntity;clock=clock+800;events.Tick()')
    g = bridge.globals()
    assert not g.statuses[g.friend]
    assert g.vars.OwnedCombat is None
    assert list(g.removed.values()) == [g.friend]


def test_unobserved_application_cancellation_survives_lua_reload(bridge):
    delayed_combat(bridge)
    bridge.execute('control.enabled=false;clock=clock+800;events.Tick()')
    bridge.execute(SOURCE.read_text(encoding="utf-8"))
    bridge.execute('events.SessionLoaded();statuses[queued]=true;clock=clock+800;events.Tick()')
    g = bridge.globals()
    assert not g.statuses[g.friend]
    assert g.vars.OwnedCombat is None
    assert g.removed == 1


@pytest.mark.parametrize('mode', ['raises', 'delayed'])
def test_removal_is_retried_until_the_engine_reports_absence(bridge, mode):
    combat(bridge)
    bridge.execute('''
      attempts=0
      Osi.RemoveStatus=function(actor)
        attempts=attempts+1
    ''' + ('error("engine not ready")' if mode == 'raises' else 'removing=actor') + '''
      end
      control.enabled=false;clock=clock+800;events.Tick()
    ''')
    g = bridge.globals()
    assert g.statuses[g.friend]
    assert g.vars.OwnedCombat.releasing[g.friend]
    assert g.saved['BG3Friend/snapshot.json']['combat']['controller'] == 'releasing'
    bridge.execute('''
      Osi.RemoveStatus=function(actor) attempts=attempts+1;statuses[actor]=nil end
      clock=clock+800;events.Tick()
    ''')
    assert not g.statuses[g.friend]
    assert g.vars.OwnedCombat is None
    assert g.attempts >= 2


@pytest.mark.parametrize('kind', ['combat', 'follow'])
def test_missing_host_snapshot_cannot_prevent_lease_cleanup(bridge, kind):
    if kind == 'combat':
        combat(bridge)
    else:
        submit(bridge)
    bridge.execute('entities[host]=nil;clock=clock+5000;events.Tick()')
    g = bridge.globals()
    if kind == 'combat':
        assert not g.statuses[g.friend]
        assert g.vars.OwnedCombat is None
    else:
        assert g.noFollow == 0
        assert g.vars.OwnedFollowFlag is None
        assert g.flushed == 1


def test_follow_return_retries_after_missing_entity_and_lua_reload(bridge):
    submit(bridge)
    bridge.execute('''
      savedEntity=entities[friend];entities[friend]=nil
      control.enabled=false;clock=clock+800;events.Tick()
    ''')
    assert bridge.globals().vars.OwnedFollowFlag.releasing[bridge.globals().friend]
    bridge.execute(SOURCE.read_text(encoding="utf-8"))
    bridge.execute('events.SessionLoaded();entities[friend]=savedEntity;clock=clock+800;events.Tick()')
    assert bridge.globals().noFollow == 0
    assert bridge.globals().vars.OwnedFollowFlag is None


def test_reassignment_preserves_cleanup_for_the_unavailable_old_actor(bridge):
    combat(bridge)
    bridge.execute('''
      other="33333333-3333-3333-3333-333333333333"
      entities[other]=entity(other,4)
      Osi.DB_PartyMembers.Get=function() return {{host},{friend},{other}} end
      savedEntity=entities[friend];entities[friend]=nil;control.companion=other
      clock=clock+800;events.Tick()
    ''')
    g = bridge.globals()
    assert g.statuses[g.other]
    assert g.vars.OwnedCombat.actor == g.other
    assert g.vars.OwnedCombat.releasing[g.friend]
    bridge.execute('entities[friend]=savedEntity;clock=clock+800;events.Tick()')
    assert not g.statuses[g.friend]
    assert g.statuses[g.other]
    assert g.vars.OwnedCombat.actor == g.other
    assert not g.vars.OwnedCombat.releasing[g.friend]


def test_unowned_combat_status_and_human_control_are_never_removed(bridge):
    bridge.execute('''
      statuses={[friend]=true,[host]=true};removed={};applied=0
      Osi.IsInCombat=function() return 1 end
      Osi.HasActiveStatus=function(actor) return statuses[actor] and 1 or 0 end
      Osi.ApplyStatus=function() applied=applied+1 end
      Osi.RemoveStatus=function(actor) removed[#removed+1]=actor;statuses[actor]=nil end
      clock=clock+800;events.Tick()
      control.enabled=false;clock=clock+800;events.Tick()
      events.SessionLoaded();clock=clock+800;events.Tick()
    ''')
    g = bridge.globals()
    assert g.statuses[g.friend] and g.statuses[g.host]
    assert len(g.removed) == 0 and g.applied == 0
    assert g.vars.OwnedCombat is None


def test_automatic_combat_focus_cannot_change_human_identity(bridge):
    bridge.execute('''
      Osi.DB_Avatars={Get=function() return {{host}} end}
      Osi.GetHostCharacter=function() return friend end
      Osi.GetReservedUserID=function() return 1 end
    ''')
    combat(bridge)
    s = bridge.globals().saved['BG3Friend/snapshot.json']
    assert s['player']['id'] == bridge.globals().host
    assert s['companion']['id'] == bridge.globals().friend
    assert s['combat']['controller'] == 'game_ai'


def test_reload_with_companion_focused_resolves_the_actual_avatar(bridge):
    bridge.execute('''
      Osi.DB_Avatars={Get=function() return {{host}} end}
      Osi.GetHostCharacter=function() return friend end
      Osi.GetReservedUserID=function() return 1 end
      events.SessionLoaded();clock=clock+800;events.Tick()
    ''')
    s = bridge.globals().saved['BG3Friend/snapshot.json']
    assert s['player']['id'] == bridge.globals().host
    assert s['companion']['id'] == bridge.globals().friend


def meet_newcomer(bridge):
    bridge.execute('''
      newcomer="33333333-3333-3333-3333-333333333333"
      entities[newcomer]=entity(newcomer,5)
      Osi.DB_Origins={Get=function() return {{friend},{newcomer}} end}
      Osi.DB_Avatars={Get=function() return {{host}} end}
      events.SessionLoaded();clock=clock+2000;events.Tick()
      state=saved["BG3Friend/snapshot.json"];control.session=state.session
    ''')
    assert not bridge.globals().vars.Introductions.met[bridge.globals().newcomer]
    bridge.execute('''
      listeners.DialogStarted("dialog",41)
      listeners.DialogActorJoined("dialog",41,newcomer,1)
      listeners.DialogActorJoined("dialog",41,host,2)
      clock=clock+2000;events.Tick()
    ''')


def choose_newcomer(bridge, patch=''):
    bridge.execute('''
      request={id="choice1",session=state.session,actor=newcomer,choice="friend",activate=true,control_revision=control.revision}
    ''' + patch + '''
      files["BG3Friend/connection-request.json"]=request
      clock=clock+800;events.Tick()
    ''')


def test_first_meeting_waits_for_actual_party_dialogue_and_its_end(bridge):
    meet_newcomer(bridge)
    g = bridge.globals()
    assert g.vars.Introductions.met[g.newcomer]
    assert not g.saved['BG3Friend/snapshot.json']['introductions']['ready']
    bridge.execute('listeners.DialogEnded("dialog",41);clock=clock+800;events.Tick()')
    assert not g.saved['BG3Friend/snapshot.json']['introductions']['ready']
    bridge.execute('clock=clock+800;events.Tick()')
    intro = g.saved['BG3Friend/snapshot.json']['introductions']
    assert intro['ready']
    assert any(c['id'] == g.newcomer and not c['in_party'] for _, c in intro['candidates'].items())


def test_remote_npc_dialogue_does_not_reveal_origin_companions(bridge):
    meet_newcomer(bridge)
    bridge.execute('''
      vars.Introductions=nil;events.SessionLoaded();clock=clock+2000;events.Tick()
      listeners.DialogActorJoined("remote",91,newcomer,1)
      listeners.DialogEnded("remote",91)
      clock=clock+2000;events.Tick()
    ''')
    assert not bridge.globals().vars.Introductions.met[bridge.globals().newcomer]


def test_story_origin_database_may_be_empty_until_after_session_loaded(bridge):
    bridge.execute('''
      newcomer="33333333-3333-3333-3333-333333333333"
      entities[newcomer]=entity(newcomer,5)
      Osi.DB_Origins={Get=function() return {} end}
      events.SessionLoaded();clock=clock+2000;events.Tick()
      Osi.DB_Origins.Get=function() return {{newcomer}} end
      listeners.DialogStarted("beach",51)
      listeners.DialogActorJoined("beach",51,host,1)
      listeners.DialogActorJoined("beach",51,newcomer,2)
      listeners.DialogEnded("beach",51)
      clock=clock+2000;events.Tick()
    ''')
    g = bridge.globals()
    assert g.vars.Introductions.met[g.newcomer]
    intro = g.saved['BG3Friend/snapshot.json']['introductions']
    assert intro['ready']
    assert any(c['id'] == g.newcomer and not c['in_party'] for _, c in intro['candidates'].items())


@pytest.mark.parametrize('patch', [
    'request.session="old";', 'request.control_revision=99;', 'request.actor=host;',
    'request.actor="unmet";', 'request.choice="execute";',
])
def test_stale_or_invalid_connection_choice_cannot_change_preferences(bridge, patch):
    meet_newcomer(bridge)
    choose_newcomer(bridge, patch)
    g = bridge.globals()
    assert not g.vars.Introductions.choices[g.newcomer]
    assert g.saved['BG3Friend/snapshot.json']['introductions']['result']['status'] == 'rejected'


def test_pre_party_acceptance_records_intent_without_taking_npc_control(bridge):
    meet_newcomer(bridge)
    choose_newcomer(bridge)
    g = bridge.globals()
    assert g.vars.Introductions.choices[g.newcomer] == 'friend'
    assert g.control.companion == g.friend
    assert g.saved['BG3Friend/snapshot.json']['introductions']['deferred']['actor'] == g.newcomer
    bridge.execute('control.enabled=false;control.revision=control.revision+1;clock=clock+800;events.Tick()')
    assert not g.saved['BG3Friend/snapshot.json']['introductions']['deferred']


def test_saved_choice_survives_session_reload_without_auto_resuming(bridge):
    meet_newcomer(bridge)
    choose_newcomer(bridge, 'request.choice="manual";')
    bridge.execute('events.SessionLoaded();clock=clock+2000;events.Tick()')
    g = bridge.globals()
    intro = g.saved['BG3Friend/snapshot.json']['introductions']
    assert intro['choices'][g.newcomer] == 'manual'
    assert not intro['deferred']


def test_party_join_is_detected_without_a_dialogue_and_combat_defers_card(bridge):
    bridge.execute('''
      newcomer="33333333-3333-3333-3333-333333333333"
      entities[newcomer]=entity(newcomer,5)
      Osi.DB_PartyMembers.Get=function() return {{host},{friend},{newcomer}} end
      Osi.IsInCombat=function(actor) return actor==newcomer and 1 or 0 end
      clock=clock+2000;events.Tick()
    ''')
    g = bridge.globals()
    assert g.vars.Introductions.met[g.newcomer]
    assert not g.saved['BG3Friend/snapshot.json']['introductions']['ready']
