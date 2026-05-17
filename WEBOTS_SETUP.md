# Webots Setup Guide for ARIA

This guide walks you through setting up the Webots simulation for the ARIA project.

## Prerequisites

- Webots R2024a+ installed
- This repository cloned to `/Users/mayureshkhalane/Documents/ARIA`
- TCP port 19997 available (for robot controller)

## Step 1: Create or Import a Webots World

### Option A: Create a New World (Recommended)

1. **Open Webots**
2. **File → New World**
3. **Choose a template** (empty world is fine)
4. **Save as** `src/webots/worlds/arena.wbt`

### Option B: Use an Existing World

If you have a pre-made world:
1. Copy it to `src/webots/worlds/arena.wbt`
2. Continue to Step 2

## Step 2: Add a Mobile Robot

### Recommended: Pioneer 3-DX

1. **Click the "Add new object" button** (in the bottom-left panel)
2. **Search for "Pioneer3dx"** in the PROTO database
3. **Click to add it** to the world
4. **Verify it spawns** in the center

Alternatively, you can:
- Use TurtleBot
- Use DJI M100
- Or any wheeled mobile robot in the library

## Step 3: Configure Robot Motors

The robot needs **two wheel motors** named exactly:
- `left wheel motor`
- `right wheel motor`

**If using Pioneer 3-DX:**
- These motors are **already configured** ✓

**If using a different robot:**
1. Right-click the robot → **Edit**
2. Find the motor nodes
3. Rename them to match the names above
   - Or update `tcp_controller.py` to match your robot's motor names

## Step 4: Add Sensors

Your robot needs these sensors (minimum):

### Distance Sensors (×8)

1. **Add → Webots objects → Sensor Nodes → DistanceSensor**
2. **Set name:** `distance sensor 0`
3. **Position:** Front of robot
4. **Repeat 7 more times** with names `distance sensor 1`–`distance sensor 7`

**Recommended positions:**
- `distance sensor 0–2`: Front (left, center, right)
- `distance sensor 3–4`: Sides (left, right)
- `distance sensor 5–7`: Back + diagonals

### GPS

1. **Add → Webots objects → Sensor Nodes → GPS**
2. **Set name:** `gps`
3. **Parent it to the robot** (drag into robot node)

### Compass

1. **Add → Webots objects → Sensor Nodes → Compass**
2. **Set name:** `compass`
3. **Parent it to the robot**

### Camera (Optional)

For future object detection:
1. **Add → Webots objects → Sensor Nodes → Camera**
2. **Set name:** `camera`
3. **Parent it to the robot**

## Step 5: Add World Objects

### Navigation Target

1. **Add → Webots objects → Basic Shapes → Sphere**
2. **Scale:** 0.1m radius
3. **Color:** Green
4. **Position:** Anywhere in the world (e.g., 5, 0, 0)
5. **Name it:** `target` (optional, for reference)

### Obstacles (Boxes/Walls)

1. **Add → Webots objects → Basic Shapes → Box**
2. **Dimensions:** 0.5m × 0.5m × 1m (for walls)
3. **Positions:** Scattered in the world
4. **Make them static:** Set `Physics → Solid → Density to 0`

**Example obstacle layout:**
```
[Target]
      
   [Robot]  [Box]
   
      [Wall]
```

## Step 6: Create the Robot Controller

This is where we place our TCP server code.

1. **In Webots, right-click the robot → Add → Controller**
2. **A new controller window opens**
3. **Copy entire contents of** `src/webots/controllers/tcp_controller.py`
4. **Paste into the controller file**
5. **Save the controller**

Webots will now use this controller when the robot runs.

## Step 7: Verify Sensor/Motor Names

**Critical:** The controller code expects specific device names.

In `tcp_controller.py` (line ~70–80), check these names match your robot:

```python
left_motor = self.robot.getDevice("left wheel motor")
right_motor = self.robot.getDevice("right wheel motor")

for i in range(8):
    sensor = self.robot.getDevice(f"distance sensor {i}")
    
gps = self.robot.getDevice("gps")
compass = self.robot.getDevice("compass")
camera = self.robot.getDevice("camera")  # optional
```

**If your robot has different names:**
- Find the actual device names in Webots (expand robot node in tree)
- Update the names in `tcp_controller.py` to match

## Step 8: Test the Connection

### Start the Simulation

1. **In Webots: Play button (▶) to start simulation**
2. **You should see in the console:**
   ```
   [Webots] Robot server initialized on port 19997
   ```

### Test TCP Connection

In a terminal:

```bash
python3 << 'EOF'
import socket
import json

s = socket.socket()
s.connect(("localhost", 19997))
s.sendall(b'{"cmd": "get_state"}\n')
response = json.loads(s.recv(1024).decode())
print("Success! Robot state:")
print(f"  Position: {response.get('position')}")
print(f"  Sensors: {len(response.get('proximity', {}))} distance sensors")
s.close()
EOF
```

You should see robot position and sensor readings.

## Step 9: Run Full Test Suite

Once TCP connection works:

```bash
python -m pytest tests/test_webots_connection.py -v
```

All tests should pass ✓

## Troubleshooting

### Port 19997 Already in Use

```bash
# Kill the process using that port
lsof -i :19997
kill -9 <PID>
```

Or change `WEBOTS_PORT` in `.env`:
```
WEBOTS_PORT=19998
```

### Connection Refused

- Is Webots running? ✓ Play button pressed?
- Is the controller actually executing? Check console output
- Is the robot name correct? Check device names in tree

### Sensor Not Found

```python
# If you see: "Could not find device: distance sensor 0"
# Then either:
# 1. The sensor doesn't exist in Webots
# 2. The name in code doesn't match Webots
# 3. The sensor wasn't parented to the robot
```

**Fix:** Find the actual device name in Webots robot tree, update code.

### Robot Doesn't Move

Check:
- Are the motors named correctly? (`left wheel motor`, `right wheel motor`)
- Are they wheel joints (Hinge or HingeZ)?
- Is physics enabled on the robot?

### World Setup Checklist

- [ ] Robot added to world (Pioneer 3-DX or similar)
- [ ] Two motors: `left wheel motor`, `right wheel motor`
- [ ] 8× Distance sensors: `distance sensor 0`–`7`
- [ ] GPS sensor: `gps`
- [ ] Compass sensor: `compass`
- [ ] Target sphere added (green, optional)
- [ ] Obstacles added (boxes/walls, optional)
- [ ] Controller file created with `tcp_controller.py` content
- [ ] Simulation runs without errors
- [ ] Port 19997 accepts TCP connections

## Next Steps

Once Webots is set up and TCP connection works:

1. **Test with MCP server:**
   ```bash
   python src/mcp_server/server.py
   ```

2. **Run full test suite:**
   ```bash
   python -m pytest tests/ -v
   ```

3. **Proceed to Phase 3** (MCP server integration)

## References

- Webots Documentation: https://cyberbotics.com/doc/guide/index.html
- Pioneer 3-DX Robot: https://en.wikipedia.org/wiki/Pioneer_(robot)
- TCP Socket Programming: https://docs.python.org/3/howto/sockets.html

## Questions?

Check the main `README.md` for more details on the ARIA architecture.
