from assets import get_npc_template_by_id
from companions import (
    companion_roster_has_capacity,
    list_owned_companions_for_session,
    pick_voice_line,
    remove_companion_roster_entry,
    resolve_room_recruiter,
    session_has_companion_npc,
    spawn_companion_for_session,
)
from display_core import build_menu_table_parts, build_part, newline_part
from display_feedback import display_command_result, display_error
from models import ClientSession, EntityState
from player_state_db import save_player_state
from session_registry import shared_world_entities
from settings import MAX_COMPANIONS_PER_PLAYER

from .types import OutboundResult


HandledResult = OutboundResult | None

# Prefixes start at three letters: "re" belongs to the posture handler (rest)
# and two-letter forms would shadow it in the dispatch waterfall.
_RECRUIT_MENU_VERBS = {"rec", "recr", "recru", "recrui", "recruit", "recruits"}
_ENLIST_VERBS = {"enl", "enli", "enlis", "enlist"}
_DISMISS_VERBS = {"dis", "dism", "dismi", "dismis", "dismiss"}


def _resolve_recruit_entries(recruiter: EntityState) -> list[dict]:
    entries: list[dict] = []
    for recruit_entry in getattr(recruiter, "recruitable_companions", []):
        if not isinstance(recruit_entry, dict):
            continue
        npc_id = str(recruit_entry.get("npc_id", "")).strip()
        template = get_npc_template_by_id(npc_id)
        if template is None or not bool(template.get("is_companion", False)):
            continue
        if bool(template.get("is_guardian", False)):
            role = "Guardian"
        elif template.get("spell_ids"):
            role = "Caster"
        else:
            role = "Fighter"
        entries.append({
            "npc_id": npc_id,
            "name": str(template.get("name", "")).strip() or npc_id,
            "role": role,
            "price": max(1, int(recruit_entry.get("price", 1))),
        })
    return entries


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous_row = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current_row[right_index - 1] + 1
            delete_cost = previous_row[right_index] + 1
            substitute_cost = previous_row[right_index - 1] + (0 if left_char == right_char else 1)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        previous_row = current_row
    return previous_row[-1]


def _match_name_index(names: list[str], selector_text: str) -> int | None:
    """Match a typed selector against companion names.

    Tries exact, then prefix, then word prefix, then small-typo fuzzy
    matching (e.g. 'gerenado' still finds Genenado the Brute).
    """
    normalized_selector = str(selector_text).strip().lower()
    if not normalized_selector:
        return None

    normalized_names = [str(name).strip().lower() for name in names]

    for index, name in enumerate(normalized_names):
        if name == normalized_selector:
            return index

    for index, name in enumerate(normalized_names):
        if name.startswith(normalized_selector):
            return index
        if any(word.startswith(normalized_selector) for word in name.split()):
            return index

    if len(normalized_selector) < 4:
        return None
    max_distance = 1 if len(normalized_selector) <= 5 else 2
    best_index: int | None = None
    best_distance = max_distance + 1
    for index, name in enumerate(normalized_names):
        candidates = [name] + name.split()
        distance = min(_levenshtein_distance(candidate, normalized_selector) for candidate in candidates)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index if best_distance <= max_distance else None


def _match_recruit_entry(entries: list[dict], selector_text: str) -> dict | None:
    matched_index = _match_name_index([str(entry["name"]) for entry in entries], selector_text)
    return entries[matched_index] if matched_index is not None else None


def _match_owned_companion(companions: list[EntityState], selector_text: str) -> EntityState | None:
    matched_index = _match_name_index([companion.name for companion in companions], selector_text)
    return companions[matched_index] if matched_index is not None else None


def _display_recruit_menu(session: ClientSession, recruiter: EntityState) -> dict:
    entries = _resolve_recruit_entries(recruiter)
    rows = []
    row_cell_colors = []
    for entry in entries:
        already_hired = session_has_companion_npc(session, str(entry["npc_id"]))
        price_text = "hired" if already_hired else f"{int(entry['price'])} coins"
        rows.append([str(entry["name"]), str(entry["role"]), price_text])
        row_cell_colors.append([
            "feedback.value",
            "feedback.text",
            "feedback.text" if already_hired else "feedback.warning",
        ])
    parts = build_menu_table_parts(
        f"{recruiter.name}'s Recruits",
        ["Companion", "Role", "Price"],
        rows,
        row_cell_colors=row_cell_colors,
        column_alignments=["left", "left", "right"],
        empty_message="No recruits are available right now.",
    )
    parts.extend([
        newline_part(),
        build_part("Commands: ", "feedback.text"),
        build_part("enlist <name>", "feedback.value", True),
        build_part(", ", "feedback.text"),
        build_part("dismiss <name>", "feedback.value", True),
    ])
    return display_command_result(session, parts)


