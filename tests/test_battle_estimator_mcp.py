from __future__ import annotations

import asyncio
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    _write_empty_h3m_map,
    _write_gui_save,
    _write_h3m_map_with_portals,
    _write_h3m_map_with_town,
    _write_multi_gui_save,
)
from tests.test_h3_map_parser import (
    _base_string,
    _build_minimal_h3m_header,
    _build_minimal_sod_h3m_with_teams,
    _enabled_sod_player,
    _minimal_h3m_with_templates_and_objects,
    _monster_payload,
    _object_bytes,
    _object_template_bytes,
    _town_payload,
)


class _FakeToolError(Exception):
    pass


class _FakeFastMCP:
    instances = []

    def __init__(self, name):
        self.name = name
        self.tools = {}
        self.run_calls = []
        self.__class__.instances.append(self)

    def tool(self):
        def register(func):
            self.tools[func.__name__] = func
            return func

        return register

    def run(self, *, transport="stdio"):
        self.run_calls.append({"transport": transport})


class _RecordingMcpService:
    def __init__(self):
        self.calls = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return {"tool": name, "call_count": len(self.calls)}

    def refresh_context(self):
        return self._record("refresh_context")

    def get_advisor_context(self, color_id, **kwargs):
        return self._record("get_advisor_context", color_id, **kwargs)

    def scan_nearby(self, hero_id, **kwargs):
        return self._record("scan_nearby", hero_id, **kwargs)

    def estimate_battle(self, hero_id, target_id, **kwargs):
        return self._record("estimate_battle", hero_id, target_id, **kwargs)

    def find_route(self, hero_id, **kwargs):
        return self._record("find_route", hero_id, **kwargs)

    def explain_portal(self, portal_id, **kwargs):
        return self._record("explain_portal", portal_id, **kwargs)

    def list_colors(self, **kwargs):
        return self._record("list_colors", **kwargs)

    def get_alerts(self, color_id, **kwargs):
        return self._record("get_alerts", color_id, **kwargs)


class _FailingMcpService(_RecordingMcpService):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def list_colors(self, **kwargs):
        raise self.exc


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


