# Battle Estimator MCP Strategic Advisor - Task Breakdown

> **Source**: planning discussion on 2026-05-26.
>
> This plan adds a local MCP interface for agent-facing strategic and tactical
> advice. The companion app should expose current game state and safe analysis
> tools to external coding/assistant clients such as Codex or Claude Code, while
> keeping the H3 Companion GUI free of direct LLM API integration in this
> improvement iteration.
>
> **Related**:
> [README](../README.md),
> [AGENTS](../AGENTS.md),
> [Autosave Brief](./battle-estimator-autosave-brief.md),
> [Map Improvements](./battle-estimator-map-improvements.md),
> [Save-Aware Improvements](./battle-estimator-save-aware-improvements.md),
> and
> [Hero Skill Recommendations](./battle-estimator-hero-skill-recommendations.md).

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
> 6. **Do not commit real saves, maps, private paths, MCP client config files,
>    API keys, or assistant transcripts.**
> 7. **Do not add direct LLM API integration to the GUI for this improvement
>    iteration.**
>
> Status values: `todo` = ready to pick up | `in-progress` = being worked on |
> `done` = completed | `blocked` = waiting on dependencies.

---

## Goal

Enable the user to ask an external agent for tactical and strategic advice about
the current Heroes III game state using a local MCP server.

The MCP server should expose enough structured state and safe compute tools for
an agent to answer questions such as:

- What should red do now?
- Which enemy threats matter this turn?
- Which nearby fights look safe or valuable?
- Which portals or subterranean gates expose our towns?
- How should one player coordinate with the allied team?

This improvement iteration is agent-facing, not GUI-native. The user will talk
to an MCP-capable assistant in Codex, Claude Code, or another local client. H3
Companion only provides truthful game context and analysis helpers.

## Product Decisions

- Default advice scope is one concrete player color. Team/alliance advice is
  available on request with `scope="team"`.
- The MCP surface is read-only plus safe compute tools. It must not mutate GUI
  config, selected hero, hidden targets, map state, or local files.
- A future GUI advisor board is deferred. No MCP tool should write advice back
  into the GUI in this improvement iteration.
- The main tool should be a condensed `advisor_context`, not only raw
  `/api/state`. Raw state can exist as a debug/fallback tool.
- The MCP server should be a separate entrypoint, for example
  `python3 tools/battle_estimator_mcp.py`, while reusing existing backend
  functions from `battle_estimator_gui.py`, `h3_save_parser.py`,
  `h3_map_parser.py`, and `battle_estimator.py`.
- The MCP server should default to the same local config and autosave discovery
  behavior as the GUI, with CLI overrides for `--game-dir`, `--save-file`, and
  `--map-file`.
- The server should cache the last built domain snapshot but provide explicit
  refresh behavior. `get_advisor_context(..., refresh=true)` should default to
  fresh context so the agent does not reason from stale saves.
- Tool output must include source metadata: save file name, map file name,
  snapshot timestamp or fingerprint, selected color/team, and important model
  limitations.
- The advisor should never claim full game-rule accuracy. It must surface known
  limitations around fog of war, exact movement points, roads, terrain movement
  cost, active spells, artifacts, tactics, and incomplete save parsing.

## Critical Implementation Notes

- Current GUI backend already has a useful domain snapshot:
  `build_domain_snapshot(...)` returns map, players, teams, route layers,
  heroes, neutral targets, towns, portals, portal edges, town ownership, castle
  alerts, hidden target filtering context, and raw parser objects.
- Existing HTTP handlers implement safe compute behavior that should be reused
  or factored into non-HTTP helpers:
  radius scan, single battle estimate, pathfinding, portal explanation, and
  castle alerts.
- Existing config path remains `~/.config/vcmi-battle-estimator/config.json`
  for compatibility. Do not casually rename it.
- Local real saves and maps may be used for manual verification, but must not
  be committed or copied into the repo.
