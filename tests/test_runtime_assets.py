"""Pinned runtime preparation through controlled local archive/source fixtures."""

import hashlib
import io
import json
import multiprocessing
import tarfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.strategies import (
    BaselineStrategy,
    PlanningStrategy,
    SimpleMultimodalStrategy,
    SimpleRoadOnlyStrategy,
)
from app.simulation.openttd.runtime_assets import (
    AssetPin,
    OfficialRuntimeSource,
    PinnedRuntimePreparer,
    RuntimeAssetSource,
    RuntimePreparationCode,
    RuntimePreparationError,
)


def _tar(members: dict[str, bytes], *, compression: str = "") -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:" + compression) as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return output.getvalue()


def _tar_with_link(target: str) -> bytes:
    output = io.BytesIO()
    root = "openttd-13.4-linux-generic-amd64/"
    with tarfile.open(fileobj=output, mode="w:xz") as archive:
        binary = tarfile.TarInfo(root + "openttd")
        binary.size = 6
        archive.addfile(binary, io.BytesIO(b"binary"))
        library = tarfile.TarInfo(root + "lib/libexample.so.1.0")
        library.size = 7
        archive.addfile(library, io.BytesIO(b"library"))
        alias = tarfile.TarInfo(root + "lib/libexample.so.1")
        alias.type = tarfile.SYMTYPE
        alias.linkname = target
        archive.addfile(alias)
    return output.getvalue()


class _LocalSource(RuntimeAssetSource):
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.calls: list[str] = []

    def fetch(self, pin: AssetPin, destination: Path, *, root_ai: AssetPin | None = None) -> None:
        self.calls.append(pin.key)
        destination.write_bytes(self.blobs[pin.key])


def _fixture_assets(
    *, dependencies: bool = False, baseline: bool = False
) -> tuple[dict[str, AssetPin], dict[str, bytes]]:
    blobs = {
        "openttd": _tar({"openttd-13.4-linux-generic-amd64/openttd": b"binary"}, compression="xz"),
        "opengfx": _zip({"opengfx-7.1.tar": _tar({"opengfx-7.1/opengfx.obg": b"gfx"})}),
        "simpleai": _tar({"SimpleAI-14/info.nut": b"SimpleAI"}),
    }
    pins = {
        key: AssetPin(
            key=key,
            version={"openttd": "13.4", "opengfx": "7.1", "simpleai": "14"}[key],
            filename={
                "openttd": "openttd-13.4-linux-generic-amd64.tar.xz",
                "opengfx": "opengfx-7.1-all.zip",
                "simpleai": "534d504c-SimpleAI-14.tar",
            }[key],
            sha256=hashlib.sha256(blob).hexdigest(),
            content_id="534d504c" if key == "simpleai" else None,
            md5="b3137bbd0c73641cf510ead06e36dab6" if key == "simpleai" else None,
        )
        for key, blob in blobs.items()
    }
    if dependencies:
        blobs["pathfinder_road"] = _tar({"Pathfinder.Road-4/library.nut": b"road"})
        pins["pathfinder_road"] = AssetPin(
            "pathfinder_road",
            "4",
            "5046524f-Pathfinder.Road-4.tar",
            hashlib.sha256(blobs["pathfinder_road"]).hexdigest(),
            "5046524f",
            "999de61c",
        )
        pins["simpleai"] = replace(pins["simpleai"], dependencies=("pathfinder_road",))
    if baseline:
        blobs["trains"] = _tar({"trAIns-2.1/info.nut": b"trAIns"})
        pins["trains"] = AssetPin(
            "trains",
            "2.1",
            "54524149-trAIns-2.1.tar",
            hashlib.sha256(blobs["trains"]).hexdigest(),
            "54524149",
            "c4c069dc797674e545411b59867ad0c2",
        )
    return pins, blobs


def _config(strategy: PlanningStrategy | None = None) -> ExperimentConfig:
    scenario = ScenarioConfig(identifier="demo", version="1")
    chosen = strategy or SimpleRoadOnlyStrategy()
    planning, ai = chosen.configure(scenario)
    return ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=17,
        duration_days=30,
    )


