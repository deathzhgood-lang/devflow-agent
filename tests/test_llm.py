import json
from pathlib import Path
from typing import Any

import httpx

from devflow.config import Settings
from devflow.llm import DeepSeekClient, DeepSeekEvidenceReasoner, LLMJSONResult
from devflow.models import CreateTaskRequest, IntentResult, TaskStatus
from devflow.planner import DeterministicPlanner, HybridPlanner
from devflow.runtime import DevFlowRuntime


def llm_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "db_path": tmp_path / "devflow.db",
        "report_dir": tmp_path / "reports",
        "tool_mode": "local",
        "max_steps": 8,
        "max_replans": 2,
        "cors_origins": ("http://localhost:3000",),
        "llm_enabled": True,
        "deepseek_api_key": "test-secret-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_deepseek_client_uses_json_mode_without_leaking_key(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        headers = {"x-request-id": "req-test"}

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": '{"service":"payment"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            }

    def fake_post(url: str, **kwargs: Any):
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = DeepSeekClient(llm_settings(tmp_path))
    result = client.complete_json(
        messages=[{"role": "user", "content": "return json"}],
        purpose="test",
    )

    assert result.data == {"service": "payment"}
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert "test-secret-key" not in str(result.metadata())


class StubDeepSeekClient:
    model = "deepseek-v4-flash"

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = responses

    def complete_json(self, *, messages: list[dict[str, str]], purpose: str) -> LLMJSONResult:
        return LLMJSONResult(
            data=self.responses.pop(0),
            model=self.model,
            prompt_tokens=10,
            completion_tokens=10,
            duration_ms=5,
            purpose=purpose,
        )


def test_hybrid_planner_uses_valid_deepseek_structured_outputs() -> None:
    intent_data = IntentResult(service="payment", days=30, confidence=0.96).model_dump(mode="json")
    plan_data = DeterministicPlanner().create_plan(
        IntentResult(service="payment", days=30, confidence=0.96)
    ).model_dump(mode="json")
    planner = HybridPlanner(StubDeepSeekClient([intent_data, plan_data]))  # type: ignore[arg-type]

    intent = planner.detect_intent("分析支付服务最近 30 天异常", {})
    plan = planner.create_plan(intent)

    assert intent.service == "payment"
    assert len(plan.steps) == 7
    assert planner.consume_metadata()["mode"] == "remote"


def test_trusted_context_suppresses_redundant_llm_questions() -> None:
    noisy_intent = IntentResult(
        service="payment",
        days=30,
        confidence=0.8,
        clarification_questions=["请补充已经由表单提供的信息"],
    ).model_dump(mode="json")
    planner = HybridPlanner(StubDeepSeekClient([noisy_intent]))  # type: ignore[arg-type]

    intent = planner.detect_intent(
        "分析支付服务最近 30 天异常",
        {"service": "payment", "days": 30},
    )

    assert intent.service == "payment"
    assert intent.days == 30
    assert intent.clarification_questions == []


def test_hybrid_planner_falls_back_on_invalid_plan() -> None:
    planner = HybridPlanner(StubDeepSeekClient([{"unexpected": True}]))  # type: ignore[arg-type]
    intent = IntentResult(service="payment", days=30, confidence=1.0)

    plan = planner.create_plan(intent)

    assert len(plan.steps) == 7
    assert planner.consume_metadata()["mode"] == "deterministic_fallback"


def test_prompt_injected_structured_plan_cannot_add_tool() -> None:
    intent = IntentResult(service="payment", days=30, confidence=1.0)
    plan_data = DeterministicPlanner().create_plan(intent).model_dump(mode="json")
    plan_data["steps"][0]["tool_name"] = "delete_repository"
    planner = HybridPlanner(StubDeepSeekClient([plan_data]))  # type: ignore[arg-type]

    plan = planner.create_plan(intent)

    assert [step.tool_name for step in plan.steps][0] == "query_metrics"
    assert all(step.tool_name != "delete_repository" for step in plan.steps)
    assert planner.consume_metadata()["mode"] == "deterministic_fallback"


