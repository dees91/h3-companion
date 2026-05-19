# Phase 3: Battle Estimator Local GUI - Task Breakdown

> **Source**: `grill-me` planning session on 2026-05-19.
> This plan adds a local browser GUI on top of the existing autosave, H3M map,
> nearby scan, and battle-estimation code.
>
> **Related**:
> [Battle Estimator Autosave Brief](./battle-estimator-autosave-brief.md),
> [Phase 1 Autosave MVP Tasks](./phase-1-battle-estimator-autosave-mvp-tasks.md),
> [Phase 2 Nearby Scan Tasks](./phase-2-battle-estimator-nearby-scan-tasks.md),
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
> 5. **Before marking `done`**: run task-specific verification plus the broadest
>    relevant Python verification available at that point.
>
> Status values: `todo` = ready to pick up | `in-progress` = being worked on |
> `done` = completed | `blocked` = waiting on dependencies

---

## Goal

Build a local read-only GUI for the battle estimator:

- display the current map as a simple tile grid,
- show hero and neutral monster markers on that grid,
- choose a "my hero" from a searchable hero list with recent selections,
- click a monster or other hero on the map to run a single battle estimate,
- run the existing nearby-radius scan and visualize who can be beaten,
- follow the latest autosave by default,
- allow pinning a manually selected save,
- refresh automatically when a newer/latest save appears.

Target startup:

```bash
python3 tools/battle_estimator_gui.py
```

The server prints a local URL, for example:

```text
http://127.0.0.1:8765
```

## Product Decisions

- GUI is a local browser app served by a Python backend.
- Backend remains Python and reuses the existing parser and estimator modules.
- Frontend is plain HTML/CSS/JavaScript unless implementation finds a strong
  reason for a dependency.
- Use `<canvas>` for the map grid and markers.
- Render the full current map with pan and zoom, not only a local viewport.
- Map shows only heroes and neutral monsters on a neutral tile grid.
- Do not render terrain, roads, obstacles, fog of war, pathfinding, ownership,
  or passability in MVP.
- Selected hero remains selected while clicking multiple targets.
- Clicking a target runs one estimate: selected hero vs clicked target.
- Radius scan uses the same model as CLI `--scan-nearby`.
- Radius scan results are shown both as marker coloring on the map and as a
  side list sorted by distance.
- Default mode follows the latest numeric save in the selected autosave folder.
- Manual save selection switches to pinned-save mode.
- Pinned-save mode does not jump to newer saves until the user returns to
  follow-latest mode.
- Recent heroes are persisted in the existing user config alongside
  `last_hero`.
- Hero list includes all detected heroes. Do not filter "my heroes" by owner or
  team in MVP.
- GUI is read-only toward `.GM1`, `.GM2`, and `.h3m` files.

## Architecture Decisions

### Local Web App

Use a small local HTTP server in `tools/battle_estimator_gui.py`, serving static
files from:

```text
tools/battle_estimator_gui/
```

Expected static files:

```text
tools/battle_estimator_gui/index.html
tools/battle_estimator_gui/app.js
tools/battle_estimator_gui/style.css
```

Recommended backend implementation for MVP:

- Python standard library `http.server.ThreadingHTTPServer`
- JSON endpoints implemented in the request handler
- no Flask/FastAPI dependency unless the stdlib version becomes painful

This keeps the GUI portable inside the current repo and avoids adding project
dependency management before it is needed.

### Reuse Existing Domain Code

Do not duplicate scan or simulation logic in the GUI. Reuse:

- `tools/h3_save_parser.py`
- `tools/h3_map_parser.py`
- `tools/battle_estimator.py`
  - `build_nearby_scan_targets()`
  - `estimate_nearby_scan_targets()`
  - existing hero selection and save/map resolution helpers where practical

If CLI helpers are currently private but useful, extract small public service
functions rather than importing deeply coupled CLI print functions.

### Stable Target IDs

The frontend must not infer target identity from labels or table row indexes.
Backend should emit stable IDs:

```text
hero:<source_offset-or-normalized-identity>
neutral:<h3m_object_index>
```

The exact hero ID can be adjusted during implementation, but it must survive
refreshes where possible and be unambiguous within a loaded save snapshot.

### Snapshot Model

The GUI should work from a "state snapshot" object:

- selected game folder,
- current save file,
- save mode: `follow_latest` or `pinned`,
- current map file,
- map size and levels,
- heroes with positions and armies,
- neutral monster targets with positions, counts, names, removed flag,
- selected hero,
- recent heroes,
- current file fingerprint for refresh checks.

