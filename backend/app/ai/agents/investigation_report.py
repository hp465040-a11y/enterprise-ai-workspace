"""Model selects outcome/citations; Python validates and renders business facts."""
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class EvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["observed_delay", "no_observed_delay", "insufficient_evidence", "not_found", "invalid_input"]
    evidence_event_ids: list[UUID]
    root_cause: Literal["unknown", "inventory_allocation_blocked"]
    knowledge_source_ids: list[UUID] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def serialize_report(self, handler):
        # Preserve the original three-field response for reports without knowledge citations.
        result = handler(self)
        if not self.knowledge_source_ids:
            result.pop("knowledge_source_ids", None)
        return result


def knowledge_sources(trace: list[dict]) -> dict[str, dict]:
    """Only successful, current-run retrieval observations are citable."""
    return {str(UUID(str(source["chunk_id"]))): source for step in trace
            if step["tool"] == "search_knowledge" and step["result"]["status"] == "found"
            for source in step["result"]["sources"]}


def evidence_contract(trace: list[dict]) -> dict:
    analyses = [s["result"]["analysis"] for s in trace
                if s["tool"] == "analyze_fulfillment" and s["result"]["status"] == "found"]
    events = set()
    for step in trace:
        result = step["result"]
        if result["status"] != "found":
            continue
        if step["tool"] == "analyze_fulfillment":
            events.update(result["analysis"].get("evidence_event_ids", []))
        elif step["tool"] == "get_fulfillment_events":
            events.update(e["event_id"] for e in result["events"])
    business_trace = [s for s in trace if s["tool"] != "search_knowledge"]
    terminal = business_trace[-1]["result"]["status"] if business_trace else None
    if terminal in ("not_found", "invalid_input"):
        outcome = terminal
    elif analyses:
        statuses = [analyses[-1].get(k, {}).get("status", "unknown") for k in ("shipment", "delivery")]
        outcome = ("observed_delay" if "late" in statuses else
                   "no_observed_delay" if statuses == ["on_time", "on_time"] else "insufficient_evidence")
    else:
        outcome = "insufficient_evidence"
    allocation = analyses[-1].get("allocation", {}) if analyses else {}
    linked_ids = {str(allocation.get("attribution_event_id")),
                  str(allocation.get("linked_failure_event_id"))}
    linked = (allocation.get("status") == "blocked"
              and allocation.get("causal_status") == "linked_to_shipment_delay"
              and None not in (allocation.get("attribution_event_id"),
                               allocation.get("linked_failure_event_id"))
              and str(allocation.get("linked_failure_event_id")) in {
                  str(event) for event in allocation.get("failure_event_ids", [])}
              and allocation.get("attribution_event_id") != allocation.get("linked_failure_event_id")
              and linked_ids <= {str(event) for event in events}
              and analyses[-1].get("shipment", {}).get("status") == "late"
              and outcome == "observed_delay")
    contract = {"outcome": outcome, "evidence_event_ids": sorted(events),
                "root_cause": "inventory_allocation_blocked" if linked else "unknown"}
    if any(s["tool"] == "search_knowledge" for s in trace):
        contract["knowledge_source_ids"] = sorted(knowledge_sources(trace))
    return contract


def validate_report(content: str, trace: list[dict]) -> EvidenceReport:
    report = EvidenceReport.model_validate_json(content)
    expected = evidence_contract(trace)
    identifiers = [str(value) for value in report.evidence_event_ids]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(expected["evidence_event_ids"]):
        raise ValueError("Missing, duplicate or invented event citations")
    if report.outcome != expected["outcome"]:
        raise ValueError("Outcome contradicts observations")
    if report.root_cause != expected["root_cause"]:
        raise ValueError("Root cause contradicts linked order evidence")
    knowledge_ids = [str(value) for value in report.knowledge_source_ids]
    if len(knowledge_ids) != len(set(knowledge_ids)) or not set(knowledge_ids) <= knowledge_sources(trace).keys():
        raise ValueError("Duplicate or unobserved knowledge citations")
    return report


