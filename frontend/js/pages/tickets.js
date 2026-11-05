import { api } from "../api.js";
import { state, can, isStaff, catalog, supportGroups } from "../state.js";
import { $, $$, html, mount, icon, fmtRelative, fmtDate, statusBadge, prioBadge, slaBadge, skeletonRows, emptyState,
  errorToast, debounce, toast, initials, empId, deskBadge } from "../ui.js";

const STAFF_TABS = [
  ["open", "All open", { scope: "all", status: "open" }],
  ["assigned", "Assigned to me", { scope: "all", status: "open", assignee: "me" }],
  ["unassigned", "Unassigned", { scope: "all", status: "open", assignee: "unassigned" }],
  ["all", "All statuses", { scope: "all" }],
  ["mine", "Raised by me", { scope: "mine" }],
  ["starred", "★ Starred", { scope: "all", starred: "true" }],
];
const EMP_TABS = [
  ["open", "Open", { scope: "mine", status: "open" }],
  ["waiting", "Awaiting my reply", { scope: "mine", status: "PENDING_EMPLOYEE" }],
  ["resolved", "Resolved", { scope: "mine", status: "RESOLVED" }],
  ["all", "All my tickets", { scope: "mine" }],
  ["starred", "★ Starred", { scope: "mine", starred: "true" }],
];
const VIEWER_TABS = [["all", "All tickets", { scope: "all", status: "open" }], ["mine", "Raised by me", { scope: "mine" }]];
const KEYS = ["q", "scope", "status", "priority", "category_id", "group_id", "assignee", "sla", "sort", "page",
  "requester", "starred", "department_id", "desk"];
const DESK_TABS = [["it", "IT tickets", "inbox"], ["erp", "ERP-IT tickets", "layers"], ["all", "All tickets", "ticket"]];

