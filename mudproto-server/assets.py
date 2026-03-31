import json
from functools import lru_cache
from pathlib import Path

from settings import CONFIGURABLE_ASSET_ROOT


SERVER_ROOT = Path(__file__).resolve().parent
ATTRIBUTE_CONFIG_ROOT = SERVER_ROOT / "configuration" / "attributes"
EQUIPMENT_FILE = CONFIGURABLE_ASSET_ROOT / "equipment.json"
ROOMS_FILE = CONFIGURABLE_ASSET_ROOT / "rooms.json"
SPELLS_FILE = CONFIGURABLE_ASSET_ROOT / "spells.json"
SKILLS_FILE = CONFIGURABLE_ASSET_ROOT / "skills.json"
PLAYER_CLASSES_FILE = ATTRIBUTE_CONFIG_ROOT / "classes.json"
WEAR_SLOTS_FILE = ATTRIBUTE_CONFIG_ROOT / "wear_slots.json"
NPCS_FILE = CONFIGURABLE_ASSET_ROOT / "npcs.json"
ATTRIBUTES_FILE = ATTRIBUTE_CONFIG_ROOT / "character_attributes.json"
REGENERATION_FILE = ATTRIBUTE_CONFIG_ROOT / "regeneration.json"
HAND_WEIGHT_FILE = ATTRIBUTE_CONFIG_ROOT / "hand_weight.json"


