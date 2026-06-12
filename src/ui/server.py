"""Browser dashboard for ARIA robot control."""

from __future__ import annotations

import asyncio
import atexit
import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, Set

import cv2
from aiohttp import web

from src.agent.aria_agent import run_aria_agent, set_stop_signal
from src.common.config import OLLAMA_MODEL, PERCEPTION_MODE
from src.common.log_retention import update_log_whitelist
from src.mcp_server.server import call_tool
from src.perception.camera import get_camera_manager
from src.perception.camera import prepare_vision_frame
from src.perception.object_detector import get_detector
from src.agent.environment_graph import get_environment_graph

ROOT = Path(__file__).parent
STATIC = ROOT / "static"


class Dashboard:
    """Small aiohttp dashboard with live robot events."""

    def __init__(self) -> None:
        self.websockets: Set[web.WebSocketResponse] = set()
        self.current_task: asyncio.Task | None = None
        self.current_perception_mode: str = PERCEPTION_MODE
        self.latest_camera_event: Dict[str, Any] | None = None

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
        if isinstance(event, dict) and event.get("type") == "camera":
            self.latest_camera_event = dict(event)
        asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)


dashboard = Dashboard()


def _camera_event_is_fresh(event: Dict[str, Any] | None, *, now: float, max_age: float = 2.0) -> bool:
    """True when an agent-emitted camera event is recent enough to reuse."""
    if not isinstance(event, dict):
        return False
    try:
        captured_at = float(event.get("captured_at"))
    except (TypeError, ValueError):
        return False
    return (now - captured_at) <= max_age


def _policy_to_perception_mode(policy: str) -> str:
    policy = (policy or "").strip().lower()
    if policy in ("smart_vision", "vision"):
        return "vlm_only"
    if policy in ("reactive",):
        return "sensor_only"
    if policy in ("yolo_vlm",):
        return "yolo_vlm"
    if policy in ("aria", "ollama", ""):
        return "vlm_first"
    return PERCEPTION_MODE


def _normalize_model_name(model: str) -> str:
    model = (model or "").strip()
    if not model:
        return OLLAMA_MODEL
    return model.split("(")[0].strip()


def _resolve_instruction(body: Dict[str, Any]) -> str:
    instruction = str(body.get("instruction") or body.get("goal") or "").strip()
    if instruction:
        return instruction
    return "find the soccer ball"


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
    goal = _resolve_instruction(body)
    steps = int(body.get("steps", 50))
    policy = (body.get("policy") or "yolo_vlm").strip()
    model = _normalize_model_name(body.get("model", OLLAMA_MODEL))
    perception_mode = _policy_to_perception_mode(policy)
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
            model,
            perception_mode,
            lambda event: dashboard.emit_threadsafe(loop, event),
        )

    dashboard.current_task = asyncio.create_task(runner())
    dashboard.current_perception_mode = perception_mode
    await dashboard.broadcast({
        "type": "goal",
        "goal": goal,
        "instruction": goal,
        "plan": goal,
        "policy": policy,
        "perception_mode": perception_mode,
        "model": model,
        "step": 0,
    })
    return web.json_response({"ok": True, "goal": goal, "instruction": goal, "policy": policy, "perception_mode": perception_mode, "model": model})


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
    detector = None
    detector_mode = None
    detector_classes_ready = False
    last_agent_camera_step = -1
    
    try:
        while not ws.closed:
            agent_camera_event = dashboard.latest_camera_event
            if (
                dashboard.current_task
                and not dashboard.current_task.done()
                and _camera_event_is_fresh(agent_camera_event, now=time.time())
            ):
                step = int(agent_camera_event.get("step", -1))
                if step != last_agent_camera_step:
                    last_agent_camera_step = step
                    try:
                        await ws.send_str(json.dumps(agent_camera_event, default=str))
                    except Exception:
                        break
                await asyncio.sleep(0.05)
                continue

            mode = dashboard.current_perception_mode
            if mode != detector_mode:
                detector_mode = mode
                detector = None
                detector_classes_ready = False

            if mode == "yolo_vlm" and detector is None:
                detector = get_detector()
                if getattr(detector, "is_open_vocab", False) and not detector_classes_ready:
                    try:
                        detector.set_classes(detector.get_common_classes())
                    except Exception as e:
                        print(f"[UI] Detector class setup error: {e}")
                    detector_classes_ready = True

            # Get a fresh frame from Webots
            frame = await asyncio.to_thread(camera.get_frame, True)
            if frame is None:
                await asyncio.sleep(0.1)
                continue

            frame = prepare_vision_frame(frame)

            detection_data = []
            detections = []
            if detector is not None:
                # Only draw boxes in the explicit YOLO mode.
                try:
                    detections = detector.detect(frame)
                    detection_data = [
                        {
                            "class_name": d.class_name,
                            "confidence": float(d.confidence),
                            "bbox": d.bbox,
                            "center": d.center,
                        }
                        for d in detections[:5]
                    ]
                except Exception as e:
                    detections = []
                    detection_data = []
                    print(f"[UI] Detection error: {e}")

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
    # When the server stops (Ctrl-C or normal exit), trim the .gitignore log
    # whitelist to only the latest few run logs so old logs never pile into git.
    atexit.register(update_log_whitelist)
    # Bind on all interfaces so Windows browsers can reach the UI from WSL2.
    try:
        web.run_app(make_app(), host="0.0.0.0", port=8080)
    finally:
        # Also run it directly here in case atexit is bypassed; the helper is
        # idempotent so running twice is harmless.
        update_log_whitelist()


if __name__ == "__main__":
    main()
