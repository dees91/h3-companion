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


def _base_string(value: str) -> bytes:
    raw = value.encode("latin-1")
    return len(raw).to_bytes(4, "little") + raw


def _build_minimal_sod_h3m_with_monster(
    animation_file="AVWgnll0.def",
    subid=98,
    count=37,
    position=(39, 70, 1),
    sign_before_monster=False,
):
    x, y, z = position
    header = b"".join((
        _build_minimal_h3m_header(map_size=1, levels=1),
        _base_string("Synthetic"),
        _base_string(""),
        b"\x00",  # difficulty
        b"\x00",  # level limit
    ))
    disabled_players = (b"\x00\x00" + (b"\x00" * 13)) * 8
    pre_terrain = b"".join((
        header,
        disabled_players,
        b"\xff",  # standard victory
        b"\xff",  # standard loss
        b"\x00",  # no teams
        b"\x00" * 20,  # allowed heroes
        (0).to_bytes(4, "little"),  # placeholder heroes
        b"\x00",  # disposed heroes
        b"\x00" * 31,  # map options
        b"\x00" * 18,  # allowed artifacts
        b"\x00" * 9,  # allowed spells
        b"\x00" * 4,  # allowed skills
        (0).to_bytes(4, "little"),  # rumors
        b"\x00" * 156,  # predefined heroes
        b"\x00" * 7,  # one terrain tile
    ))
    monster_template = b"".join((
        _base_string(animation_file),
        b"\x00" * 6,
        b"\x00" * 6,
        b"\x00" * 2,
        (0x01FF).to_bytes(2, "little"),
        h3_map_parser.H3M_OBJECT_MONSTER.to_bytes(4, "little"),
        int(subid).to_bytes(4, "little"),
        b"\x02",
        b"\x00",
        b"\x00" * 16,
    ))
    sign_template = b"".join((
        _base_string("AVXsign0.def"),
        b"\x00" * 6,
        b"\x00" * 6,
        b"\x00" * 2,
        (0x01FF).to_bytes(2, "little"),
        (91).to_bytes(4, "little"),
        (0).to_bytes(4, "little"),
        b"\x00",
        b"\x00",
        b"\x00" * 16,
    ))
    templates = [monster_template]
    objects = []

    if sign_before_monster:
        templates.insert(0, sign_template)
        objects.append(b"".join((
            bytes([1, 1, 0]),
            (0).to_bytes(4, "little"),
            b"\x00" * 5,
            _base_string("Read me"),
            b"\x00" * 4,
        )))
        monster_template_index = 1
    else:
        monster_template_index = 0

    monster_object = b"".join((
        bytes([x, y, z]),
        monster_template_index.to_bytes(4, "little"),
        b"\x00" * 5,
        (1234).to_bytes(4, "little"),  # AB/SoD monster identifier
        int(count).to_bytes(2, "little"),
        b"\x00",  # character
        b"\x00",  # has_message
        b"\x00",  # never flees
        b"\x00",  # not growing team
        b"\x00" * 2,
    ))
    objects.append(monster_object)
    return b"".join((
        pre_terrain,
        len(templates).to_bytes(4, "little"),
        b"".join(templates),
        len(objects).to_bytes(4, "little"),
        b"".join(objects),
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

    def test_parse_neutral_monster_from_sequential_sod_stream(self):
        payload = _build_minimal_sod_h3m_with_monster()
        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/synthetic.h3m",
            parse_objects=True,
        )

        self.assertEqual(len(loaded.templates), 1)
        self.assertEqual(len(loaded.objects), 1)
        self.assertEqual(len(loaded.neutral_targets), 1)

        target = loaded.neutral_targets[0]
        self.assertEqual(target.object_index, 0)
        self.assertEqual((target.x, target.y, target.z), (39, 70, 1))
        self.assertEqual(target.template.animation_file, "AVWgnll0.def")
        self.assertEqual(target.h3m_subid, 98)
        self.assertEqual(target.count, 37)
        self.assertEqual(target.creature_name, "Gnoll")
        self.assertEqual(target.estimator_creature_id, 98)

    def test_unknown_neutral_template_does_not_fallback_to_subid(self):
        payload = _build_minimal_sod_h3m_with_monster(
            animation_file="AVWunknown.def",
            subid=104,
            count=20,
        )

        targets = h3_map_parser.parse_h3m_neutral_monsters(
            payload,
            path="/tmp/unknown.h3m",
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].h3m_subid, 104)
        self.assertEqual(targets[0].count, 20)
        self.assertIsNone(targets[0].creature_name)
        self.assertIsNone(targets[0].estimator_creature_id)

    def test_parser_keeps_offset_after_non_monster_payload(self):
        payload = _build_minimal_sod_h3m_with_monster(sign_before_monster=True)

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/sign-before-monster.h3m",
            parse_objects=True,
        )

        self.assertEqual(len(loaded.templates), 2)
        self.assertEqual(len(loaded.objects), 2)
        self.assertEqual(len(loaded.neutral_targets), 1)
        self.assertEqual(loaded.objects[0].template_index, 0)
        self.assertEqual(loaded.neutral_targets[0].object_index, 1)
        self.assertEqual(loaded.neutral_targets[0].count, 37)


if __name__ == "__main__":
    unittest.main()
