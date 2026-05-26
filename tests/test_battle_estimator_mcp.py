from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import battle_estimator_gui, battle_estimator_mcp, h3_save_parser
from tests.test_battle_estimator_cli import _write_h3m_map
from tests.test_battle_estimator_gui import _write_gui_save


class AdvisorContextServiceTests(unittest.TestCase):
    def test_loads_follow_latest_from_config_without_mutating_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "configured-game"
            game_dir.mkdir()
            latest_save = _write_gui_save(game_dir, "009.GM1", hero_name="Config")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_payload = {
                "autosave_dir": str(game_dir),
                "last_hero": "Config",
                "recent_heroes": ["Config"],
                "hidden_neutral_targets_by_map": {"map": ["neutral:1"]},
            }
            config_path.write_text(json.dumps(config_payload) + "\n", encoding="utf-8")
            before_config = config_path.read_bytes()

            service = battle_estimator_mcp.AdvisorContextService(
                map_file=map_path,
                config_path=config_path,
            )
            metadata = service.refresh_context()
            snapshot = service.get_domain_snapshot()

            self.assertEqual(metadata["mode"], battle_estimator_gui.FOLLOW_LATEST_MODE)
            self.assertEqual(metadata["autosave_dir"], str(game_dir))
            self.assertEqual(metadata["save_file"], str(latest_save))
            self.assertEqual(metadata["save_name"], "009.GM1")
            self.assertEqual(metadata["map_file"], str(map_path))
            self.assertEqual(metadata["map_name"], "map.h3m")
            self.assertEqual(metadata["hero_count"], 1)
            self.assertEqual(snapshot.state["save_file"], str(latest_save))
            self.assertEqual(snapshot.state["heroes"][0]["name"], "Config")
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_game_dir_override_picks_latest_numeric_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            older_save = _write_gui_save(game_dir, "001.GM2", hero_name="Old")
            latest_save = _write_gui_save(game_dir, "002.GM2", hero_name="Latest")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            service = battle_estimator_mcp.AdvisorContextService(
                game_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )
            metadata = service.refresh_context()

            self.assertEqual(metadata["save_file"], str(latest_save))
            self.assertNotEqual(metadata["save_file"], str(older_save))

    def test_save_file_override_defaults_to_pinned_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_gui_save(game_dir, "010.GM2", hero_name="Latest")
            pinned_save = _write_gui_save(game_dir, "003.GM1", hero_name="Pinned")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            service = battle_estimator_mcp.AdvisorContextService(
                save_file=pinned_save,
                map_file=map_path,
                config_path=config_path,
            )
            metadata = service.refresh_context()

            self.assertEqual(metadata["mode"], battle_estimator_gui.PINNED_MODE)
            self.assertEqual(metadata["save_file"], str(pinned_save))
            self.assertEqual(service.get_domain_snapshot().state["heroes"][0]["name"], "Pinned")

    def test_rejects_explicit_follow_latest_with_save_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_file = Path(temp_dir) / "001.GM2"
            save_file.write_bytes(b"not-used")

            with self.assertRaisesRegex(ValueError, "save_file requires pinned mode"):
                battle_estimator_mcp.AdvisorContextService(
                    mode=battle_estimator_gui.FOLLOW_LATEST_MODE,
                    save_file=save_file,
                )

    def test_cache_stays_stale_until_refresh_and_metadata_is_deep_copied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_one = _write_gui_save(game_dir, "001.GM2", hero_name="One")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            service = battle_estimator_mcp.AdvisorContextService(
                game_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )
            first_metadata = service.refresh_context()
            first_metadata["save_fingerprint"]["path"] = "mutated"
            self.assertNotEqual(
                service.cached_metadata()["save_fingerprint"]["path"],
                "mutated",
            )
            self.assertEqual(service.get_domain_snapshot().state["save_file"], str(save_one))

            save_two = _write_gui_save(game_dir, "002.GM2", hero_name="Two")

            self.assertEqual(service.get_domain_snapshot().state["save_file"], str(save_one))
            refreshed_snapshot = service.get_domain_snapshot(refresh=True)
            refreshed_metadata = service.cached_metadata()
            self.assertEqual(refreshed_snapshot.state["save_file"], str(save_two))
            self.assertEqual(refreshed_metadata["save_file"], str(save_two))

    def test_failed_refresh_preserves_previous_cached_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            save_path = _write_gui_save(game_dir, "001.GM2", hero_name="Isra")
            map_path = _write_h3m_map(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            service = battle_estimator_mcp.AdvisorContextService(
                game_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )
            service.refresh_context()
            cached_snapshot = service.get_domain_snapshot()
            cached_metadata = service.cached_metadata()

            with patch.object(
                battle_estimator_mcp.battle_estimator_gui,
                "build_domain_snapshot",
                side_effect=h3_save_parser.SaveSelectionError(save_path, "boom"),
            ):
                with self.assertRaises(h3_save_parser.SaveSelectionError):
                    service.refresh_context()

            self.assertIs(service.get_domain_snapshot(), cached_snapshot)
            self.assertEqual(service.cached_metadata(), cached_metadata)


if __name__ == "__main__":
    unittest.main()
