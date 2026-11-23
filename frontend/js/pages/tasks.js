// Task management: overview (management home), task lists / board, new task, task page.
import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, toast, errorToast, emptyState, skeletonRows, debounce,
  initials, empId, openModal, busy, showFieldErrors } from "../ui.js";
import { navigate, refreshTaskAccess } from "../app.js";

export const PRIO = { high: ["High", "danger"], medium: ["Medium", "warn"], low: ["Low", "info"] };
const STATUS = {
  not_started: ["Not started", "neutral"], in_progress: ["In progress", "info"],
  waiting_approval: ["Waiting for approval", "warn"], completed: ["Completed", "ok"], cancelled: ["Cancelled", "neutral"],
};
const prioPill = (p) => html`<span class="tk-pill tone-${PRIO[p][1]}">${PRIO[p][0]}</span>`;
const statusPill = (s) => html`<span class="tk-pill tone-${STATUS[s][1]}">${STATUS[s][0]}</span>`;
const bar = (pct, tone = "") => html`<span class="tk-bar ${tone}" title="${pct}% done"><i style="width:${Math.max(pct, 2)}%"></i></span>`;
const who = (u) => u ? html`<span class="tk-who"><span class="avatar">${initials(u.name)}</span><span>${u.name}${empId(u.employee_code)}</span></span>` : "—";

function dueText(t) {
  if (!t.due_at) return html`<span class="tk-due"><span class="muted">No deadline</span></span>`;
  const d = new Date(t.due_at), now = new Date();
  const days = Math.round((d - now) / 86400000);
  let rel, tone = "";
  const calDays = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  if (t.status === "completed" || t.status === "cancelled") rel = "";
  else if (t.overdue) { const late = Math.max(1, Math.round((now - d) / 86400000)); rel = `${late} day${late > 1 ? "s" : ""} late`; tone = "late"; }
  else if (calDays <= 0) { rel = "due today"; tone = "soon"; }
  else if (calDays === 1) { rel = "due tomorrow"; tone = "soon"; }
  else { rel = `in ${calDays} days`; tone = calDays <= 2 ? "soon" : ""; }
  return html`<span class="tk-due ${tone}"><span>${fmtDate(t.due_at)}</span>${rel ? html`<b>${rel}</b>` : ""}</span>`;
}

const greet = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

// ======================================================================= overview (management home)
export async function renderOverview(view, _p, query = {}) {
  const acc = state.tasks || {};
  if (!acc.can_assign) return navigate("/tasks/list?view=to_me");
  try { localStorage.setItem("sd-mode", "tasks"); } catch { /* storage blocked */ }
  let scope = query.scope === "all" && acc.sees_all ? "all" : "mine";
  mount(view, html`${taskTabs("overview")}<div class="page-head tk-hello"><div><h1>${greet()}, ${state.me.full_name.split(" ")[0]}</h1>
      <div class="sub" id="ov-sub">Your team's tasks at a glance.</div></div>
    <div class="row">${acc.sees_all ? html`<div class="seg" id="ov-scope"><button data-v="mine" class="${scope === "mine" ? "on" : ""}">Assigned by me</button>
      <button data-v="all" class="${scope === "all" ? "on" : ""}">Whole company</button></div>` : ""}
      <a class="btn tk-green" href="#/tasks/new">${icon("plus")} Create</a></div></div>
    <div id="ov-body"><div class="card"><div class="card-body">${skeletonRows(4, 4)}</div></div></div>`);

  async function load() {
    try {
      const d = await api.get("/tasks/overview", { scope });
      if (!$("#ov-body", view)?.isConnected) return;
      const T = d.tiles;
      const list = (q) => `#/tasks/list?layout=list&view=${scope === "all" ? "all" : "by_me"}&${q.replace("status=overdue", "status=open&overdue=1")}`;
      $("#ov-sub", view).textContent = scope === "all" ? "Every task in the company." : "Tasks you assigned, and how your team is doing.";
      const tile = (label, value, foot, href, tone = "") => html`<a class="kpi tk-kpi ${tone}" href="${href}">
        <div class="label">${label}</div><div class="value">${value}</div><div class="foot">${foot}</div></a>`;
      mount($("#ov-body", view), html`
        <div class="tk-kpis">
          ${tile("Overdue", T.overdue, "past the deadline", list("status=overdue"), T.overdue ? "alert" : "")}
          ${tile("Due this week", T.due_this_week, "next 7 days", list("status=open&sort=due"))}
          ${tile("Waiting for your approval", T.waiting_approval, "marked complete by the assignee", list("status=waiting_approval"), T.waiting_approval ? "warn" : "")}
          ${tile("On-time completion", T.on_time_percent === null ? "—" : html`${T.on_time_percent}<small>%</small>`, `${T.completed_30} completed · last 30 days`, list("status=completed"))}
          ${tile("Open tasks", T.open, "not started, in progress or waiting", list("status=open"))}
        </div>
        <div class="tk-grid">
          <div class="card tk-panel"><div class="card-head"><h2>${icon("alert")} Needs your attention</h2><span class="hint">${d.attention.length}</span></div>
            <div class="card-body flush">${d.attention.length ? html`<ul class="tk-att">${d.attention.map((a) => html`<li>
              <a href="#/tasks/${a.task.number}"><span class="tk-att-tag k-${a.kind}">${a.label}</span>
                <b>${a.task.title}</b><span class="muted small">${peopleText(a.task.assignees)} · ${a.task.progress}%${a.task.due_at ? ` · due ${fmtDate(a.task.due_at, false)}` : ""}</span></a></li>`)}</ul>`
              : html`<div class="tk-empty">${icon("checkCircle")} Nothing needs you right now.</div>`}</div></div>
          <div class="card tk-panel"><div class="card-head"><h2>${icon("calendar")} Deadlines in the next 7 days</h2></div>
            <div class="card-body flush">${d.upcoming.length ? html`<ul class="tk-att">${d.upcoming.map((t) => html`<li>
              <a href="#/tasks/${t.number}">${prioPill(t.priority)}<b>${t.title}</b><span class="muted small">${peopleText(t.assignees)} · ${t.progress}%</span>${dueText(t)}</a></li>`)}</ul>`
              : html`<div class="tk-empty">${icon("calendar")} No deadlines this week.</div>`}</div></div>
        </div>
        <div class="card tk-panel"><div class="card-head"><h2>${icon("users")} Team progress</h2><span class="hint">open tasks per person</span></div>
          <div class="card-body flush table-wrap">${d.team.length ? html`<table class="data tk-team"><thead><tr><th>Person</th><th class="num">Open</th>
            <th class="num">Overdue</th><th class="num hide-sm">Waiting approval</th><th>Average progress</th></tr></thead><tbody>
            ${d.team.map((r) => html`<tr class="clickable" data-href="${list(`status=open&assignee_id=${r.user.id}`)}">
              <td>${who(r.user)}${r.user.department ? html`<div class="t-sub2">${r.user.department}</div>` : ""}</td>
              <td class="num">${r.open}</td><td class="num ${r.overdue ? "tk-red" : ""}">${r.overdue}</td>
              <td class="num hide-sm">${r.waiting_approval}</td><td>${bar(r.avg_progress, r.overdue ? "late" : "")} <span class="small">${r.avg_progress}%</span></td></tr>`)}
            </tbody></table>` : html`<div class="tk-empty">${icon("users")} No open tasks yet. <a href="#/tasks/new">Assign the first one</a>.</div>`}</div></div>
        <div class="card tk-panel"><div class="card-head"><h2>${icon("activity")} Latest updates</h2></div>
          <div class="card-body flush">${d.feed.length ? html`<ul class="tk-feed">${d.feed.map((e) => html`<li>
            <span class="avatar">${initials(e.author?.name || "S")}</span>
            <div><div>${eventLine(e)} <a href="#/tasks/${e.task.number}">${e.task.title}</a></div>
              ${e.body ? html`<div class="tk-feed-body">${e.body}</div>` : e.private ? html`<div class="tk-feed-body tk-hidden">${icon("lock")} Private message</div>` : ""}
              <span class="muted small">${fmtRelative(e.created_at)}</span></div></li>`)}</ul>`
            : html`<div class="tk-empty">${icon("activity")} Updates from your team will appear here.</div>`}</div></div>`);
      $$("tr[data-href]", view).forEach((tr) => tr.addEventListener("click", () => { location.hash = tr.dataset.href; }));
    } catch (e) { errorToast(e); }
  }
  $("#ov-scope", view)?.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    scope = b.dataset.v;
    $$("#ov-scope button", view).forEach((x) => x.classList.toggle("on", x === b));
    history.replaceState(null, "", `#/tasks${scope === "all" ? "?scope=all" : ""}`);
    load();
  });
  await load();
}

