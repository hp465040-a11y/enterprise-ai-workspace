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
  investigateCase,
  type InvestigationViewState,
} from "@/lib/api/investigations";
import { beijingTime, investigationPresentation } from "@/lib/investigation-presentation";
import { isLocalInvestigationReplay, newReplayComponent, newReplaySubmission, replayTrace } from "@/lib/investigation-replay-diagnostics";
import { useWorkspaceStore } from "@/store/workspace-store";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function InvestigationsPage() {
  const organizationId = useWorkspaceStore((state) => state.organizationId);
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
  const runner = useRef<ReturnType<typeof createInvestigationRunner> | null>(null);
  const componentId = useRef(0);
  const submissionId = useRef(0);
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
    if (runner.current?.pending) {
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
      setView(state);
    };
    const request = (org: string, input: Parameters<typeof investigateCase>[1]) =>
      investigateCase(org, input, (stage, status) =>
        replayTrace(stage, sequence, componentId.current, status));
    runner.current = createInvestigationRunner(update, request, localReplay ? 10_000 : undefined,
      (stage) => replayTrace(stage, sequence, componentId.current));
    void runner.current.submit(organization.id, {
      case_id: normalizedCaseId,
      ...(timestamp ? { as_of: timestamp.toISOString() } : {}),
      ...(selectedWorkspace ? { workspace_id: selectedWorkspace.id } : {}),
      ...(requireKnowledge ? { require_knowledge: true } : {}),
    }).then(
      () => replayTrace("runner_settled", sequence, componentId.current),
      () => replayTrace("runner_rejected", sequence, componentId.current),
    );
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
            <Button key={pending ? "pending" : "ready"} type="submit" disabled={pending || !organization}
              data-investigation-submit data-investigation-submit-status={view.status} translate="no"
              className="self-start">
              {pending ? "调查中…" : "生成只读交接单"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {pending && <p role="status" data-investigation-pending aria-live="polite" className="text-sm text-muted-foreground">
        正在调查并校验证据，请等待本次请求完成。
      </p>}
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
    </div>
  );
}
