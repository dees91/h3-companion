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

3. Historical Phase 2 scan and estimation in `tools/battle_estimator.py`
   - filters targets to the selected hero's `z` level
   - uses Manhattan distance, `abs(dx) + abs(dy)`
   - filters removed neutrals by default, with `--include-removed` for debug
   - estimates neutral targets as one mapped creature stack
   - estimated hero targets as army-only and marked them `army-only`
   - uses `500` simulations per scan target by default; `--simulations/-n`
     overrides this
   - keeps unsupported targets in the output with a clear note instead of
     crashing the whole scan

Known Phase 2 limitations from this historical checkpoint:

- `.h3m` neutral counts are base map object counts; save-side split/upgraded
  neutral compositions are not reconstructed.
- Scan distance is not pathfinding. It ignores terrain, roads, obstacles,
  guards, movement points, and reachability.
- Only same-level (`z`) targets are included.
- Hero-vs-hero estimates used creature stacks only. This was superseded by the
  later bounded hero-combat implementation for supported combat-context
  profiles.
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
2. A direct current-town-owner parser. This was later implemented for the
   observed town-state record pattern described below.

## Bounded Current Town Ownership Hypothesis

This section deliberately documents the older bounded proxy hypothesis, not the
direct save-side town-owner parser implemented later. Any proxy implementation
based on this section must expose its confidence and must return
`ownership_unavailable` outside the narrow supported case.

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

The proxy path does not decode current owner color directly from a town record.
Its supported flow is:

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

The direct town-state record parser described below supersedes this proxy.
Proxy inference remains a fallback only when no direct candidate record is
present; duplicated, invalid, or ambiguous direct records stay unavailable and
do not fall back to proxy inference.

## Direct Town-State Ownership Parser

`detect_current_town_ownership(data, town_targets)` now first scans decompressed
save bytes for exact town-state records joined to parsed H3M town targets. The
supported observed record pattern is deliberately strict:

- town identity uses the H3M town sequence index from `enumerate(town_targets)`,
  not `object_index`,
- the record owner byte is accepted only as `0..7` for player colors or `0xff`
  for neutral/unowned,
- `h3m_subid` and the town's projected visitable `(x, y, z)` must match,
- the observed record context must match the supported town-state shape,
- duplicate matching records or invalid owner bytes return
  `ownership_unavailable` instead of falling back to proxy.

Successful direct observations use:

```text
ownership_status = exact
ownership_source = save_town_state_record
ownership_confidence = exact
```

An exact neutral/unowned town has `current_owner_color_id = None` with
`ownership_status = exact`; this is known current ownership, not an unavailable
state. If an exact record and a hero-on-town proxy disagree, the exact record
wins because it is the direct town-state source.

### Implemented Parser Contract

The implemented parser contract lives in `tools/h3_save_parser.py`:

- `detect_current_town_ownership(data, town_targets)` is the main save-byte API.
  It scans direct town-state records from decompressed save bytes first, then
  uses proxy inference only when no direct candidate record is present for a
  town.
- `infer_current_town_ownership(town_targets, heroes)` is the proxy fallback
  helper. It accepts parsed H3M town targets and the raw detected visible save
  heroes.
- Results are `TownOwnershipObservation` records with explicit
  `ownership_status`, `ownership_source`, `ownership_confidence`, optional
  `current_owner_color_id`, `reason`, and matching-hero details.
- Successful proxy observations use:

```text
ownership_status = proxy
ownership_source = hero_on_town_tile_proxy
ownership_confidence = proxy
```

Unavailable observations use `ownership_status = ownership_unavailable` and a
closed reason string such as `no_visible_hero_on_town_tile`,
`ambiguous_visible_heroes_on_town_tile`, or `missing_hero_owner_color`.

This API does not prove that the supplied H3M map is the correct map for the
save. Callers must only pass town targets from a trusted map/save context. If
map resolution is missing or mismatched, the caller should treat ownership as
unavailable instead of calling the proxy inference on unrelated town targets.

### Required `ownership_unavailable` Cases

Return `ownership_unavailable` instead of guessing when any of these conditions
apply:

- the H3M map is unavailable, mismatched, or cannot be parsed,
- the object is not a standard parsed H3M town target,
- the town's visitable tile cannot be resolved deterministically,
- the save format lacks the supported direct town-state record and proxy
  inference is also unavailable,
- no eligible visible hero occupies the town visitable tile,
- the matching hero has no decoded owner color or is unowned,
- the matching hero has no decoded position, an out-of-bounds position, or a
  level that does not match the town tile,
- multiple visible owned heroes occupy the same town tile, even when their
  owner colors agree,
