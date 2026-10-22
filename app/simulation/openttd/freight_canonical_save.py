"""Bounded native save clock readback through the existing OpenTTDLab parser."""

import lzma
import zlib
from pathlib import Path

from openttdlab import parse_savegame

MAX_SAVE_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
CLOCK_FIELDS = (
    "date",
    "date_fract",
    "economy_date",
    "economy_date_fract",
    "calendar_sub_date_fract",
    "tick_counter",
    "pause_mode",
)


def read_save_clock(path: Path) -> dict[str, int]:
    """Read exact serialized time; never infer fractions from script ticks.

    Only the qualified target's version 362 is accepted. Decompression is capped
    before handing the uncompressed stream to the existing parser.
    """
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("canonical clock save must not traverse symlinks")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SAVE_BYTES + 1)
    if len(raw) < 8 or len(raw) > MAX_SAVE_BYTES:
        raise ValueError("canonical save size bound")
    if int.from_bytes(raw[4:6], "big") != 362 or raw[6:8] != b"\0\0":
        raise ValueError("canonical save requires OpenTTD 15.3 version 362")
    try:
        if raw[:4] == b"OTTN":
            expanded = raw[8:]
        elif raw[:4] == b"OTTZ":
            decoder = zlib.decompressobj()
            expanded = decoder.decompress(raw[8:], MAX_EXPANDED_BYTES + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("invalid or oversized canonical zlib save")
        elif raw[:4] == b"OTTX":
            decoder_xz = lzma.LZMADecompressor(memlimit=MAX_EXPANDED_BYTES)
            expanded = decoder_xz.decompress(raw[8:], max_length=MAX_EXPANDED_BYTES + 1)
            if not decoder_xz.eof or decoder_xz.unused_data:
                raise ValueError("invalid or oversized canonical lzma save")
        else:
            raise ValueError("unsupported canonical save compression")
        if len(expanded) > MAX_EXPANDED_BYTES:
            raise ValueError("canonical expanded save size bound")
        game = parse_savegame(iter((b"OTTN" + raw[4:8], expanded)))
        records = game["chunks"]["DATE"]["records"]
        if set(records) != {"0"}:
            raise ValueError("unique native DATE record required")
        clock = {name: records["0"][name] for name in CLOCK_FIELDS}
    except (KeyError, TypeError, zlib.error, lzma.LZMAError) as error:
        raise ValueError("invalid native save clock") from error
    if any(type(value) is not int or value < 0 for value in clock.values()):
        raise ValueError("invalid native clock value")
    if not clock["pause_mode"]:
        raise ValueError("native clock snapshot must be paused")
    return clock
