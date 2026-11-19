// SLA compliance report — ticket-by-ticket SLA details for IT administrators (Dashboard → SLA compliance).
import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtMinutes, fmtNum, prioBadge, statusBadge, emptyState, errorToast,
  skeletonRows, debounce, deskBadge, empId } from "../ui.js";
import { slaBadge, slaBar } from "../sla-ui.js";

const RANGES = [["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last 12 months"]];
const STATES = [["", "All tickets"], ["breached", "Breached"], ["at_risk", "At risk"], ["on_track", "On track"],
  ["paused", "Paused"], ["met", "Met"]];
const DESKS = [["all", "IT + ERP-IT"], ["it", "IT"], ["erp", "ERP-IT"]];

const isoDaysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };

export async function render(view, _p, query = {}) {
  const f = {
    days: RANGES.some(([v]) => v === query.days) ? query.days : "30",
    desk: ["all", "it", "erp"].includes(query.desk) ? query.desk : (state.me.desk || "all"),
    state: query.state || "", q: query.q || "",
  };
  mount(view, html`
    <div class="crumbs"><a href="#/">Dashboard</a> / <span>SLA compliance</span></div>
    <div class="page-head"><div><h1>SLA compliance</h1>
      <div class="sub">Every ticket's service-level targets, due times, first reply, time used and breaches — in business hours,
        with time spent waiting on the employee excluded. Visible to IT administrators only.</div></div></div>
    <div class="card" style="margin-bottom:16px"><div class="toolbar" style="border:0">
      ${icon("filter")}
      <select id="s-days" aria-label="Period">${RANGES.map(([v, l]) => html`<option value="${v}" ${f.days === v ? "selected" : ""}>${l}</option>`)}</select>
      <select id="s-desk" aria-label="IT department">${DESKS.map(([v, l]) => html`<option value="${v}" ${f.desk === v ? "selected" : ""}>${l}</option>`)}</select>
      <select id="s-state" aria-label="SLA state">${STATES.map(([v, l]) => html`<option value="${v}" ${f.state === v ? "selected" : ""}>${l}</option>`)}</select>
      <div class="search-inline">${icon("search")}<input type="search" id="s-q" placeholder="Ticket number or subject" value="${f.q}" aria-label="Search"></div>
      <span class="spacer"></span><span class="small muted" id="s-at"></span>
    </div></div>
    <div class="sla-sum" id="s-sum"></div>
    <div class="card"><div class="table-wrap"><table class="data sla-table">
      <thead><tr><th style="width:34px"></th><th>Ticket</th><th>Priority</th><th>Status</th><th class="hide-sm">Assigned to</th>
        <th>First reply</th><th class="hide-sm">Resolve by</th><th class="hide-sm">Time used</th><th>SLA</th></tr></thead>
      <tbody id="s-rows">${skeletonRows(6, 9)}</tbody></table></div></div>`);

  const push = () => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) q.set(k, v);
    if (view.isConnected) history.replaceState(null, "", `#/sla?${q}`);
  };

  function detail(i) {
    const ev = [
      ["Ticket raised", i.created_at, ""],
      ["First reply due", i.response_due_at, ""],
      i.first_response_at ? [`First reply (${fmtMinutes(i.response_minutes)})`, i.first_response_at, i.response_state === "met" ? "good" : "bad"] : null,
      ["Resolution due", i.resolution_due_at, ""],
      i.resolved_at ? ["Resolved", i.resolved_at, i.state === "breached" ? "bad" : "good"] : null,
      i.closed_at ? ["Closed", i.closed_at, ""] : null,
    ].filter(Boolean).sort((a, b) => new Date(a[1]) - new Date(b[1]));
    return html`<div class="sla-detail">
      <div><h4>Timeline</h4><ol class="sla-tl">${ev.map(([l, d, c]) => html`<li class="${c}"><b>${l}</b><span>${fmtDate(d)}</span></li>`)}</ol></div>
      <div><h4>Targets</h4><dl class="kv">
        <dt>First reply within</dt><dd>${fmtMinutes(i.response_target_minutes)} ${slaBadge(i.response_state)}</dd>
        <dt>Resolve within</dt><dd>${fmtMinutes(i.resolution_target_minutes)}</dd>
        <dt>Time used</dt><dd>${fmtMinutes(i.business_minutes_used)} (${i.percent_used}%)</dd>
        <dt>Paused</dt><dd>${fmtMinutes(i.paused_minutes)}${i.is_paused ? " · paused now" : ""}</dd>
        <dt>Escalation</dt><dd>${i.escalation_level ? `Level ${i.escalation_level}` : "None"}</dd>
        ${i.reopen_count ? html`<dt>Reopened</dt><dd>${i.reopen_count}×</dd>` : ""}</dl></div>
      <div><h4>Ticket</h4><dl class="kv">
        <dt>Category</dt><dd>${i.category}</dd>
        <dt>Raised by</dt><dd>${i.requester}${empId(i.requester_code)}</dd>
        <dt>IT department</dt><dd>${deskBadge(i.desk)}</dd>
        <dt>Assigned to</dt><dd>${i.assignee || html`<span class="muted">Unassigned</span>`}</dd></dl>
        <a class="btn sm" href="#/tickets/${i.number}" style="margin-top:10px">${icon("external")} Open ticket</a></div>
    </div>`;
  }

  async function load() {
    push();
    mount($("#s-rows", view), skeletonRows(6, 9));
    try {
      const r = await api.get("/dashboard/sla", { start: isoDaysAgo(Number(f.days) - 1), desk: f.desk,
        state: f.state || undefined, q: f.q || undefined });
      if (!$("#s-rows", view)?.isConnected) return;
      const S = r.summary;
      $("#s-at", view).textContent = `${r.items.length} of ${S.total} tickets · updated ${new Date(r.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
      const tile = (label, value, foot, tone = "", st = null) => html`<div class="kpi ${tone} ${st !== null ? "clickable-kpi" : ""}" ${st !== null ? html`data-st="${st}"` : ""}>
        <div class="label">${label}</div><div class="value">${value}</div>${foot ? html`<div class="foot">${foot}</div>` : ""}</div>`;
      mount($("#s-sum", view), html`
        ${tile("SLA compliance", S.compliance_percent === null ? "—" : html`${S.compliance_percent}<small>%</small>`, `${S.met + S.breached} finished tickets`,
          S.compliance_percent !== null && S.compliance_percent < 80 ? "warn" : "")}
        ${tile("Met", fmtNum(S.met), "resolved in time", "", "met")}
        ${tile("Breached", fmtNum(S.breached), "missed the target", S.breached ? "alert" : "", "breached")}
        ${tile("At risk", fmtNum(S.at_risk), "most of the time used", S.at_risk ? "warn" : "", "at_risk")}
        ${tile("On track", fmtNum(S.on_track), "open, within target", "", "on_track")}
        ${tile("First reply on time", S.response_met_percent === null ? "—" : html`${S.response_met_percent}<small>%</small>`, `avg ${fmtMinutes(S.avg_response_minutes)}`)}`);
      $$("[data-st]", view).forEach((k) => k.addEventListener("click", () => {
        f.state = f.state === k.dataset.st ? "" : k.dataset.st; $("#s-state", view).value = f.state; load();
      }));
      mount($("#s-rows", view), r.items.length ? html`${r.items.map((i, k) => html`
        <tr class="clickable" data-k="${k}">
          <td><button class="sla-expand" aria-expanded="false" aria-label="Show SLA details for ${i.number}" data-x="${k}">${icon("chevRight")}</button></td>
          <td><a class="t-id" href="#/tickets/${i.number}">${i.number}</a><span class="t-sub2" style="display:block" title="${i.subject}">${i.subject.length > 46 ? i.subject.slice(0, 45) + "…" : i.subject}</span></td>
          <td>${prioBadge(i.priority.code)}</td><td>${statusBadge(i.status)}</td>
          <td class="hide-sm small">${i.assignee || html`<span class="muted">Unassigned</span>`}</td>
          <td class="small">${i.first_response_at ? fmtMinutes(i.response_minutes) : html`<span class="muted">—</span>`} ${slaBadge(i.response_state)}</td>
          <td class="hide-sm small">${fmtDate(i.resolution_due_at)}</td>
          <td class="hide-sm mini">${slaBar(i.percent_used, i.state)}<span class="t-sub2">${fmtMinutes(i.business_minutes_used)} of ${fmtMinutes(i.resolution_target_minutes)}</span></td>
          <td>${slaBadge(i.state)}</td></tr>
        <tr class="sla-row-detail" data-d="${k}" hidden><td colspan="9">${detail(i)}</td></tr>`)}`
        : html`<tr><td colspan="9">${emptyState("No tickets here", "Nothing matches this period and filter.", "gauge")}</td></tr>`);
      $$("tr[data-k]", view).forEach((tr) => tr.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        const k = tr.dataset.k, d = $(`tr[data-d="${k}"]`, view), b = $(`[data-x="${k}"]`, view);
        d.hidden = !d.hidden; b.setAttribute("aria-expanded", String(!d.hidden));
      }));
    } catch (e) { errorToast(e); }
  }
  $("#s-days", view).addEventListener("change", (e) => { f.days = e.target.value; load(); });
  $("#s-desk", view).addEventListener("change", (e) => { f.desk = e.target.value; load(); });
  $("#s-state", view).addEventListener("change", (e) => { f.state = e.target.value; load(); });
  $("#s-q", view).addEventListener("input", debounce((e) => { f.q = e.target.value.trim(); load(); }, 350));
  await load();
}
