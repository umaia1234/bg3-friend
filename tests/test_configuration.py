import json
import os
from pathlib import Path

import pytest

from companion.configuration import ConfigurationError, Settings, discover_games, load_settings, save_settings
from companion.diagnostics import Check, file_age, support_report
from companion.protocol import write_json
from companion import windows_paths


def test_discovery_uses_steam_library_metadata_with_spaces_and_unicode(tmp_path):
    steam = tmp_path / "Steam"
    library = tmp_path / "게임 보관함"
    (steam / "steamapps").mkdir(parents=True)
    (library / "steamapps/common/Custom BG3/bin").mkdir(parents=True)
    (library / "steamapps/common/Custom BG3/bin/bg3_dx11.exe").write_bytes(b"fixture")
    (steam / "steamapps/libraryfolders.vdf").write_text(f'"path" "{library.as_posix()}"', encoding="utf-8")
    (library / "steamapps/appmanifest_1086940.acf").write_text('"installdir" "Custom BG3"', encoding="utf-8")
    assert discover_games([steam]) == [library / "steamapps/common/Custom BG3"]


def test_settings_roundtrip_and_corruption_preserved(tmp_path):
    settings = Settings(game=str(tmp_path / "게임"), profile=str(tmp_path / "프로필"), consent=True)
    save_settings(settings, tmp_path / "state")
    assert load_settings(tmp_path / "state") == settings
    path = tmp_path / "state/settings.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path / "state")
    assert path.read_text() == "{broken"


@pytest.mark.parametrize("changes", [{"version": 2}, {"timeout": float("nan")}, {"consent": "yes"},
                                     {"game": "relative"}, {"model": "--model injected"}])
def test_invalid_settings_rejected(changes):
    with pytest.raises(ConfigurationError):
        Settings(**changes).validate()


def test_diagnostic_report_omits_private_data_even_in_unexpected_fields(tmp_path):
    settings = Settings(profile=str(tmp_path), codex="private-path", model="private-model")
    folder = settings.io
    write_json(folder / "runner.json", {"runner": "private-chat", "error_code": "private-auth", "token": "private-token"})
    write_json(folder / "snapshot.json", {"session": "private-save", "companion": {"name": "private-name"}})
    report = support_report(settings, [Check("login", False, "private-account")])
    serialized = json.dumps(report)
    assert "private" not in serialized and str(tmp_path) not in serialized
    assert report["runtime"]["status"] == "stopped"
    assert not report["runtime"]["running"]


def test_missing_file_is_never_fresh(tmp_path):
    assert file_age(tmp_path / "missing") == float("inf")


@pytest.mark.skipif(os.name != "nt", reason="Windows known folders")
def test_settings_default_does_not_follow_msix_localappdata(monkeypatch, tmp_path):
    calls = []
    def known(identifier):
        calls.append(identifier)
        return str(tmp_path / "실제 게임 설정")
    monkeypatch.setattr(windows_paths, "_known_folder", known)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "private-package-cache"))
    assert windows_paths.user_state_dir() == tmp_path / "실제 게임 설정/BG3Friend"
    assert calls == ["4c5c32ff-bb9d-43b0-b5b4-2d72e54eaaa4"]
    assert not (tmp_path / "실제 게임 설정").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows known folders")
def test_known_folder_failure_does_not_silently_switch_install_ownership(monkeypatch):
    def broken(identifier):
        raise OSError("fixture read failure")
    monkeypatch.setattr(windows_paths, "_known_folder", broken)
    with pytest.raises(OSError):
        windows_paths.user_state_dir()


@pytest.mark.parametrize("alive,blocked", [(True, True), (None, True), (False, False)])
def test_install_claim_guard_covers_runner_before_first_heartbeat(tmp_path, monkeypatch, alive, blocked):
    from companion import lifecycle
    write_json(tmp_path / "runner-claim/owner.json", {"pid": 42, "platform": "foreign"})
    monkeypatch.setattr(lifecycle, "_owner_alive", lambda owner: alive)
    assert lifecycle.runner_claim_active(tmp_path) is blocked
