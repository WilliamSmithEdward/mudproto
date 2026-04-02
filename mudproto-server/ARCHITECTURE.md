# MudProto Architecture

## Overview

MudProto is an async WebSocket-based MUD (Multi-User Dungeon) server and
generic terminal client, written in Python. The server is the sole owner of
game meaning; the client is a dumb renderer.

---

## 1. Client / Server Boundary

### Client (`mudproto-client/client.py`)

The client is **generic** — it contains zero game-specific logic.

Responsibilities:
- Open and maintain the WebSocket connection.
- Send raw user input to the server as `input` messages.
- Render `display` messages (ANSI color, bold, prompts).
- Handle local-only commands (`/quit`).

The client must **not** know command semantics, game mechanics, or
rendering rules beyond color/bold.

### Server (`mudproto-server/`)

The server is the sole owner of game meaning.

Responsibilities:
- Validate protocol envelopes.
- Parse commands and apply gameplay rules.
- Enforce lag and queue commands during lag.
- Build display/output instructions for the client.
- Manage session, world, and persistence state.

### Invariants

- Lag is enforced server-side and blocks command execution, not outbound
  messages.
- Command queues are FIFO per session.
- The client sends generic input; the server sends structured display
  instructions.

---

## 2. Protocol Contract

### Client → Server

```json
{
  "type": "input",
  "source": "mudproto-client",
  "timestamp": "2026-03-28T12:34:56Z",
  "payload": { "text": "look" }
}
```

### Server → Client

```json
{
  "type": "display",
  "source": "mudproto-server",
  "timestamp": "2026-03-28T12:34:56Z",
  "payload": {
    "lines": [
      [],
      [
        { "text": "You see ", "fg": "bright_white", "bold": false },
        { "text": "an orc",  "fg": "bright_magenta", "bold": true },
        { "text": ".",        "fg": "bright_white",   "bold": false }
      ]
    ],
    "prompt_lines": [
      [],
      [{ "text": "575H 119V 160M> " }]
    ],
    "starts_on_new_line": false,
    "room_broadcast_lines": []
  }
}
```

Every envelope has `type`, `source`, `timestamp`, `payload`. Validation
lives in `protocol.py`.

---

## 3. Module Map

| Module | Responsibility |
|--------|----------------|
| `server.py` | WebSocket listener, global tick loops (combat rounds, game hours), room-round broadcast orchestration, offline character processing. |
| `protocol.py` | Envelope construction (`build_response`) and validation (`validate_message`). Timestamp helper `utc_now_iso()`. |
| `models.py` | Core dataclasses: `ClientSession`, `ItemState`, `EntityState`, `EquipmentState`, `CombatState`, `CorpseState`, `ActiveSupportEffectState`, `PlayerState`, `PlayerStatus`, `PlayerCombatState`. |
| `settings.py` | Loads `configuration/server/settings.json` and exposes typed constants (timing, combat, gameplay, session, offline, database, assets). Also bootstraps the `player_settings` DB table for reference max HP/vigor/mana. |
| `sessions.py` | Session registry (`connected_clients`, `active_character_sessions`), login/disconnect lifecycle, shared world attachment, offline character loop, session hydration on reconnect. |
| `commands.py` | Command parsing, dispatch, authentication state machine, all player-facing commands (movement, combat, inventory, equipment, spells, skills, look, say, etc.). |
| `combat.py` | Combat round resolution, NPC AI (skill usage), entity spawning, corpse/loot creation, spell/skill execution, flee logic. |
| `combat_text.py` | Damage-severity classification and attack-verb templates for player and NPC combat messages. |
| `damage.py` | Damage rolling (`roll_player_damage`, `roll_npc_weapon_damage`), hit-chance calculation, weapon verb resolution. |
| `equipment.py` | Equip/wear/unequip mechanics, hand weight validation, armor class calculation, equipped-item selector resolution. |
| `inventory.py` | Item equippability checks, gear template hydration, item selector parsing/resolution, keyword helpers. |
| `display.py` | Display message building (room, inventory, equipment, attributes, spells, skills, prompt), color/item-highlight logic. |
| `grammar.py` | Shared text transforms: `indefinite_article`, `with_article`, `to_third_person`, `capitalize_after_newlines`, `third_personize_text`. |
| `attribute_config.py` | Attribute/rules config loaders for character attributes, player classes, wear slots, regeneration, hand weight, combat severity, and experience progression. |
| `assets.py` | Content asset loaders for gear, items, rooms, NPCs, spells, and skills with structural and cross-reference validation. |
| `player_state_db.py` | SQLite persistence: character credentials, full session serialization/deserialization. |
| `world.py` | `Room` dataclass including exits and NPC spawn config. |
| `battle_round_ticks.py` | Per-round support effect processing during combat. |
| `game_hour_ticks.py` | Per-hour regeneration (HP/vigor/mana) and timed support effect processing. |

