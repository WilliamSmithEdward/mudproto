# MudProto

A server-authoritative multiplayer MUD built in Python.

Async WebSocket server, terminal and GUI clients, tabletop-inspired fantasy systems.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![WebSockets](https://img.shields.io/badge/WebSockets-async-4B8BBE)](https://websockets.readthedocs.io)
[![SQLite](https://img.shields.io/badge/SQLite-persistence-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)

![MudProto gameplay screenshot](/images/mudproto_01.png)

## Quick Start

```bash
# Clone
git clone https://github.com/WilliamSmithEdward/mudproto.git
cd mudproto

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Install dependency
pip install websockets

# Start server
python mudproto-server/core_logic/server.py

# Start terminal client (new terminal)
cd mudproto-client
python client.py

# Or GUI client (new terminal)
cd ..\mudproto-client-gui
python client_gui.py
```

First commands to try:

- start
- look
- score
- inventory
- scan

## Current Gameplay Highlights

### Combat and Abilities

- Multi-target room combat with shared round output.
- Skills and spells with round cooldowns and optional game-hour cooldowns.
- Timed and battle-round support effects.
- NPC ability usage with independent skill/spell cooldown tracking.
- Bash-style target lag now also forces target posture to sitting.

### Posture System

- Postures: standing, sitting, resting.
- Commands:
    - sit aliases: si, sit
    - rest aliases: r, re, res, rest
    - stand aliases: st, sta, stan, stand
- Sitting and resting can block movement using posture config flags.
- Posture damage multipliers are data-driven from posture config.
- Resting can apply regeneration bonus multipliers.
- Room look output shows posture for living NPCs and players.
- Score output shows current posture state.

### Social and Grouping

- Follow, watch, group flows.
- Swap command supports self/member and member/member reorder patterns.
- Follow/group behavior reconciles correctly on death and movement.

### Persistence and World

- SQLite-backed player persistence.
- Shared room state for NPCs, corpses, coin piles, and ground items.
- JSON-driven content for rooms, zones, NPCs, items, spells, skills, and attributes.

## Architecture

Clients send raw text commands. The server owns all game logic and returns structured display envelopes.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a deeper technical breakdown.

## AI Content Pipeline

MudProto supports LLM-assisted asset bundle generation.

Main entrypoint:

- mudproto-llm-interfaces/generate_asset_payload_generation_instructions.py

Generated instruction payload:

- mudproto-llm-interfaces/asset_payload_generation_instructions.json

Typical workflow:

1. Regenerate instruction payload.
2. Provide payload plus a content brief to an AI model.
3. Save returned JSON payload under mudproto-server/configuration/assets/asset-payloads/.
4. Restart server to load new content.

Full process details: [LLM_CONTENT_GENERATION.md](LLM_CONTENT_GENERATION.md).

## Project Layout

```text
mudproto/
|- ARCHITECTURE.md
|- ASSET_GENERATION.md
|- LLM_CONTENT_GENERATION.md
|- mudproto-client/
|  |- client.py
|- mudproto-client-gui/
|  |- client_gui.py
|- mudproto-llm-interfaces/
|  |- generate_asset_payload_generation_instructions.py
|  |- asset_payload_generation_instructions.json
|- mudproto-server/
|  |- configuration/
|  |  |- assets/
|  |  |- attributes/
|  |- core_logic/
|     |- server.py
|     |- command_handlers/
|     |- tests/
|- images/
|- README.md
```

## Development Notes

- Python version target: 3.12+
- Minimal runtime dependencies (websockets plus Python standard library)
- Core test suite lives under mudproto-server/core_logic/tests

Run tests:

```bash
cd mudproto-server/core_logic
python -m pytest
```

MudProto is designed to be practical to run, straightforward to read, and easy to extend.