function eventLine(e) {
  const n = html`<b>${e.author?.name || "System"}</b>`;
  switch (e.kind) {
    case "created": return html`${n} assigned the task to <b>${e.new_value}</b>`;
    case "progress": return html`${n} updated progress to <b>${e.progress}%</b>`;
    case "comment": return html`${n} wrote a message`;
    case "status": return e.new_value === "in_progress" ? html`${n} started working on the task` : html`${n} changed the status`;
    case "submitted": return html`${n} marked it complete and asked for approval`;
    case "completed": return html`${n} completed the task`;
    case "approved": return html`${n} approved the work${e.new_value ? html` · <b>${e.new_value}</b>` : ""}`;
    case "returned": return html`${n} sent it back with feedback`;
    case "cancelled": return html`${n} cancelled the task`;
    case "deadline": return e.new_value === "none" ? html`${n} removed the deadline` : html`${n} changed the deadline to <b>${fmtDate(e.new_value)}</b>`;
    case "title": return e.new_value ? html`${n} renamed the task to <b>${e.new_value}</b>` : html`${n} renamed the task`;
    case "description": return html`${n} changed the details`;
    case "priority": return html`${n} changed priority to <b>${e.new_value}</b>`;
    case "reassigned": return html`${n} changed the people${e.new_value ? html` · added <b>${e.new_value}</b>` : ""}${e.old_value ? html` · removed <b>${e.old_value}</b>` : ""}`;
    case "extension_requested": return html`${n} asked for more time, until <b>${fmtDate(e.new_value)}</b>`;
    case "extension_approved": return html`${n} approved more time — new deadline <b>${fmtDate(e.new_value)}</b>`;
    case "extension_declined": return html`${n} kept the deadline (more time not approved)`;
    default: return html`${n} updated the task`;
  }
}
const EV_ICON = { title: "edit", description: "edit", created: "plus", progress: "activity", comment: "send", status: "zap", submitted: "flag", completed: "checkCircle",
  approved: "checkCircle", returned: "refresh", cancelled: "x", deadline: "calendar", priority: "alert", reassigned: "user",
  extension_requested: "clock", extension_approved: "clock", extension_declined: "clock" };

// ======================================================================= top bar shared by the Tasks pages
export function taskTabs(active) {
  const acc = state.tasks || {};
  const tabs = [acc.can_assign && ["overview", "#/tasks", "Overview"], ["tasks", "#/tasks/list", "Tasks"],
    ["performance", "#/tasks/performance", "Performance"], ["analytics", "#/tasks/analytics", "Analytics"]].filter(Boolean);
  return html`<nav class="tk-top" aria-label="Task management">${tabs.map(([k, href, l]) => html`<a href="${href}" class="${k === active ? "on" : ""}">${l}
    ${k === "tasks" ? html`<span class="tk-top-n" id="tk-top-n" hidden></span>` : ""}</a>`)}</nav>`;
}

// ======================================================================= Tasks: toolbar + views
const VIEWS = [["list", "List"], ["deadline", "Deadline"], ["planner", "Planner"], ["calendar", "Calendar"], ["gantt", "Gantt"]];
const VIEW_TITLE = { list: "Tasks", deadline: "Deadline", planner: "Planner", calendar: "Calendar", gantt: "Gantt" };

function presets() {
  const a = state.tasks || {};
  return [
    ["ongoing", "Ongoing", { view: "mine", status: "open" }],
    a.can_assign && ["by_me", "Assigned by me", { view: "by_me", status: "open" }],
    ["to_me", "Assigned to me", { view: "to_me", status: "open" }],
    a.can_assign && ["approval", "Waiting for my approval", { view: "by_me", status: "waiting_approval" }],
    ["overdue", "Overdue", { view: "mine", status: "open", overdue: "1" }],
    ["unread", "With new comments", { view: "mine", status: "all", unread: "1" }],
    ["completed", "Completed", { view: "mine", status: "completed" }],
    a.sees_all && ["all", "All tasks in the company", { view: "all", status: "open" }],
  ].filter(Boolean);
}

// filter fields → readable chip labels
const STATUS_LABEL = { open: "Open", not_started: "Not started", in_progress: "In progress", waiting_approval: "Waiting approval",
  completed: "Completed", cancelled: "Cancelled", all: "Any status" };
const VIEW_LABEL = { mine: "Mine", to_me: "Assigned to me", by_me: "Assigned by me", all: "Whole company" };
const FILTER_KEYS = ["view", "status", "q", "assignee_id", "assigner_id", "priority", "category", "due_from", "due_to",
  "created_from", "created_to", "overdue", "no_deadline", "has_request", "unread"];

const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
function weekEnd(d) { const s = dayStart(d); return addDays(s, 7 - ((s.getDay() + 6) % 7)); }   // next Monday 00:00
function bucketOf(t, now = new Date()) {
  if (t.status === "completed" || t.status === "cancelled") return "completed";
  if (!t.due_at) return "none";
  const d = new Date(t.due_at);
  if (t.status !== "waiting_approval" && d < now) return "overdue";
  const today = dayStart(now), tomorrow = addDays(today, 1), we = weekEnd(now), nwe = addDays(we, 7);
  if (d < tomorrow) return "today";
  if (d < we) return "week";
  if (d < nwe) return "next";
  return "later";
}
const COLUMNS = [["overdue", "Overdue", "c-red"], ["today", "Due today", "c-orange"], ["week", "Due this week", "c-sky"],
  ["next", "Due next week", "c-teal"], ["later", "Due over two weeks", "c-blue"], ["none", "No deadline", "c-grey"],
  ["completed", "Completed", "c-done"]];
function quickDue(col) {   // deadline used when you add a task with "+" in a column (18:00 local)
  const now = new Date(), at = (d) => { const x = new Date(d); x.setHours(18, 0, 0, 0); return x; };
  if (col === "today") return at(now);
  if (col === "week") { const d = addDays(weekEnd(now), -3); return at(d < now ? now : d); }       // Friday
  if (col === "next") return at(addDays(weekEnd(now), 4));
  if (col === "later") return at(addDays(weekEnd(now), 14));
  return null;
}

const avatars = (list = []) => html`<span class="tk-avs">${list.slice(0, 3).map((u) => html`<span class="avatar" title="${u.name}">${initials(u.name)}</span>`)}
  ${list.length > 3 ? html`<span class="avatar more">+${list.length - 3}</span>` : ""}</span>`;
const peopleText = (list = []) => list.length > 1 ? `${list[0].name} +${list.length - 1}` : (list[0]?.name || "—");

function card(t) {
  return html`<a class="tk-card ${t.overdue ? "late" : ""}" href="#/tasks/${t.number}">
    <div class="tk-card-top">${prioPill(t.priority)}${t.unread ? html`<span class="tk-unread" title="New comments">${icon("send")} ${t.unread}</span>` : ""}
      <span class="mono small muted">${t.number}</span></div>
    <b>${t.private ? html`${icon("lock")} ` : ""}${t.title}</b>
    ${t.status !== "completed" ? bar(t.progress, t.overdue ? "late" : "") : ""}
    <div class="tk-card-foot">${avatars(t.assignees)}${t.status === "completed" ? statusPill(t.status) : t.due_at ? dueText(t) : html`<span class="muted small">No deadline</span>`}</div></a>`;
}

