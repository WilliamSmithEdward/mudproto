# MudProto Architecture

## Core Boundary

MudProto uses a strict client/server separation of concerns.

### Client responsibilities
The client is generic. It should not contain game-specific logic.

The client is responsible for:
- opening and maintaining the websocket connection
- sending generic user input messages to the server
- rendering generic display messages from the server
- local terminal behavior such as:
  - ANSI color rendering
  - bold text rendering
  - prompt display
  - local-only commands like `/quit`

The client must not:
- know game command semantics
- interpret game mechanics
- decide how gameplay text should be composed
- embed rules for room descriptions, combat, lag, or queue behavior

### Server responsibilities
The server is the sole owner of game meaning.

The server is responsible for:
- validating protocol envelopes
- interpreting generic client input
- parsing commands
- applying gameplay rules
- enforcing lag
- queueing commands during lag
- generating display/output instructions for the client
- managing connection/session state

## Invariants

- Lag is enforced server-side.
- Lag blocks command execution, not outbound server messages.
- Commands received during lag are queued per session.
- Command queues are FIFO per session.
- The client is generic and does not contain game-specific rendering rules.
- The server sends display/output instructions to the client.
- The server is the sole owner of input interpretation.
- The client sends generic user input, not game-specific protocol messages.

## Current Client-to-Server Contract

Client sends generic input messages:

- `type = "input"`
- `payload.text = "<raw user input>"`

Example:

```json
{
  "type": "input",
  "source": "mudproto-client",
  "timestamp": "2026-03-28T12:34:56Z",
  "payload": {
    "text": "look"
  }
}