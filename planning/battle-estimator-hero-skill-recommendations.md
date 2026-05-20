# Implementation Plan: Hero Skill Recommendations

## Overview

Add a separate hero secondary-skill recommendation module for the battle
estimator GUI. For the selected hero, the tool should show the current
secondary skills, recommend the best next skills, highlight low-priority traps,
and compare concrete level-up offers such as `Basic Earth Magic` vs
`Expert Necromancy`. The MVP is intentionally limited to secondary skills:
no artifacts, spellbook parsing, banned-skill rules, map-context heuristics, or
automatic current-skill extraction from save files.

## Product Decisions

- Recommendations are possible with the current codebase, but the current save
  parser does not yet expose current secondary skills. MVP uses manual skill
  state in the GUI, prefilled from VCMI hero starting skills.
- Recommendation rules are custom battle-estimator rules, not generated from
  VCMI alone. VCMI remains the factual source for hero identity, class,
  faction, specialty, starting skills, and skill metadata.
- Scope is standard faction heroes only: 144 heroes from `castle`, `conflux`,
  `dungeon`, `fortress`, `inferno`, `necropolis`, `rampart`, `stronghold`, and
  `tower`. Exclude `special.json`, `portraits.json`, and
  `portraitsChronicles.json`.
- Full standard-hero rule coverage is required before GUI integration.
- Recommendations target the user's main use case: multiplayer 2v2 tempo play,
  map clearing, movement, combat value, and main-hero scaling.
- MVP has one default role: `main`. The rules format should leave room for
  future `scout`, `support`, and `economy` roles, but the GUI does not need role
  switching in MVP.
- Skill scoring uses numeric scores for deterministic ordering and readable
  tiers for display.
- Skill-vs-skill compares concrete offered target levels, not just skill names.
- If a hero already has 8 different secondary skills, new skills are marked
  unavailable and only existing-skill upgrades can be recommended.
- Banned skills, item recommendations, and automatic save parsing of current
  skills are out of scope for MVP.
- The GUI should expose a `Skills` action for the currently selected hero and
  open a scrollable dialog instead of squeezing the workflow into the side
  panel.

## Data Sources

- `config/heroes/{castle,conflux,dungeon,fortress,inferno,necropolis,rampart,stronghold,tower}.json`
  for standard hero metadata and starting skills.
- `config/heroClasses.json` for class-to-faction and might/magic affinity.
- `config/skills.json` for skill IDs, display metadata, effects, and generic
  gain chances. This file contains JSON-style comments, so the loader needs
  JSONC support or a controlled comment-stripping parser.
- `planning/hero-isra-skills-and-tips.md` as an initial quality reference for
  Isra/Necropolis rules.

## Proposed Rule File

Recommended path:

- `config/battle_estimator/hero_skill_recommendations.json`

Recommended shape:

```json
{
  "version": 1,
  "scope": {
    "hero_files": [
      "castle",
      "conflux",
      "dungeon",
      "fortress",
      "inferno",
      "necropolis",
      "rampart",
      "stronghold",
      "tower"
    ],
    "excluded_files": ["special", "portraits", "portraitsChronicles"]
  },
  "default_role": "main",
  "tiers": {
    "S": { "min_score": 90 },
    "A": { "min_score": 75 },
    "B": { "min_score": 55 },
    "C": { "min_score": 35 },
    "D": { "min_score": 0 }
  },
  "global": {
    "main": {
      "skills": {
        "earthMagic": {
          "score": 95,
          "reasons": ["mass_slow", "town_portal", "animate_dead"]
        }
      }
    }
  },
  "factions": {},
  "classes": {},
  "specialties": {},
  "heroes": {
    "isra": {
      "role": "main",
      "skills": {
        "necromancy": {
          "score": 98,
          "upgrade_priority": 12,
          "reasons": ["hero_specialty", "snowball"]
        }
      }
    }
  }
}
```

The exact schema can change during Task 1, but it must support global,
faction, class, specialty, and hero-specific layers without duplicating full
builds for every hero.

## Recommendation Inputs And Outputs

### Input

