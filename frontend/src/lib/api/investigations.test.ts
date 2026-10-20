import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(public status: number, public code: string, message: string) {
      super(message);
    }
  }
  return { ApiError, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "@/lib/api/client";
import {
  createInvestigationRunner,
  investigateCase,
  investigationErrorMessage,
  type InvestigationResponse,
  type InvestigationViewState,
} from "@/lib/api/investigations";

const response: InvestigationResponse = {
  request_id: "request-1",
  organization_id: "org-1",
  case_id: "case-1",
  as_of: "2026-10-15T12:00:00Z",
  report: { outcome: "insufficient_evidence", evidence_event_ids: [], root_cause: "unknown" },
  handoff: "1. 已确认事实\n2. 证据引用及观察时间\n3. 不能确认的事项\n4. 缺少的资料\n5. 下一步建议\n6. 处理状态",
};

afterEach(() => vi.clearAllMocks());

describe("read-only investigation request", () => {
  it("uses the selected organization and sends one authenticated POST without retry", async () => {
    vi.mocked(apiFetch).mockResolvedValue(response);
    await expect(investigateCase("org-1", { case_id: "case-1" })).resolves.toEqual(response);
    expect(apiFetch).toHaveBeenCalledOnce();
    expect(apiFetch).toHaveBeenCalledWith("/organizations/org-1/investigations", {
      method: "POST", body: { case_id: "case-1" }, retryUnauthorized: false,
    });
  });

  it("passes the explicitly selected SOP scope and required lookup to the API", async () => {
    vi.mocked(apiFetch).mockResolvedValue(response);
    const input = { case_id: "case-1", workspace_id: "workspace-1", require_knowledge: true };
    await investigateCase("org-1", input);
    expect(apiFetch).toHaveBeenCalledWith("/organizations/org-1/investigations", {
      method: "POST", body: input, retryUnauthorized: false,
    });
  });

  it("shows waiting, blocks a duplicate submission, then exposes the fixed report", async () => {
    let finish!: (value: InvestigationResponse) => void;
    const request = vi.fn(() => new Promise<InvestigationResponse>((resolve) => { finish = resolve; }));
    const states: InvestigationViewState[] = [];
    const runner = createInvestigationRunner((state) => states.push(state), request);
    const first = runner.submit("org-1", { case_id: "case-1" });
    expect(runner.pending).toBe(true);
    expect(states).toEqual([{ status: "pending" }]);
    await expect(runner.submit("org-1", { case_id: "case-1" })).resolves.toBe(false);
    expect(request).toHaveBeenCalledOnce();
    finish(response);
    await first;
    expect(runner.pending).toBe(false);
    expect(states.at(-1)).toEqual({ status: "success", result: response });
  });

  it("keeps business not_found as a completed report", async () => {
    const notFound: InvestigationResponse = {
      ...response, report: { ...response.report, outcome: "not_found" },
    };
    const states: InvestigationViewState[] = [];
    await createInvestigationRunner((state) => states.push(state), async () => notFound)
      .submit("org-1", { case_id: "case-1" });
    expect(states.at(-1)).toEqual({ status: "success", result: notFound });
  });

  it.each([
    [new ApiError(401, "authentication_error", "internal"), "未登录"],
    [new ApiError(403, "permission_denied", "internal"), "无权"],
    [new ApiError(422, "validation_error", "internal"), "输入无效"],
    [new ApiError(502, "tool_failed", "secret trace"), "调查执行失败"],
    [new TypeError("network details"), "网络连接失败"],
  ])("maps failures to a safe non-business error state", async (error, expected) => {
    const states: InvestigationViewState[] = [];
    await createInvestigationRunner((state) => states.push(state), async () => { throw error; })
      .submit("org-1", { case_id: "case-1" });
    expect(states.at(-1)).toEqual({ status: "error", message: investigationErrorMessage(error) });
    expect(investigationErrorMessage(error)).toContain(expected);
    expect(investigationErrorMessage(error)).not.toContain("internal");
    expect(investigationErrorMessage(error)).not.toContain("trace");
  });
});
