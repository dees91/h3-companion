# Battle Estimator Autosave Brief

> **Source**: `grill-me` planning session on 2026-05-18, plus the save parsing
> investigation captured in
> [`tools/battle_estimator_save_parsing_checkpoint.md`](../tools/battle_estimator_save_parsing_checkpoint.md).
>
> **Related plan**:
> [`phase-1-battle-estimator-autosave-mvp-tasks.md`](./phase-1-battle-estimator-autosave-mvp-tasks.md).

## Product Intent

`tools/battle_estimator.py` should become an autosave-first battle estimator for
the user's Heroes III multiplayer games. The tool should read the current hero
army from the latest autosave and run the existing battle estimate against a
manually supplied enemy army.

The primary use case is a 2v2 multiplayer game:

- user + brother on one team
- two AI players on the opposing team
- HD Mod / Porting Kit creates autosaves every turn
- the user wants to quickly select any of their heroes and estimate a fight
  against a chosen enemy stack or army

## Target Environment

For Phase 1, the target environment is intentionally hardcoded to the user's
current Porting Kit install. Do not generalize this prematurely.

Default autosave root:

```text
~/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games/Random/PlayerTwo
```

Observed current game folder example:

```text
2026.04.26 20;45 Diamond
```

Observed autosaves:

```text
337.GM2
415.GM2
417.GM2
GAME_BEGIN.GM2
```

Controlled comparison file:

```text
415_moved.GM1
```

`PlayerTwo` is hardcoded for Phase 1. Do not implement player-folder discovery or
multi-wrapper discovery in the MVP.

## Core Product Decisions

### Autosave-First UX

The new workflow is autosave-first. Backward compatibility with the old manual
army CLI is not a design constraint.

Primary command:

```bash
python3 tools/battle_estimator.py Isra vs "horde of ancient behemoth"
```

Equivalent explicit command:

```bash
python3 tools/battle_estimator.py --hero Isra vs "horde of ancient behemoth"
```

With no arguments, the tool should launch a simple terminal wizard:

```bash
python3 tools/battle_estimator.py
```

The wizard should:

1. resolve the current autosave folder,
2. select the latest save,
3. show selected folder and save,
4. list relevant heroes and armies,
5. ask for hero,
6. ask for enemy army,
7. run the estimate.

This terminal wizard is the Phase 1 substitute for GUI. A separate GUI is out
of scope until the parser and CLI behavior are stable.

### Autosave Folder Selection

Folder resolution priority:

1. `--autosave-dir PATH` for this invocation only
2. saved config `autosave_dir`
3. newest game folder under the hardcoded `Random/PlayerTwo` root

When using auto-discovery, choose the newest folder by the date encoded in the
folder name:

```text
YYYY.MM.DD HH;MM Template Name
```

Do not use filesystem `mtime` as the primary signal. Manual copies and test
files can make `mtime` misleading.

### Latest Save Selection

`latest` is the default when a save is not specified.

Eligible latest files:

```text
<number>.GM1
<number>.GM2
```

Selection rules:

1. choose the highest numeric save number,
2. if both `.GM1` and `.GM2` exist for the same number, prefer `.GM2`,
3. ignore special or manual names such as `GAME_BEGIN.GM2`, `BATTLE.GM2`,
   `AUTOSAVE.GM2`, and `415_moved.GM1`.

Explicit save selection should exist:

```bash
python3 tools/battle_estimator.py --save 415 --hero Isra vs "..."
python3 tools/battle_estimator.py --save-file "/path/to/415.GM2" --hero Isra vs "..."
```

### Hero Selection

Hero selection is by the name detected in the save data.

Supported forms:

```bash
python3 tools/battle_estimator.py Isra vs "..."
python3 tools/battle_estimator.py "Lord Haart" vs "..."
python3 tools/battle_estimator.py --hero Isra vs "..."
```

Matching should be case-insensitive. Prefix matching is acceptable only when it
is unambiguous.

If no hero is supplied in non-interactive mode, list relevant heroes and exit.
Do not guess.

If a hero name is missing or ambiguous, print candidates and exit. Do not
silently choose a hero.

### Hero Ownership and Team