class AdvisorMcpServerEntrypointTests(unittest.TestCase):
    def setUp(self):
        _FakeFastMCP.instances.clear()

    def test_script_help_works_without_mcp_sdk(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(repo_root / "tools" / "battle_estimator_mcp.py"),
                "--help",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("H3 Companion MCP strategic advisor server", result.stdout)
        self.assertIn("--map-file", result.stdout)
        self.assertIn("--transport", result.stdout)

    def test_service_from_args_defaults_save_file_to_pinned_mode(self):
        parser = battle_estimator_mcp.build_mcp_arg_parser()
        args = parser.parse_args([
            "--save-file",
            "001.GM2",
            "--map-file",
            "map.h3m",
            "--config-path",
            "config.json",
        ])

        service = battle_estimator_mcp._advisor_service_from_mcp_args(args)

        self.assertEqual(service.mode, battle_estimator_gui.PINNED_MODE)
        self.assertEqual(service.save_file, Path("001.GM2"))
        self.assertEqual(service.map_file, Path("map.h3m"))
        self.assertEqual(service.config_path, Path("config.json"))

    def test_main_reports_missing_mcp_sdk_without_snapshot_load(self):
        with patch.object(
            battle_estimator_mcp,
            "_load_mcp_sdk",
            side_effect=battle_estimator_mcp.McpSdkUnavailableError("sdk missing"),
        ):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                exit_code = battle_estimator_mcp.main(["--map-file", "map.h3m"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("sdk missing", stderr.getvalue())

    def test_run_mcp_server_uses_injected_sdk_and_stdio_transport(self):
        exit_code = battle_estimator_mcp.run_mcp_server(
            ["--save-file", "001.GM2", "--map-file", "map.h3m"],
            fastmcp_cls=_FakeFastMCP,
            tool_error_cls=_FakeToolError,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(_FakeFastMCP.instances), 1)
        self.assertEqual(
            _FakeFastMCP.instances[0].run_calls,
            [{"transport": battle_estimator_mcp.MCP_TRANSPORT_STDIO}],
        )

    def test_create_mcp_server_registers_approved_tools_and_delegates(self):
        service = _RecordingMcpService()
        server = battle_estimator_mcp.create_mcp_server(
            service,
            fastmcp_cls=_FakeFastMCP,
            tool_error_cls=_FakeToolError,
        )

        self.assertEqual(set(server.tools), set(battle_estimator_mcp.MCP_TOOL_NAMES))
        payload = server.tools["scan_nearby"](
            "hero:isra",
            radius=8,
            sort_mode=battle_estimator_mcp.ADVISOR_SCAN_SORT_EASIEST,
            refresh=False,
        )

        self.assertEqual(payload["tool"], "scan_nearby")
        self.assertEqual(
            service.calls[-1],
            (
                "scan_nearby",
                ("hero:isra",),
                {
                    "radius": 8,
                    "target_type": "all",
                    "sort_mode": battle_estimator_mcp.ADVISOR_SCAN_SORT_EASIEST,
                    "simulations": battle_estimator_mcp.battle_estimator.DEFAULT_SCAN_SIMULATIONS,
                    "refresh": False,
                    "include_removed": False,
                    "include_hidden_targets": False,
                },
            ),
        )

    def test_mcp_tool_wrapper_converts_expected_errors(self):
        service = _FailingMcpService(ValueError("bad input"))
        server = battle_estimator_mcp.create_mcp_server(
            service,
            fastmcp_cls=_FakeFastMCP,
            tool_error_cls=_FakeToolError,
        )

        with self.assertRaisesRegex(_FakeToolError, "ValueError: bad input"):
            server.tools["list_colors"]()

    def test_mcp_tool_wrapper_does_not_mask_unexpected_errors(self):
        service = _FailingMcpService(RuntimeError("bug"))
        server = battle_estimator_mcp.create_mcp_server(
            service,
            fastmcp_cls=_FakeFastMCP,
            tool_error_cls=_FakeToolError,
        )

        with self.assertRaisesRegex(RuntimeError, "bug"):
            server.tools["list_colors"]()


class AdvisorMcpSdkSmokeTests(unittest.TestCase):
    @unittest.skipIf(
        sys.version_info < battle_estimator_mcp.MCP_MIN_PYTHON_VERSION,
        "MCP SDK requires Python >=3.10",
    )
    def test_mcp_sdk_in_memory_smoke_lists_and_calls_tools(self):
        try:
            from mcp.shared.memory import create_connected_server_and_client_session
        except ImportError as exc:
            self.skipTest(f"MCP SDK unavailable: {exc}")

        service = _RecordingMcpService()
        server = battle_estimator_mcp.create_mcp_server(service)

        async def run_smoke():
            async with create_connected_server_and_client_session(
                server,
                raise_exceptions=True,
            ) as session:
                listed = await session.list_tools()
                self.assertEqual(
                    {tool.name for tool in listed.tools},
                    set(battle_estimator_mcp.MCP_TOOL_NAMES),
                )
                result = await session.call_tool(
                    "list_colors",
                    {"refresh": False},
                )
                self.assertFalse(result.isError)

        asyncio.run(run_smoke())
        self.assertEqual(
            service.calls[-1],
            ("list_colors", (), {"refresh": False}),
        )

    @unittest.skipIf(
        sys.version_info < battle_estimator_mcp.MCP_MIN_PYTHON_VERSION,
        "MCP SDK requires Python >=3.10",
    )
    def test_mcp_sdk_e2e_smoke_with_synthetic_context(self):
        try:
            from mcp.shared.memory import create_connected_server_and_client_session
        except ImportError as exc:
            self.skipTest(f"MCP SDK unavailable: {exc}")

        with tempfile.TemporaryDirectory() as temp_dir:
            service = _advisor_e2e_service(Path(temp_dir))
            server = battle_estimator_mcp.create_mcp_server(service)

            async def run_smoke():
                async with create_connected_server_and_client_session(
                    server,
                    raise_exceptions=True,
                ) as session:
                    listed = await session.list_tools()
                    self.assertEqual(
                        {tool.name for tool in listed.tools},
                        set(battle_estimator_mcp.MCP_TOOL_NAMES),
                    )

                    refresh = await _mcp_call_ok(session, "refresh_context")
                    self.assertEqual(refresh["hero_count"], 2)
                    self.assertEqual(refresh["neutral_target_count"], 1)
                    self.assertEqual(refresh["town_count"], 1)
                    self.assertEqual(refresh["portal_count"], 3)

                    colors = await _mcp_call_ok(
                        session,
                        "list_colors",
                        {"refresh": False},
                    )
                    self.assertTrue(colors["configured_my_color_available"])
                    self.assertEqual(len(colors["active_colors"]), 4)

                    context = await _mcp_call_ok(
                        session,
                        "get_advisor_context",
                        {"color_id": 0, "scope": "color", "refresh": False},
                    )
                    self.assertEqual(context["subject"]["color_name"], "red")
                    self.assertEqual(context["heroes"]["own"]["total_count"], 1)
                    self.assertEqual(context["heroes"]["enemy"]["total_count"], 1)

                    scan = await _mcp_call_ok(
                        session,
                        "scan_nearby",
                        {
                            "hero_id": "hero:256",
                            "radius": 3,
                            "simulations": 1,
                            "refresh": False,
                        },
                    )
                    self.assertEqual(scan["result_count"], 2)
                    self.assertIn(
                        "neutral:0",
                        {item["target_id"] for item in scan["results"]},
                    )

                    estimate = await _mcp_call_ok(
                        session,
                        "estimate_battle",
                        {
                            "hero_id": "hero:256",
                            "target_id": "hero:512",
                            "simulations": 1,
                            "refresh": False,
                        },
                    )
                    self.assertEqual(estimate["estimate"]["target_type"], "hero")

                    route = await _mcp_call_ok(
                        session,
                        "find_route",
                        {
                            "hero_id": "hero:256",
                            "target_id": "portal:4",
                            "refresh": False,
                        },
                    )
                    self.assertEqual(route["target_id"], "portal:4")
                    self.assertIn("status", route)
                    self.assertIn("fallback_status", route)

                    portal = await _mcp_call_ok(
                        session,
                        "explain_portal",
                        {"portal_id": "portal:2", "refresh": False},
                    )
                    self.assertTrue(portal["is_non_deterministic"])
                    self.assertEqual(portal["destination_count"], 2)

                    alerts = await _mcp_call_ok(
                        session,
                        "get_alerts",
                        {"color_id": 0, "refresh": False},
                    )
                    self.assertIn(
                        alerts["alerts"]["status"],
                        {
                            battle_estimator_gui.CASTLE_ALERT_STATUS_OK,
                            battle_estimator_gui.CASTLE_ALERT_STATUS_OWNERSHIP_UNAVAILABLE,
                        },
                    )
                    self.assertIn("town_ownership", alerts)

            asyncio.run(run_smoke())


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


class AdvisorRouteAndPortalToolTests(unittest.TestCase):
    def test_find_route_accepts_explicit_target_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=3)
            service, _ = _advisor_route_service(temp_path, map_path)

            payload = service.find_route(
                "hero:256",
                target_position={"x": 2, "y": 0, "z": 0},
                refresh=True,
            )

            self.assertEqual(payload["hero_id"], "hero:256")
            self.assertEqual(payload["status"], battle_estimator_gui.PATH_STATUS_FOUND)
            self.assertEqual(payload["fallback_status"], "exact")
            self.assertFalse(payload["uses_portals"])
            self.assertFalse(payload["has_non_deterministic_portal"])
            self.assertEqual(payload["target_position"], {"x": 2, "y": 0, "z": 0})
            self.assertEqual(
                [step["position"] for step in payload["steps"]],
                [
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 1, "y": 0, "z": 0},
                    {"x": 2, "y": 0, "z": 0},
                ],
            )
            self.assertTrue(payload["known_limitations"])

    def test_find_route_to_portal_target_reports_used_portal_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_h3m_map_with_portals(temp_path / "map.h3m")
            service, _ = _advisor_route_service(
                temp_path,
                map_path,
                hero_position=(6, 5, 0),
            )

            payload = service.find_route(
                "hero:256",
                target_id="portal:1",
                refresh=True,
            )

            self.assertEqual(payload["target_id"], "portal:1")
            self.assertEqual(payload["status"], battle_estimator_gui.PATH_STATUS_FOUND)
            self.assertEqual(payload["fallback_status"], "exact")
            self.assertTrue(payload["uses_portals"])
            self.assertEqual(len(payload["portal_segments"]), 1)
            segment = payload["portal_segments"][0]
            self.assertEqual(segment["segment_type"], "portal")
            self.assertEqual(segment["portal_edge"]["source_id"], "portal:0")
            self.assertEqual(segment["portal_edge"]["destination_id"], "portal:1")
            self.assertFalse(payload["has_non_deterministic_portal"])

    def test_find_route_filters_hidden_targets_without_exposing_hidden_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_route_neutral_h3m(temp_path / "map.h3m")
            service, config_path = _advisor_route_service(temp_path, map_path)
            snapshot = service.get_domain_snapshot(refresh=True)
            map_key = battle_estimator_gui._hidden_neutral_map_key(snapshot)
            config_path.write_text(
                json.dumps({
                    "hidden_neutral_targets_by_map": {map_key: ["neutral:0"]},
                }) + "\n",
                encoding="utf-8",
            )
            before_config = config_path.read_bytes()

            visible_other_route = service.find_route(
                "hero:256",
                target_position={"x": 1, "y": 0, "z": 0},
                refresh=False,
            )

            self.assertEqual(
                visible_other_route["hidden_targets"]["neutral_count"],
                1,
            )
            self.assertEqual(
                visible_other_route["hidden_targets"]["filtered_neutral_count"],
                1,
            )
            self.assertNotIn("neutral_ids", visible_other_route["hidden_targets"])
            with self.assertRaisesRegex(ValueError, "unknown target_id"):
                service.find_route(
                    "hero:256",
                    target_id="neutral:0",
                    refresh=False,
                )

            hidden_route = service.find_route(
                "hero:256",
                target_id="neutral:0",
                include_hidden_targets=True,
                refresh=False,
            )

            self.assertEqual(hidden_route["target_id"], "neutral:0")
            self.assertEqual(
                hidden_route["hidden_targets"]["neutral_ids"],
                ["neutral:0"],
            )
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_find_route_rejects_invalid_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_empty_h3m_map(temp_path / "map.h3m", map_size=2)
            service, _ = _advisor_route_service(temp_path, map_path)

            invalid_cases = (
                (
                    lambda: service.find_route("hero:256", refresh=True),
                    "exactly one",
                ),
                (
                    lambda: service.find_route(
                        "hero:256",
                        target_id="portal:0",
                        target_position={"x": 0, "y": 0, "z": 0},
                        refresh=False,
                    ),
                    "exactly one",
                ),
                (
                    lambda: service.find_route(
                        "hero:256",
                        target_position={"x": 0, "y": 0},
                        refresh=False,
                    ),
                    "exactly x, y, z",
                ),
                (
                    lambda: service.find_route(
                        "hero:256",
                        target_position={"x": True, "y": 0, "z": 0},
                        refresh=False,
                    ),
                    "target_position.x must be an integer",
                ),
                (
                    lambda: service.find_route(
                        "hero:256",
                        target_position={"x": 9, "y": 0, "z": 0},
                        refresh=False,
                    ),
                    "out of bounds",
                ),
                (
                    lambda: service.find_route(
                        "hero:999",
                        target_position={"x": 0, "y": 0, "z": 0},
                        refresh=False,
                    ),
                    "unknown hero_id",
                ),
            )
            for call, expected_error in invalid_cases:
                with self.subTest(expected_error=expected_error):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        call()

    def test_find_route_reports_resolved_neighbor_and_not_found_fallbacks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_blocked_route_h3m(temp_path / "map.h3m")
            service, _ = _advisor_route_service(temp_path, map_path)

            fallback_payload = service.find_route(
                "hero:256",
                target_position={"x": 1, "y": 0, "z": 0},
                refresh=True,
            )
            not_found_payload = service.find_route(
                "hero:256",
                target_position={"x": 2, "y": 0, "z": 0},
                refresh=False,
            )

            self.assertEqual(fallback_payload["status"], battle_estimator_gui.PATH_STATUS_FOUND)
            self.assertEqual(fallback_payload["fallback_status"], "resolved_neighbor")
            self.assertNotEqual(
                fallback_payload["resolved_target_position"],
                fallback_payload["requested_target_position"],
            )
            self.assertEqual(not_found_payload["status"], battle_estimator_gui.PATH_STATUS_NOT_FOUND)
            self.assertEqual(not_found_payload["fallback_status"], "not_found")

    def test_find_route_marks_non_deterministic_portal_segments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_multi_exit_portal_h3m(temp_path / "map.h3m")
            service, _ = _advisor_route_service(temp_path, map_path)

            payload = service.find_route(
                "hero:256",
                target_id="portal:2",
                refresh=True,
            )

            self.assertTrue(payload["uses_portals"])
            self.assertTrue(payload["has_non_deterministic_portal"])
            self.assertEqual(len(payload["portal_segments"]), 1)
            self.assertTrue(payload["portal_segments"][0]["is_non_deterministic"])

    def test_explain_portal_reports_multi_exit_and_cross_level_edges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_multi_exit_portal_h3m(temp_path / "map.h3m")
            service, _ = _advisor_route_service(temp_path, map_path)

            payload = service.explain_portal("portal:0", refresh=True)

            self.assertEqual(payload["portal_id"], "portal:0")
            self.assertEqual(payload["portal_type"], h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY)
            self.assertEqual(payload["role"], h3_map_parser.PORTAL_ROLE_ENTRANCE)
            self.assertEqual(payload["destination_count"], 2)
            self.assertEqual(payload["source_count"], 0)
            self.assertTrue(payload["is_non_deterministic"])
            self.assertEqual(payload["cross_level_destination_count"], 1)
            self.assertEqual(
                [edge["destination_id"] for edge in payload["outbound_destinations"]],
                ["portal:1", "portal:2"],
            )
            self.assertTrue(
                all(edge["is_non_deterministic"] for edge in payload["outbound_destinations"])
            )
            self.assertTrue(payload["known_limitations"])

    def test_explain_portal_reports_inbound_sources_and_unknown_portals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = _write_multi_exit_portal_h3m(temp_path / "map.h3m")
            service, _ = _advisor_route_service(temp_path, map_path)

            payload = service.explain_portal("portal:2", refresh=True)

            self.assertEqual(payload["source_count"], 1)
            self.assertEqual(payload["destination_count"], 0)
            self.assertEqual(payload["cross_level_source_count"], 1)
            self.assertEqual(payload["inbound_sources"][0]["source_id"], "portal:0")
            with self.assertRaisesRegex(ValueError, "unknown portal_id"):
                service.explain_portal("portal:999", refresh=False)

    def test_explain_portal_reports_unresolved_raw_edges(self):
        snapshot = SimpleNamespace(
            portal_targets=(
                SimpleNamespace(
                    object_index=0,
                    x=0,
                    y=0,
                    z=0,
                    anchor_x=0,
                    anchor_y=0,
                    anchor_z=0,
                    object_id=h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
                    h3m_subid=4,
                    portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    role=h3_map_parser.PORTAL_ROLE_ENTRANCE,
                    channel_key="monolith-one-way:4",
                ),
            ),
            portal_edges=(
                SimpleNamespace(
                    source_object_index=0,
                    destination_object_index=99,
                    portal_type=h3_map_parser.PORTAL_TYPE_MONOLITH_ONE_WAY,
                    channel_key="monolith-one-way:4",
                    h3m_subid=4,
                ),
            ),
        )

        payload = battle_estimator_mcp.explain_portal(snapshot, "portal:0")

        self.assertEqual(payload["unresolved_outbound_count"], 1)
        self.assertEqual(payload["unresolved_inbound_count"], 0)
        self.assertIsNone(payload["outbound_destinations"][0]["destination_position"])
        self.assertIsNone(payload["outbound_destinations"][0]["cross_level"])


class AdvisorAlertAndColorToolTests(unittest.TestCase):
    def test_list_colors_returns_active_players_teams_config_and_hero_buckets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, config_path = _advisor_color_service(Path(temp_dir))
            before_config = config_path.read_bytes()

            payload = service.list_colors(refresh=True)

            self.assertEqual(payload["configured_my_color_id"], 2)
            self.assertEqual(payload["configured_my_color_name"], "tan")
            self.assertIs(payload["configured_my_color_available"], True)
            self.assertEqual(payload["alert_radius"], 3)
            self.assertEqual(
                [
                    (color["color_id"], color["color_name"], color["team_id"])
                    for color in payload["active_colors"]
                ],
                [(0, "red", 0), (1, "blue", 0), (2, "tan", 1), (3, "green", 1)],
            )
            self.assertEqual(
                [(team["team_id"], team["color_names"]) for team in payload["teams"]],
                [(0, ["red", "blue"]), (1, ["tan", "green"])],
            )
            red = payload["active_colors"][0]
            blue = payload["active_colors"][1]
            self.assertEqual(red["hero_count"], 1)
            self.assertEqual(red["heroes"]["items"][0]["name"], "Redmain")
            self.assertEqual(blue["hero_count"], 1)
            self.assertEqual(blue["heroes"]["items"][0]["name"], "Blueally")
            self.assertEqual(payload["unknown_owner_heroes"]["total_count"], 0)
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_list_colors_marks_inactive_configured_color_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, config_path = _advisor_color_service(Path(temp_dir))
            config_path.write_text(
                json.dumps({
                    "my_color_id": 7,
                    "alert_radius": 3,
                }) + "\n",
                encoding="utf-8",
            )
            before_config = config_path.read_bytes()

            payload = service.list_colors(refresh=True)

            self.assertEqual(payload["configured_my_color_id"], 7)
            self.assertEqual(payload["configured_my_color_name"], "pink")
            self.assertIs(payload["configured_my_color_available"], False)
            self.assertNotIn(
                7,
                {color["color_id"] for color in payload["active_colors"]},
            )
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_list_colors_keeps_unknown_owner_heroes_out_of_color_buckets(self):
        snapshot = SimpleNamespace(
            state={
                "players": [
                    {
                        "player_index": 0,
                        "color_name": "red",
                        "enabled": True,
                        "can_human_play": True,
                        "can_computer_play": False,
                        "team_id": 0,
                    },
                ],
                "teams": [],
                "heroes": [
                    {
                        "id": "hero:unknown",
                        "name": "Unknown",
                        "owner_color_id": None,
                        "position": {"x": 0, "y": 0, "z": 0},
                        "ai_value": 100,
                    },
                ],
            },
        )

        payload = battle_estimator_mcp.list_colors(snapshot)

        self.assertEqual(payload["active_colors"][0]["hero_count"], 0)
        self.assertEqual(payload["unknown_owner_heroes"]["total_count"], 1)
        self.assertEqual(
            payload["unknown_owner_heroes"]["items"][0]["name"],
            "Unknown",
        )

    def test_get_alerts_uses_configured_radius_without_writing_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, config_path = _advisor_color_service(Path(temp_dir))
            before_config = config_path.read_bytes()

            payload = service.get_alerts(0, refresh=True)

            self.assertEqual(payload["color_id"], 0)
            self.assertEqual(payload["color_name"], "red")
            self.assertEqual(payload["alert_radius"], 3)
            self.assertEqual(payload["alerts"]["status"], "ok")
            self.assertEqual(payload["alerts"]["count"], 1)
            self.assertEqual(payload["alerts"]["items"][0]["town_name"], "Blue Keep")
            self.assertEqual(payload["alerts"]["items"][0]["enemy_hero_name"], "Enemy")
            self.assertFalse(payload["town_ownership"]["partial"])
            self.assertEqual(payload["town_ownership"]["available_subject_owned_count"], 1)
            self.assertEqual(
                payload["town_ownership"]["status_counts"],
                {h3_save_parser.TOWN_OWNERSHIP_STATUS_EXACT: 1},
            )
            self.assertTrue(payload["known_limitations"])
            self.assertEqual(config_path.read_bytes(), before_config)

    def test_get_alerts_reports_unavailable_town_ownership_partial(self):
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
                ),
            )
            map_path = _write_team_town_h3m(temp_path / "map.h3m")
            config_path = temp_path / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            service = battle_estimator_mcp.AdvisorContextService(
                game_dir=game_dir,
                map_file=map_path,
                config_path=config_path,
            )

            payload = service.get_alerts(0, refresh=True)

            self.assertEqual(payload["alerts"]["status"], "ownership_unavailable")
            self.assertIn("town:0", payload["alerts"]["status_detail"])
            self.assertTrue(payload["town_ownership"]["partial"])
            self.assertEqual(payload["town_ownership"]["available_subject_owned_count"], 0)
            self.assertEqual(payload["town_ownership"]["unavailable_town_ids"], ["town:0"])
            self.assertEqual(
                payload["town_ownership"]["status_counts"],
                {h3_save_parser.TOWN_OWNERSHIP_STATUS_UNAVAILABLE: 1},
            )

    def test_get_alerts_rejects_invalid_or_inactive_colors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service, _ = _advisor_color_service(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "color_id must be between"):
                service.get_alerts(8, refresh=True)
            with self.assertRaisesRegex(ValueError, "not an active map player"):
                service.get_alerts(7, refresh=False)


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


