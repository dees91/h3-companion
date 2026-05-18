import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import battle_estimator
from tools import h3_save_parser


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


if __name__ == "__main__":
    unittest.main()
