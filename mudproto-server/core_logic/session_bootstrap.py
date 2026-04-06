import random
import uuid

from attribute_config import get_default_player_class, get_player_class_by_id, load_attributes
from assets import get_gear_template_by_id, get_item_template_by_id
from equipment import HAND_MAIN, HAND_OFF, equip_item, wear_item
from inventory import build_equippable_item_from_template, is_item_equippable
from models import ClientSession, ItemState
from player_resources import clamp_player_resources_to_caps, initialize_player_progression


def ensure_player_attributes(session: ClientSession) -> None:
    configured_attribute_ids = [
        str(attribute.get("attribute_id", "")).strip().lower()
        for attribute in load_attributes()
        if str(attribute.get("attribute_id", "")).strip()
    ]

    current_ranges: dict[str, dict[str, int]] = {}
    if session.player.class_id.strip():
        player_class = get_player_class_by_id(session.player.class_id)
        if player_class is not None:
            raw_ranges = player_class.get("attribute_ranges", {})
            if isinstance(raw_ranges, dict):
                for attribute_id in configured_attribute_ids:
                    raw_range = raw_ranges.get(attribute_id, {})
                    if isinstance(raw_range, dict):
                        current_ranges[attribute_id] = {
                            "min": int(raw_range.get("min", 0)),
                            "max": int(raw_range.get("max", 0)),
                        }

    merged: dict[str, int] = {}
    for attribute_id in configured_attribute_ids:
        if attribute_id in session.player.attributes:
            merged[attribute_id] = int(session.player.attributes[attribute_id])
            continue

        attribute_range = current_ranges.get(attribute_id)
        if attribute_range is None:
            merged[attribute_id] = 0
            continue

        merged[attribute_id] = int(attribute_range.get("min", 0))

    for attribute_id, value in session.player.attributes.items():
        if attribute_id in merged:
            continue
        merged[attribute_id] = int(value)

    session.player.attributes = merged


def _grant_starting_gear_from_template(session: ClientSession, template: dict) -> None:
    item = build_equippable_item_from_template(template)

    existing_template_ids = {
        inventory_item.template_id
        for inventory_item in session.inventory_items.values()
        if is_item_equippable(inventory_item)
    }
    existing_template_ids.update(equipped_item.template_id for equipped_item in session.equipment.equipped_items.values())
    if item.template_id in existing_template_ids:
        return

    session.inventory_items[item.item_id] = item


def _grant_starting_item_from_template(session: ClientSession, template: dict) -> None:
    template_id = str(template.get("template_id", "")).strip()
    if not template_id:
        return

    item = ItemState(
        item_id=f"item-{uuid.uuid4().hex[:8]}",
        template_id=template_id,
        name=str(template.get("name", "Item")).strip() or "Item",
        description=str(template.get("description", "")),
        keywords=[str(keyword).strip().lower() for keyword in template.get("keywords", []) if str(keyword).strip()],
    )
    session.inventory_items[item.item_id] = item


def _equip_starting_gear_by_template_id(session: ClientSession, template_id: str) -> None:
    normalized_template_id = template_id.strip().lower()
    if not normalized_template_id:
        return

    item: ItemState | None = None
    for inventory_item in session.inventory_items.values():
        if not is_item_equippable(inventory_item):
            continue
        if inventory_item.template_id.strip().lower() == normalized_template_id:
            item = inventory_item
            break

    if item is None:
        for equipped_item in session.equipment.equipped_items.values():
            if equipped_item.template_id.strip().lower() == normalized_template_id:
                return

        template = get_gear_template_by_id(template_id)
        if template is None:
            return
        item = build_equippable_item_from_template(template)
        session.inventory_items[item.item_id] = item

    if item.slot == "weapon":
        main_occupied = session.equipment.equipped_main_hand_id is not None
        target_hand = HAND_OFF if main_occupied else HAND_MAIN
        equip_item(session, item, target_hand)
        return

    if item.slot == "armor":
        wear_item(session, item)


def apply_player_class(
    session: ClientSession,
    class_id: str | None = None,
    *,
    roll_attributes: bool = False,
    initialize_progression: bool = False,
) -> None:
    player_class = get_default_player_class()
    if class_id is not None:
        matched_class = get_player_class_by_id(class_id)
        if matched_class is not None:
            player_class = matched_class

    session.player.class_id = str(player_class.get("class_id", "")).strip()

    if roll_attributes:
        raw_ranges = player_class.get("attribute_ranges", {})
        rolled_attributes: dict[str, int] = {}
        if isinstance(raw_ranges, dict):
            for attribute in load_attributes():
                attribute_id = str(attribute.get("attribute_id", "")).strip().lower()
                if not attribute_id:
                    continue

                raw_range = raw_ranges.get(attribute_id, {})
                if not isinstance(raw_range, dict):
                    continue

                min_value = int(raw_range.get("min", 0))
                max_value = int(raw_range.get("max", 0))
                rolled_attributes[attribute_id] = random.randint(min_value, max_value)

        session.player.attributes = rolled_attributes
    else:
        ensure_player_attributes(session)

    for template_id in player_class.get("starting_gear_template_ids", []):
        template = get_gear_template_by_id(str(template_id))
        if template is None:
            continue
        _grant_starting_gear_from_template(session, template)

    for template_id in player_class.get("starting_equipped_gear_template_ids", []):
        _equip_starting_gear_by_template_id(session, str(template_id))

    for template_id in player_class.get("starting_item_ids", []):
        template = get_item_template_by_id(str(template_id))
        if template is None:
            continue
        _grant_starting_item_from_template(session, template)

    known_spell_ids = {spell_id.strip().lower() for spell_id in session.known_spell_ids if spell_id.strip()}
    for spell_id in player_class.get("starting_spell_ids", []):
        normalized_spell_id = str(spell_id).strip().lower()
        if not normalized_spell_id or normalized_spell_id in known_spell_ids:
            continue
        session.known_spell_ids.append(str(spell_id).strip())
        known_spell_ids.add(normalized_spell_id)

    known_skill_ids = {skill_id.strip().lower() for skill_id in session.known_skill_ids if skill_id.strip()}
    for skill_id in player_class.get("starting_skill_ids", []):
        normalized_skill_id = str(skill_id).strip().lower()
        if not normalized_skill_id or normalized_skill_id in known_skill_ids:
            continue
        session.known_skill_ids.append(str(skill_id).strip())
        known_skill_ids.add(normalized_skill_id)

    if initialize_progression:
        initialize_player_progression(session)
    else:
        clamp_player_resources_to_caps(session)