def _prepare_in_child(
    cache_root: str, pins: dict[str, AssetPin], blobs: dict[str, bytes], ready, start, result
) -> None:
    ready.put(True)
    start.wait()
    try:
        runtime = PinnedRuntimePreparer(
            Path(cache_root), source=_LocalSource(blobs), pins=pins
        ).prepare(_config())
        result.put(runtime.executable_path.is_file())
    except Exception as error:
        result.put(type(error).__name__)


def test_prepares_verified_pinned_runtime_and_reuses_cache(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    source = _LocalSource(blobs)
    preparer = PinnedRuntimePreparer(tmp_path, source=source, pins=pins)

    first = preparer.prepare(_config())
    second = preparer.prepare(_config())

    assert first.executable_path.read_bytes() == b"binary"
    assert first.opengfx_archive_path.read_bytes().startswith(b"opengfx")
    assert first.ai_archive_path.exists()
    assert first.ai_configuration == _config().ai
    assert first.provenance["openttd_version"] == "13.4"
    assert first.provenance["ai_content_id"] == "534d504c"
    assert first == second
    assert source.calls == ["openttd", "opengfx", "simpleai"]


def test_existing_road_multimodal_and_baseline_ai_settings_survive(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets(dependencies=True, baseline=True)
    source = _LocalSource(blobs)
    preparer = PinnedRuntimePreparer(tmp_path, source=source, pins=pins)
    for strategy in (SimpleRoadOnlyStrategy(), SimpleMultimodalStrategy(), BaselineStrategy()):
        config = _config(strategy)
        runtime = preparer.prepare(config)
        assert runtime.ai_configuration == config.ai
        assert runtime.ai_configuration.parameters == config.ai.parameters
        assert runtime.provenance["ai_content_id"] == config.ai.content_id
        assert runtime.provenance["ai_md5"] == config.ai.md5
        assert all(path.exists() for path in runtime.dependency_archive_paths)
    assert source.calls.count("simpleai") == 1
    assert source.calls.count("pathfinder_road") == 1
    assert source.calls.count("trains") == 1


def test_version_and_ai_identity_mismatches_fail_before_fetch(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    source = _LocalSource(blobs)
    preparer = PinnedRuntimePreparer(tmp_path, source=source, pins=pins)
    for config in (
        _config().model_copy(update={"openttd_version": "14.0"}),
        _config().model_copy(update={"opengfx_version": "7.0"}),
        _config().model_copy(update={"ai": _config().ai.model_copy(update={"md5": "0" * 32})}),
    ):
        with pytest.raises(RuntimePreparationError) as error:
            preparer.prepare(config)
        assert error.value.code is RuntimePreparationCode.UNSUPPORTED_PIN
    assert source.calls == []


def test_checksum_mismatch_is_not_published_or_reused(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    blobs["openttd"] = b"wrong bytes"
    preparer = PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins)
    with pytest.raises(RuntimePreparationError) as error:
        preparer.prepare(_config())
    assert error.value.code is RuntimePreparationCode.CHECKSUM_MISMATCH
    assert not (tmp_path / "openttd-13.4-pinned-v1" / "openttd").exists()


def test_missing_dependency_is_typed_and_never_partial_published(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets(dependencies=True)
    del blobs["pathfinder_road"]
    preparer = PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins)
    with pytest.raises(RuntimePreparationError) as error:
        preparer.prepare(_config())
    assert error.value.code is RuntimePreparationCode.DEPENDENCY_FAILURE
    assert not (tmp_path / "openttd-13.4-pinned-v1" / "pathfinder_road").exists()


def test_interrupted_provisioning_leaves_no_valid_looking_asset(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()

    class InterruptedSource(_LocalSource):
        def fetch(
            self, pin: AssetPin, destination: Path, *, root_ai: AssetPin | None = None
        ) -> None:
            destination.write_bytes(b"partial")
            raise OSError("private path or token that must not escape")

    with pytest.raises(RuntimePreparationError) as error:
        PinnedRuntimePreparer(tmp_path, source=InterruptedSource(blobs), pins=pins).prepare(
            _config()
        )
    assert error.value.code is RuntimePreparationCode.MISSING_ASSET
    assert "private path" not in str(error.value)
    root = tmp_path / "openttd-13.4-pinned-v1"
    assert not (root / "openttd").exists()
    assert list(root.glob(".staging-*")) == []


@pytest.mark.parametrize("bad_name", ["../escape", "/absolute/escape", "C:\\escape"])
def test_tar_archive_rejects_unsafe_paths(tmp_path: Path, bad_name: str) -> None:
    pins, blobs = _fixture_assets()
    blobs["openttd"] = _tar(
        {
            "openttd-13.4-linux-generic-amd64/openttd": b"binary",
            bad_name: b"evil",
        },
        compression="xz",
    )
    pins["openttd"] = replace(pins["openttd"], sha256=hashlib.sha256(blobs["openttd"]).hexdigest())
    with pytest.raises(RuntimePreparationError) as error:
        PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(_config())
    assert error.value.code is RuntimePreparationCode.UNSAFE_ARCHIVE_PATH
    assert not (tmp_path / "escape").exists()


def test_zip_archive_rejects_traversal_and_corruption(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    blobs["opengfx"] = _zip({"../escape": b"evil", "opengfx-7.1.tar": b"not a tar"})
    pins["opengfx"] = replace(pins["opengfx"], sha256=hashlib.sha256(blobs["opengfx"]).hexdigest())
    with pytest.raises(RuntimePreparationError) as error:
        PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(_config())
    assert error.value.code is RuntimePreparationCode.UNSAFE_ARCHIVE_PATH
    assert not (tmp_path / "escape").exists()


def test_corrupt_archive_fails_after_checksum_verification(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    blobs["openttd"] = b"not a tar"
    pins["openttd"] = replace(pins["openttd"], sha256=hashlib.sha256(blobs["openttd"]).hexdigest())
    with pytest.raises(RuntimePreparationError) as error:
        PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(_config())
    assert error.value.code is RuntimePreparationCode.CORRUPT_ARCHIVE


def test_release_relative_library_symlink_is_materialized_safely(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    blobs["openttd"] = _tar_with_link("libexample.so.1.0")
    pins["openttd"] = replace(pins["openttd"], sha256=hashlib.sha256(blobs["openttd"]).hexdigest())
    runtime = PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(
        _config()
    )
    assert (runtime.executable_path.parent / "lib/libexample.so.1").read_bytes() == b"library"


@pytest.mark.parametrize("target", ["../../escape", "/absolute/escape"])
def test_release_unsafe_library_symlink_is_rejected(tmp_path: Path, target: str) -> None:
    pins, blobs = _fixture_assets()
    blobs["openttd"] = _tar_with_link(target)
    pins["openttd"] = replace(pins["openttd"], sha256=hashlib.sha256(blobs["openttd"]).hexdigest())
    with pytest.raises(RuntimePreparationError) as error:
        PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(_config())
    assert error.value.code is RuntimePreparationCode.UNSAFE_ARCHIVE_PATH


def test_concurrent_preparation_publishes_each_asset_once(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    source = _LocalSource(blobs)
    barrier = threading.Barrier(2)

    def prepare() -> object:
        barrier.wait()
        return PinnedRuntimePreparer(tmp_path, source=source, pins=pins).prepare(_config())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(prepare)
        second = pool.submit(prepare)
        assert first.result() == second.result()
    assert source.calls == ["openttd", "opengfx", "simpleai"]


def test_concurrent_processes_share_verified_publication(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    context = multiprocessing.get_context("fork")
    ready = context.Queue()
    result = context.Queue()
    start = context.Event()
    workers = [
        context.Process(
            target=_prepare_in_child, args=(str(tmp_path), pins, blobs, ready, start, result)
        )
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        for _ in workers:
            assert ready.get(timeout=5) is True
        start.set()
        assert [result.get(timeout=5) for _ in workers] == [True, True]
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)


def test_cached_extracted_file_is_verified_before_reuse(tmp_path: Path) -> None:
    pins, blobs = _fixture_assets()
    source = _LocalSource(blobs)
    preparer = PinnedRuntimePreparer(tmp_path, source=source, pins=pins)
    prepared = preparer.prepare(_config())
    prepared.executable_path.write_bytes(b"corrupted")
    with pytest.raises(RuntimePreparationError) as error:
        preparer.prepare(_config())
    assert error.value.code is RuntimePreparationCode.CHECKSUM_MISMATCH
    assert source.calls == ["openttd", "opengfx", "simpleai"]


@pytest.mark.parametrize("tamper", ["omit", "bless_corruption"])
def test_tampered_receipt_cannot_bless_missing_or_changed_executable(
    tmp_path: Path, tamper: str
) -> None:
    pins, blobs = _fixture_assets()
    preparer = PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins)
    runtime = preparer.prepare(_config())
    receipt_path = runtime.executable_path.parents[1] / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if tamper == "omit":
        receipt["files"] = {}
        runtime.executable_path.unlink()
    else:
        runtime.executable_path.write_bytes(b"other-binary")
        receipt["files"]["openttd"] = hashlib.sha256(b"other-binary").hexdigest()
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(RuntimePreparationError) as error:
        preparer.prepare(_config())
    assert error.value.code is RuntimePreparationCode.CHECKSUM_MISMATCH


def test_cache_lock_and_publication_failures_are_typed(tmp_path: Path, monkeypatch) -> None:
    import app.simulation.openttd.runtime_assets as module

    pins, blobs = _fixture_assets()
    source = _LocalSource(blobs)

    def fail(*_args: object) -> None:
        raise OSError("private path must not escape")

    monkeypatch.setattr(module.fcntl, "flock", fail)
    with pytest.raises(RuntimePreparationError) as lock_error:
        PinnedRuntimePreparer(tmp_path, source=source, pins=pins).prepare(_config())
    assert lock_error.value.code is RuntimePreparationCode.CACHE_FAILURE
    assert source.calls == []
    monkeypatch.undo()

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(RuntimePreparationError) as publication_error:
        PinnedRuntimePreparer(tmp_path, source=source, pins=pins).prepare(_config())
    assert publication_error.value.code is RuntimePreparationCode.CACHE_FAILURE
    assert "private path" not in str(publication_error.value)
    assert not (tmp_path / "openttd-13.4-pinned-v1" / "openttd").exists()


def test_provenance_is_sanitized_and_preparation_starts_no_process(
    tmp_path: Path, monkeypatch
) -> None:
    import subprocess

    def reject_process(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("process execution is outside T05")

    monkeypatch.setattr(subprocess, "Popen", reject_process)
    pins, blobs = _fixture_assets()
    runtime = PinnedRuntimePreparer(tmp_path, source=_LocalSource(blobs), pins=pins).prepare(
        _config()
    )
    serialized = repr(runtime.provenance).lower()
    assert "password" not in serialized
    assert "secret" not in serialized
    assert "environment" not in serialized
    assert str(tmp_path) not in serialized
    assert runtime.provenance["assets"][2]["sha256"] == pins["simpleai"].sha256


def test_official_release_source_requires_matching_manifest_before_using_download(
    tmp_path: Path, monkeypatch
) -> None:
    import app.simulation.openttd.runtime_assets as module

    pins, blobs = _fixture_assets()
    pin = pins["openttd"]
    manifest = (
        "version: 13.4\nfiles:\n"
        f"- id: {pin.filename}\n  size: {len(blobs['openttd'])}\n"
        f"  sha256sum: {pin.sha256}\n"
    ).encode()
    requested: list[str] = []

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def iter_bytes(self):
            yield self.content

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def stream(self, method: str, url: str) -> Response:
            assert method == "GET"
            requested.append(url)
            return Response(manifest if url.endswith("manifest.yaml") else blobs["openttd"])

    monkeypatch.setattr(module.httpx, "Client", Client)
    target = tmp_path / "download"
    OfficialRuntimeSource().fetch(pin, target)
    assert target.read_bytes() == blobs["openttd"]
    assert requested == [
        "https://cdn.openttd.org/openttd-releases/13.4/manifest.yaml",
        "https://cdn.openttd.org/openttd-releases/13.4/" + pin.filename,
    ]


def test_public_lab_helper_is_used_only_for_pinned_ai_content(tmp_path: Path, monkeypatch) -> None:
    import openttdlab

    pins, blobs = _fixture_assets()
    called: list[tuple[str, str]] = []

    class Content:
        def __enter__(self):
            return iter([blobs["simpleai"]])

        def __exit__(self, *_args: object) -> None:
            pass

    class Download:
        def __enter__(self):
            return [
                ("ai/534d504c", pins["simpleai"].filename, "GPL v2", pins["simpleai"].md5, Content)
            ]

        def __exit__(self, *_args: object) -> None:
            pass

    def public_download(content_id: str, *, md5: str, get_cache_dir) -> Download:
        called.append((content_id, md5))
        assert get_cache_dir()
        return Download()

    monkeypatch.setattr(openttdlab, "download_from_bananas", public_download)
    target = tmp_path / "ai.tar"
    OfficialRuntimeSource().fetch(pins["simpleai"], target, root_ai=pins["simpleai"])
    assert target.read_bytes() == blobs["simpleai"]
    assert called == [("ai/534d504c", "b3137bbd0c73641cf510ead06e36dab6")]


def test_official_source_rejects_manifest_checksum_without_fetching_archive(
    tmp_path: Path, monkeypatch
) -> None:
    import app.simulation.openttd.runtime_assets as module

    pins, _ = _fixture_assets()
    requested: list[str] = []

    class Response:
        content = (
            f"version: 13.4\nfiles:\n- id: {pins['openttd'].filename}\n"
            "  size: 123\n  sha256sum: wrong\n"
        ).encode()

        def raise_for_status(self) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def iter_bytes(self):
            yield self.content

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def stream(self, method: str, url: str) -> Response:
            assert method == "GET"
            requested.append(url)
            return Response()

    monkeypatch.setattr(module.httpx, "Client", Client)
    with pytest.raises(RuntimePreparationError) as error:
        OfficialRuntimeSource().fetch(pins["openttd"], tmp_path / "archive")
    assert error.value.code is RuntimePreparationCode.CHECKSUM_MISMATCH
    assert len(requested) == 1


@pytest.mark.parametrize("oversized", ["manifest", "archive"])
def test_official_source_bounds_streamed_downloads_before_publication(
    tmp_path: Path, monkeypatch, oversized: str
) -> None:
    import app.simulation.openttd.runtime_assets as module

    pins, blobs = _fixture_assets()
    pin = pins["openttd"]
    manifest = (
        "version: 13.4\nfiles:\n"
        f"- id: {pin.filename}\n  size: {len(blobs['openttd'])}\n"
        f"  sha256sum: {pin.sha256}\n"
    ).encode()
    requested: list[str] = []

    class Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self):
            yield self.payload

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def stream(self, method: str, url: str) -> Response:
            assert method == "GET"
            requested.append(url)
            if url.endswith("manifest.yaml"):
                return Response(b"x" * (1024 * 1024 + 1) if oversized == "manifest" else manifest)
            return Response(blobs["openttd"] + b"extra")

    monkeypatch.setattr(module.httpx, "Client", Client)
    target = tmp_path / "download"
    with pytest.raises(RuntimePreparationError) as error:
        OfficialRuntimeSource().fetch(pin, target)
    assert error.value.code is (
        RuntimePreparationCode.MISSING_ASSET
        if oversized == "manifest"
        else RuntimePreparationCode.CHECKSUM_MISMATCH
    )
    assert len(requested) == (1 if oversized == "manifest" else 2)


def test_runtime_module_has_no_private_launcher_or_prototype_dependency() -> None:
    import ast

    path = Path(__file__).resolve().parents[1] / "app/simulation/openttd/runtime_assets.py"
    syntax = ast.parse(path.read_text())
    imports = [
        alias.name
        for node in ast.walk(syntax)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [node.module or "" for node in ast.walk(syntax) if isinstance(node, ast.ImportFrom)]
    assert not any(name.startswith("prototype") for name in imports)
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "_run_experiment"
        for node in ast.walk(syntax)
    )
