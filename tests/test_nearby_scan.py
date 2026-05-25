import unittest
from unittest.mock import patch

from tools import battle_estimator
from tools import h3_map_parser
from tools import h3_save_parser
from tools import hero_skill_recommender


_DEFAULT_ESTIMATOR_CREATURE_ID = object()


def _hero_army(
    hero_name,
    position=None,
    source_offset=0,
    stack_specs=((0, 1),),
    combat_context=None,
):
    return h3_save_parser.HeroArmy(
        hero_name=hero_name,
        stacks=tuple(
            h3_save_parser.HeroStack.from_creature_id(creature_id, count)
            for creature_id, count in stack_specs
        ),
        source_offset=source_offset,
        position=(
            None
            if position is None
            else h3_save_parser.HeroPosition(*position)
        ),
        combat_context=(
            h3_save_parser.HeroCombatContext()
            if combat_context is None
            else combat_context
        ),
    )


def _hero_target(
    hero_name,
    position,
    source_offset,
    stack_specs=((0, 1),),
    combat_context=None,
):
    army = _hero_army(
        hero_name,
        position,
        source_offset,
        stack_specs,
        combat_context=combat_context,
    )
    return h3_save_parser.HeroTarget(
        hero_name=hero_name,
        position=army.position,
        army=army,
    )


def _combat_context(
    primary=(0, 0, 0, 0),
    secondary_skills=(),
    status=h3_save_parser.HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY,
):
    return h3_save_parser.HeroCombatContext(
        status=status,
        source=h3_save_parser.HERO_COMBAT_SOURCE_SAVE,
        primary_skills=h3_save_parser.HeroPrimarySkills(*primary),
        secondary_skills=tuple(
            hero_skill_recommender.CurrentSkill(skill_id, level)
            for skill_id, level in secondary_skills
        ),
        reason=None
        if status == h3_save_parser.HERO_COMBAT_STATUS_PRIMARY_AND_SECONDARY
        else "test_partial",
    )


def _neutral_target(
    object_index,
    position,
    h3m_subid=98,
    count=1,
    creature_name="Gnoll",
    estimator_creature_id=_DEFAULT_ESTIMATOR_CREATURE_ID,
):
    if estimator_creature_id is _DEFAULT_ESTIMATOR_CREATURE_ID:
        estimator_creature_id = h3m_subid

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
        estimator_creature_id=estimator_creature_id,
    )


