# Phase 2: Battle Estimator Nearby Scan - Task Breakdown

> **Source**: research and `grill-me` planning session on 2026-05-19.
> This plan extends the autosave-first battle estimator with a nearby target
> scan that combines the current save with the generated `.h3m` map.
>
> **Related**:
> [Battle Estimator Autosave Brief](./battle-estimator-autosave-brief.md),
> [Phase 1 Autosave MVP Tasks](./phase-1-battle-estimator-autosave-mvp-tasks.md),
> and
> [`tools/battle_estimator_save_parsing_checkpoint.md`](../tools/battle_estimator_save_parsing_checkpoint.md).

---

> **MANDATORY FOR ALL AGENTS**
>
> The **Summary Table** at the bottom of this file is the single source of
> truth for task status. Follow these rules:
>
> 1. **Before starting a task**: set its Status to `in-progress` in the
>    Summary Table.
> 2. **After completing a task**: set its Status to `done` in the Summary
>    Table.
> 3. **After completing a task**: check all tasks that list your completed task
>    in their "Blocked By" column. If all blockers are now `done`, change their
>    Status from `blocked` to `todo`.
> 4. **Do not start** a task that is `blocked`.
> 5. **Before marking `done`**: run task-specific verification plus the
>    broadest relevant Python verification available at that point.
>
> Status values: `todo` = ready to pick up | `in-progress` = being worked on |
> `done` = completed | `blocked` = waiting on dependencies

---

## Goal

Add a command that lets the user select a hero from the current autosave, scan
nearby attack targets on the same map level, run the existing battle estimator
for every target, and print a distance-sorted ranking.

Target command shape:

```bash
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --target-type neutral
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --target-type hero
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --map-file "/path/to/map.h3m"
```

The feature is intentionally a pragmatic scouting/ranking tool. It does not
try to become a full Heroes III pathfinder or a full hero-vs-hero combat model.

## Product Decisions

- `--scan-nearby` immediately runs battle estimates for every target in radius.
- Default output includes both neutral monsters and other heroes.
- `--target-type all|neutral|hero` filters the scan target set.
- Results are sorted primarily by tile distance, not by win percentage.
- Distance is Manhattan distance: `abs(dx) + abs(dy)`.
- Only targets on the same map level `z` are included.
- Neutral monster count comes from `.h3m`.
- For MVP, one neutral map object is modeled as one army stack:
  exact `.h3m` count plus mapped creature type.
- Other heroes are modeled army-only with the same limitations as Phase 1:
  no hero stats, skills, artifacts, spells, morale, luck, terrain, or tactics.
- Removed/killed neutral monsters are filtered by default.
- `--include-removed` includes removed neutral monsters for debugging.
- The scan mode should default to a faster simulation count than full manual
  analysis, for example 500 simulations per target, while still allowing the
  user to override with `--simulations`.
- `.h3m` is auto-detected from the current autosave game folder when possible.
- `--map-file` is an explicit override and should be used for debugging or
  when auto-detection fails.

## Critical Implementation Notes

### Hybrid Data Source

Use a hybrid model:

- save file (`.GM1` / `.GM2`): current selected hero, current hero position,
  other heroes, hero armies, and removed neutral object detection.
- map file (`.h3m`): neutral monster positions, base creature type, and base
  count.

Do not attempt save-only neutral count parsing for MVP. Research showed that
`.h3m` already stores the exact base count for neutral monsters.

### Known Local Map Pair

