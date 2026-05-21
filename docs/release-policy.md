# Release And Compatibility Policy

This document defines how H3 Companion is versioned, released, and kept
compatible for users.

## Release Status

The first public release should be `v0.1.0`.

Use `0.x` releases while the project is useful but still stabilizing. The save
parser, map parser, GUI workflow, and recommendation rules are functional, but
some contracts are still intentionally narrow and based on observed Heroes III
Complete data.

Use `v1.0.0` only when the documented CLI, config format, and main GUI workflow
are stable enough that breaking changes should be rare.

## Versioning

H3 Companion uses semantic versioning:

- `MAJOR`: breaking changes to stable public contracts.
- `MINOR`: new features, compatibility improvements, or breaking changes during
  the `0.x` phase.
- `PATCH`: bug fixes, documentation updates, test fixes, and small compatible
  improvements.

During `0.x`, minor releases may include breaking changes, but every breaking
change must be called out in `CHANGELOG.md` and GitHub release notes.

Examples:

- `v0.1.1`: focused bug fix or docs-only release.
- `v0.2.0`: new user-facing feature, parser expansion, GUI workflow change, or
  intentional breaking change before `v1.0.0`.
- `v1.0.0`: first stable release with a stronger compatibility promise.

## Compatibility Surface

### Stable Public Surface

These should stay compatible whenever practical:

- Documented CLI entrypoints:
  - `python3 tools/battle_estimator.py`
  - `python3 tools/battle_estimator_gui.py`
- Documented CLI flags and common examples in `README.md`.
- User config location:
  - `$HOME/.config/vcmi-battle-estimator/config.json`
- Basic support for `.GM1`, `.GM2`, and `.h3m` input files.
- The repository license and VCMI attribution model in `NOTICE.md`.

Changing these requires a compatibility note. Removing or renaming them should
use the deprecation process below unless the current behavior is unsafe or
clearly broken.

### Additive Or Migrated Surface

These may evolve, but old user data should keep loading where reasonable:

- User config schema under `config.json`.
- Hidden target state.
- Manual current-skill state for hero recommendations.
- Recommendation rule data under `config/battle_estimator/`.

Prefer additive changes. If a stored shape changes, add migration or tolerant
loading so older local configs do not break.

### Best-Effort Surface

These are supported, but not guaranteed to be exact across all Heroes III files:

- Save parsing for unobserved `.GM1` and `.GM2` structures.
- H3M parsing for unobserved object layouts.
- Battle simulation accuracy versus real Heroes III mechanics.
- Strategic pathfinding accuracy versus exact in-game movement rules.

Fixes here can change outputs when the old result was incomplete or wrong.
Document material behavior changes in `CHANGELOG.md`.

### Internal Surface

These are not stable public APIs:

- GUI JSON endpoints under the local HTTP server.
- Python module internals, dataclasses, and helper functions.
- Cache files under `$HOME/.cache/vcmi-battle-estimator`.
- Frontend DOM structure and CSS class names.
- Planning documents under `planning/`.

Internal changes do not require deprecation, but releases should still mention
visible behavior changes.

## Deprecation Policy

Before `v1.0.0`:

- Prefer keeping existing documented CLI usage working.
- Breaking changes are allowed in minor releases.
- Every breaking change must appear in `CHANGELOG.md` under
  `Compatibility Notes`.
- Provide a replacement command or migration path when practical.

After `v1.0.0`:

- Avoid breaking the stable public surface in minor or patch releases.
- Deprecate first, remove later.
- Keep deprecated documented CLI usage for at least one minor release unless it
  is unsafe or actively misleading.
- Major releases may remove deprecated behavior after documenting the migration.

## Release Checklist

Before tagging a release:

1. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

2. Run the full test suite and JavaScript syntax check:

   ```bash
   python3 -m unittest
   node --check tools/battle_estimator_gui/app.js
   ```

3. Start the GUI and smoke-check the main workflow:

   ```bash
   python3 tools/battle_estimator_gui.py
   ```

4. Review public-safety basics:

   ```bash
   find . -path ./.git -prune -o -type f \( \
     -iname '*.GM1' -o -iname '*.GM2' -o -iname '*.h3m' -o \
     -iname '*.h3s' -o -iname '*.h3c' -o -iname '*.sav' -o \
     -iname '*.zip' -o -iname '*.7z' -o -iname '*.rar' -o \
     -iname '.env*' -o -iname '*.pem' -o -iname '*.key' \
   \) -print
   ```

5. Update `CHANGELOG.md`:

   - move user-facing entries from `Unreleased` to the release version,
   - include `Compatibility Notes`,
   - include known limitations when they matter for the release.

6. Review `README.md`, `NOTICE.md`, screenshots, and license notes.

7. Tag the release:

   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```

8. Create the GitHub release from the tag.

For now, source archives generated by GitHub are the release artifact. Do not
publish bundled game data, saves, generated maps, or Heroes III assets.

## Release Notes Template

Use this structure for GitHub release notes:

```markdown
## Summary

Short description of the release.

## Highlights

- ...

## Compatibility Notes

- ...

## Known Limitations

- ...

## Verification

- `python3 -m unittest`
- `node --check tools/battle_estimator_gui/app.js`
```