- The project usually avoids runtime third-party dependencies, but T01 selects
  the official MCP Python SDK because it is a task-specific implementation that
  reduces protocol and client-compatibility risk. Introduce the dependency
  deliberately with docs, tests, and compatibility notes when the server entry
  point is implemented.
- MCP clients can differ in configuration format. Keep project docs focused on
  the server command and tool contracts rather than committing local client
  config.
- A local VCMI checkout outside this repository may be used
  read-only as a mechanics reference if needed, but this project must not gain a
  runtime dependency on that checkout.

## MCP Tool Contract

Tool names are planning targets. Final names may change during implementation
if a client or SDK imposes naming constraints.

### `refresh_context`

Reload the current save/map and rebuild cached advisor state.

Input:

```json
{
  "mode": "follow_latest",
  "game_dir": null,
  "save_file": null,
  "map_file": null
}
```

Output should include save/map identity, fingerprint, active color/team summary,
and any load warnings.

### `get_state_summary`

Return a compact debug summary: current save, map, dimensions, players, teams,
selected GUI hero if known, active colors, hero/town/portal/target counts, and
snapshot freshness.

### `list_colors`

Return active map colors, team membership, detected heroes by color, and whether
the configured `My color` is available.

### `get_advisor_context`

Primary tool for strategic advice.

Input:

```json
{
  "color_id": 0,
  "scope": "color",
  "refresh": true,
  "include_raw_ids": true
}
```

Recommended output sections:

- `subject`: color, color name, team ID, allied colors for `scope="team"`,
- `snapshot`: save/map identity and limitations,
- `heroes`: own/allied/enemy hero summaries with positions, owner colors,
  armies, rough strength, combat context status, and reachable/nearby notes,
- `towns`: current owned towns when available, initial-owner caveats otherwise,
- `alerts`: defensive threat alerts/status for the requested color,
- `nearby_opportunities`: condensed target opportunities, with tool hints for
  deeper scans,
- `portals`: important nearby or cross-level portal facts,
- `routes`: suggested route checks rather than huge precomputed paths,
- `known_limitations`: explicit model limitations and unavailable data.

### `get_state_raw`

Debug/fallback tool. Return raw `/api/state`-equivalent data or a bounded subset
if the snapshot is too large. This should be clearly marked as verbose.

### `scan_nearby`

Run a safe radius scan for one hero.

Input:

```json
{
  "hero_id": "hero:731686",
  "radius": 10,
  "target_filter": "both",
  "sort": "distance",
  "simulations": 200,
  "refresh": false
}
```

Output should reuse existing scan estimates and include target IDs that can be
passed to other tools.

### `estimate_battle`

Estimate one selected hero versus one target hero or neutral target. Must remain
read-only and expose the same combat model limitations as the GUI/CLI.

### `find_route`

Find a strategic route from a hero to a target ID or explicit position using the
existing land/portal pathfinding model. Must report target fallback,
cross-level segments, portal segments, and non-deterministic portal traversal.

### `explain_portal`

Explain one portal or subterranean gate: type, role, channel key, possible
destinations, levels, non-determinism, and route/path implications.

### `get_alerts`

Return castle/town defensive alerts for a color. If current town ownership is
unavailable or partially supported for the current save, return explicit status
instead of guessing.

## Advisor Runbook

Create a Markdown runbook for users and agents. Recommended operational flow:

1. Call `refresh_context` unless the user explicitly asks to use cached state.
2. Call `get_advisor_context(color_id, scope="color")` by default.
3. For alliance-level questions, use `scope="team"`.
4. Evaluate in this order:
   - immediate threats,
   - vulnerable towns,
   - hero strength and role distribution,
   - easy nearby targets,
   - routes to objectives and threats,
   - portal/subterranean exposure,
   - unknowns and model limitations.
5. Use compute tools only to check concrete hypotheses:
   - `scan_nearby` for specific heroes,
   - `find_route` to towns, portals, objectives, or enemy heroes,
   - `estimate_battle` for specific fights,
   - `explain_portal` for ambiguous portal networks.
