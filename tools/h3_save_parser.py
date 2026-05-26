#!/usr/bin/env python3
"""Contracts and constants for Heroes III save parsing."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import zlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from tools.battle_estimator import Creature
        from tools.hero_skill_recommender import (
            CurrentSkill,
            VcmiHeroSkillMetadata,
        )
    except ImportError:  # pragma: no cover - used only for type checking.
        from battle_estimator import Creature
        from hero_skill_recommender import CurrentSkill, VcmiHeroSkillMetadata


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
DEFAULT_ALERT_RADIUS = 10
MAX_ALERT_RADIUS = 200
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
HIDDEN_HERO_TARGET_PATTERN = re.compile(r"^hero:(?P<identity>[a-z0-9][a-z0-9:,-]{0,199})$")
HERO_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,12}$")
HERO_NAME_FIRST_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
HERO_NAME_REST_CHARS = HERO_NAME_FIRST_CHARS + b"0123456789 '-"
PLAYER_COLOR_NAMES = (
    "red",
    "blue",
    "tan",
    "green",
    "orange",
    "purple",
    "teal",
    "pink",
)

HERO_ARMY_SLOT_COUNT = 7
HERO_ARMY_VALUE_SIZE = 4
HERO_NAME_SIZE = 13
HERO_ARMY_XOR_KEY = 0x01
HERO_ARMY_XOR_KEYS = (HERO_ARMY_XOR_KEY, 0x00)
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
HERO_OWNER_UNOWNED = 0xFF
HERO_STRUCT_POSITION_FROM_NAME_OFFSET = -194
HERO_POSITION_SIZE = 5
MAX_HERO_POSITION_COORD = 255
MAX_HERO_POSITION_LEVEL = 1
HERO_COMBAT_GM1_SAVE_EXTENSION = ".GM1"
HERO_COMBAT_GM2_SAVE_EXTENSION = ".GM2"
HERO_COMBAT_GM1_H3SVG_OFFSET = 0
HERO_COMBAT_GM2_H3SVG_OFFSET = 65
HERO_COMBAT_SUPPORTED_SAVE_EXTENSION = HERO_COMBAT_GM1_SAVE_EXTENSION
HERO_COMBAT_SUPPORTED_XOR_KEY = 0x00
HERO_COMBAT_GM2_XOR_KEY = HERO_ARMY_XOR_KEY
HERO_COMBAT_SECONDARY_COUNT_MODE_EXPLICIT = "explicit"
HERO_COMBAT_SECONDARY_COUNT_MODE_DERIVED = "derived"
HERO_COMBAT_SECONDARY_COUNT_FROM_NAME_OFFSET = -126
HERO_COMBAT_SECONDARY_LEVELS_FROM_NAME_OFFSET = 13
HERO_COMBAT_SECONDARY_SLOTS_FROM_NAME_OFFSET = 41
HERO_COMBAT_SECONDARY_VECTOR_SIZE = 28
HERO_COMBAT_MAX_SECONDARY_SKILLS = 8
HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET = 69
HERO_COMBAT_PRIMARY_SIZE = 4
HERO_COMBAT_STATUS_UNAVAILABLE = "unavailable"
HERO_COMBAT_STATUS_PRIMARY_ONLY = "primary-only"
HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY = "primary+secondary"
HERO_COMBAT_STATUS_PARTIAL = "partial"
HERO_COMBAT_SOURCE_SAVE = "save"
HERO_COMBAT_REASON_UNSUPPORTED_SAVE_STRUCTURE = "unsupported_save_structure"
HERO_COMBAT_REASON_TRUNCATED_PRIMARY = "truncated_primary"
HERO_COMBAT_REASON_TRUNCATED_SECONDARY = "truncated_secondary"
HERO_COMBAT_REASON_INVALID_SECONDARY_COUNT = "invalid_secondary_count"
HERO_COMBAT_REASON_INVALID_SECONDARY_LEVEL = "invalid_secondary_level"
HERO_COMBAT_REASON_INVALID_SECONDARY_SLOT = "invalid_secondary_slot"
HERO_COMBAT_REASON_SECONDARY_LEVEL_SLOT_MISMATCH = (
    "secondary_level_slot_mismatch"
)
HERO_COMBAT_REASON_UNKNOWN_SECONDARY_SKILL = "unknown_secondary_skill"
HERO_COMBAT_SECONDARY_LEVEL_BY_ID = {
    1: "basic",
    2: "advanced",
    3: "expert",
}
HERO_COMBAT_PASSIVE_MODIFIER_DEFAULTS = {
    "offence_melee_pct": 0,
    "armorer_all_pct": 0,
    "archery_ranged_pct": 0,
}
HERO_COMBAT_PASSIVE_MODIFIERS = {
    "offence": {
        "basic": ("offence_melee_pct", 10),
        "advanced": ("offence_melee_pct", 20),
        "expert": ("offence_melee_pct", 30),
    },
    "armorer": {
        "basic": ("armorer_all_pct", 5),
        "advanced": ("armorer_all_pct", 10),
        "expert": ("armorer_all_pct", 15),
    },
    "archery": {
        "basic": ("archery_ranged_pct", 10),
        "advanced": ("archery_ranged_pct", 25),
        "expert": ("archery_ranged_pct", 50),
    },
}
H3M_TOWN_OBJECT_ID = 98
TOWN_OWNERSHIP_SOURCE_SAVE_TOWN_STATE_RECORD = "save_town_state_record"
TOWN_OWNERSHIP_SOURCE_HERO_ON_TOWN_TILE_PROXY = "hero_on_town_tile_proxy"
TOWN_OWNERSHIP_STATUS_EXACT = "exact"
TOWN_OWNERSHIP_STATUS_PROXY = "proxy"
TOWN_OWNERSHIP_STATUS_UNAVAILABLE = "ownership_unavailable"
TOWN_OWNERSHIP_REASON_NOT_STANDARD_TOWN_TARGET = "not_standard_town_target"
TOWN_OWNERSHIP_REASON_MISSING_TOWN_IDENTITY = "missing_town_identity"
TOWN_OWNERSHIP_REASON_MISSING_TOWN_POSITION = "missing_town_position"
TOWN_OWNERSHIP_REASON_AMBIGUOUS_TOWN_STATE_RECORD = (
    "ambiguous_town_state_record"
)
TOWN_OWNERSHIP_REASON_INVALID_TOWN_STATE_OWNER = "invalid_town_state_owner"
TOWN_OWNERSHIP_REASON_NO_VISIBLE_HERO = "no_visible_hero_on_town_tile"
TOWN_OWNERSHIP_REASON_AMBIGUOUS_VISIBLE_HEROES = (
    "ambiguous_visible_heroes_on_town_tile"
)
TOWN_OWNERSHIP_REASON_MISSING_HERO_OWNER_COLOR = "missing_hero_owner_color"

HERO_ARMY_TYPES_FROM_NAME_OFFSET = (
    HERO_STRUCT_ARMY_TYPES_OFFSET - HERO_STRUCT_NAME_OFFSET
)
HERO_ARMY_COUNTS_FROM_NAME_OFFSET = (
    HERO_STRUCT_ARMY_COUNTS_OFFSET - HERO_STRUCT_NAME_OFFSET
)
HOTSEAT_HERO_STRUCT_POSITION_FROM_NAME_OFFSET = (
    HERO_STRUCT_POSITION_FROM_NAME_OFFSET - 1
)
HERO_POSITION_OFFSETS_BY_XOR_KEY = {
    HERO_ARMY_XOR_KEY: (HERO_STRUCT_POSITION_FROM_NAME_OFFSET,),
    0x00: (HOTSEAT_HERO_STRUCT_POSITION_FROM_NAME_OFFSET,),
}


def _build_encoded_hero_name_candidate_pattern(key: int):
    return re.compile(
        rb"(?=([" +
        re.escape(bytes(byte ^ key for byte in HERO_NAME_FIRST_CHARS)) +
        rb"][" +
        re.escape(
            bytes(byte ^ key for byte in HERO_NAME_REST_CHARS)
            + bytes([key])
        ) +
        rb"]{12}))"
    )


ENCODED_HERO_NAME_CANDIDATE_PATTERN = _build_encoded_hero_name_candidate_pattern(
    HERO_ARMY_XOR_KEY
)
HERO_NAME_CANDIDATE_PATTERNS_BY_XOR_KEY = {
    key: _build_encoded_hero_name_candidate_pattern(key)
    for key in HERO_ARMY_XOR_KEYS
}


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
    my_color_id: int | None = None
    alert_radius: int = DEFAULT_ALERT_RADIUS
    hidden_neutral_targets_by_map: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    hidden_hero_targets_by_map: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    manual_hero_current_skills_by_map: dict[
        str,
        dict[str, tuple["CurrentSkill", ...]],
    ] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadedSave:
    """Decompressed save bytes with the located H3SVG signature offset."""

    path: Path
    data: bytes
    h3svg_offset: int


@dataclass(frozen=True)
class HeroCombatContextProfile:
    """Save-level hero combat context layout accepted by the parser."""

    source: str
    xor_key: int
    secondary_count_mode: str

    def __post_init__(self) -> None:
        if self.source != HERO_COMBAT_SOURCE_SAVE:
            raise ValueError(f"unknown hero combat context source: {self.source!r}")
        if self.secondary_count_mode not in (
            HERO_COMBAT_SECONDARY_COUNT_MODE_EXPLICIT,
            HERO_COMBAT_SECONDARY_COUNT_MODE_DERIVED,
        ):
            raise ValueError(
                "unknown hero combat secondary count mode: "
                f"{self.secondary_count_mode!r}"
            )


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
class HeroPrimarySkills:
    """Current/effective primary skills decoded from a save hero record."""

    attack: int
    defense: int
    spell_power: int
    knowledge: int


@dataclass(frozen=True)
class HeroCombatContext:
    """Save-derived hero combat fields and their parse confidence status."""

    status: str = HERO_COMBAT_STATUS_UNAVAILABLE
    source: str | None = None
    primary_skills: HeroPrimarySkills | None = None
    secondary_skills: tuple["CurrentSkill", ...] = ()
    reason: str | None = HERO_COMBAT_REASON_UNSUPPORTED_SAVE_STRUCTURE

    def __post_init__(self) -> None:
        object.__setattr__(self, "secondary_skills", tuple(self.secondary_skills))
        if self.status not in (
            HERO_COMBAT_STATUS_UNAVAILABLE,
            HERO_COMBAT_STATUS_PRIMARY_ONLY,
            HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY,
            HERO_COMBAT_STATUS_PARTIAL,
        ):
            raise ValueError(f"unknown hero combat context status: {self.status!r}")
        if self.source is not None and self.source != HERO_COMBAT_SOURCE_SAVE:
            raise ValueError(f"unknown hero combat context source: {self.source!r}")
        if self.status == HERO_COMBAT_STATUS_UNAVAILABLE:
            if self.primary_skills is not None:
                raise ValueError("unavailable combat context cannot include primary skills")
            if self.secondary_skills:
                raise ValueError("unavailable combat context cannot include secondary skills")
            if self.source is not None:
                raise ValueError("unavailable combat context cannot include a source")
            if self.reason is None:
                raise ValueError("unavailable combat context requires a reason")
        if self.status == HERO_COMBAT_STATUS_PRIMARY_ONLY:
            if self.primary_skills is None:
                raise ValueError("primary-only combat context requires primary skills")
            if self.secondary_skills:
                raise ValueError("primary-only combat context cannot include secondary skills")
            if self.source != HERO_COMBAT_SOURCE_SAVE:
                raise ValueError("primary-only combat context requires save source")
            if self.reason is None:
                raise ValueError("primary-only combat context requires a reason")
        if self.status == HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY:
            if self.primary_skills is None:
                raise ValueError(
                    "primary+secondary combat context requires primary skills"
                )
            if self.source != HERO_COMBAT_SOURCE_SAVE:
                raise ValueError("primary+secondary combat context requires save source")
            if self.reason is not None:
                raise ValueError(
                    "primary+secondary combat context must not include a reason"
                )
        if self.status == HERO_COMBAT_STATUS_PARTIAL:
            if self.primary_skills is None and not self.secondary_skills:
                raise ValueError("partial combat context requires parsed data")
            if self.source != HERO_COMBAT_SOURCE_SAVE:
                raise ValueError("partial combat context requires save source")
            if self.reason is None:
                raise ValueError("partial combat context requires a reason")


@dataclass(frozen=True)
class HeroArmy:
    """Army stacks detected for one hero in a save file."""

    hero_name: str
    stacks: tuple[HeroStack, ...]
    source_offset: int | None = None
    position: HeroPosition | None = None
    owner_color_id: int | None = None
    combat_context: HeroCombatContext = field(default_factory=HeroCombatContext)

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
    def owner_color_name(self) -> str | None:
        if self.owner_color_id is None:
            return None
        if 0 <= self.owner_color_id < len(PLAYER_COLOR_NAMES):
            return PLAYER_COLOR_NAMES[self.owner_color_id]
        return None

    @property
    def primary_skills(self) -> HeroPrimarySkills | None:
        return self.combat_context.primary_skills

    @property
    def secondary_skills(self) -> tuple["CurrentSkill", ...]:
        return self.combat_context.secondary_skills

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


@dataclass(frozen=True)
class TownOwnershipObservation:
    """Current town ownership observation derived from save hero state."""

    object_index: int | None
    h3m_subid: int | None
    position: HeroPosition | None
    current_owner_color_id: int | None = None
    ownership_status: str = TOWN_OWNERSHIP_STATUS_UNAVAILABLE
    ownership_source: str | None = None
    ownership_confidence: str = TOWN_OWNERSHIP_STATUS_UNAVAILABLE
    reason: str | None = None
    matching_hero_names: tuple[str, ...] = ()
    matching_hero_source_offsets: tuple[int | None, ...] = ()

    @property
    def current_owner_color_name(self) -> str | None:
        if self.current_owner_color_id is None:
            return None
        if 0 <= self.current_owner_color_id < len(PLAYER_COLOR_NAMES):
            return PLAYER_COLOR_NAMES[self.current_owner_color_id]
        return None

    @property
    def x(self) -> int | None:
        return None if self.position is None else self.position.x

    @property
    def y(self) -> int | None:
        return None if self.position is None else self.position.y

    @property
    def z(self) -> int | None:
        return None if self.position is None else self.position.z

    @property
    def matching_hero_count(self) -> int:
        return len(self.matching_hero_names)

    @property
    def matching_hero_name(self) -> str | None:
        if len(self.matching_hero_names) != 1:
            return None
        return self.matching_hero_names[0]

    @property
    def matching_hero_source_offset(self) -> int | None:
        if len(self.matching_hero_source_offsets) != 1:
            return None
        return self.matching_hero_source_offsets[0]


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
        my_color_id=_read_optional_player_color_id(data, "my_color_id", path),
        alert_radius=_read_alert_radius(data, path),
        hidden_neutral_targets_by_map=_read_hidden_neutral_targets_by_map(
            data,
            path,
        ),
        hidden_hero_targets_by_map=_read_hidden_hero_targets_by_map(
            data,
            path,
        ),
        manual_hero_current_skills_by_map=_read_manual_hero_current_skills_by_map(
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
    data = _config_to_json(_validated_config_for_write(config, path))
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


def _validated_config_for_write(
    config: BattleEstimatorConfig,
    path: Path,
) -> BattleEstimatorConfig:
    return replace(
        config,
        my_color_id=validate_optional_player_color_id(config.my_color_id, path),
        alert_radius=validate_alert_radius(config.alert_radius, path),
    )


def set_config_autosave_dir(
    autosave_dir: str | Path,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Save an autosave directory while preserving other config values."""

    if isinstance(autosave_dir, str) and not autosave_dir.strip():
        raise ConfigError(config_path, "invalid autosave_dir: value must not be blank")
    autosave_path = Path(autosave_dir)
    current = load_config(config_path)
    updated = replace(current, autosave_dir=autosave_path)
    save_config(updated, config_path)
    return updated


