# Notices

H3 Companion is an independent local utility for Heroes of Might and Magic III
Complete. It is not part of, endorsed by, or distributed with VCMI.

## VCMI-Derived Data And References

This repository vendors a minimal VCMI configuration snapshot used by the hero
skill recommender:

- `config/heroClasses.json`
- `config/skills.json`
- `config/heroes/*.json`

Those files provide standard hero identity, class metadata, starting secondary
skills, and secondary-skill metadata.

The battle estimator also uses VCMI as a reference for Heroes III mechanics and
data, including damage-related constants and creature statistics. The H3M parser
uses VCMI-compatible object template interpretation for map object masks,
portals, subterranean gates, towns, neutral monsters, and route layers.

No VCMI binaries, full source tree, runtime installation, or VCMI game assets
are required by this project.

## License

VCMI source code is licensed under GNU GPL version 2 or later. The official VCMI
project states this in its public README at <https://github.com/vcmi/vcmi>, and
a copy of the GPLv2 text vendored with VCMI is included at
`third_party/vcmi/license.txt`.

Because this project includes VCMI-derived data and mechanics references, H3
Companion is distributed under GNU GPL version 2 or later. See `LICENSE`.

The custom recommendation rules under `config/battle_estimator/` are project
data and are distributed under the same project license.

## Game Assets And Saves

This repository should not contain proprietary Heroes III assets, generated
random maps, game saves, screenshots, user configuration, or local cache data.
