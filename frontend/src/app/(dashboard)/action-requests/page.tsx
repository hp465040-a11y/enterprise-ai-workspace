"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useOrganizations } from "@/hooks/use-organizations";
import { useOrganizationMembers } from "@/hooks/use-organization-members";
import {
  actionErrorMessage, createActionRequest, executeActionRequest, getActionNotification,
  listActionRequests, reviewActionRequest,
  type ActionRequestRecord,
  type CustomerNotificationRecord,
} from "@/lib/api/action-requests";
import {
  applyExecutionResult, applyReviewResult, executionTime, formatBeijingTime,
  locateNotificationCard, notificationKey, notificationMatches, requestActions,
  resolveNotification, reviewDetails, statusText, upsertRequest,
} from "@/lib/action-request-state";
import { useAuthStore } from "@/store/auth-store";
import { useWorkspaceStore } from "@/store/workspace-store";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function ActionRequestsPage() {
  const organizationId = useWorkspaceStore((state) => state.organizationId);
  const user = useAuthStore((state) => state.user);
  const { data: organizations } = useOrganizations();
  const organization = organizations?.find((item) => item.id === organizationId);
  const { data: members, isLoading: membershipLoading } = useOrganizationMembers(organizationId ?? "");
  const role = members?.find((member) => member.user_id === user?.id)?.role;
  const canReview = role === "admin" || role === "owner";
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: ["action-requests", organizationId],
    queryFn: () => listActionRequests(organizationId!),
    enabled: !!organizationId,
  });
  const [caseId, setCaseId] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [recentId, setRecentId] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<Record<string, CustomerNotificationRecord>>({});
  const [loadingNotificationKey, setLoadingNotificationKey] = useState<string | null>(null);
  const [focusTarget, setFocusTarget] = useState<{ key: string; sequence: number } | null>(null);
  const [highlightedKey, setHighlightedKey] = useState<string | null>(null);
  const notificationRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const notificationReadPending = useRef(false);
  const focusSequence = useRef(0);
  const createPending = useRef(false);
  const reviewPending = useRef(false);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const recent = requests.data?.find((item) => item.id === recentId);

  useEffect(() => {
    if (!focusTarget || !notifications[focusTarget.key]) return;
    const frame = requestAnimationFrame(() => {
      const card = notificationRefs.current[focusTarget.key];
      if (!card) return;
      locateNotificationCard(card);
      setHighlightedKey(focusTarget.key);
    });
    const timer = setTimeout(() => setHighlightedKey((key) => key === focusTarget.key ? null : key), 2200);
    return () => { cancelAnimationFrame(frame); clearTimeout(timer); };
  }, [focusTarget, notifications]);

  async function reconcileConfirmed(
    orgId: string,
    update: (current: ActionRequestRecord[] | undefined) => ActionRequestRecord[] | undefined,
    failureMessage: string,
  ) {
    const queryKey = ["action-requests", orgId];
    try {
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueryData<ActionRequestRecord[]>(queryKey, update);
      await queryClient.fetchQuery({ queryKey, queryFn: () => listActionRequests(orgId), staleTime: 0 });
    } catch {
      // The POST already committed. A failed list read must never be called an operation failure.
      setWarning(failureMessage);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createPending.current) return;
    if (!organizationId || !role || !UUID_PATTERN.test(caseId.trim()) || !message.trim()) {
      setError("请选择有权限的企业，并填写有效案件 ID 和通知内容。");
      return;
    }
    const input = { target_case_id: caseId.trim(), message: message.trim() };
    const fingerprint = JSON.stringify([organizationId, user?.id, input.target_case_id, input.message]);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, key: crypto.randomUUID() };
    const idempotencyKey = retry.current.key;
    createPending.current = true;
    setSubmitting(true);
    setError("");
    setWarning("");
    try {
      const created = await createActionRequest(organizationId, { ...input, idempotency_key: idempotencyKey });
      setRecentId(created.id);
      await reconcileConfirmed(organizationId, (current) => upsertRequest(current, created),
        "申请已创建，但列表刷新失败；页面显示的是提交响应，请稍后刷新核对。");
    } catch (cause) {
      setError(actionErrorMessage(cause));
    } finally {
      createPending.current = false;
      setSubmitting(false);
    }
  }

  async function review(requestId: string, decision: "approved" | "rejected") {
    if (!organizationId || !canReview || reviewPending.current) return;
    reviewPending.current = true;
    setReviewingId(requestId);
    setError("");
    setWarning("");
    try {
      const reviewed = await reviewActionRequest(organizationId, requestId, decision);
      await reconcileConfirmed(organizationId, (current) => applyReviewResult(current, reviewed),
        "审核已提交成功，但列表刷新失败；页面显示的是审核响应，请稍后刷新核对。");
    } catch (cause) {
      setError(actionErrorMessage(cause));
    } finally {
      reviewPending.current = false;
      setReviewingId(null);
    }
  }

  async function execute(requestId: string) {
    if (!organizationId || !canReview || reviewPending.current) return;
    reviewPending.current = true;
    setReviewingId(requestId);
    setError("");
    setWarning("");
    try {
      const record = await executeActionRequest(organizationId, requestId);
      if (notificationMatches(record, organizationId, requestId)) {
        setNotifications((current) => ({ ...current, [notificationKey(organizationId, requestId)]: record }));
      }
      await reconcileConfirmed(organizationId, (current) => applyExecutionResult(current, record),
        "站内通知记录已创建，但列表刷新失败；页面显示的是执行响应，请稍后刷新核对。");
    } catch (cause) {
      setError(actionErrorMessage(cause));
    } finally {
      reviewPending.current = false;
      setReviewingId(null);
    }
  }

  async function showNotification(requestId: string) {
    if (!organizationId || notificationReadPending.current) return;
    const key = notificationKey(organizationId, requestId);
    setError("");
    notificationReadPending.current = true;
    setLoadingNotificationKey(key);
    try {
      const record = await resolveNotification(organizationId, requestId, notifications[key],
        () => getActionNotification(organizationId, requestId));
      if (!record) {
        setError("通知记录与所选申请不一致，无法定位；请刷新后核对。");
        return;
      }
      setNotifications((current) => ({ ...current, [key]: record }));
      setFocusTarget({ key, sequence: ++focusSequence.current });
    } catch (cause) {
      setError(`查看通知记录失败：${actionErrorMessage(cause)}`);
    } finally {
      notificationReadPending.current = false;
      setLoadingNotificationKey(null);
    }
  }

  return <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
    <div>
      <h1 className="text-xl font-semibold">客户通知申请</h1>
      <p className="text-sm text-muted-foreground">当前企业：{organization?.name ?? "正在加载"}。申请、审核和站内执行均不向客户发送通知。</p>
    </div>
    <Card><CardHeader><CardTitle className="text-base">创建处置申请</CardTitle></CardHeader><CardContent>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1"><Label htmlFor="action-case-id">案件 ID</Label>
          <Input id="action-case-id" value={caseId} onChange={(event) => setCaseId(event.target.value)}
            placeholder="当前企业案件 UUID" disabled={submitting} required /></div>
        <div className="space-y-1"><Label htmlFor="action-message">拟发送的客户通知内容</Label>
          <Textarea id="action-message" value={message} onChange={(event) => setMessage(event.target.value)}
            maxLength={1000} disabled={submitting} required /></div>
        <Button type="submit" disabled={submitting || !role || !organizationId}>
          {submitting ? "提交中…" : "提交审核申请"}
        </Button>
      </form>
      {membershipLoading && <p role="status" className="mt-3 text-sm">正在核对企业权限…</p>}
      {role === "member" && <p className="mt-3 text-sm text-muted-foreground">普通成员可以创建申请；批准或拒绝须由本企业 admin/owner 操作。</p>}
    </CardContent></Card>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {warning && <p role="status" className="text-sm text-amber-700">{warning}</p>}
    {recent?.organization_id === organizationId && <p role="status" className="text-sm">
      申请 ID：{recent.id}；实际状态：{statusText(recent.status)}
    </p>}
    <Card><CardHeader><CardTitle className="text-base">本企业申请</CardTitle></CardHeader><CardContent className="space-y-4">
      {requests.isLoading && <p role="status">正在读取申请…</p>}
      {requests.isError && <p role="alert">申请列表读取失败；当前列表可能不是最新状态，请稍后刷新核对。</p>}
      {requests.data?.length === 0 && <p>暂无可见申请。</p>}
      {requests.data?.map((item) => {
        const actions = requestActions(item.status, canReview);
        const reviewInfo = reviewDetails(item);
        const key = notificationKey(organizationId!, item.id);
        const notification = notifications[key];
        return <div key={item.id} className="space-y-2 border-b pb-4 text-sm">
        <p className="break-all font-medium">申请 ID：{item.id}</p>
        <p className="break-all">案件 ID：{item.target_case_id}</p>
        <p>状态：{statusText(item.status)}</p>
        <p>申请创建：{formatBeijingTime(item.created_at)}</p>
        <p>审核决定：{reviewInfo.decision}</p>
        <p>审核时间：{reviewInfo.time}</p>
        <p>执行时间：{executionTime(item)}</p>
        {actions.review && <div className="flex gap-2">
          <Button type="button" disabled={!!reviewingId} onClick={() => void review(item.id, "approved")}>
            {reviewingId === item.id ? "审核中…" : "批准"}
          </Button>
          <Button type="button" variant="outline" disabled={!!reviewingId} onClick={() => void review(item.id, "rejected")}>拒绝</Button>
        </div>}
        {actions.execute && <Button type="button" disabled={!!reviewingId}
          onClick={() => void execute(item.id)}>
          {reviewingId === item.id ? "创建中…" : "创建站内通知记录"}
        </Button>}
        {actions.viewNotification && <Button type="button" variant="outline"
          disabled={!!loadingNotificationKey} onClick={() => void showNotification(item.id)}>
          {loadingNotificationKey === key ? "读取并定位中…" : "查看通知记录"}
        </Button>}
        {notification && <div ref={(element) => { notificationRefs.current[key] = element; }}
          tabIndex={-1} className={`rounded-md outline-none transition-colors duration-700 ${
            highlightedKey === key ? "ring-2 ring-primary bg-primary/5" : ""
          }`}>
          <Card><CardHeader><CardTitle className="text-base">站内通知记录</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p className="break-all">记录 ID：{notification.id}</p>
              <p className="break-all">申请 ID：{notification.action_request_id}</p>
              <p>记录创建：{formatBeijingTime(notification.created_at)}</p>
              <p className="font-medium">记录已创建；本系统未发送，客户收悉未确认。</p>
              <p className="whitespace-pre-wrap break-words">{notification.content}</p>
            </CardContent>
          </Card>
        </div>}
      </div>;
      })}
      {!membershipLoading && !canReview && <p className="text-xs text-muted-foreground">你只能查看自己的申请；审核按钮仅对本企业 admin/owner 显示。</p>}
    </CardContent></Card>
  </div>;
}
