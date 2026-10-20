// Fixed-response browser acceptance. Uses installed Chrome and Next's existing ws.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const WebSocket = require('../frontend/node_modules/next/dist/compiled/ws');

const root = path.resolve(__dirname, '..');
const origin = 'http://127.0.0.1:3107';
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const output = path.join(__dirname, `investigations_browser_${stamp}`);
fs.mkdirSync(output);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'project-a-browser-'));
const evidence = {
  started_at: new Date().toISOString(), scope: 'browser + fixed API responses only',
  origin, timezone: 'Asia/Shanghai', requests: [], checks: [], screenshots: [],
  unexpected_requests: [], passed: false, profile,
  source_sha256: Object.fromEntries([
    'frontend/src/app/(dashboard)/investigations/page.tsx',
    'frontend/src/lib/api/investigations.ts', 'frontend/src/lib/api/client.ts',
  ].map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')])),
  build_id: fs.readFileSync(path.join(root, 'frontend/.next/BUILD_ID'), 'utf8').trim(),
};
const browser = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
  '--disable-component-update', '--disable-sync', 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
evidence.browser_pid = browser.pid;
let ws, seq = 0, active = false;
const pending = new Map();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await sleep(100);
  }
  throw new Error(`UI wait failed: ${expression}`);
}
const org = '22222222-2222-4222-8222-222222222222';
const caseId = '33333333-3333-4333-8333-333333333333';
const headings = ['1. 已确认事实', '2. 证据引用及观察时间', '3. 不能确认的事项',
  '4. 缺少的资料', '5. 与资料缺口逐项对应的下一步建议', '6. 处理状态'];
