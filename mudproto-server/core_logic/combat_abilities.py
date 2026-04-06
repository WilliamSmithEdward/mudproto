import random

from assets import get_skill_by_id, get_spell_by_id
from combat_text import append_newline_if_needed
from damage import roll_skill_damage, roll_spell_damage
from grammar import with_article
from models import ActiveSupportEffectState, ClientSession, EntityState
from player_resources import get_player_resource_caps
from targeting import list_room_entities, resolve_room_entity_selector


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


def use_skill(session: ClientSession, skill: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from combat import (
        _attach_room_broadcast_lines,
        _award_shared_entity_experience,
        _engage_next_targeting_entity,
        _mark_entity_contributor,
        _observer_context_from_player_context,
        _render_observer_template,
        _resolve_combat_context,
        _resolve_observer_action_line,
        clear_combat_if_invalid,
        get_engaged_entity,
        spawn_corpse_for_entity,
    )
    from display import build_part, display_command_result, display_error

    skill_id = str(skill.get("skill_id", "")).strip()
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    usable_out_of_combat = bool(skill.get("usable_out_of_combat", False))
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    damage_context = str(skill.get("damage_context", "")).strip()
    support_effect = str(skill.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(skill.get("support_amount", 0)))
    support_context = str(skill.get("support_context", "")).strip()
    observer_action = str(skill.get("observer_action", "")).strip()
    observer_context = str(skill.get("observer_context", "")).strip()
    scaling_bonus = _resolve_player_skill_scale_bonus(session, skill)
    actor_name = session.authenticated_character_name or "Someone"

    if get_engaged_entity(session) is None and not usable_out_of_combat:
        return display_error(f"{skill_name} can only be used while in combat.", session), False

    if skill_id and session.combat.skill_cooldowns.get(skill_id, 0) > 0:
        return display_error(
            f"{skill_name} is on cooldown for {session.combat.skill_cooldowns[skill_id]} more round(s).",
            session,
        ), False

    if cast_type not in {"self", "target", "aoe"}:
        return display_error(f"Skill '{skill_name}' has unsupported cast_type '{cast_type}'.", session), False
    if skill_type not in {"damage", "support"}:
        return display_error(f"Skill '{skill_name}' has unsupported skill_type '{skill_type}'.", session), False

    description = str(skill.get("description", "")).strip()

    target_text = ""
    if cast_type == "target" and target_name:
        target_entity, _ = resolve_room_entity_selector(
            session,
            session.player.current_room_id,
            target_name,
            living_only=True,
        )
        if target_entity:
            target_text = f" on {with_article(target_entity.name)}"
        else:
            target_text = f" on {target_name}"
    elif cast_type == "self":
        target_text = " on yourself"

    parts = [
        build_part("You use "),
        build_part(skill_name),
        build_part(target_text + "."),
    ]
    if description and skill_type != "support":
        parts.extend([
            build_part(" "),
            build_part(description),
        ])

    if skill_type == "support":
        if cast_type != "self":
            return display_error(f"Support skill '{skill_name}' must be cast_type 'self'.", session), False
        if support_effect not in {"heal", "vigor", "mana"}:
            return display_error(
                f"Skill '{skill_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False

        if session.status.vigor < vigor_cost:
            return display_error(
                f"Not enough vigor for {skill_name}. Need {vigor_cost}V, have {session.status.vigor}V.",
                session,
            ), False

        session.status.vigor -= vigor_cost
        caps = get_player_resource_caps(session)

        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            session.status.hit_points = min(caps["hit_points"], session.status.hit_points + total_support_amount)
        elif support_effect == "vigor":
            session.status.vigor = min(caps["vigor"], session.status.vigor + total_support_amount)
        else:
            session.status.mana = min(caps["mana"], session.status.mana + total_support_amount)

        if support_context:
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])

        _set_player_skill_cooldown(session, skill)
        _apply_player_skill_lag(session, skill)
        observer_lines = [
            _resolve_observer_action_line(
                actor_name,
                "uses",
                skill_name,
                cast_type,
                observer_action=observer_action,
            ),
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts, blank_lines_before=0)
        return _attach_room_broadcast_lines(result, observer_lines), True

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    peaceful_targets_for_feedback: list[EntityState] = []
    if cast_type == "target":
        entity: EntityState | None = None
        if target_name:
            entity, resolve_error = resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                target_name,
                living_only=True,
            )
            if entity is None:
                return display_error(resolve_error or f"No target named '{target_name}' is here.", session), False
        else:
            entity = get_engaged_entity(session)
            if entity is None:
                return display_error("Target skill requires a target: skill <name> <target>", session), False
        if bool(getattr(entity, "is_peaceful", False)):
            peaceful_targets_for_feedback.append(entity)
        else:
            damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if not entity.is_alive:
                continue
            if bool(getattr(entity, "is_peaceful", False)):
                peaceful_targets_for_feedback.append(entity)
                continue
            if entity.is_ally:
                continue
            damage_targets.append(entity)
        if not damage_targets and not peaceful_targets_for_feedback:
            return display_error("No valid hostile targets in the room.", session), False
    else:
        return display_error(f"Damage skill '{skill_name}' cannot be cast as '{cast_type}'.", session), False

    if session.status.vigor < vigor_cost:
        return display_error(
            f"Not enough vigor for {skill_name}. Need {vigor_cost}V, have {session.status.vigor}V.",
            session,
        ), False

    session.status.vigor -= vigor_cost

    total_damage = roll_skill_damage(skill) + scaling_bonus
    restore_effect, restore_ratio, restore_context, observer_restore_context = _resolve_secondary_restore_fields(skill)
    total_damage_dealt = 0
    destroyed_entity_names: list[str] = []

    for entity in damage_targets:
        parts.append(build_part("\n"))
        named_target = with_article(entity.name, capitalize=True)
        resolved_context = _resolve_combat_context(damage_context, target_text=named_target, verb="is")

        if total_damage > 0:
            _mark_entity_contributor(session, entity)
            dealt = min(entity.hit_points, total_damage)
            entity.hit_points = max(0, entity.hit_points - total_damage)
            total_damage_dealt += max(0, dealt)
            if resolved_context:
                parts.append(build_part(resolved_context))
            else:
                parts.extend([
                    build_part(named_target),
                    build_part(" is struck by "),
                    build_part(skill_name),
                    build_part("."),
                ])
        else:
            parts.extend([
                build_part(named_target),
                build_part(" avoids "),
                build_part(skill_name),
                build_part("."),
            ])

        if entity.hit_points <= 0:
            entity.is_alive = False
            spawn_corpse_for_entity(session, entity)
            _award_shared_entity_experience(session, entity, parts, build_part)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True), "bright_red", True),
                build_part(" is dead!", "bright_red", True),
            ])

            if entity.entity_id in session.combat.engaged_entity_ids:
                session.combat.engaged_entity_ids.discard(entity.entity_id)
                next_target = _engage_next_targeting_entity(session, entity.entity_id)
                if next_target is not None:
                    parts.extend([
                        build_part("\n"),
                        build_part("You turn to "),
                        build_part(with_article(next_target.name)),
                        build_part("."),
                    ])

    if not damage_targets and peaceful_targets_for_feedback:
        parts.extend([
            build_part("\n"),
            build_part(f"{peaceful_targets_for_feedback[0].name} remains untouched."),
        ])

    restored_amount = 0
    if restore_ratio > 0.0 and total_damage_dealt > 0:
        restore_amount = int(total_damage_dealt * restore_ratio)
        restored_amount = _apply_player_secondary_restore(session, restore_effect, restore_amount)
        if restored_amount > 0:
            parts.extend([
                build_part("\n"),
                build_part(restore_context or _player_restore_fallback(restore_effect)),
            ])

    _set_player_skill_cooldown(session, skill)
    _apply_player_skill_lag(session, skill)
    target_label = with_article(damage_targets[0].name) if damage_targets else None
    observer_lines = [
        _resolve_observer_action_line(
            actor_name,
            "uses",
            skill_name,
            cast_type,
            target_label=target_label,
            observer_action=observer_action,
        ),
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    if restored_amount > 0:
        observer_lines.append(_render_observer_template(
            observer_restore_context or _observer_restore_fallback(restore_effect),
            actor_name,
        ))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is dead!")

    result = display_command_result(session, parts, blank_lines_before=0)
    return _attach_room_broadcast_lines(result, observer_lines), True


def _entity_try_use_skill(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from combat import _observer_context_from_player_context, _render_observer_template, _resolve_combat_context
    from display import build_part

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
        support_context = str(skill.get("support_context", "")).strip()
        total_support_amount = max(0, support_amount + scaling_bonus)

        if support_effect == "heal":
            entity.hit_points = min(entity.max_hit_points, entity.hit_points + total_support_amount)
        elif support_effect == "vigor":
            entity.vigor = min(entity.max_vigor, entity.vigor + total_support_amount)
        elif support_effect == "mana":
            entity.mana = min(entity.max_mana, entity.mana + total_support_amount)
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
            damage_dealt = min(session.status.hit_points, total_damage)
            session.status.hit_points = max(0, session.status.hit_points - total_damage)

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

        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    return False


def _entity_try_cast_spell(session: ClientSession, entity: EntityState, parts: list[dict]) -> bool:
    from combat import _observer_context_from_player_context, _render_observer_template, _resolve_combat_context
    from display import build_part

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
            damage_dealt = min(session.status.hit_points, spell_damage)
            session.status.hit_points = max(0, session.status.hit_points - spell_damage)

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


def cast_spell(session: ClientSession, spell: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from combat import (
        _attach_room_broadcast_lines,
        _award_shared_entity_experience,
        _engage_next_targeting_entity,
        _mark_entity_contributor,
        _observer_context_from_player_context,
        _render_observer_template,
        _resolve_combat_context,
        _resolve_observer_action_line,
        clear_combat_if_invalid,
        get_engaged_entity,
        spawn_corpse_for_entity,
    )
    from display import build_part, display_command_result, display_error

    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
    cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"

    damage_context = str(spell.get("damage_context", "")).strip()
    support_effect = str(spell.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(spell.get("support_amount", 0)))
    support_dice_count = max(0, int(spell.get("support_dice_count", 0)))
    duration_hours = max(0, int(spell.get("duration_hours", 0)))
    duration_rounds = max(0, int(spell.get("duration_rounds", 0)))
    support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
    support_context = str(spell.get("support_context", "")).strip()
    observer_action = str(spell.get("observer_action", "")).strip()
    observer_context = str(spell.get("observer_context", "")).strip()
    spell_id = str(spell.get("spell_id", spell_name)).strip() or spell_name
    actor_name = session.authenticated_character_name or "Someone"

    status = session.status
    if status.mana < mana_cost:
        return display_error(
            f"Not enough mana for {spell_name}. Need {mana_cost}M, have {status.mana}M.",
            session,
        ), False

    if cast_type not in {"self", "target", "aoe"}:
        return display_error(f"Spell '{spell_name}' has unsupported cast_type '{cast_type}'.", session), False

    if spell_type == "support":
        if cast_type != "self":
            return display_error(f"Support spell '{spell_name}' must be cast_type 'self'.", session), False
        if support_effect not in {"heal", "vigor", "mana"}:
            return display_error(
                f"Spell '{spell_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False
        if support_mode not in {"timed", "instant", "battle_rounds"}:
            return display_error(
                f"Spell '{spell_name}' has unsupported support_mode '{support_mode}'.",
                session,
            ), False
        if support_mode == "timed" and duration_hours <= 0:
            return display_error(
                f"Spell '{spell_name}' must have duration_hours > 0.",
                session,
            ), False
        if support_mode == "battle_rounds" and duration_rounds <= 0:
            return display_error(
                f"Spell '{spell_name}' must have duration_rounds > 0.",
                session,
            ), False
        if support_amount <= 0 and support_dice_count <= 0:
            return display_error(
                f"Spell '{spell_name}' must define support_amount and/or support_dice_count.",
                session,
            ), False
        if not support_context:
            return display_error(
                f"Spell '{spell_name}' must define support_context.",
                session,
            ), False

        status.mana -= mana_cost

        if support_mode == "instant":
            parts = [
                build_part("You cast "),
                build_part(spell_name),
                build_part("."),
            ]

            rolled_support_amount, _, _, _, _ = _roll_player_support_amount(session, spell, support_effect)
            caps = get_player_resource_caps(session)
            if support_effect == "heal":
                status.hit_points = min(caps["hit_points"], status.hit_points + rolled_support_amount)
            elif support_effect == "vigor":
                status.vigor = min(caps["vigor"], status.vigor + rolled_support_amount)
            else:
                status.mana = min(caps["mana"], status.mana + rolled_support_amount)
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])
            observer_lines = [
                _resolve_observer_action_line(
                    actor_name,
                    "casts",
                    spell_name,
                    cast_type,
                    observer_action=observer_action,
                ),
            ]
            support_observer_context = observer_context or _observer_context_from_player_context(support_context)
            if support_observer_context:
                observer_lines.append(_render_observer_template(support_observer_context, actor_name))

            result = display_command_result(session, parts, blank_lines_before=0)
            return _attach_room_broadcast_lines(result, observer_lines), True

        _, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_player_support_amount(
            session,
            spell,
            support_effect,
        )

        refreshed = False
        for active_effect in session.active_support_effects:
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
            session.active_support_effects.append(ActiveSupportEffectState(
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

        parts = [
            build_part("You cast "),
            build_part(spell_name),
            build_part("."),
            build_part("\n"),
            build_part(support_context),
        ]
        observer_lines = [
            _resolve_observer_action_line(
                actor_name,
                "casts",
                spell_name,
                cast_type,
                observer_action=observer_action,
            ),
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(support_context)
        if support_observer_context:
            observer_lines.append(_render_observer_template(support_observer_context, actor_name))

        result = display_command_result(session, parts, blank_lines_before=0)
        return _attach_room_broadcast_lines(result, observer_lines), True

    if spell_type != "damage":
        return display_error(f"Spell '{spell_name}' has unsupported spell_type '{spell_type}'.", session), False

    clear_combat_if_invalid(session)

    damage_targets: list[EntityState] = []
    peaceful_targets_for_feedback: list[EntityState] = []
    if cast_type == "target":
        entity: EntityState | None = None
        if target_name:
            entity, resolve_error = resolve_room_entity_selector(
                session,
                session.player.current_room_id,
                target_name,
                living_only=True,
            )
            if entity is None:
                return display_error(resolve_error or f"No target named '{target_name}' is here.", session), False
        else:
            entity = get_engaged_entity(session)
            if entity is None:
                return display_error("Target spell requires a target: cast 'spell' <target>", session), False
        if bool(getattr(entity, "is_peaceful", False)):
            peaceful_targets_for_feedback.append(entity)
        else:
            damage_targets.append(entity)
    elif cast_type == "aoe":
        for entity in list_room_entities(session, session.player.current_room_id):
            if not entity.is_alive:
                continue
            if bool(getattr(entity, "is_peaceful", False)):
                peaceful_targets_for_feedback.append(entity)
                continue
            if entity.is_ally:
                continue
            damage_targets.append(entity)

        if not damage_targets and not peaceful_targets_for_feedback:
            return display_error("No valid hostile targets in the room.", session), False
    else:
        return display_error(f"Damage spell '{spell_name}' cannot be cast as '{cast_type}'.", session), False

    status.mana -= mana_cost

    total_damage = roll_spell_damage(spell, _resolve_player_damage_scaling_bonus(session, spell))
    restore_effect, restore_ratio, restore_context, observer_restore_context = _resolve_secondary_restore_fields(spell)
    total_damage_dealt = 0
    destroyed_entity_names: list[str] = []

    parts = [
        build_part("You cast "),
        build_part(spell_name),
        build_part("."),
    ]

    for entity in damage_targets:
        parts.append(build_part("\n"))

        named_target = with_article(entity.name, capitalize=True)
        resolved_context = _resolve_combat_context(damage_context, target_text=named_target, verb="is")

        if total_damage > 0:
            _mark_entity_contributor(session, entity)
            dealt = min(entity.hit_points, total_damage)
            entity.hit_points = max(0, entity.hit_points - total_damage)
            total_damage_dealt += max(0, dealt)
            if resolved_context:
                parts.append(build_part(resolved_context))
            else:
                parts.extend([
                    build_part(named_target),
                    build_part(" is struck by "),
                    build_part(spell_name),
                    build_part("."),
                ])
        else:
            parts.extend([
                build_part(named_target),
                build_part(" resists "),
                build_part(spell_name),
                build_part("."),
            ])

        if entity.hit_points <= 0:
            entity.is_alive = False
            spawn_corpse_for_entity(session, entity)
            _award_shared_entity_experience(session, entity, parts, build_part)
            destroyed_entity_names.append(entity.name)
            parts.extend([
                build_part("\n"),
                build_part(with_article(entity.name, capitalize=True), "bright_red", True),
                build_part(" is dead!", "bright_red", True),
            ])

            if entity.entity_id in session.combat.engaged_entity_ids:
                session.combat.engaged_entity_ids.discard(entity.entity_id)
                next_target = _engage_next_targeting_entity(session, entity.entity_id)
                if next_target is not None:
                    parts.extend([
                        build_part("\n"),
                        build_part("You turn to "),
                        build_part(with_article(next_target.name)),
                        build_part("."),
                    ])

    if not damage_targets and peaceful_targets_for_feedback:
        parts.extend([
            build_part("\n"),
            build_part(f"{peaceful_targets_for_feedback[0].name} remains untouched."),
        ])

    restored_amount = 0
    if restore_ratio > 0.0 and total_damage_dealt > 0:
        restore_amount = int(total_damage_dealt * restore_ratio)
        restored_amount = _apply_player_secondary_restore(session, restore_effect, restore_amount)
        if restored_amount > 0:
            parts.extend([
                build_part("\n"),
                build_part(restore_context or _player_restore_fallback(restore_effect)),
            ])

    target_label = with_article(damage_targets[0].name) if damage_targets else None
    observer_lines = [
        _resolve_observer_action_line(
            actor_name,
            "casts",
            spell_name,
            cast_type,
            target_label=target_label,
            observer_action=observer_action,
        ),
    ]
    damage_observer_context = observer_context or _observer_context_from_player_context(damage_context, target_label)
    if damage_observer_context:
        observer_lines.append(_render_observer_template(damage_observer_context, actor_name))
    if restored_amount > 0:
        observer_lines.append(_render_observer_template(
            observer_restore_context or _observer_restore_fallback(restore_effect),
            actor_name,
        ))
    for destroyed_name in destroyed_entity_names:
        observer_lines.append(f"{with_article(destroyed_name, capitalize=True)} is dead!")

    result = display_command_result(session, parts, blank_lines_before=0)
    return _attach_room_broadcast_lines(result, observer_lines), True
