from __future__ import annotations

import math
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

from tools import hero_skill_recommender as recommender


class HeroSkillRecommenderContractTests(unittest.TestCase):
    def test_current_skill_normalizes_level_and_trims_skill_id(self):
        skill = recommender.CurrentSkill(" earthMagic ", " Basic ")

        self.assertEqual(skill.skill_id, "earthMagic")
        self.assertEqual(skill.skill, "earthMagic")
        self.assertEqual(skill.level, "basic")

    def test_invalid_skill_levels_are_rejected(self):
        for value in ("novice", "", None):
            with self.subTest(value=value):
                with self.assertRaises(recommender.HeroSkillRecommendationError):
                    recommender.normalize_skill_level(value)

    def test_current_skills_reject_duplicate_skill_ids(self):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.validate_current_skills((
                recommender.CurrentSkill("earthMagic", "basic"),
                {"skill": "earthMagic", "level": "advanced"},
            ))

    def test_current_skills_allow_eight_distinct_skills(self):
        skills = recommender.validate_current_skills(
            {"skill": f"skill{i}", "level": "basic"} for i in range(8)
        )

        self.assertEqual(len(skills), recommender.MAX_SECONDARY_SKILLS)

    def test_current_skills_reject_more_than_eight_distinct_skills(self):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.validate_current_skills(
                {"skill": f"skill{i}", "level": "basic"} for i in range(9)
            )

    def test_skill_offer_contract_requires_skill_and_target_level(self):
        comparison = recommender.OfferComparisonInput(
            hero_key="isra",
            current_skills=(),
            offers=(
                {"skill": "necromancy", "level": "expert"},
                {"skill_id": "earthMagic", "target_level": "basic"},
            ),
        )

        self.assertEqual(comparison.offers[0].skill_id, "necromancy")
        self.assertEqual(comparison.offers[0].target_level, "expert")
        self.assertEqual(comparison.offers[0].key, "necromancy:expert")
        self.assertEqual(comparison.offers[1].skill_id, "earthMagic")
        self.assertEqual(comparison.offers[1].target_level, "basic")

    def test_skill_offer_rejects_missing_target_level(self):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.OfferComparisonInput(
                hero_key="isra",
                current_skills=(),
                offers=(
                    {"skill": "necromancy", "target_level": "expert"},
                    {"skill": "earthMagic"},
                ),
            )

    def test_offer_comparison_requires_two_or_more_offers(self):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.OfferComparisonInput(
                hero_key="isra",
                current_skills=(),
                offers=({"skill": "necromancy", "level": "expert"},),
            )

    def test_recommendation_entry_normalizes_required_fields(self):
        entry = recommender.RecommendationEntry(
            skill_id=" necromancy ",
            score=98,
            tier="s",
            availability=" AVAILABLE ",
            reason_codes=("hero_specialty", "snowball"),
            display_name=" Necromancy ",
            target_level=" Expert ",
        )

        self.assertEqual(entry.skill_id, "necromancy")
        self.assertEqual(entry.score, 98.0)
        self.assertEqual(entry.tier, "S")
        self.assertEqual(entry.availability, recommender.AVAILABILITY_AVAILABLE)
        self.assertEqual(entry.reason_codes, ("hero_specialty", "snowball"))
        self.assertEqual(entry.display_name, "Necromancy")
        self.assertEqual(entry.target_level, "expert")

    def test_recommendation_entry_rejects_invalid_score(self):
        invalid_scores = (True, -1, 101, math.inf)

        for score in invalid_scores:
            with self.subTest(score=score):
                with self.assertRaises(recommender.HeroSkillRecommendationError):
                    recommender.RecommendationEntry(
                        skill_id="necromancy",
                        score=score,
                        tier="S",
                        availability=recommender.AVAILABILITY_AVAILABLE,
                        reason_codes=("hero_specialty",),
                    )

    def test_recommendation_entry_rejects_invalid_tier_availability_and_reasons(self):
        base = {
            "skill_id": "necromancy",
            "score": 90,
            "tier": "S",
            "availability": recommender.AVAILABILITY_AVAILABLE,
            "reason_codes": ("hero_specialty",),
        }
        invalid_cases = (
            {"tier": "SS"},
            {"availability": "maybe"},
            {"reason_codes": ("HeroSpecialty",)},
            {"reason_codes": ("mass slow",)},
            {"reason_codes": ("hero_specialty", "hero_specialty")},
        )

        for overrides in invalid_cases:
            data = dict(base)
            data.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(recommender.HeroSkillRecommendationError):
                    recommender.RecommendationEntry(**data)

    def test_recommendation_output_normalizes_nested_contracts(self):
        top_entry = recommender.RecommendationEntry(
            skill_id="necromancy",
            score=98,
            tier="S",
            availability=recommender.AVAILABILITY_AVAILABLE,
            reason_codes=("hero_specialty",),
            target_level="expert",
        )
        avoid_entry = recommender.RecommendationEntry(
            skill_id="eagleEye",
            score=10,
            tier="D",
            availability=recommender.AVAILABILITY_UNAVAILABLE,
            reason_codes=("low_tempo",),
        )
        comparison = recommender.OfferComparisonOutput(
            winner="necromancy:expert",
            offers=(top_entry, avoid_entry),
            reason_codes=("higher_score",),
        )

        output = recommender.RecommendationOutput(
            hero_key=" isra ",
            current_skills=({"skill": "necromancy", "level": "advanced"},),
            top_next=(top_entry,),
            avoid=(avoid_entry,),
            offer_comparison=comparison,
        )

        self.assertEqual(output.hero_key, "isra")
        self.assertEqual(output.role, recommender.DEFAULT_ROLE)
        self.assertEqual(output.current_skills[0].level, "advanced")
        self.assertEqual(output.top_next, (top_entry,))
        self.assertEqual(output.avoid, (avoid_entry,))
        self.assertEqual(output.offer_comparison, comparison)

    def test_offer_comparison_output_requires_two_offers(self):
        entry = recommender.RecommendationEntry(
            skill_id="necromancy",
            score=98,
            tier="S",
            availability=recommender.AVAILABILITY_AVAILABLE,
            reason_codes=("hero_specialty",),
            target_level="expert",
        )

        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.OfferComparisonOutput(
                winner="necromancy:expert",
                offers=(entry,),
            )

    def test_offer_comparison_output_rejects_unknown_winner(self):
        necromancy = recommender.RecommendationEntry(
            skill_id="necromancy",
            score=98,
            tier="S",
            availability=recommender.AVAILABILITY_AVAILABLE,
            reason_codes=("hero_specialty",),
            target_level="expert",
        )
        earth_magic = recommender.RecommendationEntry(
            skill_id="earthMagic",
            score=95,
            tier="S",
            availability=recommender.AVAILABILITY_AVAILABLE,
            reason_codes=("mass_slow",),
            target_level="basic",
        )

        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.OfferComparisonOutput(
                winner="logistics:basic",
                offers=(necromancy, earth_magic),
            )

    def test_recommendation_output_rejects_invalid_nested_entries(self):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.RecommendationOutput(
                hero_key="isra",
                top_next=({"skill_id": "necromancy"},),
            )


