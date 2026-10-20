import { describe, expect, it } from "vitest";

import type { ActionRequestRecord, CustomerNotificationRecord } from "@/lib/api/action-requests";
import {
  applyExecutionResult, applyReviewResult, executionTime, formatBeijingTime,
  locateNotificationCard, notificationKey, requestActions, resolveNotification,
  reviewDetails, statusText, upsertRequest,
} from "@/lib/action-request-state";

const pending: ActionRequestRecord = {
  id: "request-1", organization_id: "org-1", requested_by_user_id: "user-1",
  action_type: "notify_case_customer", target_case_id: "case-1",
  status: "pending_approval", created_at: "2026-10-19T00:00:00Z",
  review_decision: null, reviewed_at: null, executed_at: null,
};

const notification: CustomerNotificationRecord = {
  id: "notification-1", organization_id: "org-1", action_request_id: "request-1",
  target_case_id: "case-1", created_by_user_id: "admin-1", content: "Prepared message",
  delivery_status: "not_sent", created_at: "2026-10-19T00:01:00Z",
};

describe("action-request confirmed state", () => {
  it("shows approved status and execute action from one updated list without a read", () => {
    const rows = upsertRequest([], pending);
    const updated = applyReviewResult(rows, {
      id: pending.id, organization_id: pending.organization_id,
      status: "approved", review_decision: "approved", reviewed_at: "2026-10-19T00:00:30Z",
    })!;
    expect(statusText(updated[0]!.status)).toBe("已批准，尚未发送通知");
    expect(requestActions(updated[0]!.status, true)).toEqual({
      review: false, execute: true, viewNotification: false,
    });
    expect(rows[0]!.status).toBe("pending_approval");
  });

  it("shows rejected status with no review or execution action", () => {
    const updated = applyReviewResult([pending], {
      id: pending.id, organization_id: pending.organization_id,
      status: "rejected", review_decision: "rejected", reviewed_at: "2026-10-19T00:00:30Z",
    })!;
    expect(statusText(updated[0]!.status)).toBe("已拒绝");
    expect(requestActions(updated[0]!.status, true)).toEqual({
      review: false, execute: false, viewNotification: false,
    });
  });

  it("shows internal execution and view action from the committed notification", () => {
    const approved = { ...pending, status: "approved" as const };
    const updated = applyExecutionResult([approved], notification)!;
    expect(statusText(updated[0]!.status)).toContain("未发送；客户收悉未确认");
    expect(requestActions(updated[0]!.status, true)).toEqual({
      review: false, execute: false, viewNotification: true,
    });
  });

  it("does not change unrelated organizations or invent success when an operation fails", () => {
    const other = { ...pending, id: "request-other", organization_id: "org-other" };
    const original = [pending, other];
    expect(applyReviewResult(original, {
      id: pending.id, organization_id: "org-other",
      status: "approved", review_decision: "approved", reviewed_at: "2026-10-19T00:00:30Z",
    })).toEqual(original);
    expect(applyExecutionResult(original, { ...notification, organization_id: "org-other" })).toEqual(original);
    expect(requestActions(original[0]!.status, true).review).toBe(true);
    expect(statusText(original[0]!.status)).toContain("待人工审核");
  });

  it("uses real lifecycle instants in Beijing time and distinguishes absent history", () => {
    expect(formatBeijingTime(pending.created_at)).toContain("08:00:00");
    expect(formatBeijingTime(pending.created_at)).toContain("北京时间");
    expect(reviewDetails(pending)).toEqual({ decision: "尚未审核", time: "尚未审核" });
    expect(executionTime(pending)).toBe("尚未执行");
    const historical = { ...pending, status: "executed" as const };
    expect(reviewDetails(historical)).toEqual({ decision: "未记录", time: "未记录" });
    expect(executionTime(historical)).toBe("未记录");
    expect(formatBeijingTime(null)).toBe("未记录");
    const executed = applyExecutionResult([historical], notification)![0]!;
    expect(executionTime(executed)).toContain("08:01:00");
  });

  it("loads only an uncached notification and checks the exact organization and request", async () => {
    let reads = 0;
    const read = async () => { reads++; return notification; };
    const first = await resolveNotification("org-1", "request-1", undefined, read);
    expect(first).toEqual(notification);
    expect(reads).toBe(1);
    expect(await resolveNotification("org-1", "request-1", first!, read)).toEqual(notification);
    expect(reads).toBe(1);
    expect(await resolveNotification("org-1", "request-2", undefined, read)).toBe(null);
    expect(await resolveNotification("org-2", "request-1", undefined, read)).toBe(null);
    expect(notificationKey("org-1", "request-1") === notificationKey("org-1", "request-2")).toBe(false);
  });

  it("scrolls and focuses the chosen notification card", () => {
    const actions: unknown[] = [];
    locateNotificationCard({
      scrollIntoView: (options) => actions.push(["scroll", options]),
      focus: (options) => actions.push(["focus", options]),
    });
    expect(actions).toEqual([
      ["scroll", { behavior: "smooth", block: "center" }],
      ["focus", { preventScroll: true }],
    ]);
  });
});
