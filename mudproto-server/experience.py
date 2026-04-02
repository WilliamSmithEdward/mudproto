from attribute_config import load_experience_table
from models import ClientSession


def _normalize_total_experience(total_experience: int) -> int:
    return max(0, int(total_experience))


def get_level_for_experience(total_experience: int) -> int:
    total_experience = _normalize_total_experience(total_experience)
    table = load_experience_table()

    level = 1
    for row in table:
        row_total = int(row.get("total_experience", 0))
        row_level = int(row.get("level", level))
        if total_experience >= row_total:
            level = row_level
        else:
            break

    return max(1, level)


def get_xp_to_next_level(total_experience: int) -> int:
    total_experience = _normalize_total_experience(total_experience)
    table = load_experience_table()

    for row in table:
        row_total = int(row.get("total_experience", 0))
        if row_total > total_experience:
            return max(0, row_total - total_experience)

    return 0


def award_experience(session: ClientSession, experience_amount: int) -> tuple[int, int, int, int]:
    gained = max(0, int(experience_amount))
    old_level = get_level_for_experience(session.player.experience_points)

    if gained > 0:
        session.player.experience_points = max(0, int(session.player.experience_points) + gained)

    new_level = get_level_for_experience(session.player.experience_points)
    session.player.level = new_level
    xp_to_next = get_xp_to_next_level(session.player.experience_points)
    return gained, old_level, new_level, xp_to_next
