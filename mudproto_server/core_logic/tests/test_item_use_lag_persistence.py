import item_logic
from command_handlers.item_actions import handle_item_use_command
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


def _render_text(outbound: dict) -> str:
    payload = outbound.get("payload", {})
    lines = payload.get("lines", [])
    rendered_lines: list[str] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        rendered_lines.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(rendered_lines)


def test_quaff_aliases_delegate_to_item_use(monkeypatch) -> None:
    session = _make_session("client-quaff-aliases", "Lucia")

    captured_calls: list[str] = []

    def _fake_use(_session, selector: str, *, verb: str = "use") -> dict:
        captured_calls.append(f"{verb}:{selector}")
        return {"ok": True}

    monkeypatch.setattr("command_handlers.item_actions._use_misc_item", _fake_use)

    for verb in ["use", "qu", "qua", "quaf", "quaff"]:
        result = handle_item_use_command(session, verb, ["potion", "of", "mana"], f"{verb} potion of mana")
        assert result == {"ok": True}

    assert captured_calls == [
        "use:potion.of.mana",
        "qu:potion.of.mana",
        "qua:potion.of.mana",
        "quaf:potion.of.mana",
        "quaff:potion.of.mana",
    ]


def test_quaff_rejects_non_potion_items(monkeypatch) -> None:
    session = _make_session("client-quaff-non-potion", "Lucia")
    session.status.vigor = 10

    item = ItemState(item_id="item-tonic", name="Tonic")
    session.inventory_items[item.item_id] = item

    monkeypatch.setattr(item_logic, "_resolve_misc_inventory_selector", lambda _session, _selector: (item, None))
    monkeypatch.setattr(
        item_logic,
        "_find_item_template_for_misc_item",
        lambda _item: {
            "name": "Tonic",
            "item_type": "consumable",
            "effect_type": "restore",
            "effect_target": "vigor",
            "effect_amount": 5,
            "use_lag_seconds": 0.0,
        },
    )
    monkeypatch.setattr(item_logic, "hydrate_misc_item_from_template", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(item_logic, "get_player_resource_caps", lambda _session: {"hit_points": 100, "vigor": 100, "mana": 100})

    outbound = handle_item_use_command(session, "quaff", ["tonic"], "quaff tonic")

    assert isinstance(outbound, dict)
    assert "only quaff potions" in _render_text(outbound).lower()
    assert item.item_id in session.inventory_items


def test_potion_item_type_enables_quaff_and_cooldown(monkeypatch) -> None:
    session = _make_session("client-quaff-potion-type", "Lucia")
    session.status.vigor = 10

    item = ItemState(item_id="item-draught", name="Battle Draught")
    session.inventory_items[item.item_id] = item

    monkeypatch.setattr(item_logic, "_resolve_misc_inventory_selector", lambda _session, _selector: (item, None))
    monkeypatch.setattr(
        item_logic,
        "_find_item_template_for_misc_item",
        lambda _item: {
            "name": "Battle Draught",
            "item_type": "potion",
            "effect_type": "restore",
            "effect_target": "vigor",
            "effect_amount": 5,
            "use_lag_seconds": 0.0,
        },
    )
    monkeypatch.setattr(item_logic, "hydrate_misc_item_from_template", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(item_logic, "get_player_resource_caps", lambda _session: {"hit_points": 100, "vigor": 100, "mana": 100})
    monkeypatch.setattr(item_logic, "_get_potion_cooldown_rounds", lambda: 2)

    outbound = item_logic._use_misc_item(session, "battle draught", verb="quaff")

    assert isinstance(outbound, dict)
    assert item.item_id not in session.inventory_items
    assert session.status.vigor == 15
    assert session.combat.potion_cooldown_until > 0


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
