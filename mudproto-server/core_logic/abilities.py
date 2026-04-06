"""Spell and skill knowledge lookup helpers."""

from assets import load_skills, load_spells
from models import ClientSession


def _list_known_spells(session: ClientSession) -> list[dict]:
    known_ids = {spell_id.strip().lower() for spell_id in session.known_spell_ids if spell_id.strip()}
    if not known_ids:
        return []

    known_spells = [
        spell
        for spell in load_spells()
        if str(spell.get("spell_id", "")).strip().lower() in known_ids
    ]
    known_spells.sort(key=lambda spell: str(spell.get("name", "")).strip().lower())
    return known_spells


def _resolve_spell_by_name(spell_name: str, spells: list[dict] | None = None) -> tuple[dict | None, str | None]:
    normalized = spell_name.strip().lower()
    if not normalized:
        return None, "Usage: cast 'spell name' [target]"

    def _tokenize(value: str) -> list[str]:
        return [token for token in value.strip().lower().split() if token]

    query_tokens = _tokenize(normalized)
    query_joined = "".join(query_tokens)

    exact_matches: list[dict] = []
    partial_matches: list[dict] = []

    for spell in (spells if spells is not None else load_spells()):
        name = str(spell.get("name", "")).strip()
        spell_normalized = name.lower()
        if not spell_normalized:
            continue

        if spell_normalized == normalized:
            exact_matches.append(spell)
            continue

        name_tokens = _tokenize(spell_normalized)
        initials = "".join(token[0] for token in name_tokens if token)
        token_prefix_match = False
        if query_tokens and len(query_tokens) <= len(name_tokens):
            token_prefix_match = all(
                name_tokens[index].startswith(query_tokens[index])
                for index in range(len(query_tokens))
            )

        joined_prefix_match = bool(query_joined) and initials.startswith(query_joined)
        substring_match = normalized in spell_normalized
        if token_prefix_match or joined_prefix_match or substring_match:
            partial_matches.append(spell)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        names = ", ".join(str(spell.get("name", "Spell")) for spell in exact_matches[:3])
        return None, f"Multiple exact spell matches found: {names}"

    if len(partial_matches) == 1:
        return partial_matches[0], None
    if len(partial_matches) > 1:
        names = ", ".join(str(spell.get("name", "Spell")) for spell in partial_matches[:3])
        return None, f"Multiple spell matches found. Be more specific: {names}"

    return None, f"Unknown spell: {spell_name}"


def _list_known_skills(session: ClientSession) -> list[dict]:
    known_ids = {skill_id.strip().lower() for skill_id in session.known_skill_ids if skill_id.strip()}
    if not known_ids:
        return []

    known_skills = [
        skill
        for skill in load_skills()
        if str(skill.get("skill_id", "")).strip().lower() in known_ids
    ]
    known_skills.sort(key=lambda skill: str(skill.get("name", "")).strip().lower())
    return known_skills


def _resolve_skill_by_name(skill_name: str, skills: list[dict] | None = None) -> tuple[dict | None, str | None]:
    normalized = skill_name.strip().lower()
    if not normalized:
        return None, "Usage: <skill> [target]"

    def _tokenize(value: str) -> list[str]:
        return [token for token in value.strip().lower().split() if token]

    query_tokens = _tokenize(normalized)
    query_joined = "".join(query_tokens)

    exact_matches: list[dict] = []
    partial_matches: list[dict] = []

    for skill in (skills if skills is not None else load_skills()):
        name = str(skill.get("name", "")).strip()
        skill_normalized = name.lower()
        if not skill_normalized:
            continue

        if skill_normalized == normalized:
            exact_matches.append(skill)
            continue

        name_tokens = _tokenize(skill_normalized)
        initials = "".join(token[0] for token in name_tokens if token)
        token_prefix_match = False
        if query_tokens and len(query_tokens) <= len(name_tokens):
            token_prefix_match = all(
                name_tokens[index].startswith(query_tokens[index])
                for index in range(len(query_tokens))
            )

        joined_prefix_match = bool(query_joined) and initials.startswith(query_joined)
        if token_prefix_match or joined_prefix_match:
            partial_matches.append(skill)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        names = ", ".join(str(skill.get("name", "Skill")) for skill in exact_matches[:3])
        return None, f"Multiple exact skill matches found: {names}"

    if len(partial_matches) == 1:
        return partial_matches[0], None
    if len(partial_matches) > 1:
        names = ", ".join(str(skill.get("name", "Skill")) for skill in partial_matches[:3])
        return None, f"Multiple skill matches found. Be more specific: {names}"

    return None, f"Unknown skill: {skill_name}"
