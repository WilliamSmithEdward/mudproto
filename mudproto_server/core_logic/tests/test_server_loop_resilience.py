"""Resilience tests for the core background loops (RG-23).

These verify that a single failure does not permanently stop game timing: the
supervisor restarts a crashed loop, and the game-hour tick keeps running after a
tick body raises.
"""

import asyncio

import server
import server_loops


def test_supervise_loop_restarts_after_crash(monkeypatch) -> None:
    monkeypatch.setattr(server, "LOOP_RESTART_DELAY_SECONDS", 0)
    calls = {"n": 0}

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        await asyncio.Event().wait()  # third run: block until cancelled

    async def run() -> None:
        task = asyncio.create_task(server._supervise_loop(flaky, "flaky"))
        try:
            async with asyncio.timeout(2):
                while calls["n"] < 3:
                    await asyncio.sleep(0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(run())
    assert calls["n"] >= 3


def test_game_tick_loop_survives_failing_tick(monkeypatch) -> None:
    monkeypatch.setattr(server_loops, "GAME_TICK_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(server_loops, "shared_world_entities", {})
    monkeypatch.setattr(server_loops, "repopulate_game_hour_zones", lambda: None)
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise RuntimeError("tick boom")

    monkeypatch.setattr(server_loops, "process_world_item_game_hour_tick", boom)

    async def run() -> None:
        task = asyncio.create_task(server_loops.game_tick_loop())
        try:
            async with asyncio.timeout(2):
                while calls["n"] < 3:
                    await asyncio.sleep(0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    original_anchor = server_loops.next_game_tick_monotonic
    try:
        asyncio.run(run())
    finally:
        server_loops.next_game_tick_monotonic = original_anchor

    assert calls["n"] >= 3
