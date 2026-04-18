import json
import sqlite3
import hashlib
import secrets
from datetime import datetime, timezone

from grammar import normalize_player_gender
from models import ActiveAffectState, ClientSession, ItemState
from experience import get_level_for_experience
from settings import DEFAULT_PLAYER_STATE_KEY, PLAYER_STATE_DB_PATH


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    PLAYER_STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(PLAYER_STATE_DB_PATH))
    connection.row_factory = sqlite3.Row
    return connection


def _is_transient_interaction_flag(flag_key: str) -> bool:
    normalized_flag = str(flag_key).strip().lower()
    if not normalized_flag or not normalized_flag.startswith("zone."):
        return False
    return "hostile" in normalized_flag or "aggro" in normalized_flag


def _normalize_interaction_flags(raw_flags: dict | None, *, include_transient: bool = False) -> dict[str, bool]:
    if not isinstance(raw_flags, dict):
        return {}

    normalized_flags: dict[str, bool] = {}
    for flag_key, flag_value in raw_flags.items():
        normalized_key = str(flag_key).strip().lower()
        if not normalized_key or not bool(flag_value):
            continue
        if not include_transient and _is_transient_interaction_flag(normalized_key):
            continue
        normalized_flags[normalized_key] = True
    return normalized_flags


def clear_transient_interaction_flags_for_session(session: ClientSession) -> int:
    current_flags = _normalize_interaction_flags(getattr(session.player, "interaction_flags", {}) or {}, include_transient=True)
    persistent_flags = {
        flag_key: flag_value
        for flag_key, flag_value in current_flags.items()
        if not _is_transient_interaction_flag(flag_key)
    }
    removed_count = len(current_flags) - len(persistent_flags)
    if removed_count > 0:
        session.player.interaction_flags = persistent_flags
    return removed_count


def initialize_player_state_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                character_key TEXT PRIMARY KEY,
                character_name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                class_id TEXT NOT NULL,
                gender TEXT NOT NULL DEFAULT 'unspecified',
                login_room_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        character_columns = {
            str(row["name"]).strip().lower()
            for row in connection.execute("PRAGMA table_info(characters)").fetchall()
        }
        if "gender" not in character_columns:
            connection.execute("ALTER TABLE characters ADD COLUMN gender TEXT NOT NULL DEFAULT 'unspecified'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS player_state (
                player_key TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS login_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempted_at TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                session_auth_stage TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                character_name TEXT NOT NULL DEFAULT '',
                character_key TEXT NOT NULL DEFAULT '',
                failure_reason TEXT NOT NULL DEFAULT '',
                remote_address TEXT NOT NULL DEFAULT '',
                local_address TEXT NOT NULL DEFAULT '',
                request_path TEXT NOT NULL DEFAULT '',
                headers_json TEXT NOT NULL DEFAULT '{}',
                connection_info_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.commit()


def normalize_character_name(raw_name: str) -> str | None:
    stripped = raw_name.strip()
    if not stripped:
        return None

    if not stripped.isalpha():
        return None

    return stripped.title()


def _character_key(character_name: str) -> str:
    return character_name.strip().lower()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _build_connection_snapshot(session: ClientSession) -> dict[str, object]:
    websocket = getattr(session, "websocket", None)
    request = getattr(websocket, "request", None)

    headers: dict[str, str] = {}
    raw_headers = getattr(request, "headers", None)
    if raw_headers is not None:
        try:
            headers = {str(key): str(value) for key, value in raw_headers.items()}
        except Exception:
            try:
                headers = {str(key): str(value) for key, value in raw_headers.raw_items()}
            except Exception:
                headers = {"repr": repr(raw_headers)}

    return {
        "client_id": str(getattr(session, "client_id", "") or ""),
        "connected_at": str(getattr(session, "connected_at", "") or ""),
        "remote_address": getattr(websocket, "remote_address", ""),
        "local_address": getattr(websocket, "local_address", ""),
        "request_path": str(getattr(request, "path", "") or ""),
        "subprotocol": str(getattr(websocket, "subprotocol", "") or ""),
        "headers": headers,
    }


def log_login_event(
    session: ClientSession,
    *,
    event_type: str,
    success: bool,
    character_name: str = "",
    character_key: str = "",
    failure_reason: str = "",
) -> None:
    initialize_player_state_db()
    snapshot = _build_connection_snapshot(session)

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO login_audit (
                attempted_at,
                client_id,
                session_auth_stage,
                event_type,
                success,
                character_name,
                character_key,
                failure_reason,
                remote_address,
                local_address,
                request_path,
                headers_json,
                connection_info_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                str(getattr(session, "client_id", "") or ""),
                str(getattr(session, "auth_stage", "") or ""),
                str(event_type).strip() or "unknown",
                1 if success else 0,
                str(character_name).strip(),
                str(character_key).strip().lower(),
                str(failure_reason).strip().lower(),
                _json_text(snapshot.get("remote_address", "")),
                _json_text(snapshot.get("local_address", "")),
                str(snapshot.get("request_path", "") or ""),
                _json_text(snapshot.get("headers", {})),
                _json_text(snapshot),
            ),
        )
        connection.commit()


