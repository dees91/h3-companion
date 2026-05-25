# Battle Estimator Save-Aware Improvements - Task Breakdown

> **Source**: planning discussion on 2026-05-25.
>
> This plan tracks save-aware improvements that require reverse engineering
> GM1/GM2 data beyond the existing hero army parser. Current workstreams cover
> save-derived current town ownership, defensive alerts, and save-derived hero
> combat context for stronger battle estimates.
>
> It also keeps a short priority map-UX follow-up queue at the beginning of the
> task list. Those tasks build on the completed portal-readability work in
> [Map Improvements](./battle-estimator-map-improvements.md) and should be
> handled before the longer save-research workstreams if the user asks for the
> next map usability pass.
>
> **Related**:
> [Autosave Brief](./battle-estimator-autosave-brief.md),
> [Phase 1 Autosave MVP Tasks](./phase-1-battle-estimator-autosave-mvp-tasks.md),
> [Phase 2 Nearby Scan Tasks](./phase-2-battle-estimator-nearby-scan-tasks.md),
> [Phase 3 GUI Tasks](./phase-3-battle-estimator-gui-tasks.md),
> [Map Improvements](./battle-estimator-map-improvements.md),
> and
> [Save Parsing Checkpoint](../tools/battle_estimator_save_parsing_checkpoint.md).

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
>    broadest relevant Python/JavaScript verification available at that point.
> 6. **Never commit real saves or private game data**. Use real saves only for
>    local reverse engineering; commit only synthetic fixtures and anonymized
>    observations.
>
> Status values: `todo` = ready to pick up | `in-progress` = being worked on |
> `done` = completed | `blocked` = waiting on dependencies.

---

## Goal

When the GUI refreshes an autosave snapshot, it should warn the user if any
enemy hero is within an alert radius of any current town owned by the user's
selected player color.

The alerts must use current ownership parsed from the save. They must not fall
back to `.h3m` `initial_owner`, because towns can be captured during play and
the user cares about currently owned towns.

The battle estimator should also improve hero combat estimates by using hero
combat context parsed from the save whenever it is reliable. The first useful
threshold is current primary Attack/Defense for both sides. If current secondary
combat skills can also be parsed, the estimator should apply passive damage
modifiers such as Offense, Armorer, and Archery. The estimator must never use
VCMI starting skills or manual state as a silent fallback for combat math.

The immediate map UX follow-up should make two-level portal navigation and map
readability faster during play: subterranean gates should be easy to traverse
visually, neutral monster markers should stop obscuring more important markers,
cross-level portal destinations should be visible as ghost context, and an
optional side-by-side level view should let the user inspect surface and
underground together.

## Product Decisions

- Add a persistent `My color` setting in the left hero panel.
- Add a separate persistent `Alert radius` setting, defaulting to `10`.
- Alert distance uses the same metric as radius scan: Manhattan distance on the
  same map level, `abs(dx) + abs(dy)`.
- Enemy hero means a positioned hero with a detected owner color whose color is
  not `My color` and not in the same H3M team as `My color`.
- Heroes with unknown owner color are ignored for alerts.
- Alerts apply to every current town owned by `My color`, regardless of fort
  or castle building level.
- Alerts do not include allied towns by default.
- Render alerts as the first section of the right sidebar, above `Target`.
- Emit one alert per enemy hero. If the hero threatens multiple towns, show the
  nearest town and a `+N other towns in radius` detail.
- Clicking an alert centers the map on the enemy hero and activates its marker.
- If current town ownership cannot be parsed confidently for a snapshot, show a
  diagnostic state and emit no fallback alerts.
- Hero combat context is save-first. Do not add manual combat stat entry for
  this workflow.
- Research should look broadly for hero primary skills, secondary skills,
  artifacts, spellbook, mana, experience, level, and specialty-related data.
- Estimator integration should be incremental and explicit: use any reliable
  parsed subset, but label the model as `army-only`, `primary-only`, or
  `primary+secondary` per side.
- The first estimator integration should cover passive combat modifiers only:
  primary Attack/Defense, Offense, Armorer, and Archery.
- Active spell casting, artifact bonuses, morale/luck modeling, specialties,
  tactics deployment, and battlefield positioning are out of the first hero
  combat estimator integration even if research finds related save data.
- Hero combat context should improve both selected-hero-vs-neutral estimates
  and hero-vs-hero estimates. Enemy combat context is used only when the target
  is another parsed hero.
- Priority map UX follow-ups are frontend-first and should reuse existing
  `portal_targets`, `portal_edges`, portal relation state, and `Portal links`
  toggle unless implementation proves the snapshot contract is insufficient.
- Normal-mode click on a paired subterranean gate should switch to the paired
  gate's level, center it, and preserve the source portal relation context.
  Path mode click semantics must remain route requests.
- Cross-level portal relation preview should draw off-level destination portals
  as ghost markers at their map `(x, y)` with alpha around `0.5`, plus a line
  from the source to the ghost and a badge showing the real destination level.
  This applies only to hovered/pinned portal relations, not all portals.
- Neutral monster markers should render and hit-test below heroes, portals, and
  towns. Recommended hit priority is hero, portal, town, then monster.
- Side-by-side map levels should be an optional view mode, not a replacement
  for the existing single-level view. It is enabled only for two-level maps,
  uses shared pan/zoom and the same scale for both levels, and is hidden or
  disabled for single-level maps.

## Critical Implementation Notes

- Current town ownership is not implemented today. Existing town markers expose
  `.h3m` `initial_owner` only, and older planning explicitly marks current town
  ownership as out of scope.
- The parser currently extracts save-derived hero army, position, and owner
  color from observed GM1/GM2 structures. Town ownership must be researched
  separately from real local saves and then covered with synthetic tests.
- Current hero combat context is not implemented today. `HeroArmy` contains
  name, stacks, source offset, position, and owner color only.
- Existing hero skill recommendation state is manually maintained for advice.
  It must not be reused as combat-estimator input unless a future task
  explicitly asks for a manual what-if mode.
- Existing VCMI-derived hero metadata includes starting secondary skills and
  skill effect values, but starting skills are not current save state. Combat
  estimates must not silently fall back to those values.
- VCMI's `DamageCalculator` is the mechanics reference for passive damage
  math. Attack-side factors are additive, defense-side factors are
  multiplicative reductions.
- `config/skills.json` already contains Offense, Armorer, and Archery effect
  values. Use the existing JSONC loader path instead of raw `json.loads()`.
- Current town ownership needs to join save-derived ownership records to H3M
  town targets. The join should be based on coordinates/object identity when
  supported by observed save data, not on display name alone.
- If the parser can identify ownership only for a subset of towns, the alert
  service should expose a confidence/diagnostic status instead of silently
  treating missing towns as unowned.
- The existing `PLAYER_COLOR_NAMES`, H3M player/team parsing, `team_by_color`,
  and hero serialization should be reused.
- Keep the GUI dependency-free. Use existing compact sidebar/list patterns and
  avoid decorative UI.
- Keep real save files out of the repo. Add only synthetic binary fixtures to
  tests.
- The current portal-readability baseline already has portal relation state,
  marker symbols, portal links overlay, target details, and Path mode
  preservation in `tools/battle_estimator_gui/app.js`.
- The current single-level map model filters markers by `mapView.level`.
  Side-by-side levels will require explicit viewport/lane geometry rather than
  only changing `setMapLevel()`.
- Current marker rendering/hit testing should be audited before changing z
  order; marker cache order and reverse hit-test order both affect priority.

