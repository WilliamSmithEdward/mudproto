import asyncio
import json
from datetime import datetime, timezone

import websockets


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def receive_json(websocket) -> dict:
    response_text = await websocket.recv()
    print(f"Raw response: {response_text}")

    response = json.loads(response_text)
    print(f"Parsed response: {response}")
    return response


async def send_json(websocket, message: dict) -> None:
    message_text = json.dumps(message)
    await websocket.send(message_text)
    print(f"Sent: {message_text}")


def build_message(message_type: str, payload: dict) -> dict:
    return {
        "type": message_type,
        "source": "mudproto-client",
        "timestamp": utc_now_iso(),
        "payload": payload
    }


async def main():
    uri = "ws://localhost:8765"

    async with websockets.connect(uri) as websocket:
        connected_response = await receive_json(websocket)
        client_id = connected_response["payload"]["client_id"]
        print(f"Assigned client_id: {client_id}")

        await send_json(websocket, build_message("hello", {
            "name": "William"
        }))
        await receive_json(websocket)

        await send_json(websocket, build_message("ping", {}))
        await receive_json(websocket)

        await send_json(websocket, build_message("whoami", {}))
        await receive_json(websocket)


if __name__ == "__main__":
    asyncio.run(main())