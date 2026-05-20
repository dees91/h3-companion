#!/usr/bin/env python3
"""Contracts for battle-estimator hero secondary-skill recommendations."""

from __future__ import annotations

import math
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


MAX_SECONDARY_SKILLS = 8
SKILL_LEVELS = ("basic", "advanced", "expert")
VALID_TIERS = ("S", "A", "B", "C", "D")

AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_UNAVAILABLE = "unavailable"
VALID_AVAILABILITY = (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_UNAVAILABLE,
)

DEFAULT_ROLE = "main"

STANDARD_HERO_FILES = (
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
EXCLUDED_HERO_FILES = (
    "portraits.json",
    "portraitsChronicles.json",
    "special.json",
)
DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "battle_estimator"
    / "hero_skill_recommendations.json"
)

_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_CAMEL_WORD_RE = re.compile(r"(?<!^)(?=[A-Z])")


class HeroSkillRecommendationError(ValueError):
    """Raised when hero-skill recommendation contract data is invalid."""


def normalize_skill_level(value: Any) -> str:
    """Return a canonical secondary-skill level."""
    if not isinstance(value, str):
        raise HeroSkillRecommendationError("skill level must be a string")
    normalized = value.strip().lower()
    if normalized not in SKILL_LEVELS:
        allowed = ", ".join(SKILL_LEVELS)
        raise HeroSkillRecommendationError(
            f"skill level must be one of: {allowed}"
        )
    return normalized


def load_jsonc(path: Path) -> Any:
    """Load JSON or JSONC with comments stripped outside string literals."""
    path = Path(path)
    return json.loads(_strip_json_comments(path.read_text(encoding="utf-8")))


def load_vcmi_hero_skill_metadata(
    config_root: Optional[Path] = None,
) -> "VcmiHeroSkillMetadata":
    """Load standard hero, class, and skill metadata from VCMI config."""
    root = _default_config_root() if config_root is None else Path(config_root)
    classes = _load_hero_classes(root / "heroClasses.json")
    skills = _load_skill_metadata(root / "skills.json")

    heroes = {}
    for file_name in STANDARD_HERO_FILES:
        path = root / "heroes" / file_name
        raw_heroes = load_jsonc(path)
        for hero_key in sorted(raw_heroes):
            hero = _hero_metadata_from_entry(
                hero_key,
                raw_heroes[hero_key],
                classes,
                skills,
            )
            if hero.key in heroes:
                raise HeroSkillRecommendationError(
                    f"duplicate hero key: {hero.key}"
                )
            heroes[hero.key] = hero

    return VcmiHeroSkillMetadata(
        heroes=heroes,
        hero_classes=classes,
        skills=skills,
        loaded_hero_files=STANDARD_HERO_FILES,
        excluded_hero_files=EXCLUDED_HERO_FILES,
    )


def load_recommendation_rules(
    path: Optional[Path] = None,
    metadata: Optional["VcmiHeroSkillMetadata"] = None,
) -> "RecommendationRules":
    """Load and validate strict JSON recommendation rules."""
    rules_path = DEFAULT_RULES_PATH if path is None else Path(path)
    raw_rules = json.loads(rules_path.read_text(encoding="utf-8"))
    return validate_recommendation_rules(raw_rules, metadata=metadata)


def validate_recommendation_rules(
    raw_rules: Mapping[str, Any],
    metadata: Optional["VcmiHeroSkillMetadata"] = None,
) -> "RecommendationRules":
    """Validate recommendation rule schema against loaded VCMI metadata."""
    if not isinstance(raw_rules, Mapping):
        raise HeroSkillRecommendationError("recommendation rules must be a mapping")
    metadata = metadata or load_vcmi_hero_skill_metadata()
    version = _normalize_non_bool_int(
        _required_mapping_value(raw_rules, "version", "rules"),
        "version",
    )
    if version != 1:
        raise HeroSkillRecommendationError("rules version must be 1")

    scope = _required_mapping_value(raw_rules, "scope", "rules")
    _validate_rules_scope(scope, metadata)
    default_role = _normalize_non_empty_string(
        raw_rules.get("default_role", DEFAULT_ROLE),
        "default_role",
    )
    tiers = _normalize_rule_tiers(_required_mapping_value(raw_rules, "tiers", "rules"))

    global_rules = _parse_rule_layer_group(
        raw_rules.get("global", {}),
        metadata,
        tiers,
        "global",
    )
    faction_rules = _parse_keyed_rule_groups(
        raw_rules.get("factions", {}),
        set(_metadata_factions(metadata)),
        metadata,
        tiers,
        "factions",
    )
    class_rules = _parse_keyed_rule_groups(
        raw_rules.get("classes", {}),
        set(metadata.hero_classes),
        metadata,
        tiers,
        "classes",
    )
    specialty_rules = _parse_keyed_rule_groups(
        raw_rules.get("specialties", {}),
        set(_metadata_specialties(metadata)),
        metadata,
        tiers,
        "specialties",
    )
    hero_rules = _parse_keyed_rule_groups(
        raw_rules.get("heroes", {}),
        set(metadata.heroes),
        metadata,
        tiers,
        "heroes",
    )

    rules = RecommendationRules(
        version=version,
        scope=dict(scope),
        default_role=default_role,
        tiers=tiers,
        global_rules=global_rules,
        faction_rules=faction_rules,
        class_rules=class_rules,
        specialty_rules=specialty_rules,
        hero_rules=hero_rules,
    )
    _validate_rules_coverage(rules, metadata)
    return rules


