import gzip
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import h3_map_parser


REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_minimal_h3m_header(
    format_version=h3_map_parser.H3M_FORMAT_SOD,
    are_any_players=True,
    map_size=108,
    levels=2,
):
    return b"".join((
        int(format_version).to_bytes(4, "little"),
        bytes([1 if are_any_players else 0]),
        int(map_size).to_bytes(4, "little", signed=True),
        bytes([1 if levels == 2 else 0]),
    ))


class H3MapParserContractTests(unittest.TestCase):
    def test_contract_dataclasses_expose_map_shapes(self):
        template = h3_map_parser.H3ObjectTemplate(
            template_index=3,
            animation_file="AVWgnll0.def",
            block_mask=b"\x00" * 6,
            visit_mask=b"\x01" * 6,
            terrain_mask=0x01FF,
            object_id=54,
            subid=98,
            object_type=2,
            print_priority=4,
        )
        placed_object = h3_map_parser.H3MapObject(
            object_index=10,
            x=39,
            y=70,
            z=1,
            template_index=3,
        )
        target = h3_map_parser.H3NeutralMonsterTarget(
            object_index=10,
            x=39,
            y=70,
            z=1,
            template=template,
            h3m_subid=98,
            count=37,
            creature_name="Gnoll",
            estimator_creature_id=98,
        )

        self.assertEqual(template.animation_file, "AVWgnll0.def")
        self.assertEqual(placed_object.template_index, 3)
        self.assertEqual(target.template, template)
        self.assertEqual(target.count, 37)

    def test_load_h3m_reads_gzip_with_format_id_at_offset_zero(self):
        payload = _build_minimal_h3m_header()

        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "test.h3m"
            map_path.write_bytes(gzip.compress(payload))

            loaded = h3_map_parser.load_h3m(map_path)

        self.assertEqual(loaded.path, map_path)
        self.assertEqual(loaded.data, payload)
        self.assertEqual(loaded.h3m_offset, 0)
        self.assertEqual(loaded.header.format_version, h3_map_parser.H3M_FORMAT_SOD)
        self.assertEqual(loaded.header.format_name, "SoD")
        self.assertEqual(loaded.header.map_size, 108)
        self.assertEqual(loaded.header.levels, 2)
        self.assertTrue(loaded.header.are_any_players)
        self.assertEqual(loaded.templates, ())
        self.assertEqual(loaded.objects, ())
        self.assertEqual(loaded.neutral_targets, ())

    def test_load_h3m_reads_gzip_with_prefixed_format_id(self):
        payload = (b"x" * 43) + _build_minimal_h3m_header(
            are_any_players=False,
            map_size=72,
            levels=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "prefixed.h3m"
            map_path.write_bytes(gzip.compress(payload))

            loaded = h3_map_parser.load_h3m(str(map_path))

        self.assertEqual(loaded.h3m_offset, 43)
        self.assertEqual(loaded.header.map_size, 72)
        self.assertEqual(loaded.header.levels, 1)
        self.assertFalse(loaded.header.are_any_players)

    def test_find_h3m_start_offset_checks_supported_candidate_offsets(self):
        self.assertEqual(
            h3_map_parser.find_h3m_start_offset(_build_minimal_h3m_header()),
            0,
        )
        self.assertEqual(
            h3_map_parser.find_h3m_start_offset(
                (b"x" * 43) + _build_minimal_h3m_header()
            ),
            43,
        )
        self.assertIsNone(
            h3_map_parser.find_h3m_start_offset(
                (b"x" * 20) + _build_minimal_h3m_header()
            )
        )

    def test_find_h3m_start_offset_skips_invalid_early_candidate(self):
        false_prefix = b"".join((
            h3_map_parser.H3M_FORMAT_SOD.to_bytes(4, "little"),
            b"\x01",
            (0).to_bytes(4, "little", signed=True),
            b"\x00",
        ))
        payload = false_prefix + (b"x" * (43 - len(false_prefix)))
        payload += _build_minimal_h3m_header()

        self.assertEqual(h3_map_parser.find_h3m_start_offset(payload), 43)

    def test_parse_h3m_header_reports_unsupported_format(self):
        data = _build_minimal_h3m_header(format_version=32)

        with self.assertRaises(h3_map_parser.H3MapLoadError) as raised:
            h3_map_parser.parse_h3m_header(data, path="/tmp/hota.h3m")

        self.assertEqual(raised.exception.path, Path("/tmp/hota.h3m"))
        self.assertIn("unsupported H3M format id: 32", raised.exception.reason)
        self.assertIn("/tmp/hota.h3m", str(raised.exception))

    def test_parse_h3m_header_reports_truncated_header(self):
        with self.assertRaises(h3_map_parser.H3MapLoadError) as raised:
            h3_map_parser.parse_h3m_header(b"\x1c\x00", path="/tmp/bad.h3m")

        self.assertEqual(raised.exception.path, Path("/tmp/bad.h3m"))
        self.assertIn("truncated", raised.exception.reason)

    def test_load_h3m_reports_missing_file_with_path(self):
        missing_path = Path("/tmp/vcmi-missing-map-for-test.h3m")

        with self.assertRaises(h3_map_parser.H3MapLoadError) as raised:
            h3_map_parser.load_h3m(missing_path)

        self.assertEqual(raised.exception.path, missing_path)
        self.assertIn("read failed", raised.exception.reason)

    def test_load_h3m_reports_invalid_gzip_with_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "bad.h3m"
            map_path.write_bytes(b"not gzip")

            with self.assertRaises(h3_map_parser.H3MapLoadError) as raised:
                h3_map_parser.load_h3m(map_path)

        self.assertEqual(raised.exception.path, map_path)
        self.assertIn("gzip decompress failed", raised.exception.reason)

    def test_load_h3m_reports_missing_supported_format_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "bad.h3m"
            map_path.write_bytes(gzip.compress(b"no H3M format id here"))

            with self.assertRaises(h3_map_parser.H3MapLoadError) as raised:
                h3_map_parser.load_h3m(map_path)

        self.assertEqual(raised.exception.path, map_path)
        self.assertIn("offset 0 or 43", raised.exception.reason)

    def test_battle_estimator_help_import_smoke(self):
        result = subprocess.run(
            [sys.executable, "tools/battle_estimator.py", "--help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VCMI Battle Estimator", result.stdout)


if __name__ == "__main__":
    unittest.main()
