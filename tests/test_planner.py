import pytest

from devflow.models import IntentResult, RiskLevel, TaskPlan
from devflow.planner import DeterministicPlanner


def test_detects_payment_month_request() -> None:
    planner = DeterministicPlanner()
    intent = planner.detect_intent("分析最近一个月支付服务异常并生成复盘", {})
    assert intent.service == "payment"
    assert intent.days == 30
    assert intent.clarification_questions == []


def test_missing_service_requests_clarification() -> None:
    planner = DeterministicPlanner()
    intent = planner.detect_intent("分析最近一个月异常", {})
    assert intent.service is None
    assert intent.clarification_questions


def test_plan_has_approval_for_high_write() -> None:
    planner = DeterministicPlanner()
    plan = planner.create_plan(IntentResult(service="payment", days=30, confidence=1.0))
    assert len(plan.steps) == 7
    issue_step = plan.steps[-1]
    assert issue_step.risk_level == RiskLevel.HIGH_WRITE
    assert issue_step.requires_approval is True


def test_plan_validator_rejects_forward_dependency() -> None:
    with pytest.raises(ValueError):
        TaskPlan.model_validate(
            {
                "status": "ready",
                "goal": "invalid",
                "steps": [
                    {
                        "step_id": "S1",
                        "title": "bad",
                        "skill_id": "x",
                        "tool_name": "x",
                        "depends_on": ["S2"],
                        "success_criteria": ["x"],
                        "risk_level": "read",
                    }
                ],
                "completion_criteria": ["x"],
            }
        )