function report(marker, outcome = 'insufficient_evidence') {
  return { request_id: marker, organization_id: org, case_id: caseId,
    as_of: '2026-10-15T12:00:00Z',
    report: { outcome, evidence_event_ids: [], root_cause: 'unknown' },
    handoff: headings.map((heading, index) => `${heading}\n测试样例 ${marker}：${[
      '仅确认已读取的固定事实。', '事件时间未提供；库存观察时间未提供；分析时点 2026-10-15T12:00:00Z。',
      '无法确认根因或整单履约情况。', 'G1：缺少履约事件资料。',
      'G1：建议补充履约事件，建议，尚未执行。', '未通知、未分派，案件状态未提供。',
    ][index]}`).join('\n\n') };
}
let queued = [], handlerError;
async function fulfill(requestId, status, body) {
  await cdp('Fetch.fulfillRequest', { requestId, responseCode: status,
    responseHeaders: [{ name: 'Content-Type', value: 'application/json; charset=utf-8' },
      { name: 'Access-Control-Allow-Origin', value: '*' },
      { name: 'Access-Control-Allow-Headers', value: 'authorization,content-type' },
      { name: 'Access-Control-Allow-Methods', value: 'GET,POST,OPTIONS' }],
    body: Buffer.from(JSON.stringify(body)).toString('base64') });
}
async function intercept(event) {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) {
    if (event.request.method === 'OPTIONS') return fulfill(event.requestId, 200, {});
    if (url.pathname === '/api/v1/organizations') return fulfill(event.requestId, 200, [
      { id: '11111111-1111-4111-8111-111111111111', name: '测试企业 A', slug: 'a', plan_tier: 'free' },
      { id: org, name: '测试企业 B（当前企业）', slug: 'b', plan_tier: 'free' },
    ]);
    if (url.pathname.endsWith('/workspaces')) return fulfill(event.requestId, 200, []);
    if (url.pathname.endsWith('/investigations')) {
      evidence.requests.push({ method: event.request.method, path: url.pathname,
        body: JSON.parse(event.request.postData),
        authorization_present: Object.keys(event.request.headers).some(key => key.toLowerCase() === 'authorization') });
      queued.push(event.requestId);
      return;
    }
  } else if (url.origin === origin) return cdp('Fetch.continueRequest', { requestId: event.requestId });
  evidence.unexpected_requests.push({ method: event.request.method, origin: url.origin, path: url.pathname });
  await cdp('Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' });
}
async function screenshot(name) {
  const image = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(image.data, 'base64'));
  evidence.screenshots.push(`${name}.png`);
}
async function clickSubmit() {
  const point = await evaluate(`(()=>{const r=document.querySelector('button[type="submit"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  for (const type of ['mousePressed', 'mouseReleased']) await cdp('Input.dispatchMouseEvent', {
    type, ...point, button: 'left', clickCount: 1,
  });
}
async function setInput(id, value) {
  await evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function startRequest() {
  await clickSubmit();
  await waitFor(`document.querySelector('[role="status"]')?.textContent.includes('正在调查')`);
  for (let i = 0; i < 80 && !queued.length; i++) await sleep(100);
  assert.equal(queued.length, 1);
  assert.equal(await evaluate(`!!document.querySelector('pre')`), false);
  return queued.shift();
}
async function seedSuccess(marker) {
  await fulfill(await startRequest(), 200, report(marker));
  await waitFor(`document.querySelector('pre')?.textContent.includes(${JSON.stringify(marker)})`);
}

(async () => {
  try {
    const portFile = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await sleep(100);
    const port = fs.readFileSync(portFile, 'utf8').split('\n')[0];
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    ws = new WebSocket(targets.find(item => item.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.once('open', resolve); ws.once('error', reject); });
    active = true;
    ws.on('message', data => {
      const msg = JSON.parse(data);
      if (msg.id) {
        const entry = pending.get(msg.id);
        if (!entry) return;
        pending.delete(msg.id); clearTimeout(entry.timer);
        if (msg.error) entry.reject(new Error(msg.error.message)); else entry.resolve(msg.result);
      } else if (msg.method === 'Fetch.requestPaused') intercept(msg.params).catch(error => { handlerError = error; });
    });
    evidence.browser_version = await cdp('Browser.getVersion');
    await cdp('Page.enable'); await cdp('Runtime.enable');
    await cdp('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
    await cdp('Emulation.setTimezoneOverride', { timezoneId: 'Asia/Shanghai' });
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1100, deviceScaleFactor: 1, mobile: false });
    const token = `test.${Buffer.from(JSON.stringify({ exp: 4102444800 })).toString('base64url')}.fixed-browser-fixture`;
    await cdp('Page.addScriptToEvaluateOnNewDocument', { source: `
      localStorage.setItem('ragforge-auth',JSON.stringify({state:{accessToken:${JSON.stringify(token)},refreshToken:null,user:{id:'fixed-user',email:'browser@example.invalid',full_name:'浏览器测试',is_active:true,is_superuser:false}},version:0}));
      localStorage.setItem('ragforge-workspace-selection',JSON.stringify({state:{organizationId:${JSON.stringify(org)},workspaceId:null},version:0}));` });
    await cdp('Page.navigate', { url: `${origin}/investigations` });
    await waitFor(`document.body.textContent.includes('测试企业 B（当前企业）') && !document.querySelector('button[type="submit"]').disabled`);
    await setInput('investigation-case-id', ` ${caseId} `);
    await setInput('investigation-as-of', '2026-10-15T20:00');
    const first = await startRequest();
    for (let i = 0; i < 4; i++) await clickSubmit();
    await sleep(400);
    assert.equal(evidence.requests.length, 1);
    assert.equal(await evaluate(`document.querySelector('button[type="submit"]').disabled`), true);
    assert.deepEqual(evidence.requests[0].body, { case_id: caseId, as_of: '2026-10-15T12:00:00.000Z' });
    assert.equal(evidence.requests[0].path, `/api/v1/organizations/${org}/investigations`);
    assert.equal(evidence.requests[0].method, 'POST');
    evidence.checks.push({ name: 'selected_org_case_and_explicit_as_of', passed: true },
      { name: 'pending_and_five_clicks_one_request', passed: true });
    await screenshot('pending');
    const fixed = report('browser-success-1');
    await fulfill(first, 200, fixed);
    await waitFor(`document.querySelector('pre')?.textContent.includes('browser-success-1')`);
    assert.equal(await evaluate(`document.querySelector('pre').textContent`), fixed.handoff);
    assert.ok(await evaluate(`document.body.textContent.includes('请求标识：browser-success-1')`));
    evidence.checks.push({ name: 'request_id_and_all_six_sections_exact', passed: true });
    await screenshot('success');

    await setInput('investigation-as-of', '');
    const noRecord = await startRequest();
    assert.deepEqual(evidence.requests.at(-1).body, { case_id: caseId });
    await fulfill(noRecord, 200, report('browser-not-found', 'not_found'));
    await waitFor(`document.body.textContent.includes('未找到与该企业及案件 ID 匹配的记录。')`);
    assert.equal(await evaluate(`document.body.textContent.includes('browser-success-1')`), false);
    evidence.checks.push({ name: 'omitted_as_of_and_not_found_replaces_success', passed: true });
    await screenshot('not-found');

    for (const [mode, message] of [[403, '无权调查当前企业的案件。'],
      [500, '调查执行失败，请稍后人工核查。此次没有形成业务结论。'],
      ['network', '网络连接失败，调查未完成；请检查连接后再试。']]) {
      const marker = `success-before-${mode}`;
      await seedSuccess(marker);
      const requestId = await startRequest();
      const count = evidence.requests.length;
      if (mode === 'network') await cdp('Fetch.failRequest', { requestId, errorReason: 'ConnectionFailed' });
      else await fulfill(requestId, mode, { error: { code: mode === 403 ? 'permission_denied' : 'internal_error', message: 'PRIVATE_EXCEPTION_DETAIL' } });
      await waitFor(`document.querySelector('[role="alert"]')?.textContent.includes(${JSON.stringify(message)})`);
      await sleep(400);
      assert.equal(evidence.requests.length, count);
      assert.equal(await evaluate(`!!document.querySelector('pre') || document.body.textContent.includes(${JSON.stringify(marker)}) || document.body.textContent.includes('PRIVATE_EXCEPTION_DETAIL')`), false);
      evidence.checks.push({ name: `${mode}_message_no_stale_report_no_retry`, passed: true });
      await screenshot(String(mode));
    }
    if (handlerError) throw handlerError;
    assert.deepEqual(evidence.unexpected_requests, []);
    assert.equal(evidence.requests.length, 8);
    evidence.passed = true;
  } catch (error) {
    evidence.failure = { type: error.name, message: error.message };
    if (active) await screenshot('failure').catch(() => {});
    process.exitCode = 1;
  } finally {
    if (active) await cdp('Browser.close').catch(() => {});
    for (let i = 0; i < 50 && browser.exitCode === null; i++) await sleep(100);
    if (browser.exitCode === null) browser.kill();
    evidence.browser_exit_code = browser.exitCode;
    evidence.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify({ passed: evidence.passed, checks: evidence.checks.length,
      requests: evidence.requests.length, failure: evidence.failure, evidence: path.join(output, 'evidence.json') }));
    if (ws) ws.close();
  }
})();
