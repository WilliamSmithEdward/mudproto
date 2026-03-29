import asyncio
import random
import uuid

from equipment import get_equipped_main_hand, get_equipped_off_hand
from models import ClientSession, EntityState, EquipmentItemState


COMBAT_ROUND_INTERVAL_SECONDS = 2.5
OPENING_ATTACKER_PLAYER = "player"
OPENING_ATTACKER_ENTITY = "entity"
PLAYER_ARMOR_CLASS = 10
HIT_ROLL_DICE_SIDES = 20
PLAYER_REFERENCE_MAX_HP = 575
PLAYER_REFERENCE_MAX_VIGOR = 119
PLAYER_REFERENCE_MAX_MANA = 160

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


def list_room_entities(session: ClientSession, room_id: str) -> list[EntityState]:
    entities: list[EntityState] = []

    for entity in session.entities.values():
        if entity.is_alive and entity.room_id == room_id:
            entities.append(entity)

    entities.sort(key=lambda item: item.spawn_sequence)
    return entities


def get_health_condition(hit_points: int, max_hit_points: int) -> tuple[str, str]:
    if max_hit_points <= 0:
        return "awful", "bright_red"

    ratio = max(0.0, min(1.0, hit_points / max_hit_points))
    if ratio <= 0.15:
        return "awful", "bright_red"
    if ratio <= 0.30:
        return "very poor", "bright_red"
    if ratio <= 0.45:
        return "poor", "bright_red"
    if ratio <= 0.60:
        return "average", "bright_yellow"
    if ratio <= 0.75:
        return "fair", "bright_yellow"
    if ratio <= 0.90:
        return "good", "bright_green"
    if ratio < 1.0:
        return "very good", "bright_green"
    return "perfect", "bright_green"


def get_entity_condition(entity: EntityState) -> tuple[str, str]:
    return get_health_condition(entity.hit_points, entity.max_hit_points)


def _to_third_person(verb: str) -> str:
    normalized = verb.strip().lower() or "hit"
    if normalized.endswith("y") and len(normalized) > 1 and normalized[-2] not in "aeiou":
        return f"{normalized[:-1]}ies"
    if normalized.endswith(("s", "x", "z", "ch", "sh")):
        return f"{normalized}es"
    return f"{normalized}s"


def _resolve_weapon_verb(weapon_type: str) -> str:
    normalized = weapon_type.strip().lower() if weapon_type else "unarmed"
    return WEAPON_TYPE_TO_VERB.get(normalized, "hit")


def _article(name: str) -> str:
    return "an" if name.strip().lower()[:1] in "aeiou" else "a"


def _choose_severity(damage: int, target_max_hp: int) -> str:
    if damage <= 0:
        return "miss"

    ratio = damage / max(1, target_max_hp)
    if ratio < 0.05:
        return "barely"
    if ratio < 0.12:
        return "normal"
    if ratio < 0.22:
        return "hard"
    if ratio < 0.35:
        return "extreme"
    if ratio < 0.50:
        return "massacre"
    if ratio < 0.75:
        return "annihilate"
    return "obliterate"


def _build_player_attack_parts(
    *,
    entity_name: str,
    attack_verb: str,
    damage: int,
    target_max_hp: int,
) -> list[dict]:
    from display import build_part

    verb_noun = _to_third_person(attack_verb)
    severity = _choose_severity(damage, target_max_hp)
    article = _article(entity_name)
    named = f"{article} {entity_name}"

    parts: list[dict] = []
    if severity == "miss":
        parts.extend([
            build_part("You miss "),
            build_part(named),
            build_part(" with your "),
            build_part(attack_verb),
            build_part("."),
        ])
        return parts

    if severity in {"barely", "normal", "hard", "extreme"}:
        if severity == "barely":
            parts.append(build_part("You barely "))
        else:
            parts.append(build_part("You "))
        parts.extend([
            build_part(attack_verb),
            build_part(" "),
            build_part(named),
        ])
        if severity == "hard":
            parts.append(build_part(" hard"))
        elif severity == "extreme":
            parts.append(build_part(" extremely hard"))
        parts.append(build_part("."))
        return parts

    top_label = {
        "massacre": "massacre",
        "annihilate": "annihilate",
        "obliterate": "obliterate",
    }[severity]
    parts.extend([
        build_part(f"You {top_label} "),
        build_part(named),
        build_part(" with your "),
        build_part(verb_noun),
        build_part("."),
    ])
    return parts


