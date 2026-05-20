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
- make target visibility and scan controls easier to use during play,
- find strategic land routes from the selected hero to clicked map tiles using
  portals and subterranean gates.

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
- Pathfinding MVP is land-only: it can use land route tiles plus portal and
  subterranean-gate edges, but it does not route over water.
- Neutral monsters are route-passable for pathfinding in this iteration. A
  later iteration can run battle estimates for required blockers.
- Towns and ordinary visitable objects are terminals, not transit corridors.
  The route may end at their target tile, but should not use them as ordinary
  intermediate path nodes.
- Pathfinding is started from a GUI `Path mode`; in that mode, marker clicks
  request a route instead of running battle simulation.
- Pathfinding optimizes for the fewest tile steps, not movement points, terrain
  movement cost, or roads.
- Multi-exit portals are treated as possible edges and must be marked as
  non-deterministic when used in a returned route.
- If the clicked tile is blocked, the pathfinder should route to the nearest
  reachable neighboring tile and report that fallback in the result.
- Cross-level paths are shown as per-level route segments. The GUI should not
  automatically switch levels after calculating a path; segment selection can
  switch level and center the relevant fragment.
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

### Pathfinding MVP

The pathfinding feature should build on the already parsed static map data:

- `route_layers` for land/water/blocked tile state,
- `portal_targets` for portal marker positions,
- `portal_edges` for directed static portal traversal.

Use a simple uniform-cost shortest-path search for MVP. Breadth-first search is
acceptable because every normal tile step and every portal jump is treated as
one step. A* is also acceptable if implemented cleanly, but it is not required.

Path graph rules:

- node identity is `(x, y, z)`,
- normal edges connect 8-directional neighboring `land` tiles on the same
  level,
- `water` tiles are not connected in the MVP,
- `blocked` tiles are not connected,
- neutral monster positions remain traversable because the existing route layer
  treats them as route-capable,
- portal edges connect source portal tile to destination portal tile using the
  serialized `portal_edges`,
- one-way portal edges remain one-way,
- two-way monoliths and subterranean gates are represented by directed edges in
  both directions when the parser emits both directions.

Destination rules:

- path mode click on an empty land tile routes to that tile,
- path mode click on a marker routes to that marker's target position,
- path mode click on a blocked tile routes to the nearest reachable neighbor
  and includes a fallback note,
- path mode click on another map level is allowed; the route can use portal or
  subterranean-gate edges to cross levels.

The returned route should include enough metadata for the GUI to draw both the
visible path and an explanatory segment list:

```json
{
  "status": "found",
  "start": {"x": 10, "y": 20, "z": 0},
  "requested_target": {"x": 50, "y": 60, "z": 1},
  "resolved_target": {"x": 49, "y": 60, "z": 1},
  "target_fallback": "nearest_reachable_neighbor",
  "path": [
    {"x": 10, "y": 20, "z": 0},
    {"x": 11, "y": 21, "z": 0}
  ],
  "segments": [
    {"type": "walk", "z": 0, "from_index": 0, "to_index": 12},
    {"type": "portal", "from_index": 12, "to_index": 13, "non_deterministic": false},
    {"type": "walk", "z": 1, "from_index": 13, "to_index": 24}
  ]
}
```

The exact JSON can change during implementation, but it must preserve these
concepts: status, requested/resolved target, path coordinates, segment
metadata, and non-deterministic portal flag.

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
- [x] Known towns appear at expected visitable positions.
- [x] Known monoliths show expected possible exits.
- [x] Known subterranean gates pair surface and underground positions.
- [x] Underground rock and object bodies appear as blocked route tiles.
- [x] Water appears as water route tiles, not as hard blocked terrain.
- [x] Existing click-to-simulate behavior still works for neutral and hero
      targets.

**Verification:**
- [x] Run `python3 -m unittest`.
- [x] Start the GUI and manually inspect at least one current Diamond save/map.

