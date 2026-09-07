"""Registration and Windows PowerShell behavior using isolated files and fake processes.

The tiny diagnostic fixture is not BG3 Friend: it only copies a supplied report.
No test starts a game, native app GUI, runner, login or model request.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".agents/skills/bg3-friend-start"
spec = importlib.util.spec_from_file_location("native_skill_installer", REPO / "scripts/install_skill.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def native_config(**extra):
    return {"repository": "https://github.com/umaia1234/bg3-friend", "steamAppId": "1086940",
            "nativeExe": "C:/Apps/BG3Friend/BG3Friend.exe", "nativeConfigRoot": "D:/My Games/Friend settings", **extra}


def test_native_registration_needs_no_wsl_or_system_python(tmp_path):
    source = tmp_path / "repository/.agents/skills/bg3-friend-start"
    for name in installer.FILES:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL / name, destination)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(native_config()), encoding="utf-8")
    target = tmp_path / "skills/bg3-friend-start"
    preview = installer.register(config, target, root=tmp_path / "repository")
    assert len(preview["changed_files"]) == 5 and not target.exists()
    installer.register(config, target, root=tmp_path / "repository", apply=True)
    assert installer.read_config(target / "project.local.json") == native_config()
    repeated = installer.register(config, target, root=tmp_path / "repository", apply=True)
    assert repeated["changed_files"] == [] and repeated["backup"] is None


@pytest.mark.parametrize("field,value", [("nativeExe", "relative/BG3Friend.exe"),
                                        ("nativeConfigRoot", "C:relative"),
                                        ("nativeExe", "C:/Apps/app.cmd"),
                                        ("nativeExe", True), ("nativeConfigRoot", "C:/YOUR_ROOT")])
def test_native_registration_rejects_unresolved_or_invalid_paths(field, value):
    with pytest.raises(ValueError):
        installer.validate_config(native_config(**{field: value}))


def test_optional_native_settings_do_not_require_fake_source_paths():
    config = native_config()
    del config["nativeConfigRoot"]
    installer.validate_config(config)
    config["nativeExe"] = ""
    with pytest.raises(ValueError, match="distro"):
        installer.validate_config(config)


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def windows_path(path):
    if os.name == "nt":
        return str(path)
    return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()


@pytest.fixture(scope="module")
def windows_workspace():
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell integration requires Windows or WSL interop")
    result = subprocess.run([powershell, "-NoProfile", "-Command",
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); [Console]::Write([IO.Path]::GetTempPath())"],
        capture_output=True, timeout=10, check=True)
    base_windows = result.stdout.decode("utf-8")
    base = Path(base_windows) if os.name == "nt" else Path(subprocess.check_output(
        ["wslpath", "-u", base_windows], text=True).strip())
    with tempfile.TemporaryDirectory(prefix="bg3-native-skill-", dir=base) as directory:
        root = Path(directory)
        assert base.resolve() in root.resolve().parents
        script = root / "start.ps1"
        shutil.copy2(SKILL / "scripts/start.ps1", script)
        yield powershell, root, script


def run_ps(workspace, body, *, definitions=False, expected=0):
    powershell, root, script = workspace
    prefix = "$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
    if definitions:
        prefix += ("$tokens=$null; $errors=$null\n$ast=[Management.Automation.Language.Parser]::ParseFile("
                   + ps_quote(windows_path(script)) + ",[ref]$tokens,[ref]$errors)\n"
                   "if ($errors.Count) { throw ($errors | Out-String) }\n"
                   "foreach ($statement in $ast.EndBlock.Statements) {\n"
                   " if ($statement -is [Management.Automation.Language.FunctionDefinitionAst]) {\n"
                   "  . ([scriptblock]::Create($statement.Extent.Text))\n }\n}\n")
    wrapper = root / "test-invocation.ps1"
    wrapper.write_text(prefix + body, encoding="utf-8-sig")
    result = subprocess.run([powershell, "-NoProfile", "-File", windows_path(wrapper)],
                            capture_output=True, timeout=45)
    stdout = result.stdout.decode("utf-8", errors="strict")
    assert result.returncode == expected, (result.returncode, stdout, result.stderr)
    assert "\ufffd" not in stdout
    return json.loads(stdout)


def ps_json(name, value):
    return "$" + name + " = ConvertFrom-Json -InputObject @'\n" + json.dumps(value) + "\n'@\n"


def test_default_app_state_ignores_packaged_parent_localappdata(windows_workspace):
    fake = windows_path(windows_workspace[1] / "Packages/FakeCodex/LocalCache/Local")
    result = run_ps(windows_workspace, "$env:LOCALAPPDATA=" + ps_quote(fake) + "\n"
        "@{actual=(Get-Bg3UserSavedGames); redirected=$env:LOCALAPPDATA} | ConvertTo-Json", definitions=True)
    assert result["actual"] != fake and result["redirected"] == fake
    assert "/Packages/FakeCodex/" not in result["actual"].replace("\\", "/")


def state(workspace, **changes):
    evidence = {"runner": {"runner": "paused", "session": "current", "calls": 20},
                "snapshot": {"protocol": 1, "session": "current", "companion": {"name": "섀도하트"}},
                "runnerAge": 1, "snapshotAge": 1, "game": [{"Id": 1}], "launcher": [],
                "processes": {"apps": [{"ProcessId": 2}], "workers": [{"ProcessId": 3}],
                              "overlays": [{"ProcessId": 4}], "source_overlays": []},
                "ownerAlive": True, "backend": "native", **changes}
    return run_ps(workspace, ps_json("e", evidence) +
        "Resolve-Bg3RuntimeState $e.runner $e.snapshot $e.runnerAge $e.snapshotAge $e.game $e.launcher $e.processes $e.ownerAlive $e.backend | ConvertTo-Json -Depth 10", definitions=True)


def test_native_state_requires_fresh_matching_game_and_runner(windows_workspace):
    assert state(windows_workspace)["game_connected"] is True
    assert state(windows_workspace)["model_connection"] == "not_verified"  # calls are not successful responses.
    for change in ({"snapshotAge": 5}, {"runnerAge": 9}, {"ownerAlive": False}, {"game": []},
                   {"runner": {"runner": "unknown", "session": "current"}},
                   {"snapshot": {"protocol": 1, "session": "old"}}):
        assert state(windows_workspace, **change)["game_connected"] is False


def test_model_error_does_not_erase_verified_game_connection(windows_workspace):
    result = state(windows_workspace, runner={"runner": "error", "session": "current",
        "error_code": "login_required", "error": "로그인이 필요합니다."})
    assert result["game_connected"] and result["game_connection"] == "connected"
    assert result["mode"] == "model_error" and result["model_connection"] == "error"
    assert result["runner_error"] == "로그인이 필요합니다."


def test_main_app_is_distinct_from_worker_overlay_and_other_profile(windows_workspace):
    exe, root, io = "C:/Apps/BG3Friend.exe", "D:/Friend state", "D:/Game profile/Script Extender/BG3Friend"
    processes = [
        {"ProcessId": 1, "ExecutablePath": exe, "CommandLine": f'"{exe}" --config-root "{root}"'},
        {"ProcessId": 2, "ExecutablePath": exe, "CommandLine": f'"{exe}" --worker --config-root "{root}"'},
        {"ProcessId": 3, "ExecutablePath": exe, "CommandLine": f'"{exe}" --overlay --io "{io}"'},
        {"ProcessId": 4, "ExecutablePath": exe, "CommandLine": f'"{exe}" --config-root "D:/Other"'},
        {"ProcessId": 5, "ExecutablePath": exe, "CommandLine": f'"{exe}" --diagnose --config-root "{root}"'},
        {"ProcessId": 6, "ExecutablePath": "C:/Python/pythonw.exe", "CommandLine": f'pythonw.exe "C:/Old checkout/companion/gui.py" --io "{io}"'},
        {"ProcessId": 7, "ExecutablePath": exe, "CommandLine": f'"{exe}" --status --config-root "{root}"'},
    ]
    result = run_ps(windows_workspace, ps_json("p", processes) + "Select-Bg3Processes $p " +
        " ".join(ps_quote(v) for v in (exe, root, "C:/Default state", io)) + " | ConvertTo-Json -Depth 6", definitions=True)
    assert [p["ProcessId"] for p in result["apps"]] == [1]
    assert [p["ProcessId"] for p in result["workers"]] == [2]
    assert [p["ProcessId"] for p in result["overlays"]] == [3, 6]
    main_only = state(windows_workspace, runner=None, runnerAge=None, ownerAlive=None,
        processes={"apps": [{"ProcessId": 1}], "workers": [], "overlays": [], "source_overlays": []})
    assert main_only["mode"] == "app_ready" and not main_only["helper_running"] and not main_only["game_connected"]


@pytest.fixture(scope="module")
def diagnostic_fixture(windows_workspace):
    _, root, _ = windows_workspace
    exe = root / "BG3Friend.exe"
    source = r'''using System;
using System.IO;
using System.Text;
public class Fixture {
    public static int Main(string[] args) {
        int c=Array.IndexOf(args,"--config-root"), r=Array.IndexOf(args,"--report");
        if(Array.IndexOf(args,"--diagnose")<0 || c<0 || r<0) return 91;
        string folder=args[c+1];
        File.WriteAllLines(Path.Combine(folder,"received-arguments.txt"),args,new UTF8Encoding(false));
        File.Copy(Path.Combine(folder,"fixture-report.json"),args[r+1],true);
        return Int32.Parse(File.ReadAllText(Path.Combine(folder,"fixture-exit.txt")));
    }
}'''
    run_ps(windows_workspace, "$source=@'\n" + source + "\n'@\nAdd-Type -TypeDefinition $source -OutputAssembly " +
           ps_quote(windows_path(exe)) + " -OutputType ConsoleApplication\n'{\"compiled\":true}'")
    return exe


def native_invocation(workspace, exe, *, missing=(), malformed=False, action="Check", existing_app=False, allow_launch=False):
    _, root, script = workspace
    settings_root = root / "한글 설정's folder"
    settings_root.mkdir(exist_ok=True)
    profile = root / "isolated game profile"
    settings = {"version": 1, "game": "", "profile": windows_path(profile), "codex": "", "model": "gpt-6-astra", "timeout": 45, "consent": not missing}
    (settings_root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    ids = ("game", "profile", "extender", "codex", "package", "installed", "login", "consent")
    report = {"checks": [] if malformed else [{"id": key, "ok": key not in missing} for key in ids], "runtime": {}}
    (settings_root / "fixture-report.json").write_text(json.dumps(report), encoding="utf-8")
    (settings_root / "fixture-exit.txt").write_text("2" if missing else "0", encoding="ascii")
    config = root / "native.local.json"
    config.write_text(json.dumps(native_config(nativeExe=windows_path(exe), nativeConfigRoot=windows_path(settings_root))), encoding="utf-8")
    process = {"ProcessId": 1234, "Name": "BG3Friend.exe", "ExecutablePath": windows_path(exe),
               "CommandLine": f'"{windows_path(exe)}" --config-root "{windows_path(settings_root)}"'}
    # Mock only process observations and Start-Process; the diagnostic .exe really runs.
    body = ps_json("observed", [process] if existing_app else [])
    body += "function Get-CimInstance { param($Filter,$ClassName); return $observed }\n"
    body += "function Get-Process { param($Name,$Id,$ErrorAction); return @() }\n"
    if allow_launch:
        body += ("function Start-Process { param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru); "
                 "@{executable=$FilePath;arguments=$ArgumentList;style=$WindowStyle} | ConvertTo-Json | "
                 "Set-Content -Encoding UTF8 -LiteralPath " + ps_quote(windows_path(settings_root / "launch.json")) + " }\n")
    else:
        body += "function Start-Process { param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru); throw 'A Start-Process call was not expected.' }\n"
    body += "& " + ps_quote(windows_path(script)) + " -Action " + action + " -HelperOnly -WaitSeconds 0 -ConfigPath " + ps_quote(windows_path(config)) + "\nexit $LASTEXITCODE"
    expected = 1 if missing or malformed or not exe.exists() or (action == "Start" and not existing_app) else 0
    return run_ps(workspace, body, expected=expected), settings_root


def test_native_diagnostic_report_and_quoted_unicode_path(windows_workspace, diagnostic_fixture):
    result, folder = native_invocation(windows_workspace, diagnostic_fixture)
    assert result["backend"] == "native" and result["preflight"]["ready"]
    arguments = (folder / "received-arguments.txt").read_text(encoding="utf-8").splitlines()
    assert arguments[arguments.index("--config-root") + 1] == windows_path(folder)
    assert "--start" not in arguments
    report_path = Path(arguments[-1]) if os.name == "nt" else Path(subprocess.check_output(
        ["wslpath", "-u", arguments[-1]], text=True).strip())
    assert not report_path.exists()


def test_native_missing_checks_are_structured(windows_workspace, diagnostic_fixture):
    result, _ = native_invocation(windows_workspace, diagnostic_fixture, missing=("login", "consent"))
    assert result["preflight"]["ready"] is False
    assert result["preflight"]["setup_required"] == ["login", "consent"]
    assert result["preflight"]["doctor_exit_code"] == 2 and result["actions"] == []
    invalid, _ = native_invocation(windows_workspace, diagnostic_fixture, malformed=True)
    assert "native_diagnostic_report" in invalid["preflight"]["setup_required"]


def test_missing_native_exe_does_not_silently_fall_back_to_wsl(windows_workspace):
    result, _ = native_invocation(windows_workspace, windows_workspace[1] / "Missing-BG3Friend.exe")
    assert result["backend"] == "native" and result["preflight"]["missing"][0]["item"] == "native_executable"
    assert "needs_configuration" not in result and result["actions"] == []


def test_start_reuses_an_existing_main_window_without_spawning(windows_workspace, diagnostic_fixture):
    result, _ = native_invocation(windows_workspace, diagnostic_fixture, action="Start", existing_app=True)
    assert result["state"]["app_running"] and not result["state"]["helper_running"]
    assert result["actions"] == [] and "existing BG3 Friend window" in result["next"]


def test_start_opens_setup_without_auto_start_until_consent_is_ready(windows_workspace, diagnostic_fixture):
    result, folder = native_invocation(windows_workspace, diagnostic_fixture, action="Start", missing=("consent",), allow_launch=True)
    launch = json.loads((folder / "launch.json").read_text(encoding="utf-8-sig"))
    assert result["actions"] == ["setup_app_open_requested"]
    assert "--start" not in launch["arguments"] and launch["style"] == "Normal"
    assert json.loads((folder / "settings.json").read_text(encoding="utf-8"))["consent"] is False
    ready, folder = native_invocation(windows_workspace, diagnostic_fixture, action="Start", allow_launch=True)
    launch = json.loads((folder / "launch.json").read_text(encoding="utf-8-sig"))
    assert ready["actions"] == ["helper_launch_requested"] and "--start" in launch["arguments"]
    assert "not verified" in ready["error"]  # A simulated spawn is not proof of a live helper.
