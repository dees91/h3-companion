#!/usr/bin/env python3
"""Agent-facing MCP advisor helpers for H3 Companion."""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

try:
    from tools import battle_estimator, battle_estimator_gui, h3_save_parser
except ImportError:  # pragma: no cover - direct script execution fallback.
    import battle_estimator
    import battle_estimator_gui
    import h3_save_parser


ADVISOR_SCOPE_COLOR = "color"
ADVISOR_SCOPE_TEAM = "team"
ADVISOR_SCOPES = frozenset((ADVISOR_SCOPE_COLOR, ADVISOR_SCOPE_TEAM))
MAX_CONTEXT_HEROES_PER_GROUP = 12
MAX_CONTEXT_TOWNS_PER_GROUP = 12
MAX_CONTEXT_PORTAL_EXAMPLES = 12
MAX_CONTEXT_PORTAL_IDS = 12
MAX_CONTEXT_ALERTS = 8
MAX_CONTEXT_STATUS_DETAIL_CHARS = 240
ADVISOR_SCAN_SORT_DISTANCE = "distance"
ADVISOR_SCAN_SORT_EASIEST = "easiest"
ADVISOR_SCAN_SORT_MODES = frozenset((
    ADVISOR_SCAN_SORT_DISTANCE,
    ADVISOR_SCAN_SORT_EASIEST,
))


@dataclass(frozen=True)
class AdvisorContextMetadata:
    """Small read-only summary for the cached advisor domain snapshot."""

    mode: str
    autosave_dir: str
    save_file: str
    save_name: str
    save_fingerprint: dict[str, Any]
    map_file: str
    map_name: str
    map_fingerprint: dict[str, Any]
    loaded_at: str
    hero_count: int
    neutral_target_count: int
    town_count: int
    portal_count: int

    @classmethod
    def from_domain_snapshot(
        cls,
        domain_snapshot: battle_estimator_gui.DomainSnapshot,
    ) -> "AdvisorContextMetadata":
        state = domain_snapshot.state
        save_file = Path(state["save_file"])
        map_file = Path(state["map_file"])
        return cls(
            mode=state["mode"],
            autosave_dir=state["autosave_dir"],
            save_file=str(save_file),
            save_name=save_file.name,
            save_fingerprint=copy.deepcopy(state["save_fingerprint"]),
            map_file=str(map_file),
            map_name=map_file.name,
            map_fingerprint=copy.deepcopy(state["map_fingerprint"]),
            loaded_at=datetime.now(timezone.utc).isoformat(),
            hero_count=len(state.get("heroes", ())),
            neutral_target_count=len(state.get("neutral_targets", ())),
            town_count=len(state.get("town_targets", ())),
            portal_count=len(state.get("portal_targets", ())),
        )

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "mode": self.mode,
            "autosave_dir": self.autosave_dir,
            "save_file": self.save_file,
            "save_name": self.save_name,
            "save_fingerprint": self.save_fingerprint,
            "map_file": self.map_file,
            "map_name": self.map_name,
            "map_fingerprint": self.map_fingerprint,
            "loaded_at": self.loaded_at,
            "hero_count": self.hero_count,
            "neutral_target_count": self.neutral_target_count,
            "town_count": self.town_count,
            "portal_count": self.portal_count,
        })


