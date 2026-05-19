#!/usr/bin/env python3
"""Local browser GUI server for the VCMI battle estimator."""

from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    from tools import h3_map_parser, h3_save_parser
except ImportError:  # pragma: no cover - direct script execution fallback.
    import h3_map_parser
    import h3_save_parser


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
FOLLOW_LATEST_MODE = "follow_latest"
PINNED_MODE = "pinned"
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


class BattleEstimatorGuiHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local read-only GUI."""

    server_version = "VCMIBattleEstimatorGUI/0.1"

    def do_GET(self):
        self._handle_get(send_body=True)

    def do_HEAD(self):
        self._handle_get(send_body=False)

    def _handle_get(self, send_body: bool):
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json({"ok": True}, send_body=send_body)
            return

        static_name = STATIC_ROUTES.get(path)
        if static_name is not None:
            self._send_static(static_name, send_body=send_body)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_json(self, payload, send_body: bool):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

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
) -> ThreadingHTTPServer:
    """Create a local GUI HTTP server without starting its serve loop."""

    return ThreadingHTTPServer((host, port), BattleEstimatorGuiHandler)


def build_state_snapshot(
    mode: str = FOLLOW_LATEST_MODE,
    autosave_dir: str | Path | None = None,
    save_file: str | Path | None = None,
    map_file: str | Path | None = None,
    config_path: str | Path = h3_save_parser.CONFIG_PATH,
) -> dict:
    """Build a JSON-serializable GUI state snapshot from save and map files."""

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
    loaded_save = h3_save_parser.load_save(save_context.save_file)
    heroes = h3_save_parser.scan_xor01_hero_armies(loaded_save.data)
    loaded_map = h3_map_parser.load_h3m(resolved_map_file, parse_objects=True)
    removed_records = h3_save_parser.detect_removed_neutral_records(
        loaded_save.data,
        loaded_map.neutral_targets,
    )
    neutral_targets = h3_map_parser.filter_removed_neutral_targets(
        loaded_map.neutral_targets,
        removed_records,
        include_removed=True,
    )
    _ensure_unchanged(save_context.save_file, save_fingerprint)
    _ensure_unchanged(resolved_map_file, map_fingerprint)

    return {
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
        "heroes": _serialize_heroes(heroes),
        "neutral_targets": [
            _serialize_neutral_target(target)
            for target in neutral_targets
        ],
    }


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

    save_path = h3_save_parser.select_latest_save(game_dir)
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


def _serialize_heroes(heroes) -> list[dict]:
    hero_ids = _unique_hero_ids(heroes)
    return [
        _serialize_hero(hero, hero_id)
        for hero, hero_id in zip(heroes, hero_ids)
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
        "id": f"neutral:{target.object_index}",
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


def _serialize_position(position) -> dict | None:
    if position is None:
        return None
    return {
        "x": position.x,
        "y": position.y,
        "z": position.z,
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