def derive_tier(
    score: float,
    tiers: Mapping[str, "TierRule"],
) -> str:
    """Return the display tier for a normalized score."""
    score = _normalize_score(score)
    for tier_name in VALID_TIERS:
        if score >= tiers[tier_name].min_score:
            return tier_name
    return "D"


def recommend_hero_skills(
    hero_key: str,
    role: Optional[str] = None,
    current_skills: Sequence[Any] = (),
    metadata: Optional["VcmiHeroSkillMetadata"] = None,
    rules: Optional["RecommendationRules"] = None,
    top_limit: Optional[int] = None,
    avoid_limit: Optional[int] = None,
) -> "RecommendationOutput":
    """Rank next secondary-skill candidates for a hero.

    ``top_next`` contains deterministic ranked candidates. Candidates that are
    blocked by a full 8-skill build are kept with unavailable availability so
    callers can explain why a high-value new skill cannot be taken.
    """
    metadata = metadata or load_vcmi_hero_skill_metadata()
    rules = rules or load_recommendation_rules(metadata=metadata)
    hero_key = _normalize_non_empty_string(hero_key, "hero_key")
    if hero_key not in metadata.heroes:
        raise HeroSkillRecommendationError(f"unknown hero key: {hero_key}")
    hero = metadata.heroes[hero_key]
    role = _normalize_non_empty_string(role or rules.default_role, "role")
    current_skills = validate_current_skills(current_skills)
    _validate_known_current_skills(current_skills, metadata)
    top_limit = _normalize_optional_limit(top_limit, "top_limit")
    avoid_limit = _normalize_optional_limit(avoid_limit, "avoid_limit")

    skill_rules = _effective_skill_rules_for_hero(rules, hero, role)
    current_by_skill = {skill.skill_id: skill for skill in current_skills}
    has_open_slot = len(current_by_skill) < MAX_SECONDARY_SKILLS
    candidates = []
    for skill_id, skill_rule in skill_rules.items():
        current_skill = current_by_skill.get(skill_id)
        entry = _entry_for_skill_rule(
            skill_rule,
            current_skill,
            has_open_slot,
            metadata,
        )
        if entry is not None:
            candidates.append((entry, skill_rule.upgrade_priority))

    entries = tuple(
        entry
        for entry, _priority in sorted(candidates, key=_candidate_sort_key)
    )
    avoid = tuple(
        entry
        for entry in entries
        if entry.availability == AVAILABILITY_UNAVAILABLE or entry.tier == "D"
    )

    return RecommendationOutput(
        hero_key=hero.key,
        role=role,
        current_skills=current_skills,
        top_next=_apply_limit(entries, top_limit),
        avoid=_apply_limit(avoid, avoid_limit),
    )


def compare_skill_offers(
    hero_key: str,
    current_skills: Sequence[Any],
    offers: Sequence[Any],
    role: Optional[str] = None,
    metadata: Optional["VcmiHeroSkillMetadata"] = None,
    rules: Optional["RecommendationRules"] = None,
) -> "OfferComparisonOutput":
    """Compare concrete level-up offers using the recommendation rules."""
    metadata = metadata or load_vcmi_hero_skill_metadata()
    rules = rules or load_recommendation_rules(metadata=metadata)
    role = _normalize_non_empty_string(role or rules.default_role, "role")
    comparison_input = OfferComparisonInput(
        hero_key=hero_key,
        role=role,
        current_skills=current_skills,
        offers=offers,
    )
    if comparison_input.hero_key not in metadata.heroes:
        raise HeroSkillRecommendationError(
            f"unknown hero key: {comparison_input.hero_key}"
        )
    _validate_known_current_skills(comparison_input.current_skills, metadata)
    _validate_known_offer_skills(comparison_input.offers, metadata)
    _validate_distinct_offer_keys(comparison_input.offers)

    hero = metadata.heroes[comparison_input.hero_key]
    skill_rules = _effective_skill_rules_for_hero(rules, hero, role)
    current_by_skill = {
        skill.skill_id: skill
        for skill in comparison_input.current_skills
    }
    has_open_slot = len(current_by_skill) < MAX_SECONDARY_SKILLS

    candidates = []
    output_entries = []
    for offer in comparison_input.offers:
        skill_rule = skill_rules.get(offer.skill_id)
        entry = _entry_for_skill_offer(
            offer,
            skill_rule,
            current_by_skill.get(offer.skill_id),
            has_open_slot,
            metadata,
        )
        output_entries.append(entry)
        candidates.append((
            entry,
            skill_rule.upgrade_priority if skill_rule is not None else 0.0,
        ))

    available_candidates = [
        candidate
        for candidate in candidates
        if candidate[0].availability == AVAILABILITY_AVAILABLE
    ]
    if available_candidates:
        winner_entry, winner_priority = sorted(
            available_candidates,
            key=_candidate_sort_key,
        )[0]
        winner = _recommendation_entry_offer_key(winner_entry)
        reason_codes = _comparison_reason_codes(
            winner_entry,
            winner_priority,
            available_candidates,
        )
    else:
        winner = None
        reason_codes = ("no_available_offers",)

    return OfferComparisonOutput(
        winner=winner,
        offers=tuple(output_entries),
        reason_codes=reason_codes,
    )


