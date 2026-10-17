import { api } from "../api.js";
import { $, $$, html, mount, icon, fmtRelative, fmtDate, emptyState, errorToast, toast } from "../ui.js";
import { refreshUnread } from "../app.js";

const EV_ICON = { ticket_created: "ticket", ticket_assigned: "user", status_changed: "refresh", comment_added: "send",
  info_requested: "alert", sla_warning: "clock", sla_breached: "alert", ticket_resolved: "checkCircle",
  ticket_reopened: "refresh", ticket_closed: "check" };

export async function render(view) {
  let unreadOnly = false, page = 1;
  mount(view, html`<div class="page-head"><div><h1>Notifications</h1><div class="sub">Updates on tickets you raised or work on.</div></div>
    <div class="row"><div class="seg" id="nf"><button class="on" data-v="all">All</button><button data-v="unread">Unread</button></div>
    <button class="btn" id="mark">${icon("check")} Mark all read</button></div></div>
    <div class="card"><ul class="list" id="nl"></ul><div class="pager" id="np"></div></div>`);

  async function load() {
    try {
      const r = await api.get("/notifications", { unread_only: unreadOnly, page, page_size: 20 });
      if (!$("#nl", view)?.isConnected) return;
      mount($("#nl", view), r.items.length ? html`${r.items.map((n) => html`<li style="${n.is_read ? "" : "background:var(--surface-hover)"}">
        <a class="item row" style="flex-wrap:nowrap;align-items:flex-start;gap:14px" href="${n.link || "#/notifications"}" data-id="${n.id}" data-read="${n.is_read}">
          <span class="attach" style="padding:0"><span class="ic">${icon(EV_ICON[n.event] || "bell")}</span></span>
          <span style="flex:1;min-width:0"><b style="font-weight:${n.is_read ? 500 : 650}">${n.title}</b>
            ${n.body ? html`<div class="t-sub2" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${n.body}</div>` : ""}</span>
          <span class="muted small" title="${fmtDate(n.created_at)}" style="white-space:nowrap">${fmtRelative(n.created_at)}</span></a></li>`)}` :
        html`<li>${emptyState(unreadOnly ? "You're all caught up" : "No notifications yet", "We'll let you know when something changes on your tickets.", "bell")}</li>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#np", view), html`<span>${r.total} total</span><div class="row"><button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button>
        <button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { page--; load(); });
      $("#nx", view).addEventListener("click", () => { page++; load(); });
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
  $("#mark", view).addEventListener("click", async () => {
    try { await api.post("/notifications/read-all"); toast("All notifications marked as read."); refreshUnread(); load(); } catch (e) { errorToast(e); }
  });
  await load();
}
