import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, initials, emptyState, errorToast, toast, openModal, busy,
  confirmDialog, debounce, skeletonRows, showFieldErrors } from "../ui.js";

// =================================================================== users & roles
export async function renderUsers(view) {
  let q = "", page = 1;
  const roles = await api.get("/admin/roles");
  const roleName = Object.fromEntries(roles.map((r) => [r.code, r.name]));
  mount(view, html`<div class="page-head"><div><h1>Users & roles</h1>
      <div class="sub">Two roles: <b>Employee</b> raises tickets, <b>IT Administrator</b> works and assigns them.
      Changes are recorded in the audit log.</div></div>
      <button class="btn primary" id="add-user">${icon("plus")} Add user</button></div>
    <div class="card">
      <div class="toolbar"><div class="search-inline">${icon("search")}<input type="search" id="uq" placeholder="Name, email or employee code" aria-label="Search users"></div></div>
      <div class="table-wrap"><table class="data"><thead><tr><th>User</th><th class="hide-sm">Employee code</th><th class="hide-sm">Department</th>
        <th>Roles</th><th class="hide-sm">Last sign-in</th><th>Status</th><th></th></tr></thead><tbody id="ur">${skeletonRows(6, 7)}</tbody></table></div>
      <div class="pager" id="up"></div></div>
    <div class="card" style="margin-top:20px"><div class="card-head"><h2>Role permission matrix</h2><span class="hint">Enforced on the server for every request</span></div>
      <div class="card-body flush table-wrap">${matrix(roles)}</div></div>`);

  async function load() {
    try {
      const r = await api.get("/admin/users", { q, page, page_size: 25 });
      if (!$("#ur", view)?.isConnected) return;
      mount($("#ur", view), r.items.length ? html`${r.items.map((u) => html`<tr>
        <td><div class="row" style="flex-wrap:nowrap"><span class="avatar sm">${initials(u.full_name)}</span><div style="min-width:0"><b style="font-weight:600">${u.full_name}</b>
          ${u.is_demo ? html` <span class="pill demo">demo</span>` : ""}<div class="t-sub2">${u.email}</div></div></div></td>
        <td class="hide-sm mono">${u.employee_code}</td><td class="hide-sm">${u.department || "—"}</td>
        <td>${u.roles.map((c) => html`<span class="pill" style="margin:1px 3px 1px 0">${roleName[c] || c}</span>`)}</td>
        <td class="hide-sm muted small">${u.last_login_at ? fmtRelative(u.last_login_at) : "Never"}</td>
        <td>${!u.is_active ? html`<span class="badge">Inactive</span>` : u.locked ? html`<span class="badge warn">Locked</span>` : html`<span class="badge ok">Active</span>`}</td>
        <td style="text-align:right;white-space:nowrap"><button class="btn sm" data-roles="${u.id}">Roles</button>
          <button class="btn sm" data-pw="${u.id}">${icon("key")} Password</button>
          ${u.id !== state.me.id ? html`<button class="btn sm ghost" data-active="${u.id}" data-on="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button>` : ""}</td></tr>`)}` :
        html`<tr><td colspan="7">${emptyState("No users found", "Try another search.", "users")}</td></tr>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#up", view), html`<span>${r.total} users</span><div class="row"><button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { page--; load(); });
      $("#nx", view).addEventListener("click", () => { page++; load(); });
      $$("[data-roles]", view).forEach((b) => b.addEventListener("click", () => editRoles(r.items.find((u) => String(u.id) === b.dataset.roles))));
      $$("[data-active]", view).forEach((b) => b.addEventListener("click", () => toggleActive(r.items.find((u) => String(u.id) === b.dataset.active))));
      $$("[data-pw]", view).forEach((b) => b.addEventListener("click", () => resetPassword(r.items.find((u) => String(u.id) === b.dataset.pw))));
    } catch (e) { errorToast(e); }
  }

  function editRoles(u) {
    openModal({ title: `Roles for ${u.full_name}`, subtitle: "Grant the least privilege needed. The user's sessions are signed out to apply changes.",
      body: html`<form id="rf" class="stack" style="gap:10px">${roles.map((r) => html`<label class="check" style="align-items:flex-start;padding:8px 10px;border:1px solid var(--border);border-radius:8px">
        <input type="checkbox" name="role" value="${r.code}" ${u.roles.includes(r.code) ? "checked" : ""}>
        <span><b>${r.name}</b><div class="t-sub2">${r.description}</div></span></label>`)}</form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="rs">Save roles</button>`,
      onMount: (el, close) => $("#rs", el).addEventListener("click", async (e) => {
        const sel = $$("input[name=role]:checked", el).map((i) => i.value);
        if (!sel.length) return toast("Select at least one role.", "err");
        busy(e.currentTarget);
        try { await api.put(`/admin/users/${u.id}/roles`, { roles: sel }); close(); toast("Roles updated."); load(); }
        catch (ex) { busy(e.currentTarget, false); errorToast(ex); }
      }) });
  }
  function resetPassword(u) {
    openModal({ title: `Set password for ${u.full_name}`, subtitle: "The account is also unlocked and signed out on other devices.",
      body: html`<form id="pwf" class="stack" style="gap:12px" novalidate>
        <label class="field"><span class="lbl">New password<span class="req">*</span></span>
          <input type="text" name="password" minlength="6" maxlength="200" autocomplete="off" required>
          <div class="help">At least 6 characters. Tell the user privately.</div></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="pw-save">Save password</button>`,
      onMount: (el, close) => $("#pw-save", el).addEventListener("click", async (e) => {
        const f = $("#pwf", el);
        const pw = f.password.value;
        if (pw.length < 6) return showFieldErrors(f, { password: "At least 6 characters." });
        busy(e.currentTarget);
        try { await api.post(`/admin/users/${u.id}/password`, { password: pw }); close(); toast(`Password updated for ${u.full_name}.`); load(); }
        catch (ex) { busy(e.currentTarget, false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
      }) });
  }

  async function toggleActive(u) {
    const ok = await confirmDialog({ title: u.is_active ? `Deactivate ${u.full_name}?` : `Activate ${u.full_name}?`,
      message: u.is_active ? "They will be signed out immediately and cannot sign in. Their tickets and history are kept." : "They will be able to sign in again.",
      confirmText: u.is_active ? "Deactivate" : "Activate", danger: u.is_active });
    if (!ok) return;
    try { await api.patch(`/admin/users/${u.id}/active`, { is_active: !u.is_active }); toast("User updated."); load(); } catch (e) { errorToast(e); }
  }
  $("#uq", view).addEventListener("input", debounce((e) => { q = e.target.value.trim(); page = 1; load(); }, 300));
  $("#add-user", view).addEventListener("click", addUser);

  async function addUser() {
    const depts = await api.get("/departments").catch(() => []);
    openModal({ title: "Add user", subtitle: "Use the person's real company email — notifications are emailed there.", wide: true,
      body: html`<form id="nu" class="form-grid" novalidate>
        <label class="field"><span class="lbl">Full name<span class="req">*</span></span><input type="text" name="full_name" maxlength="150" required></label>
        <label class="field"><span class="lbl">Company email<span class="req">*</span></span><input type="email" name="email" maxlength="254" required></label>
        <label class="field"><span class="lbl">Employee code<span class="req">*</span></span><input type="text" name="employee_code" maxlength="30" required></label>
        <label class="field"><span class="lbl">Department</span><select name="department_id"><option value="">—</option>
          ${depts.map((d) => html`<option value="${d.id}">${d.name}</option>`)}</select></label>
        <label class="field"><span class="lbl">Job title</span><input type="text" name="job_title" maxlength="120"></label>
        <label class="field"><span class="lbl">Phone</span><input type="text" name="phone" maxlength="30"></label>
        <div class="field full"><span class="lbl">Role</span>
          <div class="choice-grid" style="grid-template-columns:1fr 1fr" id="role-pick">
            <div class="choice on" data-v="employee" role="radio" tabindex="0"><b>Employee</b><span>Raises and tracks own tickets</span></div>
            <div class="choice" data-v="it_admin" role="radio" tabindex="0"><b>IT Administrator</b><span>Works and assigns all tickets</span></div>
          </div></div>
        <label class="field full"><span class="lbl">Temporary password<span class="req">*</span></span>
          <input type="text" name="password" minlength="10" required autocomplete="off">
          <div class="help">At least 10 characters with upper and lower case letters and a digit. Share it privately; the user can change it after signing in.</div></label>
        </form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="nu-save">Create user</button>`,
      onMount: (el, close) => {
        let role = "employee";
        $("#role-pick", el).addEventListener("click", (e) => {
          const c = e.target.closest(".choice"); if (!c) return;
          role = c.dataset.v; $$(".choice", el).forEach((x) => x.classList.toggle("on", x === c));
        });
        $("#nu-save", el).addEventListener("click", async (e) => {
          const f = $("#nu", el);
          const d = Object.fromEntries(new FormData(f));
          busy(e.currentTarget);
          try {
            await api.post("/admin/users", { full_name: d.full_name.trim(), email: d.email.trim(), employee_code: d.employee_code.trim(),
              department_id: d.department_id ? Number(d.department_id) : null, job_title: d.job_title.trim() || null,
              phone: d.phone.trim() || null, role, password: d.password });
            close(); toast(`${d.full_name} added.`); load();
          } catch (ex) { busy(e.currentTarget, false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
        });
      } });
  }
  await load();
}

function matrix(roles) {
  const perms = [...new Set(roles.flatMap((r) => r.permissions))].sort();
  return html`<table class="data"><thead><tr><th>Permission</th>${roles.map((r) => html`<th style="text-align:center">${r.name}</th>`)}</tr></thead>
    <tbody>${perms.map((p) => html`<tr><td class="mono">${p}</td>${roles.map((r) => html`<td style="text-align:center">${r.permissions.includes(p) ? html`<span style="color:var(--ok)">${icon("check")}</span>` : html`<span class="muted">·</span>`}</td>`)}</tr>`)}</tbody></table>`;
}

// =================================================================== audit log
export async function renderAudit(view) {
  let page = 1, action = "", actor = "";
  mount(view, html`<div class="page-head"><div><h1>Audit log</h1><div class="sub">Sign-ins, role changes, ticket actions, exports and downloads. Read-only.</div></div></div>
    <div class="card"><div class="toolbar">
      <select id="aa" aria-label="Action"><option value="">All actions</option><option value="auth.">Authentication</option><option value="admin.">Administration</option>
        <option value="ticket.">Ticket actions</option><option value="report.">Exports</option></select>
      <div class="search-inline">${icon("search")}<input type="search" id="au" placeholder="Filter by user email" aria-label="Filter by user"></div></div>
      <div class="table-wrap"><table class="data"><thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th class="hide-sm">Detail</th><th class="hide-sm">IP</th><th>Result</th></tr></thead>
      <tbody id="al">${skeletonRows(8, 7)}</tbody></table></div><div class="pager" id="ap"></div></div>`);
  async function load() {
    try {
      const r = await api.get("/audit-logs", { page, page_size: 50, action, actor });
      if (!$("#al", view)?.isConnected) return;
      mount($("#al", view), r.items.length ? html`${r.items.map((a) => html`<tr>
        <td class="small" style="white-space:nowrap">${fmtDate(a.created_at)}</td><td class="small">${a.actor_label || "System"}</td>
        <td><span class="mono">${a.action}</span></td>
        <td class="small">${a.entity_type === "ticket" && a.entity_id ? html`<a href="#/tickets/${a.entity_id}">${a.entity_id}</a>` : a.entity_id ? `${a.entity_type} ${a.entity_id}` : "—"}</td>
        <td class="hide-sm small muted" style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${a.detail || ""}">${a.detail || ""}</td>
        <td class="hide-sm small mono">${a.ip_address || ""}</td>
        <td>${a.outcome === "success" ? html`<span class="badge ok">OK</span>` : html`<span class="badge danger">${a.outcome}</span>`}</td></tr>`)}` :
        html`<tr><td colspan="7">${emptyState("No audit entries", "Nothing matches these filters.", "shield")}</td></tr>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#ap", view), html`<span>${r.total} entries</span><div class="row"><button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { page--; load(); });
      $("#nx", view).addEventListener("click", () => { page++; load(); });
    } catch (e) { errorToast(e); }
  }
  $("#aa", view).addEventListener("change", (e) => { action = e.target.value; page = 1; load(); });
  $("#au", view).addEventListener("input", debounce((e) => { actor = e.target.value.trim(); page = 1; load(); }, 300));
  await load();
}

// =================================================================== email notifications
export async function renderEmail(view) {
  mount(view, html`<div class="page-head"><div><h1>Email notifications</h1>
      <div class="sub">Employees and IT administrators receive an email for every in-app notification:
      new tickets, assignments (with the assigned person's name), replies, status changes and resolution.</div></div></div>
    <div class="grid grid-main-side">
      <div class="card"><div class="card-head"><h2>Mail server</h2><span id="em-badge"></span></div>
        <div class="card-body" id="em-body"><div class="skeleton"></div></div></div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Send a test email</h2></div>
          <div class="card-body"><form id="tf" class="stack" style="gap:12px">
            <label class="field"><span class="lbl">Send to</span><input type="email" name="to" value="${state.me.email}"></label>
            <button class="btn primary" type="submit">${icon("send")} Send test email</button></form>
            <div id="tf-result" style="margin-top:12px"></div></div></div>
        <div class="card"><div class="card-body small">
          <div class="row" style="gap:8px;margin-bottom:8px">${icon("info")}<b>How to turn email on</b></div>
          <p class="muted">Mail settings are kept in the server environment (never in the browser) so the password stays secret.
          Set these variables, then restart or redeploy:</p>
          <pre class="mono" style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:10px;white-space:pre-wrap;margin:10px 0 0">EMAIL_ENABLED=true
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=it-servicedesk@yourcompany.com
SMTP_PASSWORD=********
SMTP_FROM=it-servicedesk@yourcompany.com
APP_BASE_URL=https://your-portal-address</pre></div></div>
      </div>
    </div>`);

  async function load() {
    try {
      const s = await api.get("/admin/email");
      if (!$("#em-body", view)?.isConnected) return;
      mount($("#em-badge", view), s.configured ? html`<span class="badge ok">Active</span>`
        : html`<span class="badge warn">${s.enabled ? "Incomplete" : "Off"}</span>`);
      mount($("#em-body", view), html`
        ${s.configured ? "" : html`<div class="notice warn" style="margin-bottom:16px">${icon("alert")}<div><b>Emails are not being sent</b>
          Notifications still appear in the app. Configure the mail server (see the right-hand panel) to start sending emails.</div></div>`}
        <dl class="kv">
          <dt>Status</dt><dd>${s.configured ? "Sending emails" : s.enabled ? "Enabled, but SMTP host missing" : "Disabled"}</dd>
          <dt>SMTP server</dt><dd class="mono">${s.smtp_host}:${s.smtp_port}</dd>
          <dt>Security</dt><dd>${s.security}</dd>
          <dt>From</dt><dd>${s.from_name} &lt;${s.from_address}&gt;</dd>
          <dt>Links point to</dt><dd class="mono">${s.portal_url}</dd>
          <dt>Sent (7 days)</dt><dd>${s.sent_last_7_days}</dd>
          <dt>Waiting</dt><dd>${s.pending}</dd>
          <dt>Failed</dt><dd>${s.failed ? html`<span style="color:var(--danger);font-weight:600">${s.failed}</span>` : "0"}</dd>
          ${s.last_error ? html`<dt>Last error</dt><dd class="small" style="color:var(--danger)">${s.last_error}</dd>` : ""}
        </dl>
        <p class="small muted" style="margin-top:14px">Demo accounts (addresses ending in example.com) never receive emails.
          Failed emails are retried automatically up to 5 times.</p>`);
    } catch (e) { errorToast(e); }
  }
  $("#tf", view).addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", e.target), out = $("#tf-result", view);
    busy(btn);
    try {
      const r = await api.post("/admin/email/test", { to: e.target.to.value.trim() || null });
      mount(out, html`<div class="notice">${icon("checkCircle")}<div>${r.message}</div></div>`);
    } catch (ex) {
      mount(out, html`<div class="notice danger">${icon("alert")}<div>${ex.message}</div></div>`);
    } finally { busy(btn, false); load(); }
  });
  await load();
}
