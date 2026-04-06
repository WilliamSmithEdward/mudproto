# MudProto Architecture

## Overview

MudProto is an async WebSocket-based MUD (Multi-User Dungeon) server and
generic terminal client, written in Python. The server is the sole owner of
game meaning; the client is a dumb renderer.

---

## 1. Client / Server Boundary

### Clients (`mudproto-client/client.py`, `mudproto-client-gui/client_gui.py`)

Both clients are **generic renderers** — they contain zero game-specific logic.

Responsibilities:
- Open and maintain the WebSocket connection.
- Send raw user input to the server as `input` messages.
- Render `display` messages and prompts.
- Handle local-only client actions such as `/quit`.

The terminal client renders ANSI output; the GUI client renders the same
structured payload in a Tk-based interface. Neither client should know
command semantics or gameplay rules.

### Server (`mudproto-server/core_logic/`)

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

### Display Spacing Aesthetics

MudProto intentionally treats blank lines as part of the UI contract, not as
incidental formatting. Both the terminal and GUI clients should render the
spacing supplied by the server exactly.

Preferred conventions:
- **Prompt block first**: the current prompt/status line stands alone.
- **Combat/action block grouped**: attack lines, death lines, and "turn to"
  lines stay contiguous with no unnecessary blank lines inserted between them.
- **Reward block separated**: XP gain and level-up text are shown after a
  single blank line following the resolved combat/death block.
- **Level-up sub-block preserved**: if a level is gained, use:
  - `You gain <n> experience.`
  - blank line
  - `You advance to level <n>!`
  - `Level gains: +HP +V +M`
- **Next prompt separated**: after the reward block, leave one blank line
  before the refreshed prompt.

Example preferred layout:

```text
132H 87V 122M 33C 113X [Tick:39s] [Me:Perfect] [Blackwatch Sentry:Awful] Exits:NES>
Lucia annihilates a Blackwatch Sentry with her slash.
A Blackwatch Sentry is dead!

You gain 38 experience.

You advance to level 5!
Level gains: +10HP +5V +6M

132H 87V 122M 33C 75X [Tick:37s] [Me:Perfect] Exits:NES>
```

---

## 3. Module Map

> Unless otherwise noted, the server Python modules below now live under `mudproto-server/core_logic/`.

