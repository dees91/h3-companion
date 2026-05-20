#!/usr/bin/env python3
"""Contracts and minimal loader for Heroes III H3M map files."""

from __future__ import annotations

import gzip
import re
import zlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path


H3M_START_OFFSET_CANDIDATES = (0, 43)
H3M_HEADER_MIN_SIZE = 10
H3M_FORMAT_ROE = 0x0E
H3M_FORMAT_AB = 0x15
H3M_FORMAT_SOD = 0x1C
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
MAX_RANDOM_MAP_TIME_DELTA = timedelta(hours=2)
RANDOM_MAP_DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})\.(?P<month>\d{2})\.(?P<day>\d{2})"
    r"\s+"
    r"(?P<hour>\d{2})[;:](?P<minute>\d{2})"
    r"(?:\s+(?P<template>.+?))?$"
)
H3M_OBJECT_MONSTER = 54
H3M_OBJECT_RANDOM_MONSTER = 71
H3M_OBJECT_RANDOM_MONSTER_L1 = 72
H3M_OBJECT_RANDOM_MONSTER_L2 = 73
H3M_OBJECT_RANDOM_MONSTER_L3 = 74
H3M_OBJECT_RANDOM_MONSTER_L4 = 75
H3M_OBJECT_ARTIFACT = 5
H3M_OBJECT_RANDOM_ARTIFACT = 65
H3M_OBJECT_RANDOM_TREASURE_ARTIFACT = 66
H3M_OBJECT_RANDOM_MINOR_ARTIFACT = 67
H3M_OBJECT_RANDOM_MAJOR_ARTIFACT = 68
H3M_OBJECT_RANDOM_RELIC_ARTIFACT = 69
H3M_OBJECT_RESOURCE = 76
H3M_OBJECT_RANDOM_RESOURCE = 79
H3M_OBJECT_SPELL_SCROLL = 93
H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE = 43
H3M_OBJECT_MONOLITH_ONE_WAY_EXIT = 44
H3M_OBJECT_MONOLITH_TWO_WAY = 45
H3M_OBJECT_SUBTERRANEAN_GATE = 103

H3M_TERRAIN_WATER = 8
H3M_TERRAIN_ROCK = 9
ROUTE_LAND = "land"
ROUTE_WATER = "water"
ROUTE_BLOCKED = "blocked"

H3M_MONSTER_OBJECT_IDS = frozenset((
    H3M_OBJECT_MONSTER,
    H3M_OBJECT_RANDOM_MONSTER,
    H3M_OBJECT_RANDOM_MONSTER_L1,
    H3M_OBJECT_RANDOM_MONSTER_L2,
    H3M_OBJECT_RANDOM_MONSTER_L3,
    H3M_OBJECT_RANDOM_MONSTER_L4,
))

H3M_ROUTE_TRANSPARENT_OBJECT_IDS = H3M_MONSTER_OBJECT_IDS | frozenset((
    H3M_OBJECT_ARTIFACT,
    H3M_OBJECT_RANDOM_ARTIFACT,
    H3M_OBJECT_RANDOM_TREASURE_ARTIFACT,
    H3M_OBJECT_RANDOM_MINOR_ARTIFACT,
    H3M_OBJECT_RANDOM_MAJOR_ARTIFACT,
    H3M_OBJECT_RANDOM_RELIC_ARTIFACT,
    H3M_OBJECT_RESOURCE,
    H3M_OBJECT_RANDOM_RESOURCE,
    H3M_OBJECT_SPELL_SCROLL,
    H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
    H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
    H3M_OBJECT_MONOLITH_TWO_WAY,
    H3M_OBJECT_SUBTERRANEAN_GATE,
))

SUPPORTED_H3M_FORMATS = {
    H3M_FORMAT_ROE: "RoE",
    H3M_FORMAT_AB: "AB",
    H3M_FORMAT_SOD: "SoD",
}

