from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import (
    battle_estimator_gui,
    battle_estimator_mcp,
    h3_map_parser,
    h3_save_parser,
)
from tests.test_battle_estimator_cli import _write_h3m_map
from tests.test_battle_estimator_gui import (
    _gui_town_state_record_bytes,
    _write_gui_save,
    _write_h3m_map_with_town,
    _write_multi_gui_save,
)
from tests.test_h3_map_parser import (
    _build_minimal_sod_h3m_with_teams,
    _object_bytes,
    _object_template_bytes,
    _town_payload,
)


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


class AdvisorContextBuilderTests(unittest.TestCase):
    def test_color_scope_groups_own_allied_enemy_and_unknown_heroes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = _advisor_service_with_team_map(Path(temp_dir), (
                {
                    "hero_name": "Redmain",
                    "name_offset": 256,
                    "position": (0, 0, 0),
                    "owner_color_id": 0,
                },
                {
                    "hero_name": "Blueally",
                    "name_offset": 640,
                    "position": (0, 0, 0),
                    "owner_color_id": 1,
                },
                {
                    "hero_name": "Tanenemy",
                    "name_offset": 1024,
                    "position": (0, 0, 0),
                    "owner_color_id": 2,
                },
                {
                    "hero_name": "Greenenemy",
                    "name_offset": 1408,
                    "position": (0, 0, 0),
                    "owner_color_id": 3,
                },
            ))

            context = service.get_advisor_context(0, refresh=True)

            self.assertEqual(context["subject"]["scope"], "color")
            self.assertEqual(context["subject"]["color_name"], "red")
            self.assertEqual(context["subject"]["team_id"], 0)
            self.assertEqual(context["subject"]["allied_color_ids"], [1])
            self.assertEqual(context["subject"]["subject_color_ids"], [0])
            self.assertEqual(
                [hero["name"] for hero in context["heroes"]["own"]["items"]],
                ["Redmain"],
            )
            self.assertEqual(
                [hero["name"] for hero in context["heroes"]["allied"]["items"]],
                ["Blueally"],
            )
            self.assertEqual(
                [hero["name"] for hero in context["heroes"]["enemy"]["items"]],
                ["Greenenemy", "Tanenemy"],
            )
            self.assertEqual(context["heroes"]["unknown"]["total_count"], 0)
            self.assertIn("snapshot", context)
            self.assertIn("towns", context)
            self.assertIn("alerts", context)
            self.assertIn("nearby_opportunities", context)
            self.assertIn("portals", context)
            self.assertIn("routes", context)
            self.assertEqual(context["alerts"]["status"], "no_owned_towns")
            self.assertEqual(context["nearby_opportunities"]["tool_hint"], "scan_nearby")
            self.assertEqual(context["routes"]["tool_hint"], "find_route")
            self.assertTrue(context["known_limitations"])
            self.assertNotIn("heroes", context["snapshot"])

    def test_team_scope_expands_subject_to_allied_colors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = _advisor_service_with_team_map(Path(temp_dir), (
                {
                    "hero_name": "Redmain",
                    "name_offset": 256,
                    "position": (0, 0, 0),
                    "owner_color_id": 0,
                },
                {
                    "hero_name": "Blueally",
                    "name_offset": 640,
                    "position": (0, 0, 0),
                    "owner_color_id": 1,
                },
                {
                    "hero_name": "Tanenemy",
                    "name_offset": 1024,
                    "position": (0, 0, 0),
                    "owner_color_id": 2,
                },
            ))

            context = service.get_advisor_context(0, scope="team", refresh=True)

            self.assertEqual(context["subject"]["scope"], "team")
            self.assertEqual(context["subject"]["subject_color_ids"], [0, 1])
            self.assertEqual(context["subject"]["subject_color_names"], ["red", "blue"])
            opportunity_names = [
                hero["name"]
                for hero in context["nearby_opportunities"]["candidate_heroes"]["items"]
            ]
            self.assertEqual(opportunity_names, ["Blueally", "Redmain"])
            route_names = [
                hero["name"]
                for hero in context["routes"]["candidate_heroes"]
            ]
            self.assertEqual(route_names, ["Blueally", "Redmain"])

    def test_team_scope_alerts_include_allied_owned_towns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            _write_multi_gui_save(
                game_dir,
                "001.GM2",
                (
                    {
                        "hero_name": "Redmain",
                        "name_offset": 256,
                        "position": (0, 0, 0),
                        "owner_color_id": 0,
                    },
                    {
                        "hero_name": "Enemy",
                        "name_offset": 640,
                        "position": (6, 6, 0),
                        "owner_color_id": 2,
                    },
                ),
                town_state_records=(
                    _gui_town_state_record_bytes(owner_color_id=1),
                ),
            )
            map_path = _write_team_town_h3m(temp_path / "team-town.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text(json.dumps({"alert_radius": 10}), encoding="utf-8")
            service = battle_estimator_mcp.AdvisorContextService(
                game_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            color_context = service.get_advisor_context(0, refresh=True)
            team_context = service.get_advisor_context(0, scope="team", refresh=False)

            self.assertEqual(color_context["alerts"]["status"], "no_owned_towns")
            self.assertEqual(team_context["alerts"]["status"], "ok")
            self.assertEqual(team_context["alerts"]["items"][0]["town_name"], "Blue Keep")
            self.assertEqual(team_context["alerts"]["items"][0]["enemy_hero_name"], "Enemy")

    def test_team_scope_reports_limitation_without_team_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = _advisor_service_with_no_explicit_team_map(Path(temp_dir), (
                {
                    "hero_name": "Redmain",
                    "name_offset": 256,
                    "position": (0, 0, 0),
                    "owner_color_id": 0,
                },
            ))

            context = service.get_advisor_context(0, scope="team", refresh=True)

            self.assertFalse(context["subject"]["team_scope_available"])
            self.assertEqual(context["subject"]["subject_color_ids"], [0])
            limitation_ids = [item["id"] for item in context["known_limitations"]]
            self.assertIn("team_scope_unavailable", limitation_ids)
            self.assertIn("fog_of_war", limitation_ids)

    def test_alert_status_detail_is_bounded(self):
        long_detail = "unavailable town ownership: " + ", ".join(
            f"town:{index}" for index in range(100)
        )
        result = battle_estimator_gui.CastleAlertResult(
            battle_estimator_gui.CASTLE_ALERT_STATUS_OWNERSHIP_UNAVAILABLE,
            status_detail=long_detail,
        )

        payload = battle_estimator_mcp._advisor_alerts_section(
            result,
            include_raw_ids=True,
        )

        self.assertLessEqual(
            len(payload["status_detail"]),
            battle_estimator_mcp.MAX_CONTEXT_STATUS_DETAIL_CHARS,
        )
        self.assertTrue(payload["status_detail"].endswith("..."))

    def test_unknown_color_and_invalid_scope_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = _advisor_service_with_team_map(Path(temp_dir), (
                {
                    "hero_name": "Redmain",
                    "name_offset": 256,
                    "position": (0, 0, 0),
                    "owner_color_id": 0,
                },
            ))

            with self.assertRaisesRegex(ValueError, "not an active map player"):
                service.get_advisor_context(7, refresh=True)
            with self.assertRaisesRegex(ValueError, "invalid advisor scope"):
                service.get_advisor_context(0, scope="alliance", refresh=True)


class AdvisorComputeToolTests(unittest.TestCase):
    def test_scan_nearby_returns_neutral_and_enemy_hero_estimates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, config_path = _advisor_scan_service(Path(temp_dir))
            before_config = config_path.read_bytes()

            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                side_effect=(91.5, 72.0),
            ) as run_mock:
                payload = service.scan_nearby(
                    "hero:256",
                    radius=2,
                    target_type="all",
                    simulations=7,
                    refresh=True,
                )

            self.assertEqual(payload["hero_id"], "hero:256")
            self.assertEqual(payload["radius"], 2)
            self.assertEqual(payload["target_type"], "all")
            self.assertEqual(payload["sort_mode"], "distance")
            self.assertEqual(payload["simulations"], 7)
            self.assertEqual(payload["result_count"], 2)
            self.assertEqual(
                [
                    (item["target_id"], item["distance"], item["win_pct"])
                    for item in payload["results"]
                ],
                [("neutral:0", 1, 91.5), ("hero:512", 2, 72.0)],
            )
            self.assertEqual(payload["results"][1]["target"]["name"], "Marius")
            self.assertTrue(payload["known_limitations"])
            self.assertEqual(run_mock.call_count, 2)
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_scan_nearby_supports_easiest_sort_and_hero_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, _ = _advisor_scan_service(Path(temp_dir))

            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                side_effect=(20.0, 90.0),
            ):
                easiest_payload = service.scan_nearby(
                    "hero:256",
                    radius=2,
                    sort_mode="easiest",
                    simulations=5,
                    refresh=True,
                )
            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                return_value=80.0,
            ):
                hero_payload = service.scan_nearby(
                    "hero:256",
                    radius=2,
                    target_type="hero",
                    simulations=5,
                    refresh=False,
                )

            self.assertEqual(
                [item["target_id"] for item in easiest_payload["results"]],
                ["hero:512", "neutral:0"],
            )
            self.assertEqual(
                [item["target_id"] for item in hero_payload["results"]],
                ["hero:512"],
            )

    def test_estimate_battle_resolves_enemy_hero_target_on_other_level(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, _ = _advisor_scan_service(
                Path(temp_dir),
                enemy_position=(39, 71, 0),
            )

            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                return_value=72.0,
            ):
                payload = service.estimate_battle(
                    "hero:256",
                    "hero:512",
                    simulations=9,
                    refresh=True,
                )

            self.assertEqual(payload["hero_id"], "hero:256")
            self.assertEqual(payload["target_id"], "hero:512")
            self.assertEqual(payload["simulations"], 9)
            self.assertEqual(payload["estimate"]["target_id"], "hero:512")
            self.assertEqual(payload["estimate"]["target_type"], "hero")
            self.assertEqual(payload["estimate"]["target"]["name"], "Marius")
            self.assertEqual(payload["estimate"]["position"]["z"], 0)
            self.assertEqual(payload["estimate"]["win_pct"], 72.0)
            self.assertTrue(payload["known_limitations"])

    def test_scan_and_estimate_filter_hidden_targets_without_mutating_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, config_path = _advisor_scan_service(Path(temp_dir))
            snapshot = service.get_domain_snapshot(refresh=True)
            map_key = battle_estimator_gui._hidden_neutral_map_key(snapshot)
            config_path.write_text(
                json.dumps({
                    "hidden_neutral_targets_by_map": {map_key: ["neutral:0"]},
                    "hidden_hero_targets_by_map": {map_key: ["hero:512"]},
                }) + "\n",
                encoding="utf-8",
            )
            before_config = config_path.read_bytes()

            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                return_value=99.0,
            ) as hidden_run_mock:
                hidden_payload = service.scan_nearby(
                    "hero:256",
                    radius=2,
                    refresh=False,
                )
            with patch.object(
                battle_estimator_mcp.battle_estimator,
                "run_simulations",
                side_effect=(91.5, 72.0),
            ):
                visible_payload = service.scan_nearby(
                    "hero:256",
                    radius=2,
                    include_hidden_targets=True,
                    refresh=False,
                )

            self.assertEqual(hidden_payload["results"], [])
            self.assertEqual(hidden_payload["hidden_targets"]["neutral_count"], 1)
            self.assertEqual(hidden_payload["hidden_targets"]["hero_count"], 1)
            self.assertEqual(hidden_payload["hidden_targets"]["filtered_neutral_count"], 1)
            self.assertEqual(hidden_payload["hidden_targets"]["filtered_hero_count"], 1)
            self.assertNotIn("neutral_ids", hidden_payload["hidden_targets"])
            self.assertNotIn("hero_ids", hidden_payload["hidden_targets"])
            hidden_run_mock.assert_not_called()
            self.assertEqual(
                [item["target_id"] for item in visible_payload["results"]],
                ["neutral:0", "hero:512"],
            )
            self.assertEqual(
                visible_payload["hidden_targets"]["neutral_ids"],
                ["neutral:0"],
            )
            self.assertEqual(
                visible_payload["hidden_targets"]["hero_ids"],
                ["hero:512"],
            )
            self.assertEqual(config_path.read_bytes(), before_config)
            with self.assertRaisesRegex(ValueError, "unknown target_id"):
                service.estimate_battle(
                    "hero:256",
                    "neutral:0",
                    refresh=False,
                )

    def test_compute_tools_reject_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, _ = _advisor_scan_service(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "unknown hero_id"):
                service.scan_nearby("hero:999", refresh=True)
            with self.assertRaisesRegex(ValueError, "invalid target_type"):
                service.scan_nearby("hero:256", target_type="town", refresh=False)
            with self.assertRaisesRegex(ValueError, "invalid sort_mode"):
                service.scan_nearby("hero:256", sort_mode="hardest", refresh=False)
            with self.assertRaisesRegex(ValueError, "radius must be between"):
                service.scan_nearby("hero:256", radius=-1, refresh=False)
            with self.assertRaisesRegex(ValueError, "simulations must be between"):
                service.estimate_battle("hero:256", "neutral:0", simulations=0)
            with self.assertRaisesRegex(ValueError, "unknown target_id"):
                service.estimate_battle("hero:256", "neutral:999", refresh=False)

    def test_easiest_sort_places_missing_target_ids_last_on_ties(self):
        results = [
            {"target_id": None, "win_pct": 50.0, "distance": 1},
            {"target_id": "hero:512", "win_pct": 50.0, "distance": 1},
        ]

        sorted_results = battle_estimator_mcp._sort_scan_results(
            results,
            "easiest",
        )

        self.assertEqual(
            [item["target_id"] for item in sorted_results],
            ["hero:512", None],
        )


