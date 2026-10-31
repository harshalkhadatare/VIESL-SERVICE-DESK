// Announcements: a banner at the top of every page for everyone, and an admin page to post them.
import { api } from "../api.js";
import { $, $$, html, mount, icon, fmtDate, fmtRelative, emptyState, errorToast, toast, busy, confirmDialog } from "../ui.js";

const SEV = {
  info: ["Information", "megaphone", ""],
  warning: ["Warning", "alert", "warn"],
  outage: ["Outage", "zap", "danger"],
};
const KEY = "sd-dismissed-ann";
const dismissed = () => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } };
const dismiss = (id) => { try { localStorage.setItem(KEY, JSON.stringify([...dismissed(), id].slice(-50))); } catch { /* ignore */ } };

/** Shows active announcements above the page. Outages can't be dismissed. */
export async function loadBanner() {
  const bar = $("#ann-bar");
  if (!bar) return;
  let list = [];
  try { list = await api.get("/announcements"); } catch { return; }
  const hidden = dismissed();
  const rank = { outage: 0, warning: 1, info: 2 };
  const show = list.filter((a) => a.severity === "outage" || !hidden.includes(a.id))
    .sort((x, y) => rank[x.severity] - rank[y.severity]).slice(0, 2);   // keep the page uncluttered
  mount(bar, html`${show.map((a) => html`<div class="ann ${SEV[a.severity]?.[2] || ""}" data-id="${a.id}">
    <span class="ann-ic">${icon(SEV[a.severity]?.[1] || "megaphone")}</span>
    <div class="ann-txt"><b>${a.title}</b> <span>${a.body}</span></div>
    ${a.severity !== "outage" ? html`<button class="ann-x" data-x="${a.id}" aria-label="Dismiss">${icon("x")}</button>` : ""}</div>`)}`);
  $$("[data-x]", bar).forEach((b) => b.addEventListener("click", () => {
    dismiss(Number(b.dataset.x)); b.closest(".ann").remove();
  }));
}

export async function renderAdmin(view) {
  mount(view, html`
    <div class="page-head"><div><h1>Announcements</h1>
      <div class="sub">Post a message everyone sees at the top of the portal — planned maintenance, outages, new services.</div></div></div>
    <div class="grid grid-main-side">
      <div class="card"><div class="card-head"><h2>Posted announcements</h2></div><ul class="ann-admin" id="al"></ul></div>
      <form class="card" id="af" novalidate>
        <div class="card-head"><h2>New announcement</h2></div>
        <div class="card-body stack" style="gap:14px">
          <div class="field"><span class="lbl">Type</span>
            <div class="choice-grid" id="sev">${Object.entries(SEV).map(([k, [name, ic, tone]], i) => html`
              <div class="choice ${i === 0 ? "on" : ""} sev-${k}" data-v="${k}" role="radio" tabindex="0">${icon(ic)}<b>${name}</b></div>`)}</div></div>
          <label class="field"><span class="lbl">Title<span class="req">*</span></span>
            <input type="text" name="title" maxlength="200" required placeholder="e.g. Email maintenance tonight"></label>
          <label class="field"><span class="lbl">Message<span class="req">*</span></span>
            <textarea name="body" rows="3" maxlength="2000" required placeholder="e.g. Outlook will be unavailable from 9 to 10 pm. No action needed."></textarea></label>
          <label class="field"><span class="lbl">Show for</span><select name="hours">
            <option value="4">4 hours</option><option value="24" selected>1 day</option><option value="72">3 days</option>
            <option value="168">1 week</option><option value="">Until I remove it</option></select></label>
          <div class="ann-preview" id="ap"></div>
          <button class="btn primary" type="submit">${icon("megaphone")} Post announcement</button>
        </div></form>
    </div>`);

  let sev = "info";
  const f = $("#af", view);
  const preview = () => mount($("#ap", view), html`<span class="small muted">Preview</span>
    <div class="ann ${SEV[sev][2]}"><span class="ann-ic">${icon(SEV[sev][1])}</span>
    <div class="ann-txt"><b>${f.title.value || "Title"}</b> <span>${f.body.value || "Your message"}</span></div></div>`);
  $("#sev", view).addEventListener("click", (e) => {
    const c = e.target.closest(".choice"); if (!c) return;
    sev = c.dataset.v; $$("#sev .choice", view).forEach((x) => x.classList.toggle("on", x === c)); preview();
  });
  f.title.addEventListener("input", preview); f.body.addEventListener("input", preview);
  preview();

  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (f.title.value.trim().length < 3 || f.body.value.trim().length < 3) return toast("Add a title and a message.", "err");
    const btn = $("button[type=submit]", f); busy(btn);
    try {
      await api.post("/admin/announcements", { title: f.title.value.trim(), body: f.body.value.trim(), severity: sev,
        hours: f.hours.value ? Number(f.hours.value) : null });
      f.reset(); preview(); toast("Announcement posted — everyone sees it now."); load(); loadBanner();
    } catch (ex) { errorToast(ex); } finally { busy(btn, false); }
  });

  async function load() {
    let list;
    try { list = await api.get("/admin/announcements"); } catch (e) { return errorToast(e); }
    if (!$("#al", view)?.isConnected) return;
    mount($("#al", view), list.length ? html`${list.map((a) => html`<li class="${a.active ? "" : "ended"}">
      <span class="ann-ic ${SEV[a.severity][2]}">${icon(SEV[a.severity][1])}</span>
      <div class="grow"><b>${a.title}</b>${a.active ? html` <span class="badge ok">Live</span>` : html` <span class="badge">Ended</span>`}
        <div class="t-sub2" style="white-space:normal">${a.body}</div>
        <div class="t-sub2">Posted ${fmtRelative(a.starts_at)}${a.created_by ? ` by ${a.created_by}` : ""} ·
          ${a.ends_at ? (a.active ? `ends ${fmtDate(a.ends_at)}` : `ended ${fmtDate(a.ends_at)}`) : "no end date"}</div></div>
      <div class="row" style="flex-wrap:nowrap">${a.active ? html`<button class="btn sm" data-end="${a.id}">End now</button>` : ""}
        <button class="btn sm ghost icon-only del-user" data-del="${a.id}" title="Delete">${icon("trash")}</button></div></li>`)}` :
      html`<li>${emptyState("No announcements yet", "Post one to let everyone know about maintenance or outages.", "megaphone")}</li>`);
    $$("[data-end]", view).forEach((b) => b.addEventListener("click", async () => {
      try { await api.post(`/admin/announcements/${b.dataset.end}/end`); toast("Announcement ended."); load(); loadBanner(); } catch (e) { errorToast(e); }
    }));
    $$("[data-del]", view).forEach((b) => b.addEventListener("click", async () => {
      if (!await confirmDialog({ title: "Delete this announcement?", message: "It will be removed from the list.", confirmText: "Delete", danger: true })) return;
      try { await api.del(`/admin/announcements/${b.dataset.del}`); load(); loadBanner(); } catch (e) { errorToast(e); }
    }));
  }
  await load();
}
