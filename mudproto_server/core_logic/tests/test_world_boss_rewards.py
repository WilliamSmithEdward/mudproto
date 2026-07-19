from assets import load_gear_templates, load_item_templates, load_npc_templates, load_rooms, load_zones


BOSS_REWARDS_BY_ZONE = {
    "zone.prototype-core": {},
    "zone.northern-wing": {
        "npc.east-watch-reaver": "weapon.reaver-nightblade",
    },
    "zone.whispering-sanctum": {
        "npc.ashen-reliquary-exarch": "weapon.exarch-doomblade",
    },
    "zone.west-road": {},
    "zone.ashen-sepulcher-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": {
        "npc.penitent-custodian-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77":
            "armor.funerary-plate-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77",
    },
    "zone.corrupted-emerald-maze-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": {
        "npc.aurelian-faerie-prince-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
            "armor.briar-clasp-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
        "npc.serelyth-faerie-princess-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
            "armor.mothwing-veil-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
        "npc.gianda-the-faerie-monarch-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
            "armor.green-glass-crown-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
    },
    "zone.crowbanner-fort-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": {
        "npc.ironhook-maela-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
            "weapon.ironhook-cleaver-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
        "npc.varo-cindersmile-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
            "weapon.cinderbrand-sabre-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
        "npc.seln-of-the-pins-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
            "weapon.tower-shiv-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
        "npc.brother-cleft-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
            "weapon.carrion-maul-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
        "npc.hadrik-crowbanner-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
            "armor.crowbanner-plate-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
    },
    "zone.blackwatch-outpost-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": {
        "npc.dark-priestess-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11":
            "armor.ossuary-cloak-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11",
        "npc.dread-revenant-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11":
            "armor.blackwatch-cuirass-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11",
    },
    "zone.sunscour-redoubt-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": {
        "npc.buried-heresiarch-7b211de0-4cff-4cbc-83bb-a7a6c9269c83":
            "armor.split-sun-disc-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
    },
}

PRUNED_ITEM_IDS = {
    "item.charred-prayer-beads-penitent-custodian-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77",
    "item.bandit-salve-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
    "item.black-banner-token-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
    "item.shadow-balm-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11",
    "item.grave-salt-draught-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11",
    "item.scarab-shell-dune-scarab-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
    "item.cracked-sun-medallion-buried-heresiarch-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
}


def _guaranteed_gear_drop_ids(npc: dict, gear_ids: set[str]) -> set[str]:
    drop_ids = {
        entry["template_id"]
        for entry in npc.get("inventory_items", [])
        if entry["template_id"] in gear_ids and float(entry.get("spawn_chance", 100)) >= 100
    }
    for weapon_field in ("main_hand_weapon", "off_hand_weapon"):
        weapon = npc.get(weapon_field, {})
        if float(weapon.get("spawn_chance", 100)) < 100:
            continue
        if float(weapon.get("drop_on_death", 0)) < 100:
            continue
        if weapon.get("template_id") in gear_ids:
            drop_ids.add(weapon["template_id"])
    return drop_ids


def test_every_zone_has_an_explicit_boss_reward_plan() -> None:
    zones = load_zones()
    rooms = load_rooms()

    assert set(BOSS_REWARDS_BY_ZONE) == {zone["zone_id"] for zone in zones}

    zone_by_id = {zone["zone_id"]: zone for zone in zones}
    for zone_id, boss_rewards in BOSS_REWARDS_BY_ZONE.items():
        spawned_npc_ids = {
            spawn["npc_id"]
            for room in rooms
            if room["zone_id"] == zone_id
            for spawn in room.get("npcs", [])
        }
        spawned_npc_ids.update(
            spawn["npc_id"]
            for spawn in zone_by_id[zone_id].get("flag_spawns", [])
        )
        assert set(boss_rewards).issubset(spawned_npc_ids)


def test_bosses_guarantee_distinctive_stat_gear() -> None:
    gear_by_id = {entry["template_id"]: entry for entry in load_gear_templates()}
    npc_by_id = {entry["npc_id"]: entry for entry in load_npc_templates()}
    reward_ids = [
        reward_id
        for boss_rewards in BOSS_REWARDS_BY_ZONE.values()
        for reward_id in boss_rewards.values()
    ]

    assert len(reward_ids) == len(set(reward_ids))
    for boss_rewards in BOSS_REWARDS_BY_ZONE.values():
        for npc_id, reward_id in boss_rewards.items():
            npc = npc_by_id[npc_id]
            assert _guaranteed_gear_drop_ids(npc, set(gear_by_id)) == {reward_id}

            effects = gear_by_id[reward_id]["equipment_effects"]
            effect_types = {effect["effect_type"] for effect in effects}
            assert len(effects) >= 3
            assert {"str", "dex", "con", "wis"} & effect_types
            assert {"weapon_damage", "damage_reduction"} & effect_types
            assert all(int(effect["amount"]) > 0 for effect in effects)


def test_ordinary_npcs_do_not_carry_guaranteed_loot_clutter() -> None:
    boss_ids = {
        npc_id
        for boss_rewards in BOSS_REWARDS_BY_ZONE.values()
        for npc_id in boss_rewards
    }

    for npc in load_npc_templates():
        if npc["npc_id"] in boss_ids:
            continue
        assert npc.get("inventory_items", []) == []
        for weapon_field in ("main_hand_weapon", "off_hand_weapon"):
            assert float(npc.get(weapon_field, {}).get("drop_on_death", 0)) == 0


def test_pruned_loot_templates_are_not_referenced() -> None:
    item_ids = {entry["template_id"] for entry in load_item_templates()}
    npc_inventory_ids = {
        item["template_id"]
        for npc in load_npc_templates()
        for item in npc.get("inventory_items", [])
    }

    assert PRUNED_ITEM_IDS.isdisjoint(item_ids)
    assert PRUNED_ITEM_IDS.isdisjoint(npc_inventory_ids)
