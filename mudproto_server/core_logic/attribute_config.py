import json
from functools import lru_cache
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent.parent
ATTRIBUTE_CONFIG_ROOT = SERVER_ROOT / "configuration" / "attributes"
WEAR_SLOTS_FILE = ATTRIBUTE_CONFIG_ROOT / "wear_slots.json"
ATTRIBUTES_FILE = ATTRIBUTE_CONFIG_ROOT / "character_attributes.json"
PLAYER_CLASSES_FILE = ATTRIBUTE_CONFIG_ROOT / "classes.json"
PASSIVES_FILE = ATTRIBUTE_CONFIG_ROOT / "passives.json"
REGENERATION_FILE = ATTRIBUTE_CONFIG_ROOT / "regeneration.json"
HAND_WEIGHT_FILE = ATTRIBUTE_CONFIG_ROOT / "hand_weight.json"
COMBAT_SEVERITY_FILE = ATTRIBUTE_CONFIG_ROOT / "combat_severity.json"
ITEM_USAGE_FILE = ATTRIBUTE_CONFIG_ROOT / "item_usage.json"
LEVEL_SCALING_FILE = ATTRIBUTE_CONFIG_ROOT / "level_scaling.json"
EXPERIENCE_TABLE_FILE = ATTRIBUTE_CONFIG_ROOT / "experience.json"
WEAPON_TYPES_FILE = ATTRIBUTE_CONFIG_ROOT / "weapon_types.json"
POSTURE_FILE = ATTRIBUTE_CONFIG_ROOT / "posture.json"


