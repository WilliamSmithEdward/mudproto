from containers import display_container_examination
from models import ClientSession, CorpseState, ItemState
from protocol import utc_now_iso


def _make_session() -> ClientSession:
    session = ClientSession(client_id="client-corpse-exam", websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = "Lucia"
    session.player_state_key = "lucia"
    session.player.current_room_id = "start"
    return session


def _display_text_colors(outbound: dict) -> dict[str, str]:
    payload = outbound.get("payload", {})
    lines = payload.get("lines", [])
    colors: dict[str, str] = {}
    for line in lines:
        if not isinstance(line, list):
            continue
        for part in line:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text", "")).strip()
            if text:
                colors[text] = str(part.get("fg", ""))
    return colors


def _display_lines(outbound: dict) -> list[str]:
    payload = outbound.get("payload", {})
    lines = payload.get("lines", [])
    rendered_lines: list[str] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        rendered_lines.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return rendered_lines


def _find_part_style(outbound: dict, snippet: str) -> tuple[str, bool] | None:
    payload = outbound.get("payload", {})
    lines = payload.get("lines", [])
    for line in lines:
        if not isinstance(line, list):
            continue
        for part in line:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text", ""))
            if snippet in text:
                return str(part.get("fg", "")), bool(part.get("bold", False))
    return None


def test_corpse_examination_uses_standard_container_rules() -> None:
    session = _make_session()
    corpse = CorpseState(
        corpse_id="corpse-1",
        source_entity_id="npc-1",
        source_name="Blackwatch Sentry",
        room_id="start",
        coins=28,
        loot_items={
            "armor-1": ItemState(
                item_id="armor-1",
                name="Blackwatch Cuirass",
                equippable=True,
                slot="armor",
                wear_slot="chest",
            ),
            "item-1": ItemState(
                item_id="item-1",
                name="Shadow Balm",
                item_type="misc",
            ),
        },
    )
    chest = ItemState(
        item_id="chest-1",
        name="Travel Chest",
        item_type="container",
        portable=False,
        container_items={
            "armor-2": ItemState(
                item_id="armor-2",
                name="Blackwatch Cuirass",
                equippable=True,
                slot="armor",
                wear_slot="chest",
            ),
            "item-2": ItemState(
                item_id="item-2",
                name="Shadow Balm",
                item_type="misc",
            ),
        },
    )

    corpse_response = display_container_examination(session, corpse)
    chest_response = display_container_examination(session, chest)
    corpse_colors = _display_text_colors(corpse_response)
    chest_colors = _display_text_colors(chest_response)

    assert corpse_colors["Equipment"] == chest_colors["Equipment"] == "bright_magenta"
    assert corpse_colors["Item"] == chest_colors["Item"] == "bright_yellow"
    assert corpse_colors["Blackwatch Cuirass"] == chest_colors["Blackwatch Cuirass"] == "bright_magenta"
    assert corpse_colors["Shadow Balm"] == chest_colors["Shadow Balm"] == "bright_yellow"
    assert corpse_colors["Open"] == "bright_green"
    assert "Container" not in corpse_colors
    assert "Room" not in corpse_colors
    assert "No" not in corpse_colors


def test_container_description_wraps_within_contents_column() -> None:
    session = _make_session()
    long_description = (
        "A weathered cedar chest bound in dark iron bands rests beneath the loft rafters, "
        "sturdy and too awkward to carry off whole."
    )
    chest = ItemState(
        item_id="chest-2",
        name="Weathered Chest",
        item_type="container",
        can_close=True,
        is_closed=True,
        is_locked=True,
        description=long_description,
    )

    response = display_container_examination(session, chest)
    lines = _display_lines(response)
    text = "\n".join(lines)

    assert "Description" in text
    assert not any(line.strip() == long_description for line in lines)
    assert any("A weathered cedar chest bound in dark iron bands rests" in line for line in lines)
    assert any("beneath the loft rafters, sturdy and too awkward to carry" in line for line in lines)
    assert any("off whole." in line for line in lines)


def test_container_status_and_description_render_below_contents_divider() -> None:
    session = _make_session()
    chest = ItemState(
        item_id="chest-3",
        name="Supply Chest",
        item_type="container",
        description="A broad training chest with neatly sorted supplies.",
        container_items={
            "item-3": ItemState(item_id="item-3", name="Potion of Mending", item_type="potion"),
        },
        coins=24,
    )

    response = display_container_examination(session, chest)
    lines = _display_lines(response)
    divider_indices = [index for index, line in enumerate(lines) if line.strip() and set(line.strip()) == {"-"}]
    status_index = next(index for index, line in enumerate(lines) if "Status" in line)
    description_index = next(index for index, line in enumerate(lines) if "Description" in line)

    assert len(divider_indices) >= 3
    assert any("Potion of Mending" in line for line in lines[:divider_indices[-1]])
    assert status_index > divider_indices[-1]
    assert description_index > status_index


def test_container_wrapped_description_lines_keep_same_style() -> None:
    session = _make_session()
    chest = ItemState(
        item_id="chest-4",
        name="Supply Chest",
        item_type="container",
        description=(
            "A banded supply chest sits open against the wall, stocked with potions, "
            "loose coin, and a prize blade for a promising newcomer."
        ),
    )

    response = display_container_examination(session, chest)
    first_style = _find_part_style(response, "A banded supply chest sits open against the wall")
    second_style = _find_part_style(response, "with potions, loose coin, and a prize blade for a")
    third_style = _find_part_style(response, "promising newcomer.")

    assert first_style is not None
    assert second_style == first_style
    assert third_style == first_style
