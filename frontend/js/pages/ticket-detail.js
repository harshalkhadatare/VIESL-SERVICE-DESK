import { api } from "../api.js";
import { state, catalog, supportGroups, can } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, statusBadge, prioBadge, initials, toast, errorToast,
  openModal, busy, emptyState, fileSize, showFieldErrors, realEmail, confirmDialog, deskBadge, nameId, nameIdText, empId } from "../ui.js";
import { refreshUnread } from "../app.js";

const FIELD_LABEL = { status: "Status", assignee: "Assignee", support_group: "Support group", priority: "Priority",
  created: "Ticket created", resolution_notes: "Resolution notes", root_cause: "Root cause", attachment: "Attachment",
  link: "Linked", rating: "Rating", sla: "SLA" };
const IMPACT = { 1: "High", 2: "Medium", 3: "Low" };

// Ready-made replies for IT administrators ({name} = requester's first name)
const QUICK_REPLIES = [
  ["Looking into it", "Hi {name}, thanks for reporting this. I'm looking into it now and will update you shortly."],
  ["Need more details", "Hi {name}, could you please share a screenshot of the error and tell me when it started?"],
  ["Remote session", "Hi {name}, I'd like to connect to your computer remotely to check this. What time suits you today?"],
  ["Please restart", "Hi {name}, please restart your computer once and try again. Let me know if the problem continues."],
  ["Fixed — please check", "Hi {name}, this should be fixed now. Please check and confirm it's working on your side."],
  ["Waiting for vendor", "Hi {name}, we've raised this with the vendor and are waiting for their reply. I'll update you as soon as we hear back."],
  ["Visiting your desk", "Hi {name}, I'll come to your desk shortly to have a look."],
];

// Progress tracker steps
const STEPS = ["Submitted", "Assigned", "In progress", "Resolved", "Closed"];
const STEP_OF = { NEW: 0, SUBMITTED: 0, TRIAGED: 0, ASSIGNED: 1, IN_PROGRESS: 2, PENDING_EMPLOYEE: 2, PENDING_APPROVAL: 2,
  PENDING_VENDOR: 2, PENDING_CHANGE: 2, REOPENED: 2, RESOLVED: 3, CLOSED: 4 };

