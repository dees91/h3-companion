# AGENTS.md

Context for agents working in this repository.

## Project Snapshot

This repository is `h3-companion`, a local Heroes of Might and Magic III
Complete companion tool for autosave-driven battle estimation, map scanning,
pathfinding overlays, and hero skill recommendations.

The project has no runtime dependency on the VCMI source tree or VCMI binaries.
It vendors a minimal VCMI-derived config snapshot and uses VCMI as a mechanics
reference where explicitly noted in code or docs.

The current source layout is intentionally preserved for now:

- `tools/`
- `tests/`
- `planning/`

- Do not do a large package rename or directory reshuffle as part of unrelated
  work. If it is needed later, plan it as a separate migration.

## User And Workflow Context

The primary supported workflow is Heroes of Might and Magic III Complete running
through Porting Kit on macOS.

Default game root used by the code:

```text
$HOME/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games
```

Common autosave/game folders live under that root, including Random map folders.
Older planning may mention narrower example Random-map roots, but current code
follows the broader `Games` root.

The user usually communicates in Polish. Keep final answers concise and
practical. For code work, implement and verify unless the user explicitly asks
only for discussion, research, or planning.

## Commands

Run the full Python test suite:

```bash
python3 -m unittest
```

Last known full-suite verification:

```text
Ran 336 tests in 34.027s
OK
```

Run a focused test module:

```bash
python3 -m unittest tests.test_hero_skill_recommender
python3 -m unittest tests.test_battle_estimator_gui
python3 -m unittest tests.test_h3_save_parser
```

Check the browser GUI JavaScript syntax:

```bash
node --check tools/battle_estimator_gui/app.js
```

Start the local GUI:

```bash
python3 tools/battle_estimator_gui.py
```

Start the CLI wizard:

```bash
python3 tools/battle_estimator.py
```

Useful CLI examples:

```bash
python3 tools/battle_estimator.py --list-save-heroes --all-heroes
python3 tools/battle_estimator.py --hero Isra vs "horde of ancient behemoth"
python3 tools/battle_estimator.py --scan-nearby 10 --hero Isra
python3 tools/battle_estimator.py --save-file "/path/to/415.GM2" --hero Isra vs "30 champion"
```

## Documentation Routing

Agents starting work in this repo should use this section to choose the right
project docs before changing code or public behavior.

Always start with:

- `README.md` for the public project overview, quick start, supported workflow,
  screenshots, VCMI data notes, and current user-facing framing.
- `AGENTS.md` for repository-specific working rules, commands, module context,
  gotchas, and current implementation assumptions.

For releases, compatibility, and public repo preparation:

- `CHANGELOG.md` for user-facing release notes and compatibility notes.
- `docs/release-policy.md` for versioning, public compatibility surfaces,
  deprecation rules, release checklist, and GitHub release note template.
- `NOTICE.md` and `LICENSE` for VCMI-derived data attribution, GPLv2+ project
  licensing, and public distribution constraints.

For save parsing, autosaves, and local config/cache behavior:

- `planning/battle-estimator-autosave-brief.md` for the autosave-first workflow
  and early save parsing context.
- `planning/phase-1-battle-estimator-autosave-mvp-tasks.md` for autosave MVP
  implementation decisions and parser test expectations.
- `planning/battle-estimator-current-town-alerts.md` for save-derived current
  town ownership research, player color settings, alert radius behavior, and
  defensive castle/town threat alert tasks.
- `tools/battle_estimator_save_parsing_checkpoint.md` for detailed historical
  save parsing findings and observed GM1/GM2 structures.

For nearby scans, H3M parsing, map overlays, portals, and routing:

- `planning/phase-2-battle-estimator-nearby-scan-tasks.md` for nearby scan and
  H3M parser implementation context.
- `planning/battle-estimator-map-improvements.md` for map rendering,
  terrain/route layers, town/portal parsing, and pathfinding decisions.

For GUI work:

- `planning/phase-3-battle-estimator-gui-tasks.md` for the local browser GUI
  feature history, API shape, state handling, and UX constraints.
- `README.md` screenshots for the public-facing expected GUI presentation.

For hero skill recommendations:

- `planning/battle-estimator-hero-skill-recommendations.md` for recommender
  scope, layered rule model, metadata loading, scoring behavior, and test
  expectations.
