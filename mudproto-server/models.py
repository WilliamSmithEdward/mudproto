import asyncio
from dataclasses import dataclass, field
from typing import Optional

from websockets.asyncio.server import ServerConnection


@dataclass
class QueuedCommand:
    command_text: str
    received_at_iso: str


@dataclass
class PlayerState:
    current_room_id: str = "start"
    hit_points: int = 575
    vigor: int = 119
    extra_lives: int = 1
    coins: int = 4030
    attack_damage: int = 12
    attacks_per_round: int = 1




@dataclass
class EntityState:
    entity_id: str
    name: str
    room_id: str
    hit_points: int
    max_hit_points: int
    attack_damage: int = 1
    attacks_per_round: int = 1
    coin_reward: int = 0
    is_alive: bool = True
    spawn_sequence: int = 0


@dataclass
class ClientSession:
    client_id: str
    websocket: ServerConnection
    connected_at: str
    player: PlayerState = field(default_factory=PlayerState)
    last_message_at: Optional[str] = None
    lag_until_monotonic: Optional[float] = None
    command_queue: list[QueuedCommand] = field(default_factory=list)
    scheduler_task: Optional[asyncio.Task] = None
    prompt_pending_after_lag: bool = False
    entities: dict[str, EntityState] = field(default_factory=dict)
    entity_spawn_counter: int = 0
    engaged_entity_id: Optional[str] = None
    next_combat_round_monotonic: Optional[float] = None
