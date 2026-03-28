import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from websockets.asyncio.server import ServerConnection


@dataclass
class QueuedCommand:
    command_text: str
    received_at_iso: str


@dataclass
class PlayerState:
    current_room_id: str = "start"


@dataclass
class PlayerCombatState:
    attack_damage: int = 12
    attacks_per_round: int = 1


@dataclass
class PlayerStatus:
    hit_points: int = 575
    vigor: int = 119
    extra_lives: int = 1
    coins: int = 4030


@dataclass
class CombatState:
    engaged_entity_id: Optional[str] = None
    next_round_monotonic: Optional[float] = None
    opening_attacker: Optional[str] = None


@dataclass
class EquipmentItemState:
    item_id: str
    template_id: str
    name: str
    slot: str
    description: str = ""
    attack_damage_bonus: int = 0
    attacks_per_round_bonus: int = 0


@dataclass
class EquipmentState:
    items: dict[str, EquipmentItemState] = field(default_factory=dict)
    equipped_weapon_id: Optional[str] = None


@dataclass
class EntityState:
    entity_id: str
    name: str
    room_id: str
    hit_points: int
    max_hit_points: int
    attack_damage: int = 1
    attacks_per_round: int = 1
    coin_reward: int = 0
    is_alive: bool = True
    spawn_sequence: int = 0
    is_aggro: bool = False


def _build_default_equipment_state() -> EquipmentState:
    from assets import load_starting_equipment_templates

    items: dict[str, EquipmentItemState] = {}
    equipped_weapon_id: Optional[str] = None

    for template in load_starting_equipment_templates():
        item_id = f"item-{uuid.uuid4().hex[:8]}"
        item = EquipmentItemState(
            item_id=item_id,
            template_id=template["template_id"],
            name=template["name"],
            slot=template["slot"],
            description=template["description"],
            attack_damage_bonus=template["attack_damage_bonus"],
            attacks_per_round_bonus=template["attacks_per_round_bonus"],
        )
        items[item_id] = item

        if template["equip_on_grant"] and item.slot == "weapon" and equipped_weapon_id is None:
            equipped_weapon_id = item_id

    return EquipmentState(items=items, equipped_weapon_id=equipped_weapon_id)


@dataclass
class ClientSession:
    client_id: str
    websocket: ServerConnection
    connected_at: str
    player: PlayerState = field(default_factory=PlayerState)
    player_combat: PlayerCombatState = field(default_factory=PlayerCombatState)
    status: PlayerStatus = field(default_factory=PlayerStatus)
    combat: CombatState = field(default_factory=CombatState)
    equipment: EquipmentState = field(default_factory=_build_default_equipment_state)
    last_message_at: Optional[str] = None
    lag_until_monotonic: Optional[float] = None
    command_queue: list[QueuedCommand] = field(default_factory=list)
    scheduler_task: Optional[asyncio.Task] = None
    prompt_pending_after_lag: bool = False
    entities: dict[str, EntityState] = field(default_factory=dict)
    entity_spawn_counter: int = 0
