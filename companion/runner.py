"""Observe -> decide off-thread -> revalidate -> dispatch -> remember outcome."""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError, Future
import copy
import json
from pathlib import Path
import queue
import threading
import time
import uuid

from .model import CodexModel, ReplayModel
from .director import Director
from .protocol import command_for, read_json, validate_decision, write_json


class _DecisionWorker:
    """One daemon worker; an uncooperative fixture cannot hold interpreter exit open."""

    def __init__(self):
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.closed = False
        self.thread = None

    def submit(self, function, *args):
        with self.lock:
            if self.closed:
                raise RuntimeError("Decision worker is stopped")
            future = Future()
            self.jobs.put((future, function, args))
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="friend-decision", daemon=True)
                self.thread.start()
            return future

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            future, function, args = job
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args))
                except BaseException as exc:
                    future.set_exception(exc)

    def shutdown(self, wait=True, cancel_futures=False, timeout=None):
        with self.lock:
            if not self.closed:
                self.closed = True
                if cancel_futures:
                    while True:
                        try:
                            self.jobs.get_nowait()[0].cancel()
                        except queue.Empty:
                            break
                self.jobs.put(None)
        if wait and self.thread:
            self.thread.join(timeout)


_UNOBSERVED = object()


class BridgeIOError(RuntimeError):
    code = "local_io_failed"

    def __init__(self):
        super().__init__("게임 연결 파일을 갱신하지 못해 대화를 중지했습니다. 쓰기 권한과 파일을 사용 중인 프로그램을 확인한 뒤 다시 연결해 주세요.")


