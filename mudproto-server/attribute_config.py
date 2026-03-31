import json
from functools import lru_cache
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
ATTRIBUTE_CONFIG_ROOT = SERVER_ROOT / "configuration" / "attributes"
WEAR_SLOTS_FILE = ATTRIBUTE_CONFIG_ROOT / "wear_slots.json"
ATTRIBUTES_FILE = ATTRIBUTE_CONFIG_ROOT / "character_attributes.json"
REGENERATION_FILE = ATTRIBUTE_CONFIG_ROOT / "regeneration.json"
HAND_WEIGHT_FILE = ATTRIBUTE_CONFIG_ROOT / "hand_weight.json"
COMBAT_SEVERITY_FILE = ATTRIBUTE_CONFIG_ROOT / "combat_severity.json"


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
    for hand in ("main_hand", "off_hand"):
        raw_hand = raw_requirements.get(hand)
        if not isinstance(raw_hand, dict):
            raise ValueError(f"Hand weight config must include object for '{hand}'.")

        weight_multiplier = float(raw_hand.get("weight_multiplier", 1.0))
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