#!/usr/bin/env python3
"""Local browser GUI server for the VCMI battle estimator."""

from __future__ import annotations

import argparse
import json
import re
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from tools import battle_estimator, h3_map_parser, h3_save_parser
except ImportError:  # pragma: no cover - direct script execution fallback.
    import battle_estimator
    import h3_map_parser
    import h3_save_parser


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
    removed_records: tuple


@dataclass(frozen=True)
class DomainSnapshotSource:
    """Resolved files and fingerprints used to build a domain snapshot."""

    save_context: h3_save_parser.SaveContext
    map_file: Path
    save_fingerprint: dict
    map_fingerprint: dict


class BattleEstimatorGuiHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local read-only GUI."""

    server_version = "VCMIBattleEstimatorGUI/0.1"

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
            "/api/simulate-target": self._api_simulate_target,
            "/api/scan-radius": self._api_scan_radius,
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
            game_dir = _select_latest_game_folder(active_game_dir.parent)
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
        scan_target, resolved_target_id = _single_scan_target(
            domain_snapshot,
            selected_hero,
            target_id,
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
        hero_targets = h3_save_parser.build_other_hero_targets(
            domain_snapshot.heroes,
            selected_hero,
            same_level_z=selected_hero.z,
        )
        scan_targets = battle_estimator.build_nearby_scan_targets(
            selected_hero,
            neutral_targets=domain_snapshot.neutral_targets,
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
    heroes = h3_save_parser.scan_xor01_hero_armies(loaded_save.data)
    loaded_map = h3_map_parser.load_h3m(resolved_map_file, parse_objects=True)
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
        "heroes": _serialize_heroes(hero_entries),
        "neutral_targets": [
            _serialize_neutral_target(target)
            for target in neutral_targets
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
        removed_records=removed_records,
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
        autosave_root = game_dir.parent
    else:
        config = h3_save_parser.load_config(config_path)
        if config.autosave_dir is not None:
            game_dir = config.autosave_dir.expanduser()
            autosave_root = game_dir.parent
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


def _serialize_heroes(hero_entries) -> list[dict]:
    return [
        _serialize_hero(hero, hero_id)
        for hero_id, hero in hero_entries
    ]


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


def _serialize_hero(hero, hero_id: str) -> dict:
    return {
        "id": hero_id,
        "name": hero.hero_name,
        "source_offset": hero.source_offset,
        "position": _serialize_position(hero.position),
        "army": [_serialize_hero_stack(stack) for stack in hero.stacks],
        "army_summary": hero.army_summary,
        "total_creatures": hero.total_creatures,
        "ai_value": hero.ai_value,
    }


def _serialize_hero_stack(stack) -> dict:
    return {
        "creature_id": stack.creature_id,
        "creature_name": stack.creature.name,
        "count": stack.count,
    }


def _serialize_neutral_target(target) -> dict:
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
    }


def _neutral_target_id(target) -> str:
    return f"neutral:{target.object_index}"


def _serialize_position(position) -> dict | None:
    if position is None:
        return None
    return {
        "x": position.x,
        "y": position.y,
        "z": position.z,
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
    selected_hero_id = _resolve_selected_hero_id_for_app(
        app_state,
        domain_snapshot,
        config.last_hero,
    )
    payload = dict(domain_snapshot.state)
    payload["selected_hero_id"] = selected_hero_id
    payload["recent_heroes"] = list(config.recent_heroes)
    return payload


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
    autosave_root = active_game_dir.parent
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
            "no game folders with numeric non-symlink GM1/GM2 saves found",
        )
    return Path(game_folders[0]["path"])


def _list_game_folders(autosave_root: str | Path) -> list[dict]:
    root = Path(autosave_root).expanduser()
    if not root.is_dir():
        raise h3_save_parser.SaveSelectionError(
            root,
            "autosave root is not a directory",
        )
    try:
        children = list(root.iterdir())
    except OSError as exc:
        raise h3_save_parser.SaveSelectionError(
            root,
            f"failed to list autosave root: {exc}",
        ) from exc

    dated_folders = []
    other_folders = []
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        saves = _list_numeric_saves(child)
        if not saves:
            continue
        latest_save = saves[-1]
        entry = {
            "path": str(child),
            "name": child.name,
            "save_count": len(saves),
            "latest_save_file": latest_save["path"],
        }
        folder_date = h3_save_parser.parse_game_folder_datetime(child.name)
        if folder_date is None:
            other_folders.append((child.name.casefold(), entry))
        else:
            dated_folders.append((folder_date, child.name, entry))

    dated_folders.sort(key=lambda item: (item[0], item[1]), reverse=True)
    other_folders.sort(key=lambda item: item[0])
    return [item[2] for item in dated_folders] + [item[1] for item in other_folders]


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
            "autosave_dir has no numeric non-symlink GM1/GM2 saves",
        )
    return resolved_folder


def _select_latest_gui_save(game_dir: str | Path) -> Path:
    saves = _list_numeric_save_paths(game_dir)
    if not saves:
        folder = Path(game_dir)
        raise h3_save_parser.SaveSelectionError(
            folder,
            "no numeric non-symlink GM1/GM2 saves found",
        )
    return saves[-1][3]


def _list_numeric_save_paths(game_dir: str | Path) -> list[tuple[int, int, str, Path]]:
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
        saves.append((number, extension_rank, child.name, child))
    return sorted(saves, key=lambda item: item[:3])


def _list_numeric_saves(game_dir: str | Path) -> list[dict]:
    saves = []
    for number, extension_rank, name, child in _list_numeric_save_paths(game_dir):
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
        raise ApiError(HTTPStatus.BAD_REQUEST, "save_file must be numeric .GM1/.GM2")

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
):
    neutral = domain_snapshot.neutral_by_id.get(target_id)
    if neutral is not None:
        return _scan_target_for_raw_target("neutral", selected_hero, neutral), target_id

    hero_target = _hero_target_by_id(
        domain_snapshot,
        selected_hero,
        target_id,
        same_level_z=None,
    )
    if hero_target is not None:
        return _scan_target_for_raw_target("hero", selected_hero, hero_target), target_id

    raise ApiError(HTTPStatus.NOT_FOUND, f"unknown target_id: {target_id}")


def _hero_target_by_id(
    domain_snapshot: DomainSnapshot,
    selected_hero,
    target_id: str,
    same_level_z: int | None,
):
    hero_targets = h3_save_parser.build_other_hero_targets(
        domain_snapshot.heroes,
        selected_hero,
        same_level_z=same_level_z,
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
    return {
        "id": target_id,
        "name": target.hero_name,
        "position": _serialize_position(target.position),
        "army_summary": target.army_summary,
        "total_creatures": target.total_creatures,
        "ai_value": target.ai_value,
    }


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="VCMI Battle Estimator GUI")
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
