// Local-only React page replay of one saved authenticated investigation response.
// The upstream investigation POST is never sent. Other requests use the real web/API.
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const state = JSON.parse(fs.readFileSync(path.join(__dirname, "investigation_allocation_demo_state.json"), "utf8"));
const run = JSON.parse(fs.readFileSync(path.join(__dirname, "investigation_allocation_run_http_short_refs_20261021.json"), "utf8"));
const response = run.response;
const origin = "http://127.0.0.1:3110";
const port = 3111;

if (run.status !== "completed" || run.http_status !== 200 ||
    run.request_id !== "350b8943-4dcc-493f-b090-11b8076265e4" ||
    !response || response.request_id !== run.request_id ||
    response.organization_id !== state.organization_id ||
    response.case_id !== state.case_id || !state.prepared ||
    state.database !== "ragforge_day6_test") {
  throw new Error("Retained replay evidence or isolated scope does not match");
}

function json(res, status, body, replay = false) {
  const payload = Buffer.from(JSON.stringify(body));
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": payload.length,
    "Cache-Control": "no-store",
    ...(replay ? { "X-Project-A-Local-Replay": run.request_id } : {}),
  });
  res.end(payload);
}

async function readBody(req) {
  let body = "";
  for await (const part of req) {
    body += part;
    if (body.length > 65536) throw new Error("request too large");
  }
  return JSON.parse(body);
}

async function authorized(headers) {
  const authorization = headers.authorization;
  if (!/^Bearer [^\s]+$/.test(authorization || "")) return false;
  const options = { headers: { Authorization: authorization }, signal: AbortSignal.timeout(10000) };
  const [me, organizations, workspaces] = await Promise.all([
    fetch(`${origin}/api/v1/auth/me`, options),
    fetch(`${origin}/api/v1/organizations`, options),
    fetch(`${origin}/api/v1/organizations/${state.organization_id}/workspaces`, options),
  ]);
  if (!me.ok || !organizations.ok || !workspaces.ok) return false;
  const owned = await organizations.json();
  const visible = await workspaces.json();
  return Array.isArray(owned) && owned.some((item) => item.id === state.organization_id) &&
    Array.isArray(visible) && visible.some((item) => item.id === state.workspace_id);
}

function proxy(req, res) {
  const headers = { ...req.headers, host: "127.0.0.1:3110" };
  const upstream = http.request(`${origin}${req.url}`, { method: req.method, headers }, (reply) => {
    res.writeHead(reply.statusCode, reply.headers);
    reply.pipe(res);
  });
  upstream.on("error", () => json(res, 502, { error: { code: "replay_upstream_unavailable" } }));
  req.pipe(upstream);
}

const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, origin).pathname;
  if (pathname === "/__project_a_replay") {
    return json(res, 200, { mode: "local_saved_response", request_id: run.request_id,
      case_id: state.case_id, workspace_id: state.workspace_id, upstream: origin });
  }
  if (req.method !== "POST" || !pathname.includes("investigations")) {
    return proxy(req, res);
  }
  const started = Date.now();
  res.on("finish", () => console.log(
    `replay_post_finished at=${new Date().toISOString()} host=${req.headers.host} ` +
    `path=${pathname} status=${res.statusCode} elapsed_ms=${Date.now() - started}`,
  ));
  res.on("close", () => {
    if (!res.writableFinished) console.log(`replay_post_disconnected path=${pathname}`);
  });
  if (!/^\/api\/v1\/organizations\/[^/]+\/investigations\/?$/.test(pathname)) {
    return json(res, 409, { error: { code: "replay_path_mismatch",
      message: "本地回放未识别此调查路径；没有发起新调查。" } });
  }
  try {
    const body = await readBody(req);
    const organizationId = pathname.split("/")[4];
    const asOf = body.as_of === undefined ? null : Date.parse(body.as_of);
    if (organizationId !== state.organization_id || body.case_id !== state.case_id ||
        body.workspace_id !== state.workspace_id || body.require_knowledge !== true ||
        (asOf !== null && (!Number.isFinite(asOf) ||
          Math.abs(asOf - Date.parse(state.as_of)) > 60000))) {
      return json(res, 409, { error: { code: "replay_input_mismatch",
        message: "本地回放仅接受已保存案件和工作区；没有发起新调查。" } });
    }
    if (!(await authorized(req.headers))) {
      return json(res, 403, { error: { code: "permission_denied",
        message: "当前登录身份无法读取保存报告的企业和工作区。" } });
    }
    return json(res, 200, response, true);
  } catch (error) {
    return json(res, 400, { error: { code: "replay_request_invalid",
      message: "本地回放请求无效；没有发起新调查。" } });
  }
});

// Next's development client needs an upgraded connection for hot reload.
// Only this local HMR path can be upgraded; investigation POSTs stay intercepted.
server.on("upgrade", (req, socket, head) => {
  const pathname = new URL(req.url, origin).pathname;
  if (req.method !== "GET" || pathname !== "/_next/webpack-hmr") {
    socket.end("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
    return;
  }
  const upstream = http.request(`${origin}${req.url}`, {
    method: "GET",
    headers: { ...req.headers, host: "127.0.0.1:3110" },
  });
  socket.on("error", () => upstream.destroy());
  socket.on("close", () => upstream.destroy());
  upstream.on("upgrade", (reply, upstreamSocket, upstreamHead) => {
    const headers = [];
    for (let i = 0; i < reply.rawHeaders.length; i += 2) {
      headers.push(`${reply.rawHeaders[i]}: ${reply.rawHeaders[i + 1]}`);
    }
    socket.write(`HTTP/1.1 101 Switching Protocols\r\n${headers.join("\r\n")}\r\n\r\n`);
    if (head.length) upstreamSocket.write(head);
    if (upstreamHead.length) socket.write(upstreamHead);
    socket.pipe(upstreamSocket).pipe(socket);
    upstreamSocket.on("error", () => socket.destroy());
    console.log("replay_hmr_upgrade status=101");
  });
  upstream.on("response", (reply) => {
    socket.write(`HTTP/1.1 ${reply.statusCode} ${reply.statusMessage}\r\nConnection: close\r\n\r\n`);
    reply.pipe(socket);
    console.log(`replay_hmr_upgrade status=${reply.statusCode}`);
  });
  upstream.on("error", () => socket.destroy());
  upstream.end();
});

server.listen(port, "127.0.0.1", () => {
  console.log(`LOCAL_REPLAY_READY http://127.0.0.1:${port}/investigations pid=${process.pid} request_id=${run.request_id}`);
});
