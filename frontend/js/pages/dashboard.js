import { api } from "../api.js";
import { state, can, catalog, supportGroups } from "../state.js";
import { $, html, mount, icon, fmtRelative, fmtMinutes, fmtNum, statusBadge, prioBadge, emptyState, errorToast,
  skeletonRows, toast } from "../ui.js";
import { trendChart, hbars, donut, tipHandlers } from "../charts.js";

export async function render(view, _params, query) {
  const ops = can("dashboard.ops");
  const mode = ops && query.view !== "mine" ? "ops" : "mine";
  if (mode === "ops") return renderOps(view);
  return renderEmployee(view, ops);
}

const greet = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

function viewSwitch(active) {
  return html`<div class="seg" role="tablist">
    <button role="tab" class="${active === "ops" ? "on" : ""}" data-href="#/">Operations</button>
    <button role="tab" class="${active === "mine" ? "on" : ""}" data-href="#/?view=mine">My requests</button></div>`;
}
function wireSwitch(view) {
  view.querySelectorAll(".seg [data-href]").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.href; }));
}

// ===================================================================== employee
async function renderEmployee(view, showSwitch) {
  const first = state.me.full_name.split(" ")[0];
  mount(view, html`
    ${showSwitch ? html`<div class="page-head" style="margin-bottom:16px"><div></div>${viewSwitch("mine")}</div>` : ""}
    <section class="hero">
      <div>
        <h1>${greet()}, ${first}</h1>
        <p>How can IT help you today? Search for a quick fix or raise a ticket.</p>
        <form class="search" id="kb-quick" role="search">${icon("search")}
          <input type="search" name="q" placeholder="e.g. VPN disconnects, printer offline, ERP report mismatch" aria-label="Search the knowledge base"></form>
      </div>
      <a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a>
    </section>
    <div class="kpis" style="margin-top:20px" id="emp-kpis">${[1, 2, 3, 4].map(() => html`<div class="kpi"><div class="skeleton" style="width:50%"></div><div class="skeleton" style="width:30%;height:26px;margin-top:8px"></div></div>`)}</div>
    <div class="grid grid-main-side" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>Recently updated</h2><a href="#/tickets?scope=mine" class="small">View all</a></div>
        <div class="card-body flush"><div class="table-wrap"><table class="data"><thead><tr><th>Ticket</th><th>Subject</th><th>Status</th><th class="hide-sm">Assigned to</th><th class="hide-sm">Updated</th></tr></thead>
        <tbody id="emp-recent">${skeletonRows(4, 5)}</tbody></table></div></div></div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Announcements</h2></div><div class="card-body" id="ann"><div class="skeleton"></div></div></div>
        <div class="card"><div class="card-head"><h2>Popular answers</h2><a class="small" href="#/kb">Knowledge base</a></div>
          <ul class="list" id="pop" style="padding-bottom:6px"></ul></div>
      </div>
    </div>`);
  if (showSwitch) wireSwitch(view);
  $("#kb-quick", view).addEventListener("submit", (e) => {
    e.preventDefault();
    location.hash = `#/kb?q=${encodeURIComponent(e.target.q.value.trim())}`;
  });

  try {
    const [d, ann, kb] = await Promise.all([api.get("/dashboard/employee"), api.get("/announcements"),
      api.get("/kb/articles", { limit: 5 })]);
    if (!$("#emp-kpis", view)?.isConnected) return;
    const s = d.summary;
    mount($("#emp-kpis", view), html`
      ${kpi("Open tickets", s.open, "#/tickets?scope=mine&status=open")}
      ${kpi("Awaiting your reply", s.awaiting_me, "#/tickets?scope=mine&status=PENDING_EMPLOYEE", s.awaiting_me ? "warn" : "")}
      ${kpi("Being worked on", s.in_progress, "#/tickets?scope=mine&status=ASSIGNED,IN_PROGRESS,REOPENED")}
      ${kpi("Resolved — please confirm", s.resolved, "#/tickets?scope=mine&status=RESOLVED")}`);
    mount($("#emp-recent", view), d.recent.length ? html`${d.recent.map((t) => html`
      <tr class="clickable" data-href="#/tickets/${t.number}"><td><span class="t-id">${t.number}</span></td>
      <td><span class="t-subject">${t.subject}</span></td><td>${statusBadge(t.status)}</td>
      <td class="hide-sm">${t.assignee || html`<span class="muted">Not yet assigned</span>`}</td>
      <td class="hide-sm muted">${fmtRelative(t.updated_at)}</td></tr>`)}` :
      html`<tr><td colspan="5">${emptyState("No tickets yet", "When you raise a ticket it will appear here.", "inbox",
        html`<a class="btn primary sm" href="#/tickets/new">Raise your first ticket</a>`)}</td></tr>`);
    rowLinks(view);
    mount($("#ann", view), ann.length ? html`<div class="stack" style="gap:12px">${ann.map((a) => html`
      <div class="notice ${a.severity === "warning" ? "warn" : a.severity === "outage" ? "danger" : ""}">${icon("megaphone")}
      <div><b>${a.title}</b>${a.body}</div></div>`)}</div>` : html`<p class="muted small">No announcements right now.</p>`);
    mount($("#pop", view), kb.length ? html`${kb.map((a) => html`<li><a class="item" href="#/kb/${a.id}">${a.title}
      <div class="t-sub2">${a.category || "General"}</div></a></li>`)}` : html`<li class="muted small">No articles yet.</li>`);
  } catch (e) { errorToast(e); }
}