def test_hybrid_planner_normalizes_control_fields() -> None:
    intent = IntentResult(service="payment", days=30, confidence=1.0)
    plan_data = DeterministicPlanner().create_plan(intent).model_dump(mode="json")
    plan_data["steps"][1]["depends_on"] = []
    plan_data["steps"][6]["requires_approval"] = False
    plan_data["steps"][6]["risk_level"] = "read"
    planner = HybridPlanner(StubDeepSeekClient([plan_data]))  # type: ignore[arg-type]

    plan = planner.create_plan(intent)

    assert plan.steps[1].depends_on == ["S1"]
    assert plan.steps[6].requires_approval is True
    assert plan.steps[6].risk_level.value == "high_write"
    assert planner.consume_metadata()["policy_normalized"] is True


def test_evidence_reasoner_accepts_only_known_citations() -> None:
    client = StubDeepSeekClient(
        [
            {
                "summary": "提交修改与连接泄漏假设相关 [ev_git]，仍需要压测确认。",
                "confidence": 0.82,
                "supporting_evidence_ids": ["ev_git"],
                "unverified": ["需要压测复现"],
            }
        ]
    )
    reasoner = DeepSeekEvidenceReasoner(client)  # type: ignore[arg-type]
    output, metadata = reasoner.reason(
        [
            {
                "evidence_id": "ev_git",
                "source_type": "git",
                "source_uri": "git://payment/a9c4d21",
                "summary": "异常路径未释放连接",
            }
        ],
        "task_test",
    )

    assert output.supporting_evidence_ids == ["ev_git"]
    assert metadata["provider"] == "deepseek"


def test_enabled_llm_without_key_uses_safe_fallback(tmp_path: Path) -> None:
    runtime = DevFlowRuntime(
        llm_settings(
            tmp_path,
            deepseek_api_key=None,
            llm_fallback_enabled=True,
        )
    )
    assert runtime.llm_status()["mode"] == "deterministic_missing_key"
    assert runtime.llm_status()["enabled"] is False


def test_runtime_uses_deepseek_for_planning_and_evidence(tmp_path: Path, monkeypatch) -> None:
    intent = IntentResult(service="payment", days=30, confidence=0.97)
    plan = DeterministicPlanner().create_plan(intent)

    def fake_completion(
        self,
        *,
        messages: list[dict[str, str]],
        purpose: str,
    ) -> LLMJSONResult:
        if purpose == "intent_detection":
            data = intent.model_dump(mode="json")
        elif purpose == "task_planning":
            data = plan.model_dump(mode="json")
        else:
            evidence = json.loads(messages[-1]["content"])["evidence"]
            supporting_ids = [item["evidence_id"] for item in evidence]
            data = {
                "summary": (
                    f"日志证据 [{supporting_ids[1]}] 与代码变更 [{supporting_ids[-1]}] "
                    "共同支持连接未释放假设，仍需故障注入验证。"
                ),
                "confidence": 0.86,
                "supporting_evidence_ids": supporting_ids,
                "unverified": ["需要故障注入验证"],
            }
        return LLMJSONResult(
            data=data,
            model=self.model,
            prompt_tokens=20,
            completion_tokens=15,
            duration_ms=8,
            purpose=purpose,
        )

    monkeypatch.setattr(DeepSeekClient, "complete_json", fake_completion)
    runtime = DevFlowRuntime(llm_settings(tmp_path))
    task = runtime.create_and_run(
        CreateTaskRequest(
            request="分析最近一个月支付服务异常并生成复盘与整改 Issue",
            service="payment",
            days=30,
        )
    )

    assert task.status == TaskStatus.WAITING_APPROVAL
    state = runtime.store.get_state(task.task_id)
    assert state is not None
    reasoning_result = next(
        item for item in state["tool_results"] if item["tool_name"] == "correlate_evidence"
    )
    assert reasoning_result["result"]["data"]["llm"]["mode"] == "remote"
    events = runtime.store.list_events(task.task_id)
    intent_event = next(event for event in events if event["event_type"] == "intent_detected")
    plan_event = next(event for event in events if event["event_type"] == "plan_created")
    assert intent_event["payload"]["llm"]["provider"] == "deepseek"
    assert plan_event["payload"]["llm"]["provider"] == "deepseek"
