#!/usr/bin/env python3
"""Contracts and minimal loader for Heroes III H3M map files."""

from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path


H3M_START_OFFSET_CANDIDATES = (0, 43)
H3M_HEADER_MIN_SIZE = 10
H3M_FORMAT_ROE = 0x0E
H3M_FORMAT_AB = 0x15
H3M_FORMAT_SOD = 0x1C
H3M_OBJECT_MONSTER = 54
H3M_OBJECT_RANDOM_MONSTER = 71
H3M_OBJECT_RANDOM_MONSTER_L1 = 72
H3M_OBJECT_RANDOM_MONSTER_L2 = 73
H3M_OBJECT_RANDOM_MONSTER_L3 = 74
H3M_OBJECT_RANDOM_MONSTER_L4 = 75

H3M_MONSTER_OBJECT_IDS = frozenset((
    H3M_OBJECT_MONSTER,
    H3M_OBJECT_RANDOM_MONSTER,
    H3M_OBJECT_RANDOM_MONSTER_L1,
    H3M_OBJECT_RANDOM_MONSTER_L2,
    H3M_OBJECT_RANDOM_MONSTER_L3,
    H3M_OBJECT_RANDOM_MONSTER_L4,
))

SUPPORTED_H3M_FORMATS = {
    H3M_FORMAT_ROE: "RoE",
    H3M_FORMAT_AB: "AB",
    H3M_FORMAT_SOD: "SoD",
}

H3M_DEF_TO_ESTIMATOR_CREATURE_NAME = {
    "avwgrem0.def": "Gremlin",
    "avwgrex0.def": "Master Gremlin",
    "avwgnll0.def": "Gnoll",
    "avwgnlx0.def": "Gnoll Marauder",
    "avwsfly.def": "Serpent Fly",
    "avwdfly.def": "Dragon Fly",
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


class H3MapLoadError(ValueError):
    """Raised when a Heroes III map cannot be loaded or identified."""

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
        header, templates, objects, neutral_targets = _parse_h3m_structures(
            data,
            h3m_offset,
            map_path,
        )
        return LoadedH3Map(
            path=map_path,
            data=data,
            h3m_offset=h3m_offset,
            header=header,
            templates=templates,
            objects=objects,
            neutral_targets=neutral_targets,
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


def load_h3m_neutral_monsters(path: str | Path) -> tuple[H3NeutralMonsterTarget, ...]:
    """Load neutral monster targets from an H3M map file."""

    return load_h3m(path, parse_objects=True).neutral_targets


def parse_h3m_neutral_monsters(
    data: bytes,
    offset: int = 0,
    path: str | Path = "<memory>",
) -> tuple[H3NeutralMonsterTarget, ...]:
    """Parse neutral monster targets from decompressed H3M bytes."""

    return _parse_h3m_structures(data, offset, Path(path))[3]


def _decompress_h3m_bytes(compressed: bytes, path: Path) -> bytes:
    try:
        return gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as exc:
        raise H3MapLoadError(path, f"gzip decompress failed: {exc}") from exc


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
) -> tuple[
    H3MapHeader,
    tuple[H3ObjectTemplate, ...],
    tuple[H3MapObject, ...],
    tuple[H3NeutralMonsterTarget, ...],
]:
    reader = _H3MReader(data, path, offset)
    header, features = _read_full_header(reader)
    _skip_player_info(reader, features)
    _skip_victory_loss_conditions(reader, features)
    _skip_team_info(reader)
    _skip_allowed_heroes(reader, features)
    _skip_disposed_heroes(reader, features)
    _skip_map_options(reader)
    _skip_allowed_artifacts(reader, features)
    _skip_allowed_spells_abilities(reader, features)
    _skip_rumors(reader)
    _skip_predefined_heroes(reader, features)
    _skip_terrain(reader, header)
    templates = _read_object_templates(reader)
    objects, targets = _read_objects(reader, templates, features)
    return header, templates, objects, targets


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


def _skip_player_info(reader: _H3MReader, features: _H3MFeatures) -> None:
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
            continue

        reader.read_i8(f"player {player_index} AI tactic")
        if features.level_sod:
            reader.skip(1, f"player {player_index} selectable faction flag")
        reader.skip(features.factions_bytes, f"player {player_index} factions bitmask")
        reader.read_u8(f"player {player_index} random faction flag")

        has_main_town = bool(reader.read_u8(f"player {player_index} main town flag"))
        if has_main_town:
            if features.level_ab:
                reader.read_u8(f"player {player_index} generate hero at main town")
                reader.skip(1, f"player {player_index} unused starting town type")
            reader.skip(3, f"player {player_index} main town position")

        reader.read_u8(f"player {player_index} random hero flag")
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


def _skip_team_info(reader: _H3MReader) -> None:
    team_count = reader.read_u8("team count")
    if team_count > 0:
        reader.skip(8, "team assignments")


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


def _skip_terrain(reader: _H3MReader, header: H3MapHeader) -> None:
    tile_count = header.map_size * header.map_size * header.levels
    reader.skip(tile_count * 7, "terrain tiles")


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