## Proposed Data Contracts

These are planning targets, not final implementation requirements.

### Config

```json
{
  "my_color_id": 0,
  "alert_radius": 10
}
```

### Town Serialization

Extend `town_targets` entries with save-derived fields when available:

```json
{
  "id": "town:2231",
  "initial_owner": 1,
  "initial_owner_color_name": "blue",
  "current_owner": 0,
  "current_owner_color_name": "red",
  "current_owner_source": "save",
  "current_owner_confidence": "exact"
}
```

If current ownership is unavailable, fields should be explicit:

```json
{
  "current_owner": null,
  "current_owner_color_name": null,
  "current_owner_source": "unavailable",
  "current_owner_confidence": "unknown"
}
```

### Alert Serialization

Add a snapshot-level alert block:

```json
{
  "alert_settings": {
    "my_color_id": 0,
    "my_color_name": "red",
    "my_team_id": 0,
    "alert_radius": 10
  },
  "castle_alerts_status": "ok",
  "castle_alerts_status_detail": null,
  "castle_alerts": [
    {
      "id": "castle-threat:hero:gem",
      "enemy_hero_id": "hero:gem",
      "enemy_hero_name": "Gem",
      "enemy_color_id": 2,
      "enemy_color_name": "tan",
      "town_id": "town:2231",
      "town_name": "Castle Keep",
      "distance": 7,
      "other_towns_in_radius": 1,
      "enemy_position": {"x": 45, "y": 46, "z": 0},
      "town_position": {"x": 39, "y": 46, "z": 0}
    }
  ]
}
```

Recommended `castle_alerts_status` values:

- `ok`: ownership was parsed and alerts are meaningful,
- `unconfigured`: `My color` is not selected,
- `ownership_unavailable`: current town ownership could not be parsed,
- `no_owned_towns`: ownership parsed, but `My color` owns no towns,
- `no_threats`: ownership parsed and no enemy is within radius.

### Hero Combat Context Serialization

Extend serialized hero entries with save-derived combat context when available:

```json
{
  "id": "hero:783079",
  "name": "Isra",
  "combat_context": {
    "status": "primary+secondary",
    "source": "save",
    "primary": {
      "attack": 12,
      "defense": 10,
      "spell_power": 7,
      "knowledge": 6
    },
    "secondary_skills": [
      {"skill": "offence", "level": "expert"},
      {"skill": "armorer", "level": "basic"}
    ],
    "passive_modifiers": {
      "offence_melee_pct": 30,
      "armorer_all_pct": 5,
      "archery_ranged_pct": 0
    },
    "unsupported_observed": ["artifacts", "spellbook"]
  }
}
```

Recommended hero combat context statuses:

- `unavailable`: no reliable current combat context was parsed,
- `primary-only`: current primary skills were parsed,
- `primary+secondary`: current primary skills and current secondary skills were
  parsed,
- `partial`: some useful data was parsed, but not enough to fit the stable
  `primary-only` or `primary+secondary` shapes.

Do not emit VCMI starting skills as `save` context. Starting skills may appear
elsewhere in the hero skill recommender, but they are not current combat state.

### Estimate Combat Model Notes

Extend estimate payloads with model notes rather than overloading the existing
`note` string:

```json
{
  "combat_model": {
    "player_status": "primary+secondary",
    "enemy_status": "army-only",
    "applied": [
      "player primary attack/defense",
      "player offence",
      "player archery"
    ],
    "omitted": [
      "enemy hero context unavailable",
      "artifacts not modeled",
      "active spells not modeled"
    ]
  }
}
```

## Dependency Graph

```text
Save-Aware Improvements

  Priority Map UX Follow-Ups:
    M01 [Lower Monster Marker Priority]
    M02 [Subterranean Gate Click Level Toggle]
      -> M03 [Cross-Level Ghost Portal Destinations]
    M04 [Dual-Level View State And Geometry]
      -> M05 [Render Dual-Level Map And Markers]
      -> M06 [Dual-Level Interactions And Portal Links]
    M01, M02, M03, M04, M05, M06 -> M07 [Map UX Follow-Up Verification]

  Research:
    T01 [Collect Local Save Evidence]
      -> T02 [Document Save Ownership Hypothesis]

  Parser Foundation:
    T02 -> T03 [Synthetic Current Town Ownership Fixtures]
    T03 -> T04 [Parse Current Town Ownership]
    T04 -> T05 [Join Save Ownership To H3M Town Targets]

  Backend Feature:
    T06 [Persist My Color And Alert Radius]
    T05, T06 -> T07 [Build Threat Alert Service]
    T07 -> T08 [Expose Snapshot Contract]

  Frontend Feature:
    T08 -> T09 [Render My Color And Alert Radius Controls]
    T08 -> T10 [Render Alerts Sidebar Section]
    T10 -> T11 [Center And Activate Alert Target]

  Hero Combat Context:
    T13 [Research Save Hero Combat Data]
      -> T14 [Document Hero Combat Data Hypothesis]
      -> T15 [Synthetic Hero Combat Fixtures]
      -> T16 [Parse Hero Primary Skills]
      -> T17 [Parse Hero Secondary Skills]
      -> T18 [Build Combat Context Contract]
      -> T19 [Apply Passive Combat Modifiers]
      -> T20 [Expose Combat Model Notes]
      -> T21 [Render Estimate Model Details]
      -> T22 [Hero Combat Docs And Verification]

  Quality:
    T08, T09, T10, T11 -> T12 [Docs And Verification Pass]
```

**Max parallelism:** T06 can run after the config contract is agreed, while
T03/T04 parser work continues. T09 can be prototyped against a fixed test
snapshot after T08's contract is written, but final wiring must wait for T08.
T13/T14 hero combat research can run in parallel with town ownership research,
but T03/T04 and T15/T16/T17 should be coordinated because they share
`tools/h3_save_parser.py` and binary fixture helpers. Parser tasks should be
single-owner per file during implementation. M01 and M02 can be implemented
independently. M03 should wait for M02 if ghost destination clicks share the
same center/switch behavior. M04/M05/M06 should be sequential because
side-by-side view changes map geometry, rendering, and hit testing.

## Task Definitions

### M01: Lower Monster Marker Priority

| Field | Value |
|---|---|
| Description | Change map marker draw and hit-test priority so neutral monster markers no longer obscure heroes, portals, or towns. |
| Blocked By | -- |
| Wave | priority-map-ux |
| Execution | Parallel |
| Effort | S |
| Scope | GUI |
| Source | User request for monster markers below more important map markers |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Neutral monster markers render below towns, portals, and heroes.
2. Hit testing prefers heroes, then portals, then towns, then monsters when
   markers overlap.
3. Scan rings and hover/active states for monsters remain visible when the
   monster is not covered by a higher-priority marker.
4. Existing marker filtering and hidden-target behavior remain unchanged.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual or headless GUI check with overlapping monster and portal/town/hero
   markers.

**Completion Notes:**

- Done in commit for M01. Marker cache order now draws neutral monster markers
  before towns, portals, and heroes, which also makes reverse-order hit testing
  prefer heroes, then portals, then towns, then monsters. Frontend helper tests
  cover cache order, overlap hit priority, and a headless canvas draw-order
  check for overlapping monster/town/portal/hero markers. Verified with
  `node --check tools/battle_estimator_gui/app.js` and
  `python3 -m unittest tests.test_battle_estimator_gui`.

---

### M02: Subterranean Gate Click Level Toggle

