import command_handlers.observation as observation
from command_handlers.observation import handle_observation_command
from models import ClientSession, ItemState
from world import Room


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _extract_display_text(outbound: dict | list[dict]) -> str:
    messages = outbound if isinstance(outbound, list) else [outbound]
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "display":
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        raw_lines = payload.get("lines", [])
        if not isinstance(raw_lines, list):
            continue
        for line in raw_lines:
            if not isinstance(line, list):
                continue
            lines.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))
    return "\n".join(lines)


def test_sleeping_blocks_look_scan_and_examine() -> None:
    session = _make_session("client-observe-sleep", "Lucia")
    session.is_sleeping = True

    for verb, args in (("look", []), ("scan", []), ("examine", ["sword"])):
        outbound = handle_observation_command(session, verb, list(args), f"{verb} {' '.join(args)}".strip())
        assert isinstance(outbound, dict)
        assert "Shhh... You are asleep. Use wake first." in _extract_display_text(outbound)


def test_sleeping_does_not_block_non_observation_verbs() -> None:
    session = _make_session("client-observe-metadata", "Lucia")
    session.is_sleeping = True

    for verb in ("score", "eq", "inv", "sk"):
        outbound = handle_observation_command(session, verb, [], verb)
        assert outbound is None


def test_look_direction_prefixes_take_precedence_over_matching_targets(monkeypatch) -> None:
    session = _make_session("client-observe-direction", "Lucia")
    monkeypatch.setattr(observation, "get_room", lambda _room_id: Room(room_id="start", title="Start", description="A room."))
    monkeypatch.setattr(observation, "_resolve_owned_item_selector", lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(observation, "_resolve_room_ground_item_selector", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(observation, "resolve_room_object_selector", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(observation, "resolve_room_entity_selector", lambda *_args, **_kwargs: (None, "entity fallback should not win"))
    monkeypatch.setattr(observation, "resolve_room_corpse_selector", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(observation, "_resolve_room_player_selector", lambda *_args, **_kwargs: (object(), None))
    monkeypatch.setattr(observation, "display_player_summary", lambda *_args, **_kwargs: {"type": "display", "payload": {"lines": [[{"text": "PLAYER TARGET", "fg": "bright_white", "bold": False}]], "prompt_lines": []}})

    expected_messages = {
        "n": "You peer to the north, but nothing there draws your eye.",
        "no": "You peer to the north, but nothing there draws your eye.",
        "nor": "You peer to the north, but nothing there draws your eye.",
        "nort": "You peer to the north, but nothing there draws your eye.",
        "north": "You peer to the north, but nothing there draws your eye.",
        "s": "You peer to the south, but nothing there draws your eye.",
        "so": "You peer to the south, but nothing there draws your eye.",
        "sou": "You peer to the south, but nothing there draws your eye.",
        "sout": "You peer to the south, but nothing there draws your eye.",
        "south": "You peer to the south, but nothing there draws your eye.",
        "e": "You peer to the east, but nothing there draws your eye.",
        "ea": "You peer to the east, but nothing there draws your eye.",
        "eas": "You peer to the east, but nothing there draws your eye.",
        "east": "You peer to the east, but nothing there draws your eye.",
        "w": "You peer to the west, but nothing there draws your eye.",
        "we": "You peer to the west, but nothing there draws your eye.",
        "wes": "You peer to the west, but nothing there draws your eye.",
        "west": "You peer to the west, but nothing there draws your eye.",
        "u": "You lift your gaze overhead, but nothing there answers your attention.",
        "up": "You lift your gaze overhead, but nothing there answers your attention.",
        "d": "You glance below, but nothing there reveals itself.",
        "do": "You glance below, but nothing there reveals itself.",
        "dow": "You glance below, but nothing there reveals itself.",
        "down": "You glance below, but nothing there reveals itself.",
    }

    for selector, expected_text in expected_messages.items():
        outbound = handle_observation_command(session, "look", [selector], f"look {selector}")
        rendered = _extract_display_text(outbound)
        assert expected_text in rendered
        assert "PLAYER TARGET" not in rendered


def test_look_and_examine_do_not_match_hidden_wear_slot_keywords(monkeypatch) -> None:
    session = _make_session("client-observe-slot", "Lucia")
    worn_armor = ItemState(
        item_id="armor-1",
        name="Blackwatch Cuirass",
        equippable=True,
        slot="armor",
        wear_slot="chest",
        wear_slots=["chest"],
        keywords=["blackwatch", "cuirass", "chest"],
    )
    session.equipment.equipped_items[worn_armor.item_id] = worn_armor
    session.equipment.worn_item_ids["chest"] = worn_armor.item_id
    session.room_ground_items["start"] = {
        "chest-1": ItemState(
            item_id="chest-1",
            name="Travel Chest",
            item_type="container",
            portable=False,
        )
    }

    monkeypatch.setattr(observation, "get_room", lambda _room_id: Room(room_id="start", title="Start", description="A room."))

    look_outbound = handle_observation_command(session, "look", ["chest"], "look chest")
    examine_outbound = handle_observation_command(session, "examine", ["chest"], "examine chest")

    look_text = _extract_display_text(look_outbound)
    examine_text = _extract_display_text(examine_outbound)

    assert "Travel Chest" in look_text
    assert "Travel Chest" in examine_text
    assert "Blackwatch Cuirass" not in look_text
    assert "Blackwatch Cuirass" not in examine_text
