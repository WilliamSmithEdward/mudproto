import random

from attribute_config import load_level_scaling_config, load_weapon_type_config
from models import EntityState, ItemState, PlayerCombatState
from settings import HIT_ROLL_DICE_SIDES, UNARMED_DAMAGE_VARIANCE


def resolve_weapon_verb(weapon_type: str) -> str:
    weapon_type_config = load_weapon_type_config()
    weapon_types = weapon_type_config.get("weapon_types", {}) if isinstance(weapon_type_config, dict) else {}
    default_weapon_type = str(weapon_type_config.get("default_weapon_type", "unarmed")).strip().lower() or "unarmed"
    normalized = weapon_type.strip().lower() if weapon_type else default_weapon_type
    entry = weapon_types.get(normalized) or weapon_types.get(default_weapon_type, {})
    return str(entry.get("verb", "hit")).strip().lower() or "hit"


def roll_weapon_room_proc_damage(weapon: ItemState | None) -> tuple[bool, int]:
    if weapon is None:
        return False, 0

    chance = max(0.0, float(getattr(weapon, "on_hit_room_damage_chance", 0.0) or 0.0))
    if chance <= 0.0 or random.random() > chance:
        return False, 0

    damage = _roll_damage_dice(
        int(getattr(weapon, "on_hit_room_damage_dice_count", 0)),
        int(getattr(weapon, "on_hit_room_damage_dice_sides", 0)),
    ) + int(getattr(weapon, "on_hit_room_damage_roll_modifier", 0))
    return (damage > 0), max(0, damage)


def roll_weapon_target_proc_damage(weapon: ItemState | None) -> tuple[bool, int]:
    if weapon is None:
        return False, 0

    chance = max(0.0, float(getattr(weapon, "on_hit_target_damage_chance", 0.0) or 0.0))
    if chance <= 0.0 or random.random() > chance:
        return False, 0

    damage = _roll_damage_dice(
        int(getattr(weapon, "on_hit_target_damage_dice_count", 0)),
        int(getattr(weapon, "on_hit_target_damage_dice_sides", 0)),
    ) + int(getattr(weapon, "on_hit_target_damage_roll_modifier", 0))
    return (damage > 0), max(0, damage)


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


def _resolve_player_melee_level_bonuses(player_level: int) -> tuple[int, int]:
    normalized_level = max(1, int(player_level))
    level_scaling = load_level_scaling_config()
    melee_scaling = level_scaling.get("melee", {}) if isinstance(level_scaling, dict) else {}

    def _resolve_bonus(rule_name: str) -> int:
        rule = melee_scaling.get(rule_name, {}) if isinstance(melee_scaling, dict) else {}
        if not isinstance(rule, dict):
            return 0

        levels_per_bonus = max(0, int(rule.get("levels_per_bonus", 0)))
        bonus_per_step = max(0, int(rule.get("bonus_per_step", 0)))
        if levels_per_bonus <= 0 or bonus_per_step <= 0:
            return 0
        return max(0, ((normalized_level - 1) // levels_per_bonus) * bonus_per_step)

    return _resolve_bonus("hit_roll"), _resolve_bonus("damage_roll")


def roll_player_damage(
    player_combat: PlayerCombatState,
    weapon: ItemState | None,
    *,
    player_level: int = 1,
    unarmed_damage_bonus: int = 0,
) -> tuple[int, str | None, str]:
    _, level_damage_bonus = _resolve_player_melee_level_bonuses(player_level)

    if weapon is None:
        bonus_damage = max(0, int(unarmed_damage_bonus))
        base_damage = roll_unarmed_damage(player_combat.attack_damage + bonus_damage) + level_damage_bonus
        return max(0, base_damage), None, "hit"

    rolled_damage = _roll_damage_dice(weapon.damage_dice_count, weapon.damage_dice_sides)
    total_damage = (
        rolled_damage
        + player_combat.attack_damage
        + weapon.damage_roll_modifier
        + weapon.attack_damage_bonus
        + level_damage_bonus
    )
    return max(0, total_damage), weapon.name, resolve_weapon_verb(weapon.weapon_type)


def get_player_hit_modifier(
    weapon: ItemState | None,
    *,
    player_level: int = 1,
    unarmed_hit_bonus: int = 0,
) -> int:
    level_hit_bonus, _ = _resolve_player_melee_level_bonuses(player_level)
    if weapon is None:
        return level_hit_bonus + max(0, int(unarmed_hit_bonus))
    return weapon.hit_roll_modifier + level_hit_bonus


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