| Module | Responsibility |
|--------|----------------|
| `server.py` | Thin WebSocket entrypoint plus global tick loops; delegates room broadcast shaping to `server_broadcasts.py` and movement/follow side effects to `server_movement.py`. |
| `server_broadcasts.py` | Observer-facing room broadcast generation, private-line injection, prompt spacing, and unified room-round display helpers. |
| `server_movement.py` | Movement notices, follower propagation, arrival/departure messaging, and post-move room refresh handling. |
| `protocol.py` | Envelope construction (`build_response`) and validation (`validate_message`). Timestamp helper `utc_now_iso()`. |
| `models.py` | Core dataclasses: `ClientSession`, `ItemState`, `EntityState`, `EquipmentState`, `CombatState`, `CorpseState`, `ActiveSupportEffectState`, `PlayerState`, `PlayerStatus`, `PlayerCombatState`. |
| `settings.py` | Loads `configuration/server/settings.json` and exposes typed constants (timing, combat, gameplay, session, offline, database, assets). Also bootstraps the `player_settings` DB table for reference max HP/vigor/mana. |
| `session_registry.py` | Shared connected/authenticated session maps, shared world state attachment, and session/world lookup helpers. |
| `session_timing.py` | Lag timing, lag-duration math, queued command handling, and last-message tracking for active sessions. |
| `session_bootstrap.py` | Player class application, attribute initialization, starting gear/items, and early progression bootstrap. |
| `session_lifecycle.py` | Disconnect/login reset flow, offline character processing, and session hydration/re-attachment on reconnect. |
| `commands.py` | Inbound protocol-message dispatch, auth/input handling, and lag-aware routing into `command_handlers/`. |
| `commerce.py` | Merchant/trade pricing, stock resolution, resale handling, and shared buy/sell helper logic used by command handlers. |
| `targeting_parsing.py` | Shared selector parsing and normalization helpers for commands and resolvers. |
| `targeting_entities.py` | Entity/player/corpse lookup plus room target resolution helpers. |
| `targeting_items.py` | Item and equipment selector resolution across inventory, corpses, and room ground items. |
| `targeting_follow.py` | Follow/unfollow targeting helpers and social-follow resolution. |
| `item_logic.py` | Shared corpse/item display logic and misc item-use handling. |
| `abilities.py` | Shared known spell/skill lookup and name-resolution helpers. |
| `world_population.py` | NPC/entity template hydration, training dummy spawning, shared-world initialization, and zone repopulation/reinitialization. |
| `combat_ability_effects.py` | Shared support-effect scaling, restore logic, cooldown bookkeeping, and timed/battle-round effect processing. |
| `combat_player_abilities.py` | Player skill and spell execution, targeting, resource spend, reward hooks, and observer text setup. |
| `combat_entity_abilities.py` | NPC/entity skill and spell usage against players, including self-buffs and restore effects. |
| `combat_state.py` | Encounter state transitions, engagement validation, corpse spawning, cooldown tickdown, and aggro auto-engage helpers. |
| `combat_rewards.py` | Shared contributor tracking and XP/reward distribution helpers. |
| `combat_observer.py` | Combat observer-line templating, room-broadcast line shaping, and third-person text helpers. |
| `command_handlers/` | Grouped player-facing handlers plus `runtime.py` registry/orchestration for auth, character creation, world, observation, loot, equipment, commerce, spells, skills, movement, and social interactions. |
| `combat.py` | Combat round orchestration, melee/flee flow, and encounter-resolution glue over the extracted combat helper modules. |
| `combat_text.py` | Damage-severity classification and attack-verb templates for player and NPC combat messages. |
| `damage.py` | Damage rolling (`roll_player_damage`, `roll_npc_weapon_damage`), hit-chance calculation, weapon verb resolution. |
| `equipment_logic.py` | Equip/wear/unequip mechanics, hand weight validation, armor class calculation, equipped-item selector resolution. |
| `inventory.py` | Item equippability checks, gear template hydration, item selector parsing/resolution, keyword helpers. |
| `display_core.py` | Core display builders, line/part composition, and item-highlight coloring helpers. |
| `display_feedback.py` | Prompt/status displays, command results, and error/connection feedback builders. |
| `display_views.py` | Room, inventory, equipment, spell, skill, and other structured gameplay views. |
| `grammar.py` | Shared text transforms: `indefinite_article`, `with_article`, `to_third_person`, `capitalize_after_newlines`, `third_personize_text`. |
| `attribute_config.py` | Attribute and rules config loaders for classes, regeneration, combat severity, level scaling, item usage, and experience progression. |
| `assets.py` | Content asset loaders for gear, items, rooms, zones, NPCs, spells, and skills with structural and cross-reference validation. |
| `player_state_db.py` | SQLite persistence: character credentials, full session serialization/deserialization. |
| `world.py` | `Room` and `Zone` dataclasses, including room zone membership and repopulation metadata. |
| `battle_round_ticks.py` | Per-round support effect processing during combat. |
| `game_hour_ticks.py` | Per-hour regeneration (HP/vigor/mana) and timed support effect processing. |

---

## 3A. Separation of Concern Methodology

MudProto should stay organized around **layered ownership** rather than around arbitrary file size.

### Placement Rules

1. **Client layer**
   - Clients render server output and collect input only.
   - No gameplay rules or combat/business logic should exist in client code.

2. **Public shell layer**
   - `commands.py` owns inbound message handling, auth/input dispatch, and lag-aware routing.
   - Gameplay implementation should stay in `command_handlers/` and focused domain modules rather than accumulating here.

3. **Command orchestration layer**
   - `command_handlers/` owns verb routing and player-facing command flow.
   - If code branches on `verb`, parses command-specific arguments, or decides which domain operation to invoke, it belongs here.

4. **Domain logic layer**
   - Reusable game rules belong in focused core modules such as `combat.py`, `combat_state.py`, `combat_player_abilities.py`, `commerce.py`, `inventory.py`, `equipment_logic.py`, `targeting_entities.py`, `targeting_items.py`, `item_logic.py`, and `abilities.py`.
   - If logic is shared by multiple commands, it should live here rather than in a handler file.

5. **Presentation layer**
   - Output formatting belongs in `display_core.py`, `display_feedback.py`, `display_views.py`, and `grammar.py`.
   - Game rules should not be mixed with text styling or sentence transformation helpers.

6. **Configuration and persistence layer**
   - `settings.py`, `assets.py`, `attribute_config.py`, and `player_state_db.py` own data loading, configuration validation, and persistence concerns.
   - These modules should not become command-routing or gameplay orchestration sinks.

### Dependency Direction

Preferred dependency flow:

```text
server.py / session_* modules
  -> commands.py
    -> command_handlers/*
      -> domain/core modules
        -> display/config/persistence helpers
```

Rules:
- Domain modules should **not** import command handler modules.
- Command-handler facades and registries should stay **thin**, not become new sinks for shared business logic.
- Lazy imports are acceptable only to preserve public compatibility boundaries or to avoid unavoidable cycles during refactors.

