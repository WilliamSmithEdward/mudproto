"""Companion combat AI: heal, assist, and attack execution for enlisted companions.

Companions act inside their owner's combat round, immediately after the owner's
attacks. They have no engagement state of their own; the target is derived from
the owner's engagement each round. All companion damage credits the owner as
the experience contributor.
"""

import random

from assets import get_gear_template_by_id, get_skill_by_id, get_spell_by_id
from combat_ability_effects import (
    _apply_ability_affects,
    _apply_entity_damage_with_reduction,
    _apply_entity_dealt_damage_multiplier,
    _apply_entity_secondary_restore,
    _apply_entity_skill_lag,
    _apply_player_secondary_restore,
    _preview_entity_damage_with_reduction,
    _resolve_entity_damage_scaling_bonus,
    _resolve_entity_skill_scale_bonus,
    _roll_entity_support_amount,
    _set_entity_skill_cooldown,
    _set_entity_spell_cooldown,
)
from combat_rewards import _mark_entity_contributor
from combat_text import _choose_severity, append_newline_if_needed
from companions import list_owned_companions_in_room
from damage import get_npc_hit_modifier, roll_hit, roll_npc_weapon_damage, roll_skill_damage, roll_spell_damage
from display_core import build_part
from grammar import to_third_person, with_article
from models import ClientSession, EntityState
from player_resources import get_player_resource_caps
from settings import COMPANION_HEAL_THRESHOLD


def _companion_part(text: str, fg: str = "display_core.default_fg", bold: bool = False) -> dict:
    """Build a display part tagged as belonging to the actor's player phase.

    The room round display splits actor output from enemy retaliation by line
    prefix; companion lines start with the companion's name, so they carry an
    explicit marker to stay in the player phase.
    """
    part = build_part(text, fg, bold)
    part["player_phase"] = True
    return part


def _companion_label(companion: EntityState) -> str:
    return with_article(companion.name, capitalize=True, is_named=companion.is_named)


def _target_label(target: EntityState, *, capitalize: bool = False) -> str:
    return with_article(target.name, capitalize=capitalize, is_named=getattr(target, "is_named", None))


def _session_display_name(session: ClientSession) -> str:
    return (session.authenticated_character_name or "").strip() or "someone"


def _list_heal_candidates(owner_session: ClientSession) -> list[ClientSession]:
    from targeting_follow import _list_group_member_sessions

    room_id = owner_session.player.current_room_id
    candidates: list[ClientSession] = []
    seen_keys: set[str] = set()
    _, member_sessions = _list_group_member_sessions(owner_session)
    for member in [owner_session] + member_sessions:
        member_key = (member.player_state_key or member.client_id).strip().lower()
        if not member_key or member_key in seen_keys:
            continue
        seen_keys.add(member_key)
        if not member.is_authenticated or member.pending_death_logout:
            continue
        if member.player.current_room_id != room_id:
            continue
        if member.status.hit_points <= 0:
            continue
        candidates.append(member)
    return candidates


def _lowest_health_heal_target(owner_session: ClientSession) -> tuple[ClientSession | EntityState | None, float]:
    """Pick the most hurt ally: the owner, in-room group members, or any of
    their companions (the healer itself included)."""
    best_target: ClientSession | EntityState | None = None
    best_ratio = 1.0
    heal_candidates = _list_heal_candidates(owner_session)
    for member in heal_candidates:
        caps = get_player_resource_caps(member)
        cap_hit_points = max(1, int(caps.get("hit_points", 1)))
        ratio = member.status.hit_points / cap_hit_points
        if ratio < best_ratio:
            best_target = member
            best_ratio = ratio

    seen_companion_ids: set[str] = set()
    for member in heal_candidates:
        for companion in list_owned_companions_in_room(member):
            if companion.entity_id in seen_companion_ids:
                continue
            seen_companion_ids.add(companion.entity_id)
            if companion.hit_points <= 0 or companion.max_hit_points <= 0:
                continue
            ratio = companion.hit_points / companion.max_hit_points
            if ratio < best_ratio:
                best_target = companion
                best_ratio = ratio
    return best_target, best_ratio


