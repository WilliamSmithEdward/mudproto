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
    interaction_flags: dict[str, bool] = field(default_factory=dict)


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
    potion_cooldown_until: float = 0.0
    skill_hour_cooldowns: dict[str, int] = field(default_factory=dict)


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
class ActiveAffectState:
    affect_id: str
    affect_name: str
    affect_mode: str
    affect_type: str
    affect_damage_elements: list[str] = field(default_factory=list)
    target_resource: str = "hit_points"
    affect_amount: float = 0.0
    affect_dice_count: int = 0
    affect_dice_sides: int = 0
    affect_roll_modifier: float = 0.0
    affect_scaling_bonus: float = 0.0
    extra_main_hand_hits: int = 0
    extra_off_hand_hits: int = 0
    extra_unarmed_hits: int = 0
    hits_per_level_step: int = 0
    level_step: int = 0
    remaining_hours: int = 0
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
    on_hit_room_damage_chance: float = 0.0
    on_hit_room_damage_dice_count: int = 0
    on_hit_room_damage_dice_sides: int = 0
    on_hit_room_damage_roll_modifier: int = 0
    on_hit_room_damage_message: str = ""
    on_hit_room_damage_observer_message: str = ""
    on_hit_target_damage_chance: float = 0.0
    on_hit_target_damage_dice_count: int = 0
    on_hit_target_damage_dice_sides: int = 0
    on_hit_target_damage_roll_modifier: int = 0
    on_hit_target_damage_message: str = ""
    on_hit_target_damage_observer_message: str = ""
    armor_class_bonus: int = 0
    equipment_effects: list[dict[str, object]] = field(default_factory=list)
    wear_slot: str = ""
    wear_slots: list[str] = field(default_factory=list)
    item_type: str = "misc"
    persistent: bool = True
    lock_ids: list[str] = field(default_factory=list)
    portable: bool = True
    consume_on_use: bool = False
    consume_message: str = ""
    decay_game_hours: int = 0
    remaining_game_hours: int = 0
    decay_message: str = ""
    can_close: bool = False
    can_lock: bool = False
    lock_id: str = ""
    is_closed: bool = False
    is_locked: bool = False
    open_message: str = ""
    close_message: str = ""
    lock_message: str = ""
    unlock_message: str = ""
    closed_message: str = ""
    locked_message: str = ""
    needs_key_message: str = ""
    must_close_to_lock_message: str = ""
    already_open_message: str = ""
    already_closed_message: str = ""
    already_locked_message: str = ""
    already_unlocked_message: str = ""
    container_items: dict[str, "ItemState"] = field(default_factory=dict)


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
    is_named: bool = False
    corpse_label_style: str = "generic"
    coins: int = 0
    loot_items: dict[str, ItemState] = field(default_factory=dict)
    spawn_sequence: int = 0
    description: str = ""
    item_type: str = "container"
    portable: bool = False
    can_close: bool = False
    can_lock: bool = False
    lock_id: str = ""
    is_closed: bool = False
    is_locked: bool = False

    @property
    def name(self) -> str:
        from corpse_labels import build_corpse_label

        return build_corpse_label(
            self.source_name,
            self.corpse_label_style,
            is_named=bool(self.is_named),
        )

    @property
    def container_items(self) -> dict[str, ItemState]:
        return self.loot_items


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
    inventory_items: list[ItemState] = field(default_factory=list)
    is_alive: bool = True
    spawn_sequence: int = 0
    is_aggro: bool = False
    is_named: bool = False
    aggro_player_flags: list[str] = field(default_factory=list)
    set_player_flags_on_hostile_action: list[str] = field(default_factory=list)
    set_player_flags_on_death: list[str] = field(default_factory=list)
    set_world_flags_on_death: list[str] = field(default_factory=list)
    corpse_label_style: str = "generic"
    is_ally: bool = False
    is_peaceful: bool = False
    combat_target_player_key: str = ""
    respawn: bool = False
    is_merchant: bool = False
    merchant_inventory_template_ids: list[str] = field(default_factory=list)
    merchant_inventory: list[dict[str, object]] = field(default_factory=list)
    merchant_buy_markup: float = 1.0
    merchant_sell_ratio: float = 0.5
    merchant_restock_game_hours: int = 0
    merchant_restock_elapsed_hours: int = 0
    merchant_resale_items: dict[str, dict[str, object]] = field(default_factory=dict)
    pronoun_possessive: str = "its"
    main_hand_weapon_template_id: str = ""
    main_hand_weapon_drop_on_death: float = 0.0
    off_hand_weapon_template_id: str = ""
    off_hand_weapon_drop_on_death: float = 0.0
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
    active_affects: list[ActiveAffectState] = field(default_factory=list)
    is_sitting: bool = False
    is_resting: bool = False
    is_sleeping: bool = False
    wander_chance: float = 0.0
    wander_room_ids: list[str] = field(default_factory=list)


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
    known_passive_ids: list[str] = field(default_factory=list)
    active_support_effects: list[ActiveSupportEffectState] = field(default_factory=list)
    active_affects: list[ActiveAffectState] = field(default_factory=list)
    next_game_tick_monotonic: Optional[float] = None
    next_non_combat_battleround_tick_monotonic: Optional[float] = None
    is_authenticated: bool = False
    auth_stage: str = "awaiting_character_or_start"
    authenticated_character_name: str = ""
    player_state_key: str = ""
    pending_character_name: str = ""
    pending_password: str = ""
    pending_gender: str = ""
    failed_password_attempts: int = 0
    following_player_key: str = ""
    following_player_name: str = ""
    is_sitting: bool = False
    is_resting: bool = False
    is_sleeping: bool = False
    watch_player_key: str = ""
    watch_player_name: str = ""
    group_leader_key: str = ""
    group_member_keys: set[str] = field(default_factory=set)
    login_room_id: str = "start"
    is_connected: bool = True
    disconnected_by_server: bool = False
    pending_death_logout: bool = False
    pending_paged_displays: list[dict[str, object]] = field(default_factory=list)