---

## 4. Configuration & Assets

All data-driven files live under `configuration/`.

```
configuration/
  server/
    settings.json          # network, timing, combat, gameplay, session,
                           # offline, database, assets sections
  assets/
    gear.json              # weapon & armor templates (damage, AC, slots)
    items.json             # consumable item templates
    npcs.json              # NPC templates (HP, attacks, loot, skills)
    rooms.json             # world rooms (exits, NPC spawns)
    spells.json            # player spells (damage/support, mana cost, school)
    skills.json            # player skills (vigor cost, scaling, cooldown)
  attributes/
    character_attributes.json   # attribute definitions (STR, DEX, CON, INT, WIS)
    classes.json                # player classes, starting_gear_template_ids,
                                # starting_equipped_gear_template_ids, spells, skills
    hand_weight.json            # weapon STR requirements
    regeneration.json           # regen rates per attribute & resource
    wear_slots.json             # armor slot options (left/right, head, chest, etc.)
```

Loaders in `assets.py` and `attribute_config.py` are **LRU-cached** (loaded
once per process) and eagerly validate:
- No duplicate IDs.
- Required fields and correct types.
- Cross-references resolve (e.g. class gear template IDs exist in
  `gear.json`).

---

## 5. Data Model

### Item Model (unified)

All items — inventory, ground, loot, equipped — use a single `ItemState`
dataclass. The `equippable` flag is an **intrinsic property** populated from
the gear template at creation/deserialization time.

```
ItemState
  ├─ item_id (UUID)
  ├─ template_id
  ├─ name, description, keywords
  ├─ equippable (bool)
  ├─ slot ("weapon" | "armor")
  ├─ Weapon fields: damage dice, hit/damage modifiers, weapon_type, can_hold
  ├─ Armor fields:  armor_class_bonus, wear_slot, wear_slots
  └─ weight
```

`inventory.py::is_item_equippable()` lazily hydrates missing stats from the
gear template. `inventory.py::build_equippable_item_from_template()` creates
a fresh `ItemState` from a template ID.

### Equipment State

```
EquipmentState
  ├─ equipped_items          {item_id → ItemState}
  ├─ equipped_main_hand_id   (Optional)
  ├─ equipped_off_hand_id    (Optional)
  └─ worn_item_ids           {wear_slot → item_id}
```

Invariant: every item in `equipped_items` is referenced by exactly one of
`equipped_main_hand_id`, `equipped_off_hand_id`, or an entry in
`worn_item_ids`.

### Entity State

NPCs are represented by `EntityState` — each instance is spawned per-player
via `combat.py::initialize_session_entities()`. Entities carry their own HP,
power level, weapon template IDs, skill list, and cooldown tracking.

### Session Model

`ClientSession` is the god-object for a connected player. It holds:
- `player` (room, class, attributes), `status` (HP/vigor/mana/coins)
- `player_combat` (attack damage, attacks per round)
- `equipment`, `inventory_items`
- `combat` (engaged entities, cooldowns, opening attacker)
- `entities`, `corpses`, `room_coin_piles`, `room_ground_items` (shared
  world references)
- `known_spell_ids`, `known_skill_ids`, `active_support_effects`
- Auth/connection state, lag state, command queue, scheduler task

---

## 6. Session Lifecycle

### Connection

1. WebSocket connects → `ClientSession` created with unique `client_id`.
2. Registered in `connected_clients`.
3. Attached to shared world state (entities, corpses, coins, ground items).
4. Per-session `command_scheduler_loop` task launched.
5. Welcome screen sent; message listen loop starts.

### Authentication

Multi-stage state machine in `commands.py::_process_auth_input()`:

```
awaiting_character_or_start
  ├─ "start" → awaiting_new_character_name → awaiting_new_character_password
  │            → awaiting_new_character_class → create & login
  └─ <name>  → awaiting_existing_password → validate & login
```