def _build_entity_attack_parts(
    *,
    entity: EntityState,
    attack_verb: str,
    damage: int,
) -> list[dict]:
    from display import build_part

    verb_noun = _to_third_person(attack_verb)
    severity = _choose_severity(damage, PLAYER_REFERENCE_MAX_HP)

    parts: list[dict] = []
    if severity == "miss":
        parts.extend([
            build_part(entity.name),
            build_part(" misses you."),
        ])
        return parts

    if severity == "barely":
        parts.extend([
            build_part(entity.name),
            build_part(" barely "),
            build_part(_to_third_person(attack_verb)),
            build_part(" you."),
        ])
        return parts

    if severity in {"normal", "hard", "extreme"}:
        parts.extend([
            build_part(entity.name),
            build_part(" "),
            build_part(_to_third_person(attack_verb)),
            build_part(" you"),
        ])
        if severity == "hard":
            parts.append(build_part(" hard"))
        elif severity == "extreme":
            parts.append(build_part(" extremely hard"))
        parts.append(build_part("."))
        return parts

    top_verb = {
        "massacre": "massacres",
        "annihilate": "annihilates",
        "obliterate": "obliterates",
    }[severity]
    pronoun = entity.pronoun_possessive.strip().lower() or "its"
    parts.extend([
        build_part(entity.name),
        build_part(f" {top_verb} you with {pronoun} "),
        build_part(verb_noun),
        build_part("."),
    ])
    return parts


def _roll_hit(total_modifier: int, target_armor_class: int) -> bool:
    roll = random.randint(1, HIT_ROLL_DICE_SIDES)
    return (roll + total_modifier) >= target_armor_class


def _roll_player_damage(session: ClientSession, weapon: EquipmentItemState | None) -> tuple[int, str | None, str]:

    if weapon is None:
        base_damage = max(0, session.player_combat.attack_damage)
        return base_damage, None, "hit"

    dice_count = max(0, weapon.damage_dice_count)
    dice_sides = max(0, weapon.damage_dice_sides)

    rolled_damage = 0
    if dice_count > 0 and dice_sides > 0:
        for _ in range(dice_count):
            rolled_damage += random.randint(1, dice_sides)

    total_damage = (
        rolled_damage
        + session.player_combat.attack_damage
        + weapon.damage_roll_modifier
        + weapon.attack_damage_bonus
    )
    return max(0, total_damage), weapon.name, _resolve_weapon_verb(weapon.weapon_type)


def _get_player_hit_modifier(weapon: EquipmentItemState | None) -> int:
    if weapon is None:
        return 0
    return weapon.hit_roll_modifier


def _build_player_attack_sequence(session: ClientSession, allow_off_hand: bool) -> list[EquipmentItemState | None]:
    attack_sequence: list[EquipmentItemState | None] = []

    main_hand = get_equipped_main_hand(session)
    main_weapon = main_hand if main_hand is not None and main_hand.slot == "weapon" else None

    off_hand = get_equipped_off_hand(session)
    off_weapon = off_hand if off_hand is not None and off_hand.slot == "weapon" else None
    if main_weapon is not None and off_weapon is not None and off_weapon.item_id == main_weapon.item_id:
        off_weapon = None

    attack_sequence.append(main_weapon)

    if allow_off_hand and off_weapon is not None:
        attack_sequence.append(off_weapon)

    return attack_sequence


def find_room_entity_by_name(session: ClientSession, room_id: str, search_text: str) -> EntityState | None:
    normalized = search_text.strip().lower()
    if not normalized:
        return None

    exact_match: EntityState | None = None
    partial_match: EntityState | None = None

    for entity in list_room_entities(session, room_id):
        entity_name = entity.name.lower()

        if entity_name == normalized:
            exact_match = entity
            break

        if normalized in entity_name and partial_match is None:
            partial_match = entity

    return exact_match or partial_match


def clear_combat_if_invalid(session: ClientSession) -> None:
    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        end_combat(session)


def end_combat(session: ClientSession) -> None:
    session.combat.engaged_entity_id = None
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = None


def start_combat(session: ClientSession, entity_id: str, opening_attacker: str) -> None:
    session.combat.engaged_entity_id = entity_id
    session.combat.next_round_monotonic = None
    session.combat.opening_attacker = opening_attacker


def _schedule_next_combat_round(session: ClientSession) -> None:
    try:
        now = asyncio.get_running_loop().time()
    except RuntimeError:
        session.combat.next_round_monotonic = None
        return

    session.combat.next_round_monotonic = now + COMBAT_ROUND_INTERVAL_SECONDS


def get_engaged_entity(session: ClientSession) -> EntityState | None:
    clear_combat_if_invalid(session)

    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return None

    return session.entities.get(target_id)


