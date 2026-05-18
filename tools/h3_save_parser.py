#!/usr/bin/env python3
"""Contracts and constants for Heroes III save parsing."""

from __future__ import annotations

import gzip
import re
import zlib
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from tools.battle_estimator import Creature
    except ImportError:  # pragma: no cover - used only for type checking.
        from battle_estimator import Creature


DEFAULT_AUTOSAVE_ROOT = (
    Path.home()
    / "Applications"
    / "Heroes of Might and Magic 3.app"
    / "Contents"
    / "SharedSupport"
    / "prefix"
    / "drive_c"
    / "GOG Games"
    / "HoMM 3 Complete"
    / "Games"
    / "Random"
    / "PlayerTwo"
)
CONFIG_PATH = Path.home() / ".config" / "vcmi-battle-estimator" / "config.json"

SAVE_EXTENSIONS = (".GM1", ".GM2")
H3SVG_SIGNATURE = b"H3SVG"
GAME_FOLDER_DATE_PATTERN = re.compile(
    r"^(?P<year>\d{4})\.(?P<month>\d{2})\.(?P<day>\d{2})"
    r"\s+"
    r"(?P<hour>\d{2})[;:](?P<minute>\d{2})(?:\b|$)"
)
NUMERIC_SAVE_PATTERN = re.compile(r"^(?P<number>\d+)\.(?P<ext>gm[12])$", re.I)

HERO_ARMY_SLOT_COUNT = 7
HERO_ARMY_VALUE_SIZE = 4
HERO_NAME_SIZE = 13
HERO_ARMY_XOR_KEY = 0x01

HERO_STRUCT_ARMY_TYPES_OFFSET = 113
HERO_STRUCT_ARMY_COUNTS_OFFSET = 141
HERO_STRUCT_NAME_OFFSET = 169

HERO_ARMY_TYPES_FROM_NAME_OFFSET = (
    HERO_STRUCT_ARMY_TYPES_OFFSET - HERO_STRUCT_NAME_OFFSET
)
HERO_ARMY_COUNTS_FROM_NAME_OFFSET = (
    HERO_STRUCT_ARMY_COUNTS_OFFSET - HERO_STRUCT_NAME_OFFSET
)


@dataclass(frozen=True)
class SaveContext:
    """Selected autosave location and file metadata."""

    autosave_root: Path = DEFAULT_AUTOSAVE_ROOT
    game_dir: Path | None = None
    save_file: Path | None = None


@dataclass(frozen=True)
class LoadedSave:
    """Decompressed save bytes with the located H3SVG signature offset."""

    path: Path
    data: bytes
    h3svg_offset: int


@dataclass(frozen=True)
class HeroStack:
    """One non-empty hero army slot."""

    creature_id: int
    creature: Creature
    count: int

    @classmethod
    def from_creature_id(cls, creature_id: int, count: int) -> HeroStack:
        return cls(
            creature_id=creature_id,
            creature=creature_by_id(creature_id),
            count=count,
        )


@dataclass(frozen=True)
class HeroArmy:
    """Army stacks detected for one hero in a save file."""

    hero_name: str
    stacks: tuple[HeroStack, ...]
    source_offset: int | None = None

    @property
    def total_creatures(self) -> int:
        return sum(stack.count for stack in self.stacks)

    @property
    def ai_value(self) -> int:
        return sum(stack.creature.ai_value * stack.count for stack in self.stacks)


class SaveLoadError(ValueError):
    """Raised when a Heroes III save cannot be loaded or identified."""


class SaveSelectionError(ValueError):
    """Raised when autosave folder or save-file selection fails."""

    def __init__(self, path: str | Path, reason: str):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


def load_save(path: str | Path) -> LoadedSave:
    """Read and decompress a Heroes III save file."""

    save_path = Path(path)
    try:
        compressed = save_path.read_bytes()
    except OSError as exc:
        raise SaveLoadError(f"{save_path}: read failed: {exc}") from exc

    raw = _decompress_save_bytes(compressed, save_path)
    h3svg_offset = find_h3svg_offset(raw)
    if h3svg_offset is None:
        raise SaveLoadError(f"{save_path}: missing H3SVG signature")
    return LoadedSave(path=save_path, data=raw, h3svg_offset=h3svg_offset)


