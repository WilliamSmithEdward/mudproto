from abilities import _list_known_passives
from assets import get_gear_template_by_id
from combat_ability_effects import (
    _apply_entity_damage_with_reduction,
    _apply_entity_dealt_damage_multiplier,
    _apply_player_damage_with_reduction,
    _apply_player_dealt_damage_multiplier,
    _preview_entity_damage_with_reduction,
    _resolve_extra_hits_from_affects,
)
from combat_entity_abilities import _entity_try_cast_spell, _entity_try_use_skill
from combat_rewards import (
    _award_shared_entity_experience,
    _mark_entity_contributor,
)
from combat_state import (
    _display_peaceful_warning,
    _engage_next_targeting_entity,
    _process_combat_round_timers,
    _schedule_next_combat_round,
    apply_entity_defeat_flags,
    clear_combat_if_invalid,
    get_engaged_entities,
    spawn_corpse_for_entity,
    start_combat,
)
from combat_text import (
    append_newline_if_needed,
    build_entity_attack_parts,
    build_player_attack_parts,
)
from damage import (
    get_npc_hit_modifier,
    get_player_hit_modifier,
    resolve_weapon_verb,
    roll_hit,
    roll_npc_weapon_damage,
    roll_player_damage,
    roll_weapon_room_proc_damage,
    roll_weapon_target_proc_damage,
)
from death import build_player_death_broadcast_parts, build_player_death_mourn_parts, build_player_death_parts, handle_player_death
from display_core import build_part
from equipment_logic import (
    get_equipped_main_hand,
    get_equipped_off_hand,
    get_player_armor_class,
    get_player_effective_attribute,
    get_player_hitroll_bonus,
    get_player_weapon_damage_bonus,
)
from grammar import with_article
from models import ClientSession, EntityState, ItemState
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from session_timing import apply_lag
from targeting_entities import list_room_entities, resolve_room_entity_selector


OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"


def _get_player_unarmed_profile(session: ClientSession) -> tuple[int, int, bool]:
    player_level = max(1, int(session.player.level))

    unarmed_damage_bonus = 0
    unarmed_hit_bonus = 0
    dual_unarmed_attacks = False

    for passive in _list_known_passives(session):
        passive_damage_bonus = max(0, int(passive.get("unarmed_damage_bonus", 0)))
        scaling_attribute_id = str(passive.get("unarmed_scaling_attribute_id", "")).strip().lower()
        scaling_multiplier = max(0.0, float(passive.get("unarmed_scaling_multiplier", 0.0)))
        if scaling_attribute_id and scaling_multiplier > 0.0:
            attribute_value = get_player_effective_attribute(session, scaling_attribute_id)
            attribute_modifier = (attribute_value - 10) // 2
            passive_damage_bonus += max(0, int(attribute_modifier * scaling_multiplier))

        level_scaling_multiplier = max(0.0, float(passive.get("unarmed_level_scaling_multiplier", 0.0)))
        if level_scaling_multiplier > 0.0:
            passive_damage_bonus += max(0, int((player_level - 1) * level_scaling_multiplier))

        passive_hit_bonus = max(0, int(passive.get("unarmed_hit_roll_bonus", 0)))
        hit_scaling_attribute_id = str(passive.get("unarmed_hit_scaling_attribute_id", "")).strip().lower()
        hit_scaling_multiplier = max(0.0, float(passive.get("unarmed_hit_scaling_multiplier", 0.0)))
        if hit_scaling_attribute_id and hit_scaling_multiplier > 0.0:
            attribute_value = get_player_effective_attribute(session, hit_scaling_attribute_id)
            attribute_modifier = (attribute_value - 10) // 2
            passive_hit_bonus += max(0, int(attribute_modifier * hit_scaling_multiplier))

        hit_level_scaling_multiplier = max(0.0, float(passive.get("unarmed_hit_level_scaling_multiplier", 0.0)))
        if hit_level_scaling_multiplier > 0.0:
            passive_hit_bonus += max(0, int((player_level - 1) * hit_level_scaling_multiplier))

        unarmed_damage_bonus += passive_damage_bonus
        unarmed_hit_bonus += passive_hit_bonus
        if bool(passive.get("dual_unarmed_attacks", False)):
            dual_unarmed_attacks = True

    return unarmed_damage_bonus, unarmed_hit_bonus, dual_unarmed_attacks