def validate_current_skills(values: Iterable[Any]) -> Tuple["CurrentSkill", ...]:
    """Normalize current skill slots and enforce distinct skill IDs."""
    skills = tuple(_current_skill_from_input(value) for value in values)
    if len(skills) > MAX_SECONDARY_SKILLS:
        raise HeroSkillRecommendationError(
            f"current skills cannot exceed {MAX_SECONDARY_SKILLS}"
        )

    seen = set()
    duplicates = []
    for skill in skills:
        if skill.skill_id in seen:
            duplicates.append(skill.skill_id)
        seen.add(skill.skill_id)
    if duplicates:
        duplicate_list = ", ".join(sorted(set(duplicates)))
        raise HeroSkillRecommendationError(
            f"current skills contain duplicate skill IDs: {duplicate_list}"
        )
    return skills


@dataclass(frozen=True)
class CurrentSkill:
    """A secondary skill currently owned by a hero."""

    skill_id: str
    level: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skill_id",
            _normalize_non_empty_string(self.skill_id, "skill_id"),
        )
        object.__setattr__(self, "level", normalize_skill_level(self.level))

    @property
    def skill(self) -> str:
        return self.skill_id


@dataclass(frozen=True)
class TierRule:
    """Display tier threshold from recommendation rules."""

    name: str
    min_score: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_tier(self.name))
        object.__setattr__(self, "min_score", _normalize_score(self.min_score))


@dataclass(frozen=True)
class SkillRule:
    """Validated recommendation rule for a single skill."""

    skill_id: str
    score: float
    tier: str
    reason_codes: Tuple[str, ...]
    upgrade_priority: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skill_id",
            _normalize_non_empty_string(self.skill_id, "skill_id"),
        )
        object.__setattr__(self, "score", _normalize_score(self.score))
        object.__setattr__(self, "tier", _normalize_tier(self.tier))
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_reason_codes(self.reason_codes),
        )
        object.__setattr__(
            self,
            "upgrade_priority",
            _normalize_finite_number(self.upgrade_priority, "upgrade_priority"),
        )


@dataclass(frozen=True)
class RecommendationRules:
    """Validated layered recommendation rules."""

    version: int
    scope: Mapping[str, Any]
    default_role: str
    tiers: Mapping[str, TierRule]
    global_rules: Mapping[str, Mapping[str, SkillRule]]
    faction_rules: Mapping[str, Mapping[str, Mapping[str, SkillRule]]]
    class_rules: Mapping[str, Mapping[str, Mapping[str, SkillRule]]]
    specialty_rules: Mapping[str, Mapping[str, Mapping[str, SkillRule]]]
    hero_rules: Mapping[str, Mapping[str, Mapping[str, SkillRule]]]

    def __post_init__(self) -> None:
        if self.version != 1:
            raise HeroSkillRecommendationError("rules version must be 1")
        object.__setattr__(
            self,
            "default_role",
            _normalize_non_empty_string(self.default_role, "default_role"),
        )
        object.__setattr__(self, "scope", dict(self.scope))
        object.__setattr__(self, "tiers", dict(self.tiers))
        object.__setattr__(self, "global_rules", dict(self.global_rules))
        object.__setattr__(self, "faction_rules", dict(self.faction_rules))
        object.__setattr__(self, "class_rules", dict(self.class_rules))
        object.__setattr__(self, "specialty_rules", dict(self.specialty_rules))
        object.__setattr__(self, "hero_rules", dict(self.hero_rules))


@dataclass(frozen=True)
class SkillMetadata:
    """VCMI secondary-skill metadata used by recommendation rules."""

    key: str
    display_name: str
    index: Optional[int]
    specialty_tags: Tuple[str, ...]
    level_blocks: Mapping[str, Mapping[str, Any]]
    gain_chance: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key",
            _normalize_non_empty_string(self.key, "key"),
        )
        object.__setattr__(
            self,
            "display_name",
            _normalize_non_empty_string(self.display_name, "display_name"),
        )
        if self.index is not None:
            object.__setattr__(self, "index", _normalize_non_bool_int(
                self.index,
                "index",
            ))
        object.__setattr__(
            self,
            "specialty_tags",
            tuple(_normalize_non_empty_string(tag, "specialty_tag")
                  for tag in self.specialty_tags),
        )
        level_blocks = {}
        for level in SKILL_LEVELS:
            block = self.level_blocks.get(level, {})
            if not isinstance(block, Mapping):
                raise HeroSkillRecommendationError(
                    f"{self.key}.{level} metadata must be a mapping"
                )
            level_blocks[level] = dict(block)
        object.__setattr__(self, "level_blocks", level_blocks)
        if self.gain_chance is not None and not isinstance(
            self.gain_chance,
            Mapping,
        ):
            raise HeroSkillRecommendationError(
                f"{self.key}.gain_chance must be a mapping"
            )


@dataclass(frozen=True)
class HeroClassMetadata:
    """VCMI hero class metadata relevant to recommendations."""

    key: str
    faction: str
    affinity: str
    index: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key",
            _normalize_non_empty_string(self.key, "key"),
        )
        object.__setattr__(
            self,
            "faction",
            _normalize_non_empty_string(self.faction, "faction"),
        )
        object.__setattr__(
            self,
            "affinity",
            _normalize_non_empty_string(self.affinity, "affinity"),
        )
        if self.index is not None:
            object.__setattr__(self, "index", _normalize_non_bool_int(
                self.index,
                "index",
            ))


