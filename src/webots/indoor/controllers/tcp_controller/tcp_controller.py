"""ARIA TCP Controller - Webots R2025a"""

import sys

# Step 1: test Python works at all inside Webots
print("STEP 1: Python is running inside Webots")
sys.stdout.flush()

try:
    from controller import Robot
    print("STEP 2: controller module imported OK")
    sys.stdout.flush()
except Exception as e:
    print(f"STEP 2 FAILED: {e}")
    sys.stdout.flush()
    sys.exit(1)

try:
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())
    print(f"STEP 3: Robot() OK, timestep={timestep}ms")
    sys.stdout.flush()
except Exception as e:
    print(f"STEP 3 FAILED: {e}")
    sys.stdout.flush()
    sys.exit(1)

try:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 19997))
    s.listen(1)
    s.settimeout(0.1)
    print("STEP 4: TCP socket bound on 0.0.0.0:19997 OK")
    sys.stdout.flush()
except Exception as e:
    print(f"STEP 4 FAILED (TCP): {e}")
    sys.stdout.flush()
    s = None

print("STEP 5: entering simulation loop")
sys.stdout.flush()

client = None
step = 0
while robot.step(timestep) != -1:
    step += 1
    if step % 200 == 0:
        print(f"STEP 5: still running at simulation step {step}")
        sys.stdout.flush()
