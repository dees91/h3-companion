from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import h3_save_parser


REPO_ROOT = Path(__file__).resolve().parents[1]

ISRA_CREATURE_IDS = (57, 59, 63, 65, 67, 56, 69)
ISRA_COUNTS = (731, 181, 59, 47, 19, 316, 8)


def _xor_encode(raw: bytes) -> bytes:
    return bytes(byte ^ h3_save_parser.HERO_ARMY_XOR_KEY for byte in raw)


def _build_xor_hero_fixture(
    hero_name="Isra",
    creature_ids=ISRA_CREATURE_IDS,
    counts=ISRA_COUNTS,
    name_offset=256,
):
    data = bytearray(name_offset + h3_save_parser.HERO_NAME_SIZE + 32)
    ids_offset = name_offset + h3_save_parser.HERO_ARMY_TYPES_FROM_NAME_OFFSET
    counts_offset = name_offset + h3_save_parser.HERO_ARMY_COUNTS_FROM_NAME_OFFSET

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
    data[0:len(h3_save_parser.H3SVG_SIGNATURE)] = h3_save_parser.H3SVG_SIGNATURE
    return bytes(data)


def _compressed_save(hero_name="Isra", counts=ISRA_COUNTS):
    return gzip.compress(_build_xor_hero_fixture(hero_name=hero_name, counts=counts))


def _write_save(game_dir: Path, name: str, hero_name="Isra", counts=ISRA_COUNTS):
    game_dir.mkdir(parents=True, exist_ok=True)
    save_path = game_dir / name
    save_path.write_bytes(_compressed_save(hero_name=hero_name, counts=counts))
    return save_path


def _run_cli(args, home: Path | None = None):
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "tools/battle_estimator.py", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_config(home: Path, autosave_dir: Path):
    config_path = home / ".config" / "vcmi-battle-estimator" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"autosave_dir": str(autosave_dir)}) + "\n",
        encoding="utf-8",
    )


class BattleEstimatorCliTests(unittest.TestCase):
    def test_manual_army_mode_still_runs_without_autosave_context(self):
        result = _run_cli(["10 pikeman", "vs", "20 boar", "-n", "1"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gracz: 10x Pikeman", result.stdout)
        self.assertIn("Wrog: 20x Boar", result.stdout)
        self.assertNotIn("Folder zapisu:", result.stdout)

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
        self.assertIn("Isra: 731x Skeleton Warrior", result.stdout)
        self.assertIn("Plik zapisu:", result.stdout)

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
        self.assertNotIn("VCMI Battle Estimator", set_result.stdout)
        self.assertEqual(run_result.returncode, 0, run_result.stderr)
        self.assertIn("Isra: 731x Skeleton Warrior", run_result.stdout)

    def test_show_config_command_does_not_run_simulation(self):
        with tempfile.TemporaryDirectory() as temp_home:
            result = _run_cli(["--show-config"], home=Path(temp_home))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Config path:", result.stdout)
        self.assertIn("autosave_dir: (not set)", result.stdout)
        self.assertIn("last_hero: (not set)", result.stdout)
        self.assertNotIn("VCMI Battle Estimator", result.stdout)

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

    def test_list_command_takes_precedence_over_simulation_flags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = Path(temp_dir)
            _write_save(game_dir, "415.GM2")

            result = _run_cli([
                "--list",
                "castle",
                "--autosave-dir",
                str(game_dir),
                "Isra",
                "vs",
                "1 pikeman",
            ])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CASTLE", result.stdout)
        self.assertNotIn("VCMI Battle Estimator", result.stdout)


if __name__ == "__main__":
    unittest.main()
