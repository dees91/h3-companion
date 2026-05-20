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
    if isinstance(values, str):
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
