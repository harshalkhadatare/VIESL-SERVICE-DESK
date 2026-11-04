import { api } from "../api.js";
import { state } from "../state.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, initials, emptyState, errorToast, toast, openModal, busy,
  confirmDialog, debounce, skeletonRows, showFieldErrors, deskBadge } from "../ui.js";

// =================================================================== users & roles
export async function renderUsers(view) {
  let q = "", page = 1;
  const roles = await api.get("/admin/roles");
  const roleName = Object.fromEntries(roles.map((r) => [r.code, r.name]));
  mount(view, html`<div class="page-head"><div><h1>Users & roles</h1>
      <div class="sub">Two roles: <b>Employee</b> raises tickets, <b>IT Administrator</b> works and assigns them.
      Changes are recorded in the audit log.</div></div>
      <div class="row"><button class="btn" id="import-users">${icon("download")} Import from Excel</button>
      <button class="btn primary" id="add-user">${icon("plus")} Add user</button></div></div>
    <div class="card">
      <div class="toolbar"><div class="search-inline">${icon("search")}<input type="search" id="uq" placeholder="Name, email or employee code" aria-label="Search users"></div></div>
      <div class="table-wrap"><table class="data ulist"><thead><tr><th>User</th><th class="hide-sm">Employee code</th><th class="hide-sm hide-md">Department</th>
        <th>Roles</th><th class="hide-sm hide-md">Last sign-in</th><th>Status</th><th></th></tr></thead><tbody id="ur">${skeletonRows(6, 7)}</tbody></table></div>
      <div class="pager" id="up"></div></div>
    <div class="card" style="margin-top:20px"><div class="card-head"><h2>Role permission matrix</h2><span class="hint">Enforced on the server for every request</span></div>
      <div class="card-body flush table-wrap">${matrix(roles)}</div></div>`);

  async function load() {
    try {
      const r = await api.get("/admin/users", { q, page, page_size: 25 });
      if (!$("#ur", view)?.isConnected) return;
      mount($("#ur", view), r.items.length ? html`${r.items.map((u) => html`<tr>
        <td class="u-user"><div class="row" style="flex-wrap:nowrap"><span class="avatar sm">${initials(u.full_name)}</span><div style="min-width:0"><b style="font-weight:600">${u.full_name}</b>
          ${u.is_demo ? html` <span class="pill demo">demo</span>` : ""}<div class="t-sub2">${u.has_email ? u.email : html`<span style="color:var(--warn)">No email yet</span>`}</div></div></div></td>
        <td class="hide-sm mono u-code" data-label="Employee ID">${u.employee_code}</td><td class="hide-sm hide-md u-dept">${u.department || "—"}</td>
        <td class="u-roles">${u.roles.map((c) => html`<span class="pill" style="margin:1px 3px 1px 0">${roleName[c] || c}</span>`)}${u.roles.includes("it_admin") && u.desk ? html` ${deskBadge(u.desk)}` : ""}</td>
        <td class="hide-sm hide-md muted small u-last">${u.last_login_at ? fmtRelative(u.last_login_at) : "Never"}</td>
        <td class="u-status">${!u.is_active ? html`<span class="badge">Inactive</span>` : u.locked ? html`<span class="badge warn">Locked</span>` : html`<span class="badge ok">Active</span>`}</td>
        <td class="u-actions" style="text-align:right;white-space:nowrap"><a class="btn sm ghost" href="#/tickets?scope=all&requester=${encodeURIComponent(u.employee_code)}" title="All tickets raised by ${u.full_name}">${icon("ticket")} Tickets</a>
          <button class="btn sm" data-edit="${u.id}">Edit</button>
          <button class="btn sm" data-roles="${u.id}">Roles</button>
          <button class="btn sm" data-pw="${u.id}">Password</button>
          ${u.id !== state.me.id ? html`<button class="btn sm ghost" data-active="${u.id}" data-on="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button>
          <button class="btn sm ghost icon-only del-user" data-del="${u.id}" title="Delete permanently" aria-label="Delete ${u.full_name} permanently">${icon("trash")}</button>` : ""}</td></tr>`)}` :
        html`<tr><td colspan="7">${emptyState("No users found", "Try another search.", "users")}</td></tr>`);
      const pages = Math.max(1, Math.ceil(r.total / r.page_size));
      mount($("#up", view), html`<span>${r.total} users</span><div class="row"><button class="btn sm" id="pv" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="btn sm" id="nx" ${page >= pages ? "disabled" : ""}>Next</button></div>`);
      $("#pv", view).addEventListener("click", () => { page--; load(); });
      $("#nx", view).addEventListener("click", () => { page++; load(); });
      $$("[data-roles]", view).forEach((b) => b.addEventListener("click", () => editRoles(r.items.find((u) => String(u.id) === b.dataset.roles))));
      $$("[data-active]", view).forEach((b) => b.addEventListener("click", () => toggleActive(r.items.find((u) => String(u.id) === b.dataset.active))));
      $$("[data-edit]", view).forEach((b) => b.addEventListener("click", () => editUser(r.items.find((u) => String(u.id) === b.dataset.edit))));
      $$("[data-del]", view).forEach((b) => b.addEventListener("click", () => deleteUser(r.items.find((u) => String(u.id) === b.dataset.del))));
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
          <input type="text" name="password" maxlength="200" autocomplete="off" required>
          <div class="help">Any password. Tell the user privately.</div></label></form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="pw-save">Save password</button>`,
      onMount: (el, close) => $("#pw-save", el).addEventListener("click", async (e) => {
        const f = $("#pwf", el);
        const pw = f.password.value;
        if (!pw.length) return showFieldErrors(f, { password: "Enter a password." });
        busy(e.currentTarget);
        try { await api.post(`/admin/users/${u.id}/password`, { password: pw }); close(); toast(`Password updated for ${u.full_name}.`); load(); }
        catch (ex) { busy(e.currentTarget, false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
      }) });
  }

  async function deleteUser(u) {
    let pv;
    try { pv = await api.get(`/admin/users/${u.id}/delete-preview`); } catch (e) { return errorToast(e); }
    const lose = [[pv.tickets_raised, "ticket(s) they raised, with all messages and files"],
      [pv.comments, "message(s) they wrote on other tickets"], [pv.attachments, "file(s) they uploaded"],
      [pv.kb_articles, "knowledge-base article(s) they wrote"]].filter(([n]) => n);
    openModal({ title: `Delete ${u.full_name} permanently?`,
      subtitle: "This removes the account from the database. It cannot be undone.",
      body: html`<div class="stack" style="gap:14px">
        <div class="del-sum">${lose.length ? html`<b>Will also be deleted:</b><ul>${lose.map(([n, t]) => html`<li><b>${n}</b> ${t}</li>`)}</ul>`
          : html`<b>Nothing else is deleted</b> — this user has no tickets, messages or files.`}
          ${pv.tickets_assigned ? html`<p class="small" style="margin:8px 0 0">${pv.tickets_assigned} ticket(s) assigned to them will become <b>Unassigned</b>.</p>` : ""}</div>
        ${u.is_active ? html`<div class="notice">${icon("info")}<div>Just leaving the company? <strong>Deactivate</strong> instead — they can't sign in, and their old tickets stay readable.</div></div>` : ""}
        <label class="field"><span class="lbl">Type the employee ID <b class="mono">${u.employee_code}</b> to confirm</span>
          <input type="text" id="del-confirm" autocomplete="off" spellcheck="false"></label></div>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn danger solid" id="del-go" disabled>${icon("trash")} Delete permanently</button>`,
      onMount: (el, close) => {
        const inp = $("#del-confirm", el), go = $("#del-go", el);
        inp.addEventListener("input", () => { go.disabled = inp.value.trim().toUpperCase() !== u.employee_code.toUpperCase(); });
        inp.focus();
        go.addEventListener("click", async () => {
          busy(go);
          try { await api.del(`/admin/users/${u.id}`); close(); toast(`${u.full_name} deleted.`); load(); }
          catch (ex) { busy(go, false); errorToast(ex); }
        });
      } });
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
  $("#import-users", view).addEventListener("click", importUsers);

  async function editUser(u) {
    const depts = await api.get("/departments").catch(() => []);
    openModal({ title: `Edit ${u.full_name}`, subtitle: "Add a real email so this person receives email notifications.", wide: true,
      body: html`<form id="eu" class="form-grid" novalidate>
        <label class="field"><span class="lbl">Full name</span><input type="text" name="full_name" maxlength="150" value="${u.full_name}"></label>
        <label class="field"><span class="lbl">Employee ID (used to sign in)</span><input type="text" name="employee_code" maxlength="30" value="${u.employee_code}"></label>
        <label class="field"><span class="lbl">Company email</span><input type="email" name="email" maxlength="254" value="${u.has_email ? u.email : ""}" placeholder="name@visioninfra.co.in"></label>
        <label class="field"><span class="lbl">Department</span><select name="department_id"><option value="">—</option>
          ${depts.map((d) => html`<option value="${d.id}" ${d.id === u.department_id ? "selected" : ""}>${d.name}</option>`)}</select></label>
        <label class="field"><span class="lbl">Job title</span><input type="text" name="job_title" maxlength="120" value="${u.job_title || ""}"></label>
        <label class="field"><span class="lbl">Phone</span><input type="text" name="phone" maxlength="30" value="${u.phone || ""}"></label>
        ${u.roles.includes("it_admin") ? html`<label class="field"><span class="lbl">IT department (for IT Administrators)</span><select name="desk">
          <option value="it" ${u.desk !== "erp" ? "selected" : ""}>IT — hardware, network, email…</option>
          <option value="erp" ${u.desk === "erp" ? "selected" : ""}>ERP-IT — ERP software</option></select>
          <div class="help">Decides which tickets and dashboard they see first.</div></label>` : ""}</form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="eu-save">Save changes</button>`,
      onMount: (el, close) => $("#eu-save", el).addEventListener("click", async (e) => {
        const f = $("#eu", el);
        const d = Object.fromEntries(new FormData(f));
        const body = { full_name: d.full_name.trim(), employee_code: d.employee_code.trim(),
          department_id: d.department_id ? Number(d.department_id) : null, job_title: d.job_title, phone: d.phone };
        if (d.desk) body.desk = d.desk;
        body.email = d.email.trim() || null;
        busy(e.currentTarget);
        try { await api.patch(`/admin/users/${u.id}`, body); close(); toast("User updated."); load(); }
        catch (ex) { busy(e.currentTarget, false); showFieldErrors(f, ex.fieldErrors?.() || {}); errorToast(ex); }
      }) });
  }

  function importUsers() {
    let file = null;
    openModal({ title: "Import employees from Excel", wide: true,
      subtitle: "Upload an .xlsx or .csv file. Required columns: employee ID (e.g. USER_ID) and name (e.g. USER_NAME). Optional: EMAIL, DEPARTMENT, DESIGNATION, PHONE, ROLE, PASSWORD.",
      body: html`<form id="imp" class="stack" style="gap:14px" novalidate>
        <div class="notice">${icon("info")}<div>New to this? <a href="/static/assets/Employee_Upload_Template.xlsx" download>Download the Excel template</a>
          — fill the first sheet and upload it here.</div></div>
        <div class="field"><span class="lbl">File</span>
          <div class="dropzone" id="imp-drop" tabindex="0" role="button">${icon("file")} <span id="imp-name">Choose or drop your Excel file here</span></div>
          <input type="file" id="imp-file" accept=".xlsx,.csv" hidden></div>
        <div class="form-grid">
          <label class="field"><span class="lbl">Starting password for everyone<span class="req">*</span></span>
            <input type="text" name="default_password" maxlength="200" value="Viesl@2026" autocomplete="off">
            <div class="help">Used unless the file has a PASSWORD column. Employees can change it after signing in.</div></label>
          <label class="field"><span class="lbl">Role for imported people</span><select name="default_role">
            <option value="employee">Employee</option><option value="it_admin">IT Administrator</option></select>
            <div class="help">A ROLE column in the file overrides this.</div></label>
        </div>
        <label class="check"><input type="checkbox" name="update_existing"> Update names/emails of employees who already exist</label>
        <div id="imp-result"></div></form>`,
      actions: html`<button class="btn" data-close>Close</button><button class="btn" id="imp-preview">Preview</button>
        <button class="btn primary" id="imp-go" disabled>Import</button>`,
      onMount: (el, close) => {
        const f = $("#imp", el), drop = $("#imp-drop", el), input = $("#imp-file", el), out = $("#imp-result", el);
        const go = $("#imp-go", el);
        const pick = (fl) => { if (!fl) return; file = fl; $("#imp-name", el).textContent = `${fl.name} · ${(fl.size / 1024).toFixed(0)} KB`; go.disabled = true; out.innerHTML = ""; };
        drop.addEventListener("click", () => input.click());
        drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
        input.addEventListener("change", () => pick(input.files[0]));
        ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
        ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
        drop.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));
        f.addEventListener("change", (e) => { if (e.target !== input) go.disabled = true; });

        async function send(dry, btn) {
          if (!file) { toast("Choose a file first.", "err"); return; }
          if (!f.default_password.value.length) { showFieldErrors(f, { default_password: "Enter a starting password." }); return; }
          const fd = new FormData();
          fd.append("file", file); fd.append("default_password", f.default_password.value);
          fd.append("default_role", f.default_role.value); fd.append("update_existing", f.update_existing.checked ? "true" : "false");
          fd.append("dry_run", dry ? "true" : "false");
          busy(btn);
          let imported = false;
          try {
            const r = await api.upload("/admin/users/import", fd);
            const n = r.created + r.updated;
            mount(out, html`<div class="notice ${r.error_count ? "warn" : ""}">${icon(dry ? "info" : "checkCircle")}<div>
              <b>${dry ? "Preview — nothing saved yet" : "Import finished"}</b>
              ${r.total_rows} rows read · <strong>${r.created}</strong> ${dry ? "will be created" : "created"}${r.updated ? html` · <strong>${r.updated}</strong> ${dry ? "will be updated" : "updated"}` : ""}
              · ${r.skipped_existing} already exist${r.error_count ? html` · <strong style="color:var(--danger)">${r.error_count} with problems</strong>` : ""}
              <div class="small muted" style="margin-top:4px">Columns used: ${Object.entries(r.columns).map(([k, v]) => `${k} → ${v}`).join(", ")}</div></div></div>
              ${r.errors.length ? html`<div class="table-wrap" style="max-height:180px;overflow:auto;margin-top:10px"><table class="data"><thead><tr><th>Row</th><th>Employee ID</th><th>Problem</th></tr></thead>
                <tbody>${r.errors.map((x) => html`<tr><td>${x.row}</td><td class="mono">${x.employee_id || "—"}</td><td>${x.message}</td></tr>`)}</tbody></table></div>` : ""}
              ${dry && r.preview.length ? html`<div class="table-wrap" style="max-height:220px;overflow:auto;margin-top:10px"><table class="data"><thead><tr><th>Row</th><th>Employee ID</th><th>Name</th><th>Action</th></tr></thead>
                <tbody>${r.preview.map((x) => html`<tr><td>${x.row}</td><td class="mono">${x.employee_id}</td><td>${x.name}</td><td>${x.action}</td></tr>`)}</tbody></table>
                ${r.total_rows > r.preview.length ? html`<div class="small muted" style="padding:6px 2px">First ${r.preview.length} rows shown.</div>` : ""}</div>` : ""}
              ${!dry ? html`<p class="small" style="margin-top:10px">Employees sign in with their <b>Employee ID</b> and the starting password. You can see or change passwords with the <b>Password</b> button.</p>` : ""}`);
            if (dry) { go.disabled = n === 0; go.textContent = n ? `Import ${n} employee${n === 1 ? "" : "s"}` : "Nothing to import"; }
            else { imported = true; load(); }
          } catch (ex) {
            mount(out, html`<div class="notice danger">${icon("alert")}<div>${ex.message}</div></div>`);
          } finally {
            busy(btn, false);
            if (!dry) { go.disabled = true; if (imported) go.textContent = "Imported"; }
          }
        }
        $("#imp-preview", el).addEventListener("click", (e) => send(true, e.currentTarget));
        go.addEventListener("click", (e) => send(false, e.currentTarget));
      } });
  }

  async function addUser() {
    const depts = await api.get("/departments").catch(() => []);
    openModal({ title: "Add user", subtitle: "They sign in with their Employee ID. Add an email only if they have one — updates are emailed there.", wide: true,
      body: html`<form id="nu" class="form-grid" novalidate>
        <label class="field"><span class="lbl">Full name<span class="req">*</span></span><input type="text" name="full_name" maxlength="150" required></label>
        <label class="field"><span class="lbl">Company email <span class="muted" style="font-weight:400">(optional)</span></span><input type="email" name="email" maxlength="254" placeholder="Leave blank if they don't have one"></label>
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
        <div class="field full" id="desk-row" hidden><span class="lbl">IT department</span>
          <div class="choice-grid" style="grid-template-columns:1fr 1fr" id="desk-pick2">
            <div class="choice on" data-v="it" role="radio" tabindex="0"><b>IT</b><span>Hardware, network, email, accounts</span></div>
            <div class="choice" data-v="erp" role="radio" tabindex="0"><b>ERP-IT</b><span>ERP software, data, reports</span></div>
          </div></div>
        <label class="field full"><span class="lbl">Temporary password<span class="req">*</span></span>
          <input type="text" name="password" required autocomplete="off">
          <div class="help">Any password. Share it privately; the user can change it after signing in.</div></label>
        </form>`,
      actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="nu-save">Create user</button>`,
      onMount: (el, close) => {
        let role = "employee", desk = "it";
        $("#role-pick", el).addEventListener("click", (e) => {
          const c = e.target.closest(".choice"); if (!c) return;
          role = c.dataset.v; $$("#role-pick .choice", el).forEach((x) => x.classList.toggle("on", x === c));
          $("#desk-row", el).hidden = role !== "it_admin";
        });
        $("#desk-pick2", el).addEventListener("click", (e) => {
          const c = e.target.closest(".choice"); if (!c) return;
          desk = c.dataset.v; $$("#desk-pick2 .choice", el).forEach((x) => x.classList.toggle("on", x === c));
        });
        $("#nu-save", el).addEventListener("click", async (e) => {
          const f = $("#nu", el);
          const d = Object.fromEntries(new FormData(f));
          busy(e.currentTarget);
          try {
            await api.post("/admin/users", { full_name: d.full_name.trim(), email: d.email.trim() || null, employee_code: d.employee_code.trim(),
              department_id: d.department_id ? Number(d.department_id) : null, job_title: d.job_title.trim() || null,
              phone: d.phone.trim() || null, role, password: d.password, ...(role === "it_admin" ? { desk } : {}) });
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