6. Answer in this format:
   - `Now`
   - `Next 1-2 turns`
   - `Risks`
   - `Checks I ran`
   - `Uncertainties`

The runbook should instruct the agent to cite concrete tool facts such as hero
IDs, positions, target IDs, town IDs, save/map names, and limitation statuses.

## Dependency Graph

```text
MCP Strategic Advisor

  Foundation:
    T01 [MCP Transport Spike]
      -> T02 [Read-Only Context Loader]
      -> T03 [Advisor Context Builder]

  Safe Compute Tools:
    T02 -> T04 [Scan And Estimate Tools]
    T02 -> T05 [Route And Portal Tools]
    T03 -> T06 [Alerts And Color Scope Tools]

  Agent Interface:
    T03, T04, T05, T06 -> T07 [MCP Server Entry Point]
    T07 -> T08 [Runbook And Client Setup Docs]

  Quality:
    T07, T08 -> T09 [End-To-End MCP Verification]
```

**Max parallelism:** T04 and T05 can run in parallel after T02 if they avoid
conflicting edits in shared helper extraction. T08 can draft docs after T01/T03
define the final transport and context shape, but it should not be marked done
until T07 exists. T07 should be single-owner because it binds tool contracts,
transport, and context cache behavior.

## Task Definitions

### T01: MCP Transport Spike

| Field | Value |
|---|---|
| Description | Determine the smallest reliable MCP server transport for this repo and document whether to use stdlib JSON-RPC, an available MCP SDK, or a new dependency. |
| Blocked By | -- |
| Wave | foundation |
| Execution | Main |
| Effort | S |
| Scope | Research/Docs |
| Source | Need compatibility with Codex/Claude Code without unnecessary dependencies |

**Files to modify:**

- This planning doc
- Possibly `README.md` or a new docs/runbook file if a setup constraint is discovered

**Acceptance Criteria:**

1. The selected MCP transport approach is documented with rationale.
2. The decision explains whether a third-party Python dependency is required.
3. The decision names the command future users will run, for example
   `python3 tools/battle_estimator_mcp.py`.
4. The decision avoids committing local MCP client config or credentials.

**Verification:**

1. `git diff --check`
2. Markdown review for private paths beyond the known local VCMI reference.

**Completion Notes:**

- Selected transport/library: local MCP over `stdio` using the official Model
  Context Protocol Python SDK (`mcp`) for the server implementation.
- Rationale: the official SDK is a maintained, task-specific library that avoids
  hand-rolled protocol, framing, and lifecycle bugs, while `stdio` remains the
  best fit for local MCP clients and avoids opening a local HTTP port or adding
  an auth surface.
- Third-party dependency decision: a Python dependency on the base `mcp` package
  is required and deliberate. Avoid `mcp[cli]` unless T07 proves SDK CLI tooling
  is needed.
- Dependency management requirement for T07: when the entry point is
  implemented, add an explicit install path such as a dependency manifest or
  documented `pip install mcp`, plus matching tests and runbook notes.
- Protocol target: the server entry point should use the SDK's stdio server
  support for the stable 2025-06-18/2025-03-26-style initialize-based MCP
  lifecycle used by current local clients.
- Stdio constraints for T07: stdout must contain only MCP messages, logs must
  go to stderr, and stdin EOF should terminate the process cleanly. These should
  be satisfied through SDK transport behavior rather than a custom protocol
  loop.
- Future command: `python3 tools/battle_estimator_mcp.py`.
- No MCP client configuration, credentials, transcripts, real saves, or real
  maps were added for this spike.

---

### T02: Read-Only Context Loader

| Field | Value |
|---|---|
| Description | Build an advisor context service that loads/caches the same domain snapshot as the GUI, with explicit refresh and CLI overrides for game/save/map selection. |
| Blocked By | T01 |
| Wave | foundation |
| Execution | Main |
| Effort | M |
| Scope | Core/Test |
| Source | Fresh save-aware context for agent tools |