H3M_DEF_TO_ESTIMATOR_CREATURE_NAME = {
    # Castle
    "avwpike.def": "Pikeman",
    "avwpikx0.def": "Halberdier",
    "avwlcrs.def": "Archer",
    "avwhcrs.def": "Marksman",
    "avwgrif.def": "Griffin",
    "avwgrix0.def": "Royal Griffin",
    "avwswrd0.def": "Swordsman",
    "avwswrx0.def": "Crusader",
    "avwmonk.def": "Monk",
    "avwmonx0.def": "Zealot",
    "avwcvlr0.def": "Cavalier",
    "avwcvlx0.def": "Champion",
    "avwangl.def": "Angel",
    "avwarch.def": "Archangel",
    # Rampart
    "avwcent0.def": "Centaur",
    "avwcenx0.def": "Centaur Captain",
    "avwdwrf0.def": "Dwarf",
    "avwdwrx0.def": "Battle Dwarf",
    "avwelfw0.def": "Wood Elf",
    "avwelfx0.def": "Grand Elf",
    "avwpega0.def": "Pegasus",
    "avwpegx0.def": "Silver Pegasus",
    "avwtree0.def": "Dendroid Guard",
    "avwtrex0.def": "Dendroid Soldier",
    "avwunic0.def": "Unicorn",
    "avwunix0.def": "War Unicorn",
    "avwdrag0.def": "Green Dragon",
    "avwdrax0.def": "Gold Dragon",
    # Tower
    "avwgrem0.def": "Gremlin",
    "avwgrex0.def": "Master Gremlin",
    "avwgarg0.def": "Stone Gargoyle",
    "avwgarx0.def": "Obsidian Gargoyle",
    "avwgolm0.def": "Stone Golem",
    "avwgolx0.def": "Iron Golem",
    "avwmage0.def": "Mage",
    "avwmagx0.def": "Arch Mage",
    "avwgeni0.def": "Genie",
    "avwgenx0.def": "Master Genie",
    "avwnaga0.def": "Naga",
    "avwnagx0.def": "Naga Queen",
    "avwtitn0.def": "Giant",
    "avwtitx0.def": "Titan",
    # Inferno
    "avwimp0.def": "Imp",
    "avwimpx0.def": "Familiar",
    "avwgog0.def": "Gog",
    "avwgogx0.def": "Magog",
    "avwhoun0.def": "Hell Hound",
    "avwhoux0.def": "Cerberus",
    "avwdemn0.def": "Demon",
    "avwdemx0.def": "Horned Demon",
    "avwpitf0.def": "Pit Fiend",
    "avwpitx0.def": "Pit Lord",
    "avwefre0.def": "Efreet",
    "avwefrx0.def": "Efreet Sultan",
    "avwdevl0.def": "Devil",
    "avwdevx0.def": "Arch Devil",
    # Necropolis
    "avwskel0.def": "Skeleton",
    "avwskex0.def": "Skeleton Warrior",
    "avwzomb0.def": "Walking Dead",
    "avwzomx0.def": "Zombie",
    "avwwigh.def": "Wight",
    "avwwigx0.def": "Wraith",
    "avwvamp0.def": "Vampire",
    "avwvamx0.def": "Vampire Lord",
    "avwlich0.def": "Lich",
    "avwlicx0.def": "Power Lich",
    "avwbkni0.def": "Black Knight",
    "avwbknx0.def": "Dread Knight",
    "avwbone0.def": "Bone Dragon",
    "avwbonx0.def": "Ghost Dragon",
    # Dungeon
    "avwtrog0.def": "Troglodyte",
    "avwinfr.def": "Infernal Troglodyte",
    "avwharp0.def": "Harpy",
    "avwharx0.def": "Harpy Hag",
    "avwbehl0.def": "Beholder",
    "avwbehx0.def": "Evil Eye",
    "avwmeds.def": "Medusa",
    "avwmedx0.def": "Medusa Queen",
    "avwmino.def": "Minotaur",
    "avwminx0.def": "Minotaur King",
    "avwmant0.def": "Manticore",
    "avwmanx0.def": "Scorpicore",
    "avwrdrg.def": "Red Dragon",
    "avwddrx0.def": "Black Dragon",
    # Stronghold
    "avwgobl0.def": "Goblin",
    "avwgobx0.def": "Hobgoblin",
    "avwwolf0.def": "Wolf Rider",
    "avwwolx0.def": "Wolf Raider",
    "avworc0.def": "Orc",
    "avworcx0.def": "Orc Chieftain",
    "avwogre0.def": "Ogre",
    "avwogrx0.def": "Ogre Mage",
    "avwroc0.def": "Roc",
    "avwrocx0.def": "Thunderbird",
    "avwcycl0.def": "Cyclops",
    "avwcycx0.def": "Cyclops King",
    "avwbhmt0.def": "Behemoth",
    "avwbhmx0.def": "Ancient Behemoth",
    # Fortress
    "avwgnll0.def": "Gnoll",
    "avwgnlx0.def": "Gnoll Marauder",
    "avwlizr.def": "Lizardman",
    "avwlizx0.def": "Lizard Warrior",
    "avwdfly.def": "Serpent Fly",
    "avwdfir.def": "Dragon Fly",
    "avwsfly.def": "Serpent Fly",
    "avwbasl.def": "Basilisk",
    "avwgbas.def": "Greater Basilisk",
    "avwgorg.def": "Gorgon",
    "avwgorx0.def": "Mighty Gorgon",
    "avwwyvr.def": "Wyvern",
    "avwwyvx0.def": "Wyvern Monarch",
    "avwhydr.def": "Hydra",
    "avwhydx0.def": "Chaos Hydra",
    # Conflux
    "avwpixie.def": "Pixie",
    "avwsprit.def": "Sprite",
    "avwelma0.def": "Air Elemental",
    "avwelme0.def": "Earth Elemental",
    "avwelmf0.def": "Fire Elemental",
    "avwelmw0.def": "Water Elemental",
    "avwstorm.def": "Storm Elemental",
    "avwicee.def": "Ice Elemental",
    "avwstone.def": "Magma Elemental",
    "avwnrg.def": "Energy Elemental",
    "avwglmg0.def": "Gold Golem",
    "avwglmd0.def": "Diamond Golem",
    "avwpsye.def": "Psychic Elemental",
    "avwmagel.def": "Magic Elemental",
    "avwfbird.def": "Firebird",
    "avwphx.def": "Phoenix",
    # Neutral
    "avwpeas.def": "Peasant",
    "avwhalf.def": "Halfling",
    "avwboar.def": "Boar",
    "avwrog.def": "Rogue",
    "avwmumy.def": "Mummy",
    "avwnomd.def": "Nomad",
    "avwtrll.def": "Troll",
    "avwsharp.def": "Sharpshooter",
    "avwench.def": "Enchanter",
    "avwfdrg.def": "Faerie Dragon",
    "avwrust.def": "Rust Dragon",
    "avwcdrg.def": "Crystal Dragon",
    "avwazure.def": "Azure Dragon",
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
class H3TerrainTile:
    """One H3M terrain tile in map coordinates."""

    x: int
    y: int
    z: int
    terrain_type: int
    terrain_view: int
    river_type: int
    river_direction: int
    road_type: int
    road_direction: int
    ext_flags: int


@dataclass(frozen=True)
class H3RouteTile:
    """One simplified static route-classification tile."""

    x: int
    y: int
    z: int
    state: str


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
class H3MapPlayer:
    """One H3M player slot in Heroes III color order."""

    player_index: int
    color_name: str
    can_human_play: bool
    can_computer_play: bool
    team_id: int | None = None
    main_town_position: tuple[int, int, int] | None = None
    random_hero: bool | None = None

    @property
    def enabled(self) -> bool:
        return self.can_human_play or self.can_computer_play


@dataclass(frozen=True)
class H3MapTeam:
    """Resolved active color slots that belong to one H3M team."""

    team_id: int
    player_indices: tuple[int, ...]
    color_names: tuple[str, ...]


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
    removed: bool = False
    removal_note: str | None = None


@dataclass(frozen=True)
class LoadedH3Map:
    """Decompressed H3M map bytes and parsed smoke-level metadata."""

    path: Path
    data: bytes
    h3m_offset: int
    header: H3MapHeader
    players: tuple[H3MapPlayer, ...] = field(default_factory=tuple)
    teams: tuple[H3MapTeam, ...] = field(default_factory=tuple)
    terrain_tiles: tuple[H3TerrainTile, ...] = field(default_factory=tuple)
    route_tiles: tuple[H3RouteTile, ...] = field(default_factory=tuple)
    templates: tuple[H3ObjectTemplate, ...] = field(default_factory=tuple)
    objects: tuple[H3MapObject, ...] = field(default_factory=tuple)
    neutral_targets: tuple[H3NeutralMonsterTarget, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _H3MFeatures:
    level_ab: bool
    level_sod: bool
    factions_bytes: int
    heroes_bytes: int
    artifacts_bytes: int
    spells_bytes: int
    skills_bytes: int
    resources_bytes: int
    resources_count: int
    heroes_count: int
    artifact_slots_count: int
    buildings_bytes: int


@dataclass(frozen=True)
class _ParsedH3MStructures:
    header: H3MapHeader
    players: tuple[H3MapPlayer, ...]
    teams: tuple[H3MapTeam, ...]
    terrain_tiles: tuple[H3TerrainTile, ...]
    route_tiles: tuple[H3RouteTile, ...]
    templates: tuple[H3ObjectTemplate, ...]
    objects: tuple[H3MapObject, ...]
    neutral_targets: tuple[H3NeutralMonsterTarget, ...]


class H3MapLoadError(ValueError):
    """Raised when a Heroes III map cannot be loaded or identified."""

    def __init__(self, path: str | Path, reason: str):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


class H3MapSelectionError(ValueError):
    """Raised when a matching H3M map path cannot be selected."""

    def __init__(self, path: str | Path, reason: str):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path}: {reason}")


_H3M_FEATURES = {
    H3M_FORMAT_ROE: _H3MFeatures(
        level_ab=False,
        level_sod=False,
        factions_bytes=1,
        heroes_bytes=16,
        artifacts_bytes=16,
        spells_bytes=9,
        skills_bytes=4,
        resources_bytes=4,
        resources_count=7,
        heroes_count=128,
        artifact_slots_count=18,
        buildings_bytes=6,
    ),
    H3M_FORMAT_AB: _H3MFeatures(
        level_ab=True,
        level_sod=False,
        factions_bytes=2,
        heroes_bytes=20,
        artifacts_bytes=17,
        spells_bytes=9,
        skills_bytes=4,
        resources_bytes=4,
        resources_count=7,
        heroes_count=156,
        artifact_slots_count=18,
        buildings_bytes=6,
    ),
    H3M_FORMAT_SOD: _H3MFeatures(
        level_ab=True,
        level_sod=True,
        factions_bytes=2,
        heroes_bytes=20,
        artifacts_bytes=18,
        spells_bytes=9,
        skills_bytes=4,
        resources_bytes=4,
        resources_count=7,
        heroes_count=156,
        artifact_slots_count=19,
        buildings_bytes=6,
    ),
}


def load_h3m(path: str | Path, parse_objects: bool = False) -> LoadedH3Map:
    """Read, decompress, and parse smoke-level metadata from an H3M map."""

    map_path = Path(path)
    try:
        compressed = map_path.read_bytes()
    except OSError as exc:
        raise H3MapLoadError(map_path, f"read failed: {exc}") from exc

    return load_h3m_bytes(compressed, map_path, parse_objects=parse_objects)


def load_h3m_bytes(
    compressed: bytes,
    path: str | Path,
    parse_objects: bool = False,
) -> LoadedH3Map:
    """Load a gzip-compressed H3M byte stream from an already-read buffer."""

    map_path = Path(path)
    data = _decompress_h3m_bytes(compressed, map_path)
    h3m_offset = find_h3m_start_offset(data)
    if h3m_offset is None:
        raise H3MapLoadError(
            map_path,
            "missing valid supported H3M header at offset 0 or 43",
        )

    if parse_objects:
        parsed = _parse_h3m_structures(
            data,
            h3m_offset,
            map_path,
        )
        return LoadedH3Map(
            path=map_path,
            data=data,
            h3m_offset=h3m_offset,
            header=parsed.header,
            players=parsed.players,
            teams=parsed.teams,
            terrain_tiles=parsed.terrain_tiles,
            route_tiles=parsed.route_tiles,
            templates=parsed.templates,
            objects=parsed.objects,
            neutral_targets=parsed.neutral_targets,
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


def resolve_h3m_map(
    game_dir: str | Path,
    explicit_map_file: str | Path | None = None,
) -> Path:
    """Resolve an H3M map path for an autosave game folder."""

    if explicit_map_file is not None:
        return _validate_explicit_map_file(explicit_map_file)

    game_path = Path(game_dir).expanduser()
    if not game_path.is_dir():
        raise H3MapSelectionError(
            game_path,
            "game folder is not a directory; use --map-file to select a map",
        )

    random_maps_dir = _random_maps_dir_for_game_dir(game_path)
    if not random_maps_dir.is_dir():
        raise H3MapSelectionError(
            random_maps_dir,
            "random_maps folder not found; use --map-file to select a map",
        )

    game_stamp = parse_random_map_stamp(game_path.name)
    if game_stamp is None:
        raise H3MapSelectionError(
            game_path,
            "game folder name has no map timestamp/template; use --map-file",
        )
    game_datetime, game_template = game_stamp
    if not game_template:
        raise H3MapSelectionError(
            game_path,
            "game folder name has no map template; use --map-file",
        )

    candidates = []
    try:
        children = list(random_maps_dir.iterdir())
    except OSError as exc:
        raise H3MapSelectionError(
            random_maps_dir,
            f"failed to list random_maps folder: {exc}; use --map-file",
        ) from exc

    normalized_game_template = _normalize_map_template(game_template)
    for child in children:
        if not child.is_file() or child.suffix.casefold() != ".h3m":
            continue
        candidate_stamp = parse_random_map_stamp(child.stem)
        if candidate_stamp is None:
            continue
        candidate_datetime, candidate_template = candidate_stamp
        if _normalize_map_template(candidate_template) != normalized_game_template:
            continue
        delta = abs(candidate_datetime - game_datetime)
        if delta > MAX_RANDOM_MAP_TIME_DELTA:
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            mtime = 0
        candidates.append((delta, -mtime, child.name.casefold(), child))

    if not candidates:
        raise H3MapSelectionError(
            random_maps_dir,
            f"no matching .h3m map for '{game_path.name}'; use --map-file",
        )

    return min(candidates, key=lambda item: item[:3])[3]


def parse_random_map_stamp(name: str) -> tuple[datetime, str] | None:
    """Return the embedded random-map timestamp and template suffix."""

    match = None
    for candidate in RANDOM_MAP_DATE_PATTERN.finditer(name):
        match = candidate
    if match is None:
        return None
    try:
        stamp = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
        )
    except ValueError:
        return None
    return stamp, (match.group("template") or "").strip()


def load_h3m_neutral_monsters(path: str | Path) -> tuple[H3NeutralMonsterTarget, ...]:
    """Load neutral monster targets from an H3M map file."""

    return load_h3m(path, parse_objects=True).neutral_targets


def filter_removed_neutral_targets(
    targets,
    removed_records,
    include_removed: bool = False,
) -> tuple[H3NeutralMonsterTarget, ...]:
    """Filter H3M neutral targets using removed records from the current save."""

    removed_by_key = {}
    for record in removed_records:
        key = (record.object_index, record.h3m_subid)
        removed_by_key.setdefault(key, record)

    filtered = []
    for target in targets:
        record = removed_by_key.get((target.object_index, target.h3m_subid))
        if record is None:
            filtered.append(target)
            continue
        if include_removed:
            filtered.append(
                replace(
                    target,
                    removed=True,
                    removal_note=_removed_neutral_note(record),
                )
            )

    return tuple(filtered)


def parse_h3m_neutral_monsters(
    data: bytes,
    offset: int = 0,
    path: str | Path = "<memory>",
) -> tuple[H3NeutralMonsterTarget, ...]:
    """Parse neutral monster targets from decompressed H3M bytes."""

    return _parse_h3m_structures(data, offset, Path(path)).neutral_targets


def _removed_neutral_note(record) -> str:
    source_offset = getattr(record, "source_offset", None)
    if source_offset is None:
        return "removed-save-record"
    source_path = getattr(record, "source_path", None)
    if source_path is not None:
        return f"removed-save-record@{Path(source_path).name}:{source_offset}"
    return f"removed-save-record@{source_offset}"


def _decompress_h3m_bytes(compressed: bytes, path: Path) -> bytes:
    try:
        return gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as exc:
        raise H3MapLoadError(path, f"gzip decompress failed: {exc}") from exc


def _validate_explicit_map_file(path: str | Path) -> Path:
    map_path = Path(path).expanduser()
    if not map_path.is_file():
        raise H3MapSelectionError(map_path, "map file is not a file")
    if map_path.suffix.casefold() != ".h3m":
        raise H3MapSelectionError(map_path, "map file must have .h3m extension")
    return map_path


def _random_maps_dir_for_game_dir(game_dir: Path) -> Path:
    parts = game_dir.parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].casefold() == "games":
            homm_root = Path(*parts[:index])
            return homm_root / "random_maps"
    return game_dir.parent / "random_maps"