```json
{
  "hero_key": "isra",
  "role": "main",
  "current_skills": [
    { "skill": "necromancy", "level": "advanced" },
    { "skill": "earthMagic", "level": "basic" }
  ],
  "offers": [
    { "skill": "necromancy", "level": "expert" },
    { "skill": "offence", "level": "basic" }
  ]
}
```

### Output

```json
{
  "hero_key": "isra",
  "role": "main",
  "current_skills": [],
  "top_next": [],
  "avoid": [],
  "offer_comparison": {
    "winner": "necromancy:expert",
    "offers": []
  }
}
```

Output entries should include skill ID, display name, offered target level,
score, tier, availability, and short reason codes.

## Task List

## Task 1: Define Recommendation Data Contracts

**Status:** done

**Description:** Create the in-code data contracts for skill IDs, skill levels,
current skill slots, recommendation entries, offer comparison inputs, and
recommendation outputs. Keep these contracts independent from the GUI server so
the module can be tested directly.

**Acceptance criteria:**
- [x] Skill levels are normalized to `basic`, `advanced`, and `expert`.
- [x] Current skills reject duplicate skill IDs.
- [x] Current skills enforce at most 8 distinct secondary skills.
- [x] Offer inputs include both skill ID and target level.
- [x] Recommendation entries include score, tier, availability, and reason
      codes.

**Verification:**
- [x] Add focused unit tests for valid and invalid contract inputs.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Added GUI-independent recommendation contract types in
`tools/hero_skill_recommender.py` with normalized skill levels, current-skill
deduplication and slot-limit checks, concrete offer inputs, recommendation
entries, and typed recommendation/comparison outputs. Plan and code were
reviewed by subagents; the output comparison contract was tightened after code
review to require two offers and a winner matching one of them. Required tests
passed with 15 focused cases.

**Dependencies:** None

**Files likely touched:**
- `tools/hero_skill_recommender.py`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Small

## Task 2: Add VCMI Hero And Skill Metadata Loader

**Status:** done

**Description:** Add a small metadata loader that reads standard hero files,
hero classes, and skill metadata from VCMI config. It should produce normalized
hero records keyed by hero ID and expose starting secondary skills for each
standard hero.

**Acceptance criteria:**
- [x] Loader includes exactly the nine standard faction hero files.
- [x] Loader excludes `special.json`, `portraits.json`, and
      `portraitsChronicles.json`.
- [x] Loader finds 144 standard heroes.
- [x] Each loaded hero has key, display name, class, faction, affinity,
      specialty summary, and starting skills.
- [x] Loader can parse `config/skills.json` despite JSON-style comments.

**Verification:**
- [x] Add metadata tests for hero count, excluded files, Isra starting skills,
      class/faction lookup, and skill metadata parsing.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Added a VCMI metadata loader with exact standard hero-file
scope, explicit excluded-file metadata, normalized hero/class/skill records,
starting secondary skills, and JSONC parsing for commented config files. The
loader resolves 144 standard heroes, preserves camelCase skill IDs, derives
display-name fallbacks when config text is absent, and validates starting-skill
IDs against loaded skill metadata. Plan and code were reviewed by subagents;
after review, block-comment stripping was tightened so removed comments do not
merge neighboring JSON tokens. Required tests passed with 22 focused cases.

**Dependencies:** Task 1

**Files likely touched:**
- `tools/hero_skill_recommender.py`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Medium

## Task 3: Define And Validate Recommendation Rule Schema

**Status:** done

**Description:** Add the custom recommendation rules file and validation logic.
The schema should support global, faction, class, specialty, and hero layers,
numeric scores, tier derivation, upgrade priority modifiers, and reason codes.

**Acceptance criteria:**
- [x] Rules file exists at
      `config/battle_estimator/hero_skill_recommendations.json`.
- [x] Validation rejects unknown skill IDs.
- [x] Validation rejects unknown hero, class, and faction keys.
- [x] Validation rejects out-of-range scores.
- [x] Validation confirms every reason code is a short stable identifier.
- [x] Validation confirms all standard heroes are covered by fallback rules,
      even before hero-specific overrides are complete.

