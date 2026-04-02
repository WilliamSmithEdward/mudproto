import asyncio
import json
import sys
from datetime import datetime, timezone

import websockets


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
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


def render_parts(parts: list[dict]) -> str:
    rendered: list[str] = []

    for part in parts:
        if not isinstance(part, dict):
            continue

        text = str(part.get("text", ""))
        fg = part.get("fg")
        bold = bool(part.get("bold", False))

        if text.strip() == "":
            rendered.append(text)
        else:
            rendered.append(style_text(text, fg, bold))

    return "".join(rendered)


def render_lines(lines: list[list[dict]]) -> str:
    rendered_lines: list[str] = []

    for line in lines:
        if not isinstance(line, list):
            continue
        rendered_lines.append(render_parts(line))

    return "\n".join(rendered_lines)


def write_line(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)


def render_display_message(message: dict) -> None:
    payload = message.get("payload", {})
    blank_lines_before = int(payload.get("blank_lines_before", 0) or 0)
    blank_lines_after = int(payload.get("blank_lines_after", 0) or 0)
    prompt_blank_lines_before = int(payload.get("prompt_blank_lines_before", 0) or 0)
    prompt_lines = payload.get("prompt_lines") or []
    lines = payload.get("lines") or []
    starts_on_new_line = bool(payload.get("starts_on_new_line", False))

    has_lines = isinstance(lines, list) and len(lines) > 0
    has_prompt_lines = isinstance(prompt_lines, list) and len(prompt_lines) > 0

    if starts_on_new_line:
        sys.stdout.write("\n")

    if blank_lines_before > 0:
        sys.stdout.write("\n" * blank_lines_before)

    if has_lines:
        sys.stdout.write(render_lines(lines))

    if has_prompt_lines:
        if has_lines:
            sys.stdout.write("\n" * (prompt_blank_lines_before + 1))
        elif prompt_blank_lines_before > 0:
            sys.stdout.write("\n" * prompt_blank_lines_before)

        sys.stdout.write(render_lines(prompt_lines))
        sys.stdout.flush()
    elif has_lines:
        sys.stdout.write("\n" * (blank_lines_after + 1))

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
