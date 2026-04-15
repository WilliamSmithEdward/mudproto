import re


_PROPER_NAME_TITLES = {
    "brother",
    "sister",
    "father",
    "mother",
    "lord",
    "lady",
    "sir",
    "dame",
    "king",
    "queen",
    "prince",
    "princess",
}

_GENERIC_ROLE_WORDS = {
    "reaver",
    "hexer",
    "bulwark",
    "knifeman",
    "mercenary",
    "guard",
    "raider",
    "bandit",
    "scout",
    "soldier",
    "captain",
    "priest",
    "mage",
    "warrior",
    "hunter",
    "goblin",
    "orc",
    "wolf",
}


def _looks_like_proper_name(name: str) -> bool:
    tokens = [token for token in str(name).strip().split() if token]
    if len(tokens) < 2:
        return False

    first_token = tokens[0].strip(".,!?;:'\"")
    if first_token.lower() in _PROPER_NAME_TITLES:
        return True

    lowered_tokens = {token.strip(".,!?;:'\"").lower() for token in tokens}
    if {"of", "the"} & lowered_tokens:
        return True

    cleaned_last = tokens[-1].strip(".,!?;:'\"")
    if cleaned_last and cleaned_last[0].isupper() and cleaned_last.lower() not in _GENERIC_ROLE_WORDS:
        return True

    return False


def indefinite_article(name: str, *, capitalize: bool = False) -> str:
    article = "an" if name.strip().lower()[:1] in "aeiou" else "a"
    if capitalize:
        article = article.capitalize()
    return article


def with_article(name: str, *, capitalize: bool = False, is_named: bool | None = None) -> str:
    if is_named is True:
        return str(name)
    if is_named is False:
        return f"{indefinite_article(name, capitalize=capitalize)} {name}"
    if _looks_like_proper_name(name):
        return str(name)
    return f"{indefinite_article(name, capitalize=capitalize)} {name}"


def to_third_person(verb: str) -> str:
    normalized = verb.strip().lower() or "hit"

    irregulars = {
        "am": "is",
        "are": "is",
        "have": "has",
        "do": "does",
        "go": "goes",
    }
    if normalized in irregulars:
        return irregulars[normalized]

    if normalized.endswith("y") and len(normalized) > 1 and normalized[-2] not in "aeiou":
        return f"{normalized[:-1]}ies"
    if normalized.endswith(("s", "x", "z", "ch", "sh")):
        return f"{normalized}es"
    return f"{normalized}s"


def capitalize_after_newlines(text: str) -> str:
    if not text:
        return text

    result: list[str] = []
    capitalize_next = False
    for index, char in enumerate(text):
        if index == 0:
            result.append(char.upper() if char.isalpha() else char)
        elif char == "\n":
            result.append(char)
            capitalize_next = True
        elif capitalize_next and char.isalpha():
            result.append(char.upper())
            capitalize_next = False
        else:
            result.append(char)
            capitalize_next = False

    return "".join(result)


def normalize_player_gender(value: str | None, *, allow_unspecified: bool = True) -> str | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "m": "male",
        "male": "male",
        "f": "female",
        "female": "female",
    }
    if normalized in aliases:
        return aliases[normalized]
    if allow_unspecified and normalized in {"", "u", "unspecified", "unknown", "none"}:
        return "unspecified"
    return None

def resolve_player_pronouns(*, actor_name: str = "", actor_gender: str | None = None) -> tuple[str, str, str, str]:
    normalized_gender = normalize_player_gender(actor_gender)
    if normalized_gender == "female":
        return "she", "her", "her", "herself"
    if normalized_gender == "male":
        return "he", "him", "his", "himself"
    return "they", "them", "their", "themselves"


def third_personize_text(text: str, actor_name: str, actor_gender: str | None = None) -> str:
    if not text:
        return text

    _, _, possessive_pronoun, reflexive_pronoun = resolve_player_pronouns(
        actor_name=actor_name,
        actor_gender=actor_gender,
    )
    rewritten = text
    rewritten = re.sub(r"\byou are\b", f"{actor_name} is", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou were\b", f"{actor_name} was", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou have\b", f"{actor_name} has", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou do\b", f"{actor_name} does", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byourself\b", reflexive_pronoun, rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byour\b", possessive_pronoun, rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou\b", actor_name, rewritten, flags=re.IGNORECASE)

    def _rewrite_subject_verb(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix"))
        verb = str(match.group("verb"))
        normalized_verb = verb.strip().lower()
        if normalized_verb in {"is", "was", "has", "does"}:
            return f"{prefix}{verb}"
        return f"{prefix}{to_third_person(verb)}"

    rewritten = re.sub(
        rf"(?im)^(?P<prefix>{re.escape(actor_name)}(?:\s+barely)?\s+)(?P<verb>[a-z]+)\b",
        _rewrite_subject_verb,
        rewritten,
    )
    return rewritten