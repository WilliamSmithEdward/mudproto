import item_logic
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


def test_item_use_lag_applies_out_of_combat(monkeypatch) -> None:
    session = _make_session("client-item-lag", "Lucia")
    session.combat.engaged_entity_ids.clear()
    session.status.vigor = 10

    item = ItemState(item_id="item-tonic", name="Tonic")
    session.inventory_items[item.item_id] = item

    monkeypatch.setattr(item_logic, "_resolve_misc_inventory_selector", lambda _session, _selector: (item, None))
    monkeypatch.setattr(
        item_logic,
        "_find_item_template_for_misc_item",
        lambda _item: {
            "name": "Tonic",
            "effect_type": "restore",
            "effect_target": "vigor",
            "effect_amount": 5,
            "use_lag_seconds": 3.0,
        },
    )
    monkeypatch.setattr(item_logic, "hydrate_misc_item_from_template", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(item_logic, "get_player_resource_caps", lambda _session: {"hit_points": 100, "vigor": 100, "mana": 100})

    lag_calls: list[float] = []
    monkeypatch.setattr(item_logic, "apply_lag", lambda _session, duration_seconds: lag_calls.append(duration_seconds))

    outbound = item_logic._use_misc_item(session, "tonic")

    assert isinstance(outbound, dict)
    assert lag_calls == [3.0]