**Completion Notes (2026-05-20):**
- Verified the configured Diamond game
  `Games/Random/PlayerTwo/2026.05.19 20;00 Diamond` against resolved map
  `PlayerOne,PlayerTwo 2026.05.19 18;00 Diamond.h3m`.
- H3M/parser facts: 108 x 108 x 2 map, 24 towns, 289 neutral targets,
  44 portal targets, 44 portal edges, and route counts `blocked=7568`,
  `land=7567`, `water=8193`.
- Known town sample `town:2231` appeared at visitable `(45,46,0)` with anchor
  `(47,46,0)`, `Faction/subid: 2/2`, `Initial owner: Blue`, and a nonblank
  marker pixel.
- Known one-way monolith `portal:2349` at `(22,96,0)` showed both expected exits
  `(33,82,0)` and `(82,48,1)`.
- Known subterranean topology included `portal:2282` `(28,5,0)` paired with
  `portal:2281` `(28,5,1)` and reverse edge present; GUI context-menu check on
  visible pair `portal:2292 -> portal:2293` switched from level 0 to level 1 and
  activated the destination marker.
- Route-layer samples: water `(0,0,1)` was `W` with canvas pixel
  `[213,233,245,255]`; rock terrain `(107,107,0)`, object body `(0,0,0)`, and
  underground object body `(43,1,1)` were `B` with blocked canvas pixels.
- Local real-map corpus note: no `.h3m` under the HoMM 3 Complete directory had
  a `terrain_type=rock` tile on `z=1`; added a synthetic two-level H3M check
  where underground rock `(1,0,1)` serialized as route char `B`.
- Click-to-simulate: selected `Coronius` (`hero:731686`) through the GUI, then
  clicked supported neutral `neutral:2289` and enemy hero `hero:740438`; both
  returned estimate results for the clicked target.
- Verification: `python3 -m unittest`; headless Chrome/CDP GUI check on local
  port 8769; synthetic underground-rock route-layer check.

**Dependencies:** Tasks 4, 6, 8

**Files likely touched:**
- No production files expected unless verification finds issues.

**Estimated scope:** Small

## Task 10: Add Hidden Hero Target State

**Description:** Extend hidden-target persistence and snapshot handling so hero
targets can be hidden using the same semantics as neutral monster targets.

**Acceptance criteria:**
- [x] Hidden hero IDs are persisted per map key.
- [x] Hidden heroes are omitted from map markers by default.
- [x] Hidden heroes are omitted from scan results by default.
- [x] The existing "show hidden" behavior includes both hidden neutrals and
      hidden heroes.
- [x] Hidden neutral behavior remains backward compatible.

**Verification:**
- [x] Add or update config and GUI snapshot tests.
- [x] Run `python3 -m unittest tests.test_h3_save_parser tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added `hidden_hero_targets_by_map` config persistence with bounded
  `hero:<stable_id>` normalization, per-map storage, and preservation through
  existing config mutators.
- Added `/api/hidden-target` support for known, non-selected hero targets and
  exposed `hidden_hero_target_ids` plus per-hero `hidden` flags in state
  payloads.
- Kept hidden scan compatibility: hidden neutral and hero targets are omitted
  from scan-radius results even when show-hidden is enabled; direct target
  simulation remains gated by show-hidden.
- Updated the map marker cache and context menu path so hidden hero markers are
  omitted by default, restored by the show-hidden toggle, and non-selected hero
  markers can be hidden/restored.
- Verification: `python3 -m unittest tests.test_h3_save_parser`;
  `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent code review found no
  blocking issues.

**Dependencies:** None

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tests/test_h3_save_parser.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 11: Add Hero Marker Context Actions

**Description:** Extend the map marker context menu for hero markers. Right
clicking a hero marker should allow selecting that hero as the active player
hero and hiding/restoring that hero.

