from models import ClientSession
from player_state_db import save_player_state


def handle_player_death(session: ClientSession) -> None:
    """Mark the player as dead and prepare the session for login-screen return.

    This function is the single authority for all on-death side effects.
    Call it whenever player HP reaches 0, regardless of cause.
    Any future logic (death penalties, respawn mechanics, cause tracking, etc.)
    should be added here.
    """
    from combat_state import end_combat

    end_combat(session)
    session.active_support_effects.clear()
    session.status.hit_points = 1
    save_player_state(session)
    session.pending_death_logout = True


def build_player_death_parts() -> list[dict]:
    """Return the display parts shown to the player who just died."""
    from display_core import build_part

    return [
        build_part("\n"),
        build_part("You are dead!\n", "bright_red", True),
    ]


def build_player_death_mourn_parts() -> list[dict]:
    """Return the mourn message display parts after player death."""
    from display_core import build_part

    return [
        build_part("Your comrades mourn your death.", "bright_white"),
    ]


def build_player_death_broadcast_parts(actor_name: str) -> list[dict]:
    """Return the room-broadcast parts shown to observers when a player dies."""
    from display_core import build_part

    return [
        build_part(f"{actor_name} is dead!", "bright_red", True),
    ]
