import random

from attribute_config import load_regeneration_config
from models import ClientSession
from settings import PLAYER_REFERENCE_MAX_HP, PLAYER_REFERENCE_MAX_MANA, PLAYER_REFERENCE_MAX_VIGOR


def _roll_support_effect_amount(effect) -> int:
    total = int(effect.support_amount) + int(effect.support_roll_modifier) + int(effect.support_scaling_bonus)
    dice_count = max(0, int(effect.support_dice_count))
    dice_sides = max(0, int(effect.support_dice_sides))
    if dice_count > 0 and dice_sides > 0:
        total += sum(random.randint(1, dice_sides) for _ in range(dice_count))
    return max(0, total)


def process_game_hour_tick(session: ClientSession) -> list[str]:
    expired_spell_names: list[str] = []

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
        ("hit_points", "hit_points", PLAYER_REFERENCE_MAX_HP),
        ("vigor", "vigor", PLAYER_REFERENCE_MAX_VIGOR),
        ("mana", "mana", PLAYER_REFERENCE_MAX_MANA),
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
            session.status.hit_points = min(PLAYER_REFERENCE_MAX_HP, session.status.hit_points + applied_amount)
        elif effect.support_effect == "vigor":
            session.status.vigor = min(PLAYER_REFERENCE_MAX_VIGOR, session.status.vigor + applied_amount)
        elif effect.support_effect == "mana":
            session.status.mana = min(PLAYER_REFERENCE_MAX_MANA, session.status.mana + applied_amount)

        effect.remaining_hours -= 1
        if effect.remaining_hours <= 0:
            session.active_support_effects.remove(effect)
            expired_spell_names.append(effect.spell_name)

    return expired_spell_names