**Verification:**
- [x] Add schema validation tests for valid rules and representative invalid
      rules.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Added strict JSON recommendation rules at
`config/battle_estimator/hero_skill_recommendations.json` with global fallback
main-hero guidance plus focused Necropolis, Death Knight, Necromancy-specialist,
and Isra overrides. Added validation for exact scoped hero files, tier
thresholds, layer keys, skill IDs, finite scores, derived tiers, optional
upgrade priority, short reason codes, and default-role fallback coverage across
all 144 standard heroes. Plan and code were reviewed by subagents; after code
review, `reason_codes` now rejects JSON objects/null/scalars and rules
`version` rejects bool values. Required tests passed with 34 focused cases.

**Dependencies:** Task 2

**Files likely touched:**
- `config/battle_estimator/hero_skill_recommendations.json`
- `tools/hero_skill_recommender.py`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Medium

## Task 4: Implement Core Recommendation Scoring

**Status:** done

**Description:** Implement score resolution by layering global, faction, class,
specialty, and hero-specific rules. Generate recommended next legal skill
offers and low-priority/avoid entries from current skill state.

**Acceptance criteria:**
- [x] Existing skills can be recommended only as legal upgrades.
- [x] New skills are recommended only when the hero has fewer than 8 distinct
      secondary skills.
- [x] Full 8-skill state marks new skills as unavailable.
- [x] Sorting is deterministic by score, tier, skill priority, and skill ID.
- [x] Output includes concise reason codes explaining each recommendation.

**Verification:**
- [x] Add tests for Isra's `Advanced Necromancy -> Expert Necromancy` priority.
- [x] Add tests for new-skill recommendations with open slots.
- [x] Add tests for full-slot behavior.
- [x] Add tests for deterministic tie ordering.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Added `recommend_hero_skills` core scoring that resolves
layered global, faction, class, specialty, and hero rules into ranked
`RecommendationOutput` entries. Existing skills are emitted only as legal next
level upgrades, expert skills are omitted, new skills target Basic, and full
8-slot builds keep new candidates visible as unavailable with
`no_open_skill_slot` while existing upgrades remain available. Sorting is
deterministic by score, tier, upgrade priority, skill ID, and target level, and
`avoid` uses the same order for D-tier or unavailable entries. Plan and code
were reviewed by subagents; after code review, a regression test was added for
upgrade-priority ordering. Required tests passed with 42 focused cases.

**Dependencies:** Task 3

**Files likely touched:**
- `tools/hero_skill_recommender.py`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Medium

## Task 5: Implement Skill-Vs-Skill Comparison

**Status:** done

**Description:** Add a comparison function that evaluates concrete level-up
offers using the same scoring engine as top-next recommendations.

**Acceptance criteria:**
- [x] Comparison accepts two or more concrete offers.
- [x] Offers include target levels, such as `basic` or `expert`.
- [x] Illegal offers are marked with availability reasons.
- [x] Winner selection is deterministic.
- [x] The result includes a short explanation for why the winner wins.

**Verification:**
- [x] Add tests for upgrade vs new skill.
- [x] Add tests for two legal new skills.
- [x] Add tests for illegal new skill when slots are full.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Added `compare_skill_offers`, which evaluates concrete
level-up offers through the same layered rule scores and deterministic sort
used by top-next recommendations. The comparison preserves each offered target
level, rejects duplicate exact offer keys, marks illegal upgrades/new skills
with availability reason codes, keeps output offers in input order, and chooses
the winner only from available offers. Winner explanations now distinguish
higher score, higher tier, higher upgrade priority, deterministic tie-breaks,
single available offer, and no available offers. Plan and code were reviewed by
subagents; after review, a deterministic tie-break regression test was added.
Required tests passed with 49 focused cases.

**Dependencies:** Task 4

**Files likely touched:**
- `tools/hero_skill_recommender.py`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Small

## Task 6: Prepare Full Standard-Hero Rule Coverage

**Status:** done

**Description:** Fill the rules file so every standard hero has useful
recommendations under the `main` role. This should be done after the validator
exists, and can later be delegated to xhigh-effort subagents by faction or hero
class when implementation starts.

