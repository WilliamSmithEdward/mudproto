from dataclasses import dataclass, field


@dataclass
class Room:
    room_id: str
    title: str
    description: str
    exits: dict[str, str] = field(default_factory=dict)


@dataclass
class WorldState:
    rooms: dict[str, Room] = field(default_factory=dict)


def build_default_world() -> WorldState:
    world = WorldState()

    world.rooms["start"] = Room(
        room_id="start",
        title="Prototype Chamber",
        description="A plain stone chamber used for early server testing.",
        exits={
            "north": "hall"
        }
    )

    world.rooms["hall"] = Room(
        room_id="hall",
        title="Northern Hall",
        description="A narrow hall of cold stone extends here, quiet and still.",
        exits={
            "south": "start"
        }
    )

    return world


WORLD = build_default_world()


def get_room(room_id: str) -> Room | None:
    return WORLD.rooms.get(room_id)