"""NPC and entity skill/spell execution helpers."""

import random

from assets import get_skill_by_id, get_spell_by_id
from combat_text import append_newline_if_needed
from damage import roll_skill_damage, roll_spell_damage
from grammar import with_article
from models import ActiveSupportEffectState, ClientSession, EntityState

from combat_ability_effects import (
    _apply_entity_secondary_restore,
    _apply_entity_skill_lag,
    _apply_entity_spell_lag,
    _apply_player_damage_with_reduction,
    _observer_restore_fallback,
    _resolve_entity_damage_scaling_bonus,
    _resolve_entity_skill_scale_bonus,
    _resolve_secondary_restore_fields,
    _roll_entity_support_amount,
    _set_entity_skill_cooldown,
    _set_entity_spell_cooldown,
)
from session_timing import apply_lag
from settings import COMBAT_ROUND_INTERVAL_SECONDS


def _entity_has_active_ongoing_support_effect(entity: EntityState, effect_id: str) -> bool:
    normalized_effect_id = str(effect_id).strip().lower()
    if not normalized_effect_id:
        return False

    for active_effect in entity.active_support_effects:
        active_effect_id = str(active_effect.spell_id).strip().lower()
        if active_effect_id != normalized_effect_id:
            continue

        support_mode = str(active_effect.support_mode).strip().lower() or "timed"
        if support_mode == "battle_rounds" and int(active_effect.remaining_rounds) > 0:
            return True
        if support_mode == "timed" and int(active_effect.remaining_hours) > 0:
            return True

    return False


