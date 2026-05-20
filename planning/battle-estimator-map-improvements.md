# Battle Estimator Map Improvements - Task Breakdown

> **Source**: research and planning discussion on 2026-05-20.
> This plan extends the local battle-estimator GUI with richer static map
> visualization: route-oriented terrain passability, town markers, portal
> markers, and portal destinations.
>
> **Related**:
> [Battle Estimator Autosave Brief](./battle-estimator-autosave-brief.md),
> [Phase 2 Nearby Scan Tasks](./phase-2-battle-estimator-nearby-scan-tasks.md),
> and
> [Phase 3 GUI Tasks](./phase-3-battle-estimator-gui-tasks.md).

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

Improve the map view so it can help the player visually understand routes
across the map:

- show permanent barriers,
- show land that can be walked through,
- show water that can be sailed through,
- show towns as unique markers,
- show portals and subterranean gates as unique markers,
- show portal/gate destination information,
- make target visibility and scan controls easier to use during play.

This is not a full Heroes III pathfinder. It is a pragmatic static route
visualization layer built from the `.h3m` map, combined with the existing save
data for heroes and neutral-monster removal where already available.

## Product Decisions

- The route overlay uses three states:
  - `land`: land route tile,
  - `water`: water/sailing route tile,
  - `blocked`: permanent route barrier.
- Neutral monsters are already represented by markers. Their underlying tile
  should remain route-capable for this overlay.
- Resources and artifacts are not shown as markers in this iteration. Their
  tiles should remain route-capable.
- Heroes stay as dynamic markers from the save. They do not change the static
  route overlay in this iteration.
- Towns are unique markers. They are not treated as normal route transit.
- Portals are unique markers with destination information. Portal movement is
  represented by special edges, not by pretending the map is physically
  connected.
- Water is not a hard barrier. It is shown as a separate route state so sailing
  routes can be visually distinguished from land routes.
- The map target filter and the scan target filter are one control:
  - `both`: show heroes and neutral monsters; scan both,
  - `heroes`: show heroes; scan heroes,
  - `monsters`: show neutral monsters; scan neutrals.
- The scan sort defaults to distance, with an alternate "easiest target" mode.
- Hidden heroes behave like hidden neutral monsters: hidden by default, skipped
  by scan by default, visible only when the global hidden-target toggle is on.
- Right-clicking a hero marker can select that hero as the player's active
  hero. This action is only available from hero markers, not from scan results.
- Scan result hover highlights a marker without moving the map. Clicking a scan
  result may center and activate the target, but should not rerun an individual
  simulation because the scan already contains the estimate.
- Scan result difficulty colors should be drawn as marker borders/rings, not as
  marker fills, so owner/team colors remain visible.
- Roads, movement points, terrain movement cost, fog of war, Fly, Water Walk,
  boats, current town ownership, and exact pathfinding rules are out of scope
  for this iteration.

## Architecture Decisions

### H3M Is The Static Source Of Truth

Use `.h3m` for:

- terrain tiles,
- terrain kind: land, water, rock,
- object templates and their block/visit masks,
- town positions and initial map owner,
- portal objects and static portal topology.

Use `.GM1` / `.GM2` for data that is already save-derived today:

- current heroes,
- hero positions,
- hero armies,
- removed neutral-monster filtering.

Do not attempt save parsing for current town ownership in this iteration. The
town marker can show the initial `.h3m` owner if available, but it must not
claim that this is definitely the current owner after captures.

### Route Layer Contract

Expose route tiles compactly in `/api/state`, separate from markers.

Recommended shape:

```json
{
  "route_layers": [
    [
      "LLLLLBBBBW",
      "LLLLLBBBBW"
    ],
    [
      "BBBBBLLLLL"
    ]
  ]
}
```

Where every string is one `y` row for a level `z`, and every character is one
`x` tile:

```text
L = land
W = water
B = blocked
```

