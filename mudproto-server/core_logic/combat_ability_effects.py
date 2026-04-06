"""Shared scaling, restore, cooldown, and support-effect helpers for combat abilities."""

import random

from models import ActiveSupportEffectState, ClientSession, EntityState
from player_resources import get_player_resource_caps


def _resolve_secondary_restore_fields(ability: dict) -> tuple[str, float, str, str]:
    restore_effect = str(ability.get("restore_effect", "")).strip().lower()
    restore_ratio = float(ability.get("restore_ratio", ability.get("life_steal_ratio", 0.0)))
    if not restore_effect and restore_ratio > 0.0 and float(ability.get("life_steal_ratio", 0.0)) > 0.0:
        restore_effect = "heal"

    restore_context = str(ability.get("restore_context", ability.get("life_steal_context", ""))).strip()
    observer_restore_context = str(
        ability.get("observer_restore_context", ability.get("observer_life_steal_context", ""))
    ).strip()
    return restore_effect, max(0.0, min(1.0, restore_ratio)), restore_context, observer_restore_context


def _player_restore_fallback(effect: str) -> str:
    if effect == "mana":
        return "Arcane current rushes back into your spirit."
    if effect == "vigor":
        return "Battle fervor surges back through your limbs."
    return "Stolen vitality surges back through your veins."


def _observer_restore_fallback(effect: str) -> str:
    if effect == "mana":
        return "Arcane current recoils into [actor_name], renewing [actor_object]."
    if effect == "vigor":
        return "Battle fervor surges back through [actor_possessive] limbs."
    return "Vital force recoils into [actor_name], renewing [actor_object]."


def _apply_player_secondary_restore(session: ClientSession, effect: str, amount: int) -> int:
    if amount <= 0:
        return 0

    caps = get_player_resource_caps(session)

    if effect == "mana":
        before = session.status.mana
        session.status.mana = min(caps["mana"], session.status.mana + amount)
        return session.status.mana - before
    if effect == "vigor":
        before = session.status.vigor
        session.status.vigor = min(caps["vigor"], session.status.vigor + amount)
        return session.status.vigor - before

    before = session.status.hit_points
    session.status.hit_points = min(caps["hit_points"], session.status.hit_points + amount)
    return session.status.hit_points - before


def _apply_entity_secondary_restore(entity: EntityState, effect: str, amount: int) -> int:
    if amount <= 0:
        return 0

    if effect == "mana":
        before = entity.mana
        entity.mana = min(entity.max_mana, entity.mana + amount)
        return entity.mana - before
    if effect == "vigor":
        before = entity.vigor
        entity.vigor = min(entity.max_vigor, entity.vigor + amount)
        return entity.vigor - before

    before = entity.hit_points
    entity.hit_points = min(entity.max_hit_points, entity.hit_points + amount)
    return entity.hit_points - before


