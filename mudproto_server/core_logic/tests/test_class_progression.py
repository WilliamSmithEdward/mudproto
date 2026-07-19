import json

import pytest

import attribute_config
from attribute_config import get_player_class_by_id, load_player_classes
from assets import get_skill_by_id, get_spell_by_id
from combat_rewards import _append_experience_gain_notification
from display_core import build_part
from models import ClientSession
from session_bootstrap import apply_player_class, grant_class_abilities_for_level


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _parts_text(parts: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in parts)


def test_class_ability_unlocks_are_configured_by_level() -> None:
    arcanist = get_player_class_by_id("class.arcanist")
    monk = get_player_class_by_id("class.monk")

    assert arcanist is not None
    assert monk is not None
    assert [entry["level"] for entry in arcanist["ability_unlocks"]] == list(range(2, 11))
    assert [entry["level"] for entry in monk["ability_unlocks"]] == [2, 3, 4, 5, 7, 10]


def test_apply_player_class_only_grants_level_one_kit() -> None:
    arcanist = _make_session("client-arcanist-progression", "Arcanist")

    apply_player_class(arcanist, "class.arcanist", roll_attributes=False, initialize_progression=False)

    assert set(arcanist.known_spell_ids) == {"spell.spark", "spell.healing-light"}
    assert arcanist.known_skill_ids == ["skill.jab"]
    assert "spell.arc-bolt" not in arcanist.known_spell_ids


def test_grant_class_abilities_for_level_adds_crossed_unlocks_once() -> None:
    arcanist = _make_session("client-arcanist-level-five", "Arcanist")
    apply_player_class(arcanist, "class.arcanist", roll_attributes=False, initialize_progression=False)

    unlocked = grant_class_abilities_for_level(arcanist, 5)
    unlocked_again = grant_class_abilities_for_level(arcanist, 5)

    assert [(entry["kind"], entry["name"]) for entry in unlocked] == [
        ("skill", "Guard Breath"),
        ("spell", "Arc Bolt"),
        ("spell", "Mending Word"),
        ("spell", "Bark Skin"),
    ]
    assert unlocked_again == []


def test_level_up_message_names_new_abilities() -> None:
    monk = _make_session("client-monk-level-three", "Monk")
    apply_player_class(monk, "class.monk", roll_attributes=False, initialize_progression=False)
    monk.player.level = 3
    parts: list[dict] = []

    _append_experience_gain_notification(monk, 150, 1, 3, parts, build_part)

    rendered = _parts_text(parts)
    assert "New skill: Centered Guard." in rendered
    assert "New skill: Roundhouse Kick." in rendered


def test_player_ability_costs_use_rebalanced_values() -> None:
    expected_spell_costs = {
        "spell.spark": 18,
        "spell.bark-skin": 30,
        "spell.ice-storm": 70,
    }
    expected_skill_costs = {
        "skill.jab": 6,
        "skill.roundhouse-kick": 18,
        "skill.fist-flurry": 16,
    }

    for spell_id, expected_cost in expected_spell_costs.items():
        spell = get_spell_by_id(spell_id)
        assert spell is not None
        assert spell["mana_cost"] == expected_cost

    for skill_id, expected_cost in expected_skill_costs.items():
        skill = get_skill_by_id(skill_id)
        assert skill is not None
        assert skill["vigor_cost"] == expected_cost


def test_player_class_loader_rejects_duplicate_progression_ability(tmp_path, monkeypatch) -> None:
    classes_path = tmp_path / "classes.json"
    raw_classes = json.loads(attribute_config.PLAYER_CLASSES_FILE.read_text(encoding="utf-8"))
    raw_classes[0]["ability_unlocks"][1]["spell_ids"].append("spell.spark")
    classes_path.write_text(json.dumps(raw_classes), encoding="utf-8")
    monkeypatch.setattr(attribute_config, "PLAYER_CLASSES_FILE", classes_path)
    load_player_classes.cache_clear()

    with pytest.raises(ValueError, match="assigns spell 'spell.spark' more than once"):
        load_player_classes()

    load_player_classes.cache_clear()
