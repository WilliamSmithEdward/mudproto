# Equipment Effects

## Overview

Gear templates can grant passive stat bonuses through an inline `equipment_effects` field. Each entry specifies an `effect_type` and an `amount` applied while the item is equipped.

## Schema

```json
"equipment_effects": [
  { "effect_type": "con", "amount": 3 },
  { "effect_type": "hit_points", "amount": 40 }
]
```

Both weapons and armor support `equipment_effects`.

## Supported Effect Types

### Attribute bonuses

Any configured player attribute ID from `configuration/attributes/character_attributes.json` is valid:

- `str`
- `dex`
- `con`
- `wis`

These are not listed in `equipment_effects.json` — they are auto-derived from `character_attributes.json` at load time by `load_equipment_effects()` in `core_logic/attribute_config.py`.

### Non-attribute bonuses

Additional bonus types are defined in `configuration/attributes/equipment_effects.json`:

- `hit_points` — max HP cap
- `vigor` — max vigor cap
- `mana` — max mana cap
- `weapon_damage` — flat bonus to all melee damage rolls
- `hitroll` — flat bonus to all melee hit rolls

## How Effects Are Applied

| System | File |
|---|---|
| Effective attributes and bonus aggregation | `core_logic/equipment_logic.py` |
| Resource cap calculation (HP, vigor, mana) | `core_logic/player_resources.py` |
| Melee hitroll and weapon damage bonuses | `core_logic/combat.py` |
| Score and stats display | `core_logic/display_character.py` |

`get_player_equipment_bonuses()` iterates all unique equipped items (worn armor and wielded weapons) and sums their `equipment_effects` into a single bonus dict.

## Attribute Cap

Effective attributes from gear are capped at the server setting `max_effective_attribute` in `configuration/server/settings.json` (default: `28`).

## Validation

`_resolve_equipment_effects()` in `core_logic/assets.py` validates every gear template's effects at load time. Any `effect_type` not in the supported set raises a startup error.

## Distinction from Weapon-Intrinsic Fields

Weapon templates have their own per-swing fields (`hit_roll_modifier`, `damage_roll_modifier`, `attack_damage_bonus`) that apply only when that specific weapon strikes. These are consumed directly by `roll_player_damage()` and `get_player_hit_modifier()` in `core_logic/damage.py`.

`equipment_effects` bonuses are global — they apply to every attack and persist as long as the item is equipped regardless of which weapon swings.

## Authoring Guidance

- Use broad, reusable effect types (`dex`, `hitroll`, `hit_points`).
- Avoid inventing specialized or lore-only bonus names.
- Adding a new attribute to `character_attributes.json` automatically makes it available as an `equipment_effects` type — no changes to `equipment_effects.json` needed.
- To add a new non-attribute bonus type, add it to `equipment_effects.json` and wire up the runtime in `equipment_logic.py`.