def _handle_enlist(session: ClientSession, args: list[str]) -> OutboundResult:
    recruiter, resolve_error = resolve_room_recruiter(session)
    if recruiter is None:
        return display_error(
            resolve_error or "There is no recruiter here.",
            session,
            error_code="no-recruiter-here",
        )

    selector_text = " ".join(arg.strip() for arg in args if arg.strip())
    if not selector_text:
        return _display_recruit_menu(session, recruiter)

    entries = _resolve_recruit_entries(recruiter)
    entry = _match_recruit_entry(entries, selector_text)
    if entry is None:
        available_names = ", ".join(str(recruit_entry["name"]) for recruit_entry in entries) or "none"
        return display_error(
            f"No recruit named '{selector_text}' is available here. Recruits: {available_names}.",
            session,
        )

    if session_has_companion_npc(session, str(entry["npc_id"])):
        return display_error(
            f"{entry['name']} already follows you.",
            session,
        )

    if not companion_roster_has_capacity(session):
        return display_error(
            f"You cannot enlist more than {MAX_COMPANIONS_PER_PLAYER} companions.",
            session,
        )

    companion_name = str(entry["name"])
    price = int(entry["price"])
    if session.status.coins < price:
        return display_error(
            f"You need {price} coins to enlist {companion_name}.",
            session,
            error_code="merchant-insufficient-coins",
            error_context={"item": companion_name, "price": price},
        )

    companion, spawn_error = spawn_companion_for_session(session, str(entry["npc_id"]))
    if companion is None:
        return display_error(spawn_error or f"{companion_name} cannot be enlisted right now.", session)

    session.status.coins -= price
    session.companion_roster.append({"npc_id": str(entry["npc_id"]), "name": companion.name})
    save_player_state(session)

    result_parts = [
        build_part(companion.name, "feedback.value", True),
        build_part(" joins you.", "feedback.text"),
    ]
    voice_line = pick_voice_line(companion, "enlist")
    if voice_line:
        result_parts.extend([
            newline_part(),
            build_part(voice_line, "feedback.text"),
        ])

    result = display_command_result(session, result_parts)
    payload = result.get("payload") if isinstance(result, dict) else None
    if isinstance(payload, dict):
        actor_name = session.authenticated_character_name.strip() or "Someone"
        room_broadcast_lines = [[
            build_part(companion.name, "feedback.value", True),
            build_part(f" falls in behind {actor_name}.", "feedback.text"),
        ]]
        if voice_line:
            room_broadcast_lines.append([build_part(voice_line, "feedback.text")])
        payload["broadcast_to_room"] = True
        payload["room_broadcast_lines"] = room_broadcast_lines
    return result


def _handle_dismiss(session: ClientSession, args: list[str]) -> OutboundResult:
    owned_companions = list_owned_companions_for_session(session)
    if not owned_companions:
        return display_error("You have no enlisted companions.", session)

    selector_text = " ".join(arg.strip() for arg in args if arg.strip())
    if not selector_text:
        if len(owned_companions) == 1:
            companion = owned_companions[0]
        else:
            companion_names = ", ".join(entity.name for entity in owned_companions)
            return display_error(
                f"Dismiss which companion? ({companion_names})",
                session,
                error_code="usage",
                error_context={"usage": "dismiss <name>"},
            )
    else:
        companion = _match_owned_companion(owned_companions, selector_text)
        if companion is None:
            companion_names = ", ".join(entity.name for entity in owned_companions)
            return display_error(
                f"No companion named '{selector_text}' follows you. Your companions: {companion_names}.",
                session,
            )

    companion_room_id = companion.room_id
    voice_line = pick_voice_line(companion, "dismiss")
    shared_world_entities.pop(companion.entity_id, None)
    remove_companion_roster_entry(session, companion.npc_id)
    save_player_state(session)

    result_parts = [
        build_part(companion.name, "feedback.value", True),
        build_part(" departs.", "feedback.text"),
    ]
    if voice_line:
        result_parts.extend([
            newline_part(),
            build_part(voice_line, "feedback.text"),
        ])

    result = display_command_result(session, result_parts)
    payload = result.get("payload") if isinstance(result, dict) else None
    if isinstance(payload, dict) and companion_room_id == session.player.current_room_id:
        actor_name = session.authenticated_character_name.strip() or "Someone"
        room_broadcast_lines = [[
            build_part(companion.name, "feedback.value", True),
            build_part(f" takes leave of {actor_name}.", "feedback.text"),
        ]]
        if voice_line:
            room_broadcast_lines.append([build_part(voice_line, "feedback.text")])
        payload["broadcast_to_room"] = True
        payload["room_broadcast_lines"] = room_broadcast_lines
    return result


def handle_recruitment_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb in _RECRUIT_MENU_VERBS:
        recruiter, resolve_error = resolve_room_recruiter(session)
        if recruiter is None:
            return display_error(
                resolve_error or "There is no recruiter here.",
                session,
                error_code="no-recruiter-here",
            )
        return _display_recruit_menu(session, recruiter)

    if verb in _ENLIST_VERBS:
        return _handle_enlist(session, args)

    if verb in _DISMISS_VERBS:
        return _handle_dismiss(session, args)

    return None