The backend may keep richer debug reasons internally, but the GUI should not
need large per-tile JSON objects for the normal view.

### Object Mask Projection

Follow VCMI's H3M object template interpretation:

- H3M object templates use an 8 x 6 mask.
- A `block_mask` bit value of `0` means blocked.
- A `visit_mask` bit value of `1` means visitable.
- Mask coordinates are projected from object anchor as `anchor - offset`.

Relevant VCMI references:

- `lib/mapping/MapFormatH3M.cpp`
- `lib/mapping/CMap.cpp`
- `lib/mapObjects/ObjectTemplate.cpp`

The first implementation should deliberately keep a small list of route
exceptions:

- neutral monster object IDs: keep route state from underlying terrain,
- resource/artifact/scroll pickups: keep route state from underlying terrain,
- portal markers: keep marker/edge separate from route state,
- town markers: marker separate; do not create normal transit through town.

### Portal Topology

Use the static topology VCMI uses:

- `43` one-way monolith entrance, `subid = channel`,
- `44` one-way monolith exit, `subid = channel`,
- `45` two-way monolith, `subid = channel`,
- `103` subterranean gate.

Rules:

- `43/subid=N` connects to every `44/subid=N`.
- `45/subid=N` connects bidirectionally to other `45/subid=N` objects.
- `103` gates are paired like VCMI: sort surface gates, then pair each surface
  gate with the nearest unassigned underground gate by 2D squared distance.
- If a portal has multiple exits, the UI must show all possible exits instead
  of pretending there is one deterministic destination.

Whirlpools (`111`) are known as a related water teleport object, but they are
not required in this iteration unless encountered during implementation and
cheap to expose with the same portal model.

### Target Visibility And Scan Workflow

Extend the existing hidden-neutral model rather than creating a separate UX for
heroes:

- keep target IDs stable and type-prefixed: `neutral:<object_index>` and
  `hero:<stable-hero-id>`,
- persist hidden heroes per map key, like hidden neutral targets,
- keep one visible "show hidden" toggle for all hidden target types,
- omit hidden targets from scan unless "show hidden" is enabled.

The current scan target type control should be replaced by the map target
filter. The backend may still translate the selected filter into the existing
`target_type` values internally, but the user should not need to manage two
separate filters.

Scan sorting should be represented as an explicit control independent from the
map target filter. Recommended values:

```text
distance = lowest tile distance first, then stable target ID
easiest = highest win percentage first, then lower distance, then stable target ID
```

If future estimates expose better loss/risk data, `easiest` can be refined, but
the first implementation should use fields already present in scan results.

## Task 1: Parse Terrain Tiles From H3M

**Description:** Replace the current terrain skip with terrain parsing in
`h3_map_parser`. Store the terrain type, terrain view, river, river direction,
road, road direction, and ext flags for every `(x, y, z)` tile.

**Acceptance criteria:**
- [ ] `LoadedH3Map` exposes terrain data when `parse_objects=True`.
- [ ] Parsed terrain count equals `map_size * map_size * levels`.
- [ ] Existing neutral-monster parsing behavior is unchanged.

**Verification:**
- [ ] Add or update parser tests in `tests/test_h3_map_parser.py`.
- [ ] Run `python3 -m unittest tests.test_h3_map_parser`.

**Completion Notes (2026-05-20):**
- Added `H3TerrainTile` records and `LoadedH3Map.terrain_tiles` for
  `parse_objects=True`.
- Replaced the terrain byte skip with VCMI-order `[z][y][x]` terrain parsing
  for terrain type, terrain view, river, river direction, road, road direction,
  and ext flags.
- Kept neutral-monster parsing behavior covered through the existing sequential
  object tests and direct `parse_h3m_neutral_monsters` coverage.
- Verification: `python3 -m unittest tests.test_h3_map_parser` and
  `python3 -m unittest`.

**Dependencies:** None

