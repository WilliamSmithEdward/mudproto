# MudProto web-first client direction

This document records the current product direction for player-facing client work.

## Current direction

- The browser client under mudproto_client_web is the single supported player client.
- The former desktop Python GUI was removed to avoid maintaining two different clients.
- New player-facing UX work should land in the web client.

## Web client expectations

These behaviors should stay stable unless there is a strong reason to change them:

- default server target
- reconnect timing
- server-driven semantic color rendering
- handling of structured display messages
- local #clear behavior
- local #quit behavior
- command history with Up and Down keys
- local settings and import or export flows

## Maintenance rule

When client-facing behavior changes, update the web client docs and tests in the same change.
