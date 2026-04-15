import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone


SERVER_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = SERVER_ROOT / "configuration" / "server" / "settings.json"
CONSTANTS_FILE = SERVER_ROOT / "configuration" / "server" / "constants.json"


@lru_cache(maxsize=1)
def load_server_settings() -> dict:
    with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"Server settings file must contain an object: {SETTINGS_FILE}")

    return raw


@lru_cache(maxsize=1)
def load_server_constants() -> dict:
    if not CONSTANTS_FILE.exists():
        return {}

    raw_text = CONSTANTS_FILE.read_text(encoding="utf-8").strip()
    if not raw_text:
        return {}

    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"Server constants file must contain an object: {CONSTANTS_FILE}")

    return raw


_SETTINGS = load_server_settings()
_CONSTANTS = load_server_constants()


def _section(name: str) -> dict:
    value = _SETTINGS.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Server settings section '{name}' must be an object.")
    return value


def _constant_section(name: str) -> dict:
    value = _CONSTANTS.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Server constants section '{name}' must be an object.")
    return value


_NETWORK = _section("network")
_TIMING = _section("timing")
_COMBAT = _section("combat")
_GAMEPLAY = _section("gameplay")
_SESSION = _section("session")
_OFFLINE = _section("offline")
_DATABASE = _section("database")
_ASSETS = _section("assets")
_DIRECTIONS = _constant_section("directions")
_HEALTH_CONDITIONS = _constant_section("health_conditions")

_DEFAULT_DIRECTION_SHORT_LABELS = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "up": "U",
    "down": "D",
}
_DEFAULT_DIRECTION_SORT_ORDER = {
    "north": 0,
    "east": 1,
    "south": 2,
    "west": 3,
    "up": 4,
    "down": 5,
}
_DEFAULT_DIRECTION_ALIASES = {
    "n": "north",
    "north": "north",
    "s": "south",
    "south": "south",
    "e": "east",
    "east": "east",
    "w": "west",
    "west": "west",
    "u": "up",
    "up": "up",
    "d": "down",
    "down": "down",
}
_DEFAULT_HEALTH_CONDITION_BANDS = [
    {"max_ratio": 0.15, "label": "awful", "color": "bright_red"},
    {"max_ratio": 0.30, "label": "very poor", "color": "bright_red"},
    {"max_ratio": 0.45, "label": "poor", "color": "bright_red"},
    {"max_ratio": 0.60, "label": "average", "color": "bright_yellow"},
    {"max_ratio": 0.75, "label": "fair", "color": "bright_yellow"},
    {"max_ratio": 0.90, "label": "good", "color": "bright_green"},
    {"max_ratio": 0.999999, "label": "very good", "color": "bright_green"},
    {"max_ratio": 1.0, "label": "perfect", "color": "bright_green"},
]

DIRECTION_SHORT_LABELS = {
    **_DEFAULT_DIRECTION_SHORT_LABELS,
    **{
        str(direction).strip().lower(): str(label).strip()
        for direction, label in dict(_DIRECTIONS.get("short_labels", {})).items()
        if str(direction).strip() and str(label).strip()
    },
}
DIRECTION_SORT_ORDER = {
    **_DEFAULT_DIRECTION_SORT_ORDER,
    **{
        str(direction).strip().lower(): int(order)
        for direction, order in dict(_DIRECTIONS.get("sort_order", {})).items()
        if str(direction).strip()
    },
}
DIRECTION_ALIASES = {
    **_DEFAULT_DIRECTION_ALIASES,
    **{
        str(alias).strip().lower(): str(target).strip().lower()
        for alias, target in dict(_DIRECTIONS.get("aliases", {})).items()
        if str(alias).strip() and str(target).strip()
    },
}

_raw_health_condition_bands = _HEALTH_CONDITIONS.get("bands", _DEFAULT_HEALTH_CONDITION_BANDS)
if not isinstance(_raw_health_condition_bands, list) or not _raw_health_condition_bands:
    _raw_health_condition_bands = list(_DEFAULT_HEALTH_CONDITION_BANDS)

