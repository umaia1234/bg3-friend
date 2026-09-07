"""Small, explicit boundary between model intent and game actions."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time
import uuid

PROTOCOL = 1
ACTIONS = ("wait", "follow", "approach", "look")
DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "say": {"type": "string"},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "target": {"type": "string"},
        "reason": {"type": "string"},
        "remember": {"type": "string"},
        "stance": {"type": "string", "enum": ["keep", "hold", "together", "scout"]},
    },
    "required": ["say", "action", "target", "reason", "remember", "stance"],
}


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        # The game writes snapshots in place. A partial write is retried next poll.
        return None


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        # BG3 opens bridge files without Windows delete-sharing. Its brief read must not
        # crash the runner when a WSL rename overlaps it.
        for attempt in range(7):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 6:
                    raise
                time.sleep(.005 * 2 ** attempt)
    finally:
        temp.unlink(missing_ok=True)


def distance(a: list, b: list) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def validate_decision(value: dict, snapshot: dict) -> dict:
    if not isinstance(value, dict) or set(value) != set(DECISION_SCHEMA["required"]):
        raise ValueError("Invalid decision shape")
    if not all(isinstance(v, str) for v in value.values()):
        raise ValueError("Decision values must be strings")
    if value["action"] not in ACTIONS:
        raise ValueError("Unsupported action")
    if value["stance"] not in ("keep", "hold", "together", "scout"):
        raise ValueError("Unsupported shared plan")
    if value["stance"] == "hold" and value["action"] in ("follow", "approach"):
        raise ValueError("Waiting agreement cannot start movement")
    if len(value["say"]) > 300 or len(value["reason"]) > 500 or len(value["remember"]) > 300:
        raise ValueError("Decision too long")
    companion = snapshot.get("companion")
    if not companion:
        raise ValueError("No assigned companion")
    targets = {e["id"]: e for e in snapshot.get("nearby", [])}
    if value["action"] in ("approach", "look"):
        if value["target"] not in targets:
            raise ValueError("Target is not observed")
    elif value["target"]:
        raise ValueError("This action does not take a target")
    if value["action"] == "approach":
        target = targets[value["target"]]
        if target.get("hostile") or target.get("dead"):
            raise ValueError("Unsafe exploration target")
        if distance(companion["position"], target["position"]) > 12:
            raise ValueError("Target beyond exploration radius")
    if value["action"] in ("follow", "approach"):
        if snapshot.get("blocked") or companion.get("selected"):
            raise ValueError("Game currently prevents autonomous movement")
    return value


def command_for(decision: dict, snapshot: dict, revision: int) -> dict:
    validate_decision(decision, snapshot)
    return {
        "protocol": PROTOCOL,
        "id": uuid.uuid4().hex,
        "session": snapshot["session"],
        "observed_seq": snapshot["seq"],
        "control_revision": revision,
        "actor": snapshot["companion"]["id"],
        "action": decision["action"],
        "target": decision["target"],
        "say": decision["say"],
    }
