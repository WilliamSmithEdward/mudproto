import combat
from equipment_logic import get_player_effective_attributes, unequip_item, wear_item
from inventory import build_equippable_item_from_template, is_item_equippable
from models import ClientSession, EntityState, ItemState
from player_resources import get_player_resource_caps


def _make_session(client_id: str, name: str) -> ClientSession:
    from protocol import utc_now_iso

    session = ClientSession(client_id=client_id, websocket=object(), connected_at=utc_now_iso())  # type: ignore[arg-type]
    session.is_authenticated = True
    session.authenticated_character_name = name
    session.player_state_key = name.strip().lower()
    session.player.current_room_id = "start"
    session.player.class_id = "class.arcanist"
    session.player.attributes = {"str": 10, "dex": 10, "con": 10, "wis": 10}
    return session


def _equip_item(session: ClientSession, item: ItemState, *, wear_slot: str = "ring") -> None:
    session.equipment.equipped_items[item.item_id] = item
    session.equipment.worn_item_ids[wear_slot] = item.item_id


def test_equipment_effects_raise_caps_and_clamp_attributes() -> None:
    session = _make_session("client-cap", "Lucia")
    session.player.attributes.update({"dex": 27, "con": 27, "wis": 27})
    baseline_caps = get_player_resource_caps(session)

    _equip_item(session, ItemState(
        item_id="item-road-ring",
        template_id="armor.test-ring-amber",
        name="Road Ring",
        equippable=True,
        slot="armor",
        wear_slot="ring",
        wear_slots=["ring"],
        equipment_effects=[
            {"effect_type": "dex", "amount": 3},
            {"effect_type": "con", "amount": 1},
            {"effect_type": "con", "amount": 2},
            {"effect_type": "hit_points", "amount": 40},
            {"effect_type": "mana", "amount": 51},
            {"effect_type": "vigor", "amount": 46},
        ],
    ))

    attributes = get_player_effective_attributes(session)
    caps = get_player_resource_caps(session)

    assert attributes["dex"] == 28
    assert attributes["con"] == 28
    assert attributes["wis"] == 27
    assert caps["hit_points"] >= baseline_caps["hit_points"] + 40
    assert caps["vigor"] >= baseline_caps["vigor"] + 46
    assert caps["mana"] >= baseline_caps["mana"] + 51


def test_equipment_hitroll_bonus_applies_to_player_attacks(monkeypatch) -> None:
    session = _make_session("client-hitroll", "Lucia")
    entity = EntityState(entity_id="entity-dummy", name="Dummy", room_id="start", hit_points=100, max_hit_points=100)
    _equip_item(session, ItemState(
        item_id="item-aim-ring",
        name="Aim Ring",
        equippable=True,
        slot="armor",
        wear_slot="ring",
        wear_slots=["ring"],
        equipment_effects=[{"effect_type": "hitroll", "amount": 6}],
    ))

    seen_modifiers: list[int] = []
    monkeypatch.setattr(combat, "roll_hit", lambda modifier, _armor_class: seen_modifiers.append(modifier) or False)

    combat._apply_player_attacks(session, entity, [], [], allow_off_hand=False)

    assert seen_modifiers
    assert seen_modifiers[0] == 6


def test_equipment_weapon_damage_bonus_applies_to_player_attacks(monkeypatch) -> None:
    session = _make_session("client-damage", "Lucia")
    entity = EntityState(entity_id="entity-dummy", name="Dummy", room_id="start", hit_points=100, max_hit_points=100)
    _equip_item(session, ItemState(
        item_id="item-power-ring",
        name="Power Ring",
        equippable=True,
        slot="armor",
        wear_slot="ring",
        wear_slots=["ring"],
        equipment_effects=[{"effect_type": "weapon_damage", "amount": 4}],
    ))

    monkeypatch.setattr(combat, "roll_hit", lambda _modifier, _armor_class: True)
    monkeypatch.setattr(combat, "roll_player_damage", lambda *_args, **_kwargs: (10, "fists", "hit"))

    combat._apply_player_attacks(session, entity, [], [], allow_off_hand=False)

    assert entity.hit_points == 86


def test_equippable_hydration_preserves_equipment_effects() -> None:
    template = {
        "template_id": "armor.test-travel-ring",
        "name": "Travel Ring",
        "slot": "armor",
        "wear_slots": ["ring"],
        "equipment_effects": [
            {"effect_type": "dex", "amount": 2},
            {"effect_type": "hitroll", "amount": 3},
        ],
    }

    hydrated = build_equippable_item_from_template(template, item_id="item-test-ring")
    assert hydrated.equipment_effects == [
        {"effect_type": "dex", "amount": 2},
        {"effect_type": "hitroll", "amount": 3},
    ]


def test_wear_and_unequip_recalculate_resource_caps_immediately() -> None:
    session = _make_session("client-reeval", "Lucia")
    ring = ItemState(
        item_id="item-vital-ring",
        name="Vital Ring",
        equippable=True,
        slot="armor",
        wear_slot="ring",
        wear_slots=["ring"],
        equipment_effects=[{"effect_type": "hit_points", "amount": 40}],
    )
    session.inventory_items[ring.item_id] = ring

    baseline_caps = get_player_resource_caps(session)
    session.status.hit_points = baseline_caps["hit_points"]

    wore, _slot = wear_item(session, ring)
    assert wore is True
    boosted_caps = get_player_resource_caps(session)
    assert boosted_caps["hit_points"] == baseline_caps["hit_points"] + 40

    session.status.hit_points = boosted_caps["hit_points"]
    assert unequip_item(session, ring) is True
    reduced_caps = get_player_resource_caps(session)

    assert reduced_caps["hit_points"] == baseline_caps["hit_points"]
    assert session.status.hit_points == reduced_caps["hit_points"]
