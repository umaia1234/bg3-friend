"""CLI wiring with fake process checks and real temporary installation files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from companion import installation
from scripts import install, uninstall


@pytest.fixture
def cli(tmp_path, monkeypatch):
    game, profile, state = tmp_path / "Game", tmp_path / "Different User/Profile", tmp_path / "State"
    (game / "bin").mkdir(parents=True)
    (game / "bin/bg3_dx11.exe").write_bytes(b"fixture-game")
    (game / "bin/DWrite.dll").write_bytes(b"existing-extender")
    settings = profile / "PlayerProfiles/Public/modsettings.lsx"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b'<save><region id="ModuleSettings"><node id="root"><children><node id="Mods"><children><node id="ModuleShortDesc"><attribute id="UUID" value="other-mod"/></node></children></node></children></node></region></save>')
    package = tmp_path / "BG3Friend.pak"
    package.write_bytes(b"LSPK\x12\0\0\0fixture-package")
    checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    arguments = ["--game", str(game), "--profile", str(profile), "--state-root", str(state),
                 "--package", str(package), "--package-sha256", checksum, "--version", "test-1"]
    monkeypatch.setattr(install, "game_is_running", lambda: False)
    return SimpleNamespace(game=game, profile=profile, state=state, package=package,
                           checksum=checksum, args=arguments, settings=settings)


def test_cli_prebuilt_dry_run_does_not_build_or_write(cli, monkeypatch, capsys):
    monkeypatch.setattr(install, "build_package", lambda *args: pytest.fail("prebuilt install must not build"))
    before = cli.settings.read_bytes()
    assert install.main(cli.args + ["--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run" and output["plan"]["ready"]
    assert cli.settings.read_bytes() == before
    assert not cli.state.exists()
    assert not (cli.profile / "Mods").exists()


def test_cli_roundtrip_preserves_corrupt_control_and_original_settings(cli, capsys):
    original = cli.settings.read_bytes()
    control = cli.profile / "Script Extender/BG3Friend/control.json"
    control.parent.mkdir(parents=True)
    control.write_bytes(b"not-json-user-control")
    assert install.main(cli.args) == 0
    capsys.readouterr()
    assert uninstall.main(["--state-root", str(cli.state), "--profile", str(cli.profile), "--dry-run"]) == 0
    capsys.readouterr()
    assert (cli.profile / "Mods/BG3Friend.pak").exists()
    assert uninstall.main(["--state-root", str(cli.state), "--profile", str(cli.profile)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["action"] == "uninstall"
    assert control.read_bytes() == b"not-json-user-control"
    assert cli.settings.read_bytes() == original


@pytest.mark.parametrize("style", ["package_object", "file_map", "file_objects"])
def test_cli_release_manifest_verifies_prebuilt_package(cli, tmp_path, capsys, style):
    data = {"version": "manifest-version"}
    if style == "package_object":
        data["package"] = {"path": cli.package.name, "sha256": cli.checksum}
    else:
        data["package"] = cli.package.name
        data["files"] = {cli.package.name: cli.checksum if style == "file_map" else {"sha256": cli.checksum}}
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert install.main(cli.args[:6] + ["--manifest", str(manifest), "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["plan"]["version"] == "manifest-version"
    assert not cli.state.exists()


def test_cli_rejects_missing_or_conflicting_checksum(cli, tmp_path, capsys):
    assert install.main(cli.args[:8] + ["--dry-run"]) == 1
    assert "checksum" in json.loads(capsys.readouterr().out)["error"]
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps({"version": "1", "package": {"path": cli.package.name, "sha256": "0" * 64}}))
    assert install.main(cli.args + ["--manifest", str(manifest), "--dry-run"]) == 1
    assert "conflicts" in json.loads(capsys.readouterr().out)["error"]
    assert not cli.state.exists()


def test_cli_active_game_refuses_without_building(cli, monkeypatch, capsys):
    monkeypatch.setattr(install, "game_is_running", lambda: True)
    monkeypatch.setattr(install, "build_package", lambda *args: pytest.fail("running game must block source install before build"))
    assert install.main(cli.args[:6]) == 1
    assert "Close BG3" in json.loads(capsys.readouterr().out)["error"]
    assert not cli.state.exists()


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_cli_active_runner_refuses_install_and_remove(cli, capsys, operation):
    if operation == "uninstall":
        assert install.main(cli.args) == 0
        capsys.readouterr()
    runner = cli.profile / "Script Extender/BG3Friend/runner.json"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(json.dumps({"runner": "thinking"}))
    before = cli.settings.read_bytes()
    result = install.main(cli.args) if operation == "install" else uninstall.main(["--state-root", str(cli.state)])
    assert result == 1
    assert "runner" in json.loads(capsys.readouterr().out)["error"]
    assert cli.settings.read_bytes() == before


def test_runner_lock_detects_hung_runner_without_fresh_heartbeat(cli):
    lock = cli.profile / "Script Extender/BG3Friend/runner.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a+b") as handle:
        handle.write(b"\0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(installation.PreflightError, match="runner is active"):
            install.require_runner_stopped(cli.profile)


@pytest.mark.parametrize("claim", [True, None])
def test_runner_claim_blocks_before_heartbeat_or_other_os_file_lock(cli, monkeypatch, claim):
    monkeypatch.setattr(install, "runner_claim_active", lambda folder: claim)
    assert not (cli.profile / "Script Extender/BG3Friend/runner.json").exists()
    with pytest.raises(installation.PreflightError, match="runner claim"):
        install.require_runner_stopped(cli.profile)
    assert not cli.state.exists() and not (cli.profile / "Mods/BG3Friend.pak").exists()


def test_runner_claim_read_failure_blocks(cli, monkeypatch):
    def unreadable(folder):
        raise OSError("fixture claim query failed")
    monkeypatch.setattr(install, "runner_claim_active", unreadable)
    with pytest.raises(installation.PreflightError, match="runner claim"):
        install.require_runner_stopped(cli.profile)


@pytest.mark.parametrize("checksum", [123, ["invalid"], "not-a-sha256"])
def test_cli_malformed_manifest_checksum_is_a_preflight_error(cli, tmp_path, capsys, checksum):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "fixture", "package": {"path": cli.package.name, "sha256": checksum}}))
    original = cli.settings.read_bytes()
    assert install.main(cli.args[:6] + ["--manifest", str(manifest), "--dry-run"]) == 1
    assert "SHA-256" in json.loads(capsys.readouterr().out)["error"]
    assert cli.settings.read_bytes() == original and not cli.state.exists()


@pytest.mark.parametrize("exit_code,expected", [(0, False), (10, True), (1, None), (20, None), (-1, None)])
def test_game_process_exit_codes_fail_closed(monkeypatch, exit_code, expected):
    monkeypatch.setattr(install.shutil, "which", lambda _: "fixture-powershell")
    monkeypatch.setattr(install.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=exit_code))
    if expected is None:
        with pytest.raises(installation.PreflightError, match="process check failed"):
            install.game_is_running()
    else:
        assert install.game_is_running() is expected


def test_game_process_timeout_fails_closed(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda _: "fixture-powershell")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fixture", 10)
    monkeypatch.setattr(install.subprocess, "run", timeout)
    with pytest.raises(installation.PreflightError, match="Cannot determine"):
        install.game_is_running()


def test_build_only_works_without_game_or_profile(cli, monkeypatch, capsys):
    monkeypatch.setattr(install, "build_package", lambda divine: cli.package)
    monkeypatch.setattr(install, "game_is_running", lambda: pytest.fail("build-only must not query/start the game"))
    assert install.main(["--build-only", "--divine", "/explicit/Divine.exe"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "build_only"
    assert not cli.state.exists()


def test_dry_run_without_artifact_never_builds(cli, monkeypatch, capsys):
    monkeypatch.setattr(install, "build_package", lambda *args: pytest.fail("dry-run must not build"))
    assert install.main(cli.args[:6] + ["--dry-run"]) == 1
    assert "requires a prebuilt" in json.loads(capsys.readouterr().out)["error"]


def test_state_defaults_follow_windows_saved_games_and_xdg(tmp_path, monkeypatch):
    from companion import windows_paths
    monkeypatch.setattr(windows_paths, "user_state_dir", lambda: tmp_path / "Saved Games/BG3Friend")
    assert install.default_state_root(platform="nt") == tmp_path / "Saved Games/BG3Friend/install"
    assert install.default_state_root(platform="posix", environ={"XDG_STATE_HOME": str(tmp_path)}) == tmp_path / "bg3-friend/install"


def test_windows_state_lookup_failure_is_explicit(tmp_path, monkeypatch):
    from companion import windows_paths
    def missing():
        raise OSError("fixture known folder unavailable")
    monkeypatch.setattr(windows_paths, "user_state_dir", missing)
    with pytest.raises(installation.PreflightError, match="Saved Games"):
        install.default_state_root(platform="nt")


def test_uninstall_reports_interrupted_journal_even_when_manifest_is_missing(cli, capsys, monkeypatch):
    journal = cli.state / "transactions" / ("f" * 32) / "journal.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"schema": 1, "action": "uninstall", "phase": "applying", "operations": []}), encoding="utf-8")
    monkeypatch.setattr(uninstall, "process_check", lambda _: pytest.fail("recovery must be reported before other work"))
    assert uninstall.main(["--state-root", str(cli.state), "--dry-run"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert str(journal) in report["error"] and "needs recovery" in report["error"]


def test_uninstall_legacy_profile_must_match_state(cli, tmp_path, capsys):
    assert install.main(cli.args) == 0
    capsys.readouterr()
    assert uninstall.main(["--state-root", str(cli.state), "--profile", str(tmp_path / "wrong-profile")]) == 1
    assert "does not match" in json.loads(capsys.readouterr().out)["error"]
    assert (cli.profile / "Mods/BG3Friend.pak").exists()
