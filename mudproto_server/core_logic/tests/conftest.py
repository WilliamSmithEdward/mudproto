"""Shared pytest configuration for mudproto_server tests.

Adds core_logic to sys.path and injects dynamic test asset fallbacks so tests are
not tightly coupled to mutable JSON content.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_class_asset_ids() -> dict[str, set[str]]:
	classes_file = Path(__file__).resolve().parent.parent.parent / "configuration" / "attributes" / "classes.json"
	result = {
		"spells": set(),
		"skills": set(),
		"gear": set(),
		"items": set(),
	}

	try:
		with classes_file.open("r", encoding="utf-8") as handle:
			raw_classes = json.load(handle)
	except (OSError, ValueError):
		return result

	if not isinstance(raw_classes, list):
		return result

	for raw_class in raw_classes:
		if not isinstance(raw_class, dict):
			continue

		id_fields = {
			"spells": raw_class.get("starting_spell_ids", []),
			"skills": raw_class.get("starting_skill_ids", []),
			"gear": raw_class.get("starting_gear_template_ids", []),
			"items": raw_class.get("starting_item_ids", []),
		}
		for kind, raw_ids in id_fields.items():
			if not isinstance(raw_ids, list):
				continue
			for raw_id in raw_ids:
				value = str(raw_id).strip().lower()
				if value:
					result[kind].add(value)

	return result


def _title_from_id(value: str, prefix: str) -> str:
	return value.replace(prefix, "", 1).replace("-", " ").replace("_", " ").title() or "Generated"


def _build_generated_test_spell(spell_id: str) -> dict:
	return {
		"spell_id": spell_id,
		"name": _title_from_id(spell_id, "spell."),
		"school": "Generated",
		"description": "Auto-generated test spell placeholder.",
		"spell_type": "damage",
		"element": "arcane",
		"cast_type": "target",
		"mana_cost": 1,
		"damage_dice_count": 1,
		"damage_dice_sides": 1,
		"damage_modifier": 0,
		"damage_scaling_attribute_id": "int",
		"damage_scaling_multiplier": 0.0,
		"level_scaling_multiplier": 0.0,
		"damage_context": "[a/an] [verb] hit by a generated test spell.",
		"affect_ids": [],
		"affects": [],
	}


def _build_generated_test_skill(skill_id: str) -> dict:
	return {
		"skill_id": skill_id,
		"name": _title_from_id(skill_id, "skill."),
		"description": "Auto-generated test skill placeholder.",
		"skill_type": "damage",
		"element": "physical",
		"cast_type": "target",
		"vigor_cost": 1,
		"usable_out_of_combat": True,
		"scaling_attribute_id": "",
		"scaling_multiplier": 0.0,
		"level_scaling_multiplier": 0.0,
		"damage_dice_count": 1,
		"damage_dice_sides": 1,
		"damage_modifier": 0,
		"damage_context": "[a/an] [verb] clipped by a generated test skill.",
		"affect_ids": [],
		"affects": [],
	}


def _build_generated_test_gear(template_id: str) -> dict:
	is_armor = template_id.startswith("armor.")
	slot = "armor" if is_armor else "weapon"
	return {
		"template_id": template_id,
		"name": _title_from_id(template_id, "armor." if is_armor else "weapon."),
		"slot": slot,
		"description": "Auto-generated test gear placeholder.",
		"keywords": [],
		"weapon_type": "unarmed" if slot == "weapon" else "unarmed",
		"can_hold": False,
		"can_two_hand": False,
		"requires_two_hands": False,
		"wear_slots": ["chest"] if slot == "armor" else [],
		"damage_dice_count": 0,
		"damage_dice_sides": 0,
		"damage_roll_modifier": 0,
		"armor_class_bonus": 0,
		"hit_roll_bonus": 0,
		"damage_reduction": 0,
		"coin_value": 0,
		"on_hit_room_damage_chance": 0.0,
		"on_hit_room_damage_dice_count": 0,
		"on_hit_room_damage_dice_sides": 0,
		"on_hit_room_damage_roll_modifier": 0,
		"on_hit_room_damage_message": "",
		"on_hit_room_damage_observer_message": "",
		"on_hit_target_damage_chance": 0.0,
		"on_hit_target_damage_dice_count": 0,
		"on_hit_target_damage_dice_sides": 0,
		"on_hit_target_damage_roll_modifier": 0,
		"on_hit_target_damage_message": "",
		"on_hit_target_damage_observer_message": "",
	}


def _build_generated_test_item(template_id: str) -> dict:
	return {
		"template_id": template_id,
		"name": _title_from_id(template_id, "item."),
		"description": "Auto-generated test item placeholder.",
		"keywords": [],
		"item_type": "misc",
		"persistent": False,
		"portable": True,
		"lock_ids": [],
		"contents": [],
		"consume_on_use": False,
		"consume_message": "",
		"decay_game_hours": 0,
		"decay_message": "",
		"can_close": False,
		"can_lock": False,
		"lock_id": "",
		"is_closed": False,
		"is_locked": False,
		"open_message": "",
		"close_message": "",
		"lock_message": "",
		"unlock_message": "",
		"closed_message": "",
		"locked_message": "",
		"needs_key_message": "",
		"must_close_to_lock_message": "",
		"already_open_message": "",
		"already_closed_message": "",
		"already_locked_message": "",
		"already_unlocked_message": "",
		"effect_type": "",
		"effect_target": "",
		"effect_amount": 0,
		"coin_value": 0,
		"use_lag_seconds": 0.0,
		"observer_action": "",
		"observer_context": "",
		"affect_ids": [],
		"affects": [],
	}


@pytest.fixture(autouse=True, scope="session")
def _inject_dynamic_test_asset_fallbacks():
	import assets

	monkeypatch = pytest.MonkeyPatch()
	class_ids = _load_class_asset_ids()

	generated: dict[str, dict[str, dict]] = {
		"spells": {},
		"skills": {},
		"gear": {},
		"items": {},
	}

	original_get_spell_by_id = assets.get_spell_by_id
	original_get_skill_by_id = assets.get_skill_by_id
	original_get_gear_template_by_id = assets.get_gear_template_by_id
	original_get_item_template_by_id = assets.get_item_template_by_id
	original_load_spells = assets.load_spells
	original_load_skills = assets.load_skills
	original_load_gear_templates = assets.load_gear_templates
	original_load_item_templates = assets.load_item_templates

	def _wants_generated(kind: str, normalized_id: str) -> bool:
		if normalized_id in class_ids[kind]:
			return True
		if kind == "spells":
			return normalized_id.startswith("spell.")
		if kind == "skills":
			return normalized_id.startswith("skill.")
		if kind == "gear":
			return normalized_id.startswith("weapon.") or normalized_id.startswith("armor.")
		if kind == "items":
			return normalized_id.startswith("item.")
		return False

	def _get_or_generate(kind: str, raw_id: str, existing_lookup) -> dict | None:
		normalized_id = str(raw_id).strip().lower()
		if not normalized_id:
			return None

		existing = existing_lookup(normalized_id)
		if existing is not None:
			return existing
		if not _wants_generated(kind, normalized_id):
			return None

		if normalized_id not in generated[kind]:
			if kind == "spells":
				generated[kind][normalized_id] = _build_generated_test_spell(normalized_id)
			elif kind == "skills":
				generated[kind][normalized_id] = _build_generated_test_skill(normalized_id)
			elif kind == "gear":
				generated[kind][normalized_id] = _build_generated_test_gear(normalized_id)
			else:
				generated[kind][normalized_id] = _build_generated_test_item(normalized_id)
		return generated[kind][normalized_id]

	def _patched_get_spell_by_id(spell_id: str) -> dict | None:
		return _get_or_generate("spells", spell_id, original_get_spell_by_id)

	def _patched_get_skill_by_id(skill_id: str) -> dict | None:
		return _get_or_generate("skills", skill_id, original_get_skill_by_id)

	def _patched_get_gear_template_by_id(template_id: str) -> dict | None:
		return _get_or_generate("gear", template_id, original_get_gear_template_by_id)

	def _patched_get_item_template_by_id(template_id: str) -> dict | None:
		return _get_or_generate("items", template_id, original_get_item_template_by_id)

	def _patched_load_spells() -> list[dict]:
		loaded = list(original_load_spells())
		loaded_ids = {str(row.get("spell_id", "")).strip().lower() for row in loaded if isinstance(row, dict)}
		for spell_id in sorted(class_ids["spells"] | set(generated["spells"].keys())):
			if spell_id in loaded_ids:
				continue
			row = _patched_get_spell_by_id(spell_id)
			if row is not None:
				loaded.append(row)
		return loaded

	def _patched_load_skills() -> list[dict]:
		loaded = list(original_load_skills())
		loaded_ids = {str(row.get("skill_id", "")).strip().lower() for row in loaded if isinstance(row, dict)}
		for skill_id in sorted(class_ids["skills"] | set(generated["skills"].keys())):
			if skill_id in loaded_ids:
				continue
			row = _patched_get_skill_by_id(skill_id)
			if row is not None:
				loaded.append(row)
		return loaded

	def _patched_load_gear_templates() -> list[dict]:
		loaded = list(original_load_gear_templates())
		loaded_ids = {str(row.get("template_id", "")).strip().lower() for row in loaded if isinstance(row, dict)}
		for template_id in sorted(class_ids["gear"] | set(generated["gear"].keys())):
			if template_id in loaded_ids:
				continue
			row = _patched_get_gear_template_by_id(template_id)
			if row is not None:
				loaded.append(row)
		return loaded

	def _patched_load_item_templates() -> list[dict]:
		loaded = list(original_load_item_templates())
		loaded_ids = {str(row.get("template_id", "")).strip().lower() for row in loaded if isinstance(row, dict)}
		for template_id in sorted(class_ids["items"] | set(generated["items"].keys())):
			if template_id in loaded_ids:
				continue
			row = _patched_get_item_template_by_id(template_id)
			if row is not None:
				loaded.append(row)
		return loaded

	monkeypatch.setattr(assets, "get_spell_by_id", _patched_get_spell_by_id)
	monkeypatch.setattr(assets, "get_skill_by_id", _patched_get_skill_by_id)
	monkeypatch.setattr(assets, "get_gear_template_by_id", _patched_get_gear_template_by_id)
	monkeypatch.setattr(assets, "get_item_template_by_id", _patched_get_item_template_by_id)
	monkeypatch.setattr(assets, "load_spells", _patched_load_spells)
	monkeypatch.setattr(assets, "load_skills", _patched_load_skills)
	monkeypatch.setattr(assets, "load_gear_templates", _patched_load_gear_templates)
	monkeypatch.setattr(assets, "load_item_templates", _patched_load_item_templates)

	# Some modules import these helpers directly; patch aliases when present.
	alias_targets = {
		"get_spell_by_id": _patched_get_spell_by_id,
		"get_skill_by_id": _patched_get_skill_by_id,
		"get_gear_template_by_id": _patched_get_gear_template_by_id,
		"get_item_template_by_id": _patched_get_item_template_by_id,
		"load_spells": _patched_load_spells,
		"load_skills": _patched_load_skills,
		"load_gear_templates": _patched_load_gear_templates,
		"load_item_templates": _patched_load_item_templates,
	}
	for module in list(sys.modules.values()):
		if module is None:
			continue
		for attr_name, patched_fn in alias_targets.items():
			if hasattr(module, attr_name):
				monkeypatch.setattr(module, attr_name, patched_fn, raising=False)

	try:
		yield
	finally:
		monkeypatch.undo()

