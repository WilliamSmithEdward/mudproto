"""Thin compatibility exports for combat ability modules."""

from combat_ability_effects import (
    _process_entity_battle_round_support_effects,
    process_entity_game_hour_tick,
)
from combat_entity_abilities import _entity_try_cast_spell, _entity_try_use_skill
from combat_player_abilities import cast_spell, use_skill

__all__ = [
    "_entity_try_cast_spell",
    "_entity_try_use_skill",
    "_process_entity_battle_round_support_effects",
    "cast_spell",
    "process_entity_game_hour_tick",
    "use_skill",
]