def clear_config_autosave_dir(
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Clear the saved autosave directory while preserving other values."""

    current = load_config(config_path)
    updated = replace(current, autosave_dir=None)
    save_config(updated, config_path)
    return updated


def set_config_last_hero(
    last_hero: str | None,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Save the last interactive hero name while preserving other values."""

    current = load_config(config_path)
    normalized_hero = last_hero.strip() if last_hero else ""
    updated = replace(current, last_hero=normalized_hero or None)
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
    updated = replace(
        current,
        last_hero=normalized_hero or None,
        recent_heroes=recent_heroes,
    )
    save_config(updated, config_path)
    return updated


def set_config_alert_settings(
    my_color_id,
    alert_radius,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Persist alert settings while preserving unrelated config values."""

    validated_color = validate_optional_player_color_id(my_color_id, config_path)
    validated_radius = validate_alert_radius(alert_radius, config_path)
    current = load_config(config_path)
    updated = replace(
        current,
        my_color_id=validated_color,
        alert_radius=validated_radius,
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

    updated = replace(current, hidden_neutral_targets_by_map=hidden_by_map)
    save_config(updated, config_path)
    return updated


def set_config_hidden_hero_target(
    map_key: str,
    target_id: str,
    hidden: bool,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Persist one hidden-hero setting while preserving other config values."""

    normalized_map_key = map_key.strip() if isinstance(map_key, str) else ""
    if not normalized_map_key:
        raise ConfigError(config_path, "invalid map_key: value must not be blank")

    normalized_target_id = _normalize_hidden_hero_target_id(target_id)
    if normalized_target_id is None:
        raise ConfigError(
            config_path,
            "invalid target_id: expected hero:<stable_id>",
        )

    current = load_config(config_path)
    hidden_by_map = {
        key: tuple(values)
        for key, values in current.hidden_hero_targets_by_map.items()
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

    normalized_targets = _normalize_hidden_hero_target_ids(current_targets)
    if normalized_targets:
        hidden_by_map[normalized_map_key] = normalized_targets
    else:
        hidden_by_map.pop(normalized_map_key, None)

    updated = replace(current, hidden_hero_targets_by_map=hidden_by_map)
    save_config(updated, config_path)
    return updated


def get_config_hero_skill_state(
    map_key: str,
    hero_id: str,
    standard_hero_key: str,
    config: BattleEstimatorConfig | None = None,
    config_path: str | Path = CONFIG_PATH,
    metadata: "VcmiHeroSkillMetadata | None" = None,
) -> tuple["CurrentSkill", ...]:
    """Return persisted hero skills or VCMI starting skills when unset."""

    normalized_map_key = _normalize_config_map_key(map_key, config_path)
    normalized_hero_id = _normalize_config_hero_id(hero_id, config_path)
    resolved_metadata = _hero_skill_metadata(metadata)
    hero = _standard_hero_metadata(
        standard_hero_key,
        resolved_metadata,
        config_path,
    )
    current = load_config(config_path) if config is None else config
    manual_by_hero = current.manual_hero_current_skills_by_map.get(
        normalized_map_key,
        {},
    )
    return manual_by_hero.get(normalized_hero_id, hero.starting_skills)


def set_config_hero_skill_state(
    map_key: str,
    hero_id: str,
    standard_hero_key: str,
    skills,
    config_path: str | Path = CONFIG_PATH,
    metadata: "VcmiHeroSkillMetadata | None" = None,
) -> BattleEstimatorConfig:
    """Persist one hero's manually edited current secondary-skill state.

    Empty skill state is treated as a reset because missing manual state already
    falls back to the hero's VCMI starting skills.
    """

    normalized_map_key = _normalize_config_map_key(map_key, config_path)
    normalized_hero_id = _normalize_config_hero_id(hero_id, config_path)
    resolved_metadata = _hero_skill_metadata(metadata)
    _standard_hero_metadata(standard_hero_key, resolved_metadata, config_path)
    normalized_skills = _validated_manual_hero_current_skills(
        skills,
        resolved_metadata,
        config_path,
    )
    if not normalized_skills:
        return reset_config_hero_skill_state(
            normalized_map_key,
            normalized_hero_id,
            config_path=config_path,
        )

    current = load_config(config_path)
    manual_by_map = _copy_manual_hero_current_skills_by_map(
        current.manual_hero_current_skills_by_map
    )
    manual_by_map.setdefault(normalized_map_key, {})[
        normalized_hero_id
    ] = normalized_skills

    updated = replace(current, manual_hero_current_skills_by_map=manual_by_map)
    save_config(updated, config_path)
    return updated


def reset_config_hero_skill_state(
    map_key: str,
    hero_id: str,
    config_path: str | Path = CONFIG_PATH,
) -> BattleEstimatorConfig:
    """Remove one hero's manual skill state so callers use starting skills."""

    normalized_map_key = _normalize_config_map_key(map_key, config_path)
    normalized_hero_id = _normalize_config_hero_id(hero_id, config_path)
    current = load_config(config_path)
    manual_by_map = _copy_manual_hero_current_skills_by_map(
        current.manual_hero_current_skills_by_map
    )
    manual_by_hero = manual_by_map.get(normalized_map_key)
    if manual_by_hero is not None:
        manual_by_hero.pop(normalized_hero_id, None)
        if not manual_by_hero:
            manual_by_map.pop(normalized_map_key, None)

    updated = replace(current, manual_hero_current_skills_by_map=manual_by_map)
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
    """Load a save file and scan it for detectable hero armies."""

    loaded_save = load_save(path)
    return scan_hero_armies_from_loaded_save(loaded_save)


def scan_hero_armies_from_loaded_save(loaded_save: LoadedSave) -> tuple[HeroArmy, ...]:
    """Scan a loaded save with save-level context for bounded hero combat fields."""

    combat_context_profile = _loaded_save_hero_combat_context_profile(
        loaded_save,
    )
    return scan_xor01_hero_armies(
        loaded_save.data,
        combat_context_profile=combat_context_profile,
        hero_skill_id_by_index=(
            _hero_skill_id_by_index()
            if combat_context_profile is not None
            else None
        ),
    )


def _loaded_save_supports_hero_combat_context(loaded_save: LoadedSave) -> bool:
    return _loaded_save_hero_combat_context_profile(loaded_save) is not None


def _loaded_save_hero_combat_context_profile(
    loaded_save: LoadedSave,
) -> HeroCombatContextProfile | None:
    suffix = loaded_save.path.suffix.upper()
    if (
        suffix == HERO_COMBAT_GM1_SAVE_EXTENSION
        and loaded_save.h3svg_offset == HERO_COMBAT_GM1_H3SVG_OFFSET
        and loaded_save.data.startswith(H3SVG_SIGNATURE)
    ):
        return HeroCombatContextProfile(
            source=HERO_COMBAT_SOURCE_SAVE,
            xor_key=HERO_COMBAT_SUPPORTED_XOR_KEY,
            secondary_count_mode=HERO_COMBAT_SECONDARY_COUNT_MODE_EXPLICIT,
        )
    if (
        suffix == HERO_COMBAT_GM2_SAVE_EXTENSION
        and loaded_save.h3svg_offset == HERO_COMBAT_GM2_H3SVG_OFFSET
    ):
        return HeroCombatContextProfile(
            source=HERO_COMBAT_SOURCE_SAVE,
            xor_key=HERO_COMBAT_GM2_XOR_KEY,
            secondary_count_mode=HERO_COMBAT_SECONDARY_COUNT_MODE_DERIVED,
        )
    return None


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


def detect_current_town_ownership(
    data: bytes,
    town_targets,
) -> tuple[TownOwnershipObservation, ...]:
    """Infer current town ownership from save bytes and parsed H3M towns."""

    towns = tuple(town_targets or ())
    if not towns:
        return ()

    h3svg_offset = find_h3svg_offset(data)
    if h3svg_offset is None:
        direct_observations = (None,) * len(towns)
    else:
        direct_observations = tuple(
            _detect_current_town_state_ownership_for_target(
                data,
                target,
                sequence_index,
                len(towns),
                scan_start=h3svg_offset + len(H3SVG_SIGNATURE),
            )
            for sequence_index, target in enumerate(towns)
        )
    if all(observation is not None for observation in direct_observations):
        return direct_observations

    proxy_observations = infer_current_town_ownership(
        towns,
        scan_xor01_hero_armies(data),
    )
    return tuple(
        proxy if direct is None else direct
        for direct, proxy in zip(direct_observations, proxy_observations)
    )


def _detect_current_town_state_ownership_for_target(
    data: bytes,
    target,
    sequence_index: int,
    town_count: int,
    scan_start: int = 5,
) -> TownOwnershipObservation | None:
    object_index = _town_target_int_attr(target, "object_index")
    h3m_subid = _town_target_int_attr(target, "h3m_subid")
    position = _town_target_position(target)

    if _town_target_int_attr(target, "object_id") != H3M_TOWN_OBJECT_ID:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_NOT_STANDARD_TOWN_TARGET,
        )
    if (
        object_index is None
        or h3m_subid is None
        or not _town_target_has_anchor_identity(target)
    ):
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_MISSING_TOWN_IDENTITY,
        )
    if position is None:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            None,
            TOWN_OWNERSHIP_REASON_MISSING_TOWN_POSITION,
        )

    matches = _find_current_town_state_record_matches(
        data,
        sequence_index,
        town_count,
        h3m_subid,
        position,
        scan_start,
    )
    if not matches:
        return None
    if len(matches) != 1:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_AMBIGUOUS_TOWN_STATE_RECORD,
        )

    owner_color_id = matches[0]
    if owner_color_id == HERO_OWNER_UNOWNED:
        owner_color_id = None
    elif owner_color_id < 0 or owner_color_id >= len(PLAYER_COLOR_NAMES):
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_INVALID_TOWN_STATE_OWNER,
        )

    return TownOwnershipObservation(
        object_index=object_index,
        h3m_subid=h3m_subid,
        position=position,
        current_owner_color_id=owner_color_id,
        ownership_status=TOWN_OWNERSHIP_STATUS_EXACT,
        ownership_source=TOWN_OWNERSHIP_SOURCE_SAVE_TOWN_STATE_RECORD,
        ownership_confidence=TOWN_OWNERSHIP_STATUS_EXACT,
        reason=None,
    )