class NearbyScanServiceTests(unittest.TestCase):
    def test_calc_damage_applies_primary_and_passive_modifiers_once(self):
        attacker = battle_estimator.Stack(
            battle_estimator.Creature(
                "Attacker",
                "Test",
                1,
                18,
                1,
                2,
                2,
                10,
                5,
                1,
            ),
            1,
            side=0,
        )
        defender = battle_estimator.Stack(
            battle_estimator.Creature(
                "Defender",
                "Test",
                1,
                1,
                10,
                1,
                1,
                10,
                5,
                1,
            ),
            1,
            side=1,
        )

        damage = battle_estimator.calc_damage(
            attacker,
            defender,
            attacker_modifiers=battle_estimator.CombatSideModifiers(
                offence_melee_pct=30,
            ),
            defender_modifiers=battle_estimator.CombatSideModifiers(
                armorer_all_pct=15,
            ),
        )

        self.assertEqual(damage, 3)

    def test_calc_damage_applies_primary_attack_and_defense(self):
        attacker = battle_estimator.Stack(
            battle_estimator.Creature(
                "Attacker",
                "Test",
                1,
                10,
                1,
                10,
                10,
                10,
                5,
                1,
            ),
            1,
            side=0,
        )
        defender = battle_estimator.Stack(
            battle_estimator.Creature(
                "Defender",
                "Test",
                1,
                1,
                10,
                1,
                1,
                10,
                5,
                1,
            ),
            1,
            side=1,
        )

        boosted_attack = battle_estimator.calc_damage(
            attacker,
            defender,
            attacker_modifiers=battle_estimator.CombatSideModifiers(attack=4),
        )
        boosted_defense = battle_estimator.calc_damage(
            attacker,
            defender,
            defender_modifiers=battle_estimator.CombatSideModifiers(defense=4),
        )

        self.assertEqual(boosted_attack, 12)
        self.assertEqual(boosted_defense, 9)

    def test_calc_damage_applies_archery_only_to_ranged_attacks(self):
        shooter = battle_estimator.Stack(
            battle_estimator.Creature(
                "Shooter",
                "Test",
                1,
                10,
                1,
                10,
                10,
                10,
                5,
                1,
                shots=12,
            ),
            1,
            side=0,
        )
        defender = battle_estimator.Stack(
            battle_estimator.Creature(
                "Defender",
                "Test",
                1,
                1,
                10,
                1,
                1,
                10,
                5,
                1,
            ),
            1,
            side=1,
        )
        modifiers = battle_estimator.CombatSideModifiers(
            archery_ranged_pct=50,
            offence_melee_pct=30,
        )

        ranged_damage = battle_estimator.calc_damage(
            shooter,
            defender,
            shooting=True,
            attacker_modifiers=modifiers,
        )
        melee_damage = battle_estimator.calc_damage(
            shooter,
            defender,
            shooting=False,
            attacker_modifiers=modifiers,
        )

        self.assertEqual(ranged_damage, 15)
        self.assertEqual(melee_damage, 6)

    def test_combat_modifiers_from_save_context_use_primary_and_passives(self):
        context = _combat_context(
            primary=(8, 6, 4, 5),
            secondary_skills=(
                ("offence", "expert"),
                ("armorer", "advanced"),
                ("archery", "basic"),
            ),
        )

        modifiers = battle_estimator._combat_modifiers_from_context(context)

        self.assertEqual(
            modifiers,
            battle_estimator.CombatSideModifiers(
                attack=8,
                defense=6,
                offence_melee_pct=30,
                armorer_all_pct=10,
                archery_ranged_pct=10,
            ),
        )

    def test_combat_modifiers_ignore_unavailable_contexts(self):
        modifiers = battle_estimator._combat_modifiers_from_context(
            h3_save_parser.HeroCombatContext(),
        )

        self.assertEqual(modifiers, battle_estimator.CombatSideModifiers())

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

    def test_estimate_nearby_scan_targets_estimates_neutral_and_hero_targets(self):
        selected = _hero_army("Isra", (39, 69, 1))
        neutral = _neutral_target(2393, (39, 70, 1), 98, 37, "Gnoll")
        hero = _hero_target("Marius", (39, 71, 1), 102, stack_specs=((1, 3),))
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            hero_targets=(hero,),
            radius=10,
        )

        with patch.object(
            battle_estimator,
            "run_simulations",
            side_effect=(91.5, 72.0),
        ) as run_mock:
            estimates = battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
                simulations=123,
            )

        self.assertEqual([estimate.win_pct for estimate in estimates], [91.5, 72.0])
        self.assertEqual(estimates[0].target_type, "neutral")
        self.assertEqual(estimates[0].enemy_army, (
            (battle_estimator.CREATURES[98], 37),
        ))
        self.assertEqual(
            estimates[0].enemy_ai_value,
            battle_estimator.CREATURES[98].ai_value * 37,
        )
        self.assertEqual(estimates[0].note, "")
        self.assertEqual(estimates[1].target_type, "hero")
        self.assertEqual(estimates[1].note, "army-only")
        self.assertEqual(estimates[1].enemy_army, (
            (battle_estimator.CREATURES[1], 3),
        ))
        self.assertEqual(run_mock.call_count, 2)
        self.assertTrue(all(call.args[2] == 123 for call in run_mock.call_args_list))
        self.assertEqual(run_mock.call_args_list[1].args[1], [
            (battle_estimator.CREATURES[1], 3),
        ])
        self.assertTrue(all(
            call.kwargs == {"verbose_first": False}
            for call in run_mock.call_args_list
        ))

    def test_estimate_nearby_scan_targets_passes_player_context_for_neutrals(self):
        selected_context = _combat_context(primary=(8, 6, 4, 5))
        selected = _hero_army("Isra", (39, 69, 1), combat_context=selected_context)
        neutral = _neutral_target(2393, (39, 70, 1), 98, 37, "Gnoll")
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            radius=10,
            target_type="neutral",
        )

        with patch.object(
            battle_estimator,
            "run_simulations",
            return_value=80.0,
        ) as run_mock:
            battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
                simulations=123,
            )

        self.assertIs(run_mock.call_args.kwargs["player_combat_context"], selected_context)
        self.assertNotIn("enemy_combat_context", run_mock.call_args.kwargs)

    def test_estimate_nearby_scan_targets_passes_both_contexts_for_heroes(self):
        selected_context = _combat_context(primary=(8, 6, 4, 5))
        enemy_context = _combat_context(primary=(3, 9, 1, 1))
        selected = _hero_army("Isra", (39, 69, 1), combat_context=selected_context)
        hero = _hero_target(
            "Marius",
            (39, 71, 1),
            102,
            stack_specs=((1, 3),),
            combat_context=enemy_context,
        )
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            hero_targets=(hero,),
            radius=10,
            target_type="hero",
        )

        with patch.object(
            battle_estimator,
            "run_simulations",
            return_value=72.0,
        ) as run_mock:
            battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
                simulations=123,
            )

        self.assertIs(run_mock.call_args.kwargs["player_combat_context"], selected_context)
        self.assertIs(run_mock.call_args.kwargs["enemy_combat_context"], enemy_context)

    def test_estimate_nearby_scan_targets_uses_default_scan_simulations(self):
        selected = _hero_army("Isra", (39, 69, 1))
        neutral = _neutral_target(2393, (39, 70, 1), 98, 37, "Gnoll")
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(neutral,),
            radius=10,
            target_type="neutral",
        )

        with patch.object(
            battle_estimator,
            "run_simulations",
            return_value=80.0,
        ) as run_mock:
            estimates = battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
            )

        self.assertEqual(estimates[0].win_pct, 80.0)
        self.assertEqual(
            run_mock.call_args.args[2],
            battle_estimator.DEFAULT_SCAN_SIMULATIONS,
        )

    def test_estimate_nearby_scan_targets_marks_unsupported_neutrals(self):
        selected = _hero_army("Isra", (39, 69, 1))
        unknown = _neutral_target(
            2401,
            (39, 70, 1),
            104,
            20,
            creature_name=None,
            estimator_creature_id=None,
        )
        out_of_range = _neutral_target(
            2402,
            (40, 70, 1),
            104,
            20,
            creature_name="Bad Mapping",
            estimator_creature_id=len(battle_estimator.CREATURES),
        )
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(unknown, out_of_range),
            radius=10,
            target_type="neutral",
        )

        with patch.object(battle_estimator, "run_simulations") as run_mock:
            estimates = battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
            )

        run_mock.assert_not_called()
        self.assertEqual([estimate.win_pct for estimate in estimates], [None, None])
        self.assertTrue(all(estimate.enemy_army == () for estimate in estimates))
        self.assertTrue(all(estimate.enemy_ai_value == 0 for estimate in estimates))
        self.assertTrue(all(
            estimate.note.startswith("unsupported neutral creature:")
            for estimate in estimates
        ))

    def test_estimate_nearby_scan_targets_keeps_going_after_target_error(self):
        selected = _hero_army("Isra", (39, 69, 1))
        bad_target = _neutral_target(2393, (39, 70, 1), 98, 37, "Gnoll")
        good_target = _neutral_target(2330, (40, 73, 1), 29, 32, "Master Gremlin")
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected,
            neutral_targets=(bad_target, good_target),
            radius=10,
            target_type="neutral",
        )

        def fake_run_simulations(player_army, enemy_army, simulations, verbose_first=False):
            if enemy_army[0][1] == 37:
                raise RuntimeError("boom")
            return 64.0

        with patch.object(
            battle_estimator,
            "run_simulations",
            side_effect=fake_run_simulations,
        ):
            estimates = battle_estimator.estimate_nearby_scan_targets(
                selected,
                scan_targets,
                simulations=123,
            )

        self.assertIsNone(estimates[0].win_pct)
        self.assertEqual(estimates[0].note, "estimation failed: boom")
        self.assertEqual(estimates[1].win_pct, 64.0)
        self.assertEqual(estimates[1].note, "")
        self.assertTrue(all(
            estimate.win_pct is not None or estimate.note
            for estimate in estimates
        ))

    def test_estimate_nearby_scan_targets_validates_global_inputs(self):
        selected = _hero_army("Isra", (39, 69, 1))
        empty_selected = h3_save_parser.HeroArmy(
            hero_name="Isra",
            stacks=(),
            position=h3_save_parser.HeroPosition(39, 69, 1),
        )

        with self.assertRaisesRegex(
            battle_estimator.NearbyScanError,
            "positive",
        ):
            battle_estimator.estimate_nearby_scan_targets(
                selected,
                (),
                simulations=0,
            )
        with self.assertRaisesRegex(
            battle_estimator.NearbyScanError,
            "army stacks",
        ):
            battle_estimator.estimate_nearby_scan_targets(empty_selected, ())

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
