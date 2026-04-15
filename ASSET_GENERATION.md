# MudProto Asset Generation Guide

> Scope: this document covers how to add or modify content in `mudproto_server/configuration/assets/`.
>
> Note: the real folder name is `assets` â€” not `asssets`.

---

## 1. What this folder contains

`mudproto_server/configuration/assets/` is the content layer for the game world. These files define **what exists in the world**, while rules like wear slots, regeneration, level scaling, and potion cooldowns live in `mudproto_server/configuration/attributes/`.

### Asset files

| File | Purpose |
|---|---|
| `gear.json` | Weapons and armor templates |
| `items.json` | Consumables and misc usable items |
| `npcs.json` | NPC definitions, merchants, spell/skill loadouts |
| `rooms.json` | Rooms, descriptions, exits, and NPC spawn points |
| `zones.json` | Zone metadata and repop timing |
| `spells.json` | Spell definitions |
| `skills.json` | Skill definitions |

The **authoritative schema and validation rules** for all of these files live in `mudproto_server/assets.py`.

---

## 2. Non-negotiable rules

When editing or generating assets, follow these rules exactly:

1. **All files must be valid JSON**
   - Use double quotes.
   - No trailing commas.
   - Top-level structure must match the fileâ€™s expected shape.

2. **IDs must be unique within their asset type**
   - Duplicate IDs will raise a `ValueError` and stop load/startup.

3. **Cross-references must already exist**
   - If a room references an NPC, that NPC must exist.
   - If an NPC references a spell, skill, or gear template, those must exist.

4. **Prefer lowercase IDs and lowercase keywords**
   - This matches current project conventions and selector logic.

5. **Restart the server after edits**
   - Asset loaders in `assets.py` use `@lru_cache(maxsize=1)`, so JSON changes are not reliably hot-reloaded in a running process.

6. **Follow current naming conventions**
   - `weapon.*`, `armor.*`, `item.*`, `npc.*`, `spell.*`, `skill.*`, `zone.*`
   - `room_id` values are usually short slugs like `start`, `hall`, `east-watch`, `south-market`

---

## 3. Recommended authoring workflow

### Safe order of operations

When adding new content, use this order:

1. Add any required **gear**, **items**, **spells**, or **skills** first.
2. Add or update the **NPC** that references them.
3. Add or update the **room** that spawns that NPC.
4. Add or update the **zone** if the room belongs to a new zone.
5. Restart the server and smoke test in-game.

### Smoke-test checklist

After editing assets:

- restart with:
  ```powershell
  python mudproto_server/server.py
  ```
- connect a client and test relevant commands:
  - `look`
  - `scan`
  - `look <npc>`
  - `inventory`, `equipment`
  - `buy <item>` / `sell <item>` if merchant content changed
  - `cast <spell>` or use a skill if combat abilities changed

---

## 4. Cross-reference map

These references must stay valid:

| Source field | Must exist in | Notes |
|---|---|---|
| `rooms[].zone_id` | `zones.json -> zone_id` | Required for every room |
| `rooms[].npcs[].npc_id` | `npcs.json -> npc_id` | Spawn entries must reference valid NPCs |
| `npcs[].main_hand_weapon.template_id` | `gear.json -> template_id` | Usually `weapon.*` |
| `npcs[].off_hand_weapon.template_id` | `gear.json -> template_id` | Usually `weapon.*` |
| `npcs[].merchant_inventory[].template_id` | `gear.json` or `items.json` | Merchant stock can sell gear or consumables |
| `npcs[].skill_ids[]` | `skills.json -> skill_id` | Unknown IDs fail validation |
| `npcs[].spell_ids[]` | `spells.json -> spell_id` | Unknown IDs fail validation |
| `spells[].damage_scaling_attribute_id` | `configuration/attributes/character_attributes.json` | Current ids: `str`, `dex`, `con`, `int`, `wis` |
| `skills[].scaling_attribute_id` | `configuration/attributes/character_attributes.json` | Same attribute set |
| `rooms[].exits[direction]` | another `room_id` in `rooms.json` | Validated at world build time |

