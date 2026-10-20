// Real Chrome + Next + JWT login + isolated PostgreSQL ActionRequest demo.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const WebSocket = require('../frontend/node_modules/next/dist/compiled/ws');

const state = JSON.parse(fs.readFileSync(path.join(__dirname, 'action_request_demo_state.json'), 'utf8'));
assert.equal(state.database, 'ragforge_day6_test');
const origin = 'http://127.0.0.1:3108';
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const output = path.join(__dirname, `action_request_browser_${stamp}`);
fs.mkdirSync(output);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'project-a-action-browser-'));
const browserPath = process.env.PROJECT_A_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const evidence = { database: state.database, schema: state.schema, origin, started_at: new Date().toISOString(),
  browser_requests: [], checks: [], screenshots: [], passed: false, profile, browser_path: browserPath };
const browser = spawn(browserPath, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
  '--disable-component-update', '--disable-sync', '--disable-gpu', '--disable-gpu-compositing',
  '--disable-gpu-sandbox', '--disable-software-rasterizer',
  '--disable-features=Vulkan,DawnGraphite,UseSkiaRenderer', 'about:blank',
], { windowsHide: true, stdio: ['ignore', fs.openSync(path.join(output, 'chrome.stdout.log'), 'w'),
  fs.openSync(path.join(output, 'chrome.stderr.log'), 'w')] });
evidence.browser_pid = browser.pid;
let ws, seq = 0, held = null, holdCreation = false;
const pending = new Map();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression, attempts = 200) {
  for (let i = 0; i < attempts; i++) {
    if (await evaluate(expression)) return;
    await sleep(100);
  }
  throw new Error(`Browser wait failed: ${expression}`);
}
async function setInput(id, value) {
  await evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});` +
    `const setter=Object.getOwnPropertyDescriptor(e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;` +
    `setter.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));` +
    `e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function clickText(text) {
  const clicked = await evaluate(`(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent?.trim()===${JSON.stringify(text)});` +
    `if(!b||b.disabled)return false;b.click();return true})()`);
  assert.equal(clicked, true, `button unavailable: ${text}`);
}
async function screenshot(name) {
  const result = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(result.data, 'base64'));
  evidence.screenshots.push(`${name}.png`);
}
async function navigate(route) {
  await cdp('Page.navigate', { url: origin + route });
}
async function login(role) {
  await navigate('/login');
  await waitFor(`!!document.getElementById('email') && !!document.getElementById('password')`);
  await setInput('email', state.emails[role]);
  await setInput('password', state.password);
  await clickText('Sign in');
  await waitFor(`location.pathname==='/dashboard'`);
  await navigate('/action-requests');
  await waitFor(`document.body.textContent.includes('客户通知申请') && !!document.getElementById('action-case-id')`);
  await waitFor(`!![...document.querySelectorAll('button')].find(b=>b.textContent?.includes('提交审核申请')&&!b.disabled)`);
  evidence.checks.push(`${role}_real_login_and_jwt`);
}
async function browserApi(pathname, options = {}) {
  return evaluate(`(async()=>{const token=JSON.parse(localStorage.getItem('ragforge-auth')).state.accessToken;` +
    `const res=await fetch(${JSON.stringify(pathname)},{method:${JSON.stringify(options.method || 'GET')},` +
    `headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},` +
    `body:${options.body ? JSON.stringify(JSON.stringify(options.body)) : 'undefined'}});` +
    `return {status:res.status,body:await res.json()}})()`);
}
async function createViaUi(message) {
  const before = evidence.browser_requests.length;
  await setInput('action-case-id', state.case_id);
  await setInput('action-message', message);
  await clickText('提交审核申请');
  for (let i = 0; i < 100 && evidence.browser_requests.length === before; i++) await sleep(100);
  assert.equal(evidence.browser_requests.length, before + 1);
  await waitFor(`!![...document.querySelectorAll('[role="status"]')].find(x=>x.textContent?.includes('申请 ID：') && x.textContent?.includes('待人工审核'))`);
}
async function reviewViaUi(id, decision) {
  const clicked = await evaluate(`(()=>{const p=[...document.querySelectorAll('p')].find(x=>x.textContent?.trim()===${JSON.stringify('申请 ID：'+id)});` +
    `const b=[...p?.parentElement?.querySelectorAll('button')||[]].find(x=>x.textContent?.trim()===${JSON.stringify(decision)});` +
    `if(!b||b.disabled)return false;b.click();return true})()`);
  assert.equal(clicked, true, `review button unavailable: ${id}/${decision}`);
  await waitFor(`(()=>{const p=[...document.querySelectorAll('p')].find(x=>x.textContent?.trim()===${JSON.stringify('申请 ID：'+id)});` +
    `return p?.parentElement?.textContent.includes(${JSON.stringify(decision === '批准' ? '已批准，尚未发送通知' : '已拒绝')})})()`);
}