- `config/battle_estimator/hero_skill_recommendations.json` for the active
  recommendation rule data.

Planning/history docs are useful context, but current code and tests are the
source of truth when docs conflict. Update public docs (`README.md`,
`CHANGELOG.md`, `docs/release-policy.md`, `NOTICE.md`) when behavior,
compatibility, attribution, or release process changes. Avoid churning old
planning docs for style-only updates.

## Git Hygiene

- The user may have other work in progress. Always check `git status --short`.
- Do not revert changes you did not make.
- Commit only when the user asks for a commit.
- When committing, stage only the intended files.
- Use `apply_patch` for manual file edits.
- Avoid destructive git commands unless explicitly requested.

## Runtime And Data Dependencies

The project is mostly stdlib Python plus local static frontend assets.

Vendored VCMI data snapshot:

- `config/heroClasses.json`
- `config/skills.json`
- `config/heroes/*.json`

Custom project rules:

- `config/battle_estimator/hero_skill_recommendations.json`

Attribution:

- `NOTICE.md`
- `third_party/vcmi/license.txt`

The vendored VCMI config is intentionally minimal. Do not add the full VCMI
`config/` tree without a specific reason. If more VCMI config is needed, add
only the required subset and update `NOTICE.md` if the provenance changes.

`config/skills.json` and other VCMI config files are JSONC-like and can contain
comments. Use the existing `hero_skill_recommender.load_jsonc()` helper for
those files instead of raw `json.loads()`.

## Important Modules

`tools/battle_estimator.py`

- CLI entrypoint and Monte Carlo battle estimator.
- Contains hardcoded HoMM3 creature stats derived from VCMI data.
- Supports manual army mode, autosave hero mode, save hero listing, and nearby
  target scanning.
- Simulation is intentionally simplified and does not model hero stats, spells,
  artifacts, morale, luck, or many special creature abilities.

`tools/h3_save_parser.py`

- GM1/GM2 save loading, gzip/raw-deflate handling, and H3SVG detection.
- Autosave folder and save selection logic.
- User config handling under:
  - `~/.config/vcmi-battle-estimator/config.json`
- Cache handling under:
  - `~/.cache/vcmi-battle-estimator`
- Hero army scanner for observed multiplayer/hotseat save structures.
- Hidden target persistence.
- Manual current-skill state persistence for hero recommendations.

`tools/h3_map_parser.py`

- H3M parser for map metadata used by the tool.
- Parses neutral monster targets, towns, portals, portal edges, terrain/route
  layers, and water/blocked/land routing states.
- Used by scan, GUI map rendering, and pathfinding.

`tools/battle_estimator_gui.py`

- Local HTTP server using stdlib `ThreadingHTTPServer`.
- Serves static files from `tools/battle_estimator_gui/`.
- Builds domain snapshots from save/map/config data.
- Provides JSON APIs for hero selection, scan, simulation, pathfinding, hidden
  targets, folder/save selection, and hero skill recommendations.
- Contains backend pathfinding service contracts and implementation.

`tools/hero_skill_recommender.py`

- Loads VCMI hero/skill metadata.
- Validates custom skill recommendation rules.
- Scores next secondary skill recommendations.
- Compares concrete level-up offers such as `earthMagic:basic` vs
  `necromancy:expert`.

`tools/battle_estimator_gui/`

- Static browser frontend:
  - `index.html`
  - `app.js`
  - `style.css`
- No build step. Keep it dependency-free unless there is a clear reason to
  introduce tooling.

## Save Parsing Context

Known supported save files:

- `.GM1`
- `.GM2`
- `GAME_BEGIN.GM1` / `GAME_BEGIN.GM2`
- hotseat saves with `[hotseat] ` prefix

Save ordering behavior:

- `GAME_BEGIN` is accepted as the first save when present.
- `[hotseat] ` prefixes are normalized away for numeric save ordering.
- Numeric GM1/GM2 autosaves are ordered by number, with existing tie-break
  behavior in parser tests.

Hero save parsing:

- Multiplayer hero army structures were observed with XOR `0x01`.
- Hotseat/unencoded structures are also handled through the parser's supported
  key set.
