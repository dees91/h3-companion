from __future__ import annotations

import argparse
import io
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import battle_estimator
from tools import h3_map_parser
from tools import h3_save_parser
from tests.test_h3_map_parser import _build_minimal_sod_h3m_with_monster
from tests.test_h3_save_parser import (
    _build_xor_hero_fixture as _build_parser_hero_fixture,
    _write_hero_combat_fields,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

ISRA_CREATURE_IDS = (57, 59, 63, 65, 67, 56, 69)
ISRA_COUNTS = (731, 181, 59, 47, 19, 316, 8)


def _xor_encode(raw: bytes) -> bytes:
    return bytes(byte ^ h3_save_parser.HERO_ARMY_XOR_KEY for byte in raw)


def _write_xor_hero_window(
    data: bytearray,
    hero_name="Isra",
    creature_ids=ISRA_CREATURE_IDS,
    counts=ISRA_COUNTS,
    name_offset=256,
    position=None,
    owner_color_id=0,
):
    ids_offset = name_offset + h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET
    counts_offset = name_offset + h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET
    owner_offset = name_offset - h3_save_parser.HERO_STRUCT_NAME_OFFSET

    if owner_offset >= 0 and owner_color_id is not None:
        data[owner_offset:owner_offset + 1] = _xor_encode(bytes([int(owner_color_id)]))

    for slot, creature_id in enumerate(creature_ids):
        encoded = _xor_encode(int(creature_id).to_bytes(4, "little"))
        offset = ids_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded
    for slot, count in enumerate(counts):
        encoded = _xor_encode(int(count).to_bytes(4, "little"))
        offset = counts_offset + slot * h3_save_parser.HERO_ARMY_VALUE_SIZE
        data[offset:offset + 4] = encoded

    name_bytes = hero_name.encode("ascii")
    padded_name = name_bytes.ljust(h3_save_parser.HERO_NAME_SIZE, b"\x00")
    data[name_offset:name_offset + h3_save_parser.HERO_NAME_SIZE] = _xor_encode(
        padded_name
    )
    if position is not None:
        x, y, z = position
        position_offset = name_offset + h3_save_parser.HERO_STRUCT_POSITION_FROM_NAME_OFFSET
        position_bytes = b"".join((
            int(x).to_bytes(2, "little"),
            int(y).to_bytes(2, "little"),
            bytes([int(z)]),
        ))
        data[position_offset:position_offset + h3_save_parser.HERO_POSITION_SIZE] = _xor_encode(
            position_bytes
        )


def _build_xor_hero_fixture(
    hero_name="Isra",
    creature_ids=ISRA_CREATURE_IDS,
    counts=ISRA_COUNTS,
    name_offset=256,
    position=None,
    owner_color_id=0,
):
    data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE + 32)
    data[0:len(h3_save_parser.H3SVG_SIGNATURE)] = h3_save_parser.H3SVG_SIGNATURE
    _write_xor_hero_window(
        data,
        hero_name=hero_name,
        creature_ids=creature_ids,
        counts=counts,
        name_offset=name_offset,
        position=position,
        owner_color_id=owner_color_id,
    )
    return bytes(data)


def _build_multi_hero_fixture(hero_specs):
    max_name_offset = max(spec["name_offset"] for spec in hero_specs)
    data = bytearray(max_name_offset + h3_save_parser.HERO_NAME_SIZE + 32)
    data[0:len(h3_save_parser.H3SVG_SIGNATURE)] = h3_save_parser.H3SVG_SIGNATURE
    for spec in hero_specs:
        _write_xor_hero_window(
            data,
            hero_name=spec["hero_name"],
            creature_ids=spec.get("creature_ids", ISRA_CREATURE_IDS),
            counts=spec.get("counts", ISRA_COUNTS),
            name_offset=spec["name_offset"],
            owner_color_id=spec.get("owner_color_id", 0),
        )
    return bytes(data)


