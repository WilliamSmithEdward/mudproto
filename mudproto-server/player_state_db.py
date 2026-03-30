import json
import sqlite3
from datetime import datetime, timezone

from models import ActiveSupportEffectState, ClientSession, EquipmentItemState, LootItemState
from settings import DEFAULT_PLAYER_STATE_KEY, PLAYER_STATE_DB_PATH


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    PLAYER_STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(PLAYER_STATE_DB_PATH))
    connection.row_factory = sqlite3.Row
    return connection


def initialize_player_state_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS player_state (
                player_key TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def _serialize_equipment_item(item: EquipmentItemState) -> dict:
    return {
        "item_id": item.item_id,
        "template_id": item.template_id,
        "name": item.name,
        "slot": item.slot,
        "description": item.description,
        "keywords": list(item.keywords),
        "weapon_type": item.weapon_type,
        "preferred_hand": item.preferred_hand,
        "damage_dice_count": int(item.damage_dice_count),
        "damage_dice_sides": int(item.damage_dice_sides),
        "damage_roll_modifier": int(item.damage_roll_modifier),
        "hit_roll_modifier": int(item.hit_roll_modifier),
        "attack_damage_bonus": int(item.attack_damage_bonus),
        "attacks_per_round_bonus": int(item.attacks_per_round_bonus),
        "armor_class_bonus": int(item.armor_class_bonus),
        "wear_slot": item.wear_slot,
        "wear_slots": list(item.wear_slots),
    }


def _deserialize_equipment_item(raw: dict) -> EquipmentItemState:
    return EquipmentItemState(
        item_id=str(raw.get("item_id", "")).strip(),
        template_id=str(raw.get("template_id", "")).strip(),
        name=str(raw.get("name", "")).strip(),
        slot=str(raw.get("slot", "")).strip(),
        description=str(raw.get("description", "")),
        keywords=[str(keyword) for keyword in raw.get("keywords", [])],
        weapon_type=str(raw.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
        preferred_hand=str(raw.get("preferred_hand", "main_hand")).strip().lower() or "main_hand",
        damage_dice_count=int(raw.get("damage_dice_count", 0)),
        damage_dice_sides=int(raw.get("damage_dice_sides", 0)),
        damage_roll_modifier=int(raw.get("damage_roll_modifier", 0)),
        hit_roll_modifier=int(raw.get("hit_roll_modifier", 0)),
        attack_damage_bonus=int(raw.get("attack_damage_bonus", 0)),
        attacks_per_round_bonus=int(raw.get("attacks_per_round_bonus", 0)),
        armor_class_bonus=int(raw.get("armor_class_bonus", 0)),
        wear_slot=str(raw.get("wear_slot", "")).strip(),
        wear_slots=[str(slot).strip().lower() for slot in raw.get("wear_slots", []) if str(slot).strip()],
    )


def _serialize_loot_item(item: LootItemState) -> dict:
    return {
        "item_id": item.item_id,
        "name": item.name,
        "description": item.description,
        "keywords": list(item.keywords),
    }


def _deserialize_loot_item(raw: dict) -> LootItemState:
    return LootItemState(
        item_id=str(raw.get("item_id", "")).strip(),
        name=str(raw.get("name", "")).strip() or "Item",
        description=str(raw.get("description", "")),
        keywords=[str(keyword) for keyword in raw.get("keywords", [])],
    )


def _serialize_support_effect(effect: ActiveSupportEffectState) -> dict:
    return {
        "spell_id": effect.spell_id,
        "spell_name": effect.spell_name,
        "support_mode": effect.support_mode,
        "support_effect": effect.support_effect,
        "support_amount": int(effect.support_amount),
        "remaining_hours": int(effect.remaining_hours),
        "remaining_rounds": int(effect.remaining_rounds),
    }


def _deserialize_support_effect(raw: dict) -> ActiveSupportEffectState:
    return ActiveSupportEffectState(
        spell_id=str(raw.get("spell_id", "")).strip(),
        spell_name=str(raw.get("spell_name", "")).strip() or "Spell",
        support_mode=str(raw.get("support_mode", "timed")).strip().lower() or "timed",
        support_effect=str(raw.get("support_effect", "")).strip().lower(),
        support_amount=int(raw.get("support_amount", 0)),
        remaining_hours=int(raw.get("remaining_hours", 0)),
        remaining_rounds=int(raw.get("remaining_rounds", 0)),
    )


def _serialize_session(session: ClientSession) -> dict:
    return {
        "player": {
            "current_room_id": session.player.current_room_id,
            "class_id": session.player.class_id,
        },
        "player_combat": {
            "attack_damage": int(session.player_combat.attack_damage),
            "attacks_per_round": int(session.player_combat.attacks_per_round),
        },
        "status": {
            "hit_points": int(session.status.hit_points),
            "vigor": int(session.status.vigor),
            "mana": int(session.status.mana),
            "coins": int(session.status.coins),
        },
        "equipment": {
            "items": {item_id: _serialize_equipment_item(item) for item_id, item in session.equipment.items.items()},
            "equipped_items": {
                item_id: _serialize_equipment_item(item)
                for item_id, item in session.equipment.equipped_items.items()
            },
            "equipped_main_hand_id": session.equipment.equipped_main_hand_id,
            "equipped_off_hand_id": session.equipment.equipped_off_hand_id,
            "worn_item_ids": dict(session.equipment.worn_item_ids),
        },
        "inventory_items": {
            item_id: _serialize_loot_item(item)
            for item_id, item in session.inventory_items.items()
        },
        "known_spell_ids": list(session.known_spell_ids),
        "known_skill_ids": list(session.known_skill_ids),
        "active_support_effects": [_serialize_support_effect(effect) for effect in session.active_support_effects],
    }


def save_player_state(session: ClientSession, player_key: str = DEFAULT_PLAYER_STATE_KEY) -> None:
    initialize_player_state_db()
    state_json = json.dumps(_serialize_session(session), separators=(",", ":"))

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO player_state(player_key, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                state_json=excluded.state_json,
                updated_at=excluded.updated_at
            """,
            (player_key, state_json, _utc_now_iso()),
        )
        connection.commit()


def load_player_state(session: ClientSession, player_key: str = DEFAULT_PLAYER_STATE_KEY) -> bool:
    initialize_player_state_db()

    with _connect() as connection:
        row = connection.execute(
            "SELECT state_json FROM player_state WHERE player_key = ?",
            (player_key,),
        ).fetchone()

    if row is None:
        return False

    raw_state = json.loads(str(row["state_json"]))
    if not isinstance(raw_state, dict):
        return False

    raw_player = raw_state.get("player", {})
    if isinstance(raw_player, dict):
        room_id = str(raw_player.get("current_room_id", "")).strip()
        class_id = str(raw_player.get("class_id", "")).strip()
        if room_id:
            session.player.current_room_id = room_id
        session.player.class_id = class_id

    raw_player_combat = raw_state.get("player_combat", {})
    if isinstance(raw_player_combat, dict):
        session.player_combat.attack_damage = int(raw_player_combat.get("attack_damage", session.player_combat.attack_damage))
        session.player_combat.attacks_per_round = max(1, int(raw_player_combat.get("attacks_per_round", session.player_combat.attacks_per_round)))

    raw_status = raw_state.get("status", {})
    if isinstance(raw_status, dict):
        session.status.hit_points = max(0, int(raw_status.get("hit_points", session.status.hit_points)))
        session.status.vigor = max(0, int(raw_status.get("vigor", session.status.vigor)))
        session.status.mana = max(0, int(raw_status.get("mana", session.status.mana)))
        session.status.coins = max(0, int(raw_status.get("coins", session.status.coins)))

    raw_equipment = raw_state.get("equipment", {})
    if isinstance(raw_equipment, dict):
        raw_items = raw_equipment.get("items", {})
        if isinstance(raw_items, dict):
            session.equipment.items = {
                str(item_id): _deserialize_equipment_item(raw_item)
                for item_id, raw_item in raw_items.items()
                if isinstance(raw_item, dict)
            }

        raw_equipped_items = raw_equipment.get("equipped_items", {})
        if isinstance(raw_equipped_items, dict):
            session.equipment.equipped_items = {
                str(item_id): _deserialize_equipment_item(raw_item)
                for item_id, raw_item in raw_equipped_items.items()
                if isinstance(raw_item, dict)
            }

        main_hand_id = raw_equipment.get("equipped_main_hand_id")
        off_hand_id = raw_equipment.get("equipped_off_hand_id")
        session.equipment.equipped_main_hand_id = str(main_hand_id).strip() if isinstance(main_hand_id, str) else None
        session.equipment.equipped_off_hand_id = str(off_hand_id).strip() if isinstance(off_hand_id, str) else None

        raw_worn_item_ids = raw_equipment.get("worn_item_ids", {})
        if isinstance(raw_worn_item_ids, dict):
            session.equipment.worn_item_ids = {
                str(slot): str(item_id)
                for slot, item_id in raw_worn_item_ids.items()
            }

    raw_inventory_items = raw_state.get("inventory_items", {})
    if isinstance(raw_inventory_items, dict):
        session.inventory_items = {
            str(item_id): _deserialize_loot_item(raw_item)
            for item_id, raw_item in raw_inventory_items.items()
            if isinstance(raw_item, dict)
        }

    raw_known_spell_ids = raw_state.get("known_spell_ids", [])
    if isinstance(raw_known_spell_ids, list):
        session.known_spell_ids = [str(spell_id).strip() for spell_id in raw_known_spell_ids if str(spell_id).strip()]

    raw_known_skill_ids = raw_state.get("known_skill_ids", [])
    if isinstance(raw_known_skill_ids, list):
        session.known_skill_ids = [str(skill_id).strip() for skill_id in raw_known_skill_ids if str(skill_id).strip()]

    raw_support_effects = raw_state.get("active_support_effects", [])
    if isinstance(raw_support_effects, list):
        session.active_support_effects = [
            _deserialize_support_effect(raw_effect)
            for raw_effect in raw_support_effects
            if isinstance(raw_effect, dict)
        ]

    return True