**Acceptance criteria:**
- [x] All 144 standard heroes are covered.
- [x] Each standard faction has faction/class-level guidance.
- [x] Important specialists have hero-specific overrides where fallback rules
      would be too generic.
- [x] Rules reflect tempo-oriented multiplayer main-hero play.
- [x] Special/campaign heroes remain excluded.
- [x] No rule entry copies a full build unnecessarily when a fallback layer is
      enough.

**Verification:**
- [x] Add or run a coverage test that lists any standard hero without effective
      recommendations.
- [x] Manually review at least one hero from each faction.
- [x] Run `python3 -m unittest tests.test_hero_skill_recommender`.

**Completion notes:** Expanded the rules file with layered `main` guidance for
all 9 standard factions and all 18 standard classes, plus shared secondary-skill
specialty layers and small hero-specific overrides for 25 important specialists.
Global rules now also score common situational and low-priority skills so legal
offers have explicit explanations instead of falling through as unknown. Added
coverage tests that require non-empty faction/class guidance, recommendations
for all 144 standard heroes using VCMI starting skills, excluded special/campaign
scope, small hero override sizes, and metadata-consistent `hero_specialty`
reason codes. Manually reviewed one hero per faction: Orrin/Archery,
Kyrre/Logistics, Solmyr/Air Magic, Nymus/Offence, Isra/Necromancy,
Gunnar/Logistics, Crag Hack/Offence, Tazar/Armorer, and Luna/Fire Magic all
surface the expected S/A top guidance. Plan and code were reviewed by
subagents; after code review, Adela's Diplomacy reason was corrected because her
VCMI specialty is Bless rather than Diplomacy. Required tests passed with 55
focused cases.

**Dependencies:** Task 5

**Files likely touched:**
- `config/battle_estimator/hero_skill_recommendations.json`
- `tests/test_hero_skill_recommender.py`

**Estimated scope:** Medium

## Task 7: Persist Manual Current-Skill State

**Status:** done

**Description:** Extend user config with per-map, per-hero manually edited
secondary-skill state. When no manual state exists, selected heroes should
prefill from VCMI starting skills.

**Acceptance criteria:**
- [x] Config stores skill state outside the repo.
- [x] State is keyed by existing map key and stable hero ID.
- [x] Missing state falls back to VCMI starting skills.
- [x] Reset removes manual state for that hero and returns to starting skills.
- [x] Invalid stored states are ignored or cleaned without breaking GUI load.

**Verification:**
- [x] Add config load/save tests for storing, updating, resetting, and ignoring
      invalid skill states.
- [x] Run `python3 -m unittest tests.test_h3_save_parser`.

**Completion notes:** Added `manual_hero_current_skills_by_map` to the
user-global config JSON at `~/.config/vcmi-battle-estimator/config.json`, keyed
by the existing map key and GUI-style stable hero instance IDs such as
`hero:512`. Added `get_config_hero_skill_state`,
`set_config_hero_skill_state`, and `reset_config_hero_skill_state`; callers pass
the standard VCMI hero key separately so missing manual state falls back to the
hero's starting skills without leaking edits between duplicate hero instances.
The manual-state loader is deliberately tolerant: malformed maps, hero IDs,
skill lists, duplicate skills, unknown skill IDs, and invalid levels are ignored
for that stored hero state and are removed on the next save. Existing strict
config validation for other fields remains unchanged. Plan and code were
reviewed by subagents; code review requested two additional tests for manual
readback and empty-skill reset behavior. Required tests passed with 105 focused
cases.

**Dependencies:** Task 6

**Files likely touched:**
- `tools/h3_save_parser.py`
- `tests/test_h3_save_parser.py`

**Estimated scope:** Medium

## Task 8: Add Hero Skill Recommendation API

**Status:** done

**Description:** Add GUI backend endpoints that return the selected hero's
skill metadata, current editable state, top recommendations, avoid entries, and
skill-vs-skill comparison results.

**Acceptance criteria:**
- [x] API rejects missing or invalid hero IDs.
- [x] API returns starting skills when no manual state exists.
- [x] API persists edited current-skill slots.
- [x] API returns top recommendations and avoid entries.
- [x] API compares concrete level-up offers.
- [x] API responses include enough metadata for the GUI dialog without
      requiring client-side rule evaluation.