**Files to modify:**

- New: `tools/battle_estimator_mcp.py` or a shared advisor module under `tools/`
- `tools/battle_estimator_gui.py` only if shared snapshot helpers need a small extraction
- `tests/test_battle_estimator_mcp.py`

**Acceptance Criteria:**

1. Service can load current context from existing GUI config/follow-latest
   behavior.
2. Service supports CLI or constructor overrides for `game_dir`, `save_file`,
   and `map_file`.
3. Service exposes `refresh_context` and cached snapshot metadata including
   save/map identity and fingerprints.
4. Service does not mutate config, selected hero, hidden targets, or UI state.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Added `AdvisorContextService` in `tools/battle_estimator_mcp.py`.
- The service wraps `battle_estimator_gui.build_domain_snapshot()` directly,
  keeps an in-memory cached `DomainSnapshot`, and exposes `refresh_context()`,
  `get_domain_snapshot(refresh=False)`, and defensive-copy metadata.
- Constructor overrides support `game_dir`, `save_file`, `map_file`, and
  `config_path`. `save_file` without an explicit mode selects pinned mode;
  explicit `follow_latest` plus `save_file` is rejected to avoid silently
  ignoring the pinned override.
- The loader does not use `GuiAppState`, `_state_payload_for_app()`, selected
  hero mutation, hidden-target writes, or the persistent removed-neutral cache.
  Failed refreshes leave the previous cached snapshot and metadata intact.
- Added `tests/test_battle_estimator_mcp.py` for config/follow-latest loading,
  game/save/map overrides, cache refresh semantics, metadata deep-copy behavior,
  and preservation of cached state after refresh errors.

---

### T03: Advisor Context Builder

| Field | Value |
|---|---|
| Description | Convert the rich domain snapshot into a condensed advisor context optimized for an LLM agent, with default color scope and optional team scope. |
| Blocked By | T02 |
| Wave | foundation |
| Execution | Main |
| Effort | M |
| Scope | Core/Test |
| Source | Primary context tool for strategic/tactical advice |

**Files to modify:**

- Advisor module under `tools/`
- `tests/test_battle_estimator_mcp.py`

**Acceptance Criteria:**

1. `get_advisor_context(color_id, scope="color")` groups own, allied, and enemy
   heroes for the requested color.
2. `scope="team"` expands the subject to allied colors from H3M team data.
3. Context includes save/map metadata, color/team metadata, heroes, towns,
   alerts status, portal summary, opportunity hints, and known limitations.
4. Output is bounded and deterministic enough for tests; raw state is not the
   only way to reason about the game.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. Focused tests for color scope, team scope, unknown color, and limitation
   reporting.

**Completion Notes:**

- Added `AdvisorContextService.get_advisor_context()` and
  `build_advisor_context()` in `tools/battle_estimator_mcp.py`.
- Context output is a bounded, deterministic dict with `subject`, `snapshot`,
  `heroes`, `towns`, `alerts`, `nearby_opportunities`, `portals`, `routes`, and
  `known_limitations` sections instead of raw state dumps.
- `scope="color"` keeps the requested color as the subject while still grouping
  same-team heroes as allied. `scope="team"` expands `subject_color_ids` to the
  requested color plus allied colors from H3M team data.
- The builder validates active player colors and invalid scopes, reports model
  limitations, includes alert status through the existing castle-alert service,
  and provides scan/route tool hints without running compute tools.
- Added focused MCP tests for color scope grouping, team scope expansion,
  unavailable team-scope limitations, unknown colors, invalid scopes, and
  required context sections.

---

### T04: Scan And Estimate Tools

| Field | Value |
|---|---|
| Description | Expose safe compute helpers for nearby scans and single battle estimates using existing battle estimator code. |
| Blocked By | T02 |
| Wave | compute-tools |
| Execution | Parallel |
| Effort | M |
| Scope | Core/Test |
| Source | Agent needs concrete tactical checks beyond static context |

