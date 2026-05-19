from __future__ import annotations

import gzip
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from tools import battle_estimator_gui
from tests.test_battle_estimator_cli import (
    _build_xor_hero_fixture,
    _removed_neutral_record_core_bytes,
    _write_h3m_map,
)


class BattleEstimatorGuiServerTests(unittest.TestCase):
    def _with_server(self, callback):
        server = battle_estimator_gui.create_server(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            callback(battle_estimator_gui.server_url(server))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def _get(self, base_url, path):
        with urlopen(f"{base_url}{path}", timeout=2) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                response.read(),
            )

    def test_health_endpoint_returns_json_ok(self):
        def check(base_url):
            status, content_type, body = self._get(base_url, "/api/health")

            self.assertEqual(status, 200)
            self.assertEqual(content_type, "application/json")
            self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})

        self._with_server(check)

    def test_static_assets_are_served_from_whitelisted_routes(self):
        def check(base_url):
            cases = (
                ("/", "text/html; charset=utf-8", b"VCMI Battle Estimator"),
                ("/index.html", "text/html; charset=utf-8", b"/app.js"),
                ("/app.js", "application/javascript; charset=utf-8", b"/api/health"),
                ("/style.css", "text/css; charset=utf-8", b".app-shell"),
            )
            for path, expected_type, expected_body in cases:
                with self.subTest(path=path):
                    status, content_type, body = self._get(base_url, path)

                    self.assertEqual(status, 200)
                    self.assertEqual(content_type, expected_type)
                    self.assertIn(expected_body, body)

        self._with_server(check)

    def test_static_routes_are_allowlisted(self):
        def check(base_url):
            for path in ("/missing", "/../battle_estimator.py", "/%2e%2e/battle_estimator.py"):
                with self.subTest(path=path):
                    with self.assertRaises(HTTPError) as raised:
                        self._get(base_url, path)

                    self.assertEqual(raised.exception.code, 404)

        self._with_server(check)

    def test_default_server_binds_to_localhost(self):
        server = battle_estimator_gui.create_server(port=0)
        try:
            host, _ = server.server_address[:2]

            self.assertEqual(host, battle_estimator_gui.DEFAULT_HOST)
        finally:
            server.server_close()


