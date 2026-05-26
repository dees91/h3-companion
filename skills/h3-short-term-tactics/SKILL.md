---
name: h3-short-term-tactics
description: Choose immediate Heroes of Might and Magic III tactical actions from the H3 Companion MCP game state. Use before or after a move, on frequent autosaves, when the user asks what to do now, which hero to move, whether to attack or avoid a target, how to defend or take a castle this turn, whether to buy heroes, or how to execute an existing long-term H3 strategic goal.
---

# H3 Short Term Tactics

## Overview

Use this skill to produce the next concrete moves for the current H3 save. Keep the answer operational: who moves, what to attack or avoid, which towns need action, and what to check next.

## Data Workflow

1. Use H3 Companion MCP tools when available. If they are unavailable, say MCP is not connected and do not fabricate the current position.
2. Call `refresh_context` when the user asks about the current/latest save, when follow-latest may have advanced, or when no fresh snapshot is available.
3. Resolve the subject color. If the user does not name one, use configured color from `list_colors`; if none is configured and the color is ambiguous, ask one short question.
4. Call `get_advisor_context` with `scope="team"` by default, because tactical moves often defend allied towns or create chain opportunities.
5. Call `get_alerts` for the subject color and any allied color with nearby threats.
6. Identify the important heroes: subject main, allied main/support near threats, enemy heroes near towns, and enemy top combat threats.
7. Use `scan_nearby` for the subject main and relevant support heroes. Prefer radius `20-35` for immediate tactics; expand only when the current problem requires it.
8. Use `estimate_battle` for candidate attacks and dangerous enemy matchups. Avoid estimating every visible target.
9. Use `find_route` for each recommended movement objective so the action is tied to an actual route or a reported routing failure.

## Tactical Priorities

Resolve in this order:

1. Prevent immediate town loss or main-hero death.
2. Take favorable hero fights only when they are local/route-efficient and serve an objective: prevent town loss, protect a chain, unlock a town/front, or remove a credible counterattacker.
3. Take towns only when the main is not exposed to a losing counterattack.
4. Chain army and scouts before spending main-hero movement on low-value errands.
5. Use support heroes for scouting, garrisoning, ferrying troops, blocking paths, and town recapture; do not split the main army without a concrete reason.
6. Buy additional heroes when the side has too few utility heroes and gold allows it; prefer practical chain/scout value over making a second main.
- When no immediate town/main threat exists, prioritize safe castle capture, high-value farming, army chaining, and main-hero development over chasing beatable but low-impact enemy heroes.
- For any main-hero move that is not farming or castle capture, briefly state why it outranks those alternatives.

## Battle Decision Bands

- `>=90%`: treat as favorable, still note if the reward is low or the route is bad.
- `75-90%`: take only when strategically useful or when delay creates worse risk.
- `55-75%`: call it risky; prefer blocking, reinforcing, or waiting unless the position demands action.
- `<55%`: recommend avoiding the fight unless the user explicitly wants a desperation line.
- Do not decide from win percentage alone. Also weigh expected losses, route cost, reward, follow-up position, and enemy counterattack risk.
- Always mention that artifacts, active spells, morale/luck, tactics, terrain, exact movement, and fog of war may change the real game result.

## Answer Format

Answer in the user's language. For Polish users, use short, direct recommendations.

Use this structure unless the user asks for a narrower answer:

1. **Ruch teraz**: 3-7 ordered actions, each starting with a hero/town name.
2. **Walki**: attack/avoid list with estimated win percentages.
3. **Zamki**: defend, recruit, garrison, or capture instructions.
4. **Nowi bohaterowie**: buy/don't buy and why.
5. **Następny check**: what to re-evaluate after the move or next autosave.

When a long-term plan is already in the conversation, explicitly say how the proposed tactical actions serve it. If no long-term plan exists, include a one-sentence operational objective, not a full strategic essay.

## Grounding Rules

- Separate MCP facts from tactical inference.
- Include coordinates and target IDs only when they reduce ambiguity.
- Do not claim exact one-turn reachability unless the tool explicitly models it; route steps are strategic paths, not exact movement points.
- Prefer concise uncertainty over false precision.
