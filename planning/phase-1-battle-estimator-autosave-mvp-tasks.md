# Phase 1: Battle Estimator Autosave MVP - Task Breakdown

> **Source**: `grill-me` planning session on 2026-05-18. The autosave-first UX,
> target Porting Kit paths, save selection rules, parser scope, and non-goals
> were agreed with the user before implementation.
>
> **Related**:
> [Battle Estimator Autosave Brief](./battle-estimator-autosave-brief.md) and
> [`tools/battle_estimator_save_parsing_checkpoint.md`](../tools/battle_estimator_save_parsing_checkpoint.md).

---

> **MANDATORY FOR ALL AGENTS**
>
> The **Summary Table** at the bottom of this file is the single source of truth
> for task status. Follow these rules:
>
> 1. **Before starting a task**: set its Status to `in-progress` in the Summary Table.
> 2. **After completing a task**: set its Status to `done` in the Summary Table.
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

## Dependency Graph

```text
Phase 1 Autosave MVP

  Foundation:
    BE-T01 [Parser Data Model + Constants]
      -> BE-T02 [Save Loading + H3SVG Detection]
      -> BE-T03 [Latest Folder + Latest Save Selection]
      -> BE-T04 [Config Store]

  Save parsing:
    BE-T01, BE-T02 -> BE-T05 [XOR 0x01 Hero Army Scanner]
    BE-T05 -> BE-T06 [Hero Filtering + Selection]

  CLI integration:
    BE-T03, BE-T04, BE-T06 -> BE-T07 [Autosave-First CLI Dispatch]
    BE-T07 -> BE-T08 [List Save Heroes Command]
    BE-T07 -> BE-T09 [Interactive Wizard]
    BE-T07 -> BE-T10 [Simulation Output Context]

  Quality:
    BE-T01, BE-T03, BE-T05, BE-T06 -> BE-T11 [Parser Unit Tests]
    BE-T07, BE-T08, BE-T09 -> BE-T12 [CLI/Wizard Tests]
    BE-T10, BE-T11, BE-T12 -> BE-T13 [Documentation Verification Pass]
```

**Max parallelism:** After BE-T01, autosave path selection/config and save
hero scanning can be developed in parallel if file ownership is coordinated.
CLI dispatch should wait until the parser contracts are stable.

---

## Product Decisions

- The new UX is autosave-first; old manual-army compatibility is not a design
  constraint.
- Short command form is supported: `python3 tools/battle_estimator.py Isra vs "..."`.
- No arguments launches a terminal wizard.
- Enemy army remains manually typed after `vs`.
- Save folder root is hardcoded for Phase 1:
  `~/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games/Random/PlayerTwo`.
- If no concrete autosave folder is configured, select the newest child folder
  by date in its name.
- Latest save means the highest numeric `*.GM1` or `*.GM2`; if the same number
  exists in both extensions, prefer `.GM2`.
- Hero selection is by detected save name, case-insensitive, with unambiguous
  prefix matching.
- No owner/team detection in Phase 1.
- Parser reads only army stacks; hero stats, skills, artifacts, spells, morale,
  and luck are out of scope.
- Parser implementation belongs in a separate module, expected path:
  `tools/h3_save_parser.py`.
- Full real save files must not be committed as tests.

---

## Task Definitions

### BE-T01: Parser Data Model + Constants

| Field | Value |
|---|---|
| Description | Create the parser module skeleton with explicit data types and constants for the hardcoded Porting Kit autosave root, hero army offsets, save extensions, and config path. No filesystem scanning yet. |
| Blocked By | -- |
| Wave | foundation |
| Execution | Main |
| Effort | S |
| Scope | Parser |
| Source | Planning |

**Files to modify:**
- New: `tools/h3_save_parser.py`
- New or existing: parser-focused tests under `test/` or `tests/`, following repo conventions discovered during implementation

**Acceptance Criteria:**
1. Parser module exposes data types for `SaveContext`, `HeroArmy`, and `HeroStack` or equivalent.
2. Hardcoded `PlayerTwo` autosave root is represented as a single constant derived from `Path.home()`.
3. Hero army offsets are named constants, not magic numbers in parser logic.
4. Creature IDs can be mapped to the existing `Creature` definitions in `battle_estimator.py` without duplicating the creature database.
5. Importing the parser module has no filesystem side effects.

**Verification:**
1. Run a focused import/type smoke test for the new parser module.
2. Run existing battle estimator CLI help or an equivalent no-op command to confirm no import regression.