**Files likely touched:**
- `tools/h3_map_parser.py`
- `tests/test_h3_map_parser.py`

**Estimated scope:** Medium

## Task 2: Build The Static Route Layer

**Description:** Build a route layer from terrain and projected object masks.
The layer should classify each tile as `land`, `water`, or `blocked` according
to the simplified route-visualization semantics.

**Acceptance criteria:**
- [ ] Rock terrain is classified as `blocked`.
- [ ] Water terrain is classified as `water` unless permanently blocked by an
      object.
- [ ] Normal land terrain is classified as `land` unless permanently blocked by
      an object.
- [ ] Neutral monsters, resources, artifacts, and scrolls do not create
      permanent route barriers in this layer.
- [ ] Large object blocking masks create barriers at the expected projected
      positions.

**Verification:**
- [ ] Add unit tests for mask projection and route classification.
- [ ] Run `python3 -m unittest tests.test_h3_map_parser`.

**Completion Notes (2026-05-20):**
- Added `H3RouteTile` records and `LoadedH3Map.route_tiles` for
  `parse_objects=True`.
- Built base route states from parsed terrain: land, water, and rock/blocked.
- Applied VCMI-style projected object block masks, while leaving neutral
  monsters, pickups, scrolls, monoliths, and subterranean gates route-transparent
  for this static overlay.
- Added focused tests for route classification, water blocked by permanent
  objects, exact asymmetric mask projection, and route-transparent object IDs.
- Verification: `python3 -m unittest tests.test_h3_map_parser` and
  `python3 -m unittest`.

**Dependencies:** Task 1

**Files likely touched:**
- `tools/h3_map_parser.py`
- `tests/test_h3_map_parser.py`

**Estimated scope:** Medium

## Task 3: Expose Route Layers In The GUI Snapshot

**Description:** Serialize the static route layer in `GET /api/state` using a
compact level/row string format. Keep this separate from heroes, neutral
targets, towns, and portals.

**Acceptance criteria:**
- [ ] `/api/state` includes `route_layers`.
- [ ] Each level has exactly `map.height` rows.
- [ ] Each row has exactly `map.width` characters.
- [ ] Existing GUI state consumers continue to work if they ignore
      `route_layers`.

**Verification:**
- [ ] Add or update GUI snapshot tests in `tests/test_battle_estimator_gui.py`.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added compact `route_layers` serialization to the GUI state snapshot using
  `L`, `W`, and `B` row strings grouped by level.
- Added internal validation for duplicate, out-of-bounds, missing, or unknown
  route tiles before exposing the snapshot.
- Added snapshot and HTTP `/api/state` tests for route-layer presence,
  dimensions, and multi-level row serialization.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui` and
  `python3 -m unittest`.

**Dependencies:** Task 2

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Small

## Task 4: Render The Route Overlay

**Description:** Draw the route layer under existing markers in the canvas map.
Use a clear but restrained visual distinction between land, water, and blocked
tiles, and provide a toggle to show or hide the overlay.

**Acceptance criteria:**
- [ ] `blocked` tiles are visually distinct from walkable/sailable tiles.
- [ ] `water` tiles are visually distinct from land and blocked tiles.
- [ ] Existing hero and neutral markers remain readable above the overlay.
- [ ] The user can toggle the route overlay without reloading the page.

**Verification:**
- [ ] Manual GUI check on a known Diamond map with both surface and underground
      levels.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added a `Route Overlay` map-toolbar toggle, enabled by default and handled
  entirely client-side without reloading the page.
- Rendered compact `route_layers` under the map grid and existing markers with
  distinct restrained styles for land, water, and blocked route tiles.
- Added frontend smoke coverage for route helpers, canvas overlay drawing, and
  toggling overlay off/on without additional fetches.
- Manual GUI check: started the local GUI on the configured Diamond game
  (`2026.05.19 20;00 Diamond`) with the resolved map
  `PlayerOne,PlayerTwo 2026.05.19 18;00 Diamond.h3m`; verified a 108 x 108 x 2
  map, route chars `B/L/W`, route overlay canvas changes on both level 0 and
  level 1 when toggled, levels render differently, and hero/neutral marker
  pixels remain present above the overlay.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui` and
  `python3 -m unittest`.

