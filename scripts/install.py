"""Install a prebuilt release, or explicitly build the developer source package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.installation import (ApplyError, ConflictError, InstallationError,
                                    PreflightError, apply_plan, plan_install)
from companion.lifecycle import runner_claim_active


def default_state_root(*, platform: str | None = None, environ: dict | None = None) -> Path:
    environment = os.environ if environ is None else environ
    if (platform or os.name) == "nt":
        from companion.windows_paths import user_state_dir
        try:
            return user_state_dir() / "install"
        except OSError as exc:
            raise PreflightError("Cannot determine the Windows Saved Games state folder; pass the reviewed --state-root explicitly") from exc
    base = environment.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local/state") / "bg3-friend/install"


def windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path.resolve())
    try:
        return subprocess.check_output(["wslpath", "-w", str(path.resolve())], text=True, timeout=10).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("Windows path conversion failed; source packaging requires Windows or WSL") from exc


def game_is_running() -> bool:
    """False means the native process query positively found no BG3 process."""
    powershell = shutil.which("powershell.exe")
    if not powershell and os.name == "nt" and os.environ.get("SystemRoot"):
        candidate = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if candidate.is_file():
            powershell = str(candidate)
    if not powershell:
        raise PreflightError("Cannot check Windows game processes: PowerShell is unavailable. No installation files were changed")
    command = "$ErrorActionPreference='Stop'; try { $p=@(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -in @('bg3','bg3_dx11') }); if($p.Count -gt 0){exit 10}; exit 0 } catch { exit 20 }"
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("Cannot determine whether BG3 is running; close BG3 and repair the Windows process check before retrying") from exc
    if result.returncode == 10:
        return True
    if result.returncode != 0:
        raise PreflightError(f"Windows game process check failed (exit {result.returncode}); installation was refused")
    return False


def require_runner_stopped(profile: Path) -> None:
    folder = profile / "Script Extender/BG3Friend"
    try:
        claimed = runner_claim_active(folder)
    except (OSError, ValueError) as exc:
        raise PreflightError("Cannot verify the BG3 Friend runner claim. Stop the conversation and inspect its status before installing or removing") from exc
    if claimed is not False:
        raise PreflightError("BG3 Friend has an active or unverified runner claim. Stop the conversation first and wait for it to exit before installing or removing; do not delete its ownership files")
    lock = folder / "runner.lock"
    if lock.exists():
        try:
            with lock.open("r+b") as handle:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise PreflightError("BG3 Friend runner is active or its lock cannot be checked. Use the chat menu's Close conversation action, then retry; do not delete runner.lock") from exc
    heartbeat = folder / "runner.json"
    if heartbeat.exists():
        try:
            age = time.time() - heartbeat.stat().st_mtime
            data = json.loads(heartbeat.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            raise PreflightError("Cannot verify BG3 Friend runner status. Close the companion chat and inspect its status before retrying") from exc
        if age < 10 and data.get("runner") not in (None, "stopped"):
            raise PreflightError("BG3 Friend runner has a recent active heartbeat. Use the chat menu's Close conversation action and wait for it to stop before installing or removing")


def process_check(profile: Path):
    def check() -> bool:
        require_runner_stopped(profile)
        return game_is_running()
    return check


def require_stopped(check) -> None:
    if check() is not False:
        raise PreflightError("Close BG3 and BG3 Friend's companion chat before installing or removing")


def build_package(divine: Path | None = None) -> Path:
    """Explicit developer-only packaging; never needed for a prebuilt release."""
    divine = (divine or ROOT / ".tools/lslib/Packed/Tools/Divine.exe").resolve()
    if not divine.is_file():
        raise PreflightError("Divine.exe is missing. Use a prebuilt --package, or prepare LSLib and pass --divine")
    if not (ROOT / "mod/Mods/BG3Friend/meta.lsx").is_file():
        raise PreflightError("The mod source is missing; use the complete source tree or a prebuilt release")
    destination = ROOT / "dist/BG3Friend.pak"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run([str(divine), "-g", "bg3", "-a", "create-package", "-s",
                                 windows_path(ROOT / "mod"), "-d", windows_path(destination), "-c", "lz4"],
                                capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("Source packaging failed; check LSLib and its Windows .NET runtime") from exc
    if result.returncode != 0 or not destination.is_file():
        raise PreflightError(f"Source packaging failed (exit {result.returncode}); no game files were changed")
    return destination


def source_version() -> str:
    try:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except (OSError, ValueError, KeyError):
        raise PreflightError("Pass --version or provide a release manifest with its version")


def package_metadata(args) -> tuple[Path, str, str, str | None]:
    metadata = {}
    manifest = args.manifest.resolve() if args.manifest else None
    if manifest:
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if not isinstance(metadata, dict):
                raise ValueError("manifest must be an object")
        except (OSError, ValueError) as exc:
            raise PreflightError(f"Cannot read the release manifest: {exc}") from exc
    package_entry = metadata.get("package", {})
    entry_path = package_entry.get("path") if isinstance(package_entry, dict) else package_entry
    package = args.package.absolute() if args.package else (manifest.parent / entry_path).absolute() if manifest and isinstance(entry_path, str) else None
    recorded_checksum = package_entry.get("sha256") if isinstance(package_entry, dict) else None
    recorded_checksum = recorded_checksum or metadata.get("package_sha256") or metadata.get("sha256")
    if not recorded_checksum and package is not None and manifest is not None and isinstance(metadata.get("files"), dict):
        try:
            relative = package.relative_to(manifest.parent).as_posix()
        except ValueError:
            raise PreflightError("The selected package must be inside the manifest's release folder")
        recorded_checksum = metadata["files"].get(relative)
        if isinstance(recorded_checksum, dict):
            recorded_checksum = recorded_checksum.get("sha256")
    if recorded_checksum is not None and (not isinstance(recorded_checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", recorded_checksum)):
        raise PreflightError("The release manifest checksum must be a 64-character SHA-256 string")
    if recorded_checksum and args.package_sha256 and recorded_checksum.lower() != args.package_sha256.lower():
        raise PreflightError("--package-sha256 conflicts with the release manifest checksum")
    checksum = recorded_checksum or args.package_sha256
    version = args.version or metadata.get("version")
    if package is None:
        if args.dry_run:
            raise PreflightError("--dry-run requires a prebuilt --package. Build once with --build-only, then preview that package")
        if manifest:
            raise PreflightError("The manifest does not identify a package; pass --package explicitly")
        package = build_package(args.divine)
        checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    elif not checksum:
        raise PreflightError("A prebuilt package requires --package-sha256 or a release manifest checksum")
    return package, checksum, version or source_version(), metadata.get("mod_version64")


def error_output(exc: BaseException) -> int:
    output = {"ok": False, "error": str(exc)}
    if isinstance(exc, ConflictError):
        output["conflicts"] = list(exc.conflicts)
    if isinstance(exc, ApplyError):
        output.update(rolled_back=exc.rolled_back, rollback_errors=list(exc.rollback_errors), journal=str(exc.journal))
    print(json.dumps(output, ensure_ascii=False))
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path)
    parser.add_argument("--profile", type=Path, help="Baldur's Gate 3 LocalAppData folder")
    parser.add_argument("--package", type=Path, help="Prebuilt release BG3Friend.pak; no LSLib/.NET needed")
    parser.add_argument("--package-sha256")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--mod-version64")
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--script-extender", "--extender", type=Path, dest="extender")
    parser.add_argument("--script-extender-sha256", dest="extender_sha256")
    parser.add_argument("--divine", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Read-only installation plan; does not build or apply")
    args = parser.parse_args(argv)
    try:
        if args.build_only:
            if args.dry_run or args.package or args.manifest:
                raise PreflightError("--build-only cannot be combined with --dry-run, --package, or --manifest")
            package = build_package(args.divine)
            print(json.dumps({"ok": True, "mode": "build_only", "package": str(package), "sha256": hashlib.sha256(package.read_bytes()).hexdigest()}))
            return 0
        if args.game is None or args.profile is None:
            raise PreflightError("Installation requires --game and --profile with the confirmed paths")
        game, profile = args.game.absolute(), args.profile.absolute()
        check = process_check(profile)
        require_stopped(check)
        package, checksum, version, metadata_mod_version = package_metadata(args)
        extender = args.extender
        if extender is None and (ROOT / ".tools/bg3se/DWrite.dll").is_file():
            extender = ROOT / ".tools/bg3se/DWrite.dll"
        options = {}
        if args.mod_version64 or metadata_mod_version:
            options["mod_version64"] = str(args.mod_version64 or metadata_mod_version)
        preview = plan_install(game, profile, package, (args.state_root or default_state_root()).absolute(),
                               version=version, package_sha256=checksum, game_running=check,
                               extender=extender.absolute() if extender else None, extender_sha256=args.extender_sha256, **options)
        output = {"ok": True, "mode": "dry_run" if args.dry_run else "apply", "plan": preview.to_dict()}
        if not args.dry_run:
            output["result"] = apply_plan(preview, game_running=check).to_dict()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (InstallationError, OSError, ValueError, TypeError) as exc:
        return error_output(exc)


if __name__ == "__main__":
    raise SystemExit(main())
