import { api } from "../api.js";
import { $, $$, html, mount, icon, fmtRelative, fmtDate, emptyState, errorToast, toast, initials } from "../ui.js";
import { refreshUnread, notifArea } from "../app.js";

// What each event is called on screen, its icon and its colour
const EV = {
  ticket_created:  ["New ticket", "ticket", "info"],
  ticket_assigned: ["Assigned", "user", "info"],
  status_changed:  ["Status changed", "refresh", "neutral"],
  comment_added:   ["New message", "send", "primary"],
  info_requested:  ["Your reply needed", "alert", "warn"],
  ticket_resolved: ["Resolved", "checkCircle", "ok"],
  ticket_reopened: ["Reopened", "refresh", "warn"],
  ticket_closed:   ["Closed", "check", "neutral"],
  sla_warning:     ["Deadline near", "clock", "warn"],
  sla_breached:    ["Overdue", "alert", "danger"],
  // task management
  task_assigned:   ["New task", "target", "info"],
  task_update:     ["Task update", "send", "primary"],
  task_submitted:  ["Ready for review", "flag", "warn"],
  task_completed:  ["Completed", "checkCircle", "ok"],
  task_returned:   ["Changes needed", "refresh", "warn"],
  task_extension:  ["Deadline", "clock", "info"],
  task_due_soon:   ["Due soon", "clock", "warn"],
  task_overdue:    ["Overdue", "alert", "danger"],
};
const KINDS = [["", "All types"], ["messages", "Messages"], ["updates", "Status updates"], ["alerts", "Alerts"]];

function dayLabel(v) {
  const d = new Date(v), today = new Date();
  const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(today) - start(d)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export async function render(view, _p, query = {}) {
  let unreadOnly = false, kind = "", page = 1;
  const area = query.area === "tasks" ? "tasks" : notifArea();
  const tasks = area === "tasks";
  mount(view, html`<div class="page-head"><div><h1>${tasks ? "Task notifications" : "Notifications"}</h1>
      <div class="sub" id="nsub">${tasks ? "Only Task management: new tasks, updates, approvals and deadline reminders." : "Updates on tickets you raised or work on."}</div></div>
    <button class="btn" id="mark">${icon("check")} Mark all as read</button></div>
    <div class="nf-bar">
      <div class="seg" id="nf"><button class="on" data-v="all">All</button><button data-v="unread">Unread</button></div>
      <div class="nf-kinds" id="nk">${KINDS.map(([v, l]) => html`<button class="chip ${v === "" ? "on" : ""}" data-v="${v}">${l}</button>`)}</div>
    </div>
    <div id="nl" class="nf-list"></div><div class="pager" id="np"></div>`);

  function item(n) {
    const [label, ic, tone] = EV[n.event] || ["Update", "bell", "neutral"];
    const body = (n.body || "").split("\n").map((l) => l.trim())
      .filter((l) => l && !l.startsWith("Assigned to:")).join(" · ")
      .replace(n.ticket_subject ? new RegExp("^" + n.ticket_subject.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "( · )?") : /^$/, "");
    return html`<a class="nf-item ${n.is_read ? "" : "unread"}" href="${n.link || "#/notifications"}" data-id="${n.id}" data-read="${n.is_read}">
      <span class="nf-ic tone-${tone}">${icon(ic)}</span>
      <span class="nf-main">
        <span class="nf-top"><span class="nf-tag tone-${tone}">${label}</span>
          ${n.ticket_number ? html`<span class="nf-num">${n.ticket_number}</span>` : ""}
          <span class="nf-time" title="${fmtDate(n.created_at)}">${fmtRelative(n.created_at)}</span></span>
        <span class="nf-title">${n.title}</span>
        ${n.ticket_subject ? html`<span class="nf-subj">${icon(n.area === "tasks" ? "target" : "ticket")} ${n.ticket_subject}</span>` : ""}
        ${body ? html`<span class="nf-body">${body}</span>` : ""}
        <span class="nf-meta">
          ${n.ticket_status ? html`<span class="nf-pill">Status: <b>${n.ticket_status}</b></span>` : ""}
          ${n.area === "tasks" && n.assignee_name ? html`<span class="nf-pill">${icon("users")} ${n.assignee_name}</span>` : n.ticket_number ? (n.assignee_name
            ? html`<span class="nf-pill"><span class="avatar">${initials(n.assignee_name)}</span>${n.assignee_name}</span>`
            : html`<span class="nf-pill warn">Not yet assigned</span>`) : ""}
          ${n.email_status === "sent" ? html`<span class="nf-pill" title="An email was also sent">${icon("mail")} Emailed</span>` : ""}
        </span>
      </span>
      ${n.is_read ? "" : html`<span class="nf-dot" title="Unread"></span>`}
    </a>`;
  }

  async function load() {
    try {
      const [r, unread] = await Promise.all([
        api.get("/notifications", { unread_only: unreadOnly, page, page_size: 20, area, ...(kind ? { kind } : {}) }),
        api.get("/notifications/unread-count", { area }).catch(() => null),
      ]);
      if (!$("#nl", view)?.isConnected) return;
      if (unread) $("#nsub", view).textContent = unread.count
        ? `You have ${unread.count} unread notification${unread.count === 1 ? "" : "s"}.` : "You're all caught up.";
      // group by day
      const groups = [];
      for (const n of r.items) {
        const d = dayLabel(n.created_at);
        if (!groups.length || groups[groups.length - 1].d !== d) groups.push({ d, list: [] });
        groups[groups.length - 1].list.push(n);
      }
      mount($("#nl", view), groups.length
        ? html`${groups.map((g) => html`<section class="nf-day"><h3>${g.d}</h3><div class="card nf-card">${g.list.map(item)}</div></section>`)}`
        : html`<div class="card">${emptyState(unreadOnly ? "You're all caught up" : "No notifications here",
            "We'll let you know when something changes on your tickets.", "bell")}</div>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#np", view), r.total > r.page_size ? html`<span>Page ${page} of ${pages} · ${r.total} notifications</span><div class="row">
        <button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button>
        <button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>` : html`<span>${r.total} notification${r.total === 1 ? "" : "s"}</span>`);
      $("#pv", view)?.addEventListener("click", () => { page--; load(); });
      $("#nx", view)?.addEventListener("click", () => { page++; load(); });
      $$("[data-id]", view).forEach((a) => a.addEventListener("click", () => {
        if (a.dataset.read === "false") api.post(`/notifications/${a.dataset.id}/read`).then(refreshUnread).catch(() => {});
      }));
    } catch (e) { errorToast(e); }
  }
  $("#nf", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#nf button", view).forEach((x) => x.classList.toggle("on", x === b));
    unreadOnly = b.dataset.v === "unread"; page = 1; load();
  });
  $("#nk", view).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#nk button", view).forEach((x) => x.classList.toggle("on", x === b));
    kind = b.dataset.v; page = 1; load();
  });
  $("#mark", view).addEventListener("click", async () => {
    try { await api.post(`/notifications/read-all${area ? `?area=${area}` : ""}`); toast("All notifications marked as read."); refreshUnread(); load(); } catch (e) { errorToast(e); }
  });
  await load();
}
