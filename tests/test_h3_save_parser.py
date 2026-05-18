import importlib
import gzip
import json
import os
import tempfile
import unittest
import zlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools import battle_estimator
from tools import h3_save_parser


ISRA_CREATURE_IDS = (57, 59, 63, 65, 67, 56, 69)
ISRA_MOVED_CREATURE_IDS = (59, 57, 63, 65, 67, 56, 69)
ISRA_COUNTS = (731, 181, 59, 47, 19, 316, 8)
ISRA_MOVED_COUNTS = (181, 731, 59, 47, 19, 316, 8)


def _xor_encode(raw: bytes) -> bytes:
    return bytes(byte ^ h3_save_parser.HERO_ARMY_XOR_KEY for byte in raw)


def _build_xor_hero_fixture(
    hero_name="Isra",
    creature_ids=ISRA_CREATURE_IDS,
    counts=ISRA_COUNTS,
    name_offset=256,
):
    data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE + 32)
    ids_offset = name_offset + h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET
    counts_offset = name_offset + h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET

    for slot, creature_id in enumerate(creature_ids):
        encoded = _xor_encode(int(creature_id).to_bytes(4, "little"))
        offset = ids_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded
    for slot, count in enumerate(counts):
        encoded = _xor_encode(int(count).to_bytes(4, "little"))
        offset = counts_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded

    name_bytes = hero_name.encode("ascii")
    if len(name_bytes) > h3_save_parser.HERO_NAME_SIZE:
        raise ValueError("test hero name is too long")
    padded_name = name_bytes.ljust(h3_save_parser.HERO_NAME_SIZE, b"\x00")
    data[name_offset:name_offset + h3_save_parser.HERO_NAME_SIZE] = _xor_encode(
        padded_name
    )
    return bytes(data), name_offset


class H3SaveParserContractTests(unittest.TestCase):
    def test_constants_use_home_derived_paths(self):
        home = Path.home()

        self.assertEqual(
            h3_save_parser.DEFAULT_AUTOSAVE_ROOT,
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
            / "Random"
            / "PlayerTwo",
        )
        self.assertEqual(
            h3_save_parser.CONFIG_PATH,
            home / ".config" / "vcmi-battle-estimator" / "config.json",
        )
        self.assertEqual(h3_save_parser.SAVE_EXTENSIONS, (".GM1", ".GM2"))

    def test_named_hero_offsets_are_derived_from_struct_offsets(self):
        self.assertEqual(h3_save_parser.HERO_ARMY_SLOT_COUNT, 7)
        self.assertEqual(h3_save_parser.HERO_ARMY_VALUE_SIZE, 4)
        self.assertEqual(h3_save_parser.HERO_NAME_SIZE, 13)
        self.assertEqual(h3_save_parser.HERO_STRUCT_ARMY_TYPES_OFFSET, 113)
        self.assertEqual(h3_save_parser.HERO_STRUCT_ARMY_COUNTS_OFFSET, 141)
        self.assertEqual(h3_save_parser.HERO_STRUCT_NAME_OFFSET, 169)
        self.assertEqual(h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET, -56)
        self.assertEqual(h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET, -28)

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

    def test_select_game_dir_picks_newest_dated_child(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "2026.04.26 20;45 Diamond"
            newest = root / "2026.05.01 09;15 Crystal"
            ignored = root / "Manual Saves"
            malformed = root / "2026.99.99 20;45 Bad"
            for folder in (older, newest, ignored, malformed):
                folder.mkdir()

            selected = h3_save_parser.select_game_dir(autosave_root=root)

        self.assertEqual(selected, newest)

    def test_parse_numeric_save_name(self):
        self.assertEqual(h3_save_parser.parse_numeric_save_name("415.GM1"), (415, 1))
        self.assertEqual(h3_save_parser.parse_numeric_save_name("415.gm2"), (415, 2))
        self.assertIsNone(h3_save_parser.parse_numeric_save_name("415_moved.GM1"))
        self.assertIsNone(h3_save_parser.parse_numeric_save_name("BATTLE.GM2"))

    def test_select_latest_save_ignores_non_numeric_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            (game_dir / "1.GM1").write_bytes(b"")
            (game_dir / "415.GM1").write_bytes(b"")
            expected = game_dir / "416.gm1"
            expected.write_bytes(b"")
            for ignored_name in (
                "GAME_BEGIN.GM2",
                "BATTLE.GM2",
                "AUTOSAVE.GM2",
                "415_moved.GM1",
                "notes.txt",
            ):
                (game_dir / ignored_name).write_bytes(b"")
            (game_dir / "999.GM2").mkdir()

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
            self.assertFalse(config_path.exists())

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

    def test_clear_config_autosave_dir_removes_key_and_preserves_last_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                    last_hero="Isra",
                ),
                config_path,
            )

            updated = h3_save_parser.clear_config_autosave_dir(config_path)
            loaded = h3_save_parser.load_config(config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.autosave_dir)
        self.assertIsNone(loaded.autosave_dir)
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertNotIn("autosave_dir", raw_config)
        self.assertEqual(raw_config["last_hero"], "Isra")

    def test_set_config_last_hero_saves_stripped_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(
                    autosave_dir=Path(temp_dir) / "game",
                ),
                config_path,
            )

            updated = h3_save_parser.set_config_last_hero("  Isra  ", config_path)
            loaded = h3_save_parser.load_config(config_path)

        self.assertEqual(updated.last_hero, "Isra")
        self.assertEqual(loaded.last_hero, "Isra")
        self.assertEqual(loaded.autosave_dir, Path(temp_dir) / "game")

    def test_set_config_last_hero_blank_clears_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            h3_save_parser.save_config(
                h3_save_parser.BattleEstimatorConfig(last_hero="Isra"),
                config_path,
            )

            updated = h3_save_parser.set_config_last_hero("   ", config_path)
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertIsNone(updated.last_hero)
        self.assertNotIn("last_hero", raw_config)

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
            {"autosave_dir": 123},
            {"last_hero": []},
        )
        for data in cases:
            with self.subTest(data=data):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "config.json"
                    config_path.write_text(json.dumps(data), encoding="utf-8")

                    with self.assertRaises(h3_save_parser.ConfigError) as raised:
                        h3_save_parser.load_config(config_path)

                self.assertEqual(raised.exception.path, config_path)
                self.assertIn("must be a string", raised.exception.reason)

    def test_load_config_treats_null_and_blank_values_as_unset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"autosave_dir": "  ", "last_hero": None}),
                encoding="utf-8",
            )

            config = h3_save_parser.load_config(config_path)

        self.assertIsNone(config.autosave_dir)
        self.assertIsNone(config.last_hero)

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

    def test_scan_xor01_hero_armies_finds_embedded_synthetic_hero(self):
        fixture, name_offset = _build_xor_hero_fixture(name_offset=300)
        data = b"prefix bytes" + fixture + b"suffix bytes"

        heroes = h3_save_parser.scan_xor01_hero_armies(data)

        self.assertEqual(len(heroes), 1)
        self.assertEqual(heroes[0].hero_name, "Isra")
        self.assertEqual(heroes[0].source_offset, name_offset + len(b"prefix bytes"))

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


if __name__ == "__main__":
    unittest.main()
