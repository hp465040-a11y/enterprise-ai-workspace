import { ApiError, apiFetch } from "@/lib/api/client";

export interface InvestigationResponse {
  request_id: string;
  organization_id: string;
  case_id: string;
  as_of: string;
  report: {
    outcome: "observed_delay" | "no_observed_delay" | "insufficient_evidence" | "not_found" | "invalid_input";
    evidence_event_ids: string[];
    root_cause: "unknown";
    knowledge_source_ids?: string[];
  };
  handoff: string;
  observations?: {
    whole_order_completion: string | null;
    shipment: TimingObservation | null;
    delivery: TimingObservation | null;
  } | null;
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
): Promise<InvestigationResponse> {
  return apiFetch<InvestigationResponse>(`/organizations/${organizationId}/investigations`, {
    method: "POST",
    body: input,
    retryUnauthorized: false,
  });
}

export function investigationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "未登录或登录已过期，请重新登录。";
    if (error.status === 403) return "无权调查当前企业的案件。";
    if (error.status === 422) return "输入无效，请检查案件 ID 和分析时点。";
    if (error.status >= 500) return "调查执行失败，请稍后人工核查。此次没有形成业务结论。";
  }
  if (error instanceof TypeError) return "网络连接失败，调查未完成；请检查连接后再试。";
  return "调查未完成，请核查请求状态。";
}

export type InvestigationViewState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success"; result: InvestigationResponse }
  | { status: "error"; message: string };

/** One click starts at most one investigation; the caller owns display state. */
export function createInvestigationRunner(
  update: (state: InvestigationViewState) => void,
  request = investigateCase,
) {
  let pending = false;
  return {
    get pending() { return pending; },
    async submit(organizationId: string, input: InvestigationInput): Promise<boolean> {
      if (pending) return false;
      pending = true;
      update({ status: "pending" });
      try {
        update({ status: "success", result: await request(organizationId, input) });
      } catch (error) {
        update({ status: "error", message: investigationErrorMessage(error) });
      } finally {
        pending = false;
      }
      return true;
    },
  };
}
