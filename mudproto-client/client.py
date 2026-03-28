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


def build_message(message_type: str, payload: dict) -> dict:
    return {
        "type": message_type,
        "source": "mudproto-client",
        "timestamp": utc_now_iso(),
        "payload": payload
    }


def print_prompt() -> None:
    sys.stdout.write("\n\n> ")
    sys.stdout.flush()


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

        rendered.append(style_text(text, fg, bold))

    return "".join(rendered)


def write_line(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)


def render_display_message(message: dict) -> None:
    payload = message.get("payload", {})
    blank_lines_before = int(payload.get("blank_lines_before", 0))
    prompt_after = bool(payload.get("prompt_after", True))
    parts = payload.get("parts", [])

    if blank_lines_before > 0:
        sys.stdout.write("\n" * blank_lines_before)

    if isinstance(parts, list) and parts:
        sys.stdout.write(render_parts(parts))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")

    sys.stdout.flush()

    if prompt_after:
        print_prompt()


async def receive_loop(websocket) -> None:
    try:
        async for response_text in websocket:
            try:
                response = json.loads(response_text)
            except json.JSONDecodeError:
                write_line("Received non-JSON response from server.")
                print_prompt()
                continue

            if response.get("type") == "display":
                render_display_message(response)
            else:
                write_line(json.dumps(response, ensure_ascii=False))
                print_prompt()

    except websockets.ConnectionClosed:
        write_line("\nConnection closed by server.")


async def input_loop(websocket) -> None:
    write_line("Type commands and press Enter.")
    write_line("Special local commands:")
    write_line("  /hello <name>")
    write_line("  /ping")
    write_line("  /whoami")
    write_line("  /quit")
    write_line("Anything else will be sent as a game command.")

    while True:
        print_prompt()
        user_input = await asyncio.to_thread(input, "")
        user_input = user_input.strip()

        if not user_input:
            continue

        if user_input.lower() == "/quit":
            write_line("Closing connection...")
            await websocket.close()
            break

        if user_input.lower().startswith("/hello"):
            parts = user_input.split(maxsplit=1)
            name = parts[1] if len(parts) > 1 else "William"

            await send_json(websocket, build_message("hello", {
                "name": name
            }))
            continue

        if user_input.lower() == "/ping":
            await send_json(websocket, build_message("ping", {}))
            continue

        if user_input.lower() == "/whoami":
            await send_json(websocket, build_message("whoami", {}))
            continue

        await send_json(websocket, build_message("command", {
            "command_text": user_input
        }))


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