"""Compatibility facade for session helpers.

`session_registry.py`, `session_timing.py`, `session_bootstrap.py`, and
`session_lifecycle.py` own the concrete session responsibilities. This module
remains as a stable import surface for any older callers that still import from
`sessions`.
"""

from session_bootstrap import apply_player_class, ensure_player_attributes
from session_lifecycle import (
    handle_client_disconnect,
    hydrate_session_from_active_character,
    register_authenticated_character_session,
    reset_session_to_login,
    start_offline_character_processing,
    stop_offline_character_processing,
)
from session_registry import (
    active_character_sessions,
    attach_session_to_shared_world,
    connected_clients,
    get_active_character_session,
    get_connection_count,
    list_authenticated_room_players,
    offline_character_tasks,
    register_client,
    shared_world_corpses,
    shared_world_entities,
    shared_world_room_coin_piles,
    shared_world_room_ground_items,
    unregister_client,
)
from session_timing import (
    apply_lag,
    enqueue_command,
    get_remaining_lag_seconds,
    is_session_lagged,
    touch_session,
)

__all__ = [
    "active_character_sessions",
    "apply_lag",
    "apply_player_class",
    "attach_session_to_shared_world",
    "connected_clients",
    "enqueue_command",
    "ensure_player_attributes",
    "get_active_character_session",
    "get_connection_count",
    "get_remaining_lag_seconds",
    "handle_client_disconnect",
    "hydrate_session_from_active_character",
    "is_session_lagged",
    "list_authenticated_room_players",
    "offline_character_tasks",
    "register_authenticated_character_session",
    "register_client",
    "reset_session_to_login",
    "shared_world_corpses",
    "shared_world_entities",
    "shared_world_room_coin_piles",
    "shared_world_room_ground_items",
    "start_offline_character_processing",
    "stop_offline_character_processing",
    "touch_session",
    "unregister_client",
]