def _entity_try_use_skill(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from combat_observer import _observer_context_from_player_context, _render_observer_template, _resolve_combat_context
    from display_core import build_part

    if not entity.skill_ids:
        return False

    chance = max(0.0, min(1.0, float(entity.skill_use_chance)))
    if random.random() >= chance:
        return False

    available_skills: list[dict] = []
    for skill_id in entity.skill_ids:
        skill = get_skill_by_id(skill_id)
        if skill is None:
            continue
        normalized_skill_id = str(skill.get("skill_id", "")).strip()
        if normalized_skill_id and entity.skill_cooldowns.get(normalized_skill_id, 0) > 0:
            continue
        vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
        if entity.vigor < vigor_cost:
            continue

        skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
        cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
        support_mode = str(skill.get("support_mode", "instant")).strip().lower() or "instant"
        if skill_type == "support" and cast_type == "self" and support_mode in {"timed", "battle_rounds"}:
            effect_id = str(skill.get("skill_id", "")).strip() or str(skill.get("name", "")).strip()
            if _entity_has_active_ongoing_support_effect(entity, effect_id):
                continue

        available_skills.append(skill)

    if not available_skills:
        return False

    skill = random.choice(available_skills)
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    scaling_bonus = _resolve_entity_skill_scale_bonus(entity, skill)
    observer_context = str(skill.get("observer_context", "")).strip()

    description = str(skill.get("description", "")).strip()
    cast_target_text = " on you!"
    if skill_type == "support" and cast_type == "self":
        cast_target_text = " on themselves!"
    elif cast_type == "aoe":
        cast_target_text = " across the room!"

    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True)),
        build_part(" uses "),
        build_part(skill_name),
        build_part(cast_target_text),
    ])
    if description and skill_type != "support":
        parts.extend([
            build_part(" "),
            build_part(description),
        ])

    entity.vigor = max(0, entity.vigor - vigor_cost)

    if skill_type == "support" and cast_type == "self":
        support_effect = str(skill.get("support_effect", "")).strip().lower()
        support_amount = max(0, int(skill.get("support_amount", 0)))
        support_mode = str(skill.get("support_mode", "instant")).strip().lower() or "instant"
        duration_hours = max(0, int(skill.get("duration_hours", 0)))
        duration_rounds = max(0, int(skill.get("duration_rounds", 0)))
        support_context = str(skill.get("support_context", "")).strip()
        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_mode == "instant":
            if support_effect == "heal":
                entity.hit_points = min(entity.max_hit_points, entity.hit_points + total_support_amount)
            elif support_effect == "vigor":
                entity.vigor = min(entity.max_vigor, entity.vigor + total_support_amount)
            elif support_effect == "mana":
                entity.mana = min(entity.max_mana, entity.mana + total_support_amount)
        elif support_mode in {"timed", "battle_rounds"}:
            effect_id = str(skill.get("skill_id", skill_name)).strip() or skill_name
            refreshed = False
            for active_effect in entity.active_support_effects:
                if active_effect.spell_id != effect_id:
                    continue
                active_effect.support_mode = support_mode
                active_effect.support_effect = support_effect
                active_effect.support_amount = total_support_amount
                active_effect.support_dice_count = 0
                active_effect.support_dice_sides = 0
                active_effect.support_roll_modifier = 0
                active_effect.support_scaling_bonus = 0
                active_effect.remaining_hours = duration_hours
                active_effect.remaining_rounds = duration_rounds
                refreshed = True
                break

            if not refreshed:
                entity.active_support_effects.append(ActiveSupportEffectState(
                    spell_id=effect_id,
                    spell_name=skill_name,
                    support_mode=support_mode,
                    support_effect=support_effect,
                    support_amount=total_support_amount,
                    remaining_hours=duration_hours,
                    support_dice_count=0,
                    support_dice_sides=0,
                    support_roll_modifier=0,
                    support_scaling_bonus=0,
                    remaining_rounds=duration_rounds,
                ))
        if support_context:
            rendered_support_context = observer_context or _observer_context_from_player_context(support_context)
            append_newline_if_needed(parts)
            parts.append(build_part(_render_observer_template(
                rendered_support_context,
                with_article(entity.name, capitalize=True),
            )))

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    if skill_type == "damage" and cast_type in {"target", "aoe"}:
        total_damage = roll_skill_damage(skill) + scaling_bonus
        damage_context = str(skill.get("damage_context", "")).strip()
        restore_effect, restore_ratio, _, observer_restore_context = _resolve_secondary_restore_fields(skill)
        damage_dealt = 0

        if total_damage > 0:
            damage_dealt = _apply_player_damage_with_reduction(session, total_damage)

        restored_amount = 0
        if restore_ratio > 0.0 and damage_dealt > 0:
            restore_amount = int(damage_dealt * restore_ratio)
            restored_amount = _apply_entity_secondary_restore(entity, restore_effect, restore_amount)

        append_newline_if_needed(parts)
        if damage_context:
            resolved_context = _resolve_combat_context(damage_context, target_text="you", verb="are")
            parts.append(build_part(resolved_context))
        elif total_damage > 0:
            parts.extend([
                build_part("You are hit by "),
                build_part(skill_name),
                build_part("."),
            ])
        else:
            parts.extend([
                build_part("You avoid "),
                build_part(skill_name),
                build_part("."),
            ])

        if restored_amount > 0:
            append_newline_if_needed(parts)
            rendered_restore_context = _render_observer_template(
                observer_restore_context or _observer_restore_fallback(restore_effect),
                with_article(entity.name, capitalize=True),
            )
            parts.append(build_part(rendered_restore_context))

        target_lag_rounds = max(0, int(skill.get("target_lag_rounds", 0)))
        if target_lag_rounds > 0 and damage_dealt > 0:
            apply_lag(session, float(target_lag_rounds) * float(COMBAT_ROUND_INTERVAL_SECONDS))
            session.is_resting = False
            session.is_sitting = True
            entity.skill_lag_rounds_remaining = max(entity.skill_lag_rounds_remaining, target_lag_rounds)

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    return False


