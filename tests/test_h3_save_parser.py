import importlib
import gzip
import json
import os
import tempfile
import unittest
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import battle_estimator
from tools import h3_map_parser
from tools import h3_save_parser
from tools import hero_skill_recommender


ISRA_CREATURE_IDS = (57, 59, 63, 65, 67, 56, 69)
ISRA_MOVED_CREATURE_IDS = (59, 57, 63, 65, 67, 56, 69)
ISRA_COUNTS = (731, 181, 59, 47, 19, 316, 8)
ISRA_MOVED_COUNTS = (181, 731, 59, 47, 19, 316, 8)
HERO_COMBAT_SECONDARY_COUNT_FROM_NAME_OFFSET = -126
HERO_COMBAT_SECONDARY_LEVELS_FROM_NAME_OFFSET = 13
HERO_COMBAT_SECONDARY_SLOTS_FROM_NAME_OFFSET = 41
HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET = 69
HERO_COMBAT_SECONDARY_SKILL_COUNT = 28
HERO_COMBAT_LEVEL_BASIC = 1
HERO_COMBAT_LEVEL_ADVANCED = 2
HERO_COMBAT_LEVEL_EXPERT = 3
# Standard H3 save-vector indices. Project-facing IDs may normalize names later
# (for example Offense becomes the VCMI-style "offence").
HERO_COMBAT_ARCHERY_INDEX = 1
HERO_COMBAT_OFFENSE_INDEX = 22
HERO_COMBAT_ARMORER_INDEX = 23


def _xor_encode(raw: bytes, key=h3_save_parser.HERO_ARMY_XOR_KEY) -> bytes:
    return bytes(byte ^ key for byte in raw)


def _ensure_data_size(data: bytearray, size: int):
    if size > len(data):
        data.extend(b"\x00" * (size - len(data)))


def _write_encoded_test_bytes(
    data: bytearray,
    offset: int,
    raw: bytes,
    xor_key: int,
):
    _ensure_data_size(data, offset + len(raw))
    data[offset:offset + len(raw)] = _xor_encode(raw, xor_key)


def _write_hero_combat_fields(
    data: bytearray,
    name_offset: int,
    primary_skills=None,
    secondary_skills=(),
    secondary_count=None,
    secondary_levels=None,
    secondary_slots=None,
    xor_key=0x00,
):
    if primary_skills is not None:
        if len(primary_skills) != 4:
            raise ValueError("primary_skills must contain four values")
        _write_encoded_test_bytes(
            data,
            name_offset + HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET,
            bytes(int(value) for value in primary_skills),
            xor_key,
        )

    if (
        secondary_skills
        or secondary_count is not None
        or secondary_levels is not None
        or secondary_slots is not None
    ):
        levels = (
            [0] * HERO_COMBAT_SECONDARY_SKILL_COUNT
            if secondary_levels is None
            else list(secondary_levels)
        )
        slots = (
            [0] * HERO_COMBAT_SECONDARY_SKILL_COUNT
            if secondary_slots is None
            else list(secondary_slots)
        )
        if len(levels) != HERO_COMBAT_SECONDARY_SKILL_COUNT:
            raise ValueError("secondary_levels must contain 28 values")
        if len(slots) != HERO_COMBAT_SECONDARY_SKILL_COUNT:
            raise ValueError("secondary_slots must contain 28 values")

        for skill_index, level, slot in secondary_skills:
            if not 0 <= skill_index < HERO_COMBAT_SECONDARY_SKILL_COUNT:
                raise ValueError(f"skill index out of range: {skill_index}")
            levels[skill_index] = int(level)
            slots[skill_index] = int(slot)

        if secondary_count is None:
            secondary_count = sum(
                1
                for level, slot in zip(levels, slots)
                if level or slot
            )

        _write_encoded_test_bytes(
            data,
            name_offset + HERO_COMBAT_SECONDARY_COUNT_FROM_NAME_OFFSET,
            bytes([int(secondary_count)]),
            xor_key,
        )
        _write_encoded_test_bytes(
            data,
            name_offset + HERO_COMBAT_SECONDARY_LEVELS_FROM_NAME_OFFSET,
            bytes(levels),
            xor_key,
        )
        _write_encoded_test_bytes(
            data,
            name_offset + HERO_COMBAT_SECONDARY_SLOTS_FROM_NAME_OFFSET,
            bytes(slots),
            xor_key,
        )


def _removed_neutral_record_bytes(
    object_index,
    h3m_subid,
    removal_flags=0x8000,
):
    return b"".join((
        int(object_index).to_bytes(4, "little"),
        int(removal_flags).to_bytes(4, "little"),
        int(h3m_subid).to_bytes(4, "little"),
        h3_save_parser.REMOVED_NEUTRAL_RECORD_MARKER.to_bytes(4, "little"),
    ))


def _removed_neutral_record_core_bytes(
    object_index,
    h3m_subid,
    removal_flags=0x8000,
):
    return b"".join((
        int(object_index).to_bytes(4, "little"),
        int(removal_flags).to_bytes(4, "little"),
        int(h3m_subid).to_bytes(4, "little"),
    ))


def _removed_neutral_coord_record_bytes(
    position,
    object_index,
    h3m_subid,
    removal_flags=0x48007000,
):
    x, y, z = position
    encoded_yz = int(y) + (int(z) << h3_save_parser.REMOVED_NEUTRAL_COORD_LEVEL_SHIFT)
    return b"".join((
        int(x).to_bytes(2, "little"),
        encoded_yz.to_bytes(2, "little"),
        int(object_index).to_bytes(4, "little"),
        int(removal_flags).to_bytes(4, "little"),
        int(h3m_subid).to_bytes(4, "little"),
    ))


def _build_xor_hero_fixture(
    hero_name="Isra",
    creature_ids=ISRA_CREATURE_IDS,
    counts=ISRA_COUNTS,
    name_offset=256,
    position=None,
    owner_color_id=0,
    xor_key=h3_save_parser.HERO_ARMY_XOR_KEY,
    position_from_name_offset=h3_save_parser.HERO_STRUCT_POSITION_FROM_NAME_OFFSET,
):
    data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE + 32)
    ids_offset = name_offset + h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET
    counts_offset = name_offset + h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET
    owner_offset = name_offset - h3_save_parser.HERO_STRUCT_NAME_OFFSET

    if owner_offset >= 0 and owner_color_id is not None:
        encoded_owner = _xor_encode(bytes([int(owner_color_id)]), xor_key)
        data[owner_offset:owner_offset + 1] = encoded_owner

    for slot, creature_id in enumerate(creature_ids):
        encoded = _xor_encode(int(creature_id).to_bytes(4, "little"), xor_key)
        offset = ids_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded
    for slot, count in enumerate(counts):
        encoded = _xor_encode(int(count).to_bytes(4, "little"), xor_key)
        offset = counts_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded

    name_bytes = hero_name.encode("ascii")
    if len(name_bytes) > h3_save_parser.HERO_NAME_SIZE:
        raise ValueError("test hero name is too long")
    padded_name = name_bytes.ljust(h3_save_parser.HERO_NAME_SIZE, b"\x00")
    data[name_offset:name_offset + h3_save_parser.HERO_NAME_SIZE] = _xor_encode(
        padded_name,
        xor_key,
    )
    if position is not None:
        x, y, z = position
        position_offset = name_offset + position_from_name_offset
        position_bytes = b"".join((
            int(x).to_bytes(2, "little"),
            int(y).to_bytes(2, "little"),
            bytes([int(z)]),
        ))
        data[position_offset:position_offset + h3_save_parser.HERO_POSITION_SIZE] = _xor_encode(
            position_bytes,
            xor_key,
        )
    return bytes(data), name_offset


def _build_hero_combat_fixture(
    hero_name="Isra",
    primary_skills=(8, 6, 4, 5),
    secondary_skills=(),
    secondary_count=None,
    secondary_levels=None,
    secondary_slots=None,
    name_offset=256,
    xor_key=0x00,
    include_h3svg_signature=True,
):
    data, name_offset = _build_xor_hero_fixture(
        hero_name=hero_name,
        name_offset=name_offset,
        xor_key=xor_key,
    )
    mutable = bytearray(data)
    if include_h3svg_signature:
        mutable[0:len(h3_save_parser.H3SVG_SIGNATURE)] = (
            h3_save_parser.H3SVG_SIGNATURE
        )
    _write_hero_combat_fields(
        mutable,
        name_offset,
        primary_skills=primary_skills,
        secondary_skills=secondary_skills,
        secondary_count=secondary_count,
        secondary_levels=secondary_levels,
        secondary_slots=secondary_slots,
        xor_key=xor_key,
    )
    return bytes(mutable), name_offset


def _decode_test_hero_combat_window(
    data: bytes,
    name_offset: int,
    relative_offset: int,
    length: int,
    xor_key=0x00,
):
    return h3_save_parser.xor_decode_bytes(
        data,
        name_offset + relative_offset,
        length,
        xor_key,
    )


def _decode_test_hero_combat_primary(data: bytes, name_offset: int, xor_key=0x00):
    return tuple(
        _decode_test_hero_combat_window(
            data,
            name_offset,
            HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET,
            4,
            xor_key,
        )
    )


def _decode_test_hero_combat_secondary_count(
    data: bytes,
    name_offset: int,
    xor_key=0x00,
):
    return _decode_test_hero_combat_window(
        data,
        name_offset,
        HERO_COMBAT_SECONDARY_COUNT_FROM_NAME_OFFSET,
        1,
        xor_key,
    )[0]


def _decode_test_hero_combat_secondary_vectors(
    data: bytes,
    name_offset: int,
    xor_key=0x00,
):
    levels = tuple(
        _decode_test_hero_combat_window(
            data,
            name_offset,
            HERO_COMBAT_SECONDARY_LEVELS_FROM_NAME_OFFSET,
            HERO_COMBAT_SECONDARY_SKILL_COUNT,
            xor_key,
        )
    )
    slots = tuple(
        _decode_test_hero_combat_window(
            data,
            name_offset,
            HERO_COMBAT_SECONDARY_SLOTS_FROM_NAME_OFFSET,
            HERO_COMBAT_SECONDARY_SKILL_COUNT,
            xor_key,
        )
    )
    return levels, slots


def _decode_test_hero_combat_active_secondaries(
    data: bytes,
    name_offset: int,
    xor_key=0x00,
):
    levels, slots = _decode_test_hero_combat_secondary_vectors(
        data,
        name_offset,
        xor_key,
    )
    active = []
    for skill_index, (level, slot) in enumerate(zip(levels, slots)):
        if level or slot:
            active.append((slot, skill_index, level))
    return tuple(
        (skill_index, level, slot)
        for slot, skill_index, level in sorted(active)
    )


def _write_gzip_save(path: Path, payload: bytes):
    path.write_bytes(gzip.compress(payload))


def _brute_force_scan_xor01_hero_armies(data: bytes):
    heroes = []
    last_name_offset = len(data) - h3_save_parser.HERO_NAME_SIZE
    for name_offset in range(h3_save_parser.HERO_STRUCT_NAME_OFFSET, last_name_offset + 1):
        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)
        if hero is not None:
            heroes.append(hero)
    return tuple(heroes)


def _build_multi_xor_hero_fixture(hero_specs):
    chunks = []
    for spec in hero_specs:
        chunk, _ = _build_xor_hero_fixture(
            hero_name=spec["hero_name"],
            creature_ids=spec.get("creature_ids", ISRA_CREATURE_IDS),
            counts=spec.get("counts", ISRA_COUNTS),
            name_offset=spec.get("name_offset", 256),
            position=spec.get("position"),
            owner_color_id=spec.get("owner_color_id", 0),
        )
        chunks.append(chunk)
        chunks.append(b"\x00" * 64)
    return b"".join(chunks)


