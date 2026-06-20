"""Password hashing tests: KDF format, verification, and legacy upgrade (RG-12)."""

import player_state_db
from player_state_db import (
    _hash_password,
    _hash_password_legacy_sha256,
    _password_matches,
    create_character,
    verify_character_credentials,
)


def test_new_hash_uses_pbkdf2_format() -> None:
    stored = _hash_password("hunter2", "abc123")
    assert stored.startswith("pbkdf2_sha256$")


def test_password_matches_accepts_correct_and_rejects_wrong() -> None:
    salt = "abc123"
    stored = _hash_password("hunter2", salt)
    assert _password_matches("hunter2", salt, stored) is True
    assert _password_matches("wrong", salt, stored) is False


def test_legacy_sha256_hash_still_verifies() -> None:
    salt = "deadbeef"
    legacy = _hash_password_legacy_sha256("hunter2", salt)
    assert not legacy.startswith("pbkdf2_sha256$")
    assert _password_matches("hunter2", salt, legacy) is True
    assert _password_matches("wrong", salt, legacy) is False


def test_create_and_verify_roundtrip_stores_kdf_hash() -> None:
    created = create_character(
        character_name="Tester",
        password="s3cret-pass",
        class_id="warrior",
        gender="male",
        login_room_id="start",
    )
    assert verify_character_credentials("Tester", "s3cret-pass") is not None
    assert verify_character_credentials("Tester", "nope") is None

    with player_state_db._connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM characters WHERE character_key = ?",
            (created["character_key"],),
        ).fetchone()
    assert str(row["password_hash"]).startswith("pbkdf2_sha256$")


def test_legacy_hash_is_upgraded_on_login() -> None:
    created = create_character(
        character_name="Legacyuser",
        password="old-pass",
        class_id="warrior",
        gender="female",
        login_room_id="start",
    )
    key = created["character_key"]

    salt = "legacy-salt"
    legacy = _hash_password_legacy_sha256("old-pass", salt)
    with player_state_db._connect() as connection:
        connection.execute(
            "UPDATE characters SET password_salt = ?, password_hash = ? WHERE character_key = ?",
            (salt, legacy, key),
        )
        connection.commit()

    assert verify_character_credentials("Legacyuser", "old-pass") is not None

    with player_state_db._connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM characters WHERE character_key = ?",
            (key,),
        ).fetchone()
    assert str(row["password_hash"]).startswith("pbkdf2_sha256$")
