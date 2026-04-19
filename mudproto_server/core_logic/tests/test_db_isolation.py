from pathlib import Path

import player_state_db
import settings


def test_server_tests_do_not_use_live_player_database() -> None:
    repo_db = Path(__file__).resolve().parents[2] / "db" / "mudproto.sqlite3"

    assert player_state_db.PLAYER_STATE_DB_PATH != repo_db
    assert settings.PLAYER_STATE_DB_PATH != repo_db
