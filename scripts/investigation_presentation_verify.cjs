// Offline replay of the retained HTTP response and analysis observation; no API or model calls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const vm = require("node:vm");
const ts = require("../frontend/node_modules/typescript");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "frontend/src/lib/investigation-presentation.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleScope = { exports: {} };
vm.runInNewContext(compiled, { module: moduleScope, exports: moduleScope.exports, Intl, Date, Number, Math });
const { investigationPresentation, beijingTime } = moduleScope.exports;

const evidence = JSON.parse(fs.readFileSync(path.join(root,
  "scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json"), "utf8"));
const analysis = evidence.trace.find((step) => step.tool === "analyze_fulfillment").result.analysis;
const response = {
  request_id: evidence.request_id, organization_id: evidence.organization_id,
  case_id: evidence.case_id, as_of: analysis.as_of, report: evidence.report,
  handoff: evidence.handoff,
  observations: {
    whole_order_completion: analysis.whole_order_completion,
    shipment: analysis.shipment, delivery: analysis.delivery,
  },
};
const view = investigationPresentation(response);
assert.ok(view.headline.includes("1 \u5c0f\u65f6"));
assert.ok(view.headline.includes("\u53d1\u8d27") && view.headline.includes("\u9001\u8fbe"));
assert.ok(view.headline.includes("\u65e9") && view.headline.includes("\u665a"));
assert.equal(view.wholeOrder, "\u6574\u5355\u5b8c\u6210\u60c5\u51b5\u672a\u77e5");
assert.ok(view.causeGap.includes("\u539f\u56e0\u8bf4\u660e"));
assert.equal(view.sections.length, 6);
assert.ok(view.sections.every((section) => !section[1].includes(evidence.report.evidence_event_ids[0])));
assert.ok(beijingTime(analysis.shipment.expected_at).includes("\u5317\u4eac\u65f6\u95f4"));
const withoutAnalysis = investigationPresentation({ ...response, observations: null });
assert.ok(withoutAnalysis.headline.includes("\u672a\u63d0\u4f9b"));
assert.ok(!withoutAnalysis.headline.includes("1 \u5c0f\u65f6"));
const blocked = investigationPresentation({ ...response, observations: {
  ...response.observations,
  allocation: { status: "blocked", causal_status: "unknown", failure_event_ids: [
    evidence.report.evidence_event_ids[0],
  ], attribution_event_id: null, linked_failure_event_id: null },
} });
assert.ok(blocked.allocationFact.includes("\u5e93\u5b58\u5206\u914d\u53d7\u963b"));
assert.ok(blocked.causeSummary.includes("\u6839\u56e0\u672a\u77e5"));
assert.ok(blocked.causeGap.includes("\u4e0d\u80fd\u636e\u6b64\u5f52\u56e0"));
const linked = investigationPresentation({ ...response,
  report: { ...response.report, root_cause: "inventory_allocation_blocked" },
  observations: { ...response.observations, allocation: {
    status: "blocked", causal_status: "linked_to_shipment_delay",
    failure_event_ids: [evidence.report.evidence_event_ids[0]],
    attribution_event_id: evidence.report.evidence_event_ids[1],
    linked_failure_event_id: evidence.report.evidence_event_ids[0],
  } },
});
assert.ok(linked.causeSummary.includes("\u6709\u8ba2\u5355\u7ea7\u5e93\u5b58\u5206\u914d\u53d7\u963b\u5173\u8054\u8bb0\u5f55"));
assert.ok(linked.sections[0][1].includes("\u6709\u660e\u786e\u5ef6\u8fdf\u5173\u8054"));
console.log("presentation replay passed: timing, cause gap, six sections, hidden IDs, no-analysis fallback");

