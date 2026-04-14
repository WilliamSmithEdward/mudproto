from command_handlers.observation import handle_observation_command
from models import ClientSession


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
        assert "Shhh... You are asleep." in _extract_display_text(outbound)


def test_sleeping_does_not_block_non_observation_verbs() -> None:
    session = _make_session("client-observe-metadata", "Lucia")
    session.is_sleeping = True

    for verb in ("score", "eq", "inv", "sk"):
        outbound = handle_observation_command(session, verb, [], verb)
        assert outbound is None