@dataclass(frozen=True)
class HeroMetadata:
    """Standard VCMI hero metadata exposed to the recommender."""

    key: str
    display_name: str
    class_id: str
    faction: str
    affinity: str
    specialty_summary: str
    starting_skills: Tuple[CurrentSkill, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key",
            _normalize_non_empty_string(self.key, "key"),
        )
        object.__setattr__(
            self,
            "display_name",
            _normalize_non_empty_string(self.display_name, "display_name"),
        )
        object.__setattr__(
            self,
            "class_id",
            _normalize_non_empty_string(self.class_id, "class_id"),
        )
        object.__setattr__(
            self,
            "faction",
            _normalize_non_empty_string(self.faction, "faction"),
        )
        object.__setattr__(
            self,
            "affinity",
            _normalize_non_empty_string(self.affinity, "affinity"),
        )
        object.__setattr__(
            self,
            "specialty_summary",
            _normalize_non_empty_string(
                self.specialty_summary,
                "specialty_summary",
            ),
        )
        object.__setattr__(
            self,
            "starting_skills",
            validate_current_skills(self.starting_skills),
        )


@dataclass(frozen=True)
class VcmiHeroSkillMetadata:
    """Loaded VCMI metadata bundle for hero-skill recommendations."""

    heroes: Mapping[str, HeroMetadata]
    hero_classes: Mapping[str, HeroClassMetadata]
    skills: Mapping[str, SkillMetadata]
    loaded_hero_files: Tuple[str, ...]
    excluded_hero_files: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "heroes", dict(self.heroes))
        object.__setattr__(self, "hero_classes", dict(self.hero_classes))
        object.__setattr__(self, "skills", dict(self.skills))
        object.__setattr__(self, "loaded_hero_files", tuple(
            _normalize_non_empty_string(name, "loaded_hero_file")
            for name in self.loaded_hero_files
        ))
        object.__setattr__(self, "excluded_hero_files", tuple(
            _normalize_non_empty_string(name, "excluded_hero_file")
            for name in self.excluded_hero_files
        ))


@dataclass(frozen=True)
class SkillOffer:
    """A concrete level-up offer for a target skill level."""

    skill_id: str
    target_level: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skill_id",
            _normalize_non_empty_string(self.skill_id, "skill_id"),
        )
        object.__setattr__(
            self,
            "target_level",
            normalize_skill_level(self.target_level),
        )

    @property
    def skill(self) -> str:
        return self.skill_id

    @property
    def level(self) -> str:
        return self.target_level

    @property
    def key(self) -> str:
        return f"{self.skill_id}:{self.target_level}"


@dataclass(frozen=True)
class RecommendationEntry:
    """A scored recommendation or avoid entry."""

    skill_id: str
    score: float
    tier: str
    availability: str
    reason_codes: Sequence[str]
    display_name: Optional[str] = None
    target_level: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skill_id",
            _normalize_non_empty_string(self.skill_id, "skill_id"),
        )
        object.__setattr__(self, "score", _normalize_score(self.score))
        object.__setattr__(self, "tier", _normalize_tier(self.tier))
        object.__setattr__(
            self,
            "availability",
            _normalize_availability(self.availability),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_reason_codes(self.reason_codes),
        )
        if self.display_name is not None:
            object.__setattr__(
                self,
                "display_name",
                _normalize_non_empty_string(self.display_name, "display_name"),
            )
        if self.target_level is not None:
            object.__setattr__(
                self,
                "target_level",
                normalize_skill_level(self.target_level),
            )


@dataclass(frozen=True)
class OfferComparisonInput:
    """Input contract for comparing two or more concrete skill offers."""

    hero_key: str
    current_skills: Sequence[Any]
    offers: Sequence[Any]
    role: str = DEFAULT_ROLE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hero_key",
            _normalize_non_empty_string(self.hero_key, "hero_key"),
        )
        object.__setattr__(
            self,
            "role",
            _normalize_non_empty_string(self.role, "role"),
        )
        object.__setattr__(
            self,
            "current_skills",
            validate_current_skills(self.current_skills),
        )
        offers = tuple(_skill_offer_from_input(value) for value in self.offers)
        if len(offers) < 2:
            raise HeroSkillRecommendationError(
                "offer comparison requires at least two offers"
            )
        object.__setattr__(self, "offers", offers)


@dataclass(frozen=True)
class OfferComparisonOutput:
    """Output contract for a skill-vs-skill comparison result."""

    winner: Optional[str]
    offers: Sequence[RecommendationEntry]
    reason_codes: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.winner is not None:
            object.__setattr__(
                self,
                "winner",
                _normalize_non_empty_string(self.winner, "winner"),
            )
        offers = _normalize_recommendation_entries(self.offers, "offers")
        if len(offers) < 2:
            raise HeroSkillRecommendationError(
                "offer comparison output requires at least two offers"
            )
        offer_keys = tuple(_recommendation_entry_offer_key(entry) for entry in offers)
        if self.winner is not None and self.winner not in offer_keys:
            raise HeroSkillRecommendationError(
                "winner must match one of the comparison offers"
            )
        object.__setattr__(self, "offers", offers)
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_reason_codes(self.reason_codes),
        )


