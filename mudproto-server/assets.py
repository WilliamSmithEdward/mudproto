import json
from functools import lru_cache
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
DEFAULT_ASSET_ROOT = SERVER_ROOT / "assets" / "default-assets"
CONFIGURABLE_ASSET_ROOT = SERVER_ROOT / "assets" / "configurable-assets"
TRAINING_EQUIPMENT_FILE = DEFAULT_ASSET_ROOT / "training-equipment.json"
ROOMS_FILE = CONFIGURABLE_ASSET_ROOT / "rooms.json"
SPELLS_FILE = CONFIGURABLE_ASSET_ROOT / "spells.json"


def _read_json_asset(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_equipment_templates() -> list[dict]:
    raw_templates = _read_json_asset(TRAINING_EQUIPMENT_FILE)
    if not isinstance(raw_templates, list):
        raise ValueError(f"Equipment asset file must contain a list: {TRAINING_EQUIPMENT_FILE}")

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

        template_ids.add(template_id)
        raw_keywords = raw_template.get("keywords", [])
        if raw_keywords is None:
            raw_keywords = []
        if not isinstance(raw_keywords, list):
            raise ValueError(f"Equipment asset '{template_id}' keywords must be a list.")

        normalized_templates.append({
            "template_id": template_id,
            "name": name,
            "slot": slot,
            "description": str(raw_template.get("description", "")),
            "keywords": [str(keyword).strip().lower() for keyword in raw_keywords if str(keyword).strip()],
            "weapon_type": str(raw_template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
            "preferred_hand": str(raw_template.get("preferred_hand", "main_hand")).strip().lower() or "main_hand",
            "damage_dice_count": int(raw_template.get("damage_dice_count", 0)),
            "damage_dice_sides": int(raw_template.get("damage_dice_sides", 0)),
            "damage_roll_modifier": int(raw_template.get("damage_roll_modifier", 0)),
            "hit_roll_modifier": int(raw_template.get("hit_roll_modifier", 0)),
            "attack_damage_bonus": int(raw_template.get("attack_damage_bonus", 0)),
            "attacks_per_round_bonus": int(raw_template.get("attacks_per_round_bonus", 0)),
            "grant_to_new_players": bool(raw_template.get("grant_to_new_players", False)),
            "equip_on_grant": bool(raw_template.get("equip_on_grant", False)),
        })

    return normalized_templates


def load_starting_equipment_templates() -> list[dict]:
    return [
        template
        for template in load_equipment_templates()
        if template["grant_to_new_players"]
    ]


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

        normalized_exits: dict[str, str] = {}
        for direction, destination_room_id in exits.items():
            if not isinstance(direction, str) or not direction.strip():
                raise ValueError(f"Room asset '{room_id}' has an exit with an invalid direction.")
            if not isinstance(destination_room_id, str) or not destination_room_id.strip():
                raise ValueError(f"Room asset '{room_id}' exit '{direction}' has an invalid destination room id.")
            normalized_exits[direction.strip().lower()] = destination_room_id.strip()

        room_ids.add(room_id)
        normalized_rooms.append({
            "room_id": room_id,
            "title": title,
            "description": description,
            "exits": normalized_exits,
        })

    return normalized_rooms


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
        dice_count = int(raw_spell.get("damage_dice_count", 0))
        dice_sides = int(raw_spell.get("damage_dice_sides", 0))
        damage_modifier = int(raw_spell.get("damage_modifier", 0))

        if mana_cost < 0:
            raise ValueError(f"Spell asset '{spell_id}' mana_cost must be zero or greater.")
        if dice_count < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_count must be zero or greater.")
        if dice_sides < 0:
            raise ValueError(f"Spell asset '{spell_id}' damage_dice_sides must be zero or greater.")

        spell_ids.add(spell_id)
        spell_names.add(normalized_name)
        normalized_spells.append({
            "spell_id": spell_id.strip(),
            "name": name.strip(),
            "description": str(raw_spell.get("description", "")).strip(),
            "mana_cost": mana_cost,
            "damage_dice_count": dice_count,
            "damage_dice_sides": dice_sides,
            "damage_modifier": damage_modifier,
        })

    return normalized_spells