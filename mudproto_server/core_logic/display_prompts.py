"""Prompt builders for auth and character-creation flows."""

from attribute_config import load_player_classes
from display_core import build_part, newline_part
from display_feedback import display_command_result, display_prompt
from models import ClientSession


def initial_auth_prompt(session: ClientSession) -> dict[str, object]:
    return display_command_result(session, [
        build_part("Enter an existing character name (letters only) or type ", "feedback.text"),
        build_part("start", "feedback.warning", True),
        build_part(" to create a new character.", "feedback.text"),
    ])


def login_prompt(session: ClientSession) -> dict[str, object]:
    """Minimal login prompt (bare "> ") for re-entry after death or other events."""
    return display_prompt(session)


def build_new_character_name_prompt(session: ClientSession) -> dict[str, object]:
    return display_command_result(session, [
        build_part("Enter a new character name (letters only).", "feedback.text"),
    ])


def build_existing_password_prompt(session: ClientSession) -> dict[str, object]:
    return display_command_result(session, [
        build_part("Character found. Enter your password.", "feedback.text"),
    ])


def build_new_character_password_prompt(session: ClientSession) -> dict[str, object]:
    return display_command_result(session, [
        build_part("Enter a password for your character.", "feedback.text"),
    ])


def build_gender_prompt(session: ClientSession) -> dict[str, object]:
    return display_command_result(session, [
        build_part("Choose a gender: ", "feedback.text"),
        build_part("male", "feedback.value", True),
        build_part(" or ", "feedback.text"),
        build_part("female", "item_logic.highlight.item", True),
        build_part(".", "feedback.text"),
    ])


def build_class_prompt(session: ClientSession) -> dict[str, object]:
    classes = load_player_classes()
    parts: list[dict[str, object]] = [
        build_part("Choose a class by id or name:", "feedback.text"),
    ]
    for player_class in classes:
        parts.extend([
            newline_part(),
            build_part(" - ", "feedback.text"),
            build_part(str(player_class.get("class_id", "")), "feedback.value", True),
            build_part(" (", "feedback.text"),
            build_part(str(player_class.get("name", "")), "feedback.warning", True),
            build_part(")", "feedback.text"),
        ])
    return display_command_result(session, parts)
