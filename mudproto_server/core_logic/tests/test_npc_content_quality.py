from assets import load_npc_templates, load_skills, load_spells


EXPECTED_NPC_NAMES = {
    "npc.east-watch-reaver": "Bell Watch Deserter",
    "npc.wandering-mercenary": "Road Mercenary",
    "npc.ashen-acolyte-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Censer Keeper",
    "npc.dustbound-cantor-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Funeral Cantor",
    "npc.sepulcher-guardian-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Ossuary Watchman",
    "npc.lockward-sentinel-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Seal Warden",
    "npc.penitent-custodian-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Old Custodian",
    "npc.thornbound-boar-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Boar in a Thorn Harness",
    "npc.enspelled-stag-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Stag With a Silver Bridle",
    "npc.crownscar-bear-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Bear With a Thorn Collar",
    "npc.canker-pixie-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Pixie With Mold-Spotted Wings",
    "npc.gloam-faerie-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Faerie Hedge Scout",
    "npc.royal-guard-faerie-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Faerie Palace Guard",
    "npc.throne-attendant-faerie-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Faerie Chamberlain",
    "npc.aurelian-faerie-prince-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Aurelian",
    "npc.serelyth-faerie-princess-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Serelyth",
    "npc.gianda-the-faerie-monarch-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Queen Gianda",
    "npc.crowbanner-reaver-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Crowbanner Axeman",
    "npc.crowbanner-hexer-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
        "Crowbanner Fire-Setter",
    "npc.crowbanner-bulwark-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11":
        "Crowbanner Shieldman",
    "npc.ironhook-maela-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Maela Dorr",
    "npc.varo-cindersmile-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Varo Kesh",
    "npc.seln-of-the-pins-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Seln Varr",
    "npc.brother-cleft-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Brother Edran",
    "npc.hadrik-crowbanner-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Hadrik Voss",
    "npc.grave-acolyte-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Altar Acolyte",
    "npc.dark-priestess-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Keeper Vael",
    "npc.dread-revenant-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11":
        "Blackwatch Revenant",
    "npc.sunken-guardian-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Buried Watchman",
    "npc.sunmarshal-aurek-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Marshal Aurek",
    "npc.prayer-warden-samiel-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Brother Samiel",
    "npc.buried-heresiarch-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Brother Merovech",
}

EXPECTED_ABILITY_NAMES = {
    "skill.overhead-crack": "Overhead Blow",
    "skill.guard-breath": "Catch Breath",
    "skill.bone-rake-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Haft Hook",
    "skill.censer-guard-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Bitter Incense",
    "skill.briar-gore-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Driving Charge",
    "skill.thorn-trample-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Trampling Rush",
    "skill.mindlash-feint-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Mirror Feint",
    "skill.wingstorm-veil-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Wing Guard",
    "skill.crownbreak-swipe-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Court Strike",
    "skill.ironhook-rend-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Hooking Chop",
    "skill.gutter-step-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Low Step",
    "skill.wallbreaker-swing-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Driving Swing",
    "skill.crippling-pitchknife-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Thrown Knife",
    "skill.plank-guard-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Hard Guard",
    "skill.sundering-cleave-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Downward Cleave",
    "skill.grave-guard-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Watchman's Guard",
    "skill.sandrush-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Dune Rush",
    "skill.vow-of-endurance-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Hold Fast",
    "spell.graveflare-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Funeral Flame",
    "spell.martyrs-keeping-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": "Ash Binding",
    "spell.corrupted-pollen-burst-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Choking Pollen",
    "spell.emerald-starfall-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Glassleaf Storm",
    "spell.mind-thorn-lance-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Glamour Needle",
    "spell.verdant-ruin-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1":
        "Root-Splinter Curse",
    "spell.monarchs-cascade-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Green Glass Rain",
    "spell.regal-bloom-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": "Root Draw",
    "spell.cinder-kiss-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Pitch Flame",
    "spell.coalburst-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Cast Coals",
    "spell.grave-prayer-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": "Last Prayer",
    "spell.grave-bolt-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Cresset Flame",
    "spell.unhallowed-mending-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Cold Mending",
    "spell.night-veil-9d2a2c3e-5b7c-4b82-9d7c-9f1e3c6a4b11": "Blackwatch Vow",
    "spell.solar-lance-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Sun Bolt",
    "spell.oasis-prayer-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": "Cistern Prayer",
}


