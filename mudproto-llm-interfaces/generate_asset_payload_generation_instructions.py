from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ASSET_ROOT = REPO_ROOT / "mudproto-server" / "configuration" / "assets"
LLM_PAYLOAD_ROOT = ASSET_ROOT / "llm-payloads"
OUTPUT_FILE = SCRIPT_DIR / "asset_payload_generation_instructions.json"

BASE_ASSET_FILES = {
    "gear": "gear.json",
    "items": "items.json",
    "npcs": "npcs.json",
    "rooms": "rooms.json",
    "skills": "skills.json",
    "spells": "spells.json",
    "zones": "zones.json",
}

FULL_ASSET_SCHEMAS = {
    "payload_bundle": {
        "top_level_type": "object",
        "required_fields": {
            "payload_id": {
                "type": "string",
                "notes": "Unique bundle identifier. Append a GUID suffix.",
            },
            "description": {
                "type": "string",
                "notes": "Short human-readable summary of what the payload adds.",
            },
            "gear": {"type": "array[gear]"},
            "items": {"type": "array[item]"},
            "spells": {"type": "array[spell]"},
            "skills": {"type": "array[skill]"},
            "npcs": {"type": "array[npc]"},
            "rooms": {"type": "array[room]"},
            "zones": {"type": "array[zone]"},
        },
    },
    "gear": {
        "file": "gear.json",
        "top_level_type": "array",
        "id_field": "template_id",
        "id_prefixes": ["weapon.", "armor."],
        "fields": {
            "template_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "slot": {"type": "string", "required": True, "allowed_values": ["weapon", "armor"]},
            "description": {"type": "string", "required": False, "default": ""},
            "keywords": {"type": "array[string]", "required": False, "default": []},
            "weapon_type": {"type": "string", "required": False, "default": "unarmed"},
            "can_hold": {"type": "boolean", "required": False, "default": False, "notes": "Weapon-only field."},
            "weight": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "coin_value": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "damage_dice_count": {"type": "integer", "required": False, "default": 0},
            "damage_dice_sides": {"type": "integer", "required": False, "default": 0},
            "damage_roll_modifier": {"type": "integer", "required": False, "default": 0},
            "hit_roll_modifier": {"type": "integer", "required": False, "default": 0},
            "attack_damage_bonus": {"type": "integer", "required": False, "default": 0},
            "attacks_per_round_bonus": {"type": "integer", "required": False, "default": 0},
            "armor_class_bonus": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "wear_slots": {"type": "array[string]", "required": False, "default": [], "notes": "Required for armor, must be empty for weapons."},
        },
    },
    "items": {
        "file": "items.json",
        "top_level_type": "array",
        "id_field": "template_id",
        "id_prefixes": ["item."],
        "fields": {
            "template_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "description": {"type": "string", "required": False, "default": ""},
            "keywords": {"type": "array[string]", "required": False, "default": []},
            "effect_type": {"type": "string", "required": True, "allowed_values": ["restore"]},
            "effect_target": {"type": "string", "required": True, "allowed_values": ["hit_points", "mana", "vigor"]},
            "effect_amount": {"type": "integer", "required": True, "minimum": 1},
            "coin_value": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "use_lag_seconds": {"type": "number", "required": False, "default": 0.0, "minimum": 0.0},
            "observer_action": {"type": "string", "required": False, "default": ""},
            "observer_context": {"type": "string", "required": False, "default": ""},
        },
    },
    "zones": {
        "file": "zones.json",
        "top_level_type": "array",
        "id_field": "zone_id",
        "id_prefixes": ["zone."],
        "fields": {
            "zone_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "repopulate_game_hours": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "repopulate_each_game_hour": {"type": "boolean", "required": False, "legacy_alias": True, "notes": "Legacy compatibility flag; prefer repopulate_game_hours."},
        },
    },
    "rooms": {
        "file": "rooms.json",
        "top_level_type": "array",
        "id_field": "room_id",
        "fields": {
            "room_id": {"type": "string", "required": True},
            "title": {"type": "string", "required": True},
            "description": {"type": "string", "required": True},
            "zone_id": {"type": "string", "required": True},
            "exits": {"type": "object<string, room_id>", "required": True},
            "npcs": {
                "type": "array[object]",
                "required": False,
                "default": [],
                "entry_schema": {
                    "npc_id": {"type": "string", "required": True},
                    "count": {"type": "integer", "required": False, "default": 1, "minimum": 1},
                },
            },
        },
    },
    "npcs": {
        "file": "npcs.json",
        "top_level_type": "object",
        "top_level_key": "npcs",
        "id_field": "npc_id",
        "id_prefixes": ["npc."],
        "fields": {
            "npc_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "hit_points": {"type": "integer", "required": False, "default": "max_hit_points"},
            "max_hit_points": {"type": "integer", "required": True, "minimum": 1},
            "power_level": {"type": "integer", "required": False, "default": 1, "minimum": 0},
            "attacks_per_round": {"type": "integer", "required": False, "default": 1},
            "hit_roll_modifier": {"type": "integer", "required": False, "default": 0},
            "armor_class": {"type": "integer", "required": False, "default": 10},
            "off_hand_attacks_per_round": {"type": "integer", "required": False, "default": 0},
            "off_hand_hit_roll_modifier": {"type": "integer", "required": False, "default": 0},
            "coin_reward": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "experience_reward": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "is_aggro": {"type": "boolean", "required": False, "default": False},
            "is_ally": {"type": "boolean", "required": False, "default": False},
            "is_peaceful": {"type": "boolean", "required": False, "default": False},
            "respawn": {"type": "boolean", "required": False, "default": True},
            "is_merchant": {"type": "boolean", "required": False, "default": False},
            "merchant_inventory": {
                "type": "array[object]",
                "required": False,
                "default": [],
                "entry_schema": {
                    "template_id": {"type": "string", "required": True},
                    "infinite": {"type": "boolean", "required": False, "default": False},
                    "quantity": {"type": "integer", "required": False, "default": 1, "minimum": 0},
                },
            },
            "merchant_inventory_template_ids": {"type": "array[string]", "required": False, "default": [], "legacy_alias": True},
            "merchant_buy_markup": {"type": "number", "required": False, "default": 1.0, "exclusive_minimum": 0.0},
            "merchant_sell_ratio": {"type": "number", "required": False, "default": 0.5, "minimum": 0.0, "maximum": 1.0},
            "pronoun_possessive": {"type": "string", "required": False, "default": "its"},
            "main_hand_weapon_template_id": {"type": "string", "required": False, "default": ""},
            "off_hand_weapon_template_id": {"type": "string", "required": False, "default": ""},
            "vigor": {"type": "integer", "required": False, "default": "max_vigor", "minimum": 0},
            "max_vigor": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "mana": {"type": "integer", "required": False, "default": "max_mana", "minimum": 0},
            "max_mana": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "skill_use_chance": {"type": "number", "required": False, "default": 0.35, "minimum": 0.0, "maximum": 1.0},
            "skill_ids": {"type": "array[string]", "required": False, "default": []},
            "spell_use_chance": {"type": "number", "required": False, "default": 0.25, "minimum": 0.0, "maximum": 1.0},
            "spell_ids": {"type": "array[string]", "required": False, "default": []},
            "loot_items": {
                "type": "array[object]",
                "required": False,
                "default": [],
                "entry_schema": {
                    "name": {"type": "string", "required": True},
                    "description": {"type": "string", "required": False, "default": ""},
                    "keywords": {"type": "array[string]", "required": False, "default": []},
                },
            },
        },
    },
    "spells": {
        "file": "spells.json",
        "top_level_type": "array",
        "id_field": "spell_id",
        "id_prefixes": ["spell."],
        "fields": {
            "spell_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "school": {"type": "string", "required": True},
            "description": {"type": "string", "required": False, "default": ""},
            "mana_cost": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "spell_type": {"type": "string", "required": False, "default": "damage", "allowed_values": ["damage", "support"]},
            "cast_type": {"type": "string", "required": False, "default": "target for damage, self for support", "allowed_values": ["self", "target", "aoe"]},
            "damage_dice_count": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "damage_dice_sides": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "damage_modifier": {"type": "integer", "required": False, "default": 0},
            "damage_scaling_attribute_id": {"type": "string", "required": False, "default": "int", "allowed_values": ["str", "dex", "con", "int", "wis"]},
            "damage_scaling_multiplier": {"type": "number", "required": False, "default": 1.0, "minimum": 0.0},
            "level_scaling_multiplier": {"type": "number", "required": False, "default": 1.0, "minimum": 0.0},
            "damage_context": {"type": "string", "required": "for damage spells"},
            "restore_effect": {"type": "string", "required": False, "allowed_values": ["heal", "vigor", "mana", ""]},
            "restore_ratio": {"type": "number", "required": False, "default": 0.0, "minimum": 0.0, "maximum": 1.0},
            "restore_context": {"type": "string", "required": False, "default": ""},
            "observer_restore_context": {"type": "string", "required": False, "default": ""},
            "life_steal_ratio": {"type": "number", "required": False, "legacy_alias": True},
            "life_steal_context": {"type": "string", "required": False, "legacy_alias": True},
            "observer_life_steal_context": {"type": "string", "required": False, "legacy_alias": True},
            "support_effect": {"type": "string", "required": "for support spells", "allowed_values": ["heal", "vigor", "mana"]},
            "support_amount": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "support_dice_count": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "support_dice_sides": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "support_roll_modifier": {"type": "integer", "required": False, "default": 0},
            "support_scaling_attribute_id": {"type": "string", "required": False, "default": ""},
            "support_scaling_multiplier": {"type": "number", "required": False, "default": 1.0, "minimum": 0.0},
            "duration_hours": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "duration_rounds": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "support_mode": {"type": "string", "required": False, "default": "timed", "allowed_values": ["timed", "instant", "battle_rounds"]},
            "support_context": {"type": "string", "required": "for support spells"},
            "observer_action": {"type": "string", "required": False, "default": ""},
            "observer_context": {"type": "string", "required": False, "default": ""},
        },
    },
    "skills": {
        "file": "skills.json",
        "top_level_type": "array",
        "id_field": "skill_id",
        "id_prefixes": ["skill."],
        "fields": {
            "skill_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "description": {"type": "string", "required": False, "default": ""},
            "skill_type": {"type": "string", "required": False, "default": "damage", "allowed_values": ["damage", "support"]},
            "cast_type": {"type": "string", "required": False, "default": "target for damage, self for support", "allowed_values": ["self", "target", "aoe"]},
            "damage_dice_count": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "damage_dice_sides": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "damage_modifier": {"type": "integer", "required": False, "default": 0},
            "vigor_cost": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "usable_out_of_combat": {"type": "boolean", "required": False, "default": False},
            "scaling_attribute_id": {"type": "string", "required": False, "default": "", "allowed_values": ["", "str", "dex", "con", "int", "wis"]},
            "scaling_multiplier": {"type": "number", "required": False, "default": 0.0, "minimum": 0.0},
            "level_scaling_multiplier": {"type": "number", "required": False, "default": 1.0, "minimum": 0.0},
            "damage_context": {"type": "string", "required": "for damage skills"},
            "restore_effect": {"type": "string", "required": False, "allowed_values": ["heal", "vigor", "mana", ""]},
            "restore_ratio": {"type": "number", "required": False, "default": 0.0, "minimum": 0.0, "maximum": 1.0},
            "restore_context": {"type": "string", "required": False, "default": ""},
            "observer_restore_context": {"type": "string", "required": False, "default": ""},
            "support_effect": {"type": "string", "required": "for support skills", "allowed_values": ["heal", "vigor", "mana"]},
            "support_amount": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "support_context": {"type": "string", "required": "for support skills"},
            "observer_action": {"type": "string", "required": False, "default": ""},
            "observer_context": {"type": "string", "required": False, "default": ""},
            "lag_rounds": {"type": "integer", "required": False, "default": 0, "minimum": 0},
            "cooldown_rounds": {"type": "integer", "required": False, "default": 0, "minimum": 0},
        },
    },
}


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_base_assets() -> dict[str, object]:
    return {
        asset_type: read_json(ASSET_ROOT / filename)
        for asset_type, filename in BASE_ASSET_FILES.items()
    }


