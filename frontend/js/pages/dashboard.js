import { api } from "../api.js";
import { state, can, catalog, supportGroups } from "../state.js";
import { $, $$, html, mount, icon, fmtRelative, fmtMinutes, fmtNum, statusBadge, prioBadge, emptyState, errorToast,
  skeletonRows, toast, initials, empId } from "../ui.js";
import { trendChart, hbars, donut, tipHandlers } from "../charts.js";

export async function render(view, _params, query) {
  const ops = can("dashboard.ops");
  const mode = ops && query.view !== "mine" ? "ops" : "mine";
  if (mode === "ops") return renderAdminHome(view);
  return renderEmployee(view, ops);
}

const greet = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

function viewSwitch(active) {
  return html`<div class="seg" role="tablist">
    <button role="tab" class="${active === "ops" ? "on" : ""}" data-href="#/">Overview</button>
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
    <div class="section-label" style="margin-top:22px">Quick help — pick what's wrong</div>
    <div class="quick-tiles">${QUICK.map(([k, ic, t, sub]) => html`<a class="quick-tile" href="#/tickets/new?quick=${k}">
      <span class="qt-ic">${icon(ic)}</span><span><b>${t}</b><span>${sub}</span></span></a>`)}</div>
    <div class="kpis" style="margin-top:20px" id="emp-kpis">${[1, 2, 3, 4].map(() => html`<div class="kpi"><div class="skeleton" style="width:50%"></div><div class="skeleton" style="width:30%;height:26px;margin-top:8px"></div></div>`)}</div>
    <div class="grid grid-main-side" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>Recently updated</h2><a href="#/tickets?scope=mine" class="small">View all</a></div>
        <div class="card-body flush"><div class="table-wrap"><table class="data"><thead><tr><th>Ticket</th><th>Subject</th><th>Status</th><th class="hide-sm">Assigned to</th><th class="hide-sm">Updated</th></tr></thead>
        <tbody id="emp-recent">${skeletonRows(4, 5)}</tbody></table></div></div></div>
      <div class="stack">
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
    const [d, kb] = await Promise.all([api.get("/dashboard/employee"), api.get("/kb/articles", { limit: 5 })]);
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
    mount($("#pop", view), kb.length ? html`${kb.map((a) => html`<li><a class="item" href="#/kb/${a.id}">${a.title}
      <div class="t-sub2">${a.category || "General"}</div></a></li>`)}` : html`<li class="muted small">No articles yet.</li>`);
  } catch (e) { errorToast(e); }
}

// shortcuts on the employee home → pre-filled "Raise a ticket" form (see new-ticket.js QUICK_TEMPLATES)
const QUICK = [
  ["password", "key", "Forgot password", "Reset or unlock an account"],
  ["outlook", "mail", "Email / Outlook", "Not syncing, can't send"],
  ["printer", "file", "Printer / scanner", "Not printing, jammed"],
  ["internet", "zap", "Internet / VPN", "Slow or no connection"],
  ["erp", "layers", "ERP problem", "Error, wrong data, report"],
  ["laptop", "inbox", "Laptop / desktop", "Slow, broken, new device"],
];

function kpi(label, value, href, tone = "", foot = "") {
  return html`<div class="kpi ${tone}">${href ? html`<a class="kpi-link" href="${href}" aria-label="${label}"></a>` : ""}
    <div class="label">${label}</div><div class="value">${value ?? "—"}</div>${foot ? html`<div class="foot">${foot}</div>` : ""}</div>`;
}
function rowLinks(root) {
  root.querySelectorAll("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", () => { location.hash = tr.dataset.href; });
  });
}

// ===================================================================== admin home
const REASON_TONE = { overdue: "danger", unassigned: "warn", due: "warn", high: "info" };

function tile(ic, label, value, sub, href, tone = "") {
  return html`<a class="dash-tile ${tone}" href="${href}"><span class="dt-ic">${icon(ic)}</span>
    <span class="dt-body"><span class="dt-label">${label}</span><span class="dt-value">${value ?? "—"}</span><span class="dt-sub">${sub}</span></span>
    <span class="dt-go">${icon("arrowLeft")}</span></a>`;
}

async function renderAdminHome(view) {
  const first = state.me.full_name.split(" ")[0];
  mount(view, html`
    <div class="page-head">
      <div><h1>${greet()}, ${first}</h1><div class="sub">Here's what needs attention right now.</div></div>
      <div class="row">${viewSwitch("ops")}<a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a></div>
    </div>
    <div class="dash-tiles" id="tiles">${Array.from({ length: 4 }, () => html`<div class="dash-tile"><div class="skeleton" style="width:70%;height:40px"></div></div>`)}</div>
    <div class="strip" id="strip"></div>
    <div class="grid grid-main-side" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>${icon("alert")} Needs attention</h2><a class="small" href="#/tickets?scope=all&status=open&sort=due">See all open</a></div>
        <ul class="att-list" id="att"><li class="att-item"><div class="skeleton" style="width:80%"></div></li></ul></div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Team this week</h2><span class="hint">Resolved · open · rating</span></div>
          <ul class="team-list" id="team"></ul></div>
        <div class="card"><div class="card-head"><h2>This week</h2><span class="hint">Last 7 days</span></div>
          <div class="card-body" id="week"></div></div>
      </div>
    </div>
    <details class="card reports" id="reports">
      <summary>${icon("chart")} <b>Detailed reports</b><span class="muted small">Trends, categories, departments, SLA, export</span><span class="spacer"></span><span class="chev">${icon("arrowLeft")}</span></summary>
      <div id="reports-body"></div>
    </details>`);
  wireSwitch(view);
  const rep = $("#reports", view);
  let reportsCleanup = null;
  rep.addEventListener("toggle", async () => {
    if (rep.open && !$("#reports-body", view).childElementCount) reportsCleanup = await renderOps($("#reports-body", view));
  });

  const loadHome = async (quiet) => {
    let h, o;
    try {
      [h, o] = await Promise.all([api.get("/dashboard/admin-home"), api.get("/dashboard/ops", { start: isoDaysAgo(6) })]);
    } catch (e) { if (!quiet) errorToast(e); return; }
    if (!$("#tiles", view)?.isConnected) return;
    const L = o.live, H = o.historical;
    mount($("#tiles", view), html`
      ${tile("user", "Need an owner", fmtNum(L.unassigned), L.unassigned ? "Open tickets nobody owns" : "All tickets have an owner",
        "#/tickets?scope=all&status=open&assignee=unassigned", L.unassigned ? "warn" : "ok")}
      ${tile("ticket", "Assigned to me", fmtNum(h.my_open), h.my_open ? "Your open tickets" : "Nothing waiting for you",
        "#/tickets?scope=all&status=open&assignee=me", "")}
      ${tile("clock", "Overdue", fmtNum(L.overdue), L.overdue ? "Past their target time" : "All within target",
        "#/tickets?scope=all&sla=breached&status=open&sort=due", L.overdue ? "danger" : "ok")}
      ${tile("checkCircle", "Resolved today", fmtNum(L.resolved_today), `${fmtNum(L.new_today)} new today`,
        "#/tickets?scope=all&status=RESOLVED,CLOSED&sort=updated_desc", "ok")}`);
    mount($("#strip", view), html`
      <a href="#/tickets?scope=all&status=open">${icon("inbox")} <b>${fmtNum(L.open)}</b> open in total</a>
      <a href="#/tickets?scope=all&status=open&priority=P1,P2">${icon("zap")} <b>${fmtNum(L.critical_high)}</b> high priority</a>
      <a href="#/tickets?scope=all&sla=at_risk&sort=due">${icon("clock")} <b>${fmtNum(L.approaching_sla)}</b> due within 4 h</a>
      <a href="#/tickets?scope=all&status=PENDING_EMPLOYEE">${icon("send")} <b>${fmtNum(L.pending_employee)}</b> waiting for employee reply</a>`);

    mount($("#att", view), h.attention.length ? html`${h.attention.map((t) => html`<li class="att-item">
      <span class="prio-dot ${t.priority}" title="${t.priority}"></span>
      <a class="att-main" href="#/tickets/${t.number}">
        <span class="att-top"><span class="t-id">${t.number}</span><span class="badge ${REASON_TONE[t.reason]} plain">${t.reason_label}</span></span>
        <span class="att-subj">${t.subject}</span>
        <span class="t-sub2">${t.requester} ${t.requester_code ? `(${t.requester_code})` : ""} · ${fmtRelative(t.created_at)}${t.assignee ? ` · with ${t.assignee}` : ""}</span></a>
      ${t.assignee_id !== state.me.id ? html`<button class="btn sm" data-take="${t.number}" data-v="${t.version}" title="Assign this ticket to yourself">${icon("user")} Take it</button>`
        : html`<span class="pill">Yours</span>`}</li>`)}` :
      html`<li class="att-empty">${icon("checkCircle")}<div><b>All clear</b><span>No overdue, unassigned or urgent tickets right now.</span></div></li>`);
    $$("[data-take]", view).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        await api.post(`/tickets/${b.dataset.take}/assign`, { assignee_id: state.me.id, expected_version: Number(b.dataset.v) });
        toast(`${b.dataset.take} is now yours.`); loadHome(true);
      } catch (e) { b.disabled = false; errorToast(e); }
    }));

    const maxRes = Math.max(1, ...h.team.map((m) => m.resolved_week));
    mount($("#team", view), h.team.length ? html`${h.team.map((m, i) => html`<li class="${m.is_me ? "me" : ""}">
      <span class="rank">${i < 3 && m.resolved_week ? ["🥇", "🥈", "🥉"][i] : i + 1}</span>
      <span class="avatar sm">${initials(m.name)}</span>
      <a class="tm-main" href="#/tickets?scope=all&status=open&assignee=${m.user_id}"><span class="tm-name">${m.is_me ? "You" : m.name}${empId(m.employee_code)}</span>
        <span class="tm-bar"><i style="width:${Math.round((m.resolved_week / maxRes) * 100)}%"></i></span></a>
      <span class="tm-stats"><b title="Resolved in the last 7 days">${m.resolved_week}</b><span title="Open now">${m.open} open</span>
        ${m.rating ? html`<span class="tm-star" title="${m.ratings} rating(s), last 30 days">★ ${m.rating}</span>` : ""}</span></li>`)}` :
      html`<li class="muted small" style="padding:16px">No IT administrators yet.</li>`);

    mount($("#week", view), html`<div class="week-grid">
      <div><span class="wk-v">${fmtNum(H.created)}</span><span class="wk-l">tickets raised</span></div>
      <div><span class="wk-v">${fmtMinutes(H.avg_first_response_minutes)}</span><span class="wk-l">avg first reply</span></div>
      <div><span class="wk-v">${H.sla_compliance_percent === null ? "—" : `${H.sla_compliance_percent}%`}</span><span class="wk-l">on time</span></div>
      <div><span class="wk-v">${H.csat_average === null ? "—" : html`${H.csat_average}<small> ★</small>`}</span><span class="wk-l">satisfaction</span></div></div>`);
  };
  await loadHome();
  const t = setInterval(() => { if (!document.hidden) loadHome(true); }, 120000);
  return () => { clearInterval(t); if (typeof reportsCleanup === "function") reportsCleanup(); };
}

// ===================================================================== detailed reports
const RANGES = [["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"], ["90", "Last 90 days"]];
const filters = { days: "14", group_id: "", category_id: "", department_id: "" };

async function renderOps(view) {
  const [cat, groups, depts] = await Promise.all([catalog(), supportGroups(), api.get("/departments").catch(() => [])]);
  mount(view, html`
    <div class="toolbar">
      ${icon("filter")}<span class="small muted" style="margin-right:4px">Filters</span>
      <select id="f-days" aria-label="Date range">${RANGES.map(([v, l]) => html`<option value="${v}" ${filters.days === v ? "selected" : ""}>${l}</option>`)}</select>
      <select id="f-group" aria-label="Support group"><option value="">All support groups</option>${groups.map((g) => html`<option value="${g.id}" ${String(filters.group_id) === String(g.id) ? "selected" : ""}>${g.name}</option>`)}</select>
      <select id="f-cat" aria-label="Category"><option value="">All categories</option>${cat.categories.map((c) => html`<option value="${c.id}" ${String(filters.category_id) === String(c.id) ? "selected" : ""}>${c.name}</option>`)}</select>
      <select id="f-dept" aria-label="Department"><option value="">All departments</option>${depts.map((d) => html`<option value="${d.id}" ${String(filters.department_id) === String(d.id) ? "selected" : ""}>${d.name}</option>`)}</select>
      <span class="spacer"></span><button class="btn ghost sm" id="f-refresh">${icon("refresh")} Refresh</button>
      ${can("report.export") ? html`<button class="btn sm" id="exp">${icon("download")} Export CSV</button>` : ""}
    </div><div class="reports-inner">
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
    </div></div>`);

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
  const t = setInterval(() => { if (!document.hidden && view.isConnected) load(view, true); }, 120000);
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
