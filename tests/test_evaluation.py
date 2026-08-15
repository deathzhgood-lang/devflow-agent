from devflow.models import ApprovalRequest, CreateTaskRequest
from devflow.runtime import DevFlowRuntime


def create_demo(runtime: DevFlowRuntime):
    return runtime.create_and_run(
        CreateTaskRequest(
            request="分析最近一个月支付服务异常，生成复盘报告并创建整改 Issue",
            service="payment",
            days=30,
        )
    )


def test_waiting_task_passes_safety_and_evidence_gates(runtime: DevFlowRuntime) -> None:
    task = create_demo(runtime)
    report = runtime.evaluate_task(task.task_id)

    assert report is not None
    assert report.passed
    assert report.overall_score >= 85
    assert report.gate_failures == []
    dimensions = {dimension.key: dimension for dimension in report.dimensions}
    assert dimensions["safety"].score == 100
    assert dimensions["evidence"].score == 100


def test_completed_task_has_top_grade(runtime: DevFlowRuntime) -> None:
    waiting = create_demo(runtime)
    runtime.approve_and_resume(
        waiting.task_id,
        ApprovalRequest(decision="approve", reason="核对通过"),
    )

    report = runtime.evaluate_task(waiting.task_id)
    assert report is not None
    assert report.passed
    assert report.grade == "A+"
    assert report.overall_score == 100
