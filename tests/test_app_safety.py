"""Headless setup/consent regressions; never open a GUI or touch a real profile."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from companion import app as app_module
from companion import diagnostics, lifecycle
from companion.configuration import Settings, discover_games, load_settings, save_settings
from companion.diagnostics import Check
from companion.model import ModelFailure
from companion.protocol import write_json


class Value:
    def __init__(self, value="", **kwargs):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.state = "normal"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)

    def delete(self, *args):
        pass

    def insert(self, *args):
        pass


class Root(Widget):
    def __init__(self):
        super().__init__()
        self.scheduled = []
        self.destroyed = False

    def title(self, *args):
        pass

    def geometry(self, *args):
        pass

    def minsize(self, *args):
        pass

    def option_add(self, *args):
        pass

    def protocol(self, *args):
        pass

    def winfo_screenheight(self):
        return 1080

    def after(self, milliseconds, callback):
        self.scheduled.append(callback)

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    settings = Settings(game=str(tmp_path / "game"), profile=str(tmp_path / "profile-a"),
                        codex=str(tmp_path / "fixture-cli.exe"), consent=True)
    root = tmp_path / "state"
    save_settings(settings, root)

    def build_ui(app):
        app.start_button, app.stop_button, app.check_text = Widget(), Widget(), Widget()
        app.buttons.extend([app.start_button])

    monkeypatch.setattr(app_module, "enable_dpi_awareness", lambda: None)
    monkeypatch.setattr(app_module.tk, "Tk", Root)
    monkeypatch.setattr(app_module.tk, "StringVar", Value)
    monkeypatch.setattr(app_module.tk, "BooleanVar", Value)
    monkeypatch.setattr(app_module.DesktopApp, "build_ui", build_ui)
    monkeypatch.setattr(app_module, "runtime_status", lambda folder: {"running": False})
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *a, **k: None)
    app = app_module.DesktopApp(root, smoke=True)
    app.root.scheduled.clear()
    return app


def pending_start(app, monkeypatch):
    jobs, launched = [], []

    def job(operation, callback):
        app.busy = True
        jobs.append((operation, callback))

    monkeypatch.setattr(app, "job", job)
    monkeypatch.setattr(app_module, "start_worker", lambda root: launched.append(root))
    app.start()
    assert len(jobs) == 1

    def ready():
        app.queue.put((jobs[0][1], [Check("consent", True, "fixture accepted earlier")], None))
        app.poll()

    return launched, ready


@pytest.mark.parametrize("operation", ["stop", "close"])
def test_running_worker_keeps_original_profile_when_settings_are_edited(desktop, tmp_path, monkeypatch, operation):
    original = desktop.settings
    desktop.worker = SimpleNamespace(poll=lambda: None)
    desktop.worker_io = original.io
    stopped = []
    monkeypatch.setattr(app_module, "request_stop", lambda folder: stopped.append(folder) or True)
    desktop.fields["profile"].set(str(tmp_path / "profile-b"))
    desktop.save(quiet=True)
    assert load_settings(desktop.config_root) == original
    getattr(desktop, operation)()
    assert stopped == [original.io]


@pytest.mark.parametrize("change", ["consent", "profile", "model", "stop"])
def test_pending_start_cannot_use_stale_permission_or_settings(desktop, tmp_path, monkeypatch, change):
    launched, ready = pending_start(desktop, monkeypatch)
    monkeypatch.setattr(app_module, "request_stop", lambda folder: False)
    if change == "consent":
        desktop.consent.set(False)
    elif change == "profile":
        desktop.fields["profile"].set(str(tmp_path / "different-profile"))
    elif change == "model":
        desktop.fields["model"].set("different-model")
    else:
        desktop.stop()
    ready()
    assert launched == []


def test_success_callback_failure_does_not_stop_desktop_polling(desktop):
    def fail(result):
        raise OSError("fixture worker launch failed")

    desktop.busy = True
    desktop.queue.put((fail, None, None))
    desktop.poll()
    assert not desktop.busy
    assert "fixture worker launch failed" in desktop.notice.get()
    assert desktop.root.scheduled


def test_consent_withdrawal_is_saved_even_if_bridge_stop_write_fails(desktop, tmp_path, monkeypatch):
    original_profile = desktop.settings.profile
    desktop.worker = SimpleNamespace(poll=lambda: None)
    desktop.worker_io = desktop.settings.io
    desktop.fields["profile"].set(str(tmp_path / "unsaved-profile"))

    def cannot_stop(folder):
        raise PermissionError("fixture bridge stop is locked")

    monkeypatch.setattr(app_module, "request_stop", cannot_stop)
    desktop.consent.set(False)
    desktop.consent_changed()
    saved = load_settings(desktop.config_root)
    assert saved.consent is False and saved.profile == original_profile


def test_stop_before_worker_claim_is_retried_after_startup(desktop, monkeypatch):
    desktop.worker = SimpleNamespace(poll=lambda: None)
    desktop.worker_io = desktop.settings.io
    attempts = []

    def stop_once_claim_exists(folder):
        attempts.append(folder)
        return len(attempts) >= 2

    monkeypatch.setattr(app_module, "request_stop", stop_once_claim_exists)
    desktop.stop()
    for _ in range(3):
        desktop.poll()
        callbacks, desktop.root.scheduled = desktop.root.scheduled, []
        for callback in callbacks:
            callback()
        if len(attempts) >= 2:
            break
    assert len(attempts) >= 2
    assert set(attempts) == {desktop.worker_io}


def test_close_waits_for_setup_mutation_to_finish(desktop):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def mutation():
        entered.set()
        try:
            assert release.wait(3), "fixture cleanup was not released"
        finally:
            finished.set()

    desktop.job(mutation, lambda result: None)
    try:
        assert entered.wait(2)
        desktop.close()
        assert not desktop.root.destroyed, "normal close must let setup finish/rollback"
    finally:
        release.set()
        assert finished.wait(2)
    deadline = time.monotonic() + 2
    while not desktop.root.destroyed and time.monotonic() < deadline:
        pending, desktop.root.scheduled = desktop.root.scheduled, []
        for callback in pending:
            callback()
        time.sleep(.01)
    assert desktop.root.destroyed


@pytest.mark.parametrize("mismatch", ["session", "companion", "revision"])
def test_diagnostic_enabled_requires_current_session_and_assignment(tmp_path, mismatch):
    write_json(tmp_path / "runner.json", {"runner": "ready", "session": "new"})
    write_json(tmp_path / "snapshot.json", {"session": "new", "control_revision": 2,
        "companion": {"id": "friend", "name": "fixture"}})
    control = {"session": "new", "companion": "friend", "revision": 2, "enabled": True}
    control[mismatch] = {"session": "old", "companion": "someone-else", "revision": 1}[mismatch]
    write_json(tmp_path / "control.json", control)
    status = diagnostics.runtime_status(tmp_path)
    assert status["game_connected"]
    assert status["enabled"] is False


def test_empty_runner_document_is_not_evidence_of_a_running_service(tmp_path):
    write_json(tmp_path / "runner.json", {})
    assert diagnostics.runtime_status(tmp_path)["running"] is False


@pytest.mark.parametrize("version,login_code", [("Codex Desktop", 0), ("codex-cli fixture", 1), ("codex-cli fixture", 0)])
def test_setup_requires_cli_identity_before_login_and_keeps_account_output_private(tmp_path, monkeypatch, version, login_code):
    cli = tmp_path / "fixture-cli.exe"
    cli.write_bytes(b"never execute this fixture file")
    settings = Settings(game=str(tmp_path / "game"), profile=str(tmp_path / "profile"),
                        codex=str(cli), consent=True)
    calls = []

    def probe(executable, arguments, timeout=10):
        assert executable == str(cli)
        calls.append(arguments)
        return (0, version) if arguments == ["--version"] else (login_code, "private-account@example.test")

    monkeypatch.setattr(diagnostics, "probe_cli", probe)
    checks = diagnostics.setup_checks(settings)
    result = {check.id: check.ok for check in checks}
    assert result["codex"] == version.startswith("codex-cli ")
    assert result["login"] == (version.startswith("codex-cli ") and login_code == 0)
    assert calls == ([["--version"], ["login", "status"]] if version.startswith("codex-cli ") else [["--version"]])
    assert "private-account" not in repr(checks)
    assert "private-account" not in repr(diagnostics.support_report(settings, checks))


def test_setup_probe_failure_is_reported_without_escaping_the_job(tmp_path, monkeypatch):
    cli = tmp_path / "fixture-cli.exe"
    cli.write_bytes(b"fixture")

    def timeout(*args, **kwargs):
        raise ModelFailure("timeout", "fixture safe timeout", retryable=True)

    monkeypatch.setattr(diagnostics, "probe_cli", timeout)
    checks = diagnostics.setup_checks(Settings(codex=str(cli)))
    assert not next(check for check in checks if check.id == "login").ok


@pytest.mark.parametrize("file", ["libraryfolders.vdf", "appmanifest_1086940.acf"])
def test_unreadable_steam_metadata_does_not_crash_discovery(tmp_path, file):
    steamapps = tmp_path / "steamapps"
    game = steamapps / "common/Baldurs Gate 3"
    (game / "bin").mkdir(parents=True)
    (game / "bin/bg3.exe").write_bytes(b"fixture")
    (steamapps / file).write_bytes(b"\xff\xfeinvalid")
    assert discover_games([tmp_path]) == [game]


def test_frozen_child_command_reuses_executable_with_explicit_mode(tmp_path, monkeypatch):
    executable = str(tmp_path / "BG3 Friend.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    assert lifecycle.app_command("--worker", "--config-root", str(tmp_path)) == [
        executable, "--worker", "--config-root", str(tmp_path)]


def test_worker_entry_does_not_initialize_desktop_ui(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("friend_app_entry_fixture", Path(__file__).parents[1] / "scripts/app.py")
    entry = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "path", sys.path[:])
    spec.loader.exec_module(entry)
    calls = []
    monkeypatch.setattr(lifecycle, "run_worker", lambda root, parent: calls.append((root, parent)))
    monkeypatch.setattr(app_module, "DesktopApp", lambda *a, **k: pytest.fail("child initialized desktop UI"))
    monkeypatch.setattr(sys, "argv", ["app.py", "--worker", "--config-root", str(tmp_path), "--parent-pid", "123"])
    assert entry.main() == 0
    assert calls == [(tmp_path, 123)]
