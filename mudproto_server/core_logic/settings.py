import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone


SERVER_ROOT = Path(__file__).resolve().parent.parent
SERVER_CONFIG_ROOT = SERVER_ROOT / "configuration" / "server"
SETTINGS_FILE = SERVER_CONFIG_ROOT / "settings.json"
DIRECTIONS_FILE = SERVER_CONFIG_ROOT / "directions.json"
HEALTH_CONDITIONS_FILE = SERVER_CONFIG_ROOT / "health_conditions.json"
DISPLAY_FEEDBACK_FILE = SERVER_CONFIG_ROOT / "display_feedback.json"
DISPLAY_COLORS_FILE = SERVER_CONFIG_ROOT / "display_colors.json"


def _load_json_object(path: Path, *, label: str) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")

    return raw


def _resolve_optional_path(value: object) -> Path | None:
    raw = str(value).strip()
    if not raw:
        return None

    path = Path(raw)
    if not path.is_absolute():
        path = SERVER_ROOT / path
    return path


@lru_cache(maxsize=1)
def load_server_settings() -> dict:
    return _load_json_object(SETTINGS_FILE, label="Server settings file")


@lru_cache(maxsize=1)
def load_direction_config() -> dict:
    return _load_json_object(DIRECTIONS_FILE, label="Directions config")


@lru_cache(maxsize=1)
def load_health_condition_config() -> dict:
    return _load_json_object(HEALTH_CONDITIONS_FILE, label="Health conditions config")


@lru_cache(maxsize=1)
def load_display_feedback_config() -> dict:
    return _load_json_object(DISPLAY_FEEDBACK_FILE, label="Display feedback config")


@lru_cache(maxsize=1)
def load_display_color_config() -> dict:
    return _load_json_object(DISPLAY_COLORS_FILE, label="Display colors config")


_SETTINGS = load_server_settings()
_DIRECTIONS = load_direction_config()
_HEALTH_CONDITIONS = load_health_condition_config()
_DISPLAY_FEEDBACK = load_display_feedback_config()
_DISPLAY_COLORS = load_display_color_config()


def _section(name: str) -> dict:
    value = _SETTINGS.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Server settings section '{name}' must be an object.")
    return value


_NETWORK = _section("network")
_TIMING = _section("timing")
_COMBAT = _section("combat")
_GAMEPLAY = _section("gameplay")
_GENERIC = _section("generic")
_SESSION = _section("session")
_OFFLINE = _section("offline")
_DATABASE = _section("database")
_ASSETS = _section("assets")

_raw_direction_short_labels = _DIRECTIONS.get("short_labels")
if not isinstance(_raw_direction_short_labels, dict) or not _raw_direction_short_labels:
    raise ValueError("Directions config must define a non-empty 'short_labels' object.")

_raw_direction_sort_order = _DIRECTIONS.get("sort_order")
if not isinstance(_raw_direction_sort_order, dict) or not _raw_direction_sort_order:
    raise ValueError("Directions config must define a non-empty 'sort_order' object.")

_raw_direction_aliases = _DIRECTIONS.get("aliases")
if not isinstance(_raw_direction_aliases, dict) or not _raw_direction_aliases:
    raise ValueError("Directions config must define a non-empty 'aliases' object.")

DIRECTION_SHORT_LABELS = {
    str(direction).strip().lower(): str(label).strip()
    for direction, label in _raw_direction_short_labels.items()
    if str(direction).strip() and str(label).strip()
}
DIRECTION_SORT_ORDER = {
    str(direction).strip().lower(): int(order)
    for direction, order in _raw_direction_sort_order.items()
    if str(direction).strip()
}
DIRECTION_ALIASES = {
    str(alias).strip().lower(): str(target).strip().lower()
    for alias, target in _raw_direction_aliases.items()
    if str(alias).strip() and str(target).strip()
}

_raw_health_condition_bands = _HEALTH_CONDITIONS.get("bands")
if not isinstance(_raw_health_condition_bands, list) or not _raw_health_condition_bands:
    raise ValueError("Health conditions config must define a non-empty 'bands' array.")