**Files to modify:**

- Advisor/MCP module under `tools/`
- Possibly small helper extraction from `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_mcp.py`

**Acceptance Criteria:**

1. `scan_nearby` accepts hero ID, radius, target filter, sort mode, simulations,
   and refresh flag.
2. `scan_nearby` returns serialized target estimates with target IDs suitable
   for follow-up tools.
3. `estimate_battle` estimates hero versus neutral or enemy hero targets using
   existing estimator logic.
4. Both tools are read-only and report model limitations.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Added read-only `AdvisorContextService.scan_nearby()` and
  `AdvisorContextService.estimate_battle()` wrappers plus pure module-level
  helpers in `tools/battle_estimator_mcp.py`.
- `scan_nearby` accepts hero ID, radius, target type, easiest/distance sort
  mode, simulation count, refresh flag, removed-target inclusion, and hidden
  target inclusion. It reuses existing nearby-scan and battle-estimator logic
  and returns GUI-compatible serialized estimates with target IDs.
- `estimate_battle` resolves an exact neutral or enemy-hero target ID without
  scan-radius or same-level filtering, matching the existing GUI single-target
  simulation behavior.
- Hidden neutral/hero targets are read from config and filtered by default
  without mutating config. Filtered responses report counts only; exact hidden
  IDs are exposed only when hidden targets are explicitly included.
- Added focused tests for neutral+hero scans, easiest sorting, hero-only scans,
  exact hero-target estimates across levels, hidden-target filtering, invalid
  inputs, model limitations, and config preservation.

---

### T05: Route And Portal Tools

| Field | Value |
|---|---|
| Description | Expose safe compute helpers for strategic routes and portal/subterranean gate explanation. |
| Blocked By | T02 |
| Wave | compute-tools |
| Execution | Parallel |
| Effort | M |
| Scope | Core/Test |
| Source | Agent needs route and portal analysis for strategic advice |

**Files to modify:**

- Advisor/MCP module under `tools/`
- Possibly small helper extraction from `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_mcp.py`

**Acceptance Criteria:**

1. `find_route` accepts hero ID and either target ID or explicit target
   position.
2. Route output reports requested/resolved target, path segments, portal
   segments, fallback status, and non-deterministic portal traversal.
3. `explain_portal` returns portal type, role, channel, destinations,
   cross-level details, and non-deterministic status.
4. Tools do not mutate GUI state, map level, selected hero, or config.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Added read-only `AdvisorContextService.find_route()` and
  `AdvisorContextService.explain_portal()` wrappers plus module-level route and
  portal helpers in `tools/battle_estimator_mcp.py`.
- `find_route` accepts a hero ID and exactly one target source: a marker target
  ID or strict `{x, y, z}` target position. It reuses existing GUI pathfinding
  request/result helpers and reports requested/resolved positions, route
  segments, portal segments, fallback status, non-deterministic portal usage,
  hidden-target counts, and model limitations.
- Hidden neutral/hero target IDs are treated as unknown by default and exact
  hidden IDs are only exposed when hidden targets are explicitly included.
- `explain_portal` inspects raw parsed portal targets and edges, reporting
  portal role/type/channel, outbound destinations, inbound sources, cross-level
  edges, non-deterministic multi-exit channels, and unresolved edge counts
  without invoking pathfinding conversion.
- Added focused tests for explicit-position routing, marker-target routing
  through portals, fallback/not-found statuses, hidden route target privacy,
  non-deterministic portal segments, portal explanation, unresolved portal
  edges, invalid payloads, limitations, and read-only config behavior.

---

### T06: Alerts And Color Scope Tools

| Field | Value |
|---|---|
| Description | Expose read-only tools for color/team selection, active players, and defensive alert status. |
| Blocked By | T03 |
| Wave | compute-tools |
| Execution | Parallel |
| Effort | S |
| Scope | Core/Test |
| Source | Agent needs reliable subject selection and threat context |

