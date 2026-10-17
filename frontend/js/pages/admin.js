import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, initials, emptyState, errorToast, toast, openModal, busy,
  confirmDialog, debounce, skeletonRows } from "../ui.js";

// =================================================================== users & roles
export async function renderUsers(view) {
  let q = "", page = 1;
  const roles = await api.get("/admin/roles");
  const roleName = Object.fromEntries(roles.map((r) => [r.code, r.name]));
  mount(view, html`<div class="page-head"><div><h1>Users & roles</h1>
      <div class="sub">Role changes take effect at the user's next sign-in and are recorded in the audit log.</div></div></div>
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
          ${u.id !== state.me.id ? html`<button class="btn sm ghost" data-active="${u.id}" data-on="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button>` : ""}</td></tr>`)}` :
        html`<tr><td colspan="7">${emptyState("No users found", "Try another search.", "users")}</td></tr>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#up", view), html`<span>${r.total} users</span><div class="row"><button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { page--; load(); });
      $("#nx", view).addEventListener("click", () => { page++; load(); });
      $$("[data-roles]", view).forEach((b) => b.addEventListener("click", () => editRoles(r.items.find((u) => String(u.id) === b.dataset.roles))));
      $$("[data-active]", view).forEach((b) => b.addEventListener("click", () => toggleActive(r.items.find((u) => String(u.id) === b.dataset.active))));
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
  async function toggleActive(u) {
    const ok = await confirmDialog({ title: u.is_active ? `Deactivate ${u.full_name}?` : `Activate ${u.full_name}?`,
      message: u.is_active ? "They will be signed out immediately and cannot sign in. Their tickets and history are kept." : "They will be able to sign in again.",
      confirmText: u.is_active ? "Deactivate" : "Activate", danger: u.is_active });
    if (!ok) return;
    try { await api.patch(`/admin/users/${u.id}/active`, { is_active: !u.is_active }); toast("User updated."); load(); } catch (e) { errorToast(e); }
  }
  $("#uq", view).addEventListener("input", debounce((e) => { q = e.target.value.trim(); page = 1; load(); }, 300));
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