---

## 5. File-by-file reference

## `gear.json`

### Top-level shape
A **list** of objects.

```json
[
  { "template_id": "weapon.training-sword", "name": "Training Sword", "slot": "weapon" }
]
```

### Required/common fields

#### Shared
- `template_id` â€” required, unique string
- `name` â€” required, non-empty string
- `slot` â€” required, must be `"weapon"` or `"armor"`
- `description` â€” recommended
- `keywords` â€” recommended list of lowercase tokens
- `weight` â€” non-negative integer
- `coin_value` â€” non-negative integer

#### Weapon-only fields
- `weapon_type` â€” e.g. `sword`, `dagger`
- `can_hold` â€” `true` if the item should be holdable/off-hand usable for players
- `damage_dice_count`
- `damage_dice_sides`
- `damage_roll_modifier`
- `hit_roll_modifier`
- `attack_damage_bonus`
- `attacks_per_round_bonus`

#### Armor-only fields
- `wear_slots` â€” **required for armor**, non-empty list
- `armor_class_bonus` â€” must be `>= 0`

### Important validation rules
- Weapons **cannot** define `wear_slots`.
- Armor **must** define `wear_slots`.
- `armor_class_bonus` must be zero or greater.

### Example weapon
```json
{
  "template_id": "weapon.reaver-nightblade",
  "name": "Reaver Nightblade",
  "slot": "weapon",
  "description": "A blackened longsword etched with pale runes that drink the brazier light.",
  "keywords": ["reaver", "nightblade", "sword"],
  "weapon_type": "sword",
  "can_hold": false,
  "weight": 7,
  "coin_value": 58,
  "damage_dice_count": 4,
  "damage_dice_sides": 6,
  "damage_roll_modifier": 2,
  "hit_roll_modifier": 2,
  "attack_damage_bonus": 1,
  "attacks_per_round_bonus": 0
}
```

### Example armor
```json
{
  "template_id": "armor.vanguard-jacket",
  "name": "Vanguard Jacket",
  "slot": "armor",
  "wear_slots": ["chest"],
  "description": "A reinforced jacket worn by front-line trainees.",
  "keywords": ["vanguard", "jacket", "chest"],
  "weight": 10,
  "coin_value": 30,
  "armor_class_bonus": 2
}
```

---

## `items.json`

### Top-level shape
A **list** of objects.

### Current engine expectation
Items in this file are currently **restore consumables**.

### Required/common fields
- `template_id`
- `name`
- `description`
- `keywords`
- `effect_type` â€” currently must be `"restore"`
- `effect_target` â€” must be one of:
  - `hit_points`
  - `mana`
  - `vigor`
- `effect_amount` â€” integer, must be `> 0`
- `coin_value` â€” non-negative integer
- `use_lag_seconds` â€” non-negative float
- `observer_action` â€” optional but recommended
- `observer_context` â€” optional but recommended

### Example
```json
{
  "template_id": "item.potion.vigor",
  "name": "Potion of Vigor",
  "description": "A lively golden tonic that steadies the breath and restores battle stamina.",
  "keywords": ["potion", "vigor", "stamina"],
  "effect_type": "restore",
  "effect_target": "vigor",
  "effect_amount": 40,
  "coin_value": 15,
  "use_lag_seconds": 0,
  "observer_action": "[actor_name] drinks a potion of vigor.",
  "observer_context": "Renewed energy surges through [actor_object]."
}
```

### Important note
Potion cooldown behavior is **not** configured here. That lives in:

- `mudproto_server/configuration/attributes/item_usage.json`

---

## `npcs.json`

### Top-level shape
Unlike most asset files, this file is an **object** with an `npcs` array:

```json
{
  "npcs": [
    { "npc_id": "npc.hall-scout", "name": "Hall Scout" }
  ]
}
```

