"""Exact native table format clock extraction, with bounded decompression."""

import lzma
import struct
import zlib

import pytest

from app.simulation.openttd import freight_canonical_save as clock


def gamma(number):
    if number < 128:
        return bytes([number])
    return bytes([128 | (number >> 8), number & 255])


def native_save(*, pause=1, compression=b"OTTN"):
    fields = dict(
        date=712223,
        date_fract=17,
        economy_date=712223,
        economy_date_fract=17,
        calendar_sub_date_fract=3,
        tick_counter=1297,
        pause_mode=pause,
    )
    headers = b"".join(b"\x08" + gamma(len(k)) + k.encode() for k in fields) + b"\0"
    row = b"".join(struct.pack(">Q", v) for v in fields.values())
    payload = b"DATE\x03" + gamma(len(headers) + 1) + headers
    payload += gamma(len(row) + 1) + row + b"\0\0\0\0\0"
    if compression == b"OTTZ":
        payload = zlib.compress(payload)
    elif compression == b"OTTX":
        payload = lzma.compress(payload)
    return compression + struct.pack(">HH", 362, 0) + payload


@pytest.mark.parametrize("compression", [b"OTTN", b"OTTZ", b"OTTX"])
def test_exact_serialized_clock(tmp_path, compression):
    path = tmp_path / "paused.sav"
    path.write_bytes(native_save(compression=compression))
    result = clock.read_save_clock(path)
    assert result == dict(
        date=712223,
        date_fract=17,
        economy_date=712223,
        economy_date_fract=17,
        calendar_sub_date_fract=3,
        tick_counter=1297,
        pause_mode=1,
    )


def test_unpaused_and_unknown_save_rejected(tmp_path):
    path = tmp_path / "paused.sav"
    path.write_bytes(native_save(pause=0))
    with pytest.raises(ValueError, match="must be paused"):
        clock.read_save_clock(path)
    path.write_bytes(b"OTTN\0\x01\0\0garbage")
    with pytest.raises(ValueError, match="version 362"):
        clock.read_save_clock(path)


def test_decompression_bound(tmp_path, monkeypatch):
    path = tmp_path / "paused.sav"
    path.write_bytes(native_save(compression=b"OTTZ"))
    monkeypatch.setattr(clock, "MAX_EXPANDED_BYTES", 32)
    with pytest.raises(ValueError, match="oversized"):
        clock.read_save_clock(path)


def test_symlink_rejected(tmp_path):
    target = tmp_path / "target.sav"
    target.write_bytes(native_save())
    link = tmp_path / "link.sav"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        clock.read_save_clock(link)