On login:
- If character already active (reconnect): hydrate new session from stale
  session's state.
- Otherwise: load from SQLite via `player_state_db`.
- Apply class defaults, spawn entities, display room.

### Disconnect

1. Remove from `connected_clients`.
2. Save player state to DB.
3. Launch `_offline_character_loop()`:
   - Auto-flee every 2 s if in combat.
   - Regenerate via game-hour ticks.
   - After 5 consecutive safe hours → auto-disconnect, respawn at
     `login_room_id`.

### Reconnect

`hydrate_session_from_active_character()` copies all runtime state (combat,
equipment, inventory, position, support effects) from the stale session.
Old scheduler task is cancelled; new one starts.

---

## 7. Command System

### Parsing

`parse_command(text)` → `(verb, args)`. First whitespace-delimited word is
the verb; remainder is args. Direction aliases (`n`→`north`, `u`→`up`, etc.)
are normalised.

### Dispatch

```
Raw input
  ↓  validate_message() [protocol.py]
  ↓  dispatch_message() [commands.py]
  ├─ Not authenticated → _process_auth_input()
  ├─ Authenticated + lagged → enqueue (FIFO, max 5)
  └─ Authenticated + not lagged → execute_command()
  ↓
  send_outbound() → client
  optional room_broadcast_lines → other players in room
```

### Lag & Queuing

- `lag_until_monotonic` is a monotonic timestamp on the session.
- Combat/skill/spell actions apply `COMBAT_ROUND_INTERVAL_SECONDS` (2.5 s)
  of lag.
- Query commands (`look`, `inventory`, `equipment`, `attributes`) are
  instant.
- `command_scheduler_loop` (0.1 s tick) dequeues and executes one command
  when lag expires.

### Item / Entity Selectors

Selectors use `<index>.<keyword>` syntax:
- `1.sword` — first item matching "sword".
- `2.training.sword` — second item matching both "training" and "sword".
- `wear vest left.hand` — wear to a specific slot.

Resolution lives in `inventory.py` (inventory/ground selectors) and
`equipment.py` (equipped-item selectors).

---

## 8. Combat System

### Engagement

- `attack <target>` adds entity to `combat.engaged_entity_ids`.
- A player can fight **multiple NPCs simultaneously**.
- `flee` has 50 % success chance; on success, move to a random exit.

### Combat Round Loop

`server.py::combat_round_loop()` ticks every 2.5 s globally:

1. Collect all authenticated sessions with active combat.
2. Group by room.
3. Per room, assign each NPC an active target session (one player per NPC).
4. For each player (alphabetical order):
   - `combat.py::resolve_combat_round()` — player attacks primary target,
     entities retaliate.
5. Build **unified room-round display** — each player's combat output is
   third-personised for observers, then merged into a single chronological
   block so everyone in the room sees the full picture.
6. Send display + force prompt to each player.

Out-of-combat sessions still get their skill cooldowns decremented each
tick.

### Opening Round

The `opening_attacker` field tracks who struck first. The opener gets a
half-strength first hit; the other side responds at full strength.
Subsequent rounds are full strength for both sides.

### Damage

- Player: base attack damage + weapon dice + modifiers
  (`damage.py::roll_player_damage`).
- NPC: power level + weapon dice + modifiers
  (`damage.py::roll_npc_weapon_damage`).
- Severity label chosen by damage-to-max-HP ratio (`combat_text.py`):
  miss → barely → normal → hard → extreme → massacre → annihilate →
  obliterate.

### Death & Loot

