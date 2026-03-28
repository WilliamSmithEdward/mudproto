from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_response(message_type: str, payload: dict) -> dict:
    return {
        "type": message_type,
        "source": "mudproto-server",
        "timestamp": utc_now_iso(),
        "payload": payload
    }


def validate_message(message: object) -> str | None:
    required_fields = ["type", "source", "timestamp", "payload"]

    if not isinstance(message, dict):
        return "Message must be a JSON object."

    for field_name in required_fields:
        if field_name not in message:
            return f"Missing required field: {field_name}"

    if not isinstance(message["type"], str):
        return "Field 'type' must be a string."

    if not isinstance(message["source"], str):
        return "Field 'source' must be a string."

    if not isinstance(message["timestamp"], str):
        return "Field 'timestamp' must be a string."

    if not isinstance(message["payload"], dict):
        return "Field 'payload' must be an object."

    return None