- a hidden or otherwise parser-invisible hero is required to explain ownership,
- direct town-state records are duplicated or have invalid owner bytes,
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

## Hero Combat Data Evidence, Anonymized

Date: 2026-05-25

This research pass inspected local real saves in place. No real save files, map
files, cache files, raw bytes, paths, map names, player names, or custom object
names are recorded here.

The validation source was local `h3sed export` output for the same save files.
This is not a game-screen screenshot, but it is an independent parser already
used as a reference in earlier save-parsing work. The observed primary values
should be treated as current/effective save-stored values until artifact/base
stat separation is validated directly.

### Validated GM1 Combat Fields

Two real Shadow of Death `GM1` saves from one generated-map series were
inspected. Both have `H3SVG` at offset `0` and use the raw `0x00` hero-struct
encoding. The observed hero is a standard built-in hero name, not private data.

For the validated hero, combat-adjacent fields are in the same hero struct
already used for name, army, position, and owner color. No linked record was
needed for these fields.

Offsets below are relative to the parser's existing `source_offset`, which is
the hero name offset:

| Field | Candidate Offset | Encoding |
|---|---:|---|
| hero struct start | `source_offset - 169` | anchor |
| experience | `source_offset - 130` | little-endian `u32` |
| learned secondary skill count | `source_offset - 126` | `u8` |
| mana left | `source_offset - 122` | little-endian `u16` |
| level | `source_offset - 120` | `u8` |
| secondary skill levels | `source_offset + 13` through `+40` | 28 `u8` values |
| secondary skill display slots | `source_offset + 41` through `+68` | 28 `u8` values |
| primary skills | `source_offset + 69` through `+72` | attack, defense, power, knowledge as `u8` |

Secondary skills use the standard H3 skill order:

```text
Pathfinding, Archery, Logistics, Scouting, Diplomacy, Navigation, Leadership,
Wisdom, Mysticism, Luck, Ballistics, Eagle Eye, Necromancy, Estates,
Fire Magic, Air Magic, Water Magic, Earth Magic, Scholar, Tactics, Artillery,
Learning, Offense, Armorer, Intelligence, Sorcery, Resistance, First Aid
```

A skill is active when its level byte is non-zero and its slot byte is non-zero
and less than or equal to the learned skill count. Slot bytes define hero-screen
ordering. Level ids decode as `1 = Basic`, `2 = Advanced`, `3 = Expert`.

Validated observations:

| Save Label | Candidate Primary | `h3sed` Primary | Candidate Secondary Skills | `h3sed` Secondary Skills |
|---|---|---|---|---|
| Combat Save A | `3/1/3/3` | `3/1/3/3` | Expert Wisdom; Expert Earth Magic; Basic Necromancy; Advanced First Aid; Basic Eagle Eye | same |
| Combat Save B | `4/2/4/5` | `4/2/4/5` | Expert Wisdom; Expert Earth Magic; Advanced Necromancy; Expert First Aid; Expert Eagle Eye | same |

The same relative fields also matched `h3sed` experience, level, mana, and
skill count:

| Save Label | Experience | Level | Mana Left | Skill Count |
|---|---:|---:|---:|---:|
| Combat Save A | `6843` | `6` | `1` | `5` |
| Combat Save B | `14944` | `10` | `11` | `5` |

Validation signals:

- the existing parser identified the same hero record by name, army, position,
  owner color, and source offset,
- primary values changed between the two saves while the relative offsets
  stayed stable,
- secondary skills decoded exact names, order, and levels, including
  Necromancy changing from Basic to Advanced and First Aid/Eagle Eye changing
  from partial to Expert,
- another nearby standard hero in the same saves decoded different primary
  values at the same relative offsets, reducing the chance that these are
  global or static bytes,
- `h3sed` reports the same learned skill count as the decoded non-empty skill
  slots.

### Adjacent Data And Unsupported Fields

The same h3sed layout places spellbook and artifact data later in the same
hero struct: equipped artifact slots start at `source_offset + 213`,
the spellbook slot is at `source_offset + 349`, and inventory starts at
`source_offset + 365`. Those offsets were not validated enough for the battle
estimator in this pass. In particular:

- artifact ids and combination-artifact reservation bytes need separate parser
  fixtures before they can be trusted,
- primary Attack/Defense values should be treated as current/effective
  save-stored values; base stats minus artifact bonuses were not independently
  validated,
- spellbook presence is observable in the struct, but spellbook contents and
  castable spell state remain outside the passive combat estimator scope,
- no separate numeric hero specialty identifier was isolated; continue linking
  standard hero metadata by resolved hero name plus source-offset identity until
  a save-side id is validated.