Auto-refresh should compare lightweight save metadata first, for example:

```text
save path + size + mtime
```

Only reload and reparse when that fingerprint changes or when the selected save
mode changes.

### Config Extension

Current config supports:

```json
{
  "autosave_dir": "...",
  "last_hero": "Isra"
}
```

Extend it with:

```json
{
  "recent_heroes": ["Isra", "Marius", "Aenain"]
}
```

Rules:

- preserve backward compatibility with missing `recent_heroes`,
- keep `last_hero` for CLI wizard compatibility,
- update both `last_hero` and `recent_heroes` when GUI selects a hero,
- cap recent heroes to a small number, recommended 8.

### GUI Visual Design

This is an operational tool, not a landing page.

Use a dense, utilitarian layout:

- top/status bar for save mode, save file, map file, refresh state,
- left panel for hero search and recent heroes,
- central full-height canvas map,
- right panel for target details, single simulation result, and radius scan
  results.

Avoid marketing-style sections. The first screen should be the working map UI.

## Proposed JSON API

The exact shape can change during implementation, but the frontend/backend
contract should stay close to this.

### `GET /api/state`

Returns the current snapshot:

```json
{
  "mode": "follow_latest",
  "autosave_dir": "/path/to/game/folder",
  "save_file": "/path/to/417.GM2",
  "save_fingerprint": {
    "path": "/path/to/417.GM2",
    "size": 123456,
    "mtime": 1770000000.0
  },
  "map_file": "/path/to/map.h3m",
  "map": { "width": 108, "height": 108, "levels": 2 },
  "selected_hero_id": "hero:783079",
  "recent_heroes": ["Isra"],
  "heroes": [],
  "neutral_targets": []
}
```

### `GET /api/saves`

Returns eligible numeric `.GM1` / `.GM2` saves in the current game folder.

### `POST /api/select-hero`

Body:

```json
{ "hero_id": "hero:783079" }
```

Updates runtime selected hero and persists `last_hero` / `recent_heroes`.

### `POST /api/save-mode`

Body examples:

```json
{ "mode": "follow_latest" }
{ "mode": "pinned", "save_file": "/path/to/415.GM2" }
```

Switches snapshot source.

### `POST /api/simulate-target`

Body:

```json
{
  "hero_id": "hero:783079",
  "target_id": "neutral:2330",
  "simulations": 500
}
```

Returns one compact estimate.

### `POST /api/scan-radius`

Body:

```json
{
  "hero_id": "hero:783079",
  "radius": 10,
  "target_type": "all",
  "include_removed": false,
  "simulations": 500
}
```

Returns distance-sorted scan estimates.

## Dependency Graph

```text
Phase 3 Local GUI

  Backend foundation:
    GUI-T01 [GUI Server + Static Asset Skeleton]
      -> GUI-T02 [Snapshot Builder Service]
      -> GUI-T03 [Config Recent Heroes]
      -> GUI-T04 [JSON API Endpoints]

  Frontend foundation:
    GUI-T01 -> GUI-T05 [Frontend Layout Shell]
    GUI-T04, GUI-T05 -> GUI-T06 [Canvas Map Rendering]
    GUI-T03, GUI-T04, GUI-T05 -> GUI-T07 [Hero Search + Recent Selection]

  User workflows:
    GUI-T04, GUI-T06, GUI-T07 -> GUI-T08 [Click Target Simulation]
    GUI-T04, GUI-T06, GUI-T07 -> GUI-T09 [Radius Scan Visualization]
    GUI-T02, GUI-T04, GUI-T05 -> GUI-T10 [Save Picker + Auto Refresh]

  Quality:
    GUI-T08, GUI-T09, GUI-T10 -> GUI-T11 [End-to-End Polish + Docs]
```

**Parallelism:** After GUI-T01 defines the static asset paths and basic server,
GUI-T02/GUI-T03 can be implemented in parallel with GUI-T05. GUI-T08 and
GUI-T09 share frontend state and should start only after target IDs and API
payloads are stable.

---

## Task Definitions

### GUI-T01: GUI Server + Static Asset Skeleton

| Field | Value |
|---|---|
| Description | Add the local GUI entrypoint and static asset directory. The server should serve the frontend and expose a minimal health endpoint without adding heavy dependencies. |
| Blocked By | -- |
| Wave | foundation |
| Execution | Main |
| Effort | S |
| Scope | Backend/Frontend skeleton |

