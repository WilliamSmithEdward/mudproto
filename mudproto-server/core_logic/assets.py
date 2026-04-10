import json
from functools import lru_cache
from pathlib import Path

from attribute_config import load_attributes
from settings import CONFIGURABLE_ASSET_ROOT


SERVER_ROOT = Path(__file__).resolve().parent
GEAR_FILE = CONFIGURABLE_ASSET_ROOT / "gear.json"
ITEMS_FILE = CONFIGURABLE_ASSET_ROOT / "items.json"
ROOMS_FILE = CONFIGURABLE_ASSET_ROOT / "rooms.json"
ZONES_FILE = CONFIGURABLE_ASSET_ROOT / "zones.json"
SPELLS_FILE = CONFIGURABLE_ASSET_ROOT / "spells.json"
SKILLS_FILE = CONFIGURABLE_ASSET_ROOT / "skills.json"
NPCS_FILE = CONFIGURABLE_ASSET_ROOT / "npcs.json"
ASSET_PAYLOADS_DIR = CONFIGURABLE_ASSET_ROOT / "asset-payloads"
SUPPORTED_ASSET_PAYLOAD_SECTIONS = ("gear", "items", "zones", "rooms", "spells", "skills", "npcs")


def _read_json_asset(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _load_asset_payload_documents() -> tuple[tuple[Path, dict], ...]:
    if not ASSET_PAYLOADS_DIR.exists():
        return tuple()

    payload_documents: list[tuple[Path, dict]] = []
    for path in sorted(ASSET_PAYLOADS_DIR.glob("*.json")):
        if not path.is_file():
            continue

        raw_payload = _read_json_asset(path)
        if not isinstance(raw_payload, dict):
            raise ValueError(f"Asset payload file must contain an object: {path}")

        for section_name in SUPPORTED_ASSET_PAYLOAD_SECTIONS:
            raw_section = raw_payload.get(section_name, [])
            if raw_section is None:
                raw_section = []
            if not isinstance(raw_section, list):
                raise ValueError(f"Asset payload '{path.name}' field '{section_name}' must be a list.")

        payload_documents.append((path, raw_payload))

    return tuple(payload_documents)


def _load_asset_payload_section(section_name: str) -> list[dict]:
    if section_name not in SUPPORTED_ASSET_PAYLOAD_SECTIONS:
        raise ValueError(f"Unsupported asset payload section '{section_name}'.")

    merged_entries: list[dict] = []
    for path, raw_payload in _load_asset_payload_documents():
        raw_entries = raw_payload.get(section_name, [])
        if raw_entries is None:
            continue

        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ValueError(f"Asset payload '{path.name}' section '{section_name}' entries must be objects.")
            merged_entry = dict(raw_entry)
            merged_entry["__source_payload_file"] = path.name
            merged_entries.append(merged_entry)

    return merged_entries


def _is_asset_payload_override(raw_entry: dict) -> bool:
    return bool(str(raw_entry.get("__source_payload_file", "")).strip())


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
    raw_templates = list(raw_templates) + _load_asset_payload_section("gear")

    normalized_templates_by_id: dict[str, dict] = {}
    ordered_template_ids: list[str] = []

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Gear asset entries must be objects.")

        template_id, name, normalized_keywords = _normalize_template_identity(raw_template, context="Gear asset")
        slot = raw_template.get("slot")
        normalized_template_id = template_id.strip().lower()
        is_payload_override = _is_asset_payload_override(raw_template)

        if normalized_template_id in normalized_templates_by_id and not is_payload_override:
            raise ValueError(f"Duplicate gear template_id: {template_id}")
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"Gear asset '{template_id}' must include a non-empty slot.")
        normalized_slot = slot.strip().lower()
        if normalized_slot not in {"weapon", "armor"}:
            raise ValueError(
                f"Gear asset '{template_id}' slot must be 'weapon' or 'armor'."
            )

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

        if normalized_template_id not in normalized_templates_by_id:
            ordered_template_ids.append(normalized_template_id)

        normalized_templates_by_id[normalized_template_id] = {
            "template_id": template_id,
            "name": name,
            "slot": normalized_slot,
            "description": str(raw_template.get("description", "")),
            "keywords": normalized_keywords,
            "weapon_type": str(raw_template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
            "can_hold": bool(raw_template.get("can_hold", False)) if normalized_slot == "weapon" else False,
            "can_two_hand": bool(raw_template.get("can_two_hand", False)) if normalized_slot == "weapon" else False,
            "requires_two_hands": bool(raw_template.get("requires_two_hands", False)) if normalized_slot == "weapon" else False,
            "weight": max(0, int(raw_template.get("weight", 0))),
            "coin_value": max(0, int(raw_template.get("coin_value", 0))),
            "damage_dice_count": int(raw_template.get("damage_dice_count", 0)),
            "damage_dice_sides": int(raw_template.get("damage_dice_sides", 0)),
            "damage_roll_modifier": int(raw_template.get("damage_roll_modifier", 0)),
            "hit_roll_modifier": int(raw_template.get("hit_roll_modifier", 0)),
            "attack_damage_bonus": int(raw_template.get("attack_damage_bonus", 0)),
            "attacks_per_round_bonus": int(raw_template.get("attacks_per_round_bonus", 0)),
            "armor_class_bonus": armor_class_bonus,
            "wear_slots": wear_slots,
        }

    return [normalized_templates_by_id[template_id] for template_id in ordered_template_ids]


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
    raw_templates = list(raw_templates) + _load_asset_payload_section("items")

    normalized_templates_by_id: dict[str, dict] = {}
    ordered_template_ids: list[str] = []
    allowed_effect_targets = {"hit_points", "mana", "vigor"}
    allowed_item_types = {"consumable", "key", "misc"}

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Item asset entries must be objects.")

        template_id, name, normalized_keywords = _normalize_template_identity(raw_template, context="Item asset")
        raw_item_type = str(raw_template.get("item_type", "")).strip().lower()
        effect_type = str(raw_template.get("effect_type", "")).strip().lower()
        effect_target = str(raw_template.get("effect_target", "")).strip().lower()
        effect_amount = int(raw_template.get("effect_amount", 0) or 0)
        use_lag_seconds = max(0.0, float(raw_template.get("use_lag_seconds", 0.0)))
        normalized_template_id = template_id.strip().lower()
        is_payload_override = _is_asset_payload_override(raw_template)

        if not raw_item_type:
            raw_item_type = "consumable" if effect_type else "misc"
        if raw_item_type not in allowed_item_types:
            raise ValueError(
                f"Item asset '{template_id}' item_type must be one of: consumable, key, misc."
            )

        raw_persistent = raw_template.get("persistent")
        if raw_persistent is None and "persistant" in raw_template:
            raw_persistent = raw_template.get("persistant")
        persistent = True if raw_persistent is None else bool(raw_persistent)
        lock_ids = [
            str(lock_id).strip().lower()
            for lock_id in raw_template.get("lock_ids", [])
            if str(lock_id).strip()
        ]

        if normalized_template_id in normalized_templates_by_id and not is_payload_override:
            raise ValueError(f"Duplicate item template_id: {template_id}")
        if raw_item_type == "consumable":
            if effect_type != "restore":
                raise ValueError(f"Item asset '{template_id}' effect_type must be 'restore'.")
            if effect_target not in allowed_effect_targets:
                raise ValueError(
                    f"Item asset '{template_id}' effect_target must be one of: hit_points, mana, vigor."
                )
            if effect_amount <= 0:
                raise ValueError(f"Item asset '{template_id}' effect_amount must be greater than zero.")
        elif effect_type and effect_type != "restore":
            raise ValueError(f"Item asset '{template_id}' effect_type must be 'restore' when provided.")

        if raw_item_type == "key" and not lock_ids:
            raise ValueError(f"Item asset '{template_id}' key items must define at least one lock_id.")

        if normalized_template_id not in normalized_templates_by_id:
            ordered_template_ids.append(normalized_template_id)
        normalized_templates_by_id[normalized_template_id] = {
            "template_id": template_id,
            "name": name,
            "description": str(raw_template.get("description", "")),
            "keywords": normalized_keywords,
            "item_type": raw_item_type,
            "persistent": persistent,
            "lock_ids": lock_ids,
            "effect_type": effect_type,
            "effect_target": effect_target,
            "effect_amount": effect_amount,
            "coin_value": max(0, int(raw_template.get("coin_value", 0))),
            "use_lag_seconds": use_lag_seconds,
            "observer_action": str(raw_template.get("observer_action", "")).strip(),
            "observer_context": str(raw_template.get("observer_context", "")).strip(),
        }

    return [normalized_templates_by_id[template_id] for template_id in ordered_template_ids]


def get_item_template_by_id(template_id: str) -> dict | None:
    normalized = template_id.strip().lower()
    for template in load_item_templates():
        if str(template.get("template_id", "")).strip().lower() == normalized:
            return template
    return None


@lru_cache(maxsize=1)
def load_zones() -> list[dict]:
    raw_zones = _read_json_asset(ZONES_FILE)
    if not isinstance(raw_zones, list):
        raise ValueError(f"Zone asset file must contain a list: {ZONES_FILE}")
    raw_zones = list(raw_zones) + _load_asset_payload_section("zones")

    normalized_zones_by_id: dict[str, dict] = {}
    ordered_zone_ids: list[str] = []

    for raw_zone in raw_zones:
        if not isinstance(raw_zone, dict):
            raise ValueError("Zone asset entries must be objects.")

        zone_id = str(raw_zone.get("zone_id", "")).strip()
        name = str(raw_zone.get("name", "")).strip()
        normalized_zone_id = zone_id.lower()
        is_payload_override = _is_asset_payload_override(raw_zone)
        if not zone_id:
            raise ValueError("Zone asset entries must include a non-empty string zone_id.")
        if not name:
            raise ValueError(f"Zone asset '{zone_id}' must include a non-empty name.")
        if normalized_zone_id in normalized_zones_by_id and not is_payload_override:
            raise ValueError(f"Duplicate zone_id in zone assets: {zone_id}")

        raw_repopulate_game_hours = raw_zone.get("repopulate_game_hours")
        if raw_repopulate_game_hours is None:
            raw_repopulate_game_hours = 1 if bool(raw_zone.get("repopulate_each_game_hour", False)) else 0

        repopulate_game_hours = int(raw_repopulate_game_hours)
        if repopulate_game_hours < 0:
            raise ValueError(f"Zone asset '{zone_id}' repopulate_game_hours must be zero or greater.")

        if normalized_zone_id not in normalized_zones_by_id:
            ordered_zone_ids.append(normalized_zone_id)
        normalized_zones_by_id[normalized_zone_id] = {
            "zone_id": zone_id,
            "name": name,
            "repopulate_game_hours": repopulate_game_hours,
        }

    return [normalized_zones_by_id[zone_id] for zone_id in ordered_zone_ids]


def get_zone_by_id(zone_id: str) -> dict | None:
    normalized = zone_id.strip().lower()
    for zone in load_zones():
        if str(zone.get("zone_id", "")).strip().lower() == normalized:
            return zone
    return None


@lru_cache(maxsize=1)
def load_rooms() -> list[dict]:
    raw_rooms = _read_json_asset(ROOMS_FILE)
    if not isinstance(raw_rooms, list):
        raise ValueError(f"Room asset file must contain a list: {ROOMS_FILE}")
    raw_rooms = list(raw_rooms) + _load_asset_payload_section("rooms")

    normalized_rooms_by_id: dict[str, dict] = {}
    ordered_room_ids: list[str] = []

    for raw_room in raw_rooms:
        if not isinstance(raw_room, dict):
            raise ValueError("Room asset entries must be objects.")

        room_id = raw_room.get("room_id")
        title = raw_room.get("title")
        description = raw_room.get("description")
        zone_id = str(raw_room.get("zone_id", "")).strip()
        exits = raw_room.get("exits", {})
        room_npcs = raw_room.get("npcs", [])
        room_items = raw_room.get("items", [])
        room_keyword_actions = raw_room.get("keyword_actions", [])
        room_objects = raw_room.get("room_objects", [])
        room_exit_details = raw_room.get("exit_details", [])
        normalized_room_id = str(room_id).strip().lower() if isinstance(room_id, str) else ""
        is_payload_override = _is_asset_payload_override(raw_room)

        if not isinstance(room_id, str) or not room_id.strip():
            raise ValueError("Room asset entries must include a non-empty string room_id.")
        if normalized_room_id in normalized_rooms_by_id and not is_payload_override:
            raise ValueError(f"Duplicate room_id in room assets: {room_id}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Room asset '{room_id}' must include a non-empty title.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Room asset '{room_id}' must include a non-empty description.")
        if not zone_id:
            raise ValueError(f"Room asset '{room_id}' must include a non-empty zone_id.")
        if not isinstance(exits, dict):
            raise ValueError(f"Room asset '{room_id}' exits must be an object.")
        if room_npcs is None:
            room_npcs = []
        if not isinstance(room_npcs, list):
            raise ValueError(f"Room asset '{room_id}' npcs must be a list.")
        if room_items is None:
            room_items = []
        if not isinstance(room_items, list):
            raise ValueError(f"Room asset '{room_id}' items must be a list.")
        if room_keyword_actions is None:
            room_keyword_actions = []
        if not isinstance(room_keyword_actions, list):
            raise ValueError(f"Room asset '{room_id}' keyword_actions must be a list.")
        if room_objects is None:
            room_objects = []
        if not isinstance(room_objects, list):
            raise ValueError(f"Room asset '{room_id}' room_objects must be a list.")
        if room_exit_details is None:
            room_exit_details = []
        if not isinstance(room_exit_details, list):
            raise ValueError(f"Room asset '{room_id}' exit_details must be a list.")

        normalized_room_items: list[dict] = []
        for raw_room_item in room_items:
            if not isinstance(raw_room_item, dict):
                raise ValueError(f"Room asset '{room_id}' items entries must be objects.")

            template_id = str(raw_room_item.get("template_id", "")).strip()
            if not template_id:
                raise ValueError(f"Room asset '{room_id}' items entries must include template_id.")

            quantity = max(1, int(raw_room_item.get("count", 1)))
            normalized_room_items.append({
                "template_id": template_id,
                "count": quantity,
            })

        normalized_room_objects: list[dict] = []
        for raw_room_object in room_objects:
            if not isinstance(raw_room_object, dict):
                raise ValueError(f"Room asset '{room_id}' room_objects entries must be objects.")

            object_id = str(raw_room_object.get("object_id", "")).strip()
            object_name = str(raw_room_object.get("name", "")).strip()
            object_description = str(raw_room_object.get("description", "")).strip()
            if not object_id:
                raise ValueError(f"Room asset '{room_id}' room_objects entries must include object_id.")
            if not object_name:
                raise ValueError(f"Room asset '{room_id}' room object '{object_id}' must include name.")
            if not object_description:
                raise ValueError(f"Room asset '{room_id}' room object '{object_id}' must include description.")

            raw_object_keywords = raw_room_object.get("keywords", [])
            if raw_object_keywords is None:
                raw_object_keywords = []
            if not isinstance(raw_object_keywords, list):
                raise ValueError(f"Room asset '{room_id}' room object '{object_id}' keywords must be a list.")

            normalized_room_objects.append({
                "object_id": object_id,
                "name": object_name,
                "description": object_description,
                "keywords": [str(keyword).strip().lower() for keyword in raw_object_keywords if str(keyword).strip()],
            })

        normalized_exit_details: list[dict] = []
        for raw_exit_detail in room_exit_details:
            if not isinstance(raw_exit_detail, dict):
                raise ValueError(f"Room asset '{room_id}' exit_details entries must be objects.")

            direction = str(raw_exit_detail.get("direction", "")).strip().lower()
            if not direction:
                raise ValueError(f"Room asset '{room_id}' exit details must include direction.")

            exit_type = str(raw_exit_detail.get("exit_type", "exit")).strip().lower() or "exit"
            name = str(raw_exit_detail.get("name", "")).strip()
            raw_exit_keywords = raw_exit_detail.get("keywords", [])
            if raw_exit_keywords is None:
                raw_exit_keywords = []
            if not isinstance(raw_exit_keywords, list):
                raise ValueError(f"Room asset '{room_id}' exit detail '{direction}' keywords must be a list.")

            normalized_exit_details.append({
                "direction": direction,
                "exit_type": exit_type,
                "name": name,
                "description": str(raw_exit_detail.get("description", "")).strip(),
                "keywords": [str(keyword).strip().lower() for keyword in raw_exit_keywords if str(keyword).strip()],
                "lock_id": str(raw_exit_detail.get("lock_id", "")).strip().lower(),
                "can_close": bool(raw_exit_detail.get("can_close", True)),
                "can_lock": bool(raw_exit_detail.get("can_lock", bool(str(raw_exit_detail.get("lock_id", "")).strip()))),
                "is_closed": bool(raw_exit_detail.get("is_closed", False)),
                "is_locked": bool(raw_exit_detail.get("is_locked", False)),
                "open_message": str(raw_exit_detail.get("open_message", "")).strip(),
                "close_message": str(raw_exit_detail.get("close_message", "")).strip(),
                "lock_message": str(raw_exit_detail.get("lock_message", "")).strip(),
                "unlock_message": str(raw_exit_detail.get("unlock_message", "")).strip(),
                "closed_message": str(raw_exit_detail.get("closed_message", "")).strip(),
                "locked_message": str(raw_exit_detail.get("locked_message", "")).strip(),
                "needs_key_message": str(raw_exit_detail.get("needs_key_message", "")).strip(),
                "must_close_to_lock_message": str(raw_exit_detail.get("must_close_to_lock_message", "")).strip(),
                "already_open_message": str(raw_exit_detail.get("already_open_message", "")).strip(),
                "already_closed_message": str(raw_exit_detail.get("already_closed_message", "")).strip(),
                "already_locked_message": str(raw_exit_detail.get("already_locked_message", "")).strip(),
                "already_unlocked_message": str(raw_exit_detail.get("already_unlocked_message", "")).strip(),
            })

        normalized_keyword_actions: list[dict] = []
        for raw_keyword_action in room_keyword_actions:
            if not isinstance(raw_keyword_action, dict):
                raise ValueError(f"Room asset '{room_id}' keyword_actions entries must be objects.")

            raw_keywords = raw_keyword_action.get("keywords", [])
            if raw_keywords is None:
                raw_keywords = []
            if not isinstance(raw_keywords, list):
                raise ValueError(f"Room asset '{room_id}' keyword_actions keywords must be a list.")

            normalized_keywords = [
                " ".join(str(keyword).strip().lower().split())
                for keyword in raw_keywords
                if str(keyword).strip()
            ]
            if not normalized_keywords:
                raise ValueError(f"Room asset '{room_id}' keyword_actions entries must define at least one keyword.")

            raw_actions = raw_keyword_action.get("actions", [])
            if raw_actions is None:
                raw_actions = []
            if not isinstance(raw_actions, list) or not raw_actions:
                raise ValueError(f"Room asset '{room_id}' keyword_actions entries must define a non-empty actions list.")

            refresh_view = str(raw_keyword_action.get("refresh_view", "none")).strip().lower() or "none"
            if refresh_view not in {"none", "exits", "room"}:
                raise ValueError(f"Room asset '{room_id}' keyword_actions refresh_view must be 'none', 'exits', or 'room'.")

            normalized_actions: list[dict] = []
            for raw_action in raw_actions:
                if not isinstance(raw_action, dict):
                    raise ValueError(f"Room asset '{room_id}' keyword action definitions must be objects.")

                action_type = str(raw_action.get("type", "")).strip().lower()
                if action_type not in {"set_exit", "reveal_exit", "show_exit", "hide_exit", "remove_exit", "unset_exit"}:
                    raise ValueError(f"Room asset '{room_id}' keyword action has unsupported type '{action_type}'.")

                direction = str(raw_action.get("direction", "")).strip().lower()
                if not direction:
                    raise ValueError(f"Room asset '{room_id}' keyword action '{action_type}' must include a direction.")

                normalized_action = {
                    "type": action_type,
                    "direction": direction,
                }
                if action_type in {"set_exit", "reveal_exit", "show_exit"}:
                    destination_room_id = str(raw_action.get("destination_room_id", "")).strip()
                    if not destination_room_id:
                        raise ValueError(
                            f"Room asset '{room_id}' keyword action '{action_type}' must include destination_room_id."
                        )
                    normalized_action["destination_room_id"] = destination_room_id

                normalized_actions.append(normalized_action)

            normalized_keyword_actions.append({
                "keywords": normalized_keywords,
                "message": str(raw_keyword_action.get("message", "")).strip(),
                "already_message": str(raw_keyword_action.get("already_message", "")).strip(),
                "refresh_view": refresh_view,
                "actions": normalized_actions,
            })

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

        merged_exits = dict(normalized_exits)
        merged_room_items = list(normalized_room_items)
        merged_keyword_actions = list(normalized_keyword_actions)
        merged_room_objects = list(normalized_room_objects)
        merged_exit_details = list(normalized_exit_details)
        if normalized_room_id in normalized_rooms_by_id and is_payload_override:
            existing_room = normalized_rooms_by_id[normalized_room_id]
            existing_exits = existing_room.get("exits", {})
            if isinstance(existing_exits, dict):
                merged_exits = dict(existing_exits)
                merged_exits.update(normalized_exits)

            existing_room_items = existing_room.get("items", [])
            if isinstance(existing_room_items, list):
                merged_room_items = list(existing_room_items) + normalized_room_items

            existing_keyword_actions = existing_room.get("keyword_actions", [])
            if isinstance(existing_keyword_actions, list):
                merged_keyword_actions = list(existing_keyword_actions) + normalized_keyword_actions

            existing_room_objects = existing_room.get("room_objects", [])
            if isinstance(existing_room_objects, list):
                merged_room_objects = list(existing_room_objects) + normalized_room_objects

            existing_exit_details = existing_room.get("exit_details", [])
            if isinstance(existing_exit_details, list):
                merged_exit_details = list(existing_exit_details)
                for new_exit_detail in normalized_exit_details:
                    new_direction = str(new_exit_detail.get("direction", "")).strip().lower()
                    for index, existing_exit_detail in enumerate(merged_exit_details):
                        existing_direction = str(existing_exit_detail.get("direction", "")).strip().lower()
                        if existing_direction == new_direction:
                            merged_exit_details[index] = dict(existing_exit_detail) | dict(new_exit_detail)
                            break
                    else:
                        merged_exit_details.append(new_exit_detail)

        if normalized_room_id not in normalized_rooms_by_id:
            ordered_room_ids.append(normalized_room_id)
        normalized_rooms_by_id[normalized_room_id] = {
            "room_id": room_id,
            "title": title,
            "description": description,
            "zone_id": zone_id,
            "exits": merged_exits,
            "npcs": normalized_npcs,
            "items": merged_room_items,
            "keyword_actions": merged_keyword_actions,
            "room_objects": merged_room_objects,
            "exit_details": merged_exit_details,
        }

    return [normalized_rooms_by_id[room_id] for room_id in ordered_room_ids]


@lru_cache(maxsize=1)
def load_npc_templates() -> list[dict]:
    raw_config = _read_json_asset(NPCS_FILE)
    if not isinstance(raw_config, dict):
        raise ValueError(f"NPC asset file must contain an object: {NPCS_FILE}")

    raw_npcs = list(raw_config.get("npcs", [])) + _load_asset_payload_section("npcs")
    if raw_npcs is None:
        raw_npcs = []
    if not isinstance(raw_npcs, list):
        raise ValueError("NPC asset field 'npcs' must be a list.")

    normalized_npcs_by_id: dict[str, dict] = {}
    ordered_npc_ids: list[str] = []

    for raw_npc in raw_npcs:
        if not isinstance(raw_npc, dict):
            raise ValueError("NPC entries must be objects.")

        npc_id = str(raw_npc.get("npc_id", "")).strip()
        normalized_npc_id = npc_id.lower()
        is_payload_override = _is_asset_payload_override(raw_npc)
        if not npc_id:
            raise ValueError("NPC entries must include npc_id.")
        if normalized_npc_id in normalized_npcs_by_id and not is_payload_override:
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
                "template_id": str(raw_loot_item.get("template_id", "")).strip(),
                "name": loot_name,
                "description": str(raw_loot_item.get("description", "")),
                "keywords": [str(keyword).strip().lower() for keyword in raw_loot_keywords if str(keyword).strip()],
            })

        raw_inventory_items = raw_npc.get("inventory_items", [])
        if raw_inventory_items is None:
            raw_inventory_items = []
        if not isinstance(raw_inventory_items, list):
            raise ValueError(f"NPC '{npc_id}' inventory_items must be a list.")

        normalized_inventory_items: list[dict] = []
        for raw_inventory_item in raw_inventory_items:
            if isinstance(raw_inventory_item, str):
                raw_inventory_item = {
                    "template_id": str(raw_inventory_item).strip(),
                    "quantity": 1,
                }
            if not isinstance(raw_inventory_item, dict):
                raise ValueError(f"NPC '{npc_id}' inventory_items entries must be objects or template_id strings.")

            template_id = str(raw_inventory_item.get("template_id", "")).strip()
            if not template_id:
                raise ValueError(f"NPC '{npc_id}' inventory_items entries must include template_id.")
            if get_gear_template_by_id(template_id) is None and get_item_template_by_id(template_id) is None:
                raise ValueError(f"NPC '{npc_id}' references unknown inventory item template: {template_id}")

            quantity = int(raw_inventory_item.get("quantity", 1))
            if quantity <= 0:
                raise ValueError(f"NPC '{npc_id}' inventory item '{template_id}' quantity must be 1 or greater.")

            normalized_inventory_items.append({
                "template_id": template_id,
                "quantity": quantity,
            })

        is_merchant = bool(raw_npc.get("is_merchant", False))
        raw_merchant_inventory = raw_npc.get("merchant_inventory")
        if raw_merchant_inventory is None:
            raw_merchant_inventory_template_ids = raw_npc.get("merchant_inventory_template_ids", [])
            if raw_merchant_inventory_template_ids is None:
                raw_merchant_inventory_template_ids = []
            if not isinstance(raw_merchant_inventory_template_ids, list):
                raise ValueError(f"NPC '{npc_id}' merchant_inventory_template_ids must be a list.")
            raw_merchant_inventory = [
                {
                    "template_id": str(raw_template_id).strip(),
                    "infinite": True,
                    "quantity": 1,
                }
                for raw_template_id in raw_merchant_inventory_template_ids
                if str(raw_template_id).strip()
            ]

        if not isinstance(raw_merchant_inventory, list):
            raise ValueError(f"NPC '{npc_id}' merchant_inventory must be a list.")

        merchant_inventory: list[dict] = []
        merchant_inventory_template_ids: list[str] = []
        seen_merchant_template_ids: set[str] = set()
        for raw_stock_entry in raw_merchant_inventory:
            if isinstance(raw_stock_entry, str):
                raw_stock_entry = {
                    "template_id": str(raw_stock_entry).strip(),
                    "infinite": True,
                    "quantity": 1,
                }
            if not isinstance(raw_stock_entry, dict):
                raise ValueError(f"NPC '{npc_id}' merchant inventory entries must be objects.")

            template_id = str(raw_stock_entry.get("template_id", "")).strip()
            if not template_id:
                raise ValueError(f"NPC '{npc_id}' merchant inventory entries must include template_id.")

            normalized_template_id = template_id.lower()
            if normalized_template_id in seen_merchant_template_ids:
                raise ValueError(f"NPC '{npc_id}' has duplicate merchant stock entry: {template_id}")
            if get_gear_template_by_id(template_id) is None and get_item_template_by_id(template_id) is None:
                raise ValueError(f"NPC '{npc_id}' references unknown merchant stock item: {template_id}")

            infinite = bool(raw_stock_entry.get("infinite", False))
            quantity = max(0, int(raw_stock_entry.get("quantity", 1)))
            if not infinite and quantity <= 0:
                raise ValueError(f"NPC '{npc_id}' limited merchant stock '{template_id}' must have quantity >= 1.")

            seen_merchant_template_ids.add(normalized_template_id)
            merchant_inventory_template_ids.append(template_id)
            merchant_inventory.append({
                "template_id": template_id,
                "infinite": infinite,
                "quantity": quantity,
            })

        merchant_buy_markup = float(raw_npc.get("merchant_buy_markup", 1.0))
        if merchant_buy_markup <= 0.0:
            raise ValueError(f"NPC '{npc_id}' merchant_buy_markup must be greater than zero.")

        merchant_sell_ratio = float(raw_npc.get("merchant_sell_ratio", 0.5))
        if merchant_sell_ratio < 0.0 or merchant_sell_ratio > 1.0:
            raise ValueError(f"NPC '{npc_id}' merchant_sell_ratio must be between 0.0 and 1.0.")

        if is_merchant and not merchant_inventory:
            raise ValueError(f"Merchant NPC '{npc_id}' must define merchant_inventory or merchant_inventory_template_ids.")

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

        normalized_skill_ids: list[str] = []
        seen_skill_ids: set[str] = set()
        for raw_skill_id in raw_skill_ids:
            skill_id = str(raw_skill_id).strip()
            if not skill_id:
                continue
            normalized_skill_id = skill_id.lower()
            if normalized_skill_id in seen_skill_ids:
                continue
            if get_skill_by_id(skill_id) is None:
                raise ValueError(f"NPC '{npc_id}' references unknown skill: {skill_id}")
            seen_skill_ids.add(normalized_skill_id)
            normalized_skill_ids.append(skill_id)

        power_level = max(0, int(raw_npc.get("power_level", 1)))

        if normalized_npc_id not in normalized_npcs_by_id:
            ordered_npc_ids.append(normalized_npc_id)
        normalized_npcs_by_id[normalized_npc_id] = {
            "npc_id": npc_id,
            "name": name,
            "hit_points": hit_points,
            "max_hit_points": max_hit_points,
            "power_level": power_level,
            "attacks_per_round": int(raw_npc.get("attacks_per_round", 1)),
            "hit_roll_modifier": int(raw_npc.get("hit_roll_modifier", 0)),
            "armor_class": int(raw_npc.get("armor_class", 10)),
            "off_hand_attacks_per_round": int(raw_npc.get("off_hand_attacks_per_round", 0)),
            "off_hand_hit_roll_modifier": int(raw_npc.get("off_hand_hit_roll_modifier", 0)),
            "coin_reward": max(0, int(raw_npc.get("coin_reward", 0))),
            "experience_reward": max(0, int(raw_npc.get("experience_reward", 0))),
            "is_aggro": bool(raw_npc.get("is_aggro", False)),
            "is_ally": bool(raw_npc.get("is_ally", False)),
            "is_peaceful": bool(raw_npc.get("is_peaceful", False)),
            "respawn": bool(raw_npc.get("respawn", True)),
            "is_merchant": is_merchant,
            "merchant_inventory_template_ids": merchant_inventory_template_ids,
            "merchant_inventory": merchant_inventory,
            "merchant_buy_markup": merchant_buy_markup,
            "merchant_sell_ratio": merchant_sell_ratio,
            "pronoun_possessive": str(raw_npc.get("pronoun_possessive", "its")).strip().lower() or "its",
            "main_hand_weapon_template_id": str(raw_npc.get("main_hand_weapon_template_id", "")).strip(),
            "off_hand_weapon_template_id": str(raw_npc.get("off_hand_weapon_template_id", "")).strip(),
            "vigor": vigor,
            "max_vigor": max_vigor,
            "mana": mana,
            "max_mana": max_mana,
            "skill_use_chance": skill_use_chance,
            "skill_ids": normalized_skill_ids,
            "spell_use_chance": spell_use_chance,
            "spell_ids": normalized_spell_ids,
            "inventory_items": normalized_inventory_items,
            "loot_items": normalized_loot_items,
        }

    return [normalized_npcs_by_id[npc_id] for npc_id in ordered_npc_ids]


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
    raw_spells = list(raw_spells) + _load_asset_payload_section("spells")

    normalized_spells_by_id: dict[str, dict] = {}
    ordered_spell_ids: list[str] = []
    spell_name_to_id: dict[str, str] = {}
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

        normalized_spell_id = spell_id.strip().lower()
        normalized_name = name.strip().lower()
        is_payload_override = _is_asset_payload_override(raw_spell)
        existing_name = ""
        if normalized_spell_id in normalized_spells_by_id:
            existing_name = str(normalized_spells_by_id[normalized_spell_id].get("name", "")).strip().lower()
            if not is_payload_override:
                raise ValueError(f"Duplicate spell_id in spell assets: {spell_id}")

        if normalized_name in spell_name_to_id and spell_name_to_id[normalized_name] != normalized_spell_id:
            raise ValueError(f"Duplicate spell name in spell assets: {name}")
        if existing_name and existing_name != normalized_name and spell_name_to_id.get(existing_name) == normalized_spell_id:
            del spell_name_to_id[existing_name]

        if normalized_spell_id not in normalized_spells_by_id:
            ordered_spell_ids.append(normalized_spell_id)
        spell_name_to_id[normalized_name] = normalized_spell_id

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

        normalized_spells_by_id[normalized_spell_id] = {
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
        }

    return [normalized_spells_by_id[spell_id] for spell_id in ordered_spell_ids]


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
    raw_skills = list(raw_skills) + _load_asset_payload_section("skills")

    normalized_skills_by_id: dict[str, dict] = {}
    ordered_skill_ids: list[str] = []
    skill_name_to_id: dict[str, str] = {}
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

        normalized_skill_id = skill_id.strip().lower()
        normalized_name = name.strip().lower()
        is_payload_override = _is_asset_payload_override(raw_skill)
        existing_name = ""
        if normalized_skill_id in normalized_skills_by_id:
            existing_name = str(normalized_skills_by_id[normalized_skill_id].get("name", "")).strip().lower()
            if not is_payload_override:
                raise ValueError(f"Duplicate skill_id in skill assets: {skill_id}")

        if normalized_name in skill_name_to_id and skill_name_to_id[normalized_name] != normalized_skill_id:
            raise ValueError(f"Duplicate skill name in skill assets: {name}")
        if existing_name and existing_name != normalized_name and skill_name_to_id.get(existing_name) == normalized_skill_id:
            del skill_name_to_id[existing_name]

        if normalized_skill_id not in normalized_skills_by_id:
            ordered_skill_ids.append(normalized_skill_id)
        skill_name_to_id[normalized_name] = normalized_skill_id

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
        level_scaling_multiplier = float(raw_skill.get("level_scaling_multiplier", 1.0))
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
        if level_scaling_multiplier < 0.0:
            raise ValueError(f"Skill asset '{skill_id}' level_scaling_multiplier must be zero or greater.")
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

        normalized_skills_by_id[normalized_skill_id] = {
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
            "level_scaling_multiplier": level_scaling_multiplier,
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
        }

    return [normalized_skills_by_id[skill_id] for skill_id in ordered_skill_ids]


def get_skill_by_id(skill_id: str) -> dict | None:
    normalized = skill_id.strip().lower()
    for skill in load_skills():
        if str(skill.get("skill_id", "")).strip().lower() == normalized:
            return skill
    return None