**Completion Notes:**
- Added `tools/h3_save_parser.py` with parser data contracts, autosave/config constants, named hero army offsets, and lazy creature-ID mapping through `battle_estimator.CREATURES`.
- Added synthetic parser contract tests in `tests/test_h3_save_parser.py`.
- Verification passed: `python3 -m unittest tests.test_h3_save_parser`; `python3 tools/battle_estimator.py --help`.

---

### BE-T02: Save Loading + H3SVG Detection

| Field | Value |
|---|---|
| Description | Add gzip save loading and signature detection. The loader must support `H3SVG` at offset `0` and at offset `65`, and should report useful errors for unreadable or unsupported files. |
| Blocked By | BE-T01 |
| Wave | foundation |
| Execution | Main |
| Effort | S |
| Scope | Parser |
| Source | Planning |

**Files to modify:**
- `tools/h3_save_parser.py`
- Parser tests

**Acceptance Criteria:**
1. `load_save(path)` or equivalent reads gzip-compressed `.GM1`/`.GM2` saves.
2. Raw deflate fallback using `zlib.decompress(compressed[10:-8], -zlib.MAX_WBITS)` is covered.
3. The loader locates `H3SVG` instead of assuming offset `0`.
4. Error messages include the path and reason when loading fails.
5. Loader does not mutate save files.

**Verification:**
1. Unit test with synthetic gzip data containing `H3SVG` at offset `0`.
2. Unit test with synthetic gzip data containing prefix bytes before `H3SVG`.
3. Unit test for non-gzip or missing file error behavior.

---

### BE-T03: Latest Folder + Latest Save Selection

| Field | Value |
|---|---|
| Description | Implement autosave folder and latest-save selection. This resolves the current game folder and selected save before parsing heroes. |
| Blocked By | BE-T01 |
| Wave | foundation |
| Execution | Main |
| Effort | M |
| Scope | Parser |
| Source | Planning |

**Files to modify:**
- `tools/h3_save_parser.py`
- Parser tests

**Acceptance Criteria:**
1. `--autosave-dir` equivalent can be represented as an explicit selected game folder.
2. Without explicit/configured folder, the newest child folder under the hardcoded root is selected by parsed folder-name date.
3. Latest save selection considers only numeric `*.GM1` and `*.GM2`.
4. Highest numeric save wins.
5. Same-number tie prefers `.GM2`.
6. Special/manual names like `GAME_BEGIN.GM2`, `BATTLE.GM2`, `AUTOSAVE.GM2`, and `415_moved.GM1` are ignored by latest selection.

**Verification:**
1. Unit test newest folder selection using temporary directories.
2. Unit test latest save selection with mixed numeric and non-numeric files.
3. Unit test `.GM2` tie-break over `.GM1`.

---

### BE-T04: Config Store

| Field | Value |
|---|---|
| Description | Add user config support for persistent autosave directory and last interactive hero. Config lives outside the repo under `~/.config/vcmi-battle-estimator/config.json`. |
| Blocked By | BE-T01 |
| Wave | foundation |
| Execution | Main |
| Effort | S |
| Scope | Parser/CLI |
| Source | Planning |

**Files to modify:**
- `tools/h3_save_parser.py` or a small config helper if cleaner
- Config tests

**Acceptance Criteria:**
1. Missing config loads as empty/default config.
2. `autosave_dir` can be saved and loaded.
3. `autosave_dir` can be cleared.
4. `last_hero` can be saved and loaded for wizard defaults.
5. Config write creates parent directories as needed.
6. Config paths are user-global and not repo-local.

**Verification:**
1. Unit tests with temporary `HOME` or injected config path.
2. Malformed config returns a clear error or safe failure, not a traceback.

---

### BE-T05: XOR 0x01 Hero Army Scanner

| Field | Value |
|---|---|
| Description | Implement the GM1/GM2 hero army scanner for the observed multiplayer save format. The scanner should decode candidate hero windows with XOR `0x01`, validate hero names, read 7 army slots, and return parsed hero armies. |
| Blocked By | BE-T01, BE-T02 |
| Wave | parsing |
| Execution | Main |
| Effort | M |
| Scope | Parser |
| Source | Planning |

**Files to modify:**
- `tools/h3_save_parser.py`
- Parser tests

