import asyncio
from dataclasses import dataclass, field
from typing import Optional

from websockets.asyncio.server import ServerConnection


@dataclass
class QueuedCommand:
    command_text: str
    received_at_iso: str


@dataclass
class ClientSession:
    client_id: str
    websocket: ServerConnection
    connected_at: str
    current_room_id: str = "start"
    last_message_at: Optional[str] = None
    lag_until_monotonic: Optional[float] = None
    command_queue: list[QueuedCommand] = field(default_factory=list)
    scheduler_task: Optional[asyncio.Task] = None