export async function renderList(view, _p, query = {}) {
  const acc = state.tasks || {};
  const ps = presets();
  let layout = VIEWS.some(([v]) => v === query.layout) ? query.layout : (localStorage.getItem("sd-task-layout") || "deadline");
  // filters come from the URL; old links (?view=to_me&status=overdue) still work
  const f = {};
  for (const k of FILTER_KEYS) if (query[k]) f[k] = query[k];
  let preset = query.preset || "";
  if (!Object.keys(f).length) {
    const pr = ps.find(([k]) => k === (preset || (acc.can_assign ? "by_me" : "to_me"))) || ps[0];
    preset = pr[0]; Object.assign(f, pr[2]);
  }
  if (f.status === "overdue") { f.status = "open"; f.overdue = "1"; }
  let monthOffset = 0, ganttOffset = 0, items = [], total = 0;

  mount(view, html`${taskTabs("tasks")}
    <div class="tk-bar1">
      <h1 id="tl-title">${VIEW_TITLE[layout]}</h1>
      ${acc.can_assign ? html`<div class="tk-create"><a class="btn tk-green" href="#/tasks/new">${icon("plus")} Create</a>
        <button class="btn tk-green tk-create-more" id="tl-create-more" aria-label="More create options">${icon("chevDown")}</button>
        <div class="tk-menu" id="tl-create-menu" hidden><a href="#/tasks/new">${icon("plus")} New task (full form)</a>
          <button type="button" data-quick="today">${icon("zap")} Quick task for today</button>
          <button type="button" data-quick="none">${icon("target")} Quick task, no deadline</button></div></div>` : ""}
      <div class="tk-presets"><button class="btn tk-glass" id="tl-preset">${icon("filter")} <span id="tl-preset-name"></span> <span class="tk-n" id="tl-total"></span> ${icon("chevDown")}</button>
        <div class="tk-menu" id="tl-preset-menu" hidden>${ps.map(([k, l]) => html`<button type="button" data-p="${k}">${l}</button>`)}</div></div>
      <div class="tk-filterbox" id="tl-fbox">
        <div class="tk-chips" id="tl-chips"></div>
        <input type="search" id="tl-q" placeholder="search" value="${f.q || ""}" aria-label="Search tasks">
        <button class="tk-icon" id="tl-adv" title="Advanced search" aria-label="Advanced search">${icon("sliders")}</button>
        <button class="tk-icon" id="tl-clear" title="Clear filters" aria-label="Clear filters">${icon("x")}</button>
      </div>
      <div class="tk-gear"><button class="tk-icon tk-glass" id="tl-gear" title="Settings" aria-label="Settings">${icon("settings")}</button>
        <div class="tk-menu right" id="tl-gear-menu" hidden>
          <div class="tk-menu-h">Open Tasks in</div>${VIEWS.map(([v, l]) => html`<button type="button" data-def="${v}">${l} view</button>`)}
          <label class="tk-menu-check"><input type="checkbox" id="tl-showdone"> Show “Completed” column</label></div></div>
    </div>
    <div class="tk-adv" id="tl-advp" hidden></div>
    <div class="tk-bar2">
      <div class="tk-views" role="tablist">${VIEWS.map(([v, l]) => html`<button role="tab" data-v="${v}" class="${v === layout ? "on" : ""}">${l}</button>`)}</div>
      <div class="tk-counters">
        <button class="tk-count red" id="tl-c-over" title="Show overdue tasks"><b id="tl-c-over-n">0</b> Overdue</button>
        <button class="tk-count" id="tl-c-com" title="Show tasks with new comments"><b id="tl-c-com-n">0</b> Comments</button>
        <button class="tk-count ghost" id="tl-readall">Mark all as read</button>
      </div>
    </div>
    <div id="tl-body" class="tk-body"></div>`);

  const showDone = () => localStorage.getItem("sd-task-done") !== "0";
  $("#tl-showdone", view).checked = showDone();

  // ---------- menus
  const menus = [["#tl-create-more", "#tl-create-menu"], ["#tl-preset", "#tl-preset-menu"], ["#tl-gear", "#tl-gear-menu"]];
  for (const [btn, menu] of menus) {
    $(btn, view)?.addEventListener("click", (e) => {
      e.stopPropagation();
      const m = $(menu, view), was = m.hidden;
      menus.forEach(([, x]) => { const el = $(x, view); if (el) el.hidden = true; });
      m.hidden = !was;
    });
  }
  const closeMenus = (e) => { if (!view.isConnected) return document.removeEventListener("click", closeMenus);
    if (!e.target.closest(".tk-menu")) menus.forEach(([, x]) => { const el = $(x, view); if (el) el.hidden = true; }); };
  document.addEventListener("click", closeMenus);

  $$("#tl-preset-menu [data-p]", view).forEach((b) => b.addEventListener("click", () => {
    const pr = ps.find(([k]) => k === b.dataset.p);
    preset = pr[0];
    for (const k of FILTER_KEYS) delete f[k];
    Object.assign(f, pr[2]);
    $("#tl-q", view).value = "";
    $("#tl-preset-menu", view).hidden = true;
    load();
  }));
  $$("#tl-gear-menu [data-def]", view).forEach((b) => b.addEventListener("click", () => {
    try { localStorage.setItem("sd-task-layout", b.dataset.def); } catch { /* */ }
    toast(`Tasks will open in ${VIEW_TITLE[b.dataset.def]} view.`); setLayout(b.dataset.def);
  }));
  $("#tl-showdone", view).addEventListener("change", (e) => { try { localStorage.setItem("sd-task-done", e.target.checked ? "1" : "0"); } catch { /* */ } draw(); });
  $$("[data-quick]", view).forEach((b) => b.addEventListener("click", () => quickTask(b.dataset.quick)));

  // ---------- filters, chips, advanced search
  function presetName() {
    const pr = ps.find(([k]) => k === preset);
    const same = pr && FILTER_KEYS.every((k) => (pr[2][k] || "") === (f[k] || ""));
    return same ? pr[1] : "Filtered";
  }
  function chips() {
    const out = [];
    const add = (k, label) => out.push(html`<span class="tk-chip">${label}<button type="button" data-x="${k}" aria-label="Remove">${icon("x")}</button></span>`);
    if (f.view && f.view !== "mine") add("view", `Role: ${VIEW_LABEL[f.view]}`);
    if (f.status && f.status !== "all") add("status", f.status.split(",").map((s) => STATUS_LABEL[s] || s).join(", "));
    if (f.overdue) add("overdue", "Overdue");
    if (f.unread) add("unread", "New comments");
    if (f.no_deadline) add("no_deadline", "No deadline");
    if (f.has_request) add("has_request", "More time asked");
    if (f.priority) add("priority", `Priority: ${f.priority.split(",").map((p) => PRIO[p][0]).join(", ")}`);
    if (f.category) add("category", `Category: ${f.category}`);
    if (f.assignee_id) add("assignee_id", `Person: ${f._assignee_name || "#" + f.assignee_id}`);
    if (f.assigner_id) add("assigner_id", `Assigned by: ${f._assigner_name || "#" + f.assigner_id}`);
    if (f.due_from || f.due_to) add("due", `Deadline ${f.due_from ? "from " + f.due_from.slice(0, 10) : ""} ${f.due_to ? "to " + f.due_to.slice(0, 10) : ""}`);
    if (f.created_from || f.created_to) add("created", `Created ${f.created_from ? "from " + f.created_from.slice(0, 10) : ""} ${f.created_to ? "to " + f.created_to.slice(0, 10) : ""}`);
    const shown = out.slice(0, 3);
    if (out.length > 3) shown.push(html`<span class="tk-chip more">${out.length - 3} more</span>`);
    mount($("#tl-chips", view), html`${shown}`);
    $$("[data-x]", view).forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const k = b.dataset.x;
      if (k === "due") { delete f.due_from; delete f.due_to; } else if (k === "created") { delete f.created_from; delete f.created_to; }
      else if (k === "view") f.view = "mine"; else if (k === "status") f.status = "all"; else delete f[k];
      load();
    }));
  }
  $("#tl-q", view).addEventListener("input", debounce((e) => { const v = e.target.value.trim(); if (v) f.q = v; else delete f.q; load(); }, 300));
  $("#tl-clear", view).addEventListener("click", () => {
    for (const k of FILTER_KEYS) delete f[k];
    f.view = "mine"; f.status = "open"; preset = "ongoing"; $("#tl-q", view).value = ""; load();
  });
  $("#tl-adv", view).addEventListener("click", () => { const p = $("#tl-advp", view); p.hidden = !p.hidden; if (!p.hidden) advanced(); });
  $("#tl-fbox", view).addEventListener("click", (e) => { if (e.target === $("#tl-fbox", view) || e.target.closest("#tl-chips")) $("#tl-adv", view).click(); });

  function advanced() {
    const p = $("#tl-advp", view);
    const st = new Set((f.status || "").split(",").filter(Boolean));
    const pr = new Set((f.priority || "").split(",").filter(Boolean));
    const d10 = (v) => (v || "").slice(0, 10);
    mount(p, html`<form id="adv" class="tk-adv-grid">
      <div class="tk-adv-h"><b>${icon("sliders")} Advanced search</b><span class="muted small">Combine any of these. Results update when you press “Search”.</span></div>
      <label class="field"><span class="lbl">Words in the title, number, category or person${acc.can_assign ? "" : ""}</span><input type="search" name="q" value="${f.q || ""}" placeholder="e.g. MIS, TSK-26-000012, Pune"></label>
      <label class="field"><span class="lbl">Role</span><select name="view">${[["mine", "Mine (assigned by or to me)"], ["to_me", "Assigned to me"],
        acc.can_assign && ["by_me", "Assigned by me"], acc.sees_all && ["all", "Whole company"]].filter(Boolean).map(([v, l]) => html`<option value="${v}" ${f.view === v ? "selected" : ""}>${l}</option>`)}</select></label>
      <div class="field"><span class="lbl">Status</span><div class="tk-checks">${Object.entries(STATUS_LABEL).filter(([k]) => k !== "all").map(([k, l]) => html`<label><input type="checkbox" name="st" value="${k}" ${st.has(k) ? "checked" : ""}> ${l}</label>`)}</div></div>
      <div class="field"><span class="lbl">Priority</span><div class="tk-checks">${Object.entries(PRIO).map(([k, [l]]) => html`<label><input type="checkbox" name="pr" value="${k}" ${pr.has(k) ? "checked" : ""}> ${l}</label>`)}</div></div>
      ${acc.can_assign ? html`<div class="field"><span class="lbl">Person on the task</span><div id="adv-person"></div></div>` : ""}
      ${acc.can_assign ? html`<div class="field"><span class="lbl">Assigned by</span><div id="adv-assigner"></div></div>` : ""}
      <label class="field"><span class="lbl">Category</span><input type="text" name="category" value="${f.category || ""}" placeholder="e.g. Finance"></label>
      <div class="field"><span class="lbl">Deadline between</span><div class="tk-range"><input type="date" name="due_from" value="${d10(f.due_from)}"><span>and</span><input type="date" name="due_to" value="${d10(f.due_to)}"></div></div>
      <div class="field"><span class="lbl">Created between</span><div class="tk-range"><input type="date" name="created_from" value="${d10(f.created_from)}"><span>and</span><input type="date" name="created_to" value="${d10(f.created_to)}"></div></div>
      <div class="field"><span class="lbl">Only</span><div class="tk-checks">
        <label><input type="checkbox" name="overdue" ${f.overdue ? "checked" : ""}> Overdue</label>
        <label><input type="checkbox" name="unread" ${f.unread ? "checked" : ""}> With new comments</label>
        <label><input type="checkbox" name="no_deadline" ${f.no_deadline ? "checked" : ""}> No deadline</label>
        <label><input type="checkbox" name="has_request" ${f.has_request ? "checked" : ""}> More time asked</label></div></div>
      <div class="tk-adv-foot"><button type="button" class="btn" id="adv-reset">Reset</button><button class="btn primary" type="submit">${icon("search")} Search</button></div>
    </form>`);
    let who = f.assignee_id ? { id: Number(f.assignee_id), name: f._assignee_name || `#${f.assignee_id}` } : null;
    let by = f.assigner_id ? { id: Number(f.assigner_id), name: f._assigner_name || `#${f.assigner_id}` } : null;
    if ($("#adv-person", p)) personPicker($("#adv-person", p), (u) => { who = u; }, who);
    if ($("#adv-assigner", p)) personPicker($("#adv-assigner", p), (u) => { by = u; }, by);
    $("#adv-reset", p).addEventListener("click", () => { for (const k of FILTER_KEYS) delete f[k]; f.view = "mine"; f.status = "open"; p.hidden = true; $("#tl-q", view).value = ""; load(); });
    $("#adv", p).addEventListener("submit", (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      for (const k of FILTER_KEYS) delete f[k];
      const val = (k) => (fd.get(k) || "").trim();
      f.view = val("view") || "mine";
      const sts = fd.getAll("st"); f.status = sts.length ? sts.join(",") : "all";
      const prs = fd.getAll("pr"); if (prs.length) f.priority = prs.join(",");
      if (val("q")) f.q = val("q");
      if (val("category")) f.category = val("category");
      const iso = (d, end) => d ? new Date(`${d}T${end ? "23:59:59" : "00:00:00"}`).toISOString() : null;
      if (val("due_from")) f.due_from = iso(val("due_from")); if (val("due_to")) f.due_to = iso(val("due_to"), true);
      if (val("created_from")) f.created_from = iso(val("created_from")); if (val("created_to")) f.created_to = iso(val("created_to"), true);
      for (const k of ["overdue", "unread", "no_deadline", "has_request"]) if (fd.get(k)) f[k] = "1";
      if (who) { f.assignee_id = String(who.id); f._assignee_name = who.name; }
      if (by) { f.assigner_id = String(by.id); f._assigner_name = by.name; }
      $("#tl-q", view).value = f.q || "";
      p.hidden = true;
      load();
    });
  }

  // ---------- counters
  async function counters() {
    try {
      const c = await api.get("/tasks/counters");
      $("#tl-c-over-n", view).textContent = c.overdue; $("#tl-c-com-n", view).textContent = c.comments;
      $("#tl-c-over", view).classList.toggle("zero", !c.overdue); $("#tl-c-com", view).classList.toggle("zero", !c.comments);
      const n = $("#tk-top-n", view); if (n) { n.textContent = c.overdue + c.comments; n.hidden = !(c.overdue + c.comments); }
    } catch { /* ignore */ }
  }
  $("#tl-c-over", view).addEventListener("click", () => { for (const k of FILTER_KEYS) delete f[k]; Object.assign(f, { view: "mine", status: "open", overdue: "1" }); preset = "overdue"; load(); });
  $("#tl-c-com", view).addEventListener("click", () => { for (const k of FILTER_KEYS) delete f[k]; Object.assign(f, { view: "mine", status: "all", unread: "1" }); preset = "unread"; load(); });
  $("#tl-readall", view).addEventListener("click", async () => {
    try { const r = await api.post("/tasks/read-all"); toast(r.marked ? `Marked ${r.marked} task${r.marked > 1 ? "s" : ""} as read.` : "Nothing new to read."); counters(); load(); } catch (e) { errorToast(e); }
  });

  // ---------- views
  function setLayout(v) {
    layout = v;
    $$(".tk-views button", view).forEach((b) => b.classList.toggle("on", b.dataset.v === v));
    $("#tl-title", view).textContent = VIEW_TITLE[v];
    load();
  }
  $$(".tk-views button", view).forEach((b) => b.addEventListener("click", () => setLayout(b.dataset.v)));

  function params() {
    const q = { ...f };
    for (const k of Object.keys(q)) if (k.startsWith("_")) delete q[k];
    if (layout === "deadline" || layout === "planner" || layout === "calendar" || layout === "gantt") {
      // boards show finished work in its own column: include completed unless the filter is narrower
      if (q.status === "open") q.status = "open,completed";
    }
    return { ...q, sort: layout === "list" ? (f._sort || "due") : "due", page_size: layout === "list" ? 100 : 500 };
  }

  async function load() {
    const url = new URLSearchParams(Object.entries({ ...f, layout, preset }).filter(([k, v]) => v && !k.startsWith("_")));
    history.replaceState(null, "", `#/tasks/list?${url}`);
    $("#tl-preset-name", view).textContent = presetName();
    chips();
    mount($("#tl-body", view), html`<div class="tk-panel"><div class="card-body">${skeletonRows(5, 4)}</div></div>`);
    try {
      const r = await api.get("/tasks", params());
      if (!$("#tl-body", view)?.isConnected) return;
      items = r.items; total = r.total;
      $("#tl-total", view).textContent = total;
      draw();
    } catch (e) { errorToast(e); }
  }

  function draw() {
    const body = $("#tl-body", view);
    if (layout === "list") return drawList(body);
    if (layout === "deadline") return drawColumns(body, COLUMNS.filter(([k]) => k !== "completed" || showDone()), (t) => bucketOf(t), true);
    if (layout === "planner") return drawColumns(body, [["not_started", "Not started", "c-grey"], ["in_progress", "In progress", "c-sky"],
      ["waiting_approval", "Waiting for approval", "c-orange"], ["completed", "Completed", "c-done"]].filter(([k]) => k !== "completed" || showDone()),
      (t) => (t.status === "cancelled" ? "completed" : t.status), false);
    if (layout === "calendar") return drawCalendar(body);
    return drawGantt(body);
  }

  function drawList(body) {
    if (!items.length) return mount(body, html`<div class="tk-panel">${emptyState("No tasks here", "Nothing matches these filters.", "inbox")}</div>`);
    mount(body, html`<div class="tk-panel"><div class="table-wrap"><table class="data tk-table"><thead><tr><th>Task</th><th>Status</th><th>Deadline</th>
      <th class="hide-sm">Assigned by</th><th>People</th><th class="hide-sm">Priority</th><th class="hide-sm">Progress</th></tr></thead><tbody>
      ${items.map((t) => html`<tr class="clickable ${t.overdue ? "tk-row-late" : ""}" data-n="${t.number}">
        <td><a class="t-id" href="#/tasks/${t.number}">${t.number}</a>${t.unread ? html` <span class="tk-unread">${icon("send")} ${t.unread}</span>` : ""}
          <span class="t-sub2" style="display:block">${t.private ? html`${icon("lock")} ` : ""}${t.title}${t.category ? html` <span class="tk-cat">${t.category}</span>` : ""}</span></td>
        <td>${statusPill(t.status)}${t.has_extension_request ? html`<div class="t-sub2">${icon("clock")} more time asked</div>` : ""}</td>
        <td>${t.due_at ? dueText(t) : html`<span class="muted small">No deadline</span>`}</td>
        <td class="hide-sm">${who(t.assigner)}</td><td>${avatars(t.assignees)} <span class="small hide-sm">${peopleText(t.assignees)}</span></td>
        <td class="hide-sm">${prioPill(t.priority)}</td><td class="hide-sm">${bar(t.progress, t.overdue ? "late" : "")} <span class="small">${t.progress}%</span></td></tr>`)}
      </tbody></table></div>${total > items.length ? html`<div class="tk-more muted small">Showing ${items.length} of ${total}. Narrow the search to see the rest.</div>` : ""}</div>`);
    $$("tr[data-n]", body).forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) navigate(`/tasks/${tr.dataset.n}`); }));
  }

  function drawColumns(body, cols, keyOf, byDeadline) {
    const groups = Object.fromEntries(cols.map(([k]) => [k, []]));
    for (const t of items) { const k = keyOf(t); if (groups[k]) groups[k].push(t); }
    mount(body, html`<div class="tk-cols-wrap"><button class="tk-scroll left" aria-label="Scroll left">${icon("chevLeft")}</button>
      <div class="tk-cols">${cols.map(([k, l, c]) => html`<section class="tk-col2">
        <header class="tk-colh ${c}"><span>${l}</span><b>${groups[k].length}</b></header>
        ${acc.can_assign && k !== "completed" && k !== "overdue" && (byDeadline || k === "not_started") ? html`<button class="tk-add" data-add="${byDeadline ? k : "none"}" title="Quick task in “${l}”">${icon("plus")}</button>` : ""}
        <div class="tk-col2-body">${groups[k].map(card)}${groups[k].length ? "" : html`<div class="tk-col-empty">No tasks</div>`}</div></section>`)}</div>
      <button class="tk-scroll right" aria-label="Scroll right">${icon("chevRight")}</button></div>`);
    const sc = $(".tk-cols", body);
    $(".tk-scroll.left", body).addEventListener("click", () => sc.scrollBy({ left: -320, behavior: "smooth" }));
    $(".tk-scroll.right", body).addEventListener("click", () => sc.scrollBy({ left: 320, behavior: "smooth" }));
    $$("[data-add]", body).forEach((b) => b.addEventListener("click", () => quickTask(b.dataset.add)));
  }

  function drawCalendar(body) {
    const now = new Date(), first = new Date(now.getFullYear(), now.getMonth() + monthOffset, 1);
    const start = addDays(first, -((first.getDay() + 6) % 7));   // Monday before the 1st
    const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
    const byDay = {};
    const noDl = [];
    for (const t of items) {
      if (!t.due_at) { noDl.push(t); continue; }
      const d = dayStart(new Date(t.due_at)).getTime();
      (byDay[d] ||= []).push(t);
    }
    const monthName = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    const today = dayStart(now).getTime();
    mount(body, html`<div class="tk-panel tk-cal"><div class="tk-cal-head">
        <button class="btn sm" data-m="-1" aria-label="Previous month">${icon("chevLeft")}</button><b>${monthName}</b>
        <button class="btn sm" data-m="1" aria-label="Next month">${icon("chevRight")}</button>
        ${monthOffset ? html`<button class="btn sm ghost" data-m="0">Today</button>` : ""}</div>
      <div class="tk-cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => html`<div class="tk-cal-dow">${d}</div>`)}
        ${days.map((d) => { const list = byDay[d.getTime()] || [];
          return html`<div class="tk-cal-day ${d.getMonth() !== first.getMonth() ? "out" : ""} ${d.getTime() === today ? "today" : ""} ${list.length ? "has" : ""}">
            <span class="tk-cal-n">${d.getDate()}</span>
            ${list.slice(0, 3).map((t) => html`<a class="tk-cal-t ${t.overdue ? "late" : ""} ${t.status === "completed" ? "done" : ""} p-${t.priority}" href="#/tasks/${t.number}" title="${t.title}">${t.title}</a>`)}
            ${list.length > 3 ? html`<span class="tk-cal-more">+${list.length - 3} more</span>` : ""}</div>`; })}</div>
      <div class="tk-agenda">${days.filter((d) => d.getMonth() === first.getMonth() && (byDay[d.getTime()] || []).length).map((d) => html`<div class="tk-ag-day">
        <b>${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</b>${byDay[d.getTime()].map(card)}</div>`)}</div>
      ${noDl.length ? html`<div class="tk-cal-nodl"><b>No deadline</b> ${noDl.map((t) => html`<a href="#/tasks/${t.number}" class="tk-cal-t">${t.title}</a>`)}</div>` : ""}</div>`);
    $$("[data-m]", body).forEach((b) => b.addEventListener("click", () => { const m = Number(b.dataset.m); monthOffset = m ? monthOffset + m : 0; drawCalendar(body); }));
  }

  function drawGantt(body) {
    const now = new Date(), from = addDays(dayStart(now), -7 + ganttOffset * 14), DAYS = 35;
    const to = addDays(from, DAYS);
    const rows = items.filter((t) => {
      const s = new Date(t.started_at || t.created_at), e = t.due_at ? new Date(t.due_at) : (t.completed_at ? new Date(t.completed_at) : now);
      return e >= from && s < to;
    });
    const pct = (d) => Math.min(100, Math.max(0, (d - from) / (to - from) * 100));
    const days = Array.from({ length: DAYS }, (_, i) => addDays(from, i));
    mount(body, html`<div class="tk-panel tk-gantt"><div class="tk-cal-head">
        <button class="btn sm" data-g="-1" aria-label="Earlier">${icon("chevLeft")}</button>
        <b>${from.toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${addDays(to, -1).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</b>
        <button class="btn sm" data-g="1" aria-label="Later">${icon("chevRight")}</button>${ganttOffset ? html`<button class="btn sm ghost" data-g="0">Today</button>` : ""}</div>
      <div class="tk-g-scroll"><div class="tk-g">
        <div class="tk-g-row tk-g-headrow"><div class="tk-g-name">Task</div><div class="tk-g-track">${days.map((d) => html`<span class="tk-g-day ${d.getDay() === 0 || d.getDay() === 6 ? "we" : ""}" style="left:${pct(d)}%">${d.getDate()}</span>`)}
          <i class="tk-g-today" style="left:${pct(now)}%"></i></div></div>
        ${rows.length ? rows.map((t) => {
          const s = new Date(t.started_at || t.created_at), e = t.due_at ? new Date(t.due_at) : (t.completed_at ? new Date(t.completed_at) : now);
          const l = pct(s), w = Math.max(1.5, pct(e) - l);
          return html`<div class="tk-g-row"><a class="tk-g-name" href="#/tasks/${t.number}" title="${t.title}"><span>${t.title}</span><small>${peopleText(t.assignees)}</small></a>
            <div class="tk-g-track"><i class="tk-g-today" style="left:${pct(now)}%"></i>
              <a href="#/tasks/${t.number}" class="tk-g-bar s-${t.status} ${t.overdue ? "late" : ""} ${t.due_at ? "" : "open-end"}" style="left:${l}%;width:${w}%" title="${t.title} · ${t.progress}%">
                <i style="width:${t.progress}%"></i>${w > 4 ? html`<span>${t.progress}%</span>` : ""}</a></div></div>`;
        }) : html`<div class="tk-col-empty" style="padding:30px">No tasks in these dates.</div>`}
      </div></div></div>`);
    $$("[data-g]", body).forEach((b) => b.addEventListener("click", () => { const g = Number(b.dataset.g); ganttOffset = g ? ganttOffset + g : 0; drawGantt(body); }));
  }

  // ---------- quick task (from "+" in a column, or the Create menu)
  function quickTask(col) {
    const due = quickDue(col);
    let people = [{ id: state.me.id, name: state.me.full_name, employee_code: state.me.employee_code }];
    openModal({ title: "Quick task", subtitle: due ? `Deadline: ${fmtDate(due.toISOString())}` : "No deadline",
      body: html`<form id="qf" class="stack" style="gap:12px">
        <label class="field"><span class="lbl">What needs to be done?<span class="req">*</span></span><input type="text" name="title" maxlength="200" placeholder="Type and press Enter"></label>
        <div class="field"><span class="lbl">For</span><div id="qf-people"></div></div></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn tk-green" id="qf-ok">${icon("plus")} Add task</button>`,
      onMount: (el, close) => {
        multiPicker($("#qf-people", el), people, (list) => { people = list; });
        setTimeout(() => $("input[name=title]", el).focus(), 50);
        const go = async () => {
          const title = $("input[name=title]", el).value.trim();
          if (title.length < 3) return showFieldErrors($("#qf", el), { title: "At least 3 characters." });
          if (!people.length) return toast("Choose at least one person.", "info");
          busy($("#qf-ok", el));
          try {
            const t = await api.post("/tasks", { title, assignee_ids: people.map((u) => u.id), due_at: due ? due.toISOString() : null });
            close(); toast(`Task ${t.number} added.`); load(); counters();
          } catch (ex) { busy($("#qf-ok", el), false); errorToast(ex); }
        };
        $("#qf-ok", el).addEventListener("click", go);
        $("#qf", el).addEventListener("submit", (e) => { e.preventDefault(); go(); });
      } });
  }

  await Promise.all([load(), counters()]);
}

