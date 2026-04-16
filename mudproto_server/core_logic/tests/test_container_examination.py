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

    assert corpse_colors["Blackwatch Cuirass"] == chest_colors["Blackwatch Cuirass"] == "bright_magenta"
    assert corpse_colors["Shadow Balm"] == chest_colors["Shadow Balm"] == "bright_yellow"
    assert corpse_colors["Container"] == "bright_yellow"
    assert corpse_colors["No"] == "bright_white"
    assert corpse_colors["Open"] == "bright_green"