**Dependencies:** Task 3

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 5: Parse Town Targets

**Description:** Parse town objects from `.h3m` instead of only skipping their
payload. Emit town targets with stable IDs, visitable position, object ID,
subid/faction, initial owner, optional custom name, and garrison presence.

**Acceptance criteria:**
- [ ] Object IDs `98` and `77` are recognized as town-like targets.
- [ ] Town marker position uses the visitable tile, not the raw anchor tile.
- [ ] Initial owner is exposed when available, with a clear field name that
      does not imply current save ownership.
- [ ] Existing map parsing remains sequential and does not break later object
      parsing.

**Verification:**
- [ ] Add parser tests for town extraction and town visitable position.
- [ ] Run `python3 -m unittest tests.test_h3_map_parser`.

**Completion Notes (2026-05-20):**
- Added `H3TownTarget` records and `LoadedH3Map.town_targets` for
  `parse_objects=True`.
- Parse town-like object IDs `98` and `77` into separate town targets while
  keeping neutral-monster targets unchanged.
- Project town marker positions from the first VCMI-order visitable mask tile,
  falling back to the raw anchor when no visitable tile is present.
- Exposed stable `object_index`, anchor position, object ID, raw H3M subid,
  concrete-town faction subid, initial owner, optional custom name, and garrison
  presence.
- Added parser tests for SoD town extraction with a later neutral object, random
  towns, RoE town payloads, visitable-position projection, and
  `parse_h3m_neutral_monsters` compatibility.
- Verification: `python3 -m unittest tests.test_h3_map_parser` and
  `python3 -m unittest`.

**Dependencies:** Task 1

**Files likely touched:**
- `tools/h3_map_parser.py`
- `tests/test_h3_map_parser.py`

**Estimated scope:** Medium

## Task 6: Show Town Markers In The GUI

**Description:** Serialize town targets in `/api/state` and render them as a
unique marker type. Towns should be visually distinct from heroes, neutrals,
and portals.

**Acceptance criteria:**
- [ ] `/api/state` includes `town_targets`.
- [ ] Town markers render on the correct map level.
- [ ] Town tooltip includes at least position, faction/subid, and initial
      owner when available.
- [ ] Clicking a town does not run a battle estimate.

**Verification:**
- [ ] Add or update GUI snapshot tests.
- [ ] Manual GUI check on a map with known starting towns.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added `town_targets` to `/api/state`, serialized from H3M town targets with
  stable `town:<object_index>` IDs, visitable and anchor positions, object ID,
  raw subid, faction subid, initial owner, initial owner color name, custom name,
  and garrison presence.
- Rendered town markers on the canvas as a distinct two-part square marker,
  colored by initial owner when known and ordered below heroes/neutrals for
  overlap hit-testing.
- Added town tooltip/target details with position, faction/subid, and explicit
  `Initial owner` wording; random/null town data avoids displaying `null`.
- Blocked town clicks from running battle estimates while still selecting the
  marker and showing details.
- Added GUI/API and frontend smoke tests for town serialization, level filtering,
  overlap priority, random town null handling, tooltip/details text, town drawing,
  and the real canvas click path not posting to `/api/simulate-target`.
