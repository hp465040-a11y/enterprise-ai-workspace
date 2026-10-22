"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrganizations } from "@/hooks/use-organizations";
import { useWorkspaces } from "@/hooks/use-workspaces";
import {
  createInvestigationRunner,
  getInvestigationSubmission,
  investigateCase,
  investigationErrorMessage,
  listInvestigations,
  type InvestigationResponse,
  type InvestigationInput,
  type InvestigationRun,
  type InvestigationViewState,
} from "@/lib/api/investigations";
import { beijingTime, investigationPresentation } from "@/lib/investigation-presentation";
import { isLocalInvestigationReplay, newReplayComponent, newReplaySubmission, replayTrace } from "@/lib/investigation-replay-diagnostics";
import { useWorkspaceStore } from "@/store/workspace-store";
import { useAuthStore } from "@/store/auth-store";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function InvestigationsPage() {
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const userId = useAuthStore((state) => state.user?.id);
  const { data: organizations, isLoading: organizationsLoading } = useOrganizations();
  const organization = organizations?.find((item) => item.id === organizationId);
  const organizationLabel = organization?.name ?? (organizationId
    ? organizationsLoading ? `正在读取企业（${organizationId}）` : `企业资料暂不可用（${organizationId}）`
    : "未选择企业");
  const { data: workspaces, isLoading: workspacesLoading } = useWorkspaces(organizationId);
  const [caseId, setCaseId] = useState("");
  const [asOfLocal, setAsOfLocal] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [requireKnowledge, setRequireKnowledge] = useState(false);
  const [view, setView] = useState<InvestigationViewState>({ status: "idle" });
  const [copyStatus, setCopyStatus] = useState("");
  const [replayBuild, setReplayBuild] = useState(false);
  const [history, setHistory] = useState<InvestigationRun[]>([]);
  const [statusNotice, setStatusNotice] = useState("");
  const [recovering, setRecovering] = useState(true);
  const runner = useRef<ReturnType<typeof createInvestigationRunner> | null>(null);
  const componentId = useRef(0);
  const submissionId = useRef(0);
  const activeKey = useRef<string | null>(null);
  const activeInput = useRef<InvestigationInput | null>(null);
  const storageKey = organizationId && userId
    ? `ragforge-investigation-submission:${organizationId}:${userId}` : null;

  useEffect(() => {
    if (isLocalInvestigationReplay()) { setRecovering(false); return; }
    if (!organizationId || !storageKey) {
      setHistory([]);
      setView({ status: "idle" });
      activeKey.current = null;
      activeInput.current = null;
      setRecovering(false);
      return;
    }
    let active = true;
    setRecovering(true);
    const org = organizationId;
    const stored = localStorage.getItem(storageKey);
    let key: string | null = null;
    let input: InvestigationInput | null = null;
    if (stored) {
      try {
        const parsed: unknown = JSON.parse(stored);
        if (parsed && typeof parsed === "object" && "key" in parsed && "input" in parsed
            && typeof parsed.key === "string" && parsed.input && typeof parsed.input === "object") {
          key = parsed.key;
          input = parsed.input as InvestigationInput;
        }
      } catch { key = stored; } // Older local submissions stored only the key.
    }
    setHistory([]);
    setView({ status: "idle" });
    setStatusNotice("");
    activeKey.current = key;
    activeInput.current = input;
    const accept = (run: InvestigationRun) => {
      if (!active) return;
      if (run.status === "running") {
        setView({ status: "pending", run });
        setStatusNotice("原提交尚无终态；可能仍在运行或等待状态落库，请勿再次提交。");
      } else if (run.status === "succeeded" && run.result) {
        setView({ status: "success", result: run.result });
        setStatusNotice("已读取保存的调查报告。");
      } else {
        setView({ status: "error", message: "原调查已结束，未保存已校验报告。" });
        setStatusNotice("本次没有可恢复的业务结论，可核对后重新提交。");
      }
      if (run.status !== "running") {
        localStorage.removeItem(storageKey);
        if (activeKey.current === key) activeKey.current = null;
        activeInput.current = null;
        void listInvestigations(org).then((items) => { if (active) setHistory(items); }).catch(() => {});
      }
    };
    const check = async () => {
      if (!key) { if (active) setRecovering(false); return; }
      try { accept(await getInvestigationSubmission(org, key)); }
      catch { if (active) setStatusNotice("暂时无法核对原调查状态；请勿重复提交，稍后再核查。"); }
      finally { if (active) setRecovering(false); }
    };
    void check();
    void listInvestigations(org).then((items) => { if (active) setHistory(items); }).catch(() => {});
    const interval = setInterval(() => {
      if (activeKey.current) void getInvestigationSubmission(org, activeKey.current)
        .then(accept).catch(() => {
          if (active) setStatusNotice("暂时无法核对原调查状态；请勿重复提交，稍后再核查。");
        });
    }, 10_000);
    return () => { active = false; clearInterval(interval); };
  }, [organizationId, storageKey]);
  useEffect(() => {
    const localReplay = isLocalInvestigationReplay();
    setReplayBuild(localReplay);
    if (localReplay) {
      componentId.current = newReplayComponent();
      replayTrace("component_mounted", 0, componentId.current);
    }
    return () => replayTrace("component_unmounted", submissionId.current, componentId.current);
  }, []);
  useEffect(() => {
    if (!replayBuild) return;
    const sequence = submissionId.current;
    const component = componentId.current;
    replayTrace(`state_committed_${view.status}`, sequence, component);
    const reportVisible = !!document.querySelector("[data-investigation-report]");
    if (view.status === "pending" && reportVisible) {
      replayTrace("old_report_visible_during_pending", sequence, component);
    }
    if (view.status === "success") {
      replayTrace(reportVisible ? "report_rendered" : "report_missing", sequence, component);
      const button = document.querySelector<HTMLButtonElement>("[data-investigation-submit]");
      replayTrace(button && !button.disabled && button.textContent?.trim() === "生成只读交接单"
        ? "submit_button_ready" : "submit_button_mismatch", sequence, component);
    }
  }, [view, replayBuild]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (recovering || runner.current?.pending || activeKey.current) {
      replayTrace("duplicate_blocked", submissionId.current, componentId.current);
      return;
    }
    setCopyStatus("");
    if (!organization) {
      setView({ status: "error", message: "当前企业不可用，请重新选择企业。" });
      return;
    }
    const normalizedCaseId = caseId.trim();
    if (!UUID_PATTERN.test(normalizedCaseId)) {
      setView({ status: "error", message: "请输入有效的案件 ID（UUID）。" });
      return;
    }
    const timestamp = asOfLocal ? new Date(asOfLocal) : null;
    if (timestamp && Number.isNaN(timestamp.getTime())) {
      setView({ status: "error", message: "分析时点无效，请重新填写。" });
      return;
    }
    const selectedWorkspace = workspaces?.find((item) => item.id === workspaceId);
    if (requireKnowledge && !selectedWorkspace) {
      setView({ status: "error", message: "必需检索 SOP 时，请先选择当前企业内有权限的工作区。" });
      return;
    }
    // A completed runner must not retain a callback from an earlier hot update.
    const localReplay = isLocalInvestigationReplay();
    const sequence = localReplay ? newReplaySubmission() : 0;
    submissionId.current = sequence;
    replayTrace("submit_started", sequence, componentId.current);
    const update = (state: InvestigationViewState) => {
      replayTrace(`state_write_${state.status}`, sequence, componentId.current);
      if (useWorkspaceStore.getState().organizationId === organization.id
          && useAuthStore.getState().user?.id === userId) setView(state);
    };
    let confirmedResult: InvestigationResponse | null = null;
    const request = (org: string, input: Parameters<typeof investigateCase>[1]) =>
      investigateCase(org, input, (stage, status) =>
        replayTrace(stage, sequence, componentId.current, status), activeKey.current ?? undefined)
        .then((answer) => {
          if (!("status" in answer)) confirmedResult = answer;
          return answer;
        });
    const key = localReplay ? null : crypto.randomUUID();
    if (!localReplay && !storageKey) return;
    const input: InvestigationInput = {
      case_id: normalizedCaseId,
      ...(timestamp ? { as_of: timestamp.toISOString() } : {}),
      ...(selectedWorkspace ? { workspace_id: selectedWorkspace.id } : {}),
      ...(requireKnowledge ? { require_knowledge: true } : {}),
    };
    if (key && storageKey) {
      localStorage.setItem(storageKey, JSON.stringify({ key, input }));
      activeKey.current = key;
      activeInput.current = input;
      setStatusNotice("调查提交中；刷新页面后可按本次提交标识恢复状态。");
    }
    runner.current = createInvestigationRunner(update, request, localReplay ? 10_000 : undefined,
      (stage) => replayTrace(stage, sequence, componentId.current));
    void runner.current.submit(organization.id, input).then(
      () => {
        replayTrace("runner_settled", sequence, componentId.current);
        if (!key) return;
        if (useWorkspaceStore.getState().organizationId !== organization.id
            || useAuthStore.getState().user?.id !== userId) return;
        if (confirmedResult) {
          if (storageKey) localStorage.removeItem(storageKey);
          if (activeKey.current === key) activeKey.current = null;
          activeInput.current = null;
          setStatusNotice("已保存并显示本次校验报告。");
          void listInvestigations(organization.id).then(setHistory).catch(() => {});
          return;
        }
        void getInvestigationSubmission(organization.id, key).then((run) => {
          if (run.status === "running") {
            setView({ status: "pending", run });
            setStatusNotice("原提交尚无终态；请勿重复提交，继续核查保存状态。");
          }
          if (run.status !== "running" && storageKey) {
            localStorage.removeItem(storageKey);
            if (activeKey.current === key) activeKey.current = null;
            activeInput.current = null;
          }
          if (run.status === "succeeded" && run.result) {
            setView({ status: "success", result: run.result });
            setStatusNotice("已读取保存的调查报告。");
            void listInvestigations(organization.id).then(setHistory).catch(() => {});
          } else if (run.status === "failed" || run.status === "interrupted") {
            setView({ status: "error", message: "调查已结束，但未形成已保存的报告。" });
          }
        }).catch(() => setStatusNotice("无法核对本次提交的最终状态；请勿再次提交，稍后再核查。"));
      },
      () => replayTrace("runner_rejected", sequence, componentId.current),
    );
  }

  async function retryOriginalSubmission() {
    const key = activeKey.current;
    const input = activeInput.current;
    if (!organizationId || !key || !input || recovering || view.status === "pending"
        || runner.current?.pending) return;
    const org = organizationId;
    const user = userId;
    setView({ status: "pending" });
    setStatusNotice("正使用原提交标识和原参数核对；数据库幂等约束只允许一次执行。");
    try {
      const answer = await investigateCase(org, input, undefined, key);
      if (useWorkspaceStore.getState().organizationId !== org
          || useAuthStore.getState().user?.id !== user || activeKey.current !== key) return;
      if ("status" in answer && answer.status === "running") {
        setView({ status: "pending", run: answer });
        return;
      }
      const result = "status" in answer ? answer.result : answer;
      if (result) {
        setView({ status: "success", result });
        setStatusNotice("已读取并显示保存的调查报告。");
      } else {
        setView({ status: "error", message: "原调查已结束，但未保存已校验报告。" });
      }
      if (storageKey) localStorage.removeItem(storageKey);
      activeKey.current = null;
      activeInput.current = null;
      void listInvestigations(org).then(setHistory).catch(() => {});
    } catch (error) {
      if (useWorkspaceStore.getState().organizationId !== org
          || useAuthStore.getState().user?.id !== user || activeKey.current !== key) return;
      setView({ status: "error", message: investigationErrorMessage(error) });
      setStatusNotice("原提交结果仍需核对；已保留提交标识和参数，请勿另建提交。");
    }
  }

  const pending = view.status === "pending";
  const result = view.status === "success" && view.result.organization_id === organizationId
    ? view.result : null;
  const presentation = result ? investigationPresentation(result) : null;

  async function copyRequestId() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.request_id);
      setCopyStatus("请求标识已复制");
    } catch {
      setCopyStatus("复制失败；可展开证据详情手动复制完整标识");
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-xl font-semibold">订单履约异常调查</h1>
        <p className="text-sm text-muted-foreground">只读查询并生成调查交接单；建议尚未执行。</p>
        {replayBuild && <p className="text-xs text-muted-foreground">本地保存报告回放 · 页面脚本 20261022-r7 · 不发起新调查</p>}
        {process.env.NEXT_PUBLIC_INVESTIGATION_CONTROLLED_REFRESH === "1" &&
          <p className="text-xs font-medium text-amber-700">受控 Provider＋真实隔离数据库验收：仅验证提交记录与刷新恢复；不调用聊天模型，不代表业务原因调查通过。</p>}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">发起调查</CardTitle>
          <CardDescription>当前企业：{organizationLabel}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="investigation-case-id">案件 ID</Label>
              <Input id="investigation-case-id" value={caseId} onChange={(event) => setCaseId(event.target.value)}
                placeholder="UUID" disabled={pending} required />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="investigation-as-of">分析时点（可选，本地时间）</Label>
              <Input id="investigation-as-of" type="datetime-local" value={asOfLocal}
                onChange={(event) => setAsOfLocal(event.target.value)} disabled={pending} />
              <p className="text-xs text-muted-foreground">留空时由服务端生成分析时点。</p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="investigation-workspace">SOP 工作区（可选）</Label>
              <select id="investigation-workspace" value={workspaceId}
                onChange={(event) => setWorkspaceId(event.target.value)} disabled={pending || workspacesLoading}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm">
                <option value="">不选择工作区</option>
                {workspaces?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={requireKnowledge}
                onChange={(event) => setRequireKnowledge(event.target.checked)} disabled={pending} />
              必须检索所选工作区的 SOP
            </label>
            <Button key={pending ? "pending" : "ready"} type="submit"
              disabled={recovering || pending || !!activeKey.current || !organization}
              data-investigation-submit data-investigation-submit-status={view.status} translate="no"
              className="self-start">
              {pending ? "调查中…" : "生成只读交接单"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {pending && <p role="status" data-investigation-pending aria-live="polite" className="text-sm text-muted-foreground">
        提交尚无终态；正在等待调查或保存结果。请勿重复提交。
      </p>}
      {statusNotice && <p role="status" className="text-sm text-muted-foreground">{statusNotice}</p>}
      {activeKey.current && view.status !== "pending" && <Button type="button" variant="outline"
        onClick={() => {
          if (!organizationId || !activeKey.current) return;
          void getInvestigationSubmission(organizationId, activeKey.current).then((run) => {
            if (run.status === "running") setView({ status: "pending", run });
            else if (run.status === "succeeded" && run.result) setView({ status: "success", result: run.result });
            else setView({ status: "error", message: "调查已结束，未保存报告。" });
            if (run.status !== "running" && storageKey) {
              localStorage.removeItem(storageKey);
              activeKey.current = null;
            }
          }).catch(() => setStatusNotice("无法核对原调查状态；请勿重复提交。"));
        }}>核查原调查状态</Button>}
      {activeKey.current && activeInput.current && view.status !== "pending" &&
        <Button type="button" variant="outline" onClick={() => void retryOriginalSubmission()}>
          使用原提交标识重试
        </Button>}
      {view.status === "error" && <p role="alert" className="text-sm text-destructive">
        {view.message}
      </p>}
      {result && presentation && <Card data-investigation-report>
        <CardHeader>
          <CardTitle className="text-base">调查结论：{presentation.outcome}</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <span>请求标识：{result.request_id.slice(0, 8)}…</span>
            <Button type="button" variant="outline" size="sm" onClick={() => void copyRequestId()}>
              复制完整标识
            </Button>
            {copyStatus && <span role="status">{copyStatus}</span>}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border bg-muted/40 p-4 text-sm">
            <p className="font-medium">{presentation.headline}</p>
            {presentation.allocationFact && <p className="mt-2">{presentation.allocationFact}</p>}
            <p className="mt-2">{presentation.causeSummary}；{presentation.wholeOrder}；本次未执行处置。</p>
            <p className="mt-2">{presentation.causeGap}</p>
          </div>
          {result.observations && <div className="grid gap-3 text-sm sm:grid-cols-2">
            {(["shipment", "delivery"] as const).map((kind) => {
              const timing = result.observations?.[kind];
              return <div key={kind} className="rounded-md border p-3">
                <p className="font-medium">{kind === "shipment" ? "发货时间" : "送达时间"}</p>
                <p>承诺：{beijingTime(timing?.expected_at)}</p>
                <p>实际：{beijingTime(timing?.actual_at)}</p>
              </div>;
            })}
          </div>}
          <details className="rounded-md border p-3 text-sm" translate="no">
            <summary className="cursor-pointer font-medium">六部分交接单</summary>
            <div className="mt-3 space-y-2">
              {presentation.sections.map(([title, content]) => <section key={title}>
                <h3 className="font-medium">{title}</h3>
                <p>{content}</p>
              </section>)}
              <details className="rounded-md border p-3">
                <summary className="cursor-pointer font-medium">查看完整原文</summary>
                <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words font-sans leading-relaxed">{result.handoff}</pre>
              </details>
            </div>
          </details>
          <details className="rounded-md border p-3 text-sm" translate="no">
            <summary className="cursor-pointer font-medium">技术证据</summary>
            <div className="mt-3 space-y-3">
              <p>{result.report.evidence_event_ids.length} 条业务事件、{result.report.knowledge_source_ids?.length ?? 0} 条 SOP 来源</p>
              <p>{presentation.sourceSummary}</p>
              <details className="rounded-md border p-3">
                <summary className="cursor-pointer font-medium">查看完整标识、JSON 与 SOP 原文</summary>
                <div className="mt-3 space-y-3">
                  <p>完整请求标识：{result.request_id}</p>
                  <p>业务事件 ID：{result.report.evidence_event_ids.join("、") || "无"}</p>
                  <p>SOP 来源 ID：{result.report.knowledge_source_ids?.join("、") || "无"}</p>
                  <p className="font-medium">原始结构化报告</p>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(result.report, null, 2)}</pre>
                  <p className="font-medium">完整交接原文（含 SOP 检索内容）</p>
                  <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words font-sans leading-relaxed">{result.handoff}</pre>
                </div>
              </details>
            </div>
          </details>
        </CardContent>
      </Card>}
      {history.some((item) => item.organization_id === organizationId) && <Card><CardHeader><CardTitle className="text-base">我的调查记录</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">{history.filter((item) => item.organization_id === organizationId).map((item) =>
          <div key={item.id} className="flex items-center justify-between gap-2 border-b pb-2">
            <span>案件 {item.case_id} · {item.status === "succeeded" ? "已完成" : item.status === "running" ? "尚无终态" : "未形成报告"}</span>
            {item.status === "succeeded" && item.result && <Button type="button" variant="outline" size="sm"
              disabled={!!activeKey.current}
              onClick={() => setView({ status: "success", result: item.result! })}>查看报告</Button>}
          </div>)}</CardContent></Card>}
    </div>
  );
}
