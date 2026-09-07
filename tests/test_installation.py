"""Real filesystem transactions in tmp_path; no native process/game/model calls."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from companion import installation as installer


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_settings(*, friend=False, order=True):
    root = ET.fromstring('<save><version major="4"/><region id="ModuleSettings"><node id="root"><children><node id="Mods"><children/></node></children></node></region></save>')
    base = root.find("./region/node/children")
    mods = base.find("./node[@id='Mods']/children")
    ids = ["other-a", installer.MOD_UUID, "other-b"] if friend else ["other-a", "other-b"]
    for uid in ids:
        node = ET.SubElement(mods, "node", id="ModuleShortDesc")
        ET.SubElement(node, "attribute", id="Name", type="LSString", value="Existing " + uid)
        ET.SubElement(node, "attribute", id="UUID", type="guid", value=uid)
    if order:
        ordered = ET.SubElement(ET.SubElement(base, "node", id="ModOrder"), "children")
        for uid in reversed(ids):
            ET.SubElement(ET.SubElement(ordered, "node", id="Module"), "attribute", id="UUID", type="guid", value=uid)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@pytest.fixture
def layout(tmp_path):
    game = tmp_path / "Games with spaces" / "발더스"
    profile = tmp_path / "Other Windows User" / "App Data" / "BG3"
    state = tmp_path / "per-user-state"
    game.joinpath("bin").mkdir(parents=True)
    game.joinpath("bin/bg3_dx11.exe").write_bytes(b"MZ-fixture-game")
    settings = profile / "PlayerProfiles/Public/modsettings.lsx"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(make_settings())
    release = tmp_path / "release"
    release.mkdir()
    package = release / "BG3Friend.pak"
    package.write_bytes(b"LSPK" + struct.pack("<I", 18) + b"fixture-release-v1")
    extender = release / "DWrite.dll"
    extender.write_bytes(b"MZ-fixture-extender")
    return {"game": game, "profile": profile, "state": state, "package": package,
            "extender": extender, "settings": settings, "pak": profile / "Mods/BG3Friend.pak",
            "dll": game / "bin/DWrite.dll"}


def plan(layout, **overrides):
    arguments = {"game": layout["game"], "profile": layout["profile"], "package": layout["package"],
                 "state_root": layout["state"], "version": "1.0.0", "package_sha256": digest(layout["package"].read_bytes()),
                 "game_running": False, "extender": layout["extender"]}
    arguments.update(overrides)
    return installer.plan_install(**arguments)


def apply(layout, **overrides):
    return installer.apply_plan(plan(layout, **overrides), game_running=False)


def files_under(*roots):
    return {(str(root), str(path.relative_to(root))): path.read_bytes()
            for root in roots if root.exists() for path in root.rglob("*") if path.is_file()}


def state(layout):
    return json.loads((layout["state"] / installer.STATE_FILE).read_bytes())


def add_other_mod(layout, name="later-added-mod"):
    root = ET.fromstring(layout["settings"].read_bytes())
    for container in root.findall("./region/node/children/node/children"):
        node = ET.SubElement(container, "node", id="ModuleShortDesc")
        ET.SubElement(node, "attribute", id="UUID", type="guid", value=name)
    layout["settings"].write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def test_plan_only_reads_even_when_state_and_mods_directory_are_absent(layout):
    before = files_under(layout["game"], layout["profile"])
    preview = plan(layout)
    assert {change.role for change in preview.changes} == {"package", "settings", "extender"}
    assert preview.to_dict()["ready"] is True
    assert preview.to_dict()["changed"] is True
    assert not layout["state"].exists()
    assert not layout["pak"].parent.exists()
    assert files_under(layout["game"], layout["profile"]) == before


def test_install_keeps_debug_settings_and_other_mod_order(layout):
    debug = layout["game"] / "bin/ScriptExtenderSettings.json"
    debug.write_bytes(b'{"CreateConsole":false,"LogRuntime":false,"another_mod":17}\n')
    debug_before = debug.read_bytes()
    apply(layout)
    assert debug.read_bytes() == debug_before
    assert layout["pak"].read_bytes() == layout["package"].read_bytes()
    assert layout["dll"].read_bytes() == layout["extender"].read_bytes()
    tree = ET.fromstring(layout["settings"].read_bytes())
    assert tree.find("./region/node/children/node[@id='ModOrder']") is not None
    for container in tree.findall("./region/node/children/node/children"):
        ids = [node.find("./attribute[@id='UUID']").get("value") for node in container]
        assert ids.count(installer.MOD_UUID) == 1
        assert "other-a" in ids and "other-b" in ids
    assert state(layout)["version"] == "1.0.0"
    assert not (layout["state"] / "pending.json").exists()


def test_no_debug_settings_created_and_shared_extender_never_overwritten(layout):
    layout["dll"].write_bytes(b"preexisting-shared-extender")
    apply(layout)
    assert layout["dll"].read_bytes() == b"preexisting-shared-extender"
    assert "extender" not in {entry["role"] for entry in state(layout)["files"]}
    assert not (layout["game"] / "bin/ScriptExtenderSettings.json").exists()
    installer.apply_plan(installer.plan_uninstall(layout["state"], game_running=False), game_running=False)
    assert layout["dll"].read_bytes() == b"preexisting-shared-extender"


@pytest.mark.parametrize("fault", ["missing_settings", "bad_xml", "bad_layout", "missing_game", "bad_package", "bad_hash", "missing_extender"])
def test_invalid_prerequisites_leave_no_partial_install(layout, fault):
    overrides = {}
    if fault == "missing_settings":
        layout["settings"].unlink()
    elif fault == "bad_xml":
        layout["settings"].write_bytes(b"<broken>")
    elif fault == "bad_layout":
        layout["settings"].write_bytes(b"<save />")
    elif fault == "missing_game":
        (layout["game"] / "bin/bg3_dx11.exe").unlink()
    elif fault == "bad_package":
        layout["package"].write_bytes(b"this is not a Larian archive")
    elif fault == "bad_hash":
        overrides["package_sha256"] = "0" * 64
    else:
        overrides["extender"] = None
    before = files_under(layout["game"], layout["profile"])
    with pytest.raises(installer.PreflightError):
        plan(layout, **overrides)
    assert files_under(layout["game"], layout["profile"]) == before
    assert not layout["state"].exists()


@pytest.mark.parametrize("status", [True, None, 0, "false"])
def test_game_check_must_be_explicit_false(layout, status):
    with pytest.raises(installer.PreflightError):
        plan(layout, game_running=status)
    assert not layout["state"].exists()


def test_game_check_exception_and_change_before_apply_fail_closed(layout):
    def failed_check():
        raise OSError("process API unavailable")
    with pytest.raises(installer.PreflightError, match="determine"):
        plan(layout, game_running=failed_check)
    preview = plan(layout)
    with pytest.raises(installer.PreflightError, match="Close BG3"):
        installer.apply_plan(preview, game_running=True)
    assert not layout["state"].exists()


@pytest.mark.parametrize("failure_number", [1, 2, 3, 4])
def test_failure_at_each_commit_step_restores_all_files_and_allows_retry(layout, monkeypatch, failure_number):
    before = files_under(layout["game"], layout["profile"])
    preview = plan(layout)
    write = installer._write_target
    calls = 0

    def fail_once(path, data):
        nonlocal calls
        calls += 1
        if calls == failure_number:
            raise OSError("injected write failure")
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(installer, "_write_target", fail_once)
        with pytest.raises(installer.ApplyError) as failed:
            installer.apply_plan(preview, game_running=False)
    assert failed.value.rolled_back
    assert files_under(layout["game"], layout["profile"]) == before
    assert not (layout["state"] / installer.STATE_FILE).exists()
    assert not (layout["state"] / "pending.json").exists()
    assert json.loads(failed.value.journal.read_bytes())["phase"] == "rolled_back"
    installer.apply_plan(preview, game_running=False)
    assert layout["pak"].read_bytes() == layout["package"].read_bytes()


def test_game_starting_during_apply_rolls_back(layout):
    before = files_under(layout["game"], layout["profile"])
    preview = plan(layout)
    calls = 0

    def game_check():
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(installer.ApplyError) as failed:
        installer.apply_plan(preview, game_running=game_check)
    assert failed.value.rolled_back
    assert files_under(layout["game"], layout["profile"]) == before


def test_repeated_identical_install_is_noop(layout):
    apply(layout)
    before = files_under(layout["game"], layout["profile"], layout["state"])
    preview = plan(layout)
    assert preview.action == "update"
    assert not preview.changed
    assert installer.apply_plan(preview, game_running=False).changed is False
    assert files_under(layout["game"], layout["profile"], layout["state"]) == before


def test_three_updates_then_uninstall_restore_first_exact_originals(layout):
    layout["settings"].write_bytes(make_settings(friend=True))
    layout["pak"].parent.mkdir()
    layout["pak"].write_bytes(b"original preexisting package")
    before = files_under(layout["game"], layout["profile"])
    originals = None
    for number in range(3):
        layout["package"].write_bytes(b"LSPK" + struct.pack("<I", 18) + f"version-{number}".encode())
        apply(layout, version=f"1.0.{number}", mod_version64=str(int(installer.MOD_VERSION64) + number))
        backups = files_under(layout["state"] / "backups")
        if originals is None:
            originals = backups
        assert backups == originals
    installer.apply_plan(installer.plan_uninstall(layout["state"], game_running=False), game_running=False)
    assert files_under(layout["game"], layout["profile"]) == before
    assert not (layout["state"] / installer.STATE_FILE).exists()
    assert files_under(layout["state"] / "backups") == originals
    apply(layout)
    assert layout["pak"].read_bytes() == layout["package"].read_bytes()


@pytest.mark.parametrize("update_after_other_mod", [False, True])
def test_uninstall_preserves_mods_added_after_install_even_across_updates(layout, update_after_other_mod):
    apply(layout)
    add_other_mod(layout)
    if update_after_other_mod:
        for number in (2, 3):
            layout["package"].write_bytes(b"LSPK" + struct.pack("<I", 18) + str(number).encode())
            apply(layout, version=str(number), mod_version64=str(int(installer.MOD_VERSION64) + number))
    installer.apply_plan(installer.plan_uninstall(layout["state"], game_running=False), game_running=False)
    restored = layout["settings"].read_bytes()
    assert b"later-added-mod" in restored and b"other-a" in restored and b"other-b" in restored
    assert installer.MOD_UUID.encode() not in restored
    assert not layout["pak"].exists()
    assert not layout["dll"].exists()


def test_other_modorder_added_later_is_preserved(layout):
    layout["settings"].write_bytes(make_settings(order=False))
    apply(layout)
    root = ET.fromstring(layout["settings"].read_bytes())
    children = root.find("./region/node/children")
    order = ET.SubElement(ET.SubElement(children, "node", id="ModOrder"), "children")
    ET.SubElement(ET.SubElement(order, "node", id="Module"), "attribute", id="UUID", value="another-mod")
    layout["settings"].write_bytes(ET.tostring(root))
    apply(layout, version="2")
    installer.apply_plan(installer.plan_uninstall(layout["state"], game_running=False), game_running=False)
    assert b"another-mod" in layout["settings"].read_bytes()


@pytest.mark.parametrize("action", ["update", "uninstall"])
def test_conflicts_report_all_managed_file_and_registration_changes_before_writes(layout, action):
    apply(layout)
    layout["pak"].write_bytes(b"user-replaced-package")
    layout["dll"].write_bytes(b"user-updated-owned-extender")
    data = layout["settings"].read_bytes().replace(b'BG3 Friend', b'My changed Friend')
    layout["settings"].write_bytes(data)
    before = files_under(layout["game"], layout["profile"], layout["state"])
    with pytest.raises(installer.ConflictError) as conflict:
        if action == "update":
            plan(layout, version="2")
        else:
            installer.plan_uninstall(layout["state"], game_running=False)
    assert len(conflict.value.conflicts) == 3
    assert files_under(layout["game"], layout["profile"], layout["state"]) == before


def test_file_changes_after_preview_are_rejected_before_state_creation(layout):
    preview = plan(layout)
    add_other_mod(layout)
    before = files_under(layout["game"], layout["profile"])
    with pytest.raises(installer.ConflictError, match="after preview"):
        installer.apply_plan(preview, game_running=False)
    assert files_under(layout["game"], layout["profile"]) == before
    assert not layout["state"].exists()


def test_update_failure_keeps_previous_install_and_first_backups(layout, monkeypatch):
    apply(layout)
    before = files_under(layout["game"], layout["profile"])
    manifest = (layout["state"] / installer.STATE_FILE).read_bytes()
    backup = files_under(layout["state"] / "backups")
    layout["package"].write_bytes(b"LSPK" + struct.pack("<I", 18) + b"new version")
    preview = plan(layout, version="2", mod_version64=str(int(installer.MOD_VERSION64) + 1))
    write = installer._write_target

    def fail_settings(path, data):
        if path == layout["settings"] and data != before[(str(layout["profile"]), "PlayerProfiles/Public/modsettings.lsx")]:
            raise OSError("injected update failure")
        write(path, data)

    monkeypatch.setattr(installer, "_write_target", fail_settings)
    with pytest.raises(installer.ApplyError) as failed:
        installer.apply_plan(preview, game_running=False)
    assert failed.value.rolled_back
    assert files_under(layout["game"], layout["profile"]) == before
    assert (layout["state"] / installer.STATE_FILE).read_bytes() == manifest
    assert files_under(layout["state"] / "backups") == backup


def test_uninstall_failure_restores_complete_current_installation(layout, monkeypatch):
    apply(layout)
    before = files_under(layout["game"], layout["profile"])
    manifest = (layout["state"] / installer.STATE_FILE).read_bytes()
    preview = installer.plan_uninstall(layout["state"], game_running=False)
    write = installer._write_target
    failed_once = False

    def fail_second(path, data):
        nonlocal failed_once
        if path == layout["settings"] and not failed_once:
            failed_once = True
            raise OSError("injected removal failure")
        write(path, data)

    monkeypatch.setattr(installer, "_write_target", fail_second)
    with pytest.raises(installer.ApplyError) as failed:
        installer.apply_plan(preview, game_running=False)
    assert failed.value.rolled_back
    assert files_under(layout["game"], layout["profile"]) == before
    assert (layout["state"] / installer.STATE_FILE).read_bytes() == manifest


def test_rollback_failure_is_recorded_and_blocks_blind_retry(layout, monkeypatch):
    preview = plan(layout)
    write = installer._write_target

    def fail_apply_and_restore(path, data):
        if path == layout["settings"] or (path == layout["pak"] and data is None):
            raise OSError("injected persistent failure")
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(installer, "_write_target", fail_apply_and_restore)
        with pytest.raises(installer.ApplyError) as failed:
            installer.apply_plan(preview, game_running=False)
    assert not failed.value.rolled_back
    assert failed.value.rollback_errors
    journal = json.loads(failed.value.journal.read_bytes())
    assert journal["phase"] == "recovery_required"
    assert (layout["state"] / "pending.json").exists()
    assert any(item["path"] == str(layout["pak"]) for item in journal["operations"])
    with pytest.raises(installer.PreflightError, match="interrupted"):
        plan(layout)


@pytest.mark.parametrize("phase", ["applying", "preparing", "recovery_required", "unknown", "corrupt", "missing"])
def test_journal_without_pending_marker_blocks_plan_without_writes(layout, phase):
    apply(layout)
    transaction = layout["state"] / "transactions" / ("f" * 32)
    transaction.mkdir()
    journal = transaction / "journal.json"
    if phase == "corrupt":
        journal.write_bytes(b"broken-json")
    elif phase != "missing":
        journal.write_text(json.dumps({"schema": 1, "action": "update", "phase": phase, "operations": []}), encoding="utf-8")
    assert not (layout["state"] / "pending.json").exists()
    before = files_under(layout["game"], layout["profile"], layout["state"])
    for operation in (lambda: plan(layout), lambda: installer.plan_uninstall(layout["state"], game_running=False)):
        with pytest.raises(installer.PreflightError, match="needs recovery") as failed:
            operation()
        assert str(journal) in str(failed.value)
    assert files_under(layout["game"], layout["profile"], layout["state"]) == before


def test_forced_process_exit_leaves_recovery_gate_even_if_pending_marker_is_lost(layout):
    script = '''
import hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from companion import installation as engine
layout = {key: Path(value) for key, value in json.loads(sys.argv[2]).items()}
write = engine._write_target
def crash_after_first_game_file(path, data):
    write(path, data)
    if path == layout['pak']:
        os._exit(73)
engine._write_target = crash_after_first_game_file
plan = engine.plan_install(layout['game'], layout['profile'], layout['package'], layout['state'],
    version='crash-fixture', package_sha256=hashlib.sha256(layout['package'].read_bytes()).hexdigest(),
    game_running=False, extender=layout['extender'])
engine.apply_plan(plan, game_running=False)
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(Path(installer.__file__).resolve().parents[1]),
                             json.dumps({key: str(path) for key, path in layout.items()})],
                            cwd=layout["state"].parent, capture_output=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 73
    assert layout["pak"].read_bytes() == layout["package"].read_bytes()
    pending = layout["state"] / "pending.json"
    assert pending.exists()
    pending.unlink()  # Model a missing marker; the durable applying journal remains.
    journal = next((layout["state"] / "transactions").glob("*/journal.json"))
    assert json.loads(journal.read_bytes())["phase"] == "applying"
    before = files_under(layout["game"], layout["profile"], layout["state"])
    with pytest.raises(installer.PreflightError, match="needs recovery") as failed:
        plan(layout)
    assert str(journal) in str(failed.value)
    with pytest.raises(installer.PreflightError, match="needs recovery"):
        installer.plan_uninstall(layout["state"], game_running=False)
    assert files_under(layout["game"], layout["profile"], layout["state"]) == before


def test_corrupt_first_backup_blocks_update_and_uninstall(layout):
    apply(layout)
    entry = next(entry for entry in state(layout)["files"] if entry["role"] == "settings")
    (layout["state"] / entry["backup"]).write_bytes(b"corrupt backup")
    before = files_under(layout["game"], layout["profile"])
    with pytest.raises(installer.PreflightError, match="damaged"):
        plan(layout, version="2")
    with pytest.raises(installer.PreflightError, match="damaged"):
        installer.plan_uninstall(layout["state"], game_running=False)
    assert files_under(layout["game"], layout["profile"]) == before


def test_empty_preexisting_package_is_restored(layout):
    layout["pak"].parent.mkdir()
    layout["pak"].write_bytes(b"")
    apply(layout)
    installer.apply_plan(installer.plan_uninstall(layout["state"], game_running=False), game_running=False)
    assert layout["pak"].exists() and layout["pak"].read_bytes() == b""


def test_overlapping_state_and_game_paths_rejected(layout):
    with pytest.raises(installer.PreflightError, match="separate"):
        plan(layout, state_root=layout["profile"] / "installation-state")


def test_linked_destination_cannot_write_outside_confirmed_tree(layout, tmp_path):
    outside = tmp_path / "unrelated.txt"
    outside.write_bytes(b"unrelated user file")
    layout["pak"].parent.mkdir()
    try:
        layout["pak"].symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit fixture symlinks")
    with pytest.raises(installer.PreflightError, match="linked"):
        plan(layout)
    assert outside.read_bytes() == b"unrelated user file"
    assert not layout["state"].exists()


def test_state_cannot_redirect_a_managed_file(layout, tmp_path):
    apply(layout)
    manifest_path = layout["state"] / installer.STATE_FILE
    manifest = state(layout)
    manifest["files"][0]["path"] = str(tmp_path / "unrelated.txt")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(installer.PreflightError, match="managed file path"):
        installer.plan_uninstall(layout["state"], game_running=False)
