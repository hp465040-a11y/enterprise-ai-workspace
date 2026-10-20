import type {
  ActionRequestRecord, ActionReviewResult, CustomerNotificationRecord,
} from "@/lib/api/action-requests";

export function statusText(status: ActionRequestRecord["status"]): string {
  if (status === "approved") return "已批准，尚未发送通知";
  if (status === "rejected") return "已拒绝";
  if (status === "executed") return "站内通知记录已创建，未发送；客户收悉未确认";
  return "待人工审核，尚未发送通知";
}

const beijingTime = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

export function formatBeijingTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? "未记录" : `${beijingTime.format(instant)}（北京时间）`;
}

export function reviewDetails(item: ActionRequestRecord) {
  if (item.status === "pending_approval") return { decision: "尚未审核", time: "尚未审核" };
  return {
    decision: item.review_decision === "approved" ? "已批准"
      : item.review_decision === "rejected" ? "已拒绝" : "未记录",
    time: formatBeijingTime(item.reviewed_at),
  };
}

export function executionTime(item: ActionRequestRecord): string {
  return item.status === "executed" ? formatBeijingTime(item.executed_at) : "尚未执行";
}

export const notificationKey = (organizationId: string, requestId: string) => `${organizationId}:${requestId}`;

export function notificationMatches(
  notification: CustomerNotificationRecord, organizationId: string, requestId: string,
): boolean {
  return notification.organization_id === organizationId && notification.action_request_id === requestId;
}

export async function resolveNotification(
  organizationId: string, requestId: string, cached: CustomerNotificationRecord | undefined,
  read: () => Promise<CustomerNotificationRecord>,
): Promise<CustomerNotificationRecord | null> {
  const record = cached ?? await read();
  return notificationMatches(record, organizationId, requestId) ? record : null;
}

export function locateNotificationCard(card: Pick<HTMLElement, "scrollIntoView" | "focus">): void {
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.focus({ preventScroll: true });
}

export function requestActions(status: ActionRequestRecord["status"], canReview: boolean) {
  return {
    review: canReview && status === "pending_approval",
    execute: canReview && status === "approved",
    viewNotification: status === "executed",
  };
}

export function upsertRequest(
  requests: ActionRequestRecord[] | undefined, created: ActionRequestRecord,
): ActionRequestRecord[] {
  return [created, ...(requests ?? []).filter((item) => item.id !== created.id)];
}

export function applyReviewResult(
  requests: ActionRequestRecord[] | undefined, result: ActionReviewResult,
): ActionRequestRecord[] | undefined {
  return requests?.map((item) => item.id === result.id && item.organization_id === result.organization_id
    ? { ...item, status: result.status, review_decision: result.review_decision,
        reviewed_at: result.reviewed_at } : item);
}

export function applyExecutionResult(
  requests: ActionRequestRecord[] | undefined, notification: CustomerNotificationRecord,
): ActionRequestRecord[] | undefined {
  // A returned notification was committed together with the executed status.
  return requests?.map((item) => item.id === notification.action_request_id
    && item.organization_id === notification.organization_id
    ? { ...item, status: "executed" as const, executed_at: notification.created_at } : item);
}