def _read_json_attribute_config(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_wear_slot_config() -> dict:
    raw_config = _read_json_attribute_config(WEAR_SLOTS_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Wear slots asset file must contain an object: {WEAR_SLOTS_FILE}")

    raw_wear_slots = raw_config.get("wear_slots", [])
    if raw_wear_slots is None:
        raw_wear_slots = []
    if not isinstance(raw_wear_slots, list):
        raise ValueError("Wear slots config field 'wear_slots' must be a list.")

    wear_slots = [str(slot).strip().lower() for slot in raw_wear_slots if str(slot).strip()]
    if not wear_slots:
        raise ValueError("Wear slots config must include at least one entry in 'wear_slots'.")

    raw_slot_options = raw_config.get("slot_options", {})
    if raw_slot_options is None:
        raw_slot_options = {}
    if not isinstance(raw_slot_options, dict):
        raise ValueError("Wear slots config field 'slot_options' must be an object.")

    slot_options: dict[str, list[str]] = {}
    for slot_name, raw_options in raw_slot_options.items():
        normalized_slot_name = str(slot_name).strip().lower()
        if not normalized_slot_name:
            raise ValueError("Wear slots config has an empty slot_options key.")
        if not isinstance(raw_options, list):
            raise ValueError(f"Wear slots config slot_options['{normalized_slot_name}'] must be a list.")

        normalized_options = [str(option).strip().lower() for option in raw_options if str(option).strip()]
        if not normalized_options:
            raise ValueError(
                f"Wear slots config slot_options['{normalized_slot_name}'] must include at least one slot."
            )
        slot_options[normalized_slot_name] = normalized_options

    raw_location_aliases = raw_config.get("location_aliases", {})
    if raw_location_aliases is None:
        raw_location_aliases = {}
    if not isinstance(raw_location_aliases, dict):
        raise ValueError("Wear slots config field 'location_aliases' must be an object.")

    location_aliases: dict[str, str] = {}
    for alias, target_slot in raw_location_aliases.items():
        normalized_alias = str(alias).strip().lower()
        normalized_target = str(target_slot).strip().lower()
        if not normalized_alias or not normalized_target:
            raise ValueError("Wear slots config has an empty location alias or target slot.")
        location_aliases[normalized_alias] = normalized_target

    return {
        "wear_slots": wear_slots,
        "slot_options": slot_options,
        "location_aliases": location_aliases,
    }


@lru_cache(maxsize=1)
def load_weapon_type_config() -> dict:
    raw_config = _read_json_attribute_config(WEAPON_TYPES_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Weapon type config file must contain an object: {WEAPON_TYPES_FILE}")

    raw_weapon_types = raw_config.get("weapon_types", {})
    if not isinstance(raw_weapon_types, dict) or not raw_weapon_types:
        raise ValueError("Weapon type config field 'weapon_types' must be a non-empty object.")

    normalized_weapon_types: dict[str, dict[str, str]] = {}
    for weapon_type_id, raw_entry in raw_weapon_types.items():
        normalized_weapon_type_id = str(weapon_type_id).strip().lower()
        if not normalized_weapon_type_id:
            raise ValueError("Weapon type config contains an empty weapon type id.")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Weapon type config entry '{normalized_weapon_type_id}' must be an object.")

        name = str(raw_entry.get("name", normalized_weapon_type_id.replace("_", " ").title())).strip()
        verb = str(raw_entry.get("verb", "")).strip().lower()
        if not verb:
            raise ValueError(f"Weapon type config entry '{normalized_weapon_type_id}' must include a non-empty verb.")

        normalized_weapon_types[normalized_weapon_type_id] = {
            "name": name or normalized_weapon_type_id.replace("_", " ").title(),
            "verb": verb,
        }

    default_weapon_type = str(raw_config.get("default_weapon_type", "unarmed")).strip().lower() or "unarmed"
    if default_weapon_type not in normalized_weapon_types:
        raise ValueError(
            f"Weapon type config default_weapon_type '{default_weapon_type}' must be defined in weapon_types."
        )

    return {
        "default_weapon_type": default_weapon_type,
        "weapon_types": normalized_weapon_types,
    }


@lru_cache(maxsize=1)
def load_attributes() -> list[dict]:
    raw_attributes = _read_json_attribute_config(ATTRIBUTES_FILE)
    if not isinstance(raw_attributes, list):
        raise ValueError(f"Attribute asset file must contain a list: {ATTRIBUTES_FILE}")

    normalized_attributes: list[dict] = []
    seen_ids: set[str] = set()

    for raw_attribute in raw_attributes:
        if not isinstance(raw_attribute, dict):
            raise ValueError("Attribute entries must be objects.")

        attribute_id = str(raw_attribute.get("attribute_id", "")).strip().lower()
        name = str(raw_attribute.get("name", "")).strip()
        if not attribute_id:
            raise ValueError("Attribute entries must include non-empty attribute_id.")
        if not attribute_id.isalpha():
            raise ValueError(f"Attribute id '{attribute_id}' must be alphabetic.")
        if attribute_id in seen_ids:
            raise ValueError(f"Duplicate attribute_id in attributes asset: {attribute_id}")
        if not name:
            raise ValueError(f"Attribute '{attribute_id}' must include non-empty name.")

        seen_ids.add(attribute_id)
        normalized_attributes.append({
            "attribute_id": attribute_id,
            "name": name,
        })

    if not normalized_attributes:
        raise ValueError("At least one attribute must be configured.")

    return normalized_attributes


@lru_cache(maxsize=1)
def load_passives() -> list[dict]:
    raw_passives = _read_json_attribute_config(PASSIVES_FILE)
    if not isinstance(raw_passives, list):
        raise ValueError(f"Passive asset file must contain a list: {PASSIVES_FILE}")

    configured_attribute_ids = {
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    }

    normalized_passives: list[dict] = []
    seen_ids: set[str] = set()
    for raw_passive in raw_passives:
        if not isinstance(raw_passive, dict):
            raise ValueError("Passive entries must be objects.")

        passive_id = str(raw_passive.get("passive_id", "")).strip().lower()
        name = str(raw_passive.get("name", "")).strip()
        description = str(raw_passive.get("description", "")).strip()
        if not passive_id:
            raise ValueError("Passive entries must include non-empty passive_id.")
        if passive_id in seen_ids:
            raise ValueError(f"Duplicate passive_id in passives asset: {passive_id}")
        if not name:
            raise ValueError(f"Passive '{passive_id}' must include non-empty name.")

        unarmed_damage_bonus = max(0, int(raw_passive.get("unarmed_damage_bonus", 0)))
        unarmed_scaling_attribute_id = str(raw_passive.get("unarmed_scaling_attribute_id", "")).strip().lower()
        unarmed_scaling_multiplier = max(0.0, float(raw_passive.get("unarmed_scaling_multiplier", 0.0)))
        unarmed_level_scaling_multiplier = max(0.0, float(raw_passive.get("unarmed_level_scaling_multiplier", 0.0)))
        unarmed_hit_roll_bonus = max(0, int(raw_passive.get("unarmed_hit_roll_bonus", 0)))
        unarmed_hit_scaling_attribute_id = str(raw_passive.get("unarmed_hit_scaling_attribute_id", "")).strip().lower()
        unarmed_hit_scaling_multiplier = max(0.0, float(raw_passive.get("unarmed_hit_scaling_multiplier", 0.0)))
        unarmed_hit_level_scaling_multiplier = max(0.0, float(raw_passive.get("unarmed_hit_level_scaling_multiplier", 0.0)))
        dual_unarmed_attacks = bool(raw_passive.get("dual_unarmed_attacks", False))

        if unarmed_scaling_attribute_id and unarmed_scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Passive '{passive_id}' unarmed_scaling_attribute_id references unknown attribute '{unarmed_scaling_attribute_id}'."
            )
        if unarmed_hit_scaling_attribute_id and unarmed_hit_scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Passive '{passive_id}' unarmed_hit_scaling_attribute_id references unknown attribute '{unarmed_hit_scaling_attribute_id}'."
            )

        seen_ids.add(passive_id)
        normalized_passives.append({
            "passive_id": passive_id,
            "name": name,
            "description": description,
            "unarmed_damage_bonus": unarmed_damage_bonus,
            "unarmed_scaling_attribute_id": unarmed_scaling_attribute_id,
            "unarmed_scaling_multiplier": unarmed_scaling_multiplier,
            "unarmed_level_scaling_multiplier": unarmed_level_scaling_multiplier,
            "unarmed_hit_roll_bonus": unarmed_hit_roll_bonus,
            "unarmed_hit_scaling_attribute_id": unarmed_hit_scaling_attribute_id,
            "unarmed_hit_scaling_multiplier": unarmed_hit_scaling_multiplier,
            "unarmed_hit_level_scaling_multiplier": unarmed_hit_level_scaling_multiplier,
            "dual_unarmed_attacks": dual_unarmed_attacks,
        })

    return normalized_passives


@lru_cache(maxsize=1)
def load_regeneration_config() -> dict:
    raw_config = _read_json_attribute_config(REGENERATION_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Regeneration asset file must contain an object: {REGENERATION_FILE}")

    raw_resources = raw_config.get("resources", {})
    if not isinstance(raw_resources, dict):
        raise ValueError("Regeneration config field 'resources' must be an object.")

    expected_resources = {"hit_points", "vigor", "mana"}
    configured_attribute_ids = {
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    }

    normalized_resources: dict[str, dict] = {}
    for resource_key in expected_resources:
        raw_resource = raw_resources.get(resource_key)
        if not isinstance(raw_resource, dict):
            raise ValueError(f"Regeneration config must include object for resource '{resource_key}'.")

        attribute_id = str(raw_resource.get("attribute_id", "")).strip().lower()
        if not attribute_id:
            raise ValueError(f"Regeneration config for '{resource_key}' must define attribute_id.")
        if attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Regeneration config for '{resource_key}' references unknown attribute_id '{attribute_id}'."
            )

        min_amount = int(raw_resource.get("min_amount", 0))
        if min_amount < 0:
            raise ValueError(f"Regeneration config for '{resource_key}' min_amount must be >= 0.")

        raw_mapping = raw_resource.get("percent_by_attribute", [])
        if not isinstance(raw_mapping, list) or not raw_mapping:
            raise ValueError(
                f"Regeneration config for '{resource_key}' must include non-empty percent_by_attribute list."
            )

        normalized_mapping: list[dict] = []
        for raw_entry in raw_mapping:
            if not isinstance(raw_entry, dict):
                raise ValueError(
                    f"Regeneration config for '{resource_key}' percent_by_attribute entries must be objects."
                )

            min_attribute = int(raw_entry.get("min", 0))
            percent = float(raw_entry.get("percent", 0.0))
            if percent < 0.0:
                raise ValueError(
                    f"Regeneration config for '{resource_key}' percent values must be >= 0.0."
                )

            normalized_mapping.append({
                "min": min_attribute,
                "percent": percent,
            })

        normalized_mapping.sort(key=lambda entry: int(entry["min"]))
        normalized_resources[resource_key] = {
            "attribute_id": attribute_id,
            "min_amount": min_amount,
            "percent_by_attribute": normalized_mapping,
        }

    for resource_key in raw_resources.keys():
        normalized_resource_key = str(resource_key).strip().lower()
        if normalized_resource_key not in expected_resources:
            raise ValueError(f"Regeneration config contains unknown resource '{resource_key}'.")

    return {
        "resources": normalized_resources,
    }


@lru_cache(maxsize=1)
def load_hand_weight_config() -> dict:
    raw_config = _read_json_attribute_config(HAND_WEIGHT_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Hand weight config file must contain an object: {HAND_WEIGHT_FILE}")

    strength_attribute_id = str(raw_config.get("strength_attribute_id", "str")).strip().lower() or "str"
    if not strength_attribute_id.isalpha():
        raise ValueError("Hand weight config field 'strength_attribute_id' must be alphabetic.")

    raw_requirements = raw_config.get("hand_requirements", {})
    if not isinstance(raw_requirements, dict):
        raise ValueError("Hand weight config field 'hand_requirements' must be an object.")

    normalized_requirements: dict[str, dict[str, float]] = {}
    default_multipliers = {
        "main_hand": 1.0,
        "off_hand": 1.5,
        "both_hands": 0.75,
    }
    for hand in ("main_hand", "off_hand", "both_hands"):
        raw_hand = raw_requirements.get(hand)
        if raw_hand is None:
            raw_hand = {"weight_multiplier": default_multipliers[hand]}
        if not isinstance(raw_hand, dict):
            raise ValueError(f"Hand weight config must include object for '{hand}'.")

        weight_multiplier = float(raw_hand.get("weight_multiplier", default_multipliers[hand]))
        if weight_multiplier <= 0:
            raise ValueError(f"Hand weight config '{hand}.weight_multiplier' must be > 0.")

        normalized_requirements[hand] = {
            "weight_multiplier": weight_multiplier,
        }

    return {
        "strength_attribute_id": strength_attribute_id,
        "hand_requirements": normalized_requirements,
    }


@lru_cache(maxsize=1)
def load_combat_severity_config() -> dict:
    raw_config = _read_json_attribute_config(COMBAT_SEVERITY_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Combat severity config file must contain an object: {COMBAT_SEVERITY_FILE}")

    raw_tiers = raw_config.get("tiers", [])
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise ValueError("Combat severity config field 'tiers' must be a non-empty list.")

    normalized_tiers: list[dict] = []
    previous_max_damage: int | None = None

    for index, raw_tier in enumerate(raw_tiers):
        if not isinstance(raw_tier, dict):
            raise ValueError("Combat severity config tiers must be objects.")

        label = str(raw_tier.get("label", "")).strip().lower()
        if not label:
            raise ValueError("Combat severity config tiers must include a non-empty label.")

        raw_max_damage = raw_tier.get("max_damage")
        if raw_max_damage is None:
            if index != len(raw_tiers) - 1:
                raise ValueError("Combat severity config only allows an open-ended tier as the final entry.")
            normalized_tiers.append({
                "label": label,
                "max_damage": None,
            })
            continue

        max_damage = int(raw_max_damage)
        if max_damage < 0:
            raise ValueError("Combat severity config max_damage values must be zero or greater.")
        if previous_max_damage is not None and max_damage <= previous_max_damage:
            raise ValueError("Combat severity config max_damage values must be strictly increasing.")

        previous_max_damage = max_damage
        normalized_tiers.append({
            "label": label,
            "max_damage": max_damage,
        })

    if normalized_tiers[-1].get("max_damage") is not None:
        raise ValueError("Combat severity config must end with an open-ended final tier.")

    return {
        "tiers": normalized_tiers,
    }


@lru_cache(maxsize=1)
def load_item_usage_config() -> dict:
    raw_config = _read_json_attribute_config(ITEM_USAGE_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Item usage config file must contain an object: {ITEM_USAGE_FILE}")

    raw_potion = raw_config.get("potion", {})
    if not isinstance(raw_potion, dict):
        raise ValueError("Item usage config field 'potion' must be an object.")

    cooldown_rounds = int(raw_potion.get("cooldown_rounds", 0))
    if cooldown_rounds < 0:
        raise ValueError("Item usage config 'potion.cooldown_rounds' must be zero or greater.")

    return {
        "potion": {
            "cooldown_rounds": cooldown_rounds,
        }
    }


@lru_cache(maxsize=1)
def load_posture_config() -> dict:
    raw_config = _read_json_attribute_config(POSTURE_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Posture config file must contain an object: {POSTURE_FILE}")

    posture_states: dict[str, dict] = {}
    for posture_state in ("sitting", "resting", "sleeping"):
        raw_state = raw_config.get(posture_state, {})
        if not isinstance(raw_state, dict):
            raise ValueError(f"Posture config '{posture_state}' must be an object.")

        received_damage_multiplier = float(raw_state.get("received_damage_multiplier", 1.0))
        if received_damage_multiplier < 1.0:
            raise ValueError(
                f"Posture config '{posture_state}.received_damage_multiplier' must be >= 1.0."
            )

        dealt_damage_multiplier = float(raw_state.get("dealt_damage_multiplier", 1.0))
        if dealt_damage_multiplier <= 0.0:
            raise ValueError(
                f"Posture config '{posture_state}.dealt_damage_multiplier' must be > 0.0."
            )

        prevents_movement = bool(raw_state.get("prevents_movement", False))
        prevents_skill_spell_use = bool(raw_state.get("prevents_skill_spell_use", False))
        prevents_observation_commands = bool(raw_state.get("prevents_observation_commands", False))
        regeneration_bonus_multiplier = float(raw_state.get("regeneration_bonus_multiplier", 1.0))
        if regeneration_bonus_multiplier < 1.0:
            raise ValueError(
                f"Posture config '{posture_state}.regeneration_bonus_multiplier' must be >= 1.0."
            )

        posture_states[posture_state] = {
            "received_damage_multiplier": received_damage_multiplier,
            "dealt_damage_multiplier": dealt_damage_multiplier,
            "prevents_movement": prevents_movement,
            "prevents_skill_spell_use": prevents_skill_spell_use,
            "prevents_observation_commands": prevents_observation_commands,
            "regeneration_bonus_multiplier": regeneration_bonus_multiplier,
        }

    return {
        "sitting": posture_states["sitting"],
        "resting": posture_states["resting"],
        "sleeping": posture_states["sleeping"],
    }


def get_sitting_damage_multiplier() -> float:
    return float(get_posture_received_damage_multiplier("sitting"))


def get_posture_received_damage_multiplier(posture_state: str) -> float:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return 1.0
    return max(1.0, float(posture_config.get("received_damage_multiplier", 1.0)))


def get_posture_dealt_damage_multiplier(posture_state: str) -> float:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return 1.0
    return max(0.0, float(posture_config.get("dealt_damage_multiplier", 1.0)))


def posture_prevents_movement(posture_state: str) -> bool:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return False
    return bool(posture_config.get("prevents_movement", False))


def posture_prevents_skill_spell_use(posture_state: str) -> bool:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return False
    return bool(posture_config.get("prevents_skill_spell_use", False))


def posture_prevents_observation_commands(posture_state: str) -> bool:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return False
    return bool(posture_config.get("prevents_observation_commands", False))


def get_posture_regeneration_bonus_multiplier(posture_state: str) -> float:
    normalized_state = str(posture_state).strip().lower()
    posture_config = load_posture_config().get(normalized_state, {})
    if not isinstance(posture_config, dict):
        return 1.0
    return max(1.0, float(posture_config.get("regeneration_bonus_multiplier", 1.0)))


@lru_cache(maxsize=1)
def load_level_scaling_config() -> dict:
    raw_config = _read_json_attribute_config(LEVEL_SCALING_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Level scaling config file must contain an object: {LEVEL_SCALING_FILE}")

    raw_melee = raw_config.get("melee", {})
    if not isinstance(raw_melee, dict):
        raise ValueError("Level scaling config field 'melee' must be an object.")

    def _normalize_rule(rule_name: str) -> dict[str, int]:
        raw_rule = raw_melee.get(rule_name, {})
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Level scaling config melee rule '{rule_name}' must be an object.")

        levels_per_bonus = int(raw_rule.get("levels_per_bonus", 0))
        bonus_per_step = int(raw_rule.get("bonus_per_step", 0))
        if levels_per_bonus < 0:
            raise ValueError(f"Level scaling config '{rule_name}.levels_per_bonus' must be >= 0.")
        if bonus_per_step < 0:
            raise ValueError(f"Level scaling config '{rule_name}.bonus_per_step' must be >= 0.")

        return {
            "levels_per_bonus": levels_per_bonus,
            "bonus_per_step": bonus_per_step,
        }

    return {
        "melee": {
            "hit_roll": _normalize_rule("hit_roll"),
            "damage_roll": _normalize_rule("damage_roll"),
        }
    }


@lru_cache(maxsize=1)
def load_experience_table() -> list[dict]:
    raw_config = _read_json_attribute_config(EXPERIENCE_TABLE_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"Experience config file must contain an object: {EXPERIENCE_TABLE_FILE}")

    raw_levels = raw_config.get("levels", [])
    if not isinstance(raw_levels, list) or not raw_levels:
        raise ValueError("Experience config field 'levels' must be a non-empty list.")

    normalized_levels: list[dict] = []
    seen_levels: set[int] = set()
    for raw_level in raw_levels:
        if not isinstance(raw_level, dict):
            raise ValueError("Experience levels entries must be objects.")

        level = int(raw_level.get("level", 0))
        total_experience = int(raw_level.get("total_experience", 0))
        if level <= 0:
            raise ValueError("Experience levels must use level >= 1.")
        if total_experience < 0:
            raise ValueError("Experience level total_experience must be >= 0.")
        if level in seen_levels:
            raise ValueError(f"Duplicate level in experience table: {level}")
        seen_levels.add(level)

        normalized_levels.append({
            "level": level,
            "total_experience": total_experience,
        })

    normalized_levels.sort(key=lambda row: int(row["level"]))
    if int(normalized_levels[0]["level"]) != 1 or int(normalized_levels[0]["total_experience"]) != 0:
        raise ValueError("Experience table must start at level 1 with total_experience 0.")

    previous_total = -1
    previous_level = 0
    for row in normalized_levels:
        level = int(row["level"])
        total_experience = int(row["total_experience"])
        if level != previous_level + 1:
            raise ValueError("Experience levels must be contiguous (1, 2, 3, ...).")
        if total_experience <= previous_total:
            raise ValueError("Experience total_experience values must be strictly increasing.")
        previous_level = level
        previous_total = total_experience

    return normalized_levels


@lru_cache(maxsize=1)
def load_player_classes() -> list[dict]:
    # Import locally to avoid circular imports with assets.py.
    from assets import get_gear_template_by_id, get_item_template_by_id, get_skill_by_id, get_spell_by_id

    raw_classes = _read_json_attribute_config(PLAYER_CLASSES_FILE)
    if not isinstance(raw_classes, list):
        raise ValueError(f"Player class asset file must contain a list: {PLAYER_CLASSES_FILE}")

    class_ids: set[str] = set()
    class_names: set[str] = set()
    normalized_classes: list[dict] = []

    configured_attribute_ids = {
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    }

    for raw_class in raw_classes:
        if not isinstance(raw_class, dict):
            raise ValueError("Player class entries must be objects.")

        class_id = raw_class.get("class_id")
        name = raw_class.get("name")
        if not isinstance(class_id, str) or not class_id.strip():
            raise ValueError("Player class entries must include a non-empty string class_id.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Player class '{class_id}' must include a non-empty name.")

        normalized_class_id = class_id.strip().lower()
        normalized_class_name = name.strip().lower()
        if normalized_class_id in class_ids:
            raise ValueError(f"Duplicate class_id in player classes: {class_id}")
        if normalized_class_name in class_names:
            raise ValueError(f"Duplicate class name in player classes: {name}")

        raw_gear_ids = raw_class.get("starting_gear_template_ids", [])
        raw_spell_ids = raw_class.get("starting_spell_ids", [])
        raw_skill_ids = raw_class.get("starting_skill_ids", [])
        raw_passive_ids = raw_class.get("starting_passive_ids", [])
        raw_equipped_gear_ids = raw_class.get("starting_equipped_gear_template_ids", [])
        raw_item_ids = raw_class.get("starting_item_ids", [])
        raw_attribute_ranges = raw_class.get("attribute_ranges", {})
        raw_resource_progression = raw_class.get("resource_progression", {})
        uses_mana = bool(raw_class.get("uses_mana", True))
        unarmed_damage_bonus = int(raw_class.get("unarmed_damage_bonus", 0))
        unarmed_scaling_attribute_id = str(raw_class.get("unarmed_scaling_attribute_id", "")).strip().lower()
        unarmed_scaling_multiplier = float(raw_class.get("unarmed_scaling_multiplier", 0.0))
        unarmed_level_scaling_multiplier = float(raw_class.get("unarmed_level_scaling_multiplier", 0.0))
        unarmed_hit_roll_bonus = int(raw_class.get("unarmed_hit_roll_bonus", 0))
        unarmed_hit_scaling_attribute_id = str(raw_class.get("unarmed_hit_scaling_attribute_id", "")).strip().lower()
        unarmed_hit_scaling_multiplier = float(raw_class.get("unarmed_hit_scaling_multiplier", 0.0))
        unarmed_hit_level_scaling_multiplier = float(raw_class.get("unarmed_hit_level_scaling_multiplier", 0.0))
        dual_unarmed_attacks = bool(raw_class.get("dual_unarmed_attacks", False))
        if not isinstance(raw_gear_ids, list):
            raise ValueError(
                f"Player class '{class_id}' starting_gear_template_ids must be a list."
            )
        if not isinstance(raw_spell_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_spell_ids must be a list.")
        if not isinstance(raw_skill_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_skill_ids must be a list.")
        if not isinstance(raw_passive_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_passive_ids must be a list.")
        if not isinstance(raw_equipped_gear_ids, list):
            raise ValueError(
                f"Player class '{class_id}' starting_equipped_gear_template_ids must be a list."
            )
        if not isinstance(raw_item_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_item_ids must be a list.")
        if not isinstance(raw_attribute_ranges, dict):
            raise ValueError(f"Player class '{class_id}' attribute_ranges must be an object.")
        if not isinstance(raw_resource_progression, dict):
            raise ValueError(f"Player class '{class_id}' resource_progression must be an object.")
        if unarmed_damage_bonus < 0:
            raise ValueError(f"Player class '{class_id}' unarmed_damage_bonus must be zero or greater.")
        if unarmed_scaling_attribute_id and unarmed_scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Player class '{class_id}' unarmed_scaling_attribute_id references unknown attribute '{unarmed_scaling_attribute_id}'."
            )
        if unarmed_scaling_multiplier < 0.0:
            raise ValueError(f"Player class '{class_id}' unarmed_scaling_multiplier must be zero or greater.")
        if unarmed_level_scaling_multiplier < 0.0:
            raise ValueError(f"Player class '{class_id}' unarmed_level_scaling_multiplier must be zero or greater.")
        if unarmed_hit_roll_bonus < 0:
            raise ValueError(f"Player class '{class_id}' unarmed_hit_roll_bonus must be zero or greater.")
        if unarmed_hit_scaling_attribute_id and unarmed_hit_scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Player class '{class_id}' unarmed_hit_scaling_attribute_id references unknown attribute '{unarmed_hit_scaling_attribute_id}'."
            )
        if unarmed_hit_scaling_multiplier < 0.0:
            raise ValueError(f"Player class '{class_id}' unarmed_hit_scaling_multiplier must be zero or greater.")
        if unarmed_hit_level_scaling_multiplier < 0.0:
            raise ValueError(f"Player class '{class_id}' unarmed_hit_level_scaling_multiplier must be zero or greater.")

        attribute_ranges: dict[str, dict[str, int]] = {}
        for attribute_id in configured_attribute_ids:
            if attribute_id not in raw_attribute_ranges:
                raise ValueError(
                    f"Player class '{class_id}' must define attribute_ranges for '{attribute_id}'."
                )

            raw_range = raw_attribute_ranges.get(attribute_id)
            if not isinstance(raw_range, dict):
                raise ValueError(
                    f"Player class '{class_id}' attribute_ranges['{attribute_id}'] must be an object."
                )

            min_value = int(raw_range.get("min", 0))
            max_value = int(raw_range.get("max", 0))
            if min_value > max_value:
                raise ValueError(
                    f"Player class '{class_id}' attribute_ranges['{attribute_id}'] has min > max."
                )

            attribute_ranges[attribute_id] = {
                "min": min_value,
                "max": max_value,
            }

        for attribute_id in raw_attribute_ranges.keys():
            normalized_attribute_id = str(attribute_id).strip().lower()
            if normalized_attribute_id not in configured_attribute_ids:
                raise ValueError(
                    f"Player class '{class_id}' attribute_ranges references unknown attribute: {attribute_id}"
                )

        normalized_resource_progression: dict[str, dict] = {}
        for resource_key, default_attribute in (("hit_points", "con"), ("vigor", "dex"), ("mana", "wis")):
            raw_resource = raw_resource_progression.get(resource_key, {})
            if not isinstance(raw_resource, dict):
                raise ValueError(
                    f"Player class '{class_id}' resource_progression['{resource_key}'] must be an object."
                )

            minimum_base = 0 if resource_key == "mana" and not uses_mana else 1
            base = int(raw_resource.get("base", 0))
            attribute_id = str(raw_resource.get("attribute_id", default_attribute)).strip().lower() or default_attribute
            attribute_multiplier = float(raw_resource.get("attribute_multiplier", 1.0))
            per_level_min = int(raw_resource.get("per_level_min", 0))
            per_level_max = int(raw_resource.get("per_level_max", 0))

            if base < minimum_base:
                comparator = ">= 0" if minimum_base == 0 else "> 0"
                raise ValueError(
                    f"Player class '{class_id}' resource_progression['{resource_key}'].base must be {comparator}."
                )
            if attribute_id not in configured_attribute_ids:
                raise ValueError(
                    f"Player class '{class_id}' resource_progression['{resource_key}'] references unknown attribute_id '{attribute_id}'."
                )
            if attribute_multiplier < 0.0:
                raise ValueError(
                    f"Player class '{class_id}' resource_progression['{resource_key}'].attribute_multiplier must be >= 0.0."
                )
            if per_level_min < 0 or per_level_max < 0:
                raise ValueError(
                    f"Player class '{class_id}' resource_progression['{resource_key}'] per-level values must be >= 0."
                )

            if resource_key == "mana" and not uses_mana:
                base = 0
                attribute_multiplier = 0.0
                per_level_min = 0
                per_level_max = 0

            normalized_resource_progression[resource_key] = {
                "base": base,
                "attribute_id": attribute_id,
                "attribute_multiplier": attribute_multiplier,
                "per_level_min": per_level_min,
                "per_level_max": per_level_max,
            }

        gear_ids: list[str] = []
        seen_gear_ids: set[str] = set()
        for raw_template_id in raw_gear_ids:
            template_id = str(raw_template_id).strip()
            if not template_id:
                continue
            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_gear_ids:
                continue
            if get_gear_template_by_id(template_id) is None:
                raise ValueError(
                    f"Player class '{class_id}' references unknown gear template: {template_id}"
                )
            seen_gear_ids.add(normalized_template_id)
            gear_ids.append(template_id)

        spell_ids: list[str] = []
        seen_spell_ids: set[str] = set()
        for raw_spell_id in raw_spell_ids:
            spell_id = str(raw_spell_id).strip()
            if not spell_id:
                continue
            normalized_spell_id = spell_id.lower()
            if normalized_spell_id in seen_spell_ids:
                continue
            if get_spell_by_id(spell_id) is None:
                raise ValueError(f"Player class '{class_id}' references unknown spell: {spell_id}")
            seen_spell_ids.add(normalized_spell_id)
            spell_ids.append(spell_id)

        skill_ids: list[str] = []
        seen_skill_ids: set[str] = set()
        for raw_skill_id in raw_skill_ids:
            skill_id = str(raw_skill_id).strip()
            if not skill_id:
                continue
            normalized_skill_id = skill_id.lower()
            if normalized_skill_id in seen_skill_ids:
                continue
            if get_skill_by_id(skill_id) is None:
                raise ValueError(f"Player class '{class_id}' references unknown skill: {skill_id}")
            seen_skill_ids.add(normalized_skill_id)
            skill_ids.append(skill_id)

        available_passive_ids = {
            str(passive.get("passive_id", "")).strip().lower()
            for passive in load_passives()
            if str(passive.get("passive_id", "")).strip()
        }
        passive_ids: list[str] = []
        seen_passive_ids: set[str] = set()
        for raw_passive_id in raw_passive_ids:
            passive_id = str(raw_passive_id).strip()
            if not passive_id:
                continue
            normalized_passive_id = passive_id.lower()
            if normalized_passive_id in seen_passive_ids:
                continue
            if normalized_passive_id not in available_passive_ids:
                raise ValueError(f"Player class '{class_id}' references unknown passive: {passive_id}")
            seen_passive_ids.add(normalized_passive_id)
            passive_ids.append(passive_id)

        equipped_gear_ids: list[str] = []
        seen_equipped_gear_ids: set[str] = set()
        for raw_template_id in raw_equipped_gear_ids:
            template_id = str(raw_template_id).strip()
            if not template_id:
                continue
            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_equipped_gear_ids:
                continue
            if get_gear_template_by_id(template_id) is None:
                raise ValueError(
                    f"Player class '{class_id}' references unknown gear template: {template_id}"
                )
            seen_equipped_gear_ids.add(normalized_template_id)
            equipped_gear_ids.append(template_id)

        item_ids: list[str] = []
        seen_item_ids: set[str] = set()
        for raw_template_id in raw_item_ids:
            template_id = str(raw_template_id).strip()
            if not template_id:
                continue
            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_item_ids:
                continue
            if get_item_template_by_id(template_id) is None:
                raise ValueError(f"Player class '{class_id}' references unknown item template: {template_id}")
            seen_item_ids.add(normalized_template_id)
            item_ids.append(template_id)

        class_ids.add(normalized_class_id)
        class_names.add(normalized_class_name)
        normalized_classes.append({
            "class_id": class_id.strip(),
            "name": name.strip(),
            "description": str(raw_class.get("description", "")).strip(),
            "uses_mana": uses_mana,
            "unarmed_damage_bonus": unarmed_damage_bonus,
            "unarmed_scaling_attribute_id": unarmed_scaling_attribute_id,
            "unarmed_scaling_multiplier": unarmed_scaling_multiplier,
            "unarmed_level_scaling_multiplier": unarmed_level_scaling_multiplier,
            "unarmed_hit_roll_bonus": unarmed_hit_roll_bonus,
            "unarmed_hit_scaling_attribute_id": unarmed_hit_scaling_attribute_id,
            "unarmed_hit_scaling_multiplier": unarmed_hit_scaling_multiplier,
            "unarmed_hit_level_scaling_multiplier": unarmed_hit_level_scaling_multiplier,
            "dual_unarmed_attacks": dual_unarmed_attacks,
            "attribute_ranges": attribute_ranges,
            "starting_gear_template_ids": gear_ids,
            "starting_equipped_gear_template_ids": equipped_gear_ids,
            "starting_item_ids": item_ids,
            "starting_spell_ids": spell_ids,
            "starting_skill_ids": skill_ids,
            "starting_passive_ids": passive_ids,
            "resource_progression": normalized_resource_progression,
            "is_default": bool(raw_class.get("is_default", False)),
        })

    if not normalized_classes:
        raise ValueError("At least one player class must be defined.")

    default_class_count = sum(1 for player_class in normalized_classes if player_class["is_default"])
    if default_class_count == 0:
        raise ValueError("One player class must set is_default to true.")
    if default_class_count > 1:
        raise ValueError("Only one player class can set is_default to true.")

    return normalized_classes


def get_player_class_by_id(class_id: str) -> dict | None:
    normalized = class_id.strip().lower()
    for player_class in load_player_classes():
        if str(player_class.get("class_id", "")).strip().lower() == normalized:
            return player_class
    return None


def player_class_uses_mana(class_id: str) -> bool:
    normalized = str(class_id).strip()
    player_class = get_player_class_by_id(normalized) if normalized else None
    if player_class is None:
        player_class = get_default_player_class()
    return bool(player_class.get("uses_mana", True))


def get_default_player_class() -> dict:
    for player_class in load_player_classes():
        if bool(player_class.get("is_default", False)):
            return player_class
    raise ValueError("No default player class is configured.")