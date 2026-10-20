import { ApiError, apiFetch } from "@/lib/api/client";

export type ActionStatus = "pending_approval" | "approved" | "rejected" | "executed";

export interface ActionRequestRecord {
  id: string;
  organization_id: string;
  requested_by_user_id: string;
  action_type: "notify_case_customer";
  target_case_id: string;
  status: ActionStatus;
  created_at: string;
  review_decision: "approved" | "rejected" | null;
  reviewed_at: string | null;
  executed_at: string | null;
}

export interface CreateActionInput {
  target_case_id: string;
  message: string;
  idempotency_key: string;
}

export interface CustomerNotificationRecord {
  id: string;
  organization_id: string;
  action_request_id: string;
  target_case_id: string;
  created_by_user_id: string;
  content: string;
  delivery_status: "not_sent";
  created_at: string;
}

export interface ActionReviewResult {
  id: string;
  organization_id: string;
  status: "approved" | "rejected";
  review_decision: "approved" | "rejected";
  reviewed_at: string;
}

export function listActionRequests(organizationId: string): Promise<ActionRequestRecord[]> {
  return apiFetch(`/organizations/${organizationId}/action-requests`);
}

export function createActionRequest(organizationId: string, input: CreateActionInput): Promise<ActionRequestRecord> {
  return apiFetch(`/organizations/${organizationId}/action-requests`, {
    method: "POST", body: input, retryUnauthorized: false,
  });
}

export function reviewActionRequest(
  organizationId: string, requestId: string, decision: "approved" | "rejected",
): Promise<ActionReviewResult> {
  return apiFetch(`/organizations/${organizationId}/action-requests/${requestId}/review`, {
    method: "POST", body: { decision }, retryUnauthorized: false,
  });
}

export function executeActionRequest(
  organizationId: string, requestId: string,
): Promise<CustomerNotificationRecord> {
  return apiFetch(`/organizations/${organizationId}/action-requests/${requestId}/execute`, {
    method: "POST", retryUnauthorized: false,
  });
}

export function getActionNotification(
  organizationId: string, requestId: string,
): Promise<CustomerNotificationRecord> {
  return apiFetch(`/organizations/${organizationId}/action-requests/${requestId}/notification`);
}

export function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录已失效，请重新登录后查看申请状态。";
    if (error.status === 403) return "你没有当前企业或审核操作的权限。";
    if (error.status === 404) return "案件或申请在当前企业中不存在。";
    if (error.status === 409) return "幂等键已用于不同内容，或该申请已经审核。请刷新列表核对状态。";
    if (error.status === 422) return "输入无效，请检查案件 ID、通知内容和幂等键。";
  }
  return "请求未确认成功。请刷新列表核对状态；重试创建会沿用同一幂等键。";
}
