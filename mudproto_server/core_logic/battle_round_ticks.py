import asyncio
import random

from combat_ability_effects import _process_player_battle_round_affects
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


def _tick_player_skill_cooldowns(session: ClientSession) -> None:
    cooldowns = session.combat.skill_cooldowns
    for key, remaining in list(cooldowns.items()):
        if remaining <= 1:
            cooldowns.pop(key, None)
        else:
            cooldowns[key] = remaining - 1


def process_player_battle_round_tick(session: ClientSession, elapsed_rounds: int = 1) -> None:
    rounds = max(0, int(elapsed_rounds))
    for _ in range(rounds):
        process_battle_round_support_effects(session)
        _process_player_battle_round_affects(session)
        _tick_player_skill_cooldowns(session)


def _compute_elapsed_rounds(now: float, due_at: float, interval_seconds: float, *, max_rounds: int | None = None) -> tuple[int, float]:
    interval = max(0.001, float(interval_seconds))
    elapsed_rounds = 0
    next_due_at = float(due_at)
    while now >= next_due_at:
        elapsed_rounds += 1
        next_due_at += interval
        if max_rounds is not None and elapsed_rounds >= max_rounds:
            break
    return elapsed_rounds, next_due_at


def process_non_combat_battleround_tick(session: ClientSession) -> bool:
    from combat_state import get_engaged_entity

    def _has_battle_round_activity() -> bool:
        has_battle_round_effect = any(effect.support_mode == "battle_rounds" for effect in session.active_support_effects)
        return has_battle_round_effect or bool(session.combat.skill_cooldowns)

    if not _has_battle_round_activity():
        session.next_non_combat_battleround_tick_monotonic = None
        return False

    if get_engaged_entity(session) is not None:
        session.next_non_combat_battleround_tick_monotonic = None
        return False

    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        return False

    due_at = session.next_non_combat_battleround_tick_monotonic
    if due_at is None:
        session.next_non_combat_battleround_tick_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS
        return False

    if now < due_at:
        return False

    elapsed_rounds, due_at = _compute_elapsed_rounds(
        now,
        due_at,
        COMBAT_ROUND_INTERVAL_SECONDS,
    )

    if elapsed_rounds <= 0:
        return False

    process_player_battle_round_tick(session, elapsed_rounds)

    if _has_battle_round_activity():
        session.next_non_combat_battleround_tick_monotonic = due_at
    else:
        session.next_non_combat_battleround_tick_monotonic = None

    return True