@dataclass(frozen=True)
class RecommendationOutput:
    """Top-level output contract returned by the recommender module."""

    hero_key: str
    role: str = DEFAULT_ROLE
    current_skills: Sequence[Any] = ()
    top_next: Sequence[RecommendationEntry] = ()
    avoid: Sequence[RecommendationEntry] = ()
    offer_comparison: Optional[OfferComparisonOutput] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hero_key",
            _normalize_non_empty_string(self.hero_key, "hero_key"),
        )
        object.__setattr__(
            self,
            "role",
            _normalize_non_empty_string(self.role, "role"),
        )
        object.__setattr__(
            self,
            "current_skills",
            validate_current_skills(self.current_skills),
        )
        object.__setattr__(
            self,
            "top_next",
            _normalize_recommendation_entries(self.top_next, "top_next"),
        )
        object.__setattr__(
            self,
            "avoid",
            _normalize_recommendation_entries(self.avoid, "avoid"),
        )
        if (
            self.offer_comparison is not None
            and not isinstance(self.offer_comparison, OfferComparisonOutput)
        ):
            raise HeroSkillRecommendationError(
                "offer_comparison must be an OfferComparisonOutput"
            )


def _current_skill_from_input(value: Any) -> CurrentSkill:
    if isinstance(value, CurrentSkill):
        return value
    if isinstance(value, Mapping):
        return CurrentSkill(
            skill_id=_mapping_value(value, ("skill_id", "skill")),
            level=_mapping_value(value, ("level",)),
        )
    raise HeroSkillRecommendationError(
        "current skill entries must be CurrentSkill or mapping values"
    )


def _validate_rules_scope(
    scope: Any,
    metadata: VcmiHeroSkillMetadata,
) -> None:
    if not isinstance(scope, Mapping):
        raise HeroSkillRecommendationError("rules scope must be a mapping")
    hero_files = tuple(_required_mapping_value(scope, "hero_files", "scope"))
    excluded_files = tuple(_required_mapping_value(
        scope,
        "excluded_files",
        "scope",
    ))
    if hero_files != metadata.loaded_hero_files:
        raise HeroSkillRecommendationError(
            "rules scope hero_files must match standard hero files"
        )
    if excluded_files != metadata.excluded_hero_files:
        raise HeroSkillRecommendationError(
            "rules scope excluded_files must match excluded hero files"
        )


def _normalize_rule_tiers(raw_tiers: Any) -> dict:
    if not isinstance(raw_tiers, Mapping):
        raise HeroSkillRecommendationError("tiers must be a mapping")
    if set(raw_tiers) != set(VALID_TIERS):
        raise HeroSkillRecommendationError("tiers must contain exactly S/A/B/C/D")

    tiers = {}
    previous_min_score = None
    for tier_name in VALID_TIERS:
        raw_tier = raw_tiers[tier_name]
        if not isinstance(raw_tier, Mapping):
            raise HeroSkillRecommendationError(f"tier {tier_name} must be a mapping")
        min_score = _required_mapping_value(
            raw_tier,
            "min_score",
            f"tier {tier_name}",
        )
        tier = TierRule(name=tier_name, min_score=min_score)
        if previous_min_score is not None and tier.min_score >= previous_min_score:
            raise HeroSkillRecommendationError(
                "tier min_score values must descend from S to D"
            )
        previous_min_score = tier.min_score
        tiers[tier_name] = tier

    if tiers["D"].min_score != 0:
        raise HeroSkillRecommendationError("tier D min_score must be 0")
    return tiers


def _parse_keyed_rule_groups(
    raw_groups: Any,
    allowed_keys: set,
    metadata: VcmiHeroSkillMetadata,
    tiers: Mapping[str, TierRule],
    context: str,
) -> dict:
    if not isinstance(raw_groups, Mapping):
        raise HeroSkillRecommendationError(f"{context} must be a mapping")
    parsed = {}
    for key in sorted(raw_groups):
        if key not in allowed_keys:
            raise HeroSkillRecommendationError(f"unknown {context} key: {key}")
        parsed[key] = _parse_rule_layer_group(
            raw_groups[key],
            metadata,
            tiers,
            f"{context}.{key}",
        )
    return parsed


def _parse_rule_layer_group(
    raw_group: Any,
    metadata: VcmiHeroSkillMetadata,
    tiers: Mapping[str, TierRule],
    context: str,
) -> dict:
    if not isinstance(raw_group, Mapping):
        raise HeroSkillRecommendationError(f"{context} must be a mapping")
    parsed = {}
    for role in sorted(raw_group):
        parsed[role] = _parse_role_skill_rules(
            role,
            raw_group[role],
            metadata,
            tiers,
            f"{context}.{role}",
        )
    return parsed


def _parse_role_skill_rules(
    role: str,
    raw_role: Any,
    metadata: VcmiHeroSkillMetadata,
    tiers: Mapping[str, TierRule],
    context: str,
) -> dict:
    _normalize_non_empty_string(role, "role")
    if not isinstance(raw_role, Mapping):
        raise HeroSkillRecommendationError(f"{context} must be a mapping")
    raw_skills = _required_mapping_value(raw_role, "skills", context)
    if not isinstance(raw_skills, Mapping):
        raise HeroSkillRecommendationError(f"{context}.skills must be a mapping")

    parsed = {}
    for skill_id in sorted(raw_skills):
        if skill_id not in metadata.skills:
            raise HeroSkillRecommendationError(f"unknown skill ID: {skill_id}")
        parsed[skill_id] = _parse_skill_rule(
            skill_id,
            raw_skills[skill_id],
            tiers,
            f"{context}.skills.{skill_id}",
        )
    return parsed


