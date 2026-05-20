#!/usr/bin/env python3
"""Contracts for battle-estimator hero secondary-skill recommendations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
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

_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


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
