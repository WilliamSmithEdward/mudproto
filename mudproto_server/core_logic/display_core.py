from grammar import capitalize_after_newlines
from protocol import build_response
from settings import DISPLAY_COLOR_MAP

PANEL_INNER_WIDTH = 34


def resolve_display_color(color_key_or_value: str | None, *, fallback: str = "display_core.default_fg") -> str:
    raw_value = str(color_key_or_value or "").strip()
    if raw_value:
        resolved = str(DISPLAY_COLOR_MAP.get(raw_value, "")).strip()
        if resolved:
            return resolved
        return raw_value

    fallback_value = str(fallback).strip()
    if fallback_value:
        resolved_fallback = str(DISPLAY_COLOR_MAP.get(fallback_value, "")).strip()
        if resolved_fallback:
            return resolved_fallback
        return fallback_value

    resolved_default = str(DISPLAY_COLOR_MAP.get("display_core.default_fg", "bright_white")).strip()
    return resolved_default or "bright_white"


def build_part(text: str, fg: str = "display_core.default_fg", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": resolve_display_color(fg),
        "bold": bold,
    }


def newline_part(count: int = 1) -> dict:
    if count <= 0:
        return build_part("")
    return build_part("\n" * count)


def build_line(*parts: dict) -> list[dict]:
    return [part for part in parts if isinstance(part, dict)]


def with_leading_blank_lines(parts: list[dict], count: int = 1) -> list[dict]:
    if count <= 0:
        return list(parts)
    return [build_part("\n" * count), *list(parts)]


def with_prompt_gap(prompt_parts: list[dict], gap_lines: int = 2) -> list[dict]:
    if gap_lines <= 0:
        return list(prompt_parts)
    return [build_part("\n" * gap_lines), *list(prompt_parts)]


def _panel_divider() -> str:
    return "-" * PANEL_INNER_WIDTH


def _panel_title_line(title: str) -> str:
    return str(title).strip().center(PANEL_INNER_WIDTH)


def build_menu_table_parts(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    column_colors: list[str] | None = None,
    row_cell_colors: list[list[str]] | None = None,
    column_alignments: list[str] | None = None,
    empty_message: str = "Nothing is known.",
) -> list[dict]:
    normalized_headers = [str(header).strip() for header in headers if str(header).strip()]
    if not normalized_headers:
        normalized_headers = ["Value"]

    column_count = len(normalized_headers)
    normalized_rows: list[list[str]] = []
    for row in rows:
        normalized_row = [str(cell) for cell in row[:column_count]]
        if len(normalized_row) < column_count:
            normalized_row.extend([""] * (column_count - len(normalized_row)))
        normalized_rows.append(normalized_row)

    if column_colors is None or len(column_colors) < column_count:
        base_colors = list(column_colors or [])
        base_colors.extend(["display_core.table.default_column"] * (column_count - len(base_colors)))
        column_colors = base_colors

    if column_alignments is None or len(column_alignments) < column_count:
        base_alignments = list(column_alignments or [])
        base_alignments.extend(["left"] * (column_count - len(base_alignments)))
        column_alignments = base_alignments

    if not normalized_rows:
        return [
            build_part(_panel_title_line(title), "display_core.table.title", True),
            newline_part(),
            build_part(_panel_divider(), "display_core.table.divider"),
            newline_part(),
            build_part(empty_message, "display_core.table.empty_message"),
        ]

    gap = 3
    col_widths: list[int] = []
    for col_index in range(column_count):
        max_cell = max(len(row[col_index]) for row in normalized_rows)
        col_widths.append(max(len(normalized_headers[col_index]), max_cell))

    content_width = sum(col_widths) + gap * (column_count - 1)
    panel_width = max(len(str(title).strip()), content_width)
    col_widths[0] += panel_width - content_width

    def _align_text(value: str, width: int, alignment: str) -> str:
        if alignment == "right":
            return value.rjust(width)
        if alignment == "center":
            return value.center(width)
        return value.ljust(width)

    parts: list[dict] = [
        build_part(str(title).strip().center(panel_width), "display_core.table.title", True),
        newline_part(),
        build_part("-" * panel_width, "display_core.table.divider"),
        newline_part(),
    ]

    for col_index in range(column_count):
        header_text = _align_text(normalized_headers[col_index], col_widths[col_index], column_alignments[col_index])
        parts.append(build_part(header_text, "display_core.table.headers", True))
        if col_index < column_count - 1:
            parts.append(build_part(" " * gap, "display_core.table.headers"))

    parts.extend([
        newline_part(),
        build_part("-" * panel_width, "display_core.table.divider"),
    ])

    for row_index, row in enumerate(normalized_rows):
        parts.append(newline_part())
        for col_index in range(column_count):
            cell_color = column_colors[col_index]
            if row_cell_colors is not None and row_index < len(row_cell_colors):
                color_row = row_cell_colors[row_index]
                if col_index < len(color_row) and str(color_row[col_index]).strip():
                    cell_color = str(color_row[col_index]).strip()

            aligned_cell = _align_text(row[col_index], col_widths[col_index], column_alignments[col_index])
            parts.append(build_part(aligned_cell, cell_color, True))
            if col_index < column_count - 1:
                parts.append(build_part(" " * gap, "display_core.default_fg"))

    return parts


