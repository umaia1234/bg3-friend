"""Scoped doctor checks use only isolated fixtures and mocked CLI/process results."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from companion import installation
from scripts import doctor


@pytest.fixture
def environment(tmp_path, monkeypatch):
    game, profile = tmp_path / "Other Drive/Game", tmp_path / "다른 사용자/Profile"
    (game / "bin").mkdir(parents=True)
    (game / "bin/bg3_dx11.exe").write_bytes(b"fixture-game")
    (game / "bin/DWrite.dll").write_bytes(b"existing-extender")
    settings = profile / "PlayerProfiles/Public/modsettings.lsx"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b'<save><region id="ModuleSettings"><node id="root"><children><node id="Mods"><children><node id="ModuleShortDesc"><attribute id="UUID" value="other-mod"/></node></children></node></children></node></region></save>')
    package = tmp_path / "BG3Friend.pak"
    package.write_bytes(b"LSPK\x12\0\0\0fixture-package")
    checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    plan = installation.plan_install(game, profile, package, tmp_path / "state", version="test",
                                    package_sha256=checksum, game_running=False)
    installation.apply_plan(plan, game_running=False)
    io = profile / "Script Extender/BG3Friend"
    io.mkdir(parents=True)
    codex = tmp_path / "mock-codex.exe"
    codex.write_bytes(b"not-an-executable")
    calls = []

    def run(executable, arguments, **kwargs):
        args = [executable, *arguments]
        calls.append(args)
        assert args == [str(codex), "login", "status"], "No real subprocess is allowed in fixture checks"
        return 0, "private account text"

    monkeypatch.setattr(doctor, "probe_cli", run)
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: pytest.fail("real subprocess is forbidden"))
    monkeypatch.setattr(doctor, "find_codex", lambda: str(codex))
    monkeypatch.setattr(doctor, "bundle_package", lambda: (package, {"version": "test", "mod_version64": installation.MOD_VERSION64,
                                                                  "package": {"path": package.name, "sha256": checksum}}))
    monkeypatch.setattr(doctor, "game_is_running", lambda: True)
    args = ["--game", str(game), "--io", str(io), "--json"]
    return SimpleNamespace(root=tmp_path, game=game, profile=profile, settings=settings, package=package,
                           checksum=checksum, io=io, codex=codex, calls=calls, args=args)


def output(capsys):
    value = json.loads(capsys.readouterr().out)
    return value, {check["id"]: check for check in value["checks"]}


def files(folder):
    return {str(path.relative_to(folder)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()}


def test_installation_success_is_read_only_and_does_not_probe(environment, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "probe", lambda *args: pytest.fail("default diagnostic must not call a model"))
    before = files(environment.root)
    assert doctor.main(environment.args) == 0
    result, checks = output(capsys)
    assert result["scope"] == "installation" and result["ok"] and not result["model_called"]
    assert checks["installed_package"]["ok"] and checks["registration"]["ok"]
    assert "snapshot" not in checks and "private account text" not in json.dumps(result)
    assert files(environment.root) == before
    assert environment.calls == [[str(environment.codex), "login", "status"]]


def test_account_success_does_not_claim_installation(environment, capsys):
    assert doctor.main(["--scope", "account", "--json"]) == 0
    result, checks = output(capsys)
    assert result["scope"] == "account" and result["ok"]
    assert set(checks) == {"python", "codex", "login"}


def test_default_requires_explicit_game_and_io_even_when_logged_in(environment, capsys):
    assert doctor.main(["--json"]) == 1
    result, checks = output(capsys)
    assert checks["login"]["ok"]
    assert not checks["game_path"]["ok"] and not checks["io_path"]["ok"]
    assert not result["ok"]


@pytest.mark.parametrize("target,check", [("game_exe", "game_executable"), ("extender", "extender"),
                                          ("package", "installed_package"), ("settings", "registration")])
def test_missing_installation_prerequisite_is_nonzero(environment, capsys, target, check):
    paths = {"game_exe": environment.game / "bin/bg3_dx11.exe", "extender": environment.game / "bin/DWrite.dll",
             "package": environment.profile / "Mods/BG3Friend.pak", "settings": environment.settings}
    paths[target].unlink()
    assert doctor.main(environment.args) == 1
    _, checks = output(capsys)
    assert not checks[check]["ok"]


@pytest.mark.parametrize("replacement", [b"different package", b"LSPK\x12\0\0\0other version"])
def test_modified_installed_package_is_nonzero(environment, capsys, replacement):
    (environment.profile / "Mods/BG3Friend.pak").write_bytes(replacement)
    assert doctor.main(environment.args) == 1
    _, checks = output(capsys)
    assert not checks["installed_package"]["ok"]


@pytest.mark.parametrize("problem", ["malformed", "wrong_folder", "wrong_version", "duplicate", "duplicate_mods", "missing_order_entry"])
def test_invalid_registration_is_nonzero(environment, capsys, problem):
    if problem == "malformed":
        environment.settings.write_bytes(b"not-xml")
    else:
        root = ET.fromstring(environment.settings.read_bytes())
        mods = root.find(".//node[@id='Mods']/children")
        friend = [node for node in mods if node.find(f"attribute[@id='UUID'][@value='{installation.MOD_UUID}']") is not None][0]
        if problem == "wrong_folder":
            friend.find("attribute[@id='Folder']").set("value", "different")
        elif problem == "wrong_version":
            friend.find("attribute[@id='Version64']").set("value", "1")
        elif problem == "duplicate":
            mods.append(ET.fromstring(ET.tostring(friend)))
        elif problem == "duplicate_mods":
            ET.SubElement(root.find("./region/node/children"), "node", id="Mods")
        else:
            children = root.find("./region/node/children")
            ET.SubElement(ET.SubElement(children, "node", id="ModOrder"), "children")
        environment.settings.write_bytes(ET.tostring(root))
    assert doctor.main(environment.args) == 1
    _, checks = output(capsys)
    assert not checks["registration"]["ok"]


def test_unavailable_release_manifest_is_not_ready(environment, monkeypatch, capsys):
    def missing():
        raise ValueError("no bundle")
    monkeypatch.setattr(doctor, "bundle_package", missing)
    assert doctor.main(environment.args) == 1
    _, checks = output(capsys)
    assert not checks["release_package"]["ok"] and not checks["installed_package"]["ok"]
    assert doctor.main(environment.args + ["--package", str(environment.package), "--package-sha256", environment.checksum]) == 0
    output(capsys)


def test_explicit_manifest_and_bad_checksum(environment, capsys):
    manifest = environment.root / "manifest.json"
    manifest.write_text(json.dumps({"version": "test", "mod_version64": installation.MOD_VERSION64,
                                   "package": {"path": environment.package.name, "sha256": environment.checksum}}))
    assert doctor.main(environment.args + ["--manifest", str(manifest)]) == 0
    output(capsys)
    assert doctor.main(environment.args + ["--manifest", str(manifest), "--package-sha256", "0" * 64]) == 1
    _, checks = output(capsys)
    assert not checks["release_package"]["ok"]


@pytest.mark.parametrize("failure", ["missing", "login", "timeout", "oserror"])
def test_account_failures_are_nonzero_and_do_not_expose_cli_output(environment, monkeypatch, capsys, failure):
    if failure == "missing":
        monkeypatch.setattr(doctor, "find_codex", lambda: None)
    else:
        def failed(executable, arguments, **kwargs):
            if failure == "timeout":
                raise doctor.ModelFailure("timeout", "private account text")
            if failure == "oserror":
                raise OSError("private account text")
            return 1, "private account text"
        monkeypatch.setattr(doctor, "probe_cli", failed)
    assert doctor.main(["--scope", "account", "--json"]) == 1
    result, checks = output(capsys)
    assert not checks["login"]["ok"] and "private account text" not in json.dumps(result)


def test_gui_runtime_requires_working_native_python(environment, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "gui_runtime", lambda path: False)
    assert doctor.main(environment.args + ["--require-gui"]) == 1
    _, checks = output(capsys)
    assert not checks["gui_runtime"]["ok"]
    windows_python = environment.root / "different Python/python.exe"
    windows_python.parent.mkdir()
    windows_python.write_bytes(b"fixture-python")
    monkeypatch.setattr(doctor, "gui_runtime", lambda path: path == windows_python)
    assert doctor.main(environment.args + ["--require-gui", "--windows-python", str(windows_python)]) == 0
    _, checks = output(capsys)
    assert checks["gui_runtime"]["ok"]


def live_fixture(environment):
    (environment.io / "snapshot.json").write_text(json.dumps({"protocol": 1, "session": "fixture-session", "player": {"id": "fixture-player"}}))
    (environment.io / "runner.json").write_text(json.dumps({"session": "fixture-session", "runner": "ready"}))


def test_game_scope_requires_fresh_matching_runner_and_snapshot(environment, capsys):
    args = environment.args + ["--scope", "game"]
    assert doctor.main(args) == 1
    _, checks = output(capsys)
    assert not checks["snapshot"]["ok"] and not checks["runner_connection"]["ok"]
    live_fixture(environment)
    assert doctor.main(args) == 0
    result, checks = output(capsys)
    assert checks["snapshot"]["ok"] and checks["runner_connection"]["ok"]
    assert "fixture-session" not in json.dumps(result) and "fixture-player" not in json.dumps(result)


@pytest.mark.parametrize("problem", ["stale", "runner_stale", "session", "invalid_protocol", "invalid_player", "stopped"])
def test_live_invalid_or_old_evidence_cannot_report_success(environment, capsys, problem):
    live_fixture(environment)
    if problem == "stale":
        os.utime(environment.io / "snapshot.json", (1, 1))
    elif problem == "runner_stale":
        os.utime(environment.io / "runner.json", (1, 1))
    elif problem == "session":
        (environment.io / "runner.json").write_text('{"runner":"ready","session":"other"}')
    elif problem == "stopped":
        (environment.io / "runner.json").write_text('{"runner":"stopped","session":"fixture-session"}')
    else:
        snapshot = json.loads((environment.io / "snapshot.json").read_text(encoding="utf-8"))
        snapshot["protocol" if problem == "invalid_protocol" else "player"] = 99
        (environment.io / "snapshot.json").write_text(json.dumps(snapshot))
    assert doctor.main(environment.args + ["--scope", "game"]) == 1
    result, _ = output(capsys)
    assert not result["ok"]


def test_game_process_check_failure_is_nonzero(environment, monkeypatch, capsys):
    live_fixture(environment)
    def failure():
        raise installation.PreflightError("fixture process query failed")
    monkeypatch.setattr(doctor, "game_is_running", failure)
    assert doctor.main(environment.args + ["--scope", "game"]) == 1
    _, checks = output(capsys)
    assert not checks["game_running"]["ok"]


def test_probe_is_explicit_once_synthetic_and_never_writes_game_files(environment, monkeypatch, capsys):
    calls = []
    class FakeModel:
        def __init__(self, **kwargs):
            assert kwargs == {"model": "fixture-model", "executable": str(environment.codex)}
        def decide(self, scene, memory, messages):
            calls.append(scene)
            assert scene["session"] == "probe" and memory == []
            return {"say": "기다릴게.", "action": "wait", "target": "", "reason": "request", "remember": "", "stance": "hold"}, 1.25
    monkeypatch.setattr(doctor, "CodexModel", FakeModel)
    before = files(environment.root)
    assert doctor.main(["--scope", "account", "--json", "--probe", "--model", "fixture-model"]) == 0
    result, checks = output(capsys)
    assert result["model_called"] and checks["model_response"]["ok"] and len(calls) == 1
    assert result["probe"]["seconds"] == 1.25 and files(environment.root) == before


def test_probe_never_runs_when_required_checks_fail(environment, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "probe", lambda *args: pytest.fail("failed preflight must not call model"))
    assert doctor.main(["--json", "--probe"]) == 1
    result, checks = output(capsys)
    assert not result["model_called"] and not checks["model_response"]["ok"]


def test_failed_probe_is_nonzero_without_raw_diagnostics(environment, monkeypatch, capsys):
    def failed(*args):
        raise RuntimeError("private account error")
    monkeypatch.setattr(doctor, "probe", failed)
    assert doctor.main(["--scope", "account", "--json", "--probe"]) == 1
    result, _ = output(capsys)
    assert result["model_called"] and not result["ok"] and "private account error" not in json.dumps(result)