def _build_town_proxy_fixture_heroes(hero_specs):
    if not hero_specs:
        return h3_save_parser.H3SVG_SIGNATURE
    return _build_multi_xor_hero_fixture(hero_specs)


def _synthetic_town_target(
    position=(6, 5, 0),
    initial_owner=0,
    object_index=17,
    h3m_subid=3,
    object_id=h3_map_parser.H3M_OBJECT_TOWN,
    include_anchor=True,
):
    x, y, z = position
    attrs = dict(
        object_index=object_index,
        object_id=object_id,
        h3m_subid=h3m_subid,
        faction_subid=h3m_subid,
        x=x,
        y=y,
        z=z,
        initial_owner=initial_owner,
    )
    if include_anchor:
        attrs.update(anchor_x=x + 1, anchor_y=y, anchor_z=z)
    return SimpleNamespace(**attrs)


def _hero_army(hero_name, stacks, source_offset=0, owner_color_id=None):
    return h3_save_parser.HeroArmy(
        hero_name=hero_name,
        stacks=tuple(
            h3_save_parser.HeroStack.from_creature_id(creature_id, count)
            for creature_id, count in stacks
        ),
        source_offset=source_offset,
        owner_color_id=owner_color_id,
    )


def _positioned_hero_army(
    hero_name,
    stacks,
    position,
    source_offset=0,
    owner_color_id=None,
):
    return h3_save_parser.HeroArmy(
        hero_name=hero_name,
        stacks=tuple(
            h3_save_parser.HeroStack.from_creature_id(creature_id, count)
            for creature_id, count in stacks
        ),
        source_offset=source_offset,
        position=h3_save_parser.HeroPosition(*position),
        owner_color_id=owner_color_id,
    )


