"""Shared scaling, restore, cooldown, and support-effect helpers for combat abilities."""

import random

from attribute_config import (
    get_affect_template_by_id,
    get_posture_dealt_damage_multiplier,
    get_posture_received_damage_multiplier,
    get_posture_regeneration_bonus_multiplier,
    load_regeneration_config,
    posture_prevents_skill_spell_use,
)
from assets import get_skill_by_id, get_spell_by_id
from equipment_logic import get_player_effective_attribute
from models import ActiveAffectState, ActiveSupportEffectState, ClientSession, EntityState
from player_resources import get_player_resource_caps


_AFFECT_ID_REGENERATION = "affect.regeneration"
_AFFECT_ID_DAMAGE_RECEIVED = "affect.received-damage"
_AFFECT_ID_DAMAGE_DEALT = "affect.dealt-damage"
_AFFECT_ID_EXTRA_HITS = "affect.extra-hits"
_AFFECT_ID_DAMAGE_REDUCTION = "affect.damage-reduction"
_AFFECT_MODES = {"instant", "timed", "battle_rounds"}
_SUPPORTED_AFFECT_IDS = {
    _AFFECT_ID_REGENERATION,
    _AFFECT_ID_DAMAGE_RECEIVED,
    _AFFECT_ID_DAMAGE_DEALT,
    _AFFECT_ID_EXTRA_HITS,
    _AFFECT_ID_DAMAGE_REDUCTION,
}


def _entity_has_active_ongoing_support_effect(entity: EntityState, effect_id: str) -> bool:
    normalized_effect_id = str(effect_id).strip().lower()
    if not normalized_effect_id:
        return False

    for active_effect in list(getattr(entity, "active_support_effects", [])):
        active_effect_id = str(getattr(active_effect, "spell_id", "")).strip().lower()
        if active_effect_id != normalized_effect_id:
            continue

        support_mode = str(getattr(active_effect, "support_mode", "timed")).strip().lower() or "timed"
        if support_mode == "battle_rounds" and int(getattr(active_effect, "remaining_rounds", 0)) > 0:
            return True
        if support_mode == "timed" and int(getattr(active_effect, "remaining_hours", 0)) > 0:
            return True

    return False


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


def _resolve_ability_affects(ability: dict) -> list[dict]:
    raw_affect_ids = ability.get("affect_ids", [])
    if not isinstance(raw_affect_ids, list):
        return []

    resolved_affects: list[dict] = []
    seen_affect_ids: set[str] = set()
    for raw_affect_ref in raw_affect_ids:
        override_payload: dict = {}
        if isinstance(raw_affect_ref, str):
            affect_id = str(raw_affect_ref).strip().lower()
        elif isinstance(raw_affect_ref, dict):
            override_payload = dict(raw_affect_ref)
            affect_id = str(override_payload.get("affect_id", "")).strip().lower()
        else:
            continue

        if not affect_id or affect_id in seen_affect_ids:
            continue

        affect_template = get_affect_template_by_id(affect_id)
        if not isinstance(affect_template, dict):
            continue

        descriptor = str(affect_template.get("descriptor", affect_id)).strip() or affect_id
        ability_name = str(ability.get("name", "")).strip()
        source_name = str(override_payload.get("name", ability_name)).strip() or descriptor

        resolved_affect = dict(affect_template)
        resolved_affect.update(override_payload)
        resolved_affect["affect_id"] = affect_id
        resolved_affect["name"] = source_name
        resolved_affect["descriptor"] = descriptor
        seen_affect_ids.add(affect_id)
        resolved_affects.append(resolved_affect)

    return resolved_affects


def _resolve_affect_scaling_bonus(actor: object, affect: dict) -> float:
    scaling_attribute_id = str(affect.get("scaling_attribute_id", "")).strip().lower()
    scaling_multiplier = float(affect.get("scaling_multiplier", 0.0))
    level_scaling_multiplier = float(affect.get("level_scaling_multiplier", 0.0))
    power_scaling_multiplier = float(affect.get("power_scaling_multiplier", 0.0))

    scaling_bonus = 0.0
    if scaling_attribute_id and scaling_multiplier != 0.0 and isinstance(actor, ClientSession):
        attribute_value = get_player_effective_attribute(actor, scaling_attribute_id)
        scaling_bonus += float(attribute_value) * scaling_multiplier

    if level_scaling_multiplier != 0.0 and isinstance(actor, ClientSession):
        scaling_bonus += float(max(1, int(actor.player.level))) * level_scaling_multiplier

    if power_scaling_multiplier != 0.0 and isinstance(actor, EntityState):
        scaling_bonus += float(max(0, int(actor.power_level))) * power_scaling_multiplier

    return float(scaling_bonus)


def _ensure_affect_list(target: object) -> list[ActiveAffectState] | None:
    affects = getattr(target, "active_affects", None)
    if isinstance(affects, list):
        return affects
    return None