class BattleEstimatorGuiSnapshotTests(unittest.TestCase):
    def test_follow_latest_snapshot_uses_latest_numeric_save_and_marks_removed_neutrals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            older_save = _write_gui_save(game_dir, "001.GM2", hero_name="Old")
            latest_save = _write_gui_save(
                game_dir,
                "002.GM2",
                hero_name="Isra",
                position=(39, 69, 1),
                removed_object_index=1,
                removed_h3m_subid=98,
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                sign_before_monster=True,
            )
            before = _file_state(latest_save, map_path)

            snapshot = battle_estimator_gui.build_state_snapshot(
                autosave_dir=game_dir,
                map_file=map_path,
            )

            self.assertEqual(snapshot["mode"], battle_estimator_gui.FOLLOW_LATEST_MODE)
            self.assertEqual(snapshot["autosave_dir"], str(game_dir))
            self.assertEqual(snapshot["save_file"], str(latest_save))
            self.assertNotEqual(snapshot["save_file"], str(older_save))
            self.assertEqual(snapshot["map_file"], str(map_path))
            self.assertEqual(snapshot["map"], {"width": 1, "height": 1, "levels": 1})
            self.assertEqual(
                snapshot["save_fingerprint"],
                _expected_fingerprint(latest_save),
            )
            self.assertEqual(
                snapshot["map_fingerprint"],
                _expected_fingerprint(map_path),
            )

            self.assertEqual(len(snapshot["heroes"]), 1)
            hero = snapshot["heroes"][0]
            self.assertEqual(hero["id"], "hero:256")
            self.assertEqual(hero["name"], "Isra")
            self.assertEqual(hero["position"], {"x": 39, "y": 69, "z": 1})
            self.assertEqual(hero["army"][0]["creature_name"], "Skeleton Warrior")
            self.assertEqual(hero["army"][0]["count"], 731)
            self.assertGreater(hero["ai_value"], 0)

            self.assertEqual(len(snapshot["neutral_targets"]), 1)
            neutral = snapshot["neutral_targets"][0]
            self.assertEqual(neutral["id"], "neutral:1")
            self.assertEqual(neutral["object_index"], 1)
            self.assertEqual(neutral["position"], {"x": 39, "y": 70, "z": 1})
            self.assertEqual(neutral["h3m_subid"], 98)
            self.assertEqual(neutral["count"], 37)
            self.assertEqual(neutral["creature_name"], "Gnoll")
            self.assertEqual(neutral["estimator_creature_id"], 98)
            self.assertTrue(neutral["removed"])
            self.assertTrue(neutral["removal_note"].startswith("removed-save-record@"))
            json.dumps(snapshot)
            self.assertEqual(_file_state(latest_save, map_path), before)

    def test_follow_latest_snapshot_uses_configured_game_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "configured-game"
            game_dir.mkdir()
            latest_save = _write_gui_save(game_dir, "009.GM1", hero_name="Config")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps({"autosave_dir": str(game_dir)}) + "\n",
                encoding="utf-8",
            )

            snapshot = battle_estimator_gui.build_state_snapshot(
                map_file=map_path,
                config_path=config_path,
            )

            self.assertEqual(snapshot["save_file"], str(latest_save))
            self.assertEqual(snapshot["heroes"][0]["name"], "Config")

    def test_pinned_snapshot_uses_explicit_save_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            latest_save = _write_gui_save(game_dir, "010.GM2", hero_name="Latest")
            pinned_save = _write_gui_save(
                game_dir,
                "003.GM1",
                hero_name="Pinned",
                position=None,
            )
            map_path = _write_h3m_map(temp_path / "map.h3m")

            snapshot = battle_estimator_gui.build_state_snapshot(
                mode=battle_estimator_gui.PINNED_MODE,
                save_file=pinned_save,
                map_file=map_path,
            )

            self.assertEqual(snapshot["mode"], battle_estimator_gui.PINNED_MODE)
            self.assertEqual(snapshot["save_file"], str(pinned_save))
            self.assertNotEqual(snapshot["save_file"], str(latest_save))
            self.assertEqual(snapshot["heroes"][0]["name"], "Pinned")
            self.assertIsNone(snapshot["heroes"][0]["position"])

    def test_snapshot_rejects_save_file_changed_during_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_path = _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            original_load_save = battle_estimator_gui.h3_save_parser.load_save

            def changing_load_save(path):
                loaded = original_load_save(path)
                save_path.write_bytes(save_path.read_bytes() + b"changed")
                return loaded

            with patch.object(
                battle_estimator_gui.h3_save_parser,
                "load_save",
                side_effect=changing_load_save,
            ):
                with self.assertRaises(battle_estimator_gui.SnapshotConsistencyError):
                    battle_estimator_gui.build_state_snapshot(
                        autosave_dir=game_dir,
                        map_file=map_path,
                    )


def _write_gui_save(
    game_dir: Path,
    name: str,
    hero_name: str,
    position=(39, 69, 1),
    removed_object_index: int | None = None,
    removed_h3m_subid: int | None = None,
) -> Path:
    payload = _build_xor_hero_fixture(hero_name=hero_name, position=position)
    if removed_object_index is not None and removed_h3m_subid is not None:
        payload += (
            b"\x00" * 3
            + _removed_neutral_record_core_bytes(
                removed_object_index,
                removed_h3m_subid,
                0x9000,
            )
        )
    save_path = game_dir / name
    save_path.write_bytes(gzip.compress(payload))
    return save_path


def _expected_fingerprint(path: Path) -> dict:
    stat_result = path.stat()
    return {
        "path": str(path),
        "size": stat_result.st_size,
        "mtime": stat_result.st_mtime,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _file_state(*paths: Path) -> tuple[tuple[bytes, int, int], ...]:
    return tuple(
        (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    )


if __name__ == "__main__":
    unittest.main()
