import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import websockets


@dataclass
class ClientSession:
    client_id: str
    websocket: object
    connected_at: str
    last_message_at: Optional[str] = None


connected_clients: dict[str, ClientSession] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_response(message_type: str, payload: dict) -> dict:
    return {
        "type": message_type,
        "source": "mudproto-server",
        "timestamp": utc_now_iso(),
        "payload": payload
    }


def validate_message(message: object) -> tuple[bool, str | None]:
    required_fields = ["type", "source", "timestamp", "payload"]

    if not isinstance(message, dict):
        return False, "Message must be a JSON object."

    for field in required_fields:
        if field not in message:
            return False, f"Missing required field: {field}"

    if not isinstance(message["type"], str):
        return False, "Field 'type' must be a string."

    if not isinstance(message["source"], str):
        return False, "Field 'source' must be a string."

    if not isinstance(message["timestamp"], str):
        return False, "Field 'timestamp' must be a string."

    if not isinstance(message["payload"], dict):
        return False, "Field 'payload' must be an object."

    return True, None


def get_connection_count() -> int:
    return len(connected_clients)


def register_client(client_id: str, websocket) -> ClientSession:
    session = ClientSession(
        client_id=client_id,
        websocket=websocket,
        connected_at=utc_now_iso()
    )
    connected_clients[client_id] = session
    return session


def unregister_client(client_id: str) -> None:
    connected_clients.pop(client_id, None)


def touch_session(session: ClientSession) -> None:
    session.last_message_at = utc_now_iso()


def handle_hello(message: dict, session: ClientSession) -> dict:
    source = message["source"]
    payload = message["payload"]
    name = payload.get("name", "unknown")

    return build_response("ack", {
        "message": f"Hello, {name}",
        "client_id": session.client_id,
        "received_type": "hello",
        "received_from": source,
        "connected_at": session.connected_at,
        "connection_count": get_connection_count()
    })


def handle_ping(message: dict, session: ClientSession) -> dict:
    source = message["source"]

    return build_response("pong", {
        "message": "Ping received.",
        "client_id": session.client_id,
        "received_type": "ping",
        "received_from": source,
        "connection_count": get_connection_count()
    })


def handle_whoami(message: dict, session: ClientSession) -> dict:
    return build_response("identity", {
        "client_id": session.client_id,
        "connected_at": session.connected_at,
        "last_message_at": session.last_message_at,
        "connection_count": get_connection_count()
    })


def dispatch_message(message: dict, session: ClientSession) -> dict:
    msg_type = message["type"]

    if msg_type == "hello":
        return handle_hello(message, session)

    if msg_type == "ping":
        return handle_ping(message, session)

    if msg_type == "whoami":
        return handle_whoami(message, session)

    return build_response("error", {
        "message": f"Unsupported message type: {msg_type}",
        "client_id": session.client_id,
        "connection_count": get_connection_count()
    })


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)
    print(f"Sent response: {message}")


async def handle_connection(websocket):
    client_id = str(uuid.uuid4())
    session = register_client(client_id, websocket)

    print(f"Client connected: {session.client_id}")
    print(f"Connected clients: {get_connection_count()}")

    try:
        connected_message = build_response("connected", {
            "client_id": session.client_id,
            "message": "Connection established.",
            "connection_count": get_connection_count()
        })
        await send_json(session.websocket, connected_message)

        async for message_text in session.websocket:
            touch_session(session)

            print(f"Raw message from {session.client_id}: {message_text}")

            try:
                message = json.loads(message_text)
            except json.JSONDecodeError as ex:
                response = build_response("error", {
                    "message": "Invalid JSON.",
                    "details": str(ex),
                    "client_id": session.client_id,
                    "connection_count": get_connection_count()
                })
                await send_json(session.websocket, response)
                continue

            print(f"Parsed message from {session.client_id}: {message}")

            is_valid, error_message = validate_message(message)
            if not is_valid:
                response = build_response("error", {
                    "message": error_message,
                    "client_id": session.client_id,
                    "connection_count": get_connection_count()
                })
                await send_json(session.websocket, response)
                continue

            response = dispatch_message(message, session)
            await send_json(session.websocket, response)

    finally:
        unregister_client(session.client_id)
        print(f"Client disconnected: {session.client_id}")
        print(f"Connected clients: {get_connection_count()}")


async def main():
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("Server listening on ws://localhost:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())