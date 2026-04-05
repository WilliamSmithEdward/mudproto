"""Thin shared surface for grouped command handlers.

This module intentionally re-exports the helpers and cross-module functions
used by the handler package so each handler can keep a small
`from . import shared as s` import style without duplicating the full command
implementation.
"""

import re

from attribute_config import load_attributes
from combat import (
    begin_attack,
    cast_spell,
    disengage,
    list_room_corpses,
    resolve_corpse_item_selector,
    resolve_room_corpse_selector,
    resolve_room_entity_selector,
    spawn_dummy,
    use_skill,
)
from display import (
    build_part,
    display_command_result,
    display_entity_summary,
    display_equipment,
    display_error,
    display_exits,
    display_inventory,
    display_player_summary,
    display_prompt,
    display_room,
)
from inventory import is_item_equippable, resolve_equipment_selector
from models import ClientSession, ItemState
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from sessions import apply_lag

from .commerce_helpers import (
    _append_item_to_merchant_stock,
    _build_inventory_item_from_template,
    _display_merchant_stock,
    _get_merchant_sale_offer,
    _remove_owned_trade_item,
    _resolve_merchant_stock_selector,
    _resolve_owned_trade_item,
    _resolve_room_merchant,
)
from commands import (
    HAND_BOTH,
    HAND_MAIN,
    HAND_OFF,
    OutboundResult,
    _add_item_to_room_ground,
    _build_corpse_label,
    _build_cost_menu_parts,
    _build_item_reference_parts,
    _clear_follow_state,
    _display_corpse_examination,
    _display_item_examination,
    _find_followed_player_session,
    _item_highlight_color,
    _list_known_skills,
    _list_known_spells,
    _list_room_ground_items,
    _normalize_item_look_selector,
    _parse_cast_spell,
    _parse_hand_and_selector,
    _parse_skill_use,
    _parse_wear_selector_and_location,
    _pickup_ground_item,
    _resolve_inventory_selector,
    _resolve_owned_item_selector,
    _resolve_room_ground_item_selector,
    _resolve_room_ground_matches,
    _resolve_room_player_selector,
    _resolve_skill_by_name,
    _resolve_spell_by_name,
    _resolve_wear_inventory_selector,
    _use_misc_item,
    _would_create_follow_loop,
    display_score,
    equip_item,
    flee,
    get_equipped_main_hand,
    get_equipped_off_hand,
    get_room,
    list_worn_items,
    normalize_direction,
    parse_command,
    resolve_equipped_selector,
    try_move,
    unequip_item,
    wear_item,
)
