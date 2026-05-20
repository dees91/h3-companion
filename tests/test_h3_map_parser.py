import gzip
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tools import battle_estimator
from tools import h3_map_parser
from tools import h3_save_parser


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


def _build_minimal_sod_h3m_with_terrain(terrain_tiles, map_size=2, levels=2):
    header = b"".join((
        _build_minimal_h3m_header(map_size=map_size, levels=levels),
        _base_string("Synthetic Terrain"),
        _base_string(""),
        b"\x00",  # difficulty
        b"\x00",  # level limit
    ))
    return b"".join((
        header,
        (b"\x00\x00" + (b"\x00" * 13)) * 8,  # disabled players
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
        b"".join(bytes(tile) for tile in terrain_tiles),
        (0).to_bytes(4, "little"),  # templates
        (0).to_bytes(4, "little"),  # objects
    ))


def _object_template_bytes(
    animation_file,
    object_id,
    subid=0,
    object_type=0,
    block_mask=b"\xff" * 6,
    visit_mask=b"\x00" * 6,
):
    return b"".join((
        _base_string(animation_file),
        block_mask,
        visit_mask,
        b"\x00" * 2,
        (0x01FF).to_bytes(2, "little"),
        int(object_id).to_bytes(4, "little"),
        int(subid).to_bytes(4, "little"),
        bytes([object_type]),
        b"\x00",
        b"\x00" * 16,
    ))


def _object_bytes(position, template_index, payload):
    return b"".join((
        bytes(position),
        int(template_index).to_bytes(4, "little"),
        b"\x00" * 5,
        payload,
    ))


def _minimal_h3m_with_templates_and_objects(
    format_version,
    templates,
    objects,
    map_size=1,
    levels=1,
):
    is_sod = format_version == h3_map_parser.H3M_FORMAT_SOD
    is_ab_or_sod = format_version in (
        h3_map_parser.H3M_FORMAT_AB,
        h3_map_parser.H3M_FORMAT_SOD,
    )
    header = b"".join((
        _build_minimal_h3m_header(
            format_version=format_version,
            map_size=map_size,
            levels=levels,
        ),
        _base_string("Synthetic Objects"),
        _base_string(""),
        b"\x00",  # difficulty
        b"\x00" if is_ab_or_sod else b"",  # level limit
    ))
    disabled_player_tail = 13 if is_sod else (12 if is_ab_or_sod else 6)
    return b"".join((
        header,
        (b"\x00\x00" + (b"\x00" * disabled_player_tail)) * 8,
        b"\xff",  # standard victory
        b"\xff",  # standard loss
        b"\x00",  # no teams
        b"\x00" * (20 if is_ab_or_sod else 16),  # allowed heroes
        (0).to_bytes(4, "little") if is_ab_or_sod else b"",  # placeholder heroes
        b"\x00" if is_sod else b"",  # disposed heroes
        b"\x00" * 31,  # map options
        (b"\x00" * 18) if is_sod else ((b"\x00" * 17) if is_ab_or_sod else b""),
        (b"\x00" * 9 + b"\x00" * 4) if is_sod else b"",  # allowed spells/skills
        (0).to_bytes(4, "little"),  # rumors
        b"\x00" * 156 if is_sod else b"",  # predefined heroes
        b"\x00" * (map_size * map_size * levels * 7),
        len(templates).to_bytes(4, "little"),
        b"".join(templates),
        len(objects).to_bytes(4, "little"),
        b"".join(objects),
    ))