def _normalize_map_template(template: str) -> str:
    return " ".join(template.casefold().split())


class _H3MReader:
    def __init__(self, data: bytes, path: Path, offset: int = 0):
        self.data = data
        self.path = path
        self.pos = offset

    def tell(self) -> int:
        return self.pos

    def read(self, size: int, context: str) -> bytes:
        if size < 0:
            raise H3MapLoadError(self.path, f"invalid read size {size}: {context}")
        end = self.pos + size
        if end > len(self.data):
            raise H3MapLoadError(
                self.path,
                f"unexpected EOF at offset {self.pos} while reading {context}",
            )
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def skip(self, size: int, context: str) -> None:
        self.read(size, context)

    def read_u8(self, context: str) -> int:
        return self.read(1, context)[0]

    def read_i8(self, context: str) -> int:
        return int.from_bytes(self.read(1, context), "little", signed=True)

    def read_u16(self, context: str) -> int:
        return int.from_bytes(self.read(2, context), "little")

    def read_u32(self, context: str) -> int:
        return int.from_bytes(self.read(4, context), "little")

    def read_i32(self, context: str) -> int:
        return int.from_bytes(self.read(4, context), "little", signed=True)

    def read_base_string(self, context: str) -> str:
        length = self.read_u32(f"{context} length")
        if length > 500_000:
            raise H3MapLoadError(
                self.path,
                f"string too long at offset {self.pos - 4} while reading {context}: {length}",
            )
        raw = self.read(length, context)
        return raw.decode("latin-1")