def _entity_try_cast_spell(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from combat_observer import _observer_context_from_player_context, _render_observer_template, _resolve_combat_context
    from display_core import build_part

    if not entity.spell_ids:
        return False

    chance = max(0.0, min(1.0, float(entity.spell_use_chance)))
    if random.random() >= chance:
        return False

    available_spells: list[dict] = []
    for spell_id in entity.spell_ids:
        spell = get_spell_by_id(spell_id)
        if spell is None:
            continue
        normalized_spell_id = str(spell.get("spell_id", "")).strip()
        if normalized_spell_id and entity.spell_cooldowns.get(normalized_spell_id, 0) > 0:
            continue

        mana_cost = max(0, int(spell.get("mana_cost", 0)))
        if entity.mana < mana_cost:
            continue

        spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
        cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"
        support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
        if spell_type == "support" and cast_type == "self" and support_mode in {"timed", "battle_rounds"}:
            effect_id = str(spell.get("spell_id", "")).strip() or str(spell.get("name", "")).strip()
            if _entity_has_active_ongoing_support_effect(entity, effect_id):
                continue

        available_spells.append(spell)

    if not available_spells:
        return False

    spell = random.choice(available_spells)
    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
    cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    observer_context = str(spell.get("observer_context", "")).strip()
    cast_target_text = " at you!"
    if spell_type == "support" and cast_type == "self":
        cast_target_text = " on themselves!"
    elif cast_type == "aoe":
        cast_target_text = " across the room!"

    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True)),
        build_part(" casts "),
        build_part(spell_name),
        build_part(cast_target_text),
    ])

    entity.mana = max(0, entity.mana - mana_cost)

    if spell_type == "support" and cast_type == "self":
        support_effect = str(spell.get("support_effect", "")).strip().lower()
        support_amount = max(0, int(spell.get("support_amount", 0)))
        support_dice_count = max(0, int(spell.get("support_dice_count", 0)))
        support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
        duration_hours = max(0, int(spell.get("duration_hours", 0)))
        duration_rounds = max(0, int(spell.get("duration_rounds", 0)))
        support_context = str(spell.get("support_context", "")).strip()

        if support_amount <= 0 and support_dice_count <= 0:
            return False

        rolled_support_amount, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_entity_support_amount(
            entity,
            spell,
            support_effect,
        )

        if support_mode == "instant":
            if support_effect == "heal":
                entity.hit_points = min(entity.max_hit_points, entity.hit_points + rolled_support_amount)
            elif support_effect == "vigor":
                entity.vigor = min(entity.max_vigor, entity.vigor + rolled_support_amount)
            elif support_effect == "mana":
                entity.mana = min(entity.max_mana, entity.mana + rolled_support_amount)
        elif support_mode in {"timed", "battle_rounds"}:
            spell_id = str(spell.get("spell_id", spell_name)).strip() or spell_name
            refreshed = False
            for active_effect in entity.active_support_effects:
                if active_effect.spell_id != spell_id:
                    continue
                active_effect.support_mode = support_mode
                active_effect.support_effect = support_effect
                active_effect.support_amount = support_amount
                active_effect.support_dice_count = dice_count
                active_effect.support_dice_sides = dice_sides
                active_effect.support_roll_modifier = roll_modifier
                active_effect.support_scaling_bonus = scaling_bonus
                active_effect.remaining_hours = duration_hours
                active_effect.remaining_rounds = duration_rounds
                refreshed = True
                break

            if not refreshed:
                entity.active_support_effects.append(ActiveSupportEffectState(
                    spell_id=spell_id,
                    spell_name=spell_name,
                    support_mode=support_mode,
                    support_effect=support_effect,
                    support_amount=support_amount,
                    support_dice_count=dice_count,
                    support_dice_sides=dice_sides,
                    support_roll_modifier=roll_modifier,
                    support_scaling_bonus=scaling_bonus,
                    remaining_hours=duration_hours,
                    remaining_rounds=duration_rounds,
                ))

        if support_context:
            rendered_support_context = observer_context or _observer_context_from_player_context(support_context)
            append_newline_if_needed(parts)
            parts.append(build_part(_render_observer_template(
                rendered_support_context,
                with_article(entity.name, capitalize=True),
            )))

        _set_entity_spell_cooldown(entity, spell)
        _apply_entity_spell_lag(entity, spell)
        return True

    if spell_type == "damage" and cast_type in {"target", "aoe"}:
        spell_damage = roll_spell_damage(spell, _resolve_entity_damage_scaling_bonus(entity, spell))
        damage_context = str(spell.get("damage_context", "")).strip()
        restore_effect, restore_ratio, _, observer_restore_context = _resolve_secondary_restore_fields(spell)
        damage_dealt = 0

        if spell_damage > 0:
            damage_dealt = _apply_player_damage_with_reduction(session, spell_damage)

        restored_amount = 0
        if restore_ratio > 0.0 and damage_dealt > 0:
            restore_amount = int(damage_dealt * restore_ratio)
            restored_amount = _apply_entity_secondary_restore(entity, restore_effect, restore_amount)

        append_newline_if_needed(parts)
        if damage_context:
            resolved_context = _resolve_combat_context(damage_context, target_text="you", verb="are")
            parts.append(build_part(resolved_context))
        elif spell_damage > 0:
            parts.extend([
                build_part("You are struck by "),
                build_part(spell_name),
                build_part("."),
            ])
        else:
            parts.extend([
                build_part("You resist "),
                build_part(spell_name),
                build_part("."),
            ])

        if restored_amount > 0:
            append_newline_if_needed(parts)
            rendered_restore_context = _render_observer_template(
                observer_restore_context or _observer_restore_fallback(restore_effect),
                with_article(entity.name, capitalize=True),
            )
            parts.append(build_part(rendered_restore_context))

        _set_entity_spell_cooldown(entity, spell)
        _apply_entity_spell_lag(entity, spell)
        return True

    return False
