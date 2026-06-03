"""Browser dashboard for ARIA robot control."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path
from typing import Any, Dict, Set

import cv2
from aiohttp import web

from src.agent.aria_agent import run_aria_agent, set_stop_signal
from src.common.config import OLLAMA_MODEL
from src.mcp_server.server import call_tool
from src.perception.camera import get_camera_manager
from src.perception.object_detector import get_detector
from src.agent.environment_graph import get_environment_graph

ROOT = Path(__file__).parent
STATIC = ROOT / "static"


class Dashboard:
    """Small aiohttp dashboard with live robot events."""

    def __init__(self) -> None:
        self.websockets: Set[web.WebSocketResponse] = set()
        self.current_task: asyncio.Task | None = None

    async def broadcast(self, event: Dict[str, Any]) -> None:
        if not self.websockets:
            return
        payload = json.dumps(event, default=str)
        stale = []
        for ws in self.websockets:
            try:
                await ws.send_str(payload)
            except ConnectionError:
                stale.append(ws)
        for ws in stale:
            self.websockets.discard(ws)

    def emit_threadsafe(self, loop: asyncio.AbstractEventLoop, event: Dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)


dashboard = Dashboard()


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    dashboard.websockets.add(ws)
    await ws.send_str(json.dumps({"type": "ui", "plan": "dashboard connected"}))
    async for _ in ws:
        pass
    dashboard.websockets.discard(ws)
    return ws


async def set_goal(request: web.Request) -> web.Response:
    body = await request.json()
    goal = body.get("goal", "explore safely")
    steps = int(body.get("steps", 50))
    policy = body.get("policy", "aria")
    # Always use the configured local VLM; UI is read-only.
    model = OLLAMA_MODEL
    loop = asyncio.get_running_loop()
    
    # Reset stop signal for new task
    set_stop_signal(False)

    if dashboard.current_task and not dashboard.current_task.done():
        dashboard.current_task.cancel()
        call_tool("stop", {})

    async def runner() -> None:
        # The ARIA grid + spatial-memory agent is the only supported policy.
        await asyncio.to_thread(
            run_aria_agent,
            goal,
            steps,
            model or OLLAMA_MODEL,
            lambda event: dashboard.emit_threadsafe(loop, event),
        )

    dashboard.current_task = asyncio.create_task(runner())
    await dashboard.broadcast({"type": "goal", "plan": goal, "policy": policy, "step": 0})
    return web.json_response({"ok": True, "goal": goal, "policy": policy})


async def stop(_request: web.Request) -> web.Response:
    """Stop the current agent task."""
    set_stop_signal(True)
    if dashboard.current_task and not dashboard.current_task.done():
        dashboard.current_task.cancel()
    result = call_tool("stop", {})
    await dashboard.broadcast({"type": "stop", "plan": "stop requested", "result": result, "step": 0})
    return web.json_response(result)


async def camera_stream(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for real-time camera streaming."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    camera = get_camera_manager()
    detector = get_detector()
    
    try:
        while not ws.closed:
            # Get a fresh frame from Webots
            frame = await asyncio.to_thread(camera.get_frame, True)
            if frame is None:
                await asyncio.sleep(0.1)
                continue

            # Run detection (detector expects BGR format directly)
            try:
                detections = detector.detect(frame)

                detection_data = [
                    {
                        "class_name": d.class_name,
                        "confidence": float(d.confidence),
                        "bbox": d.bbox,
                        "center": d.center,
                    }
                    for d in detections[:5]  # Top 5 detections
                ]
            except Exception as e:
                detections = []
                detection_data = []
                print(f"[UI] Detection error: {e}")

            # Annotate frame with detections before encoding
            if detections:
                frame = detector.visualize_detections(frame, detections)

            # Encode annotated frame as JPEG
            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpeg_b64 = base64.b64encode(encoded.tobytes()).decode("utf-8") if success else None
            if not jpeg_b64:
                await asyncio.sleep(0.1)
                continue

            # Environment-graph stats for the dashboard
            graph = get_environment_graph()

            # Send frame with metadata
            msg = {
                "type": "camera",
                "data": jpeg_b64,
                "width": frame.shape[1],
                "height": frame.shape[0],
                "detections": detection_data,
                "graph_stats": graph.get_stats(),
            }
            
            try:
                await ws.send_str(json.dumps(msg, default=str))
            except Exception:
                break
            
            # Target ~15 FPS
            await asyncio.sleep(0.067)
    
    except Exception as e:
        print(f"[UI] Camera stream error: {e}")
    
    return ws


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/camera", camera_stream)
    app.router.add_post("/goal", set_goal)
    app.router.add_post("/stop", stop)
    app.router.add_static("/static", STATIC)
    return app


def main() -> None:
    # Bind on all interfaces so Windows browsers can reach the UI from WSL2.
    web.run_app(make_app(), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
