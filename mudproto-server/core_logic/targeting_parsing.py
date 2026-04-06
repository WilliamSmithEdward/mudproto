"""Selector parsing helpers for command input."""

import re

from abilities import _list_known_skills, _list_known_spells, _resolve_skill_by_name, _resolve_spell_by_name
from equipment import HAND_BOTH, HAND_MAIN, HAND_OFF, resolve_wear_slot_alias


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


def _selector_prefix_matches_keywords(parts: list[str], keywords: set[str]) -> bool:
    if not parts or not keywords:
        return False
    return all(any(keyword.startswith(part) for keyword in keywords) for part in parts)