Autosave folder:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games/Random/PlayerTwo/2026.04.26 20;45 Diamond
```

Matching generated map:

```text
/Users/example/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/random_maps/PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m
```

Important observed `.h3m` values:

- `post_attack_2.GM1`, Isra at `(39,69,1)`: Gnoll at `(39,70,1)`,
  count `37`, matching the "Lots of Gnolls" test target.
- Gremlin at `(39,75,1)`, count `47`.
- Master Gremlin at `(40,73,1)`, count `32`.
- A fly target near the earlier attack test has total count `20`; the in-game
  battle was observed as `15 Serpent Flies, 5 Dragon Flies`, so split/upgraded
  composition is a known MVP limitation.

### `.h3m` Container and Header

Generated random maps are gzip-compressed.

The random map files observed locally do not start with the standard H3M
format ID at offset `0`. They have an HD/RMG prefix, and the standard SoD
header starts at offset `43`.

Observed examples:

```text
PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m -> H3M start offset 43, version 28, size 108, levels 2
other random_maps/*.h3m -> H3M start offset 43, version 28
```

Parser must detect the H3M start offset instead of assuming `0`.

### H3M Template and Object Parsing

Use the VCMI source as the reference:

- `lib/mapping/MapFormatH3M.cpp`
- `lib/mapping/MapReaderH3M.cpp`
- `lib/mapObjects/ObjectTemplate.cpp`

Object template entry format after reaching the template table:

```text
u32 name_len
bytes name
6 bytes block mask
6 bytes visit mask
u16 unknown/skip
u16 terrain mask
u32 object_id
u32 subid
u8 object type
u8 print priority
16 bytes skip
```

Object table starts with:

```text
u32 object_count
```

Each object starts with:

```text
u8 x
u8 y
u8 z
u32 template_index
5 bytes skip
```

For monster objects in SoD/AB maps, the type-specific payload starts with:

```text
u32 identifier
u16 count
i8 character
u8 has_message
...
```

If `has_message == 0`, the observed simple payload continues with:

```text
u8 never_flees
u8 not_growing_team
2 bytes zero
```

Do not rely on ad hoc byte scanning as the final implementation. It was useful
for research, but production code should parse sequentially according to the
format so object order and object IDs stay meaningful.

### Creature Mapping

Do not blindly map `.h3m` monster `subid` to `battle_estimator.CREATURES[subid]`.

Some entries match, for example:

```text
AVWgrem0.def -> Gremlin
AVWgrex0.def -> Master Gremlin
AVWgnll0.def -> Gnoll
```

But some `.h3m`/VCMI IDs are shifted relative to the current
`battle_estimator.py` creature list. Example:

```text
AvWDFly.def has subid 104 in the observed H3M template table,
but CREATURES[104] is Basilisk in battle_estimator.py.
```

MVP should map neutral targets by DEF/template name or an explicit H3M-to-
estimator mapping table. Unknown DEF names must be reported clearly and skipped
or marked unsupported; they must not silently use the wrong creature.

### Hero Position

Current live hero position is available in the XOR `0x01` hero struct already
used for army parsing.

Given a detected hero name offset:

```text
position_offset = name_offset - 194
decode 5 bytes with XOR key 0x01
x = u16 decoded[0:2]
y = u16 decoded[2:4]
z = u8 decoded[4]
```

Verified controls:

- `pre_move.GM1`: Isra `(54,70,1)`
- `post_move.GM1`: Isra `(55,70,1)` after one move east
- `post_attack_2.GM1`: Isra `(39,69,1)`
- `post_attack_4.GM1`: Isra `(39,74,1)`
- `415.GM2`: Isra `(40,87,1)`

### Removed Neutral Filtering

The `.h3m` map is static and still contains monsters that have already been
killed in the current save. Removed neutral monsters must be filtered by
default.

Research found late save records that identify killed monster object IDs and
creature subids. Examples:

```text
post_attack.GM1:   object #2556, subid 104
post_attack_2.GM1: object #2393, subid 98
post_attack_3.GM1: object #2331, subid 28
post_attack_4.GM1: object #2330, subid 29
```

Recommended MVP approach:

1. Parse the save's compact object table when available.
2. Detect removed/killed monster object IDs from the late save log heuristic.
3. Match removed save objects back to `.h3m` neutral objects by stable
   `x,y,z,subid` where needed.
4. Exclude matched removed neutrals unless `--include-removed` is set.

Do not assume the research byte-scan index from `.h3m` is the same as the save
object ID unless a proper sequential H3M parser proves it.

### Output Requirements

The scan output should be compact and rank-oriented, not the full verbose
single-battle report repeated for every target.

Suggested columns:

```text
d  type     pos          target/army                 enemy_ai  win%  note
1  neutral  (39,70,1)   37x Gnoll                      2072  99.0
5  neutral  (40,73,1)   32x Master Gremlin             2112  98.4
8  hero     (47,70,1)   Marius, 22 creatures           1536  97.1  army-only
```

Full per-target analysis can be added later, but MVP should keep the ranking
readable.

## Dependency Graph

```text
Phase 2 Nearby Scan

  H3M foundation:
    NS-T01 [H3M Format Contracts]
      -> NS-T02 [H3M Monster Parser]
      -> NS-T03 [H3M Map Auto-Detection]

  Save foundation:
    NS-T04 [Hero Position Parsing]
      -> NS-T05 [Other Hero Target Extraction]
    NS-T06 [Removed Neutral Detection]

  Target model:
    NS-T02, NS-T03, NS-T04, NS-T05, NS-T06
      -> NS-T07 [Nearby Target Scan Service]

  Estimation + CLI:
    NS-T07 -> NS-T08 [Per-Target Estimation Runner]
    NS-T08 -> NS-T09 [CLI Output and Arguments]

  Quality:
    NS-T01..NS-T09 -> NS-T10 [Documentation and Verification Pass]
```

**Parallelism:** NS-T01/NS-T02 and NS-T04/NS-T05 can be developed in parallel
after agreeing on the target dataclasses. NS-T06 can be explored in parallel
but should integrate only after the scan service has a clear neutral target
identity model.

---

## Task Definitions

### NS-T01: H3M Format Contracts

| Field | Value |
|---|---|
| Description | Add parser contracts for H3M maps: loaded map bytes, H3M start offset, map header summary, object templates, map objects, and neutral monsters. This task defines data shapes only; parsing can be minimal smoke-level. |
| Blocked By | -- |
| Wave | foundation |
| Execution | Main or Worker |
| Effort | S |
| Scope | Parser |

**Files likely touched:**
- `tools/h3_save_parser.py` or new `tools/h3_map_parser.py`
- `tests/test_h3_save_parser.py` or new `tests/test_h3_map_parser.py`

**Acceptance Criteria:**
1. Data classes exist for H3M map metadata, object templates, map objects, and neutral monster targets.
2. The parser can decompress gzip `.h3m` bytes.
3. The parser can detect a valid H3M start offset at either `0` or `43`.
4. Invalid/unsupported map files raise path-aware errors.

**Verification:**
1. Unit test for a synthetic H3M-like byte stream at offset `0`.
2. Unit test for a synthetic H3M-like byte stream with a prefix before the format ID.
3. Import smoke test for `battle_estimator.py --help`.

**Completion Notes (2026-05-19):**
- Added `tools/h3_map_parser.py` with H3M map/header/template/object/neutral
  target contracts plus a gzip loader for RoE/AB/SoD smoke-level metadata.
- Added `tests/test_h3_map_parser.py` for offset `0`, offset `43`,
  path-aware errors, and `battle_estimator.py --help` import smoke.
- Verified with `python3 -m unittest tests.test_h3_map_parser`,
  `python3 -m unittest tests.test_h3_save_parser`, and
  `python3 tools/battle_estimator.py --help`.

---

### NS-T02: H3M Neutral Monster Parser

| Field | Value |
|---|---|
| Description | Parse enough of SoD `.h3m` to read object templates and neutral monster objects with position, DEF/template name, subid, and count. This should be sequential parsing, not byte-pattern scanning. |
| Blocked By | NS-T01 |
| Wave | h3m |
| Execution | Main or Worker |
| Effort | M |
| Scope | Parser |

**Files likely touched:**
- `tools/h3_map_parser.py` or `tools/h3_save_parser.py`
- `tests/test_h3_map_parser.py` or `tests/test_h3_save_parser.py`

**Acceptance Criteria:**
1. Parser reaches the object template table for SoD maps.
2. Parser reads object templates using the VCMI template layout.
3. Parser reads neutral monster object payloads and exact counts.
4. Creature mapping is DEF/template-name based or uses an explicit H3M-to-
   estimator mapping table.
5. Unknown neutral creature templates are not silently mapped to the wrong
   `CREATURES` index.

**Verification:**
1. Synthetic parser test for one monster template and one monster object.
2. Manual local check on Diamond `.h3m` finds:
   - `(39,70,1)`: `37x Gnoll`
   - `(39,75,1)`: `47x Gremlin`
   - `(40,73,1)`: `32x Master Gremlin`

**Completion Notes (2026-05-19):**
- Extended `tools/h3_map_parser.py` with sequential SoD H3M section skipping,
  object template parsing, object table parsing, and neutral monster target
  extraction.
- Added DEF-name-based mapping for the observed neutral targets; unknown DEF
  names remain unsupported instead of falling back to `CREATURES[subid]`.
- Verified with `python3 -m unittest tests.test_h3_map_parser`,
  `python3 -m unittest tests.test_h3_save_parser`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and
  `python3 -m unittest discover -s tests`.
- Manual Diamond check found `37x Gnoll` at `(39,70,1)`, `47x Gremlin` at
  `(39,75,1)`, and `32x Master Gremlin` at `(40,73,1)`.

---

### NS-T03: H3M Map Auto-Detection

| Field | Value |
|---|---|
| Description | Resolve the matching `.h3m` map for the selected autosave folder. Add an explicit `--map-file` override for cases where auto-detection fails. |
| Blocked By | NS-T01 |
| Wave | h3m |
| Execution | Main or Worker |
| Effort | S |
| Scope | Parser/CLI |

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tools/battle_estimator.py`
- CLI tests

**Acceptance Criteria:**
1. `--map-file PATH` selects an explicit `.h3m` file and validates it is a file.
2. Without `--map-file`, the resolver searches `HoMM 3 Complete/random_maps`.
3. The resolver matches the autosave folder map name and date closely enough
   for the observed `Diamond` case.
4. Failure reports a clear message and suggests `--map-file`.

**Verification:**
1. Unit test with temporary autosave and random_maps directories.
2. Manual local check maps `2026.04.26 20;45 Diamond` to
   `PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m`.

**Completion Notes (2026-05-19):**
- Added `h3_map_parser.resolve_h3m_map()` with explicit `.h3m` validation,
  `random_maps` discovery, timestamp/template matching, and clear
  `--map-file` hints on selection failures.
- Added `--map-file` to `tools/battle_estimator.py`; autosave CLI flows now
  resolve and print `Plik mapy` when available, and warn clearly when
  auto-detection fails.
- Verified with `python3 -m unittest tests.test_h3_map_parser`,
  `python3 -m unittest tests.test_battle_estimator_cli`,
  `python3 -m unittest tests.test_h3_save_parser`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and
  `python3 -m unittest discover -s tests`.
- Manual Diamond check resolved `2026.04.26 20;45 Diamond` to
  `PlayerOne,PlayerTwo 2026.04.26 18;45 Diamond.h3m`.

---

### NS-T04: Hero Position Parsing

| Field | Value |
|---|---|
| Description | Extend hero parsing to expose current hero position from the XOR `0x01` hero struct. The same position data will be used for selected hero and other hero targets. |
| Blocked By | Phase 1 parser |
| Wave | save |
| Execution | Main or Worker |
| Effort | S |
| Scope | Parser |

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`

**Acceptance Criteria:**
1. `HeroArmy` or an associated structure exposes `x,y,z` when present.
2. Position parsing uses `name_offset - 194` and XOR key `0x01`.
3. Invalid position windows fail safely without rejecting otherwise valid
   army parsing unless position is required by the caller.
4. Existing hero army parsing tests still pass.

**Verification:**
1. Synthetic test with encoded position.
2. Manual local check:
   `pre_move.GM1` Isra `(54,70,1)` and `post_move.GM1` Isra `(55,70,1)`.

**Completion Notes (2026-05-19):**
- Added `HeroPosition`, optional `HeroArmy.position`, and convenience
  `x/y/z` accessors.
- Position parsing decodes the `name_offset - 194` window with XOR `0x01`
  and leaves otherwise valid hero-army parsing intact when the position window
  is missing or invalid.
- Verified with `python3 -m unittest tests.test_h3_save_parser`,
  `python3 -m unittest tests.test_battle_estimator_cli`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and
  `python3 -m unittest discover -s tests`.
- Manual local check found Isra at `(54,70,1)` in `pre_move.GM1` and
  `(55,70,1)` in `post_move.GM1`.

---

### NS-T05: Other Hero Target Extraction

| Field | Value |
|---|---|
| Description | Build target records for other heroes in the save using parsed hero positions and armies. Hero targets are army-only battle-estimator targets. |
| Blocked By | NS-T04 |
| Wave | save |
| Execution | Main or Worker |
| Effort | S |
| Scope | Parser/Scan |

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tools/battle_estimator.py`
- tests

**Acceptance Criteria:**
1. Selected hero is excluded from the other-hero target list.
2. Only heroes with a parsed position and non-empty army are considered.
3. Same-level filtering is available to the scan service.
4. Target summary includes hero name, position, AI value, total creatures, and
   army summary.

**Verification:**
1. Synthetic multi-hero save test.
2. Manual local check lists nearby heroes around a known Isra save.

**Completion Notes (2026-05-19):**
- Added `HeroTarget` records with flat `x/y/z` accessors and delegated
  `ai_value`, `total_creatures`, and `army_summary` properties.
- Added `build_other_hero_targets()` with selected-hero exclusion, non-empty
  army and parsed-position guards, and optional same-level filtering.
- Added a synthetic multi-hero encoded-save test that scans hero windows,
  selects Isra, and extracts same-level other-hero targets.
- Verified with `python3 -m unittest tests.test_h3_save_parser`,
  `python3 -m unittest tests.test_battle_estimator_cli`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and
  `python3 -m unittest discover -s tests`.
- Manual `415.GM2` check selected Isra at `(40,87,1)` and listed 20
  same-level other hero targets with summaries.

---

### NS-T06: Removed Neutral Detection

| Field | Value |
|---|---|
| Description | Detect neutral monster objects that have already been removed in the current save and expose a filter for nearby scans. Include an opt-out debug mode. |
| Blocked By | NS-T02 |
| Wave | save |
| Execution | Main or Worker |
| Effort | M |
| Scope | Parser/Scan |

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tools/h3_map_parser.py` if created
- tests

**Acceptance Criteria:**
1. Save-side removed monster detection identifies known test removals:
   `#2393/subid 98`, `#2331/subid 28`, `#2330/subid 29`.
2. Removed save objects can be matched to H3M neutral targets by stable
   `x,y,z,subid` or proven sequential object ID.
3. Removed neutral targets are excluded by default.
4. `--include-removed` includes them and marks them as removed/debug.

**Verification:**
1. Synthetic test for removed-record heuristic.
2. Manual local checks:
   - after `post_attack_2`, Gnoll target is filtered.
   - after `post_attack_3`, Gremlin target is filtered.
   - after `post_attack_4`, Master Gremlin target is filtered.

---

### NS-T07: Nearby Target Scan Service

| Field | Value |
|---|---|
| Description | Combine selected hero position, H3M neutral targets, other hero targets, removed filtering, same-level filtering, radius filtering, target-type filtering, and distance sorting into one scan service. |
| Blocked By | NS-T02, NS-T03, NS-T04, NS-T05, NS-T06 |
| Wave | scan |
| Execution | Main |
| Effort | M |
| Scope | Scan |

**Files likely touched:**
- `tools/battle_estimator.py`
- `tools/h3_save_parser.py`
- `tools/h3_map_parser.py` if created
- tests

**Acceptance Criteria:**
1. Scan includes only targets with `target.z == selected_hero.z`.
2. Radius uses Manhattan distance.
3. Results sort by distance first, then stable tie-breakers.
4. `target_type=all` includes neutrals and heroes.
5. `target_type=neutral` includes only neutral monsters.
6. `target_type=hero` includes only other heroes.

**Verification:**
1. Unit test with synthetic selected hero, neutral targets, and hero targets.
2. Manual local check around `post_attack_2.GM1` radius 10 includes known
   nearby neutral targets in distance order.

---

### NS-T08: Per-Target Estimation Runner

| Field | Value |
|---|---|
| Description | Run compact Monte Carlo battle estimation for every nearby target. This should reuse existing simulation functions without printing the full single-target report repeatedly. |
| Blocked By | NS-T07 |
| Wave | estimate |
| Execution | Main |
| Effort | M |
| Scope | Estimator |

**Files likely touched:**
- `tools/battle_estimator.py`
- tests

**Acceptance Criteria:**
1. Neutral targets are estimated as one enemy stack: mapped creature plus count.
2. Hero targets are estimated as the target hero's parsed army.
3. Scan mode uses a scan-specific default simulation count, for example 500.
4. Existing `--simulations` can override the scan simulation count.
5. Estimation errors for one target do not crash the whole scan; unsupported
   targets are reported with a clear note.

**Verification:**
1. Unit test with deterministic monkeypatched `run_simulations`.
2. CLI smoke test confirms every listed target has a `win%` or an unsupported
   note.

---

### NS-T09: CLI Output and Arguments

| Field | Value |
|---|---|
| Description | Add the user-facing CLI for nearby scans: arguments, validation, compact table output, and error handling. |
| Blocked By | NS-T08 |
| Wave | cli |
| Execution | Main |
| Effort | M |
| Scope | CLI |

**Files likely touched:**
- `tools/battle_estimator.py`
- `tests/test_battle_estimator_cli.py`

**Acceptance Criteria:**
1. Adds `--scan-nearby RADIUS`.
2. Adds `--target-type all|neutral|hero` with default `all`.
3. Adds `--map-file PATH`.
4. Adds `--include-removed`.
5. Output shows selected save, selected map, selected hero position, scan
   radius, target filter, and simulation count.
6. Output table includes distance, target type, position, target army/name,
   enemy AI value, win percentage, and notes.

**Verification:**
1. CLI tests for argument parsing and target-type validation.
2. CLI tests for compact output using synthetic fixtures.
3. Manual local command:
   `python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra --save-file ".../post_attack_2.GM1" --map-file ".../Diamond.h3m"`.

---

### NS-T10: Documentation and Verification Pass

| Field | Value |
|---|---|
| Description | Update docs/checkpoints with the implemented scan behavior, limitations, and examples. Run the focused and broad test suite relevant to this tool. |
| Blocked By | NS-T09 |
| Wave | quality |
| Execution | Main or Worker |
| Effort | S |
| Scope | Docs/Tests |

**Files likely touched:**
- `planning/phase-2-battle-estimator-nearby-scan-tasks.md`
- `planning/battle-estimator-autosave-brief.md`
- `tools/battle_estimator_save_parsing_checkpoint.md`

**Acceptance Criteria:**
1. User-facing examples include nearby scan commands.
2. Known limitations are documented:
   `.h3m` base counts, no full pathfinding, same `z` only, army-only hero
   estimates, and neutral split/upgraded composition limitations.
3. Summary Table statuses are current.
4. Local real-file verification commands are recorded when used, without
   committing real save/map files.

**Verification:**
1. Run focused parser tests.
2. Run focused CLI tests.
3. Run `python3 tools/battle_estimator.py --help`.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Wrong creature mapping from `.h3m` subid to estimator creature | High | Map by DEF/template name or explicit mapping; never silently use `CREATURES[subid]` for unknown/shifted entries. |
| Static `.h3m` contains killed monsters | High | Filter using save removed-object heuristic by default; add `--include-removed` for debugging. |
| H3M random map prefix differs across generated maps | Medium | Detect H3M start offset by validating known format IDs and plausible header fields. |
| H3M sequential parser is incomplete for some object types before monsters | Medium | Follow VCMI `MapFormatH3M.cpp`; keep parser scoped but sequential. Add clear unsupported errors. |
| Scan becomes slow with many targets | Medium | Use scan-specific lower default simulations, configurable with `--simulations`. |
| Hero-vs-hero estimate overstates accuracy | Medium | Mark hero target estimates as `army-only`; keep advanced hero modeling out of MVP. |
| Manhattan distance ignores obstacles and movement points | Low | Document as MVP behavior; pathfinding can be Phase 3. |

## Non-Goals

- Full adventure map pathfinding.
- Cross-level scanning between surface and underground.
- Modeling hero stats, skills, artifacts, spells, morale, luck, tactics, or
  terrain.
- Exact neutral split/upgraded composition reconstruction.
- GUI.
- General multi-install or multi-player-folder discovery.

## Open Questions

No blocking product questions remain from the 2026-05-19 `grill-me` session.
Implementation may still uncover parser-specific questions, especially around
H3M-to-save object identity.

## Summary Table

| Task | Status | Blocked By | Owner | Notes |
|---|---|---|---|---|
| NS-T01: H3M Format Contracts | done | -- | Codex | H3M contracts and smoke loader implemented. |
| NS-T02: H3M Neutral Monster Parser | done | NS-T01 | Codex | Sequential H3M neutral parser implemented. |
| NS-T03: H3M Map Auto-Detection | done | NS-T01 | Codex | Map-file override and random_maps resolver implemented. |
| NS-T04: Hero Position Parsing | done | -- | Codex | Hero x,y,z parsing implemented. |
| NS-T05: Other Hero Target Extraction | done | NS-T04 | Codex | Other-hero target records implemented. |
| NS-T06: Removed Neutral Detection | todo | NS-T02 | unassigned | Needs neutral identity model. |
| NS-T07: Nearby Target Scan Service | blocked | NS-T02, NS-T03, NS-T04, NS-T05, NS-T06 | unassigned | Combines all inputs. |
| NS-T08: Per-Target Estimation Runner | blocked | NS-T07 | unassigned | Compact scan estimates. |
| NS-T09: CLI Output and Arguments | blocked | NS-T08 | unassigned | User-facing scan command. |
| NS-T10: Documentation and Verification Pass | blocked | NS-T09 | unassigned | Final docs and tests. |