### Common fields
- `npc_id` â€” required, unique string
- `name` â€” required
- `hit_points`, `max_hit_points` â€” must be `> 0`
- `power_level` â€” non-negative integer
- `attacks_per_round`
- `hit_roll_modifier`
- `armor_class`
- `off_hand_attacks_per_round`
- `off_hand_hit_roll_modifier`
- `coin_reward`
- `experience_reward`
- `is_aggro`
- `is_ally`
- `is_peaceful`
- `respawn`
- `pronoun_possessive` â€” e.g. `his`, `her`, `its`
- `main_hand_weapon` â€” object with `template_id`, `spawn_chance`, `drop_on_death`
- `off_hand_weapon` â€” object with `template_id`, `spawn_chance`, `drop_on_death`
- `inventory_items` â€” template-backed carried items; each entry may include `spawn_chance`
- `vigor`, `max_vigor`
- `mana`, `max_mana`
- `skill_use_chance` â€” float from `0.0` to `1.0`
- `skill_ids` â€” valid `skill_id`s
- `spell_use_chance` â€” float from `0.0` to `1.0`
- `spell_ids` â€” valid `spell_id`s

### Merchant-only fields
- `is_merchant: true`
- `merchant_inventory` â€” list of stock objects:
  - `template_id`
  - `infinite` â€” boolean
  - `quantity` â€” required for limited stock (`>= 1` when `infinite: false`)
- `merchant_buy_markup` â€” must be `> 0`
- `merchant_sell_ratio` â€” must be between `0.0` and `1.0`

### Respawn / world behavior notes
- `respawn: true` means the NPC is eligible for zone-driven repopulation.
- `is_peaceful: true` means offensive effects should not land on the NPC.
- `is_aggro: true` means the NPC auto-engages players when appropriate.

### Example hostile NPC
```json
{
  "npc_id": "npc.east-watch-reaver",
  "name": "East Watch Reaver",
  "hit_points": 280,
  "max_hit_points": 280,
  "power_level": 5,
  "respawn": true,
  "attacks_per_round": 1,
  "hit_roll_modifier": 2,
  "armor_class": 11,
  "coin_reward": 42,
  "experience_reward": 55,
  "is_aggro": true,
  "is_ally": false,
  "pronoun_possessive": "his",
  "main_hand_weapon": {
    "template_id": "weapon.reaver-nightblade",
    "spawn_chance": 100,
    "drop_on_death": 0
  },
  "off_hand_weapon": {
    "template_id": "weapon.scout-dagger",
    "spawn_chance": 100,
    "drop_on_death": 0
  },
  "vigor": 72,
  "max_vigor": 72,
  "skill_use_chance": 0.45,
  "skill_ids": ["skill.jab", "skill.overhead-crack", "skill.guard-breath"]
}
```

### Example merchant stock entry
```json
{
  "template_id": "item.potion.mana",
  "quantity": 3,
  "infinite": false
}
```

---

## `rooms.json`

### Top-level shape
A **list** of rooms.

### Required fields
- `room_id`
- `title`
- `description`
- `zone_id`
- `exits` â€” object mapping direction to destination `room_id`

### Optional field
- `npcs` â€” list of spawn objects:
  - `npc_id`
  - `count` â€” integer, must be `>= 1`

### Example
```json
{
  "room_id": "hall",
  "title": "Northern Hall",
  "description": "A narrow hall of cold stone extends here, quiet and still.",
  "zone_id": "zone.northern-wing",
  "npcs": [
    { "npc_id": "npc.hall-scout", "count": 2 }
  ],
  "exits": {
    "south": "start",
    "east": "east-watch"
  }
}
```

### Notes
- Exit destinations are validated at world build time in `world.py`.
- Room-to-zone membership comes from each roomâ€™s `zone_id`.
- Do **not** try to assign room membership inside `zones.json`; that is derived at runtime.

---

## `zones.json`

### Top-level shape
A **list** of zone objects.

