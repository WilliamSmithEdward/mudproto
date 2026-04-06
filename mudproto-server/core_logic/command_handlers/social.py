from commands import OutboundResult
from display_core import build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from targeting_follow import (
    _clear_follow_state,
    _find_followed_player_session,
    _resolve_room_player_selector,
    _would_create_follow_loop,
)


HandledResult = OutboundResult | None


def handle_social_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in {"follow", "fol", "foll", "follo", "unfollow"}:
        selector_text = " ".join(args).strip()
        if verb == "unfollow":
            selector_text = "off"

        if not selector_text:
            followed_session = _find_followed_player_session(session)
            if followed_session is None and not session.following_player_key.strip():
                return display_error("Usage: follow <player> or follow off.", session)

            followed_name = session.following_player_name.strip() or "someone"
            if followed_session is not None:
                followed_name = (followed_session.authenticated_character_name or "").strip() or followed_name

            return display_command_result(session, [
                build_part("You are following ", "bright_white"),
                build_part(followed_name, "bright_cyan", True),
                build_part(".", "bright_white"),
            ])

        if selector_text.lower() in {"off", "stop", "none", "cancel", "clear"}:
            if not session.following_player_key.strip():
                return display_error("You are not following anyone.", session)

            followed_name = session.following_player_name.strip() or "them"
            _clear_follow_state(session)
            return display_command_result(session, [
                build_part("You stop following ", "bright_white"),
                build_part(followed_name, "bright_cyan", True),
                build_part(".", "bright_white"),
            ])

        if session.combat.engaged_entity_ids:
            return display_error("You cannot start following while engaged in combat.", session)

        target_session, target_error = _resolve_room_player_selector(session, selector_text)
        if target_session is None:
            return display_error(target_error or f"No player named '{selector_text}' is here.", session)
        if target_session.client_id == session.client_id:
            return display_error("You cannot follow yourself.", session)
        if _would_create_follow_loop(session, target_session):
            return display_error("You cannot create a follow loop.", session)

        target_key = (target_session.player_state_key or target_session.client_id).strip()
        target_name = (target_session.authenticated_character_name or "").strip() or "Unknown"
        if session.following_player_key.strip().lower() == target_key.lower():
            return display_error(f"You are already following {target_name}.", session)

        session.following_player_key = target_key
        session.following_player_name = target_name
        return display_command_result(session, [
            build_part("You start following ", "bright_white"),
            build_part(target_name, "bright_cyan", True),
            build_part(".", "bright_white"),
        ])

    if verb == "say":
        spoken_text = " ".join(args).strip()
        if not spoken_text:
            return display_error("Usage: say <text>", session)

        return display_command_result(session, [
            build_part("You say, ", "bright_white"),
            build_part(f'"{spoken_text}"', "bright_magenta", True),
        ])

    return None
