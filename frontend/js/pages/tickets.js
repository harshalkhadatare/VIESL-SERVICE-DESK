import { api } from "../api.js";
import { can, isStaff, catalog, supportGroups } from "../state.js";
import { $, $$, html, mount, icon, fmtRelative, fmtDate, statusBadge, prioBadge, slaBadge, skeletonRows, emptyState,
  errorToast, debounce, toast } from "../ui.js";

const STAFF_TABS = [
  ["queue", "My queues", { scope: "queue", status: "open" }],
  ["assigned", "Assigned to me", { scope: "assigned", status: "open" }],
  ["unassigned", "Unassigned", { scope: "queue", status: "open", assignee: "unassigned" }],
  ["all", "All visible", { scope: "all" }],
  ["mine", "Raised by me", { scope: "mine" }],
];
const EMP_TABS = [
  ["open", "Open", { scope: "mine", status: "open" }],
  ["waiting", "Awaiting my reply", { scope: "mine", status: "PENDING_EMPLOYEE" }],
  ["resolved", "Resolved", { scope: "mine", status: "RESOLVED" }],
  ["all", "All my tickets", { scope: "mine" }],
];
const VIEWER_TABS = [["all", "All tickets", { scope: "all", status: "open" }], ["mine", "Raised by me", { scope: "mine" }]];
const KEYS = ["q", "scope", "status", "priority", "category_id", "group_id", "assignee", "sla", "sort", "page"];