- Manual GUI check: started the local GUI against the configured Diamond game
  (`2026.05.19 20;00 Diamond`) and resolved Diamond map; verified a 108 x 108 x 2
  map with 24 towns, level marker counts 13/11, town tooltip/details with
  `Initial owner` and faction/subid, no town click simulation request, and a
  nonblank town marker canvas pixel.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui` and
  `python3 -m unittest`.

**Dependencies:** Task 5

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 7: Parse Portal Targets And Edges

**Description:** Parse monoliths and subterranean gates from `.h3m` and build
portal edges matching VCMI's static channel rules.

**Acceptance criteria:**
- [x] One-way monolith entrances and exits are grouped by `subid`.
- [x] Two-way monoliths are grouped bidirectionally by `subid`.
- [x] Subterranean gates are paired with the nearest opposite-level gate using
      the VCMI-style matching rule.
- [x] Multiple exits are represented as multiple possible destinations.
- [x] Portal targets use stable IDs based on object index.

**Verification:**
- [x] Add parser tests for one-way, two-way, and subterranean gate topology.
- [x] Run `python3 -m unittest tests.test_h3_map_parser`.

**Completion Notes (2026-05-20):**
- Added `H3PortalTarget` and `H3PortalEdge` parser contracts and exposed
  `portal_targets`/`portal_edges` from `LoadedH3Map` when object parsing is
  enabled.
- Parsed one-way monoliths, two-way monoliths, and subterranean gates without
  consuming payload bytes, preserving object stream offsets and existing neutral
  monster parsing compatibility.
- Built stable portal channel keys from object index or H3M subid, with
  directed edges for one-way exits, complete two-way monolith groups, and VCMI-
  style nearest unassigned subterranean gate pairing.
- Added parser tests for multiple one-way exits, two-way channels, impassable
  singleton/missing channels, subterranean tie/order behavior, surface sort
  order, and `z > 1` gate ignoring for pair edges.
- Verification: `python3 -m unittest tests.test_h3_map_parser` and
  `python3 -m unittest`.

**Dependencies:** Task 1

**Files likely touched:**
- `tools/h3_map_parser.py`
- `tests/test_h3_map_parser.py`

**Estimated scope:** Medium

## Task 8: Show Portal Markers And Destinations In The GUI

**Description:** Serialize portal targets and edges in `/api/state`, render
portal markers, and show destination information in tooltip/details. For
cross-level subterranean gates, provide a quick way to center the paired gate.

**Acceptance criteria:**
- [x] `/api/state` includes `portal_targets` and `portal_edges`.
- [x] Portal markers render on the correct map level.
- [x] Tooltip/details show whether the portal is one-way, two-way, or a
      subterranean gate.
- [x] Destination coordinates are shown for all known exits.
- [x] For destinations on another level, the UI can switch level and center the
      destination marker.

**Verification:**
- [x] Add or update GUI snapshot tests.
- [x] Manual GUI check on a Diamond map with monoliths and subterranean gates.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added `portal_targets` and `portal_edges` to `/api/state`, including stable
  `portal:<object_index>` IDs and directed edge source/destination IDs.
- Rendered portal markers on the active map level with distinct styles for
  one-way monoliths, two-way monoliths, and subterranean gates.
- Added portal tooltip/details text with type, role, subid, channel key, and all
  known destination coordinates; malformed destination edges are ignored.
- Added portal context-menu destination actions that switch map level, center the
  destination marker, and update the active marker/details. Portal clicks are
  blocked from battle simulation.
- Added API/frontend tests for portal serialization, level filtering, multiple
  one-way exits, two-way destinations, impassable portals, malformed destination
  edges, hit-test priority, canvas drawing, and real context-menu centering.
- Manual GUI check: Diamond map `PlayerOne,PlayerTwo 2026.05.19 18;00 Diamond.h3m`
  exposed 44 portal targets and 44 portal edges; headless Chrome verified a
  nonblank portal marker pixel, portal click non-simulation, destination menu,
  and cross-level centering from level 0 to level 1.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui` and
  `python3 -m unittest`.

**Dependencies:** Task 7

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 9: End-To-End Map Verification

**Description:** Verify the combined map overlay, town markers, portal markers,
and existing hero/neutral markers on real generated maps.

