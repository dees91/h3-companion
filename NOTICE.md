# Notices

This repository was extracted from a local VCMI working tree with
`git-filter-repo`, preserving the battle-estimator related history.

The minimal VCMI configuration snapshot under `config/` is vendored as data for
hero metadata and skill metadata:

- `config/heroClasses.json`
- `config/skills.json`
- `config/heroes/*.json`

VCMI is licensed under GPL-2.0. A copy of the VCMI license text is included at
`third_party/vcmi/license.txt`.

The custom battle-estimator rules under `config/battle_estimator/` are project
rules and were preserved through the filtered history.
