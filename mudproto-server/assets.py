import json
from functools import lru_cache
from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent / "assets" / "default-assets"
TRAINING_EQUIPMENT_FILE = ASSET_ROOT / "training-equipment.json"


def _read_json_asset(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_equipment_templates() -> list[dict]:
    raw_templates = _read_json_asset(TRAINING_EQUIPMENT_FILE)
    if not isinstance(raw_templates, list):
        raise ValueError(f"Equipment asset file must contain a list: {TRAINING_EQUIPMENT_FILE}")

    template_ids: set[str] = set()
    normalized_templates: list[dict] = []

    for raw_template in raw_templates:
        if not isinstance(raw_template, dict):
            raise ValueError("Equipment asset entries must be objects.")

        template_id = raw_template.get("template_id")
        name = raw_template.get("name")
        slot = raw_template.get("slot")

        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("Equipment asset entries must include a non-empty string template_id.")
        if template_id in template_ids:
            raise ValueError(f"Duplicate equipment template_id: {template_id}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Equipment asset '{template_id}' must include a non-empty name.")
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError(f"Equipment asset '{template_id}' must include a non-empty slot.")

        template_ids.add(template_id)
        normalized_templates.append({
            "template_id": template_id,
            "name": name,
            "slot": slot,
            "description": str(raw_template.get("description", "")),
            "attack_damage_bonus": int(raw_template.get("attack_damage_bonus", 0)),
            "attacks_per_round_bonus": int(raw_template.get("attacks_per_round_bonus", 0)),
            "grant_to_new_players": bool(raw_template.get("grant_to_new_players", False)),
            "equip_on_grant": bool(raw_template.get("equip_on_grant", False)),
        })

    return normalized_templates


def load_starting_equipment_templates() -> list[dict]:
    return [
        template
        for template in load_equipment_templates()
        if template["grant_to_new_players"]
    ]