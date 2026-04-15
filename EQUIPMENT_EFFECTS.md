# Equipment Effects

This document explains the direct equipment bonus system used by MudProto gear.

---

## Overview

Gear can now grant runtime stat bonuses through a simple inline field on each gear template:

- [mudproto_server/configuration/assets/gear.json](mudproto_server/configuration/assets/gear.json)

The field is:

- `equipment_effects`

Each entry is a small object with:

- `effect_type`
- `amount`

Example:

```json
"equipment_effects": [
  { "effect_type": "con", "amount": 1 },
  { "effect_type": "hit_points", "amount": 25 },
  { "effect_type": "hitroll", "amount": 3 }
]
```

---

## Supported effect types

### 1. Broad attribute bonuses
Any configured player attribute ID may be used directly as an effect type.

Examples:

- `str`
- `dex`
- `con`
- `wis`

So this:

```json
{ "effect_type": "con", "amount": 1 }
```

means:

- `+1 CON`

### 2. Non-attribute gear bonus types
The server also supports broad non-attribute types listed in:

- [mudproto_server/configuration/attributes/equipment_effects.json](mudproto_server/configuration/attributes/equipment_effects.json)

Current defaults include:

- `hit_points`
- `vigor`
- `mana`
- `weapon_damage`
- `hitroll`

---

## Behavior

Equipment bonuses are applied to live gameplay systems, including:

- effective player attributes
- HP / vigor / mana caps
- melee hitroll
- melee weapon damage
- displayed score / stats output

The runtime integration lives primarily in:

- [mudproto_server/core_logic/equipment_logic.py](mudproto_server/core_logic/equipment_logic.py)
- [mudproto_server/core_logic/player_resources.py](mudproto_server/core_logic/player_resources.py)
- [mudproto_server/core_logic/combat.py](mudproto_server/core_logic/combat.py)

---

## Attribute cap

Effective attributes from gear are capped by the server gameplay setting:

- [mudproto_server/configuration/server/settings.json](mudproto_server/configuration/server/settings.json)

Current default:

- `28`

---

## Authoring guidance

Use broad, reusable effect types whenever possible.

Preferred:

- `dex`
- `con`
- `hitroll`
- `weapon_damage`
- `hit_points`

Avoid over-specialized or flavor-only effect names.

The goal is:

- simple schema
- direct runtime meaning
- easy LLM generation
- minimal duplication

---

## Example gear snippet

```json
{
  "template_id": "armor.twinway-signet",
  "name": "Twinway Signet",
  "slot": "armor",
  "wear_slots": ["ring"],
  "description": "A roadwarden signet cut with two crossing trails.",
  "equipment_effects": [
    { "effect_type": "dex", "amount": 3 },
    { "effect_type": "con", "amount": 3 }
  ]
}
```
