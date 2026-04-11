<div align="center">

# ⚔️ MudProto

**A server-authoritative multiplayer MUD built in Python.**

*Async WebSocket server · Terminal and GUI clients · Tabletop-inspired fantasy systems*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![WebSockets](https://img.shields.io/badge/WebSockets-async-4B8BBE)](https://websockets.readthedocs.io)
[![SQLite](https://img.shields.io/badge/SQLite-persistence-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)

</div>

![MudProto gameplay screenshot](/images/mudproto_01.png)

> 🤖 **Development note:** MudProto actively uses **agentic AI workflows** for content generation, documentation, schema-guided authoring, and iteration alongside normal hand-written development.

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
python mudproto-server/core_logic/server.py

# In a second terminal — connect a client
cd mudproto-client
python client.py

# Or launch the GUI client
cd ..\mudproto-client-gui
python client_gui.py
```

Type `start` to create a character and choose a class. Good first commands are `look` and `inventory`. In the south market you can `buy potion`; in the northern hall you can `attack scout`, `jab scout`, and `flee`.

---

## 🤖 AI Content Generation

MudProto can also take **LLM-generated content bundles** through the `asset-payloads` pipeline. The intended workflow starts from the generator script:

- `mudproto-llm-interfaces/generate_asset_payload_generation_instructions.py`

That script regenerates:

- `mudproto-llm-interfaces/asset_payload_generation_instructions.json`

which is the instruction payload you hand to an AI model when asking it to generate new game content.

### Quick workflow
1. Run or reference `mudproto-llm-interfaces/generate_asset_payload_generation_instructions.py` to produce the latest instruction JSON.
2. Give the resulting `asset_payload_generation_instructions.json` to your AI model along with your content brief.
3. Make sure the model returns a **downloadable `.json` file** — not Markdown-wrapped output.
4. Save that file into `mudproto-server/configuration/assets/asset-payloads/`.
5. Restart the server to load the new payload.

For the full process, merge rules, override behavior, caveats, and review checklist, see [`LLM_CONTENT_GENERATION.md`](LLM_CONTENT_GENERATION.md).

---

## Overview

MudProto is a modern take on the classic **Multi-User Dungeon**: a shared fantasy world with real-time combat, spells, skills, merchants, and persistent characters. Content and progression are driven by JSON, while the server remains the source of truth for every rule, roll, and result.

Built as both a playable game and a systems-focused codebase, MudProto emphasizes readable architecture, server-authoritative gameplay, and an extensible content pipeline that is easy to iterate on.

---

## Highlights

### 🗡️ Combat Engine
- **Multi-NPC engagement** — fight several enemies at once, each retaliating independently.
- **Room-round consolidation** — all players in a room see a unified, chronological combat log each round.
- **Opening-round initiative** — the opener acts before the first full exchange, with off-hand attacks held back during that opening moment.
- **Selective spell engagement** — offensive spell casts only enroll the caster in combat against non-engaged targets; already-engaged targets can still be damaged without pulling the caster in.
- **Configurable damage severity messaging** — attack text uses threshold-based tiers from `miss` and `barely` up through `massacre`, `annihilate`, and `obliterate`.
- **Flee with uncertainty** — escaping is possible, but never guaranteed.

### 🧙 Spells & Skills
- **Mana-based spells** — targeted damage, AoE, self-heal, vigor restore, mana restore.
- **Vigor-based skills** — attribute-scaled damage and support, with per-skill cooldowns.
- **Support effects** — instant, timed (game hours), or combat-round durations.
- **Step-scaled support tuning** — skills can scale support effects by level steps using `support_level_step` and `support_amount_per_level_step`.
- **Game-hour skill cooldowns** — support/damage skills can use `cooldown_hours`, and these persist across full disconnect/reconnect.
- **NPC AI** — enemies can use both skills and spells with independent cooldown tracking.

### 👥 Social Systems
- **Follow + watch targeting** — players can follow allies and watch a nearby player's status from the prompt.
- **Group management** — `group`, `group form`, `group <player>`, `ungroup <player>`, and `group disband` are supported.
- **Death-aware follow behavior** — follower/group relationships are reconciled when a leader dies (group disbands, follow retargeting rules applied).

### 🎒 Unified Item System
- **Single `ItemState` model** — no split between "inventory items" and "equipment items." Every item carries an intrinsic `equippable` flag hydrated from gear templates.
- **Flexible wear slots** — armor can be worn in primary or alternate slots (e.g., rings → left or right hand).
- **Hand weight limits** — weapon wielding / holding gated by STR via configurable thresholds.
- **Color-coded display** — equippable items appear in **magenta** and consumables in **yellow**, consistently across the UI.

### 🌍 Persistent World
- **Data-driven rooms** — exits, NPC spawns, and descriptions all defined in JSON.
- **Shared world state** — entities, corpses, ground items, and coin piles visible to all connected players.
- **Aggro NPCs** — auto-engage on room entry.
- **Corpse loot** — defeated enemies drop gear and coins for any player to claim.

### 💾 Character Persistence
- **SQLite-backed** — full character state serialized/deserialized on login/logout and every game hour (60 seconds by default).
- **Offline processing** — disconnected characters auto-flee combat, regenerate, and gracefully disconnect after 5 safe hours.
- **Seamless reconnect** — resume an active session mid-combat with full state hydration.

### 🖥️ Clients
- **Terminal client** — ANSI-rendered output with a compact, readable prompt.
- **GUI client** — a Tk-based interface that consumes the same server protocol.
- **Shared protocol** — both clients stay thin; all game logic remains server-side.
- **Queue feedback** — lag-blocked commands are queued cleanly and the prompt returns when ready.

---

## Architecture at a Glance

```
┌──────────────────────┐         WebSocket          ┌─────────────────────────┐
│       Clients        │◄──────────────────────────►│     Game Server         │
│                      │   JSON envelopes           │                         │
│  • ANSI / Tk render  │   { type, source,          │  • Command parsing      │
│  • Raw input send    │     timestamp, payload }   │  • Combat resolution    │
│  • Prompt display    │                            │  • Spell / skill engine │
│  • /quit             │                            │  • Persistence (SQLite) │
└──────────────────────┘                            │  • Tick systems         │
                                                    │  • Room broadcasts      │
                                                    └─────────────────────────┘
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

**Minimal dependencies** beyond `websockets`. No framework, no ORM — just the standard library and straightforward async Python.

This keeps the project easy to inspect, run locally, and adapt for experiments in multiplayer game architecture.

---

## Project Structure

```
mudproto/
├── ARCHITECTURE.md                  # Full technical architecture doc
├── mudproto-client/
│   └── client.py                    # Generic WebSocket terminal client
├── mudproto-client-gui/
│   └── client_gui.py                # Optional GUI client
│
├── mudproto-server/
│   ├── core_logic/
│   │   ├── server.py                # Entry point and websocket orchestration
│   │   ├── server_loops.py          # Tick loops and combat round scheduling
│   │   ├── protocol.py              # Envelope construction & validation
│   │   ├── models.py                # Core session/combat/item/entity dataclasses
│   │   ├── commands.py              # Message dispatch and command routing
│   │   ├── command_handlers/        # Auth/world/social/combat command handlers
│   │   ├── combat.py                # Combat round resolution
│   │   ├── combat_player_abilities.py
│   │   ├── combat_state.py
│   │   ├── targeting_follow.py      # Follow/watch/group helpers
│   │   ├── display_feedback.py      # Prompt/result feedback builders
│   │   ├── assets.py                # Asset loaders + validation
│   │   ├── player_state_db.py       # SQLite persistence layer
│   │   └── ...
│   └── configuration/
│       ├── server/settings.json     # Network, timing, combat, gameplay
│       ├── assets/                  # gear, items, npcs, rooms, zones, spells, skills
│       └── attributes/              # classes, attributes, regen, scaling, experience
│
└── README.md                        # You are here
```

**Modular Python server · terminal + GUI clients · JSON-driven game data**

---

## Adding or Extending Game Content

Most of MudProto’s playable content is **data-driven**. Rooms, NPCs, gear, consumables, spells, skills, and zones are defined under `mudproto-server/configuration/assets/`, which makes it straightforward to expand the world without reworking the core engine.

A typical content pass looks like this:

1. Add or update templates in `gear.json`, `items.json`, `spells.json`, or `skills.json`.
2. Reference them from `npcs.json`.
3. Place those NPCs in `rooms.json` and connect the area through `zones.json`.
4. Restart the server and smoke-test key commands like `look`, `scan`, `buy`, `cast`, or combat actions.

For the full schema, validation rules, naming conventions, and asset-authoring workflow, see [`ASSET_GENERATION.md`](ASSET_GENERATION.md).

---

## Why This Project Stands Out

- **Server-authoritative gameplay** — commands, combat resolution, cooldowns, and messaging all live on the server.
- **Data-driven content** — rooms, NPCs, spells, skills, items, and progression are defined in JSON for easy iteration.
- **Thin clients, stable protocol** — the same message format powers both the terminal and GUI clients.
- **Small, readable systems** — the codebase is organized into focused modules so mechanics can be extended without losing clarity.
- **Classic fantasy tone** — the project keeps a bit of dungeon-crawl character without losing technical clarity.

---

MudProto aims to preserve the spirit of classic tabletop-inspired fantasy while remaining practical to run, read, and extend.

<div align="center">

*Roll for initiative.* 🎲

</div>