def _parse_h3m_structures(
    data: bytes,
    offset: int,
    path: Path,
) -> _ParsedH3MStructures:
    reader = _H3MReader(data, path, offset)
    header, features = _read_full_header(reader)
    players = _read_player_info(reader, features)
    _skip_victory_loss_conditions(reader, features)
    players, teams = _read_team_info(reader, players)
    _skip_allowed_heroes(reader, features)
    _skip_disposed_heroes(reader, features)
    _skip_map_options(reader)
    _skip_allowed_artifacts(reader, features)
    _skip_allowed_spells_abilities(reader, features)
    _skip_rumors(reader)
    _skip_predefined_heroes(reader, features)
    terrain_tiles = _read_terrain(reader, header)
    templates = _read_object_templates(reader)
    objects, targets = _read_objects(reader, templates, features)
    route_tiles = _build_route_tiles(header, terrain_tiles, templates, objects)
    return _ParsedH3MStructures(
        header=header,
        players=players,
        teams=teams,
        terrain_tiles=terrain_tiles,
        route_tiles=route_tiles,
        templates=templates,
        objects=objects,
        neutral_targets=targets,
    )


def _read_full_header(reader: _H3MReader) -> tuple[H3MapHeader, _H3MFeatures]:
    start_offset = reader.tell()
    format_version = reader.read_u32("H3M format id")
    features = _H3M_FEATURES.get(format_version)
    format_name = SUPPORTED_H3M_FORMATS.get(format_version)
    if features is None or format_name is None:
        raise H3MapLoadError(
            reader.path,
            f"unsupported H3M format id at offset {start_offset}: {format_version}",
        )

    are_any_players = bool(reader.read_u8("areAnyPlayers"))
    map_size = reader.read_i32("map size")
    has_two_levels = bool(reader.read_u8("map levels flag"))
    if map_size <= 0:
        raise H3MapLoadError(reader.path, f"invalid H3M map size: {map_size}")

    reader.read_base_string("map name")
    reader.read_base_string("map description")
    reader.read_i8("difficulty")
    if features.level_ab:
        reader.read_i8("level limit")

    return (
        H3MapHeader(
            format_version=format_version,
            format_name=format_name,
            map_size=map_size,
            levels=2 if has_two_levels else 1,
            are_any_players=are_any_players,
        ),
        features,
    )


def _read_player_info(
    reader: _H3MReader,
    features: _H3MFeatures,
) -> tuple[H3MapPlayer, ...]:
    players = []
    for player_index in range(8):
        can_human_play = bool(reader.read_u8(f"player {player_index} human flag"))
        can_computer_play = bool(reader.read_u8(f"player {player_index} computer flag"))

        if not (can_human_play or can_computer_play):
            skip_size = 6
            if features.level_ab:
                skip_size += 6
            if features.level_sod:
                skip_size += 1
            reader.skip(skip_size, f"disabled player {player_index} data")
            players.append(
                H3MapPlayer(
                    player_index=player_index,
                    color_name=PLAYER_COLOR_NAMES[player_index],
                    can_human_play=False,
                    can_computer_play=False,
                )
            )
            continue

        reader.read_i8(f"player {player_index} AI tactic")
        if features.level_sod:
            reader.skip(1, f"player {player_index} selectable faction flag")
        reader.skip(features.factions_bytes, f"player {player_index} factions bitmask")
        reader.read_u8(f"player {player_index} random faction flag")

        main_town_position = None
        has_main_town = bool(reader.read_u8(f"player {player_index} main town flag"))
        if has_main_town:
            if features.level_ab:
                reader.read_u8(f"player {player_index} generate hero at main town")
                reader.skip(1, f"player {player_index} unused starting town type")
            raw_position = reader.read(3, f"player {player_index} main town position")
            main_town_position = (
                raw_position[0],
                raw_position[1],
                raw_position[2],
            )

        random_hero = bool(reader.read_u8(f"player {player_index} random hero flag"))
        main_hero_id = _read_hero_id(reader, f"player {player_index} main hero")
        if main_hero_id != 0xFF:
            _read_hero_id(reader, f"player {player_index} main hero portrait")
            reader.read_base_string(f"player {player_index} main hero name")

        if features.level_ab:
            reader.skip(1, f"player {player_index} unused AB byte")
            hero_count = reader.read_u32(f"player {player_index} custom hero names count")
            for hero_index in range(hero_count):
                _read_hero_id(
                    reader,
                    f"player {player_index} custom hero {hero_index} id",
                )
                reader.read_base_string(
                    f"player {player_index} custom hero {hero_index} name",
                )

        players.append(
            H3MapPlayer(
                player_index=player_index,
                color_name=PLAYER_COLOR_NAMES[player_index],
                can_human_play=can_human_play,
                can_computer_play=can_computer_play,
                main_town_position=main_town_position,
                random_hero=random_hero,
            )
        )

    return tuple(players)


