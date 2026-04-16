"""Shared menu builders for spell and skill list displays."""

from display_core import build_menu_table_parts, build_part, newline_part


def build_cost_menu_parts(
    title: str,
    entries: list[tuple[str, str, int]],
    cost_resource_label: str,
    middle_column_header: str | None = None,
) -> list[dict]:
    if not entries:
        return [
            build_part(title, "display_character.label", True),
            newline_part(),
            build_part("Nothing is known.", "display_core.default_fg"),
        ]

    has_middle_column = bool(middle_column_header and middle_column_header.strip())
    sorted_entries = sorted(
        [
            (
                str(name).strip() or title,
                str(middle_value).strip(),
                max(0, int(cost)),
            )
            for name, middle_value, cost in entries
        ],
        key=lambda entry: entry[0].lower(),
    )

    if has_middle_column:
        middle_header_label = str(middle_column_header or "").strip()
        rows = [
            [
                name,
                middle_value,
                "Free" if cost <= 0 else f"{cost} {cost_resource_label}",
            ]
            for name, middle_value, cost in sorted_entries
        ]
        return build_menu_table_parts(
            title,
            ["Name", middle_header_label, "Cost"],
            rows,
            column_colors=["display_character.equipment.slot_column", "display_character.equipment.item_column", "commerce.stock.column.price"],
            column_alignments=["left", "left", "right"],
        )

    rows = [
        [
            name,
            "Free" if cost <= 0 else f"{cost} {cost_resource_label}",
        ]
        for name, _, cost in sorted_entries
    ]
    return build_menu_table_parts(
        title,
        ["Name", "Cost"],
        rows,
        column_colors=["display_character.equipment.slot_column", "commerce.stock.column.price"],
        column_alignments=["left", "right"],
    )
