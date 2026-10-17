import { api } from "../api.js";
import { catalog } from "../state.js";
import { $, html, mount, icon, fmtDate, emptyState, debounce, errorToast } from "../ui.js";

export async function render(view, _p, query) {
  const cat = await catalog();
  let q = query.q || "", category = query.category_id || "";
  mount(view, html`
    <div class="page-head"><div><h1>Knowledge base</h1><div class="sub">Approved fixes and how-to guides from the IT team.</div></div>
      <a class="btn" href="#/tickets/new">${icon("plus")} Didn't find it? Raise a ticket</a></div>
    <div class="card" style="margin-bottom:20px"><div class="toolbar" style="border:0">
      <div class="search-inline" style="max-width:520px">${icon("search")}<input type="search" id="kq" placeholder="Describe your problem, e.g. outlook not syncing" value="${q}" aria-label="Search articles"></div>
      <select id="kc" aria-label="Category"><option value="">All categories</option>${cat.categories.map((c) => html`<option value="${c.id}" ${String(c.id) === category ? "selected" : ""}>${c.name}</option>`)}</select>
    </div></div>
    <div class="grid grid-2" id="kl"></div>`);

  async function load() {
    history.replaceState(null, "", `#/kb${q || category ? "?" + new URLSearchParams({ ...(q && { q }), ...(category && { category_id: category }) }) : ""}`);
    try {
      const list = await api.get("/kb/articles", { q, category_id: category, limit: 40 });
      mount($("#kl", view), list.length ? html`${list.map((a) => html`<a class="kb-card" href="#/kb/${a.id}">
        <h3>${a.title}</h3><div class="t-sub2">${a.category || "General"} · Updated ${fmtDate(a.updated_at, false)} · ${a.view_count} views</div>
        ${a.keywords ? html`<div style="margin-top:10px" class="row">${a.keywords.split(/\s+/).slice(0, 5).map((k) => html`<span class="pill">${k}</span>`)}</div>` : ""}</a>`)}` :
        html`<div class="card" style="grid-column:1/-1">${emptyState("No articles found", "Try other words, or raise a ticket and the IT team will help.", "book")}</div>`);
    } catch (e) { errorToast(e); }
  }
  $("#kq", view).addEventListener("input", debounce((e) => { q = e.target.value.trim(); load(); }, 300));
  $("#kc", view).addEventListener("change", (e) => { category = e.target.value; load(); });
  await load();
}

export async function renderArticle(view, [id]) {
  try {
    const a = await api.get(`/kb/articles/${id}`);
    mount(view, html`<div class="crumbs"><a href="#/kb">Knowledge base</a> / <span>${a.category || "General"}</span></div>
      <div class="grid grid-main-side">
        <article class="card kb-article"><div class="card-body" style="padding:26px 30px 30px">
          <h1>${a.title}</h1>
          <div class="meta-line"><span>${icon("user")} ${a.author}</span><span>${icon("clock")} Updated ${fmtDate(a.updated_at, false)}</span><span>Version ${a.version}</span></div>
          <h2>Problem</h2><div class="prose">${a.problem}</div>
          <h2>Solution</h2><div class="prose">${a.solution}</div>
        </div></article>
        <aside class="stack"><div class="card"><div class="card-body">
          <b>Did this solve your problem?</b><p class="muted small" style="margin:6px 0 14px">If not, raise a ticket — mention this article so the engineer knows what you tried.</p>
          <a class="btn primary block" href="#/tickets/new">Raise a ticket</a></div></div>
          ${a.keywords ? html`<div class="card"><div class="card-head"><h2>Keywords</h2></div><div class="card-body row">${a.keywords.split(/\s+/).map((k) => html`<a class="pill" href="#/kb?q=${encodeURIComponent(k)}">${k}</a>`)}</div></div>` : ""}
        </aside></div>`);
  } catch (e) {
    mount(view, html`<div class="card">${emptyState("Article not available", e.message, "book", html`<a class="btn" href="#/kb">Back to knowledge base</a>`)}</div>`);
  }
}
