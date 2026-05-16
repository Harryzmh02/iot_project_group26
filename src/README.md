# Gomoku IoT Dashboard – MQTT + Node-RED Demo

This project implements the IoT communication and dashboard component for a Gomoku board state monitoring system.

The system uses a Python MQTT publisher to simulate detected Gomoku moves, sends the move data through a Mosquitto MQTT broker, and visualises the game state in Node-RED Dashboard.

## Features

- MQTT broker communication
- Python publisher script
- JSON-based move data format
- Node-RED dashboard integration
- Real-time player display
- Move number display
- Board position display
- Visual 15 × 15 Gomoku board
- Black and white stones displayed on board intersections
- Move history log
- Reset Game button
- Winner detection for:
  - Horizontal five-in-a-row
  - Vertical five-in-a-row
  - Diagonal five-in-a-row

## Project Structure

```text
project/
├── src/
│   └── mqtt.py
├── node_red/
│   └── gomoku_dashboard_flow.json
├── requirements.txt
└── README.md
```

## Required Software

This project requires the following software to be installed:

1. Python
2. Mosquitto MQTT Broker
3. Node.js
4. Node-RED
5. Node-RED Dashboard nodes

Python dependencies are listed in:

```text
requirements.txt
```

Install them using:

```powershell
python -m pip install -r requirements.txt
```

## Python Dependency

The Python publisher uses:

```text
paho-mqtt==2.1.0
```

## MQTT Topic

The system uses the following MQTT topic:

```text
gomoku/move
```

The Python publisher and Node-RED MQTT input node must use the same topic.

## JSON Message Format

Each move is published as a JSON message:

```json
{
  "player": "black",
  "row": 8,
  "column": 8,
  "move_number": 1,
  "timestamp": "2026-05-15T12:00:00"
}
```

Field meanings:

- `player`: The stone colour, either `black` or `white`
- `row`: Board row number, from 1 to 15
- `column`: Board column number, from 1 to 15
- `move_number`: The move sequence number
- `timestamp`: The time when the move was published

## How to Run the System

You need three terminals.

### Terminal 1 – Start Mosquitto Broker

```powershell
cd D:\env\IOT\Mosquitto
.\mosquitto.exe
```

Keep this terminal open.

### Terminal 2 – Start Node-RED

```powershell
node-red
```

Then open Node-RED in a browser:

```text
http://localhost:1880
```

Open the dashboard page:

```text
http://localhost:1880/ui
```

### Terminal 3 – Run Python Publisher

Activate the virtual environment first:

```powershell
cd D:\uni\cits5506\project
.\.venv\Scripts\activate
```

Then run:

```powershell
python src\mqtt.py
```

## Importing the Node-RED Flow

If running this project on a new computer or Raspberry Pi:

1. Start Node-RED.
2. Open `http://localhost:1880`.
3. Click the menu in the top-right corner.
4. Choose **Import**.
5. Import the exported Node-RED JSON flow file:

```text
node_red/gomoku_dashboard_flow.json
```

6. Click **Deploy**.

## Dashboard Components

The Node-RED dashboard includes:

- Gomoku Board
- Game Status
  - Current player
  - Move number
  - Current position
  - Winner status
  - Reset Game button
- Move History
  - Full move sequence

## Reset Game

The Reset Game button clears:

- Board state
- Move history
- Current player
- Move number
- Current position
- Winner status

This allows the demonstration to restart without restarting all services.

## Winner Detection

Winner detection checks whether either player has five connected stones in any of the following directions:

- Horizontal
- Vertical
- Diagonal from top-left to bottom-right
- Diagonal from top-right to bottom-left

When a winner is detected, the dashboard displays the winning player.

## Notes for Raspberry Pi Deployment

When moving from Windows to Raspberry Pi:

- Install Mosquitto on Raspberry Pi.
- Install Node.js and Node-RED.
- Install the Python dependency from `requirements.txt`.
- Import the Node-RED flow JSON file.
- Update MQTT broker address if the broker is not running locally.

If the Python publisher and Mosquitto are on the same Raspberry Pi, keep:

```python
broker = "localhost"
```

If Mosquitto is on another device, replace `localhost` with the broker device IP address.

## Demo Workflow

Recommended demonstration order:

1. Start Mosquitto broker.
2. Start Node-RED.
3. Open the dashboard.
4. Click Reset Game.
5. Run `mqtt.py`.
6. Show:
   - Real-time stone placement
   - Move history update
   - Player and move number update
   - Winner detection

## Author Responsibility

This module covers the IoT dashboard and communication layer, including:

- MQTT broker configuration
- Python publisher script
- Node-RED dashboard design
- Move history log
- Player status display
- Visual board display
- Reset function
- Winner detection