**Verification:**
- [x] Add API tests for load, save, reset, recommendations, comparison, invalid
      hero, and invalid skill state.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion notes:** Added POST API routes for `/api/hero-skills`,
`/api/hero-skills/save`, `/api/hero-skills/reset`, and
`/api/hero-skills/compare`. The endpoints resolve the GUI stable hero ID to the
current snapshot hero, bridge the save hero name to standard VCMI hero metadata,
use the Task 7 config helpers for manual state persistence, and return
GUI-ready skill metadata, current skills with `current_skills_source`,
recommendation `top_next`/`avoid` lists, and optional concrete offer comparison.
Role and hero ID validation happen at the API boundary; malformed hero IDs,
unknown heroes, unresolved standard hero names, bad skill states, invalid
offers, duplicate offers, invalid roles, and recommender data load failures now
return JSON API errors instead of requiring client-side rule evaluation. Plan
and code were reviewed by subagents; code review requested stricter malformed
hero ID handling and recommender load-error mapping, both covered by additional
tests. Required GUI tests passed with 88 focused cases.

**Dependencies:** Task 7

**Files likely touched:**
- `tools/battle_estimator_gui.py`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 9: Add Skills Dialog UI

**Status:** done

**Description:** Add a `Skills` action for the currently selected hero that
opens a scrollable dialog. The dialog should show hero metadata, the 8-slot
skill editor, top recommendations, avoid entries, and a skill-vs-skill compare
control.

**Acceptance criteria:**
- [x] `Skills` action is disabled or clearly unavailable without a selected
      hero.
- [x] Dialog opens for the currently selected hero.
- [x] Current skill slots can be edited with skill and level selects.
- [x] Duplicate skills and more than 8 skills are prevented.
- [x] Reset restores VCMI starting skills.
- [x] Top recommendations and avoid entries refresh after edits.
- [x] Skill-vs-skill comparison accepts two concrete offers and shows a winner.

**Verification:**
- [x] Add GUI tests for dialog open/close, slot editing, reset, recommendation
      refresh, and offer comparison.
- [x] Manual GUI check on Isra and at least one non-Necropolis hero.
- [x] Run `python3 -m unittest tests.test_battle_estimator_gui`.

**Completion notes:** Added a `Skills` toolbar action and a scrollable
`Hero Skills` dialog with current-skill slot editing, hero metadata, top
recommendations, avoid entries, reset/save actions, and two-offer comparison.
The dialog uses the Task 8 API only: it loads current or starting skills,
persists edited slot order, resets to VCMI starting skills, and renders
server-provided recommendation and comparison results without client-side rule
evaluation. The editor renders a fixed capped slot list from `max_skills`,
prevents duplicate nonblank current skills, disables controls while save/reset
or compare requests are in flight, and ignores stale responses after close or
selected-hero changes. Plan and code were reviewed by subagents; code review
found request-time editable controls and stale `Skills` button sync, both fixed
with regression coverage. Frontend tests cover open/close, slot editing,
duplicate prevention, save payload order, reset, recommendation refresh,
comparison winner display, stale response handling, and API error display.
Manual local GUI-server checks covered Isra and Marius. Required GUI tests passed
with 88 focused cases.

**Dependencies:** Task 8

**Files likely touched:**
- `tools/battle_estimator_gui/index.html`
- `tools/battle_estimator_gui/app.js`
- `tools/battle_estimator_gui/style.css`
- `tests/test_battle_estimator_gui.py`

**Estimated scope:** Medium

## Task 10: End-To-End Skill Recommendation Verification

**Status:** done

**Description:** Verify the full workflow with real autosaves: select a hero,
open the skills dialog, edit current skills, compare level-up offers, refresh
the save, and confirm the manual skill state remains stable for the same
map/hero.