When an entity dies:
- A `CorpseState` is created with coin reward and loot items (built from
  the entity's equipped gear templates).
- Lootable via `get <item> <corpse>` or `get all <corpse>`.
- Engaged entity removed from `engaged_entity_ids`; combat ends if no
  targets remain.

---

## 9. Spells & Skills

### Spells

- Cost mana. Defined in `spells.json`.
- Each spell declares a lore `school` string.
- **Damage spells**: targeted or AoE. Roll dice, apply to engaged entities.
- **Support spells**: heal/vigor/mana. Self-cast only.
  Modes: `instant`, `timed` (hours), `battle_rounds`.
- Cast via `cast <spell> [target]`.
- The spells menu renders aligned columns in the order: Name, School, Cost.

### Skills

- Cost vigor. Defined in `skills.json`.
- Scale with an attribute via `scaling_attribute_id` × `scaling_multiplier`.
- Have cooldowns (rounds). `usable_out_of_combat` flag.
- Used via `<skill_name> [target]` (longest-prefix match on known skills).

### Cooldowns

- Player: `combat.skill_cooldowns[skill_id]` decremented each combat
  round (and out-of-combat via `tick_out_of_combat_cooldowns`).
- NPC: `entity.skill_cooldowns` + `skill_lag_rounds_remaining`.

### Support Effects

- `ActiveSupportEffectState` tracked on player sessions and NPC entities.
- Support effects can be flat-value and/or dice-based each application tick:
  `support_amount` + rolled support dice + roll modifier + scaling bonus.
- **Timed** (`remaining_hours`): player effects are processed by
  `game_hour_ticks.py`; NPC effects are processed from the global tick loop
  via `combat.py::process_entity_game_hour_tick()`.
- **Battle-round** (`remaining_rounds`): player effects are processed by
  `battle_round_ticks.py`; NPC effects are processed in
  `combat.py::_process_combat_round_timers()`.
- Default scaling for support heal spells:
  player casts default to WIS-derived scaling when no
  `support_scaling_attribute_id` is specified; NPC casts default to
  `power_level` scaling.

### Experience & Levels

- Progression thresholds are configured in
  `configuration/attributes/experience.json`.
- Player XP and level are stored in `PlayerState` and persisted by
  `player_state_db.py`.
- NPC templates support `experience_reward`; XP is awarded when players kill
  NPCs.
- Combat output includes XP gain lines and level-up lines when applicable.

---

## 10. Equipment & Inventory

### Equip / Wear / Hold

`equipment.py` handles state transitions:
- **Wield**: main hand (weapon).
- **Hold**: off hand (weapon with `can_hold`).
- **Wear**: armor into a wear slot. If the primary slot is taken, tries
  alternates from `wear_slots.json`.
- Hand weight limits enforced via `hand_weight.json` (STR multiplier).

### Armor Class

`equipment.py::compute_player_armor_class()`:
`BASE_PLAYER_ARMOR_CLASS` + sum of `armor_class_bonus` from all worn items.

### Item Highlighting

`display.py::_item_highlight_color()` — equippable items render in
**bright magenta**; non-equippable items in **bright cyan**. This is used
consistently across inventory, room, loot, and action-message contexts.

---

## 11. Display & Rendering

Display messages are built in `display.py` and sent as structured JSON `lines`.
Each line is an array of styled text parts, where each part carries `text`,
optional `fg` color, and optional `bold` flag. The client renders line arrays
as ANSI-colored terminal output.

Key builders:
- `build_display()` — assembles final protocol payload with structural `lines`.
- `display_room()` — room title, description, exits, NPCs, corpses, items,
  coins, other players.
- `display_inventory()`, `display_equipment()`, `display_attributes()`.
- `build_prompt_parts()` — HP/vigor/mana (color-coded), coins, XP-to-next,
  tick countdown, engaged-entity condition, exits.

Rendering invariants:
- All newline behavior is server-owned and encoded in JSON via empty line
  entries (`[]`) inside `lines` / `prompt_lines`.
- The client does not inject blank lines for display messages; it only renders
  what the server sends.
- Command-panel UIs (currently score, spells, skills, inventory, and
  equipment) use a shared visual
  frame/table contract from `display.py` (`build_menu_table_parts`): dynamic
  column widths sized to content, minimum panel width (`PANEL_INNER_WIDTH`),
  centered title line, and full-width divider rows. New panel-style command
  outputs should reuse this contract for
  consistent horizontal alignment.
- A blank line before a prompt is represented by leading empty entries in
  `prompt_lines`.
- When an event is visible to both actor and observers, `room_broadcast_lines`
  should preserve the same event ordering as actor-facing `lines` whenever
  possible.
- Styling should remain semantically consistent between actor and broadcast
  output for shared events (example: death announcements stay bright red/bold
  in both views).
- Third-personisation should change wording only; it should not change spacing
  structure or intended event chronology.

Room broadcasts use `room_broadcast_lines` and are third-personised via
`grammar.py::third_personize_text()`.

---

## 12. Persistence

### SQLite Schema

```sql
characters (
  character_key  TEXT PRIMARY KEY,  -- lowercase name
  character_name TEXT,
  password_salt, password_hash,     -- SHA-256
  class_id, login_room_id,
  created_at, updated_at
)

player_state (
  player_key TEXT PRIMARY KEY,
  state_json TEXT,                  -- full serialised session
  updated_at
)

player_settings (
  setting_key   TEXT PRIMARY KEY,   -- reference_max_hp, etc.
  setting_value INTEGER,
  updated_at
)
```

### What Is Saved

Position, class, attributes, HP/vigor/mana/coins, equipment (main hand,
off hand, worn items), inventory items, known spells, known skills, active
timed support effects.

### What Is Not Saved

Combat state, command queue, lag, entities, corpses, ground items, coin
piles. These reset on logout.

Save triggers: character creation, game-hour tick, disconnect, offline
auto-disconnect.

---

## 13. Tick Systems

| Tick | Interval | Scope | Logic |
|------|----------|-------|-------|
| Command scheduler | 0.1 s | Per session | Dequeue commands, process game-hour ticks, process non-combat support. |
| Combat round | 2.5 s | Global | Resolve combat per room, unified room-round display, cooldown decrement. |
| Game hour | 60 s | Per session | HP/vigor/mana regeneration (attribute-scaled), timed support effect processing. |

---

## 14. Shared vs Private State

| State | Storage | Shared? |
|-------|---------|---------|
| Entities | `session.entities` (alias to shared dict) | Yes — all players see the same NPC instances. |
| Corpses | `session.corpses` | Yes |
| Ground items | `session.room_ground_items` | Yes |
| Coin piles | `session.room_coin_piles` | Yes |
| Inventory | `session.inventory_items` | No — per player. |
| Equipment | `session.equipment` | No — per player. |
| Combat | `session.combat` | No — per player. |

---

## 15. World & NPC Spawning

Rooms are defined in `rooms.json` with exits (direction → room ID) and NPC
spawn configs (template ID + count).

`combat.py::initialize_session_entities()` iterates every room's spawn
config and instantiates `EntityState` copies. Entities are added to the
shared world dict so all players interact with the same NPC instances.

Aggro NPCs (`is_aggro: true`) auto-engage the player on room entry.

---

## 16. Grammar & Text Pipeline

`grammar.py` centralises all natural-language transforms:
- **Articles**: `indefinite_article("orc")` → `"an"`;
  `with_article("sword")` → `"a sword"`.
- **Third-person verbs**: `to_third_person("slash")` → `"slashes"`.
- **Capitalisation**: `capitalize_after_newlines(text)` — uppercase after
  `\n` and at string start.
- **Person rewrite**: `third_personize_text(text, actor)` — rewrites
  second-person combat/action text for room observers
  ("You slash an orc" → "PlayerName slashes an orc").

---

## 17. Project Layout

```
mudproto/
  mudproto-client/
    client.py                    # generic WebSocket terminal client
  mudproto-server/
    ARCHITECTURE.md              # this file
    server.py                    # async server entry point & tick loops
    protocol.py                  # envelope helpers & validation
    models.py                    # all core dataclasses
    settings.py                  # typed constants from settings.json + DB bootstrap
    sessions.py                  # session registry & lifecycle
    commands.py                  # command parsing & all player commands
    combat.py                    # combat resolution & entity management
    combat_text.py               # damage-severity message templates
    damage.py                    # damage & hit-chance math
    equipment.py                 # equip/wear/unequip mechanics
    inventory.py                 # item equippability, selectors, template hydration
    display.py                   # display builders (room, inventory, prompt, etc.)
    grammar.py                   # shared text/grammar transforms
    attribute_config.py          # attribute and rules config loaders
    assets.py                    # content asset loaders with validation
    player_state_db.py           # SQLite persistence
    world.py                     # Room dataclass
    battle_round_ticks.py        # per-round support effect processing
    game_hour_ticks.py           # per-hour regen & timed support processing
    configuration/
      server/settings.json
      assets/gear.json
      assets/items.json
      assets/npcs.json
      assets/rooms.json
      assets/spells.json
      assets/skills.json
      attributes/character_attributes.json
      attributes/classes.json
      attributes/hand_weight.json
      attributes/regeneration.json
      attributes/wear_slots.json
    db/                          # SQLite database directory (runtime)
```