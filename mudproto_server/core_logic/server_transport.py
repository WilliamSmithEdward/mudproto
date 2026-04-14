import json

from websockets.asyncio.server import ServerConnection
import websockets


async def send_json(websocket: ServerConnection, message: dict) -> bool:
    message_text = json.dumps(message)
    try:
        await websocket.send(message_text)
    except websockets.ConnectionClosed:
        return False

    print(f"Sent response: {message}")
    return True


async def send_outbound(
    websocket: ServerConnection,
    outbound: dict | list[dict],
) -> bool:
    delivered = True
    if isinstance(outbound, list):
        for message in outbound:
            delivered = await send_json(websocket, message) and delivered
    else:
        delivered = await send_json(websocket, outbound)
    return delivered
