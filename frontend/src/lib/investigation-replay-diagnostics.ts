// Local 3111 replay diagnostics. Only fixed stage names, counters and elapsed
// times are recorded; no token, request body or report content is retained.
export type ReplayStage =
  | "component_mounted" | "component_unmounted" | "submit_started"
  | "duplicate_blocked" | "response_headers" | "json_parsed"
  | "state_write_idle" | "state_write_pending" | "state_write_success" | "state_write_error"
  | "state_committed_idle" | "state_committed_pending" | "state_committed_success" | "state_committed_error"
  | "report_rendered" | "report_missing" | "old_report_visible_during_pending"
  | "submit_button_ready" | "submit_button_mismatch"
  | "timeout_armed" | "timeout_fired" | "runner_settled" | "runner_rejected";

interface ReplayDiagnostics {
  nextSubmission: number;
  nextComponent: number;
  starts: Record<number, number>;
  lines: string[];
}

type ReplayWindow = Window & { __projectAReplayDiagnostics?: ReplayDiagnostics };

export function isLocalInvestigationReplay(): boolean {
  return typeof window !== "undefined" &&
    window.location.hostname === "127.0.0.1" && window.location.port === "3111";
}

function diagnostics(): ReplayDiagnostics {
  const scope = window as ReplayWindow;
  return scope.__projectAReplayDiagnostics ??= {
    nextSubmission: 0, nextComponent: 0, starts: {}, lines: [],
  };
}

export function newReplayComponent(): number {
  return isLocalInvestigationReplay() ? ++diagnostics().nextComponent : 0;
}

export function newReplaySubmission(): number {
  if (!isLocalInvestigationReplay()) return 0;
  const data = diagnostics();
  const sequence = ++data.nextSubmission;
  data.starts[sequence] = performance.now();
  return sequence;
}

export function replayTrace(
  stage: ReplayStage,
  sequence = 0,
  component = 0,
  status?: number,
): void {
  if (!isLocalInvestigationReplay()) return;
  try {
    const data = diagnostics();
    const elapsed = sequence && data.starts[sequence] !== undefined
      ? ` +${Math.round(performance.now() - data.starts[sequence])}ms` : "";
    const line = `${new Date().toLocaleTimeString("zh-CN", { hour12: false })} ` +
      `#${sequence || "-"} c${component || "-"}${elapsed} ${stage}` +
      (status === undefined ? "" : ` HTTP ${status}`);
    data.lines.push(line);
    data.lines = data.lines.slice(-32);
    let panel = document.getElementById("project-a-replay-diagnostics");
    if (!panel) {
      panel = document.createElement("pre");
      panel.id = "project-a-replay-diagnostics";
      panel.setAttribute("aria-label", "本地保存报告回放诊断");
      Object.assign(panel.style, {
        position: "fixed", right: "12px", bottom: "12px", zIndex: "99999",
        maxWidth: "420px", maxHeight: "240px", overflow: "auto",
        padding: "10px", border: "1px solid #888", borderRadius: "6px",
        background: "#fff", color: "#111", fontSize: "11px", whiteSpace: "pre-wrap",
      });
      document.body.appendChild(panel);
    }
    panel.textContent = `本地回放诊断（仅阶段/耗时）\n${data.lines.join("\n")}`;
    panel.scrollTop = panel.scrollHeight;
  } catch {
    // Diagnostics must never change investigation behavior.
  }
}