**Acceptance criteria:**
- [x] Right-clicking a hero marker opens a context menu.
- [x] The menu includes "Select as my hero" for hero markers.
- [x] The menu includes hide/restore actions for hero markers.
- [x] Selecting a hero from the context menu updates recent heroes and the
      selected hero state.
- [x] Context actions for neutral monsters still work.

**Verification:**
- [x] Add or update GUI tests where practical.
- [x] Manual GUI check: right-click a hero marker, select it, hide it, and
      restore it with show-hidden enabled.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added hero marker context actions for non-selected heroes: `Select as my
  hero`, `Simulate`, and `Hide`; hidden heroes show `Select as my hero` and
  `Unhide`.
- Selected hero markers now open a context menu with a `Current hero` note and
  no hide/select/simulate action, preserving the Task 10 selected-hero
  invariant.
- Selecting a hero from the context menu reuses `/api/select-hero`, updates
  recent heroes locally, and clears the selected hero from local hidden-target
  state so hidden selected heroes remain visible immediately.
- Automated verification covered neutral context-menu regression, non-selected
  hero selection payload/recent state, selected hero note/no-actions behavior,
  and hidden-hero selection cleanup.
- Manual GUI check: started a local fixture GUI on port 8771 with three heroes,
  used headless Chrome/CDP to right-click `Marius`, select him as active,
  confirm the selected-hero `Current hero` menu, hide `Isra`, show hidden
  targets, and restore `Isra`.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent code review found no
  blocking issues.

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
- [x] The default filter is `both`.
- [x] `both` shows heroes and neutral monsters and scans both target types.
- [x] `heroes` shows heroes and scans only hero targets.
- [x] `monsters` shows neutral monsters and scans only neutral targets.
- [x] The old scan target type UI is removed or hidden.
- [x] Hidden targets are still excluded unless show-hidden is enabled.

**Verification:**
- [x] Add or update GUI state and scan request tests.
- [x] Manual GUI check all three filter modes.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui tests.test_nearby_scan`.

**Completion Notes (2026-05-20):**
- Replaced the scan target type select with a single map toolbar target filter:
  `Both`, `Heroes`, and `Monsters`.
- The filter controls hero/neutral marker visibility and maps scan requests to
  backend `target_type` values `all`, `hero`, and `neutral`; towns and portals
  remain visible as map context markers.
- Filter changes clear stale hover/context/active target state and clear prior
  scan results so old scan rows do not survive a mode change.
- Hidden marker visibility still follows show-hidden; scan omission of hidden
  targets remains the Task 10 backend behavior.
- Manual GUI check: started a local fixture GUI on port 8771, used headless
  Chrome/CDP to click all three filters, confirmed hero/neutral marker
  visibility, and verified scan payloads `all`, `hero`, and `neutral`.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest tests.test_nearby_scan`; `python3 -m unittest`;
  `git diff --check`; subagent code review found no blocking issues.

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
- [x] Scan results default to distance sorting.
- [x] The user can switch to easiest-target sorting.
- [x] Sort mode is preserved when scan results refresh in the current session.
- [x] Ties are stable and deterministic.

**Verification:**
- [x] Add JavaScript/unit-style tests if the existing test structure supports
      it, or backend serialization tests if sorting is backend-owned.
- [x] Manual GUI check with a scan containing multiple targets.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added a scan sort segmented control with `Distance` and `Easiest` modes.
  Distance remains the default; easiest sorts by finite `win_pct` descending,
  then distance ascending, then target ID.
- Scan payloads are stored as `rawResults` and rendered through the current
  sort mode, so changing sort mode reorders existing rows without making a new
  `/api/scan-radius` request.
- `clearScanResults()` and new scan starts preserve the selected sort mode while
  clearing stale result rows and lookup state. The in-flight scan path now clears
  old rows before showing `Running scan...`, preventing stale results from
  reappearing if sort mode changes while a newer request is pending.
