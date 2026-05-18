import json
import time
from datetime import datetime

import paho.mqtt.client as mqtt


BROKER = "localhost"
PORT = 1883
TOPIC = "gomoku/move"
KEEPALIVE_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 2
MQTT_SUCCESS = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)

DEFAULT_MOVES = [
    ("black", 6, 6),
    ("white", 6, 7),
    ("black", 7, 7),
    ("white", 7, 6),
    ("black", 8, 8),
    ("white", 8, 7),
    ("black", 9, 9),
    ("white", 9, 8),
    ("black", 5, 10),
    ("white", 10, 8),
    ("black", 4, 4),
    ("white", 11, 8),
    ("black", 12, 12),
    ("white", 12, 8),
    ("black", 10, 10),
]


def create_client():
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def publish_move(client, player, row, col, move_num, topic=TOPIC):
    data = {
        "player": player,
        "row": row,
        "column": col,
        "move_number": move_num,
        "timestamp": datetime.now().isoformat(),
    }

    payload = json.dumps(data)
    result = client.publish(topic, payload)
    rc = getattr(result, "rc", MQTT_SUCCESS)
    if rc != MQTT_SUCCESS:
        print(f"[MQTT] Publish failed with rc={rc}: {data}")
        return False

    print(f"Sent: {data}")
    return True


def main(moves=None, broker=BROKER, port=PORT, topic=TOPIC, interval_seconds=DEFAULT_INTERVAL_SECONDS):
    move_list = list(DEFAULT_MOVES if moves is None else moves)
    client = create_client()

    try:
        client.connect(broker, port, KEEPALIVE_SECONDS)
    except Exception as exc:
        print(f"[MQTT] Connection failed: {exc}")
        return 1

    ok = True
    try:
        for index, (player, row, col) in enumerate(move_list, start=1):
            ok = publish_move(client, player, row, col, index, topic=topic) and ok
            if interval_seconds > 0 and index < len(move_list):
                time.sleep(interval_seconds)
    finally:
        client.disconnect()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