def _skip_victory_loss_conditions(
    reader: _H3MReader,
    features: _H3MFeatures,
) -> None:
    victory = reader.read_i8("victory condition")
    if victory != -1:
        reader.read_u8("victory allow normal flag")
        reader.read_u8("victory applies to AI flag")
        if victory == 0:
            _read_artifact_id(reader, features, "victory artifact")
        elif victory == 1:
            _read_creature_id(reader, features, "victory creature")
            reader.skip(4, "victory creature count")
        elif victory == 2:
            reader.skip(1, "victory resource id")
            reader.skip(4, "victory resource amount")
        elif victory == 3:
            reader.skip(3, "victory town position")
            reader.skip(2, "victory town building levels")
        elif victory in (4, 5, 6, 7):
            reader.skip(3, "victory target position")
        elif victory in (8, 9):
            pass
        elif victory == 10:
            reader.skip(1, "victory transport artifact")
            reader.skip(3, "victory transport position")
        else:
            raise H3MapLoadError(
                reader.path,
                f"unsupported victory condition {victory} at offset {reader.tell()}",
            )

    loss = reader.read_i8("loss condition")
    if loss == -1:
        return
    if loss in (0, 1):
        reader.skip(3, "loss target position")
    elif loss == 2:
        reader.skip(2, "loss days")
    else:
        raise H3MapLoadError(
            reader.path,
            f"unsupported loss condition {loss} at offset {reader.tell()}",
        )


def _read_team_info(
    reader: _H3MReader,
    players: tuple[H3MapPlayer, ...],
) -> tuple[tuple[H3MapPlayer, ...], tuple[H3MapTeam, ...]]:
    team_count = reader.read_u8("team count")
    team_ids_by_player = {}
    if team_count > 0:
        assignments = tuple(
            reader.read_u8(f"player {player_index} team assignment")
            for player_index in range(8)
        )
        team_ids_by_player = {
            player.player_index: assignments[player.player_index]
            for player in players
            if player.enabled
        }
    else:
        next_team_id = 0
        for player in players:
            if not player.enabled:
                continue
            team_ids_by_player[player.player_index] = next_team_id
            next_team_id += 1

    players_with_teams = tuple(
        replace(
            player,
            team_id=team_ids_by_player.get(player.player_index),
        )
        for player in players
    )
    teams_by_id = {}
    for player in players_with_teams:
        if player.team_id is None:
            continue
        teams_by_id.setdefault(player.team_id, []).append(player)

    teams = tuple(
        H3MapTeam(
            team_id=team_id,
            player_indices=tuple(player.player_index for player in team_players),
            color_names=tuple(player.color_name for player in team_players),
        )
        for team_id, team_players in sorted(teams_by_id.items())
    )
    return players_with_teams, teams


def _skip_allowed_heroes(reader: _H3MReader, features: _H3MFeatures) -> None:
    reader.skip(features.heroes_bytes, "allowed heroes bitmask")
    if features.level_ab:
        placeholders = reader.read_u32("placeholder heroes count")
        reader.skip(placeholders, "placeholder hero ids")


def _skip_disposed_heroes(reader: _H3MReader, features: _H3MFeatures) -> None:
    if not features.level_sod:
        return
    count = reader.read_u8("disposed heroes count")
    for index in range(count):
        _read_hero_id(reader, f"disposed hero {index} id")
        _read_hero_id(reader, f"disposed hero {index} portrait")
        reader.read_base_string(f"disposed hero {index} name")
        reader.skip(1, f"disposed hero {index} players bitmask")


def _skip_map_options(reader: _H3MReader) -> None:
    reader.skip(31, "map options")


def _skip_allowed_artifacts(reader: _H3MReader, features: _H3MFeatures) -> None:
    if features.level_ab:
        reader.skip(features.artifacts_bytes, "allowed artifacts bitmask")


def _skip_allowed_spells_abilities(
    reader: _H3MReader,
    features: _H3MFeatures,
) -> None:
    if features.level_sod:
        reader.skip(features.spells_bytes, "allowed spells bitmask")
        reader.skip(features.skills_bytes, "allowed skills bitmask")


def _skip_rumors(reader: _H3MReader) -> None:
    count = reader.read_u32("rumors count")
    for index in range(count):
        reader.read_base_string(f"rumor {index} name")
        reader.read_base_string(f"rumor {index} text")


def _skip_predefined_heroes(reader: _H3MReader, features: _H3MFeatures) -> None:
    if not features.level_sod:
        return

    for hero_id in range(features.heroes_count):
        custom = bool(reader.read_u8(f"predefined hero {hero_id} custom flag"))
        if not custom:
            continue

        if reader.read_u8(f"predefined hero {hero_id} experience flag"):
            reader.skip(4, f"predefined hero {hero_id} experience")

        if reader.read_u8(f"predefined hero {hero_id} secondary skills flag"):
            skill_count = reader.read_u32(f"predefined hero {hero_id} skill count")
            reader.skip(skill_count * 2, f"predefined hero {hero_id} skills")

        _skip_artifacts_of_hero(reader, features, f"predefined hero {hero_id}")

        if reader.read_u8(f"predefined hero {hero_id} biography flag"):
            reader.read_base_string(f"predefined hero {hero_id} biography")

        reader.skip(1, f"predefined hero {hero_id} gender")

        if reader.read_u8(f"predefined hero {hero_id} spells flag"):
            reader.skip(features.spells_bytes, f"predefined hero {hero_id} spells")

        if reader.read_u8(f"predefined hero {hero_id} primary skills flag"):
            reader.skip(4, f"predefined hero {hero_id} primary skills")


def _read_terrain(reader: _H3MReader, header: H3MapHeader) -> tuple[H3TerrainTile, ...]:
    tiles = []
    for z in range(header.levels):
        for y in range(header.map_size):
            for x in range(header.map_size):
                raw = reader.read(7, f"terrain tile {x},{y},{z}")
                tiles.append(
                    H3TerrainTile(
                        x=x,
                        y=y,
                        z=z,
                        terrain_type=raw[0],
                        terrain_view=raw[1],
                        river_type=raw[2],
                        river_direction=raw[3],
                        road_type=raw[4],
                        road_direction=raw[5],
                        ext_flags=raw[6],
                    )
                )
    return tuple(tiles)


def _build_route_tiles(
    header: H3MapHeader,
    terrain_tiles: tuple[H3TerrainTile, ...],
    templates: tuple[H3ObjectTemplate, ...],
    objects: tuple[H3MapObject, ...],
) -> tuple[H3RouteTile, ...]:
    states = {
        (tile.x, tile.y, tile.z): _terrain_route_state(tile)
        for tile in terrain_tiles
    }
    for map_object in objects:
        template = templates[map_object.template_index]
        if template.object_id in H3M_ROUTE_TRANSPARENT_OBJECT_IDS:
            continue
        for x, y, z in _project_blocked_mask_tiles(map_object, template):
            if 0 <= x < header.map_size and 0 <= y < header.map_size and 0 <= z < header.levels:
                states[(x, y, z)] = ROUTE_BLOCKED

    route_tiles = []
    for z in range(header.levels):
        for y in range(header.map_size):
            for x in range(header.map_size):
                route_tiles.append(
                    H3RouteTile(
                        x=x,
                        y=y,
                        z=z,
                        state=states[(x, y, z)],
                    )
                )
    return tuple(route_tiles)