**Files to modify:**

- Advisor/MCP module under `tools/`
- `tests/test_battle_estimator_mcp.py`

**Acceptance Criteria:**

1. `list_colors` returns active colors, teams, configured `My color` when
   available, and detected heroes per color.
2. `get_alerts(color_id)` returns castle/town alert status and details for that
   color.
3. Alert output explicitly reports unavailable or partial current town
   ownership instead of guessing.
4. Unknown, inactive, or unsupported color IDs return clear errors.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. `python3 -m unittest tests.test_battle_estimator_gui`

**Completion Notes:**

- Fill in after implementation.

---

### T07: MCP Server Entry Point

| Field | Value |
|---|---|
| Description | Bind the context service and safe compute helpers to a local MCP server entrypoint. |
| Blocked By | T03, T04, T05, T06 |
| Wave | interface |
| Execution | Main |
| Effort | M |
| Scope | CLI/Integration/Test |
| Source | Agent-facing MCP surface |

**Files to modify:**

- `tools/battle_estimator_mcp.py`
- `tests/test_battle_estimator_mcp.py`
- Possibly dependency/config docs if a third-party SDK is introduced

**Acceptance Criteria:**

1. `python3 tools/battle_estimator_mcp.py --help` works.
2. The server exposes the approved advisor tools over the selected MCP
   transport.
3. Tool argument validation returns clear structured errors.
4. Server startup does not require the browser GUI to be running.
5. Server remains read-only except for in-memory cache refresh.

**Verification:**

1. `python3 -m unittest tests.test_battle_estimator_mcp`
2. MCP protocol smoke test using subprocess/stdin-stdout or the selected SDK's
   test harness.
3. `python3 tools/battle_estimator_mcp.py --help`

**Completion Notes:**

- Fill in after implementation.

---

### T08: Runbook And Client Setup Docs

| Field | Value |
|---|---|
| Description | Write the operational runbook and setup docs for using the MCP advisor from an external agent client. |
| Blocked By | T07 |
| Wave | docs |
| Execution | Main |
| Effort | S |
| Scope | Docs |
| Source | User wants to talk to an external strategic assistant |

**Files to modify:**

- New: `docs/mcp-strategic-advisor-runbook.md`
- `README.md`
- `AGENTS.md`
- This planning doc

**Acceptance Criteria:**

1. Runbook documents the tool sequence, answer format, and limitation language.
2. Setup docs show the server command and supported CLI overrides without
   committing local client config.
3. README mentions the MCP strategic advisor as an optional local workflow.
4. AGENTS routing points future MCP advisor work to this planning doc and
   runbook.

**Verification:**

1. `git diff --check`
2. Manual Markdown link review.

**Completion Notes:**

- Fill in after implementation.

---

### T09: End-To-End MCP Verification

| Field | Value |
|---|---|
| Description | Verify the MCP advisor against synthetic fixtures and at least one local real save/map without committing private data. |
| Blocked By | T07, T08 |
| Wave | quality |
| Execution | Main |
| Effort | M |
| Scope | Test/Docs |
| Source | Release-quality verification |

**Files to modify:**

- `tests/test_battle_estimator_mcp.py`
- `CHANGELOG.md`
- This planning doc

**Acceptance Criteria:**

1. Full Python test suite passes.
2. MCP server can provide advisor context, scan, estimate, route, portal, and
   alert outputs for fixture data.
3. A local real save/map smoke test confirms the server can load current config
   or explicit overrides.
4. Verification notes include only anonymized save/map facts and no real save,
   map, private path, or client config files are staged.

**Verification:**

1. `python3 -m unittest`
2. `python3 tools/battle_estimator_mcp.py --help`
3. MCP smoke test command chosen in T07
4. `git status --short`

**Completion Notes:**

- Fill in after implementation.

---

## Checkpoints

### Checkpoint: Foundation Ready