def render_report(report: EvidenceReport, trace: list[dict]) -> str:
    """Render a validated report and its trace without new reads or model calls."""
    facts = [f"报告结论（Outcome: {report.outcome}）"]
    evidence = ["事件引用：" + (", ".join(str(v) for v in report.evidence_event_ids) or "无已观察事件引用")]
    unknowns = ["整单完成情况未知；发货/送达时间比较不证明整单履约正常或完成。"]
    if report.root_cause == "unknown":
        unknowns.insert(0, "本次延迟根因未确认（Root cause: unknown）。")
    else:
        unknowns.insert(0, "该运单发货延迟有订单级库存分配受阻关联记录；送达及整单其他原因未确认。")
    gaps = []
    case_status = "未提供"

    def shown(value):
        return "未提供" if value is None or value == "" else str(value)

    def gap(missing, suggestion):
        gaps.append((missing, suggestion))

    for step in trace:
        result = step["result"]
        tool = step["tool"]
        if tool == "search_knowledge":
            evidence.append(f"知识检索状态：{result['status']}（与业务读取状态分开）。")
            if result["status"] == "no_matches":
                gap("本次授权范围内未检索到匹配的 SOP/处理规则。",
                    "核对检索问题和授权工作区内相关规则资料；无匹配不表示规则不存在。")
            continue  # Reference text must never become a business fact or timing observation.
        if result["status"] != "found":
            facts.append(f"读取结果 {tool}：{result['status']}；不是履约正常的证明。")
            if result["status"] == "not_found":
                gap(f"{tool}：可匹配记录未提供（not_found）。",
                    "核对本次查询标识与授权范围内的对应记录；不能据此判定业务未发生。")
            elif result["status"] == "invalid_input":
                gap(f"{tool}：有效查询参数未提供。", "按工具参数要求核对并补充有效参数。")
            else:
                unknowns.append(f"{tool} 未成功读取，不能据此得出业务结论。")
        elif tool == "get_exception_case":
            case = result.get("case") or {}
            case_status = shown(case.get("status"))
            facts.append(f"已读取案件：{shown(case.get('id'))}；关联订单：{shown(case.get('order_id'))}。")
        elif tool == "analyze_fulfillment":
            analysis = result["analysis"]
            cutoff = analysis.get("as_of")
            evidence.append(f"分析时点 as_of（观察截止，非事件发生时间）：{shown(cutoff)}。")
            if cutoff is None:
                gap("分析观察截止时间未提供。", "补充本次分析实际使用的 as_of，不以当前时间代替。")
            if not analysis.get("evidence_event_ids"):
                unknowns.append("分析未提供事件引用；不能据此断言实际没有发货或送达。")
            allocation = analysis.get("allocation") or {}
            if allocation.get("status") == "blocked":
                facts.append("该订单有明确的库存分配失败记录；这项事实本身不证明延迟原因。")
                for failure in allocation.get("failures", []):
                    evidence.append(
                        f"分配失败事件 {shown(failure.get('event_id'))}：发生时间 "
                        f"{shown(failure.get('occurred_at'))}；来源 {shown(failure.get('source'))}；"
                        f"来源记录号 {shown(failure.get('external_event_id'))}；"
                        f"运单 {shown(failure.get('tracking_number'))}。"
                    )
                if report.root_cause == "inventory_allocation_blocked":
                    facts.append("结构化关联记录确认该运单发货延迟与库存分配受阻有关。")
                    evidence.append(
                        f"延迟关联事件 {shown(allocation.get('attribution_event_id'))} "
                        f"明确关联分配失败事件 {shown(allocation.get('linked_failure_event_id'))}。"
                    )
                else:
                    unknowns.append("分配失败已记录，但缺少满足订单、运单与时间边界的明确延迟关联；因果仍未知。")
                    gap("该运单发货延迟与已记录分配失败之间的明确关联资料未提供。",
                        "核对分配系统与履约系统的同运单关联记录及事件时间。")
            for kind, label in (("shipment", "发货"), ("delivery", "送达")):
                comparison = analysis.get(kind, {})
                status = comparison.get("status")
                description = {"on_time": "该时间比较未观察到延迟", "late": "该时间比较观察到延迟"}.get(
                    status, "尚不能判断是否延迟")
                facts.append(f"{label}：{description}；比较范围：{shown(comparison.get('scope'))}；"
                             f"跟踪号：{shown(comparison.get('tracking_number'))}。")
                evidence.append(f"{label}业务时间：承诺截止 {shown(comparison.get('expected_at'))}；"
                                f"实际完成 {shown(comparison.get('actual_at'))}。")
                evidence.append(f"{label}比较原始字段（null 表示未提供）：" + json.dumps({k: comparison.get(k) for k in (
                    "status", "reason", "scope", "tracking_number", "expected_at", "actual_at",
                    "difference_seconds", "promise_event_id", "actual_event_id",
                )}, ensure_ascii=False))
                if status not in ("on_time", "late"):
                    unknowns.append(f"{label}时间比较不能确认；原因字段：{shown(comparison.get('reason'))}。")
                for field, name in (("expected_at", "承诺截止时间"), ("actual_at", "实际完成时间")):
                    if comparison.get(field) is None:
                        gap(f"{label}：可比较的{name}未提供。",
                            f"补充与本次订单、比较范围及观察截止相符的{label}{name}记录及来源，以便核实时间比较。")
        elif tool == "get_inventory_status":
            inventory = result["inventory"]
            facts.append(f"组织/SKU 库存快照：SKU={shown(inventory.get('sku'))}；"
                         f"可用数量={shown(inventory.get('available_quantity'))}。")
            evidence.append(f"库存观察时间 observed_at（非事件时间或分析时点）：{shown(inventory.get('observed_at'))}。")
            evidence.append("库存原始字段（null 表示未提供）：" + json.dumps(inventory, ensure_ascii=False))
            unknowns.append("库存快照及负可用数量仅反映组织/SKU 的快照差额，不能证明本订单缺货、预留情况或异常根因。")
            for field, name in (("sku", "SKU"), ("available_quantity", "可用数量"), ("observed_at", "观察时间")):
                if inventory.get(field) is None:
                    gap(f"库存快照{name}未提供。", f"补充该库存快照的{name}及来源，不从订单或跟踪号猜测。")
        elif tool == "get_fulfillment_events":
            events = result["events"]
            if not events:
                facts.append("履约事件查询返回空列表；仅表示本次查询没有事件记录。")
                unknowns.append("空事件列表不能证明业务未发生或履约正常。")
            for event in events:
                evidence.append(f"事件 {shown(event.get('event_id'))}：发生时间 occurred_at="
                                f"{shown(event.get('occurred_at'))}；类型={shown(event.get('event_type'))}；"
                                f"来源={shown(event.get('source'))}。")
                if event.get("occurred_at") is None:
                    gap(f"事件 {shown(event.get('event_id'))} 的发生时间未提供。", "补充该事件的原始发生时间及来源记录。")
                if event.get("description"):
                    evidence.append("来源描述（未核实的来源陈述，不是因果结论）：" + event["description"])

    if len(evidence) == 1:
        evidence.append("事件发生时间、库存观察时间和分析时点：未提供。")
    if any(s["tool"] == "search_knowledge" for s in trace):
        sources = knowledge_sources(trace)
        for identifier in report.knowledge_source_ids:
            evidence.append("知识参考（非业务事实）：" + json.dumps(sources[str(identifier)], ensure_ascii=False))
        if not report.knowledge_source_ids:
            evidence.append("知识引用：未引用。")
        unknowns.append("知识引用仅校验来源确在本次成功检索中；未验证片段是否支持建议，不据此确定异常根因。")
    sections = [
        ("1. 已确认事实", facts),
        ("2. 证据引用及观察时间", evidence),
        ("3. 不能确认的事项", unknowns),
        ("4. 缺少的资料", [f"G{i}：{missing}" for i, (missing, _) in enumerate(gaps, 1)]
         or ["现有输出未识别到上述字段的具体资料缺口；不表示所有调查资料齐全。"]),
        ("5. 与资料缺口逐项对应的下一步建议",
         [f"G{i}（建议，尚未执行）：{suggestion}" for i, (_, suggestion) in enumerate(gaps, 1)]
         or ["暂无与具体资料缺口对应的建议；不自动创建后续任务。"]),
        ("6. 处理状态", [f"案件记录状态：{case_status}（仅转述读取值，本次未变更）。",
                       "本次已校验报告已生成只读交接单；不代表案件已关闭或交接已送达。",
                       "本次未通知、未分派、未执行处置；不会自动继续调查。"]),
    ]
    return "\n\n".join(title + "\n" + "\n".join(f"- {line}" for line in lines) for title, lines in sections)