The local `h3sed` version rejected the observed offset-65 multiplayer `GM2`
saves as unrecognized. Existing `GM2` army/name/position/owner parsing works
through XOR `0x01`. Later local validation against an anonymized same-map GM2
series found stable primary and secondary vectors for the accepted owned hero
records, so the parser now supports the bounded offset-65 GM2 profile described
below.

## Bounded Hero Combat Data Hypothesis

This section records the bounded parser hypothesis that was later implemented
for narrow GM1 and GM2 combat-context profiles. It deliberately supports only
validated narrow cases and must return explicit non-complete statuses outside
those cases.

### Supported Structure

The first supported combat-context structure was:

- Shadow of Death `GM1`,
- `H3SVG` at offset `0`,
- accepted hero record using raw `0x00` encoding,
- same hero struct already accepted by name, army, position, and owner parsing.

The second supported combat-context structure is:

- `GM2`,
- `H3SVG` at offset `65`,
- accepted hero record using XOR `0x01` encoding,
- same hero struct already accepted by name, army, position, and owner parsing,
- secondary-skill count derived from active level/slot vectors instead of the
  `-126` count byte.

The hero name offset remains the stable anchor (`source_offset`). The candidate
combat fields are in the same hero struct:

| Field | Relative Offset From `source_offset` | Decode |
|---|---:|---|
| experience | `-130` | little-endian `u32` |
| secondary skill count | `-126` | `u8` |
| mana left | `-122` | little-endian `u16` |
| level | `-120` | `u8` |
| secondary skill levels | `+13..+40` | 28 `u8` values |
| secondary skill slots | `+41..+68` | 28 `u8` values |
| primary skills | `+69..+72` | attack, defense, power, knowledge as `u8` |

For the supported GM2 profile, the same relative offsets are decoded with the
same per-hero XOR `0x01` key used for name/army parsing. The count byte at
`-126` is not trusted for GM2; the parser derives secondary count from active
level/slot vectors and validates the resulting `1..N` slot permutation.

### Primary Skill Decode

Primary skills decode as four one-byte current/effective save-stored values in
file order:

```text
attack, defense, spell_power, knowledge
```

These values must not be described as base stats. Artifact bonuses may already
be included, and artifact/base separation is not validated. A later artifact
parser must avoid double-counting artifact bonuses when primary skills are
already read from the save.

For the parser tasks, primary context is complete only when:

- the hero record itself is accepted by the existing scanner,
- the four-byte primary window is in bounds,
- all four values can be decoded with the supported record key,
- fixture validation proves the values round-trip for representative low,
  changed, and magic-primary cases.

If primary decoding fails, return combat context `unavailable`; do not infer
stats from hero class, level, VCMI starting data, or artifact guesses.

### T16 Primary Parser Implementation

Implemented on 2026-05-25.

The parser now exposes a `HeroCombatContext` on each parsed `HeroArmy`. T16's
first supported status was `primary-only`, with current/effective
Attack/Defense/Spell Power/Knowledge values decoded from the bounded primary
window above. T17 extended the same context with validated secondary skills and
the `primary+secondary` status.

The original T16/T17 support gate was intentionally narrow:

- loaded save path suffix is `.GM1` case-insensitively,
- `H3SVG` starts at offset `0`,
- the accepted hero record uses raw `0x00` encoding,
- the four-byte primary window is in bounds.

Unsupported cases return `status = unavailable` with
`reason = unsupported_save_structure`. Truncated primary windows return
`reason = truncated_primary` while preserving the accepted army record. Direct
byte scans without loaded-save metadata also remain unavailable by default, so
the parser does not silently infer combat stats from loose byte patterns.
G01 later added the bounded GM2 offset-65/XOR-`0x01` profile described above.

When secondary vectors validate, supported saves now report
`primary+secondary`. When primary validates but secondary vectors do not,
supported saves report `primary-only` with the secondary failure reason.

### Secondary Skill Decode

Secondary skill data is two parallel 28-byte vectors indexed by standard H3
secondary-skill order. Level ids are:

```text
0 = absent, 1 = Basic, 2 = Advanced, 3 = Expert
```

Slot ids are one-based hero-screen ordering. For complete secondary context:

- the skill count must be an integer `0..8`,
- active skills must have both non-zero level and non-zero slot,
- inactive skills must have both level and slot equal to zero,
- active level ids must be `1..3`,
- active slots must form the exact permutation `1..skill_count`,
- no skill id may appear twice, which should already follow from the fixed
  vector but must remain true after normalization,
- the number of active skills must equal the skill count,
- each normalized skill id must be known to the recommender/VCMI metadata
  mapping before it is exposed to GUI skill state.

If primary skills validate but secondary skills fail any rule above, return a
`primary-only` combat context. Do not fall back to VCMI starting skills or the
manually maintained recommendation state as if they were current save skills.