- Manual GUI check: started a local fixture GUI on port 8771, used headless
  Chrome/CDP with controlled multi-result scan responses, confirmed Distance and
  Easiest row order, no extra request on sort toggle, preservation after filter
  clear/new scan, and no stale-row redraw during a deferred in-flight scan.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent plan review and code
  review completed, with the stale in-flight-row finding fixed and re-reviewed.

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
- [x] Hovering a scan result highlights the corresponding map marker.
- [x] Hovering does not pan, zoom, or center the map.
- [x] Clicking a scan result centers and activates the target.
- [x] Clicking a scan result displays the existing scan estimate.
- [x] Clicking a scan result does not make a redundant `/api/simulate-target`
      request.

**Verification:**
- [x] Manual GUI check with scan results and visible markers.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added scan result row hover/focus behavior that highlights a currently visible
  target marker via `hoveredMarkerId` without changing map level, zoom, pan,
  active marker, target details, or API state.
- Hover state is cleared when rows are replaced, scan messages are shown, scans
  start, scan results are cleared, map level changes, or the hovered/focused row
  is left/blurred. Focusing a result without a visible marker clears any prior
  scan-row hover.
- Kept scan result click as the intentional activation path: it centers and
  activates the target, then renders the estimate already present in the scan
  result without making a `/api/simulate-target` request.
- Manual GUI check: started a local fixture GUI on port 8771, used headless
  Chrome/CDP with a controlled scan response containing visible `neutral:0`,
  confirmed hover highlight/no movement/no API side effects, non-visible focus
  cleanup, leave cleanup, click activation, and estimate rendering from scan
  data with zero simulate-target requests.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent plan and code reviews
  completed with no blocking findings after lifecycle cleanup adjustments.

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
- [x] Selecting a hero before any scan has run does not trigger scan.
- [x] Selecting a hero after a scan has run reruns scan automatically.
- [x] The rerun uses the current radius.
- [x] The rerun uses the current map filter.
- [x] The rerun preserves the current scan sort mode.
- [x] In-flight scan requests are invalidated safely when the selected hero
      changes.

**Verification:**
- [x] Manual GUI check: run scan, select another hero, confirm results refresh.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Added session scan state tracking so valid scan starts enable future
  hero-selection auto-refresh, while ordinary scan clearing keeps both the
  auto-refresh flag and the current sort mode.
- Selecting a different hero after a scan now clears/increments scan request
  state to invalidate stale responses, then starts a replacement scan with the
  current radius input and current map target filter. Selecting a hero before
  any scan, or reselecting the same active hero, does not auto-run scan.
- Existing scan freshness checks reject old in-flight scan responses after hero
  selection; the replacement scan result remains rendered.
- Manual GUI check: started a local fixture GUI on port 8771, used headless
  Chrome/CDP with controlled scan responses, ran a `radius=7` hero-filter scan,
  selected another hero from the hero list, and confirmed the automatic refresh
  used the new hero ID, same radius/filter, preserved `Easiest` sort, and
  rendered rows for the new hero.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent plan and code reviews
  completed with no blocking findings.

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
- [x] Hero marker fill continues to show owner/team color.
- [x] Neutral marker fill continues to show the neutral monster color.
- [x] Scan verdict is rendered as a ring or border.
- [x] Hover and active marker states remain visible alongside scan rings.
- [x] Selected hero styling remains distinct.

**Verification:**
- [x] Manual GUI check after scan with hero and neutral targets.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion Notes (2026-05-20):**
- Changed scan difficulty rendering from marker body colors to outer marker
  rings. Hero bodies keep selected/owner colors, and neutral bodies keep their
  existing neutral/hidden/unsupported/removed identity colors.
- Scan rings draw after marker bodies with the scan verdict stroke color, while
  hover and active rings draw outside scan rings so both states remain visible.
  Selected hero markers still skip scan coloring.