function kpi(label, value, href, tone = "", foot = "") {
  return html`<div class="kpi ${tone}">${href ? html`<a class="kpi-link" href="${href}" aria-label="${label}"></a>` : ""}
    <div class="label">${label}</div><div class="value">${value ?? "—"}</div>${foot ? html`<div class="foot">${foot}</div>` : ""}</div>`;
}
function rowLinks(root) {
  root.querySelectorAll("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", () => { location.hash = tr.dataset.href; });
  });
}

// ===================================================================== operations
const RANGES = [["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"], ["90", "Last 90 days"]];
const filters = { days: "14", group_id: "", category_id: "", department_id: "" };

async function renderOps(view) {
  const [cat, groups, depts] = await Promise.all([catalog(), supportGroups(), api.get("/departments").catch(() => [])]);
  mount(view, html`
    <div class="page-head">
      <div><h1>Service operations</h1><div class="sub">Live queue health and performance for the teams you can see.</div></div>
      <div class="row">${viewSwitch("ops")}
        ${can("report.export") ? html`<button class="btn" id="exp">${icon("download")} Export CSV</button>` : ""}</div>
    </div>
    <div class="card" style="margin-bottom:4px"><div class="toolbar" style="border:0">
      ${icon("filter")}<span class="small muted" style="margin-right:4px">Filters</span>
      <select id="f-days" aria-label="Date range">${RANGES.map(([v, l]) => html`<option value="${v}" ${filters.days === v ? "selected" : ""}>${l}</option>`)}</select>
      <select id="f-group" aria-label="Support group"><option value="">All support groups</option>${groups.map((g) => html`<option value="${g.id}" ${String(filters.group_id) === String(g.id) ? "selected" : ""}>${g.name}</option>`)}</select>
      <select id="f-cat" aria-label="Category"><option value="">All categories</option>${cat.categories.map((c) => html`<option value="${c.id}" ${String(filters.category_id) === String(c.id) ? "selected" : ""}>${c.name}</option>`)}</select>
      <select id="f-dept" aria-label="Department"><option value="">All departments</option>${depts.map((d) => html`<option value="${d.id}" ${String(filters.department_id) === String(d.id) ? "selected" : ""}>${d.name}</option>`)}</select>
      <span class="spacer"></span><button class="btn ghost sm" id="f-refresh">${icon("refresh")} Refresh</button>
    </div></div>
    <div class="section-label">Live now <span class="pill" id="live-at"></span><span class="spacer"></span>
      <span class="queue-line" id="queue-line"></span></div>
    <div class="kpis" id="live">${Array.from({ length: 6 }, () => html`<div class="kpi"><div class="skeleton" style="width:60%"></div><div class="skeleton" style="width:35%;height:26px;margin-top:8px"></div></div>`)}</div>
    <div class="section-label">Selected period <span class="pill" id="period"></span></div>
    <div class="kpis" id="hist"></div>
    <div class="grid" style="grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);margin-top:20px" id="row1">
      <div class="card"><div class="card-head"><h2>Ticket trend</h2>
        <div class="legend"><span><i style="background:var(--chart-1)"></i>Created</span><span><i style="background:var(--chart-2)"></i>Resolved</span></div></div>
        <div class="card-body" id="trend"></div></div>
      <div class="card"><div class="card-head"><h2>Priority mix</h2><span class="hint">Created in period</span></div>
        <div class="card-body" id="prio"></div></div>
    </div>
    <div class="grid grid-3" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>By category</h2></div><div class="card-body" id="bycat"></div></div>
      <div class="card"><div class="card-head"><h2>By department</h2></div><div class="card-body" id="bydept"></div></div>
      <div class="card"><div class="card-head"><h2>Engineer workload</h2><span class="hint">Open now</span></div>
        <div class="card-body flush"><table class="data"><thead><tr><th>Engineer</th><th class="num">Open</th><th class="num">P1/P2</th></tr></thead>
        <tbody id="work"></tbody></table></div></div>
    </div>`);
  wireSwitch(view);

  const read = () => {
    filters.days = $("#f-days", view).value; filters.group_id = $("#f-group", view).value;
    filters.category_id = $("#f-cat", view).value; filters.department_id = $("#f-dept", view).value;
  };
  ["#f-days", "#f-group", "#f-cat", "#f-dept"].forEach((s) => $(s, view).addEventListener("change", () => { read(); load(view); }));
  $("#f-refresh", view).addEventListener("click", () => load(view));
  $("#exp", view)?.addEventListener("click", async () => {
    try {
      await api.download("/tickets/export.csv", { group_id: filters.group_id, category_id: filters.category_id,
        date_from: isoDaysAgo(Number(filters.days) - 1) }, "tickets.csv");
      toast("Export downloaded.");
    } catch (e) { errorToast(e); }
  });
  await load(view);
  const t = setInterval(() => { if (!document.hidden) load(view, true); }, 120000);
  return () => clearInterval(t);
}