if (process.argv.includes("--preview")) {
  const allocationStage = process.argv.includes("--allocation-stage-preview");
  const allocationApi = process.argv.includes("--allocation-api-preview");
  assert.ok(!(allocationStage && allocationApi));
  let previewResponse = response;
  let previewLabel = "2026-10-19 已保存真实结果的历史回放";
  if (allocationStage) {
    const stage = JSON.parse(fs.readFileSync(path.join(root,
      "scripts/investigation_allocation_report_stage_short_refs_20261021.json"), "utf8"));
    const original = JSON.parse(fs.readFileSync(path.join(root,
      "scripts/investigation_allocation_run_20261020T200910720967Z_e78899e0.json"), "utf8"));
    assert.equal(stage.status, "validated_report");
    const observed = original.trace.find((step) => step.tool === "analyze_fulfillment").result.analysis;
    previewResponse = { request_id: stage.source_request_id,
      organization_id: original.organization_id, case_id: original.case_id, as_of: original.as_of,
      report: stage.report, handoff: stage.rendered_report,
      observations: { whole_order_completion: observed.whole_order_completion,
        shipment: observed.shipment, delivery: observed.delivery, allocation: observed.allocation },
    };
    previewLabel = "保存真实观察的报告阶段回放；完整 Graph/API 与浏览器验收尚未完成";
  } else if (allocationApi) {
    const run = JSON.parse(fs.readFileSync(path.join(root,
      "scripts/investigation_allocation_run_http_short_refs_20261021.json"), "utf8"));
    assert.equal(run.status, "completed");
    assert.equal(run.http_status, 200);
    previewResponse = run.response;
    previewLabel = "已保存的完整 Graph/API 响应回放；不代表浏览器交互验收";
  }
  const previewView = investigationPresentation(previewResponse);
  assert.equal(previewView.sections.length, 6);
  assert.equal(previewResponse.report.evidence_event_ids.length,
    allocationStage || allocationApi ? 6 : 4);
  if (allocationStage || allocationApi) {
    assert.ok(previewView.headline.includes("发货比承诺晚 1 小时"));
    assert.ok(previewView.headline.includes("送达比承诺早 1 小时"));
    assert.ok(previewView.causeSummary.includes("订单级库存分配受阻关联记录"));
    assert.ok(previewView.causeGap.includes("未列出具体资料缺口"));
    assert.ok(previewView.causeGap.includes("不表示资料齐全"));
  }
  if (allocationApi) {
    const page = fs.readFileSync(path.join(root, "frontend/src/app/(dashboard)/investigations/page.tsx"), "utf8");
    assert.match(page, /<summary[^>]*>六部分交接单<\/summary>/);
    assert.match(page, /<summary[^>]*>技术证据<\/summary>/);
    assert.match(page, /<summary[^>]*>查看完整原文<\/summary>/);
    assert.match(page, /<summary[^>]*>查看完整标识、JSON 与 SOP 原文<\/summary>/);
    assert.equal((page.match(/<details\b/g) || []).length, 4);
    assert.ok(!/<details\b[^>]*\bopen(?:=|\s|>)/.test(page));
    assert.equal((page.match(/translate="no"/g) || []).length, 3);
    assert.ok(page.indexOf("六部分交接单</summary>") < page.indexOf("技术证据</summary>"));
    assert.match(page, /presentation\.sections\.map/);
    assert.match(page, /presentation\.sourceSummary/);
    assert.ok((page.match(/max-h-64/g) || []).length >= 3);
    assert.equal(previewResponse.report.evidence_event_ids.length, 6);
    assert.equal(previewResponse.report.knowledge_source_ids?.length, 1);
    assert.ok(previewView.sourceSummary.includes("库存分配失败")
      && previewView.sourceSummary.includes("延迟关联"));
    assert.ok(previewView.sections[2][1].includes("整单其他原因")
      && previewView.sections[5][1].includes("未发送通知"));
    assert.ok(previewView.sections.every((section) =>
      !previewResponse.report.evidence_event_ids.some((id) => section[1].includes(id))));
    assert.ok(previewResponse.handoff.includes("1.") && previewResponse.handoff.includes("6."));
    const React = require("../frontend/node_modules/react");
    const { renderToStaticMarkup } = require("../frontend/node_modules/react-dom/server");
    const wrapper = (tag) => (props) => React.createElement(tag, props, props.children);
    const components = { Button: wrapper("button"), Card: wrapper("div"), CardContent: wrapper("div"),
      CardDescription: wrapper("div"), CardHeader: wrapper("div"), CardTitle: wrapper("div") };
    const compiledPage = ts.transpileModule(page, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    let stateValues = [];
    let stateIndex = 0;
    const reactHooks = { ...React, useState: (initial) => [stateValues[stateIndex++] ?? initial, () => {}],
      useRef: (initial) => ({ current: initial }), useEffect: () => {} };
    const pageModule = { exports: {} };
    const imports = {
      "react": reactHooks,
      "react/jsx-runtime": require("../frontend/node_modules/react/jsx-runtime"),
      "@/components/ui/button": { Button: components.Button },
      "@/components/ui/card": components,
      "@/components/ui/input": { Input: wrapper("input") },
      "@/components/ui/label": { Label: wrapper("label") },
      "@/hooks/use-organizations": { useOrganizations: () => ({ data: [{
        id: previewResponse.organization_id, name: "演示企业" }], isLoading: false }) },
      "@/hooks/use-workspaces": { useWorkspaces: () => ({ data: [], isLoading: false }) },
      "@/lib/api/investigations": { createInvestigationRunner: () => {}, investigateCase: () => {} },
      "@/lib/investigation-presentation": { beijingTime, investigationPresentation },
      "@/lib/investigation-replay-diagnostics": { isLocalInvestigationReplay: () => false,
        newReplayComponent: () => 0, newReplaySubmission: () => 0, replayTrace: () => {} },
      "@/store/workspace-store": { useWorkspaceStore: (select) => select({
        organizationId: previewResponse.organization_id }) },
    };
    vm.runInNewContext(compiledPage, { module: pageModule, exports: pageModule.exports,
      require: (name) => {
        assert.ok(Object.hasOwn(imports, name), `unexpected page import: ${name}`);
        return imports[name];
      }, console });
    const renderState = (viewState) => {
      stateValues = ["", "", "", false, viewState, "", false];
      stateIndex = 0;
      return renderToStaticMarkup(React.createElement(pageModule.exports.default));
    };
    const pendingMarkup = renderState({ status: "pending" });
    const successMarkup = renderState({ status: "success", result: previewResponse });
    const errorMarkup = renderState({ status: "error", message: "保存响应回放失败" });
    const submitButton = (markup) => markup.match(/<button[^>]*data-investigation-submit[^>]*>[^<]*<\/button>/)?.[0];
    assert.match(submitButton(pendingMarkup), /disabled=""/);
    assert.match(submitButton(pendingMarkup), /调查中…/);
    assert.ok(!pendingMarkup.includes("data-investigation-report"));
    for (const markup of [successMarkup, errorMarkup]) {
      assert.match(submitButton(markup), /生成只读交接单/);
      assert.ok(!submitButton(markup).includes("disabled="));
      assert.match(submitButton(markup), /translate="no"/);
    }
    assert.ok(successMarkup.includes("data-investigation-report"));
    assert.ok(!successMarkup.includes("data-investigation-pending"));
    assert.ok(!errorMarkup.includes("data-investigation-report"));
    assert.match(page, /key=\{pending \? "pending" : "ready"\}/);
    console.log("saved-response React page render passed: pending, success, error submit button and report state");
    const runnerSource = fs.readFileSync(path.join(root, "frontend/src/lib/api/investigations.ts"), "utf8");
    const runnerModule = { exports: {} };
    vm.runInNewContext(ts.transpileModule(runnerSource, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText, { module: runnerModule, exports: runnerModule.exports,
      require: () => ({ ApiError: class ApiError extends Error {}, apiFetch: () => {} }),
      setTimeout, clearTimeout });
    const stateWrites = [];
    const runner = runnerModule.exports.createInvestigationRunner(
      (state) => stateWrites.push(state), async () => previewResponse, 1000,
    );
    runner.submit(previewResponse.organization_id, { case_id: previewResponse.case_id })
      .then(async () => {
        assert.deepEqual(stateWrites.map((state) => state.status), ["pending", "success"]);
        assert.equal(runner.pending, false);
        await new Promise((resolve) => setTimeout(resolve, 40));
        assert.deepEqual(stateWrites.map((state) => state.status), ["pending", "success"]);
        const stableMarkup = renderState(stateWrites.at(-1));
        assert.ok(stableMarkup.includes("data-investigation-report"));
        assert.match(submitButton(stableMarkup), /生成只读交接单/);
        assert.ok(!submitButton(stableMarkup).includes("disabled="));
        console.log("saved-response settled state stayed success with an enabled submit button");
      }).catch((error) => { console.error(error); process.exitCode = 1; });
    console.log("saved allocation response and React layout contract passed");
  }
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const rows = (["shipment", "delivery"]).map((kind) => {
    const timing = previewResponse.observations[kind];
    return `<section class="time"><h3>${kind === "shipment" ? "发货时间" : "送达时间"}</h3>
      <p>承诺：${escape(beijingTime(timing?.expected_at))}</p>
      <p>实际：${escape(beijingTime(timing?.actual_at))}</p></section>`;
  }).join("");
  const sections = previewView.sections.map(([title, content]) =>
    `<section><h3>${escape(title)}</h3><p>${escape(content)}</p></section>`).join("");
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
    <title>Project A 保存报告本地回放</title><style>
    body{font:16px/1.7 system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#17212c;background:#f7f9fb}
    .card{background:white;border:1px solid #d8e0e8;border-radius:12px;padding:20px;margin:16px 0}
    .notice{background:#fff3d4;padding:12px;border-radius:8px}.lead{font-size:1.1rem;font-weight:600}
    .times{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
    .time{border:1px solid #d8e0e8;border-radius:8px;padding:12px}h3{margin-bottom:4px}
    p{margin:6px 0 12px}button{cursor:pointer;padding:6px 12px;margin-left:8px}
    summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:16rem;overflow-y:auto}
    code{overflow-wrap:anywhere}
    </style></head><body>
    <h1>订单履约异常调查 · 保存报告回放</h1>
    <p class="notice">${escape(previewLabel)}。此文件不调用调查 API、模型或数据库。</p>
    <article class="card"><h2>调查结论：${escape(previewView.outcome)}</h2>
    <p>请求标识：${escape(previewResponse.request_id.slice(0, 8))}… <button id="copy" type="button">复制完整标识</button><span id="copy-status" role="status"></span></p>
    <div class="card"><p class="lead">${escape(previewView.headline)}</p>
    <p>${escape(previewView.causeSummary)}；${escape(previewView.wholeOrder)}；本次未执行处置。</p><p>${escape(previewView.causeGap)}</p></div>
    <div class="times">${rows}</div>
    <details class="card" translate="no"><summary>六部分交接单</summary>
    ${sections}<details class="card"><summary>查看完整原文</summary><pre>${escape(previewResponse.handoff)}</pre></details></details>
    <details class="card" translate="no"><summary>技术证据</summary>
    <p>${previewResponse.report.evidence_event_ids.length} 条业务事件、${previewResponse.report.knowledge_source_ids?.length ?? 0} 条 SOP 来源</p>
    <p>${escape(previewView.sourceSummary)}</p>
    <details class="card"><summary>查看完整标识、JSON 与 SOP 原文</summary>
    <p>完整请求标识：<code id="request-id">${escape(previewResponse.request_id)}</code></p>
    <p>业务事件 ID：${escape(previewResponse.report.evidence_event_ids.join("、") || "无")}</p>
    <p>SOP 来源 ID：${escape(previewResponse.report.knowledge_source_ids?.join("、") || "无")}</p>
    <h3>原始结构化报告</h3><pre>${escape(JSON.stringify(previewResponse.report, null, 2))}</pre>
    <h3>完整交接原文（含 SOP 检索内容）</h3><pre>${escape(previewResponse.handoff)}</pre></details>
    </details></article><script>
    document.getElementById('copy').addEventListener('click', async () => {
      const text = document.getElementById('request-id').textContent;
      const status = document.getElementById('copy-status');
      try {
        if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
        await navigator.clipboard.writeText(text);
        status.textContent = '请求标识已复制';
      } catch {
        const input = document.createElement('textarea');
        input.value = text; document.body.appendChild(input); input.select();
        const copied = document.execCommand('copy'); input.remove();
        status.textContent = copied ? '请求标识已复制' : '复制失败；请展开证据详情手动复制';
      }
    });
    </script></body></html>`;
  const output = path.join(os.tmpdir(), allocationStage || allocationApi
    ? "project-a-allocation-saved-report-preview.html"
    : "project-a-investigation-saved-report-preview.html");
  fs.writeFileSync(output, html, { encoding: "utf8", mode: 0o600 });
  console.log(`Local preview: ${pathToFileURL(output).href}`);
}