| Field | Value |
|---|---|
| Description | Make normal-mode clicks on paired subterranean gates switch to and center the paired gate's map level while preserving portal relation context. |
| Blocked By | -- |
| Wave | priority-map-ux |
| Execution | Parallel |
| Effort | S |
| Scope | GUI |
| Source | User request for subterranean gate click-to-toggle behavior |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Clicking a subterranean gate outside Path mode pins or preserves the source
   portal relation, switches to the paired destination level, and centers the
   paired gate.
2. The destination gate is visually active or otherwise clearly identified
   after the level switch.
3. Subterranean gates with no known paired destination do not switch levels and
   show the existing diagnostic/details state.
4. Path mode left-click on a subterranean gate still requests a route instead
   of toggling levels.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual or headless GUI check on a two-level map with a paired subterranean
   gate.

**Completion Notes:**

- Done in commit for M02. Normal-mode clicks on an unambiguous cross-level
  subterranean gate pair now pin the source relation, switch to the destination
  level, center the paired gate, and make the destination marker active. Gates
  without a known resolved pair keep the existing portal diagnostic/details
  behavior. Path mode left-click still sends a route request to the source gate
  and does not toggle levels. Headless GUI tests cover forward and reverse gate
  toggles, centering, no-edge/unresolved diagnostics, and Path mode behavior.
  Verified with `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`, and `git diff --check`.

---

### M03: Cross-Level Ghost Portal Destinations

| Field | Value |
|---|---|
| Description | Improve cross-level portal relation preview by drawing off-level destination portals as ghost markers with a source-to-ghost line on the active canvas. |
| Blocked By | M02 |
| Wave | priority-map-ux |
| Execution | Main |
| Effort | M |
| Scope | GUI |
| Source | User request for visible cross-level portal destination hints |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. For hovered or pinned portal relations, destinations on another level draw
   as ghost portal markers at the destination `(x, y)` on the current canvas.
2. Ghost portal markers use reduced alpha around `0.5` and a visible badge for
   the real destination level.
3. A restrained line connects the source portal to each ghost destination.
4. Ghost destinations are drawn only for the active portal relation, not for all
   cross-level portals on the map.
5. Clicking a ghost destination switches to the real destination level and
   centers the real portal, sharing the behavior from M02 where practical.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check with one subterranean gate and one cross-level monolith
   relation.

**Completion Notes:**

- Done in commit for M03. Active portal relations now draw off-level
  destinations as canvas ghost portal markers at the destination `(x, y)` with
  alpha `0.5`, a restrained source-to-ghost line, and per-ghost `L<level>`
  badges while preserving the source summary badge. Ghosts are scoped to the
  active hovered/pinned relation and respect the `Portal links` toggle. Normal
  markers keep hit priority over ghosts; normal-mode ghost clicks center and
  activate the real destination portal through the existing portal-focus path;
  Path mode treats ghost clicks as tile path requests on the active level.
  Headless GUI tests cover drawing, badges near the ghost marker, Portal links
  off, relation scoping, normal-marker priority, destination centering, and Path
  mode transparency. Verified with
  `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`, and `git diff --check`.

---

### M04: Dual-Level View State And Geometry

| Field | Value |
|---|---|
| Description | Add an optional dual-level map view mode with shared pan/zoom and explicit geometry helpers for two side-by-side map lanes. |
| Blocked By | -- |
| Wave | priority-map-ux |
| Execution | Main |
| Effort | M |
| Scope | GUI |
| Source | User request for levels side by side instead of only switched |

**Files to modify:**

- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. A compact `Dual level` control is available only when the current map has
   exactly two levels; it is hidden or disabled for single-level maps.
2. Single-level view remains the default and keeps the existing level segmented
   control behavior.
3. Dual-level view computes two side-by-side lanes with the same tile scale,
   shared zoom, and shared pan.
4. Geometry helpers can convert between canvas points, world points, map lanes,
   and `(x, y, z)` positions without changing route/path behavior yet.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Frontend helper tests for two-level and one-level map geometry.

**Completion Notes:**

- Done in commit for M04. Added a compact `Dual level` toolbar toggle that is
  enabled only for exactly two-level maps and disabled with a diagnostic title
  for one-level or three-plus-level maps. Single-level view remains the default,
  and the existing level segmented control and route/path behavior are
  unchanged. Added dual-level lane geometry helpers for side-by-side lanes with
  shared tile scale, zoom, and pan, plus conversion helpers for
  canvas-to-lane-world and canvas-to-position mapping. Frontend helper tests
  cover supported/unsupported maps, default state, toggle on/off, preserving
  state across same-geometry refresh, lane gap misses, two-lane coordinate
  conversion, and unchanged active-level tile path semantics. Verified with
  `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`, and `git diff --check`.

---

### M05: Render Dual-Level Map And Markers

| Field | Value |
|---|---|
| Description | Render both map levels side by side in dual-level mode, including route layers and markers in the correct lane. |
| Blocked By | M04 |
| Wave | priority-map-ux |
| Execution | Main |
| Effort | M |
| Scope | GUI |
| Source | Dual-level map view implementation |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Dual-level mode draws both levels side by side on one canvas with clear
   labels such as `Surface` and `Underground`.
2. Route layers, towns, portals, heroes, and neutral markers render in the lane
   matching their real `z` level.
3. Marker hit testing works in both lanes and respects the priority from M01.
4. Existing single-level rendering remains unchanged when dual-level mode is
   off.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual or headless GUI check on a two-level map.

**Completion Notes:**

- Done in commit for M05. Dual-level mode now fits the combined two-lane world
  bounds, rebuilds marker cache for both levels, and draws Surface/Underground
  lanes side by side with each lane's route layer, grid, label, and markers.
  Marker positions keep their original `position.z` while using lane-shifted
  canvas `world` coordinates plus `laneIndex`/`laneLevel` metadata. Single-level
  rendering remains the default path, with the existing route overlay wrapper
  preserved for active-level rendering. Frontend tests cover per-level route
  colors, lane-shifted markers, original marker positions, lane-1 hit-test
  priority, lane-1 draw order, dual toggle off cache reset, unsupported map
  handling, and the headless canvas dual-lane render check. Verified with
  `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest`, and `git diff --check`.

---

### M06: Dual-Level Interactions And Portal Links

| Field | Value |
|---|---|
| Description | Make existing map interactions work in dual-level mode, including centering, portal relation overlays, ghost destinations, path rendering, and scan/active marker states. |
| Blocked By | M03, M05 |
| Wave | priority-map-ux |
| Execution | Main |
| Effort | M |
| Scope | GUI |
| Source | Dual-level interaction integration |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Centering a marker or portal destination in dual-level mode centers the
   correct lane without losing shared zoom/pan semantics.
2. Portal relation lines and ghost destinations draw correctly when source and
   destination are in different lanes.
3. Path mode clicks in either lane request routes to the clicked tile or marker
   with the correct `z` level.
4. Scan hover/click, active marker, target details, and context menu placement
   continue to work in dual-level mode.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check for portal links, path mode, and scan result interactions
   in dual-level mode.

**Completion Notes:**

- Done in commit for M06. Dual-level mode now uses lane-aware position-to-world
  helpers for centering, portal destination focus, portal ghost hit testing,
  portal relation overlays, path route rendering, path segment focus, and
  empty-tile path requests. Cross-level portal ghosts render and hit-test in
  the destination lane in both surface-to-underground and
  underground-to-surface directions. Path mode sends lane-correct `z` values
  for tile clicks and still rejects clicks in the inter-lane gap. Scan result
  hover/click and context menu interactions work on underground-lane targets
  without changing zoom unexpectedly. Single-level portal relation behavior is
  covered by regression tests after focusing an off-level destination. Verified
  with `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest`, and `git diff --check`.

