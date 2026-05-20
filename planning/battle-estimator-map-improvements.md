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
- show portal/gate destination information.

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
- [ ] One-way monolith entrances and exits are grouped by `subid`.
- [ ] Two-way monoliths are grouped bidirectionally by `subid`.
- [ ] Subterranean gates are paired with the nearest opposite-level gate using
      the VCMI-style matching rule.
- [ ] Multiple exits are represented as multiple possible destinations.
- [ ] Portal targets use stable IDs based on object index.

**Verification:**
- [ ] Add parser tests for one-way, two-way, and subterranean gate topology.
- [ ] Run `python3 -m unittest tests.test_h3_map_parser`.

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
- [ ] `/api/state` includes `portal_targets` and `portal_edges`.
- [ ] Portal markers render on the correct map level.
- [ ] Tooltip/details show whether the portal is one-way, two-way, or a
      subterranean gate.
- [ ] Destination coordinates are shown for all known exits.
- [ ] For destinations on another level, the UI can switch level and center the
      destination marker.

**Verification:**
- [ ] Add or update GUI snapshot tests.
- [ ] Manual GUI check on a Diamond map with monoliths and subterranean gates.
- [ ] Run `python3 -m unittest tests.test_battle_estimator_gui`.

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

### Checkpoint: Complete

After Task 9:

- [ ] `python3 -m unittest` passes.
- [ ] Route overlay, water, towns, portals, heroes, and neutrals are all
      visually distinguishable.
- [ ] Manual inspection confirms the tool helps understand route corridors
      across levels.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Object mask projection is off by one or mirrored incorrectly. | High | Match VCMI `ObjectTemplate::readMap` and add focused tests around known town/gate positions. |
| Visitables create false route corridors. | Medium | Keep towns and portals as markers/special nodes, and only exempt agreed pickup/fightable objects from permanent blocking. |
| `/api/state` becomes too large. | Medium | Use compact route row strings instead of per-tile objects. |
| Town owner from `.h3m` becomes misleading after captures. | Medium | Name it `initial_owner_*` and avoid current-owner claims until save parsing supports it. |
| Portal with multiple exits is displayed as one deterministic target. | Medium | Model edges as one-to-many and show every possible destination. |
| Water visualization suggests current hero can sail without a boat. | Low | Label it as water/sailing route, not current hero reachability. |

## Parallelization Opportunities

- Tasks 5 and 7 can run in parallel after Task 1 because town parsing and portal
  topology are independent.
- Task 4 can run after Task 3 while Tasks 5 and 7 are still in progress.
- Tasks 6 and 8 can run in parallel if the frontend marker changes use
  disjoint sections or coordinate carefully.
- Task 9 must be last because it validates the combined experience.

## Summary Table

| Task | Title | Status | Blocked By |
| --- | --- | --- | --- |
| 1 | Parse Terrain Tiles From H3M | todo | - |
| 2 | Build The Static Route Layer | blocked | 1 |
| 3 | Expose Route Layers In The GUI Snapshot | blocked | 2 |
| 4 | Render The Route Overlay | blocked | 3 |
| 5 | Parse Town Targets | blocked | 1 |
| 6 | Show Town Markers In The GUI | blocked | 5 |
| 7 | Parse Portal Targets And Edges | blocked | 1 |
| 8 | Show Portal Markers And Destinations In The GUI | blocked | 7 |
| 9 | End-To-End Map Verification | blocked | 4, 6, 8 |
