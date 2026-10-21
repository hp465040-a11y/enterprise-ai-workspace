import type { InvestigationResponse, TimingObservation } from "@/lib/api/investigations";

function duration(seconds: number): string {
  const whole = Math.round(Math.abs(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  return [hours && `${hours} 小时`, minutes && `${minutes} 分钟`, remainder && `${remainder} 秒`]
    .filter(Boolean).join(" ") || "0 秒";
}

export function beijingTime(value: string | null | undefined): string {
  if (!value || Number.isNaN(Date.parse(value))) return "未记录";
  return `${new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date(value))}（北京时间）`;
}

function comparison(label: string, value: TimingObservation | null | undefined): string {
  if (!value) return `${label}时间比较未提供`;
  const difference = value.difference_seconds;
  if (value.status === "late") {
    return difference != null && Number.isFinite(difference) && difference > 0
      ? `${label}比承诺晚 ${duration(difference)}` : `${label}观察到延迟，时差未记录`;
  }
  if (value.status === "on_time") {
    if (difference != null && Number.isFinite(difference) && difference < 0) {
      return `${label}比承诺早 ${duration(difference)}`;
    }
    return difference === 0 ? `${label}与承诺时间一致` : `${label}未观察到延迟`;
  }
  return `${label}是否延迟尚不能确认`;
}

export function investigationPresentation(result: InvestigationResponse) {
  const { report, observations } = result;
  const shipment = observations?.shipment;
  const delivery = observations?.delivery;
  const allocation = observations?.allocation;
  const linkedAllocation = report.root_cause === "inventory_allocation_blocked";
  const sameShipment = shipment?.scope === "shipment" && delivery?.scope === "shipment"
    && !!shipment.tracking_number && shipment.tracking_number === delivery.tracking_number;
  const headline = `${sameShipment ? "该运单" : "本次比较"}：${comparison("发货", shipment)}；${comparison("送达", delivery)}。`;
  const outcome = {
    observed_delay: "观察到履约延迟",
    no_observed_delay: "未观察到履约延迟",
    insufficient_evidence: "现有证据不足以判断是否延迟",
    not_found: "未找到可匹配的案件记录",
    invalid_input: "本次查询参数无效",
  }[report.outcome];
  const wholeOrder = observations?.whole_order_completion === "unknown"
    ? "整单完成情况未知" : "整单完成情况未确认";
  const causeGap = allocation?.status === "blocked" && !linkedAllocation
    ? "已记录该订单库存分配受阻，但尚缺与本次发货延迟明确关联的来源记录；不能据此归因。"
    : linkedAllocation
      ? "整单其他原因仍未确认；本次报告未列出具体资料缺口，不表示资料齐全。"
      : shipment?.status === "late" && !shipment.reason
    ? "当前履约分析未提供发货延迟原因说明；时间差不能证明原因。"
    : "当前响应未列出具体原因证据缺口，不表示资料齐全。";
  const causeSummary = linkedAllocation
    ? "该运单发货延迟有订单级库存分配受阻关联记录"
    : "本次延迟根因未知";
  const allocationFact = allocation?.status === "blocked"
    ? `该订单库存分配受阻已记录（${allocation.failure_event_ids.length} 条事件）；${linkedAllocation
      ? "有明确延迟关联" : "尚不能证明导致本次延迟"}。`
    : "";
  const observedSources = [
    shipment && "发货时间",
    delivery && "送达时间",
    allocation?.status === "blocked" && "库存分配失败",
    allocation?.causal_status === "linked_to_shipment_delay" && "延迟关联",
  ].filter(Boolean);
  const sourceSummary = `业务观察：${observedSources.length ? observedSources.join("、") : "未提供结构化观察"}；SOP 来源仅供规则参考，不证明业务事实。`;
  const sections = [
    ["1. 已确认事实", `${outcome}。${headline}${allocationFact}`],
    ["2. 证据引用及观察时间", `业务事件 ${report.evidence_event_ids.length} 条；SOP 来源 ${report.knowledge_source_ids?.length ?? 0} 条（仅作规则参考）。分析时点：${beijingTime(result.as_of)}。`],
    ["3. 不能确认的事项", `${linkedAllocation ? "整单其他原因及是否存在唯一根因未知" : "本次延迟根因未确认"}；${wholeOrder}。`],
    ["4. 缺少的资料", causeGap],
    ["5. 与资料缺口对应的下一步建议", "结构化响应未提供逐项建议；请以原始交接单为准，页面不会自动续查。"],
    ["6. 处理状态", "本次仅生成只读调查报告；未发送通知、未分派或执行处置。"],
  ] as const;
  return { headline, outcome, wholeOrder, causeGap, causeSummary, allocationFact, sourceSummary, sections };
}