def _find_current_town_state_record_matches(
    data: bytes,
    sequence_index: int,
    town_count: int,
    h3m_subid: int,
    position: HeroPosition,
    scan_start: int = 5,
) -> tuple[int, ...]:
    if sequence_index < 0 or sequence_index > 0xFF or h3m_subid > 0xFF:
        return ()
    if (
        position.x < 0
        or position.x > 0xFF
        or position.y < 0
        or position.y > 0xFF
        or position.z < 0
        or position.z > 0xFF
    ):
        return ()

    position_bytes = bytes((position.x & 0xFF, position.y & 0xFF, position.z & 0xFF))
    matches = []
    town_count_prefix = town_count if 0 <= town_count <= 0xFF else None
    start = max(6, scan_start)
    while True:
        offset = data.find(position_bytes, start)
        if offset == -1:
            break
        if offset + len(position_bytes) + 2 > len(data):
            break
        previous_byte = data[offset - 6]
        if (
            (previous_byte == HERO_OWNER_UNOWNED or previous_byte == town_count_prefix)
            and data[offset - 5] == sequence_index
            and data[offset - 1] == h3m_subid
            and data[offset + 3:offset + 5] == b"\xFF\xFF"
        ):
            matches.append(data[offset - 4])
        start = offset + 1
    return tuple(matches)