def _town_payload(
    format_version=h3_map_parser.H3M_FORMAT_SOD,
    owner=0,
    custom_name=None,
    has_garrison=False,
):
    is_sod = format_version == h3_map_parser.H3M_FORMAT_SOD
    is_ab_or_sod = format_version in (
        h3_map_parser.H3M_FORMAT_AB,
        h3_map_parser.H3M_FORMAT_SOD,
    )
    payload = []
    if is_ab_or_sod:
        payload.append((4321).to_bytes(4, "little"))
    payload.append(bytes([owner]))
    if custom_name is None:
        payload.append(b"\x00")
    else:
        payload.append(b"\x01")
        payload.append(_base_string(custom_name))
    payload.append(b"\x01" if has_garrison else b"\x00")
    if has_garrison:
        payload.append(b"\x00" * (7 * (4 if is_ab_or_sod else 3)))
    payload.append(b"\x00")  # formation
    payload.append(b"\x00")  # custom buildings flag
    payload.append(b"\x00")  # fort flag
    if is_ab_or_sod:
        payload.append(b"\x00" * 9)  # obligatory spells
    payload.append(b"\x00" * 9)  # possible spells
    payload.append((0).to_bytes(4, "little"))  # events
    if is_sod:
        payload.append(b"\xff")  # alignment: same as owner/random
    payload.append(b"\x00" * 3)
    return b"".join(payload)


def _monster_payload(format_version=h3_map_parser.H3M_FORMAT_SOD, count=37):
    payload = []
    if format_version in (h3_map_parser.H3M_FORMAT_AB, h3_map_parser.H3M_FORMAT_SOD):
        payload.append((1234).to_bytes(4, "little"))
    payload.extend((
        int(count).to_bytes(2, "little"),
        b"\x00",  # character
        b"\x00",  # has_message
        b"\x00",  # never flees
        b"\x00",  # not growing team
        b"\x00" * 2,
    ))
    return b"".join(payload)


def _template(
    template_index,
    object_id,
    block_mask=b"\xff" * 6,
    visit_mask=b"\x00" * 6,
):
    return h3_map_parser.H3ObjectTemplate(
        template_index=template_index,
        animation_file=f"AVXobj{template_index}.def",
        block_mask=block_mask,
        visit_mask=visit_mask,
        terrain_mask=0x01FF,
        object_id=object_id,
        subid=0,
        object_type=0,
        print_priority=0,
    )


def _map_object(object_index, position, template_index):
    return h3_map_parser.H3MapObject(
        object_index=object_index,
        x=position[0],
        y=position[1],
        z=position[2],
        template_index=template_index,
    )


def _terrain_tile(x, y, z, terrain_type):
    return h3_map_parser.H3TerrainTile(
        x=x,
        y=y,
        z=z,
        terrain_type=terrain_type,
        terrain_view=0,
        river_type=0,
        river_direction=0,
        road_type=0,
        road_direction=0,
        ext_flags=0,
    )


def _enabled_sod_player(position, human=True, computer=True):
    return b"".join((
        bytes([1 if human else 0]),
        bytes([1 if computer else 0]),
        b"\x00",  # AI tactic
        b"\x00",  # selectable faction flag
        b"\xff\x01",  # factions bitmask
        b"\x00",  # random faction flag
        b"\x01",  # main town flag
        b"\x01",  # generate hero at main town
        b"\x00",  # unused starting town type
        bytes(position),
        b"\x00",  # random hero flag
        b"\xff",  # no main hero
        b"\x00",  # unused AB byte
        (0).to_bytes(4, "little"),  # custom hero names count
    ))


def _build_minimal_sod_h3m_with_teams():
    header = b"".join((
        _build_minimal_h3m_header(map_size=1, levels=1),
        _base_string("Synthetic Teams"),
        _base_string(""),
        b"\x00",  # difficulty
        b"\x00",  # level limit
    ))
    players = b"".join((
        _enabled_sod_player((70, 55, 0)),
        _enabled_sod_player((50, 38, 0)),
        _enabled_sod_player((95, 54, 0)),
        _enabled_sod_player((7, 41, 0)),
        (b"\x00\x00" + (b"\x00" * 13)) * 4,
    ))
    return b"".join((
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
        b"\x00" * 7,  # one terrain tile
        (0).to_bytes(4, "little"),  # templates
        (0).to_bytes(4, "little"),  # objects
    ))