---

### M07: Map UX Follow-Up Verification

| Field | Value |
|---|---|
| Description | Verify the combined map UX follow-ups on real or representative two-level map data. |
| Blocked By | M01, M02, M03, M04, M05, M06 |
| Wave | priority-map-ux |
| Execution | Main |
| Effort | S |
| Scope | Docs/Test |
| Source | End-to-end quality gate |

**Files to modify:**

- `README.md`
- `CHANGELOG.md`
- This planning doc

**Acceptance Criteria:**

1. Monster marker priority, subterranean click toggle, cross-level ghost
   destinations, and dual-level view are all manually or headlessly verified on
   a two-level map.
2. Single-level map behavior remains usable and does not show unavailable
   dual-level controls as active.
3. README or CHANGELOG documents the user-visible map UX changes if this work
   is prepared for release.
4. Completion notes record the save/map used for verification without
   committing real save or map files.

**Verification:**

1. `python3 -m unittest`
2. `node --check tools/battle_estimator_gui/app.js`
3. `git status --short` confirms no real save/map files are staged.

**Completion Notes:**

- Done in commit for M07. Verified the combined map UX work using the existing
  headless GUI representative snapshots rather than real save/map files. The
  synthetic coverage includes overlapping markers with lowered neutral priority,
  paired subterranean gate click-through, cross-level portal ghost destinations,
  dual-level Surface/Underground lanes, lane-specific route overlays, portal
  relation overlays, ghost hit testing in both cross-level directions, path mode
  tile clicks with correct `z`, inter-lane gap rejection, path route rendering
  in both lanes, path segment focus, scan hover/click centering, and context
  menus on underground-lane targets. Single-level regression coverage confirms
  unsupported/non-two-level maps keep dual-level controls inactive and off-level
  portal ghosts remain hidden in single-level mode. README and CHANGELOG now
  mention the user-visible dual-level map, portal hints, marker priority, and
  subterranean gate interaction updates. Verified with
  `node --check tools/battle_estimator_gui/app.js`,
  `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest`, `git diff --check`, and `git status --short`. No real
  `.GM1`, `.GM2`, or `.h3m` files were used or staged.

---

### T01: Collect Local Save Evidence

| Field | Value |
|---|---|
| Description | Use real local saves to observe how current town ownership changes across captures without committing those files. |
| Blocked By | -- |
| Wave | research |
| Execution | Main |
| Effort | M |
| Scope | Research |
| Source | User requirement for current, save-derived towns |

**Files to modify:**

- `tools/battle_estimator_save_parsing_checkpoint.md`
- Possibly new scratch notes under `planning/` only if anonymized

**Acceptance Criteria:**

1. At least two same-map saves with different town ownership states are
   inspected locally.
2. Observed current owner facts are recorded without paths, player names, or
   real save bytes.
3. The notes identify likely save byte ranges or structures worth turning into
   synthetic fixtures.

**Verification:**

1. Manual check that no `.GM1`, `.GM2`, `.h3m`, cache files, or private paths
   are staged.
2. `git status --short`

**Completion Notes:**

- Done in commit for T01. Inspected local real saves in place without copying
  or staging save/map files. Recorded an anonymized current-town-ownership
  evidence section in `tools/battle_estimator_save_parsing_checkpoint.md`.
  The evidence uses one same-map save group with stable parsed map geometry
  (`108`, two levels, `24` town targets) and anonymized save/town labels. Two
  save pairs show different town-control states through high-confidence
  owner/position proxy facts: visible XOR `0x01` hero records of different
  owner colors occupying the same parsed town tile at different save points.
  Notes record only semantic owner ids, approximate `H3SVG`-relative supporting
  hero-structure ranges, and negative searches for direct town-owner vectors or
  coordinate/object-index patterns. No real paths, player names, map names,
  save filenames, custom town names, raw bytes, `.GM1`, `.GM2`, `.h3m`, or cache
  files were staged.

---

### T02: Document Save Ownership Hypothesis

| Field | Value |
|---|---|
| Description | Convert local observations into a bounded parser hypothesis: record shape, owner encoding, coordinate/object identity, and confidence rules. |
| Blocked By | T01 |
| Wave | research |
| Execution | Main |
| Effort | S |
| Scope | Docs |
| Source | Parser safety |

**Files to modify:**

- `tools/battle_estimator_save_parsing_checkpoint.md`
- This planning doc, if task statuses or caveats need updating

**Acceptance Criteria:**

1. The checkpoint doc explains how town records are recognized.
2. The checkpoint doc explains how current owner color is decoded.
3. The checkpoint doc lists cases that must return `ownership_unavailable`
   instead of guessing.

**Verification:**

1. Markdown review for private data leaks.
2. `git diff --check`

**Completion Notes:**

- Done in commit for T02. Added a bounded current-town-ownership hypothesis to
  the save parsing checkpoint. The hypothesis deliberately treats town identity
  as H3M-derived town target identity, not a discovered save-side town record,
  and states that the direct town-owner byte/record remains unknown. Current
  owner color is described as a `hero_on_town_tile_proxy`: decode a visible
  hero's owner and position from the supported hero struct, match exactly to a
  parsed town visitable tile, and infer proxy owner only when there is exactly
  one eligible owned hero. The checkpoint now lists required
  `ownership_unavailable` cases for missing/mismatched maps, unsupported save
  layouts, absent or ambiguous heroes, unowned/unknown owners, nondeterministic
  town tiles, direct/proxy conflicts, and loose byte-pattern matches. T03 is
  unblocked to build synthetic fixtures for this bounded proxy path while
  preserving `ownership_unavailable` outside it.

---

### T03: Synthetic Current Town Ownership Fixtures

| Field | Value |
|---|---|
| Description | Add synthetic save/map fixtures that encode the observed town ownership pattern, including captured towns and unknown/unowned cases. |
| Blocked By | T02 |
| Wave | parser |
| Execution | Main |
| Effort | M |
| Scope | Test |
| Source | Current ownership parser coverage |

**Files to modify:**

- `tests/test_h3_save_parser.py`
- `tests/test_battle_estimator_gui.py`
- Possibly test helper code already local to these files

**Acceptance Criteria:**

1. Tests cover a town that starts as one color and is currently owned by a
   different color in the synthetic save.
2. Tests cover an unowned or unknown-current-owner town.
3. Tests do not require real saves or real maps.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Done in commit for T03. Added synthetic, green fixture-contract tests for the
  bounded `hero_on_town_tile_proxy` hypothesis without adding production parser
  behavior. Save-parser tests now cover H3M initial owner `A` with exactly one
  visible hero owner `B` on the deterministic town tile, plus
  `ownership_unavailable` fixture cases for no matching hero, unowned owner,
  invalid owner, multiple visible heroes on the same town tile, wrong level,
  and missing hero position. GUI tests now include a synthetic `.GM2` plus
  synthetic `.h3m` snapshot where a red initial-owner town and tan visible hero
  occupy the same town tile. All data is generated in tests; no real saves or
  maps are required.

---

### T04: Parse Current Town Ownership

| Field | Value |
|---|---|
| Description | Implement save parsing for current town ownership records, returning structured town ownership observations with confidence status. |
| Blocked By | T03 |
| Wave | parser |
| Execution | Main |
| Effort | M |
| Scope | Core |
| Source | Required foundation for truthful alerts |

