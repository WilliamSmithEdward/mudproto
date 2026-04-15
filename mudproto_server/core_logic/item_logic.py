"""Item and corpse display helpers plus misc item-use logic."""

import re

from attribute_config import load_item_usage_config
from assets import get_item_template_by_id, load_item_templates
from combat_ability_effects import _apply_ability_affects
from command_handlers.types import OutboundResult
from corpse_labels import build_corpse_label
from display_core import build_menu_table_parts, build_part, newline_part, parts_to_lines
from display_feedback import display_command_result, display_error
from grammar import indefinite_article, resolve_player_pronouns, with_article
from inventory import hydrate_misc_item_from_template, is_item_equippable
from models import ClientSession, ItemState
from player_resources import get_player_resource_caps
from session_timing import apply_lag
from settings import COMBAT_ROUND_INTERVAL_SECONDS
from targeting_items import _resolve_misc_inventory_selector



def _build_corpse_label(source_name: str, corpse_label_style: str = "generic", *, is_named: bool = False) -> str:
    return build_corpse_label(source_name, corpse_label_style, is_named=is_named)


def _item_highlight_color(item) -> str:
    return "bright_magenta" if is_item_equippable(item) else "bright_yellow"


def _build_item_reference_parts(item, *, fg: str | None = None) -> list[dict]:
    article, _, item_name = with_article(item.name).partition(" ")
    item_color = fg or _item_highlight_color(item)
    return [
        build_part(f"{article} ", "bright_white"),
        build_part(item_name or item.name, item_color, True),
    ]


def _display_corpse_examination(session: ClientSession, corpse) -> OutboundResult:
    from containers import display_container_examination

    return display_container_examination(session, corpse)


def _resolve_item_location_label(session: ClientSession, item: ItemState, *, default_label: str = "Inventory") -> str:
    if (
        session.equipment.equipped_main_hand_id == item.item_id
        and session.equipment.equipped_off_hand_id == item.item_id
    ):
        return "Both hands"
    if session.equipment.equipped_main_hand_id == item.item_id:
        return "Main hand"
    if session.equipment.equipped_off_hand_id == item.item_id:
        return "Off hand"

    for wear_slot, worn_item_id in session.equipment.worn_item_ids.items():
        if worn_item_id == item.item_id:
            return f"Worn on {wear_slot.replace('_', ' ')}"

    if item.item_id in session.inventory_items:
        return "Inventory"

    return default_label


def _resolve_item_kind_label(item: ItemState) -> str:
    if is_item_equippable(item):
        return "Weapon" if item.slot == "weapon" else "Armor"

    hydrate_misc_item_from_template(item)
    item_type = str(getattr(item, "item_type", "misc")).strip().lower()
    if item_type == "key":
        return "Key"
    if item_type == "consumable":
        return "Consumable"
    if item_type == "container":
        return "Container"
    return "Item"


def _format_item_wear_slots(item: ItemState) -> str:
    wear_slots = [str(slot).strip().lower() for slot in item.wear_slots if str(slot).strip()]
    if not wear_slots and str(item.wear_slot).strip():
        wear_slots = [str(item.wear_slot).strip().lower()]
    return ", ".join(slot.replace("_", " ").title() for slot in wear_slots)


def _display_item_examination(session: ClientSession, item: ItemState, *, default_location: str = "Inventory") -> OutboundResult:
    kind_label = _resolve_item_kind_label(item)
    location_label = _resolve_item_location_label(session, item, default_label=default_location)
    rows: list[list[str]] = [
        ["Type", kind_label],
        ["Location", location_label],
    ]

    if kind_label == "Weapon":
        weapon_type = str(getattr(item, "weapon_type", "") or "weapon").replace("_", " ").title()
        rows.append(["Weapon Type", weapon_type])
    elif kind_label == "Armor":
        wear_slot_label = _format_item_wear_slots(item)
        if wear_slot_label:
            rows.append(["Wear Slot", wear_slot_label])
    elif kind_label == "Container":
        rows.append(["Carryable", "Yes" if bool(getattr(item, "portable", True)) else "No"])
        rows.append(["Contents", str(len(getattr(item, "container_items", {})))])

    parts = build_menu_table_parts(
        str(getattr(item, "name", "Item")).strip() or "Item",
        ["Field", "Details"],
        rows,
        column_colors=["bright_cyan", "bright_white"],
        column_alignments=["left", "left"],
    )

    description = str(getattr(item, "description", "")).strip() or "No description is available for this item."
    parts.extend([
        newline_part(),
        build_part("Description", "bright_white", True),
        newline_part(),
        build_part(description, "bright_white"),
    ])

    return display_command_result(session, parts)


def _find_item_template_for_misc_item(misc_item) -> dict | None:
    template_id = str(getattr(misc_item, "template_id", "")).strip()
    if template_id:
        template = get_item_template_by_id(template_id)
        if template is not None:
            return template

    normalized_item_name = misc_item.name.strip().lower()
    if not normalized_item_name:
        return None

    item_tokens = {token for token in re.findall(r"[a-zA-Z0-9]+", normalized_item_name) if token}
    for template in load_item_templates():
        template_name = str(template.get("name", "")).strip().lower()
        if template_name == normalized_item_name:
            return template

        keywords = [str(keyword).strip().lower() for keyword in template.get("keywords", [])]
        if keywords and all(keyword in item_tokens for keyword in keywords):
            return template

    return None


