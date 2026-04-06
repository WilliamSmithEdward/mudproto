from collections.abc import Callable

from attribute_config import get_player_class_by_id, load_player_classes
from display_core import build_part
from display_feedback import display_command_result, display_error
from grammar import normalize_player_gender
from models import ClientSession
from player_state_db import character_exists, create_character, normalize_character_name

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]

CHARACTER_CREATION_STAGES = {
    "awaiting_new_character_name",
    "awaiting_new_character_password",
    "awaiting_new_character_gender",
    "awaiting_new_character_class",
}


def is_character_creation_stage(auth_stage: str) -> bool:
    return auth_stage.strip().lower() in CHARACTER_CREATION_STAGES


def start_character_creation(session: ClientSession) -> OutboundResult:
    session.pending_character_name = ""
    session.pending_password = ""
    session.pending_gender = ""
    session.auth_stage = "awaiting_new_character_name"
    return display_command_result(session, [
        build_part("Enter a new character name (letters only).", "bright_white"),
    ])


def _build_gender_prompt(session: ClientSession) -> OutboundMessage:
    return display_command_result(session, [
        build_part("Choose a gender: ", "bright_white"),
        build_part("male", "bright_cyan", True),
        build_part(" or ", "bright_white"),
        build_part("female", "bright_magenta", True),
        build_part(".", "bright_white"),
    ])


def _build_class_prompt(session: ClientSession) -> OutboundMessage:
    classes = load_player_classes()
    parts: list[dict] = [
        build_part("Choose a class by id or name:", "bright_white"),
    ]
    for player_class in classes:
        parts.extend([
            build_part("\n"),
            build_part(" - ", "bright_white"),
            build_part(str(player_class.get("class_id", "")), "bright_cyan", True),
            build_part(" (", "bright_white"),
            build_part(str(player_class.get("name", "")), "bright_yellow", True),
            build_part(")", "bright_white"),
        ])
    return display_command_result(session, parts)


def _resolve_class_selection(selection: str) -> dict | None:
    normalized = selection.strip().lower()
    if not normalized:
        return None

    by_id = get_player_class_by_id(normalized)
    if by_id is not None:
        return by_id

    for player_class in load_player_classes():
        if str(player_class.get("name", "")).strip().lower() == normalized:
            return player_class

    return None


def process_character_creation_input(
    session: ClientSession,
    input_text: str,
    *,
    complete_login: Callable[..., OutboundResult],
) -> OutboundResult:
    if session.auth_stage == "awaiting_new_character_name":
        normalized_name = normalize_character_name(input_text)
        if normalized_name is None:
            return display_error("Character names must contain letters only.", session)
        if character_exists(normalized_name):
            return display_error(f"Character '{normalized_name}' already exists.", session)

        session.pending_character_name = normalized_name
        session.pending_gender = ""
        session.auth_stage = "awaiting_new_character_password"
        return display_command_result(session, [
            build_part("Enter a password for your character.", "bright_white"),
        ])

    if session.auth_stage == "awaiting_new_character_password":
        if not input_text.strip():
            return display_error("Password cannot be empty.", session)

        session.pending_password = input_text
        session.auth_stage = "awaiting_new_character_gender"
        return _build_gender_prompt(session)

    if session.auth_stage == "awaiting_new_character_gender":
        selected_gender = normalize_player_gender(input_text, allow_unspecified=False)
        if selected_gender is None:
            return display_error("Choose male or female.", session)

        session.pending_gender = selected_gender
        session.auth_stage = "awaiting_new_character_class"
        return _build_class_prompt(session)

    if session.auth_stage == "awaiting_new_character_class":
        selected_class = _resolve_class_selection(input_text)
        if selected_class is None:
            return display_error("Unknown class selection.", session)

        created = create_character(
            character_name=session.pending_character_name,
            password=session.pending_password,
            class_id=str(selected_class.get("class_id", "")).strip(),
            gender=session.pending_gender,
            login_room_id="start",
        )
        return complete_login(session, created, is_new_character=True)

    session.auth_stage = "awaiting_character_or_start"
    return display_error("Character creation has been reset. Type start to begin again.", session)