def _pick_target_heal_spell(companion: EntityState) -> dict | None:
    for spell_id in companion.spell_ids:
        spell = get_spell_by_id(spell_id)
        if spell is None:
            continue
        if str(spell.get("spell_type", "")).strip().lower() != "support":
            continue
        if str(spell.get("cast_type", "")).strip().lower() != "target":
            continue
        if str(spell.get("support_effect", "")).strip().lower() != "heal":
            continue
        if str(spell.get("support_mode", "")).strip().lower() != "instant":
            continue
        normalized_spell_id = str(spell.get("spell_id", "")).strip()
        if normalized_spell_id and companion.spell_cooldowns.get(normalized_spell_id, 0) > 0:
            continue
        if companion.mana < max(0, int(spell.get("mana_cost", 0))):
            continue
        return spell
    return None


def _pick_damage_spell(companion: EntityState) -> dict | None:
    available_spells: list[dict] = []
    for spell_id in companion.spell_ids:
        spell = get_spell_by_id(spell_id)
        if spell is None:
            continue
        if str(spell.get("spell_type", "")).strip().lower() != "damage":
            continue
        if str(spell.get("cast_type", "")).strip().lower() != "target":
            continue
        normalized_spell_id = str(spell.get("spell_id", "")).strip()
        if normalized_spell_id and companion.spell_cooldowns.get(normalized_spell_id, 0) > 0:
            continue
        if companion.mana < max(0, int(spell.get("mana_cost", 0))):
            continue
        available_spells.append(spell)
    if not available_spells:
        return None
    return random.choice(available_spells)


def _pick_damage_skill(companion: EntityState) -> dict | None:
    available_skills: list[dict] = []
    for skill_id in companion.skill_ids:
        skill = get_skill_by_id(skill_id)
        if skill is None:
            continue
        if str(skill.get("skill_type", "")).strip().lower() != "damage":
            continue
        if str(skill.get("cast_type", "")).strip().lower() != "target":
            continue
        normalized_skill_id = str(skill.get("skill_id", "")).strip()
        if normalized_skill_id and companion.skill_cooldowns.get(normalized_skill_id, 0) > 0:
            continue
        if companion.vigor < max(0, int(skill.get("vigor_cost", 0))):
            continue
        available_skills.append(skill)
    if not available_skills:
        return None
    return random.choice(available_skills)


def _cast_companion_heal(
    owner_session: ClientSession,
    companion: EntityState,
    spell: dict,
    heal_target: ClientSession | EntityState,
    parts: list[dict],
) -> None:
    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    support_context = str(spell.get("support_context", "")).strip()
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    companion.mana = max(0, companion.mana - mana_cost)

    rolled_amount, _, _, _, _ = _roll_entity_support_amount(companion, spell, "heal")
    target_is_owner = False
    target_is_self = False
    if isinstance(heal_target, EntityState):
        restored_amount = _apply_entity_secondary_restore(heal_target, "heal", rolled_amount)
        target_is_self = heal_target.entity_id == companion.entity_id
        target_text = "themselves" if target_is_self else _target_label(heal_target)
    else:
        restored_amount = _apply_player_secondary_restore(heal_target, "heal", rolled_amount)
        target_is_owner = heal_target.client_id == owner_session.client_id
        target_text = "you" if target_is_owner else _session_display_name(heal_target)
    _apply_ability_affects(actor=companion, target=heal_target, ability=spell, affect_target="target")
    _set_entity_spell_cooldown(companion, spell)

    append_newline_if_needed(parts)
    parts.extend([
        _companion_part(_companion_label(companion)),
        _companion_part(" casts "),
        _companion_part(spell_name),
        _companion_part(f" on {target_text}"),
        _companion_part("."),
    ])
    if restored_amount > 0:
        append_newline_if_needed(parts)
        if target_is_owner and support_context:
            parts.append(_companion_part(support_context, "combat_rewards.text"))
        elif target_is_owner:
            parts.append(_companion_part("Your wounds knit closed.", "combat_rewards.text"))
        elif target_is_self:
            pronoun = companion.pronoun_possessive.strip().lower() or "its"
            parts.append(_companion_part(f"{pronoun.capitalize()} wounds knit closed.", "combat_rewards.text"))
        else:
            capitalized_target = target_text[0].upper() + target_text[1:] if target_text else target_text
            parts.append(_companion_part(f"{capitalized_target}'s wounds knit closed.", "combat_rewards.text"))