### Fields
- `zone_id` â€” required, unique
- `name` â€” required
- `repopulate_game_hours` â€” integer, must be `>= 0`

### Example
```json
{
  "zone_id": "zone.whispering-sanctum",
  "name": "Whispering Sanctum",
  "repopulate_game_hours": 1
}
```

### Behavior notes
- `repopulate_game_hours: 0` disables automatic periodic repop.
- Zones are occupancy-aware: if players are in the zone, repop waits until a valid empty tick.
- `room_ids` are built at runtime in `world.py`; they are **not authored in this file**.

---

## `spells.json`

### Top-level shape
A **list** of spells.

### Required common fields
- `spell_id` â€” required, unique
- `name` â€” required, unique among spell names
- `school` â€” required, non-empty
- `description` â€” recommended
- `mana_cost` â€” integer, `>= 0`
- `spell_type` â€” `"damage"` or `"support"`
- `cast_type` â€” `"self"`, `"target"`, or `"aoe"`

If `cast_type` is omitted:
- support spells default to `self`
- damage spells default to `target`

### Damage spell fields
- `damage_dice_count`
- `damage_dice_sides`
- `damage_modifier`
- `damage_scaling_attribute_id` â€” must be a valid attribute id, usually `int`
- `damage_scaling_multiplier` â€” `>= 0`
- `level_scaling_multiplier` â€” `>= 0`
- `damage_context` â€” **required for damage spells**

Optional life-steal style fields on damage spells:
- `restore_effect` â€” `heal`, `vigor`, or `mana`
- `restore_ratio` â€” `0.0` to `1.0`
- `restore_context`
- `observer_restore_context`

