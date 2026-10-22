import { api } from "../api.js";
import { state, catalog } from "../state.js";
import { $, $$, html, mount, icon, debounce, busy, toast, errorToast, showFieldErrors, prioBadge, fileSize } from "../ui.js";

const ALLOWED = ".png,.jpg,.jpeg,.gif,.webp,.bmp,.tif,.tiff,.heic,.heif,.pdf";
const MAX_MB = 10;

export async function render(view) {
  const cat = await catalog();
  const me = state.me;
  const files = [];
  const idemKey = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random();
  let impact = 3, urgency = 3;

  mount(view, html`
    <div class="crumbs"><a href="#/tickets">Tickets</a> / <span>New</span></div>
    <div class="page-head"><div><h1>Raise a ticket</h1>
      <div class="sub">Raising as <b>${me.full_name}</b>${me.department ? html` · ${me.department}` : ""}${me.location ? html` · ${me.location}` : ""}</div></div></div>
    <div class="grid grid-main-side">
      <form class="card" id="tf" novalidate>
        <div class="card-body" style="padding:22px 24px">
          <section class="form-section">
            <div class="fieldset-title">What do you need help with?</div>
            <div class="fieldset-sub">Pick the closest category — it decides which team receives your ticket.</div>
            <div class="form-grid">
              <label class="field"><span class="lbl">Category<span class="req">*</span></span>
                <select name="category_id" required><option value="">Select a category…</option>
                  ${cat.categories.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select>
                <div class="help" id="cat-help"></div></label>
              <label class="field"><span class="lbl">Subcategory</span>
                <select name="subcategory_id" disabled><option value="">—</option></select></label>
              <div class="field full"><span class="lbl">Type</span>
                <div class="seg" id="type-seg"><button type="button" data-v="incident" class="on">Something is broken</button>
                <button type="button" data-v="service_request">I need something</button></div></div>
            </div>
          </section>

          <section class="form-section">
            <div class="fieldset-title">Describe the issue</div>
            <div class="fieldset-sub">A clear subject and the exact error text help us fix it faster.</div>
            <div class="stack" style="gap:16px">
              <label class="field"><span class="lbl">Subject<span class="req">*</span></span>
                <input type="text" name="subject" maxlength="200" required placeholder="e.g. Purchase order approval screen shows an error"></label>
              <div id="dupes"></div>
              <label class="field"><span class="lbl">Description<span class="req">*</span></span>
                <textarea name="description" rows="5" maxlength="8000" required placeholder="What happened? When did it start? Who else is affected?"></textarea>
                <div class="help"><span id="desc-count">0</span> / 8000</div></label>
            </div>
          </section>

          <section class="form-section" id="erp-section" hidden>
            <div class="fieldset-title">ERP details</div>
            <div class="fieldset-sub">Optional, but these let the ERP team reproduce the problem without calling you.</div>
            <div class="form-grid">
              <label class="field"><span class="lbl">ERP module</span><select name="erp_module"><option value="">Select…</option>
                ${cat.erp_modules.map((m) => html`<option>${m}</option>`)}</select></label>
              <label class="field"><span class="lbl">Transaction / document type</span><input type="text" name="transaction_type" maxlength="80" placeholder="e.g. Purchase Order"></label>
              <label class="field"><span class="lbl">Document reference no.</span><input type="text" name="reference_no" maxlength="80" placeholder="e.g. PO/PUN/2026/01482"></label>
              <label class="field"><span class="lbl">Company / branch / project</span><input type="text" name="company_branch" maxlength="120"></label>
              <label class="field"><span class="lbl">When did it happen?</span><input type="datetime-local" name="occurred_at"></label>
              <div class="field"><span class="lbl">Is there a workaround?</span>
                <div class="seg" id="wa-seg"><button type="button" data-v="">Not sure</button><button type="button" data-v="true">Yes</button><button type="button" data-v="false">No</button></div></div>
              <label class="field full"><span class="lbl">Error message</span><textarea name="error_message" rows="2" maxlength="4000" placeholder="Copy the exact text shown on screen"></textarea></label>
              <label class="field"><span class="lbl">Expected result</span><textarea name="expected_result" rows="2" maxlength="4000"></textarea></label>
              <label class="field"><span class="lbl">Actual result</span><textarea name="actual_result" rows="2" maxlength="4000"></textarea></label>
              <label class="field full"><span class="lbl">Steps to reproduce</span><textarea name="steps_to_reproduce" rows="3" maxlength="4000" placeholder="1. Open …&#10;2. Click …"></textarea></label>
              <label class="field full"><span class="lbl">Business impact</span><input type="text" name="business_impact" maxlength="500" placeholder="e.g. Month-end billing for Mumbai branch is blocked"></label>
            </div>
          </section>

          <section class="form-section">
            <div class="fieldset-title">How much is this affecting work?</div>
            <div class="fieldset-sub">Priority is calculated from impact and urgency using the company's policy.</div>
            <div class="field"><span class="lbl">Impact — who is affected?</span><div class="choice-grid" id="impact">
              ${[1, 2, 3].map((i) => html`<div class="choice ${i === 3 ? "on" : ""}" role="radio" tabindex="0" aria-checked="${i === 3}" data-v="${i}">
                <b>${["High", "Medium", "Low"][i - 1]}</b><span>${cat.impact[i].split("— ")[1]}</span></div>`)}</div></div>
            <div class="field" style="margin-top:14px"><span class="lbl">Urgency — how soon is it needed?</span><div class="choice-grid" id="urgency">
              ${[1, 2, 3].map((i) => html`<div class="choice ${i === 3 ? "on" : ""}" role="radio" tabindex="0" aria-checked="${i === 3}" data-v="${i}">
                <b>${["High", "Medium", "Low"][i - 1]}</b><span>${cat.urgency[i].split("— ")[1]}</span></div>`)}</div></div>
          </section>

          <section class="form-section">
            <div class="fieldset-title">Contact & attachments</div>
            <div class="form-grid" style="margin-top:12px">
              <label class="field"><span class="lbl">Preferred contact</span><select name="contact_method">
                <option value="portal">This portal</option><option value="email">Email</option><option value="phone">Phone</option><option value="teams">Teams</option></select></label>
              <label class="field"><span class="lbl">Related ticket (optional)</span><input type="text" name="related_ticket_number" placeholder="IT-2026-000123" pattern="IT-\\d{4}-\\d{6}"></label>
              <div class="field full"><span class="lbl">Screenshots or PDF</span>
                <div class="dropzone" id="drop" tabindex="0" role="button">${icon("clip")} Drop files here or <u>browse</u> · up to ${MAX_MB} MB each · images and PDF only</div>
                <input type="file" id="file" multiple accept="image/*,${ALLOWED}" hidden>
                <div id="file-list"></div></div>
            </div>
          </section>
        </div>
        <div class="modal-foot" style="justify-content:space-between;align-items:center">
          <span class="small muted">Your name, department and location are added automatically.</span>
          <div class="row"><a class="btn" href="#/tickets">Cancel</a><button class="btn primary" type="submit">${icon("send")} Submit ticket</button></div>
        </div>
      </form>

      <aside class="stack">
        <div class="card"><div class="card-head"><h2>Calculated priority</h2></div>
          <div class="card-body"><div id="prio-preview" style="font-size:15px"></div>
          <p class="small muted" id="prio-desc" style="margin-top:8px"></p></div></div>
        <div class="card"><div class="card-head"><h2>Might already be answered</h2></div>
          <div class="card-body" id="kb-suggest"><p class="small muted">Start typing a subject to see related help articles.</p></div></div>
        <div class="card"><div class="card-body small">
          <div class="row" style="gap:8px;margin-bottom:8px">${icon("info")}<b>Tips for a fast fix</b></div>
          <ul class="muted" style="margin:0;padding-left:18px;line-height:1.7">
            <li>One issue per ticket.</li><li>Include the exact error text or a screenshot.</li>
            <li>For security incidents, do not forward the suspicious email to colleagues.</li></ul></div></div>
      </aside>
    </div>`);

  const form = $("#tf", view);
  let ticketType = "incident", workaround = "";

  const setSeg = (seg, v) => $$("button", seg).forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  $("#type-seg", view).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { ticketType = b.dataset.v; setSeg(e.currentTarget, ticketType); } });
  $("#wa-seg", view).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { workaround = b.dataset.v; setSeg(e.currentTarget, workaround); } });
  setSeg($("#wa-seg", view), "");

  form.category_id.addEventListener("change", () => {
    const c = cat.categories.find((x) => String(x.id) === form.category_id.value);
    const sub = form.subcategory_id;
    mount(sub, html`<option value="">${c?.subcategories.length ? "Select…" : "—"}</option>${(c?.subcategories || []).map((s) => html`<option value="${s.id}">${s.name}</option>`)}`);
    sub.disabled = !c?.subcategories.length;
    $("#erp-section", view).hidden = !c?.uses_erp_fields;
    if (c) { ticketType = c.default_ticket_type; setSeg($("#type-seg", view), ticketType); }
    $("#cat-help", view).textContent = c?.requires_approval ? "This request type needs approval before work starts." : (c?.description || "");
    checkDupes(); suggest();
  });

  function wireChoices(id, set) {
    const box = $(id, view);
    const pick = (el) => { $$(".choice", box).forEach((c) => { c.classList.toggle("on", c === el); c.setAttribute("aria-checked", c === el); }); set(Number(el.dataset.v)); preview(); };
    box.addEventListener("click", (e) => { const c = e.target.closest(".choice"); if (c) pick(c); });
    box.addEventListener("keydown", (e) => { const c = e.target.closest(".choice"); if (c && (e.key === " " || e.key === "Enter")) { e.preventDefault(); pick(c); } });
  }
  wireChoices("#impact", (v) => { impact = v; });
  wireChoices("#urgency", (v) => { urgency = v; });

  function preview() {
    const row = cat.matrix.find((m) => m.impact === impact && m.urgency === urgency);
    const p = cat.priorities.find((x) => x.code === row?.priority) || cat.priorities[cat.priorities.length - 1];
    mount($("#prio-preview", view), prioBadge(p));
    $("#prio-desc", view).textContent = p.description || "";
  }
  preview();

  form.description.addEventListener("input", () => { $("#desc-count", view).textContent = form.description.value.length; });

  const checkDupes = debounce(async () => {
    const subject = form.subject.value.trim();
    const box = $("#dupes", view);
    if (subject.length < 6) { box.innerHTML = ""; return; }
    try {
      const d = await api.post("/tickets/duplicate-check", { subject, category_id: form.category_id.value ? Number(form.category_id.value) : null });
      mount(box, d.length ? html`<div class="notice warn">${icon("alert")}<div><b>You may already have a ticket for this</b>
        ${d.map((x) => html`<div><a href="#/tickets/${x.number}" target="_blank" rel="noopener">${x.number}</a> — ${x.subject} <span class="muted">(${x.status})</span></div>`)}
        <div class="small muted" style="margin-top:4px">Add a comment there instead of raising a new ticket, if it's the same issue.</div></div></div>` : "");
    } catch { box.innerHTML = ""; }
  }, 500);

  const suggest = debounce(async () => {
    const q = form.subject.value.trim();
    const box = $("#kb-suggest", view);
    if (q.length < 4) return;
    try {
      const a = await api.get("/kb/articles", { q, limit: 4, category_id: form.category_id.value || undefined });
      const list = a.length ? a : await api.get("/kb/articles", { q, limit: 4 });
      mount(box, list.length ? html`<div class="suggest">${list.map((x) => html`<a href="#/kb/${x.id}" target="_blank" rel="noopener">
        <b style="font-weight:600">${x.title}</b><div class="t-sub2">${x.category || "General"}</div></a>`)}</div>
        <p class="small muted" style="margin-top:8px">Opens in a new tab — your draft stays here.</p>` :
        html`<p class="small muted">No matching articles. Go ahead and submit.</p>`);
    } catch { /* non-critical */ }
  }, 450);
  form.subject.addEventListener("input", () => { checkDupes(); suggest(); });

  // ---- attachments (uploaded after the ticket is created)
  const drop = $("#drop", view), input = $("#file", view);
  const renderFiles = () => mount($("#file-list", view), html`${files.map((f, i) => html`<div class="attach"><span class="ic">${icon("file")}</span>
    <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">${f.name}</span><span class="muted small">${fileSize(f.size)}</span>
    <button type="button" class="btn ghost sm" data-rm="${i}" aria-label="Remove ${f.name}">${icon("x")}</button></div>`)}`);
  const addFiles = (list) => {
    for (const f of list) {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      if (!ALLOWED.split(",").includes(ext)) { toast(`${f.name}: only images and PDF files can be attached`, "err"); continue; }
      if (f.size > MAX_MB * 1048576) { toast(`${f.name}: larger than ${MAX_MB} MB`, "err"); continue; }
      if (files.length >= 5) { toast("Attach up to 5 files here; add more from the ticket page.", "info"); break; }
      files.push(f);
    }
    renderFiles();
  };
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  $("#file-list", view).addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) { files.splice(Number(b.dataset.rm), 1); renderFiles(); } });

  // ---- submit
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(form));
    const errs = {};
    if (!v.category_id) errs.category_id = "Choose a category.";
    if ((v.subject || "").trim().length < 5) errs.subject = "Subject must be at least 5 characters.";
    if ((v.description || "").trim().length < 10) errs.description = "Please describe the issue (at least 10 characters).";
    if (v.related_ticket_number && !/^IT-\d{4}-\d{6}$/.test(v.related_ticket_number.trim())) errs.related_ticket_number = "Use the format IT-2026-000123.";
    if (Object.keys(errs).length) return showFieldErrors(form, errs);
    showFieldErrors(form, {});

    const c = cat.categories.find((x) => String(x.id) === v.category_id);
    const body = {
      subject: v.subject.trim(), description: v.description.trim(), category_id: Number(v.category_id),
      subcategory_id: v.subcategory_id ? Number(v.subcategory_id) : null, ticket_type: ticketType,
      impact, urgency, contact_method: v.contact_method || "portal",
      related_ticket_number: v.related_ticket_number?.trim() || null,
    };
    if (c?.uses_erp_fields) {
      const erp = {};
      for (const k of ["erp_module", "transaction_type", "reference_no", "company_branch", "error_message", "expected_result",
        "actual_result", "steps_to_reproduce", "business_impact"]) if (v[k]?.trim()) erp[k] = v[k].trim();
      if (v.occurred_at) erp.occurred_at = new Date(v.occurred_at).toISOString();
      if (workaround) erp.workaround_available = workaround === "true";
      if (Object.keys(erp).length) body.erp = erp;
    }
    const btn = $("button[type=submit]", form);
    busy(btn);
    try {
      const t = await api.post("/tickets", body, { headers: { "Idempotency-Key": idemKey } });
      let failed = 0;
      for (const f of files) {
        const fd = new FormData(); fd.append("file", f);
        try { await api.upload(`/tickets/${t.number}/attachments`, fd); } catch { failed++; }
      }
      confirmation(view, t, failed);
    } catch (ex) {
      showFieldErrors(form, ex.fieldErrors?.() || {});
      errorToast(ex);
    } finally { busy(btn, false); }
  });
}

