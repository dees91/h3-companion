import unittest

from tools import battle_estimator
from tools import h3_map_parser
from tools import h3_save_parser


def _hero_army(hero_name, position=None, source_offset=0):
    return h3_save_parser.HeroArmy(
        hero_name=hero_name,
        stacks=(h3_save_parser.HeroStack.from_creature_id(0, 1),),
        source_offset=source_offset,
        position=(
            None
            if position is None
            else h3_save_parser.HeroPosition(*position)
        ),
    )


def _hero_target(hero_name, position, source_offset):
    army = _hero_army(hero_name, position, source_offset)
    return h3_save_parser.HeroTarget(
        hero_name=hero_name,
        position=army.position,
        army=army,
    )


def _neutral_target(
    object_index,
    position,
    h3m_subid=98,
    count=1,
    creature_name="Gnoll",
):
    template = h3_map_parser.H3ObjectTemplate(
        template_index=object_index,
        animation_file=f"AVW{object_index}.def",
        block_mask=b"\x00" * 6,
        visit_mask=b"\x01" * 6,
        terrain_mask=0x01FF,
        object_id=h3_map_parser.H3M_OBJECT_MONSTER,
        subid=h3m_subid,
        object_type=2,
        print_priority=4,
    )
    return h3_map_parser.H3NeutralMonsterTarget(
        object_index=object_index,
        x=position[0],
        y=position[1],
        z=position[2],
        template=template,
        h3m_subid=h3m_subid,
        count=count,
        creature_name=creature_name,
        estimator_creature_id=h3m_subid,
    )


class NearbyScanServiceTests(unittest.TestCase):
    def test_build_nearby_scan_targets_filters_level_radius_and_sorts(self):
        selected = _hero_army("Isra", (39, 69, 1))
        neutral_distance_two = _neutral_target(2401, (41, 69, 1))
        neutral_far = _neutral_target(2402, (50, 69, 1))
        neutral_other_level = _neutral_target(2403, (39, 70, 0))
        hero_distance_one = _hero_target("Aenain", (40, 69, 1), 101)
        hero_distance_two = _hero_target("Marius", (39, 71, 1), 102)
        hero_other_level = _hero_target("Underground", (40, 69, 0), 103)

        results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(
                neutral_far,
                neutral_other_level,
                neutral_distance_two,
            ),
            hero_targets=(
                hero_distance_two,
                hero_other_level,
                hero_distance_one,
            ),
            radius=2,
        )

        self.assertEqual(
            [(result.target_type, result.distance, result.position) for result in results],
            [
                ("hero", 1, (40, 69, 1)),
                ("neutral", 2, (41, 69, 1)),
                ("hero", 2, (39, 71, 1)),
            ],
        )
        self.assertIs(results[1].target, neutral_distance_two)
        self.assertIs(results[2].target, hero_distance_two)

    def test_build_nearby_scan_targets_applies_target_type_filter(self):
        selected = _hero_army("Isra", (39, 69, 1))
        neutral = _neutral_target(2401, (39, 70, 1))
        hero = _hero_target("Marius", (39, 71, 1), 102)

        neutral_results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            hero_targets=(hero,),
            radius=10,
            target_type="neutral",
        )
        hero_results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            hero_targets=(hero,),
            radius=10,
            target_type="hero",
        )
        all_results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            hero_targets=(hero,),
            radius=10,
            target_type="all",
        )

        self.assertEqual([result.target_type for result in neutral_results], ["neutral"])
        self.assertEqual([result.target_type for result in hero_results], ["hero"])
        self.assertEqual(
            [result.target_type for result in all_results],
            ["neutral", "hero"],
        )

    def test_build_nearby_scan_targets_uses_stable_tie_breakers(self):
        selected = _hero_army("Isra", (10, 10, 1))
        neutral_low_y = _neutral_target(200, (10, 8, 1))
        neutral_low_index = _neutral_target(100, (12, 10, 1))
        neutral_high_index = _neutral_target(300, (12, 10, 1))
        hero_a = _hero_target("Aenain", (12, 10, 1), 102)
        hero_m = _hero_target("Marius", (12, 10, 1), 101)

        results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(
                neutral_high_index,
                neutral_low_index,
                neutral_low_y,
            ),
            hero_targets=(hero_m, hero_a),
            radius=2,
        )

        self.assertEqual(
            [
                (result.target_type, result.y, result.x, result.target)
                for result in results
            ],
            [
                ("neutral", 8, 10, neutral_low_y),
                ("neutral", 10, 12, neutral_low_index),
                ("neutral", 10, 12, neutral_high_index),
                ("hero", 10, 12, hero_a),
                ("hero", 10, 12, hero_m),
            ],
        )

    def test_build_nearby_scan_targets_filters_and_marks_removed_neutrals(self):
        selected = _hero_army("Isra", (39, 69, 1))
        gnoll = _neutral_target(2393, (39, 70, 1), 98, 37, "Gnoll")
        gremlin = _neutral_target(2331, (39, 75, 1), 28, 47, "Gremlin")
        master_gremlin = _neutral_target(
            2330,
            (40, 73, 1),
            29,
            32,
            "Master Gremlin",
        )
        kept = _neutral_target(2400, (41, 75, 1), 30, 11, "Stone Gargoyle")
        records = (
            h3_save_parser.RemovedNeutralRecord(2393, 98, 946676, 0x8000),
            h3_save_parser.RemovedNeutralRecord(2331, 28, 947037, 0xA000),
            h3_save_parser.RemovedNeutralRecord(2330, 29, 947054, 0x5000),
        )

        default_results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(gnoll, gremlin, master_gremlin, kept),
            removed_records=records,
            radius=10,
            target_type="neutral",
        )
        debug_results = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(gnoll, gremlin, master_gremlin, kept),
            removed_records=records,
            radius=10,
            target_type="neutral",
            include_removed=True,
        )

        self.assertEqual(
            [result.target.object_index for result in default_results],
            [2400],
        )
        removed_debug_targets = [
            result.target
            for result in debug_results
            if result.target.object_index in (2393, 2331, 2330)
        ]
        self.assertEqual(len(removed_debug_targets), 3)
        self.assertTrue(all(target.removed for target in removed_debug_targets))
        self.assertIn("removed-save-record@946676", {
            target.removal_note for target in removed_debug_targets
        })

    def test_build_nearby_scan_targets_validates_inputs(self):
        selected_without_position = _hero_army("Isra")
        selected = _hero_army("Isra", (39, 69, 1))

        with self.assertRaisesRegex(
            battle_estimator.NearbyScanError,
            "position",
        ):
            battle_estimator.build_nearby_scan_targets(selected_without_position)
        with self.assertRaisesRegex(
            battle_estimator.NearbyScanError,
            "non-negative",
        ):
            battle_estimator.build_nearby_scan_targets(selected, radius=-1)
        with self.assertRaisesRegex(
            battle_estimator.NearbyScanError,
            "target_type",
        ):
            battle_estimator.build_nearby_scan_targets(
                selected,
                target_type="town",
            )


if __name__ == "__main__":
    unittest.main()
