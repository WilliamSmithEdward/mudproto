from command_handlers.parsing import parse_command
from command_handlers.queue import is_clear_queue_command
from command_handlers.registry import dispatch_command
from display_feedback import display_error, display_prompt
from models import ClientSession
from session_timing import enqueue_command, is_session_lagged

OutboundMessage = dict[str, object]
OutboundResult = OutboundMessage | list[OutboundMessage]


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

    verb, _args = parse_command(input_text)

    if is_session_lagged(session):
        if is_clear_queue_command(verb):
            return dispatch_command(session, input_text)

        was_queued, queue_message = enqueue_command(session, input_text)
        if not was_queued:
            return display_error(queue_message, session)

        return {"type": "noop"}

    return dispatch_command(session, input_text)


async def dispatch_message(message: dict, session: ClientSession) -> OutboundResult:
    msg_type = message["type"]

    if msg_type == "input":
        return await process_input_message(message, session)

    return display_error(f"Unsupported message type: {msg_type}")
