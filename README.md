<div align="center">

# âš”ï¸ MudProto

**A server-authoritative multiplayer MUD built in Python.**

*Async WebSocket server Â· Terminal and GUI clients Â· Tabletop-inspired fantasy systems*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![WebSockets](https://img.shields.io/badge/WebSockets-async-4B8BBE)](https://websockets.readthedocs.io)
[![SQLite](https://img.shields.io/badge/SQLite-persistence-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)

</div>

![MudProto gameplay screenshot](/images/mudproto_01.png)

> ðŸ¤– **Development note:** MudProto actively uses **agentic AI workflows** for content generation, documentation, schema-guided authoring, and iteration alongside normal hand-written development.

---

## Quick Start

```bash
# Clone
git clone https://github.com/WilliamSmithEdward/mudproto.git
cd mudproto

# Set up environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install websockets

# Start the server
python mudproto_server/core_logic/server.py

# In a second terminal â€” connect a client
cd mudproto_client
python client.py

# Or launch the GUI client
cd ..\mudproto_client_gui
python client_gui.py
```

Type `start` to create a character and choose a class. Good first commands are `look` and `inventory`. In the south market you can `buy potion`; in the northern hall you can `attack scout`, `jab scout`, and `flee`.

---

## ðŸ¤– AI Content Generation

MudProto can also take **LLM-generated content bundles** through the `asset_payloads` pipeline. The intended workflow starts from the generator script:

- `mudproto_llm_interfaces/generate_asset_payload_generation_instructions.py`

That script regenerates:

- `mudproto_llm_interfaces/asset_payload_generation_instructions.json`

which is the instruction payload you hand to an AI model when asking it to generate new game content.

### Quick workflow
1. Run or reference `mudproto_llm_interfaces/generate_asset_payload_generation_instructions.py` to produce the latest instruction JSON.
2. Give the resulting `asset_payload_generation_instructions.json` to your AI model along with your content brief.
3. Make sure the model returns a **downloadable `.json` file** â€” not Markdown-wrapped output.
4. Save that file into `mudproto_server/configuration/assets/asset_payloads/`.
5. Restart the server to load the new payload.

For the full process, merge rules, override behavior, caveats, and review checklist, see [`LLM_CONTENT_GENERATION.md`](LLM_CONTENT_GENERATION.md).

---

## Overview

MudProto is a modern take on the classic **Multi-User Dungeon**: a shared fantasy world with real-time combat, spells, skills, merchants, and persistent characters. Content and progression are driven by JSON, while the server remains the source of truth for every rule, roll, and result.

Built as both a playable game and a systems-focused codebase, MudProto emphasizes readable architecture, server-authoritative gameplay, and an extensible content pipeline that is easy to iterate on.

---

## Highlights

### ðŸ—¡ï¸ Combat Engine
- **Multi-NPC engagement** â€” fight several enemies at once, each retaliating independently.
- **Room-round consolidation** â€” all players in a room see a unified, chronological combat log each round.
- **Opening-round initiative** â€” the opener acts before the first full exchange, with off-hand attacks held back during that opening moment.
- **Selective spell engagement** â€” offensive spell casts only enroll the caster in combat against non-engaged targets; already-engaged targets can still be damaged without pulling the caster in.
- **Configurable damage severity messaging** â€” attack text uses threshold-based tiers from `miss` and `barely` up through `massacre`, `annihilate`, and `obliterate`.
- **Flee with uncertainty** â€” escaping is possible, but never guaranteed.

### ðŸ§™ Spells & Skills
- **Mana-based spells** â€” targeted damage, AoE, self-heal, vigor restore, mana restore.
- **Vigor-based skills** â€” attribute-scaled damage and support, with per-skill cooldowns.
- **Support effects** â€” instant, timed (game hours), or combat-round durations.
- **Step-scaled support tuning** â€” skills can scale support effects by level steps using `support_level_step` and `support_amount_per_level_step`.
- **Game-hour skill cooldowns** â€” support/damage skills can use `cooldown_hours`, and these persist across full disconnect/reconnect.
- **NPC AI** â€” enemies can use both skills and spells with independent cooldown tracking.

### ðŸ‘¥ Social Systems
- **Follow + watch targeting** â€” players can follow allies and watch a nearby player's status from the prompt.
- **Group management** â€” `group`, `group form`, `group <player>`, `ungroup <player>`, and `group disband` are supported.
- **Death-aware follow behavior** â€” follower/group relationships are reconciled when a leader dies (group disbands, follow retargeting rules applied).

### ðŸŽ’ Unified Item System
- **Single `ItemState` model** â€” no split between "inventory items" and "equipment items." Every item carries an intrinsic `equippable` flag hydrated from gear templates.
- **Flexible wear slots** â€” armor can be worn in primary or alternate slots (e.g., rings â†’ left or right hand).
- **Hand weight limits** â€” weapon wielding / holding gated by STR via configurable thresholds.
- **Color-coded display** â€” equippable items appear in **magenta** and consumables in **yellow**, consistently across the UI.

### ðŸŒ Persistent World
- **Data-driven rooms** â€” exits, NPC spawns, and descriptions all defined in JSON.
- **Shared world state** â€” entities, corpses, ground items, and coin piles visible to all connected players.
- **Aggro NPCs** â€” auto-engage on room entry.
- **Corpse loot** â€” defeated enemies drop gear and coins for any player to claim.

### ðŸ’¾ Character Persistence
- **SQLite-backed** â€” full character state serialized/deserialized on login/logout and every game hour (60 seconds by default).
- **Offline processing** â€” disconnected characters auto-flee combat, regenerate, and gracefully disconnect after 5 safe hours.
- **Seamless reconnect** â€” resume an active session mid-combat with full state hydration.

### ðŸ–¥ï¸ Clients
- **Terminal client** â€” ANSI-rendered output with a compact, readable prompt.
- **GUI client** â€” a Tk-based interface that consumes the same server protocol.
- **Shared protocol** â€” both clients stay thin; all game logic remains server-side.
- **Queue feedback** â€” lag-blocked commands are queued cleanly and the prompt returns when ready.

---

## Architecture at a Glance

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”         WebSocket          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚       Clients        â”‚â—„â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–ºâ”‚     Game Server         â”‚
â”‚                      â”‚   JSON envelopes           â”‚                         â”‚
â”‚  â€¢ ANSI / Tk render  â”‚   { type, source,          â”‚  â€¢ Command parsing      â”‚
â”‚  â€¢ Raw input send    â”‚     timestamp, payload }   â”‚  â€¢ Combat resolution    â”‚
â”‚  â€¢ Prompt display    â”‚                            â”‚  â€¢ Spell / skill engine â”‚
â”‚  â€¢ /quit             â”‚                            â”‚  â€¢ Persistence (SQLite) â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                            â”‚  â€¢ Tick systems         â”‚
                                                    â”‚  â€¢ Room broadcasts      â”‚
                                                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

The **clients send raw text**; the **server sends structured display instructions**. All game meaning lives server-side. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full technical deep-dive.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, `asyncio` |
| Networking | `websockets` (async server + client) |
| Persistence | SQLite 3 via `sqlite3` stdlib |
| Configuration | JSON asset files with eager validation |
| Client rendering | ANSI terminal output + Tkinter GUI |

**Minimal dependencies** beyond `websockets`. No framework, no ORM â€” just the standard library and straightforward async Python.

This keeps the project easy to inspect, run locally, and adapt for experiments in multiplayer game architecture.

---

## Project Structure

```
mudproto/
â”œâ”€â”€ ARCHITECTURE.md                  # Full technical architecture doc
â”œâ”€â”€ mudproto_client/
â”‚   â””â”€â”€ client.py                    # Generic WebSocket terminal client
â”œâ”€â”€ mudproto_client_gui/
â”‚   â””â”€â”€ client_gui.py                # Optional GUI client
â”‚
â”œâ”€â”€ mudproto_server/
â”‚   â”œâ”€â”€ core_logic/
â”‚   â”‚   â”œâ”€â”€ server.py                # Entry point and websocket orchestration
â”‚   â”‚   â”œâ”€â”€ server_loops.py          # Tick loops and combat round scheduling
â”‚   â”‚   â”œâ”€â”€ protocol.py              # Envelope construction & validation
â”‚   â”‚   â”œâ”€â”€ models.py                # Core session/combat/item/entity dataclasses
â”‚   â”‚   â”œâ”€â”€ commands.py              # Message dispatch and command routing
â”‚   â”‚   â”œâ”€â”€ command_handlers/        # Auth/world/social/combat command handlers
â”‚   â”‚   â”œâ”€â”€ combat.py                # Combat round resolution
â”‚   â”‚   â”œâ”€â”€ combat_player_abilities.py
â”‚   â”‚   â”œâ”€â”€ combat_state.py
â”‚   â”‚   â”œâ”€â”€ targeting_follow.py      # Follow/watch/group helpers
â”‚   â”‚   â”œâ”€â”€ display_feedback.py      # Prompt/result feedback builders
â”‚   â”‚   â”œâ”€â”€ assets.py                # Asset loaders + validation
â”‚   â”‚   â”œâ”€â”€ player_state_db.py       # SQLite persistence layer
â”‚   â”‚   â””â”€â”€ ...
â”‚   â””â”€â”€ configuration/
â”‚       â”œâ”€â”€ server/settings.json     # Network, timing, combat, gameplay
â”‚       â”œâ”€â”€ assets/                  # gear, items, npcs, rooms, zones, spells, skills
â”‚       â””â”€â”€ attributes/              # classes, attributes, regen, scaling, experience
â”‚
â””â”€â”€ README.md                        # You are here
```

**Modular Python server Â· terminal + GUI clients Â· JSON-driven game data**

---

## Adding or Extending Game Content

Most of MudProtoâ€™s playable content is **data-driven**. Rooms, NPCs, gear, consumables, spells, skills, and zones are defined under `mudproto_server/configuration/assets/`, which makes it straightforward to expand the world without reworking the core engine.

A typical content pass looks like this:

1. Add or update templates in `gear.json`, `items.json`, `spells.json`, or `skills.json`.
2. Reference them from `npcs.json`.
3. Place those NPCs in `rooms.json` and connect the area through `zones.json`.
4. Restart the server and smoke-test key commands like `look`, `scan`, `buy`, `cast`, or combat actions.

For the full schema, validation rules, naming conventions, and asset-authoring workflow, see [`ASSET_GENERATION.md`](ASSET_GENERATION.md).

---

## Why This Project Stands Out

- **Server-authoritative gameplay** â€” commands, combat resolution, cooldowns, and messaging all live on the server.
- **Data-driven content** â€” rooms, NPCs, spells, skills, items, and progression are defined in JSON for easy iteration.
- **Thin clients, stable protocol** â€” the same message format powers both the terminal and GUI clients.
- **Small, readable systems** â€” the codebase is organized into focused modules so mechanics can be extended without losing clarity.
- **Classic fantasy tone** â€” the project keeps a bit of dungeon-crawl character without losing technical clarity.

---

MudProto aims to preserve the spirit of classic tabletop-inspired fantasy while remaining practical to run, read, and extend.

<div align="center">

*Roll for initiative.* ðŸŽ²

</div>