- Moved z-level labels farther out when a scan ring exists to avoid ring
  overlap.
- Manual GUI check: started a local GUI on port 8771, used headless Chrome/CDP
  with controlled state and scan responses, wrapped the real canvas context, and
  confirmed hero owner fill, neutral fill, absence of scan fill in marker
  bodies, strong/risky scan rings, and separate hover/active rings.
- Verification: `python3 -m unittest tests.test_battle_estimator_gui`;
  `python3 -m unittest`; `git diff --check`; subagent plan and code reviews
  completed with no blocking findings.

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
- [x] Hidden heroes and hidden neutrals behave consistently.
- [x] The single map filter controls both markers and scan target type.
- [x] Distance and easiest sort modes both work.
- [x] Scan hover does not move the map.
- [x] Scan click intentionally centers and activates the target.
- [x] Auto scan refresh runs only after scan mode has been used.
- [x] Scan rings preserve team and neutral marker identity colors.

**Verification:**
- [x] Run `python3 -m unittest`.
- [x] Start the GUI and manually verify the workflow on a current save.

**Completion notes:**
- Full suite passed: `python3 -m unittest` (`Ran 226 tests in 22.625s OK`).
- Real backend fixture smoke used a temporary GUI server with real fixture save
  and map data, with no mocks for `/api/state`, `/api/hidden-target`,
  `/api/show-hidden`, or `/api/scan-radius`. It confirmed hidden heroes and
  hidden neutrals are exposed by the hidden-target toggle, are omitted from scan
  results, and that the Heroes/Monsters map filter constrains marker visibility.
  The full GUI test suite additionally covers default hidden-marker visibility
  and scan target-type request mapping.
- Deterministic browser workflow verified no scan before scan mode use,
  Distance and Easiest result ordering, no extra request on sort change,
  hover without map movement, click activation, auto-refresh after hero
  selection with radius/filter/sort preserved, and canvas rendering for team
  fills, neutral fills, scan difficulty rings, hover rings, and active rings.
- Verification: `python3 -m unittest`; real-backend GUI smoke via Chrome DevTools
  Protocol; deterministic browser workflow via Chrome DevTools Protocol;
  `git diff --check`; subagent plan and evidence reviews.

**Dependencies:** Tasks 10, 11, 12, 13, 14, 15, 16

**Files likely touched:**
- No production files expected unless verification finds issues.

**Estimated scope:** Small

## Task 18: Add Pathfinding Service Contract

**Description:** Define backend dataclasses/helpers for pathfinding requests,
results, path steps, and path segments. Keep this separate from the HTTP
endpoint so the core pathfinder can be tested without the GUI server.

**Acceptance criteria:**
- [ ] The service accepts selected hero position, requested target position,
      route layers, and portal edges.
- [ ] Result states include at least `found`, `not_found`, and `invalid`.
- [ ] Results can represent requested vs resolved target positions.
- [ ] Results can represent walk segments and portal segments.
- [ ] Portal segments can mark non-deterministic traversal.

**Verification:**
- [ ] Add focused service-contract tests.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Tasks 3, 8

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Small

## Task 19: Implement Land-Only Shortest Path Search

**Description:** Implement the first pathfinding pass over static `route_layers`
without portal traversal. Use uniform-cost shortest path over 8-directional
land neighbors and ignore water, blocked tiles, roads, and movement points.

**Acceptance criteria:**
- [ ] Search starts from the selected hero's current `(x, y, z)`.
- [ ] Normal movement uses 8-directional neighboring `land` tiles.
- [ ] `water` and `blocked` tiles are not traversed.
- [ ] The returned path is the shortest path by number of graph steps.
- [ ] No path is returned when the target is unreachable on land.

**Verification:**
- [ ] Add tests for reachable, unreachable, diagonal, water, and blocked cases.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 18

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 20: Add Portal And Subterranean Gate Traversal