def _advisor_color_service(
    temp_path: Path,
) -> tuple[battle_estimator_mcp.AdvisorContextService, Path]:
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
                "hero_name": "Blueally",
                "name_offset": 640,
                "position": (4, 0, 0),
                "owner_color_id": 1,
            },
            {
                "hero_name": "Enemy",
                "name_offset": 1024,
                "position": (6, 7, 0),
                "owner_color_id": 2,
            },
        ),
        town_state_records=(
            _gui_town_state_record_bytes(owner_color_id=0),
        ),
    )
    map_path = _write_team_town_h3m(temp_path / "team-town.h3m")
    config_path = temp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "my_color_id": 2,
            "alert_radius": 3,
        }) + "\n",
        encoding="utf-8",
    )
    return (
        battle_estimator_mcp.AdvisorContextService(
            game_dir=game_dir,
            map_file=map_path,
            config_path=config_path,
        ),
        config_path,
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


def _advisor_route_service(
    temp_path: Path,
    map_path: Path,
    *,
    hero_position=(0, 0, 0),
) -> tuple[battle_estimator_mcp.AdvisorContextService, Path]:
    game_dir = temp_path / "game"
    game_dir.mkdir()
    _write_gui_save(
        game_dir,
        "001.GM2",
        hero_name="Isra",
        position=hero_position,
    )
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


async def _mcp_call_ok(session, tool_name: str, arguments=None):
    result = await session.call_tool(tool_name, arguments or {})
    if result.isError:
        self_text = getattr(result, "content", None)
        raise AssertionError(f"{tool_name} returned MCP error: {self_text!r}")
    structured_content = getattr(result, "structuredContent", None)
    if structured_content is not None:
        return structured_content
    for content in result.content:
        if getattr(content, "type", None) == "text":
            return json.loads(content.text)
    raise AssertionError(f"{tool_name} returned no structured/text content")


def _advisor_e2e_service(temp_path: Path) -> battle_estimator_mcp.AdvisorContextService:
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
                "name_offset": 512,
                "position": (1, 2, 0),
                "owner_color_id": 2,
            },
        ),
        town_state_records=(
            _gui_town_state_record_bytes(owner_color_id=0),
        ),
    )
    map_path = _write_e2e_h3m(temp_path / "e2e.h3m")
    config_path = temp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "my_color_id": 0,
            "alert_radius": 3,
        }) + "\n",
        encoding="utf-8",
    )
    return battle_estimator_mcp.AdvisorContextService(
        game_dir=game_dir,
        map_file=map_path,
        config_path=config_path,
    )


