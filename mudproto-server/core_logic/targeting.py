"""Selector parsing and target resolution helpers for commands."""

import re

from abilities import _list_known_skills, _list_known_spells, _resolve_skill_by_name, _resolve_spell_by_name
from equipment import HAND_BOTH, HAND_MAIN, HAND_OFF, list_worn_items, resolve_wear_slot_alias
from inventory import get_item_keywords, is_item_equippable, parse_item_selector
from models import ClientSession, CorpseState, EntityState, ItemState
from session_registry import connected_clients, list_authenticated_room_players


def _parse_hand_and_selector(args: list[str]) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, "Usage: equip <selector> [main|off|both]"

    normalized = [arg.strip().lower() for arg in args if arg.strip()]
    hand_aliases = {
        "main": HAND_MAIN,
        "mainhand": HAND_MAIN,
        "main_hand": HAND_MAIN,
        "off": HAND_OFF,
        "offhand": HAND_OFF,
        "off_hand": HAND_OFF,
        "both": HAND_BOTH,
        "2h": HAND_BOTH,
        "twohand": HAND_BOTH,
        "twohands": HAND_BOTH,
        "two_hand": HAND_BOTH,
        "two_hands": HAND_BOTH,
    }

    hand: str | None = None
    selector_parts: list[str] = []
    for token in normalized:
        mapped_hand = hand_aliases.get(token)
        if mapped_hand is not None:
            hand = mapped_hand
            continue
        selector_parts.append(token)

    selector = ".".join(selector_parts).strip(".")
    if not selector:
        return None, None, "Usage: equip <selector> [main|off|both]"

    return hand, selector, None


def _parse_wear_selector_and_location(args: list[str]) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, "Usage: wear <selector> [location]"

    normalized = [arg.strip().lower() for arg in args if arg.strip()]
    if not normalized:
        return None, None, "Usage: wear <selector> [location]"

    selector_tokens = normalized
    wear_location: str | None = None
    for suffix_len in (2, 1):
        if len(normalized) <= suffix_len:
            continue
        candidate_suffix = normalized[-suffix_len:]
        candidate_location = resolve_wear_slot_alias(" ".join(candidate_suffix))
        if candidate_location is None:
            continue
        wear_location = candidate_location
        selector_tokens = normalized[:-suffix_len]
        break

    selector = ".".join(selector_tokens).strip(".")
    if not selector:
        return None, None, "Usage: wear <selector> [location]"

    return selector, wear_location, None


def _parse_cast_spell(
    command_text: str,
    args: list[str],
    verb: str,
) -> tuple[str | None, str | None, str | None]:
    escaped_verb = re.escape(verb.strip())
    quoted_match = re.match(
        rf"^{escaped_verb}\s+(['\"])(.+?)\1(?:\s+(.+))?\s*$",
        command_text.strip(),
        re.IGNORECASE,
    )
    if quoted_match is not None:
        spell_name = quoted_match.group(2).strip()
        target_name = (quoted_match.group(3) or "").strip() or None
        if spell_name:
            return spell_name, target_name, None

    spell_name = " ".join(args).strip()
    if len(spell_name) >= 2 and spell_name[0] in {"'", '"'} and spell_name[-1] == spell_name[0]:
        spell_name = spell_name[1:-1].strip()

    if not spell_name:
        return None, None, "Usage: cast 'spell name' [target]"

    return spell_name, None, None


def _parse_skill_use(args: list[str]) -> tuple[str | None, str | None, str | None]:
    skill_name = " ".join(args).strip()
    if not skill_name:
        return None, None, "Usage: <skill> [target]"

    return skill_name, None, None


def _normalize_item_look_selector(selector_text: str) -> tuple[str, bool]:
    cleaned = re.sub(r"\s+", " ", selector_text.strip())
    lowered = cleaned.lower()

    if lowered.startswith("at "):
        cleaned = cleaned[3:].strip()
        lowered = cleaned.lower()

    search_room = False
    for suffix in (" in the room", " in room", " on the ground", " on ground"):
        if lowered.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()
            search_room = True
            break

    return cleaned, search_room


