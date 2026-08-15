from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import yaml

from devflow.config import PROJECT_ROOT, Settings
from devflow.models import ApprovalRequest, CreateTaskRequest
from devflow.runtime import DevFlowRuntime


DEFAULT_GOLDEN_SET = PROJECT_ROOT / "evaluation" / "cases" / "golden_set.yaml"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "evaluation" / "reports"


def _run_case(runtime: DevFlowRuntime, case: dict[str, Any]) -> dict[str, Any]:
    tenant_id = case.get("tenant_id", "golden-tenant")
    task = runtime.create_and_run(
        CreateTaskRequest(
            request=case["request"],
            service=case.get("service"),
            days=case.get("days"),
            tenant_id=tenant_id,
            user_id="golden-runner",
            user_roles=case.get("roles", ["developer", "git-writer"]),
        )
    )
    decision = case.get("decision", "none")
    if decision in {"approve", "reject"} and task.status.value == "waiting_approval":
        task = runtime.approve_and_resume(
            task.task_id,
            ApprovalRequest(decision=decision, reason=f"golden set {case['id']}"),
            tenant_id=tenant_id,
            decided_by="golden-runner",
        )

    state = runtime.store.get_state(task.task_id, tenant_id)
    assert state is not None
    actual_tools = [item["tool_name"] for item in state.get("tool_results", [])]
    actual_errors = [item.get("code") for item in state.get("errors", [])]
    checks = {
        "status": task.status.value == case["expected_status"],
        "evidence": len(task.evidence) >= int(case.get("min_evidence", 0)),
        "tools": actual_tools == case.get("required_tools", []),
        "error_code": (
            True
            if not case.get("expected_error_code")
            else case["expected_error_code"] in actual_errors
        ),
        "mcp_provenance": all(
            bool(item["result"].get("data", {}).get("_mcp"))
            or item["result"].get("error_code")
            in {"policy_denied", "approval_required", "approval_stale", "risk_mismatch"}
            for item in state.get("tool_results", [])
        ),
    }
    evaluation = runtime.evaluate_task(task.task_id, tenant_id)
    return {
        "id": case["id"],
        "description": case["description"],
        "passed": all(checks.values()),
        "checks": checks,
        "expected_status": case["expected_status"],
        "actual_status": task.status.value,
        "evidence_count": len(task.evidence),
        "actual_tools": actual_tools,
        "errors": actual_errors,
        "security_case": case.get("security_case"),
        "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        "task_id": task.task_id,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DevFlow Agent Golden Set 评测报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 用例：{report['passed']}/{report['total']} 通过",
        f"- 通过率：{report['pass_rate']:.1f}%",
        f"- 安全用例：{report['security_passed']}/{report['security_total']} 通过",
        f"- 执行模式：Deterministic Planner + MCP Client（真实 LLM 默认不参与回归）",
        "",
        "| ID | 场景 | 结果 | 期望状态 | 实际状态 | 证据 |",
        "|---|---|---:|---|---|---:|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['id']} | {case['description']} | "
            f"{'PASS' if case['passed'] else 'FAIL'} | {case['expected_status']} | "
            f"{case['actual_status']} | {case['evidence_count']} |"
        )
    failures = [case for case in report["cases"] if not case["passed"]]
    lines.extend(["", "## 失败详情", ""])
    if not failures:
        lines.append("无。全部 Golden Set 断言通过。")
    else:
        for case in failures:
            failed_checks = [key for key, value in case["checks"].items() if not value]
            lines.append(f"- {case['id']}：{', '.join(failed_checks)}")
    lines.extend(
        [
            "",
            "## 验收口径",
            "",
            "每条用例同时校验终态、最低证据数、严格工具序列、预期错误码和 MCP 调用来源。",
            "真实 DeepSeek Structured Planner 作为可选模式单独验收；本报告固定使用确定性回退，保证可重复。",
            "",
        ]
    )
    return "\n".join(lines)


def run_golden_set(
    case_path: Path = DEFAULT_GOLDEN_SET,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict[str, Any]:
    payload = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload["cases"]
    runtime_root = PROJECT_ROOT / "runtime_data" / "eval_runs"
    runtime_root.mkdir(parents=True, exist_ok=True)
    temp = Path(mkdtemp(prefix="golden-", dir=runtime_root))
    runtime = DevFlowRuntime(
        Settings(
            db_path=temp / "golden.db",
            report_dir=temp / "reports",
            tool_mode="mcp",
            max_steps=8,
            max_replans=2,
            cors_origins=("http://localhost:3000",),
            llm_enabled=False,
            mcp_timeout_seconds=10,
            mcp_max_retries=1,
        )
    )
    results = [_run_case(runtime, case) for case in cases]

    passed = sum(item["passed"] for item in results)
    security = [item for item in results if item["security_case"]]
    report = {
        "version": payload.get("version", 1),
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results) * 100, 1) if results else 0,
        "security_total": len(security),
        "security_passed": sum(item["passed"] for item in security),
        "run_artifacts": str(temp),
        "cases": results,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "golden-set-latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "golden-set-latest.md").write_text(_markdown(report), encoding="utf-8")
    return report
