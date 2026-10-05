"""Pinned official OpenGFX archive, safe staging and 15.3 GRF checksum semantics."""

import configparser
import hashlib
import io
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

SOURCE_URL = "https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip"
ARCHIVE_SHA256 = "43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be"
KINDS = ("base", "logos", "arctic", "tropical", "toyland", "extra")


@dataclass(frozen=True)
class GraphicsIdentity:
    directory: Path
    archive_sha256: str
    descriptor_sha256: str
    grfs: tuple[tuple[str, str, str], ...]  # filename, full SHA256, native data-section MD5
    files: tuple[tuple[str, str], ...]
    name: str = "OpenGFX"
    release: str = "8.0"
    descriptor_version: int = 9499
    source: str = SOURCE_URL


def native_grf_md5(data: bytes) -> str:
    # newgrf_config.cpp GRFGetSizeOfDataSection, gfxinit.cpp CheckMD5.
    size = len(data)
    if len(data) >= 14 and data[:10] == b"\0\0GRF\x82\r\n\x1a\n":
        offset = int.from_bytes(data[10:14], "little")
        if offset >= 1024**3 or 14 + offset > len(data):
            raise ValueError("Invalid GRF data section")
        size = 14 + offset
    return hashlib.md5(data[:size]).hexdigest()


def validate_baseset(directory: Path) -> tuple[tuple[str, str, str], ...]:
    descriptor = directory / "opengfx.obg"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(descriptor.read_text())
    if (
        parser["metadata"]["name"] != "OpenGFX"
        or parser["metadata"]["shortname"] != "OGFX"
        or parser["metadata"]["version"] != "9499"
        or set(parser["files"]) != set(KINDS)
    ):
        raise ValueError("Unexpected OpenGFX descriptor")
    result = []
    for kind in KINDS:
        name = parser["files"][kind]
        if Path(name).name != name or not name.endswith(".grf"):
            raise ValueError("Unsafe descriptor filename")
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Incomplete base set")
        data = path.read_bytes()
        md5 = native_grf_md5(data)
        if md5 != parser["md5s"][name]:
            raise ValueError("GRF checksum mismatch")
        result.append((name, hashlib.sha256(data).hexdigest(), md5))
    if len({x[0] for x in result}) != 6:
        raise ValueError("Duplicate base-set filename")
    return tuple(sorted(result))


def stage_opengfx(
    archive: Path, destination: Path, *, expected_sha256: str = ARCHIVE_SHA256
) -> GraphicsIdentity:
    data = archive.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError("OpenGFX archive SHA-256 mismatch")
    if len(data) > 10_000_000:
        raise ValueError("Oversized graphics archive")
    destination = destination.absolute()
    for normal in (Path.home() / ".config/openttd", Path.home() / ".local/share/openttd"):
        if destination.resolve().is_relative_to(normal.resolve()):
            raise ValueError("Normal profile forbidden")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Graphics destination exists")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if z.namelist() != ["opengfx-8.0.tar"] or z.infolist()[0].file_size > 20_000_000:
            raise ValueError("Unexpected OpenGFX archive layout")
        nested = z.read("opengfx-8.0.tar")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".graphics-") as temp:
        staging = Path(temp) / "OpenGFX"
        staging.mkdir()
        with tarfile.open(fileobj=io.BytesIO(nested)) as tar:
            members = tar.getmembers()
            if len(members) > 32 or sum(m.size for m in members) > 20_000_000:
                raise ValueError("Oversized graphics contents")
            for member in members:
                if member.isdir() and member.name == "opengfx-8.0":
                    continue
                relative = Path(member.name)
                if not member.isfile() or relative.parent != Path("opengfx-8.0"):
                    raise ValueError("Unsafe graphics member")
                stream = tar.extractfile(member)
                assert stream is not None
                with (staging / relative.name).open("xb") as output:
                    output.write(stream.read())
        grfs = validate_baseset(staging)
        files = tuple(
            (p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(staging.iterdir())
        )
        descriptor = hashlib.sha256((staging / "opengfx.obg").read_bytes()).hexdigest()
        staging.rename(destination)
    return GraphicsIdentity(destination, digest, descriptor, grfs, files)