**Acceptance criteria:**
- [ ] Known towns appear at expected visitable positions.
- [ ] Known monoliths show expected possible exits.
- [ ] Known subterranean gates pair surface and underground positions.
- [ ] Underground rock and object bodies appear as blocked route tiles.
- [ ] Water appears as water route tiles, not as hard blocked terrain.
- [ ] Existing click-to-simulate behavior still works for neutral and hero
      targets.

**Verification:**
- [ ] Run `python3 -m unittest`.
- [ ] Start the GUI and manually inspect at least one current Diamond save/map.

**Dependencies:** Tasks 4, 6, 8

**Files likely touched:**
- No production files expected unless verification finds issues.

**Estimated scope:** Small

## Task 10: Add Hidden Hero Target State

**Description:** Extend hidden-target persistence and snapshot handling so hero
targets can be hidden using the same semantics as neutral monster targets.

**Acceptance criteria:**
- [ ] Hidden hero IDs are persisted per map key.
- [ ] Hidden heroes are omitted from map markers by default.
- [ ] Hidden heroes are omitted from scan results by default.
- [ ] The existing "show hidden" behavior includes both hidden neutrals and
      hidden heroes.
- [ ] Hidden neutral behavior remains backward compatible.

**Verification:**
- [ ] Add or update config and GUI snapshot tests.
- [ ] Run `python3 -m unittest tests.test_h3_save_parser tests.test_battle_estimator_gui`.

**Dependencies:** None

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tools/battle_estimator_gui.py`
- `tests/test_h3_save_parser.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 11: Add Hero Marker Context Actions

**Description:** Extend the map marker context menu for hero markers. Right
clicking a hero marker should allow selecting that hero as the active player
hero and hiding/restoring that hero.

**Acceptance criteria:**
- [ ] Right-clicking a hero marker opens a context menu.
- [ ] The menu includes "Select as my hero" for hero markers.
- [ ] The menu includes hide/restore actions for hero markers.
- [ ] Selecting a hero from the context menu updates recent heroes and the
      selected hero state.
- [ ] Context actions for neutral monsters still work.

**Verification:**
- [ ] Add or update GUI tests where practical.
- [ ] Manual GUI check: right-click a hero marker, select it, hide it, and
      restore it with show-hidden enabled.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 10

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 12: Merge Map Filter And Scan Target Type

**Description:** Replace the separate scan target type control with one map
target filter that controls both visible target markers and scan target type.

**Acceptance criteria:**
- [ ] The default filter is `both`.
- [ ] `both` shows heroes and neutral monsters and scans both target types.
- [ ] `heroes` shows heroes and scans only hero targets.
- [ ] `monsters` shows neutral monsters and scans only neutral targets.
- [ ] The old scan target type UI is removed or hidden.
- [ ] Hidden targets are still excluded unless show-hidden is enabled.

**Verification:**
- [ ] Add or update GUI state and scan request tests.
- [ ] Manual GUI check all three filter modes.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui tests.test_nearby_scan`.

**Dependencies:** None

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`
- `tests/test_nearby_scan.py`

**Estimated scope:** Medium

## Task 13: Add Scan Sort Modes

**Description:** Add a scan sort control with `distance` and `easiest` modes.
Distance remains the default. Easiest should sort by highest `win_pct`, then
lower distance, then stable target ID.

**Acceptance criteria:**
- [ ] Scan results default to distance sorting.
- [ ] The user can switch to easiest-target sorting.
- [ ] Sort mode is preserved when scan results refresh in the current session.
- [ ] Ties are stable and deterministic.

**Verification:**
- [ ] Add JavaScript/unit-style tests if the existing test structure supports
      it, or backend serialization tests if sorting is backend-owned.
- [ ] Manual GUI check with a scan containing multiple targets.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** None

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Small

## Task 14: Improve Scan Result Hover And Click Behavior

**Description:** Make scan-result hover highlight targets without moving the
map, while scan-result click intentionally activates and centers the target
using the existing scan estimate rather than rerunning a single simulation.