### Support spell fields
- `support_effect` — `heal`, `vigor`, `mana`, or `""` (empty for affect-only support spells)
- `support_amount`
- `support_dice_count`
- `support_dice_sides`
- `support_roll_modifier`
- `support_scaling_attribute_id`
- `support_scaling_multiplier`
- `support_mode` — `instant`, `timed`, or `battle_rounds`
- `duration_hours` — required when `support_mode` is `timed`
- `duration_rounds` — required when `support_mode` is `battle_rounds`
- `support_context` — **required for support spells**
- `affect_ids` — optional array of affect overrides (see [Affects](#affects) below)

Optional presentation fields:
- `observer_action`
- `observer_context`

### Example damage spell
```json
{
  "spell_id": "spell.spark",
  "name": "Spark",
  "school": "Storm",
  "description": "A focused bolt of crackling force.",
  "spell_type": "damage",
  "element": "storm",
  "cast_type": "target",
  "mana_cost": 12,
  "damage_dice_count": 10,
  "damage_dice_sides": 40,
  "damage_modifier": 4,
  "damage_scaling_attribute_id": "int",
  "damage_scaling_multiplier": 1.0,
  "level_scaling_multiplier": 1.0,
  "damage_context": "[a/an] is jolted by crackling force."
}
```

### Example support spell (with affect_ids)
```json
{
  "spell_id": "spell.regeneration-ward",
  "name": "Regeneration Ward",
  "school": "Restoration",
  "description": "A steady restorative ward that heals you each battle round, even outside combat.",
  "spell_type": "support",
  "element": "restoration",
  "cast_type": "self",
  "mana_cost": 18,
  "support_effect": "heal",
  "support_amount": 1,
  "support_mode": "instant",
  "support_context": "A pale ward settles around you, knitting your wounds with each heartbeat of battle.",
  "observer_action": "[actor_name] focuses deeply, weaving a regeneration ward.",
  "observer_context": "A pale ward settles around [actor_object], knitting wounds with each heartbeat of battle.",
  "affect_ids": [
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
  ]
}
```

---

## `skills.json`

### Top-level shape
A **list** of skills.

### Required/common fields
- `skill_id` â€” required, unique
- `name` â€” required, unique among skill names
- `description`
- `skill_type` â€” `"damage"` or `"support"`
- `cast_type` â€” `"self"`, `"target"`, or `"aoe"`
- `vigor_cost` â€” integer, `>= 0`
- `usable_out_of_combat` â€” boolean
- `lag_rounds` â€” integer, `>= 0`
- `cooldown_rounds` â€” integer, `>= 0`
- `scaling_attribute_id` â€” if set, must be a valid attribute id
- `scaling_multiplier` â€” `>= 0`
- `level_scaling_multiplier` â€” `>= 0`

### Damage skill fields
- `damage_dice_count`
- `damage_dice_sides`
- `damage_modifier`
- `damage_context` â€” **required for damage skills**

Optional on damage skills:
- `restore_effect`
- `restore_ratio`
- `restore_context`
- `observer_restore_context`

### Support skill fields
- `support_effect` — `heal`, `vigor`, `mana`, `damage_reduction`, or `""` (empty for affect-only support skills)
- `support_amount`
- `support_context` — **required for support skills**
- `observer_action`
- `observer_context`
- `affect_ids` — optional array of affect overrides (see [Affects](#affects) below)

### Example damage skill
```json
{
  "skill_id": "skill.jab",
  "name": "Jab",
  "description": "A quick probing strike.",
  "skill_type": "damage",
  "element": "physical",
  "cast_type": "target",
  "vigor_cost": 4,
  "usable_out_of_combat": false,
  "scaling_attribute_id": "dex",
  "scaling_multiplier": 2.5,
  "level_scaling_multiplier": 1.0,
  "damage_dice_count": 1,
  "damage_dice_sides": 8,
  "damage_modifier": 2,
  "damage_context": "[a/an] [verb] snapped backward by a sharp jab.",
  "observer_action": "[actor_name] snaps out a quick jab.",
  "lag_rounds": 1,
  "cooldown_rounds": 1
}
```

### Example affect-only support skill
```json
{
  "skill_id": "skill.centered-guard",
  "name": "Centered Guard",
  "description": "A rooted defensive form that lets you bleed force away before it lands.",
  "skill_type": "support",
  "element": "physical",
  "cast_type": "self",
  "vigor_cost": 8,
  "usable_out_of_combat": false,
  "scaling_attribute_id": "con",
  "scaling_multiplier": 0.5,
  "level_scaling_multiplier": 0.5,
  "support_effect": "",
  "support_amount": 0,
  "affect_ids": [
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
  ],
  "support_mode": "battle_rounds",
  "duration_rounds": 3,
  "support_context": "You settle into a centered guard, turning the worst of each blow aside.",
  "observer_action": "[actor_name] plants [actor_possessive] feet and draws a steady breath.",
  "observer_context": "[actor_name] settles into a centered guard that blunts incoming strikes.",
  "lag_rounds": 1,
  "cooldown_rounds": 4
}
```

---

## 6. Affects

Skills and spells can reference affect templates defined in `configuration/attributes/affects.json` via the `affect_ids` array. Each entry overrides template defaults with skill/spell-specific values.

### Available affect templates

| Template ID | Type | Purpose |
|---|---|---|
| `affect.increase-received-damage` | `damage_received_multiplier` | Multiplies incoming damage on the target. `amount` is a multiplier (e.g. 1.1 = +10%). `damage_elements` restricts which elements are affected; empty = all. |
| `affect.regeneration` | `regeneration` | Restores `target_resource` each tick. Supports `hit_points` (default), `mana`, or `vigor`. |
| `affect.extra-hits` | `extra_hits` | Grants extra attacks per round. Specify base counts via `extra_main_hand_hits`, `extra_off_hand_hits`, `extra_unarmed_hits`. Level scaling adds bonus hits to types with base > 0 via `hits_per_level_step` / `level_step`. |
| `affect.damage-reduction` | `damage_reduction` | Flat damage subtracted from each incoming hit. Strongest active reduction wins. |

### Override fields

Each `affect_ids` entry must include `affect_id` plus any of:

`name`, `target` (self/target), `affect_mode` (instant/timed/battle_rounds), `amount`, `dice_count`, `dice_sides`, `roll_modifier`, `scaling_attribute_id`, `scaling_multiplier`, `level_scaling_multiplier`, `power_scaling_multiplier`, `duration_hours`, `duration_rounds`, `damage_elements`, `target_resource`, `extra_main_hand_hits`, `extra_off_hand_hits`, `extra_unarmed_hits`, `hits_per_level_step`, `level_step`.

See `mudproto_server/documentation/affects.md` for full documentation and examples.

---

## 7. Supported text placeholders

These are useful when writing flavor/context strings.

### Observer templates
Used in fields like `observer_action` and `observer_context`.

Supported tokens:
- `[actor_name]`
- `[actor_subject]`
- `[actor_object]`
- `[actor_possessive]`

Example:
```text
"[actor_name] slows [actor_possessive] breathing and settles into a guarded stance."
```

### Damage/support context grammar tokens
Commonly used in `damage_context`.

Supported tokens:
- `[a/an]`
- `[verb]`

Example:
```text
"[a/an] [verb] jolted by crackling force."
```

These are resolved in combat rendering code in `mudproto_server/combat.py`.

---

## 8. Current attribute IDs for scaling

When a spell or skill uses a scaling attribute, it must match one of the configured attributes in `configuration/attributes/character_attributes.json`.

Current valid ids:
- `str`
- `dex`
- `con`
- `int`
- `wis`

---

## 9. Common pitfalls to avoid

### Donâ€™t do these
- Put `wear_slots` on a weapon.
- Forget `wear_slots` on armor.
- Add a room exit to a room that does not exist.
- Reference an NPC, spell, skill, or gear template that has not been defined yet.
- Use a negative duration, lag, cooldown, or stat value where the loader forbids it.
- Mark an NPC as a merchant without giving it inventory.
- Give a limited merchant item `infinite: false` with `quantity: 0`.

### Easy-to-miss details
- `npcs.json` is wrapped in `{ "npcs": [...] }`; it is **not** a bare list.
- `zones.json` does **not** define room membership directly.
- Spell and skill **names** as well as IDs must be unique.
- If you want a player-usable off-hand weapon, set `can_hold: true` in `gear.json`.
- If you need a new wear location or slot alias, edit `configuration/attributes/wear_slots.json`, not the assets folder.
- If you need to change potion cooldown rules, edit `configuration/attributes/item_usage.json`, not `items.json`.

---

## 10. Practical generation checklist for humans and LLMs

Before saving a new asset, verify:

- [ ] JSON syntax is valid
- [ ] ID is unique and follows project naming conventions
- [ ] `name` is non-empty and player-facing
- [ ] `keywords` are lowercase and useful for selectors
- [ ] All referenced IDs already exist
- [ ] Required context fields (`damage_context`, `support_context`, etc.) are present
- [ ] Numeric fields respect the expected range
- [ ] For rooms, all exits point to real rooms
- [ ] For merchants, stock items exist and quantities make sense
- [ ] Server is restarted after the edit

---

## 11. If you are adding a brand-new encounter

A reliable pattern is:

1. Add any new **weapons/armor** to `gear.json`
2. Add any new **spells/skills** to `spells.json` / `skills.json`
3. Add the new **NPC** to `npcs.json`
4. Spawn it from a room in `rooms.json`
5. Ensure the room belongs to a valid zone in `zones.json`
6. Restart and test:
   - `look`
   - `scan`
   - `look <npc>`
   - `attack <npc>`
   - `cast` / skill usage if relevant

---

## 12. Final guidance

If you are a human author or an AI coding agent, treat `mudproto_server/assets.py` as the source of truth for what is allowed. When in doubt:

- copy the structure of an existing working asset
- keep IDs stable and references valid
- restart the server after changes
- test the new content in the actual room flow

That approach matches the current MudProto codebase and will prevent nearly all asset-loading failures.