**Description:** Extend the pathfinding graph with directed portal edges from
`portal_edges`, including one-way monoliths, two-way monoliths, and
subterranean gates.

**Acceptance criteria:**
- [ ] Portal edges can connect different coordinates on the same level.
- [ ] Portal edges can connect coordinates across levels.
- [ ] One-way portal edges are not traversed backwards unless the parser emits
      a reverse edge.
- [ ] Multi-exit portal choices are represented as separate possible edges.
- [ ] A returned path identifies portal segments and marks
      `non_deterministic` when the used source has multiple possible exits.

**Verification:**
- [ ] Add tests for one-way, two-way, cross-level, and multi-exit routes.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 19

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 21: Resolve Blocked Targets And Terminal Markers

**Description:** Add destination resolution rules for path mode: route to marker
target positions, allow a terminal destination without treating it as a transit
node, and fall back from blocked clicked tiles to the nearest reachable
neighbor.

**Acceptance criteria:**
- [ ] Clicking a land tile routes to that tile.
- [ ] Clicking a hero, neutral, town, or portal marker routes to that marker's
      position in path mode.
- [ ] Towns and ordinary terminal targets can be final destinations but are not
      used as ordinary intermediate path nodes.
- [ ] Clicking a blocked tile resolves to the nearest reachable neighboring
      tile when one exists.
- [ ] The result reports the fallback when the resolved target differs from the
      requested target.

**Verification:**
- [ ] Add tests for marker destinations, terminal destinations, blocked target
      fallback, and blocked target with no reachable neighbor.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 20

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 22: Expose A Pathfinding API Endpoint

**Description:** Add a GUI backend endpoint that accepts selected hero ID and a
requested target tile or marker ID, then returns the serialized pathfinding
result from the service.

**Acceptance criteria:**
- [ ] The endpoint rejects requests without a selected/valid hero.
- [ ] The endpoint accepts explicit target coordinates.
- [ ] The endpoint accepts marker IDs for visible/known markers.
- [ ] The endpoint returns path status, path coordinates, segment metadata, and
      fallback notes.
- [ ] The endpoint handles stale save/map snapshots consistently with existing
      GUI endpoints.

**Verification:**
- [ ] Add API tests for successful path, no path, invalid hero, invalid target,
      and marker target requests.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 21

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 23: Add Path Mode UI And Route Rendering

**Description:** Add a `Path mode` control to the GUI. In path mode, clicking a
tile or marker requests pathfinding instead of running battle simulation, then
draws the returned path on the canvas.

**Acceptance criteria:**
- [ ] Path mode can be toggled on and off.
- [ ] In path mode, clicking an empty tile requests a path to that tile.
- [ ] In path mode, clicking a marker requests a path to that marker.
- [ ] Normal click-to-simulate behavior remains unchanged outside path mode.
- [ ] The visible path segment for the active level is drawn above the route
      overlay and below markers.
- [ ] No-path and invalid-path states are shown clearly in the side panel.

**Verification:**
- [ ] Manual GUI check for tile target, marker target, no path, and normal mode
      simulation.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 22

**Files likely touched:**
- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 24: Add Path Segment List And Cross-Level Navigation

**Description:** Add a path result panel that lists walk and portal segments.
Segment selection should switch to the segment level and center the relevant
part of the path without automatically changing level immediately after path
calculation.

**Acceptance criteria:**
- [ ] Path results list walk segments and portal/gate segments.
- [ ] Portal segments show source and destination coordinates.
- [ ] Non-deterministic portal segments are labeled clearly.
- [ ] Clicking a segment switches to its level and centers the segment.
- [ ] Cross-level paths can be inspected one level at a time.

**Verification:**
- [ ] Manual GUI check with a path using a subterranean gate.
- [ ] Manual GUI check with a path using a monolith, if the current map has
      one.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Dependencies:** Task 23

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 25: End-To-End Pathfinding Verification

