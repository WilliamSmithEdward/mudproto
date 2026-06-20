import asyncio
import json
import logging

from websockets.asyncio.server import ServerConnection
import websockets

logger = logging.getLogger("mudproto.server_transport")

# Maximum time to wait for a single websocket send before giving up on that
# delivery, so a slow or stalled client cannot block the sending task (RG-23).
SEND_TIMEOUT_SECONDS = 10.0


async def send_json(websocket: ServerConnection, message: dict) -> bool:
    message_text = json.dumps(message)
    try:
        await asyncio.wait_for(websocket.send(message_text), timeout=SEND_TIMEOUT_SECONDS)
    except websockets.ConnectionClosed:
        return False
    except asyncio.TimeoutError:
        logger.warning("Timed out sending to a client after %ss; dropping message", SEND_TIMEOUT_SECONDS)
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
