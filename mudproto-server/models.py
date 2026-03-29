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
    class_id: str = ""


@dataclass
class PlayerCombatState:
    attack_damage: int = 12
    attacks_per_round: int = 1


@dataclass
class PlayerStatus:
    hit_points: int = 575
    vigor: int = 119
    mana: int = 160
    extra_lives: int = 1
    coins: int = 0


@dataclass
class CombatState:
    engaged_entity_id: Optional[str] = None
    next_round_monotonic: Optional[float] = None
    opening_attacker: Optional[str] = None
    skip_melee_rounds: int = 0


@dataclass
class ActiveSupportEffectState:
    spell_id: str
    spell_name: str
    support_mode: str
    support_effect: str
    support_amount: int
    remaining_hours: int
    remaining_rounds: int = 0


@dataclass
class EquipmentItemState:
    item_id: str
    template_id: str
    name: str
    slot: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    weapon_type: str = "unarmed"
    preferred_hand: str = "main_hand"
    damage_dice_count: int = 0
    damage_dice_sides: int = 0
    damage_roll_modifier: int = 0
    hit_roll_modifier: int = 0
    attack_damage_bonus: int = 0
    attacks_per_round_bonus: int = 0
    armor_class_bonus: int = 0
    wear_slot: str = ""


@dataclass
class EquipmentState:
    items: dict[str, EquipmentItemState] = field(default_factory=dict)
    equipped_items: dict[str, EquipmentItemState] = field(default_factory=dict)
    equipped_main_hand_id: Optional[str] = None
    equipped_off_hand_id: Optional[str] = None
    worn_item_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class LootItemState:
    item_id: str
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class CorpseState:
    corpse_id: str
    source_entity_id: str
    source_name: str
    room_id: str
    coins: int = 0
    loot_items: dict[str, LootItemState] = field(default_factory=dict)
    spawn_sequence: int = 0


@dataclass
class EntityState:
    entity_id: str
    name: str
    room_id: str
    hit_points: int
    max_hit_points: int
    attack_damage: int = 1
    attacks_per_round: int = 1
    hit_roll_modifier: int = 0
    armor_class: int = 10
    off_hand_attack_damage: int = 0
    off_hand_attacks_per_round: int = 0
    off_hand_hit_roll_modifier: int = 0
    off_hand_attack_verb: str = "hit"
    off_hand_weapon_name: str = "off-hand"
    coin_reward: int = 0
    loot_items: list[LootItemState] = field(default_factory=list)
    is_alive: bool = True
    spawn_sequence: int = 0
    is_aggro: bool = False
    is_ally: bool = False
    pronoun_possessive: str = "its"
    attack_verb: str = "hit"


def _build_default_equipment_state() -> EquipmentState:
    return EquipmentState()


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
    corpses: dict[str, CorpseState] = field(default_factory=dict)
    corpse_spawn_counter: int = 0
    room_coin_piles: dict[str, int] = field(default_factory=dict)
    room_ground_items: dict[str, dict[str, LootItemState]] = field(default_factory=dict)
    inventory_items: dict[str, LootItemState] = field(default_factory=dict)
    known_spell_ids: list[str] = field(default_factory=list)
    active_support_effects: list[ActiveSupportEffectState] = field(default_factory=list)
    next_game_tick_monotonic: Optional[float] = None
