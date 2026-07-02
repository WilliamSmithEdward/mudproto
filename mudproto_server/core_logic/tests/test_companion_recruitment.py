import pytest

import assets
from assets import load_npc_templates
from command_handlers.recruitment import handle_recruitment_command
from models import ClientSession, EntityState
from protocol import utc_now_iso
from session_registry import shared_world_entities


def _make_session(client_id: str, name: str) -> ClientSession:
    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.is_connected = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "south-market"
    session.entities = shared_world_entities
    return session


def _make_recruiter(room_id: str = "south-market") -> EntityState:
    recruiter = EntityState(
        entity_id="recruiter-1",
        name="Sergeant Halda Brakk",
        room_id=room_id,
        hit_points=200,
        max_hit_points=200,
    )
    recruiter.is_named = True
    recruiter.is_ally = True
    recruiter.is_peaceful = True
    recruiter.is_recruiter = True
    recruiter.recruitable_companions = [
        {"npc_id": "npc.companion-squire", "price": 150},
        {"npc_id": "npc.companion-field-medic", "price": 300},
    ]
    return recruiter


def _rendered_lines(outbound: dict) -> list[str]:
    return [
        "".join(str(part.get("text", "")) for part in line if isinstance(part, dict))
        for line in outbound.get("payload", {}).get("lines", [])
        if isinstance(line, list)
    ]


def _load_npcs_with(monkeypatch, npcs: list[dict]) -> list[dict]:
    original_read = assets._read_json_asset

    def fake_read(path):
        if path == assets.NPCS_FILE:
            return {"npcs": npcs, "items": []}
        return original_read(path)

    monkeypatch.setattr(assets, "_read_json_asset", fake_read)
    monkeypatch.setattr(assets, "_load_asset_payload_section", lambda section: [])
    load_npc_templates.cache_clear()
    try:
        return load_npc_templates()
    finally:
        load_npc_templates.cache_clear()


def test_base_content_defines_recruiter_and_companion_templates() -> None:
    templates_by_id = {template["npc_id"]: template for template in load_npc_templates()}

    recruiter = templates_by_id["npc.muster-sergeant"]
    assert recruiter["is_recruiter"] is True
    assert {entry["npc_id"] for entry in recruiter["recruitable_companions"]} == {
        "npc.companion-squire",
        "npc.companion-field-medic",
    }

    for companion_npc_id in ("npc.companion-squire", "npc.companion-field-medic"):
        companion = templates_by_id[companion_npc_id]
        assert companion["is_companion"] is True
        assert companion["is_ally"] is True
        assert companion["respawn"] is False


def test_recruiter_without_roster_fails_validation(monkeypatch) -> None:
    with pytest.raises(ValueError, match="must define recruitable_companions"):
        _load_npcs_with(monkeypatch, [
            {"npc_id": "npc.test-recruiter", "name": "Test Recruiter", "hit_points": 10, "is_recruiter": True},
        ])


def test_recruiter_with_unknown_companion_fails_validation(monkeypatch) -> None:
    with pytest.raises(ValueError, match="unknown recruitable companion"):
        _load_npcs_with(monkeypatch, [
            {
                "npc_id": "npc.test-recruiter",
                "name": "Test Recruiter",
                "hit_points": 10,
                "is_recruiter": True,
                "recruitable_companions": [{"npc_id": "npc.missing", "price": 10}],
            },
        ])


def test_recruiter_referencing_non_companion_fails_validation(monkeypatch) -> None:
    with pytest.raises(ValueError, match="must set is_companion to true"):
        _load_npcs_with(monkeypatch, [
            {"npc_id": "npc.test-bystander", "name": "Test Bystander", "hit_points": 10},
            {
                "npc_id": "npc.test-recruiter",
                "name": "Test Recruiter",
                "hit_points": 10,
                "is_recruiter": True,
                "recruitable_companions": [{"npc_id": "npc.test-bystander", "price": 10}],
            },
        ])


def test_companion_template_must_disable_respawn(monkeypatch) -> None:
    with pytest.raises(ValueError, match="must set respawn to false"):
        _load_npcs_with(monkeypatch, [
            {"npc_id": "npc.test-companion", "name": "Test Companion", "hit_points": 10, "is_companion": True},
        ])


