"""Corpse naming helpers."""


def normalize_corpse_label_style(raw_style: str | None, *, default: str = "generic") -> str:
    normalized = str(raw_style or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"generic", "possessive"}:
        return normalized
    return default


def build_corpse_label(source_name: str, corpse_label_style: str = "generic") -> str:
    cleaned_name = " ".join(str(source_name).split()).strip()
    if not cleaned_name:
        return "corpse"

    normalized_style = normalize_corpse_label_style(corpse_label_style)
    if normalized_style == "possessive":
        final_word = cleaned_name.split(" ")[-1]
        suffix = "'" if final_word.endswith(("s", "S")) else "'s"
        return f"{final_word}{suffix} corpse"

    return f"{cleaned_name} corpse"
