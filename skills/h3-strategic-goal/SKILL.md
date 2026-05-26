---
name: h3-strategic-goal
description: Create and revise long-term Heroes of Might and Magic III strategic plans from the H3 Companion MCP game state. Use when the user asks for strategic direction over multiple turns/days, castle priorities, main-hero development, team/front positioning, which faction/color should pursue what plan, or when a major save-state change requires refreshing the overall plan.
---

# H3 Strategic Goal

## Overview

Use this skill to turn the current H3 Companion MCP snapshot into an actionable strategic plan. Prefer fewer, stronger claims tied to MCP facts over exhaustive commentary.

## Data Workflow

1. Use H3 Companion MCP tools when available. If they are unavailable, say that MCP is not connected and do not invent game state.
2. Refresh or load current state with `refresh_context` when the user asks about the current/latest game or when no fresh snapshot is already available.
3. Resolve the subject color from the user request. If omitted, prefer configured player color from `list_colors`; if none is configured and the subject is ambiguous, ask one short question.
4. Call `list_colors` to identify active colors, teams, hero counts, and main towns.
5. Call `get_advisor_context` for the subject color with `scope="team"` when teams matter; use `scope="color"` when the user explicitly asks about one color only.
6. Call `get_alerts` for the subject color and allied colors that have towns or exposed heroes.
7. Run focused `estimate_battle` checks only for strategic matchups: main hero versus top enemy heroes, enemy heroes near towns, or proposed attack targets. Use enough simulations for direction, not exhaustive proof.
8. Run `find_route` for proposed strategic objectives such as priority towns, dangerous enemy heroes, gates, or front anchors.

## Strategic Heuristics

- Treat towns as economy, recruitment, and map-control anchors; do not recommend taking a town if it exposes the main hero to a clearly losing fight.
- Prioritize main-hero tempo over static defense, unless a key town can be lost immediately and no ally can cover it.
- Evaluate the team, not only the selected color. If an ally cannot beat a nearby enemy threat and the subject main can, protecting the ally may be the correct strategic move.
- Prefer removing only enemy heroes that can immediately recapture, trap, or kill the main before taking an exposed town; do not chase distant/support heroes just because the fight is favorable.
- Before recommending an enemy-hero chase, state the payoff: saving or opening a town, protecting a chain, removing a credible counterattacker, or unlocking a route/front. If the payoff is only a safe win, prefer high-value farming, safe town capture, army chaining, or main-hero development.
- Safe town captures and high-value farming are proactive tempo when they improve economy, army, stats, spell access, or map control without exposing the main to a stronger counterattack.
- Recommend buying extra heroes when the side has too few scouts/chains/garrisons, usually aiming for several utility heroes once gold allows it. Do not recommend building a second main unless there is clear army, stat, and map support.
- For battle estimates, classify roughly: `>=90%` favorable, `75-90%` acceptable if strategically needed, `55-75%` risky, `<55%` avoid unless there is no alternative. Mention when model limits could change the judgment.
- Do not decide strategic fights from win percentage alone. Also weigh expected losses, route cost, reward, follow-up position, and enemy counterattack risk.
- For hero development, use parsed skills/stats when available. If skill state is incomplete, say so and frame recommendations as conditional.

## Answer Format

Answer in the user's language. For Polish users, be direct and practical.

Use this structure unless the user asks for something narrower:

1. **Teza strategiczna**: one clear strategic direction.
2. **Priorytety**: 3-5 ordered priorities.
3. **Zamki**: what to defend, what to take, and what not to overextend for.
4. **Bohaterowie**: main hero role, support hero roles, recruitment guidance.
5. **Rozwój maina**: skill/stat/army direction if data supports it.
6. **Ryzyka**: explicit avoid list and MCP limitations.
7. **Kiedy odświeżyć plan**: concrete triggers such as lost/taken town, enemy main movement, decisive battle, new gate/portal access.

## Grounding Rules

- Separate MCP facts from strategic inference.
- Include coordinates for key towns, heroes, gates, and targets when they matter.
- Do not claim exact movement points, fog-of-war knowledge, artifacts, spellbooks, morale/luck, tactics phase, or perfect battle modeling unless the tool data explicitly supports it.
- If MCP data conflicts with H3 intuition, surface the conflict and give the conservative recommendation.
