# MudProto client differences

This folder tracks the places where the desktop Python client and the web client are intentionally different.

## Shared behavior that should stay aligned

These should match unless there is a very strong reason not to:

- default server target
- reconnect timing
- server-driven semantic color rendering
- handling of structured display messages
- local `#clear` behavior
- local `#quit` behavior
- command history with Up and Down keys

If any of those change, update both clients in the same pass and keep the parity tests passing.

## Current intentional differences

### Connection security
- The desktop Python client can relax certificate verification through its local configuration for development use.
- The web client follows normal browser security rules and depends on the browser trusting the server certificate.

### Windowing and layout
- The desktop Python client uses a native app window.
- The web client runs inside the browser and keeps its main output area scrollable inside the page.

### Connection controls
- The web client shows connect, disconnect, and server address controls in the page.
- The desktop Python client connects through its configured settings and native window flow.

### Platform behavior
- The desktop Python client includes Windows-specific DPI and focus handling.
- The web client follows browser focus and keyboard behavior.

## Maintenance rule

When a new difference is introduced between the clients, document it here in the same change.