def _write_route_neutral_h3m(path: Path) -> Path:
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (
            _object_template_bytes(
                "AVWgnll0.def",
                h3_map_parser.H3M_OBJECT_MONSTER,
                subid=98,
            ),
        ),
        (
            _object_bytes(
                (2, 0, 0),
                0,
                _monster_payload(count=37),
            ),
        ),
        map_size=3,
    )
    path.write_bytes(gzip.compress(payload))
    return path


def _write_e2e_h3m(path: Path) -> Path:
    visit_mask = bytes((0x01, 0x00, 0x00, 0x00, 0x00, 0x40))
    map_size = 3
    levels = 2
    header = b"".join((
        _build_minimal_h3m_header(map_size=map_size, levels=levels),
        _base_string("Synthetic MCP E2E"),
        _base_string(""),
        b"\x00",  # difficulty
        b"\x00",  # level limit
    ))
    players = b"".join((
        _enabled_sod_player((0, 1, 0)),
        _enabled_sod_player((1, 1, 0)),
        _enabled_sod_player((2, 1, 0)),
        _enabled_sod_player((2, 2, 0)),
        (b"\x00\x00" + (b"\x00" * 13)) * 4,
    ))
    base_without_objects = b"".join((
        header,
        players,
        b"\xff",  # standard victory
        b"\xff",  # standard loss
        b"\x08",  # team assignments present
        bytes([0, 0, 1, 1, 4, 5, 6, 7]),
        b"\x00" * 20,  # allowed heroes
        (0).to_bytes(4, "little"),  # placeholder heroes
        b"\x00",  # disposed heroes
        b"\x00" * 31,  # map options
        b"\x00" * 18,  # allowed artifacts
        b"\x00" * 9,  # allowed spells
        b"\x00" * 4,  # allowed skills
        (0).to_bytes(4, "little"),  # rumors
        b"\x00" * 156,  # predefined heroes
        b"\x00" * (map_size * map_size * levels * 7),
    ))
    templates = (
        _object_template_bytes(
            "AVWgnll0.def",
            h3_map_parser.H3M_OBJECT_MONSTER,
            subid=98,
        ),
        _object_template_bytes(
            "AVCcasx0.def",
            h3_map_parser.H3M_OBJECT_TOWN,
            subid=3,
            visit_mask=visit_mask,
        ),
        _object_template_bytes(
            "AVXmn1e.def",
            h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
            subid=4,
        ),
        _object_template_bytes(
            "AVXmn1x.def",
            h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
            subid=4,
        ),
        _object_template_bytes(
            "AVXmn1x.def",
            h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
            subid=4,
        ),
    )
    objects = (
        _object_bytes((2, 0, 0), 0, _monster_payload(count=37)),
        _object_bytes(
            (1, 1, 0),
            1,
            _town_payload(owner=0, custom_name="Red Keep", has_garrison=True),
        ),
        _object_bytes((0, 0, 0), 2, b""),
        _object_bytes((2, 0, 0), 3, b""),
        _object_bytes((2, 0, 1), 4, b""),
    )
    payload = b"".join((
        base_without_objects,
        len(templates).to_bytes(4, "little"),
        b"".join(templates),
        len(objects).to_bytes(4, "little"),
        b"".join(objects),
    ))
    path.write_bytes(gzip.compress(payload))
    return path