def _parse_skill_rule(
    skill_id: str,
    raw_rule: Any,
    tiers: Mapping[str, TierRule],
    context: str,
) -> SkillRule:
    if not isinstance(raw_rule, Mapping):
        raise HeroSkillRecommendationError(f"{context} must be a mapping")
    if "tier" in raw_rule:
        raise HeroSkillRecommendationError(f"{context}.tier is derived")
    if "reasons" in raw_rule:
        raise HeroSkillRecommendationError(
            f"{context}.reasons is not supported; use reason_codes"
        )
    score = _required_mapping_value(raw_rule, "score", context)
    reason_codes = _required_mapping_value(raw_rule, "reason_codes", context)
    reason_codes = _normalize_reason_codes(reason_codes)
    if not reason_codes:
        raise HeroSkillRecommendationError(f"{context}.reason_codes cannot be empty")
    upgrade_priority = raw_rule.get("upgrade_priority", 0.0)
    return SkillRule(
        skill_id=skill_id,
        score=score,
        tier=derive_tier(score, tiers),
        reason_codes=reason_codes,
        upgrade_priority=upgrade_priority,
    )


def _validate_rules_coverage(
    rules: RecommendationRules,
    metadata: VcmiHeroSkillMetadata,
) -> None:
    missing = []
    for hero_key in sorted(metadata.heroes):
        if not _effective_skill_rules_for_hero(
            rules,
            metadata.heroes[hero_key],
            rules.default_role,
        ):
            missing.append(hero_key)

    if missing:
        sample = ", ".join(missing[:8])
        raise HeroSkillRecommendationError(
            f"missing effective {rules.default_role} rules for heroes: {sample}"
        )


def _validate_known_current_skills(
    current_skills: Sequence[CurrentSkill],
    metadata: VcmiHeroSkillMetadata,
) -> None:
    for skill in current_skills:
        if skill.skill_id not in metadata.skills:
            raise HeroSkillRecommendationError(
                f"unknown current skill ID: {skill.skill_id}"
            )


def _validate_known_offer_skills(
    offers: Sequence[SkillOffer],
    metadata: VcmiHeroSkillMetadata,
) -> None:
    for offer in offers:
        if offer.skill_id not in metadata.skills:
            raise HeroSkillRecommendationError(
                f"unknown offer skill ID: {offer.skill_id}"
            )


def _validate_distinct_offer_keys(offers: Sequence[SkillOffer]) -> None:
    seen = set()
    duplicates = []
    for offer in offers:
        if offer.key in seen:
            duplicates.append(offer.key)
        seen.add(offer.key)
    if duplicates:
        duplicate_list = ", ".join(sorted(set(duplicates)))
        raise HeroSkillRecommendationError(
            f"duplicate offer keys: {duplicate_list}"
        )


def _effective_skill_rules_for_hero(
    rules: RecommendationRules,
    hero: HeroMetadata,
    role: str,
) -> dict:
    effective = {}
    for layer in (
        rules.global_rules,
        rules.faction_rules.get(hero.faction, {}),
        rules.class_rules.get(hero.class_id, {}),
        rules.specialty_rules.get(hero.specialty_summary, {}),
        rules.hero_rules.get(hero.key, {}),
    ):
        effective.update(layer.get(role, {}))
    return effective


def _entry_for_skill_offer(
    offer: SkillOffer,
    skill_rule: Optional[SkillRule],
    current_skill: Optional[CurrentSkill],
    has_open_slot: bool,
    metadata: VcmiHeroSkillMetadata,
) -> RecommendationEntry:
    availability_reasons = _offer_availability_reasons(
        offer,
        current_skill,
        has_open_slot,
    )
    if skill_rule is None:
        score = 0.0
        tier = "D"
        rule_reason_codes = ("no_recommendation_rule",)
    else:
        score = skill_rule.score
        tier = skill_rule.tier
        rule_reason_codes = skill_rule.reason_codes

    reason_codes = _dedupe_reason_codes(
        (*rule_reason_codes, *availability_reasons)
    )
    availability = (
        AVAILABILITY_AVAILABLE
        if not availability_reasons and skill_rule is not None
        else AVAILABILITY_UNAVAILABLE
    )
    skill_metadata = metadata.skills[offer.skill_id]
    return RecommendationEntry(
        skill_id=offer.skill_id,
        score=score,
        tier=tier,
        availability=availability,
        reason_codes=reason_codes,
        display_name=skill_metadata.display_name,
        target_level=offer.target_level,
    )


def _offer_availability_reasons(
    offer: SkillOffer,
    current_skill: Optional[CurrentSkill],
    has_open_slot: bool,
) -> Tuple[str, ...]:
    if current_skill is not None:
        expected_level = _next_skill_level(current_skill.level)
        if expected_level is None or offer.target_level != expected_level:
            return ("illegal_upgrade_level",)
        return ()

    reasons = []
    if offer.target_level != "basic":
        reasons.append("illegal_new_skill_level")
    if not has_open_slot:
        reasons.append("no_open_skill_slot")
    return tuple(reasons)