def test_recruits_menu_renders_with_single_leading_blank_line() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("recruit-menu-client", "Menutester")
        recruiter = _make_recruiter()
        shared_world_entities[recruiter.entity_id] = recruiter

        outbound = handle_recruitment_command(session, "recruits", [], "recruits")

        lines = outbound["payload"]["lines"]
        assert lines[0] == []
        assert lines[1] != []

        rendered = "\n".join(_rendered_lines(outbound))
        assert "Sergeant Halda Brakk's Recruits" in rendered
        assert "Bramble Squire" in rendered
        assert "150 coins" in rendered
        assert "Field Medic Ora" in rendered
        assert "300 coins" in rendered
        assert "enlist <name>" in rendered
        assert "dismiss <name>" in rendered
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_recruits_menu_requires_recruiter_in_room() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("no-recruiter-client", "Lonelytester")

        outbound = handle_recruitment_command(session, "recruits", [], "recruits")

        assert outbound["payload"]["is_error"] is True
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_enlist_debits_coins_and_spawns_owned_companion() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("enlist-client", "Enlisttester")
        session.status.coins = 500
        recruiter = _make_recruiter()
        shared_world_entities[recruiter.entity_id] = recruiter

        outbound = handle_recruitment_command(session, "enlist", ["bramble"], "enlist bramble")

        assert outbound["payload"].get("is_error") is not True
        assert session.status.coins == 350
        assert len(session.companion_roster) == 1
        assert session.companion_roster[0]["npc_id"] == "npc.companion-squire"

        companions = [entity for entity in shared_world_entities.values() if entity.is_companion]
        assert len(companions) == 1
        companion = companions[0]
        assert companion.owner_player_key == "enlisttester"
        assert companion.room_id == "south-market"
        assert companion.respawn is False
        assert companion.is_ally is True
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_enlist_fails_without_enough_coins() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("poor-client", "Poortester")
        session.status.coins = 10
        recruiter = _make_recruiter()
        shared_world_entities[recruiter.entity_id] = recruiter

        outbound = handle_recruitment_command(session, "enlist", ["bramble"], "enlist bramble")

        assert outbound["payload"]["is_error"] is True
        assert session.status.coins == 10
        assert session.companion_roster == []
        assert not any(entity.is_companion for entity in shared_world_entities.values())
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_enlist_respects_companion_cap() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("capped-client", "Captester")
        session.status.coins = 5000
        session.companion_roster = [
            {"npc_id": "npc.companion-squire", "name": "Bramble Squire"},
            {"npc_id": "npc.companion-field-medic", "name": "Field Medic Ora"},
        ]
        recruiter = _make_recruiter()
        shared_world_entities[recruiter.entity_id] = recruiter

        outbound = handle_recruitment_command(session, "enlist", ["bramble"], "enlist bramble")

        assert outbound["payload"]["is_error"] is True
        assert session.status.coins == 5000
        assert len(session.companion_roster) == 2
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_dismiss_removes_companion_and_roster_entry() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("dismiss-client", "Dismisstester")
        session.status.coins = 500
        recruiter = _make_recruiter()
        shared_world_entities[recruiter.entity_id] = recruiter
        handle_recruitment_command(session, "enlist", ["bramble"], "enlist bramble")
        assert len(session.companion_roster) == 1

        outbound = handle_recruitment_command(session, "dismiss", ["bramble"], "dismiss bramble")

        assert outbound["payload"].get("is_error") is not True
        assert session.companion_roster == []
        assert not any(entity.is_companion for entity in shared_world_entities.values())
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)


def test_companion_template_must_be_ally(monkeypatch) -> None:
    with pytest.raises(ValueError, match="must set is_ally to true"):
        _load_npcs_with(monkeypatch, [
            {
                "npc_id": "npc.test-companion",
                "name": "Test Companion",
                "hit_points": 10,
                "is_companion": True,
                "respawn": False,
            },
        ])


def test_companion_with_skills_requires_vigor_pool(monkeypatch) -> None:
    with pytest.raises(ValueError, match="no max_vigor pool"):
        _load_npcs_with(monkeypatch, [
            {
                "npc_id": "npc.test-companion",
                "name": "Test Companion",
                "hit_points": 10,
                "is_companion": True,
                "is_ally": True,
                "respawn": False,
                "skill_ids": ["skill.jab"],
            },
        ])


def test_recruitable_companions_require_recruiter_flag(monkeypatch) -> None:
    with pytest.raises(ValueError, match="must set is_recruiter to true"):
        _load_npcs_with(monkeypatch, [
            {
                "npc_id": "npc.test-companion",
                "name": "Test Companion",
                "hit_points": 10,
                "is_companion": True,
                "is_ally": True,
                "respawn": False,
            },
            {
                "npc_id": "npc.test-bystander",
                "name": "Test Bystander",
                "hit_points": 10,
                "recruitable_companions": [{"npc_id": "npc.test-companion", "price": 10}],
            },
        ])


def test_rooms_may_not_spawn_companion_templates(monkeypatch) -> None:
    from assets import load_rooms

    original_read = assets._read_json_asset

    def fake_read(path):
        if path == assets.ROOMS_FILE:
            return [
                {
                    "room_id": "test-companion-room",
                    "name": "Test Companion Room",
                    "description": "A test room.",
                    "zone_id": "zone.prototype-core",
                    "npcs": [{"npc_id": "npc.companion-squire", "count": 1}],
                },
            ]
        return original_read(path)

    monkeypatch.setattr(assets, "_read_json_asset", fake_read)
    monkeypatch.setattr(assets, "_load_asset_payload_section", lambda section: [])
    load_rooms.cache_clear()
    try:
        with pytest.raises(ValueError, match="may not reference companion template"):
            load_rooms()
    finally:
        load_rooms.cache_clear()


def test_dismiss_of_remote_companion_skips_room_broadcast() -> None:
    previous_entities = dict(shared_world_entities)
    try:
        shared_world_entities.clear()
        session = _make_session("remote-dismiss-client", "Remotedismisser")
        companion = EntityState(
            entity_id="companion-remote",
            name="Bramble Squire",
            room_id="hall",
            hit_points=140,
            max_hit_points=140,
        )
        companion.npc_id = "npc.companion-squire"
        companion.is_named = True
        companion.is_companion = True
        companion.is_ally = True
        companion.owner_player_key = "remotedismisser"
        shared_world_entities[companion.entity_id] = companion
        session.companion_roster = [{"npc_id": "npc.companion-squire", "name": "Bramble Squire"}]

        outbound = handle_recruitment_command(session, "dismiss", ["bramble"], "dismiss bramble")

        assert outbound["payload"].get("is_error") is not True
        assert "broadcast_to_room" not in outbound["payload"]
        assert session.companion_roster == []
        assert companion.entity_id not in shared_world_entities
    finally:
        shared_world_entities.clear()
        shared_world_entities.update(previous_entities)
