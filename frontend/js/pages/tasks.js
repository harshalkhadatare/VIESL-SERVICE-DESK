// Task management: overview (management home), task lists / board, new task, task page.
import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, toast, errorToast, emptyState, skeletonRows, debounce,
  initials, empId, openModal, confirmDialog, busy, showFieldErrors } from "../ui.js";
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
  const d = new Date(t.due_at), now = new Date();
  const days = Math.round((d - now) / 86400000);
  let rel, tone = "";
  if (t.status === "completed" || t.status === "cancelled") rel = "";
  else if (t.overdue) { const late = Math.max(1, Math.round((now - d) / 86400000)); rel = `${late} day${late > 1 ? "s" : ""} late`; tone = "late"; }
  else if (d - now < 86400000) { rel = "due today"; tone = "soon"; }
  else { rel = `in ${days} day${days > 1 ? "s" : ""}`; tone = days <= 2 ? "soon" : ""; }
  return html`<span class="tk-due ${tone}"><span>${fmtDate(t.due_at)}</span>${rel ? html`<b>${rel}</b>` : ""}</span>`;
}

const greet = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; };

// ======================================================================= overview (management home)
export async function renderOverview(view, _p, query = {}) {
  const acc = state.tasks || {};
  if (!acc.can_assign) return navigate("/tasks/list?view=to_me");
  try { localStorage.setItem("sd-mode", "tasks"); } catch { /* storage blocked */ }
  let scope = query.scope === "all" && acc.sees_all ? "all" : "mine";
  mount(view, html`<div class="page-head"><div><h1>${greet()}, ${state.me.full_name.split(" ")[0]}</h1>
      <div class="sub" id="ov-sub">Your team's tasks at a glance.</div></div>
    <div class="row">${acc.sees_all ? html`<div class="seg" id="ov-scope"><button data-v="mine" class="${scope === "mine" ? "on" : ""}">Assigned by me</button>
      <button data-v="all" class="${scope === "all" ? "on" : ""}">Whole company</button></div>` : ""}
      <a class="btn primary" href="#/tasks/new">${icon("plus")} Assign task</a></div></div>
    <div id="ov-body"><div class="card"><div class="card-body">${skeletonRows(4, 4)}</div></div></div>`);

  async function load() {
    try {
      const d = await api.get("/tasks/overview", { scope });
      if (!$("#ov-body", view)?.isConnected) return;
      const T = d.tiles;
      const list = (q) => `#/tasks/list?view=${scope === "all" ? "all" : "by_me"}&${q}`;
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
          <div class="card"><div class="card-head"><h2>${icon("alert")} Needs your attention</h2><span class="hint">${d.attention.length}</span></div>
            <div class="card-body flush">${d.attention.length ? html`<ul class="tk-att">${d.attention.map((a) => html`<li>
              <a href="#/tasks/${a.task.number}"><span class="tk-att-tag k-${a.kind}">${a.label}</span>
                <b>${a.task.title}</b><span class="muted small">${a.task.assignee.name} · ${a.task.progress}% · due ${fmtDate(a.task.due_at, false)}</span></a></li>`)}</ul>`
              : html`<div class="tk-empty">${icon("checkCircle")} Nothing needs you right now.</div>`}</div></div>
          <div class="card"><div class="card-head"><h2>${icon("calendar")} Deadlines in the next 7 days</h2></div>
            <div class="card-body flush">${d.upcoming.length ? html`<ul class="tk-att">${d.upcoming.map((t) => html`<li>
              <a href="#/tasks/${t.number}">${prioPill(t.priority)}<b>${t.title}</b><span class="muted small">${t.assignee.name} · ${t.progress}%</span>${dueText(t)}</a></li>`)}</ul>`
              : html`<div class="tk-empty">${icon("calendar")} No deadlines this week.</div>`}</div></div>
        </div>
        <div class="card"><div class="card-head"><h2>${icon("users")} Team progress</h2><span class="hint">open tasks per person</span></div>
          <div class="card-body flush table-wrap">${d.team.length ? html`<table class="data tk-team"><thead><tr><th>Person</th><th class="num">Open</th>
            <th class="num">Overdue</th><th class="num hide-sm">Waiting approval</th><th>Average progress</th></tr></thead><tbody>
            ${d.team.map((r) => html`<tr class="clickable" data-href="${list(`status=open&assignee_id=${r.user.id}`)}">
              <td>${who(r.user)}${r.user.department ? html`<div class="t-sub2">${r.user.department}</div>` : ""}</td>
              <td class="num">${r.open}</td><td class="num ${r.overdue ? "tk-red" : ""}">${r.overdue}</td>
              <td class="num hide-sm">${r.waiting_approval}</td><td>${bar(r.avg_progress, r.overdue ? "late" : "")} <span class="small">${r.avg_progress}%</span></td></tr>`)}
            </tbody></table>` : html`<div class="tk-empty">${icon("users")} No open tasks yet. <a href="#/tasks/new">Assign the first one</a>.</div>`}</div></div>
        <div class="card"><div class="card-head"><h2>${icon("activity")} Latest updates</h2></div>
          <div class="card-body flush">${d.feed.length ? html`<ul class="tk-feed">${d.feed.map((e) => html`<li>
            <span class="avatar">${initials(e.author?.name || "S")}</span>
            <div><div>${eventLine(e)} <a href="#/tasks/${e.task.number}">${e.task.title}</a></div>
              ${e.body ? html`<div class="tk-feed-body">${e.body}</div>` : ""}
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
    case "status": return e.new_value === "in_progress" ? html`${n} started the task` : html`${n} changed the status`;
    case "submitted": return html`${n} marked it complete and asked for approval`;
    case "completed": return html`${n} completed the task`;
    case "approved": return html`${n} approved the work${e.new_value ? html` · <b>${e.new_value}</b>` : ""}`;
    case "returned": return html`${n} sent it back with feedback`;
    case "cancelled": return html`${n} cancelled the task`;
    case "deadline": return html`${n} changed the deadline to <b>${fmtDate(e.new_value)}</b>`;
    case "priority": return html`${n} changed priority to <b>${e.new_value}</b>`;
    case "reassigned": return html`${n} moved the task from ${e.old_value} to <b>${e.new_value}</b>`;
    case "extension_requested": return html`${n} asked for more time, until <b>${fmtDate(e.new_value)}</b>`;
    case "extension_approved": return html`${n} approved more time — new deadline <b>${fmtDate(e.new_value)}</b>`;
    case "extension_declined": return html`${n} kept the deadline (more time not approved)`;
    default: return html`${n} updated the task`;
  }
}
const EV_ICON = { created: "plus", progress: "activity", comment: "send", status: "zap", submitted: "flag", completed: "checkCircle",
  approved: "checkCircle", returned: "refresh", cancelled: "x", deadline: "calendar", priority: "alert", reassigned: "user",
  extension_requested: "clock", extension_approved: "clock", extension_declined: "clock" };

// ======================================================================= list + board
export async function renderList(view, _p, query = {}) {
  const acc = state.tasks || {};
  const views = [acc.can_assign && ["by_me", "Assigned by me"], ["to_me", "Assigned to me"], acc.sees_all && ["all", "All tasks"]].filter(Boolean);
  const f = {
    view: views.some(([v]) => v === query.view) ? query.view : views[0][0],
    status: query.status || "open", q: query.q || "", assignee_id: query.assignee_id || "", sort: query.sort || "due",
    layout: query.layout || (localStorage.getItem("sd-task-layout") || "list"),
  };
  const STATUSES = [["open", "Open"], ["overdue", "Overdue"], ["waiting_approval", "Waiting approval"], ["completed", "Completed"], ["all", "All"]];
  mount(view, html`<div class="page-head"><div><h1>Tasks</h1><div class="sub" id="tl-sub"></div></div>
      ${acc.can_assign ? html`<a class="btn primary" href="#/tasks/new">${icon("plus")} Assign task</a>` : ""}</div>
    ${views.length > 1 ? html`<div class="tabs" id="tl-views" role="tablist">${views.map(([v, l]) => html`<button role="tab" data-v="${v}" class="${f.view === v ? "on" : ""}">${l}</button>`)}</div>` : ""}
    <div class="card"><div class="toolbar">
      <div class="search-inline">${icon("search")}<input type="search" id="tl-q" placeholder="Search title, number, person or category" value="${f.q}" aria-label="Search tasks"></div>
      <div class="chips" id="tl-status">${STATUSES.map(([v, l]) => html`<button class="chip ${f.status === v ? "on" : ""}" data-v="${v}">${l}</button>`)}</div>
      <span class="spacer"></span>
      <select id="tl-sort" aria-label="Sort"><option value="due">Deadline first</option><option value="updated">Recently updated</option>
        <option value="created">Newest</option><option value="priority">Priority</option></select>
      <div class="seg" id="tl-layout"><button data-v="list" title="List">${icon("list")}</button><button data-v="board" title="Board">${icon("columns")}</button></div>
    </div><div id="tl-body"></div></div>`);
  $("#tl-sort", view).value = f.sort;
  const syncLayout = () => $$("#tl-layout button", view).forEach((b) => b.classList.toggle("on", b.dataset.v === f.layout));
  syncLayout();

  async function load() {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    history.replaceState(null, "", `#/tasks/list?${q}`);
    mount($("#tl-body", view), html`<div class="card-body">${skeletonRows(6, 5)}</div>`);
    try {
      const board = f.layout === "board";
      const r = await api.get("/tasks", { view: f.view, status: board ? "all" : f.status, q: f.q || undefined,
        assignee_id: f.assignee_id || undefined, sort: f.sort, page_size: board ? 200 : 100 });
      if (!$("#tl-body", view)?.isConnected) return;
      $("#tl-sub", view).textContent = `${r.total} task${r.total === 1 ? "" : "s"}${f.assignee_id ? " · filtered by person" : ""}`;
      $("#tl-status", view).hidden = board;
      if (!r.items.length) return mount($("#tl-body", view), emptyState("No tasks here", "Nothing matches these filters.", "inbox"));
      if (board) {
        const cols = [["not_started", "Not started"], ["in_progress", "In progress"], ["waiting_approval", "Waiting for approval"], ["completed", "Completed"]];
        mount($("#tl-body", view), html`<div class="tk-board">${cols.map(([s, l]) => {
          const items = r.items.filter((t) => t.status === s);
          return html`<div class="tk-col"><div class="tk-col-head">${statusPill(s)}<span class="muted small">${items.length}</span></div>
            ${items.map((t) => html`<a class="tk-card ${t.overdue ? "late" : ""}" href="#/tasks/${t.number}">
              <div class="tk-card-top">${prioPill(t.priority)}<span class="mono small muted">${t.number}</span></div>
              <b>${t.title}</b>${bar(t.progress, t.overdue ? "late" : "")}
              <div class="tk-card-foot">${who(f.view === "to_me" ? t.assigner : t.assignee)}${dueText(t)}</div></a>`)}
            ${items.length ? "" : html`<div class="tk-col-empty">—</div>`}</div>`;
        })}</div>`);
      } else {
        const other = f.view === "to_me" ? "Assigned by" : "Assigned to";
        mount($("#tl-body", view), html`<div class="table-wrap"><table class="data tk-table"><thead><tr><th>Task</th><th>${other}</th>
          <th class="hide-sm">Priority</th><th>Status</th><th class="hide-sm">Progress</th><th>Deadline</th></tr></thead><tbody>
          ${r.items.map((t) => html`<tr class="clickable ${t.overdue ? "tk-row-late" : ""}" data-n="${t.number}">
            <td><a class="t-id" href="#/tasks/${t.number}">${t.number}</a><span class="t-sub2" style="display:block">${t.title}${t.category ? html` <span class="tk-cat">${t.category}</span>` : ""}</span></td>
            <td>${who(f.view === "to_me" ? t.assigner : t.assignee)}</td><td class="hide-sm">${prioPill(t.priority)}</td>
            <td>${statusPill(t.status)}${t.has_extension_request ? html`<div class="t-sub2">${icon("clock")} more time asked</div>` : ""}</td>
            <td class="hide-sm">${bar(t.progress, t.overdue ? "late" : "")} <span class="small">${t.progress}%</span></td><td>${dueText(t)}</td></tr>`)}
          </tbody></table></div>`);
        $$("tr[data-n]", view).forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) navigate(`/tasks/${tr.dataset.n}`); }));
      }
    } catch (e) { errorToast(e); }
  }
  $("#tl-views", view)?.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    f.view = b.dataset.v; f.assignee_id = "";
    $$("#tl-views button", view).forEach((x) => x.classList.toggle("on", x === b)); load();
  });
  $("#tl-status", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    f.status = b.dataset.v; $$("#tl-status button", view).forEach((x) => x.classList.toggle("on", x === b)); load();
  });
  $("#tl-layout", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    f.layout = b.dataset.v; try { localStorage.setItem("sd-task-layout", f.layout); } catch { /* */ }
    syncLayout(); load();
  });
  $("#tl-sort", view).addEventListener("change", (e) => { f.sort = e.target.value; load(); });
  $("#tl-q", view).addEventListener("input", debounce((e) => { f.q = e.target.value.trim(); load(); }, 300));
  await load();
}

