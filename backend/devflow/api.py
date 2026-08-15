from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from time import perf_counter

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from devflow.config import settings
from devflow.evaluation import EvaluationReport
from devflow.models import ApprovalRequest, CreateTaskRequest, TaskView
from devflow.observability import HTTP_REQUESTS, REGISTRY
from devflow.runtime import DevFlowRuntime


def create_app(runtime: DevFlowRuntime | None = None) -> FastAPI:
    agent_runtime = runtime or DevFlowRuntime()
    app = FastAPI(
        title="DevFlow Agent API",
        version="0.1.0",
        description="Controllable incident investigation agent MVP",
    )
    app.state.runtime = agent_runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(agent_runtime.settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def record_http_metrics(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(
            method=request.method,
            route=route_path,
            status=str(response.status_code),
        ).inc()
        response.headers["server-timing"] = f"app;dur={(perf_counter() - started) * 1000:.2f}"
        return response

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "skills": len(agent_runtime.skills.list_metadata()),
            "llm": agent_runtime.llm_status(),
            "tools": agent_runtime.tool_status(),
        }

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/skills")
    def list_skills() -> list[dict[str, object]]:
        return agent_runtime.skills.list_metadata()

    @app.post("/api/tasks", response_model=TaskView, status_code=201)
    def create_task(request: CreateTaskRequest) -> TaskView:
        return agent_runtime.create_and_run(request)

    @app.get("/api/tasks", response_model=list[TaskView])
    def list_tasks(x_tenant_id: str = Header(default="demo-tenant")) -> list[TaskView]:
        return agent_runtime.list_tasks(x_tenant_id)

    @app.get("/api/tasks/{task_id}", response_model=TaskView)
    def get_task(task_id: str, x_tenant_id: str = Header(default="demo-tenant")) -> TaskView:
        task = agent_runtime.get_task(task_id, x_tenant_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return task

    @app.get("/api/tasks/{task_id}/evaluation", response_model=EvaluationReport)
    def evaluate_task(
        task_id: str,
        x_tenant_id: str = Header(default="demo-tenant"),
    ) -> EvaluationReport:
        report = agent_runtime.evaluate_task(task_id, x_tenant_id)
        if not report:
            raise HTTPException(status_code=404, detail="task not found")
        return report

    @app.get("/api/tasks/{task_id}/audit")
    def get_audit_events(
        task_id: str,
        x_tenant_id: str = Header(default="demo-tenant"),
    ) -> list[dict[str, object]]:
        if not agent_runtime.get_task(task_id, x_tenant_id):
            raise HTTPException(status_code=404, detail="task not found")
        return agent_runtime.store.list_events(task_id)

    @app.post("/api/tasks/{task_id}/approval", response_model=TaskView)
    def decide_approval(
        task_id: str,
        request: ApprovalRequest,
        x_tenant_id: str = Header(default="demo-tenant"),
        x_user_id: str = Header(default="demo-user"),
    ) -> TaskView:
        try:
            return agent_runtime.approve_and_resume(
                task_id,
                request,
                tenant_id=x_tenant_id,
                decided_by=x_user_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/resume", response_model=TaskView)
    def resume_task(
        task_id: str,
        x_tenant_id: str = Header(default="demo-tenant"),
    ) -> TaskView:
        try:
            return agent_runtime.resume_task(task_id, x_tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="task not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/events")
    async def stream_events(
        task_id: str,
        after_id: int = Query(default=0, ge=0),
        x_tenant_id: str = Header(default="demo-tenant"),
    ) -> StreamingResponse:
        if not agent_runtime.get_task(task_id, x_tenant_id):
            raise HTTPException(status_code=404, detail="task not found")

        async def generate() -> AsyncIterator[str]:
            cursor = after_id
            idle_rounds = 0
            while idle_rounds < 30:
                events = agent_runtime.store.list_events(task_id, cursor)
                if events:
                    idle_rounds = 0
                    for event in events:
                        cursor = event["event_id"]
                        yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    idle_rounds += 1
                    yield ": keep-alive\n\n"
                task = agent_runtime.get_task(task_id, x_tenant_id)
                if task and task.status.value in {"completed", "failed", "rejected", "needs_clarification"}:
                    break
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


app = create_app()
