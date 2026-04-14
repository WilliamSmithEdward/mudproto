"""Player-facing skill and spell execution helpers."""

from grammar import third_personize_text, with_article
from models import ActiveSupportEffectState, ClientSession, EntityState
from player_resources import get_player_resource_caps
from targeting_entities import list_room_entities, resolve_room_entity_selector
from targeting_follow import _resolve_room_player_selector
from damage import roll_skill_damage, roll_spell_damage

from combat_ability_effects import (
    _apply_entity_damage_with_reduction,
    _apply_player_secondary_restore,
    _apply_player_skill_lag,
    _observer_restore_fallback,
    _player_restore_fallback,
    _resolve_player_damage_scaling_bonus,
    _resolve_player_skill_scale_bonus,
    _resolve_secondary_restore_fields,
    _roll_player_support_amount,
    _set_player_skill_cooldown,
)


def use_skill(session: ClientSession, skill: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from combat_observer import (
        _attach_room_broadcast_lines,
        _observer_context_from_player_context,
        _render_observer_template,
        _resolve_combat_context,
        _resolve_observer_action_line,
    )
    from combat_rewards import _award_shared_entity_experience, _mark_entity_contributor
    from combat_state import (
        _engage_next_targeting_entity,
        _is_entity_engaged_by_other_player,
        apply_entity_defeat_flags,
        clear_combat_if_invalid,
        get_engaged_entity,
        spawn_corpse_for_entity,
        start_combat,
    )
    from display_core import build_part
    from display_feedback import display_command_result, display_error

    OPENING_ATTACKER_SKILL = "skill"

    skill_id = str(skill.get("skill_id", "")).strip()
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    usable_out_of_combat = bool(skill.get("usable_out_of_combat", False))
    skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
    cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
    damage_context = str(skill.get("damage_context", "")).strip()
    support_effect = str(skill.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(skill.get("support_amount", 0)))
    support_mode = str(skill.get("support_mode", "instant")).strip().lower() or "instant"
    duration_hours = max(0, int(skill.get("duration_hours", 0)))
    duration_rounds = max(0, int(skill.get("duration_rounds", 0)))
    support_context = str(skill.get("support_context", "")).strip()
    observer_action = str(skill.get("observer_action", "")).strip()
    observer_context = str(skill.get("observer_context", "")).strip()
    target_lag_rounds = max(0, int(skill.get("target_lag_rounds", 0)))
    scaling_bonus = _resolve_player_skill_scale_bonus(session, skill)
    actor_name = session.authenticated_character_name or "Someone"

    has_explicit_target = bool(str(target_name or "").strip())
    can_open_with_targeted_damage = (
        skill_type == "damage"
        and cast_type == "target"
        and has_explicit_target
    )
    if get_engaged_entity(session) is None and not usable_out_of_combat and not can_open_with_targeted_damage:
        return display_error(f"{skill_name} can only be used while in combat.", session), False

    if skill_id and session.combat.skill_cooldowns.get(skill_id, 0) > 0:
        return display_error(
            f"{skill_name} is on cooldown for {session.combat.skill_cooldowns[skill_id]} more round(s).",
            session,
        ), False

    if skill_id and session.combat.skill_hour_cooldowns.get(skill_id, 0) > 0:
        remaining_hours = session.combat.skill_hour_cooldowns[skill_id]
        return display_error(
            f"{skill_name} is on cooldown for {remaining_hours} more game hour(s).",
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
            require_exact_name=True,
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
        if support_effect not in {"heal", "vigor", "mana", "damage_reduction", "extra_unarmed_hits"}:
            return display_error(
                f"Skill '{skill_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False
        if support_mode not in {"instant", "timed", "battle_rounds"}:
            return display_error(
                f"Skill '{skill_name}' has unsupported support_mode '{support_mode}'.",
                session,
            ), False
        if support_effect == "damage_reduction" and support_mode == "instant":
            return display_error(
                f"Skill '{skill_name}' must use timed or battle_rounds mode for damage reduction.",
                session,
            ), False
        if support_mode == "timed" and duration_hours <= 0:
            return display_error(f"Skill '{skill_name}' must have duration_hours > 0.", session), False
        if support_mode == "battle_rounds" and duration_rounds <= 0:
            return display_error(f"Skill '{skill_name}' must have duration_rounds > 0.", session), False

        if session.status.vigor < vigor_cost:
            return display_error(
                f"Not enough vigor for {skill_name}. Need {vigor_cost}V, have {session.status.vigor}V.",
                session,
            ), False

        session.status.vigor -= vigor_cost
        caps = get_player_resource_caps(session)
        total_support_amount = max(0, support_amount + scaling_bonus)
        effect_duration_rounds = duration_rounds
        if support_effect == "extra_unarmed_hits":
            extra_step_levels = max(1, int(skill.get("support_level_step", 1)))
            extra_per_step = max(
                0,
                int(skill.get("support_amount_per_level_step", 0)),
            )
            level_bonus = (max(1, int(session.player.level)) // extra_step_levels) * extra_per_step
            total_support_amount = max(0, support_amount + level_bonus)
            # Battle-round effects decrement at round start; add one so this lasts
            # for the next N full rounds after the cast turn.
            if support_mode == "battle_rounds" and duration_rounds > 0:
                effect_duration_rounds = duration_rounds + 1

        if support_mode == "instant":
            if support_effect == "heal":
                session.status.hit_points = min(caps["hit_points"], session.status.hit_points + total_support_amount)
            elif support_effect == "vigor":
                session.status.vigor = min(caps["vigor"], session.status.vigor + total_support_amount)
            else:
                session.status.mana = min(caps["mana"], session.status.mana + total_support_amount)
        else:
            effect_id = skill_id or skill_name
            refreshed = False
            for active_effect in session.active_support_effects:
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
                active_effect.remaining_rounds = effect_duration_rounds
                refreshed = True
                break

            if not refreshed:
                session.active_support_effects.append(ActiveSupportEffectState(
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
                    remaining_rounds=effect_duration_rounds,
                ))

        if support_context:
            parts.extend([
                build_part("\n"),
                build_part(support_context),
            ])

        _set_player_skill_cooldown(session, skill)
        cooldown_hours = max(0, int(skill.get("cooldown_hours", 0)))
        if cooldown_hours > 0 and skill_id:
            session.combat.skill_hour_cooldowns[skill_id] = cooldown_hours
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
                require_exact_name=True,
            )
            if entity is None:
                return display_error(resolve_error or f"No target named '{target_name}' is here.", session), False
        else:
            entity = get_engaged_entity(session)
            if entity is None:
                return display_error("Target skill requires a target: skill <name> <target>", session), False

        # Targeted skills explicitly engage the caster, even if the target is
        # already fighting someone else. Existing target focus is preserved by
        # combat state sync logic.
        if not bool(getattr(entity, "is_peaceful", False)) and entity.entity_id not in session.combat.engaged_entity_ids:
            start_combat(session, entity.entity_id, OPENING_ATTACKER_SKILL)

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
    damage_observer_lines: list[str] = []

    for entity in damage_targets:
        parts.append(build_part("\n"))
        named_target = with_article(entity.name, capitalize=True)
        resolved_context = _resolve_combat_context(damage_context, target_text=named_target, verb="is")

        if total_damage > 0:
            should_start_combat = (
                entity.entity_id not in session.combat.engaged_entity_ids
                and (cast_type == "target" or not _is_entity_engaged_by_other_player(entity.entity_id, session))
            )
            if should_start_combat:
                start_combat(session, entity.entity_id, OPENING_ATTACKER_SKILL)
            _mark_entity_contributor(session, entity)
            dealt = _apply_entity_damage_with_reduction(entity, total_damage)
            total_damage_dealt += max(0, dealt)
            if dealt > 0 and target_lag_rounds > 0 and entity.is_alive:
                entity.skill_lag_rounds_remaining = max(entity.skill_lag_rounds_remaining, target_lag_rounds)
                entity.is_sitting = True
            if resolved_context:
                parts.append(build_part(resolved_context))
                damage_observer_lines.append(resolved_context)
            else:
                parts.extend([
                    build_part(named_target),
                    build_part(" is struck by "),
                    build_part(skill_name),
                    build_part("."),
                ])
                damage_observer_lines.append(f"{named_target} is struck by {skill_name}.")
        else:
            parts.extend([
                build_part(named_target),
                build_part(" avoids "),
                build_part(skill_name),
                build_part("."),
            ])
            damage_observer_lines.append(f"{named_target} avoids {skill_name}.")

        if entity.hit_points <= 0:
            entity.is_alive = False
            apply_entity_defeat_flags(session, entity)
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
    if observer_context:
        observer_lines.append(_render_observer_template(observer_context, actor_name))
    elif damage_observer_lines:
        observer_lines.extend(damage_observer_lines)
    else:
        damage_observer_context = _observer_context_from_player_context(damage_context, target_label)
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


def cast_spell(session: ClientSession, spell: dict, target_name: str | None = None) -> tuple[dict, bool]:
    from combat_observer import (
        _attach_room_broadcast_lines,
        _observer_context_from_player_context,
        _render_observer_template,
        _resolve_combat_context,
        _resolve_observer_action_line,
    )
    from combat_rewards import _award_shared_entity_experience, _mark_entity_contributor
    from combat_state import (
        _engage_next_targeting_entity,
        _is_entity_engaged_by_other_player,
        apply_entity_defeat_flags,
        clear_combat_if_invalid,
        get_engaged_entity,
        spawn_corpse_for_entity,
        start_combat,
    )
    from display_core import build_part
    from display_feedback import display_command_result, display_error

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
        if cast_type not in {"self", "target"}:
            return display_error(
                f"Support spell '{spell_name}' must be cast_type 'self' or 'target'.",
                session,
            ), False
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

        support_target_session = session
        if target_name:
            support_target_session, resolve_error = _resolve_room_player_selector(
                session,
                target_name,
                require_exact_name=True,
            )
            if support_target_session is None:
                return display_error(resolve_error or f"No player named '{target_name}' is here.", session), False

        support_target_name = (support_target_session.authenticated_character_name or actor_name).strip() or actor_name
        support_cast_type = "self" if support_target_session.client_id == session.client_id else "target"
        support_target_label = None if support_cast_type == "self" else support_target_name
        actor_target_text = " on yourself" if support_cast_type == "self" else f" on {support_target_name}"
        rendered_support_context = support_context
        if support_cast_type == "target":
            rendered_support_context = third_personize_text(
                support_context,
                support_target_name,
                support_target_session.player.gender,
            )

        status.mana -= mana_cost

        if support_mode == "instant":
            parts = [
                build_part("You cast "),
                build_part(spell_name),
                build_part(actor_target_text + "."),
            ]

            rolled_support_amount, _, _, _, _ = _roll_player_support_amount(session, spell, support_effect)
            target_caps = get_player_resource_caps(support_target_session)
            if support_effect == "heal":
                support_target_session.status.hit_points = min(
                    target_caps["hit_points"],
                    support_target_session.status.hit_points + rolled_support_amount,
                )
            elif support_effect == "vigor":
                support_target_session.status.vigor = min(
                    target_caps["vigor"],
                    support_target_session.status.vigor + rolled_support_amount,
                )
            else:
                support_target_session.status.mana = min(
                    target_caps["mana"],
                    support_target_session.status.mana + rolled_support_amount,
                )
            parts.extend([
                build_part("\n"),
                build_part(rendered_support_context),
            ])
            observer_lines = [
                _resolve_observer_action_line(
                    actor_name,
                    "casts",
                    spell_name,
                    support_cast_type,
                    target_label=support_target_label,
                    observer_action=observer_action,
                ),
            ]
            support_observer_context = observer_context or _observer_context_from_player_context(
                support_context,
                subject_name=support_target_name,
                subject_gender=support_target_session.player.gender,
            )
            if support_observer_context:
                observer_lines.append(_render_observer_template(
                    support_observer_context,
                    support_target_name,
                    support_target_session.player.gender,
                ))

            recipient_observer_lines: dict[str, list[str]] = {}
            if support_cast_type == "target":
                personalized_context = _resolve_combat_context(support_context, target_text="you", verb="are") or support_context
                recipient_observer_lines[support_target_session.client_id] = [
                    _resolve_observer_action_line(
                        actor_name,
                        "casts",
                        spell_name,
                        "target",
                        target_label="you",
                        observer_action=observer_action,
                    ),
                    personalized_context,
                ]

            result = display_command_result(session, parts, blank_lines_before=0)
            return _attach_room_broadcast_lines(
                result,
                observer_lines,
                recipient_lines_by_client_id=recipient_observer_lines or None,
            ), True

        _, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_player_support_amount(
            session,
            spell,
            support_effect,
        )

        refreshed = False
        for active_effect in support_target_session.active_support_effects:
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
            support_target_session.active_support_effects.append(ActiveSupportEffectState(
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
            build_part(actor_target_text + "."),
            build_part("\n"),
            build_part(rendered_support_context),
        ]
        observer_lines = [
            _resolve_observer_action_line(
                actor_name,
                "casts",
                spell_name,
                support_cast_type,
                target_label=support_target_label,
                observer_action=observer_action,
            ),
        ]
        support_observer_context = observer_context or _observer_context_from_player_context(
            support_context,
            subject_name=support_target_name,
            subject_gender=support_target_session.player.gender,
        )
        if support_observer_context:
            observer_lines.append(_render_observer_template(
                support_observer_context,
                support_target_name,
                support_target_session.player.gender,
            ))

        recipient_observer_lines: dict[str, list[str]] = {}
        if support_cast_type == "target":
            personalized_context = _resolve_combat_context(support_context, target_text="you", verb="are") or support_context
            recipient_observer_lines[support_target_session.client_id] = [
                _resolve_observer_action_line(
                    actor_name,
                    "casts",
                    spell_name,
                    "target",
                    target_label="you",
                    observer_action=observer_action,
                ),
                personalized_context,
            ]

        result = display_command_result(session, parts, blank_lines_before=0)
        return _attach_room_broadcast_lines(
            result,
            observer_lines,
            recipient_lines_by_client_id=recipient_observer_lines or None,
        ), True

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
                require_exact_name=True,
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
            should_start_combat = (
                entity.entity_id not in session.combat.engaged_entity_ids
                and not _is_entity_engaged_by_other_player(entity.entity_id, session)
            )
            if should_start_combat:
                start_combat(
                    session,
                    entity.entity_id,
                    "player",
                    trigger_player_auto_aggro=(cast_type != "aoe"),
                )
            _mark_entity_contributor(session, entity)
            dealt = _apply_entity_damage_with_reduction(entity, total_damage)
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
            apply_entity_defeat_flags(session, entity)
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