class H3SaveParserContractTests(unittest.TestCase):
    def test_constants_use_home_derived_paths(self):
        home = Path.home()

        self.assertEqual(
            h3_save_parser.DEFAULT_GAMES_ROOT,
            home
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
        self.assertEqual(
            h3_save_parser.DEFAULT_AUTOSAVE_ROOT,
            h3_save_parser.DEFAULT_GAMES_ROOT,
        )
        self.assertEqual(
            h3_save_parser.CONFIG_PATH,
            home / ".config" / "vcmi-battle-estimator" / "config.json",
        )
        self.assertEqual(h3_save_parser.SAVE_EXTENSIONS, (".GM1", ".GM2"))
        self.assertEqual(h3_save_parser.RECENT_HERO_LIMIT, 8)

    def test_named_hero_offsets_are_derived_from_struct_offsets(self):
        self.assertEqual(h3_save_parser.HERO_ARMY_SLOT_COUNT, 7)
        self.assertEqual(h3_save_parser.HERO_ARMY_VALUE_SIZE, 4)
        self.assertEqual(h3_save_parser.HERO_NAME_SIZE, 13)
        self.assertEqual(h3_save_parser.HERO_STRUCT_ARMY_TYPES_OFFSET, 113)
        self.assertEqual(h3_save_parser.HERO_STRUCT_ARMY_COUNTS_OFFSET, 141)
        self.assertEqual(h3_save_parser.HERO_STRUCT_NAME_OFFSET, 169)
        self.assertEqual(h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET, -56)
        self.assertEqual(h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET, -28)
        self.assertEqual(h3_save_parser.HERO_STRUCT_POSITION_FROM_NAME_OFFSET, -194)
        self.assertEqual(h3_save_parser.HERO_POSITION_SIZE, 5)
        self.assertEqual(h3_save_parser.MAX_HERO_POSITION_COORD, 255)
        self.assertEqual(h3_save_parser.MAX_HERO_POSITION_LEVEL, 1)
        self.assertEqual(h3_save_parser.REMOVED_NEUTRAL_RECORD_SIZE, 16)
        self.assertEqual(h3_save_parser.REMOVED_NEUTRAL_RECORD_MARKER, 11)
        self.assertEqual(h3_save_parser.REMOVED_NEUTRAL_SCAN_TAIL_BYTES, 64 * 1024)

    def test_creature_id_maps_to_existing_battle_estimator_creature(self):
        creature = h3_save_parser.creature_by_id(57)

        self.assertIs(creature, battle_estimator.CREATURES[57])
        self.assertEqual(creature.name, "Skeleton Warrior")

    def test_hero_stack_factory_keeps_original_creature_object(self):
        stack = h3_save_parser.HeroStack.from_creature_id(57, 731)

        self.assertEqual(stack.creature_id, 57)
        self.assertIs(stack.creature, battle_estimator.CREATURES[57])
        self.assertEqual(stack.count, 731)

    def test_invalid_creature_ids_include_bad_id_in_error(self):
        for bad_id in (-1, len(battle_estimator.CREATURES)):
            with self.subTest(bad_id=bad_id):
                with self.assertRaisesRegex(ValueError, str(bad_id)):
                    h3_save_parser.creature_by_id(bad_id)

    def test_import_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as temp_home:
            temp_home_path = Path(temp_home)
            autosave_root = (
                temp_home_path
                / "Applications"
                / "Heroes of Might and Magic 3.app"
                / "Contents"
            )
            config_dir = temp_home_path / ".config" / "vcmi-battle-estimator"

            with patch.dict(os.environ, {"HOME": temp_home}):
                module = importlib.reload(h3_save_parser)

            self.assertFalse(autosave_root.exists())
            self.assertFalse(config_dir.exists())
            module.DEFAULT_AUTOSAVE_ROOT.relative_to(temp_home_path)

        importlib.reload(h3_save_parser)

    def test_find_h3svg_offset_locates_signature(self):
        self.assertEqual(h3_save_parser.find_h3svg_offset(b"H3SVG payload"), 0)
        self.assertEqual(
            h3_save_parser.find_h3svg_offset((b"x" * 65) + b"H3SVG payload"),
            65,
        )
        self.assertIsNone(h3_save_parser.find_h3svg_offset(b"not a save"))

    def test_load_save_reads_gzip_with_h3svg_at_offset_zero(self):
        payload = b"H3SVG payload"

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "001.GM1"
            save_path.write_bytes(gzip.compress(payload))

            loaded = h3_save_parser.load_save(save_path)

        self.assertEqual(loaded.path, save_path)
        self.assertEqual(loaded.data, payload)
        self.assertEqual(loaded.h3svg_offset, 0)

    def test_load_save_reads_gzip_with_prefixed_h3svg(self):
        payload = (b"x" * 65) + b"H3SVG payload"

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "001.GM2"
            save_path.write_bytes(gzip.compress(payload))

            loaded = h3_save_parser.load_save(str(save_path))

        self.assertEqual(loaded.path, save_path)
        self.assertEqual(loaded.data, payload)
        self.assertEqual(loaded.h3svg_offset, 65)

    def test_load_save_uses_raw_deflate_fallback(self):
        payload = b"H3SVG payload"
        compressed = gzip.compress(payload)
        broken_footer = compressed[:-8] + (b"\x00" * 8)

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "001.GM2"
            save_path.write_bytes(broken_footer)

            loaded = h3_save_parser.load_save(save_path)

        self.assertEqual(
            zlib.decompress(broken_footer[10:-8], -zlib.MAX_WBITS),
            payload,
        )
        self.assertEqual(loaded.data, payload)
        self.assertEqual(loaded.h3svg_offset, 0)

    def test_detect_removed_neutral_records_finds_unaligned_late_log_records(self):
        payload = (
            b"H3SVG"
            + b"\x00" * 3
            + _removed_neutral_record_bytes(2393, 98, 0x8000)
            + b"\x00" * 5
            + _removed_neutral_record_bytes(2331, 28, 0xA000)
            + b"\x00" * 7
            + _removed_neutral_record_bytes(2330, 29, 0x5000)
        )

        records = h3_save_parser.detect_removed_neutral_records(payload)

        self.assertEqual(
            [(record.object_index, record.h3m_subid) for record in records],
            [(2393, 98), (2331, 28), (2330, 29)],
        )
        self.assertEqual(records[0].source_offset, 8)
        self.assertEqual(records[0].removal_flags, 0x8000)

    def test_detect_removed_neutral_records_uses_known_targets_for_markerless_records(self):
        payload = (
            b"H3SVG"
            + b"\x00" * 3
            + _removed_neutral_record_core_bytes(2576, 71, 0x9000)
            + b"\x01\x00\x45\x00"
        )
        neutral_targets = (
            SimpleNamespace(object_index=2576, h3m_subid=71),
            SimpleNamespace(object_index=2577, h3m_subid=72),
        )

        strict_records = h3_save_parser.detect_removed_neutral_records(payload)
        map_aware_records = h3_save_parser.detect_removed_neutral_records(
            payload,
            neutral_targets=neutral_targets,
        )

        self.assertEqual(strict_records, ())
        self.assertEqual(len(map_aware_records), 1)
        self.assertEqual(map_aware_records[0].object_index, 2576)
        self.assertEqual(map_aware_records[0].h3m_subid, 71)
        self.assertEqual(map_aware_records[0].source_offset, 8)
        self.assertEqual(map_aware_records[0].removal_flags, 0x9000)

    def test_detect_removed_neutral_records_uses_known_targets_for_coord_records(self):
        payload = (
            b"H3SVG"
            + b"\x00" * 3
            + _removed_neutral_coord_record_bytes(
                (91, 92, 0),
                3217,
                119,
                0x48007000,
            )
        )
        neutral_targets = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=92, z=0),
            SimpleNamespace(object_index=3253, h3m_subid=119, x=87, y=85, z=0),
        )

        strict_records = h3_save_parser.detect_removed_neutral_records(payload)
        map_aware_records = h3_save_parser.detect_removed_neutral_records(
            payload,
            neutral_targets=neutral_targets,
        )

        self.assertEqual(strict_records, ())
        self.assertEqual(len(map_aware_records), 1)
        self.assertEqual(map_aware_records[0].object_index, 3217)
        self.assertEqual(map_aware_records[0].h3m_subid, 119)
        self.assertEqual(map_aware_records[0].source_offset, 8)
        self.assertEqual(map_aware_records[0].removal_flags, 0x48007000)

    def test_detect_removed_neutral_records_ignores_markerless_records_not_in_known_targets(self):
        payload = (
            b"H3SVG"
            + b"\x00" * 3
            + _removed_neutral_record_core_bytes(2576, 71, 0x9000)
            + b"\x01\x00\x45\x00"
        )
        neutral_targets = (
            SimpleNamespace(object_index=2576, h3m_subid=72),
        )

        records = h3_save_parser.detect_removed_neutral_records(
            payload,
            neutral_targets=neutral_targets,
        )

        self.assertEqual(records, ())

    def test_detect_removed_neutral_records_ignores_coord_records_not_matching_target(self):
        payload = (
            b"H3SVG"
            + b"\x00" * 3
            + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119)
        )
        wrong_subid = (
            SimpleNamespace(object_index=3217, h3m_subid=120, x=91, y=92, z=0),
        )
        wrong_position = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=93, z=0),
        )

        self.assertEqual(
            h3_save_parser.detect_removed_neutral_records(
                payload,
                neutral_targets=wrong_subid,
            ),
            (),
        )
        self.assertEqual(
            h3_save_parser.detect_removed_neutral_records(
                payload,
                neutral_targets=wrong_position,
            ),
            (),
        )

    def test_detect_removed_neutral_records_ignores_invalid_heuristic_records(self):
        payload = b"".join((
            b"H3SVG",
            _removed_neutral_record_bytes(2393, 98, 0x8010),
            _removed_neutral_record_bytes(0, 98, 0x8000),
            _removed_neutral_record_bytes(
                2331,
                h3_save_parser.MAX_REMOVED_NEUTRAL_SUBID + 1,
                0xA000,
            ),
            int(2330).to_bytes(4, "little"),
            int(0x5000).to_bytes(4, "little"),
            int(29).to_bytes(4, "little"),
            int(12).to_bytes(4, "little"),
        ))

        records = h3_save_parser.detect_removed_neutral_records(payload)

        self.assertEqual(records, ())

    def test_load_save_errors_include_path_for_missing_file(self):
        missing_path = Path("/tmp/vcmi-missing-save-for-test.GM1")

        with self.assertRaisesRegex(
            h3_save_parser.SaveLoadError,
            "vcmi-missing-save-for-test.GM1.*read failed",
        ):
            h3_save_parser.load_save(missing_path)

    def test_load_save_reports_unsupported_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "bad.GM1"
            save_path.write_bytes(b"bad")

            with self.assertRaises(h3_save_parser.SaveLoadError) as raised:
                h3_save_parser.load_save(save_path)

        message = str(raised.exception)
        self.assertIn(str(save_path), message)
        self.assertIn("gzip decompress failed", message)
        self.assertIn("raw deflate fallback failed", message)

    def test_load_save_wraps_truncated_gzip_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "truncated.GM1"
            save_path.write_bytes(gzip.compress(b"H3SVG payload")[:12])

            with self.assertRaises(h3_save_parser.SaveLoadError) as raised:
                h3_save_parser.load_save(save_path)

        message = str(raised.exception)
        self.assertIn(str(save_path), message)
        self.assertIn("gzip decompress failed", message)
        self.assertIn("raw deflate fallback failed", message)

    def test_load_save_reports_missing_h3svg_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "bad.GM2"
            save_path.write_bytes(gzip.compress(b"no signature"))

            with self.assertRaisesRegex(
                h3_save_parser.SaveLoadError,
                "bad.GM2.*missing H3SVG signature",
            ):
                h3_save_parser.load_save(save_path)

    def test_load_save_does_not_mutate_file(self):
        payload = b"H3SVG payload"

        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "001.GM1"
            save_path.write_bytes(gzip.compress(payload))
            before = save_path.read_bytes()

            h3_save_parser.load_save(save_path)

            self.assertEqual(save_path.read_bytes(), before)

    def test_parse_game_folder_datetime(self):
        self.assertEqual(
            h3_save_parser.parse_game_folder_datetime(
                "2026.04.26 20;45 Diamond"
            ),
            datetime(2026, 4, 26, 20, 45),
        )
        self.assertEqual(
            h3_save_parser.parse_game_folder_datetime(
                "2026.04.26 20:45 Diamond"
            ),
            datetime(2026, 4, 26, 20, 45),
        )
        self.assertIsNone(h3_save_parser.parse_game_folder_datetime("Diamond"))
        self.assertIsNone(
            h3_save_parser.parse_game_folder_datetime("2026.99.99 20;45 Bad")
        )

    def test_select_game_dir_uses_explicit_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)

            selected = h3_save_parser.select_game_dir(game_dir)

        self.assertEqual(selected, game_dir)

    def test_select_game_dir_errors_for_missing_explicit_directory(self):
        missing_dir = Path("/tmp/vcmi-missing-game-dir-for-test")

        with self.assertRaises(h3_save_parser.SaveSelectionError) as raised:
            h3_save_parser.select_game_dir(missing_dir)

        self.assertEqual(raised.exception.path, missing_dir)
        self.assertIn("not a directory", raised.exception.reason)

    def test_select_game_dir_picks_folder_with_newest_save_recursively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "Random" / "PlayerTwo" / "2026.04.26 20;45 Diamond"
            newest = root / "Hotseat" / "2026.05.01 09;15 Crystal"
            ignored = root / "Manual Saves"
            malformed = root / "2026.99.99 20;45 Bad"
            for folder in (older, newest, ignored, malformed):
                folder.mkdir(parents=True)
            older_save = older / "001.GM2"
            newest_save = newest / "[hotseat] 111.GM2"
            older_save.write_bytes(b"")
            newest_save.write_bytes(b"")
            os.utime(older_save, ns=(1_000, 1_000))
            os.utime(newest_save, ns=(2_000, 2_000))

            selected = h3_save_parser.select_game_dir(autosave_root=root)
            folders = h3_save_parser.list_save_folders(root)

        self.assertEqual(selected, newest)
        self.assertEqual(
            [folder.relative_path for folder in folders],
            [
                "Hotseat/2026.05.01 09;15 Crystal",
                "Random/PlayerTwo/2026.04.26 20;45 Diamond",
            ],
        )

    def test_parse_numeric_save_name(self):
        self.assertEqual(h3_save_parser.parse_numeric_save_name("415.GM1"), (415, 1))
        self.assertEqual(h3_save_parser.parse_numeric_save_name("415.gm2"), (415, 2))
        self.assertEqual(
            h3_save_parser.parse_numeric_save_name("GAME_BEGIN.GM2"),
            (h3_save_parser.GAME_BEGIN_SAVE_NUMBER, 2),
        )
        self.assertEqual(
            h3_save_parser.parse_numeric_save_name("[hotseat] 111.GM2"),
            (111, 2),
        )
        self.assertEqual(
            h3_save_parser.normalize_save_name("[hotseat] 111.GM2"),
            "111.GM2",
        )
        self.assertIsNone(h3_save_parser.parse_numeric_save_name("415_moved.GM1"))
        self.assertIsNone(h3_save_parser.parse_numeric_save_name("BATTLE.GM2"))

    def test_select_latest_save_accepts_game_begin_but_uses_latest_numbered_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "1.GM1").write_bytes(b"")
            (game_dir / "415.GM1").write_bytes(b"")
            expected = game_dir / "416.gm1"
            expected.write_bytes(b"")
            for extra_name in (
                "GAME_BEGIN.GM2",
                "BATTLE.GM2",
                "AUTOSAVE.GM2",
                "415_moved.GM1",
                "notes.txt",
            ):
                (game_dir / extra_name).write_bytes(b"")
            (game_dir / "999.GM2").mkdir()

            selected = h3_save_parser.select_latest_save(game_dir)

        self.assertEqual(selected, expected)

    def test_select_latest_save_uses_hotseat_prefix_and_game_begin_ordering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            game_begin = game_dir / "GAME_BEGIN.GM2"
            game_begin.write_bytes(b"")
            (game_dir / "[hotseat] 111.GM2").write_bytes(b"")
            expected = game_dir / "[hotseat] 112.GM2"
            expected.write_bytes(b"")

            selected = h3_save_parser.select_latest_save(game_dir)

        self.assertEqual(selected, expected)

    def test_select_latest_save_accepts_game_begin_as_only_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            expected = game_dir / "GAME_BEGIN.GM2"
            expected.write_bytes(b"")

            selected = h3_save_parser.select_latest_save(game_dir)

        self.assertEqual(selected, expected)

    def test_select_latest_save_prefers_gm2_for_same_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "415.GM1").write_bytes(b"")
            expected = game_dir / "415.GM2"
            expected.write_bytes(b"")

            selected = h3_save_parser.select_latest_save(game_dir)

        self.assertEqual(selected, expected)

    def test_select_latest_save_errors_when_no_numeric_saves_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "BATTLE.GM2").write_bytes(b"")

            with self.assertRaises(h3_save_parser.SaveSelectionError) as raised:
                h3_save_parser.select_latest_save(game_dir)

        self.assertEqual(raised.exception.path, game_dir)
        self.assertIn("no numeric", raised.exception.reason)

    def test_select_numbered_save_prefers_gm2_for_requested_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "999.GM2").write_bytes(b"")
            (game_dir / "415.GM1").write_bytes(b"")
            (game_dir / "415_moved.GM2").write_bytes(b"")
            (game_dir / "BATTLE.GM2").write_bytes(b"")
            expected = game_dir / "415.GM2"
            expected.write_bytes(b"")

            selected = h3_save_parser.select_numbered_save(game_dir, "415")

        self.assertEqual(selected, expected)

    def test_select_numbered_save_accepts_hotseat_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            expected = game_dir / "[hotseat] 111.GM2"
            expected.write_bytes(b"")

            selected = h3_save_parser.select_numbered_save(game_dir, "111")

        self.assertEqual(selected, expected)

    def test_select_numbered_save_reports_missing_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "414.GM2").write_bytes(b"")

            with self.assertRaises(h3_save_parser.SaveSelectionError) as raised:
                h3_save_parser.select_numbered_save(game_dir, 415)

        self.assertEqual(raised.exception.path, game_dir)
        self.assertIn("number 415", raised.exception.reason)

    def test_select_numbered_save_reports_invalid_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)

            with self.assertRaises(h3_save_parser.SaveSelectionError) as raised:
                h3_save_parser.select_numbered_save(game_dir, "bad")

        self.assertEqual(raised.exception.path, game_dir)
        self.assertIn("invalid save number", raised.exception.reason)

    def test_load_removed_neutral_records_for_save_scans_numeric_history(self):
        neutral_targets = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=92, z=0),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_gzip_save(game_dir / "133.GM2", b"H3SVG")
            _write_gzip_save(
                game_dir / "134.GM2",
                b"H3SVG"
                + b"\x00" * 3
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )
            _write_gzip_save(game_dir / "417.GM2", b"H3SVG")
            _write_gzip_save(
                game_dir / "418.GM2",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )
            _write_gzip_save(
                game_dir / "post_attack.GM1",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )

            records = h3_save_parser.load_removed_neutral_records_for_save(
                game_dir / "417.GM2",
                neutral_targets=neutral_targets,
                game_dir=game_dir,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].object_index, 3217)
        self.assertEqual(records[0].h3m_subid, 119)
        self.assertEqual(records[0].source_path.name, "134.GM2")

    def test_load_removed_neutral_records_for_save_ignores_future_numeric_saves(self):
        neutral_targets = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=92, z=0),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_gzip_save(game_dir / "133.GM2", b"H3SVG")
            _write_gzip_save(
                game_dir / "134.GM2",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )

            records = h3_save_parser.load_removed_neutral_records_for_save(
                game_dir / "133.GM2",
                neutral_targets=neutral_targets,
                game_dir=game_dir,
            )

        self.assertEqual(records, ())

    def test_removed_neutral_history_cache_reuses_persisted_entries(self):
        neutral_targets = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=92, z=0),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            cache_dir = temp_path / "cache"
            game_dir.mkdir()
            _write_gzip_save(game_dir / "001.GM2", b"H3SVG")
            _write_gzip_save(
                game_dir / "002.GM2",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )

            cache = h3_save_parser.RemovedNeutralHistoryCache(cache_dir=cache_dir)
            records = cache.load_removed_neutral_records_for_save(
                game_dir / "002.GM2",
                neutral_targets=neutral_targets,
                game_dir=game_dir,
            )

            warm_cache = h3_save_parser.RemovedNeutralHistoryCache(cache_dir=cache_dir)
            with patch(
                "tools.h3_save_parser.load_save",
                side_effect=AssertionError("unexpected cache miss"),
            ):
                cached_records = warm_cache.load_removed_neutral_records_for_save(
                    game_dir / "002.GM2",
                    neutral_targets=neutral_targets,
                    game_dir=game_dir,
                )

        self.assertEqual(len(records), 1)
        self.assertEqual(len(cached_records), 1)
        self.assertEqual(cached_records[0].source_path.name, "002.GM2")

    def test_removed_neutral_history_cache_scans_only_new_numeric_saves(self):
        neutral_targets = (
            SimpleNamespace(object_index=3217, h3m_subid=119, x=91, y=92, z=0),
            SimpleNamespace(object_index=3253, h3m_subid=119, x=87, y=85, z=0),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            cache_dir = temp_path / "cache"
            game_dir.mkdir()
            _write_gzip_save(game_dir / "001.GM2", b"H3SVG")
            _write_gzip_save(
                game_dir / "002.GM2",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((91, 92, 0), 3217, 119),
            )
            cache = h3_save_parser.RemovedNeutralHistoryCache(cache_dir=cache_dir)
            cache.load_removed_neutral_records_for_save(
                game_dir / "002.GM2",
                neutral_targets=neutral_targets,
                game_dir=game_dir,
            )

            _write_gzip_save(
                game_dir / "003.GM2",
                b"H3SVG"
                + _removed_neutral_coord_record_bytes((87, 85, 0), 3253, 119),
            )
            original_load_save = h3_save_parser.load_save
            load_save_calls = []

            def recording_load_save(path):
                load_save_calls.append(Path(path).name)
                return original_load_save(path)

            with patch(
                "tools.h3_save_parser.load_save",
                side_effect=recording_load_save,
            ):
                records = cache.load_removed_neutral_records_for_save(
                    game_dir / "003.GM2",
                    neutral_targets=neutral_targets,
                    game_dir=game_dir,
                )

        self.assertEqual(load_save_calls, ["003.GM2"])
        self.assertEqual(
            [(record.object_index, record.source_path.name) for record in records],
            [(3217, "002.GM2"), (3253, "003.GM2")],
        )

    def test_resolve_save_context_selects_game_dir_and_latest_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "2026.04.26 20;45 Diamond"
            game_dir.mkdir()
            latest_save = game_dir / "415.GM2"
            latest_save.write_bytes(b"")
            (game_dir / "414.GM2").write_bytes(b"")

            context = h3_save_parser.resolve_save_context(autosave_root=root)

        self.assertEqual(context.autosave_root, root)
        self.assertEqual(context.game_dir, game_dir)
        self.assertEqual(context.save_file, latest_save)

    def test_load_config_missing_file_returns_default_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing" / "config.json"

            config = h3_save_parser.load_config(config_path)

            self.assertEqual(config, h3_save_parser.BattleEstimatorConfig())
            self.assertIsNone(config.my_color_id)
            self.assertEqual(config.alert_radius, h3_save_parser.DEFAULT_ALERT_RADIUS)
            self.assertFalse(config_path.exists())

    def test_config_alert_settings_load_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")

            config = h3_save_parser.load_config(config_path)
            h3_save_parser.save_config(config, config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(config.my_color_id)
        self.assertEqual(config.alert_radius, h3_save_parser.DEFAULT_ALERT_RADIUS)
        self.assertNotIn("my_color_id", raw_config)
        self.assertNotIn("alert_radius", raw_config)

    def test_set_config_autosave_dir_saves_and_loads_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "nested" / "config.json"
            autosave_dir = Path(temp_dir) / "game"

            updated = h3_save_parser.set_config_autosave_dir(
                autosave_dir,
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)

        self.assertEqual(updated.autosave_dir, autosave_dir)
        self.assertEqual(loaded.autosave_dir, autosave_dir)
        self.assertIsNone(loaded.last_hero)
        self.assertEqual(loaded.recent_heroes, ())
        self.assertEqual(loaded.hidden_neutral_targets_by_map, {})
        self.assertEqual(loaded.hidden_hero_targets_by_map, {})

    def test_clear_config_autosave_dir_removes_key_and_preserves_last_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra", "Marius"),
                ),
                config_path,
            )

            updated = h3_save_parser.clear_config_autosave_dir(config_path)
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.autosave_dir)
        self.assertIsNone(loaded.autosave_dir)
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.recent_heroes, ("Isra", "Marius"))
        self.assertNotIn("autosave_dir", raw_config)
        self.assertEqual(raw_config["last_hero"], "Isra")
        self.assertEqual(raw_config["recent_heroes"], ["Isra", "Marius"])

    def test_set_config_last_hero_saves_stripped_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    recent_heroes=("Marius",),
                    hidden_neutral_targets_by_map={
                        "map-key": ("neutral:1",),
                    },
                    hidden_hero_targets_by_map={
                        "map-key": ("hero:512",),
                    },
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_last_hero("  Isra  ", config_path)
            loaded = h3_save_parser.load_config(config_path)

        self.assertEqual(updated.last_hero, "Isra")
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(loaded.recent_heroes, ("Marius",))
        self.assertEqual(
            updated.hidden_neutral_targets_by_map,
            {"map-key": ("neutral:1",)},
        )
        self.assertEqual(
            updated.hidden_hero_targets_by_map,
            {"map-key": ("hero:512",)},
        )

    def test_config_hidden_neutral_targets_round_trip_and_normalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "hidden_neutral_targets_by_map": {
                        " map-key ": [
                            "neutral:10",
                            " neutral:2 ",
                            "neutral:2",
                            "hero:1",
                            "",
                            "neutral:001",
                        ],
                        "blank-after-normalize": ["hero:9", " "],
                    },
                }),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)
            h3_save_parser.save_config(config, config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config.hidden_neutral_targets_by_map,
            {"map-key": ("neutral:1", "neutral:2", "neutral:10")},
        )
        self.assertEqual(
            raw_config["hidden_neutral_targets_by_map"]["map-key"],
            ["neutral:1", "neutral:2", "neutral:10"],
        )
        self.assertNotIn(
            "blank-after-normalize",
            raw_config["hidden_neutral_targets_by_map"],
        )

    def test_set_config_hidden_neutral_target_updates_one_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra",),
                    hidden_neutral_targets_by_map={
                        "other-map": ("neutral:9",),
                    },
                ),
                config_path,
            )

            first = h3_save_parser.set_config_hidden_neutral_target(
                " map-key ",
                " neutral:002 ",
                True,
                config_path,
            )
            second = h3_save_parser.set_config_hidden_neutral_target(
                "map-key",
                "neutral:1",
                True,
                config_path,
            )
            cleared = h3_save_parser.set_config_hidden_neutral_target(
                "map-key",
                "neutral:2",
                False,
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)

        self.assertEqual(first.hidden_neutral_targets_by_map["map-key"], ("neutral:2",))
        self.assertEqual(
            second.hidden_neutral_targets_by_map["map-key"],
            ("neutral:1", "neutral:2"),
        )
        self.assertEqual(cleared.hidden_neutral_targets_by_map["map-key"], ("neutral:1",))
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.recent_heroes, ("Isra",))
        self.assertEqual(loaded.hidden_neutral_targets_by_map["other-map"], ("neutral:9",))

    def test_config_hidden_hero_targets_round_trip_and_normalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "hidden_hero_targets_by_map": {
                        " map-key ": [
                            "hero:000512",
                            " HERO:512:02 ",
                            "hero:coronius:88,28,1:9400:52",
                            "hero:coronius:88,28,1:9400:52",
                            "neutral:1",
                            "hero:/bad",
                            "",
                        ],
                        "blank-after-normalize": ["neutral:9", " "],
                    },
                }),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)
            h3_save_parser.save_config(config, config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config.hidden_hero_targets_by_map,
            {
                "map-key": (
                    "hero:512",
                    "hero:512:2",
                    "hero:coronius:88,28,1:9400:52",
                ),
            },
        )
        self.assertEqual(
            raw_config["hidden_hero_targets_by_map"]["map-key"],
            [
                "hero:512",
                "hero:512:2",
                "hero:coronius:88,28,1:9400:52",
            ],
        )
        self.assertNotIn(
            "blank-after-normalize",
            raw_config["hidden_hero_targets_by_map"],
        )

    def test_set_config_hidden_hero_target_updates_one_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra",),
                    hidden_neutral_targets_by_map={
                        "map-key": ("neutral:1",),
                    },
                    hidden_hero_targets_by_map={
                        "other-map": ("hero:9",),
                    },
                ),
                config_path,
            )

            first = h3_save_parser.set_config_hidden_hero_target(
                " map-key ",
                " HERO:002 ",
                True,
                config_path,
            )
            second = h3_save_parser.set_config_hidden_hero_target(
                "map-key",
                "hero:coronius:88,28,1:9400:52",
                True,
                config_path,
            )
            cleared = h3_save_parser.set_config_hidden_hero_target(
                "map-key",
                "hero:2",
                False,
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)

        self.assertEqual(first.hidden_hero_targets_by_map["map-key"], ("hero:2",))
        self.assertEqual(
            second.hidden_hero_targets_by_map["map-key"],
            ("hero:2", "hero:coronius:88,28,1:9400:52"),
        )
        self.assertEqual(
            cleared.hidden_hero_targets_by_map["map-key"],
            ("hero:coronius:88,28,1:9400:52",),
        )
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.recent_heroes, ("Isra",))
        self.assertEqual(loaded.hidden_neutral_targets_by_map["map-key"], ("neutral:1",))
        self.assertEqual(loaded.hidden_hero_targets_by_map["other-map"], ("hero:9",))

    def test_set_config_alert_settings_preserves_existing_config_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra", "Marius"),
                    hidden_neutral_targets_by_map={
                        "map-key": ("neutral:1",),
                    },
                    hidden_hero_targets_by_map={
                        "map-key": ("hero:512",),
                    },
                    manual_hero_current_skills_by_map={
                        "map-key": {
                            "hero:512": (
                                hero_skill_recommender.CurrentSkill(
                                    "necromancy",
                                    "basic",
                                ),
                            ),
                        },
                    },
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_alert_settings(2, 15, config_path)
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(updated.my_color_id, 2)
        self.assertEqual(updated.alert_radius, 15)
        self.assertEqual(loaded.my_color_id, 2)
        self.assertEqual(loaded.alert_radius, 15)
        self.assertEqual(raw_config["my_color_id"], 2)
        self.assertEqual(raw_config["alert_radius"], 15)
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.recent_heroes, ("Isra", "Marius"))
        self.assertEqual(
            loaded.hidden_neutral_targets_by_map["map-key"],
            ("neutral:1",),
        )
        self.assertEqual(
            loaded.hidden_hero_targets_by_map["map-key"],
            ("hero:512",),
        )
        self.assertEqual(
            loaded.manual_hero_current_skills_by_map["map-key"]["hero:512"],
            (hero_skill_recommender.CurrentSkill("necromancy", "basic"),),
        )

    def test_set_config_alert_settings_can_clear_color_and_default_radius(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    my_color_id=2,
                    alert_radius=15,
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_alert_settings(
                None,
                h3_save_parser.DEFAULT_ALERT_RADIUS,
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.my_color_id)
        self.assertEqual(updated.alert_radius, h3_save_parser.DEFAULT_ALERT_RADIUS)
        self.assertIsNone(loaded.my_color_id)
        self.assertEqual(loaded.alert_radius, h3_save_parser.DEFAULT_ALERT_RADIUS)
        self.assertNotIn("my_color_id", raw_config)
        self.assertNotIn("alert_radius", raw_config)

    def test_config_manual_hero_current_skills_round_trip_and_clean_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "manual_hero_current_skills_by_map": {
                        " Map-Key ": {
                            " HERO:000512 ": [
                                {"skill": "necromancy", "level": "Advanced"},
                                {"skill_id": "earthMagic", "level": " basic "},
                            ],
                            "bad": [
                                {"skill": "logistics", "level": "basic"},
                            ],
                            "hero:513": [
                                {"skill": "unknownSkill", "level": "basic"},
                            ],
                            "hero:514": [
                                {"skill": "logistics", "level": "wrong"},
                            ],
                            "hero:515": "not-a-list",
                            "hero:516": [
                                {"skill": "logistics", "level": "basic"},
                                {"skill": "logistics", "level": "advanced"},
                            ],
                        },
                        "blank-after-normalize": {
                            "bad": [
                                {"skill": "logistics", "level": "basic"},
                            ],
                        },
                    },
                }),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)
            h3_save_parser.save_config(config, config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config.manual_hero_current_skills_by_map,
            {
                "Map-Key": {
                    "hero:512": (
                        hero_skill_recommender.CurrentSkill(
                            "necromancy",
                            "advanced",
                        ),
                        hero_skill_recommender.CurrentSkill(
                            "earthMagic",
                            "basic",
                        ),
                    ),
                },
            },
        )
        self.assertEqual(
            raw_config["manual_hero_current_skills_by_map"],
            {
                "Map-Key": {
                    "hero:512": [
                        {"level": "advanced", "skill": "necromancy"},
                        {"level": "basic", "skill": "earthMagic"},
                    ],
                },
            },
        )

    def test_config_ignores_invalid_manual_hero_current_skill_shapes(self):
        cases = (
            {"manual_hero_current_skills_by_map": []},
            {"manual_hero_current_skills_by_map": {"map-key": []}},
            {"manual_hero_current_skills_by_map": {"map-key": {"hero:1": []}}},
            {"manual_hero_current_skills_by_map": {"map-key": {"hero:1": None}}},
        )
        for data in cases:
            with self.subTest(data=data):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "config.json"
                    config_path.write_text(json.dumps(data), encoding="utf-8")

                    config = h3_save_parser.load_config(config_path)
                    h3_save_parser.save_config(config, config_path)
                    raw_config = json.loads(
                        config_path.read_text(encoding="utf-8")
                    )

                self.assertEqual(config.manual_hero_current_skills_by_map, {})
                self.assertNotIn("manual_hero_current_skills_by_map", raw_config)

    def test_set_config_hero_skill_state_keys_by_stable_hero_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra",),
                    hidden_hero_targets_by_map={
                        "map-key": ("hero:9",),
                    },
                    manual_hero_current_skills_by_map={
                        "other-map": {
                            "hero:77": (
                                hero_skill_recommender.CurrentSkill(
                                    "logistics",
                                    "basic",
                                ),
                            ),
                        },
                    },
                ),
                config_path,
            )

            first = h3_save_parser.set_config_hero_skill_state(
                " map-key ",
                " HERO:002 ",
                "isra",
                (
                    hero_skill_recommender.CurrentSkill(
                        "necromancy",
                        "expert",
                    ),
                ),
                config_path,
            )
            second = h3_save_parser.set_config_hero_skill_state(
                "map-key",
                "hero:003",
                "isra",
                ({"skill": "earthMagic", "level": "basic"},),
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(first.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(second.last_hero, "Isra")
        self.assertEqual(loaded.recent_heroes, ("Isra",))
        self.assertEqual(loaded.hidden_hero_targets_by_map["map-key"], ("hero:9",))
        self.assertEqual(
            loaded.manual_hero_current_skills_by_map["map-key"],
            {
                "hero:2": (
                    hero_skill_recommender.CurrentSkill(
                        "necromancy",
                        "expert",
                    ),
                ),
                "hero:3": (
                    hero_skill_recommender.CurrentSkill(
                        "earthMagic",
                        "basic",
                    ),
                ),
            },
        )
        self.assertEqual(
            loaded.manual_hero_current_skills_by_map["other-map"],
            {
                "hero:77": (
                    hero_skill_recommender.CurrentSkill(
                        "logistics",
                        "basic",
                    ),
                ),
            },
        )
        self.assertIn(
            "hero:2",
            raw_config["manual_hero_current_skills_by_map"]["map-key"],
        )
        self.assertNotIn(
            "isra",
            raw_config["manual_hero_current_skills_by_map"]["map-key"],
        )

    def test_get_config_hero_skill_state_falls_back_to_vcmi_starting_skills(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing" / "config.json"

            skills = h3_save_parser.get_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                config_path=config_path,
            )

        self.assertEqual(
            skills,
            (
                hero_skill_recommender.CurrentSkill(
                    "necromancy",
                    "advanced",
                ),
            ),
        )

    def test_get_config_hero_skill_state_returns_manual_state_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.set_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                (
                    hero_skill_recommender.CurrentSkill(
                        "necromancy",
                        "expert",
                    ),
                ),
                config_path,
            )

            skills = h3_save_parser.get_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                config_path=config_path,
            )

        self.assertEqual(
            skills,
            (
                hero_skill_recommender.CurrentSkill(
                    "necromancy",
                    "expert",
                ),
            ),
        )

    def test_reset_config_hero_skill_state_removes_manual_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.set_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                (
                    hero_skill_recommender.CurrentSkill(
                        "necromancy",
                        "expert",
                    ),
                ),
                config_path,
            )

            updated = h3_save_parser.reset_config_hero_skill_state(
                "map-key",
                "hero:2",
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)
            skills = h3_save_parser.get_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                config_path=config_path,
            )
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(updated.manual_hero_current_skills_by_map, {})
        self.assertEqual(loaded.manual_hero_current_skills_by_map, {})
        self.assertEqual(
            skills,
            (
                hero_skill_recommender.CurrentSkill(
                    "necromancy",
                    "advanced",
                ),
            ),
        )
        self.assertNotIn("manual_hero_current_skills_by_map", raw_config)

    def test_set_config_hero_skill_state_empty_skills_resets_manual_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.set_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                (
                    hero_skill_recommender.CurrentSkill(
                        "necromancy",
                        "expert",
                    ),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                (),
                config_path,
            )
            skills = h3_save_parser.get_config_hero_skill_state(
                "map-key",
                "hero:2",
                "isra",
                config_path=config_path,
            )

        self.assertEqual(updated.manual_hero_current_skills_by_map, {})
        self.assertEqual(
            skills,
            (
                hero_skill_recommender.CurrentSkill(
                    "necromancy",
                    "advanced",
                ),
            ),
        )

    def test_set_config_hero_skill_state_rejects_invalid_inputs(self):
        cases = (
            (
                " ",
                "hero:2",
                "isra",
                ({"skill": "logistics", "level": "basic"},),
                "map_key",
            ),
            (
                "map",
                "bad",
                "isra",
                ({"skill": "logistics", "level": "basic"},),
                "hero_id",
            ),
            (
                "map",
                "hero:2",
                "unknown",
                ({"skill": "logistics", "level": "basic"},),
                "standard_hero_key",
            ),
            (
                "map",
                "hero:2",
                "isra",
                ({"skill": "unknownSkill", "level": "basic"},),
                "unknown skill",
            ),
        )
        for map_key, hero_id, standard_hero_key, skills, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "config.json"

                    with self.assertRaises(h3_save_parser.ConfigError) as raised:
                        h3_save_parser.set_config_hero_skill_state(
                            map_key,
                            hero_id,
                            standard_hero_key,
                            skills,
                            config_path,
                        )

                self.assertIn(expected_reason, raised.exception.reason)

    def test_set_config_last_hero_blank_clears_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    last_hero="Isra",
                    recent_heroes=("Isra",),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_last_hero("   ", config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.last_hero)
        self.assertEqual(updated.recent_heroes, ("Isra",))
        self.assertNotIn("last_hero", raw_config)
        self.assertEqual(raw_config["recent_heroes"], ["Isra"])

    def test_set_config_selected_hero_updates_last_hero_and_recent_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                    recent_heroes=("Isra", "Marius"),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_selected_hero(
                "  Aenain  ",
                config_path,
            )
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(updated, loaded)
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")
        self.assertEqual(loaded.last_hero, "Aenain")
        self.assertEqual(loaded.recent_heroes, ("Aenain", "Isra", "Marius"))
        self.assertEqual(raw_config["last_hero"], "Aenain")
        self.assertEqual(raw_config["recent_heroes"], ["Aenain", "Isra", "Marius"])

    def test_set_config_selected_hero_dedupes_case_insensitively_and_caps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    recent_heroes=(
                        "Isra",
                        "Marius",
                        "Aenain",
                        "Gunnar",
                        "Kyrre",
                        "Crag Hack",
                    ),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_selected_hero(
                "  isra  ",
                config_path,
                limit=4,
            )

        self.assertEqual(updated.last_hero, "isra")
        self.assertEqual(updated.recent_heroes, ("isra", "Marius", "Aenain", "Gunnar"))

    def test_set_config_selected_hero_uses_default_recent_hero_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    recent_heroes=(
                        "Hero 1",
                        "Hero 2",
                        "Hero 3",
                        "Hero 4",
                        "Hero 5",
                        "Hero 6",
                        "Hero 7",
                        "Hero 8",
                        "Hero 9",
                    ),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_selected_hero(
                "Selected",
                config_path,
            )

        self.assertEqual(len(updated.recent_heroes), h3_save_parser.RECENT_HERO_LIMIT)
        self.assertEqual(
            updated.recent_heroes,
            (
                "Selected",
                "Hero 1",
                "Hero 2",
                "Hero 3",
                "Hero 4",
                "Hero 5",
                "Hero 6",
                "Hero 7",
            ),
        )

    def test_set_config_selected_hero_blank_clears_last_hero_without_adding_recent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    last_hero="Isra",
                    recent_heroes=("Isra", "Marius"),
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_selected_hero("  ", config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.last_hero)
        self.assertEqual(updated.recent_heroes, ("Isra", "Marius"))
        self.assertNotIn("last_hero", raw_config)
        self.assertEqual(raw_config["recent_heroes"], ["Isra", "Marius"])

    def test_set_config_selected_hero_rejects_non_positive_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaisesRegex(ValueError, "must be positive"):
                h3_save_parser.set_config_selected_hero(
                    "Isra",
                    config_path,
                    limit=0,
                )

    def test_save_config_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "a" / "b" / "config.json"

            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(last_hero="Isra"),
                config_path,
            )

            self.assertTrue(config_path.exists())
            self.assertFalse((config_path.parent / ".config.json.tmp").exists())

    def test_load_config_reports_malformed_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{bad", encoding="utf-8")

            with self.assertRaises(h3_save_parser.ConfigError) as raised:
                h3_save_parser.load_config(config_path)

        self.assertEqual(raised.exception.path, config_path)
        self.assertIn("invalid config", raised.exception.reason)

    def test_load_config_reports_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_bytes(b"\xff")

            with self.assertRaises(h3_save_parser.ConfigError) as raised:
                h3_save_parser.load_config(config_path)

        self.assertEqual(raised.exception.path, config_path)
        self.assertIn("invalid config encoding", raised.exception.reason)

    def test_load_config_reports_non_object_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("[]", encoding="utf-8")

            with self.assertRaises(h3_save_parser.ConfigError) as raised:
                h3_save_parser.load_config(config_path)

        self.assertEqual(raised.exception.path, config_path)
        self.assertIn("root must be an object", raised.exception.reason)

    def test_load_config_reports_invalid_field_types(self):
        cases = (
            ({"autosave_dir": 123}, "must be a string"),
            ({"last_hero": []}, "must be a string"),
            ({"recent_heroes": "Isra"}, "must be a list"),
            ({"recent_heroes": ["Isra", 42]}, "recent_heroes[1] must be a string"),
            ({"my_color_id": "red"}, "my_color_id must be an integer or null"),
            ({"my_color_id": True}, "my_color_id must be an integer or null"),
            ({"my_color_id": -1}, "my_color_id must be between"),
            (
                {"my_color_id": len(h3_save_parser.PLAYER_COLOR_NAMES)},
                "my_color_id must be between",
            ),
            ({"alert_radius": "10"}, "alert_radius must be an integer"),
            ({"alert_radius": True}, "alert_radius must be an integer"),
            ({"alert_radius": -1}, "alert_radius must be between"),
            (
                {"alert_radius": h3_save_parser.MAX_ALERT_RADIUS + 1},
                "alert_radius must be between",
            ),
            (
                {"hidden_neutral_targets_by_map": []},
                "hidden_neutral_targets_by_map must be an object",
            ),
            (
                {"hidden_neutral_targets_by_map": {"map": "neutral:1"}},
                "hidden_neutral_targets_by_map['map'] must be a list",
            ),
            (
                {"hidden_neutral_targets_by_map": {"map": ["neutral:1", 2]}},
                "hidden_neutral_targets_by_map['map'][1] must be a string",
            ),
            (
                {"hidden_hero_targets_by_map": []},
                "hidden_hero_targets_by_map must be an object",
            ),
            (
                {"hidden_hero_targets_by_map": {"map": "hero:1"}},
                "hidden_hero_targets_by_map['map'] must be a list",
            ),
            (
                {"hidden_hero_targets_by_map": {"map": ["hero:1", 2]}},
                "hidden_hero_targets_by_map['map'][1] must be a string",
            ),
        )
        for data, expected_reason in cases:
            with self.subTest(data=data):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "config.json"
                    config_path.write_text(json.dumps(data), encoding="utf-8")

                    with self.assertRaises(h3_save_parser.ConfigError) as raised:
                        h3_save_parser.load_config(config_path)

                self.assertEqual(raised.exception.path, config_path)
                self.assertIn(expected_reason, raised.exception.reason)

    def test_set_config_alert_settings_rejects_invalid_values_without_writing(self):
        cases = (
            (True, 10, "my_color_id must be an integer or null"),
            ("red", 10, "my_color_id must be an integer or null"),
            (-1, 10, "my_color_id must be between"),
            (
                len(h3_save_parser.PLAYER_COLOR_NAMES),
                10,
                "my_color_id must be between",
            ),
            (0, True, "alert_radius must be an integer"),
            (0, "10", "alert_radius must be an integer"),
            (0, -1, "alert_radius must be between"),
            (
                0,
                h3_save_parser.MAX_ALERT_RADIUS + 1,
                "alert_radius must be between",
            ),
        )
        for my_color_id, alert_radius, expected_reason in cases:
            with self.subTest(my_color_id=my_color_id, alert_radius=alert_radius):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "config.json"
                    h3_save_parser.save_config(
                        h3_save_parser.BattleEstimatorConfig(last_hero="Isra"),
                        config_path,
                    )
                    before = config_path.read_bytes()

                    with self.assertRaises(h3_save_parser.ConfigError) as raised:
                        h3_save_parser.set_config_alert_settings(
                            my_color_id,
                            alert_radius,
                            config_path,
                        )

                    self.assertIn(expected_reason, raised.exception.reason)
                    self.assertEqual(config_path.read_bytes(), before)

    def test_load_config_treats_null_and_blank_values_as_unset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "autosave_dir": "  ",
                    "last_hero": None,
                    "recent_heroes": None,
                }),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)

        self.assertIsNone(config.autosave_dir)
        self.assertIsNone(config.last_hero)
        self.assertEqual(config.recent_heroes, ())

    def test_load_config_strips_recent_heroes_and_ignores_blank_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"recent_heroes": [" Isra ", " ", "Marius"]}),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)

        self.assertEqual(config.recent_heroes, ("Isra", "Marius"))

    def test_load_config_ignores_unknown_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"future": True, "last_hero": "Isra"}),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)
            h3_save_parser.save_config(config, config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(config.last_hero, "Isra")
        self.assertNotIn("future", raw_config)

    def test_config_path_is_user_global_not_repo_local(self):
        self.assertEqual(
            h3_save_parser.CONFIG_PATH,
            Path.home() / ".config" / "vcmi-battle-estimator" / "config.json",
        )
        with self.assertRaises(ValueError):
            h3_save_parser.CONFIG_PATH.relative_to(Path.cwd())

    def test_set_config_autosave_dir_rejects_blank_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with self.assertRaises(h3_save_parser.ConfigError) as raised:
                h3_save_parser.set_config_autosave_dir("  ", config_path)

        self.assertEqual(raised.exception.path, config_path)
        self.assertIn("must not be blank", raised.exception.reason)

    def test_parse_xor01_hero_at_reads_synthetic_isra_army(self):
        data, name_offset = _build_xor_hero_fixture()

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.hero_name, "Isra")
        self.assertEqual(hero.source_offset, name_offset)
        self.assertEqual([stack.count for stack in hero.stacks], list(ISRA_COUNTS))
        self.assertEqual(
            [stack.creature.name for stack in hero.stacks],
            [
                "Skeleton Warrior",
                "Zombie",
                "Vampire Lord",
                "Power Lich",
                "Dread Knight",
                "Skeleton",
                "Ghost Dragon",
            ],
        )
        self.assertIsNone(hero.position)
        self.assertIsNone(hero.x)
        self.assertIsNone(hero.y)
        self.assertIsNone(hero.z)

    def test_parse_xor01_hero_at_reads_encoded_position(self):
        data, name_offset = _build_xor_hero_fixture(position=(54, 70, 1))

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.position, h3_save_parser.HeroPosition(54, 70, 1))
        self.assertEqual(hero.x, 54)
        self.assertEqual(hero.y, 70)
        self.assertEqual(hero.z, 1)

    def test_parse_xor01_hero_at_reads_owner_color(self):
        data, name_offset = _build_xor_hero_fixture(owner_color_id=2)

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.owner_color_id, 2)
        self.assertEqual(hero.owner_color_name, "tan")

    def test_parse_xor01_hero_at_treats_unowned_color_as_missing(self):
        data, name_offset = _build_xor_hero_fixture(
            owner_color_id=h3_save_parser.HERO_OWNER_UNOWNED,
        )

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertIsNone(hero.owner_color_id)
        self.assertIsNone(hero.owner_color_name)

    def test_synthetic_hero_combat_fixture_encodes_primary_in_gm1_shape(self):
        data, name_offset = _build_hero_combat_fixture(
            primary_skills=(8, 6, 4, 5),
            xor_key=0x00,
        )

        hero = h3_save_parser.parse_hero_at(data, name_offset, key=0x00)

        self.assertEqual(
            data[:len(h3_save_parser.H3SVG_SIGNATURE)],
            h3_save_parser.H3SVG_SIGNATURE,
        )
        self.assertIsNotNone(hero)
        self.assertEqual(hero.hero_name, "Isra")
        self.assertEqual(hero.source_offset, name_offset)
        self.assertEqual(
            _decode_test_hero_combat_primary(data, name_offset, xor_key=0x00),
            (8, 6, 4, 5),
        )

    def test_synthetic_hero_combat_fixture_encodes_secondary_combat_skills(self):
        secondary_skills = (
            (HERO_COMBAT_ARCHERY_INDEX, HERO_COMBAT_LEVEL_BASIC, 1),
            (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 2),
            (HERO_COMBAT_ARMORER_INDEX, HERO_COMBAT_LEVEL_ADVANCED, 3),
        )
        data, name_offset = _build_hero_combat_fixture(
            primary_skills=(8, 6, 4, 5),
            secondary_skills=secondary_skills,
            xor_key=0x00,
        )

        levels, slots = _decode_test_hero_combat_secondary_vectors(
            data,
            name_offset,
            xor_key=0x00,
        )

        self.assertEqual(
            _decode_test_hero_combat_secondary_count(
                data,
                name_offset,
                xor_key=0x00,
            ),
            3,
        )
        self.assertEqual(levels[HERO_COMBAT_ARCHERY_INDEX], HERO_COMBAT_LEVEL_BASIC)
        self.assertEqual(levels[HERO_COMBAT_OFFENSE_INDEX], HERO_COMBAT_LEVEL_EXPERT)
        self.assertEqual(levels[HERO_COMBAT_ARMORER_INDEX], HERO_COMBAT_LEVEL_ADVANCED)
        self.assertEqual(slots[HERO_COMBAT_ARCHERY_INDEX], 1)
        self.assertEqual(slots[HERO_COMBAT_OFFENSE_INDEX], 2)
        self.assertEqual(slots[HERO_COMBAT_ARMORER_INDEX], 3)
        self.assertEqual(
            _decode_test_hero_combat_active_secondaries(
                data,
                name_offset,
                xor_key=0x00,
            ),
            secondary_skills,
        )

    def test_synthetic_hero_combat_fixtures_cover_partial_secondary_failures(self):
        cases = (
            (
                "invalid_secondary_count",
                {
                    "secondary_count": 9,
                    "secondary_skills": (
                        (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 1),
                    ),
                },
                9,
                (
                    (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 1),
                ),
            ),
            (
                "duplicate_secondary_slot",
                {
                    "secondary_count": 2,
                    "secondary_skills": (
                        (HERO_COMBAT_ARCHERY_INDEX, HERO_COMBAT_LEVEL_BASIC, 1),
                        (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 1),
                    ),
                },
                2,
                (
                    (HERO_COMBAT_ARCHERY_INDEX, HERO_COMBAT_LEVEL_BASIC, 1),
                    (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 1),
                ),
            ),
        )

        for name, fixture_kwargs, expected_count, expected_active in cases:
            with self.subTest(name=name):
                data, name_offset = _build_hero_combat_fixture(
                    primary_skills=(8, 6, 4, 5),
                    xor_key=0x00,
                    **fixture_kwargs,
                )

                self.assertEqual(
                    _decode_test_hero_combat_primary(
                        data,
                        name_offset,
                        xor_key=0x00,
                    ),
                    (8, 6, 4, 5),
                )
                self.assertEqual(
                    _decode_test_hero_combat_secondary_count(
                        data,
                        name_offset,
                        xor_key=0x00,
                    ),
                    expected_count,
                )
                self.assertEqual(
                    _decode_test_hero_combat_active_secondaries(
                        data,
                        name_offset,
                        xor_key=0x00,
                    ),
                    expected_active,
                )

    def test_synthetic_hero_combat_fixture_covers_unsupported_xor01_shape(self):
        data, name_offset = _build_hero_combat_fixture(
            primary_skills=(8, 6, 4, 5),
            secondary_skills=(
                (HERO_COMBAT_OFFENSE_INDEX, HERO_COMBAT_LEVEL_EXPERT, 1),
            ),
            xor_key=h3_save_parser.HERO_ARMY_XOR_KEY,
        )
        primary_offset = name_offset + HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET

        self.assertEqual(
            _decode_test_hero_combat_primary(
                data,
                name_offset,
                xor_key=h3_save_parser.HERO_ARMY_XOR_KEY,
            ),
            (8, 6, 4, 5),
        )
        self.assertNotEqual(
            data[primary_offset:primary_offset + 4],
            bytes((8, 6, 4, 5)),
        )

    def test_synthetic_hero_combat_fixture_covers_truncated_primary_window(self):
        data, name_offset = _build_hero_combat_fixture(
            primary_skills=(8, 6, 4, 5),
            xor_key=0x00,
        )
        truncated = data[:name_offset + HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET + 3]

        self.assertLess(
            len(truncated),
            name_offset + HERO_COMBAT_PRIMARY_FROM_NAME_OFFSET + 4,
        )
        with self.assertRaises(ValueError):
            _decode_test_hero_combat_primary(
                truncated,
                name_offset,
                xor_key=0x00,
            )

    def test_detect_current_town_ownership_uses_bounded_proxy_cases(self):
        cases = (
            {
                "name": "captured_by_visible_hero",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "Marius",
                        "position": (6, 5, 0),
                        "owner_color_id": 2,
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_PROXY,
                "expected_reason": None,
                "expected_proxy_owner_color_id": 2,
                "expected_matching_names": ("Marius",),
                "expected_heroes": (
                    ("Marius", h3_save_parser.HeroPosition(6, 5, 0), 2),
                ),
            },
            {
                "name": "no_visible_hero_on_town_tile",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": h3_save_parser.TOWN_OWNERSHIP_REASON_NO_VISIBLE_HERO,
                "expected_matching_names": (),
                "expected_heroes": (),
            },
            {
                "name": "hero_on_tile_is_unowned",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "NoOwner",
                        "position": (6, 5, 0),
                        "owner_color_id": h3_save_parser.HERO_OWNER_UNOWNED,
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": (
                    h3_save_parser.TOWN_OWNERSHIP_REASON_MISSING_HERO_OWNER_COLOR
                ),
                "expected_matching_names": ("NoOwner",),
                "expected_heroes": (
                    ("NoOwner", h3_save_parser.HeroPosition(6, 5, 0), None),
                ),
            },
            {
                "name": "hero_on_tile_has_invalid_owner",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "BadOwner",
                        "position": (6, 5, 0),
                        "owner_color_id": len(h3_save_parser.PLAYER_COLOR_NAMES),
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": (
                    h3_save_parser.TOWN_OWNERSHIP_REASON_MISSING_HERO_OWNER_COLOR
                ),
                "expected_matching_names": ("BadOwner",),
                "expected_heroes": (
                    ("BadOwner", h3_save_parser.HeroPosition(6, 5, 0), None),
                ),
            },
            {
                "name": "multiple_visible_owned_heroes_on_town_tile",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "Marius",
                        "position": (6, 5, 0),
                        "owner_color_id": 2,
                    },
                    {
                        "hero_name": "Dace",
                        "position": (6, 5, 0),
                        "owner_color_id": 2,
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": (
                    h3_save_parser.TOWN_OWNERSHIP_REASON_AMBIGUOUS_VISIBLE_HEROES
                ),
                "expected_matching_names": ("Marius", "Dace"),
                "expected_heroes": (
                    ("Marius", h3_save_parser.HeroPosition(6, 5, 0), 2),
                    ("Dace", h3_save_parser.HeroPosition(6, 5, 0), 2),
                ),
            },
            {
                "name": "same_coordinates_wrong_level",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "Underground",
                        "position": (6, 5, 1),
                        "owner_color_id": 2,
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": h3_save_parser.TOWN_OWNERSHIP_REASON_NO_VISIBLE_HERO,
                "expected_matching_names": (),
                "expected_heroes": (
                    ("Underground", h3_save_parser.HeroPosition(6, 5, 1), 2),
                ),
            },
            {
                "name": "matching_hero_has_no_position",
                "town": _synthetic_town_target(initial_owner=0),
                "hero_specs": (
                    {
                        "hero_name": "NoPos",
                        "owner_color_id": 2,
                    },
                ),
                "expected_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                "expected_reason": h3_save_parser.TOWN_OWNERSHIP_REASON_NO_VISIBLE_HERO,
                "expected_matching_names": (),
                "expected_heroes": (
                    ("NoPos", None, 2),
                ),
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                data = _build_town_proxy_fixture_heroes(case["hero_specs"])
                heroes = h3_save_parser.scan_xor01_hero_armies(data)
                town = case["town"]

                observations = h3_save_parser.detect_current_town_ownership(
                    data,
                    (town,),
                )
                infer_observations = h3_save_parser.infer_current_town_ownership(
                    (town,),
                    heroes,
                )
                result = observations[0]

                self.assertEqual(
                    [
                        (hero.hero_name, hero.position, hero.owner_color_id)
                        for hero in heroes
                    ],
                    list(case["expected_heroes"]),
                )
                self.assertEqual(observations, infer_observations)
                self.assertEqual(town.object_id, h3_map_parser.H3M_OBJECT_TOWN)
                self.assertEqual(town.initial_owner, 0)
                self.assertEqual(result.object_index, town.object_index)
                self.assertEqual(result.h3m_subid, town.h3m_subid)
                self.assertEqual(
                    result.position,
                    h3_save_parser.HeroPosition(town.x, town.y, town.z),
                )
                self.assertEqual(result.ownership_status, case["expected_status"])
                self.assertEqual(result.reason, case["expected_reason"])
                self.assertEqual(
                    result.matching_hero_names,
                    case["expected_matching_names"],
                )
                self.assertEqual(
                    result.matching_hero_count,
                    len(case["expected_matching_names"]),
                )
                if (
                    case["expected_status"]
                    == h3_save_parser.TOWN_OWNERSHIP_STATUS_PROXY
                ):
                    self.assertEqual(
                        result.ownership_source,
                        h3_save_parser.TOWN_OWNERSHIP_SOURCE_HERO_ON_TOWN_TILE_PROXY,
                    )
                    self.assertEqual(
                        result.ownership_confidence,
                        h3_save_parser.TOWN_OWNERSHIP_STATUS_PROXY,
                    )
                    self.assertEqual(
                        result.current_owner_color_id,
                        case["expected_proxy_owner_color_id"],
                    )
                    self.assertEqual(result.current_owner_color_name, "tan")
                    self.assertEqual(result.matching_hero_name, "Marius")
                    self.assertIsNotNone(result.matching_hero_source_offset)
                    self.assertNotEqual(
                        town.initial_owner,
                        result.current_owner_color_id,
                    )
                else:
                    self.assertIsNone(result.current_owner_color_id)
                    self.assertIsNone(result.current_owner_color_name)
                    self.assertIsNone(result.ownership_source)
                    self.assertEqual(
                        result.ownership_confidence,
                        h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                    )

    def test_infer_current_town_ownership_rejects_invalid_town_targets(self):
        hero = _positioned_hero_army(
            "Marius",
            [(57, 10)],
            position=(6, 5, 0),
            source_offset=256,
            owner_color_id=2,
        )
        cases = (
            (
                _synthetic_town_target(object_id=999),
                h3_save_parser.TOWN_OWNERSHIP_REASON_NOT_STANDARD_TOWN_TARGET,
            ),
            (
                _synthetic_town_target(object_index=None),
                h3_save_parser.TOWN_OWNERSHIP_REASON_MISSING_TOWN_IDENTITY,
            ),
            (
                _synthetic_town_target(include_anchor=False),
                h3_save_parser.TOWN_OWNERSHIP_REASON_MISSING_TOWN_IDENTITY,
            ),
            (
                SimpleNamespace(
                    object_index=17,
                    object_id=h3_map_parser.H3M_OBJECT_TOWN,
                    h3m_subid=3,
                    anchor_x=7,
                    anchor_y=5,
                    anchor_z=0,
                ),
                h3_save_parser.TOWN_OWNERSHIP_REASON_MISSING_TOWN_POSITION,
            ),
        )

        for town, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                observation = h3_save_parser.infer_current_town_ownership(
                    (town,),
                    (hero,),
                )[0]

                self.assertEqual(
                    observation.ownership_status,
                    h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
                )
                self.assertEqual(observation.reason, expected_reason)

    def test_parse_xor01_hero_at_keeps_army_when_position_window_is_invalid(self):
        data, name_offset = _build_xor_hero_fixture(name_offset=180)

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.hero_name, "Isra")
        self.assertEqual([stack.count for stack in hero.stacks], list(ISRA_COUNTS))
        self.assertIsNone(hero.position)

    def test_scan_xor01_hero_armies_finds_embedded_synthetic_hero(self):
        fixture, name_offset = _build_xor_hero_fixture(name_offset=300)
        data = b"prefix bytes" + fixture + b"suffix bytes"

        heroes = h3_save_parser.scan_xor01_hero_armies(data)

        self.assertEqual(len(heroes), 1)
        self.assertEqual(heroes[0].hero_name, "Isra")
        self.assertEqual(heroes[0].source_offset, name_offset + len(b"prefix bytes"))

    def test_parse_hero_at_reads_unencoded_hotseat_army(self):
        data, name_offset = _build_xor_hero_fixture(
            xor_key=0x00,
            position=(52, 54, 1),
            position_from_name_offset=(
                h3_save_parser.HOTSEAT_HERO_STRUCT_POSITION_FROM_NAME_OFFSET
            ),
        )

        hero = h3_save_parser.parse_hero_at(data, name_offset, key=0x00)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.hero_name, "Isra")
        self.assertEqual([stack.count for stack in hero.stacks], list(ISRA_COUNTS))
        self.assertEqual(hero.position, h3_save_parser.HeroPosition(52, 54, 1))

    def test_parse_hero_at_ignores_unencoded_hotseat_stale_position(self):
        data, name_offset = _build_xor_hero_fixture(
            xor_key=0x00,
            position=(44, 60, 0),
            position_from_name_offset=(
                h3_save_parser.HERO_STRUCT_POSITION_FROM_NAME_OFFSET + 6
            ),
        )

        hero = h3_save_parser.parse_hero_at(data, name_offset, key=0x00)

        self.assertIsNotNone(hero)
        self.assertEqual(hero.hero_name, "Isra")
        self.assertIsNone(hero.position)

    def test_scan_xor01_hero_armies_finds_unencoded_hotseat_hero(self):
        fixture, name_offset = _build_xor_hero_fixture(
            name_offset=300,
            xor_key=0x00,
            position=(52, 54, 1),
            position_from_name_offset=(
                h3_save_parser.HOTSEAT_HERO_STRUCT_POSITION_FROM_NAME_OFFSET
            ),
        )
        data = b"prefix bytes" + fixture + b"suffix bytes"

        heroes = h3_save_parser.scan_xor01_hero_armies(data)

        self.assertEqual(len(heroes), 1)
        self.assertEqual(heroes[0].hero_name, "Isra")
        self.assertEqual(heroes[0].source_offset, name_offset + len(b"prefix bytes"))
        self.assertEqual(heroes[0].position, h3_save_parser.HeroPosition(52, 54, 1))

    def test_scan_xor01_hero_armies_matches_brute_force_candidates(self):
        first_fixture, first_offset = _build_xor_hero_fixture(
            hero_name="Isra",
            name_offset=300,
        )
        second_fixture, second_offset = _build_xor_hero_fixture(
            hero_name="Fafner",
            name_offset=420,
        )
        false_name_candidate = _xor_encode(b"BogusHero\x00\x00\x00\x00")
        data = (
            b"\x00" * 17
            + false_name_candidate
            + b"\x00" * 23
            + first_fixture
            + b"\xff" * 31
            + second_fixture
            + b"\x00" * 29
        )

        heroes = h3_save_parser.scan_xor01_hero_armies(data)
        brute_force_heroes = _brute_force_scan_xor01_hero_armies(data)

        self.assertEqual(
            [hero.source_offset for hero in heroes],
            [hero.source_offset for hero in brute_force_heroes],
        )
        self.assertEqual(
            [hero.hero_name for hero in heroes],
            [hero.hero_name for hero in brute_force_heroes],
        )
        self.assertEqual(
            [hero.source_offset for hero in heroes],
            [
                len(b"\x00" * 17 + false_name_candidate + b"\x00" * 23) + first_offset,
                (
                    len(b"\x00" * 17 + false_name_candidate + b"\x00" * 23)
                    + len(first_fixture)
                    + len(b"\xff" * 31)
                    + second_offset
                ),
            ],
        )

    def test_parse_xor01_hero_at_reads_swapped_first_two_slots(self):
        data, name_offset = _build_xor_hero_fixture(
            creature_ids=ISRA_MOVED_CREATURE_IDS,
            counts=ISRA_MOVED_COUNTS,
        )

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(
            [(stack.count, stack.creature.name) for stack in hero.stacks],
            [
                (181, "Zombie"),
                (731, "Skeleton Warrior"),
                (59, "Vampire Lord"),
                (47, "Power Lich"),
                (19, "Dread Knight"),
                (316, "Skeleton"),
                (8, "Ghost Dragon"),
            ],
        )

    def test_parse_xor01_hero_at_ignores_empty_slots_with_invalid_ids(self):
        creature_ids = (57, 0xFFFFFFFF, 63, 65, 67, 56, 69)
        counts = (10, 0, 0, 0, 0, 0, 0)
        data, name_offset = _build_xor_hero_fixture(
            creature_ids=creature_ids,
            counts=counts,
        )

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNotNone(hero)
        self.assertEqual(len(hero.stacks), 1)
        self.assertEqual(hero.stacks[0].creature.name, "Skeleton Warrior")
        self.assertEqual(hero.stacks[0].count, 10)

    def test_parse_xor01_hero_at_rejects_invalid_non_empty_creature_id(self):
        creature_ids = (0xFFFFFFFF, 59, 63, 65, 67, 56, 69)
        data, name_offset = _build_xor_hero_fixture(creature_ids=creature_ids)

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNone(hero)

    def test_parse_xor01_hero_at_rejects_impossible_count(self):
        counts = (
            h3_save_parser.MAX_HERO_ARMY_COUNT + 1,
            181,
            59,
            47,
            19,
            316,
            8,
        )
        data, name_offset = _build_xor_hero_fixture(counts=counts)

        hero = h3_save_parser.parse_xor01_hero_at(data, name_offset)

        self.assertIsNone(hero)

    def test_parse_xor01_hero_at_rejects_invalid_hero_name(self):
        data, name_offset = _build_xor_hero_fixture()
        mutable = bytearray(data)
        mutable[name_offset] = ord("1") ^ h3_save_parser.HERO_ARMY_XOR_KEY

        hero = h3_save_parser.parse_xor01_hero_at(bytes(mutable), name_offset)

        self.assertIsNone(hero)

    def test_decode_hero_name_accepts_full_thirteen_byte_name(self):
        name_offset = 200
        data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE)
        data[name_offset:name_offset + h3_save_parser.HERO_NAME_SIZE] = _xor_encode(
            b"MaximusPrimeX"
        )

        hero_name = h3_save_parser.decode_hero_name(bytes(data), name_offset)

        self.assertEqual(hero_name, "MaximusPrimeX")

    def test_decode_hero_name_rejects_garbage_after_null_padding(self):
        name_offset = 200
        data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE)
        data[name_offset:name_offset + h3_save_parser.HERO_NAME_SIZE] = _xor_encode(
            b"Isra\x00bad-data"
        )

        hero_name = h3_save_parser.decode_hero_name(bytes(data), name_offset)

        self.assertIsNone(hero_name)

    def test_scan_xor01_hero_armies_returns_empty_for_noise(self):
        self.assertEqual(h3_save_parser.scan_xor01_hero_armies(b"\x00" * 512), ())

    def test_parse_xor01_hero_at_rejects_boundary_offsets(self):
        data, _ = _build_xor_hero_fixture(name_offset=256)

        self.assertIsNone(h3_save_parser.parse_xor01_hero_at(data, 55))
        self.assertIsNone(
            h3_save_parser.parse_xor01_hero_at(
                data[:h3_save_parser.HERO_STRUCT_NAME_OFFSET],
                h3_save_parser.HERO_STRUCT_NAME_OFFSET,
            )
        )

    def test_filter_relevant_heroes_uses_default_thresholds(self):
        low = _hero_army("Low", [(0, 1)])
        by_ai = _hero_army("ByAi", [(12, 1)])
        by_count = _hero_army("ByCount", [(0, 50)])

        relevant = h3_save_parser.filter_relevant_heroes((low, by_ai, by_count))

        self.assertEqual(relevant, (by_ai, by_count))
        self.assertEqual(by_ai.ai_value, 5019)
        self.assertEqual(by_count.total_creatures, 50)

    def test_filter_relevant_heroes_includes_exact_ai_threshold(self):
        exactly_threshold = _hero_army("Threshold", [(0, 1)])

        relevant = h3_save_parser.filter_relevant_heroes(
            (exactly_threshold,),
            min_ai_value=80,
        )

        self.assertEqual(exactly_threshold.ai_value, 80)
        self.assertEqual(relevant, (exactly_threshold,))

    def test_filter_relevant_heroes_all_heroes_bypasses_thresholds(self):
        low = _hero_army("Low", [(0, 1)])
        by_ai = _hero_army("ByAi", [(12, 1)])

        relevant = h3_save_parser.filter_relevant_heroes(
            (low, by_ai),
            all_heroes=True,
        )

        self.assertEqual(relevant, (low, by_ai))

    def test_build_other_hero_targets_excludes_selected_and_summarizes_targets(self):
        selected = _positioned_hero_army(
            "Isra",
            [(57, 10)],
            position=(39, 69, 1),
            source_offset=100,
        )
        enemy_same_level = _positioned_hero_army(
            "Marius",
            [(0, 5), (1, 2)],
            position=(47, 70, 1),
            source_offset=200,
        )
        enemy_other_level = _positioned_hero_army(
            "Underground",
            [(2, 3)],
            position=(40, 70, 0),
            source_offset=300,
        )
        no_position = _hero_army("NoPosition", [(3, 4)], source_offset=400)
        empty_army = h3_save_parser.HeroArmy(
            hero_name="Empty",
            stacks=(),
            source_offset=500,
            position=h3_save_parser.HeroPosition(41, 70, 1),
        )
        duplicate_selected_offset = _positioned_hero_army(
            "Isra Clone",
            [(57, 10)],
            position=(39, 69, 1),
            source_offset=100,
        )

        targets = h3_save_parser.build_other_hero_targets(
            (
                selected,
                enemy_same_level,
                enemy_other_level,
                no_position,
                empty_army,
                duplicate_selected_offset,
            ),
            selected,
            same_level_z=1,
        )

        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.hero_name, "Marius")
        self.assertEqual(target.position, h3_save_parser.HeroPosition(47, 70, 1))
        self.assertEqual((target.x, target.y, target.z), (47, 70, 1))
        self.assertIs(target.army, enemy_same_level)
        self.assertEqual(target.total_creatures, 7)
        self.assertEqual(target.ai_value, 630)
        self.assertEqual(target.army_summary, "5x Pikeman, 2x Halberdier")

    def test_build_other_hero_targets_can_include_other_levels(self):
        selected = _positioned_hero_army(
            "Isra",
            [(57, 10)],
            position=(39, 69, 1),
            source_offset=100,
        )
        enemy_other_level = _positioned_hero_army(
            "Underground",
            [(2, 3)],
            position=(40, 70, 0),
            source_offset=300,
        )

        targets = h3_save_parser.build_other_hero_targets(
            (selected, enemy_other_level),
            selected,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].hero_name, "Underground")
        self.assertEqual(targets[0].z, 0)

    def test_build_other_hero_targets_excludes_same_team_when_mapping_available(self):
        selected = _positioned_hero_army(
            "Isra",
            [(57, 10)],
            position=(39, 69, 1),
            source_offset=100,
            owner_color_id=0,
        )
        allied = _positioned_hero_army(
            "Kyrre",
            [(0, 5)],
            position=(40, 69, 1),
            source_offset=200,
            owner_color_id=1,
        )
        enemy = _positioned_hero_army(
            "Gem",
            [(1, 5)],
            position=(41, 69, 1),
            source_offset=300,
            owner_color_id=2,
        )

        targets = h3_save_parser.build_other_hero_targets(
            (selected, allied, enemy),
            selected,
            same_level_z=1,
            team_by_color={0: 0, 1: 0, 2: 1},
        )

        self.assertEqual([target.hero_name for target in targets], ["Gem"])

    def test_build_other_hero_targets_from_synthetic_multi_hero_save(self):
        data = _build_multi_xor_hero_fixture([
            {
                "hero_name": "Isra",
                "counts": (10, 0, 0, 0, 0, 0, 0),
                "position": (39, 69, 1),
            },
            {
                "hero_name": "Marius",
                "creature_ids": (0, 1, 63, 65, 67, 56, 69),
                "counts": (5, 2, 0, 0, 0, 0, 0),
                "position": (47, 70, 1),
                "owner_color_id": 2,
            },
            {
                "hero_name": "Dace",
                "creature_ids": (2, 59, 63, 65, 67, 56, 69),
                "counts": (3, 0, 0, 0, 0, 0, 0),
                "position": (40, 70, 0),
            },
            {
                "hero_name": "NoPos",
                "creature_ids": (3, 59, 63, 65, 67, 56, 69),
                "counts": (4, 0, 0, 0, 0, 0, 0),
            },
        ])

        heroes = h3_save_parser.scan_xor01_hero_armies(data)
        selected = h3_save_parser.select_hero(heroes, "Isra")
        targets = h3_save_parser.build_other_hero_targets(
            heroes,
            selected,
            same_level_z=selected.z,
        )

        self.assertEqual([target.hero_name for target in targets], ["Marius"])
        self.assertEqual((targets[0].x, targets[0].y, targets[0].z), (47, 70, 1))
        self.assertEqual(targets[0].total_creatures, 7)
        self.assertEqual(targets[0].army_summary, "5x Pikeman, 2x Halberdier")

    def test_select_hero_exact_match_is_case_insensitive(self):
        isra = _hero_army("Isra", [(57, 1)])
        astral = _hero_army("Astral", [(57, 1)])

        selected = h3_save_parser.select_hero((astral, isra), "isra")

        self.assertIs(selected, isra)

    def test_select_hero_exact_match_takes_precedence_over_prefix(self):
        is_hero = _hero_army("Is", [(57, 1)])
        isra = _hero_army("Isra", [(57, 1)])

        selected = h3_save_parser.select_hero((isra, is_hero), "is")

        self.assertIs(selected, is_hero)

    def test_select_hero_prefix_match_must_be_unambiguous(self):
        isra = _hero_army("Isra", [(57, 1)])
        astral = _hero_army("Astral", [(57, 1)])

        selected = h3_save_parser.select_hero((astral, isra), "Is")

        self.assertIs(selected, isra)

    def test_select_hero_missing_returns_structured_error_with_candidates(self):
        astral = _hero_army("Astral", [(57, 1)])
        isra = _hero_army("Isra", [(57, 1)])

        with self.assertRaises(h3_save_parser.HeroSelectionError) as raised:
            h3_save_parser.select_hero((astral, isra), "Crag")

        self.assertEqual(raised.exception.reason, "not_found")
        self.assertEqual(raised.exception.query, "Crag")
        self.assertEqual(raised.exception.candidates, (astral, isra))
        self.assertEqual(raised.exception.candidate_names, ("Astral", "Isra"))

    def test_select_hero_ambiguous_prefix_returns_matching_candidates(self):
        isra = _hero_army("Isra", [(57, 1)])
        israfel = _hero_army("Israfel", [(57, 1)])
        astral = _hero_army("Astral", [(57, 1)])

        with self.assertRaises(h3_save_parser.HeroSelectionError) as raised:
            h3_save_parser.select_hero((isra, astral, israfel), "Is")

        self.assertEqual(raised.exception.reason, "ambiguous_prefix")
        self.assertEqual(raised.exception.candidates, (isra, israfel))
        self.assertEqual(raised.exception.candidate_names, ("Isra", "Israfel"))

    def test_select_hero_duplicate_exact_name_is_ambiguous(self):
        isra_one = _hero_army("Isra", [(57, 1)], source_offset=100)
        isra_two = _hero_army("isra", [(57, 2)], source_offset=200)

        with self.assertRaises(h3_save_parser.HeroSelectionError) as raised:
            h3_save_parser.select_hero((isra_one, isra_two), "Isra")

        self.assertEqual(raised.exception.reason, "ambiguous_exact")
        self.assertEqual(raised.exception.candidates, (isra_one, isra_two))

    def test_select_hero_blank_query_is_structured_error(self):
        isra = _hero_army("Isra", [(57, 1)])

        with self.assertRaises(h3_save_parser.HeroSelectionError) as raised:
            h3_save_parser.select_hero((isra,), "   ")

        self.assertEqual(raised.exception.reason, "missing_query")
        self.assertEqual(raised.exception.candidates, (isra,))


if __name__ == "__main__":
    unittest.main()