**Files likely touched:**
- New: `tools/battle_estimator_gui.py`
- New: `tools/battle_estimator_gui/index.html`
- New: `tools/battle_estimator_gui/app.js`
- New: `tools/battle_estimator_gui/style.css`
- New or existing tests under `tests/`

**Acceptance Criteria:**
1. `python3 tools/battle_estimator_gui.py` starts a localhost server and prints
   the URL.
2. Static `index.html`, `app.js`, and `style.css` are served correctly.
3. `GET /api/health` returns JSON `{ "ok": true }` or equivalent.
4. The server binds to localhost only by default.
5. Existing CLI behavior remains unchanged.

**Verification:**
1. Unit or integration smoke test for `GET /api/health`.
2. Manual check opens the printed URL and loads the static shell.
3. Run `python3 tools/battle_estimator.py --help`.

**Completion Notes (2026-05-19):**
- Added `tools/battle_estimator_gui.py` using stdlib `ThreadingHTTPServer`.
- Added whitelisted static routes for `/`, `/index.html`, `/app.js`, and
  `/style.css`, plus JSON `GET /api/health`.
- Added static GUI shell files under `tools/battle_estimator_gui/`.
- Verified with `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest discover -s tests`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and an
  entrypoint smoke test using `--port 0`.

---

### GUI-T02: Snapshot Builder Service

| Field | Value |
|---|---|
| Description | Build a backend service that resolves the active save/map, parses heroes and neutral monsters, applies removed-neutral filtering metadata, and returns a JSON-serializable snapshot. |
| Blocked By | GUI-T01 |
| Wave | backend |
| Execution | Main or Worker |
| Effort | M |
| Scope | Backend |

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- possibly small service helpers extracted from `tools/battle_estimator.py`
- tests

**Acceptance Criteria:**
1. Snapshot supports follow-latest mode using existing autosave selection rules.
2. Snapshot supports pinned-save mode with an explicit save file.
3. Snapshot includes save path, map path, map dimensions, heroes, neutral
   targets, and file fingerprint.
4. Snapshot serializes positions as `{ "x": n, "y": n, "z": n }`.
5. Snapshot does not mutate save or map files.

**Verification:**
1. Unit tests with synthetic save/map fixtures where possible.
2. Manual local check loads the latest Diamond save and matching `.h3m`.

**Completion Notes (2026-05-19):**
- Added `build_state_snapshot()` with `follow_latest` and `pinned` save modes.
- Snapshot resolution reuses public save/map parser helpers, emits stable hero
  and neutral IDs, JSON-safe positions, save/map fingerprints, map dimensions,
  hero armies, and neutral target removal metadata.
- Snapshot captures save/map fingerprints before parsing and rejects files that
  change while the snapshot is being built.
- Verified with `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest discover -s tests`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and a
  standalone synthetic snapshot smoke test.

---

### GUI-T03: Config Recent Heroes