def find_h3svg_offset(data: bytes) -> int | None:
    """Return the offset of the H3SVG signature, if present."""

    offset = data.find(H3SVG_SIGNATURE)
    if offset == -1:
        return None
    return offset


def parse_game_folder_datetime(name: str) -> datetime | None:
    """Parse a timestamp from an autosave game folder name."""

    match = GAME_FOLDER_DATE_PATTERN.match(name)
    if not match:
        return None
    try:
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
        )
    except ValueError:
        return None


def select_game_dir(
    explicit_game_dir: str | Path | None = None,
    autosave_root: str | Path = DEFAULT_AUTOSAVE_ROOT,
) -> Path:
    """Return an explicit game folder or the newest dated child folder."""

    if explicit_game_dir is not None:
        game_dir = Path(explicit_game_dir)
        if not game_dir.is_dir():
            raise SaveSelectionError(game_dir, "selected game folder is not a directory")
        return game_dir

    root = Path(autosave_root)
    if not root.is_dir():
        raise SaveSelectionError(root, "autosave root is not a directory")

    try:
        child_dirs = [path for path in root.iterdir() if path.is_dir()]
    except OSError as exc:
        raise SaveSelectionError(root, f"failed to list autosave root: {exc}") from exc

    dated_dirs = []
    for child_dir in child_dirs:
        folder_date = parse_game_folder_datetime(child_dir.name)
        if folder_date is not None:
            dated_dirs.append((folder_date, child_dir.name, child_dir))

    if not dated_dirs:
        raise SaveSelectionError(root, "no dated autosave game folders found")
    return max(dated_dirs, key=lambda item: (item[0], item[1]))[2]


def parse_numeric_save_name(path_or_name: str | Path) -> tuple[int, int] | None:
    """Return numeric save number and extension rank for GM1/GM2 names."""

    name = Path(path_or_name).name
    match = NUMERIC_SAVE_PATTERN.match(name)
    if not match:
        return None
    extension_rank = 2 if match.group("ext").lower() == "gm2" else 1
    return int(match.group("number")), extension_rank


def select_latest_save(game_dir: str | Path) -> Path:
    """Return the highest numeric GM1/GM2 save in a game folder."""

    folder = Path(game_dir)
    if not folder.is_dir():
        raise SaveSelectionError(folder, "game folder is not a directory")

    try:
        children = list(folder.iterdir())
    except OSError as exc:
        raise SaveSelectionError(folder, f"failed to list game folder: {exc}") from exc

    candidates = []
    for child in children:
        if not child.is_file():
            continue
        numeric_save = parse_numeric_save_name(child)
        if numeric_save is not None:
            candidates.append((*numeric_save, child.name, child))

    if not candidates:
        raise SaveSelectionError(folder, "no numeric GM1/GM2 saves found")
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def resolve_save_context(
    explicit_game_dir: str | Path | None = None,
    autosave_root: str | Path = DEFAULT_AUTOSAVE_ROOT,
) -> SaveContext:
    """Resolve the selected game directory and latest save file."""

    root = Path(autosave_root)
    game_dir = select_game_dir(explicit_game_dir, root)
    save_file = select_latest_save(game_dir)
    return SaveContext(autosave_root=root, game_dir=game_dir, save_file=save_file)


def creature_by_id(creature_id: int) -> Creature:
    """Return the existing battle-estimator creature for a Heroes III ID."""

    creatures = _battle_estimator_creatures()
    if creature_id < 0 or creature_id >= len(creatures):
        raise ValueError(f"Unknown Heroes III creature id: {creature_id}")
    return creatures[creature_id]


def _battle_estimator_creatures() -> tuple[Creature, ...]:
    try:
        module = import_module("tools.battle_estimator")
    except ModuleNotFoundError as exc:
        if exc.name != "tools":
            raise
        module = import_module("battle_estimator")
    return tuple(module.CREATURES)


def _decompress_save_bytes(compressed: bytes, path: Path) -> bytes:
    try:
        return gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as gzip_exc:
        gzip_reason = f"gzip decompress failed: {gzip_exc}"

    try:
        if len(compressed) <= 18:
            raise ValueError("input too short for gzip raw deflate slice")
        return zlib.decompress(compressed[10:-8], -zlib.MAX_WBITS)
    except (OSError, ValueError, zlib.error) as raw_exc:
        raise SaveLoadError(
            f"{path}: {gzip_reason}; raw deflate fallback failed: {raw_exc}"
        ) from raw_exc
