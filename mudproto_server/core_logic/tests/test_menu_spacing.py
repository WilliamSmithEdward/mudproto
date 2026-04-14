import command_handlers.skills as skills
import command_handlers.spells as spells
import command_handlers.character as character
from models import ClientSession, ItemState


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _leading_blank_line_count(outbound: dict | list[dict]) -> int:
    message = outbound[0] if isinstance(outbound, list) and outbound else outbound
    if not isinstance(message, dict):
        return 0

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return 0

    raw_lines = payload.get("lines", [])
    if not isinstance(raw_lines, list):
        return 0

    count = 0
    for line in raw_lines:
        if isinstance(line, list) and len(line) == 0:
            count += 1
            continue
        break
    return count


def test_skills_menu_has_single_leading_blank_line(monkeypatch) -> None:
    monkeypatch.setattr(
        skills,
        "_list_known_skills",
        lambda _session: [{"name": "Jab", "vigor_cost": 4}],
    )

    session = _make_session("client-skills-spacing", "Lucia")
    response = skills.handle_skill_command(session, "skills", [], "skills")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_skills_empty_message_has_single_leading_blank_line(monkeypatch) -> None:
    monkeypatch.setattr(skills, "_list_known_skills", lambda _session: [])

    session = _make_session("client-skills-spacing-empty", "Lucia")
    response = skills.handle_skill_command(session, "skills", [], "skills")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_spells_menu_has_single_leading_blank_line(monkeypatch) -> None:
    monkeypatch.setattr(
        spells,
        "_list_known_spells",
        lambda _session: [{"name": "Spark", "school": "Evocation", "mana_cost": 6}],
    )

    session = _make_session("client-spells-spacing", "Lucia")
    response = spells.handle_spell_command(session, "spells", [], "spells")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_spells_empty_message_has_single_leading_blank_line(monkeypatch) -> None:
    monkeypatch.setattr(spells, "_list_known_spells", lambda _session: [])

    session = _make_session("client-spells-spacing-empty", "Lucia")
    response = spells.handle_spell_command(session, "spells", [], "spells")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_inventory_menu_has_single_leading_blank_line_empty() -> None:
    session = _make_session("client-inventory-spacing-empty", "Lucia")
    response = character.handle_character_command(session, "inventory", [], "inventory")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_inventory_menu_has_single_leading_blank_line_populated() -> None:
    session = _make_session("client-inventory-spacing", "Lucia")
    session.inventory_items["item-1"] = ItemState(item_id="item-1", name="Training Dagger")

    response = character.handle_character_command(session, "inventory", [], "inventory")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_equipment_menu_has_single_leading_blank_line_empty() -> None:
    session = _make_session("client-equipment-spacing-empty", "Lucia")
    response = character.handle_character_command(session, "equipment", [], "equipment")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1


def test_equipment_menu_has_single_leading_blank_line_populated() -> None:
    session = _make_session("client-equipment-spacing", "Lucia")
    item = ItemState(item_id="item-robe", name="Monk Robe", slot="armor", wear_slot="chest")
    session.equipment.equipped_items[item.item_id] = item
    session.equipment.worn_item_ids["chest"] = item.item_id

    response = character.handle_character_command(session, "equipment", [], "equipment")

    assert isinstance(response, dict)
    assert _leading_blank_line_count(response) == 1
