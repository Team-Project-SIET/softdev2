"""Verified, pinned OpenTTD 13.4 runtime preparation without launching a process."""

import fcntl
import hashlib
import json
import lzma
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

import httpx
import yaml  # type: ignore[import-untyped]

from app.experiments.domain import AIConfig, ExperimentConfig
from app.experiments.strategies import (
    BaselineStrategy,
    PlanningStrategy,
    SimpleMultimodalStrategy,
    SimpleRoadOnlyStrategy,
)


class RuntimePreparationCode(StrEnum):
    MISSING_ASSET = "missing_asset"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    UNSUPPORTED_PIN = "unsupported_pinned_identity"
    CORRUPT_ARCHIVE = "corrupt_archive"
    UNSAFE_ARCHIVE_PATH = "unsafe_archive_path"
    DEPENDENCY_FAILURE = "dependency_resolution_failure"
    CACHE_FAILURE = "cache_lock_or_publication_failure"


class AcquisitionPolicy(StrEnum):
    ALLOW_PROVISIONING = "allow_provisioning"
    CACHE_ONLY = "cache_only"


class RuntimePreparationError(RuntimeError):
    """Only a finite, path-free code/message crosses the preparation boundary."""

    def __init__(self, code: RuntimePreparationCode) -> None:
        self.code = code
        super().__init__(code.value.replace("_", " "))


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)


@dataclass(frozen=True)
class AssetPin:
    key: str
    version: str
    filename: str
    sha256: str
    content_id: str | None = None
    md5: str | None = None
    dependencies: tuple[str, ...] = ()


# Release SHA-256 values are from the pinned official CDN manifests. BaNaNaS
# archive SHA-256 values are from the previously verified local Lab cache; exact
# content IDs, package versions and MD5 prefixes match BaNaNaS package metadata.
PINNED_ASSETS: dict[str, AssetPin] = {
    "openttd": AssetPin(
        "openttd",
        "13.4",
        "openttd-13.4-linux-generic-amd64.tar.xz",
        "943b7be04130ea790323f70bf5476ccf17692a6e89790748e90aa590b7db4370",
    ),
    "opengfx": AssetPin(
        "opengfx",
        "7.1",
        "opengfx-7.1-all.zip",
        "928fcf34efd0719a3560cbab6821d71ce686b6315e8825360fba87a7a94d7846",
    ),
    "simpleai": AssetPin(
        "simpleai",
        "14",
        "534d504c-SimpleAI-14.tar",
        "7cb5aa4cdf30991487d0291f79666341f6fac70f24d4dd09efbcf8a91d0bff65",
        "534d504c",
        "b3137bbd0c73641cf510ead06e36dab6",
        (
            "pathfinder_rail",
            "pathfinder_road",
            "graph_aystar_4",
            "graph_aystar_6",
            "queue_binary_heap",
        ),
    ),
    "trains": AssetPin(
        "trains",
        "2.1",
        "54524149-trAIns-2.1.tar",
        "c37b44e6806202680a0abece0f71d2da3fd4dc6cd1ae5613b717ee3e480bbe53",
        "54524149",
        "c4c069dc797674e545411b59867ad0c2",
    ),
    "pathfinder_rail": AssetPin(
        "pathfinder_rail",
        "1",
        "5046524c-Pathfinder.Rail-1.tar",
        "e3ab05b1811c1a57abb4219480f0fffa885efff6be42691c836ec144ab7f8b13",
        "5046524c",
        "e6b1d198",
    ),
    "pathfinder_road": AssetPin(
        "pathfinder_road",
        "4",
        "5046524f-Pathfinder.Road-4.tar",
        "64b178e3d9c28a0d41e9bdace02ee119ae2e7c986de560c40eed51fa684e31ae",
        "5046524f",
        "999de61c",
    ),
    "graph_aystar_4": AssetPin(
        "graph_aystar_4",
        "4",
        "4752412a-Graph.AyStar-4.tar",
        "cfc09cdd5877800d57e490832b65cf028db16aef4f1906eb1d625f908ebc49f1",
        "4752412a",
        "4afad592",
    ),
    "graph_aystar_6": AssetPin(
        "graph_aystar_6",
        "6",
        "4752412a-Graph.AyStar-6.tar",
        "4e76533f1f38240bf8bb5abfca0b6cc2ea182a1c6ccf7f5f3980e5ae8d219e27",
        "4752412a",
        "f385497c",
        ("queue_binary_heap",),
    ),
    "queue_binary_heap": AssetPin(
        "queue_binary_heap",
        "1",
        "51554248-Queue.BinaryHeap-1.tar",
        "a83eb5002b1246330dfc467dbd1076687d227156a697cc140f6d04515cf3bb67",
        "51554248",
        "8ce55e13",
    ),
}