| Field | Value |
|---|---|
| Description | Extend the user config with recent hero tracking while preserving current `autosave_dir` and `last_hero` behavior. |
| Blocked By | -- |
| Wave | backend |
| Execution | Main or Worker |
| Effort | S |
| Scope | Config |

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`

**Acceptance Criteria:**
1. Missing `recent_heroes` loads as an empty tuple/list.
2. Selecting a hero updates `last_hero`.
3. Selecting a hero moves it to the front of `recent_heroes`.
4. Recent heroes are deduplicated case-insensitively.
5. Recent heroes are capped, recommended cap: 8.
6. Existing config tests still pass.

**Verification:**
1. Unit tests for loading old config without `recent_heroes`.
2. Unit tests for adding, deduping, ordering, and capping recent heroes.

**Completion Notes (2026-05-19):**
- Extended `BattleEstimatorConfig` with backward-compatible
  `recent_heroes`.
- Added `set_config_selected_hero()` for GUI selections while preserving
  existing CLI `set_config_last_hero()` behavior.
- Recent heroes are stripped, deduplicated case-insensitively on selection,
  moved to the front, and capped at `RECENT_HERO_LIMIT` (8).
- Verified with `python3 -m unittest tests.test_h3_save_parser`,
  `python3 -m unittest discover -s tests`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and a
  standalone config helper smoke test.

---

### GUI-T04: JSON API Endpoints

| Field | Value |
|---|---|
| Description | Implement the backend JSON API used by the frontend: state, saves, hero selection, save mode, single target simulation, and radius scan. |
| Blocked By | GUI-T02, GUI-T03 |
| Wave | backend |
| Execution | Main |
| Effort | M |
| Scope | Backend API |

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- tests

**Acceptance Criteria:**
1. `GET /api/state` returns the current snapshot.
2. `GET /api/saves` returns numeric `.GM1` / `.GM2` saves for the active game
   folder.
3. `POST /api/select-hero` validates hero ID and persists recent hero config.
4. `POST /api/save-mode` supports `follow_latest` and pinned save mode.
5. `POST /api/simulate-target` returns one compact estimate.
6. `POST /api/scan-radius` returns distance-sorted estimates.
7. API errors return JSON with a useful message and appropriate HTTP status.

**Verification:**
1. Endpoint tests with synthetic or monkeypatched snapshot services.
2. Invalid JSON and invalid target/hero IDs are covered.

**Completion Notes (2026-05-19):**
- Added JSON API endpoints for state, saves, hero selection, save mode,
  single-target simulation, and radius scan.
- Added `GuiAppState` runtime settings and raw `DomainSnapshot` handling so API
  simulation endpoints reuse existing battle-estimator domain helpers instead
  of dict-only snapshot data.
- API responses use JSON errors for validation failures, invalid JSON, stale
  selected heroes, snapshot consistency conflicts, and unknown API paths.
- Save listing and follow-latest ignore numeric symlinks; pinned save mode is
  restricted to non-symlink numeric saves in the active autosave folder.
- Verified with `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest discover -s tests`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and a
  standalone HTTP API smoke test for `/api/state` and `/api/saves`.

---

### GUI-T05: Frontend Layout Shell

| Field | Value |
|---|---|
| Description | Build the first usable screen: status bar, hero panel, central canvas area, and right-side result panel. No complex rendering yet. |
| Blocked By | GUI-T01 |
| Wave | frontend |
| Execution | Main or Worker |
| Effort | M |
| Scope | Frontend |

**Files likely touched:**
- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/style.css`
- `tools/battle_estimator_gui/app.js`

**Acceptance Criteria:**
1. First viewport is the working app UI, not a landing page.
2. Layout has a top status area, left hero/search panel, central canvas, and
   right result/scan panel.
3. The UI is dense and utilitarian, with no decorative hero sections.
4. Text does not overflow compact controls at common desktop widths.
5. Empty/loading/error states are visible and concise.

**Verification:**
1. Manual browser check at desktop size.
2. Static file load check through the local server.

**Completion Notes (2026-05-19):**
- Rebuilt the static frontend as a dense operational shell with top snapshot
  status, left hero/search panel, central canvas stage, and right result/scan
  panel.
- Added loading, empty, and snapshot-error states without implementing
  selection, pan/zoom, marker hit testing, polling, or save picker workflows.
- Frontend uses `/api/health` only for server health and `/api/state` for
  snapshot display; snapshot errors do not mark the local server unavailable.
- Verified with `python3 -m unittest tests.test_battle_estimator_gui`,
  `python3 -m unittest discover -s tests`,
  `python3 tools/battle_estimator.py --help`, `git diff --check`, and a
  local static-shell HTTP smoke test.

---

### GUI-T06: Canvas Map Rendering

| Field | Value |
|---|---|
| Description | Render the map grid and object markers on canvas, with pan, zoom, marker hit testing, selected hero highlight, and basic tooltip/details. |
| Blocked By | GUI-T04, GUI-T05 |
| Wave | frontend |
| Execution | Main |
| Effort | M |
| Scope | Frontend |

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- maybe frontend fixture/test helpers

**Acceptance Criteria:**
1. Canvas renders full map dimensions from `/api/state`.
2. Pan and zoom work without layout shifts.
3. Hero markers and neutral monster markers are visually distinct.
4. Selected hero marker is highlighted.
5. Removed/unsupported neutral targets have distinct visual treatment or are
   hidden according to snapshot/API choice.
6. Clicking a marker identifies its stable target ID.

**Verification:**
1. Manual check with a real local save/map.
2. Marker hit testing can be unit-tested in JS if helper functions are pure.

---

### GUI-T07: Hero Search + Recent Selection

