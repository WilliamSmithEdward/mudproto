from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ASSET_ROOT = REPO_ROOT / "mudproto_server" / "configuration" / "assets"
TEMPLATE_ROOT = ASSET_ROOT / "templates"
ASSET_PAYLOAD_ROOT = ASSET_ROOT / "asset_payloads"
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
    "gear": "gear.template.json",
    "items": "items.template.json",
    "npcs": "npcs.template.json",
    "rooms": "rooms.template.json",
    "skills": "skills.template.json",
    "spells": "spells.template.json",
    "zones": "zones.template.json",
}

PAYLOAD_BUNDLE_SCHEMA = {
    "top_level_type": "object",
    "required_fields": {
        "payload_id": {
            "type": "string",
            "notes": "Unique bundle identifier. Append a GUID suffix unless intentionally overriding existing content."
        },
        "description": {
            "type": "string",
            "notes": "Short human-readable summary of what the payload adds."
        },
        "gear": {"type": "array[gear]"},
        "items": {"type": "array[item]"},
        "spells": {"type": "array[spell]"},
        "skills": {"type": "array[skill]"},
        "npcs": {"type": "array[npc]"},
        "rooms": {"type": "array[room]"},
        "zones": {"type": "array[zone]"}
    }
}


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_base_assets() -> dict[str, object]:
    return {
        asset_type: read_json(ASSET_ROOT / filename)
        for asset_type, filename in BASE_ASSET_FILES.items()
    }


def load_asset_payloads() -> list[dict[str, object]]:
    if not ASSET_PAYLOAD_ROOT.exists():
        return []

    payloads: list[dict[str, object]] = []
    for path in sorted(ASSET_PAYLOAD_ROOT.glob("*.json")):
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


def build_asset_counts(base_assets: dict[str, object], asset_payloads: list[dict[str, object]]) -> dict[str, int]:
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
        "asset_payload_files": len(asset_payloads),
    }