def _engage_next_room_target(session: ClientSession, defeated_entity_id: str) -> EntityState | None:
    current_room_id = session.player.current_room_id
    for candidate in list_room_entities(session, current_room_id):
        if candidate.entity_id == defeated_entity_id:
            continue
        if not candidate.is_alive:
            continue

        session.combat.engaged_entity_id = candidate.entity_id
        session.combat.opening_attacker = None
        _schedule_next_combat_round(session)
        return candidate

    end_combat(session)
    return None


def cast_spell(session: ClientSession, spell: dict) -> tuple[dict, bool]:
    from display import build_part, display_command_result, display_error

    spell_name = str(spell.get("name", "Spell")).strip() or "Spell"
    mana_cost = max(0, int(spell.get("mana_cost", 0)))
    spell_type = str(spell.get("spell_type", "damage")).strip().lower() or "damage"

    dice_count = max(0, int(spell.get("damage_dice_count", 0)))
    dice_sides = max(0, int(spell.get("damage_dice_sides", 0)))
    damage_modifier = int(spell.get("damage_modifier", 0))
    support_effect = str(spell.get("support_effect", "")).strip().lower()
    support_amount = max(0, int(spell.get("support_amount", 0)))

    status = session.status
    if status.mana < mana_cost:
        return display_error(
            f"Not enough mana for {spell_name}. Need {mana_cost}M, have {status.mana}M.",
            session,
        ), False

    status.mana -= mana_cost

    if spell_type == "support":
        parts = [
            build_part("You cast "),
            build_part(spell_name),
            build_part(". "),
            build_part("Mana -"),
            build_part(str(mana_cost)),
            build_part("."),
        ]

        if support_effect == "heal":
            before = status.hit_points
            status.hit_points = min(PLAYER_REFERENCE_MAX_HP, status.hit_points + support_amount)
            parts.extend([
                build_part(" "),
                build_part("HP +"),
                build_part(str(status.hit_points - before)),
                build_part("."),
            ])
        elif support_effect == "vigor":
            before = status.vigor
            status.vigor = min(PLAYER_REFERENCE_MAX_VIGOR, status.vigor + support_amount)
            parts.extend([
                build_part(" "),
                build_part("Vigor +"),
                build_part(str(status.vigor - before)),
                build_part("."),
            ])
        elif support_effect == "mana":
            before = status.mana
            status.mana = min(PLAYER_REFERENCE_MAX_MANA, status.mana + support_amount)
            parts.extend([
                build_part(" "),
                build_part("Mana +"),
                build_part(str(status.mana - before)),
                build_part("."),
            ])
        else:
            return display_error(
                f"Spell '{spell_name}' has unsupported support_effect '{support_effect}'.",
                session,
            ), False

        return display_command_result(session, parts), True

    if spell_type != "damage":
        return display_error(f"Spell '{spell_name}' has unsupported spell_type '{spell_type}'.", session), False

    clear_combat_if_invalid(session)
    entity = get_engaged_entity(session)
    if entity is None:
        return display_error("You must be engaged in combat to cast damage spells.", session), False

    rolled_damage = 0
    if dice_count > 0 and dice_sides > 0:
        for _ in range(dice_count):
            rolled_damage += random.randint(1, dice_sides)
    total_damage = max(0, rolled_damage + damage_modifier)

    article = _article(entity.name)
    target_name = f"{article} {entity.name}"
    parts = [
        build_part("You cast "),
        build_part(spell_name),
        build_part(" on "),
        build_part(target_name),
        build_part(". "),
        build_part("Mana -"),
        build_part(str(mana_cost)),
        build_part("."),
    ]

    if total_damage > 0:
        entity.hit_points = max(0, entity.hit_points - total_damage)
        parts.extend([
            build_part(" "),
            build_part(spell_name),
            build_part(" hits for "),
            build_part(str(total_damage)),
            build_part(" damage."),
        ])
    else:
        parts.extend([
            build_part(" "),
            build_part(spell_name),
            build_part(" fizzles harmlessly."),
        ])

    if entity.hit_points <= 0:
        entity.is_alive = False
        status.coins += entity.coin_reward
        parts.extend([
            build_part(" "),
            build_part(entity.name),
            build_part(" is destroyed. Coins +"),
            build_part(str(entity.coin_reward)),
            build_part("."),
        ])

        next_target = _engage_next_room_target(session, entity.entity_id)
        if next_target is not None:
            parts.extend([
                build_part(" "),
                build_part("You turn to "),
                build_part(next_target.name),
                build_part("."),
            ])

    return display_command_result(session, parts), True