def _terrain_route_state(tile: H3TerrainTile) -> str:
    if tile.terrain_type == H3M_TERRAIN_ROCK:
        return ROUTE_BLOCKED
    if tile.terrain_type == H3M_TERRAIN_WATER:
        return ROUTE_WATER
    return ROUTE_LAND


def _project_blocked_mask_tiles(
    map_object: H3MapObject,
    template: H3ObjectTemplate,
) -> tuple[tuple[int, int, int], ...]:
    projected = []
    for row_index, row_mask in enumerate(template.block_mask):
        for bit_index in range(8):
            if (row_mask >> bit_index) & 1:
                continue
            # VCMI inverts H3M mask row/bit into bottom-right-relative offsets.
            projected.append((
                map_object.x - (7 - bit_index),
                map_object.y - (5 - row_index),
                map_object.z,
            ))
    return tuple(projected)


def _read_object_templates(reader: _H3MReader) -> tuple[H3ObjectTemplate, ...]:
    count = reader.read_u32("object template count")
    templates = []
    for template_index in range(count):
        animation_file = reader.read_base_string(f"template {template_index} animation")
        block_mask = reader.read(6, f"template {template_index} block mask")
        visit_mask = reader.read(6, f"template {template_index} visit mask")
        reader.skip(2, f"template {template_index} unused")
        terrain_mask = reader.read_u16(f"template {template_index} terrain mask")
        object_id = reader.read_u32(f"template {template_index} object id")
        subid = reader.read_u32(f"template {template_index} subid")
        object_type = reader.read_u8(f"template {template_index} object type")
        print_priority = reader.read_u8(f"template {template_index} print priority")
        reader.skip(16, f"template {template_index} unused tail")
        templates.append(
            H3ObjectTemplate(
                template_index=template_index,
                animation_file=animation_file,
                block_mask=block_mask,
                visit_mask=visit_mask,
                terrain_mask=terrain_mask,
                object_id=object_id,
                subid=subid,
                object_type=object_type,
                print_priority=print_priority,
            )
        )
    return tuple(templates)


def _read_objects(
    reader: _H3MReader,
    templates: tuple[H3ObjectTemplate, ...],
    features: _H3MFeatures,
) -> tuple[tuple[H3MapObject, ...], tuple[H3NeutralMonsterTarget, ...]]:
    count = reader.read_u32("object count")
    objects = []
    neutral_targets = []
    for object_index in range(count):
        x = reader.read_u8(f"object {object_index} x")
        y = reader.read_u8(f"object {object_index} y")
        z = reader.read_u8(f"object {object_index} z")
        template_index = reader.read_u32(f"object {object_index} template index")
        if template_index >= len(templates):
            raise H3MapLoadError(
                reader.path,
                f"object {object_index} references missing template {template_index}",
            )
        reader.skip(5, f"object {object_index} unused header")
        map_object = H3MapObject(
            object_index=object_index,
            x=x,
            y=y,
            z=z,
            template_index=template_index,
        )
        objects.append(map_object)

        template = templates[template_index]
        target = _read_object_payload(
            reader,
            features,
            map_object,
            template,
        )
        if target is not None:
            neutral_targets.append(target)

    return tuple(objects), tuple(neutral_targets)


def _read_object_payload(
    reader: _H3MReader,
    features: _H3MFeatures,
    map_object: H3MapObject,
    template: H3ObjectTemplate,
) -> H3NeutralMonsterTarget | None:
    object_id = template.object_id
    subid = template.subid

    if object_id in H3M_MONSTER_OBJECT_IDS:
        return _read_monster_target(reader, features, map_object, template)
    if object_id in (34, 62, 70):
        _skip_hero(reader, features, map_object.object_index)
    elif object_id == 26:
        _skip_event(reader, features, map_object.object_index)
    elif object_id == 6:
        _skip_pandora(reader, features, map_object.object_index)
    elif object_id in (59, 91):
        _skip_sign(reader, map_object.object_index)
    elif object_id == 83:
        _skip_seer_hut(reader, features, map_object.object_index)
    elif object_id == 113:
        _skip_witch_hut(reader, features, map_object.object_index)
    elif object_id == 81:
        _skip_scholar(reader, map_object.object_index)
    elif object_id in (33, 219):
        _skip_garrison(reader, features, map_object.object_index)
    elif object_id in (5, 65, 66, 67, 68, 69):
        _skip_artifact_object(reader, features, map_object.object_index)
    elif object_id == 93:
        _skip_scroll(reader, features, map_object.object_index)
    elif object_id in (76, 79):
        _skip_resource(reader, features, map_object.object_index)
    elif object_id in (53, 220):
        if object_id == 220 or subid >= 7:
            _skip_abandoned_mine(reader, features, map_object.object_index)
        else:
            _skip_mine(reader, map_object.object_index)
    elif object_id in (17, 18, 19, 20):
        _skip_dwelling(reader, map_object.object_index)
    elif object_id in (216, 217, 218):
        _skip_random_dwelling(reader, features, template, map_object.object_index)
    elif object_id in (88, 89, 90):
        _skip_shrine(reader, map_object.object_index)
    elif object_id == 214:
        _skip_hero_placeholder(reader, map_object.object_index)
    elif object_id == 36 and subid < 1000:
        reader.skip(4, f"object {map_object.object_index} grail radius")
    elif object_id == 215:
        _skip_quest_guard(reader, features, map_object.object_index)
    elif object_id in (42, 87):
        reader.skip(4, f"object {map_object.object_index} owner")
    elif object_id in (77, 98):
        _skip_town(reader, features, map_object.object_index)
    return None


def _read_monster_target(
    reader: _H3MReader,
    features: _H3MFeatures,
    map_object: H3MapObject,
    template: H3ObjectTemplate,
) -> H3NeutralMonsterTarget:
    if features.level_ab:
        reader.read_u32(f"object {map_object.object_index} monster identifier")
    count = reader.read_u16(f"object {map_object.object_index} monster count")
    reader.read_i8(f"object {map_object.object_index} monster character")
    has_message = bool(reader.read_u8(f"object {map_object.object_index} monster message flag"))
    if has_message:
        reader.read_base_string(f"object {map_object.object_index} monster message")
        _skip_resources(reader, features, f"object {map_object.object_index} monster resources")
        _read_artifact_id(
            reader,
            features,
            f"object {map_object.object_index} monster artifact",
        )
    reader.read_u8(f"object {map_object.object_index} monster never flees")
    reader.read_u8(f"object {map_object.object_index} monster not growing team")
    reader.skip(2, f"object {map_object.object_index} monster unused")

    creature_name, estimator_creature_id = _map_template_to_estimator_creature(
        template.animation_file,
    )
    return H3NeutralMonsterTarget(
        object_index=map_object.object_index,
        x=map_object.x,
        y=map_object.y,
        z=map_object.z,
        template=template,
        h3m_subid=template.subid,
        count=count,
        creature_name=creature_name,
        estimator_creature_id=estimator_creature_id,
    )


