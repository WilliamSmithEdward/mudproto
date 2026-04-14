from attribute_config import load_passives, player_class_uses_mana
from assets import load_skills, load_spells
from display_core import build_menu_table_parts, build_part
from display_feedback import display_command_result, display_error
from models import ClientSession
from settings import DEBUG_MODE

from .types import OutboundResult


HandledResult = OutboundResult | None

_ACQUIRE_VERBS = {"ac", "acq", "acqu", "acqui", "acquir", "acquire"}
_FORGET_VERBS = {"fo", "for", "forg", "forge", "forget"}
_KIND_ALIASES = {
    "skill": "skill",
    "skills": "skill",
    "spell": "spell",
    "spells": "spell",
    "passive": "passive",
    "passives": "passive",
}


def _known_id_set(values: list[str]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _build_all_entries(session: ClientSession) -> list[dict]:
    include_spells = player_class_uses_mana(session.player.class_id)

    entries: list[dict] = []
    for skill in load_skills():
        skill_id = str(skill.get("skill_id", "")).strip()
        name = str(skill.get("name", "Skill")).strip() or "Skill"
        if skill_id:
            entries.append({"kind": "skill", "id": skill_id, "name": name})

    if include_spells:
        for spell in load_spells():
            spell_id = str(spell.get("spell_id", "")).strip()
            name = str(spell.get("name", "Spell")).strip() or "Spell"
            if spell_id:
                entries.append({"kind": "spell", "id": spell_id, "name": name})

    for passive in load_passives():
        passive_id = str(passive.get("passive_id", "")).strip()
        name = str(passive.get("name", "Passive")).strip() or "Passive"
        if passive_id:
            entries.append({"kind": "passive", "id": passive_id, "name": name})

    return entries


def _build_known_entries(session: ClientSession) -> list[dict]:
    entries: list[dict] = []

    skill_map = {
        str(skill.get("skill_id", "")).strip().lower(): skill
        for skill in load_skills()
        if str(skill.get("skill_id", "")).strip()
    }
    for skill_id in session.known_skill_ids:
        normalized = str(skill_id).strip().lower()
        if not normalized:
            continue
        skill = skill_map.get(normalized)
        name = str(skill.get("name", skill_id)).strip() if isinstance(skill, dict) else str(skill_id).strip()
        entries.append({"kind": "skill", "id": str(skill_id).strip(), "name": name or str(skill_id).strip()})

    spell_map = {
        str(spell.get("spell_id", "")).strip().lower(): spell
        for spell in load_spells()
        if str(spell.get("spell_id", "")).strip()
    }
    for spell_id in session.known_spell_ids:
        normalized = str(spell_id).strip().lower()
        if not normalized:
            continue
        spell = spell_map.get(normalized)
        name = str(spell.get("name", spell_id)).strip() if isinstance(spell, dict) else str(spell_id).strip()
        entries.append({"kind": "spell", "id": str(spell_id).strip(), "name": name or str(spell_id).strip()})

    passive_map = {
        str(passive.get("passive_id", "")).strip().lower(): passive
        for passive in load_passives()
        if str(passive.get("passive_id", "")).strip()
    }
    for passive_id in session.known_passive_ids:
        normalized = str(passive_id).strip().lower()
        if not normalized:
            continue
        passive = passive_map.get(normalized)
        name = str(passive.get("name", passive_id)).strip() if isinstance(passive, dict) else str(passive_id).strip()
        entries.append({"kind": "passive", "id": str(passive_id).strip(), "name": name or str(passive_id).strip()})

    return entries


def _find_matches(selector: str, entries: list[dict], kind_filter: str | None = None) -> list[dict]:
    normalized_selector = str(selector).strip().lower()
    if not normalized_selector:
        return []

    candidate_entries = [entry for entry in entries if kind_filter is None or entry["kind"] == kind_filter]

    exact_matches = [
        entry
        for entry in candidate_entries
        if str(entry["id"]).strip().lower() == normalized_selector
        or str(entry["name"]).strip().lower() == normalized_selector
    ]
    if exact_matches:
        return exact_matches

    return [
        entry
        for entry in candidate_entries
        if str(entry["id"]).strip().lower().startswith(normalized_selector)
        or str(entry["name"]).strip().lower().startswith(normalized_selector)
    ]


def _resolve_selector(selector: str, entries: list[dict], kind_filter: str | None = None) -> tuple[dict | None, str | None]:
    matches = _find_matches(selector, entries, kind_filter)
    if not matches:
        return None, "No matching acquirable object was found."

    if len(matches) > 1:
        options = ", ".join(f"{entry['kind']}:{entry['name']}" for entry in matches[:3])
        return None, f"Multiple matches found. Be more specific: {options}"

    return matches[0], None


def _build_acquirable_parts(session: ClientSession) -> list[dict]:
    known_skill_ids = _known_id_set(session.known_skill_ids)
    known_spell_ids = _known_id_set(session.known_spell_ids)
    known_passive_ids = _known_id_set(session.known_passive_ids)

    rows: list[list[str]] = []
    for entry in _build_all_entries(session):
        normalized_entry_id = str(entry["id"]).strip().lower()
        kind = str(entry["kind"]).strip().lower()
        if kind == "skill" and normalized_entry_id in known_skill_ids:
            continue
        if kind == "spell" and normalized_entry_id in known_spell_ids:
            continue
        if kind == "passive" and normalized_entry_id in known_passive_ids:
            continue
        rows.append([kind.title(), str(entry["name"]), str(entry["id"])])

    rows.sort(key=lambda row: (row[0].lower(), row[1].lower(), row[2].lower()))

    if not rows:
        return [
            build_part("Nothing acquirable remains for your character.", "bright_white"),
        ]

    return build_menu_table_parts(
        "Acquirable Objects (Debug)",
        ["Type", "Name", "Id"],
        rows,
        column_colors=["bright_magenta", "bright_cyan", "bright_yellow"],
        column_alignments=["left", "left", "left"],
    )


def _grant_entry(session: ClientSession, entry: dict) -> dict:
    kind = str(entry["kind"]).strip().lower()
    entry_id = str(entry["id"]).strip()
    entry_name = str(entry["name"]).strip() or entry_id
    normalized_id = entry_id.lower()

    if kind == "spell" and not player_class_uses_mana(session.player.class_id):
        return display_error("Your class cannot acquire spells because it does not use mana.", session)

    if kind == "skill":
        if normalized_id in _known_id_set(session.known_skill_ids):
            return display_error(f"You already know skill: {entry_name}.", session)
        session.known_skill_ids.append(entry_id)
    elif kind == "spell":
        if normalized_id in _known_id_set(session.known_spell_ids):
            return display_error(f"You already know spell: {entry_name}.", session)
        session.known_spell_ids.append(entry_id)
    elif kind == "passive":
        if normalized_id in _known_id_set(session.known_passive_ids):
            return display_error(f"You already have passive: {entry_name}.", session)
        session.known_passive_ids.append(entry_id)
    else:
        return display_error("Unsupported acquire target.", session)

    return display_command_result(session, [
        build_part("Acquired ", "bright_white"),
        build_part(kind, "bright_magenta", True),
        build_part(": ", "bright_white"),
        build_part(entry_name, "bright_cyan", True),
        build_part(".", "bright_white"),
    ])


def _forget_entry(session: ClientSession, entry: dict) -> dict:
    kind = str(entry["kind"]).strip().lower()
    entry_id = str(entry["id"]).strip()
    entry_name = str(entry["name"]).strip() or entry_id
    normalized_id = entry_id.lower()

    if kind == "skill":
        session.known_skill_ids = [value for value in session.known_skill_ids if str(value).strip().lower() != normalized_id]
    elif kind == "spell":
        session.known_spell_ids = [value for value in session.known_spell_ids if str(value).strip().lower() != normalized_id]
    elif kind == "passive":
        session.known_passive_ids = [value for value in session.known_passive_ids if str(value).strip().lower() != normalized_id]
    else:
        return display_error("Unsupported forget target.", session)

    return display_command_result(session, [
        build_part("Forgot ", "bright_white"),
        build_part(kind, "bright_magenta", True),
        build_part(": ", "bright_white"),
        build_part(entry_name, "bright_cyan", True),
        build_part(".", "bright_white"),
    ])


def _extract_kind_filter(args: list[str]) -> tuple[str | None, list[str]]:
    if not args:
        return None, []

    first = str(args[0]).strip().lower()
    kind = _KIND_ALIASES.get(first)
    if kind is None:
        return None, args
    return kind, args[1:]


def handle_debug_acquire_command(
    session: ClientSession,
    verb: str,
    args: list[str],
    _command_text: str,
) -> HandledResult:
    if verb not in _ACQUIRE_VERBS and verb not in _FORGET_VERBS:
        return None

    if not DEBUG_MODE:
        return display_error("Debug mode is disabled.", session)

    if verb in _ACQUIRE_VERBS and not args:
        return display_command_result(session, _build_acquirable_parts(session))

    if not args:
        if verb in _ACQUIRE_VERBS:
            return display_error("Usage: acquire [skill|spell|passive] <name>", session)
        return display_error("Usage: forget [skill|spell|passive] <name>", session)

    kind_filter, remaining_args = _extract_kind_filter(args)
    selector = " ".join(remaining_args).strip()
    if not selector:
        if verb in _ACQUIRE_VERBS:
            return display_error("Usage: acquire [skill|spell|passive] <name>", session)
        return display_error("Usage: forget [skill|spell|passive] <name>", session)

    if verb in _ACQUIRE_VERBS:
        if kind_filter == "spell" and not player_class_uses_mana(session.player.class_id):
            return display_error("Your class cannot acquire spells because it does not use mana.", session)
        entry, resolve_error = _resolve_selector(selector, _build_all_entries(session), kind_filter)
        if entry is None:
            return display_error(resolve_error or "No matching acquirable object was found.", session)
        return _grant_entry(session, entry)

    entry, resolve_error = _resolve_selector(selector, _build_known_entries(session), kind_filter)
    if entry is None:
        return display_error(resolve_error or "No matching known object was found.", session)
    return _forget_entry(session, entry)
