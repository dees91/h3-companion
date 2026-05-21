# H3 Companion

Local Heroes of Might and Magic III companion tools extracted from the VCMI
working tree.

## What Is Included

- autosave-first battle estimator,
- save parsing for GM1/GM2 autosaves,
- H3M map parsing for neutral targets, towns, portals, and route layers,
- local browser GUI,
- pathfinding and radius scan helpers,
- hero secondary-skill recommendations.

The current source layout intentionally keeps the historical `tools/`, `tests/`,
and `planning/` paths so the extracted git history remains easy to inspect.

## Usage

Run the browser GUI:

```bash
python3 tools/battle_estimator_gui.py
```

Run the CLI wizard:

```bash
python3 tools/battle_estimator.py
```

Run tests:

```bash
python3 -m unittest
```

## Data

The `config/battle_estimator/` rules are project data. The other files under
`config/` are a minimal VCMI config snapshot needed by the skill recommendation
module. See `NOTICE.md` and `third_party/vcmi/license.txt`.