- [ ] T01, T02, and T03 are `done`.
- [ ] Advisor context can be built without starting the GUI.
- [ ] Context is color-scoped by default and supports team scope.
- [ ] Snapshot freshness and limitations are visible in output.

### Checkpoint: Compute Tools Ready

- [ ] T04, T05, and T06 are `done`.
- [ ] Scan, estimate, route, portal, color, and alert tools are read-only.
- [ ] Tool outputs include IDs that can be used in follow-up calls.
- [ ] Existing GUI scan/pathfinding tests still pass.

### Checkpoint: MCP Interface Ready

- [ ] T07 is `done`.
- [ ] Server starts as a standalone process.
- [ ] MCP tool validation and errors are covered by tests.
- [ ] No GUI process is required.

### Checkpoint: Complete

- [ ] T08 and T09 are `done`.
- [ ] Full Python suite passes.
- [ ] Runbook is linked from README and AGENTS.
- [ ] Real save/map smoke notes are anonymized.
- [ ] No MCP client config, API keys, real saves, or real maps are staged.

## Risks And Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| MCP transport choice adds brittle dependencies. | High | Use the official MCP Python SDK selected in T01, keep the dependency explicit, and avoid optional SDK extras unless they are needed. |
| Advisor context is too verbose for an LLM client. | Medium | Provide condensed `get_advisor_context` and keep raw state as debug/fallback. |
| Agent treats estimates as exact Heroes III truth. | High | Include model limitations in every advisor context and compute result. |
| Tool calls accidentally mutate GUI/config state. | High | Keep advisor tools read-only plus in-memory cache refresh; test config files remain unchanged. |
| Follow-latest context goes stale between user turns. | Medium | Default `get_advisor_context(refresh=true)` and expose snapshot save/map identity. |
| Local real saves or paths leak into docs/tests. | High | Use synthetic fixtures for automated tests and anonymized manual verification notes. |
| Existing GUI helpers are too coupled to HTTP handlers. | Medium | Extract small pure helpers rather than duplicating logic or starting the HTTP server. |
| Team advice is requested when H3M team data is unavailable. | Medium | Fall back to color scope and report unavailable team context explicitly. |

## Open Questions

- Should future versions add a write-only advisor board in the GUI for notes?
- Should MCP expose resources as well as tools once client compatibility is
  known?
- Should future versions support saved named analysis sessions or transcripts?
- Should future versions add template-specific strategic heuristics if map
  template metadata becomes available?

## Summary Table

| ID | Title | Status | Blocked By | Wave | Execution | Effort | Scope | Files Likely Touched |
|---|---|---|---|---|---|---|---|---|
| T01 | MCP Transport Spike | done | -- | foundation | Main | S | Research/Docs | planning doc, docs if needed |
| T02 | Read-Only Context Loader | done | T01 | foundation | Main | M | Core/Test | `tools/battle_estimator_mcp.py`, MCP tests |
| T03 | Advisor Context Builder | done | T02 | foundation | Main | M | Core/Test | advisor module, MCP tests |
| T04 | Scan And Estimate Tools | done | T02 | compute-tools | Parallel | M | Core/Test | advisor module, GUI helpers, MCP tests |
| T05 | Route And Portal Tools | done | T02 | compute-tools | Parallel | M | Core/Test | advisor module, GUI helpers, MCP tests |
| T06 | Alerts And Color Scope Tools | todo | T03 | compute-tools | Parallel | S | Core/Test | advisor module, MCP tests |
| T07 | MCP Server Entry Point | blocked | T03, T04, T05, T06 | interface | Main | M | CLI/Integration/Test | `tools/battle_estimator_mcp.py`, MCP tests |
| T08 | Runbook And Client Setup Docs | blocked | T07 | docs | Main | S | Docs | `docs/mcp-strategic-advisor-runbook.md`, `README.md`, `AGENTS.md` |
| T09 | End-To-End MCP Verification | blocked | T07, T08 | quality | Main | M | Test/Docs | MCP tests, `CHANGELOG.md`, planning doc |
