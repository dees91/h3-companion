#!/usr/bin/env python3
"""Contracts and constants for Heroes III save parsing."""

from __future__ import annotations

import gzip
import json
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
HERO_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,12}$")

HERO_ARMY_SLOT_COUNT = 7
HERO_ARMY_VALUE_SIZE = 4
HERO_NAME_SIZE = 13
HERO_ARMY_XOR_KEY = 0x01
# Sanity cap for parser candidates, not a Heroes III game-rule limit.
MAX_HERO_ARMY_COUNT = 1_000_000
DEFAULT_RELEVANT_HERO_AI_VALUE = 5_000
DEFAULT_RELEVANT_HERO_TOTAL_CREATURES = 50

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
class BattleEstimatorConfig:
    """User-global battle estimator configuration."""

    autosave_dir: Path | None = None
    last_hero: str | None = None


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


class ConfigError(ValueError):
    """Raised when the user config cannot be read or written."""

    def __init__(self, path: str | Path, reason: str):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


class HeroSelectionError(ValueError):
    """Raised when a hero query cannot be selected unambiguously."""

    def __init__(self, query: str, reason: str, candidates):
        self.query = query
        self.reason = reason
        self.candidates = tuple(candidates)
        names = ", ".join(self.candidate_names) or "none"
        super().__init__(f"{reason}: {query!r}; candidates: {names}")

    @property
    def candidate_names(self) -> tuple[str, ...]:
        return tuple(hero.hero_name for hero in self.candidates)


