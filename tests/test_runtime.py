from devflow.models import ApprovalRequest, CreateTaskRequest, TaskStatus
from devflow.runtime import DevFlowRuntime


def create_demo(runtime: DevFlowRuntime):
    return runtime.create_and_run(
        CreateTaskRequest(
            request="分析最近一个月支付服务异常，生成复盘报告并创建整改 Issue",
            service="payment",
            days=30,
        )
    )


def test_runtime_pauses_before_write(runtime: DevFlowRuntime) -> None:
    task = create_demo(runtime)
    assert task.status == TaskStatus.WAITING_APPROVAL
    assert task.pending_approval is not None
    assert task.pending_approval["tool_name"] == "create_issue"
    assert len(task.evidence) >= 7
    statuses = [step["status"] for step in task.plan["steps"]]
    assert statuses[-1] == "blocked"
    assert all(status == "succeeded" for status in statuses[:-1])
    state = runtime.store.get_state(task.task_id)
    assert state is not None
    assert all(item["result"]["data"]["_mcp"]["server"] for item in state["tool_results"])
    assert runtime.tool_status()["transport"] == "mcp-client"


def test_approval_resumes_and_completes(runtime: DevFlowRuntime) -> None:
    waiting = create_demo(runtime)
    completed = runtime.approve_and_resume(
        waiting.task_id,
        ApprovalRequest(decision="approve", reason="参数与报告已核对"),
    )
    assert completed.status == TaskStatus.COMPLETED
    assert "ISSUE-" in (completed.final_answer or "")
    assert completed.pending_approval is None


def test_rejection_has_no_external_write(runtime: DevFlowRuntime) -> None:
    waiting = create_demo(runtime)
    rejected = runtime.approve_and_resume(
        waiting.task_id,
        ApprovalRequest(decision="reject", reason="先做压测"),
    )
    assert rejected.status == TaskStatus.REJECTED
    assert "未产生外部写操作" in (rejected.final_answer or "")


def test_task_is_durable_in_sqlite(runtime: DevFlowRuntime) -> None:
    waiting = create_demo(runtime)
    loaded = runtime.get_task(waiting.task_id)
    assert loaded is not None
    assert loaded.status == TaskStatus.WAITING_APPROVAL
    assert loaded.plan == waiting.plan


def test_unknown_service_needs_clarification(runtime: DevFlowRuntime) -> None:
    task = runtime.create_and_run(CreateTaskRequest(request="分析最近一个月异常"))
    assert task.status == TaskStatus.NEEDS_CLARIFICATION
    assert "哪个服务" in (task.final_answer or "")
