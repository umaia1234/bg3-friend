"""Preview and transactionally install a verified, prebuilt BG3 Friend package.

This module never discovers credentials, downloads tools, starts processes, or edits
saves/control files. The caller supplies confirmed paths and a fail-closed game
process check. Planning only reads files; only ``apply_plan`` changes the system.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable
import uuid
import xml.etree.ElementTree as ET

MOD_UUID = "cfd9c54e-3884-47ed-9b40-82b8747194de"
MOD_VERSION64 = "36028797018963969"
STATE_FILE = "installation.json"
GameCheck = bool | Callable[[], bool]


class InstallationError(RuntimeError):
    """An installation operation could not safely finish."""


class PreflightError(InstallationError):
    """Missing prerequisites or invalid paths/data; no game file was changed."""


class ConflictError(InstallationError):
    def __init__(self, conflicts: list[str] | tuple[str, ...]):
        self.conflicts = tuple(conflicts)
        super().__init__("Installation conflicts: " + "; ".join(self.conflicts))


class ApplyError(InstallationError):
    def __init__(self, cause: BaseException, journal: Path, rollback_errors: list[str]):
        self.journal = journal
        self.rollback_errors = tuple(rollback_errors)
        self.rolled_back = not rollback_errors
        outcome = "All applied changes were rolled back." if self.rolled_back else "Recovery is incomplete: " + "; ".join(rollback_errors)
        super().__init__(f"Installation failed: {cause}. {outcome} Recovery journal: {journal}")


def _digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


@dataclass(frozen=True)
class FileChange:
    role: str
    path: Path
    before: bytes | None = field(repr=False)
    after: bytes | None = field(repr=False)

    def to_dict(self) -> dict:
        return {"role": self.role, "path": str(self.path),
                "operation": "remove" if self.after is None else "create" if self.before is None else "replace",
                "before_sha256": _digest(self.before), "after_sha256": _digest(self.after)}


@dataclass(frozen=True)
class InstallPlan:
    action: str
    game: Path
    profile: Path
    state_root: Path
    version: str
    changes: tuple[FileChange, ...]
    _manifest_before: bytes | None = field(repr=False)
    _manifest_after: bytes | None = field(repr=False)
    _guards: tuple[tuple[Path, str | None], ...] = field(repr=False)
    _backups: tuple[tuple[Path, bytes], ...] = field(repr=False)

    @property
    def changed(self) -> bool:
        return bool(self.changes or self._manifest_before != self._manifest_after)

    def to_dict(self) -> dict:
        return {"action": self.action, "ready": True, "version": self.version,
                "game": str(self.game), "profile": str(self.profile), "state_root": str(self.state_root),
                "changed": self.changed, "changes": [change.to_dict() for change in self.changes],
                "original_backups": [str(path) for path, _ in self._backups],
                "state_manifest": str(self.state_root / STATE_FILE)}


@dataclass(frozen=True)
class ApplyResult:
    action: str
    version: str
    changed_files: tuple[str, ...]
    state_root: Path
    journal: Path | None
    changed: bool

    def to_dict(self) -> dict:
        return {"action": self.action, "version": self.version, "changed": self.changed,
                "changed_files": list(self.changed_files), "state_root": str(self.state_root),
                "journal": str(self.journal) if self.journal else None}


def _stopped(game_running: GameCheck) -> None:
    try:
        running = game_running() if callable(game_running) else game_running
    except PreflightError:
        raise
    except Exception as exc:
        raise PreflightError("Could not determine whether BG3 is running; close the game and retry the process check") from exc
    if running is not False:
        message = "Close BG3 before modifying the installation" if running is True else "The game process check must return an explicit False"
        raise PreflightError(message)


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise PreflightError(f"Use a real path rather than a linked/reparse path: {part}")


def _absolute(path: Path | str, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise PreflightError(f"{label} must be an absolute path")
    _no_links(candidate)
    return candidate.resolve()


def _read(path: Path) -> bytes | None:
    _no_links(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise PreflightError(f"Expected a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PreflightError(f"Cannot read {path}: {exc}") from exc


def _required(path: Path) -> bytes:
    data = _read(path)
    if not data:
        raise PreflightError(f"Required file is missing or empty: {path}")
    return data


def _writable(path: Path) -> None:
    _no_links(path)
    parent = path if path.is_dir() else path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK):
        raise PreflightError(f"Destination is not writable: {path}")
    if path.exists() and path.is_file() and not os.access(path, os.W_OK):
        raise PreflightError(f"Destination is not writable: {path}")


def _locations(game: Path | str, profile: Path | str, state_root: Path | str) -> tuple[Path, Path, Path, Path]:
    game = _absolute(game, "game")
    profile = _absolute(profile, "profile")
    state_root = _absolute(state_root, "state_root")
    for first, second in ((game, profile), (game, state_root), (profile, state_root)):
        if first == second or first in second.parents or second in first.parents:
            raise PreflightError("Game, game profile, and per-user installation state must be separate directories")
    if not game.is_dir() or not profile.is_dir():
        raise PreflightError("The confirmed game and game profile directories must already exist")
    executable = next((game / "bin" / name for name in ("bg3_dx11.exe", "bg3.exe") if (game / "bin" / name).is_file()), None)
    if executable is None:
        raise PreflightError(f"No BG3 executable found in {game / 'bin'}")
    _required(executable)
    if state_root.exists() and not state_root.is_dir():
        raise PreflightError("state_root must be a directory")
    _writable(state_root / STATE_FILE)
    return game, profile, state_root, executable


def _settings(data: bytes) -> tuple[ET.Element, dict[str, ET.Element]]:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise PreflightError("modsettings.lsx must not contain a DTD or entity declarations")
    try:
        root = ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except ET.ParseError as exc:
        raise PreflightError(f"Cannot parse modsettings.lsx: {exc}") from exc
    children = root.findall("./region[@id='ModuleSettings']/node[@id='root']/children")
    if len(children) != 1:
        raise PreflightError("Unrecognized modsettings.lsx: expected one ModuleSettings root")
    containers = {}
    for name in ("Mods", "ModOrder"):
        nodes = children[0].findall(f"./node[@id='{name}']")
        if len(nodes) > 1 or (name == "Mods" and not nodes):
            raise PreflightError(f"Unrecognized modsettings.lsx: invalid {name} list")
        if nodes:
            lists = nodes[0].findall("./children")
            if len(lists) != 1:
                raise PreflightError(f"Unrecognized modsettings.lsx: missing {name}/children")
            containers[name] = lists[0]
            if len(_own_entries(lists[0])) > 1:
                raise PreflightError(f"Duplicate BG3 Friend entries in {name}; resolve the existing registration first")
    return root, containers


def _own_entries(container: ET.Element) -> list[ET.Element]:
    return [node for node in container if any(attr.get("value", "").lower() == MOD_UUID for attr in node.findall("./attribute[@id='UUID']"))]


def _signature(node: ET.Element):
    return [node.tag if isinstance(node.tag, str) else "#comment", sorted(node.attrib.items()),
            (node.text or "").strip(), [_signature(child) for child in node]]


def _owned(containers: dict[str, ET.Element]) -> dict:
    # Normalize tuple attributes through JSON so stored and in-memory signatures agree.
    return json.loads(json.dumps({name: [_signature(node) for node in _own_entries(containers[name])] if name in containers else []
                                  for name in ("Mods", "ModOrder")}))


def _replace_own(container: ET.Element, replacements: list[ET.Element]) -> None:
    old = _own_entries(container)
    index = list(container).index(old[0]) if old else len(container)
    for node in old:
        container.remove(node)
    for offset, node in enumerate(replacements):
        container.insert(index + offset, copy.deepcopy(node))


def _new_registration(mod_version64: str) -> ET.Element:
    node = ET.Element("node", id="ModuleShortDesc")
    for name, kind, value in (("Folder", "LSString", "BG3Friend"), ("MD5", "LSString", ""),
                              ("Name", "LSString", "BG3 Friend"), ("UUID", "guid", MOD_UUID),
                              ("Version64", "int64", mod_version64), ("PublishHandle", "uint64", "0")):
        ET.SubElement(node, "attribute", id=name, type=kind, value=value)
    return node


def _install_settings(data: bytes, mod_version64: str) -> tuple[bytes, dict]:
    root, containers = _settings(data)
    before_owned = _owned(containers)
    _replace_own(containers["Mods"], [_new_registration(mod_version64)])
    if "ModOrder" in containers:
        node = ET.Element("node", id="Module")
        ET.SubElement(node, "attribute", id="UUID", type="guid", value=MOD_UUID)
        _replace_own(containers["ModOrder"], [node])
    after_owned = _owned(containers)
    return (data if before_owned == after_owned else ET.tostring(root, encoding="utf-8", xml_declaration=True)), after_owned


def _restore_settings(current: bytes, original: bytes, installed_hash: str, restore_original_exact: bool) -> bytes:
    if restore_original_exact and _digest(current) == installed_hash:
        return original
    root, containers = _settings(current)
    _, originals = _settings(original)
    for name, container in containers.items():
        _replace_own(container, _own_entries(originals[name]) if name in originals else [])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def check_recovery(state_root: Path | str) -> None:
    """Read-only refusal of unfinished/unknown transactions, even without a marker.

    The caller must not delete these journals to retry. They and their before-
    images are the evidence needed for an explicit, separately reviewed recovery.
    """
    state_root = _absolute(state_root, "state_root")
    pending = _read(state_root / "pending.json")
    if pending is not None:
        raise PreflightError(f"An interrupted installation needs recovery; inspect {state_root / 'pending.json'} before retrying")
    transactions = state_root / "transactions"
    _no_links(transactions)
    if not transactions.exists():
        return
    if not transactions.is_dir():
        raise PreflightError(f"Cannot verify installation recovery records; inspect {transactions} before retrying")
    try:
        directories = sorted(transactions.iterdir())
    except OSError as exc:
        raise PreflightError(f"Cannot read installation recovery records; inspect {transactions} before retrying") from exc
    for directory in directories:
        _no_links(directory)
        journal_path = directory / "journal.json"
        message = f"An interrupted or damaged installation needs recovery; inspect {journal_path} and its before-images before retrying. No installation files were changed"
        if not directory.is_dir():
            raise PreflightError(message)
        try:
            raw = _read(journal_path)
            journal = json.loads(raw) if raw is not None else None
            finalized = (isinstance(journal, dict) and journal.get("schema") == 1
                         and journal.get("action") in ("install", "update", "uninstall")
                         and journal.get("phase") in ("complete", "rolled_back")
                         and isinstance(journal.get("operations"), list)
                         and not journal.get("rollback_errors"))
        except (ValueError, TypeError, OSError, PreflightError) as exc:
            raise PreflightError(message) from exc
        if not finalized:
            raise PreflightError(message)


def _load_state(state_root: Path) -> tuple[bytes | None, dict | None]:
    check_recovery(state_root)
    raw = _read(state_root / STATE_FILE)
    if raw is None:
        return None, None
    try:
        state = json.loads(raw)
        if not isinstance(state, dict) or state.get("schema") != 1 or not re.fullmatch(r"[a-f0-9]{32}", state.get("id", "")):
            raise ValueError("unsupported state schema or installation id")
        if not isinstance(state.get("files"), list) or not isinstance(state.get("version"), str):
            raise ValueError("missing state fields")
        expected = {"package": Path(state["profile"]) / "Mods/BG3Friend.pak",
                    "settings": Path(state["profile"]) / "PlayerProfiles/Public/modsettings.lsx",
                    "extender": Path(state["game"]) / "bin/DWrite.dll"}
        seen = set()
        for entry in state["files"]:
            role = entry["role"]
            if role in seen or role not in expected or Path(entry["path"]) != expected[role]:
                raise ValueError("unexpected managed file path")
            seen.add(role)
            if not re.fullmatch(r"[a-f0-9]{64}", entry["installed_sha256"]):
                raise ValueError("invalid installed hash")
            if type(entry["original_exists"]) is not bool:
                raise ValueError("invalid original file state")
            if entry["original_exists"]:
                if entry["backup"] != f"backups/{state['id']}/{role}.bin" or not re.fullmatch(r"[a-f0-9]{64}", entry["original_sha256"]):
                    raise ValueError("invalid original backup")
            elif entry.get("backup") is not None or entry.get("original_sha256") is not None:
                raise ValueError("unexpected backup for an absent original")
        if not {"package", "settings"}.issubset(seen):
            raise ValueError("missing managed file records")
        return raw, state
    except (ValueError, TypeError, KeyError) as exc:
        raise PreflightError(f"Invalid installation state; keep the original backups: {exc}") from exc


def _original(state_root: Path, entry: dict) -> bytes | None:
    if not entry["original_exists"]:
        return None
    data = _read(state_root / entry["backup"])
    if _digest(data) != entry["original_sha256"]:
        raise PreflightError(f"Original backup is damaged: {state_root / entry['backup']}")
    return data


def _managed_current(state: dict) -> dict[str, bytes]:
    current = {}
    conflicts = []
    for entry in state["files"]:
        path = Path(entry["path"])
        data = _read(path)
        if entry["role"] == "settings" and data is not None:
            _, containers = _settings(data)
            if _owned(containers) != entry.get("owned"):
                conflicts.append(f"BG3 Friend registration changed after installation: {path}")
        elif _digest(data) != entry["installed_sha256"]:
            conflicts.append(f"Managed file changed or disappeared after installation: {path}")
        current[entry["role"]] = data
    if conflicts:
        raise ConflictError(conflicts)
    return current


def _validate_version(version: str, mod_version64: str) -> None:
    if not isinstance(version, str) or not version.strip() or any(ord(char) < 32 for char in version):
        raise PreflightError("A nonempty release version is required")
    if not isinstance(mod_version64, str) or not mod_version64.isdecimal() or not 0 <= int(mod_version64) < 2**63:
        raise PreflightError("mod_version64 must be a nonnegative signed 64-bit integer string")


def plan_install(game: Path | str, profile: Path | str, package: Path | str, state_root: Path | str,
                 *, version: str, package_sha256: str, game_running: GameCheck,
                 extender: Path | str | None = None, extender_sha256: str | None = None,
                 mod_version64: str = MOD_VERSION64) -> InstallPlan:
    """Read every prerequisite and prepare an install/update without writing files.

    ``package_sha256`` comes from the reviewed release manifest. The hash and LSPK
    header are checked here; this is not a general-purpose Larian archive parser.
    An existing DWrite.dll is retained. If it is absent, an explicitly supplied
    extender DLL is required. ScriptExtenderSettings.json is never changed.
    """
    _stopped(game_running)
    _validate_version(version, mod_version64)
    game, profile, state_root, executable = _locations(game, profile, state_root)
    package = _absolute(package, "package")
    package_data = _required(package)
    if package.suffix.lower() != ".pak" or len(package_data) < 8 or not package_data.startswith(b"LSPK"):
        raise PreflightError("The release package must be a nonempty LSPK .pak file")
    if not isinstance(package_sha256, str) or not re.fullmatch(r"[A-Fa-f0-9]{64}", package_sha256) or _digest(package_data) != package_sha256.lower():
        raise PreflightError("Release package SHA-256 does not match the supplied manifest")
    manifest_before, state = _load_state(state_root)
    if state is not None and (Path(state["game"]) != game or Path(state["profile"]) != profile):
        raise PreflightError("This state directory belongs to a different game/profile installation")
    targets = {"package": profile / "Mods/BG3Friend.pak", "settings": profile / "PlayerProfiles/Public/modsettings.lsx", "extender": game / "bin/DWrite.dll"}
    if package in targets.values():
        raise PreflightError("Use the separate release package, not the currently installed package")
    settings_data = _required(targets["settings"])
    settings_after, owned = _install_settings(settings_data, mod_version64)
    before = _managed_current(state) if state else {"package": _read(targets["package"]), "settings": settings_data}
    after = {"package": package_data, "settings": settings_after}
    dll = _read(targets["extender"])
    if dll is None:
        if extender is None:
            raise PreflightError("Script Extender is missing; supply the reviewed DWrite.dll before installing")
        source = _absolute(extender, "extender")
        extender_data = _required(source)
        if source.suffix.lower() != ".dll" or not extender_data.startswith(b"MZ"):
            raise PreflightError("The Script Extender file must be a Windows DLL")
        if extender_sha256 is not None and _digest(extender_data) != extender_sha256.lower():
            raise PreflightError("Script Extender SHA-256 does not match the supplied manifest")
        before["extender"] = None
        after["extender"] = extender_data
    elif not dll:
        raise PreflightError("Existing DWrite.dll is empty; inspect the existing installation before changing it")
    elif "extender" in before:
        after["extender"] = dll
    action = "update" if state else "install"
    updated = copy.deepcopy(state) if state else {"schema": 1, "id": uuid.uuid4().hex, "game": str(game), "profile": str(profile), "files": []}
    updated.update(version=version, package_sha256=package_sha256.lower(), mod_version64=mod_version64)
    entries = {entry["role"]: entry for entry in updated["files"]}
    backups = []
    if state:
        for entry in state["files"]:
            _original(state_root, entry)
    for role, data in after.items():
        if role not in entries:
            original = before[role]
            backup = f"backups/{updated['id']}/{role}.bin" if original is not None else None
            entry = {"role": role, "path": str(targets[role]), "original_exists": original is not None,
                     "original_sha256": _digest(original), "backup": backup}
            entries[role] = entry
            updated["files"].append(entry)
            if original is not None:
                backups.append((state_root / backup, original))
        if role == "settings":
            entry = entries[role]
            entry["restore_original_exact"] = entry.get("restore_original_exact", True) and (
                "installed_sha256" not in entry or _digest(before[role]) == entry["installed_sha256"])
            entries[role]["owned"] = owned
        entries[role]["installed_sha256"] = _digest(data)
    changes = tuple(FileChange(role, targets[role], before[role], data) for role, data in after.items() if before[role] != data)
    guards = {path: _digest(_read(path)) for path in targets.values()}
    guards[executable] = _digest(_required(executable))
    for change in changes:
        _writable(change.path)
    return InstallPlan(action, game, profile, state_root, version, changes, manifest_before, _json_bytes(updated), tuple(guards.items()), tuple(backups))


def plan_uninstall(state_root: Path | str, *, game_running: GameCheck) -> InstallPlan:
    """Plan restoration of the first originals, preserving later unrelated mods.

    All owned-file and owned-registration conflicts are rejected before any
    mutation. Shared extender files and settings we never installed are retained.
    Original backups are retained after removal for inspection/manual recovery.
    """
    _stopped(game_running)
    state_root = _absolute(state_root, "state_root")
    manifest_before, state = _load_state(state_root)
    if state is None:
        raise PreflightError("No managed installation exists in this state directory")
    game, profile, state_root, executable = _locations(state["game"], state["profile"], state_root)
    current = _managed_current(state)
    changes = []
    for entry in state["files"]:
        role, path = entry["role"], Path(entry["path"])
        original = _original(state_root, entry)
        restored = _restore_settings(current[role], original, entry["installed_sha256"], entry.get("restore_original_exact", False)) if role == "settings" else original
        if current[role] != restored:
            _writable(path)
            changes.append(FileChange(role, path, current[role], restored))
    guards = [(Path(entry["path"]), _digest(current[entry["role"]])) for entry in state["files"]]
    guards.append((executable, _digest(_required(executable))))
    return InstallPlan("uninstall", game, profile, state_root, state["version"], tuple(changes), manifest_before, None, tuple(guards), ())


def _mkdirs(path: Path, created: list[Path]) -> None:
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_target(path: Path, data: bytes | None) -> None:
    if data is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, data)


@contextmanager
def _lock(state_root: Path):
    path = state_root / "installation.lock"
    _no_links(path)
    handle = path.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PreflightError("Another BG3 Friend installation operation is active") from exc
        yield
    finally:
        handle.close()


def _revalidate(plan: InstallPlan) -> None:
    _locations(plan.game, plan.profile, plan.state_root)
    manifest, _ = _load_state(plan.state_root)
    conflicts = []
    if manifest != plan._manifest_before:
        conflicts.append("Installation state changed after preview; create a new plan")
    for path, expected in plan._guards:
        if _digest(_read(path)) != expected:
            conflicts.append(f"File changed after preview: {path}")
    for path, data in plan._backups:
        existing = _read(path)
        if existing is not None and existing != data:
            conflicts.append(f"An original backup already exists and will not be overwritten: {path}")
    if conflicts:
        raise ConflictError(conflicts)
    for change in plan.changes:
        _writable(change.path)


def apply_plan(plan: InstallPlan, *, game_running: GameCheck) -> ApplyResult:
    """Apply an approved plan, rechecking every target and rolling back on error.

    The recovery journal and before-images are persisted before the first game
    change. If restoration itself fails, ``ApplyError.rollback_errors`` identifies
    every unrestored file and ``pending.json`` blocks a blind retry. After a hard
    process interruption, retain that journal and restore its listed before-images
    only after checking that target hashes still match that transaction.
    """
    _stopped(game_running)
    _revalidate(plan)
    if not plan.changed:
        return ApplyResult(plan.action, plan.version, (), plan.state_root, None, False)
    created = []
    _mkdirs(plan.state_root, created)
    with _lock(plan.state_root):
        _stopped(game_running)
        _revalidate(plan)
        transaction = plan.state_root / "transactions" / uuid.uuid4().hex
        _mkdirs(transaction, created)
        journal_path = transaction / "journal.json"
        pending_path = plan.state_root / "pending.json"
        operations = list(plan.changes) + [FileChange("installation_state", plan.state_root / STATE_FILE, plan._manifest_before, plan._manifest_after)]
        journal = {"schema": 1, "action": plan.action, "game": str(plan.game), "profile": str(plan.profile), "phase": "preparing", "operations": []}
        attempted = []
        try:
            for index, change in enumerate(operations):
                record = change.to_dict()
                record["before_backup"] = None
                if change.before is not None:
                    backup = transaction / f"before-{index}.bin"
                    _atomic_write(backup, change.before)
                    record["before_backup"] = str(backup.relative_to(plan.state_root))
                journal["operations"].append(record)
            for path, data in plan._backups:
                _mkdirs(path.parent, created)
                existing = _read(path)
                if existing is not None and existing != data:
                    raise ConflictError([f"Original backup already exists: {path}"])
                if existing is None:
                    _atomic_write(path, data)
            journal["phase"] = "applying"
            _atomic_write(journal_path, _json_bytes(journal))
            _atomic_write(pending_path, _json_bytes({"journal": str(journal_path.relative_to(plan.state_root))}))
            for change in operations:
                _stopped(game_running)
                if _read(change.path) != change.before:
                    raise ConflictError([f"File changed during installation: {change.path}"])
                _mkdirs(change.path.parent, created)
                attempted.append(change)
                _write_target(change.path, change.after)
            journal["phase"] = "complete"
            _atomic_write(journal_path, _json_bytes(journal))
            pending_path.unlink()
        except BaseException as exc:
            rollback_errors = []
            for change in reversed(attempted):
                try:
                    current = _read(change.path)
                    if current == change.before:
                        continue
                    if current != change.after:
                        raise ConflictError([f"File changed during rollback; preserved for manual recovery: {change.path}"])
                    _write_target(change.path, change.before)
                except BaseException as restore_exc:
                    rollback_errors.append(f"{change.path}: {restore_exc}")
            journal.update(phase="recovery_required" if rollback_errors else "rolled_back", error=str(exc), rollback_errors=rollback_errors)
            try:
                _atomic_write(journal_path, _json_bytes(journal))
                if not rollback_errors:
                    pending_path.unlink(missing_ok=True)
                else:
                    _atomic_write(pending_path, _json_bytes({"journal": str(journal_path.relative_to(plan.state_root))}))
            except BaseException as record_exc:
                rollback_errors.append(f"Could not finalize recovery journal: {record_exc}")
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise ApplyError(exc, journal_path, rollback_errors) from exc
        return ApplyResult(plan.action, plan.version, tuple(str(change.path) for change in plan.changes), plan.state_root, journal_path, True)
