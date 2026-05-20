from __future__ import annotations

import math
import unittest

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


if __name__ == "__main__":
    unittest.main()