@dataclass(frozen=True)
class PreparedRuntime:
    executable_path: Path
    opengfx_archive_path: Path
    ai_archive_path: Path
    dependency_archive_paths: tuple[Path, ...]
    ai_configuration: AIConfig
    provenance: dict[str, object]


class RuntimeAssetSource(Protocol):
    def fetch(
        self, pin: AssetPin, destination: Path, *, root_ai: AssetPin | None = None
    ) -> None: ...


class OfficialRuntimeSource:
    """Official release manifests and public Lab BaNaNaS content helper only."""

    def __init__(self) -> None:
        self._ai_bundle: dict[str, dict[tuple[str, str], tuple[bytes, str]]] = {}

    def fetch(self, pin: AssetPin, destination: Path, *, root_ai: AssetPin | None = None) -> None:
        if pin.key in {"openttd", "opengfx"}:
            category = "openttd" if pin.key == "openttd" else "opengfx"
            base = f"https://cdn.openttd.org/{category}-releases/{pin.version}/"
            try:
                with httpx.Client(timeout=30, follow_redirects=True) as client:
                    manifest_chunks: list[bytes] = []
                    manifest_size = 0
                    with client.stream("GET", base + "manifest.yaml") as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            manifest_size += len(chunk)
                            if manifest_size > 1024 * 1024:
                                raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET)
                            manifest_chunks.append(chunk)
                    manifest = yaml.safe_load(b"".join(manifest_chunks))
                    if str(manifest.get("version")) != pin.version:
                        raise RuntimePreparationError(RuntimePreparationCode.UNSUPPORTED_PIN)
                    entry = next(
                        (item for item in manifest["files"] if item["id"] == pin.filename), None
                    )
                    if entry is None or entry.get("sha256sum") != pin.sha256:
                        raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
                    expected_size = entry["size"]
                    if (
                        not isinstance(expected_size, int)
                        or not 0 < expected_size <= MAX_ARCHIVE_BYTES
                    ):
                        raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
                    total = 0
                    with client.stream("GET", base + pin.filename) as response:
                        response.raise_for_status()
                        with destination.open("wb") as output:
                            for chunk in response.iter_bytes():
                                total += len(chunk)
                                if total > expected_size:
                                    raise RuntimePreparationError(
                                        RuntimePreparationCode.CHECKSUM_MISMATCH
                                    )
                                output.write(chunk)
                    if total != expected_size:
                        raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            except RuntimePreparationError:
                raise
            except (
                httpx.HTTPError,
                yaml.YAMLError,
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET) from exc
            return
        if root_ai is None or root_ai.content_id is None or root_ai.md5 is None:
            raise RuntimePreparationError(RuntimePreparationCode.DEPENDENCY_FAILURE)
        bundle = self._ai_bundle.get(root_ai.content_id)
        if bundle is None:
            from openttdlab import download_from_bananas  # type: ignore[import-untyped]

            bundle = {}
            try:
                with tempfile.TemporaryDirectory(prefix="openttd-content-") as temporary:
                    with download_from_bananas(
                        "ai/" + root_ai.content_id,
                        md5=root_ai.md5,
                        get_cache_dir=lambda: temporary,
                    ) as items:
                        for content_id, filename, _license, md5sum, get_data in items:
                            parts: list[bytes] = []
                            total = 0
                            with get_data() as chunks:
                                for chunk in chunks:
                                    total += len(chunk)
                                    if total > MAX_ARCHIVE_BYTES:
                                        raise RuntimePreparationError(
                                            RuntimePreparationCode.CORRUPT_ARCHIVE
                                        )
                                    parts.append(chunk)
                            bundle[(content_id, filename)] = (b"".join(parts), md5sum)
                            if content_id == "ai/" + root_ai.content_id and md5sum != root_ai.md5:
                                raise RuntimePreparationError(
                                    RuntimePreparationCode.CHECKSUM_MISMATCH
                                )
            except RuntimePreparationError:
                raise
            except Exception as exc:
                raise RuntimePreparationError(RuntimePreparationCode.DEPENDENCY_FAILURE) from exc
            self._ai_bundle[root_ai.content_id] = bundle
        content_type = "ai" if pin.key == root_ai.key else "ai-library"
        selected = bundle.get((content_type + "/" + (pin.content_id or ""), pin.filename))
        if selected is None:
            raise RuntimePreparationError(RuntimePreparationCode.DEPENDENCY_FAILURE)
        selected_data, reported_md5 = selected
        if pin.md5 is None or not reported_md5.startswith(pin.md5):
            raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
        destination.write_bytes(selected_data)