def _build_player_attack_sequence(session: ClientSession, allow_off_hand: bool) -> list[ItemState | None]:
    attack_sequence: list[ItemState | None] = []

    _, _, dual_unarmed_attacks = _get_player_unarmed_profile(session)

    main_hand = get_equipped_main_hand(session)
    main_weapon = main_hand if main_hand is not None and main_hand.slot == "weapon" else None

    off_hand = get_equipped_off_hand(session)
    off_weapon = off_hand if off_hand is not None and off_hand.slot == "weapon" else None
    if main_weapon is not None and off_weapon is not None and off_weapon.item_id == main_weapon.item_id:
        off_weapon = None

    attack_sequence.append(main_weapon)

    if allow_off_hand and off_weapon is not None:
        attack_sequence.append(off_weapon)
    elif allow_off_hand and main_weapon is None and dual_unarmed_attacks:
        attack_sequence.append(None)

    return attack_sequence


def _render_weapon_proc_message(template_text: str, *, actor_name: str, weapon_name: str) -> str:
    return (
        str(template_text).strip()
        .replace("[actor_name]", actor_name.strip() or "Someone")
        .replace("[weapon_name]", weapon_name.strip() or "weapon")
    )


def _queue_private_combat_message(session: ClientSession, message: str) -> None:
    cleaned = str(message).strip()
    if not cleaned:
        return
    session.pending_private_lines.append([
        {"text": cleaned, "fg": resolve_display_color("combat.proc.message"), "bold": True},
    ])


def _append_inline_proc_message(parts: list[dict], message: str) -> None:
    cleaned = str(message).strip()
    if not cleaned:
        return
    append_newline_if_needed(parts)
    proc_part = build_part(cleaned, "combat.proc.message", True)
    proc_part["observer_plain"] = True
    parts.append(proc_part)


def _record_observer_broadcast_line(room_broadcast_lines: list[list[dict]], message: str) -> None:
    cleaned = str(message).strip()
    if not cleaned:
        return
    room_broadcast_lines.append([
        {"text": cleaned, "fg": resolve_display_color("combat.observer.message"), "bold": False},
    ])


def _resolve_entity_defeat(
    session: ClientSession,
    entity: EntityState,
    parts: list[dict],
    *,
    active_target_entity_ids: set[str] | None = None,
    allow_turn_message: bool = False,
) -> bool:
    from display_core import build_part

    if entity.hit_points > 0 or not entity.is_alive:
        return False

    entity.is_alive = False
    entity.combat_target_player_key = ""
    apply_entity_defeat_flags(session, entity)
    spawn_corpse_for_entity(session, entity)
    _award_shared_entity_experience(session, entity, parts, build_part)

    append_newline_if_needed(parts)
    parts.extend([
        build_part(with_article(entity.name, capitalize=True, is_named=getattr(entity, "is_named", None)), "combat.death", True),
        build_part(" is dead!", "combat.death", True),
    ])

    if entity.entity_id in session.combat.engaged_entity_ids:
        session.combat.engaged_entity_ids.discard(entity.entity_id)
        if allow_turn_message:
            next_target = _engage_next_targeting_entity(
                session,
                entity.entity_id,
                active_target_entity_ids=active_target_entity_ids,
            )
            if next_target is not None:
                append_newline_if_needed(parts)
                parts.extend([
                    build_part("You turn to ", "combat.turn.text"),
                    build_part(with_article(next_target.name, is_named=getattr(next_target, "is_named", None))),
                    build_part(".", "combat.turn.text"),
                ])

    return True


def _apply_weapon_room_damage_proc(
    session: ClientSession,
    weapon: ItemState | None,
    primary_target: EntityState,
    parts: list[dict],
    room_broadcast_lines: list[list[dict]],
) -> None:
    triggered, proc_damage = roll_weapon_room_proc_damage(weapon)
    if not triggered or weapon is None:
        return

    proc_damage = _apply_player_dealt_damage_multiplier(session, proc_damage)

    actor_name = session.authenticated_character_name or "Someone"
    weapon_name = weapon.name.strip() or "weapon"
    player_message = _render_weapon_proc_message(
        str(getattr(weapon, "on_hit_room_damage_message", "")),
        actor_name=actor_name,
        weapon_name=weapon_name,
    ) or f"{weapon_name} erupts with searing sunlight, scorching every enemy in the room!"
    _append_inline_proc_message(parts, player_message)

    for target in list_room_entities(session, session.player.current_room_id):
        if not getattr(target, "is_alive", False):
            continue
        if bool(getattr(target, "is_ally", False)) or bool(getattr(target, "is_peaceful", False)):
            continue

        _mark_entity_contributor(session, target)
        _apply_entity_damage_with_reduction(target, proc_damage)

        if target.entity_id != primary_target.entity_id and target.hit_points > 0:
            session.combat.engaged_entity_ids.add(target.entity_id)

        if target.entity_id != primary_target.entity_id:
            _resolve_entity_defeat(session, target, parts, allow_turn_message=False)


