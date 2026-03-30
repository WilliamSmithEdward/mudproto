# Player State DB Maintenance

This server persists player state in SQLite.

- DB file: `DB/mudproto.sqlite3`
- Primary table: `player_state`
- Primary key: `player_key`
- Default player key: `default`
- Player settings table: `player_settings`
- Character auth table: `characters`

## Initialization

- The database is auto-initialized on first server run.
- If `DB/mudproto.sqlite3` does not exist, the server creates it and creates required tables.

## Server Tuning

Offline character behavior is configured in `configuration/server/settings.json` under `offline`:

- `loop_sleep_seconds`: polling sleep interval for offline processing loop.
- `flee_interval_seconds`: delay between automatic flee attempts while offline and engaged.
- `safe_hours_to_disconnect`: number of safe game hours (no engagement, no damage) before server-side disconnect.

## Backup

1. Stop the server process to avoid copying a live-writing DB.
2. Copy `DB/mudproto.sqlite3` to a backup location.
3. Keep timestamped backups.

## Restore

1. Stop the server process.
2. Replace `DB/mudproto.sqlite3` with the backup copy.
3. Start the server.

## Inspect Data

Using sqlite3 CLI:

```powershell
sqlite3 DB/mudproto.sqlite3
.tables
SELECT player_key, updated_at FROM player_state;
SELECT json_extract(state_json, '$.player.current_room_id') AS room FROM player_state WHERE player_key='default';
SELECT setting_key, setting_value, updated_at FROM player_settings;
SELECT character_key, character_name, class_id, login_room_id FROM characters ORDER BY character_name;
```

## Player Settings In DB

Player max reference values are stored in `player_settings`:

- `reference_max_hp`
- `reference_max_vigor`
- `reference_max_mana`

Update example:

```powershell
sqlite3 DB/mudproto.sqlite3 "UPDATE player_settings SET setting_value=650, updated_at=datetime('now') WHERE setting_key='reference_max_hp';"
```

## Character Login Room

Character login room is stored in `characters.login_room_id` and is used when that character connects.
This is intentionally separate from the last room saved in `player_state`.

Update example:

```powershell
sqlite3 DB/mudproto.sqlite3 "UPDATE characters SET login_room_id='start', updated_at=datetime('now') WHERE character_key='alice';"
```

## Configurable Attributes

Base attribute definitions are configured in `configuration/assets/attributes.json`.

Default shipped attributes:

- Strength (`str`)
- Wisdom (`wis`)
- Intelligence (`int`)
- Dexterity (`dex`)
- Constitution (`con`)

Class-specific attribute ranges are configured per class in `configuration/assets/classes.json`
under `attribute_ranges`.

When a character is created, each configured attribute is rolled from that class range.

Per-character attribute values are persisted in `player_state.state_json` under:

- `player.attributes`

## Vacuum / Optimize

Run occasionally after many updates/deletes:

```powershell
sqlite3 DB/mudproto.sqlite3 "VACUUM;"
```

## Schema Notes

- `state_json` stores serialized player/session state relevant to persistence.
- If schema changes are needed, add migration SQL in server code before table use.

## Corruption Handling

- If the DB is corrupted and cannot be opened, restore from backup.
- If no backup exists, delete `DB/mudproto.sqlite3` and restart server (player state resets).