def initialize_session_entities(session: ClientSession) -> None:
    if session.entities:
        return

    for scout_index in range(2):
        session.entity_spawn_counter += 1
        scout_name = "Hall Scout"
        scout = EntityState(
            entity_id=f"scout-{uuid.uuid4().hex[:8]}",
            name=scout_name,
            room_id="hall",
            hit_points=550,
            max_hit_points=550,
            attack_damage=8,
            attacks_per_round=1,
            hit_roll_modifier=2,
            off_hand_attack_damage=6,
            off_hand_attacks_per_round=1,
            off_hand_hit_roll_modifier=1,
            off_hand_attack_verb="stab",
            off_hand_weapon_name="dagger",
            coin_reward=20,
            spawn_sequence=session.entity_spawn_counter,
            is_aggro=True,
            attack_verb="slash",
            pronoun_possessive="his",
        )
        session.entities[scout.entity_id] = scout


def maybe_auto_engage_current_room(session: ClientSession) -> EntityState | None:
    clear_combat_if_invalid(session)
    if session.combat.engaged_entity_id is not None:
        return None

    room_entities = list_room_entities(session, session.player.current_room_id)
    for entity in room_entities:
        if entity.is_aggro:
            start_combat(session, entity.entity_id, OPENING_ATTACKER_ENTITY)
            return entity

    return None


def spawn_dummy(session: ClientSession) -> dict:
    from display import build_part, display_command_result

    room_id = session.player.current_room_id
    existing_names = {entity.name for entity in list_room_entities(session, room_id)}

    dummy_number = 1
    dummy_name = "Training Dummy"
    while dummy_name in existing_names:
        dummy_number += 1
        dummy_name = f"Training Dummy {dummy_number}"

    entity_id = f"dummy-{uuid.uuid4().hex[:8]}"
    session.entity_spawn_counter += 1
    entity = EntityState(
        entity_id=entity_id,
        name=dummy_name,
        room_id=room_id,
        hit_points=40,
        max_hit_points=40,
        attack_damage=6,
        attacks_per_round=1,
        coin_reward=12,
        spawn_sequence=session.entity_spawn_counter,
    )
    session.entities[entity_id] = entity

    return display_command_result(session, [
        build_part("Spawned ", "bright_white"),
        build_part(entity.name, bold=True),
        build_part(" in this room.", "bright_white"),
    ])


def begin_attack(session: ClientSession, target_name: str) -> dict | list[dict]:
    from display import display_error, display_force_prompt

    clear_combat_if_invalid(session)
    entity = find_room_entity_by_name(session, session.player.current_room_id, target_name)

    if entity is None:
        return display_error(f"No target named '{target_name}' is here.", session)

    start_combat(session, entity.entity_id, OPENING_ATTACKER_PLAYER)
    combat_result = resolve_combat_round(session)

    if combat_result is None:
        _schedule_next_combat_round(session)
        return display_force_prompt(session)

    return [combat_result, display_force_prompt(session)]


def disengage(session: ClientSession) -> dict | list[dict]:
    from display import build_part, display_command_result, display_error

    clear_combat_if_invalid(session)

    entity = get_engaged_entity(session)
    if entity is None:
        return display_error("You are not engaged with anything.", session)

    end_combat(session)

    target_name = entity.name if entity is not None else "your target"
    return display_command_result(session, [
        build_part("You disengage from ", "bright_white"),
        build_part(target_name, bold=True),
        build_part(".", "bright_white"),
    ])


def _append_newline_if_needed(parts: list[dict]) -> None:
    if parts:
        parts.append({"text": "\n", "fg": "bright_white", "bold": False})


def _apply_player_attacks(session: ClientSession, entity: EntityState, parts: list[dict], allow_off_hand: bool) -> None:
    attack_sequence = _build_player_attack_sequence(session, allow_off_hand)

    for weapon in attack_sequence:
        if not entity.is_alive:
            break

        _append_newline_if_needed(parts)

        hit_modifier = _get_player_hit_modifier(weapon)
        if not _roll_hit(hit_modifier, entity.armor_class):
            miss_verb = _resolve_weapon_verb(weapon.weapon_type) if weapon is not None else "hit"
            parts.extend(_build_player_attack_parts(
                entity_name=entity.name,
                attack_verb=miss_verb,
                damage=0,
                target_max_hp=entity.max_hit_points,
            ))
            continue

        rolled_damage, weapon_name, attack_verb = _roll_player_damage(session, weapon)
        entity.hit_points = max(0, entity.hit_points - rolled_damage)
        parts.extend(_build_player_attack_parts(
            entity_name=entity.name,
            attack_verb=attack_verb,
            damage=rolled_damage,
            target_max_hp=entity.max_hit_points,
        ))

        if entity.hit_points <= 0:
            entity.is_alive = False
            break