**Acceptance Criteria:**
1. Scanner can parse a synthetic XOR-encoded hero named `Isra`.
2. Scanner reads 7 creature IDs and 7 counts from standard decoded offsets.
3. Scanner maps IDs to existing creature names.
4. Empty slots are ignored.
5. Invalid creature IDs or impossible counts reject a candidate.
6. Scanner returns enough source metadata to debug candidate offsets.

**Verification:**
1. Unit test synthetic `Isra` fixture with the known army:
   `731 Skeleton Warrior`, `181 Zombie`, `59 Vampire Lord`, `47 Power Lich`,
   `19 Dread Knight`, `316 Skeleton`, `8 Ghost Dragon`.
2. Unit test swapped first two slots matching `415_moved.GM1` behavior.
3. Unit test invalid ID/count rejection.

---

### BE-T06: Hero Filtering + Selection

| Field | Value |
|---|---|
| Description | Add helper logic for listing relevant heroes and selecting one by name. This keeps CLI and wizard behavior consistent. |
| Blocked By | BE-T05 |
| Wave | parsing |
| Execution | Main |
| Effort | S |
| Scope | Parser/CLI |
| Source | Planning |

**Files to modify:**
- `tools/h3_save_parser.py`
- Parser tests

**Acceptance Criteria:**
1. Relevant hero filter defaults to `ai_value >= 5000 OR total_creatures >= 50`.
2. `--all-heroes` equivalent can bypass the filter.
3. Hero selection supports case-insensitive exact match.
4. Hero selection supports unambiguous prefix match.
5. Missing hero returns a structured error with candidates.
6. Ambiguous hero returns a structured error with matching candidates.
7. Selection never guesses silently.

**Verification:**
1. Unit tests for filter threshold behavior.
2. Unit tests for exact, prefix, missing, and ambiguous selection.

---

### BE-T07: Autosave-First CLI Dispatch

| Field | Value |
|---|---|
| Description | Rework `battle_estimator.py` CLI dispatch around autosave-first usage. The short form `Hero vs "enemy"` should load the latest save and use the hero army as the player army. |
| Blocked By | BE-T03, BE-T04, BE-T06 |
| Wave | CLI |
| Execution | Main |
| Effort | M |
| Scope | CLI |
| Source | Planning |

**Files to modify:**
- `tools/battle_estimator.py`
- `tools/h3_save_parser.py` if CLI helper contracts need adjustment
- CLI tests if present or newly added

**Acceptance Criteria:**
1. `python3 tools/battle_estimator.py Isra vs "horde of ancient behemoth"` resolves latest autosave and uses `Isra` as player army.
2. `--hero Isra` works as an explicit equivalent.
3. `--save 415` selects `415.GM2` or the best matching numbered save according to parser rules.
4. `--save-file PATH` selects an explicit save file.
5. `--autosave-dir PATH` overrides config and auto-discovery for one invocation.
6. `--set-autosave-dir`, `--clear-autosave-dir`, and `--show-config` work without running a simulation.
7. Old manual army mode is not prioritized and should not complicate the new dispatch.

**Verification:**
1. CLI-level tests or smoke commands using synthetic temp autosave directories.
2. Manual smoke run against the known local `415.GM2` if available in the developer environment.

---

### BE-T08: List Save Heroes Command

| Field | Value |
|---|---|
| Description | Add a command/flag to list detected heroes from the selected/latest save. This is the safe fallback when no hero is supplied in non-interactive mode. |
| Blocked By | BE-T07 |
| Wave | CLI |
| Execution | Main |
| Effort | S |
| Scope | CLI |
| Source | Planning |

**Files to modify:**
- `tools/battle_estimator.py`

**Acceptance Criteria:**
1. `--list-save-heroes` lists heroes from the selected/latest save.
2. Output includes selected game folder and save file.
3. Default list uses relevant-hero filtering.
4. `--all-heroes` includes all detected hero armies.
5. Rows include hero name, AI value, and compact army summary.
6. If no heroes are found, output points at the selected save and parser mode.

**Verification:**
1. CLI test or smoke run for default listing.
2. CLI test or smoke run for `--all-heroes`.

---

### BE-T09: Interactive Wizard

| Field | Value |
|---|---|
| Description | Add the no-argument terminal wizard. This should be simple, text-only, and reuse the same parser and selection helpers as the CLI path. |
| Blocked By | BE-T07 |
| Wave | CLI |
| Execution | Main |
| Effort | M |
| Scope | CLI |
| Source | Planning |

**Files to modify:**
- `tools/battle_estimator.py`
- Config helper if needed