def infer_current_town_ownership(
    town_targets,
    heroes,
) -> tuple[TownOwnershipObservation, ...]:
    """Infer proxy current town ownership from parsed towns and visible heroes.

    This helper does not validate that town targets came from the matching map.
    Callers must only pass trusted H3M targets for the save being analyzed.
    """

    if town_targets is None:
        return ()
    hero_list = tuple(heroes or ())
    return tuple(
        _infer_current_town_ownership_for_target(target, hero_list)
        for target in town_targets
    )


def _infer_current_town_ownership_for_target(
    target,
    heroes,
) -> TownOwnershipObservation:
    object_index = _town_target_int_attr(target, "object_index")
    h3m_subid = _town_target_int_attr(target, "h3m_subid")
    position = _town_target_position(target)

    if _town_target_int_attr(target, "object_id") != H3M_TOWN_OBJECT_ID:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_NOT_STANDARD_TOWN_TARGET,
        )
    if (
        object_index is None
        or h3m_subid is None
        or not _town_target_has_anchor_identity(target)
    ):
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_MISSING_TOWN_IDENTITY,
        )
    if position is None:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            None,
            TOWN_OWNERSHIP_REASON_MISSING_TOWN_POSITION,
        )

    matching_heroes = tuple(
        hero for hero in heroes
        if hero.position is not None
        and (hero.x, hero.y, hero.z) == (position.x, position.y, position.z)
    )
    if not matching_heroes:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_NO_VISIBLE_HERO,
        )
    if len(matching_heroes) != 1:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_AMBIGUOUS_VISIBLE_HEROES,
            matching_heroes=matching_heroes,
        )

    hero = matching_heroes[0]
    if hero.owner_color_id is None:
        return _unavailable_town_ownership_observation(
            object_index,
            h3m_subid,
            position,
            TOWN_OWNERSHIP_REASON_MISSING_HERO_OWNER_COLOR,
            matching_heroes=matching_heroes,
        )

    return TownOwnershipObservation(
        object_index=object_index,
        h3m_subid=h3m_subid,
        position=position,
        current_owner_color_id=hero.owner_color_id,
        ownership_status=TOWN_OWNERSHIP_STATUS_PROXY,
        ownership_source=TOWN_OWNERSHIP_SOURCE_HERO_ON_TOWN_TILE_PROXY,
        ownership_confidence=TOWN_OWNERSHIP_STATUS_PROXY,
        reason=None,
        matching_hero_names=(hero.hero_name,),
        matching_hero_source_offsets=(hero.source_offset,),
    )