def load_config(config_path: str | Path = CONFIG_PATH) -> BattleEstimatorConfig:
    """Load user configuration, returning defaults when no config exists."""

    path = Path(config_path)
    if not path.exists():
        return BattleEstimatorConfig()

    try:
        raw_config = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(path, f"read failed: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(path, f"invalid config encoding: {exc}") from exc

    try:
        data = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise ConfigError(path, f"invalid config: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(path, "invalid config: root must be an object")

    return BattleEstimatorConfig(
        autosave_dir=_read_optional_path(data, "autosave_dir", path),
        last_hero=_read_optional_text(data, "last_hero", path),
    )


def save_config(
    config: BattleEstimatorConfig,
    config_path: str | Path = CONFIG_PATH,
) -> None:
    """Persist user configuration to JSON."""

    path = Path(config_path)
    data = _config_to_json(config)
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        raise ConfigError(path, f"write failed: {exc}") from exc


def set_config_autosave_dir(
    autosave_dir: str | Path,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Save an autosave directory while preserving other config values."""

    if isinstance(autosave_dir, str) and not autosave_dir.strip():
        raise ConfigError(config_path, "invalid autosave_dir: value must not be blank")
    autosave_path = Path(autosave_dir)
    current = load_config(config_path)
    updated = BattleEstimatorConfig(
        autosave_dir=autosave_path,
        last_hero=current.last_hero,
    )
    save_config(updated, config_path)
    return updated


def clear_config_autosave_dir(
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Clear the saved autosave directory while preserving other values."""

    current = load_config(config_path)
    updated = BattleEstimatorConfig(
        autosave_dir=None,
        last_hero=current.last_hero,
    )
    save_config(updated, config_path)
    return updated


def set_config_last_hero(
    last_hero: str | None,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Save the last interactive hero name while preserving other values."""

    current = load_config(config_path)
    normalized_hero = last_hero.strip() if last_hero else ""
    updated = BattleEstimatorConfig(
        autosave_dir=current.autosave_dir,
        last_hero=normalized_hero or None,
    )
    save_config(updated, config_path)
    return updated


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


def load_hero_armies_from_save(path: str | Path) -> tuple[HeroArmy, ...]:
    """Load a save file and scan it for XOR 0x01 encoded hero armies."""

    loaded_save = load_save(path)
    return scan_xor01_hero_armies(loaded_save.data)


def find_h3svg_offset(data: bytes) -> int | None:
    """Return the offset of the H3SVG signature, if present."""

    offset = data.find(H3SVG_SIGNATURE)
    if offset == -1:
        return None
    return offset


def xor_decode_bytes(
    data: bytes,
    offset: int,
    length: int,
    key: int = HERO_ARMY_XOR_KEY,
) -> bytes:
    """Decode a byte window using the observed XOR key."""

    if offset < 0 or length < 0 or offset + length > len(data):
        raise ValueError("XOR decode window is outside data")
    return bytes(byte ^ key for byte in data[offset:offset + length])


def decode_xor_u32(data: bytes, offset: int) -> int:
    """Decode one XOR-obfuscated little-endian unsigned 32-bit integer."""

    return int.from_bytes(
        xor_decode_bytes(data, offset, HERO_ARMY_VALUE_SIZE),
        "little",
    )


def decode_hero_name(data: bytes, name_offset: int) -> str | None:
    """Decode and validate a null-padded XOR-obfuscated hero name."""

    try:
        decoded = xor_decode_bytes(data, name_offset, HERO_NAME_SIZE)
    except ValueError:
        return None

    nul_index = decoded.find(b"\x00")
    if nul_index == -1:
        name_bytes = decoded
    else:
        name_bytes = decoded[:nul_index]
        if any(byte != 0 for byte in decoded[nul_index:]):
            return None

    try:
        name = name_bytes.decode("ascii").strip()
    except UnicodeDecodeError:
        return None

    if not HERO_NAME_PATTERN.fullmatch(name):
        return None
    return name


def parse_xor01_hero_at(data: bytes, name_offset: int) -> HeroArmy | None:
    """Parse one XOR 0x01 hero-army candidate by hero-name offset."""

    if name_offset < HERO_STRUCT_NAME_OFFSET:
        return None

    hero_name = decode_hero_name(data, name_offset)
    if hero_name is None:
        return None

    ids_offset = name_offset + HERO_ARMY_TYPES_FROM_NAME_OFFSET
    counts_offset = name_offset + HERO_ARMY_COUNTS_FROM_NAME_OFFSET
    stacks = []

    try:
        for slot in range(HERO_ARMY_SLOT_COUNT):
            creature_id = decode_xor_u32(
                data,
                ids_offset + slot * HERO_ARMY_VALUE_SIZE,
            )
            count = decode_xor_u32(
                data,
                counts_offset + slot * HERO_ARMY_VALUE_SIZE,
            )
            if count == 0:
                continue
            if count > MAX_HERO_ARMY_COUNT:
                return None
            stacks.append(HeroStack.from_creature_id(creature_id, count))
    except (ValueError, OverflowError):
        return None

    if not stacks:
        return None
    return HeroArmy(hero_name=hero_name, stacks=tuple(stacks), source_offset=name_offset)


def scan_xor01_hero_armies(data: bytes) -> tuple[HeroArmy, ...]:
    """Scan decompressed save bytes for XOR 0x01 encoded hero armies."""

    heroes = []
    last_name_offset = len(data) - HERO_NAME_SIZE
    for name_offset in range(HERO_STRUCT_NAME_OFFSET, last_name_offset + 1):
        hero_army = parse_xor01_hero_at(data, name_offset)
        if hero_army is not None:
            heroes.append(hero_army)
    return tuple(heroes)


def filter_relevant_heroes(
    heroes,
    all_heroes: bool = False,
    min_ai_value: int = DEFAULT_RELEVANT_HERO_AI_VALUE,
    min_total_creatures: int = DEFAULT_RELEVANT_HERO_TOTAL_CREATURES,
) -> tuple[HeroArmy, ...]:
    """Return hero armies relevant enough for default listing/selection."""

    candidates = tuple(heroes)
    if all_heroes:
        return candidates
    return tuple(
        hero for hero in candidates
        if hero.ai_value >= min_ai_value
        or hero.total_creatures >= min_total_creatures
    )


def select_hero(heroes, query: str) -> HeroArmy:
    """Select a hero by case-insensitive exact or unambiguous prefix match."""

    candidates = tuple(heroes)
    normalized_query = query.strip().casefold()
    if not normalized_query:
        raise HeroSelectionError(query, "missing_query", candidates)

    exact_matches = tuple(
        hero for hero in candidates
        if hero.hero_name.casefold() == normalized_query
    )
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise HeroSelectionError(query, "ambiguous_exact", exact_matches)

    prefix_matches = tuple(
        hero for hero in candidates
        if hero.hero_name.casefold().startswith(normalized_query)
    )
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise HeroSelectionError(query, "ambiguous_prefix", prefix_matches)

    raise HeroSelectionError(query, "not_found", candidates)


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


def _read_optional_path(data: dict, key: str, path: Path) -> Path | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(path, f"invalid config: {key} must be a string")
    normalized = value.strip()
    if not normalized:
        return None
    return Path(normalized)


def _read_optional_text(data: dict, key: str, path: Path) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(path, f"invalid config: {key} must be a string")
    normalized = value.strip()
    return normalized or None


def _config_to_json(config: BattleEstimatorConfig) -> dict:
    data = {}
    if config.autosave_dir is not None:
        data["autosave_dir"] = str(config.autosave_dir)
    if config.last_hero is not None:
        data["last_hero"] = config.last_hero
    return data
