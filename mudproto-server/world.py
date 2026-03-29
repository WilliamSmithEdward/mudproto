from dataclasses import dataclass, field

from assets import load_rooms


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

    for room_data in load_rooms():
        room = Room(
            room_id=room_data["room_id"],
            title=room_data["title"],
            description=room_data["description"],
            exits=room_data["exits"],
        )
        world.rooms[room.room_id] = room

    for room in world.rooms.values():
        for direction, destination_room_id in room.exits.items():
            if destination_room_id not in world.rooms:
                raise ValueError(
                    f"Room '{room.room_id}' has exit '{direction}' to unknown room '{destination_room_id}'."
                )

    return world


WORLD = build_default_world()


def get_room(room_id: str) -> Room | None:
    return WORLD.rooms.get(room_id)