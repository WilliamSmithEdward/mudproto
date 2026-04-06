"""Thin shared surface for grouped command handlers.

This module re-exports the helpers and cross-module functions used by the
handler package so each handler can keep a small `from . import shared as s`
import style without duplicating implementation.
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
from commerce import (
    _append_item_to_merchant_stock,
    _build_inventory_item_from_template,
    _display_merchant_stock,
    _get_merchant_sale_offer,
    _remove_owned_trade_item,
    _resolve_merchant_stock_selector,
    _resolve_owned_trade_item,
    _resolve_room_merchant,
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
from equipment import (
    HAND_BOTH,
    HAND_MAIN,
    HAND_OFF,
    equip_item,
    get_equipped_main_hand,
    get_equipped_off_hand,
    list_worn_items,
    resolve_equipped_selector,
    unequip_item,
    wear_item,
)
from inventory import is_item_equippable, resolve_equipment_selector
from models import ClientSession, ItemState
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from sessions import apply_lag
from world import get_room

from abilities import (
    _list_known_skills,
    _list_known_spells,
    _resolve_skill_by_name,
    _resolve_spell_by_name,
)
from commands import (
    OutboundResult,
    _build_cost_menu_parts,
    display_score,
    flee,
    normalize_direction,
    parse_command,
    try_move,
)
from item_logic import (
    _build_corpse_label,
    _build_item_reference_parts,
    _display_corpse_examination,
    _display_item_examination,
    _item_highlight_color,
    _use_misc_item,
)
from targeting import (
    _add_item_to_room_ground,
    _clear_follow_state,
    _find_followed_player_session,
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
    _resolve_wear_inventory_selector,
    _would_create_follow_loop,
)
