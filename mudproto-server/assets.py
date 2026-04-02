import json
from functools import lru_cache
from pathlib import Path

from attribute_config import load_attributes
from settings import CONFIGURABLE_ASSET_ROOT


SERVER_ROOT = Path(__file__).resolve().parent
GEAR_FILE = CONFIGURABLE_ASSET_ROOT / "gear.json"
ITEMS_FILE = CONFIGURABLE_ASSET_ROOT / "items.json"
ROOMS_FILE = CONFIGURABLE_ASSET_ROOT / "rooms.json"
SPELLS_FILE = CONFIGURABLE_ASSET_ROOT / "spells.json"
SKILLS_FILE = CONFIGURABLE_ASSET_ROOT / "skills.json"
NPCS_FILE = CONFIGURABLE_ASSET_ROOT / "npcs.json"


def _read_json_asset(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_keywords(raw_keywords: object, *, context: str) -> list[str]:
    if raw_keywords is None:
        raw_keywords = []
    if not isinstance(raw_keywords, list):
        raise ValueError(f"{context} keywords must be a list.")
    return [str(keyword).strip().lower() for keyword in raw_keywords if str(keyword).strip()]


def _normalize_template_identity(raw_template: dict, *, context: str) -> tuple[str, str, list[str]]:
    template_id = str(raw_template.get("template_id", "")).strip()
    name = str(raw_template.get("name", "")).strip()
    if not template_id:
        raise ValueError(f"{context} must include a non-empty string template_id.")
    if not name:
        raise ValueError(f"{context} '{template_id}' must include a non-empty name.")
    keywords = _normalize_keywords(raw_template.get("keywords", []), context=f"{context} '{template_id}'")
    return template_id, name, keywords


@lru_cache(maxsize=1)
def load_gear_templates() -> list[dict]:
    raw_templates = _read_json_asset(GEAR_FILE)
    if not isinstance(raw_templates, list):
        raise ValueError(f"Gear asset file must contain a list: {GEAR_FILE}")

    template_ids: set[str] = set()
    normalized_templates: list[dict] = []

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Gear asset entries must be objects.")

        template_id, name, normalized_keywords = _normalize_template_identity(raw_template, context="Gear asset")
        slot = raw_template.get("slot")

        if template_id in template_ids:
            raise ValueError(f"Duplicate gear template_id: {template_id}")
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"Gear asset '{template_id}' must include a non-empty slot.")
        normalized_slot = slot.strip().lower()
        if normalized_slot not in {"weapon", "armor"}:
            raise ValueError(
                f"Gear asset '{template_id}' slot must be 'weapon' or 'armor'."
            )

        template_ids.add(template_id)

        raw_wear_slots = raw_template.get("wear_slots", [])
        if raw_wear_slots is None:
            raw_wear_slots = []
        if not isinstance(raw_wear_slots, list):
            raise ValueError(f"Gear asset '{template_id}' wear_slots must be a list.")
        wear_slots = [str(slot).strip().lower() for slot in raw_wear_slots if str(slot).strip()]

        armor_class_bonus = int(raw_template.get("armor_class_bonus", 0))
        if normalized_slot == "armor" and not wear_slots:
            raise ValueError(f"Gear asset '{template_id}' armor items must define wear_slots.")
        if normalized_slot == "weapon" and wear_slots:
            raise ValueError(f"Gear asset '{template_id}' weapons cannot define wear_slots.")
        if armor_class_bonus < 0:
            raise ValueError(f"Gear asset '{template_id}' armor_class_bonus must be zero or greater.")

        normalized_templates.append({
            "template_id": template_id,
            "name": name,
            "slot": normalized_slot,
            "description": str(raw_template.get("description", "")),
            "keywords": normalized_keywords,
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


def get_gear_template_by_id(template_id: str) -> dict | None:
    normalized = template_id.strip().lower()
    for template in load_gear_templates():
        if str(template.get("template_id", "")).strip().lower() == normalized:
            return template
    return None


@lru_cache(maxsize=1)
def load_item_templates() -> list[dict]:
    raw_templates = _read_json_asset(ITEMS_FILE)
    if not isinstance(raw_templates, list):
        raise ValueError(f"Item asset file must contain a list: {ITEMS_FILE}")

    template_ids: set[str] = set()
    normalized_templates: list[dict] = []
    allowed_effect_targets = {"hit_points", "mana", "vigor"}

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Item asset entries must be objects.")

        template_id, name, normalized_keywords = _normalize_template_identity(raw_template, context="Item asset")
        effect_type = str(raw_template.get("effect_type", "restore")).strip().lower() or "restore"
        effect_target = str(raw_template.get("effect_target", "")).strip().lower()
        effect_amount = int(raw_template.get("effect_amount", 0))
        use_lag_seconds = max(0.0, float(raw_template.get("use_lag_seconds", 0.0)))

        if template_id in template_ids:
            raise ValueError(f"Duplicate item template_id: {template_id}")
        if effect_type != "restore":
            raise ValueError(f"Item asset '{template_id}' effect_type must be 'restore'.")
        if effect_target not in allowed_effect_targets:
            raise ValueError(
                f"Item asset '{template_id}' effect_target must be one of: hit_points, mana, vigor."
            )
        if effect_amount <= 0:
            raise ValueError(f"Item asset '{template_id}' effect_amount must be greater than zero.")

        template_ids.add(template_id)
        normalized_templates.append({
            "template_id": template_id,
            "name": name,
            "description": str(raw_template.get("description", "")),
            "keywords": normalized_keywords,
            "effect_type": effect_type,
            "effect_target": effect_target,
            "effect_amount": effect_amount,
            "use_lag_seconds": use_lag_seconds,
            "observer_action": str(raw_template.get("observer_action", "")).strip(),
            "observer_context": str(raw_template.get("observer_context", "")).strip(),
        })

    return normalized_templates


def get_item_template_by_id(template_id: str) -> dict | None:
    normalized = template_id.strip().lower()
    for template in load_item_templates():
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

        raw_spell_ids = raw_npc.get("spell_ids", [])
        if raw_spell_ids is None:
            raw_spell_ids = []
        if not isinstance(raw_spell_ids, list):
            raise ValueError(f"NPC '{npc_id}' spell_ids must be a list.")

        skill_use_chance = float(raw_npc.get("skill_use_chance", 0.35))
        if skill_use_chance < 0.0 or skill_use_chance > 1.0:
            raise ValueError(f"NPC '{npc_id}' skill_use_chance must be between 0.0 and 1.0.")

        spell_use_chance = float(raw_npc.get("spell_use_chance", 0.25))
        if spell_use_chance < 0.0 or spell_use_chance > 1.0:
            raise ValueError(f"NPC '{npc_id}' spell_use_chance must be between 0.0 and 1.0.")

        max_vigor = max(0, int(raw_npc.get("max_vigor", 0)))
        vigor = int(raw_npc.get("vigor", max_vigor))
        if vigor < 0:
            raise ValueError(f"NPC '{npc_id}' vigor must be zero or greater.")
        if vigor > max_vigor:
            vigor = max_vigor

        max_mana = max(0, int(raw_npc.get("max_mana", 0)))
        mana = int(raw_npc.get("mana", max_mana))
        if mana < 0:
            raise ValueError(f"NPC '{npc_id}' mana must be zero or greater.")
        if mana > max_mana:
            mana = max_mana

        normalized_spell_ids: list[str] = []
        seen_spell_ids: set[str] = set()
        for raw_spell_id in raw_spell_ids:
            spell_id = str(raw_spell_id).strip()
            if not spell_id:
                continue
            normalized_spell_id = spell_id.lower()
            if normalized_spell_id in seen_spell_ids:
                continue
            if get_spell_by_id(spell_id) is None:
                raise ValueError(f"NPC '{npc_id}' references unknown spell: {spell_id}")
            seen_spell_ids.add(normalized_spell_id)
            normalized_spell_ids.append(spell_id)

        npc_ids.add(npc_id)
        normalized_npcs.append({
            "npc_id": npc_id,
            "name": name,
            "hit_points": hit_points,
            "max_hit_points": max_hit_points,
            "power_leveL": max(0, int(raw_npc.get("power_leveL", 1))),
            "attacks_per_round": int(raw_npc.get("attacks_per_round", 1)),
            "hit_roll_modifier": int(raw_npc.get("hit_roll_modifier", 0)),
            "armor_class": int(raw_npc.get("armor_class", 10)),
            "off_hand_attacks_per_round": int(raw_npc.get("off_hand_attacks_per_round", 0)),
            "off_hand_hit_roll_modifier": int(raw_npc.get("off_hand_hit_roll_modifier", 0)),
            "coin_reward": max(0, int(raw_npc.get("coin_reward", 0))),
            "experience_reward": max(0, int(raw_npc.get("experience_reward", 0))),
            "is_aggro": bool(raw_npc.get("is_aggro", False)),
            "is_ally": bool(raw_npc.get("is_ally", False)),
            "pronoun_possessive": str(raw_npc.get("pronoun_possessive", "its")).strip().lower() or "its",
            "main_hand_weapon_template_id": str(raw_npc.get("main_hand_weapon_template_id", "")).strip(),
            "off_hand_weapon_template_id": str(raw_npc.get("off_hand_weapon_template_id", "")).strip(),
            "vigor": vigor,
            "max_vigor": max_vigor,
            "mana": mana,
            "max_mana": max_mana,
            "skill_use_chance": skill_use_chance,
            "skill_ids": [str(skill_id).strip() for skill_id in raw_skill_ids if str(skill_id).strip()],
            "spell_use_chance": spell_use_chance,
            "spell_ids": normalized_spell_ids,
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
def load_spells() -> list[dict]:
    raw_spells = _read_json_asset(SPELLS_FILE)
    if not isinstance(raw_spells, list):
        raise ValueError(f"Spell asset file must contain a list: {SPELLS_FILE}")

    spell_ids: set[str] = set()
    spell_names: set[str] = set()
    normalized_spells: list[dict] = []
    configured_attribute_ids = {
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    }

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

        school = str(raw_spell.get("school", "")).strip()

        mana_cost = int(raw_spell.get("mana_cost", 0))
        spell_type = str(raw_spell.get("spell_type", "damage")).strip().lower() or "damage"
        cast_type = str(raw_spell.get("cast_type", "")).strip().lower()
        dice_count = int(raw_spell.get("damage_dice_count", 0))
        dice_sides = int(raw_spell.get("damage_dice_sides", 0))
        damage_modifier = int(raw_spell.get("damage_modifier", 0))
        damage_scaling_attribute_id = str(raw_spell.get("damage_scaling_attribute_id", "int")).strip().lower() or "int"
        damage_scaling_multiplier = float(raw_spell.get("damage_scaling_multiplier", 1.0))
        level_scaling_multiplier = float(raw_spell.get("level_scaling_multiplier", 1.0))
        damage_context = str(raw_spell.get("damage_context", "")).strip()
        restore_effect = str(raw_spell.get("restore_effect", "")).strip().lower()
        restore_ratio = float(raw_spell.get("restore_ratio", raw_spell.get("life_steal_ratio", 0.0)))
        if not restore_effect and restore_ratio > 0.0 and "life_steal_ratio" in raw_spell:
            restore_effect = "heal"
        restore_context = str(raw_spell.get("restore_context", raw_spell.get("life_steal_context", ""))).strip()
        observer_restore_context = str(
            raw_spell.get("observer_restore_context", raw_spell.get("observer_life_steal_context", ""))
        ).strip()
        support_effect = str(raw_spell.get("support_effect", "")).strip().lower()
        support_amount = int(raw_spell.get("support_amount", 0))
        support_dice_count = int(raw_spell.get("support_dice_count", 0))
        support_dice_sides = int(raw_spell.get("support_dice_sides", 0))
        support_roll_modifier = int(raw_spell.get("support_roll_modifier", 0))
        support_scaling_attribute_id = str(raw_spell.get("support_scaling_attribute_id", "")).strip().lower()
        support_scaling_multiplier = float(raw_spell.get("support_scaling_multiplier", 1.0))
        duration_hours = int(raw_spell.get("duration_hours", 0))
        duration_rounds = int(raw_spell.get("duration_rounds", 0))
        support_mode = str(raw_spell.get("support_mode", "timed")).strip().lower() or "timed"
        support_context = str(raw_spell.get("support_context", "")).strip()
        observer_action = str(raw_spell.get("observer_action", "")).strip()
        observer_context = str(raw_spell.get("observer_context", "")).strip()

        if not cast_type:
            cast_type = "self" if spell_type == "support" else "target"

        if mana_cost < 0:
            raise ValueError(f"Spell asset '{spell_id}' mana_cost must be zero or greater.")
        if not school:
            raise ValueError(f"Spell asset '{spell_id}' must include a non-empty school.")
        if spell_type not in {"damage", "support"}:
            raise ValueError(f"Spell asset '{spell_id}' spell_type must be 'damage' or 'support'.")
        if cast_type not in {"self", "target", "aoe"}:
            raise ValueError(f"Spell asset '{spell_id}' cast_type must be one of: self, target, aoe.")
        if dice_count < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_count must be zero or greater.")
        if dice_sides < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_sides must be zero or greater.")
        if damage_scaling_multiplier < 0.0:
            raise ValueError(f"Spell asset '{spell_id}' damage_scaling_multiplier must be zero or greater.")
        if level_scaling_multiplier < 0.0:
            raise ValueError(f"Spell asset '{spell_id}' level_scaling_multiplier must be zero or greater.")
        if support_amount < 0:
            raise ValueError(f"Spell asset '{spell_id}' support_amount must be zero or greater.")
        if support_dice_count < 0:
            raise ValueError(f"Spell asset '{spell_id}' support_dice_count must be zero or greater.")
        if support_dice_sides < 0:
            raise ValueError(f"Spell asset '{spell_id}' support_dice_sides must be zero or greater.")
        if support_dice_count > 0 and support_dice_sides <= 0:
            raise ValueError(f"Spell asset '{spell_id}' support_dice_sides must be > 0 when support_dice_count is set.")
        if support_scaling_multiplier < 0.0:
            raise ValueError(f"Spell asset '{spell_id}' support_scaling_multiplier must be zero or greater.")
        if duration_hours < 0:
            raise ValueError(f"Spell asset '{spell_id}' duration_hours must be zero or greater.")
        if duration_rounds < 0:
            raise ValueError(f"Spell asset '{spell_id}' duration_rounds must be zero or greater.")
        if restore_ratio < 0.0 or restore_ratio > 1.0:
            raise ValueError(f"Spell asset '{spell_id}' restore_ratio must be between 0.0 and 1.0.")
        if support_mode not in {"timed", "instant", "battle_rounds"}:
            raise ValueError(
                f"Spell asset '{spell_id}' support_mode must be 'timed', 'instant', or 'battle_rounds'."
            )
        if restore_effect and restore_effect not in {"heal", "vigor", "mana"}:
            raise ValueError(
                f"Spell asset '{spell_id}' restore_effect must be one of: heal, vigor, mana."
            )
        if restore_ratio > 0.0 and not restore_effect:
            raise ValueError(f"Spell asset '{spell_id}' restore_ratio requires restore_effect.")
        if spell_type != "damage" and restore_ratio > 0.0:
            raise ValueError(f"Spell asset '{spell_id}' restore_ratio is only supported on damage spells.")

        if spell_type == "support" and support_effect not in {"heal", "vigor", "mana"}:
            raise ValueError(
                f"Spell asset '{spell_id}' support_effect must be one of: heal, vigor, mana."
            )
        if spell_type == "support" and support_amount <= 0 and support_dice_count <= 0:
            raise ValueError(
                f"Spell asset '{spell_id}' support spells must define support_amount and/or support_dice_count."
            )
        if spell_type == "support" and support_mode == "timed" and duration_hours <= 0:
            raise ValueError(f"Spell asset '{spell_id}' support spells must have duration_hours > 0.")
        if spell_type == "support" and support_mode == "battle_rounds" and duration_rounds <= 0:
            raise ValueError(f"Spell asset '{spell_id}' support spells must have duration_rounds > 0.")
        if spell_type == "support" and not support_context:
            raise ValueError(f"Spell asset '{spell_id}' support spells must define support_context.")
        if spell_type == "damage" and not damage_context:
            raise ValueError(f"Spell asset '{spell_id}' damage spells must define damage_context.")
        if spell_type == "damage" and damage_scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Spell asset '{spell_id}' damage_scaling_attribute_id '{damage_scaling_attribute_id}' is unknown."
            )

        spell_ids.add(spell_id)
        spell_names.add(normalized_name)
        normalized_spells.append({
            "spell_id": spell_id.strip(),
            "name": name.strip(),
            "school": school,
            "description": str(raw_spell.get("description", "")).strip(),
            "mana_cost": mana_cost,
            "spell_type": spell_type,
            "cast_type": cast_type,
            "damage_dice_count": dice_count,
            "damage_dice_sides": dice_sides,
            "damage_modifier": damage_modifier,
            "damage_scaling_attribute_id": damage_scaling_attribute_id,
            "damage_scaling_multiplier": damage_scaling_multiplier,
            "level_scaling_multiplier": level_scaling_multiplier,
            "damage_context": damage_context,
            "restore_effect": restore_effect,
            "restore_ratio": restore_ratio,
            "restore_context": restore_context,
            "observer_restore_context": observer_restore_context,
            "life_steal_ratio": restore_ratio if restore_effect == "heal" else 0.0,
            "life_steal_context": restore_context if restore_effect == "heal" else "",
            "observer_life_steal_context": observer_restore_context if restore_effect == "heal" else "",
            "support_effect": support_effect,
            "support_amount": support_amount,
            "support_dice_count": support_dice_count,
            "support_dice_sides": support_dice_sides,
            "support_roll_modifier": support_roll_modifier,
            "support_scaling_attribute_id": support_scaling_attribute_id,
            "support_scaling_multiplier": support_scaling_multiplier,
            "duration_hours": duration_hours,
            "duration_rounds": duration_rounds,
            "support_mode": support_mode,
            "support_context": support_context,
            "observer_action": observer_action,
            "observer_context": observer_context,
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
    configured_attribute_ids = {
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    }

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
        scaling_attribute_id = str(raw_skill.get("scaling_attribute_id", "")).strip().lower()
        scaling_multiplier = float(raw_skill.get("scaling_multiplier", 0.0))
        damage_context = str(raw_skill.get("damage_context", "")).strip()
        restore_effect = str(raw_skill.get("restore_effect", "")).strip().lower()
        restore_ratio = float(raw_skill.get("restore_ratio", 0.0))
        restore_context = str(raw_skill.get("restore_context", "")).strip()
        observer_restore_context = str(raw_skill.get("observer_restore_context", "")).strip()
        support_effect = str(raw_skill.get("support_effect", "")).strip().lower()
        support_amount = int(raw_skill.get("support_amount", 0))
        support_context = str(raw_skill.get("support_context", "")).strip()
        observer_action = str(raw_skill.get("observer_action", "")).strip()
        observer_context = str(raw_skill.get("observer_context", "")).strip()
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
        if scaling_multiplier < 0:
            raise ValueError(f"Skill asset '{skill_id}' scaling_multiplier must be zero or greater.")
        if restore_ratio < 0.0 or restore_ratio > 1.0:
            raise ValueError(f"Skill asset '{skill_id}' restore_ratio must be between 0.0 and 1.0.")
        if support_amount < 0:
            raise ValueError(f"Skill asset '{skill_id}' support_amount must be zero or greater.")
        if lag_rounds < 0:
            raise ValueError(f"Skill asset '{skill_id}' lag_rounds must be zero or greater.")
        if cooldown_rounds < 0:
            raise ValueError(f"Skill asset '{skill_id}' cooldown_rounds must be zero or greater.")
        if scaling_attribute_id and scaling_attribute_id not in configured_attribute_ids:
            raise ValueError(
                f"Skill asset '{skill_id}' references unknown scaling_attribute_id '{scaling_attribute_id}'."
            )
        if restore_effect and restore_effect not in {"heal", "vigor", "mana"}:
            raise ValueError(
                f"Skill asset '{skill_id}' restore_effect must be one of: heal, vigor, mana."
            )
        if restore_ratio > 0.0 and not restore_effect:
            raise ValueError(f"Skill asset '{skill_id}' restore_ratio requires restore_effect.")
        if skill_type != "damage" and restore_ratio > 0.0:
            raise ValueError(f"Skill asset '{skill_id}' restore_ratio is only supported on damage skills.")

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
            "scaling_attribute_id": scaling_attribute_id,
            "scaling_multiplier": scaling_multiplier,
            "damage_context": damage_context,
            "restore_effect": restore_effect,
            "restore_ratio": restore_ratio,
            "restore_context": restore_context,
            "observer_restore_context": observer_restore_context,
            "support_effect": support_effect,
            "support_amount": support_amount,
            "support_context": support_context,
            "observer_action": observer_action,
            "observer_context": observer_context,
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