def load_llm_payloads() -> list[dict[str, object]]:
    if not LLM_PAYLOAD_ROOT.exists():
        return []

    payloads: list[dict[str, object]] = []
    for path in sorted(LLM_PAYLOAD_ROOT.glob("*.json")):
        if not path.is_file():
            continue
        payloads.append({
            "file_name": path.name,
            "content": read_json(path),
        })
    return payloads


def _count_list_entries(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def build_asset_counts(base_assets: dict[str, object], llm_payloads: list[dict[str, object]]) -> dict[str, int]:
    raw_npcs = base_assets.get("npcs", {})
    npc_entries = raw_npcs.get("npcs", []) if isinstance(raw_npcs, dict) else []

    return {
        "gear": _count_list_entries(base_assets.get("gear", [])),
        "items": _count_list_entries(base_assets.get("items", [])),
        "npcs": _count_list_entries(npc_entries),
        "rooms": _count_list_entries(base_assets.get("rooms", [])),
        "skills": _count_list_entries(base_assets.get("skills", [])),
        "spells": _count_list_entries(base_assets.get("spells", [])),
        "zones": _count_list_entries(base_assets.get("zones", [])),
        "llm_payload_files": len(llm_payloads),
    }


def build_instruction_payload() -> dict[str, object]:
    base_assets = load_base_assets()
    llm_payloads = load_llm_payloads()

    return {
        "interface_id": "mudproto.asset-payload-generator",
        "version": "2.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Instructions for an LLM to generate a single MudProto asset payload JSON bundle that can be dropped into mudproto-server/configuration/assets/llm-payloads/ and loaded by the server.",
        "drop_location": "mudproto-server/configuration/assets/llm-payloads/",
        "response_contract": {
            "format": "Return one raw JSON object only.",
            "forbidden": [
                "markdown code fences",
                "comments",
                "explanatory prose before or after the JSON",
                "trailing commas"
            ],
            "filename_guidance": "Use a short kebab-case filename such as sanctum-library-expansion.json"
        },
        "id_collision_prevention": {
            "guid_suffix_required": True,
            "rule": "Append a GUID to every newly created asset ID and to payload_id to prevent collisions with existing or future content.",
            "applies_to": [
                "payload_id",
                "gear[].template_id",
                "items[].template_id",
                "spells[].spell_id",
                "skills[].skill_id",
                "npcs[].npc_id",
                "rooms[].room_id",
                "zones[].zone_id"
            ],
            "reference_rule": "All cross-references inside the payload must use the same GUID-suffixed IDs.",
            "example": {
                "base_slug": "npc.sanctum-archivist",
                "generated_id": "npc.sanctum-archivist-550e8400-e29b-41d4-a716-446655440000"
            }
        },
        "top_level_schema": FULL_ASSET_SCHEMAS["payload_bundle"],
        "generation_rules": [
            "Keep all IDs unique within their asset type.",
            "Append a GUID suffix to every new asset ID and payload_id.",
            "Use lowercase IDs and keywords to match project conventions.",
            "Every asset section must be present and must be a JSON array, even when empty.",
            "Only use fields supported by the schemas below.",
            "Only reference assets that exist in the base game or in this same payload.",
            "Preserve MudProto's existing fantasy tone and naming style.",
            "Prefer small, coherent bundles that describe one area, quest pocket, encounter set, merchant restock, or feature addition."
        ],
        "cross_reference_requirements": [
            "rooms[].zone_id must match a zone_id in the base assets or this payload.",
            "rooms[].npcs[].npc_id must match an NPC in the base assets or this payload.",
            "rooms[].exits[direction] must point to a valid room_id.",
            "npcs[].main_hand_weapon_template_id and off_hand_weapon_template_id must match gear template_id values.",
            "npcs[].merchant_inventory[].template_id must match a gear or item template_id.",
            "npcs[].spell_ids[] must match spell_id values.",
            "npcs[].skill_ids[] must match skill_id values.",
            "spells[].damage_scaling_attribute_id and skills[].scaling_attribute_id should use valid attribute ids such as str, dex, con, int, or wis."
        ],
        "authoring_order": [
            "Create gear, items, spells, and skills first.",
            "Create NPCs that reference those assets.",
            "Create rooms that place those NPCs.",
            "Create or update zones if needed.",
            "Validate all cross-references before returning the final JSON."
        ],
        "minimum_quality_bar": [
            "Descriptions should be concise and usable in-game.",
            "Room titles and NPC names should sound like they belong in MudProto.",
            "Combat/support context strings should be ready for player-facing text.",
            "Merchant inventories should be sensible for the NPC role.",
            "Avoid overpowered numbers unless explicitly requested."
        ],
        "asset_schemas": {
            key: value
            for key, value in FULL_ASSET_SCHEMAS.items()
            if key != "payload_bundle"
        },
        "reference_docs": [
            "ASSET_GENERATION.md",
            "mudproto-server/assets.py"
        ],
        "current_game_assets": {
            "counts": build_asset_counts(base_assets, llm_payloads),
            "base_assets": base_assets,
            "llm_payloads": llm_payloads,
        },
        "starter_template": {
            "payload_id": "example-bundle-<GUID>",
            "description": "Brief summary of the content added by this payload.",
            "gear": [],
            "items": [],
            "spells": [],
            "skills": [],
            "npcs": [],
            "rooms": [],
            "zones": []
        }
    }


def main() -> None:
    payload = build_instruction_payload()
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
