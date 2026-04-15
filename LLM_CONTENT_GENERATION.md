# LLM Content Generation for MudProto

This document describes the workflow for using an AI model to generate MudProto content as a **single downloadable `.json` payload file**.

---

## Overview

MudProto supports content bundles dropped into:

- `mudproto_server/configuration/assets/asset_payloads/`

These payloads are loaded alongside the base asset files and can:
- add new gear, items, spells, skills, NPCs, rooms, and zones
- override existing base-game assets by reusing their IDs
- extend rooms across multiple payloads with merged exits

---

## Required workflow

### 1. Start from the generator script
Use:

- `mudproto_llm_interfaces/generate_asset_payload_generation_instructions.py`

That script regenerates:

- `mudproto_llm_interfaces/asset_payload_generation_instructions.json`

The generated instruction file is what you hand to the AI model. It contains:
- the response contract
- discovery questions the LLM should ask before content creation
- ID / override rules
- conflict resolution behavior
- schema references from the template files
- a serialized snapshot of the current asset set
- the current authoring constraints, including anti-duplication guidance for abilities and consumables

### 2. Make sure the AI returns a downloadable `.json` file
This is important.

> The model should provide the result as a **downloadable `.json` file**, not as prose and not wrapped in Markdown code fences.

If the model only pastes JSON in chat, save it manually as a `.json` file before using it.

### 3. Place the file here
Drop the generated file into:

- `mudproto_server/configuration/assets/asset_payloads/`

Example:

- `mudproto_server/configuration/assets/asset_payloads/dark-knight-outpost.json`

### 4. Restart the server
Asset payloads are cached by the loader, so restart the server after adding or changing a payload.

---

## Discovery step the LLM should follow

Before generating new content, the model should ask for any missing design context, such as:

- where the new content should attach in the world
- what the zone theme or fantasy concept should be
- what kinds of content it should include
- target difficulty
- any special mechanics, hazards, or gimmicks
- approximate room count / zone size
- whether it should add new items, gear, spells, skills, merchants, or NPCs

If those details are already provided, the model can proceed directly.

---

## Asset schema references

The authoritative schema reference files live in:

- `mudproto_server/configuration/assets/templates/`
- `mudproto_server/configuration/attributes/templates/`

These template files describe the expected JSON structure for the game's config files and should be kept in sync with schema changes.

For broader authoring guidance, also see:

- `ASSET_GENERATION.md`

---

## ID rules and collision handling

### New content
For **new assets**, use a GUID suffix on IDs to avoid collisions.

Examples:
- `npc.darkwatch-captain-550e8400-e29b-41d4-a716-446655440000`
- `room.blackwatch-descent-550e8400-e29b-41d4-a716-446655440000`

### Intentional overrides
If the goal is to **replace or modify existing base-game content**, reuse the original asset ID exactly.

In that case, the payload definition is treated as the replacement.

---

## Merge and override behavior

### Most asset types: last loaded wins
For these asset types, if multiple payloads define the same ID, the **last loaded definition wins**:

- gear
- items
- spells
- skills
- NPCs
- zones

### Rooms: exits merge, other fields use the last loaded room
Rooms have one special rule.

If multiple payloads target the same `room_id`:
- `exits` are **merged together**
- all other room fields come from the **last loaded room definition**

This makes it possible for multiple payloads to attach new paths to the same room without losing earlier exits.

---

## Caveats

- **Restart required:** payload edits are not reliably hot-reloaded.
- **Cross-references must be valid:** rooms, NPCs, items, spells, skills, and zones must all point to real IDs.
- **Output must be raw JSON:** no comments, no trailing commas, no Markdown fences.
- **Use lowercase IDs and keywords:** this matches existing conventions and selector behavior.
- **Override carefully:** reusing a base ID replaces behavior/data for that asset type.
- **New spells and skills are welcome when warranted:** the LLM may create fully new spells and skills as long as they feel flavorful, distinct, and well-matched to the theme, lore, and tone of the zone and the broader game.
- **Avoid redundant reskins:** do not create new consumable items, spells, or skills that are functionally just renamed copies of existing mechanics unless a distinct variant or direct override is explicitly desired.
- **Use the affect artifact correctly:** support and lingering status behavior should reference the centralized affect templates in `mudproto_server/configuration/attributes/affects.json` via `affect_ids`; do not invent inline affect payloads.
- **Mark true proper-name NPCs explicitly:** if an NPC is a unique named character (for example a boss, officer, priestess, or story NPC with a personal name/title), set `is_named: true`; leave the field omitted for ordinary generic enemies.
- **Write ability narration in a target-safe format:** use placeholders such as `[a/an] [verb] thrown off balance by the strike!` so the same line reads correctly for both players and NPC victims. Avoid actor-POV lines like `You drive a knife into your foe!`.
- **Room merges are special-case only for exits:** everything else on the room comes from the last loaded room payload.

---

## Recommended prompt pattern

When asking an LLM to generate content, provide:

1. the instruction file
2. the relevant schema template files
3. your desired content brief
4. the attachment point in the existing world
5. a reminder that the result must be a **downloadable `.json` file**

A good final instruction is:

> Return a single downloadable `.json` file suitable for placement in `mudproto_server/configuration/assets/asset_payloads/`.

---

## Typical human review checklist

Before keeping a generated payload:

- confirm the file is valid JSON
- confirm the IDs follow the intended new-vs-override rule
- confirm room exits point to real rooms
- confirm NPCs only reference valid spells, skills, and item/gear IDs
- confirm uniquely named NPCs have `is_named: true` when appropriate
- confirm ability `damage_context` / `support_context` lines use placeholder-safe, target-state wording
- confirm balance is reasonable for the target difficulty
- restart the server and smoke test in-game

---

## Related files

- `mudproto_llm_interfaces/asset_payload_generation_instructions.json`
- `mudproto_server/configuration/assets/asset_payloads/`
- `mudproto_server/configuration/assets/templates/`
- `mudproto_server/configuration/attributes/templates/`
- `ASSET_GENERATION.md`