class Runner:
    STATUS_WRITE_GRACE = 10.0

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
        self.pending_cancel = None
        self.cancel_requested = False
        self.generation = 0
        self.last_blocked = _UNOBSERVED
        self.command_pending = None
        self.last_result = None
        self.message_revision = 0
        self.last_control_revision = None
        self.director = Director()
        self.unanswered = False
        self.last_actor = None
        self.last_reflex = 0
        self.retry_after = 0
        self.failures = 0
        self.failure_blocked = False
        self.stopping = False
        self.status_write_blocked = None
        self.pool = _DecisionWorker()
        self.status = {"runner": "waiting_game", "model": model.model, "calls": 0}
        self.folder.mkdir(parents=True, exist_ok=True)

    def invalidate_pending(self):
        self.generation += 1
        if self.pending is None or self.cancel_requested:
            return
        self.cancel_requested = True
        self.director.trigger = self.director.trigger or (self.pending_context or {}).get("trigger")
        if self.pending_cancel is not None:
            self.pending_cancel.set()
        self.pending.cancel()
        cancel = getattr(self.model, "cancel_pending", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass  # Generation validation still prevents a late result from acting.

    def reset_failures(self):
        self.failures = 0
        self.failure_blocked = False
        self.retry_after = 0
        self.status.pop("error", None)
        self.status.pop("error_code", None)
        self.status.pop("retry_attempt", None)

    def decision_failed(self, exc, context, now):
        self.failures += 1
        retryable = getattr(exc, "retryable", not isinstance(exc, (ValueError, TypeError)))
        self.failure_blocked = not retryable or self.failures > 3
        self.retry_after = now + (1, 5, 15)[min(self.failures - 1, 2)]
        self.director.trigger = self.director.trigger or context.get("trigger") or "retry"
        self.status.update(error=str(exc)[:300], error_code=getattr(exc, "code", "decision_failed"),
                           retry_attempt=self.failures, runner="error" if self.failure_blocked else "retrying")
        self.log("system", "판단을 적용하지 못했어: " + str(exc)[:200])

    def log(self, role: str, text: str, **extra) -> None:
        event = {"id": uuid.uuid4().hex, "time": time.time(), "role": role, "text": text, **extra}
        self.history.append(event)
        self.history = self.history[-100:]
        write_json(self.folder / "conversation.json", {"session": self.session, "events": self.history})

    def switch_session(self, snapshot: dict) -> None:
        self.invalidate_pending()
        self.reset_failures()
        self.last_blocked = _UNOBSERVED
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
        if self.stopping or self.status_write_blocked is not None:
            return
        now = time.monotonic()
        snapshot = read_json(self.folder / "snapshot.json")
        control = read_json(self.folder / "control.json") or {}
        self.status.update({"calls": self.calls, "updated": time.time()})
        if not snapshot or snapshot.get("protocol") != 1 or not snapshot.get("session"):
            if self.pending and not self.cancel_requested:
                self.invalidate_pending()
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
            self.invalidate_pending()
            self.reset_failures()
            self.director = Director()
            self.memory = []
            self.unanswered = False
        self.last_actor = actor
        messages_changed = self.ingest_messages(actor)
        if messages_changed:
            self.invalidate_pending()
            self.reset_failures()
        blocked = snapshot.get("blocked")
        if self.last_blocked is not _UNOBSERVED and blocked != self.last_blocked:
            self.invalidate_pending()
        self.last_blocked = blocked
        self.director.observe(snapshot)
        revision = control.get("revision", 0)
        if revision != self.last_control_revision:
            self.invalidate_pending()
            self.reset_failures()
            self.last_control_revision = revision
            self.message_revision += 1
            self.director.trigger = self.director.trigger or "control_changed"
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
        enabled = enabled and bool(actor) and actor == control.get("companion")
        enabled = enabled and snapshot.get("control_revision", revision) == revision
        self.status["runner"] = "ready" if enabled else ("paused" if fresh else "game_disconnected")
        if not enabled and self.pending and not self.cancel_requested:
            self.invalidate_pending()
        if self.pending and self.pending.done():
            future, context = self.pending, self.pending_context
            cancelled = self.cancel_requested
            self.pending = None
            self.pending_context = None
            self.pending_cancel = None
            self.cancel_requested = False
            try:
                # Human steering, assignment changes, reloads, and combat invalidate old intentions.
                unchanged = context["session"] == self.session and context["revision"] == revision
                unchanged = unchanged and context["message_revision"] == self.message_revision
                unchanged = unchanged and context["actor"] == snapshot.get("companion", {}).get("id")
                unchanged = unchanged and context.get("blocked") == snapshot.get("blocked")
                unchanged = unchanged and context.get("generation", 0) == self.generation
                if not enabled or not unchanged or cancelled:
                    self.log("system", "상황이 바뀌어 이전 판단을 취소했어.")
                else:
                    decision, latency = future.result()
                    self.status["last_latency_seconds"] = round(latency, 2)
                    validate_decision(decision, snapshot)
                    next_director = copy.deepcopy(self.director)
                    next_director.apply(decision, context.get("human_message", False))
                    command = command_for(decision, snapshot, revision)
                    write_json(self.folder / "command.json", command)
                    self.director = next_director
                    self.command_pending = command | {"sent": now}
                    self.unanswered = False
                    if decision["say"]:
                        self.log("friend", decision["say"], action=decision["action"], actor=actor,
                                 speaker=snapshot["companion"].get("name", "동료"))
                    if decision["remember"]:
                        self.memory.append({"kind": "conversation_note", "text": decision["remember"]})
                        self.memory = self.memory[-24:]
                    self.save_memory()
                    self.reset_failures()
            except CancelledError:
                self.director.trigger = self.director.trigger or context.get("trigger")
            except Exception as exc:
                self.decision_failed(exc, context, now)
        if self.command_pending and now - self.command_pending["sent"] > 22:
            self.log("system", "게임에서 행동 결과가 오지 않았어. 다음 상태를 기다릴게.")
            self.command_pending = None
        if not enabled:
            return
        if self.pending:
            self.status["runner"] = "cancelling" if self.cancel_requested else "thinking"
            return
        if self.command_pending:
            self.status["runner"] = "acting"
            return
        if self.failure_blocked:
            self.status["runner"] = "error"
            return
        if self.max_calls and self.calls >= self.max_calls:
            self.status["runner"] = "call_limit"
            return
        if now < self.retry_after:
            self.status["runner"] = "retrying"
            return
        if not self.failures and not self.unanswered and now - self.last_ask < self.interval:
            return
        if not self.failures and not self.unanswered and self.director.regroup(snapshot) and now - self.last_reflex > 8:
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
                                "blocked": snapshot.get("blocked"), "generation": self.generation,
                                "trigger": self.director.trigger}
        observed = copy.deepcopy(snapshot)
        observed["attention"] = self.director.context(self.unanswered)
        self.director.trigger = None
        self.pending_cancel = threading.Event()
        self.cancel_requested = False
        decide = getattr(self.model, "decide_cancellable", None)
        arguments = (observed, copy.deepcopy(self.memory), copy.deepcopy(self.history))
        self.pending = self.pool.submit(decide, *arguments, self.pending_cancel) if callable(decide) else \
            self.pool.submit(self.model.decide, *arguments)
        self.calls += 1
        self.last_ask = now
        self.status["runner"] = "thinking"

    def publish_status(self) -> bool:
        # Only heartbeat/state publication can be rebuilt and retried here. Never
        # queue a command or replay a serialized decision across this pause.
        status = self.status | {"updated": time.time()}
        if self.status_write_blocked is not None:
            status.update(runner="retrying", error_code="local_io_failed",
                          error="게임 연결 파일이 사용 중입니다. 판단을 멈추고 연결 복구를 기다립니다.")
        try:
            write_json(self.folder / "runner.json", status)
        except PermissionError as exc:
            now = time.monotonic()
            if self.status_write_blocked is None:
                self.status_write_blocked = now
                self.invalidate_pending()
            if now - self.status_write_blocked >= self.STATUS_WRITE_GRACE:
                raise BridgeIOError() from exc
            return False
        except OSError as exc:
            raise BridgeIOError() from exc
        self.status_write_blocked = None
        return True

    def run(self, stop_file: Path | None = None) -> None:
        failure = None
        try:
            while True:
                if stop_file and stop_file.exists():
                    break
                try:
                    self.tick()
                except Exception as exc:
                    self.status.update(runner="error", error=str(exc)[:250])
                self.publish_status()
                time.sleep(0.35)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self.stopping = True
            self.invalidate_pending()
            self.pool.shutdown(wait=False, cancel_futures=True)
            cleanup_error = None
            try:
                control = read_json(self.folder / "control.json") or {}
                if control.get("session") == self.session and control.get("enabled"):
                    control.update(enabled=False, revision=control.get("revision", 0) + 1)
                    write_json(self.folder / "control.json", control)
            except (OSError, ValueError, TypeError) as exc:
                cleanup_error = exc
            try:
                self.status["runner"] = "stopped"
                write_json(self.folder / "runner.json", self.status)
            except OSError as exc:
                cleanup_error = cleanup_error or exc
            finally:
                # Give a cancellable model time to reap its owned subprocess. A model
                # without cancellation support cannot delay process exit indefinitely.
                self.pool.shutdown(wait=True, timeout=2.5)
            if cleanup_error is not None and failure is None:
                raise BridgeIOError() from cleanup_error


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
