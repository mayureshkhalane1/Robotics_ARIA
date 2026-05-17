"""Browser dashboard for ARIA robot control."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Set

from aiohttp import web

from src.agent.graph import run_reactive_agent
from src.mcp_server.server import call_tool

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
    policy = body.get("policy", "ollama")
    model = body.get("model") or None
    loop = asyncio.get_running_loop()

    if dashboard.current_task and not dashboard.current_task.done():
        dashboard.current_task.cancel()
        call_tool("stop", {})

    async def runner() -> None:
        await asyncio.to_thread(
            run_reactive_agent,
            goal,
            steps,
            800.0,
            0.1,
            None,
            None,
            policy,
            model,
            lambda event: dashboard.emit_threadsafe(loop, event),
        )

    dashboard.current_task = asyncio.create_task(runner())
    await dashboard.broadcast({"type": "goal", "plan": goal, "policy": policy, "step": 0})
    return web.json_response({"ok": True, "goal": goal, "policy": policy})


async def stop(_request: web.Request) -> web.Response:
    if dashboard.current_task and not dashboard.current_task.done():
        dashboard.current_task.cancel()
    result = call_tool("stop", {})
    await dashboard.broadcast({"type": "stop", "plan": "stop requested", "result": result, "step": 0})
    return web.json_response(result)


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_post("/goal", set_goal)
    app.router.add_post("/stop", stop)
    app.router.add_static("/static", STATIC)
    return app


def main() -> None:
    web.run_app(make_app(), host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