def _resolve_owned_item_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None, str | None]:
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, None, parse_error

    candidates: list[tuple[int, str, ItemState]] = []
    seen_item_ids: set[str] = set()

    for location_label, item in list_worn_items(session):
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((0, str(location_label).strip() or "equipped", item))

    for item in session.inventory_items.values():
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        candidates.append((1, "inventory", item))

    candidates.sort(key=lambda entry: (entry[0], entry[2].name.lower(), entry[2].item_id))

    matches: list[tuple[ItemState, str]] = []
    for _, location_label, item in candidates:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append((item, location_label))

    if not matches:
        return None, None, f"You are not carrying or wearing anything matching '{selector}'."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, None, f"Only {len(matches)} match(es) found for '{selector}'."
        selected_item, location_label = matches[requested_index - 1]
        return selected_item, location_label, None

    selected_item, location_label = matches[0]
    return selected_item, location_label, None


def _resolve_room_ground_item_selector(session: ClientSession, room_id: str, selector: str) -> tuple[ItemState | None, str | None]:
    matches, requested_index, selector_error = _resolve_room_ground_matches(session, room_id, selector)
    if selector_error is not None:
        return None, selector_error

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _selector_prefix_matches_keywords(parts: list[str], keywords: set[str]) -> bool:
    if not parts or not keywords:
        return False
    return all(any(keyword.startswith(part) for keyword in keywords) for part in parts)


