import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime

# MQTT setup
broker = "localhost"
topic = "gomoku/move"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(broker, 1883, 60)


def publish_move(player, row, col, move_num):
    data = {
        "player": player,
        "row": row,
        "column": col,
        "move_number": move_num,
        "timestamp": datetime.now().isoformat()
    }

    payload = json.dumps(data)
    client.publish(topic, payload)

    print(f"Sent: {data}")

moves = [
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
    ("black", 10, 10)
]

move_number = 1

for player, row, col in moves:
    publish_move(player, row, col, move_number)
    move_number += 1
    time.sleep(2)
