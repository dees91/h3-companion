# MCP Strategic Advisor Runbook

This runbook describes the optional local MCP workflow for asking an external
assistant for Heroes III tactical and strategic advice.

The MCP server is read-only except for its in-memory snapshot cache. It does
not change GUI state, selected heroes, hidden targets, local config, saves, or
maps.

## Prerequisites

Normal H3 Companion GUI, CLI, and test workflows remain mostly stdlib Python and
can run with the repo's usual `python3`.

Starting the MCP server requires:

- Python `>=3.10`
- the official `mcp` Python SDK
- an MCP-capable local client

The recommended command uses `uv` so the SDK is not a normal repo dependency:

```bash
uv run --python 3.13 --with mcp python tools/battle_estimator_mcp.py
```

Run that from the repository root. If your MCP client launches from another
working directory, use an absolute script path and explicit placeholder
overrides. Do not commit client config files.

Alternative setup:

```bash
python -m pip install mcp
python tools/battle_estimator_mcp.py
```

Use that only inside a Python `>=3.10` virtual environment. `python3
tools/battle_estimator_mcp.py --help` works without the SDK because the SDK
import is lazy.

## Server Command

Supported options:

```bash
python tools/battle_estimator_mcp.py \
  --mode follow_latest \
  --game-dir "<GAME_FOLDER>" \
  --map-file "<MAP_FILE>" \
  --config-path "<CONFIG_JSON>" \
  --transport stdio
```

Use `--save-file "<SAVE_FILE>"` for pinned-save analysis. If `--save-file` is
set and `--mode` is omitted, the server uses pinned mode. Do not combine
`--mode follow_latest` with `--save-file`.

`stdio` is the only supported transport. Stdout is reserved for MCP protocol
messages; diagnostics and troubleshooting output must go to stderr.

## Tool Sequence

Use startup CLI options to choose the game/save/map/config paths. Tool calls do
not change those startup paths.

Recommended sequence:

1. Call `list_colors(refresh=true)` to discover active colors, teams, configured
   `My color`, alert radius, and hero buckets.
2. Call `get_advisor_context(color_id, scope="color", refresh=true)` for the
   main strategic context.
3. Use `scope="team"` only for alliance-level questions.
4. Call `get_alerts(color_id, refresh=false)` when town threats or ownership
   availability matter.
5. Use compute tools only for concrete hypotheses:
   `scan_nearby`, `estimate_battle`, `find_route`, and `explain_portal`.
6. Call `refresh_context()` after the save/map may have changed and before
   continuing from cached state.

Available tools:

- `refresh_context()`
- `list_colors(refresh=true)`
- `get_advisor_context(color_id, scope="color", refresh=true,
  include_raw_ids=true)`
- `scan_nearby(hero_id, radius=10, target_type="all", sort_mode="distance",
  simulations=500, refresh=true, include_removed=false,
  include_hidden_targets=false)`
- `estimate_battle(hero_id, target_id, simulations=500, refresh=true,
  include_hidden_targets=false)`
- `find_route(hero_id, target_id=null, target_position=null, refresh=true,
  include_hidden_targets=false)`
- `explain_portal(portal_id, refresh=true)`
- `get_alerts(color_id, refresh=true)`

`find_route` accepts exactly one target source: `target_id` or
`target_position` with `x`, `y`, and `z`.

## Answer Format

Advisor answers should be short, concrete, and cite tool facts:

- `Summary`
- `Key threats/opportunities`
- `Recommended next 1-2 turns`
- `Risks/limitations`
- `Checks/tool facts used`

Use exact IDs and facts when available: hero IDs, target IDs, town IDs, portal
IDs, positions, save/map names, ownership status, alert status, route fallback
status, and combat-context status.

## Limitation Language

Always state limitations that affect the recommendation. Do not present the MCP
advisor as exact Heroes III rules.

Common limitations:

- Fog of war and hidden enemy information are not modeled.
- Exact movement points, roads, terrain movement costs, boats, spells, and
  one-turn reachability are not fully modeled.
- Battle estimates still omit or simplify artifacts, active spells, morale,
  luck, tactics, terrain, specialties, and many creature special abilities.
- Save parsing is best-effort for observed `.GM1` and `.GM2` structures.
- If town ownership is unavailable or partial, report that status instead of
  guessing from initial map ownership.
- Portal and subterranean routes can be non-deterministic; surface that when a
  tool reports it.

## Privacy Rules

Do not commit:

- MCP client config files
- real saves or maps
- private absolute game paths
- API keys or tokens
- assistant transcripts
- screenshots or logs containing private save/map paths

Use placeholders such as `<GAME_FOLDER>`, `<SAVE_FILE>`, `<MAP_FILE>`, and
`<CONFIG_JSON>` in docs and shared notes.
