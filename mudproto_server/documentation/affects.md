# Affects

## Overview

Affect templates define reusable shared behaviors. Skills, spells, and item payloads reference them through `affect_ids`.

## Strategy

Prefer broad, reusable templates. Keep the shared template generic and place target, duration, scaling, and signed tuning on the applying ability via `affect_ids` override objects.

## Usage

In a skill or spell JSON, add an `affect_ids` array. Each entry may be either:

- a string shared affect id such as `"affect.regeneration"`
- an object containing `affect_id` plus override fields such as `name`, `target`, `target_resource`, `amount`, durations, and scaling values

Shared templates now use `descriptor` for the generic label text. The ability `name` remains the source label shown first in the score display.

Runtime behavior keys off the shared `affect_id` directly, while the score display combines the source name with the generic descriptor and, when relevant, polarity or resource context.

## Template Fields

| Field | Description |
|---|---|
| `descriptor` | Generic descriptor shown in the active effect label |
| `target` | `"self"` or `"target"` |
| `affect_mode` | `"instant"`, `"timed"`, or `"battle_rounds"` |
| `amount` | Base numeric amount; for dealt/received damage multipliers, values between $-1$ and $1$ are treated as signed deltas from $1.0$ |
| `can_be_negative` | Whether the affect template allows negative amount and scaling values |
| `dice_count` / `dice_sides` / `roll_modifier` | Random component |
| `scaling_attribute_id` / `scaling_multiplier` | Attribute-based scaling (players; supports decimal values) |
| `level_scaling_multiplier` | Per-level scaling (players; supports decimal values) |
| `amount_per_level_step` / `level_step` | Add or subtract the amount every N levels |
| `power_scaling_multiplier` | Per-power-level scaling (NPCs) |
| `duration_hours` / `duration_rounds` | Duration by mode |
| `duration_rounds_per_level_step` / `duration_level_step` | Add extra rounds every N levels |
| `damage_elements` | Array of elements to filter for `damage_received_multiplier` and `damage_dealt_multiplier`; empty = all |
| `target_resource` | `"hit_points"`, `"mana"`, or `"vigor"` (`regeneration` only) |
| `extra_main_hand_hits` / `extra_off_hand_hits` / `extra_unarmed_hits` | Base hit counts (`extra_hits` only) |
| `hits_per_level_step` / `level_step` | X extra hits per Y levels (`extra_hits` only; bonus applies only to hit types with base > 0) |

## Templates

### `affect.received-damage`

**Behavior:** modifies incoming damage on the target.

For multipliers, a value like `0.1` means $+10\%$, while `-0.1` means $-10\%$. This template has `can_be_negative: true`. Supports `damage_elements` to restrict which elements are affected; empty means all. Score labels render as `Increased Damage Received` or `Reduced Damage Received`.

**Example skill usage:**
```json
{
  "affect_id": "affect.received-damage",
  "name": "Pressure Point",
  "target": "target",
  "affect_mode": "battle_rounds",
  "damage_elements": ["physical"],
  "amount": 0.1,
  "scaling_attribute_id": "dex",
  "scaling_multiplier": 0.01,
  "duration_rounds": 3
}
```

### `affect.dealt-damage`

**Behavior:** modifies outgoing damage from the affected target.

A value like `-0.2` means $-20\%$ damage dealt, while `0.2` means $+20\%$. This template has `can_be_negative: true`. Supports `damage_elements` to restrict outgoing damage types. Score labels render as `Increased Damage Dealt` or `Reduced Damage Dealt`.

**Example spell usage:**
```json
{
  "affect_id": "affect.dealt-damage",
  "name": "Icebound",
  "target": "target",
  "affect_mode": "battle_rounds",
  "damage_elements": ["physical"],
  "amount": -0.2,
  "duration_rounds": 3,
  "duration_rounds_per_level_step": 1,
  "duration_level_step": 10
}
```

### `affect.regeneration`

**Behavior:** restores the chosen resource each tick.

Supports `hit_points` (default), `mana`, or `vigor`. The target resource is supplied by the applying ability, not the shared template. Score labels render resource-specific text such as `Health Regeneration`, `Mana Regeneration`, or `Vigor Regeneration`.

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

**Behavior:** grants extra attacks per round.

Specify base counts per hand type. Level scaling adds bonus hits to types with base > 0.

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

**Defensive example:**
```json
{
  "affect_id": "affect.received-damage",
  "name": "Centered Guard",
  "target": "self",
  "affect_mode": "battle_rounds",
  "amount": -0.12,
  "amount_per_level_step": -0.02,
  "level_step": 10,
  "scaling_attribute_id": "con",
  "scaling_multiplier": -0.005,
  "level_scaling_multiplier": -0.005,
  "duration_rounds": 3
}
```