def _apply_weapon_target_damage_proc(
    session: ClientSession,
    weapon: ItemState | None,
    target: EntityState,
    parts: list[dict],
) -> None:
    if weapon is None or not getattr(target, "is_alive", False):
        return

    triggered, proc_damage = roll_weapon_target_proc_damage(weapon)
    if not triggered:
        return

    proc_damage = _apply_player_dealt_damage_multiplier(session, proc_damage)

    actor_name = session.authenticated_character_name or "Someone"
    weapon_name = weapon.name.strip() or "weapon"
    player_message = _render_weapon_proc_message(
        str(getattr(weapon, "on_hit_target_damage_message", "")),
        actor_name=actor_name,
        weapon_name=weapon_name,
    ) or f"{weapon_name} flashes with focused sunlight and strikes your foe again!"
    _append_inline_proc_message(parts, player_message)
    _mark_entity_contributor(session, target)
    _apply_entity_damage_with_reduction(target, proc_damage)


def begin_attack(session: ClientSession, target_name: str) -> dict | list[dict]:
    from display_feedback import display_error, display_force_prompt

    clear_combat_if_invalid(session)
    entity, resolve_error = resolve_room_entity_selector(
        session,
        session.player.current_room_id,
        target_name,
        living_only=True,
    )

    if entity is None:
        return display_error(resolve_error or f"No target named '{target_name}' is here.", session)
    if bool(getattr(entity, "is_peaceful", False)):
        return _display_peaceful_warning(session, entity)

    started = start_combat(session, entity.entity_id, OPENING_ATTACKER_PLAYER)
    if not started:
        return display_error(f"{entity.name} is already engaged with another target.", session)

    immediate_round = resolve_combat_round(session)
    if immediate_round is not None:
        apply_lag(session, COMBAT_ROUND_INTERVAL_SECONDS)
        if session.pending_death_logout:
            return immediate_round
        return [immediate_round, display_force_prompt(session)]

    return display_error(f"You fail to engage {entity.name}.", session)