- Parser reads hero name, army stacks, position when available, and owner color.
- Current secondary skills are not automatically parsed from saves. The skill
  recommendation UI uses manually maintained current skill state, falling back
  to VCMI starting skills.

## Map And Routing Context

The GUI map is intentionally simple:

- tile grid, no full terrain graphics,
- markers for heroes, neutral monsters, towns, and portals,
- neutral monster and hero filters,
- hidden targets persisted per map.

Route/pathfinding scope:

- Pathfinding is strategic route search, not exact Heroes III movement.
- It does not model movement points, roads, terrain movement cost, spells, or
  one-turn reachability.
- It uses route layers and portal/subterranean-gate edges from parsed H3M data.
- Water is visual/contextual in the current scope, not normal land pathfinding.
- Neutral monsters can be treated as passable blockers for strategic route
  planning; battle feasibility can be layered on later.
- Towns and ordinary visitable markers are terminal targets, not generic
  transit nodes.

Portal context:

- Portal edges are modeled as directed edges.
- One-way portals remain one-way unless parser emits reverse edges.
- Multi-exit portals are represented as multiple possible edges and should be
  treated as non-deterministic in UI explanations.

## Hero Skill Recommendation Context

MVP decisions already implemented:

- Only secondary skills are covered.
- No item/artifact recommendations.
- No spellbook-aware recommendations.
- No template/banned-skill support.
- No map-context heuristics.
- Default role is `main`.
- Recommendations are tailored toward the user's use case:
  multiplayer 2v2, tempo, map clearing, movement, combat value, and main-hero
  scaling.
- Scope is standard faction heroes only:
  - castle
  - conflux
  - dungeon
  - fortress
  - inferno
  - necropolis
  - rampart
  - stronghold
  - tower
- Excluded:
  - `special.json`
  - `portraits.json`
  - `portraitsChronicles.json`

Rules are layered:

- global
- faction
- class
- specialty
- hero-specific overrides

Do not replace the layered rules with full duplicated builds per hero unless
there is a strong reason. Coverage tests expect all 144 standard heroes to have
effective recommendations.

## GUI UX Context

Important current features:

- autosave folder picker rooted at the HoMM3 `Games` directory,
- follow-latest mode,
- selected hero and recent hero list,
- map grid with markers,
- hero ranking dialog sorted by AI value,
- back/forward save navigation,
- hide/show neutral targets and hero targets,
- map filter for heroes/monsters,
- scan radius with distance/easiest sorting,
- scan result hover/click behavior,
- scan difficulty rings,
- path mode and route rendering,
- hero skills dialog.

Frontend design expectation:

- This is a dense utility tool, not a landing page.
- Keep controls compact and practical.
- Avoid decorative UI and large hero sections.
- Preserve team/owner colors and marker identity when adding overlays.
- Ensure text does not overflow compact controls.

## Planning Docs

Planning/history docs are intentionally kept:

- `planning/battle-estimator-autosave-brief.md`
- `planning/phase-1-battle-estimator-autosave-mvp-tasks.md`
- `planning/phase-2-battle-estimator-nearby-scan-tasks.md`
- `planning/phase-3-battle-estimator-gui-tasks.md`
- `planning/battle-estimator-map-improvements.md`
- `planning/battle-estimator-hero-skill-recommendations.md`
- `tools/battle_estimator_save_parsing_checkpoint.md`

Some docs still mention old `tools/...` paths and old repo context. That is
expected because the layout is currently preserved. Update docs when behavior
changes, but do not churn old checkpoint content just for style.

## Common Gotchas

- `python3 -m unittest` depends on `tests/__init__.py`; do not remove it unless
  test discovery is replaced.
- `tools/__init__.py` is needed for `from tools import ...` imports in tests and
  modules.
- The config path still says `vcmi-battle-estimator` for compatibility with the
  user's existing local config. Do not rename it casually.
- The GUI has no bundler. `node --check` is the fastest JS syntax check.
- Save/map parsing tests use synthetic binary fixtures. Prefer extending those
  fixtures over checking in real `.GM1`, `.GM2`, or `.h3m` files.
- Do not add real save files to the repo.
- `.git/filter-repo/` metadata may exist locally. It is not project source and
  should not be treated as part of the application.