def _sha256(path: Path, deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            _check_deadline(deadline)
            digest.update(chunk)
    _check_deadline(deadline)
    return digest.hexdigest()


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or not path.parts
        or name.startswith("/")
        or "\\" in name
        or ".." in path.parts
        or PureWindowsPath(name).is_absolute()
        or ":" in path.parts[0]
    ):
        raise RuntimePreparationError(RuntimePreparationCode.UNSAFE_ARCHIVE_PATH)
    return path


def _validated_tar(path: Path, deadline: float | None = None) -> list[tarfile.TarInfo]:
    try:
        with tarfile.open(path, "r:*") as archive:
            members = []
            for member in archive:
                _check_deadline(deadline)
                members.append(member)
            by_name = {member.name: member for member in members}
            total_size = 0
            for member in members:
                _check_deadline(deadline)
                _safe_member(member.name)
                if member.issym():
                    target = _safe_member(member.linkname)
                    target_name = str(PurePosixPath(member.name).parent / target)
                    if target_name not in by_name or not by_name[target_name].isfile():
                        raise RuntimePreparationError(RuntimePreparationCode.UNSAFE_ARCHIVE_PATH)
                elif not (member.isfile() or member.isdir()):
                    raise RuntimePreparationError(RuntimePreparationCode.UNSAFE_ARCHIVE_PATH)
                total_size += member.size
                if total_size > 256 * 1024 * 1024:
                    raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
            return members
    except RuntimePreparationError:
        raise
    except (tarfile.TarError, lzma.LZMAError, EOFError, OSError) as exc:
        raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE) from exc


def _release_files(members: list[tarfile.TarInfo]) -> list[tuple[str, tarfile.TarInfo]]:
    root = "openttd-13.4-linux-generic-amd64/"
    directories = ("lang/", "lib/", "share/", "ai/", "game/", "baseset/")
    selected = [
        (member.name[len(root) :], member)
        for member in members
        if (member.isfile() or member.issym())
        and member.name.startswith(root)
        and (
            member.name[len(root) :] == "openttd"
            or member.name[len(root) :].startswith(directories)
        )
    ]
    if "openttd" not in {name for name, _ in selected}:
        raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
    return selected


def _source_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> tarfile.TarInfo:
    if member.issym():
        target_name = str(PurePosixPath(member.name).parent / member.linkname)
        return archive.getmember(target_name)
    return member


def _archive_file_hashes(
    pin: AssetPin, archive_path: Path, deadline: float | None = None
) -> dict[str, str]:
    """Derive the cache's expected output from pinned bytes, never from its receipt."""
    if pin.key == "openttd":
        files = _release_files(_validated_tar(archive_path, deadline))
        try:
            with tarfile.open(archive_path, "r:xz") as archive:
                hashes = {}
                for name, member in files:
                    _check_deadline(deadline)
                    stream = archive.extractfile(_source_member(archive, member))
                    if stream is None:
                        raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
                    digest = hashlib.sha256()
                    with stream as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            _check_deadline(deadline)
                            digest.update(chunk)
                    hashes[name] = digest.hexdigest()
                return hashes
        except (tarfile.TarError, OSError) as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE) from exc
    if pin.key == "opengfx":
        try:
            with zipfile.ZipFile(archive_path) as archive:
                info = archive.getinfo("opengfx-7.1.tar")
                if info.file_size > 256 * 1024 * 1024:
                    raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
                with archive.open(info) as stream:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        _check_deadline(deadline)
                        digest.update(chunk)
                return {"opengfx-7.1.tar": digest.hexdigest()}
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE) from exc
    return {}