def _entry_for_skill_rule(
    skill_rule: SkillRule,
    current_skill: Optional[CurrentSkill],
    has_open_slot: bool,
    metadata: VcmiHeroSkillMetadata,
) -> Optional[RecommendationEntry]:
    if current_skill is not None:
        target_level = _next_skill_level(current_skill.level)
        if target_level is None:
            return None
        availability = AVAILABILITY_AVAILABLE
        reason_codes = skill_rule.reason_codes
    else:
        target_level = "basic"
        availability = (
            AVAILABILITY_AVAILABLE
            if has_open_slot
            else AVAILABILITY_UNAVAILABLE
        )
        reason_codes = skill_rule.reason_codes
        if availability == AVAILABILITY_UNAVAILABLE:
            reason_codes = (*reason_codes, "no_open_skill_slot")

    skill_metadata = metadata.skills[skill_rule.skill_id]
    return RecommendationEntry(
        skill_id=skill_rule.skill_id,
        score=skill_rule.score,
        tier=skill_rule.tier,
        availability=availability,
        reason_codes=reason_codes,
        display_name=skill_metadata.display_name,
        target_level=target_level,
    )


def _next_skill_level(level: str) -> Optional[str]:
    level = normalize_skill_level(level)
    if level == "basic":
        return "advanced"
    if level == "advanced":
        return "expert"
    return None


def _candidate_sort_key(candidate: Tuple[RecommendationEntry, float]) -> tuple:
    entry, upgrade_priority = candidate
    return (
        -entry.score,
        VALID_TIERS.index(entry.tier),
        -upgrade_priority,
        entry.skill_id,
        entry.target_level or "",
    )


def _apply_limit(
    entries: Sequence[RecommendationEntry],
    limit: Optional[int],
) -> Tuple[RecommendationEntry, ...]:
    entries = tuple(entries)
    if limit is None:
        return entries
    return entries[:limit]


def _comparison_reason_codes(
    winner: RecommendationEntry,
    winner_priority: float,
    candidates: Sequence[Tuple[RecommendationEntry, float]],
) -> Tuple[str, ...]:
    if len(candidates) == 1:
        return ("only_available_offer",)
    ordered = sorted(candidates, key=_candidate_sort_key)
    if ordered[0][0] != winner:
        raise HeroSkillRecommendationError("winner does not match sorted offers")
    runner_up, runner_up_priority = ordered[1]
    if winner.score > runner_up.score:
        return ("higher_score",)
    winner_tier_index = VALID_TIERS.index(winner.tier)
    runner_tier_index = VALID_TIERS.index(runner_up.tier)
    if winner_tier_index < runner_tier_index:
        return ("higher_tier",)
    if winner_priority > runner_up_priority:
        return ("higher_upgrade_priority",)
    return ("deterministic_tiebreak",)


def _dedupe_reason_codes(values: Iterable[str]) -> Tuple[str, ...]:
    deduped = []
    seen = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return tuple(deduped)


def _normalize_optional_limit(
    value: Optional[Any],
    field_name: str,
) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HeroSkillRecommendationError(f"{field_name} must be an integer")
    if value < 0:
        raise HeroSkillRecommendationError(f"{field_name} cannot be negative")
    return value


def _metadata_factions(metadata: VcmiHeroSkillMetadata) -> Tuple[str, ...]:
    return tuple(sorted({hero.faction for hero in metadata.heroes.values()}))


def _metadata_specialties(metadata: VcmiHeroSkillMetadata) -> Tuple[str, ...]:
    return tuple(sorted({
        hero.specialty_summary
        for hero in metadata.heroes.values()
    }))


def _default_config_root() -> Path:
    return Path(__file__).resolve().parents[1] / "config"


def _strip_json_comments(text: str) -> str:
    result = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < length and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            result.append(" ")
            index += 2
            while index + 1 < length:
                if text[index] == "*" and text[index + 1] == "/":
                    index += 2
                    break
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _load_hero_classes(path: Path) -> dict:
    raw_classes = load_jsonc(path)
    classes = {}
    for class_key in sorted(raw_classes):
        entry = raw_classes[class_key]
        classes[class_key] = HeroClassMetadata(
            key=class_key,
            faction=_required_mapping_value(entry, "faction", class_key),
            affinity=_required_mapping_value(entry, "affinity", class_key),
            index=entry.get("index"),
        )
    return classes


def _load_skill_metadata(path: Path) -> dict:
    raw_skills = load_jsonc(path)
    skills = {}
    for skill_key in sorted(raw_skills):
        entry = raw_skills[skill_key]
        display_name = _nested_text_name(entry) or _display_name_from_key(
            skill_key
        )
        skills[skill_key] = SkillMetadata(
            key=skill_key,
            display_name=display_name,
            index=entry.get("index"),
            specialty_tags=tuple(entry.get("specialty", ())),
            level_blocks={
                level: dict(entry.get(level, {}))
                for level in SKILL_LEVELS
            },
            gain_chance=entry.get("gainChance"),
        )
    return skills


