"""Portable GUI entry, with explicit child modes and a read-only build smoke check."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--overlay", action="store_true")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--io", type=Path)
    parser.add_argument("--close-file", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    from companion.configuration import load_settings, state_root
    from companion.protocol import write_json
    root = args.config_root or state_root()
    if args.status or args.stop:
        from companion.diagnostics import runtime_status
        from companion.lifecycle import request_stop
        settings = load_settings(root)
        result = runtime_status(settings.io) if settings.profile else {"running": False, "game_connected": False, "status": "unconfigured"}
        if args.stop:
            result["stop_requested"] = request_stop(settings.io) if settings.profile else False
        if args.report:
            write_json(args.report, result)
        elif sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not args.stop or result.get("stop_requested") or not result["running"] else 2
    if args.worker:
        try:
            from companion.lifecycle import run_worker
            run_worker(root, args.parent_pid)
        except Exception as exc:
            write_json(root / "worker-error.json", {"message": str(exc)[:350], "type": type(exc).__name__})
            return 1
        return 0
    if args.overlay:
        if not args.io:
            parser.error("--overlay requires --io")
        from companion.gui import FriendWindow
        FriendWindow(args.io, args.close_file, args.stop_file).root.mainloop()
        return 0
    if args.diagnose:
        from companion.diagnostics import Check, setup_checks, support_report
        from companion.configuration import ConfigurationError, Settings
        from companion.installation import InstallationError, check_recovery
        try:
            settings = load_settings(root)
        except ConfigurationError:
            settings = Settings()
            checks = [Check("configuration", False, "저장된 설정을 확인해 주세요")]
        else:
            checks = setup_checks(settings)
            try:
                check_recovery(root / "install")
            except InstallationError:
                checks.append(Check("installation_recovery", False, "중단된 설치의 복구 기록을 확인해 주세요"))
        report = support_report(settings, checks)
        if args.report:
            write_json(args.report, report)
        elif sys.stdout is not None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(c.ok for c in checks if c.required) else 2
    from companion.app import DesktopApp
    app = DesktopApp(root, smoke=args.smoke_test or args.start)
    if args.start:
        app.root.after(200, app.start)
    if args.smoke_test:
        from companion.diagnostics import bundle_package
        from companion import __version__
        package, manifest = bundle_package()
        # Exercise bundled imports/Tk and checksum without login, game access or settings writes.
        app.root.update_idletasks()
        report = {"ok": True, "version": __version__, "tk": app.root.tk.call("info", "patchlevel"),
                  "package_sha256": manifest["package"]["sha256"], "frozen": bool(getattr(sys, "frozen", False))}
        if args.report:
            write_json(args.report, report)
        app.root.after(200, app.close)
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