// ======================================================================= Performance
export async function renderPerformance(view, _p, query = {}) {
  const acc = state.tasks || {};
  let scope = ["me", "team", "all"].includes(query.scope) ? query.scope : "me";
  let days = query.days || "90";
  mount(view, html`${taskTabs("performance")}
    <div class="tk-bar1"><h1>Performance</h1>
      <div class="seg tk-glass-seg" id="pf-scope"><button data-v="me">Me</button>${acc.can_assign ? html`<button data-v="team">My team</button>` : ""}${acc.sees_all ? html`<button data-v="all">Company</button>` : ""}</div>
      <select id="pf-days" class="tk-glass-sel" aria-label="Period"><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last 12 months</option></select></div>
    <div id="pf-body"></div>`);
  $("#pf-days", view).value = days;
  const sync = () => $$("#pf-scope button", view).forEach((b) => b.classList.toggle("on", b.dataset.v === scope));
  async function load() {
    sync();
    history.replaceState(null, "", `#/tasks/performance?scope=${scope}&days=${days}`);
    mount($("#pf-body", view), html`<div class="tk-panel"><div class="card-body">${skeletonRows(4, 4)}</div></div>`);
    try {
      const a = await api.get("/tasks/analytics", { scope, days });
      const eff = a.efficiency;
      const ring = (v) => html`<div class="tk-ring" style="--p:${v ?? 0}"><b>${v === null ? "—" : `${v}%`}</b><span>efficiency</span></div>`;
      mount($("#pf-body", view), html`<div class="tk-pf-top tk-panel">${ring(eff)}
          <div><h2>${scope === "me" ? "Your performance" : scope === "team" ? "Your team's performance" : "Company performance"}</h2>
            <p class="muted">Efficiency = tasks completed on time ÷ (completed + overdue) in the period. Tasks without a deadline count as on time.</p>
            <div class="tk-pf-stats"><span><b>${a.totals.tasks}</b> tasks</span><span><b>${a.totals.completed}</b> completed</span>
              <span><b>${a.totals.open}</b> open</span><span class="${a.totals.overdue ? "tk-red" : ""}"><b>${a.totals.overdue}</b> overdue</span></div></div></div>
        ${a.people.length ? html`<div class="tk-panel"><div class="table-wrap"><table class="data"><thead><tr><th>Person</th><th class="num">Efficiency</th>
          <th class="num">Assigned</th><th class="num">Completed</th><th class="num hide-sm">On time</th><th class="num">Overdue</th>
          <th class="num hide-sm">Avg. days</th><th class="num hide-sm">Rating</th></tr></thead><tbody>
          ${a.people.map((r) => html`<tr><td>${who(r.user)}${r.user.department ? html`<div class="t-sub2">${r.user.department}</div>` : ""}</td>
            <td class="num"><b class="${r.efficiency !== null && r.efficiency < 60 ? "tk-red" : ""}">${r.efficiency === null ? "—" : r.efficiency + "%"}</b></td>
            <td class="num">${r.assigned}</td><td class="num">${r.completed}</td><td class="num hide-sm">${r.on_time}</td>
            <td class="num ${r.overdue ? "tk-red" : ""}">${r.overdue}</td><td class="num hide-sm">${r.avg_days ?? "—"}</td>
            <td class="num hide-sm">${r.avg_rating ? html`<span class="tk-stars">★</span> ${r.avg_rating}` : "—"}</td></tr>`)}
          </tbody></table></div></div>` : html`<div class="tk-panel">${emptyState("No tasks in this period", "Performance appears once tasks are assigned.", "target")}</div>`}`);
    } catch (e) { errorToast(e); }
  }
  $("#pf-scope", view).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { scope = b.dataset.v; load(); } });
  $("#pf-days", view).addEventListener("change", (e) => { days = e.target.value; load(); });
  await load();
}