Do not parse owner/team in Phase 1.

The save may contain the user's heroes, the brother's heroes, and AI heroes.
Phase 1 shows relevant hero candidates and relies on explicit hero selection by
name.

Future owner/team filters can be added later if the save structure is mapped
reliably.

### Enemy Army Input

Enemy army is manually supplied with the existing text format:

```bash
vs "horde of ancient behemoth"
vs "30 champion, 12 zealot"
```

Do not add creature abbreviations in Phase 1.

Do not parse neutral stacks, enemy heroes, map positions, or visible armies from
the save in Phase 1.

### Simulation Model Scope

Phase 1 reads only hero army stacks from the save.

Do not model:

- hero attack/defense/power/knowledge
- secondary skills
- artifacts
- morale and luck
- spells
- battlefield terrain and obstacles
- player ownership/team bonuses

The estimator output should clearly state that only creature stacks are modeled.

### Config

Use a user-global config file outside the repo:

```text
~/.config/vcmi-battle-estimator/config.json
```

Phase 1 config fields:

```json
{
  "autosave_dir": "/path/to/current/game/folder",
  "last_hero": "Isra"
}
```

Commands:

```bash
--set-autosave-dir PATH
--clear-autosave-dir
--show-config
```

`--set-autosave-dir` persists a concrete game folder. If config
`autosave_dir` exists, it wins over auto-discovery. `--clear-autosave-dir`
returns the tool to auto-discovery.

`last_hero` is used as a wizard default only. Do not use it to run a
non-interactive simulation unless the user explicitly selected that hero.

### Save Parsing

Phase 1 parser should live outside `battle_estimator.py`, likely:

```text
tools/h3_save_parser.py
```

The estimator script should remain responsible for CLI, simulation, and output.
The parser module should own:

- gzip save loading
- autosave folder resolution
- latest save selection
- GM1/GM2 hero army scanning
- hero candidate filtering and selection helpers
- config read/write helpers if they remain small

Known important parsing result:

`415.GM2` contains hero structures encoded by XOR `0x01`. After decoding, the
hero army structure matches normal HoMM3/h3sed offsets:

```text
hero_struct_start = name_offset - 169
army_types        = hero_struct_start + 113
army_counts       = hero_struct_start + 141
name              = hero_struct_start + 169
```

For the observed `Isra` hero:

```text
hero_struct_start = 782910
army_types        = 783023
army_counts       = 783051
name              = 783079
```

Decoded army in `415.GM2`:

```text
731 Skeleton Warrior
181 Zombie
59 Vampire Lord
47 Power Lich
19 Dread Knight
316 Skeleton
8 Ghost Dragon
```

Controlled swap in `415_moved.GM1` confirmed the parser can detect swapped
slots exactly.

### Relevant Hero Listing

Default hero lists should hide obvious starting armies and sort practical
candidates first.

Recommended default visibility rule:

```text
show if ai_value >= 5000 OR total_creatures >= 50
```

Add an `--all-heroes` option for full debug listing.

The list should show:

- selected game folder
- selected save
- hero name
- AI value
- army summary

### Output

Always print the selected source context:

```text
Game folder: 2026.04.26 20;45 Diamond
Save: 417.GM2
Hero: Isra
```

Use the hero name as the player army label:

```text
Isra: 731x Skeleton Warrior, 181x Zombie, ...
Wrog: horde Ancient Behemoth
```

Include a concise limitation note:

```text
Note: hero stats, skills, artifacts, spells, morale, and luck are not modeled.
```

## Non-Goals For Phase 1

- GUI
- owner/team detection
- map object or neutral stack parsing
- enemy hero parsing
- full h3sed integration
- support for arbitrary Porting Kit wrappers
- support for non-`PlayerTwo` random-map roots
- creature abbreviation aliases
- report export
- committing full save files as test fixtures

## Testing Policy

Do not commit full real save files.

Use synthetic tests for:

- XOR `0x01` hero army fixture
- normal/unencoded hero army fixture if implemented
- latest folder selection
- latest save selection
- hero filtering and ambiguous-name errors
- config read/write behavior

Small synthetic byte buffers are preferred over real save fragments.