def _advisor_service_with_team_map(
    temp_path: Path,
    hero_specs,
) -> battle_estimator_mcp.AdvisorContextService:
    game_dir = temp_path / "game"
    game_dir.mkdir()
    _write_multi_gui_save(game_dir, "001.GM2", hero_specs)
    map_path = temp_path / "teams.h3m"
    map_path.write_bytes(gzip.compress(_build_minimal_sod_h3m_with_teams()))
    config_path = temp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    return battle_estimator_mcp.AdvisorContextService(
        game_dir=game_dir,
        map_file=map_path,
        config_path=config_path,
    )


def _advisor_scan_service(
    temp_path: Path,
    *,
    enemy_position=(39, 71, 1),
) -> tuple[battle_estimator_mcp.AdvisorContextService, Path]:
    game_dir = temp_path / "game"
    game_dir.mkdir()
    _write_multi_gui_save(
        game_dir,
        "001.GM2",
        (
            {
                "hero_name": "Isra",
                "name_offset": 256,
                "position": (39, 69, 1),
                "owner_color_id": 0,
            },
            {
                "hero_name": "Marius",
                "name_offset": 512,
                "position": enemy_position,
                "owner_color_id": 2,
            },
        ),
    )
    map_path = _write_h3m_map(temp_path / "map.h3m", position=(39, 70, 1))
    config_path = temp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    return (
        battle_estimator_mcp.AdvisorContextService(
            game_dir=game_dir,
            map_file=map_path,
            config_path=config_path,
        ),
        config_path,
    )