class H3MapParserContractTests(unittest.TestCase):
    def test_h3m_def_mapping_covers_all_estimator_creatures(self):
        mapped_names = set(h3_map_parser.H3M_DEF_TO_ESTIMATOR_CREATURE_NAME.values())
        expected_names = {creature.name for creature in battle_estimator.CREATURES}

        self.assertEqual(mapped_names, expected_names)

        for def_name, expected_name in sorted(
            h3_map_parser.H3M_DEF_TO_ESTIMATOR_CREATURE_NAME.items()
        ):
            with self.subTest(def_name=def_name):
                creature_name, creature_id = (
                    h3_map_parser._map_template_to_estimator_creature(def_name)
                )

                self.assertEqual(creature_name, expected_name)
                self.assertIsNotNone(creature_id)

    def test_h3m_def_mapping_handles_nearby_scan_creatures(self):
        cases = {
            "AvWInfr.def": ("Infernal Troglodyte", 71),
            "AVWimpx0.def": ("Familiar", 43),
            "AVWelma0.def": ("Air Elemental", 114),
            "AVWsprit.def": ("Sprite", 113),
            "AvWDFly.def": ("Serpent Fly", 102),
            "AvWDFir.def": ("Dragon Fly", 103),
        }

        for animation_file, expected in cases.items():
            with self.subTest(animation_file=animation_file):
                self.assertEqual(
                    h3_map_parser._map_template_to_estimator_creature(
                        animation_file
                    ),
                    expected,
                )

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
        town_target = h3_map_parser.H3TownTarget(
            object_index=11,
            x=37,
            y=70,
            z=1,
            anchor_x=39,
            anchor_y=70,
            anchor_z=1,
            template=template,
            object_id=h3_map_parser.H3M_OBJECT_TOWN,
            h3m_subid=0,
            faction_subid=0,
            initial_owner=2,
            custom_name="Synthetic Town",
            has_garrison=True,
        )
        terrain_tile = h3_map_parser.H3TerrainTile(
            x=1,
            y=2,
            z=0,
            terrain_type=8,
            terrain_view=9,
            river_type=1,
            river_direction=2,
            road_type=3,
            road_direction=4,
            ext_flags=5,
        )

        self.assertEqual(template.animation_file, "AVWgnll0.def")
        self.assertEqual(placed_object.template_index, 3)
        self.assertEqual(target.template, template)
        self.assertEqual(target.count, 37)
        self.assertFalse(target.removed)
        self.assertIsNone(target.removal_note)
        self.assertEqual(town_target.anchor_x, 39)
        self.assertEqual(town_target.initial_owner, 2)
        self.assertEqual(town_target.custom_name, "Synthetic Town")
        self.assertTrue(town_target.has_garrison)
        self.assertEqual(terrain_tile.terrain_type, 8)
        self.assertEqual(terrain_tile.road_direction, 4)

    def test_route_layer_classifies_terrain_tiles(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=2,
            levels=1,
            are_any_players=True,
        )
        terrain_tiles = (
            _terrain_tile(0, 0, 0, 0),
            _terrain_tile(1, 0, 0, h3_map_parser.H3M_TERRAIN_WATER),
            _terrain_tile(0, 1, 0, h3_map_parser.H3M_TERRAIN_ROCK),
            _terrain_tile(1, 1, 0, 3),
        )

        route_tiles = h3_map_parser._build_route_tiles(header, terrain_tiles, (), ())

        self.assertEqual(
            len(route_tiles),
            header.map_size * header.map_size * header.levels,
        )
        self.assertEqual(
            [(tile.x, tile.y, tile.z) for tile in route_tiles],
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
        )
        self.assertEqual(
            [tile.state for tile in route_tiles],
            [
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_WATER,
                h3_map_parser.ROUTE_BLOCKED,
                h3_map_parser.ROUTE_LAND,
            ],
        )

    def test_route_layer_projects_object_blocking_masks(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=8,
            levels=1,
            are_any_players=True,
        )
        terrain_tiles = tuple(
            _terrain_tile(x, y, 0, 0)
            for y in range(header.map_size)
            for x in range(header.map_size)
        )
        block_mask = bytes((
            0xFF,
            0xFF,
            0xDF,  # row 2, bit 5 -> offset (2, 3) from anchor
            0xFF,
            0xFF,
            0xF7,  # row 5, bit 3 -> offset (4, 0) from anchor
        ))
        templates = (_template(0, object_id=147, block_mask=block_mask),)
        objects = (_map_object(0, (7, 5, 0), 0),)

        route_tiles = h3_map_parser._build_route_tiles(
            header,
            terrain_tiles,
            templates,
            objects,
        )
        blocked_positions = {
            (tile.x, tile.y, tile.z)
            for tile in route_tiles
            if tile.state == h3_map_parser.ROUTE_BLOCKED
        }

        self.assertEqual(blocked_positions, {(5, 2, 0), (3, 5, 0)})

    def test_route_layer_blocks_water_when_permanent_object_blocks_it(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=2,
            levels=1,
            are_any_players=True,
        )
        terrain_tiles = tuple(
            _terrain_tile(
                x,
                y,
                0,
                h3_map_parser.H3M_TERRAIN_WATER,
            )
            for y in range(header.map_size)
            for x in range(header.map_size)
        )
        block_anchor_only = bytes((0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F))
        templates = (_template(0, object_id=147, block_mask=block_anchor_only),)
        objects = (_map_object(0, (1, 1, 0), 0),)

        route_tiles = h3_map_parser._build_route_tiles(
            header,
            terrain_tiles,
            templates,
            objects,
        )
        states_by_position = {
            (tile.x, tile.y, tile.z): tile.state
            for tile in route_tiles
        }

        self.assertEqual(states_by_position[(1, 1, 0)], h3_map_parser.ROUTE_BLOCKED)
        self.assertEqual(states_by_position[(0, 0, 0)], h3_map_parser.ROUTE_WATER)

    def test_route_layer_ignores_route_transparent_object_masks(self):
        header = h3_map_parser.H3MapHeader(
            format_version=h3_map_parser.H3M_FORMAT_SOD,
            format_name="SoD",
            map_size=2,
            levels=1,
            are_any_players=True,
        )
        terrain_tiles = tuple(
            _terrain_tile(x, y, 0, 0)
            for y in range(header.map_size)
            for x in range(header.map_size)
        )
        transparent_ids = (
            tuple(sorted(h3_map_parser.H3M_MONSTER_OBJECT_IDS))
            + (
                h3_map_parser.H3M_OBJECT_RESOURCE,
                h3_map_parser.H3M_OBJECT_RANDOM_RESOURCE,
                h3_map_parser.H3M_OBJECT_ARTIFACT,
                h3_map_parser.H3M_OBJECT_RANDOM_ARTIFACT,
                h3_map_parser.H3M_OBJECT_RANDOM_TREASURE_ARTIFACT,
                h3_map_parser.H3M_OBJECT_RANDOM_MINOR_ARTIFACT,
                h3_map_parser.H3M_OBJECT_RANDOM_MAJOR_ARTIFACT,
                h3_map_parser.H3M_OBJECT_RANDOM_RELIC_ARTIFACT,
                h3_map_parser.H3M_OBJECT_SPELL_SCROLL,
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_ENTRANCE,
                h3_map_parser.H3M_OBJECT_MONOLITH_ONE_WAY_EXIT,
                h3_map_parser.H3M_OBJECT_MONOLITH_TWO_WAY,
                h3_map_parser.H3M_OBJECT_SUBTERRANEAN_GATE,
            )
        )
        templates = tuple(
            _template(index, object_id=object_id, block_mask=b"\x00" * 6)
            for index, object_id in enumerate(transparent_ids)
        )
        objects = tuple(
            _map_object(index, (1, 1, 0), index)
            for index in range(len(templates))
        )

        route_tiles = h3_map_parser._build_route_tiles(
            header,
            terrain_tiles,
            templates,
            objects,
        )

        self.assertTrue(
            all(tile.state == h3_map_parser.ROUTE_LAND for tile in route_tiles)
        )

    def test_load_h3m_reads_player_colors_and_teams(self):
        payload = _build_minimal_sod_h3m_with_teams()

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "teams.h3m",
            parse_objects=True,
        )

        self.assertEqual(
            [
                (player.color_name, player.enabled, player.team_id)
                for player in loaded.players
            ],
            [
                ("red", True, 0),
                ("blue", True, 0),
                ("tan", True, 1),
                ("green", True, 1),
                ("orange", False, None),
                ("purple", False, None),
                ("teal", False, None),
                ("pink", False, None),
            ],
        )
        self.assertEqual(loaded.players[0].main_town_position, (70, 55, 0))
        self.assertEqual(
            [
                (team.team_id, team.color_names)
                for team in loaded.teams
            ],
            [
                (0, ("red", "blue")),
                (1, ("tan", "green")),
            ],
        )

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
        self.assertEqual(loaded.terrain_tiles, ())
        self.assertEqual(loaded.route_tiles, ())

    def test_load_h3m_parse_objects_reads_terrain_tiles_in_vcmi_order(self):
        terrain_records = (
            (0, 11, 1, 21, 0, 31, 41),
            (8, 12, 2, 22, 1, 32, 42),
            (9, 13, 3, 23, 2, 33, 43),
            (3, 14, 4, 24, 3, 34, 44),
            (4, 15, 0, 25, 0, 35, 45),
            (5, 16, 1, 26, 1, 36, 46),
            (6, 17, 2, 27, 2, 37, 47),
            (7, 18, 3, 28, 3, 38, 48),
        )
        payload = _build_minimal_sod_h3m_with_terrain(terrain_records)

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/terrain.h3m",
            parse_objects=True,
        )

        self.assertEqual(
            len(loaded.terrain_tiles),
            loaded.header.map_size * loaded.header.map_size * loaded.header.levels,
        )
        self.assertEqual(
            [(tile.x, tile.y, tile.z) for tile in loaded.terrain_tiles],
            [
                (0, 0, 0),
                (1, 0, 0),
                (0, 1, 0),
                (1, 1, 0),
                (0, 0, 1),
                (1, 0, 1),
                (0, 1, 1),
                (1, 1, 1),
            ],
        )
        self.assertEqual(
            [
                (
                    tile.terrain_type,
                    tile.terrain_view,
                    tile.river_type,
                    tile.river_direction,
                    tile.road_type,
                    tile.road_direction,
                    tile.ext_flags,
                )
                for tile in loaded.terrain_tiles
            ],
            list(terrain_records),
        )
        self.assertEqual(
            [tile.state for tile in loaded.route_tiles],
            [
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_WATER,
                h3_map_parser.ROUTE_BLOCKED,
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_LAND,
                h3_map_parser.ROUTE_LAND,
            ],
        )

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
        self.assertIn("--map-file", result.stdout)

    def test_parse_random_map_stamp_finds_embedded_timestamp(self):
        stamp = h3_map_parser.parse_random_map_stamp(
            "PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond"
        )

        self.assertEqual(stamp, (datetime(2026, 4, 26, 18, 45), "Diamond"))

    def test_resolve_h3m_map_uses_explicit_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "manual.h3m"
            map_path.write_bytes(b"not parsed by resolver")

            selected = h3_map_parser.resolve_h3m_map(
                Path(temp_dir) / "game",
                explicit_map_file=map_path,
            )

        self.assertEqual(selected, map_path)

    def test_resolve_h3m_map_rejects_missing_explicit_file(self):
        missing_path = Path("/tmp/vcmi-missing-map-for-selection-test.h3m")

        with self.assertRaises(h3_map_parser.H3MapSelectionError) as raised:
            h3_map_parser.resolve_h3m_map(
                "/tmp/game",
                explicit_map_file=missing_path,
            )

        self.assertEqual(raised.exception.path, missing_path)
        self.assertIn("not a file", raised.exception.reason)

    def test_resolve_h3m_map_matches_random_map_by_template_and_nearest_time(self):
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
            game_dir.mkdir(parents=True)
            random_maps.mkdir()
            expected = (
                random_maps
                / "PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m"
            )
            expected.write_bytes(b"selected")
            (random_maps / "PlayerOne,PlayerTwo 2026.04.26 18;45 Jebus Cross.h3m").write_bytes(
                b"wrong template"
            )
            (random_maps / "PlayerOne,PlayerTwo 2026.04.26 10;45 Diamond.h3m").write_bytes(
                b"outside tolerance"
            )

            selected = h3_map_parser.resolve_h3m_map(game_dir)

        self.assertEqual(selected, expected)

    def test_resolve_h3m_map_reports_missing_random_maps_with_map_file_hint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            game_dir = (
                Path(temp_dir)
                / "HoMM 3 Complete"
                / "Games"
                / "Random"
                / "PlayerTwo"
                / "2026.04.26 20;45 Diamond"
            )
            game_dir.mkdir(parents=True)

            with self.assertRaises(h3_map_parser.H3MapSelectionError) as raised:
                h3_map_parser.resolve_h3m_map(game_dir)

        self.assertIn("random_maps", str(raised.exception.path))
        self.assertIn("--map-file", raised.exception.reason)

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
        self.assertEqual(
            len(loaded.terrain_tiles),
            loaded.header.map_size * loaded.header.map_size * loaded.header.levels,
        )
        self.assertEqual(
            loaded.terrain_tiles[0],
            h3_map_parser.H3TerrainTile(
                x=0,
                y=0,
                z=0,
                terrain_type=0,
                terrain_view=0,
                river_type=0,
                river_direction=0,
                road_type=0,
                road_direction=0,
                ext_flags=0,
            ),
        )
        self.assertEqual(
            loaded.route_tiles[0],
            h3_map_parser.H3RouteTile(
                x=0,
                y=0,
                z=0,
                state=h3_map_parser.ROUTE_LAND,
            ),
        )

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

    def test_parse_sod_town_target_uses_visitable_tile_and_keeps_stream_offset(self):
        visit_mask = bytes((0x01, 0x00, 0x00, 0x00, 0x00, 0x40))
        templates = (
            _object_template_bytes(
                "AVCcasx0.def",
                h3_map_parser.H3M_OBJECT_TOWN,
                subid=3,
                visit_mask=visit_mask,
            ),
            _object_template_bytes(
                "AVWgnll0.def",
                h3_map_parser.H3M_OBJECT_MONSTER,
                subid=98,
                object_type=2,
            ),
        )
        objects = (
            _object_bytes(
                (7, 5, 0),
                0,
                _town_payload(
                    owner=2,
                    custom_name="Castle Keep",
                    has_garrison=True,
                ),
            ),
            _object_bytes((4, 4, 0), 1, _monster_payload(count=29)),
        )
        payload = _minimal_h3m_with_templates_and_objects(
            h3_map_parser.H3M_FORMAT_SOD,
            templates,
            objects,
            map_size=8,
        )

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/town-and-monster.h3m",
            parse_objects=True,
        )

        self.assertEqual(len(loaded.objects), 2)
        self.assertEqual(len(loaded.town_targets), 1)
        self.assertEqual(len(loaded.neutral_targets), 1)
        town = loaded.town_targets[0]
        self.assertEqual(town.object_index, 0)
        self.assertEqual((town.x, town.y, town.z), (6, 5, 0))
        self.assertEqual((town.anchor_x, town.anchor_y, town.anchor_z), (7, 5, 0))
        self.assertEqual(town.object_id, h3_map_parser.H3M_OBJECT_TOWN)
        self.assertEqual(town.h3m_subid, 3)
        self.assertEqual(town.faction_subid, 3)
        self.assertEqual(town.initial_owner, 2)
        self.assertEqual(town.custom_name, "Castle Keep")
        self.assertTrue(town.has_garrison)
        self.assertEqual(town.template.animation_file, "AVCcasx0.def")
        self.assertEqual(loaded.neutral_targets[0].object_index, 1)
        self.assertEqual(loaded.neutral_targets[0].count, 29)
        self.assertEqual(
            h3_map_parser.parse_h3m_neutral_monsters(
                payload,
                path="/tmp/town-and-monster.h3m",
            ),
            loaded.neutral_targets,
        )

    def test_parse_random_town_target_keeps_raw_subid_without_faction(self):
        templates = (
            _object_template_bytes(
                "AVCrand0.def",
                h3_map_parser.H3M_OBJECT_RANDOM_TOWN,
                subid=99,
                visit_mask=b"\x00" * 6,
            ),
        )
        objects = (
            _object_bytes((3, 2, 0), 0, _town_payload(owner=255)),
        )
        payload = _minimal_h3m_with_templates_and_objects(
            h3_map_parser.H3M_FORMAT_SOD,
            templates,
            objects,
            map_size=4,
        )

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/random-town.h3m",
            parse_objects=True,
        )

        self.assertEqual(loaded.neutral_targets, ())
        self.assertEqual(len(loaded.town_targets), 1)
        town = loaded.town_targets[0]
        self.assertEqual(town.object_index, 0)
        self.assertEqual((town.x, town.y, town.z), (3, 2, 0))
        self.assertEqual(town.object_id, h3_map_parser.H3M_OBJECT_RANDOM_TOWN)
        self.assertEqual(town.h3m_subid, 99)
        self.assertIsNone(town.faction_subid)
        self.assertIsNone(town.initial_owner)
        self.assertIsNone(town.custom_name)
        self.assertFalse(town.has_garrison)

    def test_parse_roe_town_target_uses_roe_payload_and_preserves_empty_name(self):
        templates = (
            _object_template_bytes(
                "AVCramx0.def",
                h3_map_parser.H3M_OBJECT_TOWN,
                subid=5,
                visit_mask=bytes((0x00, 0x00, 0x00, 0x00, 0x00, 0x80)),
            ),
        )
        objects = (
            _object_bytes(
                (2, 1, 0),
                0,
                _town_payload(
                    format_version=h3_map_parser.H3M_FORMAT_ROE,
                    owner=1,
                    custom_name="",
                ),
            ),
        )
        payload = _minimal_h3m_with_templates_and_objects(
            h3_map_parser.H3M_FORMAT_ROE,
            templates,
            objects,
            map_size=3,
        )

        loaded = h3_map_parser.load_h3m_bytes(
            gzip.compress(payload),
            "/tmp/roe-town.h3m",
            parse_objects=True,
        )

        self.assertEqual(loaded.header.format_version, h3_map_parser.H3M_FORMAT_ROE)
        self.assertEqual(len(loaded.town_targets), 1)
        town = loaded.town_targets[0]
        self.assertEqual(town.object_index, 0)
        self.assertEqual((town.x, town.y, town.z), (2, 1, 0))
        self.assertEqual(town.faction_subid, 5)
        self.assertEqual(town.initial_owner, 1)
        self.assertEqual(town.custom_name, "")
        self.assertFalse(town.has_garrison)

    def test_filter_removed_neutral_targets_excludes_by_object_index_and_subid(self):
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
        def target(object_index, position, h3m_subid, count, creature_name):
            return h3_map_parser.H3NeutralMonsterTarget(
                object_index=object_index,
                x=position[0],
                y=position[1],
                z=position[2],
                template=template,
                h3m_subid=h3m_subid,
                count=count,
                creature_name=creature_name,
                estimator_creature_id=h3m_subid,
            )

        gnoll_target = target(2393, (39, 70, 1), 98, 37, "Gnoll")
        gremlin_target = target(2331, (39, 75, 1), 28, 47, "Gremlin")
        master_gremlin_target = target(
            2330,
            (40, 73, 1),
            29,
            32,
            "Master Gremlin",
        )
        kept_target = h3_map_parser.H3NeutralMonsterTarget(
            object_index=2400,
            x=41,
            y=75,
            z=1,
            template=template,
            h3m_subid=30,
            count=11,
            creature_name="Stone Gargoyle",
            estimator_creature_id=30,
        )
        records = (
            h3_save_parser.RemovedNeutralRecord(
                object_index=2393,
                h3m_subid=98,
                source_offset=946676,
                removal_flags=0x8000,
            ),
            h3_save_parser.RemovedNeutralRecord(
                object_index=2331,
                h3m_subid=28,
                source_offset=947037,
                removal_flags=0xA000,
            ),
            h3_save_parser.RemovedNeutralRecord(
                object_index=2330,
                h3m_subid=29,
                source_offset=947054,
                removal_flags=0x5000,
            ),
        )

        filtered = h3_map_parser.filter_removed_neutral_targets(
            (gnoll_target, gremlin_target, master_gremlin_target, kept_target),
            records,
        )

        self.assertEqual(filtered, (kept_target,))

    def test_filter_removed_neutral_targets_can_include_removed_debug_targets(self):
        template = h3_map_parser.H3ObjectTemplate(
            template_index=3,
            animation_file="AVWgrex0.def",
            block_mask=b"\x00" * 6,
            visit_mask=b"\x01" * 6,
            terrain_mask=0x01FF,
            object_id=54,
            subid=29,
            object_type=2,
            print_priority=4,
        )
        target = h3_map_parser.H3NeutralMonsterTarget(
            object_index=2330,
            x=40,
            y=73,
            z=1,
            template=template,
            h3m_subid=29,
            count=32,
            creature_name="Master Gremlin",
            estimator_creature_id=29,
        )
        records = (
            h3_save_parser.RemovedNeutralRecord(
                object_index=2330,
                h3m_subid=29,
                source_offset=947054,
                removal_flags=0x5000,
            ),
        )

        included = h3_map_parser.filter_removed_neutral_targets(
            (target,),
            records,
            include_removed=True,
        )

        self.assertEqual(len(included), 1)
        self.assertEqual(included[0].object_index, 2330)
        self.assertTrue(included[0].removed)
        self.assertEqual(included[0].removal_note, "removed-save-record@947054")

    def test_filter_removed_neutral_targets_notes_history_source_save(self):
        template = h3_map_parser.H3ObjectTemplate(
            template_index=3,
            animation_file="AVWsprit.def",
            block_mask=b"\x00" * 6,
            visit_mask=b"\x01" * 6,
            terrain_mask=0x01FF,
            object_id=54,
            subid=119,
            object_type=2,
            print_priority=4,
        )
        target = h3_map_parser.H3NeutralMonsterTarget(
            object_index=3217,
            x=91,
            y=92,
            z=0,
            template=template,
            h3m_subid=119,
            count=22,
            creature_name="Sprite",
            estimator_creature_id=113,
        )
        records = (
            h3_save_parser.RemovedNeutralRecord(
                object_index=3217,
                h3m_subid=119,
                source_offset=939860,
                removal_flags=0x48007000,
                source_path=Path("/tmp/134.GM2"),
            ),
        )

        included = h3_map_parser.filter_removed_neutral_targets(
            (target,),
            records,
            include_removed=True,
        )

        self.assertEqual(
            included[0].removal_note,
            "removed-save-record@134.GM2:939860",
        )


if __name__ == "__main__":
    unittest.main()