def _hero_metadata_from_entry(
    hero_key: str,
    entry: Mapping[str, Any],
    classes: Mapping[str, HeroClassMetadata],
    skills: Mapping[str, SkillMetadata],
) -> HeroMetadata:
    class_id = _required_mapping_value(entry, "class", hero_key)
    if class_id not in classes:
        raise HeroSkillRecommendationError(
            f"unknown hero class for {hero_key}: {class_id}"
        )
    hero_class = classes[class_id]

    starting_skills = validate_current_skills(entry.get("skills", ()))
    for skill in starting_skills:
        if skill.skill_id not in skills:
            raise HeroSkillRecommendationError(
                f"{hero_key} has unknown starting skill: {skill.skill_id}"
            )

    return HeroMetadata(
        key=hero_key,
        display_name=_nested_text_name(entry) or _display_name_from_key(hero_key),
        class_id=class_id,
        faction=hero_class.faction,
        affinity=hero_class.affinity,
        specialty_summary=_specialty_summary(entry.get("specialty", {})),
        starting_skills=starting_skills,
    )


def _required_mapping_value(
    entry: Mapping[str, Any],
    key: str,
    context: str,
) -> Any:
    if key not in entry:
        raise HeroSkillRecommendationError(
            f"{context} is missing required field: {key}"
        )
    return entry[key]


def _nested_text_name(entry: Mapping[str, Any]) -> Optional[str]:
    texts = entry.get("texts")
    if not isinstance(texts, Mapping):
        return None
    name = texts.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _display_name_from_key(key: str) -> str:
    words = _CAMEL_WORD_RE.sub(" ", key).replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in words.split())


def _specialty_summary(value: Any) -> str:
    if not isinstance(value, Mapping) or not value:
        return "none"

    parts = []
    for key in sorted(value):
        item = value[key]
        if key == "bonuses" and isinstance(item, Mapping):
            bonus_keys = ",".join(sorted(str(bonus_key) for bonus_key in item))
            parts.append(f"bonuses:{bonus_keys}")
        elif isinstance(item, (str, int, float, bool)) and not isinstance(
            item,
            bool,
        ):
            parts.append(f"{key}:{item}")
        elif isinstance(item, str):
            parts.append(f"{key}:{item}")
        else:
            parts.append(str(key))
    return ";".join(parts)


def _skill_offer_from_input(value: Any) -> SkillOffer:
    if isinstance(value, SkillOffer):
        return value
    if isinstance(value, Mapping):
        return SkillOffer(
            skill_id=_mapping_value(value, ("skill_id", "skill")),
            target_level=_mapping_value(value, ("target_level", "level")),
        )
    raise HeroSkillRecommendationError(
        "skill offers must be SkillOffer or mapping values"
    )


def _mapping_value(value: Mapping[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    accepted = ", ".join(keys)
    raise HeroSkillRecommendationError(f"missing required field: {accepted}")


def _normalize_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise HeroSkillRecommendationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise HeroSkillRecommendationError(f"{field_name} cannot be empty")
    return normalized


def _normalize_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HeroSkillRecommendationError("score must be a number")
    score = float(value)
    if not math.isfinite(score) or score < 0 or score > 100:
        raise HeroSkillRecommendationError("score must be between 0 and 100")
    return score


def _normalize_finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HeroSkillRecommendationError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise HeroSkillRecommendationError(f"{field_name} must be finite")
    return number


def _normalize_non_bool_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HeroSkillRecommendationError(f"{field_name} must be an integer")
    return value


def _normalize_tier(value: Any) -> str:
    tier = _normalize_non_empty_string(value, "tier").upper()
    if tier not in VALID_TIERS:
        allowed = ", ".join(VALID_TIERS)
        raise HeroSkillRecommendationError(f"tier must be one of: {allowed}")
    return tier


def _normalize_availability(value: Any) -> str:
    availability = _normalize_non_empty_string(value, "availability").lower()
    if availability not in VALID_AVAILABILITY:
        allowed = ", ".join(VALID_AVAILABILITY)
        raise HeroSkillRecommendationError(
            f"availability must be one of: {allowed}"
        )
    return availability


def _normalize_reason_codes(values: Iterable[Any]) -> Tuple[str, ...]:
    if isinstance(values, str) or isinstance(values, Mapping):
        raise HeroSkillRecommendationError(
            "reason_codes must be an iterable of strings"
        )
    if not isinstance(values, Iterable):
        raise HeroSkillRecommendationError(
            "reason_codes must be an iterable of strings"
        )
    normalized = []
    seen = set()
    for value in values:
        code = _normalize_non_empty_string(value, "reason_code").strip()
        if not _REASON_CODE_RE.match(code):
            raise HeroSkillRecommendationError(
                "reason codes must be lowercase stable identifiers"
            )
        if code in seen:
            raise HeroSkillRecommendationError(
                f"duplicate reason code: {code}"
            )
        seen.add(code)
        normalized.append(code)
    return tuple(normalized)


def _normalize_recommendation_entries(
    values: Iterable[Any],
    field_name: str,
) -> Tuple[RecommendationEntry, ...]:
    entries = tuple(values)
    for entry in entries:
        if not isinstance(entry, RecommendationEntry):
            raise HeroSkillRecommendationError(
                f"{field_name} entries must be RecommendationEntry values"
            )
    return entries


def _recommendation_entry_offer_key(entry: RecommendationEntry) -> str:
    if entry.target_level is None:
        return entry.skill_id
    return f"{entry.skill_id}:{entry.target_level}"
