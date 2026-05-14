# Hardware Wiring Notes

## Current Hardware Setup

- Raspberry Pi 3 Model B
- Raspberry Pi Camera Module
- Arduino Uno
- Breadboard
- Jumper wires
- LEDs
- Resistors
- Passive buzzer

## Arduino Feedback Module Wiring

### Common Ground
Arduino GND is connected to the negative rail of the breadboard.
All LEDs and buzzer ground connections return to this common breadboard ground rail.

### Black Move LED
- Arduino D8 -> 220Ω resistor -> LED anode
- LED cathode -> GND rail

### White Move LED
- Arduino D9 -> 220Ω resistor -> LED anode
- LED cathode -> GND rail

### Buzzer
- Arduino D6 -> buzzer positive terminal
- buzzer negative terminal -> GND rail

## Serial Command Protocol

The Raspberry Pi sends a single-byte command to the Arduino over USB serial.

| Command | Meaning | Expected Arduino Action |
|---|---|---|
| `B` | Black move detected | Turn on black-side LED feedback and short beep |
| `W` | White move detected | Turn on white-side LED feedback and short beep |
| `E` | Error / invalid state | Flash LEDs and play error beep |
| `R` | Reset feedback | Turn off LEDs and reset feedback state |

## Current Status

- Raspberry Pi to Arduino USB serial communication has been tested successfully.
- Arduino returns acknowledgment messages such as `ACK:B`, `ACK:W`, `ACK:E`, and `ACK:R`.
- Raspberry Pi 3 is the actual board used in the prototype.