HEALTH_CONDITION_BANDS = sorted([
    {
        "max_ratio": max(0.0, min(1.0, float(band.get("max_ratio", 1.0)))),
        "label": str(band.get("label", "perfect")).strip().lower() or "perfect",
        "color": str(band.get("color", "bright_green")).strip() or "bright_green",
    }
    for band in _raw_health_condition_bands
    if isinstance(band, dict)
], key=lambda band: float(band.get("max_ratio", 1.0))) or list(_DEFAULT_HEALTH_CONDITION_BANDS)


SERVER_HOST = str(_NETWORK.get("host", "localhost")).strip() or "localhost"
SERVER_PORT = int(_NETWORK.get("port", 8765))

COMMAND_SCHEDULER_INTERVAL_SECONDS = float(_TIMING.get("command_scheduler_interval_seconds", 0.1))
GAME_TICK_INTERVAL_SECONDS = float(_TIMING.get("game_tick_interval_seconds", 60.0))
COMBAT_ROUND_INTERVAL_SECONDS = float(_TIMING.get("combat_round_interval_seconds", 2.5))

HIT_ROLL_DICE_SIDES = int(_COMBAT.get("hit_roll_dice_sides", 20))
UNARMED_DAMAGE_VARIANCE = int(_COMBAT.get("unarmed_damage_variance", 2))

FLEE_SUCCESS_CHANCE = float(_GAMEPLAY.get("flee_success_chance", 0.5))
BASE_PLAYER_ARMOR_CLASS = int(_GAMEPLAY.get("base_player_armor_class", 10))
DEBUG_MODE = bool(_GAMEPLAY.get("debug_mode", False))

MAX_QUEUED_COMMANDS = int(_SESSION.get("max_queued_commands", 5))

OFFLINE_LOOP_SLEEP_SECONDS = float(_OFFLINE.get("loop_sleep_seconds", 0.5))
OFFLINE_FLEE_INTERVAL_SECONDS = float(_OFFLINE.get("flee_interval_seconds", 2.0))
OFFLINE_SAFE_HOURS_TO_DISCONNECT = int(_OFFLINE.get("safe_hours_to_disconnect", 5))

DATABASE_DIRECTORY = SERVER_ROOT / (str(_DATABASE.get("directory", "db")).strip() or "db")
DATABASE_FILENAME = str(_DATABASE.get("filename", "mudproto.sqlite3")).strip() or "mudproto.sqlite3"
PLAYER_STATE_DB_PATH = DATABASE_DIRECTORY / DATABASE_FILENAME
DEFAULT_PLAYER_STATE_KEY = str(_DATABASE.get("player_key", "default")).strip() or "default"

DEFAULT_PLAYER_REFERENCE_MAX_HP = 575
DEFAULT_PLAYER_REFERENCE_MAX_VIGOR = 119
DEFAULT_PLAYER_REFERENCE_MAX_MANA = 160


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_player_reference_settings_from_db() -> tuple[int, int, int]:
    DATABASE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(PLAYER_STATE_DB_PATH))
    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS player_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        defaults = {
            "reference_max_hp": DEFAULT_PLAYER_REFERENCE_MAX_HP,
            "reference_max_vigor": DEFAULT_PLAYER_REFERENCE_MAX_VIGOR,
            "reference_max_mana": DEFAULT_PLAYER_REFERENCE_MAX_MANA,
        }

        for key, value in defaults.items():
            connection.execute(
                """
                INSERT INTO player_settings(setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO NOTHING
                """,
                (key, int(value), _utc_now_iso()),
            )

        rows = connection.execute(
            "SELECT setting_key, setting_value FROM player_settings"
        ).fetchall()
        connection.commit()

        values = {str(row["setting_key"]): int(row["setting_value"]) for row in rows}
        max_hp = int(values.get("reference_max_hp", DEFAULT_PLAYER_REFERENCE_MAX_HP))
        max_vigor = int(values.get("reference_max_vigor", DEFAULT_PLAYER_REFERENCE_MAX_VIGOR))
        max_mana = int(values.get("reference_max_mana", DEFAULT_PLAYER_REFERENCE_MAX_MANA))
        return max_hp, max_vigor, max_mana
    finally:
        connection.close()


PLAYER_REFERENCE_MAX_HP, PLAYER_REFERENCE_MAX_VIGOR, PLAYER_REFERENCE_MAX_MANA = _load_player_reference_settings_from_db()

CONFIGURABLE_ASSET_ROOT = SERVER_ROOT / str(_ASSETS.get("configurable_asset_directory", "configuration/assets"))