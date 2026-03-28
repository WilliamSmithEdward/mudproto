# MudProto Server Architecture

## Invariants

- Lag is enforced server-side.
- Lag blocks command execution, not outbound server messages.
- Commands received during lag are queued per session.
- The client is generic and should not contain game-specific rendering rules.
- The server sends display/output instructions to the client.
- The client renders generic display parts like text, color, and boldness.

## Current Display Contract

Server-to-client display messages use:

- `type = "display"`
- `payload.parts = [{ text, fg, bold }]`
- `payload.blank_lines_before`
- `payload.prompt_after`

## Current Runtime Model

- One `ClientSession` per connected socket
- Per-session lag timer
- Per-session FIFO command queue
- Scheduler loop drains queued commands when lag clears

## Current Command Set

- `look`
- `wait`
- `heavy`
- `say`

## File Responsibilities

- `models.py` = dataclasses
- `protocol.py` = envelope and validation
- `sessions.py` = connection registry and lag/queue state
- `display.py` = server-side display composition
- `commands.py` = command parsing and execution
- `server.py` = websocket server and scheduler wiring