def _resolve_room_player_selector(session: ClientSession, selector_text: str) -> tuple[ClientSession | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    if normalized in {"me", "self", "myself"}:
        return session, None

    room_players = list_authenticated_room_players(session.player.current_room_id)
    if not room_players:
        return None, f"No player named '{selector_text}' is here."

    query_parts = [part for part in re.findall(r"[a-zA-Z0-9]+", normalized) if part]

    if "." not in normalized:
        exact_match: ClientSession | None = None
        partial_match: ClientSession | None = None
        for player_session in room_players:
            player_name = (player_session.authenticated_character_name or "").strip().lower()
            if not player_name:
                continue

            if player_name == normalized:
                exact_match = player_session
                break

            player_keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
            if _selector_prefix_matches_keywords(query_parts, player_keywords) and partial_match is None:
                partial_match = player_session

        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No player named '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a target selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[ClientSession] = []
    for player_session in room_players:
        player_name = (player_session.authenticated_character_name or "").strip().lower()
        keywords = {token for token in re.findall(r"[a-zA-Z0-9]+", player_name) if token}
        if _selector_prefix_matches_keywords(parts, keywords):
            matches.append(player_session)

    if not matches:
        return None, f"No player named '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} player match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _clear_follow_state(session: ClientSession) -> None:
    session.following_player_key = ""
    session.following_player_name = ""


def _find_followed_player_session(session: ClientSession) -> ClientSession | None:
    normalized_key = (session.following_player_key or "").strip().lower()
    if not normalized_key:
        return None

    for candidate in connected_clients.values():
        if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
            continue
        candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
        if candidate_key == normalized_key:
            return candidate
    return None


def _would_create_follow_loop(session: ClientSession, target_session: ClientSession) -> bool:
    follower_key = (session.player_state_key or session.client_id).strip().lower()
    if not follower_key:
        return False

    seen_keys: set[str] = {follower_key}
    current: ClientSession | None = target_session
    while current is not None:
        current_key = (current.player_state_key or current.client_id).strip().lower()
        if not current_key:
            return False
        if current_key in seen_keys:
            return True

        seen_keys.add(current_key)
        next_key = (current.following_player_key or "").strip().lower()
        if not next_key:
            return False

        current = None
        for candidate in connected_clients.values():
            if not candidate.is_connected or candidate.disconnected_by_server or not candidate.is_authenticated:
                continue
            candidate_key = (candidate.player_state_key or candidate.client_id).strip().lower()
            if candidate_key == next_key:
                current = candidate
                break

    return False


def _resolve_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    inventory_items = list(session.inventory_items.values())
    inventory_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in inventory_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_misc_inventory_selector(session: ClientSession, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return None, parse_error

    misc_items = [item for item in session.inventory_items.values() if not is_item_equippable(item)]
    misc_items.sort(key=lambda item: item.name.lower())

    matches = []
    for item in misc_items:
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return None, f"{selector} doesn't exist in inventory."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} match(es) found for '{selector}'."
        return matches[requested_index - 1], None

    return matches[0], None


def _resolve_wear_inventory_selector(session: ClientSession, selector: str) -> tuple[ItemState | None, str | None]:
    selected_item, resolve_error = _resolve_inventory_selector(session, selector)
    if selected_item is None:
        return None, resolve_error
    if not is_item_equippable(selected_item):
        return None, f"{selected_item.name} cannot be worn."
    return selected_item, None


def _list_room_ground_items(session: ClientSession, room_id: str):
    room_items = list(session.room_ground_items.get(room_id, {}).values())
    room_items.sort(key=lambda item: (item.name.lower(), item.item_id))
    return room_items


def _resolve_room_ground_matches(session: ClientSession, room_id: str, selector: str):
    requested_index, keywords, parse_error = parse_item_selector(selector)
    if parse_error is not None:
        return [], None, parse_error

    matches = []
    for item in _list_room_ground_items(session, room_id):
        item_keywords = get_item_keywords(item)
        if all(keyword in item_keywords for keyword in keywords):
            matches.append(item)

    if not matches:
        return [], requested_index, f"No room item matches '{selector}'."

    return matches, requested_index, None


def _add_item_to_room_ground(session: ClientSession, room_id: str, item) -> None:
    room_items = session.room_ground_items.setdefault(room_id, {})
    room_items[item.item_id] = item


def _pickup_ground_item(session: ClientSession, room_id: str, item) -> None:
    session.room_ground_items.get(room_id, {}).pop(item.item_id, None)
    session.inventory_items[item.item_id] = item


def list_room_entities(session: ClientSession, room_id: str) -> list[EntityState]:
    entities: list[EntityState] = []

    for entity in session.entities.values():
        if entity.is_alive and entity.room_id == room_id:
            entities.append(entity)

    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def list_room_corpses(session: ClientSession, room_id: str) -> list[CorpseState]:
    corpses: list[CorpseState] = []

    for corpse in session.corpses.values():
        if corpse.room_id == room_id:
            corpses.append(corpse)

    corpses.sort(key=lambda item: item.spawn_sequence)
    return corpses


def _entity_name_keywords(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", name.lower()) if token}


def _corpse_keywords(corpse: CorpseState) -> set[str]:
    keywords = _entity_name_keywords(corpse.source_name)
    keywords.add("corpse")
    return keywords


def _corpse_item_keywords(item: ItemState) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", item.name.lower()) if token}


def resolve_room_entity_selector(
    session: ClientSession,
    room_id: str,
    selector_text: str,
    *,
    living_only: bool = False,
) -> tuple[EntityState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    all_room_entities = [
        entity
        for entity in session.entities.values()
        if entity.room_id == room_id
    ]
    all_room_entities.sort(key=lambda item: item.spawn_sequence)

    room_entities = [
        entity
        for entity in all_room_entities
        if entity.is_alive or not living_only
    ]

    query_parts = [part for part in re.findall(r"[a-zA-Z0-9]+", normalized) if part]

    if "." not in normalized:
        exact_match: EntityState | None = None
        partial_match: EntityState | None = None
        for entity in room_entities:
            entity_name = entity.name.lower()
            if entity_name == normalized:
                exact_match = entity
                break
            if _selector_prefix_matches_keywords(query_parts, _entity_name_keywords(entity.name)) and partial_match is None:
                partial_match = entity
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No target named '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a target selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    all_matches: list[EntityState] = []
    for entity in all_room_entities:
        keywords = _entity_name_keywords(entity.name)
        if _selector_prefix_matches_keywords(parts, keywords):
            all_matches.append(entity)

    matches: list[EntityState] = []
    for entity in room_entities:
        keywords = _entity_name_keywords(entity.name)
        if _selector_prefix_matches_keywords(parts, keywords):
            matches.append(entity)

    if not matches:
        if living_only and all_matches:
            return None, "All matching targets are dead."
        return None, f"No target named '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            if living_only and requested_index <= len(all_matches):
                indexed_target = all_matches[requested_index - 1]
                if not indexed_target.is_alive:
                    return None, f"{indexed_target.name} is already dead."
            living_label = " living" if living_only else ""
            return None, f"Only {len(matches)}{living_label} match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def resolve_room_corpse_selector(
    session: ClientSession,
    room_id: str,
    selector_text: str,
) -> tuple[CorpseState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a corpse selector."

    room_corpses = list_room_corpses(session, room_id)
    if not room_corpses:
        return None, "There are no corpses here."

    if "." not in normalized:
        if normalized == "corpse":
            return room_corpses[0], None

        exact_match: CorpseState | None = None
        partial_match: CorpseState | None = None
        for corpse in room_corpses:
            corpse_name = f"{corpse.source_name} corpse".lower()
            if corpse_name == normalized:
                exact_match = corpse
                break
            if normalized in corpse_name and partial_match is None:
                partial_match = corpse
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No corpse matching '{selector_text}' is here."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide a corpse selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[CorpseState] = []
    for corpse in room_corpses:
        keywords = _corpse_keywords(corpse)
        if all(keyword in keywords for keyword in parts):
            matches.append(corpse)

    if not matches:
        return None, f"No corpse matching '{selector_text}' is here."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} corpse match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def resolve_corpse_item_selector(corpse: CorpseState, selector_text: str) -> tuple[ItemState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide an item selector."

    items = list(corpse.loot_items.values())
    if not items:
        return None, "That corpse has no lootable items."

    items.sort(key=lambda item: item.name.lower())

    if "." not in normalized:
        exact_match: ItemState | None = None
        partial_match: ItemState | None = None
        for item in items:
            item_name = item.name.lower()
            if item_name == normalized:
                exact_match = item
                break
            if normalized in item_name and partial_match is None:
                partial_match = item
        if exact_match is not None:
            return exact_match, None
        if partial_match is not None:
            return partial_match, None
        return None, f"No item matching '{selector_text}' is on that corpse."

    parts = [part for part in normalized.split(".") if part]
    if not parts:
        return None, "Provide an item selector."

    requested_index: int | None = None
    if parts[0].isdigit():
        requested_index = int(parts[0])
        parts = parts[1:]
        if requested_index <= 0:
            return None, "Selector index must be 1 or greater."

    if not parts:
        return None, "Provide at least one selector keyword after the index."

    matches: list[ItemState] = []
    for item in items:
        keywords = _corpse_item_keywords(item)
        if all(keyword in keywords for keyword in parts):
            matches.append(item)

    if not matches:
        return None, f"No item matching '{selector_text}' is on that corpse."

    if requested_index is not None:
        if requested_index > len(matches):
            return None, f"Only {len(matches)} item match(es) found for '{selector_text}'."
        return matches[requested_index - 1], None

    return matches[0], None


def find_room_entity_by_name(session: ClientSession, room_id: str, search_text: str) -> EntityState | None:
    entity, _ = resolve_room_entity_selector(session, room_id, search_text, living_only=True)
    return entity
