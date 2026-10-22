import { api } from "../api.js";
import { state, catalog, supportGroups, can } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, fmtMinutes, statusBadge, prioBadge, initials, toast, errorToast,
  openModal, busy, emptyState, fileSize, showFieldErrors } from "../ui.js";
import { refreshUnread } from "../app.js";

const FIELD_LABEL = { status: "Status", assignee: "Assignee", support_group: "Support group", priority: "Priority",
  created: "Ticket created", resolution_notes: "Resolution notes", root_cause: "Root cause", attachment: "Attachment",
  link: "Linked", rating: "Rating", sla: "SLA" };
const IMPACT = { 1: "High", 2: "Medium", 3: "Low" };

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
          <div class="ticket-title"><span class="t-id" style="font-size:13.5px">${t.number}</span>${statusBadge(t.status)}${prioBadge(t.priority)}
            ${t.is_demo ? html`<span class="pill demo">Demo data</span>` : ""}</div>
          <h1 style="margin-top:8px">${t.subject}</h1>
          <div class="meta-line"><span>${icon("user")} ${t.requester.full_name}</span><span>${icon("clock")} Raised ${fmtRelative(t.created_at)}</span>
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
        </div>
      </div>

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
              <button role="tab" data-tab="conversation" class="${tab === "conversation" ? "on" : ""}">Conversation<span class="n">${comments.length}</span></button>
              <button role="tab" data-tab="history" class="${tab === "history" ? "on" : ""}">History<span class="n">${history.length}</span></button>
            </div>
            ${tab === "conversation" ? conversation() : historyList()}
            ${tab === "conversation" ? (closed ? html`<div class="composer muted small">${icon("lock")} This ticket is ${t.status.name.toLowerCase()}. Raise a new ticket if you need more help.</div>` : composer()) : ""}
          </div>
        </div>

        <aside class="stack">
          ${slaCard()}
          <div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body">
            <dl class="kv">
              <dt>Requester</dt><dd>${t.requester.full_name}<div class="t-sub2">${t.requester.email}${t.requester_phone ? html`<br>${t.requester_phone}` : ""}</div></dd>
              <dt>Department</dt><dd>${t.department?.name || "—"}</dd>
              <dt>Location</dt><dd>${t.location?.name || "—"}</dd>
              <dt>Support group</dt><dd>${t.support_group?.name || html`<span class="muted">Awaiting triage</span>`}</dd>
              <dt>Assigned to</dt><dd>${t.assignee ? html`<span class="row" style="gap:8px"><span class="avatar sm">${initials(t.assignee.full_name)}</span>${t.assignee.full_name}</span>` : html`<span class="muted">Unassigned</span>`}</dd>
              <dt>Impact / urgency</dt><dd>${IMPACT[t.impact]} / ${IMPACT[t.urgency]}</dd>
              <dt>Contact via</dt><dd style="text-transform:capitalize">${t.contact_method || "portal"}</dd>
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

  function slaCard() {
    const s = t.sla;
    if (!s) return "";
    const label = { on_track: "On track", at_risk: "At risk", breached: "Breached", paused: "Paused", met: "Met" }[s.state];
    const tone = { on_track: "ok", at_risk: "warn", breached: "danger", paused: "", met: "ok" }[s.state];
    const done = ["met", "breached"].includes(s.state) && ["RESOLVED", "CLOSED", "CANCELLED"].includes(t.status.code);
    return html`<div class="card"><div class="card-head"><h2>Service level</h2><span class="badge ${tone}">${label}</span></div>
      <div class="card-body">
        <div class="sla-state"><span class="big">${done ? fmtMinutes(s.resolution_target_minutes - s.remaining_business_minutes) : s.remaining_business_minutes >= 0 ? fmtMinutes(s.remaining_business_minutes) : fmtMinutes(-s.remaining_business_minutes)}</span>
          <span class="muted small">${done ? "business time used" : s.remaining_business_minutes >= 0 ? "business time left" : "over target"}</span></div>
        <div class="sla-bar ${s.state}"><div style="width:${Math.max(3, s.percent_used)}%"></div></div>
        <dl class="kv small" style="grid-template-columns:110px 1fr">
          <dt>Resolve by</dt><dd>${fmtDate(s.resolution_due_at)}${s.is_paused && !done ? html` <span class="muted">(paused)</span>` : ""}</dd>
          <dt>Respond by</dt><dd>${fmtDate(s.response_due_at)} ${t.first_response_at ? html`<span class="badge ${s.response_breached ? "danger" : "ok"} plain">${s.response_breached ? "late" : "met"}</span>` : ""}</dd>
          <dt>Target</dt><dd>${fmtMinutes(s.resolution_target_minutes)} <span class="muted">business</span></dd>
          ${s.paused_minutes ? html`<dt>Paused</dt><dd>${fmtMinutes(s.paused_minutes)}</dd>` : ""}
          ${s.escalation_level ? html`<dt>Escalation</dt><dd>Level ${s.escalation_level}</dd>` : ""}
        </dl></div></div>`;
  }

  function conversation() {
    const events = history.filter((h) => ["status", "assignee", "support_group", "priority"].includes(h.field) || h.field === "created")
      .map((h) => ({ kind: "event", at: h.created_at, h }));
    const items = [...comments.map((c) => ({ kind: "comment", at: c.created_at, c })), ...events]
      .sort((a, b) => new Date(a.at) - new Date(b.at));
    if (!items.length) return html`<div class="card-body muted small">No messages yet.</div>`;
    return html`<ul class="timeline">${items.map((it) => it.kind === "comment" ? html`
      <li class="${it.c.is_internal ? "internal" : ""}"><span class="avatar sm">${initials(it.c.author.full_name)}</span><div style="min-width:0">
        <div class="msg-head"><b>${it.c.author.full_name}</b>${it.c.author.id === t.requester.id ? html`<span class="pill">Requester</span>` : ""}
          ${it.c.is_internal ? html`<span class="tag-internal">${icon("lock")} Internal note</span>` : ""}
          <time datetime="${it.c.created_at}" title="${fmtDate(it.c.created_at)}">${fmtRelative(it.c.created_at)}</time></div>
        <div class="prose">${it.c.body}</div></div></li>` : html`
      <li class="event"><div class="ev-dot"></div><div>${eventText(it.h)} <span class="muted">· ${fmtRelative(it.h.created_at)}</span></div></li>`)}</ul>`;
  }
  const who = (h) => h.actor ? h.actor.full_name : "System";
  function eventText(h) {
    if (h.field === "created") return html`<b>${who(h)}</b> raised the ticket`;
    if (h.field === "status") return html`<b>${who(h)}</b> changed status to <b>${statusNames[h.new_value] || h.new_value}</b>${h.reason ? html` — “${h.reason}”` : ""}`;
    if (h.field === "assignee") return h.new_value ? html`<b>${who(h)}</b> assigned to <b>${h.new_value}</b>` : html`<b>${who(h)}</b> unassigned ${h.old_value}`;
    if (h.field === "support_group") return html`<b>${who(h)}</b> routed to <b>${h.new_value}</b>${h.reason ? html` — ${h.reason}` : ""}`;
    if (h.field === "priority") return html`<b>${who(h)}</b> changed priority ${h.old_value} → <b>${h.new_value}</b>${h.reason ? html` — “${h.reason}”` : ""}`;
    return html`<b>${who(h)}</b> ${h.field}`;
  }
  function historyList() {
    return html`<div class="table-wrap"><table class="data"><thead><tr><th>When</th><th>Change</th><th>From</th><th>To</th><th>By</th><th class="hide-sm">Reason</th></tr></thead><tbody>
      ${history.slice().reverse().map((h) => html`<tr${h.is_internal ? html` style="background:var(--internal-soft)"` : ""}>
        <td class="muted small" style="white-space:nowrap">${fmtDate(h.created_at)}</td>
        <td>${FIELD_LABEL[h.field] || h.field}${h.is_internal ? html` <span class="tag-internal">${icon("lock")}</span>` : ""}</td>
        <td class="muted">${h.field === "status" ? statusNames[h.old_value] || h.old_value || "—" : h.old_value || "—"}</td>
        <td>${h.field === "status" ? statusNames[h.new_value] || h.new_value : h.new_value || "—"}</td>
        <td>${who(h)}</td><td class="hide-sm small">${h.reason || ""}</td></tr>`)}</tbody></table></div>`;
  }

  function composer() {
    const staffNote = t.can_comment_internal;
    return html`<form class="composer ${composeInternal ? "internal-mode" : ""}" id="composer">
      ${staffNote ? html`<div class="seg" style="margin-bottom:10px" id="mode">
        <button type="button" data-v="public" class="${composeInternal ? "" : "on"}">Reply to requester</button>
        <button type="button" data-v="internal" class="${composeInternal ? "on" : ""}">${icon("lock")} Internal note</button></div>` : ""}
      <label class="sr-only" for="cbody">Message</label>
      <textarea id="cbody" name="body" rows="3" maxlength="8000" placeholder="${composeInternal ? "Visible to IT staff only…" : t.can_work ? "Write a reply the requester will see…" : "Add a comment or answer IT's question…"}"></textarea>
      <div class="composer-foot">
        ${composeInternal ? html`<span class="small" style="color:var(--internal)">${icon("lock")} The requester will not see this note.</span>` : html`<span class="small muted">The ${t.can_work ? "requester" : "assigned engineer"} will be notified.</span>`}
        <span class="spacer"></span><span class="small muted">Ctrl + Enter to send</span>
        <button class="btn primary" type="submit">${icon("send")} ${composeInternal ? "Add note" : "Send"}</button></div></form>`;
  }

  function attachmentsCard(closed) {
    return html`<div class="card"><div class="card-head"><h2>Attachments</h2><span class="hint">${attachments.length}</span></div>
      <div class="card-body">${attachments.length ? attachments.map((a) => html`<div class="attach"><span class="ic">${icon("file")}</span>
        <div style="flex:1;min-width:0"><a href="#" data-dl="${a.id}" data-name="${a.original_name}" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.original_name}</a>
        <span class="t-sub2">${fileSize(a.size_bytes)} · ${a.uploader.full_name}${a.is_internal ? html` · <span class="tag-internal">internal</span>` : ""}</span></div></div>`) :
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
    $$(".tabs [data-tab]", view).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; draw(); }));
    $("#mode", view)?.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const keep = $("#cbody", view).value;
      composeInternal = b.dataset.v === "internal"; draw(); $("#cbody", view).value = keep; $("#cbody", view).focus();
    });
    const comp = $("#composer", view);
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
          ${admins.map((a) => html`<option value="${a.id}" ${a.id === t.assignee?.id ? "selected" : ""}>${a.full_name} · ${a.open_tickets} open</option>`)}</select></label>
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
