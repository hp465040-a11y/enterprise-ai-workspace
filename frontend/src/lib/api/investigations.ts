import { ApiError, apiFetch } from "@/lib/api/client";

export interface InvestigationResponse {
  run_id?: string | null;
  request_id: string;
  organization_id: string;
  case_id: string;
  as_of: string;
  report: {
    outcome: "observed_delay" | "no_observed_delay" | "insufficient_evidence" | "not_found" | "invalid_input";
    evidence_event_ids: string[];
    root_cause: "unknown" | "inventory_allocation_blocked";
    knowledge_source_ids?: string[];
  };
  handoff: string;
  observations?: {
    whole_order_completion: string | null;
    shipment: TimingObservation | null;
    delivery: TimingObservation | null;
    allocation: {
      status: "blocked" | "not_observed";
      causal_status: "linked_to_shipment_delay" | "unknown";
      failure_event_ids: string[];
      attribution_event_id: string | null;
      linked_failure_event_id: string | null;
    } | null;
  } | null;
}

export interface InvestigationRun {
  id: string;
  organization_id: string;
  case_id: string;
  workspace_id: string | null;
  as_of: string;
  status: "running" | "succeeded" | "failed" | "interrupted";
  deadline_at: string;
  created_at: string;
  finished_at: string | null;
  error_code: string | null;
  result: InvestigationResponse | null;
}

export type InvestigationSubmission = InvestigationResponse | InvestigationRun;

export function getInvestigationSubmission(organizationId: string, key: string): Promise<InvestigationRun> {
  return apiFetch<InvestigationRun>(
    `/organizations/${organizationId}/investigations/submissions/${encodeURIComponent(key)}`,
    { retryUnauthorized: false },
  );
}

export function listInvestigations(organizationId: string): Promise<InvestigationRun[]> {
  return apiFetch<InvestigationRun[]>(`/organizations/${organizationId}/investigations`,
    { retryUnauthorized: false });
}

export interface TimingObservation {
  status: string | null;
  scope: string | null;
  tracking_number: string | null;
  expected_at: string | null;
  actual_at: string | null;
  difference_seconds: number | null;
  reason: string | null;
}

export interface InvestigationInput {
  case_id: string;
  as_of?: string;
  workspace_id?: string;
  require_knowledge?: boolean;
}

export function investigateCase(
  organizationId: string,
  input: InvestigationInput,
  onTransportStage?: (stage: "response_headers" | "json_parsed", status?: number) => void,
  submissionKey?: string,
): Promise<InvestigationSubmission> {
  return apiFetch<InvestigationSubmission>(`/organizations/${organizationId}/investigations`, {
    method: "POST",
    body: input,
    retryUnauthorized: false,
    ...(submissionKey ? { headers: { "Idempotency-Key": submissionKey } } : {}),
    ...(onTransportStage ? {
      onResponseHeaders: (status: number) => onTransportStage("response_headers", status),
      onJsonParsed: () => onTransportStage("json_parsed"),
    } : {}),
  });
}

export function investigationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "未登录或登录已过期，请重新登录。";
    if (error.status === 403) return "无权调查当前企业的案件。";
    if (error.status === 422) return "输入无效，请检查案件 ID 和分析时点。";
    if (error.status >= 500) return "调查执行失败，请稍后人工核查。此次没有形成业务结论。";
  }
  if (error instanceof TypeError) return "连接已中断，服务端调查状态尚未确认；请先核查原提交，勿直接重试。";
  return "调查未完成，请核查请求状态。";
}

export type InvestigationViewState =
  | { status: "idle" }
  | { status: "pending"; run?: InvestigationRun }
  | { status: "success"; result: InvestigationResponse }
  | { status: "error"; message: string };

class LocalReplayTimeoutError extends Error {}

/** One click starts at most one investigation; the caller owns display state. */
export function createInvestigationRunner(
  update: (state: InvestigationViewState) => void,
  request = investigateCase,
  localReplayDeadlineMs?: number,
  onDeadlineStage?: (stage: "timeout_armed" | "timeout_fired") => void,
) {
  let pending = false;
  return {
    get pending() { return pending; },
    async submit(organizationId: string, input: InvestigationInput): Promise<boolean> {
      if (pending) return false;
      pending = true;
      update({ status: "pending" });
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const operation = request(organizationId, input);
        const result = localReplayDeadlineMs === undefined ? await operation : await Promise.race([
          operation,
          new Promise<InvestigationSubmission>((_, reject) => {
            timer = setTimeout(() => {
              onDeadlineStage?.("timeout_fired");
              reject(new LocalReplayTimeoutError());
            }, localReplayDeadlineMs);
            onDeadlineStage?.("timeout_armed");
          }),
        ]);
        if ("status" in result) {
          if (result.status === "running") update({ status: "pending", run: result });
          else if (result.status === "succeeded" && result.result)
            update({ status: "success", result: result.result });
          else update({ status: "error", message: "调查已结束，但未形成可恢复的已校验报告。" });
        } else update({ status: "success", result });
      } catch (error) {
        update({ status: "error", message: error instanceof LocalReplayTimeoutError
          ? "本地保存报告回放超过等待截止，页面未完成结果处理；未发起新的调查。"
          : investigationErrorMessage(error) });
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        pending = false;
      }
      return true;
    },
  };
}
