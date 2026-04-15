import json
from pathlib import Path

import pytest

import assets
import world_population
from combat_state import spawn_corpse_for_entity
from corpse_labels import build_corpse_label
from models import ClientSession, CombatState, PlayerState, PlayerStatus
from protocol import utc_now_iso


ROOM_ID = "start"


def _make_session() -> ClientSession:
    session = ClientSession(client_id="test-client", websocket=None, connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.player = PlayerState(current_room_id=ROOM_ID, class_id="", level=1)
    session.status = PlayerStatus()
    session.combat = CombatState()
    return session


def _build_template() -> dict:
    return {
        "npc_id": "npc.test-drop-rules",
        "name": "Drop Rules Tester",
        "hit_points": 100,
        "max_hit_points": 100,
        "respawn": False,
        "main_hand_weapon": {
            "template_id": "weapon.training-sword",
            "spawn_chance": 100,
            "drop_on_death": 0,
        },
        "off_hand_weapon": {
            "template_id": "weapon.scout-dagger",
            "spawn_chance": 0,
            "drop_on_death": 100,
        },
        "inventory_items": [
            {
                "template_id": "item.potion.mending",
                "quantity": 1,
                "spawn_chance": 100,
            },
            {
                "template_id": "item.potion.mana",
                "quantity": 1,
                "spawn_chance": 0,
            },
        ],
    }


def test_entity_build_respects_spawn_chances(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)

    entity = world_population._build_entity_from_template(_build_template(), ROOM_ID, 1)

    assert entity.main_hand_weapon_template_id == "weapon.training-sword"
    assert entity.off_hand_weapon_template_id == ""
    assert [item.template_id for item in entity.inventory_items] == ["item.potion.mending"]


def test_entity_build_preserves_explicit_is_named_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)
    template = _build_template()
    template["name"] = "Brother Cleft"
    template["is_named"] = True

    entity = world_population._build_entity_from_template(template, ROOM_ID, 1)

    assert entity.is_named is True


def test_entity_build_defaults_is_named_to_false_when_flag_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)
    template = _build_template()
    template["name"] = "Seln of the Pins"
    template.pop("is_named", None)

    entity = world_population._build_entity_from_template(template, ROOM_ID, 1)

    assert entity.is_named is False


def test_named_npc_corpse_uses_full_name_possessive_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)
    session = _make_session()
    template = _build_template()
    template["name"] = "Brother Cleft"
    template["is_named"] = True

    entity = world_population._build_entity_from_template(template, ROOM_ID, 1)
    corpse = spawn_corpse_for_entity(session, entity)

    assert build_corpse_label(corpse.source_name, corpse.corpse_label_style, is_named=corpse.is_named) == "Brother Cleft's corpse"


def test_spawn_corpse_respects_drop_on_death(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)
    session = _make_session()

    template = _build_template()
    template["off_hand_weapon"]["spawn_chance"] = 100
    entity = world_population._build_entity_from_template(template, ROOM_ID, 1)

    corpse = spawn_corpse_for_entity(session, entity)
    dropped_template_ids = {item.template_id for item in corpse.loot_items.values()}

    assert "weapon.training-sword" not in dropped_template_ids
    assert "weapon.scout-dagger" in dropped_template_ids
    assert "item.potion.mending" in dropped_template_ids


def test_inventory_does_not_duplicate_equipped_weapon_loot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world_population.random, "random", lambda: 0.0)
    session = _make_session()

    template = _build_template()
    template["inventory_items"] = [
        {
            "template_id": "weapon.training-sword",
            "quantity": 1,
            "spawn_chance": 100,
        },
        {
            "template_id": "item.potion.mending",
            "quantity": 1,
            "spawn_chance": 100,
        },
    ]

    entity = world_population._build_entity_from_template(template, ROOM_ID, 1)
    assert [item.template_id for item in entity.inventory_items] == ["item.potion.mending"]

    corpse = spawn_corpse_for_entity(session, entity)
    dropped_template_ids = {item.template_id for item in corpse.loot_items.values()}

    assert "weapon.training-sword" not in dropped_template_ids
    assert "item.potion.mending" in dropped_template_ids


def test_load_npc_templates_rejects_legacy_loot_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    npcs_path = tmp_path / "npcs.json"
    npcs_path.write_text(
        json.dumps({
            "npcs": [
                {
                    "npc_id": "npc.test-legacy-loot",
                    "name": "Legacy Loot Tester",
                    "hit_points": 10,
                    "max_hit_points": 10,
                    "loot_items": [{"name": "old coin", "keywords": ["coin"]}],
                }
            ]
        }),
        encoding="utf-8",
    )
    payload_dir = tmp_path / "asset_payloads"
    payload_dir.mkdir()

    monkeypatch.setattr(assets, "NPCS_FILE", npcs_path)
    monkeypatch.setattr(assets, "ASSET_PAYLOADS_DIR", payload_dir)
    assets.load_npc_templates.cache_clear()
    assets._load_asset_payload_documents.cache_clear()

    with pytest.raises(ValueError, match="loot_items is no longer supported"):
        assets.load_npc_templates()

    assets.load_npc_templates.cache_clear()
    assets._load_asset_payload_documents.cache_clear()
