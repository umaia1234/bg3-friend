-- Grounded exploration and leased, friendly engine AI for the assigned companion.
local B = {session = "", seq = 0, active = nil, result = nil, lastCommand = "", dialogs = {}, tick = 0, events = {}, dialogActors = {}}
local MOD_UUID = "cfd9c54e-3884-47ed-9b40-82b8747194de"
local COMBAT_STATUS = "BG3FRIEND_AUTOCOMBAT"
Ext.Vars.RegisterModVariable(MOD_UUID, "OwnedFollowFlag", {Server=true, Client=false, Persistent=true})
Ext.Vars.RegisterModVariable(MOD_UUID, "OwnedCombat", {Server=true, Client=false, Persistent=true})
Ext.Vars.RegisterModVariable(MOD_UUID, "Introductions", {Server=true, Client=false, Persistent=true})
local PREFIX = "BG3Friend/"
local function now() return Ext.Timer.MonotonicTime() end
local function read(name)
    local raw = Ext.IO.LoadFile(PREFIX .. name)
    if not raw then return nil end
    local ok, result = pcall(Ext.Json.Parse, raw)
    if ok and type(result) == "table" then return result end
end
local function write(name, value) Ext.IO.SaveFile(PREFIX .. name, Ext.Json.Stringify(value)) end
local function query(name, ...)
    local ok, a, b, c = pcall(function(...) return Osi[name](...) end, ...)
    if ok then return a, b, c end
    return nil
end
local function id(entity)
    if entity and entity.Uuid then return tostring(entity.Uuid.EntityUuid) end
end
local function canonical(value)
    if not value then return nil end
    return tostring(value):match("([%x]+%-%x+%-%x+%-%x+%-%x+)$") or tostring(value)
end
local function remember_meeting(actor)
    if not B.intro or not actor or (B.avatars or {})[actor] then return end
    if not B.intro.met[actor] then
        B.intro.met[actor] = true
        Ext.Vars.GetModVariables(MOD_UUID).Introductions = B.intro
    end
end
local function dialog_meetings(instance)
    local actors = B.dialogActors[instance] or {}
    local withParty = false
    for actor in pairs(actors) do
        if (B.partyIds or {})[actor] or actor == B.host then withParty = true end
    end
    if withParty then
        -- Story databases can still be empty at SessionLoaded; resolve them at the meeting.
        local ok, rows = pcall(function() return Osi.DB_Origins:Get(nil) end)
        if ok then for _,row in ipairs(rows) do B.origins[canonical(row[1])]=true end end
        for actor in pairs(actors) do
            if (B.origins or {})[actor] then remember_meeting(actor) end
        end
    end
end
local function position(entity)
    if entity and entity.Transform then
        local p = entity.Transform.Transform.Translate
        return {p[1], p[2], p[3]}
    end
end
local function distance(a, b)
    if not a or not b then return math.huge end
    return math.sqrt((a[1]-b[1])^2 + (a[2]-b[2])^2 + (a[3]-b[3])^2)
end
local function describe(entity, host, focused)
    local uuid = id(entity)
    local p = position(entity)
    if not uuid or not p then return nil end
    local name = query("GetDisplayName", uuid)
    if name then name = query("ResolveTranslatedString", name) end
    return {
        id = uuid, name = name or "이름 미확인", position = p,
        hp = entity.Health and entity.Health.Hp or 0,
        max_hp = entity.Health and entity.Health.MaxHp or 0,
        dead = query("IsDead", uuid) == 1,
        in_combat = query("IsInCombat", uuid) == 1,
        selected = uuid == focused,
        hostile = host and query("IsEnemy", uuid, host) == 1 or false,
        kind = entity.ServerCharacter and "character" or "object"
    }
end
local function finish(status, detail)
    if B.active then
        B.result = {id = B.active.id, status = status, detail = detail, actor = B.active.actor}
        B.active = nil
    end
end
local function cancel(detail)
    if B.active then
        query("PurgeOsirisQueue", B.active.actor, 1)
        query("FlushOsirisQueue", B.active.actor)
        finish("cancelled", detail)
    end
end
local function ownership(name)
    local vars = Ext.Vars.GetModVariables(MOD_UUID)
    local owned = vars[name] or {}
    owned.releasing = owned.releasing or {}
    return vars, owned
end
local function save_ownership(vars, name, owned)
    -- Reassign the table so pending restoration is also persisted in a save.
    vars[name] = (owned.actor or next(owned.releasing)) and owned or nil
