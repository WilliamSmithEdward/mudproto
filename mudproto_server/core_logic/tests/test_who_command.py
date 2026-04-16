import asyncio

from commands import process_input_message
from models import ClientSession
from protocol import utc_now_iso
from session_registry import connected_clients


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


def _flatten_prompt_lines(outbound: dict) -> str:
    payload = outbound.get("payload", {})
    prompt_lines = payload.get("prompt_lines", []) if isinstance(payload, dict) else []

    rendered: list[str] = []
    for line in prompt_lines:
        if not isinstance(line, list):
            continue
        rendered.append("".join(str(part.get("text", "")) for part in line if isinstance(part, dict)))

    return "\n".join(rendered)


def test_who_lists_online_players_and_supports_wh_alias(monkeypatch) -> None:
    async def _run() -> None:
        connected_clients.clear()
        monkeypatch.setattr("settings.PAGINATE_TO", 10)

        lucia = _make_session("client-lucia", "Lucia")
        brom = _make_session("client-brom", "Brom")
        aerin = _make_session("client-aerin", "Aerin")
        connected_clients.update({
            lucia.client_id: lucia,
            brom.client_id: brom,
            aerin.client_id: aerin,
        })

        outbound = await process_input_message(_input_message("wh"), lucia)
        rendered = _flatten_display_lines(outbound)

        assert "Players Online" in rendered
        assert "Aerin" in rendered
        assert "Brom" in rendered
        assert "Lucia" in rendered
        assert rendered.index("Aerin") < rendered.index("Brom") < rendered.index("Lucia")
        assert _flatten_prompt_lines(outbound)

    asyncio.run(_run())


def test_who_paginates_and_enter_advances_pages(monkeypatch) -> None:
    async def _run() -> None:
        connected_clients.clear()
        monkeypatch.setattr("settings.PAGINATE_TO", 2)

        viewer = _make_session("client-viewer", "Viewer")
        alpha = _make_session("client-alpha", "Alpha")
        bravo = _make_session("client-bravo", "Bravo")
        charlie = _make_session("client-charlie", "Charlie")
        delta = _make_session("client-delta", "Delta")
        connected_clients.update({
            viewer.client_id: viewer,
            alpha.client_id: alpha,
            bravo.client_id: bravo,
            charlie.client_id: charlie,
            delta.client_id: delta,
        })

        first_page = await process_input_message(_input_message("who"), viewer)
        first_rendered = _flatten_display_lines(first_page)

        assert "Alpha" in first_rendered
        assert "Bravo" in first_rendered
        assert "Charlie" not in first_rendered
        assert "Press Enter" in first_rendered

        second_page = await process_input_message(_input_message("   "), viewer)
        second_rendered = _flatten_display_lines(second_page)

        assert "Charlie" in second_rendered
        assert "Delta" in second_rendered
        assert "Viewer" not in second_rendered
        assert "Press Enter" in second_rendered

        final_page = await process_input_message(_input_message(""), viewer)
        final_rendered = _flatten_display_lines(final_page)

        assert "Viewer" in final_rendered
        assert "Press Enter" not in final_rendered
        assert _flatten_prompt_lines(final_page)

    asyncio.run(_run())
