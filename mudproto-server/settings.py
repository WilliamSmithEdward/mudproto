import json
from functools import lru_cache
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = SERVER_ROOT / "configuration" / "server" / "settings.json"


@lru_cache(maxsize=1)
def load_server_settings() -> dict:
    with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"Server settings file must contain an object: {SETTINGS_FILE}")

    return raw


_SETTINGS = load_server_settings()


def _section(name: str) -> dict:
    value = _SETTINGS.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Server settings section '{name}' must be an object.")
    return value


_NETWORK = _section("network")
_TIMING = _section("timing")
_COMBAT = _section("combat")
_GAMEPLAY = _section("gameplay")
_SESSION = _section("session")
_PLAYER = _section("player")
_ASSETS = _section("assets")


SERVER_HOST = str(_NETWORK.get("host", "localhost")).strip() or "localhost"
SERVER_PORT = int(_NETWORK.get("port", 8765))

COMMAND_SCHEDULER_INTERVAL_SECONDS = float(_TIMING.get("command_scheduler_interval_seconds", 0.1))
GAME_TICK_INTERVAL_SECONDS = float(_TIMING.get("game_tick_interval_seconds", 60.0))
COMBAT_ROUND_INTERVAL_SECONDS = float(_TIMING.get("combat_round_interval_seconds", 2.5))

HIT_ROLL_DICE_SIDES = int(_COMBAT.get("hit_roll_dice_sides", 20))
UNARMED_DAMAGE_VARIANCE = int(_COMBAT.get("unarmed_damage_variance", 2))

FLEE_SUCCESS_CHANCE = float(_GAMEPLAY.get("flee_success_chance", 0.5))
BASE_PLAYER_ARMOR_CLASS = int(_GAMEPLAY.get("base_player_armor_class", 10))

MAX_QUEUED_COMMANDS = int(_SESSION.get("max_queued_commands", 5))

PLAYER_REFERENCE_MAX_HP = int(_PLAYER.get("reference_max_hp", 575))
PLAYER_REFERENCE_MAX_VIGOR = int(_PLAYER.get("reference_max_vigor", 119))
PLAYER_REFERENCE_MAX_MANA = int(_PLAYER.get("reference_max_mana", 160))

CONFIGURABLE_ASSET_ROOT = SERVER_ROOT / str(_ASSETS.get("configurable_asset_directory", "configuration/assets"))