def _unavailable_town_ownership_observation(
    object_index: int | None,
    h3m_subid: int | None,
    position: HeroPosition | None,
    reason: str,
    matching_heroes=(),
) -> TownOwnershipObservation:
    return TownOwnershipObservation(
        object_index=object_index,
        h3m_subid=h3m_subid,
        position=position,
        ownership_status=TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
        ownership_source=None,
        ownership_confidence=TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
        reason=reason,
        matching_hero_names=tuple(hero.hero_name for hero in matching_heroes),
        matching_hero_source_offsets=tuple(
            hero.source_offset for hero in matching_heroes
        ),
    )


def _town_target_int_attr(target, name: str) -> int | None:
    value = getattr(target, name, None)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _town_target_position(target) -> HeroPosition | None:
    x = _town_target_int_attr(target, "x")
    y = _town_target_int_attr(target, "y")
    z = _town_target_int_attr(target, "z")
    if x is None or y is None or z is None:
        return None
    return HeroPosition(x, y, z)


def _town_target_has_anchor_identity(target) -> bool:
    return (
        _town_target_int_attr(target, "anchor_x") is not None
        and _town_target_int_attr(target, "anchor_y") is not None
        and _town_target_int_attr(target, "anchor_z") is not None
    )


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


def decode_xor_u32(
    data: bytes,
    offset: int,
    key: int = HERO_ARMY_XOR_KEY,
) -> int:
    """Decode one XOR-obfuscated little-endian unsigned 32-bit integer."""

    return int.from_bytes(
        xor_decode_bytes(data, offset, HERO_ARMY_VALUE_SIZE, key),
        "little",
    )


def decode_hero_name(
    data: bytes,
    name_offset: int,
    key: int = HERO_ARMY_XOR_KEY,
) -> str | None:
    """Decode and validate a null-padded XOR-obfuscated hero name."""

    try:
        decoded = xor_decode_bytes(data, name_offset, HERO_NAME_SIZE, key)
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


def decode_hero_position(
    data: bytes,
    name_offset: int,
    key: int = HERO_ARMY_XOR_KEY,
) -> HeroPosition | None:
    """Decode the optional XOR-obfuscated hero position near a hero name."""

    position_offsets = HERO_POSITION_OFFSETS_BY_XOR_KEY.get(
        key,
        (HERO_STRUCT_POSITION_FROM_NAME_OFFSET,),
    )
    for position_from_name_offset in position_offsets:
        position_offset = name_offset + position_from_name_offset
        try:
            decoded = xor_decode_bytes(
                data,
                position_offset,
                HERO_POSITION_SIZE,
                key,
            )
        except ValueError:
            continue

        x = int.from_bytes(decoded[0:2], "little")
        y = int.from_bytes(decoded[2:4], "little")
        z = decoded[4]
        if x > MAX_HERO_POSITION_COORD or y > MAX_HERO_POSITION_COORD:
            continue
        if z > MAX_HERO_POSITION_LEVEL:
            continue
        if key == 0x00 and x == 0 and y == 0 and z == 0:
            continue
        return HeroPosition(x=x, y=y, z=z)
    return None


def decode_hero_owner_color(
    data: bytes,
    name_offset: int,
    key: int = HERO_ARMY_XOR_KEY,
) -> int | None:
    """Decode the optional owner color at the start of the hero record."""

    owner_offset = name_offset - HERO_STRUCT_NAME_OFFSET
    try:
        decoded = xor_decode_bytes(data, owner_offset, 1, key)[0]
    except ValueError:
        return None
    if 0 <= decoded < len(PLAYER_COLOR_NAMES):
        return decoded
    if decoded == HERO_OWNER_UNOWNED:
        return None
    return None


def decode_hero_primary_skills(
    data: bytes,
    name_offset: int,
    key: int = HERO_COMBAT_SUPPORTED_XOR_KEY,
) -> HeroPrimarySkills:
    """Decode four current/effective primary skills from a hero record."""

    decoded = xor_decode_bytes(
        data,
        name_offset + HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET,
        HERO_COMBAT_PRIMARY_SIZE,
        key,
    )
    return HeroPrimarySkills(
        attack=decoded[0],
        defense=decoded[1],
        spell_power=decoded[2],
        knowledge=decoded[3],
    )


