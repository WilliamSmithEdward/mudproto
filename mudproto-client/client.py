import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any, TypeAlias

import websockets


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    ORANGE = "\033[38;5;208m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


COLOR_MAP = {
    "black": Ansi.BLACK,
    "red": Ansi.RED,
    "green": Ansi.GREEN,
    "yellow": Ansi.YELLOW,
    "orange": Ansi.ORANGE,
    "blue": Ansi.BLUE,
    "magenta": Ansi.MAGENTA,
    "cyan": Ansi.CYAN,
    "white": Ansi.WHITE,
    "bright_black": Ansi.BRIGHT_BLACK,
    "bright_red": Ansi.BRIGHT_RED,
    "bright_green": Ansi.BRIGHT_GREEN,
    "bright_yellow": Ansi.BRIGHT_YELLOW,
    "bright_blue": Ansi.BRIGHT_BLUE,
    "bright_magenta": Ansi.BRIGHT_MAGENTA,
    "bright_cyan": Ansi.BRIGHT_CYAN,
    "bright_white": Ansi.BRIGHT_WHITE,
}


Part: TypeAlias = dict[str, Any]
Line: TypeAlias = list[Part]


output_ends_with_newline = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_input_message(text: str) -> dict:
    return {
        "type": "input",
        "source": "mudproto-client",
        "timestamp": utc_now_iso(),
        "payload": {
            "text": text
        }
    }


def style_text(text: str, fg: str | None = None, bold: bool = False) -> str:
    prefix = ""

    if fg:
        prefix += COLOR_MAP.get(fg, "")

    if bold:
        prefix += Ansi.BOLD

    if not prefix:
        return text

    return f"{prefix}{text}{Ansi.RESET}"


def render_part(part: Part) -> str:
    text = str(part.get("text", ""))
    fg = part.get("fg")
    bold = bool(part.get("bold", False))

    # Whitespace-only text should remain unstyled to preserve exact spacing.
    if text.strip() == "":
        return text

    return style_text(text, fg, bold)


def render_parts(parts: list[Part]) -> str:
    return "".join(render_part(part) for part in parts if isinstance(part, dict))


def render_lines(lines: list[Line]) -> str:
    rendered_lines = [render_parts(line) for line in lines if isinstance(line, list)]
    return "\n".join(rendered_lines)


def _extract_lines(payload: dict, key: str) -> list[Line]:
    candidate = payload.get(key)
    if not isinstance(candidate, list):
        return []
    return [line for line in candidate if isinstance(line, list)]


def write_line(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)


def _write_line_group(lines: list[Line]) -> None:
    global output_ends_with_newline

    if not lines:
        return

    if not output_ends_with_newline and lines[0]:
        sys.stdout.write("\n")
        output_ends_with_newline = True

    sys.stdout.write(render_lines(lines))
    output_ends_with_newline = bool(lines and not lines[-1])


def render_display_message(message: dict) -> None:
    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        return

    prompt_lines = _extract_lines(payload, "prompt_lines")
    lines = _extract_lines(payload, "lines")

    if lines:
        _write_line_group(lines)

    if prompt_lines:
        _write_line_group(prompt_lines)

    sys.stdout.flush()


async def receive_loop(websocket) -> None:
    try:
        async for response_text in websocket:
            try:
                response = json.loads(response_text)
            except json.JSONDecodeError:
                continue

            if response.get("type") == "display":
                render_display_message(response)
            elif response.get("type") == "noop":
                pass

    except websockets.ConnectionClosed:
        write_line("\nConnection closed by server.")


async def input_loop(websocket) -> None:
    while True:
        user_input = await asyncio.to_thread(input, "")

        if user_input.lower().strip() == "/quit":
            write_line("Closing connection...")
            await websocket.close()
            break

        await send_json(websocket, build_input_message(user_input))


async def main():
    uri = "ws://localhost:8765"

    async with websockets.connect(uri) as websocket:
        receive_task = asyncio.create_task(receive_loop(websocket))
        input_task = asyncio.create_task(input_loop(websocket))

        done, pending = await asyncio.wait(
            {receive_task, input_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