### T17 Secondary Parser Implementation

Implemented on 2026-05-25.

The parser initially decoded the secondary skill count, 28 skill-level bytes,
and 28 display-slot bytes for the same bounded `.GM1`/`H3SVG=0`/raw `0x00`
structure supported by T16. G01 later added the bounded GM2 offset-65/XOR-`0x01`
profile, where the secondary count is derived from active level/slot vectors.

Complete secondary context returns:

- `status = primary+secondary`,
- save-derived current/effective primary skills,
- save-derived current secondary skills in hero-screen slot order.

Skill ids are normalized through the vendored VCMI skill metadata index map, so
the standard H3 Offense index returns the project skill id `offence`, while
Armorer and Archery return `armorer` and `archery`.

Invalid secondary vectors keep the accepted primary skills and return
`status = primary-only` with an explicit reason such as
`invalid_secondary_count`, `invalid_secondary_slot`,
`invalid_secondary_level`, `secondary_level_slot_mismatch`,
`unknown_secondary_skill`, or `truncated_secondary`. Unsupported save layouts
still return `unavailable`, and no parser path falls back to VCMI starting
skills or manually maintained recommendation state.

### T18-T21 Combat Context And Estimator Implementation

Implemented on 2026-05-25.

The originally implemented parser gate was deliberately narrow:

- loaded save path suffix is `.GM1` case-insensitively,
- `H3SVG` starts at offset `0`,
- the accepted hero record uses raw `0x00` encoding,
- the hero record is already accepted by name, army, position, and owner
  parsing.

G01 extended that gate with a second bounded profile:

- loaded save path suffix is `.GM2` case-insensitively,
- `H3SVG` starts at offset `65`,
- the accepted hero record uses XOR `0x01` encoding,
- secondary-skill count is derived from active level/slot vectors before the
  same secondary-skill validation is applied.

`HeroCombatContext` now carries `status`, `source`, `reason`,
`primary_skills`, and validated `secondary_skills`. Only the loaded-save-aware
parser path can set `source = save`. Direct byte scans and unsupported
save/key profiles still return unavailable combat context, although their
armies may still be parsed for army-only estimates.

The estimator applies only these save-derived combat effects:

- current/effective primary Attack and Defense,
- Offence passive melee damage,
- Armorer passive incoming damage reduction,
- Archery passive ranged damage.

Spell Power and Knowledge are exposed as parsed primary fields but are not used
by the current battle simulator. Artifacts, active spells and spellbook effects,
morale/luck, tactics, terrain, specialties, and many creature special abilities
remain omitted or simplified.

Estimate payloads and GUI/CLI output report an explicit combat model instead of
overloading target notes. Per-side statuses are estimator-facing:

- `army-only`: no save-derived combat context was applied for that side,
- `primary-only`: primary Attack/Defense was applied, but secondary passives
  were not validated,
- `primary+secondary`: primary Attack/Defense and validated secondary passives
  were available,
- `partial`: reserved for future partially parsed save-derived context.

The GUI estimate panel shows a compact model label and applied component chips,
and lists globally omitted model components so partial modeling is visible to
the user.

Experience, level, and mana are supporting fields. They can help validate a
fixture or explain a parsed context, but they should not be hard gates for
primary or secondary skill support until exact range and consistency rules are
covered by synthetic tests.

### Required Non-Complete Cases

Return `unavailable` when:

- the save is not a supported `GM1`/`H3SVG=0`/raw-hero-struct case or
  supported `GM2`/`H3SVG=65`/XOR-`0x01` hero-struct case,
- the existing hero scanner does not accept the hero record,
- the primary window is truncated or cannot be decoded,
- the candidate structure only matches by loose byte patterns without a valid
  hero name/army anchor,
- a future direct hero id or linked combat record conflicts with the same-struct
  data and the conflict is not understood.

Return `primary-only` when:

- primary skills validate but the secondary vectors are truncated,
- skill count is greater than `8`,
- active secondary slots are duplicated, out of range, or not an exact
  `1..skill_count` permutation,
- any level id is outside `0..3`, or an active level id is outside `1..3`,
- a level/slot mismatch leaves one side zero and the other non-zero,
- decoded secondary skill ids cannot be mapped to known project metadata.

Leave these fields unsupported until separately validated:

- artifacts and backpack inventory,
- base primary stats separated from artifact bonuses,
- spellbook contents, castable spell state, and mana model beyond `mana_left`,
- current morale, luck, terrain, tactics, active spell effects, and battle-side
  modifiers,
- save-side numeric hero specialty identifiers,
- unsupported `GM2`/XOR `0x01` variants outside the offset-65 profile.

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