**Files to modify:**

- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`
- `tools/battle_estimator_save_parsing_checkpoint.md`

**Acceptance Criteria:**

1. Parser returns current owner color IDs for supported synthetic town records.
2. Parser rejects ambiguous/truncated/unsupported structures with an explicit
   unavailable status.
3. Existing hero parsing, removed-neutral parsing, and config tests remain
   unchanged.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Done in commit for T04. Added the parser contract in
  `tools/h3_save_parser.py` with `TownOwnershipObservation`,
  `infer_current_town_ownership(town_targets, heroes)` as the core API, and
  `detect_current_town_ownership(data, town_targets)` as a save-byte scanning
  wrapper. The implementation is proxy-only: exactly one visible hero on the
  deterministic town tile with a decoded owner color produces
  `ownership_status = proxy`, `ownership_source = hero_on_town_tile_proxy`, and
  `ownership_confidence = proxy`. Non-town, missing identity/position, no hero,
  ambiguous heroes, and missing owner color all return explicit
  `ownership_unavailable` observations with reason strings and matching-hero
  details where available. The checkpoint doc now records the API boundary and
  states that map/save mismatch detection remains a caller precondition.

---

### T05: Join Save Ownership To H3M Town Targets

| Field | Value |
|---|---|
| Description | Attach save-derived current owner data to H3M `town_targets` in domain snapshots without replacing `initial_owner`. |
| Blocked By | T04 |
| Wave | backend |
| Execution | Main |
| Effort | M |
| Scope | API |
| Source | Snapshot contract |

**Files to modify:**

- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`
- Possibly `tools/h3_save_parser.py` for shared dataclasses

**Acceptance Criteria:**

1. `/api/state` town entries include explicit current owner fields.
2. Existing `initial_owner` fields remain present and keep their old meaning.
3. The snapshot exposes an ownership availability status when no reliable join
   is possible.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_gui`
2. `python3 -m unittest tests.test_h3_save_parser`

**Completion Notes:**

- Done in commit for T05. Domain snapshots now build
  `town_ownership_by_id` from `infer_current_town_ownership()` using raw
  detected heroes, keyed by the existing `town:<object_index>` UI id. Town
  serializers preserve `initial_owner` and append explicit save-derived
  `current_owner_*` fields plus `ownership_*` status, source, confidence,
  reason, and matching-hero details. `/api/state` and internal town marker
  lookup now serialize the same enriched town shape. Tests cover unavailable
  ownership, proxy current owner differing from initial owner, ambiguous
  multi-hero ownership, and path-marker town lookup.

---

### T06: Persist My Color And Alert Radius

| Field | Value |
|---|---|
| Description | Extend local config with `My color` and `Alert radius`, preserving compatibility with existing config files. |
| Blocked By | -- |
| Wave | backend |
| Execution | Parallel |
| Effort | S |
| Scope | Config |
| Source | User settings |

**Files to modify:**

- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Missing fields load as defaults: no selected color and alert radius `10`.
2. Invalid colors/radii fail with config/API validation errors rather than
   corrupting the config.
3. Saving config preserves existing autosave, selected hero, hidden target, and
   hero skill state data.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Done in commit for T06. Added persistent `my_color_id` and `alert_radius`
  config fields with defaults of no selected color and radius `10`, centralized
  validation for nullable player color IDs and integer radius `0..200`, and
  `set_config_alert_settings()` for preserving unrelated config sections while
  updating only alert settings. Added `POST /api/alert-settings`, which requires
  both fields, allows `my_color_id: null`, writes under `config_lock`, and
  returns the saved color name and radius. `/api/state`, alert calculation,
  frontend controls, and marker behavior are intentionally unchanged for later
  tasks.

---

### T07: Build Threat Alert Service

| Field | Value |
|---|---|
| Description | Calculate town-threat alerts from current owned towns, enemy heroes, teams, and alert radius. |
| Blocked By | T05, T06 |
| Wave | backend |
| Execution | Main |
| Effort | M |
| Scope | Core/API |
| Source | Main alert behavior |

**Files to modify:**

- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`
- Possibly `tools/h3_save_parser.py` for owner/team helper reuse

**Acceptance Criteria:**

1. Alerts use Manhattan distance on the same level as radius scan.
2. Enemy classification excludes `My color`, same-team colors, and unknown
   owner heroes.