(async () => {
  try {
    const portFile = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await sleep(100);
    const port = fs.readFileSync(portFile, 'utf8').split('\n')[0];
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    ws = new WebSocket(targets.find(item => item.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.once('open', resolve); ws.once('error', reject); });
    ws.on('message', data => {
      const msg = JSON.parse(data);
      if (msg.id) {
        const entry = pending.get(msg.id);
        if (!entry) return;
        pending.delete(msg.id); clearTimeout(entry.timer);
        if (msg.error) entry.reject(new Error(msg.error.message)); else entry.resolve(msg.result);
      } else if (msg.method === 'Fetch.requestPaused') {
        const request = msg.params.request;
        if (request.method === 'POST' && request.url.endsWith('/action-requests')) {
          evidence.browser_requests.push({ path: new URL(request.url).pathname, method: request.method,
            body: JSON.parse(request.postData) });
          if (holdCreation && !held) { held = msg.params.requestId; return; }
        }
        cdp('Fetch.continueRequest', { requestId: msg.params.requestId }).catch(() => {});
      }
    });
    await cdp('Page.enable'); await cdp('Runtime.enable');
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
    await login('member');
    const base = `/api/v1/organizations/${state.organization_id}/action-requests`;
    const baseline = await browserApi(base);
    assert.equal(baseline.status, 200);
    const previousIds = new Set(baseline.body.map(item => item.id));
    await cdp('Fetch.enable', { patterns: [{ urlPattern: '*action-requests*' }] });
    holdCreation = true;
    await setInput('action-case-id', state.case_id);
    await setInput('action-message', `${stamp}-approval`);
    await clickText('提交审核申请');
    for (let i = 0; i < 50 && !held; i++) await sleep(100);
    assert.ok(held, 'creation request not held');
    for (let i = 0; i < 4; i++) await evaluate(`document.querySelector('button[type="submit"]').click()`);
    await sleep(250);
    assert.equal(evidence.browser_requests.length, 1);
    assert.equal(await evaluate(`document.querySelector('button[type="submit"]').disabled`), true);
    evidence.checks.push('five_clicks_one_creation_request');
    holdCreation = false;
    await cdp('Fetch.continueRequest', { requestId: held });
    held = null;
    await waitFor(`!![...document.querySelectorAll('[role="status"]')].find(x=>x.textContent?.includes('申请 ID：') && x.textContent?.includes('待人工审核'))`);
    const firstBody = evidence.browser_requests[0].body;
    assert.deepEqual(Object.keys(firstBody).sort(), ['idempotency_key', 'message', 'target_case_id']);
    const firstList = await browserApi(base);
    assert.equal(firstList.status, 200);
    const first = firstList.body.find(item => !previousIds.has(item.id));
    assert.ok(first && first.status === 'pending_approval');
    await screenshot('member_pending');
    const duplicate = await browserApi(base, { method: 'POST', body: firstBody });
    assert.equal(duplicate.status, 200);
    assert.equal(duplicate.body.id, first.id);
    const conflict = await browserApi(base, { method: 'POST', body: { ...firstBody, message: 'changed' } });
    assert.equal(conflict.status, 409);
    const foreign = await browserApi(`/api/v1/organizations/${state.other_organization_id}/action-requests`);
    assert.equal(foreign.status, 403);
    const memberReview = await browserApi(`${base}/${first.id}/review`, { method: 'POST', body: { decision: 'approved' } });
    assert.equal(memberReview.status, 403);
    const unauth = await evaluate(`(async()=>{const r=await fetch(${JSON.stringify(base)});return r.status})()`);
    assert.equal(unauth, 401);
    evidence.checks.push('idempotency_conflict_cross_org_member_review_and_unauth');
    await createViaUi(`${stamp}-rejection`);
    const secondList = await browserApi(base);
    assert.equal(secondList.status, 200);
    assert.equal(secondList.body.length, baseline.body.length + 2);
    const second = secondList.body.find(item => !previousIds.has(item.id) && item.id !== first.id);
    assert.ok(second && second.status === 'pending_approval');
    await cdp('Fetch.disable');
    await login('admin');
    await waitFor(`document.body.textContent.includes(${JSON.stringify(first.id)}) && document.body.textContent.includes(${JSON.stringify(second.id)})`);
    await reviewViaUi(first.id, '批准');
    await screenshot('approved_unsent');
    await reviewViaUi(second.id, '拒绝');
    await screenshot('rejected');
    await cdp('Page.reload');
    await waitFor(`document.body.textContent.includes(${JSON.stringify(first.id)}) && document.body.textContent.includes(${JSON.stringify(second.id)})`);
    await waitFor(`document.body.textContent.includes('已批准，尚未发送通知') && document.body.textContent.includes('已拒绝')`);
    evidence.checks.push('refresh_preserves_approved_unsent_and_rejected');
    const finalList = await browserApi(base);
    assert.equal(finalList.status, 200);
    assert.equal(finalList.body.find(item => item.id === first.id).status, 'approved');
    assert.equal(finalList.body.find(item => item.id === second.id).status, 'rejected');
    evidence.request_ids = { approved: first.id, rejected: second.id };
    evidence.checks.push('browser_create_approve_and_create_reject_with_real_jwt');
    evidence.passed = true;
  } catch (error) {
    evidence.failure = { type: error.name, message: error.message };
    process.exitCode = 1;
  } finally {
    if (ws) await cdp('Browser.close').catch(() => {});
    for (let i = 0; i < 50 && browser.exitCode === null; i++) await sleep(100);
    if (browser.exitCode === null) browser.kill();
    evidence.browser_exit_code = browser.exitCode;
    evidence.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify({ passed: evidence.passed, failure: evidence.failure,
      checks: evidence.checks.length, evidence: path.join(output, 'evidence.json'), profile }));
    if (ws) ws.close();
  }
})();
