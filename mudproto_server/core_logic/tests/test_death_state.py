import time

from display_core import build_part
from models import ClientSession, QueuedCommand
from server_broadcasts import _build_unified_room_round_display, _iter_room_sessions
from session_registry import connected_clients


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    session.next_game_tick_monotonic = time.monotonic() + 60
    return session


def _line_text(line: list[dict]) -> str:
    return "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))


# handle_player_death clears command_queue


def test_handle_player_death_clears_command_queue(monkeypatch) -> None:
    from death import handle_player_death

    session = _make_session("client-death-queue", "Lucia")
    session.command_queue.append(QueuedCommand(command_text="cast regeneration ward", received_at_iso=""))
    session.command_queue.append(QueuedCommand(command_text="stand", received_at_iso=""))
    monkeypatch.setattr("death.save_player_state", lambda _s: None)

    handle_player_death(session)

    assert session.command_queue == []
    assert session.pending_death_logout is True


def test_handle_player_death_sets_pending_death_logout(monkeypatch) -> None:
    from death import handle_player_death

    session = _make_session("client-death-flag", "Lucia")
    monkeypatch.setattr("death.save_player_state", lambda _s: None)

    assert session.pending_death_logout is False
    handle_player_death(session)
    assert session.pending_death_logout is True


# _iter_room_sessions excludes pending_death_logout


def test_iter_room_sessions_excludes_dead_player() -> None:
    alive = _make_session("client-alive", "Orlandu")
    dead = _make_session("client-dead", "Lucia")
    dead.pending_death_logout = True

    previous = dict(connected_clients)
    connected_clients.clear()
    connected_clients[alive.client_id] = alive
    connected_clients[dead.client_id] = dead
    try:
        peers = _iter_room_sessions("start")
        assert alive in peers
        assert dead not in peers
    finally:
        connected_clients.clear()
        connected_clients.update(previous)


# AoE splash line ordering in _build_unified_room_round_display


def _build_actor_result(lines: list[list[dict]], **extra_payload) -> dict:
    """Build a minimal combat round result dict with display lines."""
    return {
        "type": "display",
        "payload": {
            "lines": lines,
            "prompt_lines": [],
            "is_error": False,
            "broadcast_to_room": True,
            **extra_payload,
        },
    }


