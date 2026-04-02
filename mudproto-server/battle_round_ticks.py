import asyncio
import random

from models import ClientSession
from player_resources import get_player_resource_caps
from settings import COMBAT_ROUND_INTERVAL_SECONDS


def _roll_support_effect_amount(effect) -> int:
    total = int(effect.support_amount) + int(effect.support_roll_modifier) + int(effect.support_scaling_bonus)
    dice_count = max(0, int(effect.support_dice_count))
    dice_sides = max(0, int(effect.support_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        total += sum(random.randint(1, dice_sides) for _ in range(dice_count))
    return max(0, total)


def process_battle_round_support_effects(session: ClientSession) -> None:
    caps = get_player_resource_caps(session)
    for effect in list(session.active_support_effects):
        if effect.support_mode != "battle_rounds":
            continue

        applied_amount = _roll_support_effect_amount(effect)
        if applied_amount <= 0:
            effect.remaining_rounds -= 1
            if effect.remaining_rounds <= 0:
                session.active_support_effects.remove(effect)
            continue

        if effect.support_effect == "heal":
            session.status.hit_points = min(caps["hit_points"], session.status.hit_points + applied_amount)
        elif effect.support_effect == "vigor":
            session.status.vigor = min(caps["vigor"], session.status.vigor + applied_amount)
        elif effect.support_effect == "mana":
            session.status.mana = min(caps["mana"], session.status.mana + applied_amount)

        effect.remaining_rounds -= 1
        if effect.remaining_rounds <= 0:
            session.active_support_effects.remove(effect)


def process_non_combat_support_round(session: ClientSession) -> bool:
    from combat import get_engaged_entity

    has_battle_round_effect = any(effect.support_mode == "battle_rounds" for effect in session.active_support_effects)
    if not has_battle_round_effect:
        session.next_non_combat_support_round_monotonic = None
        return False

    if get_engaged_entity(session) is not None:
        session.next_non_combat_support_round_monotonic = None
        return False

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return False

    due_at = session.next_non_combat_support_round_monotonic
    if due_at is None:
        session.next_non_combat_support_round_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS
        return False

    if now < due_at:
        return False

    process_battle_round_support_effects(session)

    has_remaining_battle_round = any(effect.support_mode == "battle_rounds" for effect in session.active_support_effects)
    if has_remaining_battle_round:
        session.next_non_combat_support_round_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS
    else:
        session.next_non_combat_support_round_monotonic = None

    return True
