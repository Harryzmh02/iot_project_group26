import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

import main_pipeline


FLOW_PATH = PROJECT_ROOT / "dashboard" / "flows.json"


def load_nodes():
    return json.loads(FLOW_PATH.read_text(encoding="utf-8"))


def find_single(nodes, description, predicate):
    matches = [node for node in nodes if predicate(node)]
    assert len(matches) == 1, f"Expected exactly one {description}, found {len(matches)}"
    return matches[0]


def test_dashboard_uses_pipeline_mqtt_topic():
    nodes = load_nodes()
    mqtt_input = find_single(nodes, "MQTT input node", lambda node: node.get("type") == "mqtt in")
    assert mqtt_input["topic"] == main_pipeline.MQTT_TOPIC
    print("PASS: dashboard MQTT topic matches main_pipeline.MQTT_TOPIC")


def test_reset_wires_clear_board_before_history():
    nodes = load_nodes()
    board_group = find_single(
        nodes, "board group", lambda node: node.get("type") == "ui_group" and node.get("name") == "Gomoku Board"
    )
    history_group = find_single(
        nodes, "history group", lambda node: node.get("type") == "ui_group" and node.get("name") == "Move History"
    )
    board_template = find_single(
        nodes,
        "board template",
        lambda node: node.get("type") == "ui_template"
        and node.get("group") == board_group["id"]
        and "gomoku-board" in node.get("format", ""),
    )
    history_template = find_single(
        nodes,
        "history template",
        lambda node: node.get("type") == "ui_template"
        and node.get("group") == history_group["id"]
        and "ng-bind-html" in node.get("format", ""),
    )
    reset_node = find_single(
        nodes, "reset function", lambda node: node.get("type") == "function" and node.get("name") == "reset"
    )

    assert reset_node["wires"][0] == [board_template["id"]]
    assert reset_node["wires"][1] == [history_template["id"]]
    print("PASS: reset sends board payload to board widget and history payload to history widget")


if __name__ == "__main__":
    test_dashboard_uses_pipeline_mqtt_topic()
    test_reset_wires_clear_board_before_history()
    print("\nAll dashboard flow contract tests passed.")
