Coordinate Text to G-code Converter

A lightweight Python GUI tool for converting structured coordinate text data into G-code, designed for pen plotters or custom CNC writing systems with Z-axis pen control.

Overview

This tool converts grouped coordinate data of the form:

{group_id}
index. {x, y, z}

into executable G-code.

Each group represents a continuous stroke (curve), and each point includes:

X, Y → spatial position
Z → pen height / pressure (e.g. 0 = pen up, 10 = pen down)
Features
Convert structured coordinate text into G-code
Simple GUI (input / output panels)
Adjustable writing parameters:
Writing speed (default: 1500 mm/min)
Rapid move speed
Z-axis movement speed
Z-axis continuous control (supports pressure variation)
Automatic coordinate normalization:
Detects X/Y bounds
Optionally shifts all coordinates so minimum becomes (0,0)
Prevents out-of-bound movement
Scaling and offset controls for X, Y, Z
Skip duplicate points (optional)
Export G-code to file
Copy G-code to clipboard
Input Format

The program expects text in the following format:

{0;0}
0. {295.555556, 0, 9.882353}
1. {295.555556, 1.744186, 10}
2. {295.555556, 3.488372, 4.627451}

{0;1}
0. {301.111111, 0, 9.921569}
1. {301.111111, 1.744186, 9.803922}
Rules
{a;b} defines a new curve
Each numbered line is a point: {x, y, z}
Z value is interpreted as pen height or pressure
Output Behavior

For each curve:

Lift pen (Z = pen_up)
Rapid move to start point (G0)
Lower pen to first Z value (G1 Z...)
Draw using G1 commands
Lift pen after finishing

Example output:

G21
G90
F1500
G0 Z0

; --- curve {0;0} ---
G0 X5.556 Y0 F2500
G1 Z9.882 F8000
G1 X5.556 Y1.744 Z10 F1500
Coordinate System Handling

To prevent machine limit errors:

The tool analyzes X/Y bounds automatically

If enabled, it shifts all coordinates so:

X_min → 0
Y_min → 0
This avoids negative coordinates that may trigger limit switches

Additional manual offsets can be applied afterward.

Feedrate (Important)
All feedrates (F) are output in mm/min
No internal scaling is applied
The value entered in the GUI is used directly

Example:

1500 → F1500
2500 → F2500
Requirements
Python 3.x
Standard library only (tkinter)

No external dependencies required.

How to Run
python your_script_name.py
GUI Description
Input Panel

Paste your coordinate text here.

Output Panel

Generated G-code appears here.

Controls
XY Scale / Offset
Z Scale / Offset
Pen Up Height (Z)
Feedrates:
Rapid XY
Writing speed
Z movement speed
Toggle options:
Emit Z at every point
Skip duplicate points
Auto shift to origin
Return to (0,0) after completion
Buttons
Convert → Generate G-code
Export → Save to file
Copy → Copy output
Clear → Reset fields
Use Case

This tool is ideal for:

CNC pen plotters
Custom writing robots
Calligraphy machines
Experimental drawing systems
Z-based pressure simulation
Notes
Z-axis must be configured correctly in your machine
Ensure proper homing before execution
Adjust feedrates according to your hardware limits
If your machine uses mm/s instead of mm/min, conversion must be handled externally
License

Free to use and modify.# 数笔成画