def get_character_by_name(character_name: str) -> dict | None:
    normalized_name = normalize_character_name(character_name)
    if normalized_name is None:
        return None

    initialize_player_state_db()
    key = _character_key(normalized_name)
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT character_key, character_name, class_id, gender, login_room_id
            FROM characters
            WHERE character_key = ?
            """,
            (key,),
        ).fetchone()

    if row is None:
        return None

    return {
        "character_key": str(row["character_key"]),
        "character_name": str(row["character_name"]),
        "class_id": str(row["class_id"]),
        "gender": normalize_player_gender(str(row["gender"]), allow_unspecified=True) or "unspecified",
        "login_room_id": str(row["login_room_id"]),
    }


def character_exists(character_name: str) -> bool:
    return get_character_by_name(character_name) is not None


def create_character(
    *,
    character_name: str,
    password: str,
    class_id: str,
    gender: str,
    login_room_id: str,
) -> dict:
    normalized_name = normalize_character_name(character_name)
    if normalized_name is None:
        raise ValueError("Character name must be alpha-only.")

    if not password.strip():
        raise ValueError("Password cannot be empty.")

    normalized_gender = normalize_player_gender(gender, allow_unspecified=False)
    if normalized_gender is None:
        raise ValueError("Character gender must be male or female.")

    character_key = _character_key(normalized_name)
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    now_iso = _utc_now_iso()

    initialize_player_state_db()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT 1 FROM characters WHERE character_key = ?",
            (character_key,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Character already exists.")

        connection.execute(
            """
            INSERT INTO characters(
                character_key,
                character_name,
                password_salt,
                password_hash,
                class_id,
                gender,
                login_room_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character_key,
                normalized_name,
                salt,
                password_hash,
                class_id.strip(),
                normalized_gender,
                login_room_id.strip(),
                now_iso,
                now_iso,
            ),
        )
        connection.commit()

    return {
        "character_key": character_key,
        "character_name": normalized_name,
        "class_id": class_id.strip(),
        "gender": normalized_gender,
        "login_room_id": login_room_id.strip(),
    }