def _cast_companion_damage_spell(
    owner_session: ClientSession,
    companion: EntityState,
    spell: dict,
    target: EntityState,
    parts: list[dict],
) -> None:
    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    element = str(spell.get("element", "arcane")).strip().lower() or "arcane"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    companion.mana = max(0, companion.mana - mana_cost)

    spell_damage = roll_spell_damage(spell, _resolve_entity_damage_scaling_bonus(companion, spell))
    spell_damage = _apply_entity_dealt_damage_multiplier(companion, spell_damage, damage_element=element)

    append_newline_if_needed(parts)
    parts.extend([
        _companion_part(_companion_label(companion)),
        _companion_part(" casts "),
        _companion_part(spell_name),
        _companion_part(" at "),
        _companion_part(_target_label(target)),
        _companion_part("!"),
    ])

    damage_dealt = 0
    if spell_damage > 0:
        _mark_entity_contributor(owner_session, target)
        damage_dealt = _apply_entity_damage_with_reduction(target, spell_damage, damage_element=element)
        if damage_dealt > 0:
            _apply_ability_affects(actor=companion, target=target, ability=spell, affect_target="target")

    append_newline_if_needed(parts)
    if damage_dealt > 0:
        parts.extend([
            _companion_part(_target_label(target, capitalize=True)),
            _companion_part(" is struck by "),
            _companion_part(spell_name),
            _companion_part("."),
        ])
    else:
        parts.extend([
            _companion_part(_target_label(target, capitalize=True)),
            _companion_part(" resists "),
            _companion_part(spell_name),
            _companion_part("."),
        ])

    _set_entity_spell_cooldown(companion, spell)


def _use_companion_damage_skill(
    owner_session: ClientSession,
    companion: EntityState,
    skill: dict,
    target: EntityState,
    parts: list[dict],
) -> None:
    skill_name = str(skill.get("name", "Skill")).strip() or "Skill"
    element = str(skill.get("element", "physical")).strip().lower() or "physical"
    vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
    companion.vigor = max(0, companion.vigor - vigor_cost)

    total_damage = roll_skill_damage(skill) + _resolve_entity_skill_scale_bonus(companion, skill)
    total_damage = _apply_entity_dealt_damage_multiplier(companion, total_damage, damage_element=element)

    append_newline_if_needed(parts)
    parts.extend([
        _companion_part(_companion_label(companion)),
        _companion_part(" uses "),
        _companion_part(skill_name),
        _companion_part(" on "),
        _companion_part(_target_label(target)),
        _companion_part("!"),
    ])

    damage_dealt = 0
    if total_damage > 0:
        _mark_entity_contributor(owner_session, target)
        damage_dealt = _apply_entity_damage_with_reduction(target, total_damage, damage_element=element)
        if damage_dealt > 0:
            _apply_ability_affects(actor=companion, target=target, ability=skill, affect_target="target")
            target_lag_rounds = max(0, int(skill.get("target_lag_rounds", 0)))
            if target_lag_rounds > 0:
                target.skill_lag_rounds_remaining = max(target.skill_lag_rounds_remaining, target_lag_rounds)

    append_newline_if_needed(parts)
    if damage_dealt > 0:
        parts.extend([
            _companion_part(_target_label(target, capitalize=True)),
            _companion_part(" is hit by "),
            _companion_part(skill_name),
            _companion_part("."),
        ])
    else:
        parts.extend([
            _companion_part(_target_label(target, capitalize=True)),
            _companion_part(" avoids "),
            _companion_part(skill_name),
            _companion_part("."),
        ])

    _set_entity_skill_cooldown(companion, skill)
    _apply_entity_skill_lag(companion, skill)


def _build_companion_attack_parts(companion: EntityState, target: EntityState, attack_verb: str, damage: int) -> list[dict]:
    severity = _choose_severity(damage, target.max_hit_points)
    subject = _companion_label(companion)
    target_text = _target_label(target)

    parts: list[dict] = []
    if severity == "miss":
        parts.extend([
            _companion_part(subject),
            _companion_part(" misses "),
            _companion_part(target_text),
            _companion_part("."),
        ])
        return parts

    if severity == "barely":
        parts.extend([
            _companion_part(subject),
            _companion_part(" barely "),
            _companion_part(to_third_person(attack_verb)),
            _companion_part(" "),
            _companion_part(target_text),
            _companion_part("."),
        ])
        return parts

    if severity in {"normal", "hard", "extreme"}:
        parts.extend([
            _companion_part(subject),
            _companion_part(" "),
            _companion_part(to_third_person(attack_verb)),
            _companion_part(" "),
            _companion_part(target_text),
        ])
        if severity == "hard":
            parts.append(_companion_part(" hard"))
        elif severity == "extreme":
            parts.append(_companion_part(" extremely hard"))
        parts.append(_companion_part("."))
        return parts

    top_verb = {
        "massacre": "massacres",
        "annihilate": "annihilates",
        "obliterate": "obliterates",
    }.get(severity, to_third_person(attack_verb))
    pronoun = companion.pronoun_possessive.strip().lower() or "its"
    parts.extend([
        _companion_part(subject),
        _companion_part(" "),
        _companion_part(top_verb),
        _companion_part(" "),
        _companion_part(target_text),
        _companion_part(f" with {pronoun} "),
        _companion_part(attack_verb),
        _companion_part("."),
    ])
    return parts