def _roll_affect_amount(effect: ActiveAffectState) -> float:
    rolled_amount = float(effect.affect_amount)
    rolled_amount += float(effect.affect_roll_modifier)
    rolled_amount += float(effect.affect_scaling_bonus)

    dice_count = max(0, int(effect.affect_dice_count))
    dice_sides = max(0, int(effect.affect_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        rolled_amount += sum(random.randint(1, dice_sides) for _ in range(dice_count))

    return float(rolled_amount)


def _coerce_affect_multiplier(raw_amount: float) -> float:
    amount = float(raw_amount)
    if -1.0 < amount < 1.0:
        return max(0.0, 1.0 + amount)
    return max(0.0, amount)


def _resolve_damage_received_multiplier(active_affects: list[ActiveAffectState], *, damage_element: str) -> float:
    normalized_damage_element = str(damage_element).strip().lower()
    resolved_multiplier = 1.0
    for effect in active_affects:
        if str(getattr(effect, "affect_id", "")).strip().lower() != _AFFECT_ID_DAMAGE_RECEIVED:
            continue

        effect_damage_elements = [
            str(element).strip().lower()
            for element in list(getattr(effect, "affect_damage_elements", []) or [])
            if str(element).strip()
        ]
        if effect_damage_elements and normalized_damage_element not in effect_damage_elements:
            continue

        if not _is_affect_active(effect):
            continue

        resolved_multiplier *= _coerce_affect_multiplier(_roll_affect_amount(effect))

    return max(0.0, resolved_multiplier)


def _resolve_damage_dealt_multiplier(active_affects: list[ActiveAffectState], *, damage_element: str) -> float:
    normalized_damage_element = str(damage_element).strip().lower()
    resolved_multiplier = 1.0
    for effect in active_affects:
        if str(getattr(effect, "affect_id", "")).strip().lower() != _AFFECT_ID_DAMAGE_DEALT:
            continue

        effect_damage_elements = [
            str(element).strip().lower()
            for element in list(getattr(effect, "affect_damage_elements", []) or [])
            if str(element).strip()
        ]
        if effect_damage_elements and normalized_damage_element not in effect_damage_elements:
            continue

        if not _is_affect_active(effect):
            continue

        resolved_multiplier *= _coerce_affect_multiplier(_roll_affect_amount(effect))

    return max(0.0, resolved_multiplier)


def _is_affect_active(effect: ActiveAffectState) -> bool:
    affect_mode = str(getattr(effect, "affect_mode", "instant")).strip().lower() or "instant"
    if affect_mode == "timed" and int(getattr(effect, "remaining_hours", 0)) <= 0:
        return False
    if affect_mode == "battle_rounds" and int(getattr(effect, "remaining_rounds", 0)) <= 0:
        return False
    return True


def _resolve_extra_hits_from_affects(
    active_affects: list[ActiveAffectState],
    player_level: int,
) -> tuple[int, int, int]:
    """Return (main_hand, off_hand, unarmed) extra hits from active extra_hits affects."""
    best_main = 0
    best_off = 0
    best_unarmed = 0
    for effect in active_affects:
        if str(getattr(effect, "affect_id", "")).strip().lower() != _AFFECT_ID_EXTRA_HITS:
            continue
        if not _is_affect_active(effect):
            continue
        base_main = max(0, int(getattr(effect, "extra_main_hand_hits", 0)))
        base_off = max(0, int(getattr(effect, "extra_off_hand_hits", 0)))
        base_unarmed = max(0, int(getattr(effect, "extra_unarmed_hits", 0)))
        hits_per_step = max(0, int(getattr(effect, "hits_per_level_step", 0)))
        step = max(0, int(getattr(effect, "level_step", 0)))
        level_bonus = (max(1, int(player_level)) // step) * hits_per_step if step > 0 and hits_per_step > 0 else 0
        if base_main > 0:
            best_main = max(best_main, base_main + level_bonus)
        if base_off > 0:
            best_off = max(best_off, base_off + level_bonus)
        if base_unarmed > 0:
            best_unarmed = max(best_unarmed, base_unarmed + level_bonus)
    return best_main, best_off, best_unarmed


def _resolve_damage_reduction_from_affects(active_affects: list[ActiveAffectState]) -> int:
    strongest_reduction = 0
    for effect in active_affects:
        if str(getattr(effect, "affect_id", "")).strip().lower() != _AFFECT_ID_DAMAGE_REDUCTION:
            continue
        if not _is_affect_active(effect):
            continue
        strongest_reduction = max(strongest_reduction, int(_roll_affect_amount(effect)))
    return max(0, strongest_reduction)


def _apply_regeneration_tick(target: object, effect: ActiveAffectState) -> None:
    if str(effect.affect_id).strip().lower() != _AFFECT_ID_REGENERATION:
        return

    amount = int(_roll_affect_amount(effect))
    if amount <= 0:
        return

    resource = str(getattr(effect, "target_resource", "hit_points")).strip().lower() or "hit_points"
    if isinstance(target, ClientSession):
        caps = get_player_resource_caps(target)
        if resource == "mana":
            target.status.mana = min(caps["mana"], target.status.mana + amount)
            return
        if resource == "vigor":
            target.status.vigor = min(caps["vigor"], target.status.vigor + amount)
            return
        target.status.hit_points = min(caps["hit_points"], target.status.hit_points + amount)
        return

    if isinstance(target, EntityState):
        if resource == "mana":
            target.mana = min(target.max_mana, target.mana + amount)
            return
        if resource == "vigor":
            target.vigor = min(target.max_vigor, target.vigor + amount)
            return
        target.hit_points = min(target.max_hit_points, target.hit_points + amount)


def _apply_ability_affects(*, actor: object, target: object, ability: dict, affect_target: str) -> bool:
    active_affects = _ensure_affect_list(target)
    if active_affects is None:
        return False

    applied = False
    for affect in _resolve_ability_affects(ability):
        target_scope = str(affect.get("target", "target")).strip().lower() or "target"
        if target_scope != affect_target:
            continue

        affect_id = str(affect.get("affect_id", "")).strip().lower()
        if affect_id not in _SUPPORTED_AFFECT_IDS:
            continue

        affect_mode = str(affect.get("affect_mode", "battle_rounds")).strip().lower() or "battle_rounds"
        if affect_mode not in _AFFECT_MODES:
            continue
        affect_descriptor = str(affect.get("descriptor", "")).strip() or affect_id
        affect_name = str(affect.get("name", "")).strip() or affect_descriptor
        can_be_negative = bool(affect.get("can_be_negative", False))
        raw_damage_elements = affect.get("damage_elements", affect.get("damage_element", []))
        if isinstance(raw_damage_elements, str):
            raw_damage_elements = [raw_damage_elements]
        if not isinstance(raw_damage_elements, list):
            raw_damage_elements = []
        affect_damage_elements = [
            str(element).strip().lower()
            for element in raw_damage_elements
            if str(element).strip()
        ]
        target_resource = str(affect.get("target_resource", "hit_points")).strip().lower() or "hit_points"
        affect_amount = float(affect.get("amount", 0.0))
        affect_dice_count = max(0, int(affect.get("dice_count", 0)))
        affect_dice_sides = max(0, int(affect.get("dice_sides", 0)))
        affect_roll_modifier = float(affect.get("roll_modifier", 0.0))
        affect_scaling_bonus = _resolve_affect_scaling_bonus(actor, affect)
        amount_per_level_step = float(affect.get("amount_per_level_step", 0.0))
        hits_per_level_step = max(0, int(affect.get("hits_per_level_step", 0)))
        level_step = max(0, int(affect.get("level_step", 0)))
        remaining_hours = max(0, int(affect.get("duration_hours", 0)))
        if remaining_hours <= 0:
            remaining_hours = max(0, int(ability.get("duration_hours", 0)))
        remaining_rounds = max(0, int(affect.get("duration_rounds", 0)))
        if remaining_rounds <= 0:
            remaining_rounds = max(0, int(ability.get("duration_rounds", 0)))

        duration_rounds_per_level_step = max(0, int(affect.get("duration_rounds_per_level_step", 0)))
        duration_level_step = max(0, int(affect.get("duration_level_step", 0)))
        actor_level = 0
        if isinstance(actor, ClientSession):
            actor_level = max(1, int(actor.player.level))
        elif isinstance(actor, EntityState):
            actor_level = max(0, int(getattr(actor, "power_level", 0)))
        if remaining_rounds > 0 and duration_rounds_per_level_step > 0 and duration_level_step > 0 and actor_level > 0:
            remaining_rounds += (actor_level // duration_level_step) * duration_rounds_per_level_step
        if amount_per_level_step != 0.0 and level_step > 0 and actor_level > 0:
            affect_scaling_bonus += (actor_level // level_step) * amount_per_level_step

        extra_main_hand_hits = max(0, int(affect.get("extra_main_hand_hits", 0)))
        extra_off_hand_hits = max(0, int(affect.get("extra_off_hand_hits", 0)))
        extra_unarmed_hits = max(0, int(affect.get("extra_unarmed_hits", 0)))

        if affect_mode == "instant":
            instant_effect = ActiveAffectState(
                affect_id=affect_id,
                affect_name=affect_name,
                affect_mode=affect_mode,
                affect_type=affect_id,
                affect_descriptor=affect_descriptor,
                can_be_negative=can_be_negative,
                affect_damage_elements=affect_damage_elements,
                target_resource=target_resource,
                affect_amount=affect_amount,
                affect_dice_count=affect_dice_count,
                affect_dice_sides=affect_dice_sides,
                affect_roll_modifier=affect_roll_modifier,
                affect_scaling_bonus=affect_scaling_bonus,
                extra_main_hand_hits=extra_main_hand_hits,
                extra_off_hand_hits=extra_off_hand_hits,
                extra_unarmed_hits=extra_unarmed_hits,
                hits_per_level_step=hits_per_level_step,
                level_step=level_step,
            )
            _apply_regeneration_tick(target, instant_effect)
            applied = True
            continue

        refreshed = False
        for active_affect in active_affects:
            if active_affect.affect_id != affect_id:
                continue
            active_affect.affect_name = affect_name
            active_affect.affect_descriptor = affect_descriptor
            active_affect.affect_mode = affect_mode
            active_affect.affect_type = affect_id
            active_affect.can_be_negative = can_be_negative
            active_affect.affect_damage_elements = affect_damage_elements
            active_affect.target_resource = target_resource
            active_affect.affect_amount = affect_amount
            active_affect.affect_dice_count = affect_dice_count
            active_affect.affect_dice_sides = affect_dice_sides
            active_affect.affect_roll_modifier = affect_roll_modifier
            active_affect.affect_scaling_bonus = affect_scaling_bonus
            active_affect.extra_main_hand_hits = extra_main_hand_hits
            active_affect.extra_off_hand_hits = extra_off_hand_hits
            active_affect.extra_unarmed_hits = extra_unarmed_hits
            active_affect.hits_per_level_step = hits_per_level_step
            active_affect.level_step = level_step
            active_affect.remaining_hours = remaining_hours
            active_affect.remaining_rounds = remaining_rounds
            refreshed = True
            applied = True
            break

        if not refreshed:
            active_affects.append(ActiveAffectState(
                affect_id=affect_id,
                affect_name=affect_name,
                affect_mode=affect_mode,
                affect_type=affect_id,
                affect_descriptor=affect_descriptor,
                can_be_negative=can_be_negative,
                affect_damage_elements=affect_damage_elements,
                target_resource=target_resource,
                affect_amount=affect_amount,
                affect_dice_count=affect_dice_count,
                affect_dice_sides=affect_dice_sides,
                affect_roll_modifier=affect_roll_modifier,
                affect_scaling_bonus=affect_scaling_bonus,
                extra_main_hand_hits=extra_main_hand_hits,
                extra_off_hand_hits=extra_off_hand_hits,
                extra_unarmed_hits=extra_unarmed_hits,
                hits_per_level_step=hits_per_level_step,
                level_step=level_step,
                remaining_hours=remaining_hours,
                remaining_rounds=remaining_rounds,
            ))
            applied = True

    return applied


def _resolve_skill_target_posture(skill: dict) -> str:
    posture = str(skill.get("target_posture", "")).strip().lower()
    if posture not in {"standing", "sitting", "resting", "sleeping"}:
        return ""
    return posture


def _apply_target_posture(target: object, posture: str) -> None:
    normalized_posture = str(posture).strip().lower()
    if normalized_posture == "standing":
        setattr(target, "is_sitting", False)
        setattr(target, "is_resting", False)
        setattr(target, "is_sleeping", False)
        return
    if normalized_posture == "sitting":
        setattr(target, "is_sitting", True)
        setattr(target, "is_resting", False)
        setattr(target, "is_sleeping", False)
        return
    if normalized_posture == "resting":
        setattr(target, "is_sitting", False)
        setattr(target, "is_resting", True)
        setattr(target, "is_sleeping", False)
        return
    if normalized_posture == "sleeping":
        setattr(target, "is_sitting", False)
        setattr(target, "is_resting", False)
        setattr(target, "is_sleeping", True)


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
            attribute_score = get_player_effective_attribute(session, scaling_attribute_id)
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
        attribute_score = get_player_effective_attribute(session, scaling_attribute_id)
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


def _resolve_active_damage_reduction(effects: list[ActiveSupportEffectState]) -> int:
    strongest_reduction = 0
    for effect in effects:
        if str(getattr(effect, "support_effect", "")).strip().lower() != "damage_reduction":
            continue

        support_mode = str(getattr(effect, "support_mode", "instant")).strip().lower() or "instant"
        if support_mode == "timed" and int(getattr(effect, "remaining_hours", 0)) <= 0:
            continue
        if support_mode == "battle_rounds" and int(getattr(effect, "remaining_rounds", 0)) <= 0:
            continue

        strongest_reduction = max(strongest_reduction, _roll_support_effect_amount(effect))

    return max(0, strongest_reduction)


def _apply_player_damage_with_reduction(session: ClientSession, amount: int, *, damage_element: str = "physical") -> int:
    incoming_damage = max(0, int(amount))
    if incoming_damage <= 0:
        return 0

    was_sleeping = bool(getattr(session, "is_sleeping", False))

    if was_sleeping:
        session.is_sleeping = False
        session.is_resting = False
        session.is_sitting = True

    posture_damage_multiplier = _resolve_posture_received_damage_multiplier(
        is_sitting=bool(getattr(session, "is_sitting", False)),
        is_resting=bool(getattr(session, "is_resting", False)),
        is_sleeping=was_sleeping,
    )
    if posture_damage_multiplier > 1.0:
        incoming_damage = int(incoming_damage * posture_damage_multiplier)

    incoming_damage = int(incoming_damage * _resolve_damage_received_multiplier(
        list(session.active_affects),
        damage_element=damage_element,
    ))

    support_reduction = _resolve_active_damage_reduction(list(session.active_support_effects))
    affect_reduction = _resolve_damage_reduction_from_affects(list(session.active_affects))
    total_reduction = max(support_reduction, affect_reduction)
    reduced_damage = max(0, incoming_damage - total_reduction)
    damage_dealt = min(max(0, int(session.status.hit_points)), reduced_damage)
    session.status.hit_points = max(0, int(session.status.hit_points) - reduced_damage)
    return max(0, damage_dealt)


def _apply_entity_damage_with_reduction(entity: EntityState, amount: int, *, damage_element: str = "physical") -> int:
    incoming_damage, reduced_damage = _resolve_entity_damage_values(entity, amount, damage_element=damage_element)
    if incoming_damage <= 0:
        return 0

    damage_dealt = min(max(0, int(entity.hit_points)), reduced_damage)
    entity.hit_points = max(0, int(entity.hit_points) - reduced_damage)
    return max(0, damage_dealt)


def _preview_entity_damage_with_reduction(entity: EntityState, amount: int, *, damage_element: str = "physical") -> int:
    incoming_damage, reduced_damage = _resolve_entity_damage_values(entity, amount, damage_element=damage_element)
    if incoming_damage <= 0:
        return 0
    return max(0, reduced_damage)


def _resolve_entity_damage_values(entity: EntityState, amount: int, *, damage_element: str) -> tuple[int, int]:
    incoming_damage = max(0, int(amount))
    if incoming_damage <= 0:
        return 0, 0

    posture_damage_multiplier = _resolve_posture_received_damage_multiplier(
        is_sitting=bool(getattr(entity, "is_sitting", False)),
        is_resting=bool(getattr(entity, "is_resting", False)),
        is_sleeping=bool(getattr(entity, "is_sleeping", False)),
    )
    if posture_damage_multiplier > 1.0:
        incoming_damage = int(incoming_damage * posture_damage_multiplier)

    incoming_damage = int(incoming_damage * _resolve_damage_received_multiplier(
        list(entity.active_affects),
        damage_element=damage_element,
    ))

    active_effects = list(getattr(entity, "active_support_effects", []))
    support_reduction = _resolve_active_damage_reduction(active_effects)
    affect_reduction = _resolve_damage_reduction_from_affects(list(entity.active_affects))
    total_reduction = max(support_reduction, affect_reduction)
    reduced_damage = max(0, incoming_damage - total_reduction)
    return incoming_damage, reduced_damage


def _apply_player_dealt_damage_multiplier(
    session: ClientSession,
    amount: int,
    *,
    damage_element: str = "physical",
) -> int:
    outgoing_damage = max(0, int(amount))
    if outgoing_damage <= 0:
        return 0

    posture_damage_multiplier = _resolve_posture_dealt_damage_multiplier(
        is_sitting=bool(getattr(session, "is_sitting", False)),
        is_resting=bool(getattr(session, "is_resting", False)),
        is_sleeping=bool(getattr(session, "is_sleeping", False)),
    )
    affect_damage_multiplier = _resolve_damage_dealt_multiplier(
        list(session.active_affects),
        damage_element=damage_element,
    )
    return max(0, int(outgoing_damage * posture_damage_multiplier * affect_damage_multiplier))


def _apply_entity_dealt_damage_multiplier(
    entity: EntityState,
    amount: int,
    *,
    damage_element: str = "physical",
) -> int:
    outgoing_damage = max(0, int(amount))
    if outgoing_damage <= 0:
        return 0

    posture_damage_multiplier = _resolve_posture_dealt_damage_multiplier(
        is_sitting=bool(getattr(entity, "is_sitting", False)),
        is_resting=bool(getattr(entity, "is_resting", False)),
        is_sleeping=bool(getattr(entity, "is_sleeping", False)),
    )
    affect_damage_multiplier = _resolve_damage_dealt_multiplier(
        list(entity.active_affects),
        damage_element=damage_element,
    )
    return max(0, int(outgoing_damage * posture_damage_multiplier * affect_damage_multiplier))


def _resolve_posture_received_damage_multiplier(*, is_sitting: bool, is_resting: bool, is_sleeping: bool) -> float:
    posture_damage_multiplier = 1.0
    if is_sleeping:
        posture_damage_multiplier = max(
            posture_damage_multiplier,
            get_posture_received_damage_multiplier("sleeping"),
        )
    if is_resting:
        posture_damage_multiplier = max(
            posture_damage_multiplier,
            get_posture_received_damage_multiplier("resting"),
        )
    if is_sitting:
        posture_damage_multiplier = max(
            posture_damage_multiplier,
            get_posture_received_damage_multiplier("sitting"),
        )
    return max(1.0, posture_damage_multiplier)


def _resolve_posture_dealt_damage_multiplier(*, is_sitting: bool, is_resting: bool, is_sleeping: bool) -> float:
    posture_damage_multiplier = 1.0
    if is_sleeping:
        posture_damage_multiplier = min(
            posture_damage_multiplier,
            get_posture_dealt_damage_multiplier("sleeping"),
        )
    if is_resting:
        posture_damage_multiplier = min(
            posture_damage_multiplier,
            get_posture_dealt_damage_multiplier("resting"),
        )
    if is_sitting:
        posture_damage_multiplier = min(
            posture_damage_multiplier,
            get_posture_dealt_damage_multiplier("sitting"),
        )
    return max(0.0, posture_damage_multiplier)


def _process_entity_battle_round_support_effects(entity: EntityState) -> None:
    for effect in list(entity.active_support_effects):
        if effect.support_mode != "battle_rounds":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_rounds -= 1
        if effect.remaining_rounds <= 0:
            entity.active_support_effects.remove(effect)


def _process_entity_battle_round_affects(entity: EntityState) -> None:
    for affect in list(entity.active_affects):
        if affect.affect_mode != "battle_rounds":
            continue

        _apply_regeneration_tick(entity, affect)
        affect.remaining_rounds -= 1
        if affect.remaining_rounds <= 0:
            entity.active_affects.remove(affect)


def _process_player_battle_round_affects(session: ClientSession) -> None:
    for affect in list(session.active_affects):
        if affect.affect_mode != "battle_rounds":
            continue

        _apply_regeneration_tick(session, affect)
        affect.remaining_rounds -= 1
        if affect.remaining_rounds <= 0:
            session.active_affects.remove(affect)


def _process_player_game_hour_affects(session: ClientSession) -> list[str]:
    expired_affect_names: list[str] = []
    for affect in list(session.active_affects):
        if affect.affect_mode != "timed":
            continue

        _apply_regeneration_tick(session, affect)
        affect.remaining_hours -= 1
        if affect.remaining_hours <= 0:
            session.active_affects.remove(affect)
            if affect.affect_name:
                expired_affect_names.append(affect.affect_name)
    return expired_affect_names


def process_entity_battle_round_tick(entity: EntityState, elapsed_rounds: int = 1) -> None:
    rounds = max(0, int(elapsed_rounds))
    for _ in range(rounds):
        _process_entity_battle_round_support_effects(entity)
        _process_entity_battle_round_affects(entity)
        for cooldowns in (entity.skill_cooldowns, entity.spell_cooldowns):
            for key, remaining in list(cooldowns.items()):
                if remaining <= 1:
                    cooldowns.pop(key, None)
                else:
                    cooldowns[key] = remaining - 1


def _entity_needs_secondary_restore(entity: EntityState, effect: str) -> bool:
    normalized_effect = str(effect).strip().lower()
    if normalized_effect == "mana":
        return int(entity.mana) < int(entity.max_mana)
    if normalized_effect == "vigor":
        return int(entity.vigor) < int(entity.max_vigor)
    return int(entity.hit_points) < int(entity.max_hit_points)


def _apply_entity_passive_regeneration(entity: EntityState) -> None:
    if not getattr(entity, "is_alive", False):
        return

    regeneration_config = load_regeneration_config()
    resources = regeneration_config.get("resources", {}) if isinstance(regeneration_config, dict) else {}

    def _resolve_regen_percent(attribute_score: int, mapping: list[dict]) -> float:
        resolved_percent = 0.0
        for entry in mapping:
            if attribute_score >= int(entry.get("min", 0)):
                resolved_percent = float(entry.get("percent", 0.0))
            else:
                break
        return max(0.0, resolved_percent)

    attribute_score = max(0, int(getattr(entity, "power_level", 0)))
    posture_multiplier = 1.0
    if bool(getattr(entity, "is_sleeping", False)):
        posture_multiplier = get_posture_regeneration_bonus_multiplier("sleeping")
    elif bool(getattr(entity, "is_resting", False)):
        posture_multiplier = get_posture_regeneration_bonus_multiplier("resting")

    resource_specs = [
        ("hit_points", "hit_points", "max_hit_points"),
        ("vigor", "vigor", "max_vigor"),
        ("mana", "mana", "max_mana"),
    ]
    for resource_key, entity_field, max_field in resource_specs:
        max_value = max(0, int(getattr(entity, max_field, 0)))
        current_value = max(0, int(getattr(entity, entity_field, 0)))
        if max_value <= 0 or current_value >= max_value:
            continue

        resource_config = resources.get(resource_key, {}) if isinstance(resources, dict) else {}
        if not isinstance(resource_config, dict):
            continue

        mapping = resource_config.get("percent_by_attribute", [])
        if not isinstance(mapping, list):
            continue

        regen_percent = _resolve_regen_percent(attribute_score, mapping)
        min_amount = max(0, int(resource_config.get("min_amount", 0)))
        regen_amount = max(min_amount, int(max_value * regen_percent))
        if posture_multiplier != 1.0:
            regen_amount = int(regen_amount * posture_multiplier)

        if regen_amount <= 0:
            continue

        setattr(entity, entity_field, min(max_value, current_value + regen_amount))


def _entity_try_use_noncombat_restorative_support(entity: EntityState) -> bool:
    if not getattr(entity, "is_alive", False):
        return False

    if str(getattr(entity, "combat_target_player_key", "")).strip():
        return False

    if entity.is_sitting and posture_prevents_skill_spell_use("sitting"):
        return False
    if entity.is_resting and posture_prevents_skill_spell_use("resting"):
        return False
    if entity.is_sleeping and posture_prevents_skill_spell_use("sleeping"):
        return False

    missing_resources = (
        int(entity.hit_points) < int(entity.max_hit_points)
        or int(entity.vigor) < int(entity.max_vigor)
        or int(entity.mana) < int(entity.max_mana)
    )
    if not missing_resources:
        return False

    available_spells: list[dict] = []
    for spell_id in entity.spell_ids:
        spell = get_spell_by_id(spell_id)
        if not isinstance(spell, dict):
            continue

        spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"
        cast_type = str(spell.get("cast_type", "target")).strip().lower() or "target"
        support_effect = str(spell.get("support_effect", "")).strip().lower()
        if spell_type != "support" or cast_type != "self" or not support_effect:
            continue

        normalized_spell_id = str(spell.get("spell_id", "")).strip()
        if normalized_spell_id and entity.spell_cooldowns.get(normalized_spell_id, 0) > 0:
            continue

        mana_cost = max(0, int(spell.get("mana_cost", 0)))
        if int(entity.mana) < mana_cost:
            continue

        if not _entity_needs_secondary_restore(entity, support_effect):
            continue

        support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
        effect_id = normalized_spell_id or str(spell.get("name", "")).strip()
        if support_mode in {"timed", "battle_rounds"} and effect_id and _entity_has_active_ongoing_support_effect(entity, effect_id):
            continue

        available_spells.append(spell)

    spell_chance = max(0.0, min(1.0, float(getattr(entity, "spell_use_chance", 0.0))))
    if available_spells and random.random() < spell_chance:
        spell = random.choice(available_spells)
        support_effect = str(spell.get("support_effect", "")).strip().lower()
        rolled_support_amount, dice_count, dice_sides, roll_modifier, scaling_bonus = _roll_entity_support_amount(
            entity,
            spell,
            support_effect,
        )
        support_mode = str(spell.get("support_mode", "timed")).strip().lower() or "timed"
        duration_hours = max(0, int(spell.get("duration_hours", 0)))
        duration_rounds = max(0, int(spell.get("duration_rounds", 0)))
        spell_id = str(spell.get("spell_id", spell.get("name", ""))).strip() or str(spell.get("name", "Spell")).strip() or "Spell"
        spell_name = str(spell.get("name", "Spell")).strip() or "Spell"

        entity.mana = max(0, int(entity.mana) - max(0, int(spell.get("mana_cost", 0))))

        if support_mode == "instant":
            _apply_entity_secondary_restore(entity, support_effect, rolled_support_amount)
        elif support_mode in {"timed", "battle_rounds"}:
            refreshed = False
            for active_effect in entity.active_support_effects:
                if active_effect.spell_id != spell_id:
                    continue
                active_effect.support_mode = support_mode
                active_effect.support_effect = support_effect
                active_effect.support_amount = max(0, int(spell.get("support_amount", 0)))
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
                    support_amount=max(0, int(spell.get("support_amount", 0))),
                    support_dice_count=dice_count,
                    support_dice_sides=dice_sides,
                    support_roll_modifier=roll_modifier,
                    support_scaling_bonus=scaling_bonus,
                    remaining_hours=duration_hours,
                    remaining_rounds=duration_rounds,
                ))

        _apply_ability_affects(actor=entity, target=entity, ability=spell, affect_target="self")
        _set_entity_spell_cooldown(entity, spell)
        _apply_entity_spell_lag(entity, spell)
        return True

    available_skills: list[dict] = []
    for skill_id in entity.skill_ids:
        skill = get_skill_by_id(skill_id)
        if not isinstance(skill, dict):
            continue

        skill_type = str(skill.get("skill_type", "damage")).strip().lower() or "damage"
        cast_type = str(skill.get("cast_type", "target")).strip().lower() or "target"
        support_effect = str(skill.get("support_effect", "")).strip().lower()
        if skill_type != "support" or cast_type != "self" or not support_effect:
            continue

        normalized_skill_id = str(skill.get("skill_id", "")).strip()
        if normalized_skill_id and entity.skill_cooldowns.get(normalized_skill_id, 0) > 0:
            continue

        vigor_cost = max(0, int(skill.get("vigor_cost", 0)))
        if int(entity.vigor) < vigor_cost:
            continue

        if not _entity_needs_secondary_restore(entity, support_effect):
            continue

        support_mode = str(skill.get("support_mode", "instant")).strip().lower() or "instant"
        effect_id = normalized_skill_id or str(skill.get("name", "")).strip()
        if support_mode in {"timed", "battle_rounds"} and effect_id and _entity_has_active_ongoing_support_effect(entity, effect_id):
            continue

        available_skills.append(skill)

    skill_chance = max(0.0, min(1.0, float(getattr(entity, "skill_use_chance", 0.0))))
    if available_skills and random.random() < skill_chance:
        skill = random.choice(available_skills)
        support_effect = str(skill.get("support_effect", "")).strip().lower()
        total_support_amount = max(0, int(skill.get("support_amount", 0)) + _resolve_entity_skill_scale_bonus(entity, skill))
        support_mode = str(skill.get("support_mode", "instant")).strip().lower() or "instant"
        duration_hours = max(0, int(skill.get("duration_hours", 0)))
        duration_rounds = max(0, int(skill.get("duration_rounds", 0)))
        skill_id = str(skill.get("skill_id", skill.get("name", ""))).strip() or str(skill.get("name", "Skill")).strip() or "Skill"
        skill_name = str(skill.get("name", "Skill")).strip() or "Skill"

        entity.vigor = max(0, int(entity.vigor) - max(0, int(skill.get("vigor_cost", 0))))

        if support_mode == "instant":
            _apply_entity_secondary_restore(entity, support_effect, total_support_amount)
        elif support_mode in {"timed", "battle_rounds"}:
            refreshed = False
            for active_effect in entity.active_support_effects:
                if active_effect.spell_id != skill_id:
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
                    spell_id=skill_id,
                    spell_name=skill_name,
                    support_mode=support_mode,
                    support_effect=support_effect,
                    support_amount=total_support_amount,
                    support_dice_count=0,
                    support_dice_sides=0,
                    support_roll_modifier=0,
                    support_scaling_bonus=0,
                    remaining_hours=duration_hours,
                    remaining_rounds=duration_rounds,
                ))

        _apply_ability_affects(actor=entity, target=entity, ability=skill, affect_target="self")
        _set_entity_skill_cooldown(entity, skill)
        _apply_entity_skill_lag(entity, skill)
        return True

    return False


def process_entity_game_hour_tick(entity: EntityState) -> None:
    _apply_entity_passive_regeneration(entity)
    _entity_try_use_noncombat_restorative_support(entity)

    for effect in list(entity.active_support_effects):
        if effect.support_mode != "timed":
            continue

        rolled_amount = _roll_support_effect_amount(effect)
        _apply_entity_secondary_restore(entity, effect.support_effect, rolled_amount)

        effect.remaining_hours -= 1
        if effect.remaining_hours <= 0:
            entity.active_support_effects.remove(effect)

    for affect in list(entity.active_affects):
        if affect.affect_mode != "timed":
            continue

        _apply_regeneration_tick(entity, affect)
        affect.remaining_hours -= 1
        if affect.remaining_hours <= 0:
            entity.active_affects.remove(affect)

    if bool(getattr(entity, "is_merchant", False)):
        from commerce import process_merchant_game_hour_tick

        process_merchant_game_hour_tick(entity)


def _resolve_player_skill_scale_bonus(session: ClientSession, skill: dict) -> int:
    scaling_attribute_id = str(skill.get("scaling_attribute_id", "")).strip().lower()
    scaling_multiplier = max(0.0, float(skill.get("scaling_multiplier", 0.0)))
    level_scaling_multiplier = max(0.0, float(skill.get("level_scaling_multiplier", 1.0)))

    scaling_bonus = 0
    if scaling_attribute_id and scaling_multiplier > 0.0:
        attribute_value = get_player_effective_attribute(session, scaling_attribute_id)
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
    # NPC spellcasting should not consume the next melee round.
    # Only players use spell lag to skip melee via `session.combat.skip_melee_rounds`.
    entity.spell_lag_rounds_remaining = 0
