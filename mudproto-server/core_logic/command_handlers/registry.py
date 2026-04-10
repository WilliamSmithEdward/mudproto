from display_feedback import display_error, display_prompt
from models import ClientSession

from .character import handle_character_command
from .commerce import handle_commerce_command
from .equipment import handle_equipment_command, handle_item_use_command
from .loot import handle_loot_command
from .movement import handle_movement_command
from .observation import handle_observation_command
from .parsing import parse_command
from .skills import handle_skill_command, handle_skill_fallback_command
from .types import OutboundResult
from .social import handle_social_command
from .spells import handle_spell_command
from .world import handle_world_command


CommandResult = OutboundResult | None


def dispatch_command(session: ClientSession, command_text: str) -> OutboundResult:
    verb, args = parse_command(command_text)

    if not verb:
        return display_prompt(session)

    handlers = (
        handle_world_command,
        handle_observation_command,
        handle_loot_command,
        handle_character_command,
        handle_commerce_command,
        handle_spell_command,
        handle_skill_command,
        handle_equipment_command,
        handle_social_command,
        handle_movement_command,
        handle_item_use_command,
    )

    for handler in handlers:
        result: CommandResult = handler(session, verb, args, command_text)
        if result is not None:
            return result

    fallback_result = handle_skill_fallback_command(session, verb, args, command_text)
    if fallback_result is not None:
        return fallback_result

    return display_error(f"Unknown command: {verb}", session)
