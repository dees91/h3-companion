#!/usr/bin/env python3
"""Contracts and minimal loader for Heroes III H3M map files."""

from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass, field
from pathlib import Path


H3M_START_OFFSET_CANDIDATES = (0, 43)
H3M_HEADER_MIN_SIZE = 10
H3M_FORMAT_ROE = 0x0E
H3M_FORMAT_AB = 0x15
H3M_FORMAT_SOD = 0x1C

SUPPORTED_H3M_FORMATS = {
    H3M_FORMAT_ROE: "RoE",
    H3M_FORMAT_AB: "AB",
    H3M_FORMAT_SOD: "SoD",
}


@dataclass(frozen=True)
class H3MapHeader:
    """Minimal H3M header summary needed before object parsing."""

    format_version: int
    format_name: str
    map_size: int
    levels: int
    are_any_players: bool


@dataclass(frozen=True)
class H3ObjectTemplate:
    """One H3M object template entry."""

    template_index: int
    animation_file: str
    block_mask: bytes
    visit_mask: bytes
    terrain_mask: int
    object_id: int
    subid: int
    object_type: int
    print_priority: int


@dataclass(frozen=True)
class H3MapObject:
    """One placed H3M map object with its template index."""

    object_index: int
    x: int
    y: int
    z: int
    template_index: int


@dataclass(frozen=True)
class H3NeutralMonsterTarget:
    """Neutral monster target derived from an H3M object."""

    object_index: int
    x: int
    y: int
    z: int
    template: H3ObjectTemplate
    h3m_subid: int
    count: int
    creature_name: str | None = None
    estimator_creature_id: int | None = None


@dataclass(frozen=True)
class LoadedH3Map:
    """Decompressed H3M map bytes and parsed smoke-level metadata."""

    path: Path
    data: bytes
    h3m_offset: int
    header: H3MapHeader
    templates: tuple[H3ObjectTemplate, ...] = field(default_factory=tuple)
    objects: tuple[H3MapObject, ...] = field(default_factory=tuple)
    neutral_targets: tuple[H3NeutralMonsterTarget, ...] = field(default_factory=tuple)


class H3MapLoadError(ValueError):
    """Raised when a Heroes III map cannot be loaded or identified."""

    def __init__(self, path: str | Path, reason: str):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


def load_h3m(path: str | Path) -> LoadedH3Map:
    """Read, decompress, and parse smoke-level metadata from an H3M map."""

    map_path = Path(path)
    try:
        compressed = map_path.read_bytes()
    except OSError as exc:
        raise H3MapLoadError(map_path, f"read failed: {exc}") from exc

    return load_h3m_bytes(compressed, map_path)


def load_h3m_bytes(compressed: bytes, path: str | Path) -> LoadedH3Map:
    """Load a gzip-compressed H3M byte stream from an already-read buffer."""

    map_path = Path(path)
    data = _decompress_h3m_bytes(compressed, map_path)
    h3m_offset = find_h3m_start_offset(data)
    if h3m_offset is None:
        raise H3MapLoadError(
            map_path,
            "missing valid supported H3M header at offset 0 or 43",
        )

    header = parse_h3m_header(data, h3m_offset, map_path)
    return LoadedH3Map(
        path=map_path,
        data=data,
        h3m_offset=h3m_offset,
        header=header,
    )


def find_h3m_start_offset(data: bytes) -> int | None:
    """Return the H3M start offset for supported RoE/AB/SoD maps."""

    for offset in H3M_START_OFFSET_CANDIDATES:
        try:
            parse_h3m_header(data, offset)
        except H3MapLoadError:
            continue
        else:
            return offset
    return None


def parse_h3m_header(
    data: bytes,
    offset: int = 0,
    path: str | Path = "<memory>",
) -> H3MapHeader:
    """Parse the minimal RoE/AB/SoD H3M header fields used by NS-T01."""

    map_path = Path(path)
    if offset < 0:
        raise H3MapLoadError(map_path, f"invalid H3M start offset: {offset}")
    if offset + H3M_HEADER_MIN_SIZE > len(data):
        raise H3MapLoadError(map_path, "truncated H3M header")

    format_version = int.from_bytes(data[offset:offset + 4], "little")
    format_name = SUPPORTED_H3M_FORMATS.get(format_version)
    if format_name is None:
        raise H3MapLoadError(
            map_path,
            f"unsupported H3M format id: {format_version}",
        )

    are_any_players = bool(data[offset + 4])
    map_size = int.from_bytes(data[offset + 5:offset + 9], "little", signed=True)
    has_two_levels = bool(data[offset + 9])
    levels = 2 if has_two_levels else 1
    if map_size <= 0:
        raise H3MapLoadError(map_path, f"invalid H3M map size: {map_size}")

    return H3MapHeader(
        format_version=format_version,
        format_name=format_name,
        map_size=map_size,
        levels=levels,
        are_any_players=are_any_players,
    )


def _decompress_h3m_bytes(compressed: bytes, path: Path) -> bytes:
    try:
        return gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as exc:
        raise H3MapLoadError(path, f"gzip decompress failed: {exc}") from exc