def _resolve_companion_weapon_template(template_id: str) -> dict | None:
    normalized_template_id = str(template_id).strip()
    if not normalized_template_id:
        return None
    template = get_gear_template_by_id(normalized_template_id)
    if template is None:
        return None
    if str(template.get("slot", "")).strip().lower() != "weapon":
        return None
    return template


def _apply_companion_melee(
    owner_session: ClientSession,
    companion: EntityState,
    target: EntityState,
    parts: list[dict],
) -> None:
    main_hand_weapon = _resolve_companion_weapon_template(companion.main_hand_weapon_template_id)

    for _ in range(max(1, companion.attacks_per_round)):
        if not target.is_alive or target.hit_points <= 0:
            break

        append_newline_if_needed(parts)
        hit_modifier = get_npc_hit_modifier(companion, main_hand_weapon, off_hand=False)
        if not roll_hit(hit_modifier, target.armor_class):
            miss_verb = (
                str(main_hand_weapon.get("weapon_type", "unarmed")).strip()
                if main_hand_weapon is not None
                else "hit"
            )
            parts.extend(_build_companion_attack_parts(companion, target, miss_verb, 0))
            continue

        attack_damage, attack_verb = roll_npc_weapon_damage(companion, main_hand_weapon)
        attack_damage = _apply_entity_dealt_damage_multiplier(companion, attack_damage)
        _mark_entity_contributor(owner_session, target)
        preview_damage = _preview_entity_damage_with_reduction(target, attack_damage)
        _apply_entity_damage_with_reduction(target, attack_damage)
        parts.extend(_build_companion_attack_parts(companion, target, attack_verb, preview_damage))


def resolve_companion_round(
    owner_session: ClientSession,
    companion: EntityState,
    target_entity: EntityState | None,
    parts: list[dict],
) -> None:
    """Run one companion's turn inside the owner's combat round."""
    if not companion.is_alive or companion.hit_points <= 0:
        return
    if companion.room_id != owner_session.player.current_room_id:
        return

    if companion.rescue_guard_rounds_remaining > 0:
        companion.rescue_guard_rounds_remaining -= 1

    can_use_special_action = True
    if companion.skill_lag_rounds_remaining > 0:
        companion.skill_lag_rounds_remaining -= 1
        can_use_special_action = False
    if companion.spell_lag_rounds_remaining > 0:
        companion.spell_lag_rounds_remaining -= 1
        can_use_special_action = False

    if companion.is_sitting and can_use_special_action:
        companion.is_sitting = False
        append_newline_if_needed(parts)
        parts.extend([
            _companion_part(_companion_label(companion)),
            _companion_part(" stands up."),
        ])
        can_use_special_action = False

    # Heal first: deterministic whenever a group member is hurt enough.
    if can_use_special_action:
        heal_target, health_ratio = _lowest_health_heal_target(owner_session)
        if heal_target is not None and health_ratio < COMPANION_HEAL_THRESHOLD:
            heal_spell = _pick_target_heal_spell(companion)
            if heal_spell is not None:
                _cast_companion_heal(owner_session, companion, heal_spell, heal_target, parts)
                can_use_special_action = False

    if target_entity is None or not target_entity.is_alive or target_entity.hit_points <= 0:
        return

    if can_use_special_action and companion.spell_ids:
        spell_chance = max(0.0, min(1.0, float(companion.spell_use_chance)))
        if random.random() < spell_chance:
            damage_spell = _pick_damage_spell(companion)
            if damage_spell is not None:
                _cast_companion_damage_spell(owner_session, companion, damage_spell, target_entity, parts)
                can_use_special_action = False

    if can_use_special_action and companion.skill_ids:
        skill_chance = max(0.0, min(1.0, float(companion.skill_use_chance)))
        if random.random() < skill_chance:
            damage_skill = _pick_damage_skill(companion)
            if damage_skill is not None:
                _use_companion_damage_skill(owner_session, companion, damage_skill, target_entity, parts)
                can_use_special_action = False

    if target_entity.is_alive and target_entity.hit_points > 0:
        _apply_companion_melee(owner_session, companion, target_entity, parts)