class VcmiHeroSkillMetadataLoaderTests(unittest.TestCase):
    def test_load_jsonc_preserves_comment_markers_inside_strings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.jsonc"
            path.write_text(
                """
                {
                  "url": "https://example.invalid/path//kept",
                  "quote": "escaped \\" // kept",
                  // dropped line comment
                  "value": 3,
                  /* dropped block
                     comment */
                  "tail": true
                }
                """,
                encoding="utf-8",
            )

            data = recommender.load_jsonc(path)

        self.assertEqual(data["url"], "https://example.invalid/path//kept")
        self.assertEqual(data["quote"], 'escaped " // kept')
        self.assertEqual(data["value"], 3)
        self.assertTrue(data["tail"])

    def test_load_jsonc_does_not_merge_tokens_around_block_comments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.jsonc"
            path.write_text("[1/* removed */2]", encoding="utf-8")

            with self.assertRaises(ValueError):
                recommender.load_jsonc(path)

    def test_loader_uses_exact_standard_hero_scope(self):
        metadata = recommender.load_vcmi_hero_skill_metadata()
        expected_standard_files = (
            "castle.json",
            "conflux.json",
            "dungeon.json",
            "fortress.json",
            "inferno.json",
            "necropolis.json",
            "rampart.json",
            "stronghold.json",
            "tower.json",
        )

        self.assertEqual(
            metadata.loaded_hero_files,
            expected_standard_files,
        )
        self.assertEqual(
            metadata.excluded_hero_files,
            recommender.EXCLUDED_HERO_FILES,
        )
        self.assertNotIn("special.json", metadata.loaded_hero_files)
        self.assertNotIn("portraits.json", metadata.loaded_hero_files)
        self.assertNotIn("portraitsChronicles.json", metadata.loaded_hero_files)

    def test_loader_finds_144_standard_heroes(self):
        metadata = recommender.load_vcmi_hero_skill_metadata()

        self.assertEqual(len(metadata.heroes), 144)

    def test_loader_exposes_isra_metadata_and_starting_skills(self):
        metadata = recommender.load_vcmi_hero_skill_metadata()

        isra = metadata.heroes["isra"]

        self.assertEqual(isra.key, "isra")
        self.assertEqual(isra.display_name, "Isra")
        self.assertEqual(isra.class_id, "deathknight")
        self.assertEqual(isra.faction, "necropolis")
        self.assertEqual(isra.affinity, "might")
        self.assertEqual(isra.specialty_summary, "secondary:necromancy")
        self.assertEqual(
            isra.starting_skills,
            (recommender.CurrentSkill("necromancy", "advanced"),),
        )

    def test_loader_exposes_class_faction_lookup(self):
        metadata = recommender.load_vcmi_hero_skill_metadata()

        deathknight = metadata.hero_classes["deathknight"]

        self.assertEqual(deathknight.key, "deathknight")
        self.assertEqual(deathknight.faction, "necropolis")
        self.assertEqual(deathknight.affinity, "might")
        self.assertEqual(deathknight.index, 8)

    def test_loader_parses_skill_metadata_from_jsonc(self):
        metadata = recommender.load_vcmi_hero_skill_metadata()

        earth_magic = metadata.skills["earthMagic"]
        necromancy = metadata.skills["necromancy"]

        self.assertEqual(earth_magic.key, "earthMagic")
        self.assertEqual(earth_magic.display_name, "Earth Magic")
        self.assertEqual(earth_magic.index, 17)
        self.assertIsNone(earth_magic.gain_chance)
        self.assertIn("basic", earth_magic.level_blocks)
        self.assertEqual(necromancy.index, 12)
        self.assertEqual(necromancy.specialty_tags, ("main",))


class RecommendationRuleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = recommender.load_vcmi_hero_skill_metadata()
        cls.rules_path = recommender.DEFAULT_RULES_PATH
        cls.raw_rules = json.loads(cls.rules_path.read_text(encoding="utf-8"))

    def _rules_with(self, mutator):
        raw_rules = deepcopy(self.raw_rules)
        mutator(raw_rules)
        return raw_rules

    def assertInvalidRules(self, raw_rules):
        with self.assertRaises(recommender.HeroSkillRecommendationError):
            recommender.validate_recommendation_rules(
                raw_rules,
                metadata=self.metadata,
            )

    def test_default_recommendation_rules_file_exists_and_loads(self):
        self.assertTrue(self.rules_path.exists())

        rules = recommender.load_recommendation_rules(metadata=self.metadata)

        self.assertEqual(rules.version, 1)
        self.assertEqual(rules.default_role, "main")
        self.assertEqual(len(self.metadata.heroes), 144)

    def test_default_rules_cover_all_standard_heroes(self):
        rules = recommender.load_recommendation_rules(metadata=self.metadata)

        missing = [
            hero.key
            for hero in self.metadata.heroes.values()
            if not recommender._effective_skill_rules_for_hero(
                rules,
                hero,
                rules.default_role,
            )
        ]

        self.assertEqual(missing, [])

    def test_rules_derive_tiers_from_scores(self):
        rules = recommender.validate_recommendation_rules(
            self.raw_rules,
            metadata=self.metadata,
        )

        self.assertEqual(
            rules.global_rules["main"]["earthMagic"].tier,
            "S",
        )
        self.assertEqual(
            rules.global_rules["main"]["wisdom"].tier,
            "B",
        )
        self.assertEqual(
            rules.global_rules["main"]["eagleEye"].tier,
            "D",
        )

    def test_recommendation_rules_are_strict_json_not_jsonc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.json"
            path.write_text(
                '{"version": 1} // comment is not allowed\n',
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                recommender.load_recommendation_rules(
                    path,
                    metadata=self.metadata,
                )

    def test_validation_rejects_unknown_skill_id(self):
        raw_rules = self._rules_with(
            lambda data: data["global"]["main"]["skills"].__setitem__(
                "unknownSkill",
                {"score": 50, "reason_codes": ["unknown_skill"]},
            )
        )

        self.assertInvalidRules(raw_rules)

    def test_validation_rejects_unknown_hero_class_faction_and_specialty_keys(self):
        invalid_mutators = (
            lambda data: data["heroes"].__setitem__(
                "unknownHero",
                {"main": {"skills": {"earthMagic": {
                    "score": 50,
                    "reason_codes": ["bad_hero"],
                }}}},
            ),
            lambda data: data["classes"].__setitem__(
                "unknownClass",
                {"main": {"skills": {"earthMagic": {
                    "score": 50,
                    "reason_codes": ["bad_class"],
                }}}},
            ),
            lambda data: data["factions"].__setitem__(
                "unknownFaction",
                {"main": {"skills": {"earthMagic": {
                    "score": 50,
                    "reason_codes": ["bad_faction"],
                }}}},
            ),
            lambda data: data["specialties"].__setitem__(
                "secondary:unknownSkill",
                {"main": {"skills": {"earthMagic": {
                    "score": 50,
                    "reason_codes": ["bad_specialty"],
                }}}},
            ),
        )

        for mutator in invalid_mutators:
            with self.subTest(mutator=mutator):
                self.assertInvalidRules(self._rules_with(mutator))

    def test_validation_rejects_out_of_range_scores(self):
        for score in (-1, 101, math.inf, True):
            with self.subTest(score=score):
                raw_rules = self._rules_with(
                    lambda data, score=score: data["global"]["main"]["skills"][
                        "earthMagic"
                    ].__setitem__("score", score)
                )

                self.assertInvalidRules(raw_rules)

    def test_validation_rejects_invalid_reason_codes(self):
        invalid_reason_codes = (
            [],
            ["MassSlow"],
            ["mass slow"],
            ["mass_slow", "mass_slow"],
            {"mass_slow": True},
            None,
            123,
        )

        for reason_codes in invalid_reason_codes:
            with self.subTest(reason_codes=reason_codes):
                raw_rules = self._rules_with(
                    lambda data, reason_codes=reason_codes: data["global"][
                        "main"
                    ]["skills"]["earthMagic"].__setitem__(
                        "reason_codes",
                        reason_codes,
                    )
                )

                self.assertInvalidRules(raw_rules)

    def test_validation_rejects_bool_version(self):
        raw_rules = self._rules_with(
            lambda data: data.__setitem__("version", True)
        )

        self.assertInvalidRules(raw_rules)

    def test_validation_rejects_unsupported_rule_shape(self):
        invalid_mutators = (
            lambda data: data["global"]["main"]["skills"]["earthMagic"].__setitem__(
                "tier",
                "S",
            ),
            lambda data: data["global"]["main"]["skills"]["earthMagic"].__setitem__(
                "reasons",
                ["mass_slow"],
            ),
            lambda data: data["global"]["main"]["skills"]["earthMagic"].__delitem__(
                "score"
            ),
        )

        for mutator in invalid_mutators:
            with self.subTest(mutator=mutator):
                self.assertInvalidRules(self._rules_with(mutator))

    def test_validation_rejects_invalid_tiers(self):
        invalid_mutators = (
            lambda data: data["tiers"].pop("D"),
            lambda data: data["tiers"]["D"].__setitem__("min_score", 1),
            lambda data: data["tiers"]["A"].__setitem__("min_score", 95),
            lambda data: data["tiers"]["S"].__setitem__("min_score", 101),
        )

        for mutator in invalid_mutators:
            with self.subTest(mutator=mutator):
                self.assertInvalidRules(self._rules_with(mutator))

    def test_validation_rejects_missing_default_role_coverage(self):
        raw_rules = self._rules_with(
            lambda data: data["global"].__setitem__("main", {"skills": {}})
        )

        self.assertInvalidRules(raw_rules)


if __name__ == "__main__":
    unittest.main()