def _compressed_save(hero_name="Isra", counts=ISRA_COUNTS, position=None):
    return gzip.compress(_build_xor_hero_fixture(
        hero_name=hero_name,
        counts=counts,
        position=position,
    ))


def _compressed_multi_hero_save(hero_specs):
    return gzip.compress(_build_multi_hero_fixture(hero_specs))


def _write_save(
    game_dir: Path,
    name: str,
    hero_name="Isra",
    counts=ISRA_COUNTS,
    position=None,
):
    game_dir.mkdir(parents=True, exist_ok=True)
    save_path = game_dir / name
    save_path.write_bytes(_compressed_save(
        hero_name=hero_name,
        counts=counts,
        position=position,
    ))
    return save_path


def _write_combat_save(
    game_dir: Path,
    name: str,
    hero_name="Isra",
    position=(39, 69, 1),
    primary_skills=(8, 6, 4, 5),
):
    game_dir.mkdir(parents=True, exist_ok=True)
    payload, name_offset = _build_parser_hero_fixture(
        hero_name=hero_name,
        position=position,
        xor_key=0x00,
        position_from_name_offset=(
            h3_save_parser.HOTSEAT_HERO_STRUCT_POSITION_FROM_NAME_OFFSET
        ),
    )
    mutable = bytearray(payload)
    mutable[0:len(h3_save_parser.H3SVG_SIGNATURE)] = h3_save_parser.H3SVG_SIGNATURE
    _write_hero_combat_fields(
        mutable,
        name_offset,
        primary_skills=primary_skills,
        xor_key=0x00,
    )
    save_path = game_dir / name
    save_path.write_bytes(gzip.compress(bytes(mutable)))
    return save_path


def _write_multi_hero_save(game_dir: Path, name: str, hero_specs):
    game_dir.mkdir(parents=True, exist_ok=True)
    save_path = game_dir / name
    save_path.write_bytes(_compressed_multi_hero_save(hero_specs))
    return save_path


def _write_empty_save(game_dir: Path, name: str):
    game_dir.mkdir(parents=True, exist_ok=True)
    save_path = game_dir / name
    save_path.write_bytes(gzip.compress(h3_save_parser.H3SVG_SIGNATURE))
    return save_path


def _write_h3m_map(path: Path, **monster_kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_minimal_sod_h3m_with_monster(**monster_kwargs)
    path.write_bytes(gzip.compress(payload))
    return path


def _removed_neutral_record_core_bytes(
    object_index,
    h3m_subid,
    removal_flags=0x8000,
):
    return b"".join((
        int(object_index).to_bytes(4, "little"),
        int(removal_flags).to_bytes(4, "little"),
        int(h3m_subid).to_bytes(4, "little"),
    ))


def _run_cli(args, home: Path | None = None, input_text: str | None = None):
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "tools/battle_estimator.py", *args],
        cwd=REPO_ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_config(home: Path, autosave_dir: Path, last_hero: str | None = None):
    config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {"autosave_dir": str(autosave_dir)}
    if last_hero is not None:
        config["last_hero"] = last_hero
    config_path.write_text(
        json.dumps(config) + "\n",
        encoding="utf-8",
    )


