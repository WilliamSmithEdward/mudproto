from attribute_config import load_combat_severity_config
from grammar import indefinite_article, to_third_person, with_article
from settings import PLAYER_REFERENCE_MAX_HP


def _choose_severity(damage: int, target_max_hp: int) -> str:
    _ = target_max_hp
    severity_config = load_combat_severity_config()
    tiers = severity_config.get("tiers", []) if isinstance(severity_config, dict) else []

    for tier in tiers:
        max_damage = tier.get("max_damage")
        if max_damage is None or damage <= int(max_damage):
            return str(tier.get("label", "miss"))

    return "miss"


def build_player_attack_parts(
    *,
    entity_name: str,
    attack_verb: str,
    damage: int,
    target_max_hp: int,
) -> list[dict]:
    from display import build_part

    severity = _choose_severity(damage, target_max_hp)
    article = indefinite_article(entity_name)
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
        build_part(attack_verb),
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
            build_part(to_third_person(attack_verb)),
            build_part(" you."),
        ])
        return parts

    if severity in {"normal", "hard", "extreme"}:
        parts.extend([
            build_part(subject),
            build_part(" "),
            build_part(to_third_person(attack_verb)),
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
        build_part(attack_verb),
        build_part("."),
    ])
    return parts


def append_newline_if_needed(parts: list[dict]) -> None:
    if parts:
        parts.append({"text": "\n", "fg": "bright_white", "bold": False})