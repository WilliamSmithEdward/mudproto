from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ASSET_ROOT = REPO_ROOT / "mudproto-server" / "configuration" / "assets"
TEMPLATE_ROOT = ASSET_ROOT / "templates"
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

SCHEMA_TEMPLATE_FILES = {
    "payload_bundle": "llm-payload.template.json",
    "gear": "gear.template.json",
    "items": "items.template.json",
    "npcs": "npcs.template.json",
    "rooms": "rooms.template.json",
    "skills": "skills.template.json",
    "spells": "spells.template.json",
    "zones": "zones.template.json",
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


def load_asset_schemas() -> dict[str, dict[str, object]]:
    schemas: dict[str, dict[str, object]] = {}

    for schema_name, file_name in SCHEMA_TEMPLATE_FILES.items():
        template_path = TEMPLATE_ROOT / file_name
        raw_template = read_json(template_path)
        if not isinstance(raw_template, dict):
            raise ValueError(f"Schema template file must contain an object: {template_path}")

        raw_schema = raw_template.get("schema")
        if not isinstance(raw_schema, dict):
            raise ValueError(f"Schema template '{template_path.name}' must contain an object field named 'schema'.")

        schemas[schema_name] = raw_schema

    return schemas


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
    asset_schemas = load_asset_schemas()

    return {
        "interface_id": "mudproto.asset-payload-generator",
        "version": "2.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Instructions for an LLM to generate a single MudProto asset payload JSON bundle that can be dropped into mudproto-server/configuration/assets/llm-payloads/ and loaded by the server.",
        "drop_location": "mudproto-server/configuration/assets/llm-payloads/",
        "response_contract": {
            "format": "Return one raw JSON object only.",
            "delivery_requirement": "The final result should be provided as a downloadable `.json` file, not just pasted as prose or wrapped in Markdown.",
            "forbidden": [
                "markdown code fences",
                "comments",
                "explanatory prose before or after the JSON",
                "trailing commas"
            ],
            "filename_guidance": "Use a short kebab-case filename such as sanctum-library-expansion.json",
            "interactive_behavior": "If the user has not yet provided enough design direction, ask concise clarifying questions first and do not emit the final JSON payload until those answers are known."
        },
        "pre_generation_discovery": {
            "required_before_content_creation": True,
            "skip_if_already_specified": True,
            "rule": "Before generating new content, the LLM should ask a short discovery set to anchor the zone into the existing world and confirm scope, tone, and mechanics.",
            "required_questions": [
                "Which existing room or area should the new content attach to?",
                "What should the new zone be about in terms of theme, story, or fantasy concept?",
                "What kinds of content should it include, such as combat, merchants, lore, puzzles, boss fights, or support NPCs?",
                "What difficulty band should the zone target?",
                "Are there any special mechanics, gimmicks, hazards, or signature encounters to include?",
                "How large should the zone be, approximately how many rooms?",
                "Should the zone add new gear, items, spells, skills, or merchants?"
            ],
            "output_behavior": "If one or more of these details is missing, ask for them before generating the asset payload."
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
        "top_level_schema": asset_schemas["payload_bundle"],
        "generation_rules": [
            "Keep all IDs unique within their asset type.",
            "Append a GUID suffix to every new asset ID and payload_id.",
            "Use lowercase IDs and keywords to match project conventions.",
            "Before content creation, ask where the new content should attach, what the zone theme/content should be, the target difficulty, any special mechanics, and the desired room count unless the user already supplied that information.",
            "Every asset section must be present and must be a JSON array, even when empty.",
            "Deliver the final output as a downloadable `.json` file suitable for saving into `mudproto-server/configuration/assets/llm-payloads/`.",
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
            for key, value in asset_schemas.items()
            if key != "payload_bundle"
        },
        "reference_docs": [
            "ASSET_GENERATION.md",
            "mudproto-server/assets.py",
            "mudproto-server/configuration/assets/templates/"
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
