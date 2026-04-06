from combat import maybe_auto_engage_current_room
from .character_creation import (
    is_character_creation_stage,
    process_character_creation_input,
    start_character_creation,
)
from display import (
    build_line,
    build_part,
    display_command_result,
    display_error,
    display_prompt,
    display_room,
)
from grammar import normalize_player_gender
from models import ClientSession
from player_resources import clamp_player_resources_to_caps
from player_state_db import (
    get_character_by_name,
    load_player_state,
    normalize_character_name,
    save_player_state,
    verify_character_credentials,
)
from sessions import (
    apply_player_class,
    ensure_player_attributes,
    hydrate_session_from_active_character,
    register_authenticated_character_session,
)
from world import get_room

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]


def initial_auth_prompt(session: ClientSession) -> OutboundMessage:
    return display_command_result(session, [
        build_part("Enter an existing character name (letters only) or type ", "bright_white"),
        build_part("start", "bright_yellow", True),
        build_part(" to create a new character.", "bright_white"),
    ])


def login_prompt(session: ClientSession) -> OutboundMessage:
    """Minimal login prompt (bare "> ") for re-entry after death or other events."""
    return display_prompt(session)


def _build_auto_aggro_outbound(session: ClientSession, room_display: OutboundMessage) -> OutboundResult:
    maybe_auto_engage_current_room(session)
    return room_display


def _complete_login(session: ClientSession, character_record: dict, *, is_new_character: bool) -> OutboundResult:
    character_key = str(character_record.get("character_key", "")).strip()
    character_name = str(character_record.get("character_name", "")).strip()
    class_id = str(character_record.get("class_id", "")).strip()
    login_room_id = str(character_record.get("login_room_id", "")).strip() or "start"
    session.player.gender = normalize_player_gender(
        character_record.get("gender", session.player.gender),
        allow_unspecified=True,
    ) or "unspecified"

    session.player_state_key = character_key
    session.authenticated_character_name = character_name
    session.login_room_id = login_room_id
    session.pending_character_name = ""
    session.pending_password = ""
    session.pending_gender = ""

    resumed_from_active = hydrate_session_from_active_character(session, character_key)

    loaded_state = False
    if not resumed_from_active:
        loaded_state = load_player_state(session, player_key=character_key)
        if not loaded_state:
            apply_player_class(session, class_id, initialize_progression=True)
        elif class_id:
            session.player.class_id = class_id

        ensure_player_attributes(session)
        session.player.current_room_id = login_room_id
    else:
        ensure_player_attributes(session)

    clamp_player_resources_to_caps(session)

    session.is_authenticated = True
    session.is_connected = True
    session.disconnected_by_server = False
    session.auth_stage = "authenticated"
    register_authenticated_character_session(session)

    if (not resumed_from_active and not loaded_state) or is_new_character:
        save_player_state(session, player_key=character_key)

    login_room = get_room(session.player.current_room_id)
    if login_room is None:
        session.player.current_room_id = "start"
        login_room = get_room("start")

    if login_room is None:
        return display_error("Login room is not configured.", session)

    room_display = display_room(session, login_room)
    payload = room_display.get("payload") if isinstance(room_display, dict) else None
    if isinstance(payload, dict):
        lines = payload.get("lines")
        if isinstance(lines, list):
            greeting = "Character created" if is_new_character else "Welcome back"
            payload["lines"] = [
                build_line(
                    build_part(f"{greeting}, ", "bright_white"),
                    build_part(character_name, "bright_green", True),
                    build_part(".", "bright_white"),
                ),
                [],
            ] + lines

    return _build_auto_aggro_outbound(session, room_display)


def process_auth_input(session: ClientSession, input_text: str) -> OutboundResult:
    lowered = input_text.strip().lower()

    if session.auth_stage == "awaiting_character_or_start":
        if lowered == "start":
            return start_character_creation(session)

        normalized_name = normalize_character_name(input_text)
        if normalized_name is None:
            return display_error("Character names must contain letters only.", session)

        character_record = get_character_by_name(normalized_name)
        if character_record is None:
            return display_error(f"Character '{normalized_name}' does not exist.", session)

        session.pending_character_name = str(character_record.get("character_name", normalized_name))
        session.auth_stage = "awaiting_existing_password"
        return display_command_result(session, [
            build_part("Character found. Enter your password.", "bright_white"),
        ])

    if session.auth_stage == "awaiting_existing_password":
        if not input_text.strip():
            return display_error("Password cannot be empty.", session)

        character_record = verify_character_credentials(session.pending_character_name, input_text)
        if character_record is None:
            return display_error("Invalid password.", session)

        return _complete_login(session, character_record, is_new_character=False)

    if is_character_creation_stage(session.auth_stage):
        return process_character_creation_input(
            session,
            input_text,
            complete_login=_complete_login,
        )

    session.auth_stage = "awaiting_character_or_start"
    return initial_auth_prompt(session)