def test_aoe_splash_inserted_after_ability_lines() -> None:
    """AoE splash for a secondary target appears right after the AoE effect,
    not after all the melee lines."""
    actor = _make_session("client-actor", "Orlandu")
    observer = _make_session("client-obs", "Lucia")

    # Observer-transformed result for Orlandu's round (what Lucia sees)
    # Lines: AoE announcement, AoE effect on primary, melee miss, melee hit
    actor_result = _build_actor_result(
        [
            [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
            [build_part("Orlandu is swallowed in a choking burst of corrupted pollen!")],
            [build_part("A Canker Pixie misses Orlandu.")],
            [build_part("A Canker Pixie stabs Orlandu extremely hard.")],
            [],
        ],
        aoe_secondary_lines={
            observer.client_id: [
                [build_part("You are swallowed in a choking burst of corrupted pollen!")],
            ],
        },
        aoe_splash_retaliation_offset=2,
        room_broadcast_lines=[],
    )

    # The actor result is what the observer sees (already observer-transformed).
    # For the unified display, the observer is NOT the actor.
    # We need _build_room_broadcast_messages to NOT be called for this test,
    # so we simulate by making the observer the actor and testing self-view.
    # Actually, let's test the unified display directly.

    # For a proper test: the actor_result should be the RAW result (primary target view),
    # and the observer view is built by _build_room_broadcast_messages.
    # But since we want to test the AoE insertion logic specifically, let's construct
    # the round results as if the observer messages are already built.

    # Simplest: test with observer as a different player, providing pre-built observer result
    previous = dict(connected_clients)
    connected_clients.clear()
    connected_clients[actor.client_id] = actor
    connected_clients[observer.client_id] = observer
    try:
        # Build unified display for observer. The round_results contain the actor's raw result.
        # Since observer != actor, _build_room_broadcast_messages is called internally.
        # We need the raw result to have room_broadcast_lines for the observer transformation.
        # For simplicity, set room_broadcast_lines to the observer-formatted lines.
        raw_actor_result = _build_actor_result(
            [
                [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
                [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                [build_part("A Canker Pixie misses you.")],
                [build_part("A Canker Pixie stabs you extremely hard.")],
                [],
            ],
            aoe_secondary_lines={
                observer.client_id: [
                    [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                ],
            },
            aoe_splash_retaliation_offset=2,
            room_broadcast_lines=[
                [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
                [build_part("Orlandu is swallowed in a choking burst of corrupted pollen!")],
                [build_part("A Canker Pixie misses Orlandu.")],
                [build_part("A Canker Pixie stabs Orlandu extremely hard.")],
            ],
        )

        unified = _build_unified_room_round_display(
            observer,
            [(actor, raw_actor_result)],
        )

        assert unified is not None
        payload = unified.get("payload")
        assert isinstance(payload, dict)
        lines = payload.get("lines")
        assert isinstance(lines, list)

        line_texts = [_line_text(line) for line in lines if _line_text(line).strip()]

        # AoE splash should appear right after the AoE effect on primary target
        assert "A Canker Pixie casts Corrupted Pollen Burst across the room!" in line_texts[0]
        assert "Orlandu is swallowed" in line_texts[1]
        assert "You are swallowed" in line_texts[2]
        # Melee lines come after
        assert "misses Orlandu" in line_texts[3]
        assert "stabs Orlandu" in line_texts[4]
    finally:
        connected_clients.clear()
        connected_clients.update(previous)


def test_aoe_splash_falls_back_to_end_without_offset() -> None:
    """When no aoe_splash_retaliation_offset is set, AoE splash appends at end."""
    actor = _make_session("client-actor-fb", "Orlandu")
    observer = _make_session("client-obs-fb", "Lucia")

    previous = dict(connected_clients)
    connected_clients.clear()
    connected_clients[actor.client_id] = actor
    connected_clients[observer.client_id] = observer
    try:
        raw_actor_result = _build_actor_result(
            [
                [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
                [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                [build_part("A Canker Pixie misses you.")],
                [],
            ],
            aoe_secondary_lines={
                observer.client_id: [
                    [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                ],
            },
            # No aoe_splash_retaliation_offset — should fall back to end
            room_broadcast_lines=[
                [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
                [build_part("Orlandu is swallowed in a choking burst of corrupted pollen!")],
                [build_part("A Canker Pixie misses Orlandu.")],
            ],
        )

        unified = _build_unified_room_round_display(
            observer,
            [(actor, raw_actor_result)],
        )

        assert unified is not None
        payload = unified.get("payload")
        assert isinstance(payload, dict)
        lines = payload.get("lines")
        assert isinstance(lines, list)

        line_texts = [_line_text(line) for line in lines if _line_text(line).strip()]

        # Without offset, splash goes at the end
        assert "You are swallowed" in line_texts[-1]
    finally:
        connected_clients.clear()
        connected_clients.update(previous)


def test_aoe_splash_not_shown_to_primary_target() -> None:
    """The primary target (actor) should NOT receive AoE splash lines — they
    already see the AoE effect in their own round."""
    actor = _make_session("client-primary", "Orlandu")
    observer = _make_session("client-secondary", "Lucia")

    previous = dict(connected_clients)
    connected_clients.clear()
    connected_clients[actor.client_id] = actor
    connected_clients[observer.client_id] = observer
    try:
        raw_actor_result = _build_actor_result(
            [
                [build_part("A Canker Pixie casts Corrupted Pollen Burst across the room!")],
                [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                [build_part("A Canker Pixie misses you.")],
                [],
            ],
            aoe_secondary_lines={
                observer.client_id: [
                    [build_part("You are swallowed in a choking burst of corrupted pollen!")],
                ],
            },
            aoe_splash_retaliation_offset=2,
        )

        unified = _build_unified_room_round_display(
            actor,
            [(actor, raw_actor_result)],
        )

        assert unified is not None
        payload = unified.get("payload")
        assert isinstance(payload, dict)
        lines = payload.get("lines")
        assert isinstance(lines, list)

        all_text = " ".join(_line_text(line) for line in lines)
        # Primary target should see their own "You are swallowed" (from their round),
        # but NOT the observer's splash. Count occurrences:
        assert all_text.count("You are swallowed") == 1
    finally:
        connected_clients.clear()
        connected_clients.update(previous)