def verify_character_credentials(character_name: str, password: str) -> dict | None:
    normalized_name = normalize_character_name(character_name)
    if normalized_name is None:
        return None

    key = _character_key(normalized_name)
    initialize_player_state_db()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT character_key, character_name, password_salt, password_hash, class_id, gender, login_room_id
            FROM characters
            WHERE character_key = ?
            """,
            (key,),
        ).fetchone()

    if row is None:
        return None

    expected_hash = str(row["password_hash"])
    computed_hash = _hash_password(password, str(row["password_salt"]))
    if computed_hash != expected_hash:
        return None

    return {
        "character_key": str(row["character_key"]),
        "character_name": str(row["character_name"]),
        "class_id": str(row["class_id"]),
        "gender": normalize_player_gender(str(row["gender"]), allow_unspecified=True) or "unspecified",
        "login_room_id": str(row["login_room_id"]),
    }


def _serialize_item(item: ItemState) -> dict:
    return {
        "item_id": item.item_id,
        "template_id": item.template_id,
        "name": item.name,
        "description": item.description,
        "keywords": list(item.keywords),
        "equippable": bool(item.equippable),
        "slot": item.slot,
        "weapon_type": item.weapon_type,
        "can_hold": item.can_hold,
        "can_two_hand": bool(item.can_two_hand),
        "requires_two_hands": bool(item.requires_two_hands),
        "weight": int(item.weight),
        "damage_dice_count": int(item.damage_dice_count),
        "damage_dice_sides": int(item.damage_dice_sides),
        "damage_roll_modifier": int(item.damage_roll_modifier),
        "hit_roll_modifier": int(item.hit_roll_modifier),
        "attack_damage_bonus": int(item.attack_damage_bonus),
        "attacks_per_round_bonus": int(item.attacks_per_round_bonus),
        "on_hit_room_damage_chance": float(getattr(item, "on_hit_room_damage_chance", 0.0)),
        "on_hit_room_damage_dice_count": int(getattr(item, "on_hit_room_damage_dice_count", 0)),
        "on_hit_room_damage_dice_sides": int(getattr(item, "on_hit_room_damage_dice_sides", 0)),
        "on_hit_room_damage_roll_modifier": int(getattr(item, "on_hit_room_damage_roll_modifier", 0)),
        "on_hit_room_damage_message": str(getattr(item, "on_hit_room_damage_message", "")).strip(),
        "on_hit_room_damage_observer_message": str(getattr(item, "on_hit_room_damage_observer_message", "")).strip(),
        "on_hit_target_damage_chance": float(getattr(item, "on_hit_target_damage_chance", 0.0)),
        "on_hit_target_damage_dice_count": int(getattr(item, "on_hit_target_damage_dice_count", 0)),
        "on_hit_target_damage_dice_sides": int(getattr(item, "on_hit_target_damage_dice_sides", 0)),
        "on_hit_target_damage_roll_modifier": int(getattr(item, "on_hit_target_damage_roll_modifier", 0)),
        "on_hit_target_damage_message": str(getattr(item, "on_hit_target_damage_message", "")).strip(),
        "on_hit_target_damage_observer_message": str(getattr(item, "on_hit_target_damage_observer_message", "")).strip(),
        "armor_class_bonus": int(item.armor_class_bonus),
        "equipment_effects": [
            {
                "effect_type": str(effect.get("effect_type", "")).strip().lower(),
                "amount": int(effect.get("amount", 0)),
            }
            for effect in getattr(item, "equipment_effects", [])
            if isinstance(effect, dict) and str(effect.get("effect_type", "")).strip()
        ],
        "wear_slot": item.wear_slot,
        "wear_slots": list(item.wear_slots),
        "item_type": str(getattr(item, "item_type", "misc") or "misc"),
        "persistent": bool(getattr(item, "persistent", True)),
        "lock_ids": [str(lock_id).strip().lower() for lock_id in getattr(item, "lock_ids", []) if str(lock_id).strip()],
        "portable": bool(getattr(item, "portable", True)),
        "coins": int(getattr(item, "coins", 0)),
        "consume_on_use": bool(getattr(item, "consume_on_use", False)),
        "consume_message": str(getattr(item, "consume_message", "")).strip(),
        "decay_game_hours": int(getattr(item, "decay_game_hours", 0)),
        "remaining_game_hours": int(getattr(item, "remaining_game_hours", 0)),
        "decay_message": str(getattr(item, "decay_message", "")).strip(),
        "can_close": bool(getattr(item, "can_close", False)),
        "can_lock": bool(getattr(item, "can_lock", False)),
        "lock_id": str(getattr(item, "lock_id", "")).strip().lower(),
        "is_closed": bool(getattr(item, "is_closed", False)),
        "is_locked": bool(getattr(item, "is_locked", False)),
        "open_message": str(getattr(item, "open_message", "")).strip(),
        "close_message": str(getattr(item, "close_message", "")).strip(),
        "lock_message": str(getattr(item, "lock_message", "")).strip(),
        "unlock_message": str(getattr(item, "unlock_message", "")).strip(),
        "closed_message": str(getattr(item, "closed_message", "")).strip(),
        "locked_message": str(getattr(item, "locked_message", "")).strip(),
        "needs_key_message": str(getattr(item, "needs_key_message", "")).strip(),
        "must_close_to_lock_message": str(getattr(item, "must_close_to_lock_message", "")).strip(),
        "already_open_message": str(getattr(item, "already_open_message", "")).strip(),
        "already_closed_message": str(getattr(item, "already_closed_message", "")).strip(),
        "already_locked_message": str(getattr(item, "already_locked_message", "")).strip(),
        "already_unlocked_message": str(getattr(item, "already_unlocked_message", "")).strip(),
        "container_items": {
            nested_item_id: _serialize_item(nested_item)
            for nested_item_id, nested_item in getattr(item, "container_items", {}).items()
        },
    }


def _deserialize_item(raw: dict) -> ItemState:
    equippable = bool(raw.get("equippable", False))
    if not equippable and str(raw.get("slot", "")).strip():
        equippable = True

    raw_container_items = raw.get("container_items", {})
    if not isinstance(raw_container_items, dict):
        raw_container_items = {}

    return ItemState(
        item_id=str(raw.get("item_id", "")).strip(),
        template_id=str(raw.get("template_id", "")).strip(),
        name=str(raw.get("name", "")).strip() or "Item",
        description=str(raw.get("description", "")),
        keywords=[str(keyword) for keyword in raw.get("keywords", [])],
        equippable=equippable,
        slot=str(raw.get("slot", "")).strip().lower(),
        weapon_type=str(raw.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
        can_hold=bool(raw.get("can_hold", False)),
        can_two_hand=bool(raw.get("can_two_hand", False)),
        requires_two_hands=bool(raw.get("requires_two_hands", False)),
        weight=max(0, int(raw.get("weight", 0))),
        damage_dice_count=int(raw.get("damage_dice_count", 0)),
        damage_dice_sides=int(raw.get("damage_dice_sides", 0)),
        damage_roll_modifier=int(raw.get("damage_roll_modifier", 0)),
        hit_roll_modifier=int(raw.get("hit_roll_modifier", 0)),
        attack_damage_bonus=int(raw.get("attack_damage_bonus", 0)),
        attacks_per_round_bonus=int(raw.get("attacks_per_round_bonus", 0)),
        on_hit_room_damage_chance=float(raw.get("on_hit_room_damage_chance", 0.0) or 0.0),
        on_hit_room_damage_dice_count=int(raw.get("on_hit_room_damage_dice_count", 0)),
        on_hit_room_damage_dice_sides=int(raw.get("on_hit_room_damage_dice_sides", 0)),
        on_hit_room_damage_roll_modifier=int(raw.get("on_hit_room_damage_roll_modifier", 0)),
        on_hit_room_damage_message=str(raw.get("on_hit_room_damage_message", "")).strip(),
        on_hit_room_damage_observer_message=str(raw.get("on_hit_room_damage_observer_message", "")).strip(),
        on_hit_target_damage_chance=float(raw.get("on_hit_target_damage_chance", 0.0) or 0.0),
        on_hit_target_damage_dice_count=int(raw.get("on_hit_target_damage_dice_count", 0)),
        on_hit_target_damage_dice_sides=int(raw.get("on_hit_target_damage_dice_sides", 0)),
        on_hit_target_damage_roll_modifier=int(raw.get("on_hit_target_damage_roll_modifier", 0)),
        on_hit_target_damage_message=str(raw.get("on_hit_target_damage_message", "")).strip(),
        on_hit_target_damage_observer_message=str(raw.get("on_hit_target_damage_observer_message", "")).strip(),
        armor_class_bonus=int(raw.get("armor_class_bonus", 0)),
        equipment_effects=[
            {
                "effect_type": str(effect.get("effect_type", "")).strip().lower(),
                "amount": int(effect.get("amount", 0)),
            }
            for effect in (
                raw.get("equipment_effects", [])
                if isinstance(raw.get("equipment_effects", []), list)
                else []
            )
            if isinstance(effect, dict) and str(effect.get("effect_type", "")).strip()
        ],
        wear_slot=str(raw.get("wear_slot", "")).strip(),
        wear_slots=[str(slot).strip().lower() for slot in raw.get("wear_slots", []) if str(slot).strip()],
        item_type=str(raw.get("item_type", "misc")).strip().lower() or "misc",
        persistent=bool(raw.get("persistent", True)),
        lock_ids=[str(lock_id).strip().lower() for lock_id in raw.get("lock_ids", []) if str(lock_id).strip()],
        portable=bool(raw.get("portable", True)),
        coins=max(0, int(raw.get("coins", 0))),
        consume_on_use=bool(raw.get("consume_on_use", False)),
        consume_message=str(raw.get("consume_message", "")).strip(),
        decay_game_hours=max(0, int(raw.get("decay_game_hours", 0))),
        remaining_game_hours=max(0, int(raw.get("remaining_game_hours", 0))),
        decay_message=str(raw.get("decay_message", "")).strip(),
        can_close=bool(raw.get("can_close", False)),
        can_lock=bool(raw.get("can_lock", False)),
        lock_id=str(raw.get("lock_id", "")).strip().lower(),
        is_closed=bool(raw.get("is_closed", False)),
        is_locked=bool(raw.get("is_locked", False)),
        open_message=str(raw.get("open_message", "")).strip(),
        close_message=str(raw.get("close_message", "")).strip(),
        lock_message=str(raw.get("lock_message", "")).strip(),
        unlock_message=str(raw.get("unlock_message", "")).strip(),
        closed_message=str(raw.get("closed_message", "")).strip(),
        locked_message=str(raw.get("locked_message", "")).strip(),
        needs_key_message=str(raw.get("needs_key_message", "")).strip(),
        must_close_to_lock_message=str(raw.get("must_close_to_lock_message", "")).strip(),
        already_open_message=str(raw.get("already_open_message", "")).strip(),
        already_closed_message=str(raw.get("already_closed_message", "")).strip(),
        already_locked_message=str(raw.get("already_locked_message", "")).strip(),
        already_unlocked_message=str(raw.get("already_unlocked_message", "")).strip(),
        container_items={
            str(nested_item_id).strip(): _deserialize_item(nested_raw)
            for nested_item_id, nested_raw in raw_container_items.items()
            if str(nested_item_id).strip() and isinstance(nested_raw, dict)
        },
    )


def _serialize_affect(effect: ActiveAffectState) -> dict:
    return {
        "affect_id": effect.affect_id,
        "affect_name": effect.affect_name,
        "affect_descriptor": effect.affect_descriptor,
        "affect_mode": effect.affect_mode,
        "affect_type": effect.affect_type,
        "can_be_negative": bool(effect.can_be_negative),
        "affect_damage_elements": [
            str(element).strip().lower()
            for element in list(effect.affect_damage_elements or [])
            if str(element).strip()
        ],
        "target_resource": effect.target_resource,
        "affect_amount": float(effect.affect_amount),
        "affect_dice_count": int(effect.affect_dice_count),
        "affect_dice_sides": int(effect.affect_dice_sides),
        "affect_roll_modifier": float(effect.affect_roll_modifier),
        "affect_scaling_bonus": float(effect.affect_scaling_bonus),
        "extra_main_hand_hits": int(effect.extra_main_hand_hits),
        "extra_off_hand_hits": int(effect.extra_off_hand_hits),
        "extra_unarmed_hits": int(effect.extra_unarmed_hits),
        "hits_per_level_step": int(effect.hits_per_level_step),
        "level_step": int(effect.level_step),
        "remaining_hours": int(effect.remaining_hours),
        "remaining_rounds": int(effect.remaining_rounds),
    }


def _deserialize_affect(raw: dict) -> ActiveAffectState:
    raw_damage_elements = raw.get("affect_damage_elements", raw.get("affect_damage_element", []))
    if isinstance(raw_damage_elements, str):
        raw_damage_elements = [raw_damage_elements]
    if not isinstance(raw_damage_elements, list):
        raw_damage_elements = []

    return ActiveAffectState(
        affect_id=str(raw.get("affect_id", "")).strip(),
        affect_name=str(raw.get("affect_name", "")).strip(),
        affect_descriptor=str(raw.get("affect_descriptor", "")).strip(),
        affect_mode=str(raw.get("affect_mode", "timed")).strip().lower() or "timed",
        affect_type=str(raw.get("affect_type", "")).strip().lower(),
        can_be_negative=bool(raw.get("can_be_negative", False)),
        affect_damage_elements=[
            str(element).strip().lower()
            for element in raw_damage_elements
            if str(element).strip()
        ],
        target_resource=str(raw.get("target_resource", "hit_points")).strip().lower() or "hit_points",
        affect_amount=float(raw.get("affect_amount", 0.0)),
        affect_dice_count=max(0, int(raw.get("affect_dice_count", 0))),
        affect_dice_sides=max(0, int(raw.get("affect_dice_sides", 0))),
        affect_roll_modifier=float(raw.get("affect_roll_modifier", 0.0)),
        affect_scaling_bonus=float(raw.get("affect_scaling_bonus", 0.0)),
        extra_main_hand_hits=max(0, int(raw.get("extra_main_hand_hits", 0))),
        extra_off_hand_hits=max(0, int(raw.get("extra_off_hand_hits", 0))),
        extra_unarmed_hits=max(0, int(raw.get("extra_unarmed_hits", 0))),
        hits_per_level_step=max(0, int(raw.get("hits_per_level_step", 0))),
        level_step=max(0, int(raw.get("level_step", 0))),
        remaining_hours=max(0, int(raw.get("remaining_hours", 0))),
        remaining_rounds=max(0, int(raw.get("remaining_rounds", 0))),
    )


def _serialize_session(session: ClientSession) -> dict:
    return {
        "player": {
            "current_room_id": session.player.current_room_id,
            "class_id": session.player.class_id,
            "gender": normalize_player_gender(session.player.gender, allow_unspecified=True) or "unspecified",
            "attributes": {key: int(value) for key, value in session.player.attributes.items()},
            "level": int(session.player.level),
            "experience_points": int(session.player.experience_points),
            "resource_level_gains": {
                str(resource_key): int(value)
                for resource_key, value in dict(session.player.resource_level_gains or {}).items()
            },
            "interaction_flags": _normalize_interaction_flags(dict(session.player.interaction_flags or {})),
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
            "equipped_items": {
                item_id: _serialize_item(item)
                for item_id, item in session.equipment.equipped_items.items()
            },
            "equipped_main_hand_id": session.equipment.equipped_main_hand_id,
            "equipped_off_hand_id": session.equipment.equipped_off_hand_id,
            "worn_item_ids": dict(session.equipment.worn_item_ids),
        },
        "inventory_items": {
            item_id: _serialize_item(item)
            for item_id, item in session.inventory_items.items()
        },
        "known_spell_ids": list(session.known_spell_ids),
        "known_skill_ids": list(session.known_skill_ids),
        "known_passive_ids": list(session.known_passive_ids),
        "is_sitting": bool(session.is_sitting),
        "is_resting": bool(session.is_resting),
        "is_sleeping": bool(session.is_sleeping),
        "combat": {
            "skill_hour_cooldowns": {
                str(skill_id).strip(): max(0, int(remaining_hours))
                for skill_id, remaining_hours in dict(session.combat.skill_hour_cooldowns or {}).items()
                if str(skill_id).strip() and int(remaining_hours) > 0
            },
        },
        "active_affects": [_serialize_affect(effect) for effect in session.active_affects],
    }


def save_player_state(session: ClientSession, player_key: str | None = None) -> None:
    initialize_player_state_db()
    resolved_player_key = (player_key or session.player_state_key or DEFAULT_PLAYER_STATE_KEY).strip()
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
            (resolved_player_key, state_json, _utc_now_iso()),
        )
        connection.commit()


def clear_player_interaction_flags(flag_keys: list[str] | set[str] | tuple[str, ...]) -> int:
    normalized_flags = {
        str(flag_key).strip().lower()
        for flag_key in (flag_keys or [])
        if str(flag_key).strip()
    }
    if not normalized_flags:
        return 0

    initialize_player_state_db()
    updated_count = 0
    with _connect() as connection:
        rows = connection.execute("SELECT player_key, state_json FROM player_state").fetchall()
        for row in rows:
            raw_state = json.loads(str(row["state_json"]))
            if not isinstance(raw_state, dict):
                continue

            raw_player = raw_state.get("player", {})
            if not isinstance(raw_player, dict):
                continue

            raw_flags = raw_player.get("interaction_flags", {})
            if not isinstance(raw_flags, dict):
                continue

            updated_flags = {
                str(flag_key).strip().lower(): bool(flag_value)
                for flag_key, flag_value in raw_flags.items()
                if str(flag_key).strip() and bool(flag_value) and str(flag_key).strip().lower() not in normalized_flags
            }
            if len(updated_flags) == len(raw_flags):
                continue

            raw_player["interaction_flags"] = updated_flags
            raw_state["player"] = raw_player
            connection.execute(
                "UPDATE player_state SET state_json = ?, updated_at = ? WHERE player_key = ?",
                (json.dumps(raw_state, separators=(",", ":")), _utc_now_iso(), str(row["player_key"])),
            )
            updated_count += 1

        connection.commit()

    return updated_count


def load_player_state(session: ClientSession, player_key: str | None = None) -> bool:
    initialize_player_state_db()
    resolved_player_key = (player_key or session.player_state_key or DEFAULT_PLAYER_STATE_KEY).strip()

    with _connect() as connection:
        row = connection.execute(
            "SELECT state_json FROM player_state WHERE player_key = ?",
            (resolved_player_key,),
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
        session.player.gender = normalize_player_gender(
            raw_player.get("gender", session.player.gender),
            allow_unspecified=True,
        ) or "unspecified"
        session.player.experience_points = max(0, int(raw_player.get("experience_points", session.player.experience_points)))
        loaded_level = max(1, int(raw_player.get("level", 0)))
        derived_level = get_level_for_experience(session.player.experience_points)
        session.player.level = max(loaded_level, derived_level)
        raw_resource_level_gains = raw_player.get("resource_level_gains", {})
        if isinstance(raw_resource_level_gains, dict):
            session.player.resource_level_gains = {
                str(resource_key).strip().lower(): max(0, int(value))
                for resource_key, value in raw_resource_level_gains.items()
                if str(resource_key).strip()
            }
        raw_attributes = raw_player.get("attributes", {})
        if isinstance(raw_attributes, dict):
            session.player.attributes = {
                str(attribute_id).strip().lower(): int(value)
                for attribute_id, value in raw_attributes.items()
                if str(attribute_id).strip()
            }
        raw_interaction_flags = raw_player.get("interaction_flags", {})
        if isinstance(raw_interaction_flags, dict):
            session.player.interaction_flags = _normalize_interaction_flags(raw_interaction_flags)

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
        raw_equipped_items = raw_equipment.get("equipped_items", {})
        if isinstance(raw_equipped_items, dict):
            session.equipment.equipped_items = {
                str(item_id): _deserialize_item(raw_item)
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
    merged_inventory_items: dict[str, ItemState] = {}
    if isinstance(raw_inventory_items, dict):
        merged_inventory_items.update({
            str(item_id): _deserialize_item(raw_item)
            for item_id, raw_item in raw_inventory_items.items()
            if isinstance(raw_item, dict)
        })
    session.inventory_items = merged_inventory_items

    raw_known_spell_ids = raw_state.get("known_spell_ids", [])
    if isinstance(raw_known_spell_ids, list):
        session.known_spell_ids = [str(spell_id).strip() for spell_id in raw_known_spell_ids if str(spell_id).strip()]

    raw_known_skill_ids = raw_state.get("known_skill_ids", [])
    if isinstance(raw_known_skill_ids, list):
        session.known_skill_ids = [str(skill_id).strip() for skill_id in raw_known_skill_ids if str(skill_id).strip()]

    raw_known_passive_ids = raw_state.get("known_passive_ids", [])
    if isinstance(raw_known_passive_ids, list):
        session.known_passive_ids = [
            str(passive_id).strip()
            for passive_id in raw_known_passive_ids
            if str(passive_id).strip()
        ]

    session.is_sitting = bool(raw_state.get("is_sitting", False))
    session.is_resting = bool(raw_state.get("is_resting", False))
    session.is_sleeping = bool(raw_state.get("is_sleeping", False))

    raw_combat = raw_state.get("combat", {})
    if isinstance(raw_combat, dict):
        raw_skill_hour_cooldowns = raw_combat.get("skill_hour_cooldowns", {})
        if isinstance(raw_skill_hour_cooldowns, dict):
            session.combat.skill_hour_cooldowns = {
                str(skill_id).strip(): max(0, int(remaining_hours))
                for skill_id, remaining_hours in raw_skill_hour_cooldowns.items()
                if str(skill_id).strip() and int(remaining_hours) > 0
            }

    raw_affects = raw_state.get("active_affects", [])
    if isinstance(raw_affects, list):
        session.active_affects = [
            _deserialize_affect(raw_effect)
            for raw_effect in raw_affects
            if isinstance(raw_effect, dict)
        ]

    return True