function confirmation(view, t, failed) {
  mount(view, html`<div class="card" style="max-width:640px;margin:20px auto">
    <div class="confirm-hero"><div class="ok-ring">${icon("check")}</div>
      <h1>Ticket submitted</h1><div class="num">${t.number}</div>
      <p class="muted">We've routed it to <b>${t.support_group?.name || "the Service Desk"}</b>${t.assignee ? html` and assigned it to <b>${t.assignee.full_name}</b>` : ""}.</p>
    </div>
    <div class="card-body" style="padding:0 28px 26px">
      <dl class="kv"><dt>Subject</dt><dd>${t.subject}</dd><dt>Priority</dt><dd>${prioBadge(t.priority)}</dd>
      <dt>Response target</dt><dd>${t.sla ? `${t.sla.response_target_minutes} business minutes` : "—"}</dd></dl>
      ${failed ? html`<div class="notice warn" style="margin-top:16px">${icon("alert")}<div>${failed} attachment(s) could not be uploaded. You can add them from the ticket page.</div></div>` : ""}
      <div class="row" style="margin-top:22px;justify-content:center">
        <a class="btn primary" href="#/tickets/${t.number}">View ticket</a><a class="btn" href="#/tickets/new" id="another">Raise another</a></div>
    </div></div>`);
  $("#another", view).addEventListener("click", (e) => { e.preventDefault(); render(view); history.replaceState(null, "", "#/tickets/new"); });

}
