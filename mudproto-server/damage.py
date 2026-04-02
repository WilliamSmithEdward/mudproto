import random

from models import EntityState, ItemState, PlayerCombatState
from settings import HIT_ROLL_DICE_SIDES, UNARMED_DAMAGE_VARIANCE


WEAPON_TYPE_TO_VERB = {
    "unarmed": "hit",
    "sword": "slash",
    "axe": "hack",
    "bludgeon": "bludgeon",
    "mace": "bludgeon",
    "club": "bludgeon",
    "dagger": "stab",
    "spear": "pierce",
}


def resolve_weapon_verb(weapon_type: str) -> str:
    normalized = weapon_type.strip().lower() if weapon_type else "unarmed"
    return WEAPON_TYPE_TO_VERB.get(normalized, "hit")


def roll_hit(total_modifier: int, target_armor_class: int) -> bool:
    roll = random.randint(1, HIT_ROLL_DICE_SIDES)
    return (roll + total_modifier) >= target_armor_class


def roll_unarmed_damage(base_damage: int) -> int:
    normalized_base = max(0, int(base_damage))
    if normalized_base <= 0:
        return 0

    low = max(1, normalized_base - UNARMED_DAMAGE_VARIANCE)
    high = normalized_base + UNARMED_DAMAGE_VARIANCE
    return random.randint(low, high)


def _roll_damage_dice(dice_count: int, dice_sides: int) -> int:
    normalized_count = max(0, int(dice_count))
    normalized_sides = max(0, int(dice_sides))
    if normalized_count <= 0 or normalized_sides <= 0:
        return 0

    total = 0
    for _ in range(normalized_count):
        total += random.randint(1, normalized_sides)
    return total


def roll_player_damage(player_combat: PlayerCombatState, weapon: ItemState | None) -> tuple[int, str | None, str]:
    if weapon is None:
        base_damage = roll_unarmed_damage(player_combat.attack_damage)
        return base_damage, None, "hit"

    rolled_damage = _roll_damage_dice(weapon.damage_dice_count, weapon.damage_dice_sides)
    total_damage = (
        rolled_damage
        + player_combat.attack_damage
        + weapon.damage_roll_modifier
        + weapon.attack_damage_bonus
    )
    return max(0, total_damage), weapon.name, resolve_weapon_verb(weapon.weapon_type)


def get_player_hit_modifier(weapon: ItemState | None) -> int:
    if weapon is None:
        return 0
    return weapon.hit_roll_modifier


def roll_skill_damage(skill: dict) -> int:
    rolled_damage = _roll_damage_dice(
        int(skill.get("damage_dice_count", 0)),
        int(skill.get("damage_dice_sides", 0)),
    )
    damage_modifier = int(skill.get("damage_modifier", 0))
    return max(0, rolled_damage + damage_modifier)


def roll_spell_damage(spell: dict, scaling_bonus: int = 0) -> int:
    rolled_damage = _roll_damage_dice(
        int(spell.get("damage_dice_count", 0)),
        int(spell.get("damage_dice_sides", 0)),
    )
    damage_modifier = int(spell.get("damage_modifier", 0))
    return max(0, rolled_damage + damage_modifier + int(scaling_bonus))


def roll_npc_weapon_damage(entity: EntityState, weapon_template: dict | None) -> tuple[int, str]:
    base_damage = max(0, entity.power_level)
    if weapon_template is None:
        return roll_unarmed_damage(base_damage), "hit"

    rolled_damage = _roll_damage_dice(
        int(weapon_template.get("damage_dice_count", 0)),
        int(weapon_template.get("damage_dice_sides", 0)),
    )
    damage_roll_modifier = int(weapon_template.get("damage_roll_modifier", 0))
    attack_damage_bonus = int(weapon_template.get("attack_damage_bonus", 0))
    total_damage = base_damage + rolled_damage + damage_roll_modifier + attack_damage_bonus
    attack_verb = resolve_weapon_verb(str(weapon_template.get("weapon_type", "unarmed")))
    return max(0, total_damage), attack_verb


def get_npc_hit_modifier(entity: EntityState, weapon_template: dict | None, *, off_hand: bool) -> int:
    base_modifier = entity.off_hand_hit_roll_modifier if off_hand else entity.hit_roll_modifier
    if weapon_template is None:
        return base_modifier
    return base_modifier + int(weapon_template.get("hit_roll_modifier", 0))