def _is_potion_template(template: dict) -> bool:
    template_name = str(template.get("name", "")).strip().lower()
    keywords = {
        str(keyword).strip().lower()
        for keyword in template.get("keywords", [])
        if str(keyword).strip()
    }
    return "potion" in keywords or "potion" in template_name


def _get_potion_cooldown_rounds() -> int:
    config = load_item_usage_config()
    potion_config = config.get("potion", {}) if isinstance(config, dict) else {}
    if not isinstance(potion_config, dict):
        return 0
    return max(0, int(potion_config.get("cooldown_rounds", 0)))


def _use_misc_item(session: ClientSession, selector: str) -> OutboundResult:
    if not selector.strip():
        return display_error("Usage: use <item>", session)

    misc_item, resolve_error = _resolve_misc_inventory_selector(session, selector)
    if misc_item is None:
        return display_error(resolve_error or f"No inventory item matches '{selector}'.", session)

    template = _find_item_template_for_misc_item(misc_item)
    if template is None:
        return display_error(f"{misc_item.name} cannot be used.", session)

    hydrate_misc_item_from_template(misc_item, template)
    effect_type = str(template.get("effect_type", "restore")).strip().lower() or "restore"
    effect_target = str(template.get("effect_target", "")).strip().lower()
    effect_amount = max(0, int(template.get("effect_amount", 0)))
    affect_ids = template.get("affect_ids", []) if isinstance(template.get("affect_ids", []), list) else []
    use_lag_seconds = max(0.0, float(template.get("use_lag_seconds", 0.0)))

    has_restore = effect_type == "restore" and effect_amount > 0
    has_affects = bool(affect_ids)
    if not has_restore and not has_affects:
        return display_error(f"{misc_item.name} cannot be used.", session)

    is_potion = _is_potion_template(template)
    if is_potion:
        import time
        remaining = session.combat.potion_cooldown_until - time.monotonic()
        if remaining > 0:
            remaining_seconds = int(remaining) + 1
            return display_error(
                f"You must wait {remaining_seconds} more second(s) before using another potion.",
                session,
            )

    if has_restore:
        current_value = 0
        max_value = 0
        effect_label = ""
        caps = get_player_resource_caps(session)
        if effect_target == "hit_points":
            current_value = session.status.hit_points
            max_value = caps["hit_points"]
            effect_label = "HP"
        elif effect_target == "mana":
            current_value = session.status.mana
            max_value = caps["mana"]
            effect_label = "Mana"
        elif effect_target == "vigor":
            current_value = session.status.vigor
            max_value = caps["vigor"]
            effect_label = "Vigor"
        else:
            return display_error(f"{misc_item.name} cannot be used.", session)

        if current_value >= max_value and not has_affects:
            return display_error(f"Your {effect_label.lower()} is already full.", session)

        if current_value < max_value:
            restored_amount = min(effect_amount, max_value - current_value)
            setattr(session.status, effect_target, current_value + restored_amount)

    if has_affects:
        _apply_ability_affects(actor=session, target=session, ability=template, affect_target="self")

    session.inventory_items.pop(misc_item.item_id, None)

    if is_potion:
        cooldown_rounds = _get_potion_cooldown_rounds()
        if cooldown_rounds > 0:
            import time
            session.combat.potion_cooldown_until = time.monotonic() + cooldown_rounds * COMBAT_ROUND_INTERVAL_SECONDS

    if use_lag_seconds > 0:
        try:
            apply_lag(session, use_lag_seconds)
        except RuntimeError:
            pass

    item_name = misc_item.name.strip().lower() or "item"
    item_article = indefinite_article(item_name)

    observer_action = str(template.get("observer_action", "")).strip()
    observer_context = str(template.get("observer_context", "")).strip()
    actor_name = session.authenticated_character_name or "Someone"

    if not observer_action:
        observer_action = f"{actor_name} uses {item_article} {item_name}."

    actor_subject_pronoun, actor_object_pronoun, actor_possessive_pronoun, _ = resolve_player_pronouns(
        actor_name=actor_name,
        actor_gender=session.player.gender,
    )
    observer_action = (
        observer_action
        .replace("[actor_name]", actor_name)
        .replace("[actor_subject]", actor_subject_pronoun)
        .replace("[actor_object]", actor_object_pronoun)
        .replace("[actor_possessive]", actor_possessive_pronoun)
    )

    if observer_context:
        observer_context = (
            observer_context
            .replace("[actor_name]", actor_name)
            .replace("[actor_subject]", actor_subject_pronoun)
            .replace("[actor_object]", actor_object_pronoun)
            .replace("[actor_possessive]", actor_possessive_pronoun)
        )

    result = display_command_result(session, [
        build_part("You use ", "bright_white"),
        build_part(f"{item_article} {item_name}", "bright_yellow", True),
        build_part(".", "bright_white"),
    ])

    payload = result.get("payload")
    if isinstance(payload, dict):
        room_parts = [build_part(observer_action, "bright_white")]
        if observer_context:
            room_parts.extend([
                newline_part(1),
                build_part(observer_context, "bright_white"),
            ])
        payload["room_broadcast_lines"] = parts_to_lines(room_parts)

    return result
