from assets import (
    get_gear_template_by_id,
    get_npc_template_by_id,
    get_skill_by_id,
    get_spell_by_id,
    load_rooms,
    load_zones,
)


ZONE_ID = "zone.whispering-sanctum"
ZONE_ROOM_IDS = {
    "sanctum",
    "room.cinder-chapel-vestry",
    "room.cinder-chapel-choir",
    "room.cinder-chapel-chancel",
    "reliquary",
    "room.cinder-chapel-ash-store",
    "room.cinder-chapel-kiln-stair",
    "room.cinder-chapel-lower-kiln",
}
BASE_HOSTILE_IDS = {
    "npc.sanctum-invoker",
    "npc.cinder-chapel-reader",
    "npc.cinder-chapel-burial-hand",
    "npc.cinder-chapel-kiln-tender",
}
BOSS_ID = "npc.ashen-reliquary-exarch"
REVERSE_DIRECTIONS = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}


def _rooms_by_id() -> dict[str, dict]:
    return {room["room_id"]: room for room in load_rooms()}


def _zone() -> dict:
    return next(zone for zone in load_zones() if zone["zone_id"] == ZONE_ID)


def _zone_npc_ids(rooms: dict[str, dict]) -> set[str]:
    npc_ids = {
        spawn["npc_id"]
        for room_id in ZONE_ROOM_IDS
        for spawn in rooms[room_id].get("npcs", [])
    }
    npc_ids.update(rule["npc_id"] for rule in _zone().get("flag_spawns", []))
    return npc_ids


def test_cinder_chapel_has_a_reciprocal_level_one_to_five_map() -> None:
    rooms = _rooms_by_id()
    actual_zone_room_ids = {
        room_id
        for room_id, room in rooms.items()
        if room.get("zone_id") == ZONE_ID
    }

    assert actual_zone_room_ids == ZONE_ROOM_IDS
    assert rooms["start"]["exits"]["east"] == "sanctum"
    assert rooms["sanctum"]["exits"]["west"] == "start"

    for room_id in ZONE_ROOM_IDS:
        room = rooms[room_id]
        assert room.get("room_objects"), f"{room_id} needs examinable physical details"
        assert len(str(room.get("description", "")).split()) <= 80
        for direction, destination_room_id in room.get("exits", {}).items():
            reverse_direction = REVERSE_DIRECTIONS[direction]
            destination = rooms[destination_room_id]
            assert destination.get("exits", {}).get(reverse_direction) == room_id


def test_cinder_chapel_encounters_rise_from_two_to_five_with_safe_breaks() -> None:
    rooms = _rooms_by_id()
    keeper = get_npc_template_by_id("npc.cinder-chapel-keeper")
    boss = get_npc_template_by_id(BOSS_ID)

    assert keeper is not None
    assert keeper["name"] == "Nella Sorn"
    assert keeper["is_peaceful"] is True
    assert keeper["is_aggro"] is False
    assert rooms["sanctum"]["npcs"] == [
        {"npc_id": "npc.cinder-chapel-keeper", "count": 1}
    ]

    expected_power_levels = {
        "npc.sanctum-invoker": 2,
        "npc.cinder-chapel-reader": 3,
        "npc.cinder-chapel-burial-hand": 3,
        "npc.cinder-chapel-kiln-tender": 4,
        BOSS_ID: 5,
    }
    for npc_id, expected_power_level in expected_power_levels.items():
        npc = get_npc_template_by_id(npc_id)
        assert npc is not None
        assert npc["power_level"] == expected_power_level

    base_spawn_ids = {
        spawn["npc_id"]
        for room_id in ZONE_ROOM_IDS
        for spawn in rooms[room_id].get("npcs", [])
    }
    assert BASE_HOSTILE_IDS <= base_spawn_ids
    assert BOSS_ID not in base_spawn_ids
    assert rooms["room.cinder-chapel-chancel"]["npcs"] == []
    assert rooms["room.cinder-chapel-kiln-stair"]["npcs"] == []
    assert boss is not None and boss["experience_reward"] >= 80


def test_cinder_chapel_boss_requires_both_ward_holders() -> None:
    zone = _zone()
    assert set(zone["reset_world_flags"]) == {
        "npc.cinder-chapel-reader.defeated",
        "npc.cinder-chapel-kiln-tender.defeated",
        "npc.prior-oren-saye.defeated",
    }
    assert len(zone["flag_spawns"]) == 1

    rule = zone["flag_spawns"][0]
    assert rule["npc_id"] == BOSS_ID
    assert rule["room_id"] == "room.cinder-chapel-lower-kiln"
    assert set(rule["required_world_flags"]) == {
        "npc.cinder-chapel-reader.defeated",
        "npc.cinder-chapel-kiln-tender.defeated",
    }
    assert rule["excluded_world_flags"] == ["npc.prior-oren-saye.defeated"]

    reader = get_npc_template_by_id("npc.cinder-chapel-reader")
    tender = get_npc_template_by_id("npc.cinder-chapel-kiln-tender")
    boss = get_npc_template_by_id(BOSS_ID)
    assert reader is not None and reader["set_world_flags_on_death"] == [
        "npc.cinder-chapel-reader.defeated"
    ]
    assert tender is not None and tender["set_world_flags_on_death"] == [
        "npc.cinder-chapel-kiln-tender.defeated"
    ]
    assert boss is not None and boss["set_world_flags_on_death"] == [
        "npc.prior-oren-saye.defeated"
    ]


def test_cinder_chapel_npcs_can_afford_every_assigned_ability() -> None:
    rooms = _rooms_by_id()
    for npc_id in _zone_npc_ids(rooms):
        npc = get_npc_template_by_id(npc_id)
        assert npc is not None

        for skill_id in npc.get("skill_ids", []):
            skill = get_skill_by_id(skill_id)
            assert skill is not None
            assert int(skill.get("vigor_cost", 0)) <= int(npc.get("max_vigor", 0)), (
                f"{npc_id} cannot afford {skill_id}"
            )

        for spell_id in npc.get("spell_ids", []):
            spell = get_spell_by_id(spell_id)
            assert spell is not None
            assert int(spell.get("mana_cost", 0)) <= int(npc.get("max_mana", 0)), (
                f"{npc_id} cannot afford {spell_id}"
            )


def test_cinder_chapel_legacy_reward_ids_have_grounded_names_and_stats() -> None:
    kiln_rake = get_gear_template_by_id("weapon.exarch-doomblade")
    wax_knife = get_gear_template_by_id("weapon.exarch-emberfang")

    assert kiln_rake is not None and kiln_rake["name"] == "Kiln Rake"
    assert kiln_rake["damage_dice_count"] == 4
    assert kiln_rake["damage_dice_sides"] == 6
    assert wax_knife is not None and wax_knife["name"] == "Wax Knife"
    assert wax_knife["damage_dice_count"] == 2
    assert wax_knife["damage_dice_sides"] == 4
