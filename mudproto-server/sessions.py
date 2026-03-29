import asyncio
import uuid

from assets import get_default_player_class, get_equipment_template_by_id
from models import ClientSession, QueuedCommand
from protocol import utc_now_iso


MAX_QUEUED_COMMANDS = 5

connected_clients: dict[str, ClientSession] = {}


def _grant_starting_equipment_from_template(session: ClientSession, template: dict) -> None:
    existing_template_ids = {item.template_id for item in session.equipment.items.values()}
    template_id = str(template.get("template_id", "")).strip()
    if not template_id or template_id in existing_template_ids:
        return

    item_id = f"item-{uuid.uuid4().hex[:8]}"
    from models import EquipmentItemState
    item = EquipmentItemState(
        item_id=item_id,
        template_id=template_id,
        name=str(template.get("name", "Item")).strip() or "Item",
        slot=str(template.get("slot", "")).strip(),
        description=str(template.get("description", "")),
        keywords=list(template.get("keywords", [])),
        weapon_type=str(template.get("weapon_type", "unarmed")).strip().lower() or "unarmed",
        preferred_hand=str(template.get("preferred_hand", "main_hand")).strip().lower() or "main_hand",
        damage_dice_count=int(template.get("damage_dice_count", 0)),
        damage_dice_sides=int(template.get("damage_dice_sides", 0)),
        damage_roll_modifier=int(template.get("damage_roll_modifier", 0)),
        hit_roll_modifier=int(template.get("hit_roll_modifier", 0)),
        attack_damage_bonus=int(template.get("attack_damage_bonus", 0)),
        attacks_per_round_bonus=int(template.get("attacks_per_round_bonus", 0)),
    )
    session.equipment.items[item_id] = item

    if bool(template.get("equip_on_grant", False)) and item.slot == "weapon":
        if item.preferred_hand == "off_hand" and session.equipment.equipped_off_hand_id is None:
            session.equipment.equipped_off_hand_id = item_id
        elif session.equipment.equipped_main_hand_id is None:
            session.equipment.equipped_main_hand_id = item_id


def _apply_default_player_class(session: ClientSession) -> None:
    player_class = get_default_player_class()
    session.player.class_id = str(player_class.get("class_id", "")).strip()

    for template_id in player_class.get("starting_equipment_template_ids", []):
        template = get_equipment_template_by_id(str(template_id))
        if template is None:
            continue
        _grant_starting_equipment_from_template(session, template)

    known_spell_ids = {spell_id.strip().lower() for spell_id in session.known_spell_ids if spell_id.strip()}
    for spell_id in player_class.get("starting_spell_ids", []):
        normalized_spell_id = str(spell_id).strip().lower()
        if not normalized_spell_id or normalized_spell_id in known_spell_ids:
            continue
        session.known_spell_ids.append(str(spell_id).strip())
        known_spell_ids.add(normalized_spell_id)


def get_connection_count() -> int:
    return len(connected_clients)


def register_client(client_id: str, websocket) -> ClientSession:
    session = ClientSession(
        client_id=client_id,
        websocket=websocket,
        connected_at=utc_now_iso()
    )
    _apply_default_player_class(session)
    connected_clients[client_id] = session
    return session


def unregister_client(client_id: str) -> None:
    connected_clients.pop(client_id, None)


def touch_session(session: ClientSession) -> None:
    session.last_message_at = utc_now_iso()


def is_session_lagged(session: ClientSession) -> bool:
    if session.lag_until_monotonic is None:
        return False

    return asyncio.get_running_loop().time() < session.lag_until_monotonic


def get_remaining_lag_seconds(session: ClientSession) -> float:
    if session.lag_until_monotonic is None:
        return 0.0

    remaining = session.lag_until_monotonic - asyncio.get_running_loop().time()
    return max(0.0, remaining)


def apply_lag(session: ClientSession, duration_seconds: float) -> None:
    if duration_seconds <= 0:
        return

    now = asyncio.get_running_loop().time()
    base = max(now, session.lag_until_monotonic or now)
    session.lag_until_monotonic = base + duration_seconds


def enqueue_command(session: ClientSession, command_text: str) -> tuple[bool, str]:
    if len(session.command_queue) >= MAX_QUEUED_COMMANDS:
        return False, "Command queue is full."

    session.command_queue.append(QueuedCommand(
        command_text=command_text,
        received_at_iso=utc_now_iso()
    ))
    return True, "Command queued."