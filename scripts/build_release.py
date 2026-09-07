"""Build an unsigned Windows portable ZIP from an explicitly supplied BG3 PAK.

No dependency installation, network request, game process, login, or game-file
modification is performed. Build dependencies and missing license texts must be
prepared separately. Only the explicitly staged PAK is passed as application data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import posixpath
import re
import shutil
import ssl
import struct
import subprocess
import sys
import uuid
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion import __version__
from companion.installation import MOD_VERSION64

PYINSTALLER_VERSION = "6.22.2"
FORBIDDEN_PARTS = {".git", ".codex", ".agents", ".claude", ".tools", ".runtime", "memory", "evidence", "__pycache__", "tests"}
FORBIDDEN_NAMES = {"auth.json", "credentials.json", "hosts.yml", "config.local.json", "project.local.json", "control.json",
                   "snapshot.json", "runner.json", "dwrite.dll", "divine.exe", "codex.exe", "codex", "pyvenv.cfg"}


class BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def json_file(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def stage_bundle(package: Path, destination: Path, *, version: str, expected_sha256: str | None = None, fixture: bool = False) -> dict:
    package = package.resolve(strict=True)
    with package.open("rb") as handle:
        header = handle.read(8)
    if package.suffix.lower() != ".pak" or len(header) != 8 or header[:4] != b"LSPK":
        raise BuildError("--package must identify the reviewed, prebuilt LSPK .pak file")
    checksum = sha256(package)
    if expected_sha256 is not None and checksum != expected_sha256.lower():
        raise BuildError("The input PAK does not match --package-sha256")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(package, destination / "BG3Friend.pak")
    if sha256(destination / "BG3Friend.pak") != checksum:
        raise BuildError("PAK changed while it was being copied; rebuild from a stable input")
    manifest = {"version": version, "mod_version64": MOD_VERSION64,
                "package": {"path": "BG3Friend.pak", "sha256": checksum}, "fixture": fixture}
    json_file(destination / "manifest.json", manifest)
    return manifest


def license_overrides(arguments: list[str]) -> dict[str, Path]:
    result = {}
    for argument in arguments:
        if "=" not in argument:
            raise BuildError("Use --license-file Component=/absolute/path/to/license")
        component, filename = argument.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", component) or component in result:
            raise BuildError("License component names must be unique simple file names")
        path = Path(filename).resolve(strict=True)
        if not path.is_file() or not path.stat().st_size:
            raise BuildError(f"Missing license text for {component}")
        result[component] = path
    return result


def runtime_licenses(overrides: dict[str, Path]) -> tuple[dict[str, Path], dict]:
    import tkinter
    interpreter = tkinter.Tcl()
    tcl_directory = Path(interpreter.eval("info library"))
    base = Path(sys.base_prefix)
    candidates = {
        "Python": [base / "LICENSE.txt", base / "LICENSE"],
        "Tcl": [tcl_directory / "license.terms", tcl_directory.parent / "license.terms"],
        "Tk": [base / "tcl" / f"tk{tkinter.TkVersion}" / "license.terms",
               tcl_directory.parent / f"tk{tkinter.TkVersion}" / "license.terms"],
    }
    distribution = importlib.metadata.distribution("pyinstaller")
    candidates["PyInstaller"] = [Path(distribution.locate_file(item)) for item in distribution.files or () if item.name.lower() == "copying.txt"]
    selected = dict(overrides)
    for component, paths in candidates.items():
        if component not in selected:
            selected[component] = next((path for path in paths if path.is_file() and path.stat().st_size), None)
        if component == "Tcl" and selected[component] is None and selected.get("Python"):
            python_notice = selected["Python"].read_text(encoding="utf-8", errors="replace")
            if "Scriptics Corporation, ActiveState" in python_notice and "Regents of the University" in python_notice:
                selected[component] = selected["Python"]
        if selected[component] is None:
            raise BuildError(f"The installed {component} license was not found. Provide its matching upstream text with --license-file {component}=<path>")
    if "OpenSSL" not in selected:
        python_notice = selected["Python"].read_text(encoding="utf-8", errors="replace")
        if ssl.OPENSSL_VERSION_INFO[0] >= 3 and all(marker in python_notice for marker in ("Apache License", "Version 2.0, January 2004", "END OF TERMS AND CONDITIONS")):
            selected["OpenSSL"] = selected["Python"]
        else:
            raise BuildError(f"Provide the license matching {ssl.OPENSSL_VERSION} with --license-file OpenSSL=<path>")
    versions = {"Python": platform.python_version(), "Tcl": interpreter.call("info", "patchlevel"),
                "Tk": str(tkinter.TkVersion), "PyInstaller": distribution.version, "OpenSSL": ssl.OPENSSL_VERSION}
    return selected, versions


def pyinstaller_command(work: Path, staged_bundle: Path, *, root: Path = ROOT) -> list[str]:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "BG3Friend", "--contents-directory", "_internal", "--noupx", "--log-level", "WARN",
               "--distpath", str(work / "frozen"), "--workpath", str(work / "analysis"), "--specpath", str(work),
               "--paths", str(root), "--add-data", f"{staged_bundle}:bundle"]
    for module in ("pytest", "lupa", "pip", "IPython", "notebook"):
        command.extend(("--exclude-module", module))
    command.append(str(root / "scripts/app.py"))
    return command


def inspect_bundle(folder: Path, licenses: dict[str, Path]) -> dict:
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    issues = []
    dlls = []
    for path in files:
        relative = path.relative_to(folder)
        parts = {part.casefold() for part in relative.parts}
        name = path.name.casefold()
        if path.is_symlink() or parts & FORBIDDEN_PARTS or name in FORBIDDEN_NAMES:
            issues.append(relative.as_posix())
        if name.startswith(".env") or path.suffix.lower() in (".py", ".pyw", ".spec", ".toc", ".log", ".lsv", ".pem", ".key"):
            issues.append(relative.as_posix())
        if path.suffix.lower() == ".pak" and relative.as_posix() != "_internal/bundle/BG3Friend.pak":
            issues.append(relative.as_posix())
        if path.suffix.lower() in (".dll", ".pyd"):
            dlls.append(relative.as_posix())
            if name.startswith(("libcrypto", "libssl")) and "OpenSSL" not in licenses:
                raise BuildError("Collected OpenSSL requires its matching notice: --license-file OpenSSL=<path>")
            known_dll = bool(re.fullmatch(r"(?:python\d+|tcl\d+t?|tk\d+t?|vcruntime\d+(?:_\d+)?|msvcp\d+(?:_\d+)?|libffi[-\w]*|libcrypto[-\w]*|libssl[-\w]*|sqlite3|ucrtbase|api-ms-win-[-\w]+)\.dll", name))
            known_pyd = path.suffix.lower() == ".pyd" and path.stem in sys.stdlib_module_names
            if not known_dll and not known_pyd and path.name not in licenses:
                raise BuildError(f"Review the unexpected runtime binary and provide --license-file {path.name}=<license>: {relative}")
    if issues:
        raise BuildError("Forbidden source/private/build files in frozen output: " + ", ".join(sorted(set(issues))))
    names = {path.name.casefold() for path in files}
    for required in ("BG3Friend.exe", "_internal/bundle/BG3Friend.pak", "_internal/bundle/manifest.json"):
        if not (folder / required).is_file():
            raise BuildError(f"Frozen output is missing {required}")
    if not any(re.fullmatch(r"python\d+\.dll", name) for name in names) or not any(re.fullmatch(r"tcl\d+t?\.dll", name) for name in names) or not any(re.fullmatch(r"tk\d+t?\.dll", name) for name in names):
        raise BuildError("The frozen output does not contain the required Python and Tcl/Tk runtimes")
    manifest = json.loads((folder / "_internal/bundle/manifest.json").read_text(encoding="utf-8"))
    if sha256(folder / "_internal/bundle/BG3Friend.pak") != manifest["package"]["sha256"]:
        raise BuildError("Frozen PAK does not match the frozen manifest")
    return {"binary_files": dlls, "file_count_before_notices": len(files)}


PUBLIC_SOURCE_LINKS = {
    # These public main targets were checked before adding them. A new source
    # link must be reviewed instead of silently packaging source/private files.
    "tests": "https://github.com/umaia1234/bg3-friend/tree/main/tests",
    "mod/Mods/BG3Friend/ScriptExtender/Lua/Server.lua": "https://github.com/umaia1234/bg3-friend/blob/main/mod/Mods/BG3Friend/ScriptExtender/Lua/Server.lua",
    ".agents/skills/bg3-friend-start/SKILL.md": "https://github.com/umaia1234/bg3-friend/blob/main/.agents/skills/bg3-friend-start/SKILL.md",
}


def portable_document(source: Path, root: Path, bundled_paths: set[str]) -> str:
    """Keep bundled-document links local; rebase only reviewed public source links."""
    relative = source.relative_to(root).as_posix()

    def rewrite(match):
        target = match.group(2)
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path:
            return match.group(0)
        key = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(parts.path)))
        if key in bundled_paths:
            return match.group(0)
        public = PUBLIC_SOURCE_LINKS.get(key)
        if public is None:
            raise BuildError(f"Unreviewed or missing relative link in release document {relative}: {target}")
        suffix = ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else "")
        return match.group(1) + public + suffix + match.group(3)

    return re.sub(r"(\[[^\]\n]+\]\()([^\s)]+)(\))", rewrite, source.read_text(encoding="utf-8"))


def add_notices(folder: Path, licenses: dict[str, Path], versions: dict, manifest: dict, inspection: dict, *, root: Path = ROOT) -> None:
    notice_dir = folder / "licenses"
    notice_dir.mkdir()
    for component, source in sorted(licenses.items()):
        shutil.copyfile(source, notice_dir / (component + "-LICENSE.txt"))
    source_license = next((root / name for name in ("LICENSE", "LICENSE.txt", "LICENSE.md") if (root / name).is_file()), None)
    if source_license is not None:
        shutil.copyfile(source_license, folder / source_license.name)
    documentation = folder / "docs"
    documentation.mkdir()
    doc_names = ("SETUP.ko.md", "RELEASE.ko.md", "VALIDATION.md")
    bundled_paths = {"docs/" + name for name in doc_names}
    for name in doc_names:
        source = root / "docs" / name
        if not source.is_file():
            raise BuildError(f"Required public distribution documentation is missing: docs/{name}")
        (documentation / name).write_text(portable_document(source, root, bundled_paths), encoding="utf-8")
    fixture_text = "\n이 ZIP은 CI용 가짜 PAK를 포함한 실행 검사 파일입니다. 게임에 설치하거나 플레이용으로 배포하지 마세요.\n" if manifest.get("fixture") else ""
    (folder / "README.ko.md").write_text(
        f"# BG3 Friend {manifest['version']}\n\nWindows x64용 휴대용 배포본입니다. 압축 전체를 새 폴더에 푼 뒤 `BG3Friend.exe`를 실행하세요. `_internal` 폴더도 함께 유지합니다. Python과 Tcl/Tk가 포함되어 있습니다.\n\n"
        "본인의 Windows BG3, Script Extender, Codex CLI와 로그인이 필요합니다. 앱에서 현재 경로를 확인한 뒤 설치 계획을 검토하고 적용하세요. 게임과 친구 프로그램이 종료된 상태에서 설치·갱신·제거합니다.\n\n"
        "대화와 파티·주변 관찰이 Codex에 전달되고 계정 사용량에 반영됩니다. 한 동료의 대화·탐험 판단은 모델이, 전투 행동은 게임 AI가 처리합니다.\n\n"
        "이 실행 파일은 서명되지 않았습니다. SHA256SUMS는 파일 일치 확인용이며 제작자 신원이나 위변조 방지를 보증하는 전자서명이 아닙니다. 새 PC 전체 설치·실제 게임 플레이 검증은 런타임 검사와 구분됩니다.\n\n"
        "[설치·사용·제거 안내](docs/SETUP.ko.md), [검증 범위](docs/VALIDATION.md), [제작·검사 명세](docs/RELEASE.ko.md), [외부 구성 요소](THIRD-PARTY.md)를 확인하세요.\n" + fixture_text,
        encoding="utf-8")
    lines = ["# Bundled third-party notices", "", "These license files are copied from the actual build runtime or explicitly supplied matching upstream notices; they are not replaced by this summary.", "", "| Component | Build version | Included notice |", "|---|---|---|"]
    for component in sorted(licenses):
        lines.append(f"| {component} | {versions.get(component, 'see notice')} | [license](licenses/{component}-LICENSE.txt) |")
    lines += ["", "Python-LICENSE.txt retains the Windows Python distribution's third-party notices, including its Microsoft Distributable Code terms where present. When that file supplies the matching Tcl or OpenSSL terms, its complete text is also retained under those component names. OpenSSL 3 uses the included Apache 2.0 terms. The included PyInstaller COPYING text covers its bootloader exception and runtime hooks. Retain the applicable notices when redistributing the ZIP.", "", "Codex CLI, Script Extender, LSLib, Steam, and Baldur's Gate 3 are not included. They remain separate user installations.", "", "The exact collected binary inventory is in BUILD-MANIFEST.json. A file-hash inventory is provided in SHA256SUMS. This build does not sign binaries or assert clean-machine/gameplay validation."]
    (folder / "THIRD-PARTY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_file(folder / "BUILD-MANIFEST.json", {"version": manifest["version"], "mod_version64": manifest["mod_version64"],
               "package_sha256": manifest["package"]["sha256"], "runtime_versions": versions, "signed": False,
               "fixture": bool(manifest.get("fixture")), "target": "windows-x64", "entry": "scripts/app.py", **inspection})


def write_zip(folder: Path, destination: Path) -> dict:
    """Archive this staged tree only. Existing release artifacts are never replaced."""
    if destination.exists():
        raise BuildError(f"Release artifact already exists; choose a new output directory: {destination}")
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    checksum_file = folder / "SHA256SUMS"
    checksum_file.write_text("".join(f"{sha256(path)}  {path.relative_to(folder).as_posix()}\n" for path in files), encoding="utf-8")
    files.append(checksum_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(files):
                info = zipfile.ZipInfo("BG3Friend/" + path.relative_to(folder).as_posix(), (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise BuildError("ZIP integrity verification failed")
        # A hard link publishes without replacing an existing destination. Some
        # Windows UNC providers do not support links; exclusive creation retains
        # the no-overwrite contract there.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise
        except OSError:
            created = False
            try:
                with destination.open("xb") as output, temporary.open("rb") as source:
                    created = True
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
            except BaseException:
                if created:
                    destination.unlink(missing_ok=True)
                raise
    finally:
        temporary.unlink(missing_ok=True)
    return {"archive": str(destination), "sha256": sha256(destination), "files": len(files)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/release")
    parser.add_argument("--work-dir", type=Path, default=ROOT / ".runtime/release-build")
    parser.add_argument("--license-file", action="append", default=[])
    parser.add_argument("--fixture-package", action="store_true", help="Label CI-only package artifacts; never a gameplay release")
    args = parser.parse_args(argv)
    try:
        if os.name != "nt" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
            raise BuildError("Build this Windows x64 bundle with an x64 Python on Windows; cross compilation is not supported")
        if importlib.metadata.version("pyinstaller") != PYINSTALLER_VERSION:
            raise BuildError(f"Use the pinned build dependency PyInstaller=={PYINSTALLER_VERSION}")
        if not (ROOT / "scripts/app.py").is_file():
            raise BuildError("The portable application entry scripts/app.py is missing")
        licenses, versions = runtime_licenses(license_overrides(args.license_file))
        suffix = "-fixture" if args.fixture_package else ""
        destination = args.output_dir.resolve() / f"BG3Friend-{__version__}-windows-x64{suffix}.zip"
        checksum_output = destination.parent / "SHA256SUMS"
        if destination.exists() or checksum_output.exists():
            raise BuildError("Output artifacts already exist; choose a new --output-dir")
        work = args.work_dir.resolve() / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=False)
        staged = work / "bundle"
        manifest = stage_bundle(args.package, staged, version=__version__, expected_sha256=args.package_sha256, fixture=args.fixture_package)
        environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(work / "cache"))
        result = subprocess.run(pyinstaller_command(work, staged), cwd=ROOT, env=environment, check=False)
        if result.returncode:
            raise BuildError(f"PyInstaller failed (exit {result.returncode}); intermediate files remain in {work}")
        folder = work / "frozen/BG3Friend"
        inspection = inspect_bundle(folder, licenses)
        add_notices(folder, licenses, versions, manifest, inspection)
        report = write_zip(folder, destination)
        with checksum_output.open("x", encoding="utf-8") as handle:
            handle.write(f"{report['sha256']}  {destination.name}\n")
        print(json.dumps({"ok": True, "signed": False, "fixture": args.fixture_package,
                          "directory": str(folder), "checksums": str(checksum_output), **report}, ensure_ascii=False, indent=2))
        return 0
    except (BuildError, OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
