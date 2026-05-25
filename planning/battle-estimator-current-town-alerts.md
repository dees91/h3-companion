# Battle Estimator Current Town Alerts - Task Breakdown

> **Source**: planning discussion on 2026-05-25.
>
> This plan adds save-derived current town ownership, a player color setting,
> and defensive alerts when enemy heroes are within an alert radius of any
> current town owned by the selected player color.
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

## Critical Implementation Notes

- Current town ownership is not implemented today. Existing town markers expose
  `.h3m` `initial_owner` only, and older planning explicitly marks current town
  ownership as out of scope.
- The parser currently extracts save-derived hero army, position, and owner
  color from observed GM1/GM2 structures. Town ownership must be researched
  separately from real local saves and then covered with synthetic tests.
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

## Dependency Graph

```text
Current Town Alerts

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

  Quality:
    T08, T09, T10, T11 -> T12 [Docs And Verification Pass]
```

**Max parallelism:** T06 can run after the config contract is agreed, while
T03/T04 parser work continues. T09 can be prototyped against a fixed test
snapshot after T08's contract is written, but final wiring must wait for T08.
Parser tasks should be single-owner because `tools/h3_save_parser.py` and its
binary fixture helpers are easy to conflict on.

## Task Definitions

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

- Fill in after implementation.

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

## Checkpoints

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

### Checkpoint: Complete

- [ ] T12 is `done`.
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

## Open Questions

- Which exact real save examples will be used for parser research?
- Does the observed save ownership record include stable town object identity,
  coordinates, or only list ordering?
- Are random town/current faction changes relevant to alert display, or only
  current owner color?
- Should a later iteration add an `Include allied towns` toggle?
- Should a later iteration add pathfinding-based "reachable threat" alerts
  using portals and route layers?

## Summary Table

| ID | Title | Status | Blocked By | Wave | Execution | Effort | Scope | Files Likely Touched |
|---|---|---|---|---|---|---|---|---|
| T01 | Collect Local Save Evidence | todo | -- | research | Main | M | Research | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T02 | Document Save Ownership Hypothesis | blocked | T01 | research | Main | S | Docs | `tools/battle_estimator_save_parsing_checkpoint.md` |
| T03 | Synthetic Current Town Ownership Fixtures | blocked | T02 | parser | Main | M | Test | `tests/test_h3_save_parser.py`, `tests/test_battle_estimator_gui.py` |
| T04 | Parse Current Town Ownership | blocked | T03 | parser | Main | M | Core | `tools/h3_save_parser.py`, `tests/test_h3_save_parser.py` |
| T05 | Join Save Ownership To H3M Town Targets | blocked | T04 | backend | Main | M | API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T06 | Persist My Color And Alert Radius | todo | -- | backend | Parallel | S | Config | `tools/h3_save_parser.py`, `tools/battle_estimator_gui.py`, tests |
| T07 | Build Threat Alert Service | blocked | T05, T06 | backend | Main | M | Core/API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T08 | Expose Snapshot Contract | blocked | T07 | backend | Main | S | API | `tools/battle_estimator_gui.py`, `tests/test_battle_estimator_gui.py` |
| T09 | Render My Color And Alert Radius Controls | blocked | T08 | frontend | Parallel | M | GUI | `index.html`, `app.js`, `style.css`, GUI tests |
| T10 | Render Alerts Sidebar Section | blocked | T08 | frontend | Parallel | M | GUI | `index.html`, `app.js`, `style.css`, GUI tests |
| T11 | Center And Activate Alert Target | blocked | T10 | frontend | Main | S | GUI | `app.js`, `style.css`, GUI tests |
| T12 | Docs And Verification Pass | blocked | T08, T09, T10, T11 | quality | Main | S | Docs/Test | `README.md`, `CHANGELOG.md`, `AGENTS.md` |