class AdvisorContextService:
    """Read-only loader/cache for advisor domain snapshots."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        game_dir: str | Path | None = None,
        save_file: str | Path | None = None,
        map_file: str | Path | None = None,
        config_path: str | Path = h3_save_parser.CONFIG_PATH,
    ) -> None:
        self.mode = _resolve_context_mode(mode, save_file)
        self.game_dir = Path(game_dir).expanduser() if game_dir is not None else None
        self.save_file = Path(save_file).expanduser() if save_file is not None else None
        self.map_file = Path(map_file).expanduser() if map_file is not None else None
        self.config_path = Path(config_path).expanduser()
        self._lock = RLock()
        self._domain_snapshot: battle_estimator_gui.DomainSnapshot | None = None
        self._metadata: AdvisorContextMetadata | None = None

    def refresh_context(self) -> dict[str, Any]:
        """Rebuild and cache the current domain snapshot, returning metadata."""

        snapshot = battle_estimator_gui.build_domain_snapshot(
            mode=self.mode,
            autosave_dir=self.game_dir,
            save_file=self.save_file,
            map_file=self.map_file,
            config_path=self.config_path,
            removed_neutral_cache=None,
        )
        metadata = AdvisorContextMetadata.from_domain_snapshot(snapshot)
        with self._lock:
            self._domain_snapshot = snapshot
            self._metadata = metadata
        return metadata.as_dict()

    def get_domain_snapshot(
        self,
        *,
        refresh: bool = False,
    ) -> battle_estimator_gui.DomainSnapshot:
        """Return the cached domain snapshot, optionally forcing a rebuild."""

        if refresh:
            self.refresh_context()
        with self._lock:
            snapshot = self._domain_snapshot
        if snapshot is not None:
            return snapshot
        self.refresh_context()
        with self._lock:
            snapshot = self._domain_snapshot
        if snapshot is None:  # pragma: no cover - defensive guard.
            raise RuntimeError("advisor context refresh did not produce a snapshot")
        return snapshot

    def get_advisor_context(
        self,
        color_id: int,
        *,
        scope: str = ADVISOR_SCOPE_COLOR,
        refresh: bool = True,
        include_raw_ids: bool = True,
    ) -> dict[str, Any]:
        """Build a bounded strategic context for one color or team."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        metadata = self.cached_metadata()
        if metadata is None:
            metadata = AdvisorContextMetadata.from_domain_snapshot(snapshot).as_dict()
        config = h3_save_parser.load_config(self.config_path)
        return build_advisor_context(
            snapshot,
            color_id,
            scope=scope,
            include_raw_ids=include_raw_ids,
            metadata=metadata,
            config=config,
        )

    def scan_nearby(
        self,
        hero_id: str,
        *,
        radius: int = 10,
        target_type: str = "all",
        sort_mode: str = ADVISOR_SCAN_SORT_DISTANCE,
        simulations: int = battle_estimator.DEFAULT_SCAN_SIMULATIONS,
        refresh: bool = True,
        include_removed: bool = False,
        include_hidden_targets: bool = False,
    ) -> dict[str, Any]:
        """Run a read-only nearby target scan for one hero."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        config = h3_save_parser.load_config(self.config_path)
        return scan_nearby(
            snapshot,
            hero_id,
            radius=radius,
            target_type=target_type,
            sort_mode=sort_mode,
            simulations=simulations,
            config=config,
            include_removed=include_removed,
            include_hidden_targets=include_hidden_targets,
        )

    def estimate_battle(
        self,
        hero_id: str,
        target_id: str,
        *,
        simulations: int = battle_estimator.DEFAULT_SCAN_SIMULATIONS,
        refresh: bool = True,
        include_hidden_targets: bool = False,
    ) -> dict[str, Any]:
        """Estimate one read-only battle for a hero and target ID."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        config = h3_save_parser.load_config(self.config_path)
        return estimate_battle(
            snapshot,
            hero_id,
            target_id,
            simulations=simulations,
            config=config,
            include_hidden_targets=include_hidden_targets,
        )

    def find_route(
        self,
        hero_id: str,
        *,
        target_id: str | None = None,
        target_position: dict[str, int] | None = None,
        refresh: bool = True,
        include_hidden_targets: bool = False,
    ) -> dict[str, Any]:
        """Find a read-only strategic route from one hero to a target."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        config = h3_save_parser.load_config(self.config_path)
        return find_route(
            snapshot,
            hero_id,
            target_id=target_id,
            target_position=target_position,
            config=config,
            include_hidden_targets=include_hidden_targets,
        )

    def explain_portal(
        self,
        portal_id: str,
        *,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Explain one parsed portal/gate and its static directed edges."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        return explain_portal(snapshot, portal_id)

    def list_colors(
        self,
        *,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """List active map colors, teams, configured alert color, and heroes."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        config = h3_save_parser.load_config(self.config_path)
        return list_colors(snapshot, config=config)

    def get_alerts(
        self,
        color_id: int,
        *,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Return defensive town/castle alerts for one active player color."""

        snapshot = self.get_domain_snapshot(refresh=refresh)
        config = h3_save_parser.load_config(self.config_path)
        return get_alerts(snapshot, color_id, config=config)

    def cached_metadata(self) -> dict[str, Any] | None:
        """Return a defensive copy of cached snapshot metadata if loaded."""

        with self._lock:
            metadata = self._metadata
        return metadata.as_dict() if metadata is not None else None


def build_advisor_context(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    color_id: int,
    *,
    scope: str = ADVISOR_SCOPE_COLOR,
    include_raw_ids: bool = True,
    metadata: dict[str, Any] | None = None,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
) -> dict[str, Any]:
    """Build a compact advisor context from one domain snapshot."""

    normalized_color_id = _normalize_advisor_color_id(color_id)
    if scope not in ADVISOR_SCOPES:
        expected = ", ".join(sorted(ADVISOR_SCOPES))
        raise ValueError(f"invalid advisor scope {scope!r}; expected {expected}")

    state = domain_snapshot.state
    players = tuple(state.get("players", ()))
    subject = _advisor_subject(
        normalized_color_id,
        scope,
        players,
        domain_snapshot.team_by_color,
        has_explicit_team_data=_has_explicit_team_data(players),
    )
    limitations = _known_advisor_limitations(subject)
    context_metadata = (
        copy.deepcopy(metadata)
        if metadata is not None
        else AdvisorContextMetadata.from_domain_snapshot(domain_snapshot).as_dict()
    )
    alert_config = replace(
        config or h3_save_parser.BattleEstimatorConfig(),
        my_color_id=normalized_color_id,
    )
    alert_result = _advisor_alert_result(domain_snapshot, alert_config, subject)

    return {
        "subject": subject,
        "snapshot": _advisor_snapshot_section(context_metadata, state),
        "heroes": _advisor_heroes_section(
            state.get("heroes", ()),
            subject,
            include_raw_ids=include_raw_ids,
        ),
        "towns": _advisor_towns_section(
            state.get("town_targets", ()),
            subject,
            include_raw_ids=include_raw_ids,
        ),
        "alerts": _advisor_alerts_section(
            alert_result,
            include_raw_ids=include_raw_ids,
        ),
        "nearby_opportunities": _advisor_opportunity_hints(
            state.get("heroes", ()),
            subject,
            include_raw_ids=include_raw_ids,
        ),
        "portals": _advisor_portals_section(
            state.get("portal_targets", ()),
            state.get("portal_edges", ()),
            include_raw_ids=include_raw_ids,
        ),
        "routes": _advisor_route_hints(
            state.get("heroes", ()),
            state.get("town_targets", ()),
            subject,
            include_raw_ids=include_raw_ids,
        ),
        "known_limitations": limitations,
    }


def scan_nearby(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    hero_id: str,
    *,
    radius: int = 10,
    target_type: str = "all",
    sort_mode: str = ADVISOR_SCAN_SORT_DISTANCE,
    simulations: int = battle_estimator.DEFAULT_SCAN_SIMULATIONS,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
    include_removed: bool = False,
    include_hidden_targets: bool = False,
) -> dict[str, Any]:
    """Run nearby scan computation without mutating GUI/config state."""

    normalized_hero_id, selected_hero = _advisor_hero_by_id(
        domain_snapshot,
        hero_id,
    )
    normalized_radius = _bounded_advisor_int(
        radius,
        "radius",
        minimum=0,
        maximum=battle_estimator_gui.MAX_SCAN_RADIUS,
    )
    normalized_simulations = _bounded_advisor_int(
        simulations,
        "simulations",
        minimum=1,
        maximum=battle_estimator_gui.MAX_API_SIMULATIONS,
    )
    normalized_target_type = _normalize_target_type(target_type)
    normalized_sort_mode = _normalize_scan_sort_mode(sort_mode)
    hidden = _advisor_hidden_targets(
        domain_snapshot,
        config,
        selected_hero_id=normalized_hero_id,
        include_hidden_targets=include_hidden_targets,
    )
    hero_targets = h3_save_parser.build_other_hero_targets(
        domain_snapshot.heroes,
        selected_hero,
        same_level_z=selected_hero.z,
        team_by_color=domain_snapshot.team_by_color,
    )
    hero_targets = _filter_hidden_hero_targets(
        domain_snapshot,
        hero_targets,
        hidden["filtered_hero_ids"],
    )
    neutral_targets = _filter_hidden_neutral_targets(
        domain_snapshot.neutral_targets,
        hidden["filtered_neutral_ids"],
    )
    scan_targets = battle_estimator.build_nearby_scan_targets(
        selected_hero,
        neutral_targets=neutral_targets,
        hero_targets=hero_targets,
        removed_records=domain_snapshot.removed_records,
        radius=normalized_radius,
        target_type=normalized_target_type,
        include_removed=bool(include_removed),
    )
    estimates = battle_estimator.estimate_nearby_scan_targets(
        selected_hero,
        scan_targets,
        simulations=normalized_simulations,
    )
    results = [
        battle_estimator_gui._serialize_scan_estimate(domain_snapshot, estimate)
        for estimate in estimates
    ]
    results = _sort_scan_results(results, normalized_sort_mode)
    return {
        "hero_id": normalized_hero_id,
        "radius": normalized_radius,
        "target_type": normalized_target_type,
        "sort_mode": normalized_sort_mode,
        "include_removed": bool(include_removed),
        "include_hidden_targets": bool(include_hidden_targets),
        "hidden_targets": _hidden_targets_summary(
            hidden,
            include_hidden_targets=bool(include_hidden_targets),
        ),
        "simulations": normalized_simulations,
        "result_count": len(results),
        "results": results,
        "known_limitations": _base_advisor_limitations(),
    }


def estimate_battle(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    hero_id: str,
    target_id: str,
    *,
    simulations: int = battle_estimator.DEFAULT_SCAN_SIMULATIONS,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
    include_hidden_targets: bool = False,
) -> dict[str, Any]:
    """Estimate a single hero-vs-target battle without scan-radius filtering."""

    normalized_hero_id, selected_hero = _advisor_hero_by_id(
        domain_snapshot,
        hero_id,
    )
    normalized_target_id = _normalize_non_empty_text(target_id, "target_id")
    normalized_simulations = _bounded_advisor_int(
        simulations,
        "simulations",
        minimum=1,
        maximum=battle_estimator_gui.MAX_API_SIMULATIONS,
    )
    hidden = _advisor_hidden_targets(
        domain_snapshot,
        config,
        selected_hero_id=normalized_hero_id,
        include_hidden_targets=include_hidden_targets,
    )
    scan_target, resolved_target_id = _single_advisor_scan_target(
        domain_snapshot,
        selected_hero,
        normalized_target_id,
        hidden_neutral_target_ids=hidden["neutral_ids"],
        hidden_hero_target_ids=hidden["hero_ids"],
        include_hidden_targets=include_hidden_targets,
    )
    estimate = battle_estimator.estimate_nearby_scan_targets(
        selected_hero,
        (scan_target,),
        simulations=normalized_simulations,
    )[0]
    return {
        "hero_id": normalized_hero_id,
        "target_id": resolved_target_id,
        "include_hidden_targets": bool(include_hidden_targets),
        "hidden_targets": _hidden_targets_summary(
            hidden,
            include_hidden_targets=bool(include_hidden_targets),
        ),
        "simulations": normalized_simulations,
        "estimate": battle_estimator_gui._serialize_scan_estimate(
            domain_snapshot,
            estimate,
        ),
        "known_limitations": _base_advisor_limitations(),
    }


def find_route(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    hero_id: str,
    *,
    target_id: str | None = None,
    target_position: dict[str, int] | None = None,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
    include_hidden_targets: bool = False,
) -> dict[str, Any]:
    """Find a strategic route without mutating GUI/config state."""

    normalized_hero_id, selected_hero = _advisor_hero_by_id(
        domain_snapshot,
        hero_id,
    )
    if selected_hero.position is None:
        raise ValueError("selected hero has no parsed position")

    hidden = _advisor_hidden_targets(
        domain_snapshot,
        config,
        selected_hero_id=normalized_hero_id,
        include_hidden_targets=include_hidden_targets,
    )
    target, resolved_target_id, normalized_target_position = _advisor_route_target(
        domain_snapshot,
        target_id=target_id,
        target_position=target_position,
        hidden_neutral_target_ids=hidden["neutral_ids"],
        hidden_hero_target_ids=hidden["hero_ids"],
        include_hidden_targets=include_hidden_targets,
    )
    terminal_positions = list(_path_terminal_positions_for_snapshot(domain_snapshot))
    if resolved_target_id is not None:
        terminal_positions.append(target)

    request = battle_estimator_gui.build_pathfinding_request(
        selected_hero.position,
        target,
        domain_snapshot.state["route_layers"],
        portal_targets=domain_snapshot.portal_targets,
        portal_edges=domain_snapshot.portal_edges,
        terminal_positions=terminal_positions,
    )
    result = battle_estimator_gui.find_path_route(request)
    payload = battle_estimator_gui._serialize_pathfinding_result(result)
    portal_segments = [
        segment
        for segment in payload["segments"]
        if segment.get("segment_type") == battle_estimator_gui.PATH_SEGMENT_PORTAL
    ]
    payload.update({
        "hero_id": normalized_hero_id,
        "include_hidden_targets": bool(include_hidden_targets),
        "hidden_targets": _hidden_targets_summary(
            hidden,
            include_hidden_targets=bool(include_hidden_targets),
        ),
        "portal_segments": portal_segments,
        "uses_portals": bool(portal_segments),
        "has_non_deterministic_portal": any(
            segment.get("is_non_deterministic")
            for segment in portal_segments
        ),
        "fallback_status": _route_fallback_status(payload),
        "known_limitations": _base_advisor_limitations(),
    })
    if resolved_target_id is not None:
        payload["target_id"] = resolved_target_id
    else:
        payload["target_position"] = normalized_target_position
    return payload


def explain_portal(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    portal_id: str,
) -> dict[str, Any]:
    """Explain a portal from raw parsed portal targets and edges."""

    normalized_portal_id = _normalize_non_empty_text(portal_id, "portal_id")
    portal_by_object_index = {
        portal.object_index: portal
        for portal in domain_snapshot.portal_targets
    }
    portal_by_id = {
        battle_estimator_gui._portal_target_id(portal): portal
        for portal in domain_snapshot.portal_targets
    }
    portal = portal_by_id.get(normalized_portal_id)
    if portal is None:
        raise ValueError(f"unknown portal_id: {normalized_portal_id}")

    outgoing_counts = Counter(
        (edge.source_object_index, edge.channel_key)
        for edge in domain_snapshot.portal_edges
    )
    outbound_edges = tuple(
        edge
        for edge in domain_snapshot.portal_edges
        if edge.source_object_index == portal.object_index
    )
    inbound_edges = tuple(
        edge
        for edge in domain_snapshot.portal_edges
        if edge.destination_object_index == portal.object_index
    )
    outbound = [
        _portal_edge_explanation(edge, portal_by_object_index, outgoing_counts)
        for edge in outbound_edges
    ]
    inbound = [
        _portal_edge_explanation(edge, portal_by_object_index, outgoing_counts)
        for edge in inbound_edges
    ]
    bounded_outbound = outbound[:MAX_CONTEXT_PORTAL_IDS]
    bounded_inbound = inbound[:MAX_CONTEXT_PORTAL_IDS]
    return {
        "portal_id": normalized_portal_id,
        "position": _target_position_payload(portal),
        "anchor_position": {
            "x": portal.anchor_x,
            "y": portal.anchor_y,
            "z": portal.anchor_z,
        },
        "object_index": portal.object_index,
        "object_id": portal.object_id,
        "h3m_subid": portal.h3m_subid,
        "portal_type": portal.portal_type,
        "role": portal.role,
        "channel_key": portal.channel_key,
        "destination_count": len(outbound),
        "source_count": len(inbound),
        "outbound_destinations": bounded_outbound,
        "inbound_sources": bounded_inbound,
        "outbound_omitted_count": max(0, len(outbound) - len(bounded_outbound)),
        "inbound_omitted_count": max(0, len(inbound) - len(bounded_inbound)),
        "unresolved_outbound_count": sum(
            1 for edge in outbound if edge["unresolved_destination"]
        ),
        "unresolved_inbound_count": sum(
            1 for edge in inbound if edge["unresolved_source"]
        ),
        "cross_level_destination_count": sum(
            1 for edge in outbound if edge["cross_level"] is True
        ),
        "cross_level_source_count": sum(
            1 for edge in inbound if edge["cross_level"] is True
        ),
        "is_non_deterministic": any(
            edge["is_non_deterministic"] for edge in outbound
        ),
        "known_limitations": _base_advisor_limitations(),
    }


def list_colors(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    *,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
) -> dict[str, Any]:
    """Return active color/team facts and detected heroes grouped by owner."""

    loaded_config = config or h3_save_parser.BattleEstimatorConfig()
    players = tuple(domain_snapshot.state.get("players", ()))
    active_players = tuple(
        player for player in players if player.get("enabled", False)
    )
    active_color_ids = {
        int(player["player_index"])
        for player in active_players
        if "player_index" in player
    }
    heroes_by_color: dict[int, list[dict[str, Any]]] = {
        int(player["player_index"]): []
        for player in active_players
        if "player_index" in player
    }
    unknown_owner_heroes = []
    for hero in sorted(domain_snapshot.state.get("heroes", ()), key=_hero_sort_key):
        owner_color_id = hero.get("owner_color_id")
        hero_ref = _hero_tool_reference(hero, include_raw_ids=True)
        if owner_color_id in heroes_by_color:
            heroes_by_color[owner_color_id].append(hero_ref)
        elif owner_color_id is None:
            unknown_owner_heroes.append(hero_ref)

    return {
        "configured_my_color_id": loaded_config.my_color_id,
        "configured_my_color_name": _player_color_name(loaded_config.my_color_id)
        if loaded_config.my_color_id is not None
        else None,
        "configured_my_color_available": (
            loaded_config.my_color_id in active_color_ids
            if loaded_config.my_color_id is not None
            else False
        ),
        "alert_radius": loaded_config.alert_radius,
        "active_colors": [
            _color_listing(player, heroes_by_color)
            for player in active_players
        ],
        "teams": copy.deepcopy(domain_snapshot.state.get("teams", ())),
        "unknown_owner_heroes": _bounded_items(
            unknown_owner_heroes,
            MAX_CONTEXT_HEROES_PER_GROUP,
        ),
    }


def get_alerts(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    color_id: int,
    *,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
    include_raw_ids: bool = True,
) -> dict[str, Any]:
    """Return defensive alerts and town ownership availability for one color."""

    normalized_color_id = _normalize_advisor_color_id(color_id)
    state = domain_snapshot.state
    players = tuple(state.get("players", ()))
    subject = _advisor_subject(
        normalized_color_id,
        ADVISOR_SCOPE_COLOR,
        players,
        domain_snapshot.team_by_color,
        has_explicit_team_data=_has_explicit_team_data(players),
    )
    loaded_config = config or h3_save_parser.BattleEstimatorConfig()
    alert_config = replace(loaded_config, my_color_id=normalized_color_id)
    alert_result = _advisor_alert_result(domain_snapshot, alert_config, subject)
    return {
        "color_id": normalized_color_id,
        "color_name": subject["color_name"],
        "team_id": subject["team_id"],
        "alert_radius": alert_config.alert_radius,
        "alerts": _advisor_alerts_section(
            alert_result,
            include_raw_ids=include_raw_ids,
        ),
        "town_ownership": _town_ownership_summary(
            domain_snapshot,
            normalized_color_id,
        ),
        "known_limitations": _base_advisor_limitations(),
    }


def _color_listing(
    player: dict[str, Any],
    heroes_by_color: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    color_id = int(player["player_index"])
    heroes = heroes_by_color.get(color_id, [])
    return {
        "color_id": color_id,
        "color_name": player.get("color_name") or _player_color_name(color_id),
        "team_id": player.get("team_id"),
        "can_human_play": player.get("can_human_play"),
        "can_computer_play": player.get("can_computer_play"),
        "main_town_position": copy.deepcopy(player.get("main_town_position")),
        "random_hero": player.get("random_hero"),
        "hero_count": len(heroes),
        "heroes": _bounded_items(heroes, MAX_CONTEXT_HEROES_PER_GROUP),
    }


def _town_ownership_summary(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    color_id: int,
) -> dict[str, Any]:
    status_counts = Counter()
    unavailable_town_ids = []
    available_subject_owned_count = 0
    for town in domain_snapshot.town_targets:
        town_id = battle_estimator_gui._town_target_id(town)
        ownership = domain_snapshot.town_ownership_by_id.get(town_id)
        status = (
            h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE
            if ownership is None
            else ownership.ownership_status
        )
        status_counts[status] += 1
        if status == h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE:
            unavailable_town_ids.append(town_id)
        elif (
            ownership is not None
            and ownership.current_owner_color_id == color_id
        ):
            available_subject_owned_count += 1

    bounded_unavailable = unavailable_town_ids[:MAX_CONTEXT_TOWNS_PER_GROUP]
    return {
        "total_towns": len(domain_snapshot.town_targets),
        "status_counts": dict(sorted(status_counts.items())),
        "partial": bool(unavailable_town_ids),
        "available_subject_owned_count": available_subject_owned_count,
        "unavailable_town_ids": bounded_unavailable,
        "unavailable_omitted_count": max(
            0,
            len(unavailable_town_ids) - len(bounded_unavailable),
        ),
    }


def _advisor_route_target(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    *,
    target_id: str | None,
    target_position: dict[str, int] | None,
    hidden_neutral_target_ids: tuple[str, ...],
    hidden_hero_target_ids: tuple[str, ...],
    include_hidden_targets: bool,
) -> tuple[dict[str, Any], str | None, dict[str, int] | None]:
    has_target_id = target_id is not None
    has_target_position = target_position is not None
    if has_target_id == has_target_position:
        raise ValueError("provide exactly one of target_position or target_id")

    if has_target_position:
        normalized_position = _strict_target_position(
            target_position,
            "target_position",
        )
        return normalized_position, None, normalized_position

    normalized_target_id = _normalize_non_empty_text(target_id, "target_id")
    target = _advisor_route_marker_target_by_id(
        domain_snapshot,
        normalized_target_id,
        hidden_neutral_target_ids=hidden_neutral_target_ids,
        hidden_hero_target_ids=hidden_hero_target_ids,
        include_hidden_targets=include_hidden_targets,
    )
    return target, normalized_target_id, None


def _strict_target_position(value, name: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object with x, y, z")
    if set(value) != {"x", "y", "z"}:
        raise ValueError(f"{name} must contain exactly x, y, z")
    return {
        coordinate: _path_coordinate(value[coordinate], f"{name}.{coordinate}")
        for coordinate in ("x", "y", "z")
    }


def _path_coordinate(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _advisor_route_marker_target_by_id(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    target_id: str,
    *,
    hidden_neutral_target_ids: tuple[str, ...],
    hidden_hero_target_ids: tuple[str, ...],
    include_hidden_targets: bool,
) -> dict[str, Any]:
    neutral = domain_snapshot.neutral_by_id.get(target_id)
    if neutral is not None:
        hidden = target_id in set(hidden_neutral_target_ids)
        if hidden and not include_hidden_targets:
            raise ValueError(f"unknown target_id: {target_id}")
        return battle_estimator_gui._serialize_neutral_target(
            neutral,
            hidden=hidden,
        )

    hero = domain_snapshot.hero_by_id.get(target_id)
    if hero is not None:
        hidden = target_id in set(hidden_hero_target_ids)
        if hidden and not include_hidden_targets:
            raise ValueError(f"unknown target_id: {target_id}")
        return battle_estimator_gui._serialize_hero(
            hero,
            target_id,
            domain_snapshot.team_by_color,
            hidden=hidden,
        )

    for town in domain_snapshot.town_targets:
        if battle_estimator_gui._town_target_id(town) == target_id:
            return battle_estimator_gui._serialize_town_target(
                town,
                domain_snapshot.town_ownership_by_id.get(target_id),
            )

    for portal in domain_snapshot.portal_targets:
        if battle_estimator_gui._portal_target_id(portal) == target_id:
            return battle_estimator_gui._serialize_portal_target(portal)

    raise ValueError(f"unknown target_id: {target_id}")


def _path_terminal_positions_for_snapshot(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
) -> tuple[battle_estimator_gui.PathPosition, ...]:
    return tuple(
        battle_estimator_gui.PathPosition(target.x, target.y, target.z)
        for target in domain_snapshot.town_targets
    )


def _route_fallback_status(route_payload: dict[str, Any]) -> str:
    if route_payload.get("status") != battle_estimator_gui.PATH_STATUS_FOUND:
        return "not_found"
    requested = route_payload.get("requested_target_position")
    resolved = route_payload.get("resolved_target_position")
    if resolved is None:
        return "not_found"
    if resolved == requested:
        return "exact"
    return "resolved_neighbor"


def _portal_edge_explanation(
    edge,
    portal_by_object_index: dict[int, Any],
    outgoing_counts: Counter,
) -> dict[str, Any]:
    source = portal_by_object_index.get(edge.source_object_index)
    destination = portal_by_object_index.get(edge.destination_object_index)
    cross_level = (
        None
        if source is None or destination is None
        else source.z != destination.z
    )
    return {
        "source_id": _portal_id_from_object_index(edge.source_object_index),
        "destination_id": _portal_id_from_object_index(edge.destination_object_index),
        "source_object_index": edge.source_object_index,
        "destination_object_index": edge.destination_object_index,
        "source_position": (
            None if source is None else _target_position_payload(source)
        ),
        "destination_position": (
            None if destination is None else _target_position_payload(destination)
        ),
        "portal_type": edge.portal_type,
        "channel_key": edge.channel_key,
        "h3m_subid": edge.h3m_subid,
        "cross_level": cross_level,
        "is_non_deterministic": (
            outgoing_counts[(edge.source_object_index, edge.channel_key)] > 1
        ),
        "unresolved_source": source is None,
        "unresolved_destination": destination is None,
    }


def _portal_id_from_object_index(object_index: int) -> str:
    return f"portal:{object_index}"


def _target_position_payload(target) -> dict[str, int]:
    return {"x": target.x, "y": target.y, "z": target.z}


def _advisor_hero_by_id(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    hero_id: str,
) -> tuple[str, h3_save_parser.HeroArmy]:
    normalized_hero_id = _normalize_non_empty_text(hero_id, "hero_id")
    hero = domain_snapshot.hero_by_id.get(normalized_hero_id)
    if hero is None:
        raise ValueError(f"unknown hero_id: {normalized_hero_id}")
    return normalized_hero_id, hero


def _normalize_non_empty_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bounded_advisor_int(value: int, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _normalize_target_type(target_type: str) -> str:
    normalized = _normalize_non_empty_text(target_type, "target_type")
    if normalized not in battle_estimator.VALID_SCAN_TARGET_TYPES:
        expected = ", ".join(battle_estimator.VALID_SCAN_TARGET_TYPES)
        raise ValueError(f"invalid target_type {normalized!r}; expected {expected}")
    return normalized


def _normalize_scan_sort_mode(sort_mode: str) -> str:
    normalized = _normalize_non_empty_text(sort_mode, "sort_mode")
    if normalized not in ADVISOR_SCAN_SORT_MODES:
        expected = ", ".join(sorted(ADVISOR_SCAN_SORT_MODES))
        raise ValueError(f"invalid sort_mode {normalized!r}; expected {expected}")
    return normalized


def _advisor_hidden_targets(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    config: h3_save_parser.BattleEstimatorConfig | None,
    *,
    selected_hero_id: str,
    include_hidden_targets: bool,
) -> dict[str, tuple[str, ...]]:
    loaded_config = config or h3_save_parser.BattleEstimatorConfig()
    neutral_ids = battle_estimator_gui._hidden_neutral_target_ids_for_config(
        loaded_config,
        domain_snapshot,
    )
    hero_ids = battle_estimator_gui._hidden_hero_target_ids_for_config(
        loaded_config,
        domain_snapshot,
        selected_hero_id,
    )
    if include_hidden_targets:
        return {
            "neutral_ids": tuple(neutral_ids),
            "hero_ids": tuple(hero_ids),
            "filtered_neutral_ids": (),
            "filtered_hero_ids": (),
        }
    return {
        "neutral_ids": tuple(neutral_ids),
        "hero_ids": tuple(hero_ids),
        "filtered_neutral_ids": tuple(neutral_ids),
        "filtered_hero_ids": tuple(hero_ids),
    }


def _hidden_targets_summary(
    hidden: dict[str, tuple[str, ...]],
    *,
    include_hidden_targets: bool,
) -> dict[str, Any]:
    summary = {
        "neutral_count": len(hidden["neutral_ids"]),
        "hero_count": len(hidden["hero_ids"]),
        "filtered_neutral_count": len(hidden["filtered_neutral_ids"]),
        "filtered_hero_count": len(hidden["filtered_hero_ids"]),
    }
    if include_hidden_targets:
        summary["neutral_ids"] = list(hidden["neutral_ids"])
        summary["hero_ids"] = list(hidden["hero_ids"])
    return summary


def _filter_hidden_neutral_targets(neutral_targets, hidden: tuple[str, ...]) -> tuple:
    hidden_ids = set(hidden)
    return tuple(
        target
        for target in neutral_targets
        if battle_estimator_gui._neutral_target_id(target) not in hidden_ids
    )


def _filter_hidden_hero_targets(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    hero_targets,
    hidden: tuple[str, ...],
) -> tuple:
    hidden_ids = set(hidden)
    return tuple(
        target
        for target in hero_targets
        if battle_estimator_gui._hero_id_for_army(domain_snapshot, target.army)
        not in hidden_ids
    )


def _single_advisor_scan_target(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    selected_hero: h3_save_parser.HeroArmy,
    target_id: str,
    *,
    hidden_neutral_target_ids: tuple[str, ...],
    hidden_hero_target_ids: tuple[str, ...],
    include_hidden_targets: bool,
):
    neutral = domain_snapshot.neutral_by_id.get(target_id)
    if neutral is not None:
        if target_id in set(hidden_neutral_target_ids) and not include_hidden_targets:
            raise ValueError(f"unknown target_id: {target_id}")
        return (
            battle_estimator_gui._scan_target_for_raw_target(
                "neutral",
                selected_hero,
                neutral,
            ),
            target_id,
        )

    hero_target = _advisor_hero_target_by_id(
        domain_snapshot,
        selected_hero,
        target_id,
    )
    if hero_target is not None:
        if target_id in set(hidden_hero_target_ids) and not include_hidden_targets:
            raise ValueError(f"unknown target_id: {target_id}")
        return (
            battle_estimator_gui._scan_target_for_raw_target(
                "hero",
                selected_hero,
                hero_target,
            ),
            target_id,
        )

    raise ValueError(f"unknown target_id: {target_id}")


def _advisor_hero_target_by_id(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    selected_hero: h3_save_parser.HeroArmy,
    target_id: str,
):
    hero_targets = h3_save_parser.build_other_hero_targets(
        domain_snapshot.heroes,
        selected_hero,
        same_level_z=None,
        team_by_color=domain_snapshot.team_by_color,
    )
    for hero_target in hero_targets:
        if battle_estimator_gui._hero_id_for_army(
            domain_snapshot,
            hero_target.army,
        ) == target_id:
            return hero_target
    return None


def _sort_scan_results(results: list[dict[str, Any]], sort_mode: str) -> list[dict[str, Any]]:
    if sort_mode == ADVISOR_SCAN_SORT_DISTANCE:
        return results
    return sorted(results, key=_easiest_scan_sort_key)


def _easiest_scan_sort_key(result: dict[str, Any]) -> tuple:
    win_pct = result.get("win_pct")
    has_no_win_pct = not isinstance(win_pct, (int, float)) or isinstance(win_pct, bool)
    distance = result.get("distance")
    if isinstance(distance, bool) or not isinstance(distance, int):
        distance = battle_estimator_gui.MAX_SCAN_RADIUS + 1
    target_id = result.get("target_id")
    has_no_target_id = target_id is None
    return (
        has_no_win_pct,
        0 if has_no_win_pct else -float(win_pct),
        distance,
        has_no_target_id,
        "" if has_no_target_id else str(target_id),
    )


def _normalize_advisor_color_id(color_id: int) -> int:
    if isinstance(color_id, bool) or not isinstance(color_id, int):
        raise ValueError("color_id must be an integer player color id")
    if color_id < 0 or color_id >= len(h3_save_parser.PLAYER_COLOR_NAMES):
        raise ValueError("color_id must be between 0 and 7")
    return color_id


def _advisor_subject(
    color_id: int,
    scope: str,
    players,
    team_by_color: dict[int, int],
    *,
    has_explicit_team_data: bool,
) -> dict[str, Any]:
    player_by_id = {
        int(player["player_index"]): player
        for player in players
        if "player_index" in player
    }
    player = player_by_id.get(color_id)
    if not player or not player.get("enabled", False):
        raise ValueError(f"color_id {color_id} is not an active map player")

    active_color_ids = tuple(
        sorted(
            int(candidate["player_index"])
            for candidate in players
            if candidate.get("enabled", False)
        )
    )
    team_id = team_by_color.get(color_id) if has_explicit_team_data else None
    allied_color_ids = tuple(
        candidate_id
        for candidate_id in active_color_ids
        if candidate_id != color_id
        and has_explicit_team_data
        and team_by_color.get(candidate_id) == team_id
    ) if team_id is not None else ()
    subject_color_ids = (
        (color_id, *allied_color_ids)
        if scope == ADVISOR_SCOPE_TEAM
        else (color_id,)
    )
    return {
        "scope": scope,
        "color_id": color_id,
        "color_name": player.get("color_name") or _player_color_name(color_id),
        "team_id": team_id,
        "team_scope_available": team_id is not None,
        "allied_color_ids": list(allied_color_ids),
        "allied_color_names": [
            _player_color_name(candidate_id) for candidate_id in allied_color_ids
        ],
        "subject_color_ids": list(subject_color_ids),
        "subject_color_names": [
            _player_color_name(candidate_id) for candidate_id in subject_color_ids
        ],
        "active_color_ids": list(active_color_ids),
        "active_color_names": [
            _player_color_name(candidate_id) for candidate_id in active_color_ids
        ],
    }


def _has_explicit_team_data(players) -> bool:
    team_counts = Counter(
        player.get("team_id")
        for player in players
        if player.get("enabled", False) and player.get("team_id") is not None
    )
    return any(count > 1 for count in team_counts.values())


def _advisor_snapshot_section(metadata: dict[str, Any], state: dict) -> dict[str, Any]:
    return {
        "mode": metadata.get("mode", state.get("mode")),
        "autosave_dir": metadata.get("autosave_dir", state.get("autosave_dir")),
        "save_file": metadata.get("save_file", state.get("save_file")),
        "save_name": metadata.get("save_name"),
        "save_fingerprint": metadata.get("save_fingerprint"),
        "map_file": metadata.get("map_file", state.get("map_file")),
        "map_name": metadata.get("map_name"),
        "map_fingerprint": metadata.get("map_fingerprint"),
        "loaded_at": metadata.get("loaded_at"),
        "map": copy.deepcopy(state.get("map", {})),
        "counts": {
            "heroes": metadata.get("hero_count", len(state.get("heroes", ()))),
            "neutral_targets": metadata.get(
                "neutral_target_count",
                len(state.get("neutral_targets", ())),
            ),
            "towns": metadata.get("town_count", len(state.get("town_targets", ()))),
            "portals": metadata.get(
                "portal_count",
                len(state.get("portal_targets", ())),
            ),
        },
    }


def _advisor_heroes_section(
    heroes,
    subject: dict[str, Any],
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    groups = {"own": [], "allied": [], "enemy": [], "unknown": []}
    for hero in sorted(heroes, key=_hero_sort_key):
        relation = _hero_relation(hero, subject)
        groups[relation].append(
            _compact_hero(hero, include_raw_ids=include_raw_ids),
        )
    return {
        relation: _bounded_items(items, MAX_CONTEXT_HEROES_PER_GROUP)
        for relation, items in groups.items()
    }


def _hero_relation(hero: dict, subject: dict[str, Any]) -> str:
    owner_color_id = hero.get("owner_color_id")
    if owner_color_id is None:
        return "unknown"
    if owner_color_id == subject["color_id"]:
        return "own"
    if owner_color_id in set(subject["allied_color_ids"]):
        return "allied"
    return "enemy"


def _compact_hero(hero: dict, *, include_raw_ids: bool) -> dict[str, Any]:
    combat_context = hero.get("combat_context") or {}
    compact = _maybe_with_id({
        "name": hero.get("name"),
        "position": copy.deepcopy(hero.get("position")),
        "owner_color_id": hero.get("owner_color_id"),
        "owner_color_name": hero.get("owner_color_name"),
        "team_id": hero.get("team_id"),
        "ai_value": hero.get("ai_value", 0),
        "total_creatures": hero.get("total_creatures", 0),
        "army_summary": hero.get("army_summary"),
        "army": [
            {
                "creature_name": stack.get("creature_name"),
                "count": stack.get("count"),
            }
            for stack in hero.get("army", ())
        ],
        "combat_context": {
            "status": combat_context.get("status"),
            "source": combat_context.get("source"),
            "reason": combat_context.get("reason"),
            "primary": copy.deepcopy(combat_context.get("primary")),
            "passive_modifiers": copy.deepcopy(
                combat_context.get("passive_modifiers", {}),
            ),
        },
    }, hero.get("id"), include_raw_ids)
    return compact


def _advisor_towns_section(
    towns,
    subject: dict[str, Any],
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    subject_color_ids = set(subject["subject_color_ids"])
    grouped = {"subject_owned": [], "other": [], "ownership_unavailable": []}
    for town in sorted(towns, key=lambda item: (item.get("object_index", 0), item.get("id", ""))):
        compact = _compact_town(town, include_raw_ids=include_raw_ids)
        status = town.get("ownership_status")
        owner_color_id = town.get("current_owner_color_id")
        if status == h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE:
            grouped["ownership_unavailable"].append(compact)
        elif owner_color_id in subject_color_ids:
            grouped["subject_owned"].append(compact)
        else:
            grouped["other"].append(compact)
    return {
        group: _bounded_items(items, MAX_CONTEXT_TOWNS_PER_GROUP)
        for group, items in grouped.items()
    }


def _compact_town(town: dict, *, include_raw_ids: bool) -> dict[str, Any]:
    return _maybe_with_id({
        "name": town.get("custom_name") or town.get("id"),
        "position": copy.deepcopy(town.get("position")),
        "current_owner_color_id": town.get("current_owner_color_id"),
        "current_owner_color_name": town.get("current_owner_color_name"),
        "initial_owner": town.get("initial_owner"),
        "initial_owner_color_name": town.get("initial_owner_color_name"),
        "ownership_status": town.get("ownership_status"),
        "ownership_reason": town.get("ownership_reason"),
    }, town.get("id"), include_raw_ids)


def _advisor_alerts_section(
    alert_result: battle_estimator_gui.CastleAlertResult,
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    alert_items = [
        _compact_alert(alert, include_raw_ids=include_raw_ids)
        for alert in alert_result.alerts[:MAX_CONTEXT_ALERTS]
    ]
    return {
        "status": alert_result.status,
        "status_detail": _bounded_text(
            alert_result.status_detail,
            MAX_CONTEXT_STATUS_DETAIL_CHARS,
        ),
        "count": len(alert_result.alerts),
        "items": alert_items,
        "omitted_count": max(0, len(alert_result.alerts) - len(alert_items)),
    }


def _advisor_alert_result(
    domain_snapshot: battle_estimator_gui.DomainSnapshot,
    config: h3_save_parser.BattleEstimatorConfig,
    subject: dict[str, Any],
) -> battle_estimator_gui.CastleAlertResult:
    if subject["scope"] != ADVISOR_SCOPE_TEAM:
        return battle_estimator_gui.build_castle_alerts(domain_snapshot, config)

    results = tuple(
        battle_estimator_gui.build_castle_alerts(
            domain_snapshot,
            replace(config, my_color_id=color_id),
        )
        for color_id in subject["subject_color_ids"]
    )
    alerts = tuple(alert for result in results for alert in result.alerts)
    if alerts:
        return battle_estimator_gui.CastleAlertResult(
            battle_estimator_gui.CASTLE_ALERT_STATUS_OK,
            alerts=alerts,
        )

    statuses = tuple(result.status for result in results)
    if battle_estimator_gui.CASTLE_ALERT_STATUS_OWNERSHIP_UNAVAILABLE in statuses:
        details = tuple(
            _bounded_text(result.status_detail, MAX_CONTEXT_STATUS_DETAIL_CHARS)
            for result in results
            if result.status_detail
        )
        return battle_estimator_gui.CastleAlertResult(
            battle_estimator_gui.CASTLE_ALERT_STATUS_OWNERSHIP_UNAVAILABLE,
            status_detail="; ".join(details) or None,
        )
    if battle_estimator_gui.CASTLE_ALERT_STATUS_UNCONFIGURED in statuses:
        return battle_estimator_gui.CastleAlertResult(
            battle_estimator_gui.CASTLE_ALERT_STATUS_UNCONFIGURED,
        )
    if all(
        status == battle_estimator_gui.CASTLE_ALERT_STATUS_NO_OWNED_TOWNS
        for status in statuses
    ):
        return battle_estimator_gui.CastleAlertResult(
            battle_estimator_gui.CASTLE_ALERT_STATUS_NO_OWNED_TOWNS,
        )
    return battle_estimator_gui.CastleAlertResult(
        battle_estimator_gui.CASTLE_ALERT_STATUS_NO_THREATS,
    )


def _compact_alert(
    alert: battle_estimator_gui.CastleAlert,
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    compact = {
        "enemy_hero_name": alert.enemy_hero_name,
        "enemy_color_id": alert.enemy_color_id,
        "enemy_color_name": alert.enemy_color_name,
        "town_name": alert.town_name,
        "distance": alert.distance,
        "other_towns_in_radius": alert.other_towns_in_radius,
        "enemy_position": battle_estimator_gui._serialize_position(
            alert.enemy_position,
        ),
        "town_position": battle_estimator_gui._serialize_position(
            alert.town_position,
        ),
    }
    if include_raw_ids:
        compact.update({
            "id": alert.id,
            "enemy_hero_id": alert.enemy_hero_id,
            "town_id": alert.town_id,
        })
    return compact


def _advisor_opportunity_hints(
    heroes,
    subject: dict[str, Any],
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    subject_colors = set(subject["subject_color_ids"])
    candidates = [
        _hero_tool_reference(hero, include_raw_ids=include_raw_ids)
        for hero in sorted(heroes, key=_hero_sort_key)
        if hero.get("owner_color_id") in subject_colors and hero.get("position")
    ]
    return {
        "status": "not_computed",
        "tool_hint": "scan_nearby",
        "candidate_heroes": _bounded_items(candidates, MAX_CONTEXT_HEROES_PER_GROUP),
    }


def _advisor_portals_section(
    portals,
    portal_edges,
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    portal_by_id = {portal.get("id"): portal for portal in portals}
    by_role = Counter(portal.get("role") or "unknown" for portal in portals)
    edges_by_source = defaultdict(list)
    cross_level_edges = 0
    for edge in portal_edges:
        edges_by_source[edge.get("source_id")].append(edge)
        source = portal_by_id.get(edge.get("source_id"))
        destination = portal_by_id.get(edge.get("destination_id"))
        source_z = (source.get("position") or {}).get("z") if source else None
        destination_z = (
            (destination.get("position") or {}).get("z") if destination else None
        )
        if source_z is not None and destination_z is not None and source_z != destination_z:
            cross_level_edges += 1

    non_deterministic_sources = sorted(
        source_id
        for source_id, edges in edges_by_source.items()
        if source_id and len(edges) > 1
    )
    examples = [
        _compact_portal(portal, edges_by_source, include_raw_ids=include_raw_ids)
        for portal in sorted(portals, key=lambda item: (item.get("object_index", 0), item.get("id", "")))
    ][:MAX_CONTEXT_PORTAL_EXAMPLES]
    return {
        "total": len(portals),
        "edge_count": len(portal_edges),
        "cross_level_edge_count": cross_level_edges,
        "non_deterministic_source_ids": non_deterministic_sources[:MAX_CONTEXT_PORTAL_IDS]
        if include_raw_ids
        else [],
        "non_deterministic_source_omitted_count": max(
            0,
            len(non_deterministic_sources) - MAX_CONTEXT_PORTAL_IDS,
        ),
        "by_role": dict(sorted(by_role.items())),
        "examples": examples,
        "omitted_count": max(0, len(portals) - len(examples)),
    }


def _compact_portal(portal: dict, edges_by_source, *, include_raw_ids: bool) -> dict[str, Any]:
    outgoing = edges_by_source.get(portal.get("id"), ())
    destination_ids = [edge.get("destination_id") for edge in outgoing]
    return _maybe_with_id({
        "position": copy.deepcopy(portal.get("position")),
        "portal_type": portal.get("portal_type"),
        "role": portal.get("role"),
        "channel_key": portal.get("channel_key"),
        "destination_count": len(outgoing),
        "destination_ids": destination_ids[:MAX_CONTEXT_PORTAL_IDS]
        if include_raw_ids
        else [],
        "destination_omitted_count": max(
            0,
            len(destination_ids) - MAX_CONTEXT_PORTAL_IDS,
        ),
    }, portal.get("id"), include_raw_ids)


def _advisor_route_hints(
    heroes,
    towns,
    subject: dict[str, Any],
    *,
    include_raw_ids: bool,
) -> dict[str, Any]:
    subject_colors = set(subject["subject_color_ids"])
    candidate_heroes = [
        _hero_tool_reference(hero, include_raw_ids=include_raw_ids)
        for hero in sorted(heroes, key=_hero_sort_key)
        if hero.get("owner_color_id") in subject_colors and hero.get("position")
    ][:MAX_CONTEXT_HEROES_PER_GROUP]
    owned_towns = [
        _compact_town(town, include_raw_ids=include_raw_ids)
        for town in towns
        if town.get("current_owner_color_id") in subject_colors
    ][:MAX_CONTEXT_TOWNS_PER_GROUP]
    return {
        "status": "not_computed",
        "tool_hint": "find_route",
        "candidate_heroes": candidate_heroes,
        "subject_towns": owned_towns,
    }


def _hero_tool_reference(hero: dict, *, include_raw_ids: bool) -> dict[str, Any]:
    return _maybe_with_id({
        "name": hero.get("name"),
        "position": copy.deepcopy(hero.get("position")),
        "ai_value": hero.get("ai_value", 0),
    }, hero.get("id"), include_raw_ids)


def _base_advisor_limitations() -> list[dict[str, str]]:
    return [
        {
            "id": "fog_of_war",
            "detail": "Fog of war and hidden enemy information are not modeled.",
        },
        {
            "id": "movement_points",
            "detail": "Exact movement points, roads, terrain costs, boats, and spells are not modeled.",
        },
        {
            "id": "battle_model",
            "detail": "Artifacts, active spells, morale/luck, tactics, terrain, and many special abilities remain simplified or omitted.",
        },
        {
            "id": "save_parsing",
            "detail": "Save parsing is best-effort for observed GM1/GM2 structures; unavailable fields are reported explicitly.",
        },
    ]


def _known_advisor_limitations(subject: dict[str, Any]) -> list[dict[str, str]]:
    limitations = _base_advisor_limitations()
    if subject["scope"] == ADVISOR_SCOPE_TEAM and not subject["team_scope_available"]:
        limitations.append({
            "id": "team_scope_unavailable",
            "detail": "Team scope was requested, but the map has no team data for this color.",
        })
    return limitations


def _bounded_items(items: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        "items": items[:limit],
        "total_count": len(items),
        "omitted_count": max(0, len(items) - limit),
    }


def _bounded_text(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:max(0, limit - 3)].rstrip() + "..."


def _maybe_with_id(
    payload: dict[str, Any],
    raw_id: str | None,
    include_raw_ids: bool,
) -> dict[str, Any]:
    if include_raw_ids and raw_id is not None:
        return {"id": raw_id, **payload}
    return payload


def _hero_sort_key(hero: dict) -> tuple:
    return (
        -(hero.get("ai_value") or 0),
        hero.get("name") or "",
        hero.get("id") or "",
    )


def _player_color_name(color_id: int) -> str:
    if 0 <= color_id < len(h3_save_parser.PLAYER_COLOR_NAMES):
        return h3_save_parser.PLAYER_COLOR_NAMES[color_id]
    return f"color:{color_id}"


def _resolve_context_mode(mode: str | None, save_file: str | Path | None) -> str:
    if mode is None:
        return (
            battle_estimator_gui.PINNED_MODE
            if save_file is not None
            else battle_estimator_gui.FOLLOW_LATEST_MODE
        )
    if mode == battle_estimator_gui.FOLLOW_LATEST_MODE and save_file is not None:
        raise ValueError("save_file requires pinned mode or mode=None")
    if mode not in {
        battle_estimator_gui.FOLLOW_LATEST_MODE,
        battle_estimator_gui.PINNED_MODE,
    }:
        expected = ", ".join((
            battle_estimator_gui.FOLLOW_LATEST_MODE,
            battle_estimator_gui.PINNED_MODE,
        ))
        raise ValueError(f"invalid mode {mode!r}; expected {expected}")
    return mode
