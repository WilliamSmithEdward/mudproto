from containers import resolve_accessible_container, take_item_from_container
from models import ClientSession, CorpseState, EntityState, ItemState
from protocol import utc_now_iso
from session_registry import shared_world_corpses, shared_world_entities, shared_world_room_ground_items
from targeting_entities import resolve_room_corpse_selector, resolve_room_entity_selector
from targeting_items import _resolve_inventory_selector, _resolve_room_ground_item_selector


def _make_session() -> ClientSession:
    session = ClientSession(client_id="client-selector-order", websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = "Lucia"
    session.player_state_key = "lucia"
    session.player.current_room_id = "start"
    session.corpses = shared_world_corpses
    session.entities = shared_world_entities
    session.room_ground_items = shared_world_room_ground_items
    return session


def test_resolve_room_corpse_selector_uses_newest_first_ordering() -> None:
    session = _make_session()
    session.corpses.clear()
    session.corpses["corpse-c"] = CorpseState(
        corpse_id="corpse-c",
        source_entity_id="npc-c",
        source_name="Crow Scout",
        room_id="start",
        spawn_sequence=1,
    )
    session.corpses["corpse-a"] = CorpseState(
        corpse_id="corpse-a",
        source_entity_id="npc-a",
        source_name="Crow Scout",
        room_id="start",
        spawn_sequence=2,
    )
    session.corpses["corpse-b"] = CorpseState(
        corpse_id="corpse-b",
        source_entity_id="npc-b",
        source_name="Crow Scout",
        room_id="start",
        spawn_sequence=3,
    )

    newest, error = resolve_room_corpse_selector(session, "start", "1.corpse")
    middle, _ = resolve_room_corpse_selector(session, "start", "2.corpse")
    oldest, _ = resolve_room_corpse_selector(session, "start", "3.corpse")

    assert error is None
    assert newest is not None and newest.corpse_id == "corpse-b"
    assert middle is not None and middle.corpse_id == "corpse-a"
    assert oldest is not None and oldest.corpse_id == "corpse-c"


def test_resolve_inventory_selector_uses_newest_first_ordering() -> None:
    session = _make_session()
    session.inventory_items.clear()
    session.inventory_items["potion-old"] = ItemState(item_id="potion-old", name="Potion of Mana", item_type="potion")
    session.inventory_items["potion-mid"] = ItemState(item_id="potion-mid", name="Potion of Mana", item_type="potion")
    session.inventory_items["potion-new"] = ItemState(item_id="potion-new", name="Potion of Mana", item_type="potion")

    newest, error = _resolve_inventory_selector(session, "1.potion")
    middle, _ = _resolve_inventory_selector(session, "2.potion")
    oldest, _ = _resolve_inventory_selector(session, "3.potion")

    assert error is None
    assert newest is not None and newest.item_id == "potion-new"
    assert middle is not None and middle.item_id == "potion-mid"
    assert oldest is not None and oldest.item_id == "potion-old"


def test_resolve_room_ground_item_selector_uses_newest_first_ordering() -> None:
    session = _make_session()
    session.room_ground_items.clear()
    session.room_ground_items["start"] = {
        "item-old": ItemState(item_id="item-old", name="Shadow Balm", item_type="misc"),
        "item-mid": ItemState(item_id="item-mid", name="Shadow Balm", item_type="misc"),
        "item-new": ItemState(item_id="item-new", name="Shadow Balm", item_type="misc"),
    }

    newest, error = _resolve_room_ground_item_selector(session, "start", "1.shadow")
    middle, _ = _resolve_room_ground_item_selector(session, "start", "2.shadow")
    oldest, _ = _resolve_room_ground_item_selector(session, "start", "3.shadow")

    assert error is None
    assert newest is not None and newest.item_id == "item-new"
    assert middle is not None and middle.item_id == "item-mid"
    assert oldest is not None and oldest.item_id == "item-old"


def test_resolve_room_entity_selector_uses_newest_first_ordering() -> None:
    session = _make_session()
    session.entities.clear()
    for entity_id, spawn_sequence in (("npc-old", 1), ("npc-mid", 2), ("npc-new", 3)):
        entity = EntityState(entity_id=entity_id, name="Hall Scout", room_id="start", hit_points=10, max_hit_points=10)
        entity.is_alive = True
        entity.spawn_sequence = spawn_sequence
        session.entities[entity_id] = entity

    newest, error = resolve_room_entity_selector(session, "start", "1.scout")
    middle, _ = resolve_room_entity_selector(session, "start", "2.scout")
    oldest, _ = resolve_room_entity_selector(session, "start", "3.scout")

    assert error is None
    assert newest is not None and newest.entity_id == "npc-new"
    assert middle is not None and middle.entity_id == "npc-mid"
    assert oldest is not None and oldest.entity_id == "npc-old"


def test_resolve_accessible_container_uses_newest_first_ordering() -> None:
    session = _make_session()
    session.room_ground_items.clear()
    session.room_ground_items["start"] = {
        "chest-old": ItemState(item_id="chest-old", name="Supply Chest", item_type="container"),
        "chest-new": ItemState(item_id="chest-new", name="Supply Chest", item_type="container"),
    }

    selected, location, error = resolve_accessible_container(session, "1.chest")

    assert error is None
    assert location == "room"
    assert selected is not None and selected.item_id == "chest-new"


def test_take_item_from_container_uses_newest_first_ordering() -> None:
    session = _make_session()
    chest = ItemState(
        item_id="chest-1",
        name="Supply Chest",
        item_type="container",
        container_items={
            "potion-old": ItemState(item_id="potion-old", name="Potion of Mana", item_type="potion"),
            "potion-new": ItemState(item_id="potion-new", name="Potion of Mana", item_type="potion"),
        },
    )

    take_item_from_container(session, chest, "1.potion")

    assert "potion-new" in session.inventory_items
    assert "potion-new" not in chest.container_items
    assert "potion-old" in chest.container_items