**Acceptance criteria:**
- [x] Full `python3 -m unittest` passes.
- [x] GUI loads a current save and opens recommendations for selected hero.
- [x] Manual skill edits persist across refresh.
- [x] Reset returns to starting skills.
- [x] Skill-vs-skill gives a deterministic result for concrete offers.
- [x] Standard hero coverage test passes for all 144 scoped heroes.

**Verification:**
- [x] Run `python3 -m unittest`.
- [x] Manual GUI check with a current Diamond save.

**Completion notes:** Verified the full recommendation workflow against the
latest real Diamond autosave discovered under `DEFAULT_AUTOSAVE_ROOT`:
`Random/PlayerTwo/2026.05.19 20;00 Diamond`, latest save `413.GM2`. The GUI
server checks used an isolated temporary config path and confirmed the real
`h3_save_parser.CONFIG_PATH` digest stayed unchanged. The workflow loaded
`/api/state`, selected standard hero `Coronius (hero:731686)`, resolved him to
standard key `coronius`, confirmed starting skills `wisdom:basic` and
`scholar:basic`, saved a manual edit adding `logistics:basic`, and confirmed
the exact manual state after state refresh, fresh `/api/hero-skills`, and a
new temporary server process using the same temp config. A headless Chrome GUI
dialog check opened the actual `Skills` dialog on the same Diamond save,
performed the edit, refreshed the save, reopened the dialog, compared concrete
offers `logistics:advanced` vs `earthMagic:basic` with deterministic winner
`logistics:advanced`, and reset back to `wisdom:basic` plus
`scholar:basic`. Full `python3 -m unittest` passed with 336 tests in 34.833s
OK, including the 144 scoped standard-hero coverage tests.

**Dependencies:** Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9

**Files likely touched:**
- No production files expected unless verification finds issues.

**Estimated scope:** Small

## Checkpoints

### Checkpoint: Recommendation Core

After Tasks 1-5:

- [ ] Metadata loading works for standard heroes and skills.
- [ ] Rule schema validation works.
- [ ] Recommender can rank next skills and compare concrete offers.
- [ ] `python3 -m unittest tests.test_hero_skill_recommender` passes.

### Checkpoint: Full Rules

After Task 6:

- [ ] All 144 standard heroes have effective `main` recommendations.
- [ ] Faction/class/specialty/hero layers validate cleanly.
- [ ] At least one hero from each faction has been manually reviewed.

### Checkpoint: Persistence And API

After Tasks 7-8:

- [ ] Manual current-skill state persists per map and hero.
- [ ] API can load, save, reset, recommend, and compare.
- [ ] `python3 -m unittest tests.test_h3_save_parser tests.test_battle_estimator_gui`
      passes.

### Checkpoint: Complete

After Tasks 9-10:

- [ ] Skills dialog works for selected hero.
- [ ] Top recommendations, avoid entries, and skill-vs-skill are usable in the
      GUI.
- [ ] Full `python3 -m unittest` passes.
- [ ] Manual GUI check confirms the workflow is useful during level-up
      decisions.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Rule quality is inconsistent across 144 heroes. | High | Validate coverage mechanically and require manual review by faction before GUI integration. |
| Rules become a duplicated build list for every hero. | Medium | Use layered global/faction/class/specialty rules and reserve hero overrides for meaningful differences. |
| Recommendations imply exact game-state awareness that MVP lacks. | Medium | Label current skills as manually maintained and do not claim artifact, spellbook, map, or save-derived context. |
| Skill IDs drift between VCMI config and custom rules. | Medium | Validate all custom rule skill IDs against loaded VCMI skill metadata. |
| JSONC parsing of VCMI config is brittle. | Medium | Keep a narrow parser with tests against `config/skills.json`; keep custom rule files strict JSON. |
| GUI dialog becomes too dense. | Medium | Use a scrollable dialog with compact sections and keep long strategy prose out of MVP. |
| Manual skill state leaks between games. | High | Key state by map key and stable hero ID, with reset to VCMI starting skills. |

## Future Work

- Parse current secondary skills automatically from save files.
- Add item/artifact and spellbook-aware advice.
- Add banned-skill/template rule support.
- Add role switching for scout/support/economy heroes.
- Add context-aware recommendations using map terrain, water density, and
  available towns or spells.