def _materialize(pin: AssetPin, archive_path: Path, files_dir: Path) -> tuple[str, ...]:
    """Validate every archive entry; publish only launcher/content inputs."""
    files_dir.mkdir()
    if pin.key == "openttd":
        selected_files = _release_files(_validated_tar(archive_path))
        selected: list[str] = []
        try:
            with tarfile.open(archive_path, "r:xz") as archive:
                for relative, member in selected_files:
                    destination = files_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(_source_member(archive, member))
                    if source is None:
                        raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
                    with source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    destination.chmod(0o755 if relative == "openttd" else 0o644)
                    selected.append(relative)
        except RuntimePreparationError:
            raise
        except (tarfile.TarError, OSError) as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE) from exc
        if "openttd" not in selected:
            raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
        return tuple(sorted(selected))
    if pin.key == "opengfx":
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for zip_info in archive.infolist():
                    _safe_member(zip_info.filename)
                    mode = zip_info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise RuntimePreparationError(RuntimePreparationCode.UNSAFE_ARCHIVE_PATH)
                names = archive.namelist()
                if names != ["opengfx-7.1.tar"]:
                    raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
                inner = files_dir / "opengfx-7.1.tar"
                if archive.getinfo(names[0]).file_size > 256 * 1024 * 1024:
                    raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
                with archive.open(names[0]) as source, inner.open("wb") as output:
                    shutil.copyfileobj(source, output)
            inner_members = _validated_tar(inner)
            if "opengfx-7.1/opengfx.obg" not in {m.name for m in inner_members}:
                raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
        except RuntimePreparationError:
            raise
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE) from exc
        return ("opengfx-7.1.tar",)
    members = _validated_tar(archive_path)
    if not any(member.name.endswith("/info.nut") for member in members) and pin.key in {
        "simpleai",
        "trains",
    }:
        raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
    return ()