export async function render(view, [number]) {
  let t, comments, history, attachments, tab = "conversation", composeInternal = false;
  const statusNames = Object.fromEntries((await catalog()).statuses.map((s) => [s.code, s.name]));

  async function loadAll() {
    [t, comments, history, attachments] = await Promise.all([
      api.get(`/tickets/${number}`), api.get(`/tickets/${number}/comments`),
      api.get(`/tickets/${number}/history`), api.get(`/tickets/${number}/attachments`)]);
  }
  try { await loadAll(); } catch (e) {
    mount(view, html`<div class="card">${emptyState(e.status === 404 ? "Ticket not found" : "Could not load ticket",
      e.status === 404 ? "It may not exist, or you may not have access to it." : e.message, "alert",
      html`<a class="btn" href="#/tickets">Back to tickets</a>`)}</div>`);
    return;
  }
  const isRequester = () => t.requester.id === state.me.id;

  function draw() {
    const allowed = t.allowed_transitions.map((s) => s.code);
    const queued = ["SUBMITTED", "TRIAGED", "ASSIGNED", "REOPENED"].includes(t.status.code);
    const canAccept = t.can_work && can("ticket.accept") && queued && (!t.assignee || t.assignee.id === state.me.id);
    const closed = ["CLOSED", "CANCELLED"].includes(t.status.code);
    mount(view, html`
      <div class="crumbs"><a href="#/tickets">Tickets</a> / <span class="mono">${t.number}</span></div>
      <div class="page-head" style="align-items:flex-start">
        <div style="min-width:0;flex:1">
          <div class="ticket-title"><span class="t-id" style="font-size:13.5px">${t.number}</span>${deskBadge(t.desk)}${statusBadge(t.status)}${prioBadge(t.priority)}
            ${t.is_demo ? html`<span class="pill demo">Demo data</span>` : ""}
            <button class="ticket-star ${t.starred ? "on" : ""}" id="star-btn" aria-pressed="${t.starred}" title="Star tickets to find them quickly in the ★ Starred tab">${icon("star")} ${t.starred ? "Starred" : "Star"}</button></div>
          <h1 style="margin-top:8px">${t.subject}</h1>
          <div class="meta-line"><span>${icon("user")} ${t.can_work && t.requester.employee_code ? html`<a href="#/tickets?scope=all&requester=${encodeURIComponent(t.requester.employee_code)}" title="All tickets raised by ${t.requester.full_name}">${nameId(t.requester)}</a>` : nameId(t.requester)}</span><span>${icon("clock")} Raised ${fmtRelative(t.created_at)}</span>
            <span>${icon("layers")} ${t.category.name}${t.subcategory ? ` › ${t.subcategory.name}` : ""}</span>
            <span>${t.ticket_type === "incident" ? "Incident" : "Service request"}</span></div>
        </div>
        <div class="row" id="actions">
          ${canAccept ? html`<button class="btn primary" data-act="accept">${icon("check")} Accept & start</button>` : ""}
          ${t.can_work && allowed.length ? html`<button class="btn ${canAccept ? "" : "primary"}" data-act="status">Update status</button>` : ""}
          ${t.can_assign ? html`<button class="btn" data-act="assign">${icon("user")} Assign</button>` : ""}
          ${t.can_set_priority ? html`<button class="btn" data-act="priority">Priority</button>` : ""}
          ${t.can_work && can("ticket.link") ? html`<button class="btn ghost" data-act="link" title="Link a related ticket">${icon("link")}</button>` : ""}
          ${!t.can_work && isRequester() && allowed.includes("CLOSED") ? html`<button class="btn primary" data-act="confirm">${icon("check")} Confirm it's fixed</button>` : ""}
          ${!t.can_work && isRequester() && allowed.includes("REOPENED") ? html`<button class="btn" data-act="reopen">Still not working</button>` : ""}
          ${!t.can_work && isRequester() && allowed.includes("CANCELLED") ? html`<button class="btn danger" data-act="cancel">Cancel ticket</button>` : ""}
          ${t.can_delete ? html`<button class="btn danger" data-act="remove" title="Delete this ticket permanently">${icon("trash")} Delete</button>` : ""}
        </div>
      </div>

      ${progress()}
      ${t.status.code === "PENDING_EMPLOYEE" && isRequester() ? html`<div class="notice warn" style="margin-bottom:20px">${icon("alert")}
        <div><b>IT is waiting for your reply</b>Answer in the conversation below — the ticket resumes automatically when you reply.</div></div>` : ""}
      ${t.status.code === "RESOLVED" && isRequester() ? html`<div class="notice" style="margin-bottom:20px">${icon("info")}
        <div><b>This ticket has been resolved</b>Please confirm the fix, or tell us if it's still not working.</div></div>` : ""}

      <div class="grid grid-main-side">
        <div class="stack">
          <div class="card"><div class="card-head"><h2>Description</h2><span class="hint">${fmtDate(t.created_at)}</span></div>
            <div class="card-body"><div class="prose">${t.description}</div>
            ${t.erp ? erpBox(t.erp) : ""}</div></div>

          ${t.resolution_notes ? html`<div class="card"><div class="card-head"><h2>Resolution</h2>
              <span class="hint">${t.resolved_at ? `Resolved ${fmtDate(t.resolved_at)}` : "Previously resolved"}</span></div>
            <div class="card-body"><div class="prose">${t.resolution_notes}</div>
            ${t.root_cause ? html`<div class="erp-box"><h3>Root cause <span class="tag-internal">${icon("lock")} internal</span></h3><div class="prose">${t.root_cause}</div></div>` : ""}
            ${t.closed_at ? html`<p class="small muted" style="margin-top:12px">Closed ${fmtDate(t.closed_at)} · ${closureLabel(t.closure_reason)}</p>` : ""}</div></div>` : ""}

          ${t.can_rate ? ratingCard() : t.rating ? html`<div class="card"><div class="card-body row">
            <span class="stars">${[1, 2, 3, 4, 5].map((i) => html`<button class="${i <= t.rating.rating ? "on" : ""}" disabled tabindex="-1">${icon("star")}</button>`)}</span>
            <span class="muted small">Requester rating${t.rating.comment ? html` — “${t.rating.comment}”` : ""}</span></div></div>` : ""}

          <div class="card">
            <div class="tabs" role="tablist">
              <button role="tab" data-tab="conversation" class="${tab === "conversation" ? "on" : ""}">Messages<span class="n">${comments.length}</span></button>
              <button role="tab" data-tab="history" class="${tab === "history" ? "on" : ""}">History<span class="n">${history.length}</span></button>
            </div>
            ${tab === "conversation" ? conversation() : historyList()}
            ${tab === "conversation" ? (closed ? html`<div class="composer closed-note muted small">${icon("lock")} This ticket is ${t.status.name.toLowerCase()}. Raise a new ticket if you need more help.</div>` : composer()) : ""}
          </div>
        </div>

        <aside class="stack">
          <div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body">
            <dl class="kv">
              <dt>Requester</dt><dd>${nameId(t.requester)}<div class="t-sub2">${realEmail(t.requester.email) || "No email on file"}${t.requester_phone ? html`<br>${t.requester_phone}` : ""}</div></dd>
              <dt>Department</dt><dd>${t.department?.name || "—"}</dd>
              <dt>Location</dt><dd>${t.location?.name || "—"}</dd>
              <dt>IT department</dt><dd>${deskBadge(t.desk)}</dd>
              <dt>Support group</dt><dd>${t.support_group?.name || html`<span class="muted">Awaiting triage</span>`}</dd>
              <dt>Assigned to</dt><dd>${t.assignee ? html`<span class="row" style="gap:8px"><span class="avatar sm">${initials(t.assignee.full_name)}</span>${nameId(t.assignee)}</span>` : html`<span class="muted">Unassigned</span>`}</dd>
              <dt>Impact / urgency</dt><dd>${IMPACT[t.impact]} / ${IMPACT[t.urgency]}</dd>
              <dt>First response</dt><dd>${t.first_response_at ? fmtDate(t.first_response_at) : html`<span class="muted">Not yet</span>`}</dd>
              <dt>Last updated</dt><dd>${fmtRelative(t.updated_at)}</dd>
              ${t.reopen_count ? html`<dt>Reopened</dt><dd>${t.reopen_count}×</dd>` : ""}
            </dl></div></div>
          ${attachmentsCard(closed)}
          ${t.relations.length ? html`<div class="card"><div class="card-head"><h2>Related tickets</h2></div><ul class="list">
            ${t.relations.map((r) => html`<li><a class="item" href="#/tickets/${r.number}"><span class="t-id">${r.number}</span>
              <span class="pill" style="margin-left:6px">${r.relation_type === "duplicate_of" ? (r.direction === "outgoing" ? "duplicate of" : "has duplicate") : "related"}</span>
              <div class="t-sub2">${r.subject} · ${r.status}</div></a></li>`)}</ul></div>` : ""}
        </aside>
      </div>`);
    wire();
  }

  // ---------------------------------------------------------------- pieces
  const erpBox = (e) => {
    const rows = [["Module", e.erp_module], ["Transaction", e.transaction_type], ["Reference", e.reference_no],
      ["Company / branch", e.company_branch], ["Occurred", e.occurred_at && fmtDate(e.occurred_at)],
      ["Workaround", e.workaround_available === null || e.workaround_available === undefined ? null : e.workaround_available ? "Yes" : "No"],
      ["Business impact", e.business_impact]].filter(([, v]) => v);
    const long = [["Error message", e.error_message], ["Expected", e.expected_result], ["Actual", e.actual_result],
      ["Steps to reproduce", e.steps_to_reproduce]].filter(([, v]) => v);
    if (!rows.length && !long.length) return "";
    return html`<div class="erp-box"><h3>ERP details</h3><dl class="kv">${rows.map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}
      ${long.map(([k, v]) => html`<dt>${k}</dt><dd class="prose">${v}</dd>`)}</dl></div>`;
  };
  const closureLabel = (r) => ({ confirmed: "confirmed by requester", auto: "closed automatically", staff: "closed by IT", cancelled: "cancelled" }[r] || "");

  // ---- conversation: chat bubbles + quiet activity lines, grouped by day
  const day = (v) => fmtDate(v, false);
  const clock = (v) => fmtDate(v).split(", ").pop();
  function dayLabel(v) {
    const d = day(v), now = new Date();
    if (d === day(now)) return "Today";
    if (d === day(new Date(now.getTime() - 864e5))) return "Yesterday";
    return d;
  }
  const EVENT_FIELDS = ["created", "status", "assignee", "support_group", "priority"];
  const EV_ICON = { created: "ticket", status: "refresh", assignee: "user", support_group: "layers", priority: "zap" };
  const statusChip = (code) => code ? statusBadge({ code, name: statusNames[code] || code }) : "";

  function conversation() {
    const events = history.filter((h) => EVENT_FIELDS.includes(h.field)).map((h) => ({ kind: "event", at: h.created_at, h }));
    const items = [...comments.map((c) => ({ kind: "msg", at: c.created_at, c })), ...events]
      .sort((a, b) => new Date(a.at) - new Date(b.at));
    // group consecutive activity lines so they don't drown out real messages
    const blocks = [];
    for (const it of items) {
      const label = dayLabel(it.at), last = blocks[blocks.length - 1];
      if (!last || last.day !== label) blocks.push({ kind: "day", day: label });
      const prev = blocks[blocks.length - 1];
      if (it.kind === "event") { if (prev.kind === "events") prev.list.push(it.h); else blocks.push({ kind: "events", day: label, list: [it.h] }); }
      else blocks.push({ kind: "msg", day: label, c: it.c });
    }
    return html`<div class="chat">
      ${comments.length ? "" : html`<div class="chat-empty">${icon("send")}<div><b>No messages yet</b><span>${t.can_work ? "Send the requester an update or ask for details below." : "Write below if you want to add details or ask the IT team something."}</span></div></div>`}
      ${blocks.map((b) => b.kind === "day" ? html`<div class="chat-day"><span>${b.day}</span></div>`
        : b.kind === "events" ? activity(b.list) : bubble(b.c))}
    </div>`;
  }
  function activity(list) {
    const row = (h) => html`<li><span class="act-ic">${icon(EV_ICON[h.field] || "info")}</span><span class="act-txt">${eventText(h)}</span><time title="${fmtDate(h.created_at)}">${clock(h.created_at)}</time></li>`;
    if (list.length <= 3) return html`<ul class="chat-activity">${list.map(row)}</ul>`;
    const hidden = list.slice(0, -2), shown = list.slice(-2);
    return html`<ul class="chat-activity"><li class="act-more"><details><summary>${icon("layers")} ${hidden.length} earlier updates</summary>
      <ul class="chat-activity inner">${hidden.map(row)}</ul></details></li>${shown.map(row)}</ul>`;
  }
  function bubble(c) {
    const me = state.me?.id;
    const fromRequester = c.author.id === t.requester.id;
    const right = c.author.id === me || (t.can_work && !fromRequester);
    const role = c.is_internal ? html`<span class="tag-internal">${icon("lock")} Internal note · IT only</span>`
      : html`<span class="who-role">${fromRequester ? "Requester" : "IT team"}</span>`;
    return html`<div class="msg ${right ? "right" : "left"} ${c.is_internal ? "internal" : fromRequester ? "req" : "it"}">
      <span class="avatar sm">${initials(c.author.full_name)}</span>
      <div class="msg-col"><div class="msg-meta"><b>${c.author.id === me ? "You" : c.author.full_name}</b>${empId(c.author.employee_code)}${role}</div>
        <div class="bubble prose">${c.body}</div>
        <time datetime="${c.created_at}" title="${fmtDate(c.created_at)}">${clock(c.created_at)} · ${fmtRelative(c.created_at)}</time></div></div>`;
  }
  const who = (h) => h.actor ? (h.actor.id === state.me?.id ? "You" : h.actor.full_name) : "System";
  function eventText(h) {
    const why = h.reason ? html` <span class="act-why">“${h.actor ? h.reason : h.reason.replace(/_/g, " ")}”</span>` : "";
    if (h.field === "created") return html`<b>${who(h)}</b> raised this ticket`;
    if (h.field === "status") return html`<b>${who(h)}</b> moved it to ${statusChip(h.new_value)}${why}`;
    if (h.field === "assignee") return h.new_value ? html`<b>${who(h)}</b> assigned it to <b>${h.new_value}</b>` : html`<b>${who(h)}</b> removed ${h.old_value}`;
    if (h.field === "support_group") return html`${h.actor ? html`<b>${who(h)}</b> sent` : "Sent"} to the <b>${h.new_value}</b> team`;
    if (h.field === "priority") return html`<b>${who(h)}</b> changed priority to <b>${h.new_value}</b>${why}`;
    return html`<b>${who(h)}</b> updated ${FIELD_LABEL[h.field] || h.field}`;
  }

  // ---- history: simple vertical timeline, newest first
  function historyList() {
    if (!history.length) return html`<div class="card-body muted small">No changes recorded yet.</div>`;
    const list = history.slice().reverse();
    let lastDay = "";
    const val = (h, v) => h.field === "status" ? statusChip(v) : html`<b>${v}</b>`;
    return html`<ol class="hist">${list.map((h) => {
      const d = dayLabel(h.created_at), head = d !== lastDay; lastDay = d;
      return html`${head ? html`<li class="hist-day">${d}</li>` : ""}
      <li class="hist-item ${h.is_internal ? "internal" : ""}"><span class="hist-dot">${icon(EV_ICON[h.field] || "info")}</span>
        <div class="hist-body"><div class="hist-title">${FIELD_LABEL[h.field] || h.field}${h.is_internal ? html` <span class="tag-internal">${icon("lock")} internal</span>` : ""}</div>
          ${h.field !== "created" && (h.old_value || h.new_value) ? html`<div class="hist-change">
            ${h.old_value ? html`<span class="hist-old">${h.field === "status" ? statusNames[h.old_value] || h.old_value : h.old_value}</span><span class="hist-arrow">→</span>` : ""}
            ${h.new_value ? val(h, h.new_value) : html`<span class="muted">none</span>`}</div>` : ""}
          ${h.reason ? html`<div class="hist-reason">“${h.reason}”</div>` : ""}
          <div class="hist-meta">${who(h)} · <time title="${fmtDate(h.created_at)}">${clock(h.created_at)}</time></div></div></li>`;
    })}</ol>`;
  }

  function progress() {
    if (t.status.code === "CANCELLED") return html`<div class="notice" style="margin-bottom:20px">${icon("x")}<div><b>This ticket was cancelled</b>No further work will be done on it.</div></div>`;
    const cur = STEP_OF[t.status.code] ?? 0;
    const when = [t.created_at, t.assigned_at, t.first_response_at, t.resolved_at, t.closed_at];
    const waiting = { PENDING_EMPLOYEE: isRequester() ? "Waiting for you" : "Waiting for employee", PENDING_VENDOR: "Waiting for vendor",
      PENDING_APPROVAL: "Waiting for approval", PENDING_CHANGE: "Waiting for change", REOPENED: "Reopened" }[t.status.code];
    return html`<ol class="progress" aria-label="Ticket progress">${STEPS.map((name, i) => html`
      <li class="${i < cur ? "done" : i === cur ? "now" : ""} ${i === cur && i < 4 && t.status.code !== "RESOLVED" ? "pulse" : ""}">
        <span class="pg-dot">${i < cur || (i === cur && i === 4) ? icon("check") : i + 1}</span>
        <span class="pg-name">${i === cur && waiting ? waiting : name}</span>
        <span class="pg-when">${i <= cur && when[i] ? fmtRelative(when[i]) : ""}</span></li>`)}</ol>`;
  }

  function composer() {
    const staffNote = t.can_comment_internal;
    return html`<form class="composer ${composeInternal ? "internal-mode" : ""}" id="composer">
      ${staffNote ? html`<div class="compose-modes" id="mode" role="tablist">
        <button type="button" data-v="public" class="${composeInternal ? "" : "on"}">${icon("send")} Reply to requester</button>
        <button type="button" data-v="internal" class="${composeInternal ? "on" : ""}">${icon("lock")} Internal note</button></div>` : ""}
      <div class="compose-box">
        ${t.can_work && !composeInternal ? html`<div class="quick-replies" id="qr"><span class="small muted">${icon("zap")} Quick reply:</span>
          ${QUICK_REPLIES.map(([label], i) => html`<button type="button" class="qr" data-qr="${i}">${label}</button>`)}</div>` : ""}
        <label class="sr-only" for="cbody">Message</label>
        <textarea id="cbody" name="body" rows="3" maxlength="8000" placeholder="${composeInternal ? "Write a note only the IT team will see…" : t.can_work ? `Write a reply to ${t.requester.full_name.split(" ")[0]}…` : "Type your message to the IT team…"}"></textarea>
        <div class="composer-foot">
          ${composeInternal ? html`<span class="small" style="color:var(--internal)">${icon("lock")} Hidden from the requester</span>` : html`<span class="small muted">${t.can_work ? nameIdText(t.requester) : t.assignee ? nameIdText(t.assignee) : "The IT team"} will be notified</span>`}
          <span class="spacer"></span><span class="small muted hide-sm">Ctrl + Enter</span>
          <button class="btn primary" type="submit">${icon("send")} ${composeInternal ? "Add note" : "Send"}</button></div>
      </div></form>`;
  }

  function attachmentsCard(closed) {
    return html`<div class="card"><div class="card-head"><h2>Attachments</h2><span class="hint">${attachments.length}</span></div>
      <div class="card-body">${attachments.length ? attachments.map((a) => html`<div class="attach"><span class="ic">${icon("file")}</span>
        <div style="flex:1;min-width:0"><a href="#" data-dl="${a.id}" data-name="${a.original_name}" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.original_name}</a>
        <span class="t-sub2">${fileSize(a.size_bytes)} · ${nameIdText(a.uploader)}${a.is_internal ? html` · <span class="tag-internal">internal</span>` : ""}</span></div></div>`) :
        html`<p class="muted small">No files attached.</p>`}
      ${!closed && (t.can_work || isRequester()) ? html`<div class="dropzone" id="up" tabindex="0" role="button" style="margin-top:12px">${icon("clip")} Add an image or PDF</div>
        <input type="file" id="upf" hidden accept="image/*,.heic,.heif,.pdf">` : ""}</div></div>`;
  }

  function ratingCard() {
    return html`<div class="card"><div class="card-head"><h2>How did we do?</h2><span class="hint">Your feedback helps the IT team improve</span></div>
      <div class="card-body"><form id="rate" class="stack" style="gap:12px">
        <div class="stars" role="radiogroup" aria-label="Rating">${[1, 2, 3, 4, 5].map((i) => html`<button type="button" data-r="${i}" aria-label="${i} star${i > 1 ? "s" : ""}">${icon("star")}</button>`)}</div>
        <textarea name="comment" rows="2" maxlength="1000" placeholder="Optional comment"></textarea>
        <div><button class="btn primary sm" type="submit" disabled>Submit rating</button></div></form></div></div>`;
  }

  // ---------------------------------------------------------------- behaviour
  async function reload(msg) {
    await loadAll(); draw(); if (msg) toast(msg); refreshUnread();
  }

  function wire() {
    $("#star-btn", view)?.addEventListener("click", async () => {
      const on = !t.starred;
      try { await api.put(`/tickets/${number}/star`, { starred: on }); t.starred = on; draw(); toast(on ? "Starred — find it in the ★ Starred tab." : "Star removed."); }
      catch (ex) { errorToast(ex); }
    });
    $$(".tabs [data-tab]", view).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; draw(); }));
    $("#mode", view)?.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const keep = $("#cbody", view).value;
      composeInternal = b.dataset.v === "internal"; draw(); $("#cbody", view).value = keep; $("#cbody", view).focus();
    });
    const comp = $("#composer", view);
    $("#qr", view)?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-qr]"); if (!b) return;
      const first = t.requester.full_name.split(" ")[0];
      comp.body.value = QUICK_REPLIES[Number(b.dataset.qr)][1].replace("{name}", first);
      comp.body.focus(); comp.body.setSelectionRange(comp.body.value.length, comp.body.value.length);
    });
    if (comp) {
      comp.body.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) comp.requestSubmit(); });
      comp.addEventListener("submit", async (e) => {
        e.preventDefault();
        const body = comp.body.value.trim();
        if (!body) return comp.body.focus();
        const btn = $("button[type=submit]", comp); busy(btn);
        try {
          await api.post(`/tickets/${number}/comments`, { body, is_internal: composeInternal });
          await reload(composeInternal ? "Internal note added." : "Message sent.");
        } catch (ex) { errorToast(ex); busy(btn, false); }
      });
    }
    $$("[data-dl]", view).forEach((a) => a.addEventListener("click", async (e) => {
      e.preventDefault();
      try { await api.download(`/tickets/${number}/attachments/${a.dataset.dl}`, null, a.dataset.name); } catch (ex) { errorToast(ex); }
    }));
    const up = $("#up", view), upf = $("#upf", view);
    if (up) {
      up.addEventListener("click", () => upf.click());
      up.addEventListener("keydown", (e) => { if (e.key === "Enter") upf.click(); });
      upf.addEventListener("change", async () => {
        const f = upf.files[0]; if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        if (composeInternal && t.can_work) fd.append("is_internal", "true");
        try { await api.upload(`/tickets/${number}/attachments`, fd); await reload("File attached."); } catch (ex) { errorToast(ex); }
      });
    }
    const rate = $("#rate", view);
    if (rate) {
      let val = 0;
      const stars = $$("[data-r]", rate);
      stars.forEach((s) => s.addEventListener("click", () => {
        val = Number(s.dataset.r); stars.forEach((x) => x.classList.toggle("on", Number(x.dataset.r) <= val));
        $("button[type=submit]", rate).disabled = false;
      }));
      rate.addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await api.post(`/tickets/${number}/rating`, { rating: val, comment: rate.comment.value.trim() || null }); await reload("Thanks for your feedback!"); }
        catch (ex) { errorToast(ex); }
      });
    }
    $("#actions", view).addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act) ACTIONS[act]?.();
    });
  }

  const doStatus = async (to, extra = {}) => {
    await api.post(`/tickets/${number}/status`, { to_status: to, expected_version: t.version, ...extra });
  };
  const handle409 = async (ex) => {
    if (ex.status === 409) { await reload(); toast("Someone else updated this ticket — showing the latest version.", "info"); }
    else throw ex;
  };

  const ACTIONS = {
    async remove() {
      const ok = await confirmDialog({ title: `Delete ${t.number}?`, danger: true, confirmText: "Delete ticket",
        message: `“${t.subject}” and all its messages and attachments will be removed permanently. This cannot be undone.` });
      if (!ok) return;
      try { await api.del(`/tickets/${number}`); toast(`${t.number} deleted.`); refreshUnread(); location.hash = "#/tickets"; }
      catch (ex) { errorToast(ex); }
    },
    async accept() {
      try { await api.post(`/tickets/${number}/accept`, { expected_version: t.version }); await reload("Ticket accepted — you're on it."); }
      catch (ex) { await handle409(ex).catch(errorToast); }
    },
    async confirm() {
      try { await doStatus("CLOSED"); await reload("Thanks — ticket closed."); } catch (ex) { await handle409(ex).catch(errorToast); }
    },
    reopen() { reasonModal("Reopen ticket", "Tell IT what is still not working.", "Reopen", async (reason) => doStatus("REOPENED", { reason }), "Ticket reopened."); },
    async cancel() {
      reasonModal("Cancel this ticket?", "Let IT know why it is no longer needed.", "Cancel ticket", async (reason) => doStatus("CANCELLED", { reason }), "Ticket cancelled.", true);
    },
    status() { statusModal(); },
    assign() { assignModal(); },
    priority() { priorityModal(); },
    link() { linkModal(); },
  };

  function reasonModal(title, subtitle, cta, fn, done, danger = false) {
    openModal({ title, subtitle, body: html`<form id="rf"><label class="field"><span class="lbl">Reason<span class="req">*</span></span>
        <textarea name="reason" rows="3" maxlength="1000" required></textarea></label></form>`,
      actions: html`<button class="btn" data-close>Back</button><button class="btn ${danger ? "danger solid" : "primary"}" id="rok">${cta}</button>`,
      onMount: (el, close) => $("#rok", el).addEventListener("click", async (e) => {
        const f = $("#rf", el); const reason = f.reason.value.trim();
        if (reason.length < 3) return showFieldErrors(f, { reason: "Please add a short reason." });
        busy(e.currentTarget);
        try { await fn(reason); close(); await reload(done); } catch (ex) { busy(e.currentTarget, false); close(); await handle409(ex).catch(errorToast); }
      }) });
  }

  function statusModal() {
    const opts = t.allowed_transitions;
    openModal({ title: "Update status", subtitle: `Currently ${t.status.name}. Only valid next steps are listed.`, wide: true,
      body: html`<form id="sf" class="stack" style="gap:14px">
        <label class="field"><span class="lbl">New status</span><select name="to_status">${opts.map((s) => html`<option value="${s.code}">${s.name}</option>`)}</select></label>
        <label class="field"><span class="lbl">Reason / message <span class="muted" id="rhint"></span></span>
          <textarea name="reason" rows="2" maxlength="1000"></textarea>
          <div class="help" id="pe-help" hidden>The requester sees this question and is notified. The SLA clock pauses until they reply.</div></label>
        <div id="res-fields" class="stack" style="gap:14px" hidden>
          <label class="field"><span class="lbl">Resolution notes<span class="req">*</span></span>
            <textarea name="resolution_notes" rows="4" maxlength="8000" placeholder="What was done to fix it? The requester will see this.">${t.resolution_notes || ""}</textarea></label>
          <label class="field"><span class="lbl">Root cause <span class="tag-internal">${icon("lock")} internal</span></span>
            <textarea name="root_cause" rows="2" maxlength="4000">${t.root_cause || ""}</textarea></label>
        </div></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="sok">Update</button>`,
      onMount: (el, close) => {
        const f = $("#sf", el);
        const sync = () => {
          const v = f.to_status.value;
          $("#res-fields", el).hidden = v !== "RESOLVED";
          $("#pe-help", el).hidden = v !== "PENDING_EMPLOYEE";
          $("#rhint", el).textContent = ["PENDING_EMPLOYEE", "PENDING_VENDOR", "PENDING_CHANGE", "PENDING_APPROVAL", "CANCELLED", "REOPENED"].includes(v) ? "(required)" : "(optional)";
        };
        f.to_status.addEventListener("change", sync); sync();
        $("#sok", el).addEventListener("click", async (e) => {
          const d = Object.fromEntries(new FormData(f));
          const body = { reason: d.reason.trim() || null };
          if (d.to_status === "RESOLVED") { body.resolution_notes = d.resolution_notes.trim(); body.root_cause = d.root_cause.trim() || null; }
          busy(e.currentTarget);
          try {
            await doStatus(d.to_status, body);
            close(); await reload("Status updated.");
          } catch (ex) {
            busy(e.currentTarget, false);
            if (ex.status === 409) { close(); return handle409(ex); }
            showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex);
          }
        });
      } });
  }

  async function assignModal() {
    const [groups, admins] = await Promise.all([supportGroups(), api.get("/it-admins")]);
    openModal({ title: "Assign ticket", subtitle: "Choose the IT administrator who will handle this ticket. They and the requester are notified by email.",
      body: html`<form id="af" class="stack" style="gap:14px">
        <label class="field"><span class="lbl">Assign to</span><select name="assignee_id">
          <option value="">— Unassigned (IT queue) —</option>
          ${admins.map((a) => html`<option value="${a.id}" ${a.id === t.assignee?.id ? "selected" : ""}>${nameIdText(a)} · ${a.open_tickets} open</option>`)}</select></label>
        <label class="field"><span class="lbl">Support team</span><select name="support_group_id">
          ${groups.map((g) => html`<option value="${g.id}" ${g.id === t.support_group?.id ? "selected" : ""}>${g.name}</option>`)}</select></label>
        <label class="field"><span class="lbl">Note for the assignee</span><input type="text" name="reason" maxlength="500" placeholder="Optional"></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="aok">Save assignment</button>`,
      onMount: (el, close) => {
        const f = $("#af", el);
        $("#aok", el).addEventListener("click", async (e) => {
          const d = Object.fromEntries(new FormData(f));
          busy(e.currentTarget);
          try {
            await api.post(`/tickets/${number}/assign`, { support_group_id: d.support_group_id ? Number(d.support_group_id) : null,
              assignee_id: d.assignee_id ? Number(d.assignee_id) : null, reason: d.reason.trim() || null, expected_version: t.version });
            close(); await reload("Assignment updated.");
          } catch (ex) { busy(e.currentTarget, false); if (ex.status === 409) { close(); return handle409(ex); } showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
        });
      } });
  }

  async function priorityModal() {
    const cat = await catalog();
    openModal({ title: "Change priority", subtitle: "The SLA target is recalculated from the original start time — the clock is not reset.",
      body: html`<form id="pf" class="form-grid">
        <label class="field"><span class="lbl">Impact</span><select name="impact">${[1, 2, 3].map((i) => html`<option value="${i}" ${t.impact === i ? "selected" : ""}>${cat.impact[i]}</option>`)}</select></label>
        <label class="field"><span class="lbl">Urgency</span><select name="urgency">${[1, 2, 3].map((i) => html`<option value="${i}" ${t.urgency === i ? "selected" : ""}>${cat.urgency[i]}</option>`)}</select></label>
        <div class="full row" id="pp"></div>
        <label class="field full"><span class="lbl">Reason<span class="req">*</span></span><input type="text" name="reason" maxlength="500" required></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="pok">Save priority</button>`,
      onMount: (el, close) => {
        const f = $("#pf", el);
        const pv = () => { const m = cat.matrix.find((x) => x.impact === Number(f.impact.value) && x.urgency === Number(f.urgency.value));
          const p = cat.priorities.find((x) => x.code === m?.priority); mount($("#pp", el), html`<span class="muted small">New priority:</span> ${p ? prioBadge(p) : ""}`); };
        f.impact.addEventListener("change", pv); f.urgency.addEventListener("change", pv); pv();
        $("#pok", el).addEventListener("click", async (e) => {
          const d = Object.fromEntries(new FormData(f));
          if (d.reason.trim().length < 5) return showFieldErrors(f, { reason: "Explain the change (at least 5 characters)." });
          busy(e.currentTarget);
          try {
            await api.post(`/tickets/${number}/priority`, { impact: Number(d.impact), urgency: Number(d.urgency), reason: d.reason.trim(), expected_version: t.version });
            close(); await reload("Priority updated.");
          } catch (ex) { busy(e.currentTarget, false); if (ex.status === 409) { close(); return handle409(ex); } errorToast(ex); }
        });
      } });
  }

  function linkModal() {
    openModal({ title: "Link a ticket", body: html`<form id="lf" class="form-grid">
        <label class="field"><span class="lbl">Ticket number</span><input type="text" name="target_number" placeholder="IT-2026-000123" required></label>
        <label class="field"><span class="lbl">Relationship</span><select name="relation_type"><option value="related">Related</option><option value="duplicate_of">This is a duplicate of</option></select></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="lok">Link</button>`,
      onMount: (el, close) => $("#lok", el).addEventListener("click", async () => {
        const d = Object.fromEntries(new FormData($("#lf", el)));
        try { await api.post(`/tickets/${number}/links`, { target_number: d.target_number.trim().toUpperCase(), relation_type: d.relation_type }); close(); await reload("Tickets linked."); }
        catch (ex) { errorToast(ex); }
      }) });
  }

  draw();
}