### Refactor Methodology

When separating concerns further:
1. Split by **domain responsibility**, not one file per verb.
2. Preserve stable public entrypoints while moving internals behind them.
3. Extract one concern at a time and verify imports/diagnostics after each move.
4. Prefer small, composable helpers over one large "shared" sink.
5. If a file owns both routing and reusable rules, move the reusable rules first.

### Current Best Next Opportunities

The current refactor now centers around thin orchestration shells with focused helpers behind them:

- **`combat.py`** now delegates encounter state, rewards, and observer text to `combat_state.py`, `combat_rewards.py`, and `combat_observer.py`.
- **Combat ability logic** now lives directly in `combat_ability_effects.py`, `combat_player_abilities.py`, and `combat_entity_abilities.py`.
- **`server.py`** now delegates room-broadcast shaping and follow/movement side effects to `server_broadcasts.py` and `server_movement.py`.

The best next cleanup from here is continuing to remove any remaining compatibility-only wrappers once all call sites are migrated directly.

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
    items.json             # consumable item templates and restore effects
    npcs.json              # NPC templates (HP, AI, loot, merchant inventory)
    rooms.json             # world rooms (exits, zone_id, NPC spawns)
    zones.json             # zone membership and repop timing in game hours
    spells.json            # player spells (damage/support, mana cost)
    skills.json            # player skills (vigor cost, scaling, cooldown)
  attributes/
    character_attributes.json   # attribute definitions (STR, DEX, CON, INT, WIS)
    classes.json                # player classes, starting gear, spells, skills
    combat_severity.json        # text thresholds and severity tuning
    experience.json             # XP required per level
    hand_weight.json            # weapon STR requirements
    item_usage.json             # consumable cooldown rules (for example potions)
    level_scaling.json          # player melee hit/damage scaling by level
    regeneration.json           # regen rates per attribute & resource
    wear_slots.json             # armor slot options (left/right, head, chest, etc.)
