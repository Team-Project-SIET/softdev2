"""Offline graphics fixtures; the official archive is separately verified in preparation."""

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.simulation.openttd.proof.graphics import stage_opengfx, validate_baseset


def graphics_archive(path: Path, *, missing=False):
    files = {
        f"{name}.grf": name.encode()
        for name in ("base", "logos", "arctic", "tropical", "toyland", "extra")
    }
    descriptor = "[metadata]\nname=OpenGFX\nshortname=OGFX\nversion=9499\n[files]\n"
    descriptor += "".join(
        f"{name}={name}.grf\n"
        for name in ("base", "logos", "arctic", "tropical", "toyland", "extra")
    )
    descriptor += "[md5s]\n" + "".join(
        f"{name}={hashlib.md5(data).hexdigest()}\n" for name, data in files.items()
    )
    files["opengfx.obg"] = descriptor.encode()
    if missing:
        del files["base.grf"]
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo("opengfx-8.0/" + name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("opengfx-8.0.tar", tar.getvalue())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_archive_staging_and_descriptor(tmp_path):
    path = tmp_path / "graphics.zip"
    expected = graphics_archive(path)
    identity = stage_opengfx(path, tmp_path / "isolated/baseset/OpenGFX", expected_sha256=expected)
    assert identity.archive_sha256 == expected
    assert identity.name == "OpenGFX" and identity.descriptor_version == 9499
    assert len(identity.grfs) == 6
    assert validate_baseset(identity.directory) == identity.grfs
    assert identity.directory.is_relative_to(tmp_path / "isolated")


def test_wrong_archive_and_incomplete_set_rejected(tmp_path):
    path = tmp_path / "graphics.zip"
    expected = graphics_archive(path, missing=True)
    with pytest.raises(ValueError, match="SHA-256"):
        stage_opengfx(path, tmp_path / "wrong")
    with pytest.raises(ValueError):
        stage_opengfx(path, tmp_path / "incomplete", expected_sha256=expected)
    assert not (tmp_path / "incomplete").exists()


def test_grf_v2_data_section_checksum_matches_engine_rule():
    from app.simulation.openttd.proof.graphics import native_grf_md5

    data = b"\0\0GRF\x82\r\n\x1a\n" + (4).to_bytes(4, "little") + b"data" + b"sprites"
    assert native_grf_md5(data) == hashlib.md5(data[:18]).hexdigest()
    assert native_grf_md5(data) != hashlib.md5(data).hexdigest()


def test_descriptor_file_corruption_rejected(tmp_path):
    path = tmp_path / "graphics.zip"
    digest = graphics_archive(path)
    identity = stage_opengfx(path, tmp_path / "baseset", expected_sha256=digest)
    (identity.directory / "base.grf").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        validate_baseset(identity.directory)
