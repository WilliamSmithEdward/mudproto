import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from websockets.asyncio.server import ServerConnection
from settings import PLAYER_REFERENCE_MAX_HP, PLAYER_REFERENCE_MAX_MANA, PLAYER_REFERENCE_MAX_VIGOR


@dataclass
class QueuedCommand:
    command_text: str
    received_at_iso: str


@dataclass
class PlayerState:
    current_room_id: str = "start"
    class_id: str = ""
    gender: str = "unspecified"
    attributes: dict[str, int] = field(default_factory=dict)
    level: int = 1
    experience_points: int = 0
    resource_level_gains: dict[str, int] = field(default_factory=dict)


@dataclass
class PlayerCombatState:
    attack_damage: int = 12
    attacks_per_round: int = 1


@dataclass
class PlayerStatus:
    hit_points: int = PLAYER_REFERENCE_MAX_HP
    vigor: int = PLAYER_REFERENCE_MAX_VIGOR
    mana: int = PLAYER_REFERENCE_MAX_MANA
    coins: int = 0


@dataclass
class CombatState:
    engaged_entity_ids: set[str] = field(default_factory=set)
    next_round_monotonic: Optional[float] = None
    opening_attacker: Optional[str] = None
    skip_melee_rounds: int = 0
    skill_cooldowns: dict[str, int] = field(default_factory=dict)
    item_cooldowns: dict[str, int] = field(default_factory=dict)


@dataclass
class ActiveSupportEffectState:
    spell_id: str
    spell_name: str
    support_mode: str
    support_effect: str
    support_amount: int
    remaining_hours: int
    support_dice_count: int = 0
    support_dice_sides: int = 0
    support_roll_modifier: int = 0
    support_scaling_bonus: int = 0
    remaining_rounds: int = 0


@dataclass
class ItemState:
    item_id: str
    template_id: str = ""
    name: str = "Item"
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    equippable: bool = False
    slot: str = ""
    weapon_type: str = "unarmed"
    can_hold: bool = False
    can_two_hand: bool = False
    requires_two_hands: bool = False
    weight: int = 0
    damage_dice_count: int = 0
    damage_dice_sides: int = 0
    damage_roll_modifier: int = 0
    hit_roll_modifier: int = 0
    attack_damage_bonus: int = 0
    attacks_per_round_bonus: int = 0
    armor_class_bonus: int = 0
    wear_slot: str = ""
    wear_slots: list[str] = field(default_factory=list)
@dataclass
class EquipmentState:
    equipped_items: dict[str, ItemState] = field(default_factory=dict)
    equipped_main_hand_id: Optional[str] = None
    equipped_off_hand_id: Optional[str] = None
    worn_item_ids: dict[str, str] = field(default_factory=dict)


InventoryItemState = ItemState


@dataclass
class CorpseState:
    corpse_id: str
    source_entity_id: str
    source_name: str
    room_id: str
    coins: int = 0
    loot_items: dict[str, ItemState] = field(default_factory=dict)
    spawn_sequence: int = 0


@dataclass
class EntityState:
    entity_id: str
    name: str
    room_id: str
    hit_points: int
    max_hit_points: int
    npc_id: str = ""
    power_level: int = 1
    attacks_per_round: int = 1
    hit_roll_modifier: int = 0
    armor_class: int = 10
    off_hand_attacks_per_round: int = 0
    off_hand_hit_roll_modifier: int = 0
    coin_reward: int = 0
    experience_reward: int = 0
    experience_contributor_keys: set[str] = field(default_factory=set)
    experience_reward_claimed: bool = False
    loot_items: list[ItemState] = field(default_factory=list)
    inventory_items: list[ItemState] = field(default_factory=list)
    is_alive: bool = True
    spawn_sequence: int = 0
    is_aggro: bool = False
    is_ally: bool = False
    is_peaceful: bool = False
    respawn: bool = False
    is_merchant: bool = False
    merchant_inventory_template_ids: list[str] = field(default_factory=list)
    merchant_inventory: list[dict[str, object]] = field(default_factory=list)
    merchant_buy_markup: float = 1.0
    merchant_sell_ratio: float = 0.5
    merchant_resale_items: dict[str, dict[str, object]] = field(default_factory=dict)
    pronoun_possessive: str = "its"
    main_hand_weapon_template_id: str = ""
    off_hand_weapon_template_id: str = ""
    vigor: int = 0
    max_vigor: int = 0
    mana: int = 0
    max_mana: int = 0
    skill_use_chance: float = 0.35
    skill_ids: list[str] = field(default_factory=list)
    skill_cooldowns: dict[str, int] = field(default_factory=dict)
    skill_lag_rounds_remaining: int = 0
    spell_use_chance: float = 0.25
    spell_ids: list[str] = field(default_factory=list)
    spell_cooldowns: dict[str, int] = field(default_factory=dict)
    spell_lag_rounds_remaining: int = 0
    active_support_effects: list[ActiveSupportEffectState] = field(default_factory=list)


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
    pending_private_lines: list[list[dict]] = field(default_factory=list)
    entities: dict[str, EntityState] = field(default_factory=dict)
    entity_spawn_counter: int = 0
    corpses: dict[str, CorpseState] = field(default_factory=dict)
    corpse_spawn_counter: int = 0
    room_coin_piles: dict[str, int] = field(default_factory=dict)
    room_ground_items: dict[str, dict[str, InventoryItemState]] = field(default_factory=dict)
    inventory_items: dict[str, InventoryItemState] = field(default_factory=dict)
    known_spell_ids: list[str] = field(default_factory=list)
    known_skill_ids: list[str] = field(default_factory=list)
    active_support_effects: list[ActiveSupportEffectState] = field(default_factory=list)
    next_game_tick_monotonic: Optional[float] = None
    next_non_combat_support_round_monotonic: Optional[float] = None
    is_authenticated: bool = False
    auth_stage: str = "awaiting_character_or_start"
    authenticated_character_name: str = ""
    player_state_key: str = ""
    pending_character_name: str = ""
    pending_password: str = ""
    pending_gender: str = ""
    following_player_key: str = ""
    following_player_name: str = ""
    login_room_id: str = "start"
    is_connected: bool = True
    disconnected_by_server: bool = False
    pending_death_logout: bool = False
