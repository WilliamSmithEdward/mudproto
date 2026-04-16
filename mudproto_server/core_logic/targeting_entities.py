"""Room entity and corpse resolution helpers."""

import re

from corpse_labels import build_corpse_label
from models import ClientSession, CorpseState, EntityState, ItemState

from targeting_parsing import _selector_prefix_matches_keywords


def list_room_entities(session: ClientSession, room_id: str) -> list[EntityState]:
    entities: list[EntityState] = []

    for entity in session.entities.values():
        if entity.is_alive and entity.room_id == room_id:
            entities.append(entity)

    entities.sort(key=lambda item: item.spawn_sequence, reverse=True)
    return entities


def list_room_corpses(session: ClientSession, room_id: str) -> list[CorpseState]:
    corpses: list[CorpseState] = []

    for corpse in session.corpses.values():
        if corpse.room_id == room_id:
            corpses.append(corpse)

    corpses.sort(key=lambda item: item.spawn_sequence, reverse=True)
    return corpses


def _entity_name_keywords(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]+", name.lower()) if token}


def _build_corpse_label(source_name: str, corpse_label_style: str = "generic", *, is_named: bool = False) -> str:
    return build_corpse_label(source_name, corpse_label_style, is_named=is_named)


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
    require_exact_name: bool = False,
) -> tuple[EntityState | None, str | None]:
    normalized = selector_text.strip().lower()
    if not normalized:
        return None, "Provide a target selector."

    all_room_entities = [
        entity
        for entity in session.entities.values()
        if entity.room_id == room_id
    ]
    all_room_entities.sort(key=lambda item: item.spawn_sequence, reverse=True)

    room_entities = [
        entity
        for entity in all_room_entities
        if entity.is_alive or not living_only
    ]

    if require_exact_name:
        exact_entity: EntityState | None = None
        for entity in all_room_entities:
            if entity.name.lower() == normalized:
                exact_entity = entity
                break
        if exact_entity is not None:
            if living_only and not exact_entity.is_alive:
                return None, f"{exact_entity.name} is already dead."
            return exact_entity, None

        # Explicit targeting can also use exact whole keywords (for example:
        # "sentry" or "2.scout"), but never prefix matching.
        requested_index: int | None = None
        selector_parts: list[str]
        if "." in normalized:
            selector_parts = [part for part in normalized.split(".") if part]
            if selector_parts and selector_parts[0].isdigit():
                requested_index = int(selector_parts[0])
                selector_parts = selector_parts[1:]
                if requested_index <= 0:
                    return None, "Selector index must be 1 or greater."
            if not selector_parts:
                return None, "Provide at least one selector keyword after the index."
        else:
            selector_parts = [normalized]

        all_token_matches: list[EntityState] = []
        for entity in all_room_entities:
            keywords = _entity_name_keywords(entity.name)
            if all(part in keywords for part in selector_parts):
                all_token_matches.append(entity)

        token_matches: list[EntityState] = []
        for entity in room_entities:
            keywords = _entity_name_keywords(entity.name)
            if all(part in keywords for part in selector_parts):
                token_matches.append(entity)

        if not token_matches:
            if living_only and requested_index is not None and requested_index <= len(all_token_matches):
                indexed_target = all_token_matches[requested_index - 1]
                if not indexed_target.is_alive:
                    return None, f"{indexed_target.name} is already dead."
            return None, f"No exact target named '{selector_text}' is here."

        if requested_index is not None:
            if requested_index > len(token_matches):
                return None, f"Only {len(token_matches)} exact match(es) found for '{selector_text}'."
            return token_matches[requested_index - 1], None

        if len(token_matches) == 1:
            return token_matches[0], None

        # On ambiguous exact-token matches, default to the first in spawn order.
        return token_matches[0], None

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
            corpse_names = {
                _build_corpse_label(
                    corpse.source_name,
                    getattr(corpse, "corpse_label_style", "generic"),
                    is_named=bool(getattr(corpse, "is_named", False)),
                ).lower(),
                f"{corpse.source_name} corpse".lower(),
            }
            if normalized in corpse_names:
                exact_match = corpse
                break
            if any(normalized in corpse_name for corpse_name in corpse_names) and partial_match is None:
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

    items = list(reversed(list(corpse.loot_items.values())))
    if not items:
        return None, "That corpse has no lootable items."

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