3. One alert is returned per enemy hero, using the nearest owned town and a
   count of additional owned towns in radius.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_gui`
2. Focused tests cover no color, unavailable ownership, no owned towns, no
   threats, same-team heroes, and multiple towns threatened by one hero.

**Completion Notes:**

- Done in commit for T07. Added a backend-only castle alert service that
  returns stable alert result/status dataclasses without exposing them through
  `/api/state` yet. The service treats missing or non-proxy town ownership as
  a snapshot-wide diagnostic, uses only save-derived current owner color for
  owned towns, ignores own-color, same-team, unknown-owner, and unpositioned
  heroes, and emits one same-level Manhattan-distance alert per enemy hero with
  nearest-town tie-breaking and extra threatened-town counts. Added focused GUI
  backend tests for unconfigured color, unavailable ownership, no owned towns,
  no threats, same-team/unknown-owner exclusions, unknown team fallback enemy
  classification, nearest-town selection, and deterministic equal-distance
  alert ordering.

---

### T08: Expose Snapshot Contract

| Field | Value |
|---|---|
| Description | Add alert settings, ownership status, and alert list to `/api/state` while preserving existing consumers. |
| Blocked By | T07 |
| Wave | backend |
| Execution | Main |
| Effort | S |
| Scope | API |
| Source | Frontend integration |

**Files to modify:**

- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. `/api/state` includes `alert_settings`, `castle_alerts_status`,
   `castle_alerts_status_detail`, and `castle_alerts`.
2. Snapshot changes are detected when alert settings or alert payload changes.
3. Existing scan, pathfinding, hidden-target, and hero-skill API tests still
   pass.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Done in commit for T08. `/api/state` now includes `alert_settings`
  (`my_color_id`, `my_color_name`, state-only `my_team_id`, `alert_radius`),
  `castle_alerts_status`, `castle_alerts_status_detail`, and serialized
  `castle_alerts`. Alert calculation remains config-dependent in
  `_state_payload_for_app`, outside `DomainSnapshot.state` and the snapshot
  cache key, so config changes are reflected without reparsing unchanged
  save/map files. `POST /api/alert-settings` keeps its previous response shape.
  The frontend still renders no alert UI, but `snapshotChanged` now compares
  the alert contract fields so future alert setting/payload changes are
  detected.

---

### T09: Render My Color And Alert Radius Controls

| Field | Value |
|---|---|
| Description | Add compact controls to the left hero panel for selecting the user's color and alert radius. |
| Blocked By | T08 |
| Wave | frontend |
| Execution | Parallel |
| Effort | M |
| Scope | GUI |
| Source | User configuration UI |

**Files to modify:**

- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. `My color` shows active player colors from the current map with color
   swatches.
2. `Alert radius` is an integer input independent from radius scan.
3. Control changes persist via backend API and survive snapshot refresh.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check that compact controls do not overflow the left panel.

**Completion Notes:**

- Fill in after implementation.

---

### T10: Render Alerts Sidebar Section

| Field | Value |
|---|---|
| Description | Show castle-threat alerts as the first right-sidebar section, including clear empty and diagnostic states. |
| Blocked By | T08 |
| Wave | frontend |
| Execution | Parallel |
| Effort | M |
| Scope | GUI |
| Source | Alert visibility |

**Files to modify:**

- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Right sidebar shows an `Alerts` section above `Target`.
2. Diagnostic states distinguish unconfigured color, unavailable ownership, no
   owned towns, and no threats.
3. Threat rows show enemy hero, enemy color, distance, nearest owned town, and
   additional threatened town count when applicable.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check at desktop and narrow widths for text overflow.

**Completion Notes:**

- Fill in after implementation.

---

### T11: Center And Activate Alert Target

| Field | Value |
|---|---|
| Description | Wire alert row clicks to center the map on the enemy hero and activate its marker, with simple visual emphasis. |
| Blocked By | T10 |
| Wave | frontend |
| Execution | Main |
| Effort | S |
| Scope | GUI |
| Source | Alert action behavior |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Clicking an alert centers on the enemy hero marker and sets it active.
2. The map switches to the enemy hero's level if needed.
3. Alert highlighting does not interfere with scan result hover or path mode.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check with at least one alert on a two-level map.

**Completion Notes:**

- Fill in after implementation.

---

### T12: Docs And Verification Pass

| Field | Value |
|---|---|
| Description | Update user-facing docs and run the full relevant verification suite after the feature is complete. |
| Blocked By | T08, T09, T10, T11 |
| Wave | quality |
| Execution | Main |
| Effort | S |
| Scope | Docs/Test |
| Source | Public behavior change |

**Files to modify:**

- `README.md`
- `CHANGELOG.md`
- `AGENTS.md`
- This planning doc

**Acceptance Criteria:**

1. README describes `My color`, alert radius, and current-town alert behavior.
2. CHANGELOG records save-derived current town ownership and alert workflow.
3. AGENTS routing points future parser/alert work to this planning doc.

**Verification:**

1. `python3 -m unittest`
2. `node --check tools/battle_estimator_gui/app.js`
3. `git status --short` confirms no real save/map files are staged.

**Completion Notes:**

- Fill in after implementation.

---

### T13: Research Save Hero Combat Data

| Field | Value |
|---|---|
| Description | Use local real saves to identify current hero combat data near or linked to parsed hero army structures. Research should look for primary skills, secondary skills, artifacts, spellbook, mana, experience, level, and specialty-relevant identifiers. |
| Blocked By | -- |
| Wave | hero-combat-research |
| Execution | Main |
| Effort | M |
| Scope | Research |
| Source | Save-first hero combat estimator requirement |

**Files to modify:**

- `tools/battle_estimator_save_parsing_checkpoint.md`
- Possibly this planning doc for revised caveats

**Acceptance Criteria:**

1. At least two real saves with known hero Attack/Defense and secondary skills
   are inspected locally.
2. Observations include whether combat data appears in the same hero struct as
   army/name/position or in a linked record.
3. Notes record candidate offsets, encoding, validation signals, and unsupported
   structures without real save bytes or private paths.

**Verification:**

1. Manual check that no `.GM1`, `.GM2`, `.h3m`, cache files, or private paths
   are staged.
2. `git status --short`

**Completion Notes:**

- Fill in after implementation.

---

### T14: Document Hero Combat Data Hypothesis

| Field | Value |
|---|---|
| Description | Convert research observations into a bounded parser hypothesis for current hero primary skills, secondary skills, and other discovered combat-adjacent data. |
| Blocked By | T13 |
| Wave | hero-combat-research |
| Execution | Main |
| Effort | S |
| Scope | Docs |
| Source | Parser safety |

**Files to modify:**

- `tools/battle_estimator_save_parsing_checkpoint.md`
- This planning doc, if task dependencies or caveats change

**Acceptance Criteria:**

1. The checkpoint doc names the supported save structures and key offsets.
2. It explains how primary and secondary skills are decoded and validated.
3. It explicitly lists conditions that must return unavailable or partial
   combat context instead of guessing.

**Verification:**

1. Markdown review for private data leaks.
2. `git diff --check`

**Completion Notes:**

- Fill in after implementation.

---

### T15: Synthetic Hero Combat Fixtures

| Field | Value |
|---|---|
| Description | Add synthetic save fixtures that encode the observed current hero combat data patterns, including complete, partial, and unsupported cases. |
| Blocked By | T14 |
| Wave | hero-combat-parser |
| Execution | Main |
| Effort | M |
| Scope | Test |
| Source | Regression coverage |

**Files to modify:**

- `tests/test_h3_save_parser.py`
- `tests/test_battle_estimator_gui.py`
- Possibly test helper code already local to these files

**Acceptance Criteria:**

1. Fixtures cover a hero with current primary Attack/Defense/Spell Power/Knowledge.
2. Fixtures cover a hero with current secondary combat skills such as Offense,
   Armorer, and Archery.
3. Fixtures cover partial or unsupported structures without using real saves.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T16: Parse Hero Primary Skills

| Field | Value |
|---|---|
| Description | Extend save hero parsing with current primary skill values, using explicit confidence/status reporting. |
| Blocked By | T15 |
| Wave | hero-combat-parser |
| Execution | Main |
| Effort | M |
| Scope | Core |
| Source | Minimum useful combat estimator threshold |

**Files to modify:**

- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`
- `tools/battle_estimator_save_parsing_checkpoint.md`

**Acceptance Criteria:**

1. Parsed hero records can expose current Attack, Defense, Spell Power, and
   Knowledge when supported by the save structure.
2. Unsupported or ambiguous records return unavailable/partial status rather
   than starting-skill fallback values.
3. Existing hero army, position, owner color, hidden-target, and skill-state
   tests keep passing.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T17: Parse Hero Secondary Skills

| Field | Value |
|---|---|
| Description | Extend save hero parsing with current secondary skills and levels, with enough validation to support passive combat modifiers. |
| Blocked By | T16 |
| Wave | hero-combat-parser |
| Execution | Main |
| Effort | M |
| Scope | Core |
| Source | Offense/Armorer/Archery estimator integration |

**Files to modify:**

- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`
- `tools/battle_estimator_save_parsing_checkpoint.md`

**Acceptance Criteria:**

1. Parser returns current secondary skills and levels for supported records.
2. Skill IDs and levels are validated against known standard skill metadata.
3. Unsupported layouts produce a clear partial/unavailable status and do not
   fall back to VCMI starting skills.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_hero_skill_recommender`

**Completion Notes:**

- Fill in after implementation.

---

### T18: Build Combat Context Contract

| Field | Value |
|---|---|
| Description | Create a stable internal and serialized combat-context contract for parsed hero primary skills, secondary skills, passive modifiers, and per-side model status. |
| Blocked By | T17 |
| Wave | hero-combat-backend |
| Execution | Main |
| Effort | M |
| Scope | API/Core |
| Source | Estimator and GUI integration |

**Files to modify:**

- `tools/h3_save_parser.py`
- `tools/battle_estimator_gui.py`
- `tests/test_h3_save_parser.py`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Hero snapshots expose `combat_context` with status, source, primary skills,
   secondary skills, and passive modifier summary.
2. Status distinguishes unavailable, primary-only, primary+secondary, and
   partial context.
3. No combat context field claims save-derived data unless it came from the
   save parser.

**Verification:**

1. `python3 -m unittest tests.test_h3_save_parser`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T19: Apply Passive Combat Modifiers