| Field | Value |
|---|---|
| Description | Implement the hero selection workflow in the left panel: search, full hero list, recent heroes, selection persistence, and map centering. |
| Blocked By | GUI-T03, GUI-T04, GUI-T05 |
| Wave | frontend |
| Execution | Main or Worker |
| Effort | M |
| Scope | Frontend/API |

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tools/battle_estimator_gui.py`
- tests

**Acceptance Criteria:**
1. Search filters heroes by name case-insensitively.
2. Recent heroes are shown above or near the full list.
3. Selecting a hero calls `/api/select-hero`.
4. Selected hero is persisted as `last_hero` and appears in recent heroes.
5. Map recenters on selected hero when position is available.
6. No owner/team filtering is attempted.

**Verification:**
1. API test for select-hero persistence.
2. Manual browser check for search, selection, recent list, and recentering.

---

### GUI-T08: Click Target Simulation

| Field | Value |
|---|---|
| Description | Wire marker clicks to single-target simulation. The selected hero remains fixed while the user clicks multiple targets. |
| Blocked By | GUI-T04, GUI-T06, GUI-T07 |
| Wave | workflow |
| Execution | Main |
| Effort | M |
| Scope | Frontend/API |

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tools/battle_estimator_gui.py`
- tests

**Acceptance Criteria:**
1. Clicking a neutral monster runs selected hero vs that monster.
2. Clicking another hero runs selected hero vs that hero's army.
3. Result panel shows target, distance, armies, enemy AI value, win percentage,
   and note/verdict.
4. Unsupported targets show a clear note instead of crashing.
5. Selected hero does not change after target clicks.

**Verification:**
1. API test for `/api/simulate-target`.
2. Manual browser check clicking several targets in sequence.

---

### GUI-T09: Radius Scan Visualization

| Field | Value |
|---|---|
| Description | Add radius scan controls and visualize scan results on both the canvas and side list. Use the same backend model as CLI `--scan-nearby`. |
| Blocked By | GUI-T04, GUI-T06, GUI-T07 |
| Wave | workflow |
| Execution | Main |
| Effort | M |
| Scope | Frontend/API |

