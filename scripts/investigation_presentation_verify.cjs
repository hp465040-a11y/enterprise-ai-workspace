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
console.log("presentation replay passed: timing, cause gap, six sections, hidden IDs, no-analysis fallback");

if (process.argv.includes("--preview")) {
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const rows = (["shipment", "delivery"]).map((kind) => {
    const timing = response.observations[kind];
    return `<section class="time"><h3>${kind === "shipment" ? "发货时间" : "送达时间"}</h3>
      <p>承诺：${escape(beijingTime(timing?.expected_at))}</p>
      <p>实际：${escape(beijingTime(timing?.actual_at))}</p></section>`;
  }).join("");
  const sections = view.sections.map(([title, content]) =>
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
    summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere}
    code{overflow-wrap:anywhere}
    </style></head><body>
    <h1>订单履约异常调查 · 保存报告回放</h1>
    <p class="notice">这是 2026-10-19 已保存真实结果的本地展示回放，不是新增模型验收。此文件不调用调查 API、模型或数据库。</p>
    <article class="card"><h2>调查结论：${escape(view.outcome)}</h2>
    <p>请求标识：${escape(response.request_id.slice(0, 8))}… <button id="copy" type="button">复制完整标识</button><span id="copy-status" role="status"></span></p>
    <div class="card"><p class="lead">${escape(view.headline)}</p>
    <p>根因未知；${escape(view.wholeOrder)}；本次未执行处置。</p><p>${escape(view.causeGap)}</p></div>
    <div class="times">${rows}</div><h2>六部分交接单</h2>${sections}
    <details class="card"><summary>证据详情（原始报告与完整交接单）</summary>
    <p>完整请求标识：<code id="request-id">${escape(response.request_id)}</code></p>
    <p>业务事件 ID：${escape(response.report.evidence_event_ids.join("、") || "无")}</p>
    <p>SOP 来源 ID：${escape(response.report.knowledge_source_ids?.join("、") || "无")}</p>
    <h3>原始结构化报告</h3><pre>${escape(JSON.stringify(response.report, null, 2))}</pre>
    <h3>完整六部分交接单（含原始来源内容）</h3><pre>${escape(response.handoff)}</pre>
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
  const output = path.join(os.tmpdir(), "project-a-investigation-saved-report-preview.html");
  fs.writeFileSync(output, html, { encoding: "utf8", mode: 0o600 });
  console.log(`Local preview: ${pathToFileURL(output).href}`);
}