```

Loaders in `assets.py` and `attribute_config.py` are **LRU-cached** (loaded once per process) and
eagerly validate:
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
via `world_population.py::initialize_session_entities()`. Entities carry their own HP,
power level, weapon template IDs, skill list, and cooldown tracking.

### Session Model

`ClientSession` is the god-object for a connected player. It holds:
- `player` (room, class, attributes), `status` (HP/vigor/mana/coins)
- `player_combat` (attack damage, attacks per round)
- `equipment`, `inventory_items`
- `combat` (engaged entities, opening attacker, skill and item cooldowns)
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
  optional room_broadcast_parts → other players in room
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
`equipment_logic.py` (equipped-item selectors).

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

Out-of-combat sessions still get their skill and item cooldowns decremented each
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
- **Damage spells**: targeted or AoE. Roll dice, apply to engaged entities.
- **Support spells**: heal/vigor/mana. Self-cast only.
  Modes: `instant`, `timed` (hours), `battle_rounds`.
- Cast via `cast <spell> [target]`.

### Skills

- Cost vigor. Defined in `skills.json`.
- Scale with an attribute via `scaling_attribute_id` × `scaling_multiplier`.
- Have cooldowns (rounds). `usable_out_of_combat` flag.
- Used via `<skill_name> [target]` (longest-prefix match on known skills).

### Cooldowns

- Player skills: `combat.skill_cooldowns[skill_id]` decremented each combat
  round and also while out of combat via `tick_out_of_combat_cooldowns()`.
- Player consumables: `combat.item_cooldowns["potion"]` enforces the global
  potion reuse lockout, configured by `configuration/attributes/item_usage.json`.
- NPC: `entity.skill_cooldowns` + `skill_lag_rounds_remaining`.

### Support Effects

- `ActiveSupportEffectState` tracked on the session.
- **Timed** (`remaining_hours`): processed by `game_hour_ticks.py` each
  game hour.
- **Battle-round** (`remaining_rounds`): processed by
  `battle_round_ticks.py` each combat round.

---

## 10. Equipment & Inventory

### Equip / Wear / Hold

`equipment_logic.py` handles state transitions:
- **Wield**: main hand (weapon).
- **Hold**: off hand (weapon with `can_hold`).
- **Wear**: armor into a wear slot. If the primary slot is taken, tries
  alternates from `wear_slots.json`.
- Hand weight limits enforced via `hand_weight.json` (STR multiplier).

### Armor Class

`equipment_logic.py::compute_player_armor_class()`:
`BASE_PLAYER_ARMOR_CLASS` + sum of `armor_class_bonus` from all worn items.

### Item Highlighting

`display_core.py::_item_highlight_color()` — equippable items render in
**bright magenta**; non-equippable items in **bright cyan**. This is used
consistently across inventory, room, loot, and action-message contexts.

---

## 11. Display & Rendering

Display messages are built across `display_core.py`, `display_feedback.py`, and `display_views.py` and sent as structured JSON `lines`. Each line is an array of styled text parts, where each part carries `text`, optional `fg` color, and optional `bold` flag. Both the terminal client and the GUI client render these line arrays from the same server payload.

Key builders:
- `build_display()` / `build_display_lines()` — assemble final protocol payloads with structural `lines`.
- `display_room()` — room title, description, exits, NPCs, corpses, items,
  coins, other players.
- `display_inventory()`, `display_equipment()`, `display_attributes()`.
- `build_prompt_parts()` — HP/vigor/mana (color-coded), coins, XP-to-next,
  engaged-entity condition, and exits.

Rendering invariants:
- Newline behavior is server-owned and represented by empty line entries (`[]`)
  inside `lines` and `prompt_lines`.
- Clients do not invent spacing for server messages; they render the supplied
  structure.
- When an event is visible to both the actor and observers, `room_broadcast_lines`
  should preserve the same event ordering whenever possible.

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

## 15. World, Zones & NPC Spawning

Rooms are defined in `rooms.json` with exits (direction → room ID), `zone_id`,
and NPC spawn configs (template ID + count). Zones are defined in `zones.json`
with `room_ids` and `repopulate_game_hours`.

`world_population.py::initialize_session_entities()` and the zone repopulation helpers
instantiate `EntityState` copies from NPC templates. Shared entities live in the
world dict so all players interact with the same NPC instances.

Key behaviors:
- Aggro NPCs (`is_aggro: true`) auto-engage the player on room entry.
- Peaceful NPCs can remain valid spell targets for messaging, but offensive
  effects do not apply to them.
- Merchant NPCs expose `merchant_inventory` with finite or infinite stock.
- Zone repopulation is occupancy-aware: if players are present, a due repop is
  delayed until the next eligible game-hour tick when the zone is empty.

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
  ARCHITECTURE.md                # this file (canonical architecture doc)
  README.md
  mudproto-client/
    client.py                    # generic ANSI terminal client
  mudproto-client-gui/
    client_gui.py                # generic Tk GUI client
  mudproto-server/
    core_logic/
      server.py                  # thin async server entry point and tick loops
      server_broadcasts.py       # room broadcast and outbound shaping helpers
      server_movement.py         # movement/follow side effects and room notices
      protocol.py                # envelope helpers and validation
      models.py                  # all core dataclasses
      settings.py                # typed constants from settings.json + DB bootstrap
      session_*.py               # session lifecycle, registry, timing, and bootstrap helpers
      commands.py                # command parsing compatibility shell
      command_handlers/          # grouped command handlers plus runtime registry
      combat.py                  # combat round orchestration and melee flow
      combat_state.py            # encounter state, corpses, and cooldown helpers
      combat_rewards.py          # XP contribution and reward helpers
      combat_observer.py         # observer/broadcast text shaping helpers
      combat_ability_effects.py  # support-effect scaling and cooldown bookkeeping
      combat_player_abilities.py # player spell/skill execution
      combat_entity_abilities.py # NPC spell/skill execution
      combat_text.py             # damage-severity message templates
      damage.py                  # damage and hit-chance math
      equipment_logic.py         # equip, wear, and unequip mechanics
      inventory.py               # item selectors and template hydration
      display_core.py            # low-level display builders and color helpers
      display_feedback.py        # prompts, errors, and command feedback builders
      display_views.py           # room/inventory/equipment/etc. views
      targeting_parsing.py       # selector parsing helpers
      targeting_entities.py      # entity/player/corpse resolvers
      targeting_items.py         # item selector resolvers
      targeting_follow.py        # follow/unfollow targeting helpers
      grammar.py                 # shared text and grammar transforms
      attribute_config.py        # attribute and rules config loaders
      assets.py                  # content asset loaders with validation
      player_state_db.py         # SQLite persistence
      world.py                   # Room and Zone dataclasses
      battle_round_ticks.py      # per-round support effect processing
      game_hour_ticks.py         # per-hour regen and timed support processing
    configuration/
      server/settings.json
      assets/gear.json
      assets/items.json
      assets/npcs.json
      assets/rooms.json
      assets/zones.json
      assets/spells.json
      assets/skills.json
      attributes/character_attributes.json
      attributes/classes.json
      attributes/combat_severity.json
      attributes/experience.json
      attributes/hand_weight.json
      attributes/item_usage.json
      attributes/level_scaling.json
      attributes/regeneration.json
      attributes/wear_slots.json
    db/                          # SQLite database directory (runtime)
```