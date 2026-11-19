// SLA display helpers (IT administrators only — employees never receive SLA data from the server).
import { html, icon, fmtDate, fmtMinutes } from "./ui.js";

export const SLA_STATE = {
  on_track: ["On track", "ok"], at_risk: ["At risk", "warn"], breached: ["Breached", "danger"],
  paused: ["Paused", "neutral"], met: ["Met", "ok"], cancelled: ["Cancelled", "neutral"],
  waiting: ["Waiting", "neutral"],
};

export function slaBadge(state) {
  const [label, tone] = SLA_STATE[state] || [state, "neutral"];
  return html`<span class="sla-badge tone-${tone}">${label}</span>`;
}

/** Progress bar of business time used against the resolution target. */
export function slaBar(pct, state) {
  const tone = (SLA_STATE[state] || [])[1] || "neutral";
  return html`<div class="sla-bar" title="${pct}% of the resolution target used"><i class="tone-${tone}" style="width:${Math.min(100, Math.max(2, pct))}%"></i></div>`;
}

/** The SLA card on the ticket page (right-hand column). */
export function slaCard(t) {
  const s = t.sla;
  if (!s) return "";
  const stopped = ["RESOLVED", "CLOSED", "CANCELLED"].includes(t.status.code);
  const used = s.resolution_target_minutes - s.remaining_business_minutes;
  const resp = t.first_response_at ? (s.response_breached ? "breached" : "met")
    : (s.response_breached || new Date(s.response_due_at) < new Date() ? "breached" : "waiting");
  return html`<div class="card sla-card"><div class="card-head"><h2>${icon("gauge")} SLA</h2>
      <span class="tag-internal">${icon("lock")} IT only</span></div>
    <div class="card-body">
      <div class="sla-top">${slaBadge(s.state)}<span class="sla-pct">${s.percent_used}% used</span></div>
      ${slaBar(s.percent_used, s.state)}
      <dl class="kv sla-kv">
        <dt>Priority target</dt><dd>${t.priority.code} ${t.priority.name} · resolve within <b>${fmtMinutes(s.resolution_target_minutes)}</b></dd>
        <dt>Resolve by</dt><dd>${fmtDate(s.resolution_due_at)}</dd>
        <dt>Time used</dt><dd>${fmtMinutes(Math.max(0, used))} <span class="muted">business time</span></dd>
        ${stopped ? "" : html`<dt>${s.remaining_business_minutes >= 0 ? "Time left" : "Over by"}</dt>
          <dd class="${s.remaining_business_minutes < 0 ? "sla-over" : ""}">${fmtMinutes(Math.abs(s.remaining_business_minutes))}</dd>`}
        <dt>First reply</dt><dd>${t.first_response_at ? fmtDate(t.first_response_at) : html`<span class="muted">Not yet</span>`} ${slaBadge(resp)}</dd>
        ${s.paused_minutes || s.is_paused ? html`<dt>Paused</dt><dd>${fmtMinutes(s.paused_minutes)}${s.is_paused ? html` <span class="muted">· paused now (waiting on employee / resolved)</span>` : ""}</dd>` : ""}
        ${s.escalation_level ? html`<dt>Escalation</dt><dd>Level ${s.escalation_level}</dd>` : ""}
      </dl>
      <a class="small" href="#/sla?q=${t.number}">${icon("chart")} Open in SLA report</a>
    </div></div>`;
}
