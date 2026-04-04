import re


def indefinite_article(name: str, *, capitalize: bool = False) -> str:
    article = "an" if name.strip().lower()[:1] in "aeiou" else "a"
    if capitalize:
        article = article.capitalize()
    return article


def with_article(name: str, *, capitalize: bool = False) -> str:
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


def third_personize_text(text: str, actor_name: str) -> str:
    if not text:
        return text

    possessive = f"{actor_name}'" if actor_name.endswith("s") else f"{actor_name}'s"
    rewritten = text
    rewritten = re.sub(r"\byou are\b", f"{actor_name} is", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou were\b", f"{actor_name} was", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou have\b", f"{actor_name} has", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byou do\b", f"{actor_name} does", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byourself\b", "themselves", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\byour\b", possessive, rewritten, flags=re.IGNORECASE)
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