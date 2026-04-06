from grammar import capitalize_after_newlines
from protocol import build_response

PANEL_INNER_WIDTH = 34


def build_part(text: str, fg: str = "bright_white", bold: bool = False) -> dict:
    return {
        "text": text,
        "fg": fg,
        "bold": bold,
    }


def build_line(*parts: dict) -> list[dict]:
    return [part for part in parts if isinstance(part, dict)]


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
        base_colors.extend(["bright_cyan"] * (column_count - len(base_colors)))
        column_colors = base_colors

    if column_alignments is None or len(column_alignments) < column_count:
        base_alignments = list(column_alignments or [])
        base_alignments.extend(["left"] * (column_count - len(base_alignments)))
        column_alignments = base_alignments

    if not normalized_rows:
        return [
            build_part(_panel_title_line(title), "bright_cyan", True),
            build_part("\n"),
            build_part(_panel_divider(), "bright_black"),
            build_part("\n"),
            build_part(empty_message, "bright_white"),
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
        build_part(str(title).strip().center(panel_width), "bright_cyan", True),
        build_part("\n"),
        build_part("-" * panel_width, "bright_black"),
        build_part("\n"),
    ]

    for col_index in range(column_count):
        header_text = _align_text(normalized_headers[col_index], col_widths[col_index], column_alignments[col_index])
        parts.append(build_part(header_text, "bright_white", True))
        if col_index < column_count - 1:
            parts.append(build_part(" " * gap, "bright_white"))

    parts.extend([
        build_part("\n"),
        build_part("-" * panel_width, "bright_black"),
    ])

    for row_index, row in enumerate(normalized_rows):
        parts.append(build_part("\n"))
        for col_index in range(column_count):
            cell_color = column_colors[col_index]
            if row_cell_colors is not None and row_index < len(row_cell_colors):
                color_row = row_cell_colors[row_index]
                if col_index < len(color_row) and str(color_row[col_index]).strip():
                    cell_color = str(color_row[col_index]).strip()

            aligned_cell = _align_text(row[col_index], col_widths[col_index], column_alignments[col_index])
            parts.append(build_part(aligned_cell, cell_color, True))
            if col_index < column_count - 1:
                parts.append(build_part(" " * gap, "bright_white"))

    return parts


def _normalize_part(part: dict) -> dict:
    return {
        "text": str(part.get("text", "")),
        "fg": part.get("fg", "bright_white"),
        "bold": part.get("bold", False),
    }


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
                current_line.append({
                    "text": segment,
                    "fg": normalized_part["fg"],
                    "bold": normalized_part["bold"],
                })

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


def _trim_empty_edge_lines(lines: list[list[dict]]) -> tuple[int, list[list[dict]], int]:
    trimmed_lines = list(lines)
    blank_lines_before = 0
    blank_lines_after = 0

    while trimmed_lines and not trimmed_lines[0]:
        blank_lines_before += 1
        trimmed_lines.pop(0)

    while trimmed_lines and not trimmed_lines[-1]:
        blank_lines_after += 1
        trimmed_lines.pop()

    return blank_lines_before, trimmed_lines, blank_lines_after


def _blank_lines(count: int) -> list[list[dict]]:
    return [[] for _ in range(max(0, count))]


def build_display(
    parts: list[dict],
    *,
    blank_lines_before: int = 1,
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    starts_on_new_line: bool = False,
    is_error: bool = False,
) -> dict:
    content_lines = parts_to_lines(_capitalize_parts(parts))
    extra_blank_lines_before, content_lines, extra_blank_lines_after = _trim_empty_edge_lines(content_lines)

    effective_blank_lines_before = blank_lines_before + extra_blank_lines_before
    effective_blank_lines_after = blank_lines_after + extra_blank_lines_after

    sanitized_content_lines = _sanitize_lines(content_lines)

    prompt_lines: list[list[dict]] = []
    if prompt_after and prompt_parts:
        prompt_lines = _sanitize_lines(parts_to_lines(_capitalize_parts(prompt_parts)))

    display_lines = _blank_lines(effective_blank_lines_before) + sanitized_content_lines

    if prompt_lines:
        prompt_prefix_blank_lines = 2 if sanitized_content_lines else effective_blank_lines_after
        prompt_lines = _blank_lines(prompt_prefix_blank_lines) + prompt_lines
    else:
        display_lines.extend(_blank_lines(effective_blank_lines_after))

    if starts_on_new_line:
        display_lines = [[]] + display_lines

    return build_response("display", {
        "lines": display_lines,
        "prompt_lines": prompt_lines,
        "is_error": bool(is_error),
    })


def build_display_lines(
    lines: list[list[dict]],
    *,
    blank_lines_before: int = 1,
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
    starts_on_new_line: bool = False,
) -> dict:
    flattened_parts: list[dict] = []
    for index, line in enumerate(lines):
        if index > 0:
            flattened_parts.append(build_part("\n"))
        for part in line:
            if isinstance(part, dict):
                flattened_parts.append(_normalize_part(part))

    return build_display(
        flattened_parts,
        blank_lines_before=blank_lines_before,
        blank_lines_after=blank_lines_after,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
        starts_on_new_line=starts_on_new_line,
    )


def display_text(
    text: str,
    *,
    fg: str = "bright_white",
    bold: bool = False,
    blank_lines_before: int = 1,
    blank_lines_after: int = 0,
    prompt_after: bool = False,
    prompt_parts: list[dict] | None = None,
) -> dict:
    return build_display(
        [build_part(text, fg, bold)],
        blank_lines_before=blank_lines_before,
        blank_lines_after=blank_lines_after,
        prompt_after=prompt_after,
        prompt_parts=prompt_parts,
    )
