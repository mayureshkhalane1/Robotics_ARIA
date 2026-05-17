# ARIA Next Phase: House + Camera + Local Qwen UI

## Start Ollama

```bash
cd /Users/mayureshkhalane/Documents/ARIA
./scripts/start_ollama.sh
```

Default model is `qwen3:8b`. Override with:

```bash
OLLAMA_MODEL=qwen3:14b ./scripts/start_ollama.sh
```

## Start Webots house world

```bash
cd /Users/mayureshkhalane/Documents/ARIA
./scripts/run_webots.sh
```

To use the older arena world:

```bash
WEBOTS_WORLD=/Users/mayureshkhalane/Documents/ARIA/src/webots/worlds/arena.wbt ./scripts/run_webots.sh
```

## Run the browser UI

```bash
uv run python -m src.ui.server
```

Open:

```text
http://127.0.0.1:8080
```

The UI shows:
- robot camera feed when Webots camera is active
- robot state
- live thinking/action events
- goal input for natural-language commands

## Run from CLI with local Qwen

```bash
uv run python -m src.agent.main --policy ollama --model qwen3:8b --goal "explore the house safely and avoid obstacles" --steps 50
```

## Current architecture

```text
Browser UI -> aiohttp server -> evented agent loop -> Ollama Qwen planner -> MCP-style Webots bridge -> Webots TCP controller -> Pioneer 3-DX
```