def _apply_player_attacks(
    session: ClientSession,
    entity: EntityState,
    parts: list[dict],
    room_broadcast_lines: list[list[dict]],
    allow_off_hand: bool,
) -> None:
    attack_sequence = _build_player_attack_sequence(session, allow_off_hand)
    unarmed_damage_bonus, unarmed_hit_bonus, _ = _get_player_unarmed_profile(session)
    equipment_hit_bonus = get_player_hitroll_bonus(session)
    equipment_damage_bonus = get_player_weapon_damage_bonus(session)

    for weapon in attack_sequence:
        if not entity.is_alive:
            break

        append_newline_if_needed(parts)

        hit_modifier = get_player_hit_modifier(
            weapon,
            player_level=session.player.level,
            unarmed_hit_bonus=unarmed_hit_bonus,
        ) + equipment_hit_bonus
        if not roll_hit(hit_modifier, entity.armor_class):
            miss_verb = resolve_weapon_verb(weapon.weapon_type) if weapon is not None else "hit"
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
                target_is_named=getattr(entity, "is_named", None),
            ))
            continue

        rolled_damage, weapon_name, attack_verb = roll_player_damage(
            session.player_combat,
            weapon,
            player_level=session.player.level,
            unarmed_damage_bonus=unarmed_damage_bonus,
        )
        rolled_damage += equipment_damage_bonus
        rolled_damage = _apply_player_dealt_damage_multiplier(session, rolled_damage)
        _mark_entity_contributor(session, entity)
        preview_damage = _preview_entity_damage_with_reduction(entity, rolled_damage)
        applied_damage = _apply_entity_damage_with_reduction(entity, rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=preview_damage,
            target_max_hp=entity.max_hit_points,
            target_is_named=getattr(entity, "is_named", None),
        ))
        _apply_weapon_room_damage_proc(session, weapon, entity, parts, room_broadcast_lines)
        _apply_weapon_target_damage_proc(session, weapon, entity, parts)

        if entity.hit_points <= 0:
            break

    # Extra unarmed hits from affect-based skills.
    affect_extra_main, affect_extra_off, affect_extra_unarmed = _resolve_extra_hits_from_affects(
        list(session.active_affects),
        player_level=max(1, int(session.player.level)),
    )
    extra_unarmed = affect_extra_unarmed

    main_hand = get_equipped_main_hand(session)
    main_weapon = main_hand if main_hand is not None and main_hand.slot == "weapon" else None
    off_hand = get_equipped_off_hand(session)
    off_weapon = off_hand if off_hand is not None and off_hand.slot == "weapon" else None
    if main_weapon is not None and off_weapon is not None and off_weapon.item_id == main_weapon.item_id:
        off_weapon = None

    for _ in range(affect_extra_main):
        if not entity.is_alive:
            break
        append_newline_if_needed(parts)
        hit_modifier = get_player_hit_modifier(
            main_weapon,
            player_level=session.player.level,
            unarmed_hit_bonus=unarmed_hit_bonus,
        ) + equipment_hit_bonus
        if not roll_hit(hit_modifier, entity.armor_class):
            miss_verb = resolve_weapon_verb(main_weapon.weapon_type) if main_weapon is not None else "hit"
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
            ))
            continue
        rolled_damage, _, attack_verb = roll_player_damage(
            session.player_combat,
            main_weapon,
            player_level=session.player.level,
            unarmed_damage_bonus=unarmed_damage_bonus,
        )
        rolled_damage += equipment_damage_bonus
        rolled_damage = _apply_player_dealt_damage_multiplier(session, rolled_damage)
        _mark_entity_contributor(session, entity)
        preview_damage = _preview_entity_damage_with_reduction(entity, rolled_damage)
        applied_damage = _apply_entity_damage_with_reduction(entity, rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=preview_damage,
            target_max_hp=entity.max_hit_points,
        ))
        if entity.hit_points <= 0:
            break

    for _ in range(affect_extra_off):
        if not entity.is_alive:
            break
        append_newline_if_needed(parts)
        hit_modifier = get_player_hit_modifier(
            off_weapon,
            player_level=session.player.level,
            unarmed_hit_bonus=unarmed_hit_bonus,
        ) + equipment_hit_bonus
        if not roll_hit(hit_modifier, entity.armor_class):
            miss_verb = resolve_weapon_verb(off_weapon.weapon_type) if off_weapon is not None else "hit"
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
            ))
            continue
        rolled_damage, _, attack_verb = roll_player_damage(
            session.player_combat,
            off_weapon,
            player_level=session.player.level,
            unarmed_damage_bonus=unarmed_damage_bonus,
        )
        rolled_damage += equipment_damage_bonus
        rolled_damage = _apply_player_dealt_damage_multiplier(session, rolled_damage)
        _mark_entity_contributor(session, entity)
        preview_damage = _preview_entity_damage_with_reduction(entity, rolled_damage)
        applied_damage = _apply_entity_damage_with_reduction(entity, rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=preview_damage,
            target_max_hp=entity.max_hit_points,
        ))
        if entity.hit_points <= 0:
            break

    for _ in range(extra_unarmed):
        if not entity.is_alive:
            break
        append_newline_if_needed(parts)
        hit_modifier = get_player_hit_modifier(
            None,
            player_level=session.player.level,
            unarmed_hit_bonus=unarmed_hit_bonus,
        ) + equipment_hit_bonus
        if not roll_hit(hit_modifier, entity.armor_class):
            parts.extend(build_player_attack_parts(
                entity_name=entity.name,
                attack_verb="hit",
                damage=0,
                target_max_hp=entity.max_hit_points,
                target_is_named=getattr(entity, "is_named", None),
            ))
            continue
        rolled_damage, _, attack_verb = roll_player_damage(
            session.player_combat,
            None,
            player_level=session.player.level,
            unarmed_damage_bonus=unarmed_damage_bonus,
        )
        rolled_damage += equipment_damage_bonus
        rolled_damage = _apply_player_dealt_damage_multiplier(session, rolled_damage)
        _mark_entity_contributor(session, entity)
        preview_damage = _preview_entity_damage_with_reduction(entity, rolled_damage)
        applied_damage = _apply_entity_damage_with_reduction(entity, rolled_damage)
        parts.extend(build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=preview_damage,
            target_max_hp=entity.max_hit_points,
            target_is_named=getattr(entity, "is_named", None),
        ))
        if entity.hit_points <= 0:
            break


