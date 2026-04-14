import random

from attribute_config import get_posture_regeneration_bonus_multiplier, load_regeneration_config
from combat_ability_effects import _process_player_game_hour_affects
from inventory import tick_item_decay_map
from models import ClientSession
from player_resources import get_player_resource_caps


def _roll_support_effect_amount(effect) -> int:
    total = int(effect.support_amount) + int(effect.support_roll_modifier) + int(effect.support_scaling_bonus)
    dice_count = max(0, int(effect.support_dice_count))
    dice_sides = max(0, int(effect.support_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        total += sum(random.randint(1, dice_sides) for _ in range(dice_count))
    return max(0, total)


def process_game_hour_tick(session: ClientSession) -> list[str]:
    expired_spell_names: list[str] = []
    expired_inventory_items = tick_item_decay_map(session.inventory_items)
    expired_equipped_items = tick_item_decay_map(session.equipment.equipped_items)
    expired_item_ids = {item.item_id for item in expired_inventory_items + expired_equipped_items}
    if session.equipment.equipped_main_hand_id in expired_item_ids:
        session.equipment.equipped_main_hand_id = None
    if session.equipment.equipped_off_hand_id in expired_item_ids:
        session.equipment.equipped_off_hand_id = None
    if expired_item_ids:
        session.equipment.worn_item_ids = {
            slot: item_id
            for slot, item_id in session.equipment.worn_item_ids.items()
            if item_id not in expired_item_ids
        }

    caps = get_player_resource_caps(session)

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

    resource_specs = [
        ("hit_points", "hit_points", int(caps["hit_points"])),
        ("vigor", "vigor", int(caps["vigor"])),
        ("mana", "mana", int(caps["mana"])),
    ]
    for resource_key, status_field, max_value in resource_specs:
        resource_config = resources.get(resource_key, {}) if isinstance(resources, dict) else {}
        if not isinstance(resource_config, dict):
            continue

        attribute_id = str(resource_config.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            continue

        attribute_score = int(session.player.attributes.get(attribute_id, 0))
        mapping = resource_config.get("percent_by_attribute", [])
        if not isinstance(mapping, list):
            continue

        regen_percent = _resolve_regen_percent(attribute_score, mapping)
        min_amount = max(0, int(resource_config.get("min_amount", 0)))
        regen_amount = max(min_amount, int(max_value * regen_percent))
        if bool(getattr(session, "is_sleeping", False)):
            regen_amount = int(regen_amount * get_posture_regeneration_bonus_multiplier("sleeping"))
        elif bool(getattr(session, "is_resting", False)):
            regen_amount = int(regen_amount * get_posture_regeneration_bonus_multiplier("resting"))

        if regen_amount <= 0:
            continue

        current_value = int(getattr(session.status, status_field))
        if current_value >= max_value:
            continue

        setattr(session.status, status_field, min(max_value, current_value + regen_amount))

    for effect in list(session.active_support_effects):
        if effect.support_mode != "timed":
            continue

        applied_amount = _roll_support_effect_amount(effect)

        if effect.support_effect == "heal":
            session.status.hit_points = min(caps["hit_points"], session.status.hit_points + applied_amount)
        elif effect.support_effect == "vigor":
            session.status.vigor = min(caps["vigor"], session.status.vigor + applied_amount)
        elif effect.support_effect == "mana":
            session.status.mana = min(caps["mana"], session.status.mana + applied_amount)

        effect.remaining_hours -= 1
        if effect.remaining_hours <= 0:
            session.active_support_effects.remove(effect)
            expired_spell_names.append(effect.spell_name)

    expired_spell_names.extend(_process_player_game_hour_affects(session))

    for skill_id in list(session.combat.skill_hour_cooldowns):
        session.combat.skill_hour_cooldowns[skill_id] -= 1
        if session.combat.skill_hour_cooldowns[skill_id] <= 0:
            del session.combat.skill_hour_cooldowns[skill_id]

    return expired_spell_names