export async function render(view, _p, query) {
  const staff = isStaff();
  const tabs = staff ? STAFF_TABS : can("ticket.view_all") ? VIEWER_TABS : EMP_TABS;
  const hasExplicit = KEYS.some((k) => query[k]);
  const f = hasExplicit ? { scope: "all", ...query } : { ...tabs[0][2] };
  // IT administrators start on their own department (IT or ERP-IT); "All tickets" shows both
  if (staff && !f.desk) f.desk = state.me.desk || "all";
  if (!staff && !can("ticket.view_all") && !can("ticket.view_department")) f.scope = "mine";
  const activeTab = () => tabs.find(([, , p]) => Object.keys(p).every((k) => String(f[k] ?? "") === String(p[k]))
    && ["priority", "category_id", "sla", "q", "group_id", "requester", "department_id"].every((k) => !f[k])
    && (p.assignee || !f.assignee) && (p.starred || !f.starred))?.[0];

  const canAssign = can("ticket.assign");
  const cols = canAssign ? 9 : 8;
  let admins = [];
  const [cat, groups, depts] = await Promise.all([catalog(), staff || can("dashboard.ops") ? supportGroups() : [],
    staff ? api.get("/departments").catch(() => []) : [],
    canAssign ? api.get("/it-admins").then((a) => { admins = a; }).catch(() => {}) : null]);
  mount(view, html`
    <div class="page-head">
      <div><h1>${staff || can("ticket.view_all") ? "Tickets" : "My tickets"}</h1>
        <div class="sub">${canAssign ? "Search by employee ID or name, click a requester to see all their tickets, ★ to star, ⋮ to assign. Green rows are new tickets you haven't opened yet." : "Track the status of everything you have raised. Click ★ to star a ticket."}</div></div>
      <div class="row">
        ${can("report.export") ? html`<button class="btn" id="exp" title="Download the tickets shown (all pages) as a formatted Excel file">${icon("download")} Export to Excel</button>` : ""}
        <a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a></div>
    </div>
    ${staff ? html`<div class="desk-switch" role="tablist" aria-label="IT department" id="desk-switch">
      ${DESK_TABS.map(([v, l, ic]) => html`<button role="tab" data-desk="${v}">${icon(ic)}<span>${l}</span><span class="n" id="dcount-${v}"></span></button>`)}</div>` : ""}
    <div class="card">
      <div class="tabs" role="tablist" id="tabs">${tabs.map(([k, l]) => html`<button role="tab" data-tab="${k}">${l}</button>`)}</div>
      <div class="toolbar">
        <div class="search-inline ${staff ? "wide" : ""}">${icon("search")}<input type="search" id="f-q" placeholder="${staff ? "Search ticket no., subject, employee ID, name, email…" : "Ticket number or subject"}" value="${f.q || ""}" aria-label="Search tickets"></div>
        ${staff ? html`<div class="search-inline emp-filter" title="Show every ticket raised by one employee">${icon("user")}<input type="search" id="f-req" placeholder="Employee ID" value="${f.requester || ""}" aria-label="Raised by employee ID"></div>
          ` : ""}
        <button type="button" class="btn tb-toggle" id="tb-toggle" aria-expanded="false">${icon("filter")} Filters</button>
        <div class="tb-more">
        ${staff && depts.length ? html`<select id="f-dept" aria-label="Department"><option value="">Any department</option>${depts.map((d) => html`<option value="${d.id}">${d.name}</option>`)}</select>` : ""}
        <select id="f-status" aria-label="Status"><option value="">Any status</option><option value="open">All open</option>
          ${cat.statuses.map((s) => html`<option value="${s.code}">${s.name}</option>`)}</select>
        <select id="f-priority" aria-label="Priority"><option value="">Any priority</option>
          ${cat.priorities.map((p) => html`<option value="${p.code}">${p.code} · ${p.name}</option>`)}<option value="P1,P2">P1 + P2</option></select>
        <select id="f-category" aria-label="Category"><option value="">Any category</option>
          ${cat.categories.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select>
        ${groups.length ? html`<select id="f-group" aria-label="Support group"><option value="">Any group</option>
          ${groups.map((g) => html`<option value="${g.id}">${g.name}</option>`)}</select>` : ""}
        <select id="f-sla" aria-label="Due time"><option value="">Any due time</option><option value="at_risk">Due within 4 hours</option><option value="breached">Overdue</option></select>
        <span class="spacer"></span>
        <select id="f-sort" aria-label="Sort"><option value="updated_desc">Recently updated</option><option value="created_desc">Newest</option>
          <option value="created_asc">Oldest</option><option value="priority">Priority</option><option value="due">Due soonest</option></select>
        </div>
      </div>
      <div id="req-chip"></div>
      <div class="table-wrap"><table class="data tlist ${canAssign ? "compact-admin" : ""}">
        <thead><tr><th class="star-col"><span class="sr-only">Starred</span></th><th>Ticket</th><th>Subject</th><th>Status</th><th>Priority</th>
          <th class="hide-sm">${staff ? "Requester" : "Category"}</th><th class="hide-sm">${staff ? "Assignee" : "Assigned to"}</th>
<th class="hide-sm ${canAssign ? "hide-md" : ""}">Updated</th>${canAssign ? html`<th class="row-menu"><span class="sr-only">Actions</span></th>` : ""}</tr></thead>
        <tbody id="rows">${skeletonRows(8, cols)}</tbody></table></div>
      <div class="pager" id="pager"></div>
    </div>`);

  const sel = { status: "#f-status", priority: "#f-priority", category_id: "#f-category", group_id: "#f-group", sla: "#f-sla", sort: "#f-sort", department_id: "#f-dept" };
  for (const [k, s] of Object.entries(sel)) { const el = $(s, view); if (el && f[k]) el.value = f[k]; }

  const syncTabs = () => {
    const a = activeTab(); $$("#tabs button", view).forEach((b) => b.classList.toggle("on", b.dataset.tab === a));
    $("#tb-toggle", view).addEventListener("click", (e) => {
    const tb = e.currentTarget.closest(".toolbar"); const open = tb.classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", open);
  });
  $$("#desk-switch button", view).forEach((b) => b.classList.toggle("on", b.dataset.desk === (f.desk || "all")));
  };
  const pushUrl = () => {
    const q = new URLSearchParams();
    KEYS.forEach((k) => { if (f[k] && !(k === "page" && f[k] === 1)) q.set(k, f[k]); });
    if (!view.isConnected) return;
    history.replaceState(null, "", `#/tickets${q.toString() ? "?" + q : ""}`);
  };

  async function load() {
    syncTabs(); pushUrl();
    mount($("#rows", view), skeletonRows(6, cols));
    try {
      const page = Number(f.page || 1);
      const r = await api.get("/tickets", { ...Object.fromEntries(KEYS.filter((k) => k !== "page").map((k) => [k, f[k]])), page, page_size: 25 });
      if (!$("#rows", view)?.isConnected) return;
      mount($("#req-chip", view), f.requester ? html`<div class="filter-chip-bar">${icon("user")}
        Showing tickets raised by <b>${r.items[0]?.requester_code?.toUpperCase() === f.requester.toUpperCase() ? r.items[0].requester : "employee"}</b>
        <span class="emp-id">${f.requester}</span> · ${r.total} ticket${r.total === 1 ? "" : "s"}
        <button class="btn sm ghost" id="req-clear">${icon("x")} Clear</button></div>` : "");
      $("#req-clear", view)?.addEventListener("click", () => { delete f.requester; $("#f-req", view).value = ""; f.page = 1; load(); });
      mount($("#rows", view), r.items.length ? html`${r.items.map((t) => html`
        <tr class="clickable ${t.is_new ? "row-new" : ""}" data-href="#/tickets/${t.number}" tabindex="0">
          <td class="star-col c-star"><button class="star-btn ${t.starred ? "on" : ""}" data-star="${t.number}" aria-pressed="${t.starred}"
            title="${t.starred ? "Starred — click to remove" : "Star this ticket"}" aria-label="Star ${t.number}">${icon("star")}</button></td>
          <td class="c-id"><span class="t-id">${t.number}</span>${t.is_new ? html`<span class="new-pill">New</span>` : ""}</td>
          <td class="c-subj"><span class="t-subject" title="${t.subject}">${t.subject}</span><span class="t-sub2">${deskBadge(t.desk)} ${staff ? t.category : t.ticket_type === "incident" ? "Incident" : "Service request"}${canAssign ? html` · ${fmtRelative(t.updated_at)}` : ""}</span></td>
          <td class="c-status">${statusBadge(t.status)}</td><td class="c-prio">${prioBadge(t.priority.code)}</td>
          <td class="hide-sm c-req" data-label="${staff ? "Raised by" : "Category"}">${staff ? html`<a class="req-link name-id" data-req="${t.requester_code || ""}" title="Show all tickets raised by ${t.requester}">${t.requester}${empId(t.requester_code)}</a><div class="t-sub2">${t.department || ""}</div>` : t.category}</td>
          <td class="hide-sm c-asg" data-label="Assigned to">${t.assignee ? html`<span class="name-id">${t.assignee}${empId(t.assignee_code)}</span>` : html`<span class="muted">Unassigned</span>`}</td>

          <td class="hide-sm muted c-upd ${canAssign ? "hide-md" : ""}" title="${fmtDate(t.updated_at)}">${fmtRelative(t.updated_at)}</td>
          ${canAssign ? html`<td class="row-menu c-menu">${["CLOSED", "CANCELLED"].includes(t.status.code) ? "" :
            html`<button class="kebab" data-menu="${t.number}" aria-haspopup="menu" aria-expanded="false"
              aria-label="Assign ${t.number}" title="Assign ticket">${icon("more")}</button>`}</td>` : ""}</tr>`)}` :
        html`<tr><td colspan="${cols}">${emptyState("No tickets match", "Try a different tab or clear the filters.", "inbox")}</td></tr>`);
      rows = Object.fromEntries(r.items.map((t) => [t.number, t]));
      $$("tr[data-href]", view).forEach((tr) => {
        tr.addEventListener("click", (e) => { if (!e.target.closest(".row-menu, .star-col, .req-link")) location.hash = tr.dataset.href; });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") location.hash = tr.dataset.href; });
      });
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      const from = r.total ? (r.page - 1) * r.page_size + 1 : 0;
      mount($("#pager", view), html`<span>${from}–${Math.min(r.total, r.page * r.page_size)} of ${r.total}</span>
        <div class="row"><button class="btn sm" id="pv" ${r.page <= 1 ? "disabled" : ""}>Previous</button>
        <span>Page ${r.page} of ${pages}</span><button class="btn sm" id="nx" ${r.page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { f.page = r.page - 1; load(); });
      $("#nx", view).addEventListener("click", () => { f.page = r.page + 1; load(); });
    } catch (e) { errorToast(e); mount($("#rows", view), html`<tr><td colspan="${cols}">${emptyState("Could not load tickets", e.message, "alert")}</td></tr>`); }
  }

  $$("#desk-switch button", view).forEach((b) => b.addEventListener("click", () => { f.desk = b.dataset.desk; f.page = 1; load(); }));
  $$("#tabs button", view).forEach((b) => b.addEventListener("click", () => {
    const preset = tabs.find((t) => t[0] === b.dataset.tab)[2];
    KEYS.forEach((k) => { if (k !== "sort" && k !== "desk") delete f[k]; });
    Object.assign(f, preset);
    for (const [k, s] of Object.entries(sel)) { const el = $(s, view); if (el && k !== "sort") el.value = f[k] || ""; }
    $("#f-q", view).value = ""; if ($("#f-req", view)) $("#f-req", view).value = "";
    load();
  }));
  for (const [k, s] of Object.entries(sel)) {
    $(s, view)?.addEventListener("change", (e) => { f[k] = e.target.value; f.page = 1; load(); });
  }
  $("#f-q", view).addEventListener("input", debounce((e) => { f.q = e.target.value.trim(); f.page = 1; load(); }, 300));
  $("#f-req", view)?.addEventListener("input", debounce((e) => { f.requester = e.target.value.trim(); f.page = 1; load(); }, 350));
  // ★ star toggle and "click a requester to see all their tickets"
  const onRowAction = async (e) => {
    const star = e.target.closest("[data-star]");
    if (star) {
      e.stopPropagation();
      const on = !star.classList.contains("on");
      star.classList.toggle("on", on); star.setAttribute("aria-pressed", on);
      try { await api.put(`/tickets/${star.dataset.star}/star`, { starred: on }); if (f.starred && !on) load(); }
      catch (ex) { star.classList.toggle("on", !on); errorToast(ex); }
      return;
    }
    const req = e.target.closest("[data-req]");
    if (req && req.dataset.req) {
      e.stopPropagation();
      KEYS.forEach((k) => { if (!["sort", "desk"].includes(k)) delete f[k]; });
      Object.assign(f, { scope: "all", requester: req.dataset.req });
      for (const [k, s2] of Object.entries(sel)) { const el = $(s2, view); if (el && k !== "sort") el.value = ""; }
      $("#f-q", view).value = ""; if ($("#f-req", view)) $("#f-req", view).value = req.dataset.req;
      load();
    }
  };
  view.addEventListener("click", onRowAction, true);
  $("#exp", view)?.addEventListener("click", async () => {
    const btn = $("#exp", view); btn.disabled = true;
    try { await api.download("/tickets/export.xlsx", Object.fromEntries(KEYS.filter((k) => k !== "page").map((k) => [k, f[k]])), "tickets.xlsx"); toast("Excel file downloaded."); }
    catch (e) { errorToast(e); } finally { btn.disabled = false; }
  });
  // ------------------------------------------------------------- ⋮ assign menu
  let rows = {};
  let menu = null;
  const onScroll = (e) => { if (menu && !menu.el.contains(e.target)) closeMenu(); };
  const closeMenu = () => {
    window.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("resize", closeMenu);
    if (!menu) return;
    menu.el.remove();
    menu.btn.setAttribute("aria-expanded", "false");
    menu = null;
  };
  async function assignTo(t, admin) {
    closeMenu();
    try {
      await api.post(`/tickets/${t.number}/assign`, { assignee_id: admin ? admin.id : null, expected_version: t.version });
      toast(admin ? `${t.number} assigned to ${admin.full_name}.` : `${t.number} unassigned.`);
      api.get("/it-admins").then((a) => { admins = a; }).catch(() => {});
      load();
    } catch (e) {
      if (e.status === 409) { toast("Someone else just updated this ticket — list refreshed.", "info"); load(); }
      else errorToast(e);
    }
  }
  function openMenu(btn) {
    const t = rows[btn.dataset.menu];
    if (!t) return;
    closeMenu();
    const el = document.createElement("div");
    el.className = "pop-menu";
    el.setAttribute("role", "menu");
    mount(el, html`<div class="pm-head">Assign ${t.number} to</div>
      ${admins.length ? admins.map((a) => html`<button role="menuitem" data-id="${a.id}">
        <span class="tick">${a.id === t.assignee_id ? icon("check") : ""}</span>
        <span class="avatar sm">${initials(a.full_name)}</span>
        <span class="grow"><b>${a.full_name}</b><span>${a.employee_code ? `ID ${a.employee_code} · ` : ""}${a.job_title || "IT Administrator"}</span></span>
        <span class="load" title="Open tickets">${a.open_tickets} open</span></button>`) :
        html`<div class="muted small" style="padding:8px 10px">No IT administrators found.</div>`}
      ${t.assignee_id ? html`<hr><button role="menuitem" data-id="none"><span class="tick"></span>${icon("x")}<span class="grow"><b>Unassign</b><span>Return to the IT queue</span></span></button>` : ""}
      <hr><button role="menuitem" data-open="1"><span class="tick"></span>${icon("ticket")}<span class="grow"><b>Open ticket</b></span></button>`);
    document.body.appendChild(el);
    const r = btn.getBoundingClientRect();
    const h = el.offsetHeight;
    el.style.left = `${Math.max(8, Math.min(window.innerWidth - el.offsetWidth - 8, r.right - el.offsetWidth))}px`;
    el.style.top = `${r.bottom + 6 + h > window.innerHeight ? Math.max(8, r.top - h - 6) : r.bottom + 6}px`;
    btn.setAttribute("aria-expanded", "true");
    menu = { el, btn };
    // close if the page scrolls (attached after the click settles so the opening scroll doesn't close it)
    setTimeout(() => { if (menu?.el === el) { window.addEventListener("scroll", onScroll, true); window.addEventListener("resize", closeMenu); } }, 120);
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.open) { closeMenu(); location.hash = `#/tickets/${t.number}`; return; }
      const id = b.dataset.id;
      if (id === "none") return assignTo(t, null);
      const a = admins.find((x) => String(x.id) === id);
      if (a && a.id !== t.assignee_id) assignTo(t, a); else closeMenu();
    });
    el.addEventListener("keydown", (e) => {
      const items = $$("button", el);
      const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      if (e.key === "Escape") { closeMenu(); btn.focus(); }
    });
    $("button", el)?.focus();
  }
  const onKebab = (e) => {
    const btn = e.target.closest(".kebab");
    if (!btn) return;
    e.stopPropagation();
    if (menu && menu.btn === btn) closeMenu(); else openMenu(btn);
  };
  view.addEventListener("click", onKebab);
  const outside = (e) => { if (menu && !menu.el.contains(e.target) && !e.target.closest(".kebab")) closeMenu(); };
  document.addEventListener("click", outside);

  await load();
  return () => {
    closeMenu();
    view.removeEventListener("click", onKebab);
    view.removeEventListener("click", onRowAction, true);
    document.removeEventListener("click", outside);
  };
}