**Files likely touched:**
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tools/battle_estimator_gui.py`
- tests

**Acceptance Criteria:**
1. User can set radius and target type (`all`, `neutral`, `hero`).
2. Scan calls `/api/scan-radius`.
3. Results list is sorted by distance.
4. Canvas markers are colored by win percentage or unsupported status.
5. Clicking a scan result centers/selects the target and shows details.
6. Scan uses default fast simulation count, with an option to override if
   exposed in UI.

**Verification:**
1. API test for `/api/scan-radius`.
2. Manual browser check for marker coloring and result-list navigation.

---

### GUI-T10: Save Picker + Auto Refresh

| Field | Value |
|---|---|
| Description | Implement follow-latest refresh and pinned-save selection. The GUI should update when a newer/latest save appears, but pinned mode should remain stable. |
| Blocked By | GUI-T02, GUI-T04, GUI-T05 |
| Wave | workflow |
| Execution | Main |
| Effort | M |
| Scope | Backend/Frontend |

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- tests

**Acceptance Criteria:**
1. Status bar shows current mode: follow latest or pinned save.
2. Save list can be loaded from `/api/saves`.
3. Choosing a save switches to pinned mode.
4. A "Follow latest" control switches back to follow-latest mode.
5. Auto-refresh checks save fingerprint at an interval, recommended default:
   5 seconds.
6. In follow-latest mode, newer numeric save selection reloads the snapshot.
7. In pinned mode, newer saves do not replace the active snapshot.
8. Refresh preserves selected hero by stable ID or by unambiguous hero name when
   possible.

**Verification:**
1. Unit tests for backend save-mode state.
2. Manual test by switching pinned/follow modes and adding or selecting saves.

---

### GUI-T11: End-to-End Polish + Docs

| Field | Value |
|---|---|
| Description | Finish the MVP loop, document usage and limitations, and run focused verification. |
| Blocked By | GUI-T08, GUI-T09, GUI-T10 |
| Wave | quality |
| Execution | Main |
| Effort | S |
| Scope | Docs/Tests |

**Files likely touched:**
- `planning/phase-3-battle-estimator-gui-tasks.md`
- `planning/battle-estimator-autosave-brief.md`
- possibly `tools/battle_estimator_save_parsing_checkpoint.md`

**Acceptance Criteria:**
1. Usage docs include starting the GUI and opening the local URL.
2. Limitations are documented:
   read-only, no terrain/pathfinding/FoW, all heroes listed, army-only hero
   simulation, `.h3m` base neutral counts.
3. Summary Table statuses are current.
4. Manual verification with a real local save/map is recorded.
5. No real save/map files are committed.

**Verification:**
1. Run parser tests.
2. Run CLI scan tests.
3. Run GUI backend/API tests.
4. Run `python3 tools/battle_estimator.py --help`.
5. Start `python3 tools/battle_estimator_gui.py` and manually exercise:
   hero selection, target click simulation, radius scan, pinned save, and
   follow-latest mode.

---

## Checkpoints

### Checkpoint: Backend Contract

After GUI-T01 through GUI-T04:

- [ ] Local GUI server starts.
- [ ] `/api/state` returns a complete snapshot.
- [ ] `/api/simulate-target` and `/api/scan-radius` work from JSON.
- [ ] Recent hero config is backward-compatible.

### Checkpoint: Interactive Map

After GUI-T05 through GUI-T08:

- [ ] Canvas map loads and displays markers.
- [ ] Hero search and recent selection work.
- [ ] Clicking a target runs a single simulation.

### Checkpoint: MVP Complete

After GUI-T09 through GUI-T11:

- [ ] Radius scan is visualized on map and list.
- [ ] Follow-latest and pinned-save modes work.
- [ ] Docs and tests are updated.
- [ ] The GUI is ready for real multiplayer use as a read-only assistant.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Browser UI drifts from CLI scan behavior | High | Reuse `build_nearby_scan_targets()` and `estimate_nearby_scan_targets()`; keep frontend as display/control layer only. |
| Target identity breaks after refresh | High | Emit stable target IDs and preserve selected hero by ID or unambiguous name fallback. |
| Auto-refresh changes context while user analyzes a pinned save | Medium | Explicit follow-latest vs pinned modes; never auto-switch when pinned. |
| Large map rendering becomes sluggish | Medium | Use canvas, not per-tile DOM; draw only visible canvas area when needed. |
| Local server exposes data on the network | Medium | Bind to `127.0.0.1` by default. |
| GUI mutates config unexpectedly | Low | Only persist `last_hero` and `recent_heroes` on explicit hero selection. |
| New frontend becomes hard to test | Medium | Keep JS state and hit-testing helpers pure where practical; test backend API separately. |

## Non-Goals

- Editing save files or map files.
- Sending actions to the game or Porting Kit.
- Rendering terrain, roads, obstacles, passability, or fog of war.
- Full pathfinding or movement-point calculation.
- Owner/team detection and filtering.
- Full hero stat/spell/artifact battle modeling.
- Multi-user remote server deployment.
- A polished packaged macOS app.

## Open Questions

No blocking product questions remain from the 2026-05-19 `grill-me` session.
Implementation may still uncover technical choices around stdlib HTTP handler
structure and frontend test strategy.

## Summary Table

| Task | Status | Blocked By | Owner | Notes |
|---|---|---|---|---|
| GUI-T01: GUI Server + Static Asset Skeleton | done | -- | Codex | Local stdlib server, static shell, and health endpoint added. |
| GUI-T02: Snapshot Builder Service | done | GUI-T01 | Codex | Snapshot builder supports follow-latest, pinned saves, map dimensions, heroes, neutrals, and fingerprints. |
| GUI-T03: Config Recent Heroes | done | -- | Codex | Config now tracks capped, deduped recent heroes for GUI selections. |
| GUI-T04: JSON API Endpoints | done | GUI-T02, GUI-T03 | Codex | JSON API endpoints added with state, saves, selection, mode, simulation, scan, and JSON errors. |
| GUI-T05: Frontend Layout Shell | done | GUI-T01 | Codex | Dense operational shell with status bar, hero panel, canvas stage, and result/scan panel. |
| GUI-T06: Canvas Map Rendering | todo | GUI-T04, GUI-T05 | unassigned | Full map grid, pan, zoom, markers. |
| GUI-T07: Hero Search + Recent Selection | todo | GUI-T03, GUI-T04, GUI-T05 | unassigned | Search/recent/select workflow. |
| GUI-T08: Click Target Simulation | blocked | GUI-T04, GUI-T06, GUI-T07 | unassigned | Single target estimate. |
| GUI-T09: Radius Scan Visualization | blocked | GUI-T04, GUI-T06, GUI-T07 | unassigned | Scan overlay and result list. |
| GUI-T10: Save Picker + Auto Refresh | blocked | GUI-T02, GUI-T04, GUI-T05 | unassigned | Follow latest and pinned save. |
| GUI-T11: End-to-End Polish + Docs | blocked | GUI-T08, GUI-T09, GUI-T10 | unassigned | Final verification pass. |