def _advisor_service_with_no_explicit_team_map(
    temp_path: Path,
    hero_specs,
) -> battle_estimator_mcp.AdvisorContextService:
    game_dir = temp_path / "game"
    game_dir.mkdir()
    _write_multi_gui_save(game_dir, "001.GM2", hero_specs)
    team_payload = _build_minimal_sod_h3m_with_teams()
    team_marker = bytes([8, 0, 0, 1, 1, 4, 5, 6, 7])
    marker_index = team_payload.index(team_marker)
    no_team_payload = (
        team_payload[:marker_index]
        + b"\x00"
        + team_payload[marker_index + len(team_marker):]
    )
    map_path = temp_path / "map.h3m"
    map_path.write_bytes(gzip.compress(no_team_payload))
    config_path = temp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    return battle_estimator_mcp.AdvisorContextService(
        game_dir=game_dir,
        map_file=map_path,
        config_path=config_path,
    )


def _write_team_town_h3m(path: Path) -> Path:
    visit_mask = bytes((0x01, 0x00, 0x00, 0x00, 0x00, 0x40))
    team_payload = _build_minimal_sod_h3m_with_teams()
    object_start = team_payload.index((0).to_bytes(4, "little") * 2, -8)
    base_without_objects = team_payload[:object_start]
    town_template = _object_template_bytes(
        "AVCcasx0.def",
        h3_map_parser.H3M_OBJECT_TOWN,
        subid=3,
        visit_mask=visit_mask,
    )
    payload = b"".join((
        base_without_objects,
        (1).to_bytes(4, "little"),
        town_template,
        (1).to_bytes(4, "little"),
        _object_bytes(
            (7, 5, 0),
            0,
            _town_payload(
                owner=1,
                custom_name="Blue Keep",
                has_garrison=True,
            ),
        ),
    ))
    path.write_bytes(gzip.compress(payload))
    return path


if __name__ == "__main__":
    unittest.main()
