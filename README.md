# H3 Companion

H3 Companion is a local helper for Heroes of Might and Magic III Complete. It
reads autosaves and map files from a local installation, renders a simple map
view, and helps estimate which fights are worth taking.

This is an unofficial fan utility. It does not include Heroes III game assets,
maps, saves, or binaries; you need your own legally installed copy of the game.

## Features

- GM1/GM2 autosave discovery and save navigation.
- Hero army extraction from observed single-player, multiplayer, and hotseat
  saves.
- Battle estimation for manual armies, save heroes, nearby neutral stacks, and
  enemy heroes.
- Browser GUI with a simple tile map, hero/monster markers, target hiding,
  hero ranking, radius scans, and pathfinding overlays.
- H3M map parsing for neutral monsters, towns, portals, subterranean gates, and
  route layers.
- Secondary-skill recommendations for standard heroes.

## Quick Start

Run the local browser GUI:

```bash
python3 tools/battle_estimator_gui.py
```

By default it serves `http://127.0.0.1:8765`.

Run the CLI wizard:

```bash
python3 tools/battle_estimator.py
```

Run tests:

```bash
python3 -m unittest
node --check tools/battle_estimator_gui/app.js
```

## Local Paths

The default save root targets the common Porting Kit layout on macOS:

```text
$HOME/Applications/Heroes of Might and Magic 3.app/Contents/SharedSupport/prefix/drive_c/GOG Games/HoMM 3 Complete/Games
```

You can select a different save folder in the GUI. The tool stores local
preferences outside the repository under:

```text
$HOME/.config/vcmi-battle-estimator/config.json
```

The config directory name is retained for compatibility with older local
versions of the tool.

## VCMI Data

The project has no runtime dependency on the VCMI source tree or VCMI binaries.
It uses a small VCMI-derived configuration snapshot for standard hero, hero
class, and secondary-skill metadata:

- `config/heroClasses.json`
- `config/skills.json`
- `config/heroes/*.json`

Some battle-estimator constants and map parsing behavior are also documented
against VCMI as a mechanics reference. See `NOTICE.md` for details.

## License

H3 Companion is licensed under the GNU General Public License version 2 or
later. See `LICENSE`.

VCMI source code is licensed under GPL version 2 or later. The vendored VCMI
license text is kept at `third_party/vcmi/license.txt`. The upstream VCMI
project is at <https://github.com/vcmi/vcmi>.
