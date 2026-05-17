# Running the ARIA Webots Demo

This repo includes a ready-to-open Webots world copied from the official Webots Pioneer 3-DX sample and wired to ARIA's TCP controller.

## Files

- World: `src/webots/worlds/arena.wbt`
- Webots controller: `src/webots/controllers/tcp_controller/tcp_controller.py`
- Agent: `src/agent/main.py`

## Start Webots

From the repo root:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
/Applications/Webots.app/Contents/MacOS/webots --stdout --stderr src/webots/worlds/arena.wbt
```

If that path does not work, open Webots normally and open:

```text
/Users/mayureshkhalane/Documents/ARIA/src/webots/worlds/arena.wbt
```

Then press the Play button.

## Expected Webots console output

```text
[Webots] Left motor: left wheel
[Webots] Right motor: right wheel
[Webots] Motors initialized
[Webots] Sensors initialized: 16 proximity, GPS=yes, Compass=yes
[Webots] Robot server initialized on port 19997
```

The important line is `Robot server initialized on port 19997`.

## Test the TCP connection

In a second terminal:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv run python - <<'PY'
import socket, json
s = socket.socket()
s.settimeout(3)
s.connect(("localhost", 19997))
s.sendall(b'{"cmd":"get_state"}\n')
print(json.dumps(json.loads(s.recv(4096).decode()), indent=2))
s.close()
PY
```

## Run integration tests

```bash
uv run --group dev pytest tests/test_webots_connection.py -v
```

## Run the agent

```bash
uv run python -m src.agent.main --goal "avoid obstacles and explore" --steps 50
```

## If connection is refused

- Make sure Webots is open with `src/webots/worlds/arena.wbt`.
- Press Play, not just open the world.
- Check the robot controller field in the world is `tcp_controller`.
- Check this folder exists: `src/webots/controllers/tcp_controller/tcp_controller.py`.
- Check port use: `lsof -i :19997`.