def _skip_hero(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    if features.level_ab:
        reader.skip(4, f"object {object_index} hero identifier")
    reader.skip(1, f"object {object_index} hero owner")
    reader.skip(1, f"object {object_index} hero type")
    if reader.read_u8(f"object {object_index} hero custom name flag"):
        reader.read_base_string(f"object {object_index} hero custom name")
    if features.level_sod:
        if reader.read_u8(f"object {object_index} hero custom experience flag"):
            reader.skip(4, f"object {object_index} hero experience")
    else:
        reader.skip(4, f"object {object_index} hero experience")
    if reader.read_u8(f"object {object_index} hero portrait flag"):
        reader.skip(1, f"object {object_index} hero portrait")
    if reader.read_u8(f"object {object_index} hero secondary skills flag"):
        skills_count = reader.read_u32(f"object {object_index} hero skills count")
        reader.skip(skills_count * 2, f"object {object_index} hero skills")
    if reader.read_u8(f"object {object_index} hero garrison flag"):
        _skip_creature_set(reader, features, f"object {object_index} hero garrison")
    reader.skip(1, f"object {object_index} hero formation")
    _skip_artifacts_of_hero(reader, features, f"object {object_index} hero")
    reader.skip(1, f"object {object_index} hero patrol radius")
    if features.level_ab:
        if reader.read_u8(f"object {object_index} hero biography flag"):
            reader.read_base_string(f"object {object_index} hero biography")
        reader.skip(1, f"object {object_index} hero gender")
    if features.level_sod:
        if reader.read_u8(f"object {object_index} hero custom spells flag"):
            reader.skip(features.spells_bytes, f"object {object_index} hero spells")
    elif features.level_ab:
        reader.skip(1, f"object {object_index} hero spell")
    if features.level_sod:
        if reader.read_u8(f"object {object_index} hero primary skills flag"):
            reader.skip(4, f"object {object_index} hero primary skills")
    reader.skip(16, f"object {object_index} hero unused tail")


def _skip_event(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_box_content(reader, features, f"object {object_index} event")
    reader.skip(1, f"object {object_index} event players")
    reader.skip(1, f"object {object_index} event computer activate")
    reader.skip(1, f"object {object_index} event remove after visit")
    reader.skip(4, f"object {object_index} event unused")


def _skip_pandora(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_box_content(reader, features, f"object {object_index} pandora")


def _skip_box_content(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    _skip_message_and_guards(reader, features, f"{context} guards")
    reader.skip(4, f"{context} hero experience")
    reader.skip(4, f"{context} mana")
    reader.skip(1, f"{context} morale")
    reader.skip(1, f"{context} luck")
    _skip_resources(reader, features, f"{context} resources")
    reader.skip(4, f"{context} primary skills")
    abilities = reader.read_u8(f"{context} abilities count")
    reader.skip(abilities * 2, f"{context} abilities")
    artifacts = reader.read_u8(f"{context} artifacts count")
    for artifact_index in range(artifacts):
        _read_artifact_id(reader, features, f"{context} artifact {artifact_index}")
    spells = reader.read_u8(f"{context} spells count")
    reader.skip(spells, f"{context} spells")
    creatures = reader.read_u8(f"{context} creatures count")
    for creature_index in range(creatures):
        _read_creature_id(reader, features, f"{context} creature {creature_index}")
        reader.skip(2, f"{context} creature {creature_index} count")
    reader.skip(8, f"{context} unused")


def _skip_sign(reader: _H3MReader, object_index: int) -> None:
    reader.read_base_string(f"object {object_index} sign message")
    reader.skip(4, f"object {object_index} sign unused")


def _skip_witch_hut(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    if features.level_ab:
        reader.skip(features.skills_bytes, f"object {object_index} witch hut skills")


def _skip_scholar(reader: _H3MReader, object_index: int) -> None:
    reader.skip(2, f"object {object_index} scholar bonus")
    reader.skip(6, f"object {object_index} scholar unused")


def _skip_garrison(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    reader.skip(4, f"object {object_index} garrison owner")
    _skip_creature_set(reader, features, f"object {object_index} garrison")
    if features.level_ab:
        reader.skip(1, f"object {object_index} garrison removable units")
    reader.skip(8, f"object {object_index} garrison unused")


def _skip_artifact_object(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_message_and_guards(reader, features, f"object {object_index} artifact")


def _skip_scroll(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_message_and_guards(reader, features, f"object {object_index} scroll")
    reader.skip(4, f"object {object_index} scroll spell")


def _skip_resource(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_message_and_guards(reader, features, f"object {object_index} resource")
    reader.skip(4, f"object {object_index} resource amount")
    reader.skip(4, f"object {object_index} resource unused")


def _skip_mine(reader: _H3MReader, object_index: int) -> None:
    reader.skip(4, f"object {object_index} mine owner")


def _skip_abandoned_mine(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    reader.skip(features.resources_bytes, f"object {object_index} abandoned mine resources")


def _skip_dwelling(reader: _H3MReader, object_index: int) -> None:
    reader.skip(4, f"object {object_index} dwelling owner")


def _skip_random_dwelling(
    reader: _H3MReader,
    features: _H3MFeatures,
    template: H3ObjectTemplate,
    object_index: int,
) -> None:
    reader.skip(4, f"object {object_index} random dwelling owner")
    if template.object_id in (216, 217):
        identifier = reader.read_u32(f"object {object_index} random dwelling identifier")
        if identifier == 0:
            reader.skip(features.factions_bytes, f"object {object_index} random dwelling factions")
    if template.object_id in (216, 218):
        reader.skip(2, f"object {object_index} random dwelling level range")


def _skip_shrine(reader: _H3MReader, object_index: int) -> None:
    reader.skip(4, f"object {object_index} shrine spell")


def _skip_hero_placeholder(reader: _H3MReader, object_index: int) -> None:
    reader.skip(1, f"object {object_index} hero placeholder owner")
    hero_type = reader.read_u8(f"object {object_index} hero placeholder type")
    if hero_type == 0xFF:
        reader.skip(1, f"object {object_index} hero placeholder power rank")


def _skip_quest_guard(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_quest(reader, features, f"object {object_index} quest guard")


def _skip_seer_hut(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    _skip_seer_hut_quest(reader, features, f"object {object_index} seer hut")
    reader.skip(2, f"object {object_index} seer hut unused")


def _skip_seer_hut_quest(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    mission = _skip_quest(reader, features, context)
    if mission != 0:
        reward = reader.read_u8(f"{context} reward type")
        if reward in (0,):
            pass
        elif reward in (1, 2):
            reader.skip(4, f"{context} reward value")
        elif reward in (3, 4):
            reader.skip(1, f"{context} reward value")
        elif reward == 5:
            reader.skip(1, f"{context} reward resource id")
            reader.skip(4, f"{context} reward resource amount")
        elif reward == 6:
            reader.skip(2, f"{context} reward primary skill")
        elif reward == 7:
            reader.skip(2, f"{context} reward secondary skill")
        elif reward == 8:
            _read_artifact_id(reader, features, f"{context} reward artifact")
        elif reward == 9:
            reader.skip(1, f"{context} reward spell")
        elif reward == 10:
            _read_creature_id(reader, features, f"{context} reward creature")
            reader.skip(2, f"{context} reward creature count")
        else:
            raise H3MapLoadError(
                reader.path,
                f"unsupported {context} reward type {reward} at offset {reader.tell()}",
            )
    else:
        reader.skip(1, f"{context} empty reward marker")


def _skip_quest(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> int:
    mission = reader.read_u8(f"{context} mission")
    if mission == 0:
        return mission
    if mission == 1:
        reader.skip(4, f"{context} quest level")
    elif mission == 2:
        reader.skip(4, f"{context} quest primary skills")
    elif mission in (3, 4):
        reader.skip(4, f"{context} quest target")
    elif mission == 5:
        artifact_count = reader.read_u8(f"{context} quest artifact count")
        for artifact_index in range(artifact_count):
            _read_artifact_id(
                reader,
                features,
                f"{context} quest artifact {artifact_index}",
            )
    elif mission == 6:
        creature_count = reader.read_u8(f"{context} quest creature count")
        for creature_index in range(creature_count):
            _read_creature_id(
                reader,
                features,
                f"{context} quest creature {creature_index}",
            )
            reader.skip(2, f"{context} quest creature {creature_index} count")
    elif mission == 7:
        _skip_resources(reader, features, f"{context} quest resources")
    elif mission == 8:
        _read_hero_id(reader, f"{context} quest hero")
    elif mission == 9:
        reader.skip(1, f"{context} quest player")
    else:
        raise H3MapLoadError(
            reader.path,
            f"unsupported {context} mission {mission} at offset {reader.tell()}",
        )

    reader.skip(4, f"{context} quest last day")
    reader.read_base_string(f"{context} quest first visit text")
    reader.read_base_string(f"{context} quest next visit text")
    reader.read_base_string(f"{context} quest completed text")
    return mission


def _skip_town(
    reader: _H3MReader,
    features: _H3MFeatures,
    object_index: int,
) -> None:
    if features.level_ab:
        reader.skip(4, f"object {object_index} town identifier")
    reader.skip(1, f"object {object_index} town owner")
    if reader.read_u8(f"object {object_index} town name flag"):
        reader.read_base_string(f"object {object_index} town name")
    if reader.read_u8(f"object {object_index} town garrison flag"):
        _skip_creature_set(reader, features, f"object {object_index} town garrison")
    reader.skip(1, f"object {object_index} town formation")
    if reader.read_u8(f"object {object_index} town custom buildings flag"):
        reader.skip(features.buildings_bytes, f"object {object_index} town built buildings")
        reader.skip(features.buildings_bytes, f"object {object_index} town forbidden buildings")
    else:
        reader.skip(1, f"object {object_index} town fort flag")
    if features.level_ab:
        reader.skip(features.spells_bytes, f"object {object_index} town obligatory spells")
    reader.skip(features.spells_bytes, f"object {object_index} town possible spells")
    event_count = reader.read_u32(f"object {object_index} town event count")
    for event_index in range(event_count):
        _skip_map_event_common(
            reader,
            features,
            f"object {object_index} town event {event_index}",
        )
        reader.skip(features.buildings_bytes, f"object {object_index} town event buildings")
        reader.skip(14, f"object {object_index} town event creatures")
        reader.skip(4, f"object {object_index} town event unused")
    if features.level_sod:
        reader.skip(1, f"object {object_index} town alignment")
    reader.skip(3, f"object {object_index} town unused")


def _skip_map_event_common(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    reader.read_base_string(f"{context} name")
    reader.read_base_string(f"{context} message")
    _skip_resources(reader, features, f"{context} resources")
    reader.skip(1, f"{context} players")
    if features.level_sod:
        reader.skip(1, f"{context} human affected")
    reader.skip(1, f"{context} computer affected")
    reader.skip(2, f"{context} first occurrence")
    reader.skip(2, f"{context} next occurrence")
    reader.skip(16, f"{context} unused")


def _skip_message_and_guards(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    has_message = bool(reader.read_u8(f"{context} message flag"))
    if not has_message:
        return
    reader.read_base_string(f"{context} message")
    has_guards = bool(reader.read_u8(f"{context} guards flag"))
    if has_guards:
        _skip_creature_set(reader, features, f"{context} guards")
    reader.skip(4, f"{context} unused")


def _skip_artifacts_of_hero(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    has_artifact_set = bool(reader.read_u8(f"{context} artifact set flag"))
    if not has_artifact_set:
        return
    for slot in range(features.artifact_slots_count):
        _read_artifact_id(reader, features, f"{context} artifact slot {slot}")
    backpack_count = reader.read_u16(f"{context} backpack artifact count")
    for index in range(backpack_count):
        _read_artifact_id(reader, features, f"{context} backpack artifact {index}")


def _skip_creature_set(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    for slot in range(7):
        _read_creature_id(reader, features, f"{context} creature slot {slot}")
        reader.skip(2, f"{context} creature slot {slot} count")


def _skip_resources(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> None:
    reader.skip(features.resources_count * 4, context)


def _read_hero_id(reader: _H3MReader, context: str) -> int:
    return reader.read_u8(context)


def _read_artifact_id(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> int:
    if features.level_ab:
        return reader.read_u16(context)
    return reader.read_u8(context)


def _read_creature_id(
    reader: _H3MReader,
    features: _H3MFeatures,
    context: str,
) -> int:
    if features.level_ab:
        return reader.read_u16(context)
    return reader.read_u8(context)


def _map_template_to_estimator_creature(
    animation_file: str,
) -> tuple[str | None, int | None]:
    def_name = animation_file.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    creature_name = H3M_DEF_TO_ESTIMATOR_CREATURE_NAME.get(def_name)
    if creature_name is None:
        return None, None
    return creature_name, _estimator_creature_id_by_name(creature_name)


def _estimator_creature_id_by_name(creature_name: str) -> int | None:
    try:
        module = import_module("tools.battle_estimator")
    except ModuleNotFoundError as exc:
        if exc.name != "tools":
            raise
        module = import_module("battle_estimator")

    for creature_id, creature in enumerate(module.CREATURES):
        if creature.name.casefold() == creature_name.casefold():
            return creature_id
    return None
