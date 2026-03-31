<div align="center">

# ⚔️ MudProto

**A real-time multiplayer MUD engine built from scratch in Python.**

*Async WebSocket server · Rich terminal client · Data-driven world*

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![WebSockets](https://img.shields.io/badge/WebSockets-async-4B8BBE)](https://websockets.readthedocs.io)
[![SQLite](https://img.shields.io/badge/SQLite-persistence-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Lines of Code](https://img.shields.io/badge/Lines_of_Code-7%2C600+-brightgreen)]()

</div>

\
![Alt text](/images/mudproto_01.png)

---

## The Pitch

MudProto is a ground-up implementation of a **Multi-User Dungeon** — the genre that paved the way from tabletop RPGs to modern MMOs. It features real-time combat with multi-NPC engagement, a data-driven spell and skill system, persistent characters, and a rich ANSI terminal client — all running over a lightweight async WebSocket protocol.

> **Built with agentic AI workflows.** MudProto was designed, architected, and developed using an AI-assisted engineering process — leveraging autonomous coding agents for implementation, refactoring, architectural audits, and iterative design. The project demonstrates how a single developer can ship a complex, systems-heavy codebase at velocity by treating AI as a full development partner.

---

## Features

### 🗡️ Combat Engine
- **Multi-NPC engagement** — fight several enemies at once, each retaliating independently.
- **Room-round consolidation** — all players in a room see a unified, chronological combat log each round.
- **Opening-round mechanics** — first-strike advantage with half-strength opener and full retaliation.
- **Damage severity tiers** — *barely grazes* through *obliterates*, scaled to target max HP.
- **Flee with risk** — 50% success chance; failure means another round of punishment.

### 🧙 Spells & Skills
- **Mana-based spells** — targeted damage, AoE, self-heal, vigor restore, mana restore.
- **Vigor-based skills** — attribute-scaled damage and support, with per-skill cooldowns.
- **Support effects** — instant, timed (game hours), or combat-round durations.
- **NPC AI** — enemies use skills probabilistically with independent cooldown tracking.

### 🎒 Unified Item System
- **Single `ItemState` model** — no split between "inventory items" and "equipment items." Every item carries an intrinsic `equippable` flag hydrated from gear templates.
- **Flexible wear slots** — armor can be worn in primary or alternate slots (e.g., rings → left or right hand).
- **Hand weight limits** — weapon wielding / holding gated by STR via configurable thresholds.
- **Color-coded display** — equippable items in **magenta**, consumables in **cyan**, consistent everywhere.

### 🌍 Persistent World
- **Data-driven rooms** — exits, NPC spawns, and descriptions all defined in JSON.
- **Shared world state** — entities, corpses, ground items, and coin piles visible to all connected players.
- **Aggro NPCs** — auto-engage on room entry.
- **Corpse loot** — defeated enemies drop gear and coins for any player to claim.

### 💾 Character Persistence
- **SQLite-backed** — full character state serialized/deserialized on login/logout and every game hour (60 seconds by default).
- **Offline processing** — disconnected characters auto-flee combat, regenerate, and gracefully disconnect after 5 safe hours.
- **Seamless reconnect** — resume an active session mid-combat with full state hydration.

### 🖥️ Terminal Client
- **Generic renderer** — zero game logic; renders structured display parts with ANSI color and bold.
- **Dynamic prompt** — color-coded HP/vigor/mana, coins, engaged enemy condition, room exits.
- **Queue feedback** — lag-blocked commands silently queued; prompt reappears when lag expires.

---

## Architecture at a Glance

```
┌──────────────────────┐         WebSocket          ┌─────────────────────────┐
│   Terminal Client    │◄──────────────────────────►│     Game Server         │
│                      │   JSON envelopes           │                         │
│  • ANSI rendering    │   { type, source,          │  • Command parsing      │
│  • Raw input send    │     timestamp, payload }   │  • Combat resolution    │
│  • Prompt display    │                            │  • Spell / skill engine │
│  • /quit             │                            │  • Persistence (SQLite) │
└──────────────────────┘                            │  • Tick systems         │
                                                    │  • Room broadcasts      │
                                                    └─────────────────────────┘
```

The **client sends raw text**; the **server sends structured display instructions**. All game meaning lives server-side. See [`ARCHITECTURE.md`](mudproto-server/ARCHITECTURE.md) for the full technical deep-dive.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, `asyncio` |
| Networking | `websockets` (async server + client) |
| Persistence | SQLite 3 via `sqlite3` stdlib |
| Configuration | JSON asset files with eager validation |
| Client rendering | ANSI escape codes (no curses dependency) |

**Zero external server dependencies** beyond `websockets`. No ORM, no framework — just the standard library and clean async Python.

---

## Project Structure

```
mudproto/
├── mudproto-client/
│   └── client.py                    # Generic WebSocket terminal client
│
├── mudproto-server/
│   ├── server.py                    # Entry point, tick loops, room broadcasts
│   ├── protocol.py                  # Envelope construction & validation
│   ├── models.py                    # Core dataclasses (19 models)
│   ├── settings.py                  # Typed config from settings.json
│   ├── sessions.py                  # Session lifecycle & registry
│   ├── commands.py                  # All player commands & auth flow
│   ├── combat.py                    # Combat resolution & entity management
│   ├── combat_text.py               # Damage severity message templates
│   ├── damage.py                    # Hit chance & damage math
│   ├── equipment.py                 # Equip / wear / unequip mechanics
│   ├── inventory.py                 # Item selectors & template hydration
│   ├── display.py                   # Display builders (room, prompt, etc.)
│   ├── grammar.py                   # NLP transforms (articles, 3rd person)
│   ├── assets.py                    # JSON loaders with cross-ref validation
│   ├── player_state_db.py           # SQLite persistence layer
│   ├── world.py                     # Room model
│   ├── battle_round_ticks.py        # Per-round support effect processing
│   ├── game_hour_ticks.py           # Regen & timed support processing
│   ├── ARCHITECTURE.md              # Full technical architecture doc
│   └── configuration/
│       ├── server/settings.json     # Network, timing, combat, gameplay
│       ├── assets/                  # gear, items, npcs, rooms, spells, skills
│       └── attributes/              # classes, character attrs, wear slots, regen
│
└── README.md                        # You are here
```

**18 server modules · ~7,600 lines of Python · 12 JSON config files**

---

## Quick Start

```bash
# Clone
git clone https://github.com/YourUsername/mudproto.git
cd mudproto

# Set up environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install websockets

# Start the server
cd mudproto-server
python server.py

# In a second terminal — connect a client
cd mudproto-client
python client.py
```

Type `start` to create a character, pick a class, and you're in. Try `look`, `jab`, `inventory`, `cast 'Healing Light'`, or `flee` if things get dicey.

---

## Design Philosophy

**Server is king.** The client is a generic terminal — it doesn't know what a sword is. Every command, every damage roll, every color choice is decided server-side and sent as structured display instructions. This makes the protocol extensible to any future client (web, mobile, GUI) without touching game logic.

**Data over code.** Rooms, NPCs, spells, skills, gear, classes, and attributes are all defined in JSON. Adding a new sword or spell is a config change, not a code change.

**Agentic development.** This project was built using AI-powered development workflows — from initial architecture decisions through multi-module refactors, gameplay audits, and documentation. The codebase reflects a tight feedback loop between human design intent and AI implementation velocity.

---

## Developed With Agentic AI

MudProto is a case study in **human + AI collaborative engineering**:

- **Architecture & design** — high-level system design driven by human vision, refined through AI-assisted exploration of trade-offs.
- **Implementation** — modules built and iterated with autonomous coding agents handling boilerplate, cross-module consistency, and mechanical refactors.
- **Refactoring at scale** — multi-file renames, model unifications, and deprecation sweeps executed by agents with human review.
- **Quality assurance** — gameplay audits, runtime smoke tests, and static analysis performed by agents to validate end-to-end correctness after every change.
- **Documentation** — architecture docs and this README generated from live codebase analysis, not guesswork.

The result: a complex, multi-system game engine developed and iterated at a pace that would typically require a team — delivered by one developer with the right tools.

---

<div align="center">

*Roll for initiative.* 🎲

</div>