**Acceptance Criteria:**
1. Running with no arguments starts wizard mode.
2. Wizard prints selected game folder and save.
3. Wizard lists relevant heroes.
4. Wizard accepts hero selection by number or name.
5. Wizard offers `last_hero` as a default when present and available.
6. Wizard prompts for enemy army text.
7. Wizard saves the selected hero as `last_hero`.
8. Wizard then runs the same simulation path as non-interactive mode.

**Verification:**
1. Unit or integration test using injectable stdin/stdout if practical.
2. Manual smoke run through the wizard.

---

### BE-T10: Simulation Output Context

| Field | Value |
|---|---|
| Description | Update output labels and context for autosave-based runs. The hero name should label the player army and the selected save context should be visible. |
| Blocked By | BE-T07 |
| Wave | CLI |
| Execution | Main |
| Effort | S |
| Scope | CLI |
| Source | Planning |

**Files to modify:**
- `tools/battle_estimator.py`

**Acceptance Criteria:**
1. Output prints selected game folder and save before analysis.
2. Player army label uses hero name, e.g. `Isra`.
3. Enemy army label remains clear.
4. Output includes a limitation note that hero stats, skills, artifacts, spells, morale, and luck are not modeled.
5. Existing static analysis and Monte Carlo results remain readable.

**Verification:**
1. Smoke run with autosave-based hero selection.
2. Confirm old Polish output remains understandable and no line wrapping is obviously broken.

---

### BE-T11: Parser Unit Tests

| Field | Value |
|---|---|
| Description | Add focused tests for parser behavior using synthetic data only. Do not commit full real save files. |
| Blocked By | BE-T01, BE-T03, BE-T05, BE-T06 |
| Wave | quality |
| Execution | Main |
| Effort | M |
| Scope | Tests |
| Source | Planning |

**Files to modify:**
- New parser test file under the repo's established Python test location
- `tools/h3_save_parser.py` only if testability helpers are needed

**Acceptance Criteria:**
1. Tests cover gzip loading and `H3SVG` detection.
2. Tests cover latest folder and latest save selection.
3. Tests cover XOR `0x01` hero army parsing.
4. Tests cover hero filtering and selection errors.
5. Tests use synthetic byte buffers and temp directories.
6. No full save files are added to the repo.

**Verification:**
1. Run the new parser test file.
2. Run the broadest available Python test command that is practical for this repo.

---

### BE-T12: CLI/Wizard Tests

| Field | Value |
|---|---|
| Description | Add coverage for CLI dispatch and wizard control flow where practical. Keep tests deterministic by using temp dirs and injected config/input. |
| Blocked By | BE-T07, BE-T08, BE-T09 |
| Wave | quality |
| Execution | Main |
| Effort | M |
| Scope | Tests |
| Source | Planning |

**Files to modify:**
- CLI test file under the repo's established Python test location
- `tools/battle_estimator.py` only if testability refactors are needed

**Acceptance Criteria:**
1. Short form `Hero vs enemy` dispatch is covered.
2. `--list-save-heroes` dispatch is covered.
3. Config commands are covered.
4. Missing/ambiguous hero errors are covered.
5. Wizard selection can be tested or has a documented manual verification if automated testing would be brittle.

**Verification:**
1. Run focused CLI tests.
2. Run at least one manual smoke command against local saves if available.

---

### BE-T13: Documentation Verification Pass

| Field | Value |
|---|---|
| Description | Update planning/checkpoint docs after implementation and verify they match actual behavior. This is the closeout task for Phase 1. |
| Blocked By | BE-T10, BE-T11, BE-T12 |
| Wave | quality |
| Execution | Main |
| Effort | S |
| Scope | Docs |
| Source | Planning |

**Files to modify:**
- `planning/battle-estimator-autosave-brief.md`
- `planning/phase-1-battle-estimator-autosave-mvp-tasks.md`
- `tools/battle_estimator_save_parsing_checkpoint.md` if new parsing facts are discovered
- `tools/battle_estimator.py` usage header if CLI changed materially

**Acceptance Criteria:**
1. Docs reflect implemented CLI flags and defaults.
2. Completed tasks have concise completion notes.
3. Any deviations from the plan are recorded with rationale.
4. Known limitations are still accurate.
5. Verification commands are recorded in completion notes or final implementation summary.

**Verification:**
1. Review docs for stale commands or contradicted decisions.
2. Run final focused parser/CLI tests.

---

## Checkpoints

### Checkpoint: Parser Foundation

After BE-T01 through BE-T06:

