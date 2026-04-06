import asyncio

from models import ClientSession

connected_clients: dict[str, ClientSession] = {}
active_character_sessions: dict[str, ClientSession] = {}
offline_character_tasks: dict[str, asyncio.Task] = {}

# Shared runtime world state across all connected characters.
shared_world_entities: dict = {}
shared_world_corpses: dict = {}
shared_world_room_coin_piles: dict[str, int] = {}
shared_world_room_ground_items: dict[str, dict] = {}


def get_connection_count() -> int:
    return sum(1 for session in connected_clients.values() if session.is_connected)


def list_authenticated_room_players(room_id: str, *, exclude_client_id: str | None = None) -> list[ClientSession]:
    normalized_room_id = room_id.strip()
    if not normalized_room_id:
        return []

    players: list[ClientSession] = []
    for session in connected_clients.values():
        if not session.is_connected or session.disconnected_by_server or not session.is_authenticated:
            continue
        if exclude_client_id is not None and session.client_id == exclude_client_id:
            continue
        if session.player.current_room_id != normalized_room_id:
            continue
        players.append(session)

    players.sort(key=lambda player_session: player_session.authenticated_character_name.lower())
    return players


def attach_session_to_shared_world(session: ClientSession) -> None:
    session.entities = shared_world_entities
    session.corpses = shared_world_corpses
    session.room_coin_piles = shared_world_room_coin_piles
    session.room_ground_items = shared_world_room_ground_items


def register_client(client_id: str, websocket) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(
        client_id=client_id,
        websocket=websocket,
        connected_at=utc_now_iso()
    )
    attach_session_to_shared_world(session)
    session.is_connected = True
    connected_clients[client_id] = session
    return session


def unregister_client(client_id: str) -> None:
    connected_clients.pop(client_id, None)


def get_active_character_session(character_key: str) -> ClientSession | None:
    normalized_key = character_key.strip().lower()
    if not normalized_key:
        return None
    return active_character_sessions.get(normalized_key)