def _list_room_attackers(session: ClientSession, primary_entity: EntityState) -> list[EntityState]:
    attackers: list[EntityState] = [primary_entity]
    for candidate in list_room_entities(session, session.player.current_room_id):
        if candidate.entity_id == primary_entity.entity_id:
            continue
        if not candidate.is_alive or not candidate.is_aggro:
            continue
        attackers.append(candidate)
    return attackers


def _apply_entity_attacks(session: ClientSession, attackers: list[EntityState], parts: list[dict], allow_off_hand: bool) -> None:
    status = session.status

    for entity in attackers:
        if not entity.is_alive:
            continue

        for _ in range(max(1, entity.attacks_per_round)):
            _append_newline_if_needed(parts)

            if not _roll_hit(entity.hit_roll_modifier, PLAYER_ARMOR_CLASS):
                parts.extend(_build_entity_attack_parts(
                    entity=entity,
                    attack_verb=entity.attack_verb,
                    damage=0,
                ))
                continue

            attack_damage = max(0, entity.attack_damage)
            status.hit_points = max(0, status.hit_points - attack_damage)
            parts.extend(_build_entity_attack_parts(
                entity=entity,
                attack_verb=entity.attack_verb,
                damage=attack_damage,
            ))

        if allow_off_hand:
            off_hand_swings = max(0, entity.off_hand_attacks_per_round)
            for _ in range(off_hand_swings):
                _append_newline_if_needed(parts)

                if not _roll_hit(entity.off_hand_hit_roll_modifier, PLAYER_ARMOR_CLASS):
                    parts.extend(_build_entity_attack_parts(
                        entity=entity,
                        attack_verb=entity.off_hand_attack_verb,
                        damage=0,
                    ))
                    continue

                off_hand_damage = max(0, entity.off_hand_attack_damage)
                status.hit_points = max(0, status.hit_points - off_hand_damage)
                parts.extend(_build_entity_attack_parts(
                    entity=entity,
                    attack_verb=entity.off_hand_attack_verb,
                    damage=off_hand_damage,
                ))


def resolve_combat_round(session: ClientSession) -> dict | None:
    from display import build_part, display_combat_round_result

    clear_combat_if_invalid(session)

    target_id = session.combat.engaged_entity_id
    if target_id is None:
        return None

    entity = session.entities.get(target_id)
    if entity is None or not entity.is_alive or entity.room_id != session.player.current_room_id:
        clear_combat_if_invalid(session)
        return None

    parts: list[dict] = []
    status = session.status
    opening_attacker = session.combat.opening_attacker
    is_opening_round = opening_attacker is not None
    room_attackers = _list_room_attackers(session, entity)

    if opening_attacker == OPENING_ATTACKER_ENTITY:
        _apply_entity_attacks(session, room_attackers, parts, allow_off_hand=False)
    else:
        _apply_player_attacks(session, entity, parts, allow_off_hand=not is_opening_round)

    if entity.hit_points <= 0:
        entity.is_alive = False
        status.coins += entity.coin_reward

        _append_newline_if_needed(parts)
        parts.extend([
            build_part(entity.name),
            build_part(" is destroyed. ", "bright_white"),
            build_part("Coins +", "bright_white"),
            build_part(str(entity.coin_reward), "bright_yellow", True),
            build_part(".", "bright_white"),
        ])

        next_target = _engage_next_room_target(session, entity.entity_id)
        if next_target is not None:
            _append_newline_if_needed(parts)
            parts.extend([
                build_part("You turn to ", "bright_white"),
                build_part(next_target.name),
                build_part(".", "bright_white"),
            ])

        return display_combat_round_result(session, parts)

    if opening_attacker is not None:
        session.combat.opening_attacker = None
    else:
        _apply_entity_attacks(session, room_attackers, parts, allow_off_hand=True)

    if status.hit_points <= 0:
        end_combat(session)

        _append_newline_if_needed(parts)
        if status.extra_lives > 0:
            status.extra_lives -= 1
            status.hit_points = 575
            status.vigor = 119
            parts.extend([
                build_part("You collapse, then recover using an extra life. Combat ends.", "bright_magenta", True),
            ])
        else:
            parts.extend([
                build_part("You collapse. Combat ends.", "bright_red", True),
            ])

        return display_combat_round_result(session, parts)

    _schedule_next_combat_round(session)
    return display_combat_round_result(session, parts)