// ======================================================================= new task
const pad = (n) => String(n).padStart(2, "0");
const localDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const toIso = (date, time) => new Date(`${date}T${time || "18:00"}`).toISOString();

/** Searchable person picker (anyone active). */
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

export async function renderNew(view) {
  const acc = state.tasks || {};
  if (!acc.can_assign) return navigate("/tasks/list");
  const tomorrow = new Date(Date.now() + 86400000);
  let assignee = null, priority = "medium";
  mount(view, html`<div class="crumbs"><a href="#/tasks">Tasks</a> / <span>Assign a task</span></div>
    <div class="page-head"><div><h1>Assign a task</h1><div class="sub">The person gets an email straight away and sees it under “My tasks”.</div></div></div>
    <form class="card" id="tf" novalidate><div class="card-body stack" style="gap:16px">
      <label class="field"><span class="lbl">What needs to be done?<span class="req">*</span></span>
        <input type="text" name="title" maxlength="200" required placeholder="e.g. Prepare the monthly MIS report"></label>
      <label class="field"><span class="lbl">Details <span class="muted" style="font-weight:400">(optional)</span></span>
        <textarea name="description" rows="5" maxlength="8000" placeholder="What exactly you expect, the format, who to contact…"></textarea></label>
      <div class="field"><span class="lbl">Assign to<span class="req">*</span></span><div id="tf-person"></div><div class="err" data-err="assignee_id"></div></div>
      <div class="grid grid-2" style="gap:14px">
        <label class="field"><span class="lbl">Deadline date<span class="req">*</span></span><input type="date" name="due_date" value="${localDate(tomorrow)}" min="${localDate(new Date())}" required></label>
        <label class="field"><span class="lbl">Time</span><input type="time" name="due_time" value="18:00"></label>
      </div>
      <div class="field"><span class="lbl">Priority</span><div class="seg" id="tf-prio">
        <button type="button" data-v="high">High</button><button type="button" data-v="medium" class="on">Medium</button><button type="button" data-v="low">Low</button></div></div>
      <label class="field"><span class="lbl">Category <span class="muted" style="font-weight:400">(optional)</span></span>
        <input type="text" name="category" maxlength="60" list="tf-cats" placeholder="e.g. MIS, Site visit, Compliance">
        <datalist id="tf-cats"><option value="MIS / Reports"><option value="Site visit"><option value="Compliance"><option value="Finance"><option value="Purchase"><option value="HR"><option value="Follow-up"></datalist></label>
      <label class="check"><input type="checkbox" name="requires_approval" checked> I want to approve the work before it's marked complete</label>
    </div><div class="modal-foot"><a class="btn" href="#/tasks">Cancel</a><button class="btn primary" type="submit" data-busy>${icon("send")} Assign task</button></div></form>`);
  personPicker($("#tf-person", view), (u) => { assignee = u; });
  $("#tf-prio", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    priority = b.dataset.v; $$("#tf-prio button", view).forEach((x) => x.classList.toggle("on", x === b));
  });
  $("#tf", view).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget, v = Object.fromEntries(new FormData(f)), btn = $("button[type=submit]", f);
    const errs = {};
    if ((v.title || "").trim().length < 3) errs.title = "Write what needs to be done (at least 3 characters).";
    if (!assignee) errs.assignee_id = "Choose who should do this task.";
    if (!v.due_date) errs.due_date = "Pick a deadline.";
    else if (new Date(toIso(v.due_date, v.due_time)) < new Date()) errs.due_date = "The deadline is in the past.";
    showFieldErrors(f, errs);
    $("[data-err=assignee_id]", f).textContent = errs.assignee_id || "";
    if (Object.keys(errs).length) return;
    busy(btn);
    try {
      const t = await api.post("/tasks", { title: v.title.trim(), description: v.description || null, assignee_id: assignee.id,
        due_at: toIso(v.due_date, v.due_time), priority, category: v.category || null, requires_approval: !!v.requires_approval });
      toast(`Task ${t.number} assigned to ${assignee.name}.`);
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
    mount(view, html`<div class="crumbs"><a href="#/tasks${c.is_assignee && !(state.tasks || {}).can_assign ? "/list?view=to_me" : ""}">Tasks</a> / <span class="mono">${t.number}</span></div>
      <div class="page-head tk-head"><div><div class="row" style="gap:8px;flex-wrap:wrap">${statusPill(t.status)}${prioPill(t.priority)}
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
      ${t.requested_due_at ? html`<div class="notice warn tk-ext">${icon("clock")}<div><b>${t.assignee.name} asks for more time</b> — until <b>${fmtDate(t.requested_due_at)}</b>
          (now ${fmtDate(t.due_at)}).<div class="small">Reason: ${t.request_reason}</div></div>
          ${c.decide_extension ? html`<div class="row"><button class="btn sm primary" data-a="ext_yes">Approve new deadline</button><button class="btn sm" data-a="ext_no">Keep current deadline</button></div>` : html`<span class="muted small">Waiting for ${t.assigner.name}</span>`}</div>` : ""}
      ${t.status === "waiting_approval" && c.is_assignee ? html`<div class="notice">${icon("info")}<div>You marked this task as complete. <b>${t.assigner.name}</b> will review it.</div></div>` : ""}
      <div class="tk-layout">
        <div class="stack" style="gap:16px">
          ${t.description ? html`<div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body tk-desc">${t.description}</div></div>` : ""}
          ${c.update || c.comment ? html`<div class="card"><div class="card-head"><h2>${c.update ? "Post an update" : "Write a message"}</h2>
              <span class="hint">${role === "assignee" ? `${t.assigner.name} will be notified` : `${t.assignee.name} will be notified`}</span></div>
            <form class="card-body stack" id="up" style="gap:12px">
              ${c.update ? html`<div class="tk-slider"><label for="up-p" class="lbl">Progress</label>
                <input type="range" id="up-p" name="progress" min="0" max="100" step="5" value="${t.progress}"><b id="up-pv">${t.progress}%</b></div>` : ""}
              <textarea name="body" rows="3" maxlength="4000" placeholder="${c.update ? "What did you do? Any problems?" : "Write a message…"}"></textarea>
              <div class="row" style="justify-content:flex-end"><button class="btn primary" type="submit" data-busy>${icon("send")} ${c.update ? "Post update" : "Send"}</button></div>
            </form></div>` : ""}
          <div class="card"><div class="card-head"><h2>${icon("activity")} Timeline</h2><span class="hint">${t.events.length}</span></div>
            <div class="card-body"><ol class="tk-tl">${[...t.events].reverse().map((e) => html`<li class="k-${e.kind}">
              <span class="tk-tl-ic">${icon(EV_ICON[e.kind] || "dot")}</span>
              <div><div>${eventLine(e)}</div>${e.body ? html`<div class="tk-tl-body">${e.body}</div>` : ""}
                <span class="muted small" title="${fmtDate(e.created_at)}">${fmtRelative(e.created_at)}</span></div></li>`)}</ol></div></div>
        </div>
        <aside class="stack" style="gap:16px">
          <div class="card"><div class="card-body">
            <div class="tk-prog-big"><b>${t.progress}%</b><span>done</span></div>${bar(t.progress, t.overdue ? "late" : "")}
            <dl class="kv" style="margin-top:16px">
              <dt>Deadline</dt><dd>${dueText(t)}</dd>
              <dt>Assigned to</dt><dd>${who(t.assignee)}</dd>
              <dt>Assigned by</dt><dd>${who(t.assigner)}</dd>
              <dt>Created</dt><dd>${fmtDate(t.created_at)}</dd>
              ${t.started_at ? html`<dt>Started</dt><dd>${fmtDate(t.started_at)}</dd>` : ""}
              ${t.submitted_at ? html`<dt>Submitted</dt><dd>${fmtDate(t.submitted_at)}</dd>` : ""}
              ${t.completed_at ? html`<dt>Completed</dt><dd>${fmtDate(t.completed_at)} ${new Date(t.completed_at) <= new Date(t.due_at) ? html`<span class="tk-pill tone-ok">On time</span>` : html`<span class="tk-pill tone-danger">Late</span>`}</dd>` : ""}
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
      let person = null;
      const due = new Date(t.due_at);
      openModal({ title: "Edit task", wide: true, body: html`<form id="ef" class="stack" style="gap:12px">
          <label class="field"><span class="lbl">Title</span><input type="text" name="title" maxlength="200" value="${t.title}"></label>
          <label class="field"><span class="lbl">Details</span><textarea name="description" rows="4" maxlength="8000">${t.description || ""}</textarea></label>
          <div class="grid grid-2" style="gap:14px"><label class="field"><span class="lbl">Deadline date</span><input type="date" name="d" value="${localDate(due)}"></label>
            <label class="field"><span class="lbl">Time</span><input type="time" name="tm" value="${pad(due.getHours())}:${pad(due.getMinutes())}"></label></div>
          <div class="grid grid-2" style="gap:14px"><label class="field"><span class="lbl">Priority</span><select name="priority">${Object.entries(PRIO).map(([k, [l]]) => html`<option value="${k}" ${t.priority === k ? "selected" : ""}>${l}</option>`)}</select></label>
            <label class="field"><span class="lbl">Category</span><input type="text" name="category" maxlength="60" value="${t.category || ""}"></label></div>
          <div class="field"><span class="lbl">Assigned to</span><div id="ef-person"></div></div>
          <label class="field"><span class="lbl">Reason for the change (optional, shown in the timeline)</span><input type="text" name="reason" maxlength="500"></label></form>`,
        actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="ef-ok">Save changes</button>`,
        onMount: (el, close) => {
          personPicker($("#ef-person", el), (u) => { person = u; }, { id: t.assignee.id, name: t.assignee.name, employee_code: t.assignee.employee_code, department: t.assignee.department });
          $("#ef-ok", el).addEventListener("click", async () => {
            const f = $("#ef", el), v = Object.fromEntries(new FormData(f)), body = {};
            if (v.title.trim() !== t.title) body.title = v.title.trim();
            if ((v.description || "") !== (t.description || "")) body.description = v.description;
            if (v.priority !== t.priority) body.priority = v.priority;
            if ((v.category || "") !== (t.category || "")) body.category = v.category;
            const iso = toIso(v.d, v.tm);
            if (new Date(iso).getTime() !== due.getTime()) body.due_at = iso;
            if (person && person.id !== t.assignee.id) body.assignee_id = person.id;
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