def _read_json_asset(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_wear_slot_config() -> dict:
    raw_config = _read_json_asset(WEAR_SLOTS_FILE)
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
def load_equipment_templates() -> list[dict]:
    raw_templates = _read_json_asset(EQUIPMENT_FILE)
    if not isinstance(raw_templates, list):
        raise ValueError(f"Equipment asset file must contain a list: {EQUIPMENT_FILE}")

    template_ids: set[str] = set()
    normalized_templates: list[dict] = []

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Equipment asset entries must be objects.")

        template_id = raw_template.get("template_id")
        name = raw_template.get("name")
        slot = raw_template.get("slot")

        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("Equipment asset entries must include a non-empty string template_id.")
        if template_id in template_ids:
            raise ValueError(f"Duplicate equipment template_id: {template_id}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Equipment asset '{template_id}' must include a non-empty name.")
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"Equipment asset '{template_id}' must include a non-empty slot.")
        normalized_slot = slot.strip().lower()
        if normalized_slot not in {"weapon", "armor"}:
            raise ValueError(
                f"Equipment asset '{template_id}' slot must be 'weapon' or 'armor'."
            )

        template_ids.add(template_id)
        raw_keywords = raw_template.get("keywords", [])
        if raw_keywords is None:
            raw_keywords = []
        if not isinstance(raw_keywords, list):
            raise ValueError(f"Equipment asset '{template_id}' keywords must be a list.")

        legacy_wear_slot = str(raw_template.get("wear_slot", "")).strip().lower()
        raw_wear_slots = raw_template.get("wear_slots", [])
        if raw_wear_slots is None:
            raw_wear_slots = []
        if not isinstance(raw_wear_slots, list):
            raise ValueError(f"Equipment asset '{template_id}' wear_slots must be a list.")
        wear_slots = [str(slot).strip().lower() for slot in raw_wear_slots if str(slot).strip()]
        if legacy_wear_slot and legacy_wear_slot not in wear_slots:
            wear_slots.insert(0, legacy_wear_slot)

        armor_class_bonus = int(raw_template.get("armor_class_bonus", 0))
        if normalized_slot == "armor" and not wear_slots:
            raise ValueError(f"Equipment asset '{template_id}' armor items must define wear_slots.")
        if normalized_slot == "weapon" and legacy_wear_slot:
            raise ValueError(f"Equipment asset '{template_id}' weapons cannot define wear_slot.")
        if normalized_slot == "weapon" and wear_slots:
            raise ValueError(f"Equipment asset '{template_id}' weapons cannot define wear_slots.")
        if armor_class_bonus < 0:
            raise ValueError(f"Equipment asset '{template_id}' armor_class_bonus must be zero or greater.")

        normalized_templates.append({
            "template_id": template_id,
            "name": name,
            "slot": normalized_slot,
            "description": str(raw_template.get("description", "")),
            "keywords": [str(keyword).strip().lower() for keyword in raw_keywords if str(keyword).strip()],
            "weapon_type": str(raw_template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
            "can_hold": bool(raw_template.get("can_hold", False)) if normalized_slot == "weapon" else False,
            "weight": max(0, int(raw_template.get("weight", 0))),
            "damage_dice_count": int(raw_template.get("damage_dice_count", 0)),
            "damage_dice_sides": int(raw_template.get("damage_dice_sides", 0)),
            "damage_roll_modifier": int(raw_template.get("damage_roll_modifier", 0)),
            "hit_roll_modifier": int(raw_template.get("hit_roll_modifier", 0)),
            "attack_damage_bonus": int(raw_template.get("attack_damage_bonus", 0)),
            "attacks_per_round_bonus": int(raw_template.get("attacks_per_round_bonus", 0)),
            "armor_class_bonus": armor_class_bonus,
            "wear_slots": wear_slots,
        })

    return normalized_templates


def get_equipment_template_by_id(template_id: str) -> dict | None:
    normalized = template_id.strip().lower()
    for template in load_equipment_templates():
        if str(template.get("template_id", "")).strip().lower() == normalized:
            return template
    return None


@lru_cache(maxsize=1)
def load_rooms() -> list[dict]:
    raw_rooms = _read_json_asset(ROOMS_FILE)
    if not isinstance(raw_rooms, list):
        raise ValueError(f"Room asset file must contain a list: {ROOMS_FILE}")

    room_ids: set[str] = set()
    normalized_rooms: list[dict] = []

    for raw_room in raw_rooms:
        if not isinstance(raw_room, dict):
            raise ValueError("Room asset entries must be objects.")

        room_id = raw_room.get("room_id")
        title = raw_room.get("title")
        description = raw_room.get("description")
        exits = raw_room.get("exits", {})
        room_npcs = raw_room.get("npcs", [])

        if not isinstance(room_id, str) or not room_id.strip():
            raise ValueError("Room asset entries must include a non-empty string room_id.")
        if room_id in room_ids:
            raise ValueError(f"Duplicate room_id in room assets: {room_id}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Room asset '{room_id}' must include a non-empty title.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Room asset '{room_id}' must include a non-empty description.")
        if not isinstance(exits, dict):
            raise ValueError(f"Room asset '{room_id}' exits must be an object.")
        if room_npcs is None:
            room_npcs = []
        if not isinstance(room_npcs, list):
            raise ValueError(f"Room asset '{room_id}' npcs must be a list.")

        normalized_exits: dict[str, str] = {}
        for direction, destination_room_id in exits.items():
            if not isinstance(direction, str) or not direction.strip():
                raise ValueError(f"Room asset '{room_id}' has an exit with an invalid direction.")
            if not isinstance(destination_room_id, str) or not destination_room_id.strip():
                raise ValueError(f"Room asset '{room_id}' exit '{direction}' has an invalid destination room id.")
            normalized_exits[direction.strip().lower()] = destination_room_id.strip()

        normalized_npcs: list[dict] = []
        for raw_npc_spawn in room_npcs:
            if not isinstance(raw_npc_spawn, dict):
                raise ValueError(f"Room asset '{room_id}' npc spawn entries must be objects.")

            npc_id = raw_npc_spawn.get("npc_id")
            if not isinstance(npc_id, str) or not npc_id.strip():
                raise ValueError(f"Room asset '{room_id}' npc spawn entries must include npc_id.")

            spawn_count = int(raw_npc_spawn.get("count", 1))
            if spawn_count <= 0:
                raise ValueError(f"Room asset '{room_id}' npc '{npc_id}' count must be 1 or greater.")

            normalized_npcs.append({
                "npc_id": npc_id.strip(),
                "count": spawn_count,
            })

        room_ids.add(room_id)
        normalized_rooms.append({
            "room_id": room_id,
            "title": title,
            "description": description,
            "exits": normalized_exits,
            "npcs": normalized_npcs,
        })

    return normalized_rooms


@lru_cache(maxsize=1)
def load_npc_templates() -> list[dict]:
    raw_config = _read_json_asset(NPCS_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"NPC asset file must contain an object: {NPCS_FILE}")

    raw_npcs = raw_config.get("npcs", [])
    if raw_npcs is None:
        raw_npcs = []
    if not isinstance(raw_npcs, list):
        raise ValueError("NPC asset field 'npcs' must be a list.")

    normalized_npcs: list[dict] = []
    npc_ids: set[str] = set()

    for raw_npc in raw_npcs:
        if not isinstance(raw_npc, dict):
            raise ValueError("NPC entries must be objects.")

        npc_id = str(raw_npc.get("npc_id", "")).strip()
        if not npc_id:
            raise ValueError("NPC entries must include npc_id.")
        if npc_id in npc_ids:
            raise ValueError(f"Duplicate npc_id in npc assets: {npc_id}")

        name = str(raw_npc.get("name", "")).strip()
        if not name:
            raise ValueError(f"NPC '{npc_id}' must define name.")

        max_hit_points = int(raw_npc.get("max_hit_points", raw_npc.get("hit_points", 1)))
        hit_points = int(raw_npc.get("hit_points", max_hit_points))
        if max_hit_points <= 0:
            raise ValueError(f"NPC '{npc_id}' max_hit_points must be greater than zero.")
        if hit_points <= 0:
            raise ValueError(f"NPC '{npc_id}' hit_points must be greater than zero.")

        raw_loot_items = raw_npc.get("loot_items", [])
        if raw_loot_items is None:
            raw_loot_items = []
        if not isinstance(raw_loot_items, list):
            raise ValueError(f"NPC '{npc_id}' loot_items must be a list.")

        normalized_loot_items: list[dict] = []
        for raw_loot_item in raw_loot_items:
            if not isinstance(raw_loot_item, dict):
                raise ValueError(f"NPC '{npc_id}' loot items must be objects.")
            loot_name = str(raw_loot_item.get("name", "")).strip()
            if not loot_name:
                raise ValueError(f"NPC '{npc_id}' loot items must include name.")
            raw_loot_keywords = raw_loot_item.get("keywords", [])
            if raw_loot_keywords is None:
                raw_loot_keywords = []
            if not isinstance(raw_loot_keywords, list):
                raise ValueError(f"NPC '{npc_id}' loot item '{loot_name}' keywords must be a list.")

            normalized_loot_items.append({
                "name": loot_name,
                "description": str(raw_loot_item.get("description", "")),
                "keywords": [str(keyword).strip().lower() for keyword in raw_loot_keywords if str(keyword).strip()],
            })

        raw_skill_ids = raw_npc.get("skill_ids", [])
        if raw_skill_ids is None:
            raw_skill_ids = []
        if not isinstance(raw_skill_ids, list):
            raise ValueError(f"NPC '{npc_id}' skill_ids must be a list.")

        skill_use_chance = float(raw_npc.get("skill_use_chance", 0.35))
        if skill_use_chance < 0.0 or skill_use_chance > 1.0:
            raise ValueError(f"NPC '{npc_id}' skill_use_chance must be between 0.0 and 1.0.")

        npc_ids.add(npc_id)
        normalized_npcs.append({
            "npc_id": npc_id,
            "name": name,
            "hit_points": hit_points,
            "max_hit_points": max_hit_points,
            "attack_damage": int(raw_npc.get("attack_damage", 1)),
            "attacks_per_round": int(raw_npc.get("attacks_per_round", 1)),
            "hit_roll_modifier": int(raw_npc.get("hit_roll_modifier", 0)),
            "armor_class": int(raw_npc.get("armor_class", 10)),
            "off_hand_attack_damage": int(raw_npc.get("off_hand_attack_damage", 0)),
            "off_hand_attacks_per_round": int(raw_npc.get("off_hand_attacks_per_round", 0)),
            "off_hand_hit_roll_modifier": int(raw_npc.get("off_hand_hit_roll_modifier", 0)),
            "off_hand_attack_verb": str(raw_npc.get("off_hand_attack_verb", "hit")).strip().lower() or "hit",
            "off_hand_weapon_name": str(raw_npc.get("off_hand_weapon_name", "off-hand")).strip() or "off-hand",
            "coin_reward": max(0, int(raw_npc.get("coin_reward", 0))),
            "is_aggro": bool(raw_npc.get("is_aggro", False)),
            "is_ally": bool(raw_npc.get("is_ally", False)),
            "pronoun_possessive": str(raw_npc.get("pronoun_possessive", "its")).strip().lower() or "its",
            "attack_verb": str(raw_npc.get("attack_verb", "hit")).strip().lower() or "hit",
            "main_hand_weapon_template_id": str(raw_npc.get("main_hand_weapon_template_id", "")).strip(),
            "off_hand_weapon_template_id": str(raw_npc.get("off_hand_weapon_template_id", "")).strip(),
            "skill_use_chance": skill_use_chance,
            "skill_ids": [str(skill_id).strip() for skill_id in raw_skill_ids if str(skill_id).strip()],
            "loot_items": normalized_loot_items,
        })

    return normalized_npcs


def get_npc_template_by_id(npc_id: str) -> dict | None:
    normalized = npc_id.strip().lower()
    for npc in load_npc_templates():
        if str(npc.get("npc_id", "")).strip().lower() == normalized:
            return npc
    return None


@lru_cache(maxsize=1)
def load_attributes() -> list[dict]:
    raw_attributes = _read_json_asset(ATTRIBUTES_FILE)
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
    raw_config = _read_json_asset(REGENERATION_FILE)
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
    raw_config = _read_json_asset(HAND_WEIGHT_FILE)
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
def load_spells() -> list[dict]:
    raw_spells = _read_json_asset(SPELLS_FILE)
    if not isinstance(raw_spells, list):
        raise ValueError(f"Spell asset file must contain a list: {SPELLS_FILE}")

    spell_ids: set[str] = set()
    spell_names: set[str] = set()
    normalized_spells: list[dict] = []

    for raw_spell in raw_spells:
        if not isinstance(raw_spell, dict):
            raise ValueError("Spell asset entries must be objects.")

        spell_id = raw_spell.get("spell_id")
        name = raw_spell.get("name")

        if not isinstance(spell_id, str) or not spell_id.strip():
            raise ValueError("Spell asset entries must include a non-empty string spell_id.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Spell asset '{spell_id}' must include a non-empty name.")
        if spell_id in spell_ids:
            raise ValueError(f"Duplicate spell_id in spell assets: {spell_id}")

        normalized_name = name.strip().lower()
        if normalized_name in spell_names:
            raise ValueError(f"Duplicate spell name in spell assets: {name}")

        mana_cost = int(raw_spell.get("mana_cost", 0))
        spell_type = str(raw_spell.get("spell_type", "damage")).strip().lower() or "damage"
        cast_type = str(raw_spell.get("cast_type", "")).strip().lower()
        dice_count = int(raw_spell.get("damage_dice_count", 0))
        dice_sides = int(raw_spell.get("damage_dice_sides", 0))
        damage_modifier = int(raw_spell.get("damage_modifier", 0))
        damage_context = str(raw_spell.get("damage_context", "")).strip()
        support_effect = str(raw_spell.get("support_effect", "")).strip().lower()
        support_amount = int(raw_spell.get("support_amount", 0))
        duration_hours = int(raw_spell.get("duration_hours", 0))
        duration_rounds = int(raw_spell.get("duration_rounds", 0))
        support_mode = str(raw_spell.get("support_mode", "timed")).strip().lower() or "timed"
        support_context = str(raw_spell.get("support_context", "")).strip()

        if not cast_type:
            cast_type = "self" if spell_type == "support" else "target"

        if mana_cost < 0:
            raise ValueError(f"Spell asset '{spell_id}' mana_cost must be zero or greater.")
        if spell_type not in {"damage", "support"}:
            raise ValueError(f"Spell asset '{spell_id}' spell_type must be 'damage' or 'support'.")
        if cast_type not in {"self", "target", "aoe"}:
            raise ValueError(f"Spell asset '{spell_id}' cast_type must be one of: self, target, aoe.")
        if dice_count < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_count must be zero or greater.")
        if dice_sides < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_sides must be zero or greater.")
        if support_amount < 0:
            raise ValueError(f"Spell asset '{spell_id}' support_amount must be zero or greater.")
        if duration_hours < 0:
            raise ValueError(f"Spell asset '{spell_id}' duration_hours must be zero or greater.")
        if duration_rounds < 0:
            raise ValueError(f"Spell asset '{spell_id}' duration_rounds must be zero or greater.")
        if support_mode not in {"timed", "instant", "battle_rounds"}:
            raise ValueError(
                f"Spell asset '{spell_id}' support_mode must be 'timed', 'instant', or 'battle_rounds'."
            )

        if spell_type == "support" and support_effect not in {"heal", "vigor", "mana"}:
            raise ValueError(
                f"Spell asset '{spell_id}' support_effect must be one of: heal, vigor, mana."
            )
        if spell_type == "support" and support_mode == "timed" and duration_hours <= 0:
            raise ValueError(f"Spell asset '{spell_id}' support spells must have duration_hours > 0.")
        if spell_type == "support" and support_mode == "battle_rounds" and duration_rounds <= 0:
            raise ValueError(f"Spell asset '{spell_id}' support spells must have duration_rounds > 0.")
        if spell_type == "support" and not support_context:
            raise ValueError(f"Spell asset '{spell_id}' support spells must define support_context.")
        if spell_type == "damage" and not damage_context:
            raise ValueError(f"Spell asset '{spell_id}' damage spells must define damage_context.")

        spell_ids.add(spell_id)
        spell_names.add(normalized_name)
        normalized_spells.append({
            "spell_id": spell_id.strip(),
            "name": name.strip(),
            "description": str(raw_spell.get("description", "")).strip(),
            "mana_cost": mana_cost,
            "spell_type": spell_type,
            "cast_type": cast_type,
            "damage_dice_count": dice_count,
            "damage_dice_sides": dice_sides,
            "damage_modifier": damage_modifier,
            "damage_context": damage_context,
            "support_effect": support_effect,
            "support_amount": support_amount,
            "duration_hours": duration_hours,
            "duration_rounds": duration_rounds,
            "support_mode": support_mode,
            "support_context": support_context,
        })

    return normalized_spells


def get_spell_by_id(spell_id: str) -> dict | None:
    normalized = spell_id.strip().lower()
    for spell in load_spells():
        if str(spell.get("spell_id", "")).strip().lower() == normalized:
            return spell
    return None


@lru_cache(maxsize=1)
def load_skills() -> list[dict]:
    raw_skills = _read_json_asset(SKILLS_FILE)
    if not isinstance(raw_skills, list):
        raise ValueError(f"Skill asset file must contain a list: {SKILLS_FILE}")

    skill_ids: set[str] = set()
    skill_names: set[str] = set()
    normalized_skills: list[dict] = []

    for raw_skill in raw_skills:
        if not isinstance(raw_skill, dict):
            raise ValueError("Skill asset entries must be objects.")

        skill_id = raw_skill.get("skill_id")
        name = raw_skill.get("name")

        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("Skill asset entries must include a non-empty string skill_id.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Skill asset '{skill_id}' must include a non-empty name.")
        if skill_id in skill_ids:
            raise ValueError(f"Duplicate skill_id in skill assets: {skill_id}")

        normalized_name = name.strip().lower()
        if normalized_name in skill_names:
            raise ValueError(f"Duplicate skill name in skill assets: {name}")

        skill_type = str(raw_skill.get("skill_type", "damage")).strip().lower() or "damage"
        cast_type = str(raw_skill.get("cast_type", "")).strip().lower()
        if not cast_type:
            cast_type = "self" if skill_type == "support" else "target"

        dice_count = int(raw_skill.get("damage_dice_count", 0))
        dice_sides = int(raw_skill.get("damage_dice_sides", 0))
        damage_modifier = int(raw_skill.get("damage_modifier", 0))
        vigor_cost = int(raw_skill.get("vigor_cost", 0))
        usable_out_of_combat = bool(raw_skill.get("usable_out_of_combat", False))
        damage_context = str(raw_skill.get("damage_context", "")).strip()
        support_effect = str(raw_skill.get("support_effect", "")).strip().lower()
        support_amount = int(raw_skill.get("support_amount", 0))
        support_context = str(raw_skill.get("support_context", "")).strip()
        lag_rounds = int(raw_skill.get("lag_rounds", 0))
        cooldown_rounds = int(raw_skill.get("cooldown_rounds", 0))

        if skill_type not in {"damage", "support"}:
            raise ValueError(f"Skill asset '{skill_id}' skill_type must be 'damage' or 'support'.")
        if cast_type not in {"self", "target", "aoe"}:
            raise ValueError(f"Skill asset '{skill_id}' cast_type must be one of: self, target, aoe.")
        if dice_count < 0:
            raise ValueError(f"Skill asset '{skill_id}' damage_dice_count must be zero or greater.")
        if dice_sides < 0:
            raise ValueError(f"Skill asset '{skill_id}' damage_dice_sides must be zero or greater.")
        if vigor_cost < 0:
            raise ValueError(f"Skill asset '{skill_id}' vigor_cost must be zero or greater.")
        if support_amount < 0:
            raise ValueError(f"Skill asset '{skill_id}' support_amount must be zero or greater.")
        if lag_rounds < 0:
            raise ValueError(f"Skill asset '{skill_id}' lag_rounds must be zero or greater.")
        if cooldown_rounds < 0:
            raise ValueError(f"Skill asset '{skill_id}' cooldown_rounds must be zero or greater.")

        if skill_type == "support":
            if support_effect not in {"heal", "vigor", "mana"}:
                raise ValueError(
                    f"Skill asset '{skill_id}' support_effect must be one of: heal, vigor, mana."
                )
            if not support_context:
                raise ValueError(f"Skill asset '{skill_id}' support skills must define support_context.")
        else:
            if not damage_context:
                raise ValueError(f"Skill asset '{skill_id}' damage skills must define damage_context.")

        skill_ids.add(skill_id)
        skill_names.add(normalized_name)
        normalized_skills.append({
            "skill_id": skill_id.strip(),
            "name": name.strip(),
            "description": str(raw_skill.get("description", "")).strip(),
            "skill_type": skill_type,
            "cast_type": cast_type,
            "damage_dice_count": dice_count,
            "damage_dice_sides": dice_sides,
            "damage_modifier": damage_modifier,
            "vigor_cost": vigor_cost,
            "usable_out_of_combat": usable_out_of_combat,
            "damage_context": damage_context,
            "support_effect": support_effect,
            "support_amount": support_amount,
            "support_context": support_context,
            "lag_rounds": lag_rounds,
            "cooldown_rounds": cooldown_rounds,
        })

    return normalized_skills


def get_skill_by_id(skill_id: str) -> dict | None:
    normalized = skill_id.strip().lower()
    for skill in load_skills():
        if str(skill.get("skill_id", "")).strip().lower() == normalized:
            return skill
    return None


@lru_cache(maxsize=1)
def load_player_classes() -> list[dict]:
    raw_classes = _read_json_asset(PLAYER_CLASSES_FILE)
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

        raw_equipment_ids = raw_class.get("starting_equipment_template_ids", [])
        raw_spell_ids = raw_class.get("starting_spell_ids", [])
        raw_skill_ids = raw_class.get("starting_skill_ids", [])
        raw_equipped_ids = raw_class.get("starting_equipped_template_ids", [])
        raw_attribute_ranges = raw_class.get("attribute_ranges", {})
        if not isinstance(raw_equipment_ids, list):
            raise ValueError(
                f"Player class '{class_id}' starting_equipment_template_ids must be a list."
            )
        if not isinstance(raw_spell_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_spell_ids must be a list.")
        if not isinstance(raw_skill_ids, list):
            raise ValueError(f"Player class '{class_id}' starting_skill_ids must be a list.")
        if not isinstance(raw_equipped_ids, list):
            raise ValueError(
                f"Player class '{class_id}' starting_equipped_template_ids must be a list."
            )
        if not isinstance(raw_attribute_ranges, dict):
            raise ValueError(f"Player class '{class_id}' attribute_ranges must be an object.")

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

        equipment_ids: list[str] = []
        seen_equipment_ids: set[str] = set()
        for raw_template_id in raw_equipment_ids:
            template_id = str(raw_template_id).strip()
            if not template_id:
                continue
            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_equipment_ids:
                continue
            if get_equipment_template_by_id(template_id) is None:
                raise ValueError(
                    f"Player class '{class_id}' references unknown equipment template: {template_id}"
                )
            seen_equipment_ids.add(normalized_template_id)
            equipment_ids.append(template_id)

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

        equipped_ids: list[str] = []
        seen_equipped_ids: set[str] = set()
        normalized_starting_equipment = {template_id.lower() for template_id in equipment_ids}
        for raw_template_id in raw_equipped_ids:
            template_id = str(raw_template_id).strip()
            if not template_id:
                continue
            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_equipped_ids:
                continue
            if normalized_template_id not in normalized_starting_equipment:
                raise ValueError(
                    f"Player class '{class_id}' starting_equipped_template_ids contains '{template_id}' "
                    "which is not present in starting_equipment_template_ids."
                )
            seen_equipped_ids.add(normalized_template_id)
            equipped_ids.append(template_id)

        class_ids.add(normalized_class_id)
        class_names.add(normalized_class_name)
        normalized_classes.append({
            "class_id": class_id.strip(),
            "name": name.strip(),
            "description": str(raw_class.get("description", "")).strip(),
            "attribute_ranges": attribute_ranges,
            "starting_equipment_template_ids": equipment_ids,
            "starting_equipped_template_ids": equipped_ids,
            "starting_spell_ids": spell_ids,
            "starting_skill_ids": skill_ids,
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


def get_default_player_class() -> dict:
    for player_class in load_player_classes():
        if bool(player_class.get("is_default", False)):
            return player_class
    raise ValueError("No default player class is configured.")