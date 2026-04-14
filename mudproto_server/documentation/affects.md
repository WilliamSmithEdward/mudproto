# Affects

## Overview

Affect templates define reusable affect types. Skills and spells reference them via `affect_ids`.

## Strategy

Prefer broad, reusable templates. Parameterize behavior at the skill/spell level via `affect_ids` overrides rather than creating narrow one-off templates.

## Usage

In a skill or spell JSON, add an `affect_ids` array. Each entry must include an `affect_id` matching a template in `configuration/attributes/affects.json`, plus any override fields.

## Override Fields

| Field | Description |
|---|---|
| `name` | Display name for the active affect |
| `target` | `"self"` or `"target"` |
| `affect_mode` | `"instant"`, `"timed"`, or `"battle_rounds"` |
| `amount` | Base numeric amount (multiplier for `damage_received_multiplier`, flat for others) |
| `dice_count` / `dice_sides` / `roll_modifier` | Random component |
| `scaling_attribute_id` / `scaling_multiplier` | Attribute-based scaling (players) |
| `level_scaling_multiplier` | Per-level scaling (players) |
| `power_scaling_multiplier` | Per-power-level scaling (NPCs) |
| `duration_hours` / `duration_rounds` | Duration by mode |
| `damage_elements` | Array of elements to filter (`damage_received_multiplier` only; empty = all) |
| `target_resource` | `"hit_points"`, `"mana"`, or `"vigor"` (`regeneration` only) |
| `extra_main_hand_hits` / `extra_off_hand_hits` / `extra_unarmed_hits` | Base hit counts (`extra_hits` only) |
| `hits_per_level_step` / `level_step` | X extra hits per Y levels (`extra_hits` only; bonus applies only to hit types with base > 0) |

## Templates

### `affect.increase-received-damage`

**Type:** `damage_received_multiplier`

Multiplies incoming damage on the target. Amount is a multiplier (e.g. 1.1 = +10% damage taken). Supports `damage_elements` to restrict which elements are affected; empty means all.

**Example skill usage:**
```json
{
  "affect_id": "affect.increase-received-damage",
  "name": "Pressure Point",
  "target": "target",
  "affect_mode": "battle_rounds",
  "damage_elements": ["physical"],
  "amount": 1.1,
  "scaling_attribute_id": "dex",
  "scaling_multiplier": 0.01,
  "duration_rounds": 3
}
```

### `affect.regeneration`

**Type:** `regeneration`

Restores `target_resource` each tick. Supports `hit_points` (default), `mana`, or `vigor`.

**Example spell usage:**
```json
{
  "affect_id": "affect.regeneration",
  "name": "Regeneration Ward",
  "target": "self",
  "affect_mode": "battle_rounds",
  "target_resource": "hit_points",
  "amount": 0,
  "dice_count": 1,
  "dice_sides": 21,
  "roll_modifier": 39,
  "scaling_attribute_id": "wis",
  "scaling_multiplier": 1.0,
  "duration_rounds": 3
}
```

### `affect.extra-hits`

**Type:** `extra_hits`

Grants extra attacks per round. Specify base counts per hand type. Level scaling adds bonus hits to types with base > 0.

**Example skill usage:**
```json
{
  "affect_id": "affect.extra-hits",
  "name": "Fist Flurry",
  "target": "self",
  "affect_mode": "battle_rounds",
  "extra_main_hand_hits": 0,
  "extra_off_hand_hits": 0,
  "extra_unarmed_hits": 2,
  "hits_per_level_step": 1,
  "level_step": 5,
  "duration_rounds": 4
}
```

### `affect.damage-reduction`

**Type:** `damage_reduction`

Flat damage subtracted from each incoming hit. Strongest active reduction wins.

**Example skill usage:**
```json
{
  "affect_id": "affect.damage-reduction",
  "name": "Centered Guard",
  "target": "self",
  "affect_mode": "battle_rounds",
  "amount": 2,
  "scaling_attribute_id": "con",
  "scaling_multiplier": 0.5,
  "level_scaling_multiplier": 0.5,
  "duration_rounds": 3
}
```