HEALTH_CONDITION_BANDS = sorted([
    {
        "max_ratio": max(0.0, min(1.0, float(band.get("max_ratio", 1.0)))),
        "label": str(band.get("label", "perfect")).strip().lower() or "perfect",
        "color": str(band.get("color", "feedback.success")).strip() or "feedback.success",
    }
    for band in _raw_health_condition_bands
    if isinstance(band, dict)
], key=lambda band: float(band.get("max_ratio", 1.0)))
if not HEALTH_CONDITION_BANDS:
    raise ValueError("Health conditions config must define at least one valid band.")

_raw_display_feedback_merchant_quotes = _DISPLAY_FEEDBACK.get("merchant_quotes")
if not isinstance(_raw_display_feedback_merchant_quotes, dict) or not _raw_display_feedback_merchant_quotes:
    raise ValueError("Display feedback config must define a non-empty 'merchant_quotes' object.")

_raw_display_feedback_simple_messages = _DISPLAY_FEEDBACK.get("simple_messages")
if not isinstance(_raw_display_feedback_simple_messages, dict) or not _raw_display_feedback_simple_messages:
    raise ValueError("Display feedback config must define a non-empty 'simple_messages' object.")

DISPLAY_FEEDBACK_MERCHANT_QUOTES = {
    str(code).strip().lower(): str(message).strip()
    for code, message in _raw_display_feedback_merchant_quotes.items()
    if str(code).strip() and str(message).strip()
}
DISPLAY_FEEDBACK_SIMPLE_MESSAGES = {
    str(code).strip().lower(): str(message).strip()
    for code, message in _raw_display_feedback_simple_messages.items()
    if str(code).strip() and str(message).strip()
}

DISPLAY_COLOR_MAP = {
    str(key).strip(): str(value).strip()
    for key, value in _DISPLAY_COLORS.items()
    if str(key).strip() and str(value).strip()
}

SERVER_HOST = str(_NETWORK.get("host", "localhost")).strip() or "localhost"
SERVER_PORT = int(_NETWORK.get("port", 8765))
MAX_CONNECTION_COUNT = max(1, int(_NETWORK.get("max_connection_count", 200)))
MAX_MESSAGE_SIZE_BYTES = max(1024, int(_NETWORK.get("max_message_size_bytes", 16384)))
SERVER_TLS_ENABLED = bool(_NETWORK.get("tls_enabled", False))
SERVER_TLS_CERTFILE = _resolve_optional_path(_NETWORK.get("tls_certfile", ""))
SERVER_TLS_KEYFILE = _resolve_optional_path(_NETWORK.get("tls_keyfile", ""))
SERVER_TLS_CA_FILE = _resolve_optional_path(_NETWORK.get("tls_ca_file", ""))
TLS_VERIFY_SERVER = bool(_NETWORK.get("tls_verify_server", False))

COMMAND_SCHEDULER_INTERVAL_SECONDS = float(_TIMING.get("command_scheduler_interval_seconds", 0.1))
GAME_TICK_INTERVAL_SECONDS = float(_TIMING.get("game_tick_interval_seconds", 60.0))
COMBAT_ROUND_INTERVAL_SECONDS = float(_TIMING.get("combat_round_interval_seconds", 2.5))

HIT_ROLL_DICE_SIDES = int(_COMBAT.get("hit_roll_dice_sides", 20))
UNARMED_DAMAGE_VARIANCE = int(_COMBAT.get("unarmed_damage_variance", 2))

FLEE_SUCCESS_CHANCE = float(_GAMEPLAY.get("flee_success_chance", 0.5))
BASE_PLAYER_ARMOR_CLASS = int(_GAMEPLAY.get("base_player_armor_class", 10))
ATTRIBUTE_MAX_CAP = int(_GAMEPLAY.get("attribute_max_cap", 28))
DEBUG_MODE = bool(_GAMEPLAY.get("debug_mode", False))
PAGINATE_TO = max(1, int(_GENERIC.get("paginate_to", 10)))

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