class BattleEstimatorCliTests(unittest.TestCase):
    def test_simulation_default_helpers_preserve_analysis_and_scan_defaults(self):
        args = argparse.Namespace(simulations=None)

        self.assertEqual(
            battle_estimator._analysis_simulations(args),
            battle_estimator.DEFAULT_ANALYSIS_SIMULATIONS,
        )
        self.assertEqual(
            battle_estimator._scan_simulations(args),
            battle_estimator.DEFAULT_SCAN_SIMULATIONS,
        )

        args = argparse.Namespace(simulations=123)

        self.assertEqual(battle_estimator._analysis_simulations(args), 123)
        self.assertEqual(battle_estimator._scan_simulations(args), 123)

    def test_resolve_cli_map_uses_explicit_map_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir()
            map_path = temp_path / "manual.h3m"
            map_path.write_bytes(b"map")
            args = argparse.Namespace(map_file=str(map_path))
            context = h3_save_parser.SaveContext(
                autosave_root=temp_path,
                game_dir=game_dir,
                save_file=game_dir / "415.GM2",
            )

            selected = battle_estimator._resolve_cli_map(args, context)

        self.assertEqual(selected, map_path)

    def test_resolve_cli_map_reports_map_selection_errors(self):
        args = argparse.Namespace(
            map_file="/tmp/vcmi-missing-cli-map-selection-test.h3m"
        )
        context = h3_save_parser.SaveContext(
            autosave_root=Path("/tmp"),
            game_dir=Path("/tmp/game"),
            save_file=Path("/tmp/game/415.GM2"),
        )

        with self.assertRaises(h3_map_parser.H3MapSelectionError):
            battle_estimator._resolve_cli_map(args, context)

    def test_autosave_mode_prints_explicit_map_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            save_file = _write_save(game_dir, "415.GM2")
            map_path = temp_path / "manual.h3m"
            map_path.write_bytes(b"map")

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "--map-file",
                str(map_path),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(save_file), result.stdout)
        self.assertIn(f"Map file:     {map_path}", result.stdout)

    def test_autosave_mode_auto_resolves_random_map(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "HoMM 3 Complete"
            game_dir = (
                root
                / "Games"
                / "Random"
                / "PlayerTwo"
                / "2026.04.26 20;45 Diamond"
            )
            random_maps = root / "random_maps"
            map_path = (
                random_maps
                / "PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m"
            )
            random_maps.mkdir(parents=True)
            map_path.write_bytes(b"map")
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Map file:     {map_path}", result.stdout)

    def test_autosave_mode_reports_bad_explicit_map_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir) / "game"
            _write_save(game_dir, "415.GM2")
            missing_map = Path(temp_dir) / "missing.h3m"

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "--map-file",
                str(missing_map),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot select H3M map", result.stderr)
        self.assertIn("map file is not a file", result.stderr)

    def test_autosave_mode_reports_auto_map_detection_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = (
                Path(temp_dir)
                / "HoMM 3 Complete"
                / "Games"
                / "Random"
                / "PlayerTwo"
                / "2026.04.26 20;45 Diamond"
            )
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not auto-detect H3M map", result.stderr)
        self.assertIn("--map-file", result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_scan_nearby_requires_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir) / "game"
            _write_save(game_dir, "415.GM2", position=(39, 69, 1))
            map_path = Path(temp_dir) / "map.h3m"
            _write_h3m_map(map_path)

            result = _run_cli([
                "--scan-nearby",
                "2",
                "--save-file",
                str(game_dir / "415.GM2"),
                "--map-file",
                str(map_path),
            ])

        self.assertEqual(result.returncode, 1)
        self.assertIn("--scan-nearby requires --hero", result.stderr)

    def test_scan_nearby_rejects_invalid_target_type(self):
        result = _run_cli([
            "--scan-nearby",
            "2",
            "--hero",
            "Isra",
            "--target-type",
            "town",
        ])

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertIn("town", result.stderr)

    def test_scan_nearby_prints_compact_output_for_synthetic_neutral(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            save_path = _write_save(
                game_dir,
                "415.GM2",
                position=(39, 69, 1),
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                count=37,
            )

            result = _run_cli([
                "--scan-nearby",
                "2",
                "--hero",
                "Isra",
                "--save-file",
                str(save_path),
                "--map-file",
                str(map_path),
                "--target-type",
                "neutral",
                "--include-removed",
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("H3 Nearby Scan", result.stdout)
        self.assertIn(f"Save file:     {save_path}", result.stdout)
        self.assertIn(f"Map file:       {map_path}", result.stdout)
        self.assertIn("Hero:         Isra (39,69,1)", result.stdout)
        self.assertIn("Scan radius:   2", result.stdout)
        self.assertIn("Target filter:   neutral", result.stdout)
        self.assertIn("Include removed: yes", result.stdout)
        self.assertIn("Simulations:       1", result.stdout)
        self.assertIn("neutral", result.stdout)
        self.assertIn("(39,70,1)", result.stdout)
        self.assertIn("37x Gnoll", result.stdout)
        self.assertRegex(result.stdout, r"\s100\.0\s")

    def test_scan_nearby_uses_loaded_save_combat_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            save_path = _write_combat_save(
                game_dir,
                "001.GM1",
                position=(39, 69, 1),
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                count=37,
            )
            args = argparse.Namespace(
                army_specs=(),
                hero="Isra",
                scan_nearby=2,
                save_file=str(save_path),
                autosave_dir=None,
                save=None,
                map_file=str(map_path),
                all_heroes=False,
                target_type="neutral",
                include_removed=False,
                simulations=1,
            )

            with patch.object(
                battle_estimator,
                "estimate_nearby_scan_targets",
                return_value=(),
            ) as estimate_mock:
                with redirect_stdout(io.StringIO()):
                    battle_estimator._run_nearby_scan(args)

        selected_hero = estimate_mock.call_args.args[0]
        self.assertEqual(
            selected_hero.combat_context.source,
            h3_save_parser.HERO_COMBAT_SOURCE_SAVE,
        )
        self.assertEqual(
            selected_hero.primary_skills,
            h3_save_parser.HeroPrimarySkills(8, 6, 4, 5),
        )

    def test_scan_nearby_filters_markerless_removed_neutral_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            game_dir.mkdir(parents=True, exist_ok=True)
            save_path = game_dir / "415.GM2"
            save_payload = (
                _build_xor_hero_fixture(position=(39, 69, 1))
                + b"\x00" * 3
                + _removed_neutral_record_core_bytes(1, 98, 0x9000)
                + b"\x01\x00\x45\x00"
            )
            save_path.write_bytes(gzip.compress(save_payload))
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                count=37,
                sign_before_monster=True,
            )

            result = _run_cli([
                "--scan-nearby",
                "2",
                "--hero",
                "Isra",
                "--save-file",
                str(save_path),
                "--map-file",
                str(map_path),
                "--target-type",
                "neutral",
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No nearby targets found.", result.stdout)
        self.assertNotIn("37x Gnoll", result.stdout)

    def test_scan_nearby_uses_default_scan_simulations_without_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            save_path = _write_save(
                game_dir,
                "415.GM2",
                position=(39, 69, 1),
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                position=(39, 70, 1),
                count=37,
            )

            result = _run_cli([
                "--scan-nearby",
                "0",
                "--hero",
                "Isra",
                "--save-file",
                str(save_path),
                "--map-file",
                str(map_path),
                "--target-type",
                "neutral",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Simulations:       500", result.stdout)
        self.assertIn("No nearby targets found.", result.stdout)

    def test_scan_nearby_prints_unsupported_note_for_unknown_neutral(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            game_dir = temp_path / "game"
            save_path = _write_save(
                game_dir,
                "415.GM2",
                position=(39, 69, 1),
            )
            map_path = _write_h3m_map(
                temp_path / "map.h3m",
                animation_file="AVWunknown.def",
                subid=104,
                count=20,
                position=(39, 70, 1),
            )

            result = _run_cli([
                "--scan-nearby",
                "2",
                "--hero",
                "Isra",
                "--save-file",
                str(save_path),
                "--map-file",
                str(map_path),
                "--target-type",
                "neutral",
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20x unsupported subid 104", result.stdout)
        self.assertIn(
            "unsupported neutral creature: AVWunknown.def/subid 104",
            result.stdout,
        )
        self.assertIn("--", result.stdout)

    def test_manual_army_mode_still_runs_without_autosave_context(self):
        result = _run_cli(["10 pikeman", "vs", "20 boar", "-n", "1"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Player: 10x Pikeman", result.stdout)
        self.assertIn("Enemy: 20x Boar", result.stdout)
        self.assertNotIn("Save folder:", result.stdout)
        self.assertNotIn("save-derived Attack/Defense", result.stdout)

    def test_short_hero_form_loads_from_explicit_autosave_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(game_dir), result.stdout)
        self.assertIn("415.GM2", result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)
        self.assertIn("Enemy: 1x Pikeman", result.stdout)
        self.assertIn("Save file:", result.stdout)
        self.assertIn("save-derived Attack/Defense", result.stdout)

    def test_explicit_hero_flag_accepts_empty_left_side(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--hero",
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_save_number_prefers_gm2_for_requested_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM1", counts=(13, 1, 1, 1, 1, 1, 1))
            _write_save(game_dir, "415.GM2", counts=ISRA_COUNTS)
            _write_save(game_dir, "999.GM2", counts=(22, 1, 1, 1, 1, 1, 1))

            result = _run_cli([
                "--hero",
                "Isra",
                "--save",
                "415",
                "--autosave-dir",
                str(game_dir),
                "vs",
                "1 pikeman",
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("415.GM2", result.stdout)
        self.assertIn("731x Skeleton Warrior", result.stdout)

    def test_save_file_ignores_bad_configured_autosave_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            root = Path(temp_dir)
            home = Path(temp_home)
            good_dir = root / "good"
            bad_dir = root / "bad"
            bad_dir.mkdir()
            save_file = _write_save(good_dir, "415.GM2")
            _write_config(home, bad_dir)

            result = _run_cli([
                "--hero",
                "Isra",
                "--save-file",
                str(save_file),
                "vs",
                "1 pikeman",
                "-n",
                "1",
            ], home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(save_file), result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_autosave_dir_overrides_bad_configured_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            root = Path(temp_dir)
            home = Path(temp_home)
            good_dir = root / "good"
            bad_dir = root / "bad"
            bad_dir.mkdir()
            _write_save(good_dir, "415.GM2")
            _write_config(home, bad_dir)

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(good_dir),
                "-n",
                "1",
            ], home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_autosave_dir_bypasses_malformed_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            root = Path(temp_dir)
            home = Path(temp_home)
            good_dir = root / "good"
            _write_save(good_dir, "415.GM2")
            config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{not json", encoding="utf-8")

            result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(good_dir),
                "-n",
                "1",
            ], home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_configured_autosave_dir_is_used_when_no_flag_is_passed(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")

            set_result = _run_cli([
                "--set-autosave-dir",
                str(game_dir),
            ], home=home)
            run_result = _run_cli([
                "Isra",
                "vs",
                "1 pikeman",
                "-n",
                "1",
            ], home=home)

        self.assertEqual(set_result.returncode, 0, set_result.stderr)
        self.assertNotIn("H3 Battle Estimator", set_result.stdout)
        self.assertEqual(run_result.returncode, 0, run_result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", run_result.stdout)

    def test_show_config_command_does_not_run_simulation(self):
        with tempfile.TemporaryDirectory() as temp_home:
            result = _run_cli(["--show-config"], home=Path(temp_home))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Config path:", result.stdout)
        self.assertIn("autosave_dir: (not set)", result.stdout)
        self.assertIn("last_hero: (not set)", result.stdout)
        self.assertNotIn("H3 Battle Estimator", result.stdout)

    def test_clear_autosave_dir_preserves_last_hero_and_does_not_simulate(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_config(home, game_dir, last_hero="Isra")

            result = _run_cli(["--clear-autosave-dir"], home=home)
            config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Autosave dir cleared", result.stdout)
        self.assertNotIn("autosave_dir", saved_config)
        self.assertEqual(saved_config["last_hero"], "Isra")
        self.assertNotIn("H3 Battle Estimator", result.stdout)

    def test_missing_hero_error_lists_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "Sorsha",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 1)
        self.assertIn("Sorsha", result.stderr)
        self.assertIn("Isra", result.stderr)

    def test_ambiguous_hero_error_lists_matching_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_multi_hero_save(game_dir, "415.GM2", [
                {
                    "hero_name": "Isra",
                    "counts": ISRA_COUNTS,
                    "name_offset": 256,
                },
                {
                    "hero_name": "Israfel",
                    "counts": ISRA_COUNTS,
                    "name_offset": 512,
                },
            ])

            result = _run_cli([
                "Is",
                "vs",
                "1 pikeman",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ])

        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous_prefix", result.stderr)
        self.assertIn("Isra", result.stderr)
        self.assertIn("Israfel", result.stderr)

    def test_list_command_takes_precedence_over_simulation_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--list",
                "castle",
                "--list-save-heroes",
                "--autosave-dir",
                str(game_dir),
                "Isra",
                "vs",
                "1 pikeman",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CASTLE", result.stdout)
        self.assertNotIn("H3 Battle Estimator", result.stdout)
        self.assertNotIn("H3 Save Heroes", result.stdout)

    def test_list_save_heroes_lists_context_and_relevant_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_multi_hero_save(game_dir, "415.GM2", [
                {
                    "hero_name": "Isra",
                    "counts": ISRA_COUNTS,
                    "name_offset": 256,
                },
                {
                    "hero_name": "Tiny",
                    "counts": (1, 0, 0, 0, 0, 0, 0),
                    "name_offset": 512,
                },
            ])

            result = _run_cli([
                "--list-save-heroes",
                "--autosave-dir",
                str(game_dir),
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("H3 Save Heroes", result.stdout)
        self.assertIn(str(game_dir), result.stdout)
        self.assertIn("415.GM2", result.stdout)
        self.assertIn("Parser mode: XOR 0x01 hero army scanner", result.stdout)
        self.assertIn("Hero", result.stdout)
        self.assertIn("AIValue", result.stdout)
        self.assertIn("Army", result.stdout)
        self.assertIn("Isra", result.stdout)
        self.assertIn("731x Skeleton Warrior", result.stdout)
        self.assertNotIn("Tiny", result.stdout)
        self.assertNotIn("MONTE CARLO SIMULATION", result.stdout)
        self.assertNotIn("STATIC ANALYSIS", result.stdout)

    def test_list_save_heroes_all_heroes_includes_filtered_small_armies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_multi_hero_save(game_dir, "415.GM2", [
                {
                    "hero_name": "Tiny",
                    "counts": (1, 0, 0, 0, 0, 0, 0),
                    "name_offset": 256,
                },
            ])

            default_result = _run_cli([
                "--list-save-heroes",
                "--autosave-dir",
                str(game_dir),
            ])
            all_result = _run_cli([
                "--list-save-heroes",
                "--all-heroes",
                "--autosave-dir",
                str(game_dir),
            ])

        self.assertEqual(default_result.returncode, 0, default_result.stderr)
        self.assertIn("No relevant hero armies found", default_result.stdout)
        self.assertIn("Use --all-heroes", default_result.stdout)
        self.assertNotIn("Tiny", default_result.stdout)
        self.assertEqual(all_result.returncode, 0, all_result.stderr)
        self.assertIn("Tiny", all_result.stdout)
        self.assertIn("1x Skeleton Warrior", all_result.stdout)

    def test_list_save_heroes_empty_save_reports_context_and_parser_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            save_file = _write_empty_save(game_dir, "415.GM2")

            result = _run_cli([
                "--list-save-heroes",
                "--autosave-dir",
                str(game_dir),
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(save_file), result.stdout)
        self.assertIn("Parser mode: XOR 0x01 hero army scanner", result.stdout)
        self.assertIn("No hero armies found in selected save.", result.stdout)

    def test_list_save_heroes_save_number_uses_requested_gm2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM1", hero_name="Tiny", counts=(1, 0, 0, 0, 0, 0, 0))
            _write_save(game_dir, "415.GM2", hero_name="Isra", counts=ISRA_COUNTS)
            _write_save(game_dir, "999.GM2", hero_name="Newer", counts=ISRA_COUNTS)

            result = _run_cli([
                "--list-save-heroes",
                "--save",
                "415",
                "--autosave-dir",
                str(game_dir),
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("415.GM2", result.stdout)
        self.assertIn("Isra", result.stdout)
        self.assertNotIn("Newer", result.stdout)

    def test_list_save_heroes_autosave_dir_bypasses_malformed_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            root = Path(temp_dir)
            home = Path(temp_home)
            good_dir = root / "good"
            _write_save(good_dir, "415.GM2")
            config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{not json", encoding="utf-8")

            result = _run_cli([
                "--list-save-heroes",
                "--autosave-dir",
                str(good_dir),
            ], home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Isra", result.stdout)

    def test_list_save_heroes_save_file_ignores_bad_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            root = Path(temp_dir)
            home = Path(temp_home)
            good_dir = root / "good"
            bad_dir = root / "bad"
            bad_dir.mkdir()
            save_file = _write_save(good_dir, "415.GM2")
            _write_config(home, bad_dir)

            result = _run_cli([
                "--list-save-heroes",
                "--save-file",
                str(save_file),
            ], home=home)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(save_file), result.stdout)
        self.assertIn("Isra", result.stdout)

    def test_no_argument_wizard_uses_configured_autosave_dir_and_saves_last_hero(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2", counts=(50, 0, 0, 0, 0, 0, 0))
            _write_config(home, game_dir)

            result = _run_cli([], home=home, input_text="1\n1 pikeman\n")
            config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("H3 Battle Estimator Wizard", result.stdout)
        self.assertIn(str(game_dir), result.stdout)
        self.assertIn("415.GM2", result.stdout)
        self.assertIn("  1 Isra", result.stdout)
        self.assertIn("Enemy army:", result.stdout)
        self.assertIn("MONTE CARLO SIMULATION", result.stdout)
        self.assertIn("Isra: 50x Skeleton Warrior", result.stdout)
        self.assertEqual(saved_config["last_hero"], "Isra")

    def test_wizard_accepts_hero_name_with_steering_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="Isra\n1 pikeman\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("H3 Battle Estimator Wizard", result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_wizard_uses_available_last_hero_as_default(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")
            _write_config(home, game_dir, last_hero="Isra")

            result = _run_cli([
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="\n1 pikeman\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hero number or name [Isra]:", result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_wizard_reprompts_after_invalid_hero_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="99\nIsra\n1 pikeman\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Invalid hero number: 99", result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)

    def test_wizard_autosave_dir_bypasses_malformed_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")
            config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{not json", encoding="utf-8")

            result = _run_cli([
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="1\n1 pikeman\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("H3 Battle Estimator Wizard", result.stdout)
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)
        self.assertIn("Warning: could not save last hero", result.stderr)

    def test_wizard_reports_no_relevant_heroes_before_prompting(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2", counts=(1, 0, 0, 0, 0, 0, 0))

            result = _run_cli([
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="")

        self.assertEqual(result.returncode, 1)
        self.assertIn("H3 Battle Estimator Wizard", result.stdout)
        self.assertIn("No relevant hero armies found", result.stdout)
        self.assertIn("Use --all-heroes", result.stdout)
        self.assertNotIn("Enemy army:", result.stdout)

    def test_hero_without_vs_does_not_start_wizard(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as temp_home:
            game_dir = Path(temp_dir)
            home = Path(temp_home)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--hero",
                "Isra",
                "--autosave-dir",
                str(game_dir),
                "-n",
                "1",
            ], home=home, input_text="1 pikeman\n")

        self.assertEqual(result.returncode, 1)
        self.assertIn("usage:", result.stdout)
        self.assertNotIn("H3 Battle Estimator Wizard", result.stdout)


if __name__ == "__main__":
    unittest.main()