// ======================================================================= Analytics
export async function renderAnalytics(view, _p, query = {}) {
  const acc = state.tasks || {};
  let scope = ["me", "team", "all"].includes(query.scope) ? query.scope : (acc.can_assign ? "team" : "me");
  let days = query.days || "90";
  mount(view, html`${taskTabs("analytics")}
    <div class="tk-bar1"><h1>Analytics</h1>
      <div class="seg tk-glass-seg" id="an-scope"><button data-v="me">Me</button>${acc.can_assign ? html`<button data-v="team">My team</button>` : ""}${acc.sees_all ? html`<button data-v="all">Company</button>` : ""}</div>
      <select id="an-days" class="tk-glass-sel" aria-label="Period"><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last 12 months</option></select></div>
    <div id="an-body"></div>`);
  $("#an-days", view).value = days;
  const hbars = (obj, labels = {}, tones = {}) => {
    const max = Math.max(1, ...Object.values(obj));
    const entries = Object.entries(obj);
    return entries.length ? html`<div class="tk-hbars">${entries.map(([k, v]) => html`<div class="tk-hbar"><span>${labels[k] || k}</span>
      <div><i class="${tones[k] || ""}" style="width:${(v / max) * 100}%"></i></div><b>${v}</b></div>`)}</div>` : html`<div class="tk-empty">No data yet.</div>`;
  };
  async function load() {
    $$("#an-scope button", view).forEach((b) => b.classList.toggle("on", b.dataset.v === scope));
    history.replaceState(null, "", `#/tasks/analytics?scope=${scope}&days=${days}`);
    mount($("#an-body", view), html`<div class="tk-panel"><div class="card-body">${skeletonRows(4, 4)}</div></div>`);
    try {
      const a = await api.get("/tasks/analytics", { scope, days });
      const maxW = Math.max(1, ...a.weeks.flatMap((w) => [w.created, w.completed]));
      const T = a.totals;
      mount($("#an-body", view), html`
        <div class="tk-kpis">${[["Tasks", T.tasks, ""], ["Completed", T.completed, ""], ["Open", T.open, ""], ["Overdue", T.overdue, T.overdue ? "alert" : ""],
          ["Efficiency", a.efficiency === null ? "—" : a.efficiency + "%", ""]].map(([l, v, c]) => html`<div class="kpi tk-kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div></div>`)}</div>
        <div class="tk-panel"><div class="card-head"><h2>${icon("activity")} Created vs completed, by week</h2>
            <span class="tk-legend"><i class="c1"></i>Created <i class="c2"></i>Completed</span></div>
          <div class="tk-weeks">${a.weeks.map((w) => html`<div class="tk-week"><div class="tk-wbars">
            <i class="c1" style="height:${(w.created / maxW) * 100}%" title="${w.created} created"></i>
            <i class="c2" style="height:${(w.completed / maxW) * 100}%" title="${w.completed} completed"></i></div>
            <span>${new Date(w.week).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span></div>`)}</div></div>
        <div class="tk-grid">
          <div class="tk-panel"><div class="card-head"><h2>${icon("target")} By status</h2></div><div class="card-body">${hbars(a.by_status,
            Object.fromEntries(Object.entries(STATUS).map(([k, [l]]) => [k, l])), { completed: "ok", cancelled: "neutral", waiting_approval: "warn", in_progress: "info" })}</div></div>
          <div class="tk-panel"><div class="card-head"><h2>${icon("alert")} By priority</h2></div><div class="card-body">${hbars(a.by_priority,
            { high: "High", medium: "Medium", low: "Low" }, { high: "danger", medium: "warn", low: "info" })}</div></div>
        </div>
        <div class="tk-panel"><div class="card-head"><h2>${icon("list")} By category</h2></div><div class="card-body">${hbars(a.by_category)}</div></div>`);
    } catch (e) { errorToast(e); }
  }
  $("#an-scope", view).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { scope = b.dataset.v; load(); } });
  $("#an-days", view).addEventListener("change", (e) => { days = e.target.value; load(); });
  await load();
}

// ======================================================================= new task
const pad = (n) => String(n).padStart(2, "0");
const localDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const toIso = (date, time) => new Date(`${date}T${time || "18:00"}`).toISOString();

/** Searchable single-person picker (anyone active). */
function personPicker(el, onPick, initial = null) {
  mount(el, html`<div class="tk-pick"><div class="tk-pick-in"><input type="search" placeholder="Type a name or employee ID, or pick from the list" aria-label="Assign to"></div>
    <div class="tk-pick-sel" hidden></div><ul class="tk-pick-list" hidden></ul></div>`);
  const input = $("input", el), list = $(".tk-pick-list", el), sel = $(".tk-pick-sel", el);
  const choose = (u) => {
    onPick(u);
    sel.hidden = !u; $(".tk-pick-in", el).hidden = !!u; list.hidden = true;
    if (u) mount(sel, html`${who({ name: u.name, employee_code: u.employee_code })}<span class="muted small">${[u.job_title, u.department].filter(Boolean).join(" · ")}</span>
      <button type="button" class="btn sm ghost">Change</button>`);
    $("button", sel)?.addEventListener("click", () => { choose(null); input.value = ""; input.focus(); search(""); });
  };
  const search = debounce(async (q) => {
    try {
      const r = await api.get("/tasks/people", { q: q || undefined });
      list.hidden = false;
      mount(list, r.length ? html`${r.map((u) => html`<li><button type="button" data-id="${u.id}">${who({ name: u.name, employee_code: u.employee_code })}
        <span class="muted small">${[u.job_title, u.department].filter(Boolean).join(" · ")}${u.is_management ? " · Management" : ""}</span></button></li>`)}`
        : html`<li class="muted small" style="padding:10px">No one found.</li>`);
      $$("button[data-id]", list).forEach((b) => b.addEventListener("click", () => choose(r.find((u) => String(u.id) === b.dataset.id))));
    } catch (e) { errorToast(e); }
  }, 250);
  input.addEventListener("input", () => search(input.value.trim()));
  input.addEventListener("focus", () => { if (list.hidden) search(input.value.trim()); });
  if (initial) choose(initial);
}

/** Several people: chips + search. onChange(list) gets the current list. */
function multiPicker(el, initial, onChange) {
  let list = [...(initial || [])];
  mount(el, html`<div class="tk-multi"><div class="tk-multi-box"><span class="tk-multi-chips"></span>
      <input type="search" placeholder="Add a person — type a name or employee ID" aria-label="Add a person"></div>
    <ul class="tk-pick-list" hidden></ul></div>`);
  const box = $(".tk-multi-chips", el), input = $("input", el), drop = $(".tk-pick-list", el);
  const paint = () => {
    mount(box, html`${list.map((u) => html`<span class="tk-chip person"><span class="avatar">${initials(u.name)}</span>${u.name}${empId(u.employee_code)}
      <button type="button" data-rm="${u.id}" aria-label="Remove ${u.name}">${icon("x")}</button></span>`)}`);
    $$("[data-rm]", box).forEach((b) => b.addEventListener("click", () => { list = list.filter((u) => String(u.id) !== b.dataset.rm); paint(); onChange(list); }));
    input.placeholder = list.length ? "Add another person" : "Add a person — type a name or employee ID";
  };
  const search = debounce(async (q) => {
    try {
      const r = (await api.get("/tasks/people", { q: q || undefined })).filter((u) => !list.some((x) => x.id === u.id));
      drop.hidden = false;
      mount(drop, r.length ? html`${r.map((u) => html`<li><button type="button" data-id="${u.id}">${who({ name: u.name, employee_code: u.employee_code })}
        <span class="muted small">${[u.job_title, u.department].filter(Boolean).join(" · ")}${u.is_management ? " · Management" : ""}</span></button></li>`)}`
        : html`<li class="muted small" style="padding:10px">No one else found.</li>`);
      $$("button[data-id]", drop).forEach((b) => b.addEventListener("click", () => {
        list.push(r.find((u) => String(u.id) === b.dataset.id)); paint(); onChange(list);
        input.value = ""; drop.hidden = true; input.focus();
      }));
    } catch (e) { errorToast(e); }
  }, 250);
  input.addEventListener("input", () => search(input.value.trim()));
  input.addEventListener("focus", () => search(input.value.trim()));
  input.addEventListener("keydown", (e) => { if (e.key === "Backspace" && !input.value && list.length) { list.pop(); paint(); onChange(list); } });
  document.addEventListener("click", function off(e) { if (!el.isConnected) return document.removeEventListener("click", off); if (!el.contains(e.target)) drop.hidden = true; });
  paint();
}

export async function renderNew(view) {
  const acc = state.tasks || {};
  if (!acc.can_assign) return navigate("/tasks/list");
  const tomorrow = new Date(Date.now() + 86400000);
  let people = [], priority = "medium";
  mount(view, html`${taskTabs("tasks")}<div class="tk-bar1"><h1>Assign a task</h1></div>
    <p class="tk-sub">Everyone you choose gets an email straight away and sees it under “My tasks”. Only you and them can read the details and messages.</p>
    <form class="card" id="tf" novalidate><div class="card-body stack" style="gap:16px">
      <label class="field"><span class="lbl">What needs to be done?<span class="req">*</span></span>
        <input type="text" name="title" maxlength="200" required placeholder="e.g. Prepare the monthly MIS report"></label>
      <label class="field"><span class="lbl">Details <span class="muted" style="font-weight:400">(optional)</span></span>
        <textarea name="description" rows="5" maxlength="8000" placeholder="What exactly you expect, the format, who to contact…"></textarea></label>
      <div class="field"><span class="lbl">Assign to — one or more people<span class="req">*</span></span><div id="tf-person"></div><div class="err" data-err="assignee_id"></div></div>
      <div class="grid grid-2" style="gap:14px" id="tf-due">
        <label class="field"><span class="lbl">Deadline date<span class="req">*</span></span><input type="date" name="due_date" value="${localDate(tomorrow)}" min="${localDate(new Date())}" required></label>
        <label class="field"><span class="lbl">Time</span><input type="time" name="due_time" value="18:00"></label>
      </div>
      <label class="check"><input type="checkbox" name="no_deadline" id="tf-nodl"> No deadline</label>
      <div class="field"><span class="lbl">Priority</span><div class="seg" id="tf-prio">
        <button type="button" data-v="high">High</button><button type="button" data-v="medium" class="on">Medium</button><button type="button" data-v="low">Low</button></div></div>
      <label class="field"><span class="lbl">Category <span class="muted" style="font-weight:400">(optional)</span></span>
        <input type="text" name="category" maxlength="60" list="tf-cats" placeholder="e.g. MIS, Site visit, Compliance">
        <datalist id="tf-cats"><option value="MIS / Reports"><option value="Site visit"><option value="Compliance"><option value="Finance"><option value="Purchase"><option value="HR"><option value="Follow-up"></datalist></label>
      <label class="check"><input type="checkbox" name="requires_approval" checked> I want to approve the work before it's marked complete</label>
    </div><div class="modal-foot"><a class="btn" href="#/tasks">Cancel</a><button class="btn primary" type="submit" data-busy>${icon("send")} Assign task</button></div></form>`);
  multiPicker($("#tf-person", view), [], (list) => { people = list; });
  $("#tf-nodl", view).addEventListener("change", (e) => { $("#tf-due", view).hidden = e.target.checked; });
  $("#tf-prio", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    priority = b.dataset.v; $$("#tf-prio button", view).forEach((x) => x.classList.toggle("on", x === b));
  });
  $("#tf", view).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget, v = Object.fromEntries(new FormData(f)), btn = $("button[type=submit]", f);
    const errs = {};
    if ((v.title || "").trim().length < 3) errs.title = "Write what needs to be done (at least 3 characters).";
    if (!people.length) errs.assignee_id = "Choose who should do this task (one or more people).";
    const noDl = !!v.no_deadline;
    if (!noDl && !v.due_date) errs.due_date = "Pick a deadline, or tick “No deadline”.";
    else if (!noDl && new Date(toIso(v.due_date, v.due_time)) < new Date()) errs.due_date = "The deadline is in the past.";
    showFieldErrors(f, errs);
    $("[data-err=assignee_id]", f).textContent = errs.assignee_id || "";
    if (Object.keys(errs).length) return;
    busy(btn);
    try {
      const t = await api.post("/tasks", { title: v.title.trim(), description: v.description || null, assignee_ids: people.map((u) => u.id),
        due_at: noDl ? null : toIso(v.due_date, v.due_time), priority, category: v.category || null, requires_approval: !!v.requires_approval });
      toast(`Task ${t.number} assigned to ${people.length > 1 ? `${people.length} people` : people[0].name}.`);
      navigate(`/tasks/${t.number}`);
    } catch (ex) { busy(btn, false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
  });
}

// ======================================================================= task page
export async function renderDetail(view, [number]) {
  let t;
  async function reload(msg) {
    t = await api.get(`/tasks/${number}`);
    if (msg) toast(msg);
    draw();
    refreshTaskAccess();
  }
  const act = async (path, body, msg) => {
    try { t = await api.post(`/tasks/${number}/${path}`, body || {}); toast(msg); draw(); refreshTaskAccess(); return true; }
    catch (e) { errorToast(e); return false; }
  };

  function draw() {
    const c = t.can;
    const role = c.is_assignee ? "assignee" : c.manage ? "owner" : "viewer";
    const names = (t.assignees || [t.assignee]).map((u) => u.name).join(", ");
    mount(view, html`${taskTabs("tasks")}<div class="crumbs tk-crumbs"><a href="#/tasks/list">Tasks</a> / <span class="mono">${t.number}</span></div>
      <div class="page-head tk-head tk-panel"><div><div class="row" style="gap:8px;flex-wrap:wrap">${statusPill(t.status)}${prioPill(t.priority)}
          ${t.overdue ? html`<span class="tk-pill tone-danger">${icon("alert")} Overdue</span>` : ""}${t.category ? html`<span class="tk-cat">${t.category}</span>` : ""}</div>
        <h1 style="margin-top:8px">${t.title}</h1>
        <div class="sub">${t.number} · assigned by ${t.assigner.name} ${fmtRelative(t.created_at)}</div></div>
        <div class="row tk-actions">
          ${c.start ? html`<button class="btn primary" data-a="start">${icon("zap")} Start</button>` : ""}
          ${c.submit ? html`<button class="btn ${c.start ? "" : "primary"}" data-a="submit">${icon("checkCircle")} Mark as complete</button>` : ""}
          ${c.request_extension ? html`<button class="btn" data-a="extension">${icon("clock")} Ask for more time</button>` : ""}
          ${c.approve ? html`<button class="btn primary" data-a="approve">${icon("checkCircle")} Approve</button>` : ""}
          ${c.send_back ? html`<button class="btn" data-a="send_back">${icon("refresh")} ${t.status === "completed" ? "Reopen" : "Send back"}</button>` : ""}
          ${c.edit ? html`<button class="btn" data-a="edit">${icon("edit")} Edit</button>` : ""}
          ${c.cancel ? html`<button class="btn ghost danger" data-a="cancel">${icon("x")} Cancel task</button>` : ""}
        </div></div>
      ${t.private ? html`<div class="notice tk-private">${icon("lock")}<div><b>Private task.</b> You can see that it exists and fix the deadline or people,
        but only ${t.assigner.name} and ${names} can read the details and messages.</div></div>` : ""}
      ${t.requested_due_at ? html`<div class="notice warn tk-ext">${icon("clock")}<div><b>More time asked</b> — until <b>${fmtDate(t.requested_due_at)}</b>
          (now ${fmtDate(t.due_at)}).${t.request_reason ? html`<div class="small">Reason: ${t.request_reason}</div>` : ""}</div>
          ${c.decide_extension ? html`<div class="row"><button class="btn sm primary" data-a="ext_yes">Approve new deadline</button><button class="btn sm" data-a="ext_no">Keep current deadline</button></div>` : html`<span class="muted small">Waiting for ${t.assigner.name}</span>`}</div>` : ""}
      ${t.status === "waiting_approval" && c.is_assignee ? html`<div class="notice">${icon("info")}<div>You marked this task as complete. <b>${t.assigner.name}</b> will review it.</div></div>` : ""}
      <div class="tk-layout">
        <div class="stack" style="gap:16px">
          ${t.description ? html`<div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body tk-desc">${t.description}</div></div>` : ""}
          ${c.update || c.comment ? html`<div class="card"><div class="card-head"><h2>${c.update ? "Post an update" : "Write a message"}</h2>
              <span class="hint">${icon("lock")} only people on this task see it · they'll get an email</span></div>
            <form class="card-body stack" id="up" style="gap:12px">
              ${c.update ? html`<div class="tk-slider"><label for="up-p" class="lbl">Progress</label>
                <input type="range" id="up-p" name="progress" min="0" max="100" step="5" value="${t.progress}"><b id="up-pv">${t.progress}%</b></div>` : ""}
              <textarea name="body" rows="3" maxlength="4000" placeholder="${c.update ? "What did you do? Any problems?" : "Write a message…"}"></textarea>
              <div class="row" style="justify-content:flex-end"><button class="btn primary" type="submit" data-busy>${icon("send")} ${c.update ? "Post update" : "Send"}</button></div>
            </form></div>` : ""}
          <div class="card"><div class="card-head"><h2>${icon("activity")} Timeline</h2><span class="hint">${t.events.length}</span></div>
            <div class="card-body"><ol class="tk-tl">${[...t.events].reverse().map((e) => html`<li class="k-${e.kind}">
              <span class="tk-tl-ic">${icon(EV_ICON[e.kind] || "dot")}</span>
              <div><div>${eventLine(e)}</div>${e.body ? html`<div class="tk-tl-body">${e.body}</div>` : e.private ? html`<div class="tk-tl-body tk-hidden">${icon("lock")} Message hidden — private to the people on this task</div>` : ""}
                <span class="muted small" title="${fmtDate(e.created_at)}">${fmtRelative(e.created_at)}</span></div></li>`)}</ol></div></div>
        </div>
        <aside class="stack" style="gap:16px">
          <div class="card"><div class="card-body">
            <div class="tk-prog-big"><b>${t.progress}%</b><span>done</span></div>${bar(t.progress, t.overdue ? "late" : "")}
            <dl class="kv" style="margin-top:16px">
              <dt>Deadline</dt><dd>${t.due_at ? dueText(t) : html`<span class="muted">No deadline</span>`}</dd>
              <dt>Assigned to</dt><dd class="tk-people">${(t.assignees || [t.assignee]).map((u) => who(u))}</dd>
              <dt>Assigned by</dt><dd>${who(t.assigner)}</dd>
              <dt>Created</dt><dd>${fmtDate(t.created_at)}</dd>
              ${t.started_at ? html`<dt>Started</dt><dd>${fmtDate(t.started_at)}</dd>` : ""}
              ${t.submitted_at ? html`<dt>Submitted</dt><dd>${fmtDate(t.submitted_at)}</dd>` : ""}
              ${t.completed_at ? html`<dt>Completed</dt><dd>${fmtDate(t.completed_at)} ${!t.due_at || new Date(t.completed_at) <= new Date(t.due_at) ? html`<span class="tk-pill tone-ok">On time</span>` : html`<span class="tk-pill tone-danger">Late</span>`}</dd>` : ""}
              ${t.rating ? html`<dt>Rating</dt><dd class="tk-stars">${"★".repeat(t.rating)}<span>${"★".repeat(5 - t.rating)}</span></dd>` : ""}
              <dt>Approval</dt><dd>${t.requires_approval ? `${t.assigner.name} approves the work` : "Not needed"}</dd>
            </dl></div></div>
        </aside>
      </div>`);
    wire();
  }

  function wire() {
    const slider = $("#up-p", view);
    slider?.addEventListener("input", () => { $("#up-pv", view).textContent = `${slider.value}%`; });
    $("#up", view)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.currentTarget, body = f.body.value.trim(), btn = $("button[type=submit]", f);
      const progress = slider ? Number(slider.value) : null;
      if (!body && (progress === null || progress === t.progress)) return toast(slider ? "Move the progress slider or write an update." : "Write a message first.", "info");
      busy(btn);
      const ok = await act("updates", { body: body || null, progress: slider && progress !== t.progress ? progress : (slider && !body ? progress : null) },
        slider ? "Update posted." : "Message sent.");
      if (!ok) busy(btn, false);
    });
    $$("[data-a]", view).forEach((b) => b.addEventListener("click", () => action(b.dataset.a)));
  }

  function noteModal({ title, subtitle, label, required = false, confirm, extra = "", onOk, mounted }) {
    openModal({ title, subtitle, body: html`<form id="nm" class="stack" style="gap:12px">${extra}
        <label class="field"><span class="lbl">${label}${required ? html`<span class="req">*</span>` : ""}</span><textarea name="body" rows="4" maxlength="4000"></textarea></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="nm-ok">${confirm}</button>`,
      onMount: (el, close) => {
        mounted?.(el);
        $("#nm-ok", el).addEventListener("click", async () => {
          const f = $("#nm", el), body = f.body.value.trim();
          if (required && body.length < 3) return showFieldErrors(f, { body: "Please write at least a few words." });
          busy($("#nm-ok", el));
          if (await onOk(body, f)) close(); else busy($("#nm-ok", el), false);
        });
      } });
  }

  async function action(a) {
    if (a === "start") return act("start", {}, "Task started — post updates as you go.");
    if (a === "submit") return noteModal({ title: "Mark as complete", label: "Note for " + t.assigner.name + " (optional)",
      subtitle: t.requires_approval ? `${t.assigner.name} will review and approve it.` : "The task will be marked complete.",
      confirm: "Mark as complete", onOk: (body) => act("submit", { body: body || null }, t.requires_approval ? "Sent for approval." : "Task completed.") });
    if (a === "approve") {
      let rating = 0;
      return noteModal({ title: "Approve the work", subtitle: `${t.assignee.name} will be told it's approved.`, label: "Feedback (optional)", confirm: "Approve",
        extra: html`<div class="field"><span class="lbl">Rating (optional)</span><div class="tk-rate" id="rate">${[1, 2, 3, 4, 5].map((n) => html`<button type="button" data-r="${n}" aria-label="${n} stars">★</button>`)}</div></div>`,
        onOk: (body) => act("approve", { body: body || null, rating: rating || null }, "Approved — task completed."),
        mounted: (el) => $$("#rate button", el).forEach((b) => b.addEventListener("click", () => {
          rating = Number(b.dataset.r); $$("#rate button", el).forEach((x) => x.classList.toggle("on", Number(x.dataset.r) <= rating));
        })) });
    }
    if (a === "send_back") return noteModal({ title: t.status === "completed" ? "Reopen the task" : "Send back with feedback",
      subtitle: `${t.assignee.name} will see your feedback and continue working.`, label: "What needs to change?", required: true,
      confirm: "Send back", onOk: (body) => act("send-back", { body }, "Sent back with your feedback.") });
    if (a === "cancel") return noteModal({ title: "Cancel this task?", subtitle: `${t.assignee.name} will be told they no longer need to work on it.`,
      label: "Reason (optional)", confirm: "Cancel task", onOk: (body) => act("cancel", { body: body || null }, "Task cancelled.") });
    if (a === "ext_yes" || a === "ext_no") return act("extension/decision", { approve: a === "ext_yes" }, a === "ext_yes" ? "New deadline approved." : "Deadline kept.");
    if (a === "extension") {
      const cur = new Date(t.due_at), next = new Date(cur.getTime() + 2 * 86400000);
      return noteModal({ title: "Ask for more time", subtitle: `Current deadline: ${fmtDate(t.due_at)}. ${t.assigner.name} will decide.`,
        label: "Why do you need more time?", required: true, confirm: "Send request",
        extra: html`<div class="grid grid-2" style="gap:14px"><label class="field"><span class="lbl">New deadline<span class="req">*</span></span><input type="date" name="d" value="${localDate(next)}" min="${localDate(cur)}"></label>
          <label class="field"><span class="lbl">Time</span><input type="time" name="tm" value="${pad(cur.getHours())}:${pad(cur.getMinutes())}"></label></div>`,
        onOk: (body, f) => act("extension", { reason: body, due_at: toIso(f.d.value, f.tm.value) }, "Request sent.") });
    }
    if (a === "edit") {
      let people = [...(t.assignees || [t.assignee])];
      const due = t.due_at ? new Date(t.due_at) : new Date(Date.now() + 86400000);
      openModal({ title: "Edit task", wide: true, body: html`<form id="ef" class="stack" style="gap:12px">
          ${c.edit_text ? html`<label class="field"><span class="lbl">Title</span><input type="text" name="title" maxlength="200" value="${t.title}"></label>
          <label class="field"><span class="lbl">Details</span><textarea name="description" rows="4" maxlength="8000">${t.description || ""}</textarea></label>` : ""}
          <div class="grid grid-2" style="gap:14px" id="ef-due" ${t.due_at ? "" : "hidden"}><label class="field"><span class="lbl">Deadline date</span><input type="date" name="d" value="${localDate(due)}"></label>
            <label class="field"><span class="lbl">Time</span><input type="time" name="tm" value="${pad(due.getHours())}:${pad(due.getMinutes())}"></label></div>
          <label class="check"><input type="checkbox" name="nodl" id="ef-nodl" ${t.due_at ? "" : "checked"}> No deadline</label>
          <div class="grid grid-2" style="gap:14px"><label class="field"><span class="lbl">Priority</span><select name="priority">${Object.entries(PRIO).map(([k, [l]]) => html`<option value="${k}" ${t.priority === k ? "selected" : ""}>${l}</option>`)}</select></label>
            <label class="field"><span class="lbl">Category</span><input type="text" name="category" maxlength="60" value="${t.category || ""}"></label></div>
          <div class="field"><span class="lbl">People on this task</span><div id="ef-person"></div></div>
          <label class="field"><span class="lbl">Reason for the change (optional, shown in the timeline)</span><input type="text" name="reason" maxlength="500"></label></form>`,
        actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="ef-ok">Save changes</button>`,
        onMount: (el, close) => {
          multiPicker($("#ef-person", el), people, (list) => { people = list; });
          $("#ef-nodl", el).addEventListener("change", (e) => { $("#ef-due", el).hidden = e.target.checked; });
          $("#ef-ok", el).addEventListener("click", async () => {
            const f = $("#ef", el), v = Object.fromEntries(new FormData(f)), body = {};
            if (c.edit_text && v.title.trim() !== t.title) body.title = v.title.trim();
            if (c.edit_text && (v.description || "") !== (t.description || "")) body.description = v.description;
            if (v.priority !== t.priority) body.priority = v.priority;
            if ((v.category || "") !== (t.category || "")) body.category = v.category;
            if (v.nodl) { if (t.due_at) body.due_at = null; }
            else { const iso = toIso(v.d, v.tm); if (!t.due_at || new Date(iso).getTime() !== new Date(t.due_at).getTime()) body.due_at = iso; }
            const ids = people.map((u) => u.id), cur = (t.assignees || [t.assignee]).map((u) => u.id);
            if (!ids.length) return toast("Keep at least one person on the task.", "info");
            if (ids.join(",") !== cur.join(",")) body.assignee_ids = ids;
            if (!Object.keys(body).length) return close();
            if (v.reason) body.reason = v.reason;
            busy($("#ef-ok", el));
            try { t = await api.patch(`/tasks/${number}`, body); close(); toast("Task updated."); draw(); }
            catch (ex) { busy($("#ef-ok", el), false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
          });
        } });
    }
  }

  try { await reload(); } catch (e) {
    mount(view, html`<div class="card">${emptyState("Task not found", "It may have been removed, or it isn't shared with you.", "lock")}</div>`);
  }
}