function isoDaysAgo(n) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.toLocaleDateString("en-CA", { timeZone: state.me.timezone });
}

async function load(view, quiet = false) {
  let d;
  try {
    d = await api.get("/dashboard/ops", { start: isoDaysAgo(Number(filters.days) - 1), group_id: filters.group_id,
      category_id: filters.category_id, department_id: filters.department_id });
  } catch (e) { if (!quiet) errorToast(e); return; }
  if (!$("#live", view)?.isConnected) return; // navigated away while loading
  const L = d.live, H = d.historical;
  const q = (s) => `#/tickets?${s}${filters.group_id ? `&group_id=${filters.group_id}` : ""}`;
  $("#live-at", view).textContent = `as of ${new Date(d.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: state.me.timezone })}`;
  $("#period", view).textContent = RANGES.find((r) => r[0] === filters.days)[1].toLowerCase();
  mount($("#live", view), html`
    ${kpi("Open", fmtNum(L.open), q("status=open"))}
    ${kpi("New today", fmtNum(L.new_today), q("status=open&sort=created_desc"))}
    ${kpi("Unassigned", fmtNum(L.unassigned), q("status=open&assignee=unassigned"), L.unassigned ? "warn" : "")}
    ${kpi("Critical / high", fmtNum(L.critical_high), q("status=open&priority=P1,P2"), L.critical_high ? "alert" : "")}
    ${kpi("Due within 4h", fmtNum(L.approaching_sla), q("sla=at_risk&sort=due"), L.approaching_sla ? "warn" : "")}
    ${kpi("Overdue", fmtNum(L.overdue), q("sla=breached&status=open&sort=due"), L.overdue ? "alert" : "")}
`);
  mount($("#queue-line", view), html`
    <a href="${q("status=PENDING_EMPLOYEE")}">Pending employee <b>${fmtNum(L.pending_employee)}</b></a>
    <a href="${q("status=PENDING_APPROVAL")}">Pending approval <b>${fmtNum(L.pending_approval)}</b></a>
    <a href="${q("status=RESOLVED,CLOSED&sort=updated_desc")}">Resolved today <b>${fmtNum(L.resolved_today)}</b></a>`);
  mount($("#hist", view), html`
    ${kpi("Tickets created", fmtNum(H.created))}
    ${kpi("Avg first response", fmtMinutes(H.avg_first_response_minutes), null, "", "business time")}
    ${kpi("Avg resolution", fmtMinutes(H.avg_resolution_minutes), null, "", "business time, net of pauses")}
    ${kpi("SLA compliance", H.sla_compliance_percent === null ? "—" : html`${H.sla_compliance_percent}<small>%</small>`, null,
      H.sla_compliance_percent !== null && H.sla_compliance_percent < 80 ? "warn" : "", `${H.sla_measured} resolved tickets`)}
    ${kpi("Reopen rate", H.reopen_rate_percent === null ? "—" : html`${H.reopen_rate_percent}<small>%</small>`)}
    ${kpi("Satisfaction", H.csat_average === null ? "—" : html`${H.csat_average}<small>/ 5</small>`, null, "", `${H.csat_responses} ratings`)}`);

  trendChart($("#trend", view), d.trend);
  const colors = { P1: "#d92d20", P2: "#ef8a17", P3: "#2f74d6", P4: "#98a6b8" };
  mount($("#prio", view), d.by_priority.length ? html`<div class="row" style="gap:22px;align-items:center;flex-wrap:nowrap">
    <div id="donut">${donut(d.by_priority, colors)}</div>
    <div class="stack" style="gap:8px;flex:1">${d.by_priority.map((p) => html`<div class="row" style="justify-content:space-between">
      ${prioBadge(p.label)}<b style="font-variant-numeric:tabular-nums">${p.value}</b></div>`)}</div></div>` :
    html`<p class="muted small">No tickets in this period.</p>`);
  const dsvg = $("#donut svg", view); if (dsvg) tipHandlers(dsvg);
  mount($("#bycat", view), hbars(d.by_category));
  mount($("#bydept", view), hbars(d.by_department));
  mount($("#work", view), d.workload.length ? html`${d.workload.slice(0, 8).map((w) => html`<tr class="clickable" data-href="#/tickets?assignee=${w.user_id}&status=open">
    <td>${w.name}</td><td class="num"><b>${w.open}</b></td><td class="num">${w.high ? html`<span style="color:var(--danger);font-weight:600">${w.high}</span>` : "0"}</td></tr>`)}` :
    html`<tr><td colspan="3" class="muted small" style="padding:18px">No open assigned tickets.</td></tr>`);
  rowLinks(view);
}
