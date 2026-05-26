# Changelog

All notable user-facing changes should be documented in this file.

This project follows semantic versioning with a pre-1.0 compatibility policy
defined in [docs/release-policy.md](docs/release-policy.md).

## [Unreleased]

### Added

- Dual-level map view for two-level maps, with Surface and Underground lanes
  rendered side by side.
- Portal relation hints now include cross-level ghost destinations, destination
  level badges, and multi-exit/non-deterministic indicators.
- Exact save-derived current town ownership for observed GM1/GM2 town-state
  records, with proxy fallback only when exact records are absent. Current
  owners are exposed in town targets, map markers, town details, and owned-town
  alerts; invalid or ambiguous ownership remains unavailable rather than
  falling back to initial H3M owners.
- Defensive owned-town alerts in the GUI, configured with `My color` and
  `Alert radius`, with alert rows that focus the threatening enemy hero and
  hover previews that show the alert radius plus every threatened town.
- Save-derived hero combat context for verified GM1 records and the bounded
  offset-65/XOR-`0x01` GM2 profile, exposing current primary and secondary
  skills in hero snapshots plus applied passive combat modifiers and per-side
  model labels in estimate payloads, CLI output, and the GUI estimate panel.

### Changed

- Map marker overlap now prioritizes towns, portals, and heroes above neutral
  monster markers.
- Hero Ranking now sorts positioned save heroes by pairwise combat score from
  current battle estimates, shows ranking numbers on hero map markers, and
  keeps army AI value visible as secondary context.
- The map stage now has an `Auto center` toggle. Turning it off preserves the
  current pan during automatic focus actions while still allowing level changes
  and detail updates.
- The map stage now also includes `Reset view` for manually fitting the current
  map view without changing the `Auto center` setting.
- Subterranean gates with a single resolved paired gate now click through to the
  destination level outside path mode.
- Path, scan, context-menu, and portal-destination interactions now work in the
  dual-level map view.
- Nearby neutral and hero-vs-hero estimates now use save-derived Attack/Defense
  plus Offence, Armorer, and Archery when those fields are parsed and validated.

### Fixed

- None.

### Compatibility Notes

- Existing local configs keep `My color` unset and use the default
  `Alert radius` of `10` until changed in the GUI.
- Battle estimates explicitly label applied save-derived combat modifiers and
  omitted components. Artifacts, active spells, morale/luck, and tactics are
  visible as omitted model components; terrain, specialties, and many creature
  special abilities remain simplified or unmodeled.

## [0.1.0] - 2026-05-21

Initial public preview release.

### Added

- Local browser GUI served from `tools/battle_estimator_gui.py`.
- CLI battle estimator and interactive wizard in `tools/battle_estimator.py`.
- GM1/GM2 save discovery, save navigation, and hero army extraction for
  observed single-player, multiplayer, and hotseat save structures.
- H3M map parsing for neutral monsters, towns, portals, subterranean gates,
  terrain, and route layers.
- Map view with hero, neutral monster, town, portal, route, and pathfinding
  overlays.
- Nearby target scanning and battle estimation for neutral stacks and enemy
  heroes.
- Manual hidden-target state for neutral and hero markers.
- Hero ranking dialog based on army AI value.
- Secondary-skill recommendation UI and backend rules for standard faction
  heroes.
- Minimal VCMI-derived configuration snapshot for hero, hero-class, and
  secondary-skill metadata.
- Release and backward compatibility policy documentation.
- Agent documentation routing in `AGENTS.md`.

### Compatibility Notes

- This is a `0.x` public preview. Documented CLI commands and the user config
  location are intended to remain usable, but minor releases may still include
  breaking changes when the project needs to correct early design decisions.
- The GUI JSON API is internal to the bundled frontend and is not yet a stable
  public API.
- Save and map parsing are best-effort for observed Heroes III Complete files
  and may need fixes for unobserved save/map structures.

### Known Limitations

- Battle simulation is intentionally simplified and does not model hero stats,
  spells, artifacts, morale, luck, or many special creature abilities.
- Pathfinding is strategic route search, not exact Heroes III movement.
- The tool does not include Heroes III game assets, saves, maps, or binaries.
