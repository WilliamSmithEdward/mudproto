import asyncio
import json
import re
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

        rendered.append(style_text(text, fg, bold))

    return "".join(rendered)


def write_line(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _condition_to_fg(condition_name: str | None) -> str | None:
    if condition_name is None:
        return None

    normalized = condition_name.strip().lower()
    if normalized in {"awful", "very poor", "poor"}:
        return "bright_red"
    if normalized in {"average", "fair"}:
        return "bright_yellow"
    if normalized in {"good", "very good", "perfect"}:
        return "bright_green"
    return None


def _style_prompt_text(prompt_text: str) -> str:
    me_match = re.search(r"\[Me:([^\]]+)\]", prompt_text)
    npc_match = re.search(r"\[NPC:([^\]]+)\]", prompt_text)

    me_fg = _condition_to_fg(me_match.group(1) if me_match else None)
    npc_fg = _condition_to_fg(npc_match.group(1) if npc_match else None)

    styled = prompt_text
    if me_fg is not None and me_match is not None:
        raw_segment = me_match.group(0)
        condition_segment = me_match.group(1)
        colored_segment = raw_segment.replace(
            condition_segment,
            style_text(condition_segment, me_fg, True),
            1,
        )
        styled = styled.replace(raw_segment, colored_segment, 1)
    if npc_fg is not None and npc_match is not None:
        raw_segment = npc_match.group(0)
        condition_segment = npc_match.group(1)
        colored_segment = raw_segment.replace(
            condition_segment,
            style_text(condition_segment, npc_fg, True),
            1,
        )
        styled = styled.replace(raw_segment, colored_segment, 1)

    hp_match = re.match(r"(\d+)H", prompt_text)
    if hp_match is not None and me_fg is not None:
        styled = styled.replace(hp_match.group(0), style_text(hp_match.group(0), me_fg, True), 1)

    return styled


def write_prompt(prompt_text: str) -> None:
    sys.stdout.write(_style_prompt_text(prompt_text))
    sys.stdout.flush()


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)


def render_display_message(message: dict) -> None:
    payload = message.get("payload", {})
    prompt_after = bool(payload.get("prompt_after", False))
    prompt_text = str(payload.get("prompt_text", ">"))
    parts = payload.get("parts", [])
    starts_on_new_line = bool(payload.get("starts_on_new_line", False))

    has_parts = isinstance(parts, list) and len(parts) > 0

    if starts_on_new_line:
        sys.stdout.write("\n")

    if has_parts:
        sys.stdout.write(render_parts(parts))

    if has_parts and prompt_after:
        sys.stdout.write("\n\n")
        write_prompt(prompt_text)
    elif prompt_after:
        sys.stdout.write("\n")
        write_prompt(prompt_text)
    elif has_parts:
        sys.stdout.write("\n")

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
