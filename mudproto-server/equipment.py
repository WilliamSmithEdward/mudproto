from models import ClientSession, EquipmentItemState


def list_equipment(session: ClientSession) -> list[EquipmentItemState]:
    equipment_items = list(session.equipment.items.values())
    equipment_items.sort(key=lambda item: (item.slot, item.name, item.item_id))
    return equipment_items


def get_equipped_weapon(session: ClientSession) -> EquipmentItemState | None:
    weapon_id = session.equipment.equipped_weapon_id
    if weapon_id is None:
        return None

    return session.equipment.items.get(weapon_id)


def get_player_attack_damage(session: ClientSession) -> int:
    damage = session.player_combat.attack_damage
    weapon = get_equipped_weapon(session)
    if weapon is not None:
        damage += weapon.attack_damage_bonus
    return max(0, damage)


def get_player_attacks_per_round(session: ClientSession) -> int:
    attacks_per_round = session.player_combat.attacks_per_round
    weapon = get_equipped_weapon(session)
    if weapon is not None:
        attacks_per_round += weapon.attacks_per_round_bonus
    return max(1, attacks_per_round)


def get_held_weapon_name(session: ClientSession) -> str | None:
    weapon = get_equipped_weapon(session)
    if weapon is None:
        return None

    return weapon.name