def _abilities_by_id() -> dict[str, dict]:
    return {
        **{skill["skill_id"]: skill for skill in load_skills()},
        **{spell["spell_id"]: spell for spell in load_spells()},
    }


def test_audited_npcs_use_grounded_display_names() -> None:
    npc_by_id = {npc["npc_id"]: npc for npc in load_npc_templates()}

    for npc_id, expected_name in EXPECTED_NPC_NAMES.items():
        assert npc_by_id[npc_id]["name"] == expected_name

    merovech = npc_by_id[
        "npc.buried-heresiarch-7b211de0-4cff-4cbc-83bb-a7a6c9269c83"
    ]
    assert merovech["is_named"] is True
    assert merovech["corpse_label_style"] == "possessive"


def test_audited_npc_abilities_use_concrete_display_names() -> None:
    ability_by_id = _abilities_by_id()

    for ability_id, expected_name in EXPECTED_ABILITY_NAMES.items():
        assert ability_by_id[ability_id]["name"] == expected_name


def test_every_npc_ability_is_affordable_and_has_outcome_text() -> None:
    ability_by_id = _abilities_by_id()

    for npc in load_npc_templates():
        ability_ids = [*npc.get("skill_ids", []), *npc.get("spell_ids", [])]
        assert len(ability_ids) == len(set(ability_ids))
        assert len(ability_ids) <= 4, f"{npc['npc_id']} has an unreadable combat kit"

        for ability_id in npc.get("skill_ids", []):
            ability = ability_by_id[ability_id]
            assert int(ability.get("vigor_cost", 0)) <= int(npc.get("max_vigor", 0)), (
                f"{npc['npc_id']} cannot afford {ability_id}"
            )
            assert ability.get("description")
            outcome_field = (
                "damage_context" if ability.get("skill_type") == "damage" else "support_context"
            )
            assert ability.get(outcome_field), f"{ability_id} lacks {outcome_field}"

        for ability_id in npc.get("spell_ids", []):
            ability = ability_by_id[ability_id]
            assert int(ability.get("mana_cost", 0)) <= int(npc.get("max_mana", 0)), (
                f"{npc['npc_id']} cannot afford {ability_id}"
            )
            assert ability.get("description")
            outcome_field = (
                "damage_context" if ability.get("spell_type") == "damage" else "support_context"
            )
            assert ability.get(outcome_field), f"{ability_id} lacks {outcome_field}"


def test_major_encounters_have_small_distinct_kits() -> None:
    npc_by_id = {npc["npc_id"]: npc for npc in load_npc_templates()}
    expected_kits = {
        "npc.penitent-custodian-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77": {
            "skill.bone-rake-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77",
            "spell.graveflare-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77",
            "spell.martyrs-keeping-a13a7a1b-4d2f-4f7e-b5b6-6a1f0c3d5e77",
        },
        "npc.aurelian-faerie-prince-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": {
            "skill.mindlash-feint-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "skill.crownbreak-swipe-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "spell.verdant-ruin-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
        },
        "npc.serelyth-faerie-princess-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": {
            "skill.wingstorm-veil-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "spell.emerald-starfall-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
        },
        "npc.gianda-the-faerie-monarch-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1": {
            "skill.wingstorm-veil-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "skill.crownbreak-swipe-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "spell.monarchs-cascade-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
            "spell.regal-bloom-7f9a2d9a-5d2e-4da5-b0f0-4b8ef4b1d6a1",
        },
        "npc.hadrik-crowbanner-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11": {
            "skill.wallbreaker-swing-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
            "skill.plank-guard-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
            "spell.coalburst-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
            "spell.grave-prayer-9a7d7c2b-7d52-4b5c-9d33-7d1d9e6f4a11",
        },
        "npc.buried-heresiarch-7b211de0-4cff-4cbc-83bb-a7a6c9269c83": {
            "skill.sandrush-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
            "spell.solar-lance-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
            "spell.oasis-prayer-7b211de0-4cff-4cbc-83bb-a7a6c9269c83",
        },
    }

    for npc_id, expected_ability_ids in expected_kits.items():
        npc = npc_by_id[npc_id]
        actual_ability_ids = {*npc.get("skill_ids", []), *npc.get("spell_ids", [])}
        assert actual_ability_ids == expected_ability_ids
