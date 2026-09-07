import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts import build_release as release


@pytest.fixture
def frozen(tmp_path):
    folder = tmp_path / "BG3Friend"
    bundle = folder / "_internal/bundle"
    package = tmp_path / "input.pak"
    package.write_bytes(b"LSPK\x12\0\0\0fixture package")
    release.stage_bundle(package, bundle, version="fixture-version", fixture=True)
    for name in ("BG3Friend.exe", "_internal/python311.dll", "_internal/tcl86t.dll", "_internal/tk86t.dll"):
        (folder / name).write_bytes(b"fake-binary-not-executable")
    return folder


def test_staged_bundle_contract_and_input_hash(tmp_path):
    package = tmp_path / "input.pak"
    package.write_bytes(b"LSPK\x12\0\0\0fixture")
    checksum = release.sha256(package)
    manifest = release.stage_bundle(package, tmp_path / "bundle", version="0.2.0-rc.1", expected_sha256=checksum)
    assert manifest["package"] == {"path": "BG3Friend.pak", "sha256": checksum}
    assert manifest["mod_version64"] == "36028797018963969"
    assert json.loads((tmp_path / "bundle/manifest.json").read_bytes()) == manifest
    with pytest.raises(release.BuildError, match="does not match"):
        release.stage_bundle(package, tmp_path / "bad", version="1", expected_sha256="0" * 64)
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("name", ["auth.json", "project.local.json", "DWrite.dll", "Divine.exe", "raw.log", "private.lsv", "developer.py"])
def test_private_source_and_shared_tools_never_pass_bundle_audit(frozen, name):
    (frozen / "_internal" / name).write_bytes(b"forbidden fixture")
    with pytest.raises(release.BuildError):
        release.inspect_bundle(frozen, {})


def test_unexpected_binary_requires_its_own_notice(frozen, tmp_path):
    extra = frozen / "_internal/unknown.dll"
    extra.write_bytes(b"binary fixture")
    with pytest.raises(release.BuildError, match="unexpected runtime binary"):
        release.inspect_bundle(frozen, {})
    notice = tmp_path / "license.txt"
    notice.write_text("fixture notice")
    inspection = release.inspect_bundle(frozen, {"unknown.dll": notice})
    assert "_internal/unknown.dll" in inspection["binary_files"]


def test_collected_openssl_requires_an_explicit_notice_entry(frozen, tmp_path):
    (frozen / "_internal/libcrypto-3.dll").write_bytes(b"fixture crypto library")
    with pytest.raises(release.BuildError, match="OpenSSL requires"):
        release.inspect_bundle(frozen, {})
    notice = tmp_path / "openssl-license.txt"
    notice.write_text("fixture matching notice")
    assert "_internal/libcrypto-3.dll" in release.inspect_bundle(frozen, {"OpenSSL": notice})["binary_files"]


def test_packaging_command_stages_only_package_and_uses_windowed_onedir(tmp_path):
    command = release.pyinstaller_command(tmp_path, tmp_path / "stage", root=tmp_path / "source")
    assert "--onedir" in command and "--windowed" in command and "--noupx" in command
    assert command[command.index("--add-data") + 1] == str(tmp_path / "stage") + ":bundle"
    assert command.count("--add-data") == 1
    assert command[-1] == str(tmp_path / "source/scripts/app.py")


def test_zip_inventory_and_no_overwrite(frozen, tmp_path):
    release.inspect_bundle(frozen, {})
    destination = tmp_path / "out/BG3Friend.zip"
    report = release.write_zip(frozen, destination)
    assert report["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        checksums = archive.read("BG3Friend/SHA256SUMS").decode("utf-8")
        for line in checksums.splitlines():
            expected, filename = line.split("  ", 1)
            assert hashlib.sha256(archive.read("BG3Friend/" + filename)).hexdigest() == expected
        assert not any("input.pak" in name for name in archive.namelist())
    original = destination.read_bytes()
    with pytest.raises(release.BuildError, match="already exists"):
        release.write_zip(frozen, destination)
    assert destination.read_bytes() == original


def test_zip_works_on_provider_without_hardlinks(frozen, tmp_path, monkeypatch):
    def unsupported(*args, **kwargs):
        raise OSError("fixture UNC provider has no hardlinks")
    monkeypatch.setattr(release.os, "link", unsupported)
    destination = tmp_path / "out/release.zip"
    report = release.write_zip(frozen, destination)
    assert report["sha256"] == release.sha256(destination)


def test_notice_collection_copies_only_explicit_licenses_and_public_docs(frozen, tmp_path):
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    for name in ("SETUP.ko.md", "RELEASE.ko.md", "VALIDATION.md"):
        (source / "docs" / name).write_text("public fixture document", encoding="utf-8")
    (source / "auth.json").write_text("private fixture must not be copied")
    notice = tmp_path / "license.txt"
    notice.write_text("actual fixture license")
    manifest = json.loads((frozen / "_internal/bundle/manifest.json").read_bytes())
    release.add_notices(frozen, {"Python": notice}, {"Python": "fixture"}, manifest, {}, root=source)
    assert (frozen / "licenses/Python-LICENSE.txt").read_text(encoding="utf-8") == "actual fixture license"
    assert (frozen / "README.ko.md").is_file() and (frozen / "THIRD-PARTY.md").is_file()
    assert (frozen / "docs/SETUP.ko.md").is_file()
    assert not (frozen / "auth.json").exists()
    assert str(source) not in (frozen / "BUILD-MANIFEST.json").read_text(encoding="utf-8")


def test_portable_notices_rebase_source_links_without_bundling_source(frozen, tmp_path):
    root = tmp_path / "source"
    (root / "docs").mkdir(parents=True)
    for name in ("SETUP.ko.md", "RELEASE.ko.md"):
        (root / "docs" / name).write_text("# Guide\n", encoding="utf-8")
    original = ("[Local](SETUP.ko.md#guide) [Tests](../tests/) "
                "[Lua](../mod/Mods/BG3Friend/ScriptExtender/Lua/Server.lua#L1) "
                "[Skill](../.agents/skills/bg3-friend-start/SKILL.md) "
                "[Remote](https://example.com/page) [Same page](#heading)")
    (root / "docs/VALIDATION.md").write_text(original, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/not-distributable.py").write_text("private fixture", encoding="utf-8")
    manifest = json.loads((frozen / "_internal/bundle/manifest.json").read_bytes())
    release.add_notices(frozen, {}, {}, manifest, {}, root=root)
    copied = (frozen / "docs/VALIDATION.md").read_text(encoding="utf-8")
    for public in release.PUBLIC_SOURCE_LINKS.values():
        assert public in copied
    assert "Server.lua#L1)" in copied
    assert "[Local](SETUP.ko.md#guide)" in copied and "[Same page](#heading)" in copied
    assert "[Remote](https://example.com/page)" in copied
    assert "../tests/" not in copied and not (frozen / "tests").exists()
    assert (root / "docs/VALIDATION.md").read_text(encoding="utf-8") == original
    assert str(root) not in copied


@pytest.mark.parametrize("target", ["MISSING.md", "../auth.json", "../../outside.md", "../tests/new-unreviewed.py"])
def test_portable_document_rejects_unreviewed_or_missing_source_link(tmp_path, target):
    source = tmp_path / "docs/SETUP.ko.md"
    source.parent.mkdir()
    source.write_text(f"[Broken]({target})", encoding="utf-8")
    with pytest.raises(release.BuildError, match="Unreviewed or missing relative link"):
        release.portable_document(source, tmp_path, {"docs/SETUP.ko.md"})