class PinnedRuntimePreparer:
    """One pinned Linux/amd64 cache, serialized across concurrent processes."""

    def __init__(
        self,
        cache_root: Path,
        *,
        source: RuntimeAssetSource | None = None,
        seed_cache: Path | None = None,
        pins: dict[str, AssetPin] | None = None,
    ) -> None:
        self.cache_root = cache_root
        self.source = source or OfficialRuntimeSource()
        self.seed_cache = seed_cache
        self.pins = pins or PINNED_ASSETS

    def prepare(
        self,
        config: ExperimentConfig,
        *,
        deadline: float | None = None,
        acquisition_policy: AcquisitionPolicy = AcquisitionPolicy.ALLOW_PROVISIONING,
    ) -> PreparedRuntime:
        _check_deadline(deadline)
        if not isinstance(acquisition_policy, AcquisitionPolicy):
            raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)
        if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
            raise RuntimePreparationError(RuntimePreparationCode.UNSUPPORTED_PIN)
        if config.openttd_version != "13.4" or config.opengfx_version != "7.1":
            raise RuntimePreparationError(RuntimePreparationCode.UNSUPPORTED_PIN)
        strategies: dict[str, PlanningStrategy] = {
            "trains-baseline": BaselineStrategy(),
            "simple-road-only": SimpleRoadOnlyStrategy(),
            "simple-multimodal": SimpleMultimodalStrategy(),
        }
        strategy = strategies.get(config.planning.strategy_identifier)
        if strategy is None or strategy.configure(config.scenario) != (config.planning, config.ai):
            raise RuntimePreparationError(RuntimePreparationCode.UNSUPPORTED_PIN)
        ai_key = "trains" if strategy.identifier == "trains-baseline" else "simpleai"
        try:
            ai_pin = self.pins[ai_key]
            required = ("openttd", "opengfx", ai_key, *ai_pin.dependencies)
            pins = [self.pins[key] for key in required]
        except KeyError as exc:
            raise RuntimePreparationError(RuntimePreparationCode.DEPENDENCY_FAILURE) from exc
        if ai_pin.content_id != config.ai.content_id or ai_pin.md5 != config.ai.md5:
            raise RuntimePreparationError(RuntimePreparationCode.UNSUPPORTED_PIN)
        root = self.cache_root / "openttd-13.4-pinned-v1"
        try:
            if acquisition_policy is AcquisitionPolicy.CACHE_ONLY:
                if not root.is_dir() or root.is_symlink():
                    raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET)
            else:
                root.mkdir(parents=True, exist_ok=True)
            with (root / ".prepare.lock").open("a+b") as lock:
                if deadline is None:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)
                    # flock(1) times out in the kernel and exits. The inherited open
                    # file description keeps its acquired lock owned by this process;
                    # subprocess.run also reaps the helper on success or timeout.
                    locker = shutil.which("flock")
                    if locker is None:
                        raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)
                    try:
                        outcome = subprocess.run(
                            (locker, "-x", "-w", str(remaining), str(lock.fileno())),
                            pass_fds=(lock.fileno(),),
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=remaining,
                            check=False,
                        )
                    except OSError, subprocess.TimeoutExpired:
                        raise RuntimePreparationError(
                            RuntimePreparationCode.CACHE_FAILURE
                        ) from None
                    if outcome.returncode != 0:
                        raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)
                    if time.monotonic() >= deadline:
                        fcntl.flock(lock, fcntl.LOCK_UN)
                        raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE)
                try:
                    for pin in pins:
                        _check_deadline(deadline)
                        self._ensure(root, pin, ai_pin, acquisition_policy, deadline)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except RuntimePreparationError:
            raise
        except OSError as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE) from exc
        asset_metadata = tuple(
            {
                "key": pin.key,
                "version": pin.version,
                "sha256": pin.sha256,
                "content_id": pin.content_id,
                "md5": pin.md5,
            }
            for pin in pins
        )
        return PreparedRuntime(
            executable_path=root / "openttd" / "files" / "openttd",
            opengfx_archive_path=root / "opengfx" / "files" / "opengfx-7.1.tar",
            ai_archive_path=root / ai_key / "archive",
            dependency_archive_paths=tuple(root / key / "archive" for key in ai_pin.dependencies),
            ai_configuration=config.ai,
            provenance={
                "openttd_version": "13.4",
                "opengfx_version": "7.1",
                "ai_content_id": config.ai.content_id,
                "ai_version": ai_pin.version,
                "ai_md5": config.ai.md5,
                "cache_identity": "openttd-13.4-pinned-v1",
                "assets": asset_metadata,
            },
        )

    def _ensure(
        self,
        root: Path,
        pin: AssetPin,
        ai_pin: AssetPin,
        acquisition_policy: AcquisitionPolicy,
        deadline: float | None,
    ) -> None:
        _check_deadline(deadline)
        entry = root / pin.key
        if entry.exists():
            if entry.is_symlink():
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            self._verify_entry(entry, pin, deadline)
            return
        if acquisition_policy is AcquisitionPolicy.CACHE_ONLY:
            raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET)
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=root) as temporary:
            stage = Path(temporary)
            archive = stage / "archive"
            if self.seed_cache is not None:
                candidate = self.seed_cache / ("bananas" if pin.content_id else "") / pin.filename
                if candidate.is_file():
                    shutil.copyfile(candidate, archive)
            if not archive.exists():
                try:
                    self.source.fetch(pin, archive, root_ai=ai_pin if pin.content_id else None)
                except RuntimePreparationError:
                    raise
                except FileNotFoundError as exc:
                    raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET) from exc
                except Exception as exc:
                    code = (
                        RuntimePreparationCode.DEPENDENCY_FAILURE
                        if pin.content_id
                        else RuntimePreparationCode.MISSING_ASSET
                    )
                    raise RuntimePreparationError(code) from exc
            if not archive.is_file():
                raise RuntimePreparationError(RuntimePreparationCode.MISSING_ASSET)
            if archive.stat().st_size > MAX_ARCHIVE_BYTES:
                raise RuntimePreparationError(RuntimePreparationCode.CORRUPT_ARCHIVE)
            if _sha256(archive) != pin.sha256:
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            paths = _materialize(pin, archive, stage / "files")
            hashes = {path: _sha256(stage / "files" / path) for path in paths}
            (stage / "receipt.json").write_text(
                json.dumps({"key": pin.key, "sha256": pin.sha256, "files": hashes}, sort_keys=True)
            )
            try:
                os.replace(stage, entry)
            except OSError as exc:
                raise RuntimePreparationError(RuntimePreparationCode.CACHE_FAILURE) from exc

    @staticmethod
    def _verify_entry(entry: Path, pin: AssetPin, deadline: float | None = None) -> None:
        try:
            _check_deadline(deadline)
            for path in entry.rglob("*"):
                _check_deadline(deadline)
                if path.is_symlink():
                    raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            receipt_path = entry / "receipt.json"
            archive_path = entry / "archive"
            if (
                not receipt_path.is_file()
                or receipt_path.stat().st_size > 1024 * 1024
                or not archive_path.is_file()
                or archive_path.stat().st_size > MAX_ARCHIVE_BYTES
            ):
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            receipt = json.loads(receipt_path.read_text())
            _check_deadline(deadline)
            if receipt["key"] != pin.key or receipt["sha256"] != pin.sha256:
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            if _sha256(archive_path, deadline) != pin.sha256:
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            expected_files = _archive_file_hashes(pin, archive_path, deadline)
            if receipt["files"] != expected_files:
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            actual_files = set()
            for path in (entry / "files").rglob("*"):
                _check_deadline(deadline)
                if path.is_file():
                    actual_files.add(str(path.relative_to(entry / "files")))
            if actual_files != expected_files.keys():
                raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            for relative, expected in expected_files.items():
                _check_deadline(deadline)
                _safe_member(relative)
                output_path = entry / "files" / relative
                if not output_path.is_file() or _sha256(output_path, deadline) != expected:
                    raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH)
            _check_deadline(deadline)
        except RuntimePreparationError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimePreparationError(RuntimePreparationCode.CHECKSUM_MISMATCH) from exc