**Description:** Verify pathfinding on real generated maps with same-level
routes, cross-level routes through subterranean gates, and routes through
monoliths when available.

**Acceptance criteria:**
- [ ] Same-level land route draws a plausible shortest path.
- [ ] Blocked target fallback is reported and visualized.
- [ ] Cross-level route through a subterranean gate is segmented correctly.
- [ ] Portal route shows portal segment metadata.
- [ ] Normal simulation clicks still work outside path mode.
- [ ] Pathfinding does not route over water in MVP.

**Verification:**
- [ ] Run `python3 -m unittest`.
- [ ] Start the GUI and manually verify path mode on at least one current
      Diamond save/map.

**Dependencies:** Tasks 18, 19, 20, 21, 22, 23, 24

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

### Checkpoint: Pathfinding MVP

After Tasks 18-25:

- [ ] Pathfinding service returns land-only paths, no-path states, and blocked
      target fallback.
- [ ] Portal and subterranean-gate edges are usable in routes.
- [ ] Path mode does not interfere with normal click-to-simulate behavior.
- [ ] Cross-level paths can be inspected through the segment list.

### Checkpoint: Complete

After Tasks 9, 17, and 25:

- [ ] `python3 -m unittest` passes.
- [ ] Route overlay, water, towns, portals, heroes, and neutrals are all
      visually distinguishable.
- [ ] Manual inspection confirms the tool helps understand route corridors
      across levels.
- [ ] Target hiding, map filtering, scan sorting, scan hover, scan click, auto
      refresh, and scan rings work together in the GUI.
- [ ] Path mode can find and display same-level and cross-level land routes.

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
| Pathfinding is mistaken for exact Heroes III movement. | Medium | Label it as strategic route search and keep movement points, roads, terrain costs, water, and spells explicitly out of MVP. |
| Portal with multiple exits produces misleading route certainty. | Medium | Mark path segments through multi-exit portals as non-deterministic. |
| Blocked target fallback hides that the clicked tile itself is unreachable. | Low | Return both requested and resolved target plus a visible fallback note. |
| Path mode conflicts with simulation clicks. | Medium | Gate route requests behind an explicit Path mode toggle and leave normal mode behavior unchanged. |

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
- Task 18 can start once route layers and portal edges are available. Tasks
  19-24 are sequential because each builds on the previous pathfinding layer.
- Task 23 can be split between API integration and frontend rendering only
  after Task 22 defines the endpoint contract.
- Tasks 9, 17, and 25 are verification tasks and should run after their
  respective feature groups are complete.

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
| 9 | End-To-End Map Verification | done | 4, 6, 8 |
| 10 | Add Hidden Hero Target State | done | - |
| 11 | Add Hero Marker Context Actions | done | 10 |
| 12 | Merge Map Filter And Scan Target Type | done | - |
| 13 | Add Scan Sort Modes | done | - |
| 14 | Improve Scan Result Hover And Click Behavior | done | - |
| 15 | Auto-Refresh Scan After Hero Selection | done | 12, 13 |
| 16 | Render Scan Difficulty As Marker Rings | done | - |
| 17 | End-To-End Workflow Verification | done | 10, 11, 12, 13, 14, 15, 16 |
| 18 | Add Pathfinding Service Contract | todo | 3, 8 |
| 19 | Implement Land-Only Shortest Path Search | blocked | 18 |
| 20 | Add Portal And Subterranean Gate Traversal | blocked | 19 |
| 21 | Resolve Blocked Targets And Terminal Markers | blocked | 20 |
| 22 | Expose A Pathfinding API Endpoint | blocked | 21 |
| 23 | Add Path Mode UI And Route Rendering | blocked | 22 |
| 24 | Add Path Segment List And Cross-Level Navigation | blocked | 23 |
| 25 | End-To-End Pathfinding Verification | blocked | 18, 19, 20, 21, 22, 23, 24 |