end
local function restore_follow()
    local vars, owned = ownership("OwnedFollowFlag")
    for actor in pairs(owned.releasing) do
        if Ext.Entity.Get(actor) then
            local flag = query("HasNoFollowFlag", actor)
            if flag == 1 then
                query("SetNoFollowFlag", actor, 0)
                flag = query("HasNoFollowFlag", actor)
            end
            if flag == 0 then owned.releasing[actor] = nil end
        end
    end
    save_ownership(vars, "OwnedFollowFlag", owned)
end
local function release()
    local vars, owned = ownership("OwnedFollowFlag")
    if owned.actor then
        owned.releasing[owned.actor] = true
        owned.actor = nil
    end
    save_ownership(vars, "OwnedFollowFlag", owned)
    B.held = nil
    restore_follow()
end
local function restore_combat()
    local vars, owned = ownership("OwnedCombat")
    for actor, pending in pairs(owned.releasing) do
        if Ext.Entity.Get(actor) then
            local active = query("HasActiveStatus", actor, COMBAT_STATUS)
            if active == 1 then
                pending.awaiting_apply = false
                query("RemoveStatus", actor, COMBAT_STATUS)
                active = query("HasActiveStatus", actor, COMBAT_STATUS)
            end
            -- An absent status does not acknowledge a queued ApplyStatus. Retain the
            -- cancellation until its application is observed, including across reloads.
            if active == 0 and not pending.awaiting_apply then owned.releasing[actor] = nil end
        end
    end
    save_ownership(vars, "OwnedCombat", owned)
end
local function release_combat()
    local vars, owned = ownership("OwnedCombat")
    if owned.actor then
        owned.releasing[owned.actor] = {awaiting_apply=owned.awaiting_apply ~= false}
        owned.actor = nil; owned.awaiting_apply = nil
    end
    save_ownership(vars, "OwnedCombat", owned)
    B.fighting = nil; B.combatActor = nil
    restore_combat()
end
local function sync_combat(state, control)
    -- Automatic turn focus is not a request to take control. Manual takeover is the chat menu.
    -- Never convert a party member into an NPC or change its faction/resources.
    local take = state.runner_connected and control.enabled and control.session == B.session
        and control.auto_combat ~= false and state.companion and state.companion.in_combat
        and not state.companion.dead and not next(B.dialogs)
    local actor = take and state.companion.id or nil
    if actor ~= B.combatActor then release_combat() end
    B.combatActor = actor
    local vars, owned = ownership("OwnedCombat")
    -- A new request for the same actor may adopt our still-pending acquisition.
    if actor and owned.releasing[actor] then
        owned.actor = actor; owned.awaiting_apply = owned.releasing[actor].awaiting_apply
        owned.releasing[actor] = nil
    end
    local active = actor and query("HasActiveStatus", actor, COMBAT_STATUS) or nil
    if actor and active == 0 and not owned.awaiting_apply then
        -- Never queue another application while the preceding one is unobserved.
        -- Multiple delayed applications could otherwise outlive a confirmed removal.
        owned.actor = actor; owned.awaiting_apply = true
        save_ownership(vars, "OwnedCombat", owned)
        local ok = pcall(Osi.ApplyStatus, actor, COMBAT_STATUS, -1.0, 1, actor)
        if not ok then owned.awaiting_apply = false end
        active = query("HasActiveStatus", actor, COMBAT_STATUS)
    end
    if actor and owned.actor == actor and active == 1 then owned.awaiting_apply = false end
    save_ownership(vars, "OwnedCombat", owned)
    B.fighting = actor and owned.actor == actor and active == 1 and actor or nil
    local returning = state.companion and owned.releasing[state.companion.id]
    state.combat = {active=state.companion and state.companion.in_combat or false,
        controller=B.fighting and "game_ai" or (returning and "releasing" or "player"), actor=B.fighting,
        events=B.events}
end
local function sync_control(state, control)
    local runner = read("runner.json") or {}
    if runner.session == B.session and runner.updated ~= B.beat and runner.runner ~= "stopped" then
        B.beat = runner.updated; B.beatAt = now()
    end
    state.runner_connected = B.beatAt ~= nil and now()-B.beatAt < 4000
    local take = state.runner_connected and control.enabled and control.session == B.session
        and state.companion and not state.companion.selected and not state.blocked
    local actor = take and state.companion.id or nil
    if actor ~= B.held then
        cancel("플레이어 제어 또는 연결 변경으로 이동을 멈췄어.")
        release()
        if actor then
            local old = query("HasNoFollowFlag", actor)
            local vars, owned = ownership("OwnedFollowFlag")
            if old == 0 or (old == 1 and owned.releasing[actor]) then
                owned.actor = actor; owned.releasing[actor] = nil
                save_ownership(vars, "OwnedFollowFlag", owned)
                if old == 0 then query("SetNoFollowFlag", actor, 1) end
            end
            if query("HasNoFollowFlag", actor) == 1 then B.held = actor end
        end
    end
    state.independent = B.held ~= nil
    sync_combat(state, control)
