from fastapi.testclient import TestClient

from devflow.api import create_app
from devflow.runtime import DevFlowRuntime


def test_api_end_to_end(runtime: DevFlowRuntime) -> None:
    client = TestClient(create_app(runtime))
    response = client.post(
        "/api/tasks",
        json={
            "request": "分析最近一个月支付服务异常，生成复盘报告并创建整改 Issue",
            "service": "payment",
            "days": 30,
        },
    )
    assert response.status_code == 201
    waiting = response.json()
    assert waiting["status"] == "waiting_approval"

    approval = client.post(
        f"/api/tasks/{waiting['task_id']}/approval",
        json={"decision": "approve", "reason": "同意创建模拟整改任务"},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "completed"

    events = runtime.store.list_events(waiting["task_id"])
    event_types = {event["event_type"] for event in events}
    assert "approval_requested" in event_types
    assert "approval_approved" in event_types
    assert "task_finished" in event_types

    evaluation = client.get(f"/api/tasks/{waiting['task_id']}/evaluation")
    assert evaluation.status_code == 200
    assert evaluation.json()["grade"] == "A+"
    assert evaluation.json()["passed"] is True

    audit = client.get(f"/api/tasks/{waiting['task_id']}/audit")
    assert audit.status_code == 200
    assert len(audit.json()) >= 10
    assert audit.json()[0]["event_type"] == "task_created"


def test_tenant_isolation(runtime: DevFlowRuntime) -> None:
    client = TestClient(create_app(runtime))
    created = client.post(
        "/api/tasks",
        json={
            "request": "分析 payment 服务异常",
            "service": "payment",
            "tenant_id": "tenant-a",
        },
    ).json()
    hidden = client.get(
        f"/api/tasks/{created['task_id']}",
        headers={"x-tenant-id": "tenant-b"},
    )
    assert hidden.status_code == 404

    hidden_evaluation = client.get(
        f"/api/tasks/{created['task_id']}/evaluation",
        headers={"x-tenant-id": "tenant-b"},
    )
    hidden_audit = client.get(
        f"/api/tasks/{created['task_id']}/audit",
        headers={"x-tenant-id": "tenant-b"},
    )
    assert hidden_evaluation.status_code == 404
    assert hidden_audit.status_code == 404


def test_health_and_metrics(runtime: DevFlowRuntime) -> None:
    client = TestClient(create_app(runtime))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["skills"] == 7
    assert health.json()["llm"]["mode"] == "deterministic"
    assert health.json()["tools"]["mode"] == "mcp"
    assert len(health.json()["tools"]["servers"]) == 4

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "devflow_http_requests_total" in metrics.text
    assert "devflow_llm_calls_total" in metrics.text
    assert "devflow_mcp_calls_total" in metrics.text


def test_localhost_cors_preflight(runtime: DevFlowRuntime) -> None:
    client = TestClient(create_app(runtime))
    response = client.options(
        "/api/tasks",
        headers={
            "origin": "http://127.0.0.1:3000",
            "access-control-request-method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
