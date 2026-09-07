"""Remove a managed installation transactionally, preserving saves and other mods."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.installation import (InstallationError, PreflightError, STATE_FILE,
                                    apply_plan, check_recovery, plan_uninstall)
from scripts.install import default_state_root, error_output, process_check, require_stopped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--profile", type=Path, help="Optional legacy argument; must match the managed installation")
    parser.add_argument("--dry-run", action="store_true", help="Read-only removal plan")
    args = parser.parse_args(argv)
    try:
        state_root = (args.state_root or default_state_root()).absolute()
        check_recovery(state_root)
        manifest_path = state_root / STATE_FILE
        if not manifest_path.is_file():
            raise PreflightError("No managed installation was found. Pass the state directory used during installation with --state-root; legacy backup folders are not managed manifests")
        try:
            state = json.loads(manifest_path.read_text(encoding="utf-8"))
            profile = Path(state["profile"])
            if not profile.is_absolute():
                raise ValueError("profile is not absolute")
        except (KeyError, TypeError, ValueError) as exc:
            raise PreflightError("The installation manifest is invalid; keep the original backups and inspect its profile path") from exc
        if args.profile is not None and args.profile.absolute() != profile:
            raise PreflightError("--profile does not match the installation recorded in --state-root")
        check = process_check(profile)
        require_stopped(check)
        preview = plan_uninstall(state_root, game_running=check)
        output = {"ok": True, "mode": "dry_run" if args.dry_run else "apply", "plan": preview.to_dict()}
        if not args.dry_run:
            output["result"] = apply_plan(preview, game_running=check).to_dict()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (InstallationError, OSError, ValueError, TypeError) as exc:
        return error_output(exc)


if __name__ == "__main__":
    raise SystemExit(main())