end
local function snapshot()
    local focused = canonical(query("GetHostCharacter"))
    local avatars = {}
    local avatarOk, avatarRows = pcall(function() return Osi.DB_Avatars:Get(nil) end)
    if avatarOk then for _, row in ipairs(avatarRows) do avatars[canonical(row[1])] = true end end
    B.avatars = avatars
    -- GetHostCharacter follows automatic combat/camera selection. Keep the human avatar stable.
    if not B.host then
        if avatars[focused] then B.host = focused
        elseif focused then
            local user = query("GetReservedUserID", focused)
            for avatar in pairs(avatars) do
                if user and query("GetReservedUserID", avatar) == user then B.host = avatar; break end
            end
            if not B.host and not next(avatars) then B.host = focused end
        end
    end
    local host = B.host
    if not host or host == "00000000-0000-0000-0000-000000000000" then return nil end
    local player = describe(Ext.Entity.Get(host), host, focused)
    if not player then return nil end
    local party, partyIds = {}, {}
    local ok, rows = pcall(function() return Osi.DB_PartyMembers:Get(nil) end)
    if ok then
        for _, row in ipairs(rows) do
            local uuid = canonical(row[1])
            local member = describe(Ext.Entity.Get(uuid), host, focused)
            if member then party[#party+1] = member; partyIds[uuid] = true end
        end
    end
    B.partyIds = partyIds
    for uuid in pairs(partyIds) do if uuid ~= host then remember_meeting(uuid) end end
    local control = read("control.json") or {}
    local actor = canonical(control.companion)
    local companion = nil
    if actor and actor ~= host and not avatars[actor] and partyIds[actor] then companion = describe(Ext.Entity.Get(actor), host, focused) end
    local blocked = nil
    local campOk, campRows = pcall(function() return Osi.DB_PlayerInCamp:Get(host) end)
    if campOk and #campRows > 0 then blocked = "camp" end
    if next(B.dialogs) then blocked = "dialogue" end
    if query("IsInForceTurnBasedMode", host) == 1 then blocked = "turn_based" end
    if player.in_combat or (companion and companion.in_combat) then blocked = "combat" end
    if companion and companion.dead then blocked = "dead" end
    local nearby = {}
    local origin = companion and companion.position or player.position
    local radius = blocked == "combat" and 30.0 or 12.0
    local aroundOk, entities = pcall(Ext.Entity.GetEntitiesAroundPosition, origin, radius)
    if aroundOk then
        for _, entity in pairs(entities) do
            local uuid = id(entity)
            if uuid and not partyIds[uuid] and uuid ~= host then
                local item = describe(entity, host, focused)
                if item and item.name ~= "이름 미확인" and distance(origin, item.position) <= radius then
                    if query("CanSee", actor or host, uuid) == 1 then nearby[#nearby+1] = item end
                end
            end
        end
    end
    table.sort(nearby, function(a,b) return distance(origin,a.position) < distance(origin,b.position) end)
    while #nearby > 20 do table.remove(nearby) end
    return {protocol = 1, session = B.session, seq = B.seq, time_ms = now(),
        player = player, avatars = avatars, party = party, companion = companion, nearby = nearby,
        blocked = blocked, active = B.active, result = B.result,
        capabilities = {"wait", "follow", "approach", "look"}, control_revision = control.revision or 0}, control
end
local function introductions(state, control)
    local request = read("connection-request.json")
    if request and type(request.id) == "string" and #request.id <= 80 and request.id ~= B.lastConnection then
        B.lastConnection = request.id
        local actor = canonical(request.actor)
        local valid = request.session == B.session and request.control_revision == (control.revision or 0)
            and actor and B.intro.met[actor] and not state.avatars[actor] and Ext.Entity.Get(actor)
            and (request.choice == "friend" or request.choice == "manual")
        B.connectionResult = {id=request.id, status=valid and "stored" or "rejected"}
        if valid then
            B.intro.choices[actor] = request.choice
            Ext.Vars.GetModVariables(MOD_UUID).Introductions = B.intro
            B.deferred = request.choice == "friend" and request.activate == true
                and {actor=actor, revision=control.revision or 0, session=B.session} or nil
        end
    end
    -- A pause, manual assignment or reload supersedes a pending invitation.
    if B.deferred and (B.deferred.session ~= B.session or B.deferred.revision ~= (control.revision or 0)) then B.deferred=nil end
    local ready = not next(B.dialogs) and now() >= (B.dialogQuietAt or 0)
        and state.blocked ~= "combat" and state.blocked ~= "dialogue" and state.blocked ~= "turn_based"
    for _, member in ipairs(state.party) do if member.in_combat then ready=false end end
    local candidates = {}
    for actor in pairs(B.intro.met) do
        if not state.avatars[actor] and actor ~= state.player.id then
            local item = describe(Ext.Entity.Get(actor), state.player.id, nil)
            if item and not item.dead and not item.hostile then
                candidates[#candidates+1] = {id=actor,name=item.name,in_party=B.partyIds[actor] == true}
            end
        end
    end
    table.sort(candidates,function(a,b) return a.id < b.id end)
    state.introductions = {ready=ready,candidates=candidates,choices=B.intro.choices,
        deferred=B.deferred,result=B.connectionResult}
end
local function execute(command, state, control)
    if type(command.id) ~= "string" or command.id == B.lastCommand then return end
    B.lastCommand = command.id
    local function reject(reason) B.result = {id=command.id, status="rejected", detail=reason} end
    if command.protocol ~= 1 or command.session ~= B.session then return reject("세션이 바뀌었어.") end
    if not control.enabled or control.session ~= B.session or command.control_revision ~= control.revision then
        return reject("동료 제어가 변경되었어.")
    end
    if not state.runner_connected then return reject("연결 프로그램이 멈췄어.") end
    if not state.companion or command.actor ~= state.companion.id then return reject("지정 동료가 아니야.") end
    if type(command.observed_seq) ~= "number" or state.seq-command.observed_seq > 5 or command.observed_seq > state.seq then
        return reject("오래된 관찰에 따른 명령이야.")
    end
    if B.active then return reject("이전 행동이 진행 중이야.") end
    if command.action == "wait" or command.action == "look" then
        if command.action == "look" then
            local found = false
            for _, target in ipairs(state.nearby) do if target.id == command.target then found = true end end
            if not found then return reject("지금 볼 수 없는 대상이야.") end
        end
        B.result = {id=command.id, status="completed", detail=command.action == "look" and "현재 보이는 주변을 살폈어." or "기다리고 있어."}
        return
    end
    if command.action ~= "follow" and command.action ~= "approach" then return reject("지원하지 않는 행동이야.") end
    if state.blocked or state.companion.selected or not state.independent then return reject("지금은 자율 이동할 수 없어.") end
    local target = state.player
    if command.action == "approach" then
        target = nil
        for _, item in ipairs(state.nearby) do if item.id == command.target then target = item end end
        if not target or target.hostile or target.dead then return reject("접근할 수 없는 대상이야.") end
        if distance(state.companion.position, target.position) > 12 then return reject("탐험 범위를 벗어났어.") end
    end
    if distance(state.companion.position, target.position) < 2 then
        B.result = {id=command.id,status="completed",detail="이미 대상 근처에 있어."}; return
    end
    local p = target.position
    local x,y,z = query("FindValidPosition", p[1], p[2], p[3], 2.0, command.actor, 1)
    if not x or not y or not z then return reject("걸어갈 위치를 찾지 못했어.") end
    if query("IsInDangerousSurfaceFor", x,y,z,command.actor,-1.0,0) ~= 0 then return reject("안전한 도착 지점을 확인하지 못했어.") end
    local goal = {x,y,z}
    local pathOk, reachable = pcall(function()
        local path = Ext.Level.BeginPathfindingImmediate(Ext.Entity.Get(command.actor), goal)
        local found = Ext.Level.FindPath(path)
        Ext.Level.ReleasePath(path)
        return found
    end)
    if not pathOk or not reachable then return reject("그쪽으로 가는 길을 찾지 못했어.") end
    B.active = {id=command.id,actor=command.actor,position=goal,started=now(),revision=control.revision}
    local ok, err = pcall(Osi.CharacterMoveToPosition, command.actor, x,y,z,"Run","BG3Friend_"..command.id)
    if not ok then return finish("failed", tostring(err)) end
    B.result = {id=command.id,status="dispatched",detail="이동을 시작했어. 도착 여부를 확인 중이야."}
end
local function tick()
    if now()-B.tick < 750 then return end
    B.tick = now()
    -- Cleanup cannot depend on a readable host/party snapshot or a live session.
    restore_follow(); restore_combat()
    if B.session == "" then return end
    B.seq = B.seq+1
    local state, control = snapshot()
    if not state then
        cancel("게임 상태를 확인할 수 없어 이동을 멈췄어.")
        release(); release_combat()
        return
    end
    introductions(state,control)
    sync_control(state,control)
    if B.active then
        if not control.enabled or control.session ~= B.session or control.revision ~= B.active.revision or
           not state.companion or state.companion.id ~= B.active.actor or state.blocked or state.companion.selected then
            cancel("플레이어 제어 또는 상황 변경으로 이동을 멈췄어.")
        elseif distance(state.companion.position, B.active.position) < 1.5 then
            finish("completed", "목적지 근처에 도착했어.")
        elseif now()-B.active.started > 15000 then
            query("PurgeOsirisQueue", B.active.actor, 1)
            query("FlushOsirisQueue", B.active.actor); finish("failed", "시간 안에 도착하지 못했어.")
        end
    end
    local command = read("command.json")
    if command then execute(command,state,control) end
    state.result = B.result; state.active = B.active
    write("snapshot.json",state)
end
local function start()
    release(); release_combat()
    B.session = tostring(now()) .. "-" .. tostring(math.random(100000,999999))
    B.seq=0; B.active=nil; B.result=nil; B.lastCommand=""; B.dialogs={}; B.events={}; B.host=nil
    B.dialogActors={}; B.dialogQuietAt=now()+1500; B.partyIds={}; B.avatars={}; B.origins={}
    B.lastConnection=nil; B.connectionResult=nil; B.deferred=nil
    B.intro=Ext.Vars.GetModVariables(MOD_UUID).Introductions or {met={},choices={}}
    B.intro.met=B.intro.met or {}; B.intro.choices=B.intro.choices or {}
    B.beat=nil; B.beatAt=nil
    print("[BG3Friend] Session " .. B.session)
end
Ext.Events.SessionLoaded:Subscribe(start)
Ext.Events.ResetCompleted:Subscribe(function() if query("GetHostCharacter") then start() end end)
Ext.Events.Tick:Subscribe(function()
    local ok, err = pcall(tick)
    if not ok and tostring(err) ~= B.lastError then
        B.lastError=tostring(err); print("[BG3Friend] " .. B.lastError)
        write("error.json", {error=B.lastError})
    end
end)
Ext.Events.GameStateChanged:Subscribe(function(e)
    if tostring(e.ToState) == "UnloadLevel" or tostring(e.ToState) == "Disconnect" then
        cancel("게임 세션이 바뀌었어."); release(); release_combat(); B.session=""
    end
end)
Ext.Osiris.RegisterListener("DialogStarted",2,"after",function(_,instance) B.dialogs[instance]=true end)
Ext.Osiris.RegisterListener("DialogActorJoined",4,"after",function(_,instance,actor)
    B.dialogActors[instance]=B.dialogActors[instance] or {}
    B.dialogActors[instance][canonical(actor)]=true
    B.dialogQuietAt=now()+1500
    dialog_meetings(instance)
end)
Ext.Osiris.RegisterListener("DialogEnded",2,"after",function(_,instance)
    dialog_meetings(instance); B.dialogs[instance]=nil; B.dialogActors[instance]=nil; B.dialogQuietAt=now()+1500
end)
Ext.Osiris.RegisterListener("GainedControl",1,"after",function(actor)
    if canonical(actor) == B.held then cancel("플레이어가 동료를 직접 선택했어."); release() end
end)
local function combat_event(kind, actor, target, spell, amount)
    local control = read("control.json") or {}
    actor = canonical(actor); target = canonical(target)
    local friend = canonical(control.companion)
    if not friend or (actor ~= friend and target ~= friend) then return end
    B.events[#B.events+1] = {id=tostring(now()).."-"..tostring(#B.events+1), kind=kind,
        actor=actor, target=target, spell=spell, amount=amount, time_ms=now()}
    while #B.events > 24 do table.remove(B.events, 1) end
end
Ext.Osiris.RegisterListener("CastedSpell",5,"after",function(actor,spell)
    combat_event("spell_cast",actor,nil,spell)
end)
Ext.Osiris.RegisterListener("AttackedBy",7,"after",function(target,owner,actor,_,amount)
    combat_event("damage",actor or owner,target,nil,amount)
end)
Ext.Osiris.RegisterListener("TurnStarted",1,"after",function(actor) combat_event("turn_started",actor) end)
Ext.Osiris.RegisterListener("TurnEnded",1,"after",function(actor) combat_event("turn_ended",actor) end)
Ext.RegisterConsoleCommand("friend_probe", function()
    local state=snapshot(); write("probe.json",state or {error="No game state"})
end)
print("[BG3Friend] Server bridge loaded")
B.Start = start
BG3Friend = B