| Field | Value |
|---|---|
| Description | Extend the battle estimator damage calculation to use parsed passive hero combat context for primary Attack/Defense and secondary Offense, Armorer, and Archery. |
| Blocked By | T18 |
| Wave | hero-combat-estimator |
| Execution | Main |
| Effort | M |
| Scope | Core |
| Source | Improved hero-vs-hero and hero-vs-neutral estimates |

**Files to modify:**

- `tools/battle_estimator.py`
- `tests/test_nearby_scan.py`
- `tests/test_battle_estimator_cli.py`
- Possibly `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Selected hero primary Attack/Defense affects estimates against neutral and
   hero targets when parsed.
2. Enemy hero primary Attack/Defense affects hero-vs-hero estimates when
   parsed.
3. Offense, Armorer, and Archery apply with VCMI-compatible passive damage
   factors and do not affect missing/unsupported contexts.

**Verification:**

1. `python3 -m unittest tests.test_nearby_scan`
2. `python3 -m unittest tests.test_battle_estimator_cli`
3. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T20: Expose Combat Model Notes

| Field | Value |
|---|---|
| Description | Include explicit combat model status in estimate payloads and CLI output so users can see which save-derived modifiers were applied or omitted. |
| Blocked By | T19 |
| Wave | hero-combat-api |
| Execution | Main |
| Effort | S |
| Scope | API/CLI |
| Source | Accuracy transparency |

**Files to modify:**

- `tools/battle_estimator.py`
- `tools/battle_estimator_gui.py`
- `tests/test_nearby_scan.py`
- `tests/test_battle_estimator_cli.py`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Estimate payloads include per-side statuses such as `army-only`,
   `primary-only`, and `primary+secondary`.
2. Payloads list applied and omitted model components separately from
   unsupported target notes.
3. CLI output keeps the existing limitation note but makes save-derived
   passive context visible when used.

**Verification:**

1. `python3 -m unittest tests.test_nearby_scan`
2. `python3 -m unittest tests.test_battle_estimator_cli`
3. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T21: Render Estimate Model Details

| Field | Value |
|---|---|
| Description | Show compact combat model details in the GUI estimate panel without cluttering the hero list. |
| Blocked By | T20 |
| Wave | hero-combat-frontend |
| Execution | Main |
| Effort | S |
| Scope | GUI |
| Source | User-facing transparency |

**Files to modify:**

- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Acceptance Criteria:**

1. Estimate results show a short model label such as `player primary+secondary,
   enemy army-only`.
2. Details expose parsed A/D and passive skill modifiers for each side when
   present.
3. Missing artifacts, active spells, morale/luck, and tactics are shown as
   omitted model components, not hidden assumptions.

**Verification:**

1. `node --check tools/battle_estimator_gui/app.js`
2. `python3 -m unittest tests.test_battle_estimator_gui`
3. Manual GUI check that the estimate panel stays compact at desktop and
   narrow widths.

**Completion Notes:**

- Fill in after implementation.

---

### T22: Hero Combat Docs And Verification

| Field | Value |
|---|---|
| Description | Update docs for save-derived hero combat context and run the full relevant verification suite. |
| Blocked By | T21 |
| Wave | hero-combat-quality |
| Execution | Main |
| Effort | S |
| Scope | Docs/Test |
| Source | Public behavior change |

**Files to modify:**

- `README.md`
- `CHANGELOG.md`
- `AGENTS.md`
- `tools/battle_estimator_save_parsing_checkpoint.md`
- This planning doc

**Acceptance Criteria:**

1. README explains which hero combat data is save-derived and which model
   components remain omitted.
2. CHANGELOG records improved hero-vs-hero and hero-vs-neutral estimates.
3. Save parsing checkpoint documents supported combat-context structures and
   unsupported variants.

**Verification:**

1. `python3 -m unittest`
2. `node --check tools/battle_estimator_gui/app.js`
3. `git status --short` confirms no real save/map files are staged.

**Completion Notes:**

- Fill in after implementation.

---

## Checkpoints

### Checkpoint: Priority Map UX Ready

- [ ] M01 through M07 are `done`.
- [ ] Neutral marker draw and hit priority no longer obscures towns, portals,
      or heroes.
- [ ] Normal-mode subterranean gate clicks switch to the paired level while
      Path mode remains route-first.
- [ ] Cross-level portal destinations can be inspected through ghost markers
      and level badges for the active relation.
- [ ] Dual-level view works as an optional two-level map mode, while
      single-level view remains the default.

### Checkpoint: Research Ready

- [ ] T01 and T02 are `done`.
- [ ] Current town ownership hypothesis is documented.
- [ ] No private saves, private map files, or local absolute save paths are in
      the working tree.
- [ ] The parser approach has at least one planned unavailable/ambiguous case.

### Checkpoint: Parser Ready

- [ ] T03, T04, and T05 are `done`.
- [ ] Synthetic fixtures prove captured-town ownership, unowned/unknown towns,
      and join behavior.
- [ ] `/api/state` can expose save-derived current owner fields without
      changing `initial_owner` semantics.

### Checkpoint: Backend Alerts Ready

- [ ] T06, T07, and T08 are `done`.
- [ ] Alert service returns correct statuses and threat lists from synthetic
      snapshots.
- [ ] Existing scan and pathfinding API tests still pass.

### Checkpoint: GUI Ready

- [ ] T09, T10, and T11 are `done`.
- [ ] Alerts are visible without selecting a hero.
- [ ] Alert controls and rows fit compact sidebars.
- [ ] Alert clicks center and activate the enemy hero marker.

### Checkpoint: Hero Combat Research Ready

- [ ] T13 and T14 are `done`.
- [ ] Current hero combat data hypothesis is documented.
- [ ] The hypothesis covers primary skills, secondary skills, and explicitly
      marks artifacts, spellbook, mana, experience, level, and specialty data
      as supported, unsupported, or observed-but-not-modeled.
- [ ] No private saves, private map files, or local absolute save paths are in
      the working tree.

### Checkpoint: Hero Combat Parser Ready

- [ ] T15, T16, T17, and T18 are `done`.
- [ ] Synthetic fixtures prove complete, partial, and unsupported hero combat
      contexts.
- [ ] Hero snapshots expose combat context without using VCMI starting skills
      or manually maintained recommendation state.

### Checkpoint: Passive Combat Estimator Ready

- [ ] T19, T20, and T21 are `done`.
- [ ] Save-derived primary Attack/Defense affect neutral and hero estimates
      when available.
- [ ] Save-derived Offense, Armorer, and Archery affect estimates only when
      current secondary skills are parsed.
- [ ] GUI estimate details clearly label applied and omitted model components.

### Checkpoint: Complete

- [ ] M07 is `done`.
- [ ] T12 is `done`.
- [ ] T22 is `done`.
- [ ] Full Python suite passes.
- [ ] JavaScript syntax check passes.
- [ ] Manual GUI check has been recorded in completion notes.
- [ ] Real save files remain excluded from the repository.

## Risks And Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Current town ownership structure differs across GM1/GM2, hotseat, or map versions. | High | Start with observed supported structures, expose `ownership_unavailable` when confidence is low, and document support limits. |
| Parser falsely assigns a captured town to the wrong player. | High | Require exact coordinate/object joins and synthetic regression tests; do not fallback to `initial_owner`. |
| Local real saves leak into the repo. | High | Keep research local, commit only synthetic fixtures, and run `git status --short` before completion. |
| Alert list creates noise in 2v2 games. | Medium | Default to `My color` towns only and same-team enemy exclusion; add ally-town toggle only in a later task if needed. |
| Alert radius conflicts with scan radius mental model. | Medium | Use separate `Alert radius` but same distance metric; label controls clearly. |
| Frontend sidebars become too crowded. | Medium | Add a compact `Alerts` section with terse rows and diagnostic states; avoid extra map modes in MVP. |
| Save-derived ownership is partially parsed. | Medium | Surface a diagnostic status instead of quietly treating missing records as no threat. |
| Hero combat data layout differs from the currently parsed hero army structure. | High | Research linked records before implementation, support only confirmed layouts, and expose unavailable/partial status for the rest. |
| Parser falsely assigns primary or secondary skills to the wrong hero. | High | Validate names, offsets, ownership, position, and army linkage together before emitting save-derived combat context. |
| Partial hero combat modeling looks more exact than it is. | Medium | Include per-side model status and applied/omitted components in API, CLI, and GUI estimate details. |
| Artifacts or spells are discovered in the save but not modeled initially. | Medium | Record them as unsupported or observed-but-omitted; do not silently include their effects until dedicated tasks model them. |
| Enemy hero context is unavailable more often than player hero context. | Medium | Allow asymmetric estimates, e.g. player `primary+secondary` versus enemy `army-only`, and make that visible. |
| Dual-level view destabilizes existing single-level map interactions. | High | Keep single-level as default, build explicit geometry helpers, and test both modes. |
| Ghost portal destinations imply that the destination is physically on the current level. | Medium | Use reduced alpha and level badges on every off-level ghost marker. |
| Subterranean click-to-toggle conflicts with Path mode. | High | Apply click-to-toggle only outside Path mode; Path mode left-click remains route request. |
| Marker priority change hides useful neutral target scan information. | Medium | Lower neutral draw/hit priority but keep scan rings and scan result rows as the main neutral-target discovery surface. |
| Dual-level shared pan/zoom feels awkward on very wide maps. | Medium | Ship as an optional mode and keep the existing single-level view available. |

## Open Questions

- Which exact real save examples will be used for parser research?
- Does the observed save ownership record include stable town object identity,
  coordinates, or only list ordering?
- Are random town/current faction changes relevant to alert display, or only
  current owner color?
- Should a later iteration add an `Include allied towns` toggle?
- Should a later iteration add pathfinding-based "reachable threat" alerts
  using portals and route layers?
- Which real saves have known hero primary skills and secondary skills for
  validating parser offsets?
- Can hero primary/secondary skill records be linked exactly to the same save
  hero record that already provides army, position, and owner color?
- Are enemy hero combat fields available for all detected visible heroes, or
  only for the current player and previously observed heroes?
- If artifacts or spellbook data are parsed later, which extra VCMI config
  files are needed for truthful modeling and attribution?

## Summary Table

| ID | Title | Status | Blocked By | Wave | Execution | Effort | Scope | Files Likely Touched |
|---|---|---|---|---|---|---|---|---|
| M01 | Lower Monster Marker Priority | done | -- | priority-map-ux | Parallel | S | GUI | `tools/battle_estimator_gui/app.js`, GUI tests |
| M02 | Subterranean Gate Click Level Toggle | done | -- | priority-map-ux | Parallel | S | GUI | `tools/battle_estimator_gui/app.js`, GUI tests |
| M03 | Cross-Level Ghost Portal Destinations | done | M02 | priority-map-ux | Main | M | GUI | `app.js`, `style.css`, GUI tests |
| M04 | Dual-Level View State And Geometry | done | -- | priority-map-ux | Main | M | GUI | `index.html`, `app.js`, `style.css`, GUI tests |
| M05 | Render Dual-Level Map And Markers | done | M04 | priority-map-ux | Main | M | GUI | `app.js`, `style.css`, GUI tests |
| M06 | Dual-Level Interactions And Portal Links | done | M03, M05 | priority-map-ux | Main | M | GUI | `app.js`, `style.css`, GUI tests |
| M07 | Map UX Follow-Up Verification | done | M01, M02, M03, M04, M05, M06 | priority-map-ux | Main | S | Docs/Test | `README.md`, `CHANGELOG.md`, planning doc |
| T01 | Collect Local Save Evidence | done | -- | research | Main | M | Research | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T02 | Document Save Ownership Hypothesis | done | T01 | research | Main | S | Docs | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T03 | Synthetic Current Town Ownership Fixtures | done | T02 | parser | Main | M | Test | `tests/test_h3_save_parser.py`, `tests/test_battle_estimator_gui.py` |
| T04 | Parse Current Town Ownership | done | T03 | parser | Main | M | Core | `tools/h3_save_parser.py`, `tests/test_h3_save_parser.py` |
| T05 | Join Save Ownership To H3M Town Targets | done | T04 | backend | Main | M | API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T06 | Persist My Color And Alert Radius | done | -- | backend | Parallel | S | Config | `tools/h3_save_parser.py`, `tools/battle_estimator_gui.py`, tests |
| T07 | Build Threat Alert Service | done | T05, T06 | backend | Main | M | Core/API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T08 | Expose Snapshot Contract | done | T07 | backend | Main | S | API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T09 | Render My Color And Alert Radius Controls | todo | T08 | frontend | Parallel | M | GUI | `index.html`, `app.js`, `style.css`, GUI tests |
| T10 | Render Alerts Sidebar Section | todo | T08 | frontend | Parallel | M | GUI | `index.html`, `app.js`, `style.css`, GUI tests |
| T11 | Center And Activate Alert Target | blocked | T10 | frontend | Main | S | GUI | `app.js`, `style.css`, GUI tests |
| T12 | Docs And Verification Pass | blocked | T08, T09, T10, T11 | quality | Main | S | Docs/Test | `README.md`, `CHANGELOG.md`, `AGENTS.md` |
| T13 | Research Save Hero Combat Data | todo | -- | hero-combat-research | Main | M | Research | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T14 | Document Hero Combat Data Hypothesis | blocked | T13 | hero-combat-research | Main | S | Docs | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T15 | Synthetic Hero Combat Fixtures | blocked | T14 | hero-combat-parser | Main | M | Test | `tests/test_h3_save_parser.py`, `tests/test_battle_estimator_gui.py` |
| T16 | Parse Hero Primary Skills | blocked | T15 | hero-combat-parser | Main | M | Core | `tools/h3_save_parser.py`, `tests/test_h3_save_parser.py` |
| T17 | Parse Hero Secondary Skills | blocked | T16 | hero-combat-parser | Main | M | Core | `tools/h3_save_parser.py`, `tests/test_h3_save_parser.py` |
| T18 | Build Combat Context Contract | blocked | T17 | hero-combat-backend | Main | M | API/Core | `tools/h3_save_parser.py`, `tools/battle_estimator_gui.py`, tests |
| T19 | Apply Passive Combat Modifiers | blocked | T18 | hero-combat-estimator | Main | M | Core | `tools/battle_estimator.py`, estimator tests |
| T20 | Expose Combat Model Notes | blocked | T19 | hero-combat-api | Main | S | API/CLI | `tools/battle_estimator.py`, `tools/battle_estimator_gui.py`, tests |
| T21 | Render Estimate Model Details | blocked | T20 | hero-combat-frontend | Main | S | GUI | `app.js`, `style.css`, GUI tests |
| T22 | Hero Combat Docs And Verification | blocked | T21 | hero-combat-quality | Main | S | Docs/Test | `README.md`, `CHANGELOG.md`, `AGENTS.md`, checkpoint doc |