class HeroSecondarySkillDecodeError(ValueError):
    """Raised when secondary-skill vectors are present but invalid."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def decode_hero_secondary_skills(
    data: bytes,
    name_offset: int,
    key: int = HERO_COMBAT_SUPPORTED_XOR_KEY,
    skill_id_by_index: dict[int, str] | None = None,
    count_mode: str = HERO_COMBAT_SECONDARY_COUNT_MODE_EXPLICIT,
) -> tuple["CurrentSkill", ...]:
    """Decode validated current secondary skills from a hero record."""

    try:
        levels = xor_decode_bytes(
            data,
            name_offset + HERO_COMBAT_SECONDARY_LEVELS_FROM_NAME_OFFSET,
            HERO_COMBAT_SECONDARY_VECTOR_SIZE,
            key,
        )
        slots = xor_decode_bytes(
            data,
            name_offset + HERO_COMBAT_SECONDARY_SLOTS_FROM_NAME_OFFSET,
            HERO_COMBAT_SECONDARY_VECTOR_SIZE,
            key,
        )
    except ValueError as exc:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_TRUNCATED_SECONDARY
        ) from exc

    if count_mode == HERO_COMBAT_SECONDARY_COUNT_MODE_EXPLICIT:
        try:
            count = xor_decode_bytes(
                data,
                name_offset + HERO_COMBAT_SECONDARY_COUNT_FROM_NAME_OFFSET,
                1,
                key,
            )[0]
        except ValueError as exc:
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_TRUNCATED_SECONDARY
            ) from exc
    elif count_mode == HERO_COMBAT_SECONDARY_COUNT_MODE_DERIVED:
        count = _derived_hero_secondary_skill_count(levels, slots)
    else:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_UNSUPPORTED_SAVE_STRUCTURE
        )

    skill_id_by_index = (
        _hero_skill_id_by_index()
        if skill_id_by_index is None
        else skill_id_by_index
    )
    return _validated_hero_secondary_skills(
        count,
        levels,
        slots,
        skill_id_by_index,
    )


def _derived_hero_secondary_skill_count(levels: bytes, slots: bytes) -> int:
    return sum(
        1
        for level_id, slot in zip(levels, slots)
        if level_id != 0 or slot != 0
    )


def _validated_hero_secondary_skills(
    count: int,
    levels: bytes,
    slots: bytes,
    skill_id_by_index: dict[int, str],
) -> tuple["CurrentSkill", ...]:
    if count > HERO_COMBAT_MAX_SECONDARY_SKILLS:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_INVALID_SECONDARY_COUNT
        )
    if len(levels) != HERO_COMBAT_SECONDARY_VECTOR_SIZE:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_TRUNCATED_SECONDARY
        )
    if len(slots) != HERO_COMBAT_SECONDARY_VECTOR_SIZE:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_TRUNCATED_SECONDARY
        )

    active = []
    for skill_index, (level_id, slot) in enumerate(zip(levels, slots)):
        if level_id == 0 and slot == 0:
            continue
        if level_id == 0 or slot == 0:
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_SECONDARY_LEVEL_SLOT_MISMATCH
            )
        level = HERO_COMBAT_SECONDARY_LEVEL_BY_ID.get(level_id)
        if level is None:
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_INVALID_SECONDARY_LEVEL
            )
        if slot > count:
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_INVALID_SECONDARY_SLOT
            )
        skill_id = skill_id_by_index.get(skill_index)
        if skill_id is None:
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_UNKNOWN_SECONDARY_SKILL
            )
        active.append((slot, skill_id, level))

    if len(active) != count:
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_INVALID_SECONDARY_COUNT
        )
    sorted_slots = sorted(slot for slot, _, _ in active)
    if sorted_slots != list(range(1, count + 1)):
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_INVALID_SECONDARY_SLOT
        )

    recommender = _hero_skill_recommender_module()
    metadata = _hero_skill_metadata()
    if any(skill_id not in metadata.skills for _, skill_id, _ in active):
        raise HeroSecondarySkillDecodeError(
            HERO_COMBAT_REASON_UNKNOWN_SECONDARY_SKILL
        )
    try:
        return recommender.validate_current_skills(
            recommender.CurrentSkill(skill_id, level)
            for slot, skill_id, level in sorted(active)
        )
    except Exception as exc:
        error_type = getattr(recommender, "HeroSkillRecommendationError", ValueError)
        if isinstance(exc, error_type):
            raise HeroSecondarySkillDecodeError(
                HERO_COMBAT_REASON_UNKNOWN_SECONDARY_SKILL
            ) from exc
        raise


def _hero_skill_id_by_index() -> dict[int, str]:
    metadata = _hero_skill_metadata()
    by_index = {}
    duplicates = set()
    for skill_id, skill in metadata.skills.items():
        index = skill.index
        if not isinstance(index, int):
            continue
        if index in by_index:
            duplicates.add(index)
            continue
        by_index[index] = skill_id
    if duplicates:
        return {
            index: skill_id
            for index, skill_id in by_index.items()
            if index not in duplicates
        }
    return by_index


def hero_combat_passive_modifiers(
    context: HeroCombatContext,
) -> dict[str, int]:
    """Return save-derived passive combat modifier percentages."""

    modifiers = dict(HERO_COMBAT_PASSIVE_MODIFIER_DEFAULTS)
    if context.source != HERO_COMBAT_SOURCE_SAVE:
        return modifiers
    if context.status not in (
        HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY,
        HERO_COMBAT_STATUS_PARTIAL,
    ):
        return modifiers

    for skill in context.secondary_skills:
        modifier = HERO_COMBAT_PASSIVE_MODIFIERS.get(skill.skill_id, {}).get(
            skill.level
        )
        if modifier is None:
            continue
        key, value = modifier
        modifiers[key] = value
    return modifiers


def _hero_combat_context_for_record(
    data: bytes,
    name_offset: int,
    key: int,
    combat_context_profile: HeroCombatContextProfile | None,
    hero_skill_id_by_index: dict[int, str] | None,
) -> HeroCombatContext:
    if (
        combat_context_profile is None
        or combat_context_profile.source != HERO_COMBAT_SOURCE_SAVE
        or key != combat_context_profile.xor_key
    ):
        return HeroCombatContext()

    try:
        primary_skills = decode_hero_primary_skills(data, name_offset, key)
    except ValueError:
        return HeroCombatContext(
            reason=HERO_COMBAT_REASON_TRUNCATED_PRIMARY,
        )
    try:
        secondary_skills = decode_hero_secondary_skills(
            data,
            name_offset,
            key,
            hero_skill_id_by_index,
            combat_context_profile.secondary_count_mode,
        )
    except HeroSecondarySkillDecodeError as exc:
        return HeroCombatContext(
            status=HERO_COMBAT_STATUS_PRIMARY_ONLY,
            source=combat_context_profile.source,
            primary_skills=primary_skills,
            reason=exc.reason,
        )
    return HeroCombatContext(
        status=HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY,
        source=combat_context_profile.source,
        primary_skills=primary_skills,
        secondary_skills=secondary_skills,
        reason=None,
    )


def parse_hero_at(
    data: bytes,
    name_offset: int,
    key: int = HERO_ARMY_XOR_KEY,
    *,
    combat_context_profile: HeroCombatContextProfile | None = None,
    hero_skill_id_by_index: dict[int, str] | None = None,
) -> HeroArmy | None:
    """Parse one hero-army candidate by hero-name offset and XOR key."""

    if name_offset < HERO_STRUCT_NAME_OFFSET:
        return None

    hero_name = decode_hero_name(data, name_offset, key)
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
                key,
            )
            count = decode_xor_u32(
                data,
                counts_offset + slot * HERO_ARMY_VALUE_SIZE,
                key,
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
    position = decode_hero_position(data, name_offset, key)
    owner_color_id = decode_hero_owner_color(data, name_offset, key)
    return HeroArmy(
        hero_name=hero_name,
        stacks=tuple(stacks),
        source_offset=name_offset,
        position=position,
        owner_color_id=owner_color_id,
        combat_context=_hero_combat_context_for_record(
            data,
            name_offset,
            key,
            combat_context_profile,
            hero_skill_id_by_index,
        ),
    )


def parse_xor01_hero_at(
    data: bytes,
    name_offset: int,
    *,
    combat_context_profile: HeroCombatContextProfile | None = None,
    hero_skill_id_by_index: dict[int, str] | None = None,
) -> HeroArmy | None:
    """Parse one XOR 0x01 hero-army candidate by hero-name offset."""

    return parse_hero_at(
        data,
        name_offset,
        HERO_ARMY_XOR_KEY,
        combat_context_profile=combat_context_profile,
        hero_skill_id_by_index=hero_skill_id_by_index,
    )


def scan_xor01_hero_armies(
    data: bytes,
    *,
    combat_context_profile: HeroCombatContextProfile | None = None,
    hero_skill_id_by_index: dict[int, str] | None = None,
) -> tuple[HeroArmy, ...]:
    """Scan decompressed save bytes for encoded and hotseat hero armies."""

    heroes = []
    for key in HERO_ARMY_XOR_KEYS:
        pattern = HERO_NAME_CANDIDATE_PATTERNS_BY_XOR_KEY[key]
        for match in pattern.finditer(data):
            name_offset = match.start()
            if name_offset < HERO_STRUCT_NAME_OFFSET:
                continue
            hero_army = parse_hero_at(
                data,
                name_offset,
                key,
                combat_context_profile=combat_context_profile,
                hero_skill_id_by_index=hero_skill_id_by_index,
            )
            if hero_army is not None:
                heroes.append(hero_army)
    return tuple(sorted(heroes, key=lambda hero: hero.source_offset or 0))


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
    team_by_color: dict[int, int] | None = None,
    include_allied: bool = False,
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
        if (
            team_by_color is not None
            and selected_hero.owner_color_id is not None
            and hero.owner_color_id is None
        ):
            continue
        if (
            not include_allied
            and _is_same_owner_or_team(selected_hero, hero, team_by_color)
        ):
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


def _is_same_owner_or_team(
    selected_hero: HeroArmy,
    candidate: HeroArmy,
    team_by_color: dict[int, int] | None,
) -> bool:
    selected_color = selected_hero.owner_color_id
    candidate_color = candidate.owner_color_id
    if selected_color is None or candidate_color is None:
        return False
    if selected_color == candidate_color:
        return True
    if team_by_color is None:
        return False
    selected_team = team_by_color.get(selected_color)
    candidate_team = team_by_color.get(candidate_color)
    return selected_team is not None and selected_team == candidate_team


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


def _read_optional_player_color_id(
    data: dict,
    key: str,
    path: Path,
) -> int | None:
    return validate_optional_player_color_id(data.get(key), path)


def _read_alert_radius(data: dict, path: Path) -> int:
    return validate_alert_radius(data.get("alert_radius", DEFAULT_ALERT_RADIUS), path)


def validate_optional_player_color_id(value, path: str | Path = CONFIG_PATH) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(path, "invalid config: my_color_id must be an integer or null")
    if value < 0 or value >= len(PLAYER_COLOR_NAMES):
        raise ConfigError(
            path,
            f"invalid config: my_color_id must be between 0 and {len(PLAYER_COLOR_NAMES) - 1}",
        )
    return value


def validate_alert_radius(value, path: str | Path = CONFIG_PATH) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(path, "invalid config: alert_radius must be an integer")
    if value < 0 or value > MAX_ALERT_RADIUS:
        raise ConfigError(
            path,
            f"invalid config: alert_radius must be between 0 and {MAX_ALERT_RADIUS}",
        )
    return value


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


def _read_hidden_hero_targets_by_map(data: dict, path: Path) -> dict[str, tuple[str, ...]]:
    value = data.get("hidden_hero_targets_by_map")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            path,
            "invalid config: hidden_hero_targets_by_map must be an object",
        )

    hidden_by_map = {}
    for raw_map_key, raw_targets in value.items():
        if not isinstance(raw_map_key, str):
            raise ConfigError(
                path,
                "invalid config: hidden_hero_targets_by_map keys must be strings",
            )
        map_key = raw_map_key.strip()
        if not map_key:
            continue
        if not isinstance(raw_targets, list):
            raise ConfigError(
                path,
                f"invalid config: hidden_hero_targets_by_map[{raw_map_key!r}] must be a list",
            )
        for index, item in enumerate(raw_targets):
            if not isinstance(item, str):
                raise ConfigError(
                    path,
                    "invalid config: "
                    f"hidden_hero_targets_by_map[{raw_map_key!r}][{index}] "
                    "must be a string",
                )
        normalized_targets = _normalize_hidden_hero_target_ids(raw_targets)
        if normalized_targets:
            hidden_by_map[map_key] = normalized_targets
    return hidden_by_map


def _read_manual_hero_current_skills_by_map(
    data: dict,
    path: Path,
) -> dict[str, dict[str, tuple["CurrentSkill", ...]]]:
    value = data.get("manual_hero_current_skills_by_map")
    if value is None or not isinstance(value, dict):
        return {}

    metadata = _hero_skill_metadata()
    skills_by_map = {}
    for raw_map_key, raw_heroes in value.items():
        if not isinstance(raw_map_key, str) or not isinstance(raw_heroes, dict):
            continue
        map_key = raw_map_key.strip()
        if not map_key:
            continue

        skills_by_hero = {}
        for raw_hero_id, raw_skills in raw_heroes.items():
            hero_id = _normalize_config_hero_id_or_none(raw_hero_id)
            if hero_id is None:
                continue
            normalized_skills = _manual_hero_current_skills_or_none(
                raw_skills,
                metadata,
                path,
            )
            if normalized_skills:
                skills_by_hero[hero_id] = normalized_skills
        if skills_by_hero:
            skills_by_map[map_key] = skills_by_hero
    return skills_by_map


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


def _normalize_hidden_hero_target_ids(values) -> tuple[str, ...]:
    normalized = {}
    for item in values:
        if not isinstance(item, str):
            continue
        target_id = _normalize_hidden_hero_target_id(item)
        if target_id is not None:
            normalized[target_id] = _hidden_hero_target_sort_key(target_id)
    return tuple(
        target_id
        for target_id, _ in sorted(
            normalized.items(),
            key=lambda item: item[1],
        )
    )


def _normalize_hidden_hero_target_id(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    match = HIDDEN_HERO_TARGET_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    source_match = re.fullmatch(
        r"hero:(?P<source_offset>\d+)(?::(?P<duplicate>\d+))?",
        normalized,
    )
    if source_match is not None:
        duplicate = source_match.group("duplicate")
        suffix = "" if duplicate is None else f":{int(duplicate)}"
        return f"hero:{int(source_match.group('source_offset'))}{suffix}"
    return normalized


def _hidden_neutral_target_sort_key(target_id: str) -> tuple[int, str]:
    match = HIDDEN_NEUTRAL_TARGET_PATTERN.fullmatch(target_id)
    if match is None:
        return (MAX_REMOVED_NEUTRAL_OBJECT_INDEX + 1, target_id)
    return (int(match.group("object_index")), target_id)


def _hidden_hero_target_sort_key(target_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"hero:(?P<source_offset>\d+)(?::(?P<duplicate>\d+))?", target_id)
    if match is None:
        return (MAX_REMOVED_NEUTRAL_OBJECT_INDEX + 1, target_id)
    duplicate = match.group("duplicate")
    return (
        int(match.group("source_offset")),
        "" if duplicate is None else f"{int(duplicate):010d}",
    )


def _normalize_config_map_key(map_key: str, config_path: str | Path) -> str:
    normalized = map_key.strip() if isinstance(map_key, str) else ""
    if not normalized:
        raise ConfigError(config_path, "invalid map_key: value must not be blank")
    return normalized


def _normalize_config_hero_id(hero_id: str, config_path: str | Path) -> str:
    normalized = _normalize_config_hero_id_or_none(hero_id)
    if normalized is None:
        raise ConfigError(config_path, "invalid hero_id: expected hero:<stable_id>")
    return normalized


def _normalize_config_hero_id_or_none(hero_id) -> str | None:
    if not isinstance(hero_id, str):
        return None
    return _normalize_hidden_hero_target_id(hero_id)


def _validated_manual_hero_current_skills(
    skills,
    metadata: "VcmiHeroSkillMetadata",
    config_path: str | Path,
) -> tuple["CurrentSkill", ...]:
    recommender = _hero_skill_recommender_module()
    try:
        normalized_skills = recommender.validate_current_skills(skills)
    except (TypeError, recommender.HeroSkillRecommendationError) as exc:
        raise ConfigError(config_path, f"invalid skill state: {exc}") from exc

    for skill in normalized_skills:
        if skill.skill_id not in metadata.skills:
            raise ConfigError(
                config_path,
                f"invalid skill state: unknown skill {skill.skill_id!r}",
            )
    return normalized_skills


def _manual_hero_current_skills_or_none(
    skills,
    metadata: "VcmiHeroSkillMetadata",
    config_path: str | Path,
) -> tuple["CurrentSkill", ...] | None:
    if not isinstance(skills, list):
        return None
    try:
        return _validated_manual_hero_current_skills(
            skills,
            metadata,
            config_path,
        )
    except ConfigError:
        return None


def _copy_manual_hero_current_skills_by_map(
    value: dict[str, dict[str, tuple["CurrentSkill", ...]]],
) -> dict[str, dict[str, tuple["CurrentSkill", ...]]]:
    return {
        map_key: {
            hero_id: tuple(skills)
            for hero_id, skills in skills_by_hero.items()
        }
        for map_key, skills_by_hero in value.items()
    }


def _standard_hero_metadata(
    standard_hero_key: str,
    metadata: "VcmiHeroSkillMetadata",
    config_path: str | Path,
):
    hero_key = standard_hero_key.strip() if isinstance(standard_hero_key, str) else ""
    if not hero_key:
        raise ConfigError(
            config_path,
            "invalid standard_hero_key: value must not be blank",
        )

    hero = metadata.heroes.get(hero_key)
    if hero is not None:
        return hero

    casefolded = hero_key.casefold()
    matches = [
        candidate
        for key, candidate in metadata.heroes.items()
        if key.casefold() == casefolded
    ]
    if len(matches) == 1:
        return matches[0]

    raise ConfigError(
        config_path,
        f"invalid standard_hero_key: unknown hero {hero_key!r}",
    )


def _hero_skill_metadata(
    metadata: "VcmiHeroSkillMetadata | None" = None,
) -> "VcmiHeroSkillMetadata":
    if metadata is not None:
        return metadata
    return _hero_skill_recommender_module().load_vcmi_hero_skill_metadata()


def _hero_skill_recommender_module():
    try:
        return import_module("tools.hero_skill_recommender")
    except ModuleNotFoundError as exc:
        if exc.name != "tools":
            raise
        return import_module("hero_skill_recommender")


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
    if config.my_color_id is not None:
        data["my_color_id"] = config.my_color_id
    if config.alert_radius != DEFAULT_ALERT_RADIUS:
        data["alert_radius"] = config.alert_radius
    hidden_neutral_targets_by_map = {
        map_key: list(target_ids)
        for map_key, target_ids in sorted(
            config.hidden_neutral_targets_by_map.items()
        )
        if target_ids
    }
    if hidden_neutral_targets_by_map:
        data["hidden_neutral_targets_by_map"] = hidden_neutral_targets_by_map
    hidden_hero_targets_by_map = {
        map_key: list(target_ids)
        for map_key, target_ids in sorted(
            config.hidden_hero_targets_by_map.items()
        )
        if target_ids
    }
    if hidden_hero_targets_by_map:
        data["hidden_hero_targets_by_map"] = hidden_hero_targets_by_map
    manual_hero_current_skills_by_map = _manual_hero_current_skills_to_json(
        config.manual_hero_current_skills_by_map
    )
    if manual_hero_current_skills_by_map:
        data["manual_hero_current_skills_by_map"] = (
            manual_hero_current_skills_by_map
        )
    return data


def _manual_hero_current_skills_to_json(
    value: dict[str, dict[str, tuple["CurrentSkill", ...]]],
) -> dict:
    data = {}
    for raw_map_key, raw_skills_by_hero in sorted(value.items()):
        if not isinstance(raw_map_key, str) or not isinstance(raw_skills_by_hero, dict):
            continue
        map_key = raw_map_key.strip()
        if not map_key:
            continue

        skills_by_hero = {}
        for raw_hero_id, skills in sorted(raw_skills_by_hero.items()):
            hero_id = _normalize_config_hero_id_or_none(raw_hero_id)
            if hero_id is None or not skills:
                continue
            skills_by_hero[hero_id] = [
                _manual_hero_current_skill_to_json(skill)
                for skill in skills
            ]
        if skills_by_hero:
            data[map_key] = skills_by_hero
    return data


def _manual_hero_current_skill_to_json(skill) -> dict:
    return {
        "skill": skill.skill_id,
        "level": skill.level,
    }