def _write_blocked_route_h3m(path: Path) -> Path:
    block_target_tile_mask = bytes((0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F))
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (
            _object_template_bytes(
                "AVXblk.def",
                0,
                block_mask=block_target_tile_mask,
            ),
        ),
        (
            _object_bytes((1, 0, 0), 0, b""),
            _object_bytes((1, 1, 0), 0, b""),
            _object_bytes((1, 2, 0), 0, b""),
        ),
        map_size=3,
    )
    path.write_bytes(gzip.compress(payload))
    return path


def _write_multi_exit_portal_h3m(path: Path) -> Path:
    payload = _minimal_h3m_with_templates_and_objects(
        h3_map_parser.H3M_FORMAT_SOD,
        (
            _object_template_bytes(
                "AVXmn1e.def",
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
                subid=4,
            ),
            _object_template_bytes(
                "AVXmn1x.def",
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
                subid=4,
            ),
            _object_template_bytes(
                "AVXmn1x.def",
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
                subid=4,
            ),
        ),
        (
            _object_bytes((0, 0, 0), 0, b""),
            _object_bytes((2, 0, 0), 1, b""),
            _object_bytes((2, 0, 1), 2, b""),
        ),
        map_size=3,
        levels=2,
    )
    path.write_bytes(gzip.compress(payload))
    return path


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
