"""Persistent shared plans and event-driven attention, independent of generated dialogue."""
from __future__ import annotations
import copy
from .protocol import distance


class Director:
    def __init__(self, saved=None):
        saved = saved or {}
        self.stance = saved.get("stance", "together")
        self.visited = saved.get("visited", [])[-12:]
        self.previous = None
        self.trigger = "joined"

    def saved(self):
        return {"stance": self.stance, "visited": self.visited[-12:]}

    def observe(self, scene):
        old = self.previous
        if old:
            if old.get("blocked") != scene.get("blocked"):
                self.trigger = "situation_changed"
            elif any(m.get("hp", 0) < next((p.get("hp", 0) for p in old.get("party", [])
                                          if p["id"] == m["id"]), m.get("hp", 0)) for m in scene.get("party", [])):
                self.trigger = "party_hurt"
            elif {n["id"] for n in scene.get("nearby", [])} - {n["id"] for n in old.get("nearby", [])}:
                self.trigger = "noticed_someone_or_something"
            elif distance(scene.get("player", {}).get("position", [0, 0, 0]),
                          old.get("player", {}).get("position", [0, 0, 0])) >= 5:
                self.trigger = "human_moved"
            else:
                return
        self.previous = copy.deepcopy(scene)

    def context(self, human_message=False):
        return self.saved() | {"trigger": "human_message" if human_message else self.trigger,
                               "human_message": human_message}

    def apply(self, decision, human_message):
        stance = decision["stance"]
        # A model's next idle thought must not undo a promise to wait.
        if self.stance == "hold" and not human_message:
            if decision["action"] in ("follow", "approach") or stance not in ("keep", "hold"):
                raise ValueError("Waiting agreement remains until the human changes it")
        if stance != "keep":
            self.stance = stance

    def completed(self, command):
        if command.get("action") in ("approach", "look") and command.get("target"):
            self.visited.append(command["target"])
            self.visited = self.visited[-12:]

    def regroup(self, scene):
        friend, player = scene.get("companion", {}), scene.get("player", {})
        return self.stance == "together" and not scene.get("blocked") and not friend.get("selected") \
            and bool(friend.get("position")) and bool(player.get("position")) \
            and distance(friend["position"], player["position"]) >= 7
