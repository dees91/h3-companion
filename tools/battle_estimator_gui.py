#!/usr/bin/env python3
"""Local browser GUI server for H3 Companion."""

from __future__ import annotations

import argparse
import json
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from tools import (
        battle_estimator,
        h3_map_parser,
        h3_save_parser,
        hero_skill_recommender,
    )
except ImportError:  # pragma: no cover - direct script execution fallback.
    import battle_estimator
    import h3_map_parser
    import h3_save_parser
    import hero_skill_recommender


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
FOLLOW_LATEST_MODE = "follow_latest"
PINNED_MODE = "pinned"
DEFAULT_API_SIMULATIONS = battle_estimator.DEFAULT_SCAN_SIMULATIONS
MAX_API_SIMULATIONS = 2000
MAX_SCAN_RADIUS = 200
MAX_JSON_BODY_BYTES = 64 * 1024
STATIC_DIR = Path(__file__).with_name("battle_estimator_gui")
STATIC_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
}
PATH_ROUTE_LAND = "L"
PATH_ROUTE_WATER = "W"
PATH_ROUTE_BLOCKED = "B"
PATH_ROUTE_STATES = frozenset((
    PATH_ROUTE_LAND,
    PATH_ROUTE_WATER,
    PATH_ROUTE_BLOCKED,
))
PATH_STATUS_FOUND = "found"
PATH_STATUS_NOT_FOUND = "not_found"
PATH_STATUS_INVALID = "invalid"
PATH_STATUSES = frozenset((
    PATH_STATUS_FOUND,
    PATH_STATUS_NOT_FOUND,
    PATH_STATUS_INVALID,
))
PATH_SEGMENT_WALK = "walk"
PATH_SEGMENT_PORTAL = "portal"
PATH_SEGMENT_TYPES = frozenset((
    PATH_SEGMENT_WALK,
    PATH_SEGMENT_PORTAL,
))
_LAND_NEIGHBOR_DELTAS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


class SnapshotModeError(ValueError):
    """Raised when a GUI snapshot mode is invalid."""


class SnapshotConsistencyError(ValueError):
    """Raised when files change while a snapshot is being built."""


class ApiError(Exception):
    """Raised for expected JSON API request errors."""

    def __init__(self, status: HTTPStatus, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass
class GuiDomainSnapshotCache:
    """In-memory cache for the latest GUI domain snapshot."""

    key: tuple | None = None
    snapshot: object | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class GuiAppState:
    """Mutable runtime settings for one local GUI server instance."""

    mode: str = FOLLOW_LATEST_MODE
    autosave_dir: Path | None = None
    save_file: Path | None = None
    map_file: Path | None = None
    selected_hero_id: str | None = None
    show_hidden_neutrals: bool = False
    config_path: Path = h3_save_parser.CONFIG_PATH
    snapshot_cache: GuiDomainSnapshotCache = field(
        default_factory=GuiDomainSnapshotCache
    )
    removed_neutral_cache: h3_save_parser.RemovedNeutralHistoryCache = field(
        default_factory=h3_save_parser.RemovedNeutralHistoryCache
    )
    lock: threading.RLock = field(default_factory=threading.RLock)
    config_lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass(frozen=True)
class DomainSnapshot:
    """Current parsed save/map state, including raw domain objects."""

    mode: str
    save_context: h3_save_parser.SaveContext
    map_file: Path
    state: dict
    heroes: tuple
    hero_entries: tuple
    hero_by_id: dict
    neutral_targets: tuple
    visible_neutral_targets: tuple
    neutral_by_id: dict
    town_targets: tuple
    town_ownership_by_id: dict
    portal_targets: tuple
    portal_edges: tuple
    removed_records: tuple
    team_by_color: dict


@dataclass(frozen=True)
class DomainSnapshotSource:
    """Resolved files and fingerprints used to build a domain snapshot."""

    save_context: h3_save_parser.SaveContext
    map_file: Path
    save_fingerprint: dict
    map_fingerprint: dict


@dataclass(frozen=True)
class HeroSkillApiContext:
    """Resolved hero-skill recommendation context for one API request."""

    hero_id: str
    save_hero: object
    map_key: str
    role: str
    metadata: object
    rules: object
    hero_metadata: object
    current_skills: tuple
    current_skills_source: str


@dataclass(frozen=True)
class PathPosition:
    """One adventure-map tile coordinate used by the pathfinding service."""

    x: int
    y: int
    z: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _path_coordinate(self.x, "x"))
        object.__setattr__(self, "y", _path_coordinate(self.y, "y"))
        object.__setattr__(self, "z", _path_coordinate(self.z, "z"))

    @classmethod
    def from_value(cls, value) -> "PathPosition":
        return _path_position_from_value(value)

    @property
    def key(self) -> tuple[int, int, int]:
        return self.x, self.y, self.z


@dataclass(frozen=True)
class PathRouteMap:
    """Immutable compact route map addressed as layers[z][y][x]."""

    layers: tuple

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "layers",
            _normalize_path_route_layers(self.layers),
        )

    @property
    def levels(self) -> int:
        return len(self.layers)

    @property
    def height(self) -> int:
        return len(self.layers[0])

    @property
    def width(self) -> int:
        return len(self.layers[0][0])

    def contains(self, position) -> bool:
        path_position = _path_position_from_value(position)
        return (
            0 <= path_position.x < self.width
            and 0 <= path_position.y < self.height
            and 0 <= path_position.z < self.levels
        )

    def state_at(self, position) -> str:
        path_position = _path_position_from_value(position)
        if not self.contains(path_position):
            raise ValueError(f"path position out of bounds: {path_position.key}")
        return self.layers[path_position.z][path_position.y][path_position.x]


@dataclass(frozen=True)
class PathfindingPortalEdge:
    """Directed portal edge with endpoint positions resolved for path search."""

    source_id: str
    destination_id: str
    source_position: PathPosition
    destination_position: PathPosition
    portal_type: str
    channel_key: str
    is_non_deterministic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _required_path_text(self.source_id, "source_id"),
        )
        object.__setattr__(
            self,
            "destination_id",
            _required_path_text(self.destination_id, "destination_id"),
        )
        object.__setattr__(
            self,
            "source_position",
            _path_position_from_value(self.source_position),
        )
        object.__setattr__(
            self,
            "destination_position",
            _path_position_from_value(self.destination_position),
        )
        object.__setattr__(
            self,
            "portal_type",
            _required_path_text(self.portal_type, "portal_type"),
        )
        object.__setattr__(
            self,
            "channel_key",
            _required_path_text(self.channel_key, "channel_key"),
        )
        object.__setattr__(
            self,
            "is_non_deterministic",
            bool(self.is_non_deterministic),
        )


@dataclass(frozen=True)
class PathfindingRequest:
    """Validated pathfinding service input independent from the HTTP layer."""

    start_position: PathPosition
    requested_target_position: PathPosition
    route_map: PathRouteMap
    portal_edges: tuple[PathfindingPortalEdge, ...] = field(default_factory=tuple)
    terminal_positions: tuple[PathPosition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        route_map = self.route_map
        if not isinstance(route_map, PathRouteMap):
            route_map = PathRouteMap(route_map)
        start_position = _path_position_from_value(self.start_position)
        requested_target_position = path_position_for_target(
            self.requested_target_position
        )
        portal_edges = tuple(self.portal_edges or ())
        terminal_positions = tuple(
            path_position_for_target(position)
            for position in (self.terminal_positions or ())
        )

        if not route_map.contains(start_position):
            raise ValueError(
                f"selected hero position out of bounds: {start_position.key}"
            )
        if route_map.state_at(start_position) != PATH_ROUTE_LAND:
            raise ValueError("selected hero position must be a land route tile")
        if not route_map.contains(requested_target_position):
            raise ValueError(
                "requested target position out of bounds: "
                f"{requested_target_position.key}"
            )
        for edge in portal_edges:
            if not isinstance(edge, PathfindingPortalEdge):
                raise ValueError("portal_edges must contain PathfindingPortalEdge")
            if not route_map.contains(edge.source_position):
                raise ValueError(
                    f"portal source position out of bounds: {edge.source_position.key}"
                )
            if not route_map.contains(edge.destination_position):
                raise ValueError(
                    "portal destination position out of bounds: "
                    f"{edge.destination_position.key}"
                )
        for position in terminal_positions:
            if not route_map.contains(position):
                raise ValueError(
                    f"terminal position out of bounds: {position.key}"
                )

        object.__setattr__(self, "route_map", route_map)
        object.__setattr__(self, "start_position", start_position)
        object.__setattr__(
            self,
            "requested_target_position",
            requested_target_position,
        )
        object.__setattr__(self, "portal_edges", portal_edges)
        object.__setattr__(self, "terminal_positions", terminal_positions)


@dataclass(frozen=True)
class PathfindingStep:
    """One tile in a returned path."""

    position: PathPosition

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "position",
            _path_position_from_value(self.position),
        )


@dataclass(frozen=True)
class PathfindingSegment:
    """A contiguous walk or portal fragment in a pathfinding result."""

    segment_type: str
    start_position: PathPosition
    end_position: PathPosition
    steps: tuple[PathfindingStep, ...] = field(default_factory=tuple)
    portal_edge: PathfindingPortalEdge | None = None
    is_non_deterministic: bool = False

    def __post_init__(self) -> None:
        if self.segment_type not in PATH_SEGMENT_TYPES:
            raise ValueError(f"unknown path segment type: {self.segment_type!r}")
        if self.segment_type == PATH_SEGMENT_PORTAL and self.portal_edge is None:
            raise ValueError("portal path segment requires portal_edge")
        if self.segment_type == PATH_SEGMENT_WALK and self.portal_edge is not None:
            raise ValueError("walk path segment cannot have portal_edge")
        is_non_deterministic = bool(self.is_non_deterministic)
        if self.portal_edge is not None:
            if not isinstance(self.portal_edge, PathfindingPortalEdge):
                raise ValueError("portal_edge must be PathfindingPortalEdge")
            is_non_deterministic = (
                is_non_deterministic or self.portal_edge.is_non_deterministic
            )

        object.__setattr__(
            self,
            "start_position",
            _path_position_from_value(self.start_position),
        )
        object.__setattr__(
            self,
            "end_position",
            _path_position_from_value(self.end_position),
        )
        object.__setattr__(self, "steps", _normalize_path_steps(self.steps))
        object.__setattr__(
            self,
            "is_non_deterministic",
            is_non_deterministic,
        )


@dataclass(frozen=True)
class PathfindingResult:
    """Pathfinding service output for found, not-found, and invalid states."""

    status: str
    requested_target_position: PathPosition
    resolved_target_position: PathPosition | None = None
    steps: tuple[PathfindingStep, ...] = field(default_factory=tuple)
    segments: tuple[PathfindingSegment, ...] = field(default_factory=tuple)
    message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in PATH_STATUSES:
            raise ValueError(f"unknown pathfinding result status: {self.status!r}")
        object.__setattr__(
            self,
            "requested_target_position",
            _path_position_from_value(self.requested_target_position),
        )
        if self.resolved_target_position is not None:
            object.__setattr__(
                self,
                "resolved_target_position",
                _path_position_from_value(self.resolved_target_position),
            )
        object.__setattr__(self, "steps", _normalize_path_steps(self.steps))
        object.__setattr__(
            self,
            "segments",
            _normalize_path_segments(self.segments),
        )


class BattleEstimatorGuiHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local read-only GUI."""

    server_version = "H3CompanionGUI/0.1"

    def do_GET(self):
        self._handle_get(send_body=True)

    def do_HEAD(self):
        self._handle_get(send_body=False)

    def do_POST(self):
        self._handle_post()

    def _handle_get(self, send_body: bool):
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json({"ok": True}, send_body=send_body)
            return
        if path == "/api/state":
            self._handle_api(lambda: self._api_state(), send_body=send_body)
            return
        if path == "/api/saves":
            self._handle_api(lambda: self._api_saves(), send_body=send_body)
            return
        if path == "/api/game-folders":
            self._handle_api(lambda: self._api_game_folders(), send_body=send_body)
            return
        if path.startswith("/api/"):
            self._send_json_error(
                HTTPStatus.NOT_FOUND,
                f"unknown API endpoint: {path}",
                send_body=send_body,
            )
            return

        static_name = STATIC_ROUTES.get(path)
        if static_name is not None:
            self._send_static(static_name, send_body=send_body)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _handle_post(self):
        path = urlsplit(self.path).path
        routes = {
            "/api/select-hero": self._api_select_hero,
            "/api/save-mode": self._api_save_mode,
            "/api/game-folder": self._api_game_folder,
            "/api/hidden-target": self._api_hidden_target,
            "/api/show-hidden": self._api_show_hidden,
            "/api/simulate-target": self._api_simulate_target,
            "/api/scan-radius": self._api_scan_radius,
            "/api/path-route": self._api_path_route,
            "/api/hero-skills": self._api_hero_skills,
            "/api/hero-skills/save": self._api_hero_skills_save,
            "/api/hero-skills/reset": self._api_hero_skills_reset,
            "/api/hero-skills/compare": self._api_hero_skills_compare,
        }
        handler = routes.get(path)
        if handler is None:
            if path.startswith("/api/"):
                self._send_json_error(
                    HTTPStatus.NOT_FOUND,
                    f"unknown API endpoint: {path}",
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        self._handle_api(lambda: handler(self._read_json_body()))

    def _handle_api(self, callback, send_body: bool = True):
        try:
            payload = callback()
        except ApiError as exc:
            self._send_json_error(exc.status, exc.message, send_body=send_body)
        except SnapshotConsistencyError as exc:
            self._send_json_error(HTTPStatus.CONFLICT, str(exc), send_body=send_body)
        except (
            SnapshotModeError,
            battle_estimator.NearbyScanError,
            hero_skill_recommender.HeroSkillRecommendationError,
            h3_map_parser.H3MapLoadError,
            h3_map_parser.H3MapSelectionError,
            h3_save_parser.ConfigError,
            h3_save_parser.HeroSelectionError,
            h3_save_parser.SaveLoadError,
            h3_save_parser.SaveSelectionError,
        ) as exc:
            self._send_json_error(HTTPStatus.BAD_REQUEST, str(exc), send_body=send_body)
        except Exception as exc:  # pragma: no cover - defensive local API boundary.
            self._send_json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"unexpected server error: {exc}",
                send_body=send_body,
            )
        else:
            self._send_json(payload, send_body=send_body)

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from exc
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON request body is too large")
        try:
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return payload

    def _api_state(self) -> dict:
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        payload = _state_payload_for_app(self.app_state, domain_snapshot)
        return payload

    def _api_saves(self) -> dict:
        game_dir = _active_game_dir_for_app(self.app_state)
        saves = _list_numeric_saves(game_dir)
        latest_save = saves[-1]["path"] if saves else None
        return {
            "autosave_dir": str(game_dir),
            "latest_save_file": latest_save,
            "saves": saves,
        }

    def _api_game_folders(self) -> dict:
        active_game_dir = _active_game_dir_for_app(self.app_state)
        return _game_folders_payload(active_game_dir)

    def _api_game_folder(self, payload: dict) -> dict:
        if _optional_bool(payload, "use_latest_game_folder", False):
            active_game_dir = _active_game_dir_for_app(self.app_state)
            game_dir = _select_latest_game_folder(
                _game_folders_root_for_active_dir(active_game_dir)
            )
        else:
            game_dir = _validate_game_dir_for_api(_required_text(payload, "autosave_dir"))

        candidate = self._app_state_copy()
        candidate.mode = FOLLOW_LATEST_MODE
        candidate.autosave_dir = game_dir
        candidate.save_file = None
        candidate.selected_hero_id = None
        domain_snapshot = _domain_snapshot_for_app(candidate)

        with self.app_state.lock:
            config_path = self.app_state.config_path
        with self.app_state.config_lock:
            h3_save_parser.set_config_autosave_dir(game_dir, config_path)
        with self.app_state.lock:
            self.app_state.mode = FOLLOW_LATEST_MODE
            self.app_state.autosave_dir = game_dir
            self.app_state.save_file = None
            self.app_state.selected_hero_id = None
        _clear_snapshot_cache(self.app_state)
        return _state_payload_for_app(self.app_state, domain_snapshot)

    def _api_select_hero(self, payload: dict) -> dict:
        hero_id = _required_text(payload, "hero_id")
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        hero = _hero_by_id(domain_snapshot, hero_id)
        with self.app_state.lock:
            config_path = self.app_state.config_path
        with self.app_state.config_lock:
            updated_config = h3_save_parser.set_config_selected_hero(
                hero.hero_name,
                config_path,
            )
            with self.app_state.lock:
                self.app_state.selected_hero_id = hero_id
        return {
            "selected_hero_id": hero_id,
            "last_hero": updated_config.last_hero,
            "recent_heroes": list(updated_config.recent_heroes),
        }

    def _api_save_mode(self, payload: dict) -> dict:
        mode = _required_text(payload, "mode")
        if mode == FOLLOW_LATEST_MODE:
            candidate = self._app_state_copy()
            candidate.mode = FOLLOW_LATEST_MODE
            candidate.save_file = None
        elif mode == PINNED_MODE:
            save_file = _required_text(payload, "save_file")
            pinned_save = _validate_pinned_save_for_app(self.app_state, save_file)
            candidate = self._app_state_copy()
            candidate.mode = PINNED_MODE
            candidate.save_file = pinned_save
        else:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                f"invalid mode {mode!r}; expected follow_latest or pinned",
            )

        domain_snapshot = _domain_snapshot_for_app(candidate)
        with self.app_state.lock:
            self.app_state.mode = candidate.mode
            self.app_state.save_file = candidate.save_file
        return _state_payload_for_app(self.app_state, domain_snapshot)

    def _api_hidden_target(self, payload: dict) -> dict:
        target_id = _required_text(payload, "target_id")
        hidden = _optional_bool(payload, "hidden", True)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        map_key = _hidden_neutral_map_key(domain_snapshot)
        config = h3_save_parser.load_config(self.app_state_config_path)
        selected_hero_id = _resolve_selected_hero_id_for_app(
            self.app_state,
            domain_snapshot,
            config.last_hero,
        )

        with self.app_state.lock:
            config_path = self.app_state.config_path
        with self.app_state.config_lock:
            if target_id.startswith("neutral:"):
                _validate_hidden_neutral_target(domain_snapshot, target_id)
                config = h3_save_parser.set_config_hidden_neutral_target(
                    map_key,
                    target_id,
                    hidden,
                    config_path,
                )
            elif target_id.startswith("hero:"):
                _validate_hidden_hero_target(
                    domain_snapshot,
                    target_id,
                    selected_hero_id,
                )
                config = h3_save_parser.set_config_hidden_hero_target(
                    map_key,
                    target_id,
                    hidden,
                    config_path,
                )
            else:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "target_id must be neutral:<object_index> or hero:<stable_id>",
                )

        hidden_ids = config.hidden_neutral_targets_by_map.get(map_key, ())
        hidden_hero_ids = _hidden_hero_target_ids_for_config(
            config,
            domain_snapshot,
            selected_hero_id,
        )
        return {
            "map_key": map_key,
            "target_id": target_id,
            "hidden": target_id in hidden_ids or target_id in hidden_hero_ids,
            "hidden_neutral_target_ids": list(hidden_ids),
            "hidden_hero_target_ids": list(hidden_hero_ids),
        }

    def _api_show_hidden(self, payload: dict) -> dict:
        show_hidden = _optional_bool(payload, "show_hidden", False)
        with self.app_state.lock:
            self.app_state.show_hidden_neutrals = show_hidden
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        return _state_payload_for_app(self.app_state, domain_snapshot)

    def _api_simulate_target(self, payload: dict) -> dict:
        hero_id = _required_text(payload, "hero_id")
        target_id = _required_text(payload, "target_id")
        simulations = _bounded_int(
            payload,
            "simulations",
            DEFAULT_API_SIMULATIONS,
            minimum=1,
            maximum=MAX_API_SIMULATIONS,
        )
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        selected_hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        hidden_ids = _hidden_neutral_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
        )
        hidden_hero_ids = _hidden_hero_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
            hero_id,
        )
        scan_target, resolved_target_id = _single_scan_target(
            domain_snapshot,
            selected_hero,
            target_id,
            hidden_neutral_target_ids=hidden_ids,
            hidden_hero_target_ids=hidden_hero_ids,
            include_hidden_targets=_show_hidden_neutrals_for_app(self.app_state),
        )
        estimate = battle_estimator.estimate_nearby_scan_targets(
            selected_hero,
            (scan_target,),
            simulations=simulations,
        )[0]
        return {
            "hero_id": hero_id,
            "target_id": resolved_target_id,
            "simulations": simulations,
            "estimate": _serialize_scan_estimate(domain_snapshot, estimate),
        }

    def _api_scan_radius(self, payload: dict) -> dict:
        hero_id = _required_text(payload, "hero_id")
        radius = _bounded_int(
            payload,
            "radius",
            10,
            minimum=0,
            maximum=MAX_SCAN_RADIUS,
        )
        simulations = _bounded_int(
            payload,
            "simulations",
            DEFAULT_API_SIMULATIONS,
            minimum=1,
            maximum=MAX_API_SIMULATIONS,
        )
        target_type = str(payload.get("target_type", "all")).strip() or "all"
        include_removed = _optional_bool(payload, "include_removed", False)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        selected_hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        hidden_ids = _hidden_neutral_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
        )
        hidden_hero_ids = _hidden_hero_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
            hero_id,
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
            hidden_hero_ids,
        )
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected_hero,
            neutral_targets=_filter_hidden_neutral_targets(
                domain_snapshot.neutral_targets,
                hidden_ids,
            ),
            hero_targets=hero_targets,
            removed_records=domain_snapshot.removed_records,
            radius=radius,
            target_type=target_type,
            include_removed=include_removed,
        )
        estimates = battle_estimator.estimate_nearby_scan_targets(
            selected_hero,
            scan_targets,
            simulations=simulations,
        )
        return {
            "hero_id": hero_id,
            "radius": radius,
            "target_type": target_type,
            "include_removed": include_removed,
            "simulations": simulations,
            "results": [
                _serialize_scan_estimate(domain_snapshot, estimate)
                for estimate in estimates
            ],
        }

    def _api_path_route(self, payload: dict) -> dict:
        hero_id = _required_text(payload, "hero_id")
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        selected_hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        if selected_hero.position is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "selected hero has no parsed position")

        hidden_ids = _hidden_neutral_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
        )
        hidden_hero_ids = _hidden_hero_target_ids_for_snapshot(
            self.app_state,
            domain_snapshot,
            hero_id,
        )
        include_hidden_targets = _show_hidden_neutrals_for_app(self.app_state)
        target, target_id, terminal_positions = _path_target_for_api_payload(
            domain_snapshot,
            payload,
            hidden_neutral_target_ids=hidden_ids,
            hidden_hero_target_ids=hidden_hero_ids,
            include_hidden_targets=include_hidden_targets,
        )
        try:
            request = build_pathfinding_request(
                selected_hero.position,
                target,
                domain_snapshot.state["route_layers"],
                portal_targets=domain_snapshot.portal_targets,
                portal_edges=domain_snapshot.portal_edges,
                terminal_positions=terminal_positions,
            )
            result = find_path_route(request)
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

        response = _serialize_pathfinding_result(result)
        response["hero_id"] = hero_id
        if target_id is not None:
            response["target_id"] = target_id
        return response

    def _api_hero_skills(self, payload: dict) -> dict:
        hero_id = _required_hero_skill_hero_id(payload)
        role = _hero_skill_role_from_payload(payload)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
        )
        return _hero_skill_payload(context)

    def _api_hero_skills_save(self, payload: dict) -> dict:
        hero_id = _required_hero_skill_hero_id(payload)
        role = _hero_skill_role_from_payload(payload)
        skills = _skill_state_from_payload(payload)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
            load_config=False,
        )
        with self.app_state.config_lock:
            config = h3_save_parser.set_config_hero_skill_state(
                context.map_key,
                hero_id,
                context.hero_metadata.key,
                skills,
                self.app_state_config_path,
                metadata=context.metadata,
            )
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
            config=config,
        )
        return _hero_skill_payload(context)

    def _api_hero_skills_reset(self, payload: dict) -> dict:
        hero_id = _required_hero_skill_hero_id(payload)
        role = _hero_skill_role_from_payload(payload)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
            load_config=False,
        )
        with self.app_state.config_lock:
            config = h3_save_parser.reset_config_hero_skill_state(
                context.map_key,
                hero_id,
                self.app_state_config_path,
            )
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
            config=config,
        )
        return _hero_skill_payload(context)

    def _api_hero_skills_compare(self, payload: dict) -> dict:
        hero_id = _required_hero_skill_hero_id(payload)
        role = _hero_skill_role_from_payload(payload)
        offers = _skill_offers_from_payload(payload)
        domain_snapshot = _domain_snapshot_for_app(self.app_state)
        hero = _request_hero_by_id(self.app_state, domain_snapshot, hero_id)
        context = _hero_skill_context_for_request(
            self.app_state,
            domain_snapshot,
            hero,
            hero_id,
            role,
        )
        comparison = hero_skill_recommender.compare_skill_offers(
            context.hero_metadata.key,
            current_skills=context.current_skills,
            offers=offers,
            role=context.role,
            metadata=context.metadata,
            rules=context.rules,
        )
        return _hero_skill_payload(context, offer_comparison=comparison)

    @property
    def app_state(self) -> GuiAppState:
        return self.server.app_state

    @property
    def app_state_config_path(self) -> Path:
        with self.app_state.lock:
            return self.app_state.config_path

    def _snapshot_kwargs(self) -> dict:
        return _snapshot_kwargs_for_state(self.app_state)

    def _app_state_copy(self) -> GuiAppState:
        with self.app_state.lock:
            return GuiAppState(
                mode=self.app_state.mode,
                autosave_dir=self.app_state.autosave_dir,
                save_file=self.app_state.save_file,
                map_file=self.app_state.map_file,
                selected_hero_id=self.app_state.selected_hero_id,
                show_hidden_neutrals=self.app_state.show_hidden_neutrals,
                config_path=self.app_state.config_path,
                snapshot_cache=self.app_state.snapshot_cache,
                removed_neutral_cache=self.app_state.removed_neutral_cache,
            )

    def _send_json(self, payload, send_body: bool = True, status=HTTPStatus.OK):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _send_json_error(
        self,
        status: HTTPStatus,
        message: str,
        send_body: bool = True,
    ):
        self._send_json(
            {"ok": False, "error": message},
            send_body=send_body,
            status=status,
        )

    def _send_static(self, static_name: str, send_body: bool):
        path = STATIC_DIR / static_name
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Static asset not found")
            return

        body = path.read_bytes()
        suffix = path.suffix.lstrip(".")
        content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def log_message(self, format, *args):  # pragma: no cover - log noise only.
        return


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    app_state: GuiAppState | None = None,
) -> ThreadingHTTPServer:
    """Create a local GUI HTTP server without starting its serve loop."""

    server = ThreadingHTTPServer((host, port), BattleEstimatorGuiHandler)
    server.app_state = app_state or GuiAppState()
    return server


def build_state_snapshot(
    mode: str = FOLLOW_LATEST_MODE,
    autosave_dir: str | Path | None = None,
    save_file: str | Path | None = None,
    map_file: str | Path | None = None,
    config_path: str | Path = h3_save_parser.CONFIG_PATH,
) -> dict:
    """Build a JSON-serializable GUI state snapshot from save and map files."""

    return build_domain_snapshot(
        mode=mode,
        autosave_dir=autosave_dir,
        save_file=save_file,
        map_file=map_file,
        config_path=config_path,
    ).state


def build_domain_snapshot(
    mode: str = FOLLOW_LATEST_MODE,
    autosave_dir: str | Path | None = None,
    save_file: str | Path | None = None,
    map_file: str | Path | None = None,
    config_path: str | Path = h3_save_parser.CONFIG_PATH,
    removed_neutral_cache: h3_save_parser.RemovedNeutralHistoryCache | None = None,
) -> DomainSnapshot:
    """Build a GUI snapshot with raw parser objects for API operations."""

    source = _resolve_domain_snapshot_source(
        mode=mode,
        autosave_dir=autosave_dir,
        save_file=save_file,
        map_file=map_file,
        config_path=config_path,
    )
    return _build_domain_snapshot_from_source(
        mode,
        source,
        removed_neutral_cache=removed_neutral_cache,
    )


def _domain_snapshot_for_app(app_state: GuiAppState) -> DomainSnapshot:
    kwargs = _snapshot_kwargs_for_state(app_state)
    source = _resolve_domain_snapshot_source(**kwargs)
    key = _domain_snapshot_cache_key(kwargs["mode"], source)
    snapshot_cache = app_state.snapshot_cache

    with snapshot_cache.lock:
        if snapshot_cache.key == key and snapshot_cache.snapshot is not None:
            return snapshot_cache.snapshot

        snapshot = _build_domain_snapshot_from_source(
            kwargs["mode"],
            source,
            removed_neutral_cache=app_state.removed_neutral_cache,
        )
        snapshot_cache.key = key
        snapshot_cache.snapshot = snapshot
        return snapshot


def _resolve_domain_snapshot_source(
    mode: str = FOLLOW_LATEST_MODE,
    autosave_dir: str | Path | None = None,
    save_file: str | Path | None = None,
    map_file: str | Path | None = None,
    config_path: str | Path = h3_save_parser.CONFIG_PATH,
) -> DomainSnapshotSource:
    save_context = _resolve_snapshot_save(
        mode=mode,
        autosave_dir=autosave_dir,
        save_file=save_file,
        config_path=config_path,
    )
    if save_context.save_file is None:
        raise h3_save_parser.SaveSelectionError(".", "missing selected save file")
    if save_context.game_dir is None:
        raise h3_save_parser.SaveSelectionError(
            save_context.save_file,
            "missing selected game folder",
        )

    resolved_map_file = h3_map_parser.resolve_h3m_map(
        save_context.game_dir,
        explicit_map_file=map_file,
    )
    save_fingerprint = _file_fingerprint(save_context.save_file)
    map_fingerprint = _file_fingerprint(resolved_map_file)
    return DomainSnapshotSource(
        save_context=save_context,
        map_file=resolved_map_file,
        save_fingerprint=save_fingerprint,
        map_fingerprint=map_fingerprint,
    )


def _build_domain_snapshot_from_source(
    mode: str,
    source: DomainSnapshotSource,
    removed_neutral_cache: h3_save_parser.RemovedNeutralHistoryCache | None = None,
) -> DomainSnapshot:
    save_context = source.save_context
    resolved_map_file = source.map_file
    save_fingerprint = source.save_fingerprint
    map_fingerprint = source.map_fingerprint
    loaded_save = h3_save_parser.load_save(save_context.save_file)
    detected_heroes = h3_save_parser.scan_xor01_hero_armies(loaded_save.data)
    loaded_map = h3_map_parser.load_h3m(resolved_map_file, parse_objects=True)
    team_by_color = _team_by_color(loaded_map.players)
    heroes = _prefer_owned_heroes(detected_heroes)
    if removed_neutral_cache is None:
        removed_records = h3_save_parser.load_removed_neutral_records_for_save(
            save_context.save_file,
            neutral_targets=loaded_map.neutral_targets,
            game_dir=save_context.game_dir,
        )
    else:
        removed_records = removed_neutral_cache.load_removed_neutral_records_for_save(
            save_context.save_file,
            neutral_targets=loaded_map.neutral_targets,
            game_dir=save_context.game_dir,
        )
    neutral_targets = h3_map_parser.filter_removed_neutral_targets(
        loaded_map.neutral_targets,
        removed_records,
        include_removed=True,
    )
    _ensure_unchanged(save_context.save_file, save_fingerprint)
    _ensure_unchanged(resolved_map_file, map_fingerprint)

    hero_entries = _hero_entries(heroes)
    town_ownership_by_id = _town_ownership_by_id(
        loaded_map.town_targets,
        h3_save_parser.infer_current_town_ownership(
            loaded_map.town_targets,
            detected_heroes,
        ),
    )
    state = {
        "mode": mode,
        "autosave_dir": str(save_context.game_dir),
        "save_file": str(save_context.save_file),
        "save_fingerprint": save_fingerprint,
        "map_file": str(resolved_map_file),
        "map_fingerprint": map_fingerprint,
        "map": {
            "width": loaded_map.header.map_size,
            "height": loaded_map.header.map_size,
            "levels": loaded_map.header.levels,
        },
        "players": [
            _serialize_map_player(player)
            for player in loaded_map.players
        ],
        "teams": [
            _serialize_map_team(team)
            for team in loaded_map.teams
        ],
        "route_layers": _serialize_route_layers(
            loaded_map.header,
            loaded_map.route_tiles,
        ),
        "heroes": _serialize_heroes(hero_entries, team_by_color),
        "neutral_targets": [
            _serialize_neutral_target(target)
            for target in neutral_targets
        ],
        "town_targets": [
            _serialize_town_target(
                target,
                town_ownership_by_id.get(_town_target_id(target)),
            )
            for target in loaded_map.town_targets
        ],
        "portal_targets": [
            _serialize_portal_target(target)
            for target in loaded_map.portal_targets
        ],
        "portal_edges": [
            _serialize_portal_edge(edge)
            for edge in loaded_map.portal_edges
        ],
    }
    return DomainSnapshot(
        mode=mode,
        save_context=save_context,
        map_file=resolved_map_file,
        state=state,
        heroes=heroes,
        hero_entries=hero_entries,
        hero_by_id={hero_id: hero for hero_id, hero in hero_entries},
        neutral_targets=loaded_map.neutral_targets,
        visible_neutral_targets=neutral_targets,
        neutral_by_id={
            _neutral_target_id(target): target
            for target in neutral_targets
        },
        town_targets=loaded_map.town_targets,
        town_ownership_by_id=town_ownership_by_id,
        portal_targets=loaded_map.portal_targets,
        portal_edges=loaded_map.portal_edges,
        removed_records=removed_records,
        team_by_color=team_by_color,
    )


def _domain_snapshot_cache_key(
    mode: str,
    source: DomainSnapshotSource,
) -> tuple:
    return (
        mode,
        _fingerprint_cache_key(source.save_fingerprint),
        _fingerprint_cache_key(source.map_fingerprint),
    )


def _fingerprint_cache_key(fingerprint: dict) -> tuple:
    return (
        fingerprint["path"],
        fingerprint["size"],
        fingerprint["mtime_ns"],
    )


def _resolve_snapshot_save(
    mode: str,
    autosave_dir: str | Path | None,
    save_file: str | Path | None,
    config_path: str | Path,
) -> h3_save_parser.SaveContext:
    if mode == FOLLOW_LATEST_MODE:
        return _resolve_follow_latest_save(autosave_dir, config_path)
    if mode == PINNED_MODE:
        return _resolve_pinned_save(save_file)

    expected = ", ".join((FOLLOW_LATEST_MODE, PINNED_MODE))
    raise SnapshotModeError(f"invalid snapshot mode {mode!r}; expected {expected}")


def _resolve_follow_latest_save(
    autosave_dir: str | Path | None,
    config_path: str | Path,
) -> h3_save_parser.SaveContext:
    if autosave_dir is not None:
        game_dir = Path(autosave_dir).expanduser()
        autosave_root = _game_folders_root_for_active_dir(game_dir)
    else:
        config = h3_save_parser.load_config(config_path)
        if config.autosave_dir is not None:
            game_dir = config.autosave_dir.expanduser()
            autosave_root = _game_folders_root_for_active_dir(game_dir)
        else:
            autosave_root = h3_save_parser.DEFAULT_AUTOSAVE_ROOT
            game_dir = h3_save_parser.select_game_dir(autosave_root=autosave_root)

    save_path = _select_latest_gui_save(game_dir)
    return h3_save_parser.SaveContext(
        autosave_root=autosave_root,
        game_dir=game_dir,
        save_file=save_path,
    )


def _resolve_pinned_save(
    save_file: str | Path | None,
) -> h3_save_parser.SaveContext:
    if save_file is None:
        raise h3_save_parser.SaveSelectionError(".", "pinned mode requires save_file")

    save_path = Path(save_file).expanduser()
    if not save_path.is_file():
        raise h3_save_parser.SaveSelectionError(save_path, "save file is not a file")
    if save_path.suffix.upper() not in h3_save_parser.SAVE_EXTENSIONS:
        raise h3_save_parser.SaveSelectionError(
            save_path,
            "save file must have .GM1 or .GM2 extension",
        )
    return h3_save_parser.SaveContext(
        autosave_root=save_path.parent,
        game_dir=save_path.parent,
        save_file=save_path,
    )


def _file_fingerprint(path: str | Path) -> dict:
    file_path = Path(path)
    stat_result = file_path.stat()
    return {
        "path": str(file_path),
        "size": stat_result.st_size,
        "mtime": stat_result.st_mtime,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _ensure_unchanged(path: str | Path, expected_fingerprint: dict) -> None:
    current_fingerprint = _file_fingerprint(path)
    if current_fingerprint != expected_fingerprint:
        raise SnapshotConsistencyError(
            f"{Path(path)} changed while building snapshot"
        )


def _hero_entries(heroes) -> tuple:
    hero_ids = _unique_hero_ids(heroes)
    return tuple(zip(hero_ids, heroes))


def _team_by_color(players) -> dict[int, int]:
    return {
        player.player_index: player.team_id
        for player in players
        if player.enabled and player.team_id is not None
    }


def _town_ownership_by_id(town_targets, ownership_observations) -> dict:
    towns = tuple(town_targets)
    observations = tuple(ownership_observations)
    if len(towns) != len(observations):
        raise ValueError("town ownership observations must match town targets")
    return {
        _town_target_id(town): observation
        for town, observation in zip(towns, observations)
    }


def _prefer_owned_heroes(heroes) -> tuple:
    owned_heroes = tuple(
        hero
        for hero in heroes
        if hero.owner_color_id is not None
    )
    if owned_heroes:
        return owned_heroes
    return tuple(heroes)


def _serialize_heroes(
    hero_entries,
    team_by_color: dict[int, int],
    hidden_hero_ids=(),
) -> list[dict]:
    hidden_id_set = set(hidden_hero_ids)
    return [
        _serialize_hero(
            hero,
            hero_id,
            team_by_color,
            hidden=hero_id in hidden_id_set,
        )
        for hero_id, hero in hero_entries
    ]


def _serialize_map_player(player) -> dict:
    return {
        "player_index": player.player_index,
        "color_name": player.color_name,
        "enabled": player.enabled,
        "can_human_play": player.can_human_play,
        "can_computer_play": player.can_computer_play,
        "team_id": player.team_id,
        "main_town_position": _serialize_tuple_position(player.main_town_position),
        "random_hero": player.random_hero,
    }


def _serialize_map_team(team) -> dict:
    return {
        "team_id": team.team_id,
        "player_indices": list(team.player_indices),
        "color_names": list(team.color_names),
    }


def _serialize_route_layers(header, route_tiles) -> list[list[str]]:
    state_chars = {
        h3_map_parser.ROUTE_LAND: PATH_ROUTE_LAND,
        h3_map_parser.ROUTE_WATER: PATH_ROUTE_WATER,
        h3_map_parser.ROUTE_BLOCKED: PATH_ROUTE_BLOCKED,
    }
    route_by_position = {}
    for tile in route_tiles:
        position = (tile.x, tile.y, tile.z)
        if position in route_by_position:
            raise ValueError(f"duplicate route tile at {position}")
        if not (
            0 <= tile.x < header.map_size
            and 0 <= tile.y < header.map_size
            and 0 <= tile.z < header.levels
        ):
            raise ValueError(f"route tile out of bounds at {position}")
        if tile.state not in state_chars:
            raise ValueError(f"unknown route tile state at {position}: {tile.state!r}")
        route_by_position[position] = state_chars[tile.state]

    expected_count = header.map_size * header.map_size * header.levels
    if len(route_by_position) != expected_count:
        raise ValueError(
            "route tile count mismatch: "
            f"expected {expected_count}, got {len(route_by_position)}"
        )

    layers = []
    for z in range(header.levels):
        rows = []
        for y in range(header.map_size):
            row = []
            for x in range(header.map_size):
                position = (x, y, z)
                route_char = route_by_position.get(position)
                if route_char is None:
                    raise ValueError(f"missing route tile at {position}")
                row.append(route_char)
            rows.append("".join(row))
        layers.append(rows)
    return layers


def build_pathfinding_request(
    selected_hero_position,
    requested_target_position,
    route_layers,
    portal_targets=(),
    portal_edges=(),
    terminal_positions=(),
) -> PathfindingRequest:
    """Build a validated pathfinding request from parsed GUI snapshot data."""

    route_map = PathRouteMap(route_layers)
    return PathfindingRequest(
        start_position=_path_position_from_value(selected_hero_position),
        requested_target_position=path_position_for_target(requested_target_position),
        route_map=route_map,
        portal_edges=_pathfinding_portal_edges(portal_targets, portal_edges),
        terminal_positions=tuple(
            path_position_for_target(position)
            for position in (terminal_positions or ())
        ),
    )


def path_position_for_target(value) -> PathPosition:
    """Resolve an explicit position or serialized marker-like target to a tile."""

    if isinstance(value, dict) and "position" in value:
        return _path_position_from_value(value["position"])
    return _path_position_from_value(value)


def find_land_path(request: PathfindingRequest) -> PathfindingResult:
    """Find a shortest same-level path over land route tiles only."""

    return _find_path_route(request, include_portals=False)


def find_path_route(request: PathfindingRequest) -> PathfindingResult:
    """Find a shortest static route over land tiles and directed portal edges."""

    return _find_path_route(request, include_portals=True)


def _find_path_route(
    request: PathfindingRequest,
    include_portals: bool,
) -> PathfindingResult:
    if not isinstance(request, PathfindingRequest):
        raise ValueError("request must be PathfindingRequest")

    terminal_keys = frozenset(
        position.key
        for position in request.terminal_positions
    )
    target_keys, not_found_message = _path_target_keys_for_request(
        request,
        terminal_keys,
    )
    if not target_keys:
        return _path_not_found_result(request, not_found_message)
    target_key_set = frozenset(target_keys)
    if request.start_position.key in target_key_set:
        return _pathfinding_result_for_positions(
            request,
            (request.start_position,),
            message=_fallback_message_for_key(request, request.start_position.key),
        )

    portal_edges_by_source = (
        _portal_edges_by_source(request.portal_edges)
        if include_portals
        else {}
    )
    frontier = deque((request.start_position,))
    previous_by_key = {request.start_position.key: (None, None)}
    position_by_key = {request.start_position.key: request.start_position}
    distance_by_key = {request.start_position.key: 0}
    best_distance = None
    found_target_keys = []

    while frontier:
        current_position = frontier.popleft()
        current_distance = distance_by_key[current_position.key]
        if best_distance is not None and current_distance >= best_distance:
            break
        for next_position, portal_edge in _path_neighbor_edges(
            request.route_map,
            current_position,
            portal_edges_by_source,
            target_key_set,
            terminal_keys,
        ):
            next_key = next_position.key
            if next_key in previous_by_key:
                continue
            previous_by_key[next_key] = (current_position.key, portal_edge)
            position_by_key[next_key] = next_position
            next_distance = current_distance + 1
            distance_by_key[next_key] = next_distance
            if next_key in target_key_set:
                if best_distance is None or next_distance < best_distance:
                    best_distance = next_distance
                    found_target_keys = []
                if next_distance == best_distance:
                    found_target_keys.append(next_key)
                continue
            frontier.append(next_position)

    if found_target_keys:
        selected_key = _select_path_target_key(found_target_keys, target_keys)
        positions, transition_edges = _reconstruct_path_positions(
            previous_by_key,
            position_by_key,
            selected_key,
        )
        return _pathfinding_result_for_positions(
            request,
            positions,
            transition_edges,
            message=_fallback_message_for_key(request, selected_key),
        )

    return _path_not_found_result(request, not_found_message)


def _path_target_keys_for_request(
    request: PathfindingRequest,
    terminal_keys: frozenset[tuple[int, int, int]],
) -> tuple[tuple[tuple[int, int, int], ...], str]:
    requested_position = request.requested_target_position
    requested_key = requested_position.key
    if (
        request.route_map.state_at(requested_position) == PATH_ROUTE_LAND
        or requested_key in terminal_keys
    ):
        return (requested_key,), "no land path found"

    fallback_positions = _fallback_target_positions(
        request.route_map,
        requested_position,
        terminal_keys,
    )
    return (
        tuple(position.key for position in fallback_positions),
        "no reachable land neighbor for target",
    )


def _fallback_target_positions(
    route_map: PathRouteMap,
    requested_position: PathPosition,
    terminal_keys: frozenset[tuple[int, int, int]],
) -> tuple[PathPosition, ...]:
    positions = []
    for dx, dy in _LAND_NEIGHBOR_DELTAS:
        candidate = PathPosition(
            requested_position.x + dx,
            requested_position.y + dy,
            requested_position.z,
        )
        if not route_map.contains(candidate):
            continue
        if candidate.key in terminal_keys:
            continue
        if route_map.state_at(candidate) != PATH_ROUTE_LAND:
            continue
        positions.append(candidate)
    return tuple(positions)


def _select_path_target_key(
    found_target_keys: list[tuple[int, int, int]],
    target_keys: tuple[tuple[int, int, int], ...],
) -> tuple[int, int, int]:
    target_order = {
        target_key: index
        for index, target_key in enumerate(target_keys)
    }
    return min(found_target_keys, key=lambda target_key: target_order[target_key])


def _fallback_message_for_key(
    request: PathfindingRequest,
    resolved_key: tuple[int, int, int],
) -> str | None:
    if resolved_key == request.requested_target_position.key:
        return None
    return f"resolved target to reachable neighbor {resolved_key}"


def _portal_edges_by_source(
    portal_edges: tuple[PathfindingPortalEdge, ...],
) -> dict[tuple[int, int, int], tuple[PathfindingPortalEdge, ...]]:
    edges_by_source = {}
    for edge in portal_edges:
        edges_by_source.setdefault(edge.source_position.key, []).append(edge)
    return {
        source_key: tuple(edges)
        for source_key, edges in edges_by_source.items()
    }


def _path_neighbor_edges(
    route_map: PathRouteMap,
    position: PathPosition,
    portal_edges_by_source: dict,
    target_keys: frozenset[tuple[int, int, int]],
    terminal_keys: frozenset[tuple[int, int, int]],
):
    for next_position in _neighbor_positions(position):
        if not route_map.contains(next_position):
            continue
        next_key = next_position.key
        if next_key in target_keys and next_key in terminal_keys:
            yield next_position, None
            continue
        if next_key in terminal_keys:
            continue
        if route_map.state_at(next_position) != PATH_ROUTE_LAND:
            continue
        yield next_position, None
    for portal_edge in portal_edges_by_source.get(position.key, ()):
        destination = portal_edge.destination_position
        if not route_map.contains(destination):
            continue
        destination_key = destination.key
        if destination_key in target_keys and destination_key in terminal_keys:
            yield destination, portal_edge
            continue
        if destination_key in terminal_keys:
            continue
        if route_map.state_at(destination) != PATH_ROUTE_LAND:
            continue
        yield destination, portal_edge


def _neighbor_positions(
    position: PathPosition,
):
    for dx, dy in _LAND_NEIGHBOR_DELTAS:
        yield PathPosition(position.x + dx, position.y + dy, position.z)


def _reconstruct_path_positions(
    previous_by_key: dict,
    position_by_key: dict,
    target_key: tuple[int, int, int],
) -> tuple[tuple[PathPosition, ...], tuple[PathfindingPortalEdge | None, ...]]:
    path_keys = []
    transition_edges = []
    current_key = target_key
    while current_key is not None:
        path_keys.append(current_key)
        previous_key, portal_edge = previous_by_key[current_key]
        if previous_key is not None:
            transition_edges.append(portal_edge)
        current_key = previous_key
    path_keys.reverse()
    transition_edges.reverse()
    return (
        tuple(position_by_key[key] for key in path_keys),
        tuple(transition_edges),
    )


def _pathfinding_result_for_positions(
    request: PathfindingRequest,
    positions: tuple[PathPosition, ...],
    transition_edges: tuple[PathfindingPortalEdge | None, ...] = (),
    message: str | None = None,
) -> PathfindingResult:
    if not positions:
        raise ValueError("pathfinding result requires at least one position")
    if not transition_edges:
        transition_edges = (None,) * (len(positions) - 1)
    if len(transition_edges) != len(positions) - 1:
        raise ValueError("pathfinding transition count must match positions")
    steps = tuple(PathfindingStep(position) for position in positions)
    return PathfindingResult(
        PATH_STATUS_FOUND,
        requested_target_position=request.requested_target_position,
        resolved_target_position=positions[-1],
        steps=steps,
        segments=_path_segments_for_positions(
            positions,
            steps,
            transition_edges,
        ),
        message=message,
    )


def _path_segments_for_positions(
    positions: tuple[PathPosition, ...],
    steps: tuple[PathfindingStep, ...],
    transition_edges: tuple[PathfindingPortalEdge | None, ...],
) -> tuple[PathfindingSegment, ...]:
    if len(positions) == 1:
        return (
            PathfindingSegment(
                PATH_SEGMENT_WALK,
                positions[0],
                positions[0],
                steps=(steps[0],),
            ),
        )

    segments = []
    walk_start_index = None
    for index, portal_edge in enumerate(transition_edges):
        if portal_edge is None:
            if walk_start_index is None:
                walk_start_index = index
            continue

        if walk_start_index is not None:
            segments.append(
                PathfindingSegment(
                    PATH_SEGMENT_WALK,
                    positions[walk_start_index],
                    positions[index],
                    steps=steps[walk_start_index:index + 1],
                )
            )
            walk_start_index = None
        segments.append(
            PathfindingSegment(
                PATH_SEGMENT_PORTAL,
                positions[index],
                positions[index + 1],
                steps=(steps[index], steps[index + 1]),
                portal_edge=portal_edge,
                is_non_deterministic=portal_edge.is_non_deterministic,
            )
        )

    if walk_start_index is not None:
        segments.append(
            PathfindingSegment(
                PATH_SEGMENT_WALK,
                positions[walk_start_index],
                positions[-1],
                steps=steps[walk_start_index:],
            )
        )
    return tuple(segments)


def _path_not_found_result(
    request: PathfindingRequest,
    message: str,
) -> PathfindingResult:
    return PathfindingResult(
        PATH_STATUS_NOT_FOUND,
        requested_target_position=request.requested_target_position,
        message=message,
    )


def _path_position_from_value(value) -> PathPosition:
    if isinstance(value, PathPosition):
        return value
    if value is None:
        raise ValueError("path position is required")
    if isinstance(value, dict):
        return PathPosition(
            _path_coordinate(value.get("x"), "x"),
            _path_coordinate(value.get("y"), "y"),
            _path_coordinate(value.get("z"), "z"),
        )
    if isinstance(value, (tuple, list)):
        if len(value) != 3:
            raise ValueError("path position tuple must contain x, y, z")
        x, y, z = value
        return PathPosition(
            _path_coordinate(x, "x"),
            _path_coordinate(y, "y"),
            _path_coordinate(z, "z"),
        )
    if all(hasattr(value, coordinate) for coordinate in ("x", "y", "z")):
        return PathPosition(
            _path_coordinate(value.x, "x"),
            _path_coordinate(value.y, "y"),
            _path_coordinate(value.z, "z"),
        )
    raise ValueError(
        "path position must be PathPosition, x/y/z object, mapping, or 3-tuple"
    )


def _path_coordinate(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"path position {name} must be an integer")
    return value


def _required_path_text(value, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _normalize_path_route_layers(route_layers) -> tuple[tuple[str, ...], ...]:
    if isinstance(route_layers, PathRouteMap):
        return route_layers.layers
    if isinstance(route_layers, (str, bytes)) or route_layers is None:
        raise ValueError("path route layers must be a non-empty sequence")

    normalized_layers = []
    expected_height = None
    expected_width = None
    for z, layer in enumerate(route_layers):
        if isinstance(layer, (str, bytes)) or layer is None:
            raise ValueError(f"path route layer {z} must be a sequence of rows")
        rows = []
        for y, row in enumerate(layer):
            if not isinstance(row, str) or not row:
                raise ValueError(f"path route row {z},{y} must be non-empty text")
            invalid_chars = sorted(set(row) - PATH_ROUTE_STATES)
            if invalid_chars:
                raise ValueError(
                    "unknown path route state at "
                    f"level {z}, row {y}: {invalid_chars[0]!r}"
                )
            if expected_width is None:
                expected_width = len(row)
            elif len(row) != expected_width:
                raise ValueError("path route rows must all have the same width")
            rows.append(row)
        if not rows:
            raise ValueError(f"path route layer {z} must contain at least one row")
        if expected_height is None:
            expected_height = len(rows)
        elif len(rows) != expected_height:
            raise ValueError("path route layers must all have the same height")
        normalized_layers.append(tuple(rows))

    if not normalized_layers:
        raise ValueError("path route layers must include at least one level")
    return tuple(normalized_layers)


def _pathfinding_portal_edges(
    portal_targets,
    portal_edges,
) -> tuple[PathfindingPortalEdge, ...]:
    target_by_index = {
        target.object_index: target
        for target in portal_targets
    }
    outgoing_counts = {}
    for edge in portal_edges:
        key = (edge.source_object_index, edge.channel_key)
        outgoing_counts[key] = outgoing_counts.get(key, 0) + 1

    path_edges = []
    for edge in portal_edges:
        source = target_by_index.get(edge.source_object_index)
        if source is None:
            raise ValueError(
                "unknown portal source object_index: "
                f"{edge.source_object_index}"
            )
        destination = target_by_index.get(edge.destination_object_index)
        if destination is None:
            raise ValueError(
                "unknown portal destination object_index: "
                f"{edge.destination_object_index}"
            )
        edge_key = (edge.source_object_index, edge.channel_key)
        path_edges.append(
            PathfindingPortalEdge(
                source_id=_portal_target_id_from_index(edge.source_object_index),
                destination_id=_portal_target_id_from_index(
                    edge.destination_object_index
                ),
                source_position=PathPosition(source.x, source.y, source.z),
                destination_position=PathPosition(
                    destination.x,
                    destination.y,
                    destination.z,
                ),
                portal_type=edge.portal_type,
                channel_key=edge.channel_key,
                is_non_deterministic=outgoing_counts[edge_key] > 1,
            )
        )
    return tuple(path_edges)


def _path_target_for_api_payload(
    domain_snapshot: DomainSnapshot,
    payload: dict,
    hidden_neutral_target_ids=(),
    hidden_hero_target_ids=(),
    include_hidden_targets: bool = False,
):
    has_target_position = "target_position" in payload
    has_target_id = "target_id" in payload
    if has_target_position == has_target_id:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "provide exactly one of target_position or target_id",
        )

    terminal_positions = list(_path_terminal_positions_for_snapshot(domain_snapshot))
    if has_target_position:
        return payload["target_position"], None, tuple(terminal_positions)

    target_id = _required_text(payload, "target_id")
    target = _path_marker_target_by_id(
        domain_snapshot,
        target_id,
        hidden_neutral_target_ids=hidden_neutral_target_ids,
        hidden_hero_target_ids=hidden_hero_target_ids,
        include_hidden_targets=include_hidden_targets,
    )
    terminal_positions.append(target)
    return target, target_id, tuple(terminal_positions)


def _path_terminal_positions_for_snapshot(
    domain_snapshot: DomainSnapshot,
) -> tuple[PathPosition, ...]:
    return tuple(
        PathPosition(target.x, target.y, target.z)
        for target in domain_snapshot.town_targets
    )


def _path_marker_target_by_id(
    domain_snapshot: DomainSnapshot,
    target_id: str,
    hidden_neutral_target_ids=(),
    hidden_hero_target_ids=(),
    include_hidden_targets: bool = False,
) -> dict:
    hidden_neutral_id_set = set(hidden_neutral_target_ids)
    hidden_hero_id_set = set(hidden_hero_target_ids)

    neutral = domain_snapshot.neutral_by_id.get(target_id)
    if neutral is not None:
        hidden = target_id in hidden_neutral_id_set
        if hidden and not include_hidden_targets:
            raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")
        return _serialize_neutral_target(neutral, hidden=hidden)

    hero = domain_snapshot.hero_by_id.get(target_id)
    if hero is not None:
        hidden = target_id in hidden_hero_id_set
        if hidden and not include_hidden_targets:
            raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")
        return _serialize_hero(
            hero,
            target_id,
            domain_snapshot.team_by_color,
            hidden=hidden,
        )

    for town in domain_snapshot.town_targets:
        if _town_target_id(town) == target_id:
            return _serialize_town_target(
                town,
                domain_snapshot.town_ownership_by_id.get(target_id),
            )

    for portal in domain_snapshot.portal_targets:
        if _portal_target_id(portal) == target_id:
            return _serialize_portal_target(portal)

    raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")


def _serialize_pathfinding_result(result: PathfindingResult) -> dict:
    return {
        "status": result.status,
        "requested_target_position": _serialize_position(
            result.requested_target_position
        ),
        "resolved_target_position": _serialize_position(
            result.resolved_target_position
        ),
        "message": result.message,
        "steps": [
            _serialize_pathfinding_step(step)
            for step in result.steps
        ],
        "segments": [
            _serialize_pathfinding_segment(segment)
            for segment in result.segments
        ],
    }


def _serialize_pathfinding_step(step: PathfindingStep) -> dict:
    return {
        "position": _serialize_position(step.position),
    }


def _serialize_pathfinding_segment(segment: PathfindingSegment) -> dict:
    payload = {
        "segment_type": segment.segment_type,
        "start_position": _serialize_position(segment.start_position),
        "end_position": _serialize_position(segment.end_position),
        "steps": [
            _serialize_pathfinding_step(step)
            for step in segment.steps
        ],
        "is_non_deterministic": segment.is_non_deterministic,
    }
    if segment.portal_edge is not None:
        payload["portal_edge"] = _serialize_pathfinding_portal_edge(
            segment.portal_edge
        )
    return payload


def _serialize_pathfinding_portal_edge(edge: PathfindingPortalEdge) -> dict:
    return {
        "source_id": edge.source_id,
        "destination_id": edge.destination_id,
        "source_position": _serialize_position(edge.source_position),
        "destination_position": _serialize_position(edge.destination_position),
        "portal_type": edge.portal_type,
        "channel_key": edge.channel_key,
        "is_non_deterministic": edge.is_non_deterministic,
    }


def _normalize_path_steps(steps) -> tuple[PathfindingStep, ...]:
    if steps is None:
        return ()
    return tuple(
        step if isinstance(step, PathfindingStep) else PathfindingStep(step)
        for step in steps
    )


def _normalize_path_segments(segments) -> tuple[PathfindingSegment, ...]:
    if segments is None:
        return ()
    normalized = tuple(segments)
    for segment in normalized:
        if not isinstance(segment, PathfindingSegment):
            raise ValueError("segments must contain PathfindingSegment")
    return normalized


def _unique_hero_ids(heroes) -> list[str]:
    bases = [_hero_id_base(hero) for hero in heroes]
    duplicate_counts = {
        base: bases.count(base)
        for base in set(bases)
    }
    seen = {}
    hero_ids = []
    for base in bases:
        if duplicate_counts[base] == 1:
            hero_ids.append(base)
            continue
        seen[base] = seen.get(base, 0) + 1
        hero_ids.append(f"{base}:{seen[base]}")
    return hero_ids


def _hero_id_base(hero) -> str:
    if hero.source_offset is not None:
        return f"hero:{hero.source_offset}"

    slug = _stable_slug(hero.hero_name) or "unknown"
    position = _position_identity(hero.position)
    return f"hero:{slug}:{position}:{hero.ai_value}:{hero.total_creatures}"


def _stable_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _position_identity(position) -> str:
    if position is None:
        return "nopos"
    return f"{position.x},{position.y},{position.z}"


def _serialize_hero(
    hero,
    hero_id: str,
    team_by_color: dict[int, int],
    hidden: bool = False,
) -> dict:
    owner_color_id = hero.owner_color_id
    return {
        "id": hero_id,
        "name": hero.hero_name,
        "source_offset": hero.source_offset,
        "position": _serialize_position(hero.position),
        "owner_color_id": owner_color_id,
        "owner_color_name": hero.owner_color_name,
        "team_id": None if owner_color_id is None else team_by_color.get(owner_color_id),
        "army": [_serialize_hero_stack(stack) for stack in hero.stacks],
        "army_summary": hero.army_summary,
        "total_creatures": hero.total_creatures,
        "ai_value": hero.ai_value,
        "hidden": hidden,
    }


def _serialize_hero_stack(stack) -> dict:
    return {
        "creature_id": stack.creature_id,
        "creature_name": stack.creature.name,
        "count": stack.count,
    }


def _serialize_neutral_target(target, hidden: bool = False) -> dict:
    return {
        "id": _neutral_target_id(target),
        "object_index": target.object_index,
        "position": {
            "x": target.x,
            "y": target.y,
            "z": target.z,
        },
        "h3m_subid": target.h3m_subid,
        "count": target.count,
        "creature_name": target.creature_name,
        "estimator_creature_id": target.estimator_creature_id,
        "removed": target.removed,
        "removal_note": target.removal_note,
        "hidden": hidden,
    }


def _serialize_town_target(target, ownership=None) -> dict:
    serialized = {
        "id": _town_target_id(target),
        "object_index": target.object_index,
        "position": {
            "x": target.x,
            "y": target.y,
            "z": target.z,
        },
        "anchor_position": {
            "x": target.anchor_x,
            "y": target.anchor_y,
            "z": target.anchor_z,
        },
        "object_id": target.object_id,
        "h3m_subid": target.h3m_subid,
        "faction_subid": target.faction_subid,
        "initial_owner": target.initial_owner,
        "initial_owner_color_name": _initial_owner_color_name(target.initial_owner),
        "custom_name": target.custom_name,
        "has_garrison": target.has_garrison,
    }
    serialized.update(_serialize_town_ownership(ownership))
    return serialized


def _serialize_town_ownership(ownership) -> dict:
    if ownership is None:
        return {
            "current_owner_color_id": None,
            "current_owner_color_name": None,
            "ownership_status": h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE,
            "ownership_source": None,
            "ownership_confidence": (
                h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE
            ),
            "ownership_reason": None,
            "ownership_matching_hero_count": 0,
            "ownership_matching_hero_names": [],
            "ownership_matching_hero_source_offsets": [],
        }

    return {
        "current_owner_color_id": ownership.current_owner_color_id,
        "current_owner_color_name": ownership.current_owner_color_name,
        "ownership_status": ownership.ownership_status,
        "ownership_source": ownership.ownership_source,
        "ownership_confidence": ownership.ownership_confidence,
        "ownership_reason": ownership.reason,
        "ownership_matching_hero_count": ownership.matching_hero_count,
        "ownership_matching_hero_names": list(ownership.matching_hero_names),
        "ownership_matching_hero_source_offsets": list(
            ownership.matching_hero_source_offsets
        ),
    }


def _serialize_portal_target(target) -> dict:
    return {
        "id": _portal_target_id(target),
        "object_index": target.object_index,
        "position": {
            "x": target.x,
            "y": target.y,
            "z": target.z,
        },
        "anchor_position": {
            "x": target.anchor_x,
            "y": target.anchor_y,
            "z": target.anchor_z,
        },
        "object_id": target.object_id,
        "h3m_subid": target.h3m_subid,
        "portal_type": target.portal_type,
        "role": target.role,
        "channel_key": target.channel_key,
    }


def _serialize_portal_edge(edge) -> dict:
    return {
        "source_id": _portal_target_id_from_index(edge.source_object_index),
        "destination_id": _portal_target_id_from_index(edge.destination_object_index),
        "source_object_index": edge.source_object_index,
        "destination_object_index": edge.destination_object_index,
        "portal_type": edge.portal_type,
        "channel_key": edge.channel_key,
        "h3m_subid": edge.h3m_subid,
    }


def _neutral_target_id(target) -> str:
    return f"neutral:{target.object_index}"


def _town_target_id(target) -> str:
    return f"town:{target.object_index}"


def _portal_target_id(target) -> str:
    return _portal_target_id_from_index(target.object_index)


def _portal_target_id_from_index(object_index: int) -> str:
    return f"portal:{object_index}"


def _initial_owner_color_name(initial_owner: int | None) -> str | None:
    if (
        initial_owner is None
        or initial_owner < 0
        or initial_owner >= len(h3_map_parser.PLAYER_COLOR_NAMES)
    ):
        return None
    return h3_map_parser.PLAYER_COLOR_NAMES[initial_owner]


def _serialize_position(position) -> dict | None:
    if position is None:
        return None
    return {
        "x": position.x,
        "y": position.y,
        "z": position.z,
    }


def _serialize_tuple_position(position) -> dict | None:
    if position is None:
        return None
    x, y, z = position
    return {
        "x": x,
        "y": y,
        "z": z,
    }


def _snapshot_kwargs_for_state(app_state: GuiAppState) -> dict:
    with app_state.lock:
        return {
            "mode": app_state.mode,
            "autosave_dir": app_state.autosave_dir,
            "save_file": app_state.save_file,
            "map_file": app_state.map_file,
            "config_path": app_state.config_path,
        }


def _state_payload_for_app(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
) -> dict:
    config = h3_save_parser.load_config(_snapshot_kwargs_for_state(app_state)["config_path"])
    show_hidden = _show_hidden_neutrals_for_app(app_state)
    selected_hero_id = _resolve_selected_hero_id_for_app(
        app_state,
        domain_snapshot,
        config.last_hero,
    )
    hidden_ids = _hidden_neutral_target_ids_for_config(config, domain_snapshot)
    hidden_hero_ids = _hidden_hero_target_ids_for_config(
        config,
        domain_snapshot,
        selected_hero_id,
    )
    payload = dict(domain_snapshot.state)
    payload["heroes"] = _serialize_heroes(
        domain_snapshot.hero_entries,
        domain_snapshot.team_by_color,
        hidden_hero_ids,
    )
    payload["neutral_targets"] = _serialize_visible_neutral_targets(
        domain_snapshot.visible_neutral_targets,
        hidden_ids,
        include_hidden=show_hidden,
    )
    payload["selected_hero_id"] = selected_hero_id
    payload["recent_heroes"] = list(config.recent_heroes)
    payload["show_hidden"] = show_hidden
    payload["hidden_neutral_target_ids"] = list(hidden_ids)
    payload["hidden_hero_target_ids"] = list(hidden_hero_ids)
    return payload


def _serialize_visible_neutral_targets(
    neutral_targets,
    hidden_ids,
    include_hidden: bool,
) -> list[dict]:
    hidden_id_set = set(hidden_ids)
    serialized = []
    for target in neutral_targets:
        target_id = _neutral_target_id(target)
        hidden = target_id in hidden_id_set
        if hidden and not include_hidden:
            continue
        serialized.append(_serialize_neutral_target(target, hidden=hidden))
    return serialized


def _hidden_neutral_target_ids_for_snapshot(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
) -> tuple[str, ...]:
    with app_state.lock:
        config_path = app_state.config_path
    config = h3_save_parser.load_config(config_path)
    return _hidden_neutral_target_ids_for_config(config, domain_snapshot)


def _hidden_hero_target_ids_for_snapshot(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
    selected_hero_id: str | None = None,
) -> tuple[str, ...]:
    with app_state.lock:
        config_path = app_state.config_path
    config = h3_save_parser.load_config(config_path)
    return _hidden_hero_target_ids_for_config(
        config,
        domain_snapshot,
        selected_hero_id,
    )


def _hidden_neutral_target_ids_for_config(
    config: h3_save_parser.BattleEstimatorConfig,
    domain_snapshot: DomainSnapshot,
) -> tuple[str, ...]:
    map_key = _hidden_neutral_map_key(domain_snapshot)
    known_ids = {
        _neutral_target_id(target)
        for target in domain_snapshot.neutral_targets
    }
    return tuple(
        target_id
        for target_id in config.hidden_neutral_targets_by_map.get(map_key, ())
        if target_id in known_ids
    )


def _hidden_hero_target_ids_for_config(
    config: h3_save_parser.BattleEstimatorConfig,
    domain_snapshot: DomainSnapshot,
    selected_hero_id: str | None = None,
) -> tuple[str, ...]:
    map_key = _hidden_neutral_map_key(domain_snapshot)
    known_ids = set(domain_snapshot.hero_by_id)
    return tuple(
        target_id
        for target_id in config.hidden_hero_targets_by_map.get(map_key, ())
        if target_id in known_ids and target_id != selected_hero_id
    )


def _hidden_neutral_map_key(domain_snapshot: DomainSnapshot) -> str:
    fingerprint = domain_snapshot.state.get("map_fingerprint") or {}
    return "|".join((
        str(domain_snapshot.map_file),
        str(fingerprint.get("size", "")),
        str(fingerprint.get("mtime_ns", "")),
    ))


def _hero_skill_context_for_request(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
    hero,
    hero_id: str,
    role: str | None,
    config: h3_save_parser.BattleEstimatorConfig | None = None,
    load_config: bool = True,
) -> HeroSkillApiContext:
    metadata, rules = _load_hero_skill_recommendation_data()
    resolved_role = _validate_hero_skill_role(
        role or rules.default_role,
        rules,
    )
    hero_metadata = _standard_hero_metadata_for_save_hero(hero, metadata)
    map_key = _hidden_neutral_map_key(domain_snapshot)
    if config is None and load_config:
        config = h3_save_parser.load_config(_snapshot_kwargs_for_state(app_state)["config_path"])
    if config is None:
        config = h3_save_parser.BattleEstimatorConfig()
    current_skills = h3_save_parser.get_config_hero_skill_state(
        map_key,
        hero_id,
        hero_metadata.key,
        config=config,
        config_path=_snapshot_kwargs_for_state(app_state)["config_path"],
        metadata=metadata,
    )
    current_skills_source = (
        "manual"
        if hero_id in config.manual_hero_current_skills_by_map.get(map_key, {})
        else "starting"
    )
    return HeroSkillApiContext(
        hero_id=hero_id,
        save_hero=hero,
        map_key=map_key,
        role=resolved_role,
        metadata=metadata,
        rules=rules,
        hero_metadata=hero_metadata,
        current_skills=current_skills,
        current_skills_source=current_skills_source,
    )


def _load_hero_skill_recommendation_data():
    try:
        metadata = hero_skill_recommender.load_vcmi_hero_skill_metadata()
        rules = hero_skill_recommender.load_recommendation_rules(metadata=metadata)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        hero_skill_recommender.HeroSkillRecommendationError,
    ) as exc:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            f"invalid hero skill recommendation data: {exc}",
        ) from exc
    return metadata, rules


def _hero_skill_payload(
    context: HeroSkillApiContext,
    offer_comparison=None,
) -> dict:
    recommendations = hero_skill_recommender.recommend_hero_skills(
        context.hero_metadata.key,
        role=context.role,
        current_skills=context.current_skills,
        metadata=context.metadata,
        rules=context.rules,
        top_limit=8,
        avoid_limit=8,
    )
    return {
        "hero_id": context.hero_id,
        "map_key": context.map_key,
        "role": context.role,
        "hero": _serialize_hero_skill_hero_metadata(context),
        "max_skills": hero_skill_recommender.MAX_SECONDARY_SKILLS,
        "skill_levels": list(hero_skill_recommender.SKILL_LEVELS),
        "skills": [
            _serialize_skill_metadata(skill)
            for skill in sorted(
                context.metadata.skills.values(),
                key=_skill_metadata_sort_key,
            )
        ],
        "current_skills": [
            _serialize_current_skill(skill, context.metadata)
            for skill in context.current_skills
        ],
        "current_skills_source": context.current_skills_source,
        "top_next": [
            _serialize_recommendation_entry(entry)
            for entry in recommendations.top_next
        ],
        "avoid": [
            _serialize_recommendation_entry(entry)
            for entry in recommendations.avoid
        ],
        "offer_comparison": _serialize_offer_comparison(offer_comparison),
    }


def _hero_skill_role_from_payload(payload: dict) -> str | None:
    if "role" not in payload or payload.get("role") is None:
        return None
    return _required_text(payload, "role")


def _required_hero_skill_hero_id(payload: dict) -> str:
    hero_id = _required_text(payload, "hero_id")
    if not h3_save_parser.HIDDEN_HERO_TARGET_PATTERN.fullmatch(hero_id):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "hero_id must be hero:<stable_id>",
        )
    return hero_id


def _validate_hero_skill_role(role: str, rules) -> str:
    normalized = role.strip() if isinstance(role, str) else ""
    if not normalized:
        raise ApiError(HTTPStatus.BAD_REQUEST, "role must be a non-empty string")
    if normalized not in rules.global_rules:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"unknown role: {normalized}")
    return normalized


def _skill_offers_from_payload(payload: dict) -> list:
    offers = payload.get("offers")
    if not isinstance(offers, list):
        raise ApiError(HTTPStatus.BAD_REQUEST, "offers must be a list")
    if len(offers) < 2:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "offer comparison requires at least two offers",
        )
    return offers


def _skill_state_from_payload(payload: dict) -> list:
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise ApiError(HTTPStatus.BAD_REQUEST, "skills must be a list")
    return skills


def _standard_hero_metadata_for_save_hero(hero, metadata):
    normalized_name = hero.hero_name.strip().casefold() if hero.hero_name else ""
    if not normalized_name:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "cannot resolve standard hero for blank hero name",
        )
    matches = [
        hero_metadata
        for hero_metadata in metadata.heroes.values()
        if hero_metadata.display_name.casefold() == normalized_name
        or hero_metadata.key.casefold() == normalized_name
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            f"ambiguous standard hero for hero name: {hero.hero_name}",
        )
    raise ApiError(
        HTTPStatus.BAD_REQUEST,
        f"unknown standard hero for hero name: {hero.hero_name}",
    )


def _serialize_hero_skill_hero_metadata(context: HeroSkillApiContext) -> dict:
    hero = context.hero_metadata
    hero_class = context.metadata.hero_classes.get(hero.class_id)
    return {
        "key": hero.key,
        "display_name": hero.display_name,
        "save_name": context.save_hero.hero_name,
        "class_id": hero.class_id,
        "class_index": None if hero_class is None else hero_class.index,
        "faction": hero.faction,
        "affinity": hero.affinity,
        "specialty_summary": hero.specialty_summary,
        "starting_skills": [
            _serialize_current_skill(skill, context.metadata)
            for skill in hero.starting_skills
        ],
    }


def _serialize_skill_metadata(skill) -> dict:
    return {
        "skill": skill.key,
        "skill_id": skill.key,
        "display_name": skill.display_name,
        "index": skill.index,
        "specialty_tags": list(skill.specialty_tags),
        "gain_chance": None if skill.gain_chance is None else dict(skill.gain_chance),
    }


def _serialize_current_skill(skill, metadata) -> dict:
    skill_metadata = metadata.skills.get(skill.skill_id)
    return {
        "skill": skill.skill_id,
        "skill_id": skill.skill_id,
        "display_name": (
            skill.skill_id if skill_metadata is None else skill_metadata.display_name
        ),
        "level": skill.level,
    }


def _serialize_recommendation_entry(entry) -> dict:
    return {
        "skill": entry.skill_id,
        "skill_id": entry.skill_id,
        "display_name": entry.display_name,
        "target_level": entry.target_level,
        "score": entry.score,
        "tier": entry.tier,
        "availability": entry.availability,
        "reason_codes": list(entry.reason_codes),
    }


def _serialize_offer_comparison(comparison) -> dict | None:
    if comparison is None:
        return None
    return {
        "winner": comparison.winner,
        "reason_codes": list(comparison.reason_codes),
        "offers": [
            _serialize_recommendation_entry(entry)
            for entry in comparison.offers
        ],
    }


def _skill_metadata_sort_key(skill) -> tuple[int, str]:
    return (
        skill.index if skill.index is not None else 10_000,
        skill.display_name,
    )


def _show_hidden_neutrals_for_app(app_state: GuiAppState) -> bool:
    with app_state.lock:
        return app_state.show_hidden_neutrals


def _filter_hidden_neutral_targets(neutral_targets, hidden_ids) -> tuple:
    hidden_id_set = set(hidden_ids)
    return tuple(
        target
        for target in neutral_targets
        if _neutral_target_id(target) not in hidden_id_set
    )


def _filter_hidden_hero_targets(
    domain_snapshot: DomainSnapshot,
    hero_targets,
    hidden_ids,
) -> tuple:
    hidden_id_set = set(hidden_ids)
    return tuple(
        target
        for target in hero_targets
        if _hero_id_for_army(domain_snapshot, target.army) not in hidden_id_set
    )


def _resolve_selected_hero_id_for_app(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
    fallback_hero_name: str | None,
) -> str | None:
    with app_state.lock:
        selected_hero_id = app_state.selected_hero_id
        if selected_hero_id is None:
            return None
        if selected_hero_id not in domain_snapshot.hero_by_id:
            selected_hero_id = _hero_id_for_unambiguous_name(
                domain_snapshot,
                fallback_hero_name,
            )
            app_state.selected_hero_id = selected_hero_id
    return selected_hero_id


def _hero_id_for_unambiguous_name(
    domain_snapshot: DomainSnapshot,
    hero_name: str | None,
) -> str | None:
    normalized = hero_name.strip().casefold() if hero_name else ""
    if not normalized:
        return None
    matches = [
        hero_id
        for hero_id, hero in domain_snapshot.hero_entries
        if hero.hero_name.casefold() == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _active_game_dir_for_app(app_state: GuiAppState) -> Path:
    with app_state.lock:
        if app_state.autosave_dir is not None:
            return Path(app_state.autosave_dir).expanduser()
        if app_state.mode == PINNED_MODE and app_state.save_file is not None:
            return Path(app_state.save_file).expanduser().parent
        config_path = app_state.config_path

    config = h3_save_parser.load_config(config_path)
    if config.autosave_dir is not None:
        return config.autosave_dir.expanduser()
    return h3_save_parser.select_game_dir(
        autosave_root=h3_save_parser.DEFAULT_AUTOSAVE_ROOT,
    )


def _clear_snapshot_cache(app_state: GuiAppState) -> None:
    with app_state.snapshot_cache.lock:
        app_state.snapshot_cache.key = None
        app_state.snapshot_cache.snapshot = None


def _game_folders_payload(active_game_dir: Path) -> dict:
    autosave_root = _game_folders_root_for_active_dir(active_game_dir)
    game_folders = _list_game_folders(autosave_root)
    return {
        "autosave_root": str(autosave_root),
        "active_autosave_dir": str(active_game_dir),
        "latest_game_folder": game_folders[0]["path"] if game_folders else None,
        "game_folders": game_folders,
    }


def _select_latest_game_folder(autosave_root: str | Path) -> Path:
    game_folders = _list_game_folders(autosave_root)
    if not game_folders:
        root = Path(autosave_root)
        raise h3_save_parser.SaveSelectionError(
            root,
            "no game folders with supported non-symlink GM1/GM2 saves found",
        )
    return Path(game_folders[0]["path"])


def _game_folders_root_for_active_dir(active_game_dir: str | Path) -> Path:
    default_root = Path(h3_save_parser.DEFAULT_AUTOSAVE_ROOT).expanduser()
    active_path = Path(active_game_dir).expanduser()
    if _path_is_relative_to(active_path, default_root):
        return default_root
    return active_path.parent


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _list_game_folders(autosave_root: str | Path) -> list[dict]:
    root = Path(autosave_root).expanduser()
    return [
        {
            "path": str(folder.path),
            "name": folder.relative_path,
            "relative_path": folder.relative_path,
            "save_count": folder.save_count,
            "latest_save_file": str(folder.latest_save_file),
            "latest_save_mtime_ns": folder.latest_save_mtime_ns,
        }
        for folder in h3_save_parser.list_save_folders(root)
    ]


def _validate_game_dir_for_api(game_dir: str) -> Path:
    folder = Path(game_dir).expanduser()
    try:
        resolved_folder = folder.resolve(strict=True)
    except OSError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"autosave_dir is not a directory: {exc}") from exc
    if not resolved_folder.is_dir():
        raise ApiError(HTTPStatus.BAD_REQUEST, "autosave_dir is not a directory")
    saves = _list_numeric_save_paths(resolved_folder)
    if not saves:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "autosave_dir has no supported non-symlink GM1/GM2 saves",
        )
    return resolved_folder


def _select_latest_gui_save(game_dir: str | Path) -> Path:
    saves = _list_numeric_save_paths(game_dir)
    if not saves:
        folder = Path(game_dir)
        raise h3_save_parser.SaveSelectionError(
            folder,
            "no supported non-symlink GM1/GM2 saves found",
        )
    return saves[-1][4]


def _list_numeric_save_paths(game_dir: str | Path) -> list[tuple[int, int, str, str, Path]]:
    folder = Path(game_dir)
    if not folder.is_dir():
        raise h3_save_parser.SaveSelectionError(
            folder,
            "game folder is not a directory",
        )
    try:
        children = list(folder.iterdir())
    except OSError as exc:
        raise h3_save_parser.SaveSelectionError(
            folder,
            f"failed to list game folder: {exc}",
        ) from exc

    saves = []
    for child in children:
        if child.is_symlink() or not child.is_file():
            continue
        numeric_save = h3_save_parser.parse_numeric_save_name(child)
        if numeric_save is None:
            continue
        number, extension_rank = numeric_save
        saves.append((
            number,
            extension_rank,
            h3_save_parser.normalize_save_name(child),
            child.name,
            child,
        ))
    return sorted(saves, key=lambda item: item[:4])


def _list_numeric_saves(game_dir: str | Path) -> list[dict]:
    saves = []
    for number, extension_rank, name, _, child in _list_numeric_save_paths(game_dir):
        fingerprint = _file_fingerprint(child)
        saves.append((
            number,
            extension_rank,
            name,
            {
                "path": str(child),
                "name": name,
                "number": number,
                "extension": child.suffix.lstrip(".").upper(),
                "size": fingerprint["size"],
                "mtime": fingerprint["mtime"],
                "mtime_ns": fingerprint["mtime_ns"],
            },
        ))

    return [item[3] for item in saves]


def _validate_pinned_save_for_app(app_state: GuiAppState, save_file: str) -> Path:
    save_path = Path(save_file).expanduser()
    try:
        resolved_save_path = save_path.resolve(strict=True)
    except OSError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"save_file is not a file: {exc}") from exc
    if save_path.is_symlink():
        raise ApiError(HTTPStatus.BAD_REQUEST, "save_file must not be a symlink")
    if not resolved_save_path.is_file():
        raise ApiError(HTTPStatus.BAD_REQUEST, "save_file is not a file")
    if h3_save_parser.parse_numeric_save_name(resolved_save_path) is None:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "save_file must be numeric or GAME_BEGIN .GM1/.GM2",
        )

    active_game_dir = _active_game_dir_for_app(app_state)
    if resolved_save_path.parent != active_game_dir.resolve():
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "pinned save_file must belong to the active autosave folder",
        )
    return save_path


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{key} must be a non-empty string")
    return value.strip()


def _validate_hidden_neutral_target(
    domain_snapshot: DomainSnapshot,
    target_id: str,
) -> None:
    if not re.fullmatch(r"neutral:\d+", target_id):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "target_id must be neutral:<object_index>",
        )
    known_target_ids = {
        _neutral_target_id(target)
        for target in domain_snapshot.neutral_targets
    }
    if target_id not in known_target_ids:
        raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")


def _validate_hidden_hero_target(
    domain_snapshot: DomainSnapshot,
    target_id: str,
    selected_hero_id: str | None = None,
) -> None:
    if not h3_save_parser.HIDDEN_HERO_TARGET_PATTERN.fullmatch(target_id):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "target_id must be hero:<stable_id>",
        )
    if target_id == selected_hero_id:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "selected hero is not a hideable target",
        )
    if target_id not in domain_snapshot.hero_by_id:
        raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")


def _bounded_int(
    payload: dict,
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{key} must be an integer")
    parsed = value
    if parsed < minimum or parsed > maximum:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            f"{key} must be between {minimum} and {maximum}",
        )
    return parsed


def _optional_bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    raise ApiError(HTTPStatus.BAD_REQUEST, f"{key} must be a boolean")


def _hero_by_id(domain_snapshot: DomainSnapshot, hero_id: str):
    hero = domain_snapshot.hero_by_id.get(hero_id)
    if hero is None:
        raise ApiError(HTTPStatus.NOT_FOUND, f"unknown hero_id: {hero_id}")
    return hero


def _request_hero_by_id(
    app_state: GuiAppState,
    domain_snapshot: DomainSnapshot,
    hero_id: str,
):
    hero = domain_snapshot.hero_by_id.get(hero_id)
    if hero is not None:
        return hero
    with app_state.lock:
        if app_state.selected_hero_id == hero_id:
            app_state.selected_hero_id = None
            raise ApiError(
                HTTPStatus.CONFLICT,
                "selected hero is no longer available in the current snapshot",
            )
    raise ApiError(HTTPStatus.NOT_FOUND, f"unknown hero_id: {hero_id}")


def _single_scan_target(
    domain_snapshot: DomainSnapshot,
    selected_hero,
    target_id: str,
    hidden_neutral_target_ids=(),
    hidden_hero_target_ids=(),
    include_hidden_targets: bool = False,
):
    neutral = domain_snapshot.neutral_by_id.get(target_id)
    if neutral is not None:
        if target_id in set(hidden_neutral_target_ids) and not include_hidden_targets:
            raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")
        return _scan_target_for_raw_target("neutral", selected_hero, neutral), target_id

    hero_target = _hero_target_by_id(
        domain_snapshot,
        selected_hero,
        target_id,
        same_level_z=None,
        team_by_color=domain_snapshot.team_by_color,
    )
    if hero_target is not None:
        if target_id in set(hidden_hero_target_ids) and not include_hidden_targets:
            raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")
        return _scan_target_for_raw_target("hero", selected_hero, hero_target), target_id

    raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")


def _hero_target_by_id(
    domain_snapshot: DomainSnapshot,
    selected_hero,
    target_id: str,
    same_level_z: int | None,
    team_by_color: dict[int, int] | None = None,
):
    hero_targets = h3_save_parser.build_other_hero_targets(
        domain_snapshot.heroes,
        selected_hero,
        same_level_z=same_level_z,
        team_by_color=team_by_color,
    )
    for hero_target in hero_targets:
        if _hero_id_for_army(domain_snapshot, hero_target.army) == target_id:
            return hero_target
    return None


def _hero_id_for_army(domain_snapshot: DomainSnapshot, hero_army) -> str | None:
    for hero_id, candidate in domain_snapshot.hero_entries:
        if candidate is hero_army:
            return hero_id
        if (
            candidate.source_offset is not None
            and hero_army.source_offset is not None
            and candidate.source_offset == hero_army.source_offset
        ):
            return hero_id
    return None


def _scan_target_for_raw_target(target_type: str, selected_hero, target):
    return battle_estimator.NearbyScanTarget(
        target_type=target_type,
        distance=_target_distance(selected_hero, target),
        x=target.x,
        y=target.y,
        z=target.z,
        target=target,
    )


def _target_distance(selected_hero, target) -> int:
    if selected_hero.position is None:
        return 0
    return abs(target.x - selected_hero.x) + abs(target.y - selected_hero.y)


def _serialize_scan_estimate(
    domain_snapshot: DomainSnapshot,
    estimate: battle_estimator.NearbyScanEstimate,
) -> dict:
    target_id = _target_id_for_estimate(domain_snapshot, estimate)
    return {
        "target_id": target_id,
        "target_type": estimate.target_type,
        "distance": estimate.distance,
        "position": {"x": estimate.x, "y": estimate.y, "z": estimate.z},
        "target": _serialize_scan_target(domain_snapshot, estimate),
        "enemy_army": [
            {
                "creature_name": creature.name,
                "count": count,
                "ai_value": creature.ai_value * count,
            }
            for creature, count in estimate.enemy_army
        ],
        "enemy_ai_value": estimate.enemy_ai_value,
        "win_pct": estimate.win_pct,
        "note": estimate.note,
    }


def _target_id_for_estimate(
    domain_snapshot: DomainSnapshot,
    estimate: battle_estimator.NearbyScanEstimate,
) -> str | None:
    target = estimate.scan_target.target
    if estimate.target_type == "neutral":
        return _neutral_target_id(target)
    if estimate.target_type == "hero":
        return _hero_id_for_army(domain_snapshot, target.army)
    return None


def _serialize_scan_target(
    domain_snapshot: DomainSnapshot,
    estimate: battle_estimator.NearbyScanEstimate,
) -> dict:
    target = estimate.scan_target.target
    if estimate.target_type == "neutral":
        return _serialize_neutral_target(target)

    target_id = _hero_id_for_army(domain_snapshot, target.army)
    payload = _serialize_hero(
        target.army,
        target_id,
        domain_snapshot.team_by_color,
    )
    payload["name"] = target.hero_name
    payload["position"] = _serialize_position(target.position)
    payload["army_summary"] = target.army_summary
    payload["total_creatures"] = target.total_creatures
    payload["ai_value"] = target.ai_value
    return payload


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="H3 Companion GUI")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="host interface to bind; defaults to localhost only",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=int,
        help=f"TCP port to bind; defaults to {DEFAULT_PORT}",
    )
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port)
    print(server_url(server), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GUI server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