export async function render(view, _p, query) {
  const staff = isStaff();
  const tabs = staff ? STAFF_TABS : can("ticket.view_all") ? VIEWER_TABS : EMP_TABS;
  const hasExplicit = KEYS.some((k) => query[k]);
  const f = hasExplicit ? { scope: "all", ...query } : { ...tabs[0][2] };
  if (!staff && !can("ticket.view_all") && !can("ticket.view_department")) f.scope = "mine";
  const activeTab = () => tabs.find(([, , p]) => Object.keys(p).every((k) => String(f[k] ?? "") === String(p[k]))
    && ["priority", "category_id", "sla", "q", "group_id"].every((k) => !f[k]) && (p.assignee || !f.assignee))?.[0];

  const [cat, groups] = await Promise.all([catalog(), staff || can("dashboard.ops") ? supportGroups() : []]);
  mount(view, html`
    <div class="page-head">
      <div><h1>${staff || can("ticket.view_all") ? "Tickets" : "My tickets"}</h1>
        <div class="sub">${staff ? "Work your queues, keep SLAs green." : "Track the status of everything you have raised."}</div></div>
      <div class="row">
        ${can("report.export") ? html`<button class="btn" id="exp">${icon("download")} Export</button>` : ""}
        <a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a></div>
    </div>
    <div class="card">
      <div class="tabs" role="tablist" id="tabs">${tabs.map(([k, l]) => html`<button role="tab" data-tab="${k}">${l}</button>`)}</div>
      <div class="toolbar">
        <div class="search-inline">${icon("search")}<input type="search" id="f-q" placeholder="Ticket number or subject" value="${f.q || ""}" aria-label="Search tickets"></div>
        <select id="f-status" aria-label="Status"><option value="">Any status</option><option value="open">All open</option>
          ${cat.statuses.map((s) => html`<option value="${s.code}">${s.name}</option>`)}</select>
        <select id="f-priority" aria-label="Priority"><option value="">Any priority</option>
          ${cat.priorities.map((p) => html`<option value="${p.code}">${p.code} · ${p.name}</option>`)}<option value="P1,P2">P1 + P2</option></select>
        <select id="f-category" aria-label="Category"><option value="">Any category</option>
          ${cat.categories.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select>
        ${groups.length ? html`<select id="f-group" aria-label="Support group"><option value="">Any group</option>
          ${groups.map((g) => html`<option value="${g.id}">${g.name}</option>`)}</select>` : ""}
        <select id="f-sla" aria-label="SLA"><option value="">Any SLA state</option><option value="at_risk">Due within 4h</option><option value="breached">Breached</option></select>
        <span class="spacer"></span>
        <select id="f-sort" aria-label="Sort"><option value="updated_desc">Recently updated</option><option value="created_desc">Newest</option>
          <option value="created_asc">Oldest</option><option value="priority">Priority</option><option value="due">SLA due soonest</option></select>
      </div>
      <div class="table-wrap"><table class="data">
        <thead><tr><th>Ticket</th><th>Subject</th><th>Status</th><th>Priority</th>
          <th class="hide-sm">${staff ? "Requester" : "Category"}</th><th class="hide-sm">${staff ? "Assignee" : "Assigned to"}</th>
          <th class="hide-sm">SLA</th><th class="hide-sm">Updated</th></tr></thead>
        <tbody id="rows">${skeletonRows(8, 8)}</tbody></table></div>
      <div class="pager" id="pager"></div>
    </div>`);

  const sel = { status: "#f-status", priority: "#f-priority", category_id: "#f-category", group_id: "#f-group", sla: "#f-sla", sort: "#f-sort" };
  for (const [k, s] of Object.entries(sel)) { const el = $(s, view); if (el && f[k]) el.value = f[k]; }

  const syncTabs = () => { const a = activeTab(); $$("#tabs button", view).forEach((b) => b.classList.toggle("on", b.dataset.tab === a)); };
  const pushUrl = () => {
    const q = new URLSearchParams();
    KEYS.forEach((k) => { if (f[k] && !(k === "page" && f[k] === 1)) q.set(k, f[k]); });
    history.replaceState(null, "", `#/tickets${q.toString() ? "?" + q : ""}`);
  };

  async function load() {
    syncTabs(); pushUrl();
    mount($("#rows", view), skeletonRows(6, 8));
    try {
      const page = Number(f.page || 1);
      const r = await api.get("/tickets", { ...Object.fromEntries(KEYS.filter((k) => k !== "page").map((k) => [k, f[k]])), page, page_size: 25 });
      if (!$("#rows", view)?.isConnected) return;
      mount($("#rows", view), r.items.length ? html`${r.items.map((t) => html`
        <tr class="clickable" data-href="#/tickets/${t.number}" tabindex="0">
          <td><span class="t-id">${t.number}</span></td>
          <td><span class="t-subject" title="${t.subject}">${t.subject}</span><span class="t-sub2">${staff ? t.category : t.ticket_type === "incident" ? "Incident" : "Service request"}${t.support_group && staff ? html` · ${t.support_group}` : ""}</span></td>
          <td>${statusBadge(t.status)}</td><td>${prioBadge(t.priority.code)}</td>
          <td class="hide-sm">${staff ? html`${t.requester}<div class="t-sub2">${t.department || ""}</div>` : t.category}</td>
          <td class="hide-sm">${t.assignee || html`<span class="muted">Unassigned</span>`}</td>
          <td class="hide-sm" title="${t.resolution_due_at ? "Due " + fmtDate(t.resolution_due_at) : ""}">${slaBadge(t.sla_state)}</td>
          <td class="hide-sm muted" title="${fmtDate(t.updated_at)}">${fmtRelative(t.updated_at)}</td></tr>`)}` :
        html`<tr><td colspan="8">${emptyState("No tickets match", "Try a different tab or clear the filters.", "inbox")}</td></tr>`);
      $$("tr[data-href]", view).forEach((tr) => {
        tr.addEventListener("click", () => { location.hash = tr.dataset.href; });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") location.hash = tr.dataset.href; });
      });
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      const from = r.total ? (r.page - 1) * r.page_size + 1 : 0;
      mount($("#pager", view), html`<span>${from}–${Math.min(r.total, r.page * r.page_size)} of ${r.total}</span>
        <div class="row"><button class="btn sm" id="pv" ${r.page <= 1 ? "disabled" : ""}>Previous</button>
        <span>Page ${r.page} of ${pages}</span><button class="btn sm" id="nx" ${r.page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { f.page = r.page - 1; load(); });
      $("#nx", view).addEventListener("click", () => { f.page = r.page + 1; load(); });
    } catch (e) { errorToast(e); mount($("#rows", view), html`<tr><td colspan="8">${emptyState("Could not load tickets", e.message, "alert")}</td></tr>`); }
  }

  $$("#tabs button", view).forEach((b) => b.addEventListener("click", () => {
    const preset = tabs.find((t) => t[0] === b.dataset.tab)[2];
    KEYS.forEach((k) => { if (k !== "sort") delete f[k]; });
    Object.assign(f, preset);
    for (const [k, s] of Object.entries(sel)) { const el = $(s, view); if (el && k !== "sort") el.value = f[k] || ""; }
    $("#f-q", view).value = "";
    load();
  }));
  for (const [k, s] of Object.entries(sel)) {
    $(s, view)?.addEventListener("change", (e) => { f[k] = e.target.value; f.page = 1; load(); });
  }
  $("#f-q", view).addEventListener("input", debounce((e) => { f.q = e.target.value.trim(); f.page = 1; load(); }, 300));
  $("#exp", view)?.addEventListener("click", async () => {
    try { await api.download("/tickets/export.csv", Object.fromEntries(KEYS.filter((k) => k !== "page" && k !== "sort").map((k) => [k, f[k]])), "tickets.csv"); toast("Export downloaded."); }
    catch (e) { errorToast(e); }
  });
  await load();
}