def _apply_entity_attacks(session: ClientSession, attacker: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    status = session.status
    player_armor_class = get_player_armor_class(session)

    def _resolve_npc_weapon_template(template_id: str) -> dict | None:
        normalized_template_id = template_id.strip()
        if not normalized_template_id:
            return None
        template = get_gear_template_by_id(normalized_template_id)
        if template is None:
            return None
        if str(template.get("slot", "")).strip().lower() != "weapon":
            return None
        return template

    entity = attacker
    if not entity.is_alive:
        return

    can_use_special_action = True
    if entity.skill_lag_rounds_remaining > 0:
        entity.skill_lag_rounds_remaining -= 1
        can_use_special_action = False
    if entity.spell_lag_rounds_remaining > 0:
        entity.spell_lag_rounds_remaining -= 1
        can_use_special_action = False

    if entity.is_sitting and can_use_special_action:
        entity.is_sitting = False
        append_newline_if_needed(parts)
        parts.extend([
            build_part(with_article(entity.name, capitalize=True, is_named=getattr(entity, "is_named", None))),
            build_part(" stands up."),
        ])
        can_use_special_action = False

    # Allow at most one special action (spell or skill) per round.
    # Keep existing priority: try spell first, then skill if no spell fired.
    if can_use_special_action:
        casted_spell = _entity_try_cast_spell(session, entity, parts)
        if not casted_spell:
            _entity_try_use_skill(session, entity, parts)

    main_hand_weapon = _resolve_npc_weapon_template(entity.main_hand_weapon_template_id)
    off_hand_weapon = _resolve_npc_weapon_template(entity.off_hand_weapon_template_id)

    for _ in range(max(1, entity.attacks_per_round)):
        append_newline_if_needed(parts)

        main_hit_modifier = get_npc_hit_modifier(entity, main_hand_weapon, off_hand=False)
        if not roll_hit(main_hit_modifier, player_armor_class):
            miss_verb = (
                resolve_weapon_verb(str(main_hand_weapon.get("weapon_type", "unarmed")))
                if main_hand_weapon is not None
                else "hit"
            )
            parts.extend(build_entity_attack_parts(
                entity_name=entity.name,
                entity_pronoun_possessive=entity.pronoun_possessive,
                attack_verb=miss_verb,
                damage=0,
                entity_is_named=getattr(entity, "is_named", None),
            ))
            continue

        attack_damage, attack_verb = roll_npc_weapon_damage(entity, main_hand_weapon)
        attack_damage = _apply_entity_dealt_damage_multiplier(entity, attack_damage)
        applied_damage = _apply_player_damage_with_reduction(session, attack_damage)
        parts.extend(build_entity_attack_parts(
            entity_name=entity.name,
            entity_pronoun_possessive=entity.pronoun_possessive,
            attack_verb=attack_verb,
            damage=applied_damage,
            entity_is_named=getattr(entity, "is_named", None),
        ))
        if status.hit_points <= 0:
            return

    if allow_off_hand:
        off_hand_swings = max(0, entity.off_hand_attacks_per_round)
        for _ in range(off_hand_swings):
            if status.hit_points <= 0:
                return
            append_newline_if_needed(parts)

            off_hit_modifier = get_npc_hit_modifier(entity, off_hand_weapon, off_hand=True)
            if not roll_hit(off_hit_modifier, player_armor_class):
                miss_verb = (
                    resolve_weapon_verb(str(off_hand_weapon.get("weapon_type", "unarmed")))
                    if off_hand_weapon is not None
                    else "hit"
                )
                parts.extend(build_entity_attack_parts(
                    entity_name=entity.name,
                    entity_pronoun_possessive=entity.pronoun_possessive,
                    attack_verb=miss_verb,
                    damage=0,
                    entity_is_named=getattr(entity, "is_named", None),
                ))
                continue

            off_hand_damage, off_attack_verb = roll_npc_weapon_damage(entity, off_hand_weapon)
            off_hand_damage = _apply_entity_dealt_damage_multiplier(entity, off_hand_damage)
            applied_damage = _apply_player_damage_with_reduction(session, off_hand_damage)
            parts.extend(build_entity_attack_parts(
                entity_name=entity.name,
                entity_pronoun_possessive=entity.pronoun_possessive,
                attack_verb=off_attack_verb,
                damage=applied_damage,
                entity_is_named=getattr(entity, "is_named", None),
            ))
            if status.hit_points <= 0:
                return


def resolve_combat_round(
    session: ClientSession,
    *,
    allowed_entity_retaliation_ids: set[str] | None = None,
) -> dict | None:
    from display_core import build_part
    from display_feedback import display_combat_round_result

    clear_combat_if_invalid(session)

    engaged_entities = get_engaged_entities(session)
    if not engaged_entities:
        return None

    entity = engaged_entities[0]  # Primary target for melee combat
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        clear_combat_if_invalid(session)
        return None

    parts: list[dict] = []
    room_broadcast_lines: list[list[dict]] = []
    status = session.status
    opening_attacker = session.combat.opening_attacker
    is_opening_round = opening_attacker is not None

    retaliating_entities = [
        engaged
        for engaged in engaged_entities
        if allowed_entity_retaliation_ids is None or engaged.entity_id in allowed_entity_retaliation_ids
    ]

    if opening_attacker == OPENING_ATTACKER_ENTITY:
        for retaliating_entity in retaliating_entities:
            if not retaliating_entity.is_alive:
                continue
            _apply_entity_attacks(session, retaliating_entity, parts, allow_off_hand=False)
            if status.hit_points <= 0:
                break
    else:
        if session.combat.skip_melee_rounds > 0:
            session.combat.skip_melee_rounds -= 1
        else:
            allow_off_hand = not (is_opening_round and opening_attacker == OPENING_ATTACKER_PLAYER)
            _apply_player_attacks(session, entity, parts, room_broadcast_lines, allow_off_hand=allow_off_hand)

    # Mark entity dead if it reached 0 HP, but don't return yet — let the round finish.
    entity_died_this_round = _resolve_entity_defeat(
        session,
        entity,
        parts,
        active_target_entity_ids=allowed_entity_retaliation_ids,
        allow_turn_message=True,
    )

    # Continue retaliation phase after player-side output has been assembled.
    if opening_attacker is not None:
        session.combat.opening_attacker = None
    else:
        current_engaged_entities = get_engaged_entities(session)
        current_retaliating_entities = [
            engaged
            for engaged in current_engaged_entities
            if allowed_entity_retaliation_ids is None or engaged.entity_id in allowed_entity_retaliation_ids
        ]
        for retaliating_entity in current_retaliating_entities:
            if not retaliating_entity.is_alive:
                continue
            _apply_entity_attacks(session, retaliating_entity, parts, allow_off_hand=True)
            if status.hit_points <= 0:
                break

    # Tick support effects, affects, and cooldowns *after* attacks so that
    # a duration_rounds value of N gives N full rounds of benefit.
    _process_combat_round_timers(session, engaged_entities)

    # Now display player death if it occurred this round.

    if status.hit_points <= 0:
        handle_player_death(session)

        append_newline_if_needed(parts)
        parts.extend(build_player_death_parts())
        parts.extend(build_player_death_mourn_parts())

        result = display_combat_round_result(session, parts)
        payload = result.get("payload") if isinstance(result, dict) else None
        if isinstance(payload, dict):
            actor_name = session.authenticated_character_name or "Someone"
            death_broadcast_lines: list[list[dict]] = []
            if entity_died_this_round:
                death_broadcast_lines.append([
                    build_part(with_article(entity.name, capitalize=True, is_named=getattr(entity, "is_named", None)), "combat.death", True),
                    build_part(" is dead!", "combat.death", True),
                ])
            death_broadcast_lines.append(build_player_death_broadcast_parts(actor_name))
            payload["room_broadcast_lines"] = death_broadcast_lines
            if room_broadcast_lines:
                payload["additional_room_broadcast_lines"] = room_broadcast_lines

        return result

    result = display_combat_round_result(session, parts)
    payload = result.get("payload") if isinstance(result, dict) else None
    if isinstance(payload, dict) and room_broadcast_lines:
        payload["additional_room_broadcast_lines"] = room_broadcast_lines

    _schedule_next_combat_round(session)
    return result