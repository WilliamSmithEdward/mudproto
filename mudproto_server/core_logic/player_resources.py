import random

from attribute_config import get_default_player_class, get_player_class_by_id
from equipment_logic import get_player_effective_attribute, get_player_equipment_bonuses
from models import ClientSession
from settings import PLAYER_REFERENCE_MAX_HP, PLAYER_REFERENCE_MAX_MANA, PLAYER_REFERENCE_MAX_VIGOR

_RESOURCE_KEYS = ("hit_points", "vigor", "mana")
_DEFAULT_RESOURCE_RULES = {
    "hit_points": {
        "base": int(PLAYER_REFERENCE_MAX_HP),
        "attribute_id": "con",
        "attribute_multiplier": 1.0,
        "per_level_min": 0,
        "per_level_max": 0,
    },
    "vigor": {
        "base": int(PLAYER_REFERENCE_MAX_VIGOR),
        "attribute_id": "dex",
        "attribute_multiplier": 1.0,
        "per_level_min": 0,
        "per_level_max": 0,
    },
    "mana": {
        "base": int(PLAYER_REFERENCE_MAX_MANA),
        "attribute_id": "wis",
        "attribute_multiplier": 1.0,
        "per_level_min": 0,
        "per_level_max": 0,
    },
}


def _resolve_class_resource_rules(session: ClientSession) -> dict[str, dict]:
    class_id = str(session.player.class_id).strip()
    player_class = get_player_class_by_id(class_id) if class_id else None
    if player_class is None:
        player_class = get_default_player_class()

    uses_mana = bool(player_class.get("uses_mana", True)) if isinstance(player_class, dict) else True
    raw_rules = player_class.get("resource_progression", {}) if isinstance(player_class, dict) else {}
    resolved: dict[str, dict] = {}
    for resource_key in _RESOURCE_KEYS:
        default_rule = _DEFAULT_RESOURCE_RULES[resource_key]
        raw_rule = raw_rules.get(resource_key, {}) if isinstance(raw_rules, dict) else {}
        if not isinstance(raw_rule, dict):
            raw_rule = {}

        is_enabled = resource_key != "mana" or uses_mana
        minimum_base = 1 if is_enabled else 0
        default_base = default_rule["base"] if is_enabled else 0
        default_multiplier = default_rule["attribute_multiplier"] if is_enabled else 0.0

        resolved[resource_key] = {
            "enabled": is_enabled,
            "base": max(minimum_base, int(raw_rule.get("base", default_base))),
            "attribute_id": str(raw_rule.get("attribute_id", default_rule["attribute_id"]))
            .strip()
            .lower()
            or str(default_rule["attribute_id"]),
            "attribute_multiplier": max(0.0, float(raw_rule.get("attribute_multiplier", default_multiplier))),
            "per_level_min": int(raw_rule.get("per_level_min", default_rule["per_level_min"] if is_enabled else 0)),
            "per_level_max": int(raw_rule.get("per_level_max", default_rule["per_level_max"] if is_enabled else 0)),
        }

    return resolved


def _attribute_modifier(session: ClientSession, attribute_id: str) -> int:
    score = int(get_player_effective_attribute(session, attribute_id))
    return (score - 10) // 2


def get_player_resource_caps(session: ClientSession) -> dict[str, int]:
    rules = _resolve_class_resource_rules(session)
    gains = dict(session.player.resource_level_gains or {})
    equipment_bonuses = get_player_equipment_bonuses(session)

    caps: dict[str, int] = {}
    for resource_key in _RESOURCE_KEYS:
        rule = rules[resource_key]
        if not bool(rule.get("enabled", True)):
            caps[resource_key] = 0
            continue

        base = int(rule["base"])
        attribute_bonus = int(_attribute_modifier(session, str(rule["attribute_id"])) * float(rule["attribute_multiplier"]))
        level_gain_total = int(gains.get(resource_key, 0))
        equipment_bonus = int(equipment_bonuses.get(resource_key, 0))
        caps[resource_key] = max(1, base + attribute_bonus + level_gain_total + equipment_bonus)

    return caps


def clamp_player_resources_to_caps(session: ClientSession) -> None:
    caps = get_player_resource_caps(session)
    session.status.hit_points = min(caps["hit_points"], max(0, int(session.status.hit_points)))
    session.status.vigor = min(caps["vigor"], max(0, int(session.status.vigor)))
    session.status.mana = min(caps["mana"], max(0, int(session.status.mana)))


def initialize_player_progression(session: ClientSession) -> None:
    session.player.level = max(1, int(session.player.level) or 1)
    session.player.experience_points = max(0, int(session.player.experience_points) or 0)
    session.player.resource_level_gains = {key: 0 for key in _RESOURCE_KEYS}

    caps = get_player_resource_caps(session)
    session.status.hit_points = caps["hit_points"]
    session.status.vigor = caps["vigor"]
    session.status.mana = caps["mana"]


def roll_level_resource_gains(session: ClientSession, old_level: int, new_level: int) -> dict[str, int]:
    old_level = max(1, int(old_level))
    new_level = max(old_level, int(new_level))
    if new_level <= old_level:
        return {key: 0 for key in _RESOURCE_KEYS}

    rules = _resolve_class_resource_rules(session)
    gains_map = dict(session.player.resource_level_gains or {})
    gained_totals = {key: 0 for key in _RESOURCE_KEYS}

    for _ in range(old_level + 1, new_level + 1):
        for resource_key in _RESOURCE_KEYS:
            rule = rules[resource_key]
            low = int(rule.get("per_level_min", 0))
            high = int(rule.get("per_level_max", 0))
            if high < low:
                low, high = high, low
            roll = random.randint(low, high) if high > low else low
            roll = max(0, int(roll))
            gained_totals[resource_key] += roll
            gains_map[resource_key] = int(gains_map.get(resource_key, 0)) + roll

    session.player.resource_level_gains = gains_map

    caps = get_player_resource_caps(session)
    session.status.hit_points = min(caps["hit_points"], session.status.hit_points + gained_totals["hit_points"])
    session.status.vigor = min(caps["vigor"], session.status.vigor + gained_totals["vigor"])
    session.status.mana = min(caps["mana"], session.status.mana + gained_totals["mana"])

    return gained_totals