**Acceptance criteria:**
- [ ] Hovering a scan result highlights the corresponding map marker.
- [ ] Hovering does not pan, zoom, or center the map.
- [ ] Clicking a scan result centers and activates the target.
- [ ] Clicking a scan result displays the existing scan estimate.
- [ ] Clicking a scan result does not make a redundant `/api/simulate-target`
      request.

**Verification:**
- [ ] Manual GUI check with scan results and visible markers.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** None

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Small

## Task 15: Auto-Refresh Scan After Hero Selection

**Description:** When the user is already working in scan mode, selecting a new
active hero should automatically rerun scan with the current radius, map
filter, and sort mode. Initial hero selection should not start scan unless a
scan has already been run in the current session.

**Acceptance criteria:**
- [ ] Selecting a hero before any scan has run does not trigger scan.
- [ ] Selecting a hero after a scan has run reruns scan automatically.
- [ ] The rerun uses the current radius.
- [ ] The rerun uses the current map filter.
- [ ] The rerun preserves the current scan sort mode.
- [ ] In-flight scan requests are invalidated safely when the selected hero
      changes.

**Verification:**
- [ ] Manual GUI check: run scan, select another hero, confirm results refresh.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Tasks 12, 13

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Small

## Task 16: Render Scan Difficulty As Marker Rings

**Description:** Change scan-result coloring so target identity remains visible.
Owner/team colors and neutral monster colors should stay as marker fill, while
scan difficulty is shown with an outer border or ring.

**Acceptance criteria:**
- [ ] Hero marker fill continues to show owner/team color.
- [ ] Neutral marker fill continues to show the neutral monster color.
- [ ] Scan verdict is rendered as a ring or border.
- [ ] Hover and active marker states remain visible alongside scan rings.
- [ ] Selected hero styling remains distinct.

