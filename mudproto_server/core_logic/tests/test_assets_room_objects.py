import assets
from titlecase import titlecase as to_title_case


def _room_by_id(room_id: str) -> dict:
    for room in assets.load_rooms():
        if str(room.get("room_id", "")).strip() == room_id:
            return room
    raise AssertionError(f"Room '{room_id}' was not found.")


def test_room_object_names_are_title_cased(monkeypatch) -> None:
    monkeypatch.setattr(assets, "DEBUG_MODE", True)
    assets.load_rooms.cache_clear()

    start_room = _room_by_id("start")
    room_objects = start_room.get("room_objects", [])
    named_objects = [
        obj for obj in room_objects
        if isinstance(obj, dict) and str(obj.get("name", "")).strip()
    ]

    assert len(named_objects) > 0, "Expected at least one room object with a name."
    for obj in named_objects:
        name = str(obj["name"])
        assert name == to_title_case(name), (
            f"Room object '{obj.get('object_id', '?')}' name '{name}' is not title-cased."
        )


def test_room_object_names_title_cased_in_payloads() -> None:
    assets.load_rooms.cache_clear()
    all_rooms = assets.load_rooms()

    objects_checked = 0
    for room in all_rooms:
        for obj in room.get("room_objects", []):
            name = str(obj.get("name", "")).strip()
            if name:
                objects_checked += 1
                assert name == to_title_case(name), (
                    f"Room '{room.get('room_id', '?')}' object '{obj.get('object_id', '?')}' "
                    f"name '{name}' is not title-cased."
                )

    assert objects_checked > 0, "Expected at least one room object name to verify."


def _load_rooms_with_raw(monkeypatch, raw_rooms: list[dict]) -> list[dict]:
    """Load rooms from a synthetic raw list, bypassing file I/O."""
    monkeypatch.setattr(assets, "_read_json_asset", lambda _path: raw_rooms)
    monkeypatch.setattr(assets, "_load_asset_payload_section", lambda _section: [])
    assets.load_rooms.cache_clear()
    return assets.load_rooms()


def test_room_object_rejects_empty_object_id(monkeypatch) -> None:
    import pytest

    raw_rooms = [
        {
            "room_id": "test.room-empty-obj-id",
            "title": "Test Room",
            "description": "A test room.",
            "zone_id": "test-zone",
            "room_objects": [
                {
                    "object_id": "",
                    "name": "broken thing",
                    "description": "It should not load.",
                }
            ],
        }
    ]

    with pytest.raises(ValueError, match="must include object_id"):
        _load_rooms_with_raw(monkeypatch, raw_rooms)


def test_room_object_rejects_empty_name(monkeypatch) -> None:
    import pytest

    raw_rooms = [
        {
            "room_id": "test.room-empty-obj-name",
            "title": "Test Room",
            "description": "A test room.",
            "zone_id": "test-zone",
            "room_objects": [
                {
                    "object_id": "obj.has-id",
                    "name": "",
                    "description": "It should not load.",
                }
            ],
        }
    ]

    with pytest.raises(ValueError, match="must include name"):
        _load_rooms_with_raw(monkeypatch, raw_rooms)


def test_title_casing_applied_to_synthetic_room_object(monkeypatch) -> None:
    raw_rooms = [
        {
            "room_id": "test.title-case-room",
            "title": "Test Room",
            "description": "A test room.",
            "zone_id": "test-zone",
            "room_objects": [
                {
                    "object_id": "obj.mossy-fountain",
                    "name": "mossy fountain",
                    "description": "A mossy fountain bubbles quietly.",
                }
            ],
        }
    ]

    rooms = _load_rooms_with_raw(monkeypatch, raw_rooms)
    obj = rooms[0]["room_objects"][0]
    assert obj["name"] == "Mossy Fountain"


def test_titlecase_preserves_small_words_in_room_objects(monkeypatch) -> None:
    raw_rooms = [
        {
            "room_id": "test.small-words-room",
            "title": "hall of the fallen king",
            "description": "A test room.",
            "zone_id": "test-zone",
            "room_objects": [
                {
                    "object_id": "obj.statue-of-the-king",
                    "name": "statue of the fallen king",
                    "description": "A grand statue.",
                }
            ],
        }
    ]

    rooms = _load_rooms_with_raw(monkeypatch, raw_rooms)
    assert rooms[0]["title"] == "Hall of the Fallen King"
    assert rooms[0]["room_objects"][0]["name"] == "Statue of the Fallen King"


def test_all_gear_names_are_title_cased() -> None:
    for gear in assets.load_gear_templates():
        name = str(gear.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"Gear '{gear.get('template_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_item_names_are_title_cased() -> None:
    for item in assets.load_item_templates():
        name = str(item.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"Item '{item.get('template_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_npc_names_are_title_cased() -> None:
    for npc in assets.load_npc_templates():
        name = str(npc.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"NPC '{npc.get('npc_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_spell_names_are_title_cased() -> None:
    for spell in assets.load_spells():
        name = str(spell.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"Spell '{spell.get('spell_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_skill_names_are_title_cased() -> None:
    for skill in assets.load_skills():
        name = str(skill.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"Skill '{skill.get('skill_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_zone_names_are_title_cased() -> None:
    for zone in assets.load_zones():
        name = str(zone.get("name", "")).strip()
        if name:
            assert name == to_title_case(name), (
                f"Zone '{zone.get('zone_id', '?')}' name '{name}' is not title-cased."
            )


def test_all_room_titles_are_title_cased() -> None:
    assets.load_rooms.cache_clear()
    for room in assets.load_rooms():
        title = str(room.get("title", "")).strip()
        if title:
            assert title == to_title_case(title), (
                f"Room '{room.get('room_id', '?')}' title '{title}' is not title-cased."
            )
