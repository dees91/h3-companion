#!/usr/bin/env python3
"""Contracts and constants for Heroes III save parsing."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from tools.battle_estimator import Creature
    except ImportError:  # pragma: no cover - used only for type checking.
        from battle_estimator import Creature


DEFAULT_GAMES_ROOT = (
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
)
DEFAULT_AUTOSAVE_ROOT = DEFAULT_GAMES_ROOT
CONFIG_PATH = Path.home() / ".config" / "vcmi-battle-estimator" / "config.json"
CACHE_ROOT = Path.home() / ".cache" / "vcmi-battle-estimator"

SAVE_EXTENSIONS = (".GM1", ".GM2")
RECENT_HERO_LIMIT = 8
H3SVG_SIGNATURE = b"H3SVG"
GAME_FOLDER_DATE_PATTERN = re.compile(
    r"^(?P<year>\d{4})\.(?P<month>\d{2})\.(?P<day>\d{2})"
    r"\s+"
    r"(?P<hour>\d{2})[;:](?P<minute>\d{2})(?:\b|$)"
)
NUMERIC_SAVE_PATTERN = re.compile(r"^(?P<number>\d+)\.(?P<ext>gm[12])$", re.I)
GAME_BEGIN_SAVE_PATTERN = re.compile(r"^GAME_BEGIN\.(?P<ext>gm[12])$", re.I)
HOTSEAT_SAVE_PREFIX_PATTERN = re.compile(r"^\[hotseat\]\s+", re.I)
GAME_BEGIN_SAVE_NUMBER = -1
HIDDEN_NEUTRAL_TARGET_PATTERN = re.compile(r"^neutral:(?P<object_index>\d+)$")
HERO_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,12}$")
HERO_NAME_FIRST_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
HERO_NAME_REST_CHARS = HERO_NAME_FIRST_CHARS + b"0123456789 '-"

HERO_ARMY_SLOT_COUNT = 7
HERO_ARMY_VALUE_SIZE = 4
HERO_NAME_SIZE = 13
HERO_ARMY_XOR_KEY = 0x01
ENCODED_HERO_NAME_CANDIDATE_PATTERN = re.compile(
    rb"(?=([" +
    re.escape(bytes(byte ^ HERO_ARMY_XOR_KEY for byte in HERO_NAME_FIRST_CHARS)) +
    rb"][" +
    re.escape(
        bytes(byte ^ HERO_ARMY_XOR_KEY for byte in HERO_NAME_REST_CHARS)
        + bytes([HERO_ARMY_XOR_KEY])
    ) +
    rb"]{12}))"
)
# Sanity cap for parser candidates, not a Heroes III game-rule limit.
MAX_HERO_ARMY_COUNT = 1_000_000
DEFAULT_RELEVANT_HERO_AI_VALUE = 5_000
DEFAULT_RELEVANT_HERO_TOTAL_CREATURES = 50
REMOVED_NEUTRAL_RECORD_CORE_SIZE = 12
REMOVED_NEUTRAL_RECORD_SIZE = 16
REMOVED_NEUTRAL_COORD_RECORD_SIZE = 16
REMOVED_NEUTRAL_SCAN_TAIL_BYTES = 64 * 1024
REMOVED_NEUTRAL_RECORD_MARKER = 11
MAX_REMOVED_NEUTRAL_OBJECT_INDEX = 100_000
MAX_REMOVED_NEUTRAL_SUBID = 512
MAX_REMOVED_NEUTRAL_REMOVAL_FLAGS = 0xFFFF
MAX_REMOVED_NEUTRAL_COORD_REMOVAL_FLAGS = 0xFFFFFFFF
REMOVED_NEUTRAL_REMOVAL_FLAG_GRANULARITY = 0x1000
REMOVED_NEUTRAL_COORD_LEVEL_SHIFT = 10
REMOVED_NEUTRAL_COORD_LEVEL_MASK = (1 << REMOVED_NEUTRAL_COORD_LEVEL_SHIFT) - 1

HERO_STRUCT_ARMY_TYPES_OFFSET = 113
HERO_STRUCT_ARMY_COUNTS_OFFSET = 141
HERO_STRUCT_NAME_OFFSET = 169
HERO_STRUCT_POSITION_FROM_NAME_OFFSET = -194
HERO_POSITION_SIZE = 5
MAX_HERO_POSITION_COORD = 255
MAX_HERO_POSITION_LEVEL = 1

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
    recent_heroes: tuple[str, ...] = ()
    hidden_neutral_targets_by_map: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class LoadedSave:
    """Decompressed save bytes with the located H3SVG signature offset."""

    path: Path
    data: bytes
    h3svg_offset: int


@dataclass(frozen=True)
class RemovedNeutralRecord:
    """Late save-log record for a neutral monster removed from the map."""

    object_index: int
    h3m_subid: int
    source_offset: int
    removal_flags: int
    source_path: Path | None = None


class RemovedNeutralHistoryCache:
    """Persistent cache for removed neutral records found in save history."""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else (
            CACHE_ROOT / "removed-neutrals"
        )
        self._lock = threading.RLock()
        self._documents: dict[Path, dict] = {}

    def load_removed_neutral_records_for_save(
        self,
        save_file: str | Path,
        neutral_targets=None,
        game_dir: str | Path | None = None,
    ) -> tuple[RemovedNeutralRecord, ...]:
        """Load removed neutral records using per-save persistent cache entries."""

        target_keys = _removed_neutral_target_keys(neutral_targets)
        if target_keys is not None and not target_keys:
            return ()

        save_path = Path(save_file)
        history_paths = _removed_neutral_history_save_paths(save_path, game_dir)
        cache_path = self._cache_path(
            game_dir if game_dir is not None else save_path.parent
        )
        target_signature = _removed_neutral_target_signature(neutral_targets)
        remaining_keys = set(target_keys) if target_keys is not None else None
        records = []
        seen_keys = set()

        with self._lock:
            document = self._load_document(cache_path)
            entries = document.setdefault("entries", {}).setdefault(target_signature, {})
            dirty = False

            for history_save_path in history_paths:
                fingerprint = _removed_neutral_file_fingerprint(history_save_path)
                entry_key = str(history_save_path)
                entry = entries.get(entry_key)
                if not _removed_neutral_cache_entry_matches(entry, fingerprint):
                    loaded_save = load_save(history_save_path)
                    detected_records = detect_removed_neutral_records(
                        loaded_save.data,
                        neutral_targets=neutral_targets,
                    )
                    entry = {
                        "fingerprint": fingerprint,
                        "records": [
                            _removed_neutral_record_to_cache(record)
                            for record in detected_records
                        ],
                    }
                    entries[entry_key] = entry
                    dirty = True

                for record in _removed_neutral_records_from_cache_entry(
                    entry,
                    history_save_path,
                ):
                    key = (record.object_index, record.h3m_subid)
                    if key in seen_keys:
                        continue
                    records.append(record)
                    seen_keys.add(key)
                    if remaining_keys is not None:
                        remaining_keys.discard(key)
                        if not remaining_keys:
                            if dirty:
                                self._write_document(cache_path, document)
                            return tuple(records)

            if dirty:
                self._write_document(cache_path, document)

        return tuple(records)

    def _cache_path(self, game_dir: str | Path) -> Path:
        folder = Path(game_dir).expanduser().resolve()
        digest = hashlib.sha256(str(folder).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _load_document(self, cache_path: Path) -> dict:
        document = self._documents.get(cache_path)
        if document is not None:
            return document

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict) or data.get("version") != 1:
            data = {"version": 1, "entries": {}}
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}

        self._documents[cache_path] = data
        return data

    def _write_document(self, cache_path: Path, document: dict) -> None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = cache_path.with_name(f".{cache_path.name}.tmp")
            temp_path.write_text(
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            temp_path.replace(cache_path)
        except OSError:
            return


@dataclass(frozen=True)
class HeroPosition:
    """Current hero adventure-map position when present in the save."""

    x: int
    y: int
    z: int


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
    position: HeroPosition | None = None

    @property
    def total_creatures(self) -> int:
        return sum(stack.count for stack in self.stacks)

    @property
    def ai_value(self) -> int:
        return sum(stack.creature.ai_value * stack.count for stack in self.stacks)

    @property
    def army_summary(self) -> str:
        return ", ".join(
            f"{stack.count}x {stack.creature.name}"
            for stack in self.stacks
        )

    @property
    def x(self) -> int | None:
        return None if self.position is None else self.position.x

    @property
    def y(self) -> int | None:
        return None if self.position is None else self.position.y

    @property
    def z(self) -> int | None:
        return None if self.position is None else self.position.z


@dataclass(frozen=True)
class HeroTarget:
    """Army-only target record for another hero in the current save."""

    hero_name: str
    position: HeroPosition
    army: HeroArmy

    @property
    def x(self) -> int:
        return self.position.x

    @property
    def y(self) -> int:
        return self.position.y

    @property
    def z(self) -> int:
        return self.position.z

    @property
    def ai_value(self) -> int:
        return self.army.ai_value

    @property
    def total_creatures(self) -> int:
        return self.army.total_creatures

    @property
    def army_summary(self) -> str:
        return self.army.army_summary


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
        recent_heroes=_read_recent_heroes(data, path),
        hidden_neutral_targets_by_map=_read_hidden_neutral_targets_by_map(
            data,
            path,
        ),
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
        recent_heroes=current.recent_heroes,
        hidden_neutral_targets_by_map=current.hidden_neutral_targets_by_map,
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
        recent_heroes=current.recent_heroes,
        hidden_neutral_targets_by_map=current.hidden_neutral_targets_by_map,
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
        recent_heroes=current.recent_heroes,
        hidden_neutral_targets_by_map=current.hidden_neutral_targets_by_map,
    )
    save_config(updated, config_path)
    return updated


def set_config_selected_hero(
    hero_name: str | None,
    config_path: str | Path = CONFIG_PATH,
    limit: int = RECENT_HERO_LIMIT,
) -> BattleEstimatorConfig:
    """Save a GUI-selected hero and update recent hero history."""

    if limit <= 0:
        raise ValueError(f"recent hero limit must be positive: {limit}")

    current = load_config(config_path)
    normalized_hero = hero_name.strip() if hero_name else ""
    recent_heroes = current.recent_heroes
    if normalized_hero:
        recent_heroes = _prepend_recent_hero(
            normalized_hero,
            recent_heroes,
            limit,
        )
    updated = BattleEstimatorConfig(
        autosave_dir=current.autosave_dir,
        last_hero=normalized_hero or None,
        recent_heroes=recent_heroes,
        hidden_neutral_targets_by_map=current.hidden_neutral_targets_by_map,
    )
    save_config(updated, config_path)
    return updated


def set_config_hidden_neutral_target(
    map_key: str,
    target_id: str,
    hidden: bool,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Persist one hidden-neutral setting while preserving other config values."""

    normalized_map_key = map_key.strip() if isinstance(map_key, str) else ""
    if not normalized_map_key:
        raise ConfigError(config_path, "invalid map_key: value must not be blank")

    normalized_target_id = _normalize_hidden_neutral_target_id(target_id)
    if normalized_target_id is None:
        raise ConfigError(
            config_path,
            "invalid target_id: expected neutral:<object_index>",
        )

    current = load_config(config_path)
    hidden_by_map = {
        key: tuple(values)
        for key, values in current.hidden_neutral_targets_by_map.items()
    }
    current_targets = list(hidden_by_map.get(normalized_map_key, ()))
    if hidden:
        if normalized_target_id not in current_targets:
            current_targets.append(normalized_target_id)
    else:
        current_targets = [
            candidate
            for candidate in current_targets
            if candidate != normalized_target_id
        ]

    normalized_targets = _normalize_hidden_neutral_target_ids(current_targets)
    if normalized_targets:
        hidden_by_map[normalized_map_key] = normalized_targets
    else:
        hidden_by_map.pop(normalized_map_key, None)

    updated = BattleEstimatorConfig(
        autosave_dir=current.autosave_dir,
        last_hero=current.last_hero,
        recent_heroes=current.recent_heroes,
        hidden_neutral_targets_by_map=hidden_by_map,
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


def load_removed_neutral_records_from_save(
    path: str | Path,
) -> tuple[RemovedNeutralRecord, ...]:
    """Load a save file and scan it for removed neutral monster records."""

    loaded_save = load_save(path)
    return detect_removed_neutral_records(loaded_save.data)


def load_removed_neutral_records_for_save(
    save_file: str | Path,
    neutral_targets=None,
    game_dir: str | Path | None = None,
) -> tuple[RemovedNeutralRecord, ...]:
    """Load removed neutral records from one save and earlier numeric saves."""

    target_keys = _removed_neutral_target_keys(neutral_targets)
    if target_keys is not None and not target_keys:
        return ()
    remaining_keys = set(target_keys) if target_keys is not None else None
    save_path = Path(save_file)
    records = []
    seen_keys = set()
    for history_save_path in _removed_neutral_history_save_paths(save_path, game_dir):
        loaded_save = load_save(history_save_path)
        for record in detect_removed_neutral_records(
            loaded_save.data,
            neutral_targets=neutral_targets,
        ):
            key = (record.object_index, record.h3m_subid)
            if key in seen_keys:
                continue
            records.append(_removed_neutral_record_with_path(record, history_save_path))
            seen_keys.add(key)
            if remaining_keys is not None:
                remaining_keys.discard(key)
                if not remaining_keys:
                    return tuple(records)

    return tuple(records)


def _removed_neutral_file_fingerprint(path: str | Path) -> dict:
    file_path = Path(path)
    stat_result = file_path.stat()
    return {
        "path": str(file_path),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _removed_neutral_cache_entry_matches(entry, fingerprint: dict) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("fingerprint") == fingerprint
        and isinstance(entry.get("records"), list)
    )


def _removed_neutral_target_signature(neutral_targets) -> str:
    if neutral_targets is None:
        return "all-targets"
    items = []
    for target in neutral_targets:
        position = _removed_neutral_target_position(target)
        items.append((
            int(target.object_index),
            int(target.h3m_subid),
            (-1, -1, -1) if position is None else tuple(position),
        ))
    raw_signature = json.dumps(
        sorted(items),
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()


def _removed_neutral_record_to_cache(record: RemovedNeutralRecord) -> dict:
    return {
        "object_index": record.object_index,
        "h3m_subid": record.h3m_subid,
        "source_offset": record.source_offset,
        "removal_flags": record.removal_flags,
    }


def _removed_neutral_records_from_cache_entry(
    entry,
    source_path: Path,
) -> tuple[RemovedNeutralRecord, ...]:
    if not isinstance(entry, dict):
        return ()
    raw_records = entry.get("records")
    if not isinstance(raw_records, list):
        return ()

    records = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        try:
            records.append(
                RemovedNeutralRecord(
                    object_index=int(raw_record["object_index"]),
                    h3m_subid=int(raw_record["h3m_subid"]),
                    source_offset=int(raw_record["source_offset"]),
                    removal_flags=int(raw_record["removal_flags"]),
                    source_path=source_path,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(records)


def find_h3svg_offset(data: bytes) -> int | None:
    """Return the offset of the H3SVG signature, if present."""

    offset = data.find(H3SVG_SIGNATURE)
    if offset == -1:
        return None
    return offset


def detect_removed_neutral_records(
    data: bytes,
    neutral_targets=None,
) -> tuple[RemovedNeutralRecord, ...]:
    """Scan the late save log for removed neutral monster records."""

    known_neutral_keys = _removed_neutral_target_keys(neutral_targets)
    known_neutral_targets = _removed_neutral_target_lookup(neutral_targets)
    record_size = (
        REMOVED_NEUTRAL_RECORD_CORE_SIZE
        if known_neutral_keys is not None
        else REMOVED_NEUTRAL_RECORD_SIZE
    )
    tail_start = max(0, len(data) - REMOVED_NEUTRAL_SCAN_TAIL_BYTES)
    minimum_record_size = min(record_size, REMOVED_NEUTRAL_COORD_RECORD_SIZE)
    last_offset = len(data) - minimum_record_size
    records = []
    seen_keys = set()

    if known_neutral_keys is None:
        candidate_offsets = range(tail_start, last_offset + 1)
    else:
        candidate_offsets = _removed_neutral_candidate_offsets(
            data,
            tail_start,
            known_neutral_keys,
            known_neutral_targets,
        )

    for offset in candidate_offsets:
        parsed_records = (
            _parse_removed_neutral_record_at(
                data,
                offset,
                known_neutral_keys=known_neutral_keys,
            ),
            _parse_removed_neutral_coord_record_at(
                data,
                offset,
                known_neutral_targets=known_neutral_targets,
            ),
        )
        for record in parsed_records:
            if record is None:
                continue
            key = (record.object_index, record.h3m_subid)
            if key in seen_keys:
                continue
            records.append(record)
            seen_keys.add(key)

    return tuple(records)


def _removed_neutral_candidate_offsets(
    data: bytes,
    tail_start: int,
    known_neutral_keys,
    known_neutral_targets,
) -> tuple[int, ...]:
    prefixes = {
        int(object_index).to_bytes(4, "little")
        for object_index, _ in known_neutral_keys
    }
    for target in known_neutral_targets.values():
        position = _removed_neutral_target_position(target)
        if position is None:
            continue
        x, y, z = position
        encoded_yz = y + (z << REMOVED_NEUTRAL_COORD_LEVEL_SHIFT)
        prefixes.add(
            int(x).to_bytes(2, "little")
            + int(encoded_yz).to_bytes(2, "little")
        )

    if not prefixes:
        return ()
    offsets = set()
    for prefix in prefixes:
        offsets.update(_find_all_offsets(data, prefix, tail_start, len(data)))
    return tuple(sorted(offsets))


def _find_all_offsets(
    data: bytes,
    needle: bytes,
    start: int,
    end: int,
) -> tuple[int, ...]:
    offsets = []
    offset = data.find(needle, start, end)
    while offset != -1:
        offsets.append(offset)
        offset = data.find(needle, offset + 1, end)
    return tuple(offsets)


def _removed_neutral_target_keys(neutral_targets):
    if neutral_targets is None:
        return None
    return {
        (int(target.object_index), int(target.h3m_subid))
        for target in neutral_targets
    }


def _removed_neutral_target_lookup(neutral_targets):
    if neutral_targets is None:
        return None
    return {
        (int(target.object_index), int(target.h3m_subid)): target
        for target in neutral_targets
    }


def _parse_removed_neutral_record_at(
    data: bytes,
    offset: int,
    known_neutral_keys=None,
) -> RemovedNeutralRecord | None:
    core_end = offset + REMOVED_NEUTRAL_RECORD_CORE_SIZE
    if offset < 0 or core_end > len(data):
        return None

    object_index = int.from_bytes(data[offset:offset + 4], "little")
    removal_flags = int.from_bytes(data[offset + 4:offset + 8], "little")
    h3m_subid = int.from_bytes(data[offset + 8:offset + 12], "little")
    marker_end = offset + REMOVED_NEUTRAL_RECORD_SIZE
    marker = None
    if marker_end <= len(data):
        marker = int.from_bytes(data[offset + 12:marker_end], "little")

    if not _looks_like_removed_neutral_record(
        object_index,
        removal_flags,
        h3m_subid,
        marker,
        known_neutral_keys=known_neutral_keys,
    ):
        return None

    return RemovedNeutralRecord(
        object_index=object_index,
        h3m_subid=h3m_subid,
        source_offset=offset,
        removal_flags=removal_flags,
    )


def _parse_removed_neutral_coord_record_at(
    data: bytes,
    offset: int,
    known_neutral_targets=None,
) -> RemovedNeutralRecord | None:
    if known_neutral_targets is None:
        return None

    record_end = offset + REMOVED_NEUTRAL_COORD_RECORD_SIZE
    if offset < 0 or record_end > len(data):
        return None

    x = int.from_bytes(data[offset:offset + 2], "little")
    encoded_yz = int.from_bytes(data[offset + 2:offset + 4], "little")
    y = encoded_yz & REMOVED_NEUTRAL_COORD_LEVEL_MASK
    z = encoded_yz >> REMOVED_NEUTRAL_COORD_LEVEL_SHIFT
    object_index = int.from_bytes(data[offset + 4:offset + 8], "little")
    removal_flags = int.from_bytes(data[offset + 8:offset + 12], "little")
    h3m_subid = int.from_bytes(data[offset + 12:offset + 16], "little")

    target = known_neutral_targets.get((object_index, h3m_subid))
    if target is None:
        return None
    target_position = _removed_neutral_target_position(target)
    if target_position is None:
        return None
    if (x, y, z) != target_position:
        return None
    if not _looks_like_coord_removed_neutral_record(
        object_index,
        removal_flags,
        h3m_subid,
        x,
        y,
        z,
    ):
        return None

    return RemovedNeutralRecord(
        object_index=object_index,
        h3m_subid=h3m_subid,
        source_offset=offset,
        removal_flags=removal_flags,
    )


def _removed_neutral_target_position(target):
    try:
        return int(target.x), int(target.y), int(target.z)
    except (AttributeError, TypeError, ValueError):
        return None


def _looks_like_removed_neutral_record(
    object_index: int,
    removal_flags: int,
    h3m_subid: int,
    marker: int | None,
    known_neutral_keys=None,
) -> bool:
    if object_index > MAX_REMOVED_NEUTRAL_OBJECT_INDEX:
        return False
    if h3m_subid > MAX_REMOVED_NEUTRAL_SUBID:
        return False
    if removal_flags <= 0 or removal_flags > MAX_REMOVED_NEUTRAL_REMOVAL_FLAGS:
        return False
    if removal_flags % REMOVED_NEUTRAL_REMOVAL_FLAG_GRANULARITY != 0:
        return False

    if known_neutral_keys is not None:
        return (object_index, h3m_subid) in known_neutral_keys

    if object_index <= 0:
        return False
    return marker == REMOVED_NEUTRAL_RECORD_MARKER


def _looks_like_coord_removed_neutral_record(
    object_index: int,
    removal_flags: int,
    h3m_subid: int,
    x: int,
    y: int,
    z: int,
) -> bool:
    if object_index <= 0 or object_index > MAX_REMOVED_NEUTRAL_OBJECT_INDEX:
        return False
    if h3m_subid > MAX_REMOVED_NEUTRAL_SUBID:
        return False
    if x > MAX_HERO_POSITION_COORD or y > MAX_HERO_POSITION_COORD:
        return False
    if z > MAX_HERO_POSITION_LEVEL:
        return False
    if removal_flags <= 0 or removal_flags > MAX_REMOVED_NEUTRAL_COORD_REMOVAL_FLAGS:
        return False
    return removal_flags % REMOVED_NEUTRAL_REMOVAL_FLAG_GRANULARITY == 0


def _removed_neutral_history_save_paths(
    save_file: Path,
    game_dir: str | Path | None,
) -> tuple[Path, ...]:
    selected_key = parse_numeric_save_name(save_file)
    if selected_key is None:
        return (save_file,)

    folder = Path(game_dir) if game_dir is not None else save_file.parent
    if not folder.is_dir():
        return (save_file,)

    try:
        children = list(folder.iterdir())
    except OSError:
        return (save_file,)

    candidates = []
    for child in children:
        if not child.is_file():
            continue
        numeric_save = parse_numeric_save_name(child)
        if numeric_save is None:
            continue
        if numeric_save <= selected_key:
            candidates.append((
                *numeric_save,
                normalize_save_name(child),
                child.name,
                child,
            ))

    if not candidates:
        return (save_file,)
    return tuple(
        item[4]
        for item in sorted(
            candidates,
            key=lambda item: (item[0], item[1], item[2], item[3]),
        )
    )


def _removed_neutral_record_with_path(
    record: RemovedNeutralRecord,
    source_path: Path,
) -> RemovedNeutralRecord:
    return RemovedNeutralRecord(
        object_index=record.object_index,
        h3m_subid=record.h3m_subid,
        source_offset=record.source_offset,
        removal_flags=record.removal_flags,
        source_path=source_path,
    )


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


def decode_hero_position(data: bytes, name_offset: int) -> HeroPosition | None:
    """Decode the optional XOR-obfuscated hero position near a hero name."""

    position_offset = name_offset + HERO_STRUCT_POSITION_FROM_NAME_OFFSET
    try:
        decoded = xor_decode_bytes(data, position_offset, HERO_POSITION_SIZE)
    except ValueError:
        return None

    x = int.from_bytes(decoded[0:2], "little")
    y = int.from_bytes(decoded[2:4], "little")
    z = decoded[4]
    if x > MAX_HERO_POSITION_COORD or y > MAX_HERO_POSITION_COORD:
        return None
    if z > MAX_HERO_POSITION_LEVEL:
        return None
    return HeroPosition(x=x, y=y, z=z)


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
    position = decode_hero_position(data, name_offset)
    return HeroArmy(
        hero_name=hero_name,
        stacks=tuple(stacks),
        source_offset=name_offset,
        position=position,
    )


def scan_xor01_hero_armies(data: bytes) -> tuple[HeroArmy, ...]:
    """Scan decompressed save bytes for XOR 0x01 encoded hero armies."""

    heroes = []
    for match in ENCODED_HERO_NAME_CANDIDATE_PATTERN.finditer(data):
        name_offset = match.start()
        if name_offset < HERO_STRUCT_NAME_OFFSET:
            continue
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


def build_other_hero_targets(
    heroes,
    selected_hero: HeroArmy,
    same_level_z: int | None = None,
) -> tuple[HeroTarget, ...]:
    """Build army-only target records for positioned heroes other than selected."""

    targets = []
    for hero in heroes:
        if _is_selected_hero(hero, selected_hero):
            continue
        if not hero.stacks:
            continue
        if hero.position is None:
            continue
        if same_level_z is not None and hero.position.z != same_level_z:
            continue
        targets.append(
            HeroTarget(
                hero_name=hero.hero_name,
                position=hero.position,
                army=hero,
            )
        )
    return tuple(targets)


def _is_selected_hero(hero: HeroArmy, selected_hero: HeroArmy) -> bool:
    if hero is selected_hero:
        return True
    if hero.source_offset is not None and selected_hero.source_offset is not None:
        return hero.source_offset == selected_hero.source_offset
    return hero == selected_hero


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
    """Return an explicit game folder or the folder with the newest save."""

    if explicit_game_dir is not None:
        game_dir = Path(explicit_game_dir)
        if not game_dir.is_dir():
            raise SaveSelectionError(game_dir, "selected game folder is not a directory")
        return game_dir

    root = Path(autosave_root)
    candidates = list_save_folders(root)
    if not candidates:
        raise SaveSelectionError(root, "no autosave game folders with saves found")
    return candidates[0].path


@dataclass(frozen=True)
class SaveFolderInfo:
    """Discovered save folder under a scan root."""

    path: Path
    relative_path: str
    save_count: int
    latest_save_file: Path
    latest_save_mtime_ns: int


def list_save_folders(root: str | Path) -> tuple[SaveFolderInfo, ...]:
    """Return save folders below root, sorted by latest save mtime descending."""

    scan_root = Path(root).expanduser()
    if not scan_root.is_dir():
        raise SaveSelectionError(scan_root, "autosave root is not a directory")

    folders = []
    try:
        candidates = [scan_root, *scan_root.rglob("*")]
    except OSError as exc:
        raise SaveSelectionError(scan_root, f"failed to scan autosave root: {exc}") from exc

    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        save_files = _supported_save_files_in_folder(candidate)
        if not save_files:
            continue
        latest_save = max(
            save_files,
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        relative_path = _relative_save_folder_path(scan_root, candidate)
        folders.append(SaveFolderInfo(
            path=candidate,
            relative_path=relative_path,
            save_count=len(save_files),
            latest_save_file=latest_save,
            latest_save_mtime_ns=latest_save.stat().st_mtime_ns,
        ))

    return tuple(sorted(
        folders,
        key=lambda item: (
            -item.latest_save_mtime_ns,
            item.relative_path.casefold(),
        ),
    ))


def _supported_save_files_in_folder(folder: Path) -> tuple[Path, ...]:
    try:
        children = list(folder.iterdir())
    except OSError:
        return ()

    save_files = []
    for child in children:
        if child.is_symlink() or not child.is_file():
            continue
        if parse_numeric_save_name(child) is not None:
            save_files.append(child)
    return tuple(save_files)


def _relative_save_folder_path(root: Path, folder: Path) -> str:
    try:
        relative = folder.relative_to(root)
    except ValueError:
        return folder.name
    if str(relative) == ".":
        return folder.name
    return str(relative)


def parse_numeric_save_name(path_or_name: str | Path) -> tuple[int, int] | None:
    """Return sortable save number and extension rank for supported GM1/GM2 names."""

    name = normalize_save_name(path_or_name)
    game_begin_match = GAME_BEGIN_SAVE_PATTERN.match(name)
    if game_begin_match:
        extension_rank = 2 if game_begin_match.group("ext").lower() == "gm2" else 1
        return GAME_BEGIN_SAVE_NUMBER, extension_rank

    match = NUMERIC_SAVE_PATTERN.match(name)
    if not match:
        return None
    extension_rank = 2 if match.group("ext").lower() == "gm2" else 1
    return int(match.group("number")), extension_rank


def normalize_save_name(path_or_name: str | Path) -> str:
    """Return the save filename without GUI-only prefixes such as hotseat."""

    return HOTSEAT_SAVE_PREFIX_PATTERN.sub("", Path(path_or_name).name)


def select_latest_save(game_dir: str | Path) -> Path:
    """Return the latest supported GM1/GM2 save in a game folder."""

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
            candidates.append((
                *numeric_save,
                normalize_save_name(child),
                child.name,
                child,
            ))

    if not candidates:
        raise SaveSelectionError(folder, "no numeric/GAME_BEGIN GM1/GM2 saves found")
    return max(candidates, key=lambda item: (item[0], item[1], item[2], item[3]))[4]


def select_numbered_save(game_dir: str | Path, save_number: str | int) -> Path:
    """Return the best GM1/GM2 save matching an explicit numeric save number."""

    folder = Path(game_dir)
    if not folder.is_dir():
        raise SaveSelectionError(folder, "game folder is not a directory")

    try:
        requested_number = int(save_number)
    except (TypeError, ValueError) as exc:
        raise SaveSelectionError(folder, f"invalid save number: {save_number!r}") from exc

    try:
        children = list(folder.iterdir())
    except OSError as exc:
        raise SaveSelectionError(folder, f"failed to list game folder: {exc}") from exc

    candidates = []
    for child in children:
        if not child.is_file():
            continue
        numeric_save = parse_numeric_save_name(child)
        if numeric_save is None:
            continue
        number, extension_rank = numeric_save
        if number == requested_number:
            candidates.append((
                extension_rank,
                normalize_save_name(child),
                child.name,
                child,
            ))

    if not candidates:
        raise SaveSelectionError(
            folder,
            f"no GM1/GM2 save found for number {requested_number}",
        )
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


def _read_recent_heroes(data: dict, path: Path) -> tuple[str, ...]:
    value = data.get("recent_heroes")
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(path, "invalid config: recent_heroes must be a list")

    recent_heroes = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(
                path,
                f"invalid config: recent_heroes[{index}] must be a string",
            )
        normalized = item.strip()
        if normalized:
            recent_heroes.append(normalized)
    return tuple(recent_heroes)


def _read_hidden_neutral_targets_by_map(data: dict, path: Path) -> dict[str, tuple[str, ...]]:
    value = data.get("hidden_neutral_targets_by_map")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            path,
            "invalid config: hidden_neutral_targets_by_map must be an object",
        )

    hidden_by_map = {}
    for raw_map_key, raw_targets in value.items():
        if not isinstance(raw_map_key, str):
            raise ConfigError(
                path,
                "invalid config: hidden_neutral_targets_by_map keys must be strings",
            )
        map_key = raw_map_key.strip()
        if not map_key:
            continue
        if not isinstance(raw_targets, list):
            raise ConfigError(
                path,
                f"invalid config: hidden_neutral_targets_by_map[{raw_map_key!r}] must be a list",
            )
        for index, item in enumerate(raw_targets):
            if not isinstance(item, str):
                raise ConfigError(
                    path,
                    "invalid config: "
                    f"hidden_neutral_targets_by_map[{raw_map_key!r}][{index}] "
                    "must be a string",
                )
        normalized_targets = _normalize_hidden_neutral_target_ids(raw_targets)
        if normalized_targets:
            hidden_by_map[map_key] = normalized_targets
    return hidden_by_map


def _normalize_hidden_neutral_target_ids(values) -> tuple[str, ...]:
    normalized = {}
    for item in values:
        if not isinstance(item, str):
            continue
        target_id = _normalize_hidden_neutral_target_id(item)
        if target_id is not None:
            normalized[target_id] = _hidden_neutral_target_sort_key(target_id)
    return tuple(
        target_id
        for target_id, _ in sorted(
            normalized.items(),
            key=lambda item: item[1],
        )
    )


def _normalize_hidden_neutral_target_id(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    match = HIDDEN_NEUTRAL_TARGET_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    return f"neutral:{int(match.group('object_index'))}"


def _hidden_neutral_target_sort_key(target_id: str) -> tuple[int, str]:
    match = HIDDEN_NEUTRAL_TARGET_PATTERN.fullmatch(target_id)
    if match is None:
        return (MAX_REMOVED_NEUTRAL_OBJECT_INDEX + 1, target_id)
    return (int(match.group("object_index")), target_id)


def _prepend_recent_hero(
    hero_name: str,
    recent_heroes,
    limit: int = RECENT_HERO_LIMIT,
) -> tuple[str, ...]:
    deduped = [hero_name]
    seen = {hero_name.casefold()}
    for recent_hero in recent_heroes:
        key = recent_hero.casefold()
        if key in seen:
            continue
        deduped.append(recent_hero)
        seen.add(key)
        if len(deduped) >= limit:
            break
    return tuple(deduped[:limit])


def _config_to_json(config: BattleEstimatorConfig) -> dict:
    data = {}
    if config.autosave_dir is not None:
        data["autosave_dir"] = str(config.autosave_dir)
    if config.last_hero is not None:
        data["last_hero"] = config.last_hero
    if config.recent_heroes:
        data["recent_heroes"] = list(config.recent_heroes)
    hidden_neutral_targets_by_map = {
        map_key: list(target_ids)
        for map_key, target_ids in sorted(
            config.hidden_neutral_targets_by_map.items()
        )
        if target_ids
    }
    if hidden_neutral_targets_by_map:
        data["hidden_neutral_targets_by_map"] = hidden_neutral_targets_by_map
    return data