**Verification:**
- [ ] Manual GUI check after scan with hero and neutral targets.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** None

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`

**Estimated scope:** Small

## Task 17: End-To-End Workflow Verification

**Description:** Verify the combined target visibility, map filter, scan
sorting, scan hover/click behavior, auto scan refresh, and scan-ring rendering
in the local GUI.

**Acceptance criteria:**
- [ ] Hidden heroes and hidden neutrals behave consistently.
- [ ] The single map filter controls both markers and scan target type.
- [ ] Distance and easiest sort modes both work.
- [ ] Scan hover does not move the map.
- [ ] Scan click intentionally centers and activates the target.
- [ ] Auto scan refresh runs only after scan mode has been used.
- [ ] Scan rings preserve team and neutral marker identity colors.

**Verification:**
- [ ] Run `python3 -m unittest`.
- [ ] Start the GUI and manually verify the workflow on a current save.

**Dependencies:** Tasks 10, 11, 12, 13, 14, 15, 16

**Files likely touched:**
- No production files expected unless verification finds issues.

**Estimated scope:** Small

## Checkpoints

### Checkpoint: Route Foundation

After Tasks 1-3:

- [ ] `python3 -m unittest tests.test_h3_map_parser` passes.
- [ ] `python3 -m unittest tests.test_battle_estimator_gui` passes.
- [ ] `/api/state` includes valid compact `route_layers`.

### Checkpoint: Static Markers

After Tasks 5-8:

- [ ] `town_targets`, `portal_targets`, and `portal_edges` exist in
      `/api/state`.
- [ ] Town and portal markers render without breaking existing hero/neutral
      interactions.
- [ ] Portal destinations are inspectable in the GUI.

### Checkpoint: Target And Scan UX

After Tasks 10-17:

- [ ] Hidden heroes follow the same semantics as hidden neutral monsters.
- [ ] The old separate scan target type is gone from the UI.
- [ ] Scan results can be sorted by distance or easiest target.
- [ ] Scan result hover highlights without moving the map.
- [ ] Scan target difficulty is shown as rings/borders without replacing team
      colors.

### Checkpoint: Complete

After Tasks 9 and 17:

- [ ] `python3 -m unittest` passes.
- [ ] Route overlay, water, towns, portals, heroes, and neutrals are all
      visually distinguishable.
- [ ] Manual inspection confirms the tool helps understand route corridors
      across levels.
- [ ] Target hiding, map filtering, scan sorting, scan hover, scan click, auto
      refresh, and scan rings work together in the GUI.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Object mask projection is off by one or mirrored incorrectly. | High | Match VCMI `ObjectTemplate::readMap` and add focused tests around known town/gate positions. |
| Visitables create false route corridors. | Medium | Keep towns and portals as markers/special nodes, and only exempt agreed pickup/fightable objects from permanent blocking. |
| `/api/state` becomes too large. | Medium | Use compact route row strings instead of per-tile objects. |
| Town owner from `.h3m` becomes misleading after captures. | Medium | Name it `initial_owner_*` and avoid current-owner claims until save parsing supports it. |
| Portal with multiple exits is displayed as one deterministic target. | Medium | Model edges as one-to-many and show every possible destination. |
| Water visualization suggests current hero can sail without a boat. | Low | Label it as water/sailing route, not current hero reachability. |
| Hidden hero IDs drift across saves. | Medium | Use the same stable hero IDs already used by the GUI snapshot and filter unknown hidden IDs out when loading config. |
| Merging map and scan filters removes useful flexibility. | Low | Product decision is intentional for simpler play workflow; the backend can still keep internal target-type mapping. |
| Auto scan refresh causes unexpected work. | Medium | Only trigger after the user has already run scan in the current session, and cancel stale in-flight requests. |
| Scan rings make markers visually noisy. | Low | Keep fills as identity colors and use restrained outer rings with hover/active priority. |

## Parallelization Opportunities

- Tasks 5 and 7 can run in parallel after Task 1 because town parsing and portal
  topology are independent.
- Task 4 can run after Task 3 while Tasks 5 and 7 are still in progress.
- Tasks 6 and 8 can run in parallel if the frontend marker changes use
  disjoint sections or coordinate carefully.
- Tasks 10, 12, 13, 14, and 16 are mostly independent GUI workflow
  improvements and can be worked in parallel with the map-static tasks.
- Task 11 should wait for Task 10 because hide/restore hero actions need the
  hidden hero state.
- Task 15 should wait for Tasks 12 and 13 so it can use the final filter and
  sort controls.
- Tasks 9 and 17 are verification tasks and should run after their respective
  feature groups are complete.

## Summary Table

| Task | Title | Status | Blocked By |
| --- | --- | --- | --- |
| 1 | Parse Terrain Tiles From H3M | done | - |
| 2 | Build The Static Route Layer | done | 1 |
| 3 | Expose Route Layers In The GUI Snapshot | done | 2 |
| 4 | Render The Route Overlay | done | 3 |
| 5 | Parse Town Targets | done | 1 |
| 6 | Show Town Markers In The GUI | done | 5 |
| 7 | Parse Portal Targets And Edges | done | 1 |
| 8 | Show Portal Markers And Destinations In The GUI | done | 7 |
| 9 | End-To-End Map Verification | todo | 4, 6, 8 |
| 10 | Add Hidden Hero Target State | todo | - |
| 11 | Add Hero Marker Context Actions | blocked | 10 |
| 12 | Merge Map Filter And Scan Target Type | todo | - |
| 13 | Add Scan Sort Modes | todo | - |
| 14 | Improve Scan Result Hover And Click Behavior | todo | - |
| 15 | Auto-Refresh Scan After Hero Selection | blocked | 12, 13 |
| 16 | Render Scan Difficulty As Marker Rings | todo | - |
| 17 | End-To-End Workflow Verification | blocked | 10, 11, 12, 13, 14, 15, 16 |