def _normalize_part(part: dict) -> dict:
    normalized = {
        "text": str(part.get("text", "")),
        "fg": resolve_display_color(part.get("fg", "display_core.default_fg")),
        "bold": part.get("bold", False),
    }
    if bool(part.get("observer_plain", False)):
        normalized["observer_plain"] = True
    return normalized


def _capitalize_parts(parts: list[dict]) -> list[dict]:
    full_text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    capitalized_text = capitalize_after_newlines(full_text)

    offset = 0
    capitalized_parts: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue

        normalized_part = _normalize_part(part)
        original_text = normalized_part["text"]
        text_len = len(original_text)
        capitalized_portion = capitalized_text[offset:offset + text_len]
        offset += text_len
        normalized_part["text"] = capitalized_portion
        capitalized_parts.append(normalized_part)

    return capitalized_parts


def parts_to_lines(parts: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    saw_part = False

    for part in parts:
        if not isinstance(part, dict):
            continue

        normalized_part = _normalize_part(part)
        text = normalized_part["text"]
        segments = text.split("\n")
        saw_part = True

        for index, segment in enumerate(segments):
            if segment:
                line_part = {
                    "text": segment,
                    "fg": normalized_part["fg"],
                    "bold": normalized_part["bold"],
                }
                if bool(normalized_part.get("observer_plain", False)):
                    line_part["observer_plain"] = True
                current_line.append(line_part)

            if index < len(segments) - 1:
                lines.append(current_line)
                current_line = []

    if current_line or (saw_part and not lines):
        lines.append(current_line)

    return lines


def _sanitize_lines(lines: list[list[dict]]) -> list[list[dict]]:
    sanitized_lines: list[list[dict]] = []
    for line in lines:
        if not isinstance(line, list):
            continue
        sanitized_line = [
            _normalize_part(part)
            for part in line
            if isinstance(part, dict)
        ]
        sanitized_lines.append(sanitized_line)
    return sanitized_lines


def build_display(
    parts: list[dict],
    *,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    is_error: bool = False,
) -> dict:
    sanitized_content_lines = _sanitize_lines(parts_to_lines(_capitalize_parts(parts)))

    prompt_lines: list[list[dict]] = []
    if prompt_after and prompt_parts:
        prompt_lines = _sanitize_lines(parts_to_lines(_capitalize_parts(prompt_parts)))

    return build_response("display", {
        "lines": sanitized_content_lines,
        "prompt_lines": prompt_lines,
        "is_error": bool(is_error),
    })


def build_display_lines(
    lines: list[list[dict]],
    *,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
) -> dict:
    trailing_empty_count = 0
    for line in reversed(lines):
        if isinstance(line, list) and not line:
            trailing_empty_count += 1
            continue
        break

    flattened_parts: list[dict] = []
    for index, line in enumerate(lines):
        if index > 0:
            flattened_parts.append(newline_part())
        for part in line:
            if isinstance(part, dict):
                flattened_parts.append(_normalize_part(part))

    outbound = build_display(
        flattened_parts,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
    )

    if trailing_empty_count > 0:
        payload = outbound.get("payload") if isinstance(outbound, dict) else None
        if isinstance(payload, dict):
            existing_lines = payload.get("lines")
            if isinstance(existing_lines, list):
                existing_lines.extend([[] for _ in range(trailing_empty_count)])

    return outbound


def display_text(
    text: str,
    *,
    fg: str = "display_core.default_fg",
    bold: bool = False,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
    )