def _resolve_player_support_scaling_bonus(session: ClientSession, spell: dict, support_effect: str) -> int:
    scaling_attribute_id = str(spell.get("support_scaling_attribute_id", "")).strip().lower()
    if not scaling_attribute_id and support_effect == "heal":
        scaling_attribute_id = "wis"
    level_scaling_multiplier = max(0.0, float(spell.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_attribute_id:
        scaling_multiplier = max(0.0, float(spell.get("support_scaling_multiplier", 1.0)))
        if scaling_multiplier > 0.0:
            attribute_score = int(session.player.attributes.get(scaling_attribute_id, 0))
            attribute_modifier = (attribute_score - 10) // 2
            scaling_bonus += int(attribute_modifier * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return scaling_bonus


def _resolve_player_damage_scaling_bonus(session: ClientSession, spell: dict) -> int:
    scaling_attribute_id = str(spell.get("damage_scaling_attribute_id", "int")).strip().lower() or "int"
    scaling_multiplier = max(0.0, float(spell.get("damage_scaling_multiplier", 1.0)))
    level_scaling_multiplier = max(0.0, float(spell.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_multiplier > 0.0:
        attribute_score = int(session.player.attributes.get(scaling_attribute_id, 0))
        attribute_modifier = (attribute_score - 10) // 2
        scaling_bonus += int(attribute_modifier * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return scaling_bonus


def _roll_player_support_amount(
    session: ClientSession,
    spell: dict,
    support_effect: str,
) -> tuple[int, int, int, int, int]:
    base_amount = max(0, int(spell.get("support_amount", 0)))
    dice_count = max(0, int(spell.get("support_dice_count", 0)))
    dice_sides = max(0, int(spell.get("support_dice_sides", 0)))
    roll_modifier = int(spell.get("support_roll_modifier", 0))
    scaling_bonus = _resolve_player_support_scaling_bonus(session, spell, support_effect)

    rolled_amount = base_amount + roll_modifier + scaling_bonus
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount), dice_count, dice_sides, roll_modifier, scaling_bonus


def _resolve_entity_support_scaling_bonus(entity: EntityState, spell: dict, support_effect: str) -> int:
    scaling_attribute_id = str(spell.get("support_scaling_attribute_id", "")).strip().lower()
    if not scaling_attribute_id and support_effect == "heal":
        scaling_attribute_id = "power_level"
    if scaling_attribute_id != "power_level":
        return 0

    scaling_multiplier = max(0.0, float(spell.get("support_scaling_multiplier", 1.0)))
    if scaling_multiplier <= 0.0:
        return 0

    return int(max(0, entity.power_level) * scaling_multiplier)


def _resolve_entity_damage_scaling_bonus(entity: EntityState, spell: dict) -> int:
    scaling_multiplier = max(0.0, float(spell.get("damage_scaling_multiplier", 1.0)))
    if scaling_multiplier <= 0.0:
        return 0

    return int(max(0, entity.power_level) * scaling_multiplier)


def _roll_entity_support_amount(
    entity: EntityState,
    spell: dict,
    support_effect: str,
) -> tuple[int, int, int, int, int]:
    base_amount = max(0, int(spell.get("support_amount", 0)))
    dice_count = max(0, int(spell.get("support_dice_count", 0)))
    dice_sides = max(0, int(spell.get("support_dice_sides", 0)))
    roll_modifier = int(spell.get("support_roll_modifier", 0))
    scaling_bonus = _resolve_entity_support_scaling_bonus(entity, spell, support_effect)

    rolled_amount = base_amount + roll_modifier + scaling_bonus
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount), dice_count, dice_sides, roll_modifier, scaling_bonus


def _roll_support_effect_amount(effect: ActiveSupportEffectState) -> int:
    rolled_amount = int(effect.support_amount)
    rolled_amount += int(effect.support_roll_modifier)
    rolled_amount += int(effect.support_scaling_bonus)

    dice_count = max(0, int(effect.support_dice_count))
    dice_sides = max(0, int(effect.support_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return max(0, rolled_amount)


def _process_entity_battle_round_support_effects(entity: EntityState) -> None:
    for effect in list(entity.active_support_effects):
        if effect.support_mode != "battle_rounds":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_rounds -= 1
        if effect.remaining_rounds <= 0:
            entity.active_support_effects.remove(effect)


def process_entity_game_hour_tick(entity: EntityState) -> None:
    for effect in list(entity.active_support_effects):
        if effect.support_mode != "timed":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_hours -= 1
        if effect.remaining_hours <= 0:
            entity.active_support_effects.remove(effect)


def _resolve_player_skill_scale_bonus(session: ClientSession, skill: dict) -> int:
    scaling_attribute_id = str(skill.get("scaling_attribute_id", "")).strip().lower()
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    level_scaling_multiplier = max(0.0, float(skill.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_attribute_id and scaling_multiplier > 0.0:
        attribute_value = int(session.player.attributes.get(scaling_attribute_id, 0))
        scaling_bonus += int(attribute_value * scaling_multiplier)

    if level_scaling_multiplier > 0.0:
        scaling_bonus += int(max(1, int(session.player.level)) * level_scaling_multiplier)

    return max(0, scaling_bonus)


def _resolve_entity_skill_scale_bonus(entity: EntityState, skill: dict) -> int:
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    if scaling_multiplier <= 0:
        return 0

    return max(0, int(max(0, entity.power_level) * scaling_multiplier))


def _set_player_skill_cooldown(session: ClientSession, skill: dict) -> None:
    cooldown_rounds = max(0, int(skill.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        skill_id = str(skill.get("skill_id", "")).strip()
        if skill_id:
            session.combat.skill_cooldowns[skill_id] = cooldown_rounds


def _set_entity_skill_cooldown(entity: EntityState, skill: dict) -> None:
    cooldown_rounds = max(0, int(skill.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        skill_id = str(skill.get("skill_id", "")).strip()
        if skill_id:
            entity.skill_cooldowns[skill_id] = cooldown_rounds


def _apply_player_skill_lag(session: ClientSession, skill: dict) -> None:
    # Lag is tracked for visual feedback but doesn't skip melee rounds.
    # Skills have lag_rounds but this doesn't prevent player melee attacks.
    pass


def _apply_entity_skill_lag(entity: EntityState, skill: dict) -> None:
    lag_rounds = max(0, int(skill.get("lag_rounds", 0)))
    if lag_rounds > 0:
        entity.skill_lag_rounds_remaining = max(entity.skill_lag_rounds_remaining, lag_rounds)


def _set_entity_spell_cooldown(entity: EntityState, spell: dict) -> None:
    cooldown_rounds = max(0, int(spell.get("cooldown_rounds", 0)))
    if cooldown_rounds > 0:
        spell_id = str(spell.get("spell_id", "")).strip()
        if spell_id:
            entity.spell_cooldowns[spell_id] = cooldown_rounds


def _apply_entity_spell_lag(entity: EntityState, spell: dict) -> None:
    lag_rounds = max(0, int(spell.get("lag_rounds", 0)))
    if lag_rounds > 0:
        entity.spell_lag_rounds_remaining = max(entity.spell_lag_rounds_remaining, lag_rounds)
