from .character_creation import (
    is_character_creation_stage,
    process_character_creation_input,
    start_character_creation,
)
from display_feedback import display_error
from display_prompts import build_existing_password_prompt, initial_auth_prompt, login_prompt
from models import ClientSession
from player_state_db import (
    get_character_by_name,
    normalize_character_name,
    verify_character_credentials,
)
from session_lifecycle import complete_login

OutboundResult = dict[str, object] | list[dict[str, object]]


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
        return build_existing_password_prompt(session)

    if session.auth_stage == "awaiting_existing_password":
        if not input_text.strip():
            return display_error("Password cannot be empty.", session)

        character_record = verify_character_credentials(session.pending_character_name, input_text)
        if character_record is None:
            return display_error("Invalid password.", session)

        return complete_login(session, character_record, is_new_character=False)

    if is_character_creation_stage(session.auth_stage):
        return process_character_creation_input(
            session,
            input_text,
            complete_login=complete_login,
        )

    session.auth_stage = "awaiting_character_or_start"
    return initial_auth_prompt(session)