- [ ] Parser module imports without side effects.
- [ ] Latest save selection works in temp-dir tests.
- [ ] Synthetic XOR `Isra` fixture parses to the expected seven-stack army.
- [ ] Hero filtering and selection behavior is deterministic.
- [ ] No changes to `battle_estimator.py` CLI yet, except harmless imports if required.

### Checkpoint: CLI MVP

After BE-T07 through BE-T10:

- [ ] Short command form works.
- [ ] No-argument wizard works manually.
- [ ] `--list-save-heroes` shows selected folder/save and hero candidates.
- [ ] Output clearly labels hero army and modeling limitations.

### Checkpoint: Phase 1 Complete

After BE-T11 through BE-T13:

- [ ] Parser tests pass.
- [ ] CLI/wizard tests or documented manual checks pass.
- [ ] No real save files are committed.
- [ ] Planning and brief docs match implemented behavior.
- [ ] Feature is ready for user review before GUI or owner/team work.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| GM1/GM2 variants beyond observed saves differ from XOR `0x01` layout | High | Keep parser errors explicit; use synthetic tests for known format; add new fixtures only after controlled diff evidence. |
| Wrong autosave folder selected | Medium | Always print selected folder and save; allow `--autosave-dir` and persisted `--set-autosave-dir`. |
| Wrong hero selected in 2v2 | Medium | Require explicit hero in non-interactive mode; no silent selection on ambiguity or missing hero. |
| Parser lists AI or brother heroes | Low | Accepted for Phase 1; user selects by name; owner/team parsing deferred. |
| Battle result overstates accuracy | Medium | Print limitation note; Phase 1 only models creature stacks. |
| Tests accidentally commit private save data | Medium | Use synthetic fixtures only; no full saves in repo. |
| `battle_estimator.py` becomes too large | Medium | Put save parsing in `tools/h3_save_parser.py`; keep CLI integration thin. |

---

## Open Questions

No blocking product questions remain for Phase 1.

Deferred questions for later phases:

- Should a GUI be a small local web UI, Tkinter, Textual, or another terminal UI?
- Can owner/team/color be parsed reliably from the same hero structure?
- Should enemy hero or neutral stack armies be parsed from the save/map?
- Should hero stats, skills, artifacts, morale, luck, and spells enter the simulator?
- Should the tool support arbitrary Porting Kit wrappers and player folders?

---

## Summary Table

| ID | Task | Status | Blocked By | Wave | Effort | Files Likely Touched |
|---|---|---|---|---|---|---|
| BE-T01 | Parser Data Model + Constants | done | -- | foundation | S | `tools/h3_save_parser.py`, parser tests |
| BE-T02 | Save Loading + H3SVG Detection | todo | BE-T01 | foundation | S | `tools/h3_save_parser.py`, parser tests |
| BE-T03 | Latest Folder + Latest Save Selection | todo | BE-T01 | foundation | M | `tools/h3_save_parser.py`, parser tests |
| BE-T04 | Config Store | todo | BE-T01 | foundation | S | `tools/h3_save_parser.py`, config tests |
| BE-T05 | XOR 0x01 Hero Army Scanner | blocked | BE-T01, BE-T02 | parsing | M | `tools/h3_save_parser.py`, parser tests |
| BE-T06 | Hero Filtering + Selection | blocked | BE-T05 | parsing | S | `tools/h3_save_parser.py`, parser tests |
| BE-T07 | Autosave-First CLI Dispatch | blocked | BE-T03, BE-T04, BE-T06 | CLI | M | `tools/battle_estimator.py`, `tools/h3_save_parser.py`, CLI tests |
| BE-T08 | List Save Heroes Command | blocked | BE-T07 | CLI | S | `tools/battle_estimator.py` |
| BE-T09 | Interactive Wizard | blocked | BE-T07 | CLI | M | `tools/battle_estimator.py`, config helper |
| BE-T10 | Simulation Output Context | blocked | BE-T07 | CLI | S | `tools/battle_estimator.py` |
| BE-T11 | Parser Unit Tests | blocked | BE-T01, BE-T03, BE-T05, BE-T06 | quality | M | parser tests |
| BE-T12 | CLI/Wizard Tests | blocked | BE-T07, BE-T08, BE-T09 | quality | M | CLI tests, `tools/battle_estimator.py` |
| BE-T13 | Documentation Verification Pass | blocked | BE-T10, BE-T11, BE-T12 | quality | S | planning docs, checkpoint, usage docs |
