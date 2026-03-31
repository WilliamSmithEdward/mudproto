from settings import PLAYER_REFERENCE_MAX_HP


def _to_third_person(verb: str) -> str:
    normalized = verb.strip().lower() or "hit"
    if normalized.endswith("y") and len(normalized) > 1 and normalized[-2] not in "aeiou":
        return f"{normalized[:-1]}ies"
    if normalized.endswith(("s", "x", "z", "ch", "sh")):
        return f"{normalized}es"
    return f"{normalized}s"


def _article(name: str) -> str:
    return "an" if name.strip().lower()[:1] in "aeiou" else "a"


def with_article(name: str, *, capitalize: bool = False) -> str:
    article = _article(name)
    if capitalize:
        article = article.capitalize()
    return f"{article} {name}"


def _choose_severity(damage: int, target_max_hp: int) -> str:
    _ = target_max_hp
    if damage <= 0:
        return "miss"

    if damage <= 5:
        return "barely"
    if damage <= 10:
        return "normal"
    if damage <= 15:
        return "hard"
    if damage <= 25:
        return "extreme"
    if damage <= 40:
        return "massacre"
    if damage <= 80:
        return "annihilate"
    return "obliterate"


def build_player_attack_parts(
    *,
    entity_name: str,
    attack_verb: str,
    damage: int,
    target_max_hp: int,
) -> list[dict]:
    from display import build_part

    verb_noun = _to_third_person(attack_verb)
    severity = _choose_severity(damage, target_max_hp)
    article = _article(entity_name)
    named = f"{article} {entity_name}"

    parts: list[dict] = []
    if severity == "miss":
        parts.extend([
            build_part("You miss "),
            build_part(named),
            build_part(" with your "),
            build_part(attack_verb),
            build_part("."),
        ])
        return parts

    if severity in {"barely", "normal", "hard", "extreme"}:
        if severity == "barely":
            parts.append(build_part("You barely "))
        else:
            parts.append(build_part("You "))
        parts.extend([
            build_part(attack_verb),
            build_part(" "),
            build_part(named),
        ])
        if severity == "hard":
            parts.append(build_part(" hard"))
        elif severity == "extreme":
            parts.append(build_part(" extremely hard"))
        parts.append(build_part("."))
        return parts

    top_label = {
        "massacre": "massacre",
        "annihilate": "annihilate",
        "obliterate": "obliterate",
    }[severity]
    parts.extend([
        build_part(f"You {top_label} "),
        build_part(named),
        build_part(" with your "),
        build_part(verb_noun),
        build_part("."),
    ])
    return parts


def build_entity_attack_parts(
    *,
    entity_name: str,
    entity_pronoun_possessive: str,
    attack_verb: str,
    damage: int,
) -> list[dict]:
    from display import build_part

    verb_noun = _to_third_person(attack_verb)
    severity = _choose_severity(damage, PLAYER_REFERENCE_MAX_HP)
    subject = with_article(entity_name, capitalize=True)

    parts: list[dict] = []
    if severity == "miss":
        parts.extend([
            build_part(subject),
            build_part(" misses you."),
        ])
        return parts

    if severity == "barely":
        parts.extend([
            build_part(subject),
            build_part(" barely "),
            build_part(_to_third_person(attack_verb)),
            build_part(" you."),
        ])
        return parts

    if severity in {"normal", "hard", "extreme"}:
        parts.extend([
            build_part(subject),
            build_part(" "),
            build_part(_to_third_person(attack_verb)),
            build_part(" you"),
        ])
        if severity == "hard":
            parts.append(build_part(" hard"))
        elif severity == "extreme":
            parts.append(build_part(" extremely hard"))
        parts.append(build_part("."))
        return parts

    top_verb = {
        "massacre": "massacres",
        "annihilate": "annihilates",
        "obliterate": "obliterates",
    }[severity]
    pronoun = entity_pronoun_possessive.strip().lower() or "its"
    parts.extend([
        build_part(subject),
        build_part(f" {top_verb} you with {pronoun} "),
        build_part(verb_noun),
        build_part("."),
    ])
    return parts


def append_newline_if_needed(parts: list[dict]) -> None:
    if parts:
        parts.append({"text": "\n", "fg": "bright_white", "bold": False})