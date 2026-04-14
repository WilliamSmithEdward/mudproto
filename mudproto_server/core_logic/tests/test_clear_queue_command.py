import asyncio

from commands import process_input_message
from models import ClientSession, QueuedCommand
from protocol import utc_now_iso


def _make_session(client_id: str, name: str) -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    return session


def _input_message(text: str) -> dict:
    return {
        "type": "input",
        "payload": {
            "text": text,
        },
    }


def _flatten_display_lines(outbound: dict) -> str:
    payload = outbound.get("payload", {})
    lines = payload.get("lines", []) if isinstance(payload, dict) else []

    rendered: list[str] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        rendered.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))

    return "\n".join(rendered)


def test_clear_aliases_clear_queued_commands_while_lagged() -> None:
    async def _run() -> None:
        for alias in ("cle", "clea", "clear"):
            session = _make_session(f"client-{alias}", "Lucia")
            session.command_queue.extend([
                QueuedCommand(command_text="north", received_at_iso=utc_now_iso()),
                QueuedCommand(command_text="bash goblin", received_at_iso=utc_now_iso()),
            ])
            session.lag_until_monotonic = asyncio.get_running_loop().time() + 10.0

            outbound = await process_input_message(_input_message(alias), session)

            assert isinstance(outbound, dict)
            assert outbound.get("type") == "display"
            assert session.command_queue == []
            assert "Cleared 2 queued commands." in _flatten_display_lines(outbound)

    asyncio.run(_run())


def test_cl_is_not_treated_as_clear_while_lagged() -> None:
    async def _run() -> None:
        session = _make_session("client-cl", "Lucia")
        session.lag_until_monotonic = asyncio.get_running_loop().time() + 10.0

        outbound = await process_input_message(_input_message("cl north"), session)

        assert isinstance(outbound, dict)
        assert outbound.get("type") == "noop"
        assert [queued.command_text for queued in session.command_queue] == ["cl north"]

    asyncio.run(_run())
