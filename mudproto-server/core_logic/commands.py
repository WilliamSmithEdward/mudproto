from display import display_error, display_prompt
from models import ClientSession
from session_timing import enqueue_command, is_session_lagged

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]


def parse_command(command_text: str) -> tuple[str, list[str]]:
    from command_handlers.runtime import parse_command as _parse_command

    return _parse_command(command_text)


def display_score(session: ClientSession) -> OutboundMessage:
    from command_handlers.runtime import display_score as _display_score

    return _display_score(session)


def normalize_direction(direction: str) -> str:
    from command_handlers.runtime import normalize_direction as _normalize_direction

    return _normalize_direction(direction)


def flee(session: ClientSession) -> OutboundResult:
    from command_handlers.runtime import flee as _flee

    return _flee(session)


def try_move(session: ClientSession, direction: str) -> OutboundResult:
    from command_handlers.runtime import try_move as _try_move

    return _try_move(session, direction)


def initial_auth_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import initial_auth_prompt as _initial_auth_prompt

    return _initial_auth_prompt(session)


def login_prompt(session: ClientSession) -> OutboundMessage:
    from command_handlers.auth import login_prompt as _login_prompt

    return _login_prompt(session)


def execute_command(session: ClientSession, command_text: str) -> OutboundResult:
    from command_handlers.registry import dispatch_command

    return dispatch_command(session, command_text)


async def process_input_message(message: dict, session: ClientSession) -> OutboundResult:
    payload = message["payload"]
    input_text = payload.get("text")

    if input_text is None:
        return display_prompt(session)

    if not isinstance(input_text, str):
        return display_error("Field 'payload.text' must be a string.", session)

    input_text = input_text.strip()
    if not input_text:
        return display_prompt(session)

    if not session.is_authenticated:
        from command_handlers.auth import process_auth_input

        return process_auth_input(session, input_text)

    if is_session_lagged(session):
        was_queued, queue_message = enqueue_command(session, input_text)
        if not was_queued:
            return display_error(queue_message, session)

        return {"type": "noop"}

    return execute_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> OutboundResult:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")
