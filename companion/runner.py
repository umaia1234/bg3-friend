"""Observe -> decide off-thread -> revalidate -> dispatch -> remember outcome."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import time
import uuid

from .model import CodexModel, ReplayModel
from .director import Director
from .protocol import command_for, read_json, validate_decision, write_json


class Runner:
    def __init__(self, folder: Path, model, interval: float = 15, max_calls: int = 0):
        self.folder = folder
        self.model = model
        self.interval = interval
        self.max_calls = max_calls
        self.calls = 0
        self.session = None
        self.history: list[dict] = []
        self.memory: list[dict] = []
        self.last_ask = 0.0
        self.pending = None
        self.pending_context = None
        self.command_pending = None
        self.last_result = None
        self.message_revision = 0
        self.last_control_revision = None
        self.director = Director()
        self.unanswered = False
        self.last_actor = None
        self.last_reflex = 0
        self.retry_after = 0
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.status = {"runner": "waiting_game", "model": model.model, "calls": 0}
        self.folder.mkdir(parents=True, exist_ok=True)

    def log(self, role: str, text: str, **extra) -> None:
        event = {"id": uuid.uuid4().hex, "time": time.time(), "role": role, "text": text, **extra}
        self.history.append(event)
        self.history = self.history[-100:]
        write_json(self.folder / "conversation.json", {"session": self.session, "events": self.history})

    def switch_session(self, snapshot: dict) -> None:
        conversation = read_json(self.folder / "conversation.json") or {}
        saved_memory = read_json(self.folder / "memory.json") or {}
        resume = self.session is None and conversation.get("session") == snapshot["session"]
        self.session = snapshot["session"]
        # A reload starts a new memory branch; knowledge from an undone future cannot leak in.
        self.history = conversation.get("events", [])[-100:] if resume else []
        self.memory = saved_memory.get("notes", [])[-24:] if resume and saved_memory.get("session") == self.session else []
        self.director = Director(saved_memory.get("plan") if resume and saved_memory.get("session") == self.session else None)
        self.unanswered = False
        self.command_pending = None
        self.last_result = None
        self.last_ask = 0
        self.message_revision += 1
        self.log("system", "대화를 이어갈 준비가 됐어. 함께 시작을 눌러줘." if resume else
                 "새 게임 세션에 연결됐어. 동료를 고르고 함께 시작을 눌러줘.")
        self.save_memory()

    def save_memory(self):
        write_json(self.folder / "memory.json", {"session": self.session, "notes": self.memory,
                   "plan": self.director.saved(), "actor": self.last_actor})

    def ingest_messages(self, actor=None) -> bool:
        changed = False
        for path in sorted((self.folder / "inbox").glob("*.json")):
            item = read_json(path)
            if item is None:
                continue
            if item.get("session") != self.session:
                path.unlink(missing_ok=True)
                continue
            if item.get("actor") and item["actor"] != actor:
                desired = (read_json(self.folder / "control.json") or {}).get("companion")
                if item["actor"] != desired:
                    path.unlink(missing_ok=True)
                continue
            path.unlink(missing_ok=True)
            if isinstance(item.get("text"), str) and item["text"].strip():
                self.log("user", item["text"].strip()[:1000], actor=actor)
                self.message_revision += 1
                self.unanswered = True
                changed = True
        return changed

    def tick(self) -> None:
        now = time.monotonic()
        snapshot = read_json(self.folder / "snapshot.json")
        control = read_json(self.folder / "control.json") or {}
        self.status.update({"calls": self.calls, "updated": time.time()})
        if not snapshot or snapshot.get("protocol") != 1 or not snapshot.get("session"):
            self.status["runner"] = "waiting_game"
            return
        try:
            fresh = time.time() - (self.folder / "snapshot.json").stat().st_mtime < 4
        except OSError:
            fresh = False
        if snapshot["session"] != self.session:
            self.switch_session(snapshot)
        self.status["session"] = self.session
        self.status["blocked"] = snapshot.get("blocked")
        actor = snapshot.get("companion", {}).get("id")
        if self.last_actor and actor != self.last_actor:
            self.director = Director()
            self.memory = []
            self.unanswered = False
        self.last_actor = actor
        messages_changed = self.ingest_messages(actor)
        self.director.observe(snapshot)
        revision = control.get("revision", 0)
        if revision != self.last_control_revision:
            self.last_control_revision = revision
            self.message_revision += 1
        result = snapshot.get("result")
        if result and (result.get("id"), result.get("status")) != self.last_result:
            self.last_result = (result.get("id"), result.get("status"))
            if self.command_pending and result.get("id") == self.command_pending["id"]:
                if self.command_pending.get("action") != "wait" or result.get("status") != "completed":
                    self.log("game", result.get("detail", result.get("status", "")), result=result)
                if result.get("status") in ("completed", "rejected", "failed", "cancelled"):
                    if result.get("status") == "completed":
                        self.director.completed(self.command_pending)
                        self.save_memory()
                    elif result.get("status") in ("failed", "rejected"):
                        self.director.trigger = "action_failed"
                    self.command_pending = None
        enabled = fresh and control.get("enabled") is True and control.get("session") == self.session
        enabled = enabled and bool(snapshot.get("companion"))
        self.status["runner"] = "ready" if enabled else ("paused" if fresh else "game_disconnected")
        if self.pending and self.pending.done():
            future, context = self.pending, self.pending_context
            self.pending = None
            self.pending_context = None
            try:
                decision, latency = future.result()
                self.status["last_latency_seconds"] = round(latency, 2)
                # Human steering, assignment changes, reloads, and combat invalidate old intentions.
                unchanged = context["session"] == self.session and context["revision"] == revision
                unchanged = unchanged and context["message_revision"] == self.message_revision
                unchanged = unchanged and context["actor"] == snapshot.get("companion", {}).get("id")
                unchanged = unchanged and context.get("blocked") == snapshot.get("blocked")
                if not enabled or not unchanged:
                    self.log("system", "상황이 바뀌어 이전 판단을 취소했어.")
                else:
                    validate_decision(decision, snapshot)
                    self.director.apply(decision, context.get("human_message", False))
                    command = command_for(decision, snapshot, revision)
                    write_json(self.folder / "command.json", command)
                    self.command_pending = command | {"sent": now}
                    self.unanswered = False
                    if decision["say"]:
                        self.log("friend", decision["say"], action=decision["action"], actor=actor,
                                 speaker=snapshot["companion"].get("name", "동료"))
                    if decision["remember"]:
                        self.memory.append({"kind": "conversation_note", "text": decision["remember"]})
                        self.memory = self.memory[-24:]
                    self.save_memory()
                    self.status.pop("error", None)
            except Exception as exc:
                self.status["error"] = str(exc)[:300]
                self.retry_after = now + 15
                self.log("system", "판단을 적용하지 못했어: " + str(exc)[:200])
        if self.command_pending and now - self.command_pending["sent"] > 22:
            self.log("system", "게임에서 행동 결과가 오지 않았어. 다음 상태를 기다릴게.")
            self.command_pending = None
        if not enabled:
            return
        if self.pending:
            self.status["runner"] = "thinking"
            return
        if self.command_pending:
            self.status["runner"] = "acting"
            return
        if self.max_calls and self.calls >= self.max_calls:
            self.status["runner"] = "call_limit"
            return
        if now < self.retry_after:
            return
        if not self.unanswered and now - self.last_ask < self.interval:
            return
        if not self.unanswered and self.director.regroup(snapshot) and now - self.last_reflex > 8:
            decision = {"say": "", "action": "follow", "target": "", "reason": "Keep travelling together",
                        "remember": "", "stance": "keep"}
            command = command_for(decision, snapshot, revision)
            write_json(self.folder / "command.json", command)
            self.command_pending = command | {"sent": now}
            self.last_reflex = now
            return
        if not self.unanswered and not self.director.trigger:
            return
        if snapshot.get("blocked") and not self.unanswered:
            # One reaction to entering/leaving combat, not narration every polling interval.
            if self.director.trigger != "situation_changed" or snapshot.get("blocked") != "combat":
                return
        if self.director.stance == "hold" and not self.unanswered and self.director.trigger == "human_moved":
            self.director.trigger = None
            return
        self.pending_context = {"session": self.session, "revision": revision,
                                "message_revision": self.message_revision,
                                "actor": snapshot["companion"]["id"], "human_message": self.unanswered,
                                "blocked": snapshot.get("blocked")}
        observed = copy.deepcopy(snapshot)
        observed["attention"] = self.director.context(self.unanswered)
        self.director.trigger = None
        self.pending = self.pool.submit(self.model.decide, observed,
                                        copy.deepcopy(self.memory), copy.deepcopy(self.history))
        self.calls += 1
        self.last_ask = now
        self.status["runner"] = "thinking"

    def run(self, stop_file: Path | None = None) -> None:
        try:
            while True:
                if stop_file and stop_file.exists():
                    break
                try:
                    self.tick()
                except Exception as exc:
                    self.status.update(runner="error", error=str(exc)[:250])
                write_json(self.folder / "runner.json", self.status)
                time.sleep(0.35)
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)
            control = read_json(self.folder / "control.json") or {}
            if control.get("session") == self.session and control.get("enabled"):
                control.update(enabled=False, revision=control.get("revision", 0) + 1)
                write_json(self.folder / "control.json", control)
            self.status["runner"] = "stopped"
            write_json(self.folder / "runner.json", self.status)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--io", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    model = ReplayModel() if args.offline else CodexModel(args.model)
    Runner(args.io, model, max(5, args.interval), args.max_calls).run()


if __name__ == "__main__":
    main()
