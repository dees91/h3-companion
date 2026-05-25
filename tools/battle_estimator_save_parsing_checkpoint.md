# Battle Estimator Save Parsing Checkpoint

Date: 2026-05-18

This is a working checkpoint for adding Heroes III savegame parsing to
`tools/battle_estimator.py`, focused on saves produced by the Porting Kit /
HD Mod setup on macOS.

## Goal

Read the player's current hero army from a Heroes III save and feed it into the
battle estimator, so the user does not have to type the full army manually.

Target install observed locally:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete
```

The Porting Kit wrapper points at:

```text
C:\GOG Games\HoMM 3 Complete\HD_Launcher.exe
```

which maps to:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/HD_Launcher.exe
```

## Save Container

Both `GM1` and `GM2` files tested are gzip-compressed.

Raw decompression can be done with:

```python
raw = zlib.decompress(compressed[10:-8], -zlib.MAX_WBITS)
```

Observed formats:

- `dd.GM1`: `H3SVG` starts at offset `0`
- random multiplayer `GM2` saves: `H3SVG` starts at offset `65`

The implemented parser locates `H3SVG` rather than assuming it is at byte `0`.

## Known Control Save

File:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games/dd.GM1
```

Findings:

- gzip compressed
- `H3SVG` at offset `0`
- recognized as Shadow of Death
- map: `Xathras's Prize`
- existing `h3sed` logic can find `156` heroes
- hero armies parse normally, e.g. `Adela`, `Aislinn`, `Charna`, `Clavius`

Conclusion: classic `GM1` parsing is understood by existing `h3sed`-style hero
structure parsing.

## Multiplayer GM2 Observations

Main tested folder:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games/Random/PlayerTwo/2026.04.26 20;45 Diamond
```

Important files:

```text
337.GM2
415.GM2
415_moved.GM1
```

For `415.GM2`:

- compressed size: `192575`
- decompressed size: `947013`
- `H3SVG` at offset `65`
- SoD version candidate at offset `113`: `0x1c`
- map/user strings visible:
  - `PlayerOne`
  - `PlayerTwo`
  - `2026.04.26 18;45`
  - `Diamond`
- marker at offset `964`: `BATTLE`

Important correction: `BATTLE` does not mean the save is from inside a battle.
It appears to be a save slot/name marker. The user confirmed `415.GM2` is a
normal between-turn autosave.

## Why h3sed Initially Failed On GM2

The raw GM2 file has valid save metadata, but the hero structs are not visible
to the normal `h3sed` regex.

Initial direct checks did not find:

- contiguous `7 x creature_id + 7 x count`
- `id/count` interleaving
- `u8`, `u16`, or `u32` straightforward army patterns
- hero structures through the normal `h3sed` scan

This was because the hero data in these multiplayer/HD saves is obfuscated.

## Breakthrough: XOR 0x01 Hero Data

The user created a controlled comparison:

```text
415.GM2
415_moved.GM1
```

Only intended change:

```text
swap 731 Skeleton Warrior with 181 Zombie
```

Both files decompress to exactly `947013` bytes. Diff result:

- only `21` raw bytes differ
- one expected difference is the save name at offset `964`
- the meaningful hero-army difference is around offset `783023`

Raw differing area in `415.GM2`:

```text
783023: 38 01 01 01 3a 01 01 01 3e 01 01 01 40 01 01 01
783039: 42 01 01 01 39 01 01 01 44 01 01 01 da 03 01 01
783055: b4 01 01 01 ...
```

If each byte is decoded as:

```python
decoded_byte = encoded_byte ^ 0x01
```

then this becomes standard little-endian hero army data:

```text
39 00 00 00 = 57 = Skeleton Warrior
3b 00 00 00 = 59 = Zombie
3f 00 00 00 = 63 = Vampire Lord
41 00 00 00 = 65 = Power Lich
43 00 00 00 = 67 = Dread Knight
38 00 00 00 = 56 = Skeleton
45 00 00 00 = 69 = Ghost Dragon

