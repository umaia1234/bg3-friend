import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_skill", REPO / "scripts/install_skill.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "repository"
    source = root / ".agents/skills/bg3-friend-start"
    for name in installer.FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPO / ".agents/skills/bg3-friend-start" / name).read_bytes())
    config = {
        "repository": "https://github.com/umaia1234/bg3-friend", "steamAppId": "1086940",
        "distro": "Ubuntu-24.04", "projectLinux": "/home/player/bg3-friend",
        "projectWindows": r"\\wsl.localhost\Ubuntu-24.04\home\player\bg3-friend",
        "ioLinux": "/mnt/c/Users/player/AppData/Local/Larian Studios/Baldur's Gate 3/Script Extender/BG3Friend",
        "profileWindows": r"C:\Users\player\AppData\Local\Larian Studios\Baldur's Gate 3",
        "windowsPython": r"C:\Users\player\AppData\Local\Programs\Python\Python311\pythonw.exe",
        "gameWindows": r"D:\SteamLibrary\steamapps\common\Baldurs Gate 3",
        "steamExe": r"C:\Program Files (x86)\Steam\steam.exe",
    }
    config_file = root / "config.local.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    target = tmp_path / "personal/skills/bg3-friend-start"
    return root, source, config, config_file, target


def test_preview_writes_nothing(setup):
    root, source, _, config_file, target = setup
    result = installer.register(config_file, target, root=root)
    assert result["mode"] == "preview" and len(result["changed_files"]) == 5
    assert not target.exists()
    assert not (source / "project.local.json").exists()
    assert not (root / ".runtime").exists()


def test_register_then_repeat_is_idempotent(setup):
    root, source, config, config_file, target = setup
    first = installer.register(config_file, target, apply=True, root=root)
    assert first["backup"] is None
    assert installer.read_config(target / "project.local.json") == config
    assert (source / "project.local.json").read_bytes() == (target / "project.local.json").read_bytes()
    second = installer.register(config_file, target, apply=True, root=root)
    assert second["changed_files"] == [] and not second["project_config_changed"]
    assert second["backup"] is None


def test_update_preserves_preferences_and_backs_up_previous_files(setup):
    root, _, config, config_file, target = setup
    installer.register(config_file, target, apply=True, root=root)
    old = config | {"preferences": {"companion": "Shadowheart", "autoCombat": False}, "localNote": "keep"}
    (target / "project.local.json").write_text(json.dumps(old), encoding="utf-8")
    (target / "SKILL.md").write_text("previous local skill", encoding="utf-8")
    (target / "user-note.txt").write_text("preserve", encoding="utf-8")
    result = installer.register(config_file, target, apply=True, root=root)
    saved = installer.read_config(target / "project.local.json")
    assert saved["preferences"] == old["preferences"] and saved["localNote"] == "keep"
    assert (target / "user-note.txt").read_text() == "preserve"
    backup = Path(result["backup"]) / installer.NAME
    assert (backup / "SKILL.md").read_text() == "previous local skill"
    assert installer.read_config(backup / "project.local.json") == old


@pytest.mark.parametrize("key,value", [("distro", "bad distro"), ("steamAppId", "1"),
                                     ("projectLinux", "relative/path"), ("gameWindows", "YOUR_GAME_PATH")])
def test_invalid_config_does_not_write(setup, key, value):
    root, source, config, config_file, target = setup
    config[key] = value
    config_file.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        installer.register(config_file, target, apply=True, root=root)
    assert not target.exists() and not (source / "project.local.json").exists()


def test_cannot_install_into_source_or_parent(setup):
    root, source, _, config_file, _ = setup
    for target in (source, source.parent, root):
        with pytest.raises(ValueError):
            installer.register(config_file, target, apply=True, root=root)


def test_linked_target_is_not_modified(setup):
    root, _, _, config_file, target = setup
    elsewhere = target.parent / "unrelated"
    elsewhere.mkdir(parents=True)
    try:
        target.symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(ValueError):
        installer.register(config_file, target, apply=True, root=root)
    assert list(elsewhere.iterdir()) == []