def build_instruction_payload() -> dict[str, object]:
    base_assets = load_base_assets()
    asset_payloads = load_asset_payloads()
    asset_schemas = load_asset_schemas()

    return {
        "interface_id": "mudproto.asset-payload-generator",
        "version": "2.20",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Instructions for an LLM to generate a single MudProto asset payload JSON bundle that can be dropped into mudproto_server/configuration/assets/asset_payloads/ and loaded by the server.",
        "drop_location": "mudproto_server/configuration/assets/asset_payloads/",
        "response_contract": {
            "format": "Return one raw JSON object only.",
            "delivery_requirement": "The final result should be provided as a downloadable `.json` file, not just pasted as prose or wrapped in Markdown.",
            "schema_conformance_requirement": "Every asset and the top-level payload must conform exactly to the provided schemas with no deviation, no extra fields, no renamed fields, no omitted required fields, and no unsupported structures.",
            "forbidden": [
                "markdown code fences",
                "comments",
                "explanatory prose before or after the JSON",
                "trailing commas",
                "extra fields not present in the provided schemas",
                "schema deviations of any kind"
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
            "override_exception": "If the goal is to intentionally override an existing base-game asset, reuse the original asset ID exactly instead of appending a GUID.",
            "applies_to": [
                "payload_id",
                "gear[].template_id",
                "items[].template_id",
                "spells[].spell_id",
                "skills[].skill_id",
                "npcs[].npc_id",
                "rooms[].room_id",
                "rooms[].room_objects[].object_id",
                "zones[].zone_id"
            ],
            "reference_rule": "All cross-references inside the payload must use the same GUID-suffixed IDs, unless the payload is intentionally overriding an existing base-game asset by reusing its original ID.",
            "example": {
                "base_slug": "npc.sanctum-archivist",
                "generated_id": "npc.sanctum-archivist-550e8400-e29b-41d4-a716-446655440000"
            }
        },
        "conflict_resolution": {
            "policy": "On asset ID conflict, the LLM payload should override the base-game definition.",
            "rule": "If the user wants to replace or modify an existing asset, reuse that asset's ID in the payload and provide the full replacement definition.",
            "room_merge_behavior": "If multiple asset payloads target the same room ID, merge the room exits across those payloads while keeping all other room fields from the last loaded room definition.",
            "other_asset_behavior": "For gear, items, spells, skills, NPCs, and zones, keep the last loaded asset definition when multiple payloads reuse the same ID.",
            "scope": ["gear", "items", "spells", "skills", "npcs", "rooms", "zones"]
        },
        "top_level_schema": PAYLOAD_BUNDLE_SCHEMA,
        "engine_capabilities": {
            "combat_and_abilities": [
                "Skills and spells support cast_type values self, target, and aoe (subject to asset-specific type constraints).",
                "Damage and support abilities support rich player-facing context strings (damage_context, support_context, observer_action, observer_context).",
                "Damage abilities support secondary restore effects via restore_effect/restore_ratio/restore_context fields.",
                "Skills support cooldown controls including cooldown_rounds, cooldown_hours, and target_lag_rounds. lag_rounds is supported but currently only enforced for NPC entities, not players.",
                "Support skills can scale over level steps using support_level_step and support_amount_per_level_step.",
                "Support effects include heal, vigor, mana, damage_reduction, and extra_unarmed_hits on skills when explicitly desired. Skills and spells also support affect-based status behavior via affect_ids, using shared templates such as affect.received-damage, affect.dealt-damage, affect.regeneration, and affect.extra-hits. Affect entries may be plain ids or override objects with affect_id plus tuning fields.",
                "Skills and spells support an element field (e.g. physical, storm, fire, restoration) used by element-aware affects such as affect.received-damage and affect.dealt-damage.",
                "Skills support a target_posture field that forces the target into standing, sitting, resting, or sleeping on a successful hit. Non-standing postures take increased damage and deal reduced damage.",
                "Skills with usable_out_of_combat set to true can be used outside of combat for support effects.",
                "Weapons support on-hit damage procs: room-wide (on_hit_room_damage_*) and single-target (on_hit_target_damage_*) with configurable chance, dice, and messages.",
                "Casting a spell during combat skips the player's next melee attack round.",
                "Spells support cooldown_rounds for NPC entity spell cooldowns; player spell cooldowns are not currently enforced."
            ],
            "npc_behavior_and_content": [
                "NPCs support aggro/ally/peaceful roles, merchant inventories and pricing, combat loadouts, and loot/inventory drops.",
                "NPCs support conditional aggro via aggro_player_flags: players with matching flags are auto-engaged on entering the NPC's room.",
                "NPCs support flag mutation on combat events: set_player_flags_on_hostile_action (when a player attacks the NPC), set_player_flags_on_death (on the killer), and set_world_flags_on_death (global). set_world_flags_on_death is critical for flag_spawns boss chains.",
                "NPCs support corpse_label_style (generic or possessive) to control corpse naming independently of is_named.",
                "NPCs support room_communications with audience control (private, room, both) plus player/world flag gating, flag mutation, and item-based gating (required_item_template_ids, excluded_item_template_ids).",
                "NPCs support keyword_actions for interactive commands, including noop, grant_item, remove_item, award_experience, teleport_player, and exit reveal/hide actions. Keyword actions also support item-based gating.",
                "NPCs support wandering via wander_chance and wander_room_ids (movement is constrained to directly connected exits that are also in wander_room_ids).",
                "NPCs sharing the same wander_pack_id in the same room wander together as a pack. When any pack member triggers a wander, all same-room pack members with that pack ID move to the same destination. Engaged pack members are left behind.",
                "Merchants support limited stock with quantity/base_quantity per inventory entry, and periodic restocking via merchant_restock_game_hours."
            ],
            "items_and_containers": [
                "Items support item_type values: consumable, potion, key, misc, and container.",
                "Consumable and potion items support affect_ids to apply status effects on use, using the same affect system as skills and spells.",
                "Key items have lock_ids matching lock_id values on exit_details or container items. Keys support consume_on_use to be destroyed after a successful unlock.",
                "Container items support open/close/lock/unlock state, contents (default items spawned inside), coins, and portable (whether the container can be picked up).",
                "Items support decay_game_hours for automatic expiry after a number of game hours, whether carried, dropped, or stored.",
                "Item coin_value is the base monetary value used by merchant pricing with buy_markup and sell_ratio multipliers."
            ],
            "rooms_and_interactions": [
                "Rooms support seeded NPCs, seeded items, room_objects, keyword_actions, and exit_details metadata/state.",
                "Exit details support close/open and lock/unlock state (including lock_id, can_lock, is_closed, is_locked, and optional message overrides).",
                "Room exits support only north/south/east/west/up/down directions; diagonals are not supported.",
                "Keyword actions support noop, grant_item, remove_item, award_experience, teleport_player, and room exit reveal/hide action types.",
                "Keyword actions and room_communications support item-based gating via required_item_template_ids and excluded_item_template_ids.",
                "Flavor-only interactions are supported through keyword_actions with noop-style messages and can be used for atmospheric commands like look shrine.",
                "Room objects are inspectable objects that respond to look commands with keywords and descriptions.",
                "Every room_objects entry must have a non-empty object_id, name, and description. The server rejects room_objects with blank or missing values for any of these fields."
            ],
            "zones_and_world_state": [
                "Zones support periodic repopulation via repopulate_game_hours.",
                "Zones support repopulation reset controls: reset_player_flags, reset_world_flags, and reset_container_template_ids.",
                "Zones support repopulation blockers via repopulation_blocking_item_template_ids and repopulation_block_cooldown_game_hours.",
                "Zones support conditional NPC spawn orchestration through flag_spawns (required/excluded world flags, npc_id, room_id, count)."
            ],
            "asset_payload_override_model": [
                "Payload entries can intentionally override base assets by reusing an existing asset ID.",
                "Rooms merge exits across payloads with the last loaded room defining non-exit fields.",
                "For non-room assets, last-loaded definition wins when IDs collide."
            ]
        },
        "generation_rules": [
            "Keep all IDs unique within their asset type.",
            "Append a GUID suffix to every new asset ID and payload_id unless you are intentionally overriding an existing base-game asset.",
            "If an asset is meant to override base-game content, reuse the base asset ID exactly and treat the payload definition as the replacement.",
            "If multiple asset payloads target the same room, their exits should accumulate while the most recently loaded room definition supplies the other room fields.",
            "For other asset types with repeated IDs, keep the most recently loaded asset definition.",
            "Use lowercase IDs and keywords to match project conventions.",
            "When defining gear bonuses, use direct `equipment_effects` entries with only `effect_type` and `amount`.",
            "For gear bonus effect_type values, use supported direct attribute ids such as `str`, `dex`, `con`, and `wis`, or configured shared gear stats such as `hit_points`, `vigor`, `mana`, `weapon_damage`, and `hitroll`.",
            "Use equipment_effects for passive while-equipped bonuses, and reserve affect_ids for temporary support or combat status behavior from abilities or valid items.",
            "Do not invent lore-only gear effect identifiers or unnecessary naming layers for equipment bonuses.",
            "Before content creation, ask where the new content should attach, what the zone theme/content should be, the target difficulty, any special mechanics, and the desired room count unless the user already supplied that information.",
            "Every asset section must be present and must be a JSON array, even when empty.",
            "Deliver the final output as a downloadable `.json` file suitable for saving into `mudproto_server/configuration/assets/asset_payloads/`.",
            "Conform every asset and the top-level payload exactly to the provided schemas with no deviation.",
            "Never leave any ID field (template_id, spell_id, skill_id, npc_id, room_id, zone_id, object_id) as an empty string. Every ID must be a meaningful, non-blank value.",
            "Never leave name or description fields as empty strings on any asset entry. Every name and description must contain meaningful text.",
            "Only use fields supported by the schemas below.",
            "Do not invent, rename, reorder semantically, or omit schema-defined structure beyond what the schemas explicitly allow.",
            "Some fields are only appropriate for certain NPC types; for example merchant and selling-related properties should only appear on merchant-style NPCs, and peaceful flags should only be used when the NPC concept actually calls for them.",
            "Only reference assets that exist in the base game or in this same payload.",
            "Do not create new consumable items, spells, or skills that are only cosmetic or lore reskins of existing mechanics. If the gameplay is materially the same, reuse or intentionally override the existing asset instead of adding a near-duplicate.",
            "You may create fully new spells and skills when they are flavorful, mechanically appropriate, and strongly matched to the theme, lore, and tone of the zone and the broader MudProto world.",
            "You may borrow from, reuse, extend, or reference existing game assets when it helps the design, but you do not have to; you may also create fully new assets when appropriate.",
            "Preserve MudProto's existing fantasy tone and naming style.",
            "Room descriptions should be 3-4 sentences long and should clearly reinforce the atmosphere, story, and theme of the zone they belong to.",
            "All room interconnections must be logical in-world and spatially coherent. Avoid random or immersion-breaking adjacency, and make connected rooms feel like they belong next to each other in a believable layout.",
            "If a final boss or locked area is gated behind multiple prerequisite kills or events, make sure every prerequisite emits the exact world flag the gate checks.",
            "Do not leave bypass routes open for gated progression. If a keep, vault, or sanctum is meant to unlock later, omit or hide that exit from the room's default exits until the gated action reveals it.",
            "Do not place a gated final boss in the room's default npc list. Prefer a zone flag_spawns rule with required_world_flags so the boss appears only after the prerequisites are met.",
            "Whenever appropriate, add at least one optional flavor interaction that is not required for progression or combat, such as a keyword action like 'look shrine' that returns atmospheric text.",
            "Flavor interactions should enrich worldbuilding and roleplay even when they have no mechanical reward.",
            "Be maximally creative with room names, spell names, skill names, item flavor, lore hooks, atmospheric details, and worldbuilding flair as long as every asset remains fully compliant with the provided schemas.",
            "Prefer small, coherent bundles that describe one area, quest pocket, encounter set, merchant restock, or feature addition.",
            "Room exits may only use the directions north, south, east, west, up, and down. Diagonal directions such as northeast, northwest, southeast, and southwest are not supported.",
            "damage_context and support_context strings that end with '!' or '?' must not also include a trailing period. The server automatically handles terminal punctuation for '.', '!', and '?'.",
            "For damage_context and support_context, write perspective-safe text that works for both player recipients and named NPC recipients. Prefer placeholders like [a/an] and [verb] rather than fixed second-person possessives.",
            "Do not use actor-POV lines like 'You drive a knife into your foe!' inside damage_context/support_context. Use neutral target-state wording such as '[a/an] [verb] thrown off balance by the strike!' so rendering remains grammatically correct for all targets.",
            "Set is_named explicitly on generated NPCs: true for unique proper-name or story-significant characters, false for ordinary generic mobs.",
            "When is_named is true, the NPC corpse label should read as the full-name possessive form, such as 'Brother Cleft's corpse'.",
            "Skills with target_lag_rounds > 0 inflict command lag on the target when hit. The attacking entity also self-lags for the same number of rounds, blocking its special abilities but not its melee attacks.",
            "NPCs with wander_chance > 0 and a non-empty wander_room_ids list will periodically move between rooms. All rooms in wander_room_ids should form a connected subgraph via their exits so the NPC can actually traverse between them. The NPC will only move to rooms that are both in wander_room_ids AND directly reachable via its current room's exits.",
            "NPCs that are currently engaged in combat with any player will not wander.",
            "To make NPCs wander as a pack, give them the same wander_pack_id value. All pack members should share the same wander_room_ids so they can travel the same routes. Pack members engaged in combat are left behind when the rest of the pack moves.",
            "Zones support a flag_spawns array for conditional NPC spawns triggered by world flag state. Each entry spawns an NPC into a specific room immediately after any NPC death that sets world flags, provided the NPC (by npc_id) is not already alive in the target room. Use this for scripted encounter progressions such as spawning a boss when a mini boss dies.",
            "flag_spawns entries fire every time the flag conditions are met and no matching NPC is alive in the room. To ensure a boss spawns exactly once per cycle, use reset_world_flags on repopulation to clear the trigger flags, which prevents the boss from re-spawning until the zone resets.",
            "When is_named is true, also set corpse_label_style to possessive so the corpse renders as the NPC's possessive name form.",
            "NPCs that should set world flags on death must include set_world_flags_on_death in the NPC template. This is the mechanism that triggers flag_spawns rules.",
            "When designing faction or reputation NPCs, use aggro_player_flags to make NPCs auto-attack players who have been flagged by hostile actions against their faction, and set_player_flags_on_hostile_action to apply the flag when a player attacks.",
            "Key items should have lock_ids that match the lock_id on the corresponding exit_details or container item they are meant to unlock.",
            "Container items placed in rooms should generally set portable to false for large environmental containers like chests.",
            "When creating quest items or keys that should not persist indefinitely, set decay_game_hours or consume_on_use as appropriate.",
            "Keyword action types grant_item, remove_item, and award_experience each have specific required fields: grant_item needs template_id (and optional quantity, if_missing), remove_item needs template_id (and optional quantity), and award_experience needs amount.",
            "Consumable and potion items can apply status effects via affect_ids using the same affect system as skills and spells."
        ],
        "data_integrity": [
            "Every asset entry must have a non-empty primary ID (template_id, spell_id, skill_id, npc_id, room_id, zone_id, or object_id for room_objects). The server rejects any asset with a blank or missing ID.",
            "Every asset entry that has a name field must provide a non-empty name string. The server rejects assets with blank or missing names.",
            "Every room_objects entry must include non-empty object_id, name, and description fields.",
            "Room object names are automatically title-cased by the server on load, so payloads should use lowercase or title case names."
        ],
        "cross_reference_requirements": [
            "rooms[].zone_id must match a zone_id in the base assets or this payload.",
            "rooms[].npcs[].npc_id must match an NPC in the base assets or this payload.",
            "rooms[].exits[direction] must point to a valid room_id.",
            "rooms[].items[].template_id must match an item template_id in the base assets or this payload.",
            "npcs[].main_hand_weapon.template_id and npcs[].off_hand_weapon.template_id must match gear template_id values.",
            "npcs[].inventory_items[].template_id and npcs[].merchant_inventory[].template_id must match a gear or item template_id.",
            "npcs[].spell_ids[] must match spell_id values.",
            "npcs[].skill_ids[] must match skill_id values.",
            "spells[].damage_scaling_attribute_id and skills[].scaling_attribute_id should use valid attribute ids such as str, dex, con, int, or wis.",
            "npcs[].wander_room_ids[] must match valid room_id values in the base assets or this payload.",
            "zones[].flag_spawns[].npc_id must match an NPC template in the base assets or this payload.",
            "zones[].flag_spawns[].room_id must match a room that belongs to this zone.",
            "npcs[].keyword_actions[].required_item_template_ids[] and excluded_item_template_ids[] must match item template_id values.",
            "npcs[].room_communications[].required_item_template_ids[] and excluded_item_template_ids[] must match item template_id values.",
            "rooms[].keyword_actions[].required_item_template_ids[] and excluded_item_template_ids[] must match item template_id values.",
            "items[].lock_ids[] on key items must match lock_id values on exit_details or container items.",
            "items[].affect_ids[] on consumable/potion items must match valid affect template ids."
        ],
        "authoring_order": [
            "Create gear, items, spells, and skills first.",
            "Create NPCs that reference those assets.",
            "Create rooms that place those NPCs.",
            "Create or update zones if needed.",
            "Validate all cross-references before returning the final JSON."
        ],
        "minimum_quality_bar": [
            "Descriptions should be concise, usable in-game, and support the intended fantasy atmosphere.",
            "Room descriptions should be 3-4 sentences in length and should tie directly into the theme of their zone.",
            "Room interconnections should feel natural and navigationally believable, with adjacency that makes sense for the fiction and layout of the area.",
            "Room titles, spell names, skill names, and NPC names should feel vivid, flavorful, and memorable while fitting MudProto's tone.",
            "Combat/support context strings should be ready for player-facing text.",
            "Combat/support context strings should be perspective-safe for both 'you' and named targets, avoiding recipient-relative nouns like 'your foe'.",
            "Include optional flavor-only interaction hooks (for example room or NPC keyword actions with noop-style output text) when they naturally fit the scene.",
            "Lore, atmosphere, and thematic flair are strongly encouraged whenever they fit within the schema-defined fields.",
            "New spells and skills should feel vivid, flavorful, and lore-native to the zone or encounter set they belong to rather than generic filler abilities.",
            "Merchant inventories should be sensible for the NPC role.",
            "Avoid redundant consumables, spells, and skills that duplicate existing mechanics under a new name unless the user explicitly requests a distinct variant or override.",
            "Gear bonus authoring should also stay broad and reusable: prefer direct stat bonuses over bespoke one-off effect labels.",
            "Boss-gated zones should be progression-safe: no always-open bypass to the finale, no missing prerequisite flags, and no pre-spawned final boss when the design calls for an unlock.",
            "Avoid overpowered numbers unless explicitly requested.",
            "Before returning the final JSON, verify that every asset has a non-empty primary ID and non-empty name. This is the most common cause of server-side validation failures."
        ],
        "asset_schemas": asset_schemas,
        "reference_docs": [
            "ASSET_GENERATION.md",
            "mudproto_server/core_logic/assets.py",
            "mudproto_server/configuration/assets/templates/"
        ],
        "current_game_assets": {
            "counts": build_asset_counts(base_assets, asset_payloads),
            "base_assets": base_assets,
            "asset_payloads": asset_payloads,
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

