"use client";

import {FormEvent, useEffect, useMemo, useState} from "react";

type Step = {
  step_id: string;
  title: string;
  skill_id: string;
  tool_name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "blocked" | "skipped";
  risk_level: string;
  result_summary?: string | null;
};

type Evidence = {
  evidence_id: string;
  source_type: string;
  source_uri: string;
  summary: string;
};

type Approval = {
  approval_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  arguments_hash: string;
  status: string;
};

type Task = {
  task_id: string;
  status: string;
  request: string;
  intent: {service?: string; days?: number};
  plan: {goal?: string; steps?: Step[]};
  evidence: Evidence[];
  pending_approval?: Approval | null;
  final_answer?: string | null;
  errors: Array<{message: string}>;
};

type EvaluationDimension = {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: "pass" | "warning" | "fail";
  explanation: string;
  checks: string[];
};

type Evaluation = {
  overall_score: number;
  grade: string;
  passed: boolean;
  dimensions: EvaluationDimension[];
  gate_failures: string[];
};

type AuditEvent = {
  event_id: number;
  event_type: string;
  node?: string | null;
  message: string;
  created_at: string;
};

type LLMStatus = {
  enabled: boolean;
  mode: string;
  provider?: string | null;
  model?: string | null;
  thinking: boolean;
  fallback_enabled: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const statusLabel: Record<string, string> = {
  created: "已创建",
  running: "执行中",
  waiting_approval: "等待审批",
  needs_clarification: "需要补充",
  completed: "已完成",
  failed: "失败",
  rejected: "已拒绝",
};

export default function Home() {
  const [request, setRequest] = useState("分析最近一个月支付服务异常，结合历史故障和代码变更生成复盘报告；经我确认后创建整改 Issue。 ");
  const [task, setTask] = useState<Task | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const completedSteps = useMemo(
    () => task?.plan.steps?.filter((step) => step.status === "succeeded").length ?? 0,
    [task],
  );
  const totalSteps = task?.plan.steps?.length ?? 0;

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((health) => setLlmStatus(health.llm))
      .catch(() => setLlmStatus(null));
  }, []);

  async function loadInsights(taskId: string) {
    const [evaluationResponse, auditResponse] = await Promise.all([
      fetch(`${API_BASE}/api/tasks/${taskId}/evaluation`),
      fetch(`${API_BASE}/api/tasks/${taskId}/audit`),
    ]);
    if (!evaluationResponse.ok || !auditResponse.ok) {
      throw new Error("质量评测或审计链加载失败");
    }
    setEvaluation(await evaluationResponse.json());
    setAuditEvents(await auditResponse.json());
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setEvaluation(null);
    setAuditEvents([]);
    try {
      const response = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({request, service: "payment", days: 30}),
      });
      if (!response.ok) throw new Error(await response.text());
      const nextTask = await response.json() as Task;
      setTask(nextTask);
      await loadInsights(nextTask.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!task) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/tasks/${task.task_id}/approval`, {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          decision,
          reason: decision === "approve" ? "已核对报告和 Issue 参数" : "需要先补充压测证据",
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const nextTask = await response.json() as Task;
      setTask(nextTask);
      await loadInsights(nextTask.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">DF</span>
          <div>
            <strong>DevFlow Agent</strong>
            <span>Enterprise Incident Operations</span>
          </div>
        </div>
        <div className={`environment ${llmStatus?.enabled ? "online" : "offline"}`}>
          <i /> {llmStatus?.enabled ? `DEEPSEEK · ${llmStatus.model}` : "DETERMINISTIC FALLBACK"}
        </div>
      </header>

      <section className="hero">
        <p className="eyebrow">CONTROLLED AGENT WORKFLOW</p>
        <h1>让企业 Agent 的每一步<br />都可见、可控、可追溯。</h1>
        <p className="lede">从指标、日志、历史知识到代码变更，完成故障调查与整改协同；写操作必须由人审批。</p>
      </section>

      <section className="workspace">
        <form className="requestPanel" onSubmit={submit}>
          <div className="sectionTitle">
            <span>01</span>
            <div><h2>任务输入</h2><p>自然语言目标将被转换为结构化执行计划</p></div>
          </div>
          <textarea value={request} onChange={(event) => setRequest(event.target.value)} rows={5} />
          <div className="formMeta">
            <span>服务 <b>payment</b></span>
            <span>范围 <b>30 days</b></span>
            <span>模式 <b>{llmStatus?.enabled ? "deepseek-hybrid" : "deterministic"}</b></span>
          </div>
          <button className="primary" disabled={busy || request.trim().length < 3}>
            {busy ? "正在执行…" : "启动调查"}<span>↗</span>
          </button>
          {error && <p className="error">{error}</p>}
        </form>

        <aside className="principles">
          <p className="eyebrow">EXECUTION POLICY</p>
          <ul>
            <li><span>01</span> 默认只读，工具按最小权限暴露</li>
            <li><span>02</span> 关键结论必须绑定 Evidence ID</li>
            <li><span>03</span> 写操作审批绑定精确参数哈希</li>
            <li><span>04</span> 检查点、幂等与 Trace 覆盖全链路</li>
          </ul>
        </aside>
      </section>

      {task && (
        <section className="resultArea">
          <div className="taskHeader">
            <div>
              <p className="eyebrow">TASK / {task.task_id}</p>
              <h2>{task.plan.goal ?? "任务执行状态"}</h2>
            </div>
            <div className={`status ${task.status}`}>{statusLabel[task.status] ?? task.status}</div>
          </div>

          <div className="stats">
            <div><span>{completedSteps}/{totalSteps}</span><small>完成步骤</small></div>
            <div><span>{task.evidence.length}</span><small>证据条目</small></div>
            <div><span>{task.intent.days ?? 0}d</span><small>调查窗口</small></div>
            <div><span>{task.pending_approval ? "1" : "0"}</span><small>待审批动作</small></div>
          </div>

          <div className="contentGrid">
            <div className="planPanel">
              <div className="sectionTitle compact"><span>02</span><div><h2>执行计划</h2><p>确定性骨架中的有界工具调用</p></div></div>
              <div className="timeline">
                {task.plan.steps?.map((step) => (
                  <article className={`step ${step.status}`} key={step.step_id}>
                    <div className="stepIndex">{step.step_id}</div>
                    <div className="stepBody">
                      <div className="stepTop"><h3>{step.title}</h3><em>{step.status}</em></div>
                      <p>{step.result_summary ?? "等待执行"}</p>
                      <div className="tags"><span>{step.skill_id}</span><span>{step.tool_name}</span><span>{step.risk_level}</span></div>
                    </div>
                  </article>
                ))}
              </div>
            </div>

            <div className="evidencePanel">
              <div className="sectionTitle compact"><span>03</span><div><h2>证据链</h2><p>结论可回溯到真实来源</p></div></div>
              <div className="evidenceList">
                {task.evidence.map((item) => (
                  <article key={item.evidence_id}>
                    <div><b>{item.source_type}</b><code>{item.evidence_id}</code></div>
                    <p>{item.summary}</p>
                    <small>{item.source_uri}</small>
                  </article>
                ))}
              </div>
            </div>
          </div>

          {evaluation && (
            <div className="insightGrid">
              <section className="qualityPanel">
                <div className="sectionTitle compact"><span>04</span><div><h2>Agent 质量评测</h2><p>确定性质量门与可解释评分</p></div></div>
                <div className="qualityOverview">
                  <div
                    className="scoreRing"
                    style={{background: `conic-gradient(var(--blue) ${evaluation.overall_score}%, #deddd5 0)`}}
                  >
                    <div><strong>{evaluation.overall_score}</strong><small>/ 100</small></div>
                  </div>
                  <div className="gradeCopy">
                    <span className={evaluation.passed ? "gatePass" : "gateFail"}>
                      {evaluation.passed ? "QUALITY GATE PASSED" : "QUALITY GATE FAILED"}
                    </span>
                    <h3>等级 {evaluation.grade}</h3>
                    <p>完成度、证据、安全、审计和可靠性五个维度加权计算。</p>
                  </div>
                </div>
                <div className="dimensionList">
                  {evaluation.dimensions.map((dimension) => (
                    <article key={dimension.key}>
                      <div className="dimensionTop">
                        <b>{dimension.label}</b>
                        <span>{dimension.score}</span>
                      </div>
                      <div className="scoreTrack"><i className={dimension.status} style={{width: `${dimension.score}%`}} /></div>
                      <p>{dimension.explanation}</p>
                    </article>
                  ))}
                </div>
                {evaluation.gate_failures.length > 0 && (
                  <ul className="gateFailures">
                    {evaluation.gate_failures.map((failure) => <li key={failure}>{failure}</li>)}
                  </ul>
                )}
              </section>

              <section className="auditPanel">
                <div className="sectionTitle compact"><span>05</span><div><h2>执行审计链</h2><p>{auditEvents.length} 条不可变事件记录</p></div></div>
                <div className="auditTimeline">
                  {auditEvents.slice(-14).map((event) => (
                    <article key={event.event_id}>
                      <div className="auditMarker" />
                      <div>
                        <div className="auditMeta">
                          <b>{event.event_type}</b>
                          <time>{new Date(event.created_at).toLocaleTimeString("zh-CN", {hour12: false})}</time>
                        </div>
                        <p>{event.message}</p>
                        <small>{event.node ?? "system"} · EVT-{String(event.event_id).padStart(4, "0")}</small>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          )}

          {task.status === "waiting_approval" && task.pending_approval && (
            <section className="approvalPanel">
              <div className="approvalIcon">!</div>
              <div className="approvalCopy">
                <p className="eyebrow">HUMAN APPROVAL REQUIRED</p>
                <h2>即将调用 {task.pending_approval.tool_name}</h2>
                <p>该动作会在外部系统产生写入。审批仅对下面这组参数有效，参数变化后自动失效。</p>
                <pre>{JSON.stringify(task.pending_approval.arguments, null, 2)}</pre>
                <small>参数哈希：{task.pending_approval.arguments_hash}</small>
              </div>
              <div className="approvalActions">
                <button className="secondary" disabled={busy} onClick={() => decide("reject")}>拒绝</button>
                <button className="approve" disabled={busy} onClick={() => decide("approve")}>批准并继续</button>
              </div>
            </section>
          )}

          {task.final_answer && (
            <section className="finalPanel">
              <p className="eyebrow">FINAL RESPONSE</p>
              <h2>任务结论</h2>
              <p>{task.final_answer}</p>
            </section>
          )}
        </section>
      )}

      <footer>DEVFLOW / CONTROLLED AGENT MVP <span>2026</span></footer>
    </main>
  );
}
