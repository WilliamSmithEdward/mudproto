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
    log_login_event,
    normalize_character_name,
    verify_character_credentials,
)
from session_lifecycle import complete_login
from session_timing import apply_lag

OutboundResult = dict[str, object] | list[dict[str, object]]

FAILED_PASSWORD_LAG_SECONDS = 3.0
MAX_FAILED_PASSWORD_ATTEMPTS = 3


def _fail_password_attempt(
    session: ClientSession,
    *,
    character_name: str,
    failure_reason: str,
    user_message: str,
) -> OutboundResult:
    session.failed_password_attempts += 1
    apply_lag(session, FAILED_PASSWORD_LAG_SECONDS)
    log_login_event(
        session,
        event_type="password_attempt",
        success=False,
        character_name=character_name,
        character_key=character_name.strip().lower(),
        failure_reason=failure_reason,
    )

    if session.failed_password_attempts >= MAX_FAILED_PASSWORD_ATTEMPTS:
        session.disconnected_by_server = True
        session.is_connected = False
        session.pending_character_name = ""
        session.pending_password = ""
        session.pending_gender = ""
        return display_error("Too many failed password attempts. Connection closed.", session)

    return display_error(user_message, session)


def process_auth_input(session: ClientSession, input_text: str) -> OutboundResult:
    lowered = input_text.strip().lower()

    if session.auth_stage == "awaiting_character_or_start":
        if lowered == "start":
            log_login_event(session, event_type="character_creation_start", success=True)
            return start_character_creation(session)

        normalized_name = normalize_character_name(input_text)
        if normalized_name is None:
            log_login_event(
                session,
                event_type="character_lookup",
                success=False,
                character_name=input_text,
                failure_reason="invalid_character_name",
            )
            return display_error("Character names must contain letters only.", session)

        character_record = get_character_by_name(normalized_name)
        if character_record is None:
            log_login_event(
                session,
                event_type="character_lookup",
                success=False,
                character_name=normalized_name,
                character_key=normalized_name.lower(),
                failure_reason="character_not_found",
            )
            return display_error(f"Character '{normalized_name}' does not exist.", session)

        session.pending_character_name = str(character_record.get("character_name", normalized_name))
        session.auth_stage = "awaiting_existing_password"
        log_login_event(
            session,
            event_type="character_lookup",
            success=True,
            character_name=session.pending_character_name,
            character_key=str(character_record.get("character_key", normalized_name.lower())),
        )
        return build_existing_password_prompt(session)

    if session.auth_stage == "awaiting_existing_password":
        character_name = session.pending_character_name.strip()
        if not input_text.strip():
            return _fail_password_attempt(
                session,
                character_name=character_name,
                failure_reason="empty_password",
                user_message="Password cannot be empty.",
            )

        character_record = verify_character_credentials(character_name, input_text)
        if character_record is None:
            return _fail_password_attempt(
                session,
                character_name=character_name,
                failure_reason="invalid_password",
                user_message="Invalid password.",
            )

        session.failed_password_attempts = 0
        log_login_event(
            session,
            event_type="password_attempt",
            success=True,
            character_name=str(character_record.get("character_name", character_name)),
            character_key=str(character_record.get("character_key", character_name.lower())),
        )
        response = complete_login(session, character_record, is_new_character=False)
        log_login_event(
            session,
            event_type="login_result",
            success=True,
            character_name=str(character_record.get("character_name", character_name)),
            character_key=str(character_record.get("character_key", character_name.lower())),
        )
        return response

    if is_character_creation_stage(session.auth_stage):
        return process_character_creation_input(
            session,
            input_text,
            complete_login=complete_login,
        )

    session.auth_stage = "awaiting_character_or_start"
    return initial_auth_prompt(session)