db 02 00 00 = 731
b5 00 00 00 = 181
3b 00 00 00 = 59
2f 00 00 00 = 47
13 00 00 00 = 19
3c 01 00 00 = 316
08 00 00 00 = 8
```

Decoded hero name at offset `783079`:

```text
Isra
```

So in `415.GM2`, decoded hero army is:

```text
Isra:
731 Skeleton Warrior
181 Zombie
59 Vampire Lord
47 Power Lich
19 Dread Knight
316 Skeleton
8 Ghost Dragon
```

In `415_moved.GM1`, decoded hero army is:

```text
Isra:
181 Zombie
731 Skeleton Warrior
59 Vampire Lord
47 Power Lich
19 Dread Knight
316 Skeleton
8 Ghost Dragon
```

The controlled swap is therefore parsed exactly.

## Inferred GM2 Hero Structure

For this GM2 variant, the hero struct appears to match the normal h3sed/HoMM3
hero layout after XOR-decoding bytes with `0x01`.

For a hero name offset:

```text
army creature IDs offset = name_offset - 56
army counts offset       = name_offset - 28
hero name offset         = name_offset
```

Using the `Isra` example:

```text
creature IDs: 783023
counts:       783051
name:         783079
```

Each creature ID and count is a 4-byte little-endian integer after XOR decode.

This also matches the standard h3sed offsets within a hero struct:

```text
army_types  = 113
army_counts = 141
name        = 169
```

Therefore:

```text
hero_struct_start = name_offset - 169
army_types        = hero_struct_start + 113
army_counts       = hero_struct_start + 141
```

For `Isra`:

```text
hero_struct_start = 782910
army_types        = 783023
army_counts       = 783051
name              = 783079
```

## Automatic Scan Result

A simple scanner that:

1. iterates candidate name offsets,
2. XOR-decodes 13 bytes as a null-padded hero name,
3. reads 7 decoded creature IDs from `name_offset - 56`,
4. reads 7 decoded counts from `name_offset - 28`,
5. validates known creature IDs and sane counts,

found `156` hero-like structures in `415.GM2`.

The important candidate:

```text
offset 783079
Isra total 1361:
731 Skeleton Warrior
181 Zombie
59 Vampire Lord
47 Power Lich
19 Dread Knight
316 Skeleton
8 Ghost Dragon
```

This strongly suggests the GM2 multiplayer hero section is parseable without
needing full h3sed integration.

## Earlier 337.GM2 Comparison

The user reported for `337.GM2`:

```text
256 Skeleton Warrior
53 Zombie
47 Vampire Lord
32 Power Lich
11 Dread Knight
172 Skeleton
5 Ghost Dragon
```

Initial raw searches did not find a normal army block. That result is now
explained by the XOR `0x01` encoding. This remains a historical observation;
full real saves are not committed as fixtures.

## Implemented Phase 1 Direction

Save parsing support is implemented in a narrow, pragmatic way through
`tools/h3_save_parser.py` plus autosave-first dispatch in
`tools/battle_estimator.py`.

Implemented command examples:

```bash
python3 tools/battle_estimator.py
python3 tools/battle_estimator.py Isra vs "horde of ancient behemoth"
python3 tools/battle_estimator.py --hero Isra vs "30 champion"
python3 tools/battle_estimator.py --save 415 --hero Isra vs "..."
python3 tools/battle_estimator.py --save-file 415.GM2 --hero Isra vs "..."
python3 tools/battle_estimator.py --list-save-heroes --all-heroes
```

The originally proposed `--from-save PATH` flag was not used. The implemented
equivalent is `--save-file PATH`.

Implemented pieces:

1. `load_save(path)`
   - reads gzip
   - supports raw deflate fallback
   - returns decompressed bytes plus located `H3SVG`

2. `select_game_dir()`, `select_latest_save()`, `select_numbered_save()`
   - select explicit or newest game folder
   - select latest numeric `.GM1`/`.GM2`
   - prefer `.GM2` for the same number
   - ignore special/manual save names

3. `scan_xor01_hero_armies(raw)`
   - scans candidate hero name offsets
   - decodes candidate hero structs with `byte ^ 0x01`
   - extracts name + seven army slots

4. `filter_relevant_heroes()` and `select_hero()`
   - default visibility is `ai_value >= 5000 OR total_creatures >= 50`
   - `--all-heroes` bypasses filtering
   - exact and unambiguous prefix matching are supported
   - missing and ambiguous selections are structured errors

5. config helpers
   - user-global config at `~/.config/vcmi-battle-estimator/config.json`
   - supports `autosave_dir` and wizard `last_hero`

Selected hero armies are converted into the existing battle estimator creature
model before simulation, avoiding duplicate module identity when the estimator
is run as a script.

## Implemented Phase 2 Nearby Scan Direction

Nearby scan support is implemented as a hybrid save + H3M workflow:

```bash
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --target-type neutral
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --target-type hero
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --map-file "/path/to/map.h3m"
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --include-removed
```

Examples without `--map-file` depend on random-map auto-detection. Use the
explicit map path when auto-detection cannot resolve the generated `.h3m`.

Implemented pieces:

1. H3M map loading and neutral target parsing in `tools/h3_map_parser.py`
   - detects generated-map H3M headers at offset `0` or `43`
   - resolves matching random maps from the autosave game folder
   - parses object templates and neutral monster objects sequentially
   - maps supported neutral creatures by DEF/template name

2. Save-side current-position and target state in `tools/h3_save_parser.py`
   - decodes hero position from the XOR `0x01` hero struct
   - builds other-hero target records from parsed hero armies and positions
   - detects removed neutral monster records from the late save log

3. Scan and estimation in `tools/battle_estimator.py`
   - filters targets to the selected hero's `z` level
   - uses Manhattan distance, `abs(dx) + abs(dy)`
   - filters removed neutrals by default, with `--include-removed` for debug
   - estimates neutral targets as one mapped creature stack
   - estimates hero targets as army-only and marks them `army-only`
   - uses `500` simulations per scan target by default; `--simulations/-n`
     overrides this
   - keeps unsupported targets in the output with a clear note instead of
     crashing the whole scan

Known Phase 2 limitations:

- `.h3m` neutral counts are base map object counts; save-side split/upgraded
  neutral compositions are not reconstructed.
- Scan distance is not pathfinding. It ignores terrain, roads, obstacles,
  guards, movement points, and reachability.
- Only same-level (`z`) targets are included.
- Hero-vs-hero estimates use creature stacks only. Hero stats, skills,
  artifacts, spells, morale, luck, terrain, and tactics are still not modeled.
- Unsupported H3M DEF/template mappings are reported as unsupported notes.

Local real-file verification used this command shape; real save and map files
remain outside the repository:

```bash
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --save-file "/path/to/post_attack_2.GM1" --map-file "/path/to/Diamond.h3m"
```

The observed local result printed Isra at `(39,69,1)`, radius `10`, simulation
count `500`, and distance-sorted rows where supported targets had `win%` values
and unsupported H3M mappings had an unsupported note.

## Current Town Ownership Evidence, Anonymized

Date: 2026-05-25

This research pass inspected local save files only in place. No real save files,
map files, cache files, raw bytes, paths, map names, player names, or custom
town names are recorded here.

### Same-Map Evidence

One anonymized random-map group was used for the strongest observations:

- `Map Group 1`
  - save series contains many numeric autosaves from one generated map,
  - resolved H3M map has size `108`, two levels, and `24` parsed town targets,
  - town target order, coordinates, object indices, object ids, subids, and
    initial owners are stable for all saves in the group,
  - inspected saves all have `H3SVG` at offset `65`,
  - decompressed sizes differ over the series, so absolute offset comparison
    needs anchoring and cannot assume fixed positions.

The observations below use anonymized save labels and town labels. Owner ids
use standard Heroes III color ids:

```text
0 red, 1 blue, 2 tan, 3 green, 4 orange, 5 purple, 6 teal, 7 pink
```

### Observed Owner Facts

The pass did not yet isolate a direct save-side town-owner field. The facts
below are high-confidence ownership proxies from game-state rules: a visible
hero record with owner color `C` occupying a parsed town's visitable tile implies
that the town is currently controlled by owner `C` or has just been captured by
that owner. This is useful evidence for locating future direct town-owner
records, but it should not replace a direct parser once that field is found.

| Map Group | Save Pair | Town | Initial Owner | Observed Earlier | Observed Later | Evidence |
|---|---|---|---|---|---|---|
| 1 | A -> B | T0 | 0 red | 2 tan | 0 red | hero owner/position records on the same town tile |
| 1 | C -> D | T2 | 2 tan | 2 tan | 0 red | hero owner/position records on the same town tile |

Additional same-map observations show neutral towns occupied by non-neutral
owners later in the series:

- `T7`: observed as `2 tan`, later observed as `1 blue`.
- `T14`: observed as `0 red`, later observed as `2 tan`.

These facts confirm that at least two same-map saves have different current
town-control states, even though the direct town-owner byte has not yet been
identified.

### Byte-Structure Evidence

The owner/position observations above come from already understood XOR `0x01`
hero structures:

- hero name offset remains the parser's `source_offset`,
- hero struct start / owner byte is at `source_offset - 169`,
- hero position is five decoded bytes at `source_offset - 194`,
- position stores `x`, `y`, and `z`; owner stores the Heroes III color id.

Anonymized supporting ranges relative to the `H3SVG` offset:

| Save | Town | Observed Owner | Supporting Structure Range |
|---|---|---|---|
| A | T0 | 2 tan | two hero structures around `H3SVG + 809k` and `H3SVG + 810k` |
| B | T0 | 0 red | one hero structure around `H3SVG + 784k` |
| C | T2 | 2 tan | one hero structure around `H3SVG + 811k` |
| D | T2 | 0 red | one hero structure around `H3SVG + 734k` |

This establishes a reliable way to build anonymized synthetic fixtures for
"hero occupying parsed town tile" ownership-proxy behavior. A future direct
town-owner fixture should still target the actual town record once identified.

### Negative Searches

Several simple direct-owner hypotheses did not produce a reliable town-owner
record:

- no simple contiguous `24`-byte town-owner vector was found using the observed
  owner subset,
- no direct town `x/y/z + owner`, `owner + x/y/z`, encoded `x + yz + owner`,
  or flattened tile-index owner pattern was found in raw or XOR `0x01` form,
- searching raw and XOR `0x01` town object indices produced many false
  positives and did not isolate a town-current-owner structure.

The next research/documentation step should therefore distinguish two possible
approaches:

1. A provisional ownership inference based on visible hero owner + exact town
   tile occupancy.
2. A direct current-town-owner parser, still requiring a better save-side
   structure hypothesis and synthetic fixtures.

## Bounded Current Town Ownership Hypothesis

This section deliberately documents a bounded proxy hypothesis, not a direct
save-side town-owner parser. The direct town-owner byte or save-side town record
has not been isolated. Any implementation based on this section must expose its
confidence and must return `ownership_unavailable` outside the narrow supported
case.

### Town Target Identity

Candidate towns are recognized from the parsed H3M map, not from a direct save
town structure. A town target is eligible only when the H3M parser can provide a
deterministic town identity:

- `object_id` is the standard H3M town object type,
- `object_index` and `h3m_subid` are available,
- the town's anchor tile and projected visitable tile are available,
- `x`, `y`, and `z` identify one deterministic visitable tile,
- `faction_subid` and H3M `initial_owner` are preserved as map context.

The current save does not need to repeat all of that identity for the proxy
path. The map target gives the candidate town; the save contributes visible
hero state that may imply current control.

### Proxy Owner Inference

Current owner color is not decoded directly from a town record. The supported
proxy path is:

1. Parse visible hero records with the existing supported save scanner.
2. Decode the hero owner color from the hero struct start
   (`source_offset - 169`) using the known save encoding.
3. Decode the hero position from the five-byte position field
   (`source_offset - 194`) using the same save encoding.
4. Match a hero to a town only when hero `(x, y, z)` exactly equals the H3M
   town target's projected visitable tile.
5. If exactly one eligible owned hero matches the town tile, infer:

```text
current_owner_color = hero.owner_color_id
ownership_source = hero_on_town_tile_proxy
ownership_confidence = proxy
```

If a future direct save-side town-owner field is discovered and passes its own
validation, it should supersede this proxy. If the direct field and proxy
conflict, the parser must not silently choose one; it should expose
`ownership_unavailable` or a dedicated conflict status until the conflict is
understood.

### Required `ownership_unavailable` Cases

Return `ownership_unavailable` instead of guessing when any of these conditions
apply:

- the H3M map is unavailable, mismatched, or cannot be parsed,
- the object is not a standard parsed H3M town target,
- the town's visitable tile cannot be resolved deterministically,
- the save format is unsupported or hero records cannot be scanned with a
  supported key/layout,
- no eligible visible hero occupies the town visitable tile,
- the matching hero has no decoded owner color or is unowned,
- the matching hero has no decoded position, an out-of-bounds position, or a
  level that does not match the town tile,
- multiple visible owned heroes occupy the same town tile, even when their
  owner colors agree,
- a hidden or otherwise parser-invisible hero is required to explain ownership,
- a future direct current-owner field is present but conflicts with the proxy,
- any candidate structure is truncated, ambiguous, or only matches by loose byte
  patterns such as object index or coordinates without semantic validation.

### Fixture Implications

Until a direct owner record is found, synthetic fixtures for the next parser
tasks should validate the bounded proxy path and preserve
`ownership_unavailable` for non-proxy cases. Useful synthetic cases:

- a town with H3M initial owner `A` and one visible hero of owner `B` on the
  town visitable tile, expecting proxy current owner `B`,
- a town with no hero on its visitable tile, expecting `ownership_unavailable`,
- a town with a hero on the tile but unknown/unowned owner, expecting
  `ownership_unavailable`,
- two visible owned heroes on the same town tile, expecting
  `ownership_unavailable`,
- a map/save mismatch where hero coordinates would otherwise match a different
  map, expecting `ownership_unavailable`,
- malformed/truncated hero owner or position fields, expecting
  `ownership_unavailable`.

These fixtures should be synthetic byte buffers and synthetic map targets only;
real `.GM1`, `.GM2`, or `.h3m` files must not be committed.

## Important Caveats

- This checkpoint only proves army extraction for the observed Porting Kit /
  HD Mod multiplayer saves.
- It does not yet identify current player ownership from save data.
- It does not yet distinguish active hero from all heroes except by name or
  by army size.
- `BATTLE` at offset `964` must not be used as a battle-state indicator.
- Full hero parsing is not required for the first useful implementation;
  extracting name + 7 army slots is enough.

## Current Status

Implemented Phase 1 facts:

- `dd.GM1` classic save can be parsed normally.
- `415.GM2` multiplayer save can be parsed by XOR-decoding hero data.
- `415_moved.GM1` confirms the army slot swap exactly.
- `Isra` in `415.GM2` is recoverable with the correct army.
- The production parser module exists at `tools/h3_save_parser.py`.
- The CLI supports autosave-first simulation, hero listing, config commands,
  and the no-argument wizard.
- The local browser GUI entrypoint exists at `tools/battle_estimator_gui.py`;
  it serves a read-only map, hero selection, single-target estimates, radius
  scan visualization, save picker, and follow-latest refresh on `127.0.0.1`.
- Tests use synthetic byte buffers and temporary directories; real local save
  paths above are investigation notes, not required repo fixtures.
