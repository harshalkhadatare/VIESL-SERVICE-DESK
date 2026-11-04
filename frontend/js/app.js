import { api, refreshSession, setSessionLostHandler } from "./api.js";
import { state, loadMe, can, isStaff, roleLabel, resetState, catalog } from "./state.js";
import { $, $$, html, mount, icon, brandMark, initials, toast, errorToast, openModal, busy, debounce, esc, realEmail,
  setTimezone, showFieldErrors } from "./ui.js";
import * as loginPage from "./pages/login.js";
import * as dashboardPage from "./pages/dashboard.js";
import * as ticketsPage from "./pages/tickets.js";
import * as newTicketPage from "./pages/new-ticket.js";
import * as detailPage from "./pages/ticket-detail.js";
import * as kbPage from "./pages/kb.js";
import * as guidePage from "./pages/guide.js";
import * as notificationsPage from "./pages/notifications.js";
import * as adminPage from "./pages/admin.js";
import * as annPage from "./pages/announcements.js";
import { setupThemeMenu } from "./theme.js";

export const COMPANY = "Vision Infra Equipment Solutions Ltd.";

const ROUTES = [
  [/^\/?$/, dashboardPage.render, "dashboard"],
  [/^\/tickets\/new$/, newTicketPage.render, "new"],
  [/^\/tickets\/(IT-\d{4}-\d{6})$/, detailPage.render, "tickets"],
  [/^\/tickets$/, ticketsPage.render, "tickets"],
  [/^\/kb\/guide$/, guidePage.render, "guide"],
  [/^\/kb\/(\d+)$/, kbPage.renderArticle, "kb"],
  [/^\/kb$/, kbPage.render, "kb"],
  [/^\/notifications$/, notificationsPage.render, "notifications"],
  [/^\/admin\/users$/, adminPage.renderUsers, "users", "user.manage"],
  [/^\/admin\/audit$/, adminPage.renderAudit, "audit", "audit.view"],
  [/^\/admin\/email$/, adminPage.renderEmail, "email", "settings.manage"],
  [/^\/admin\/announcements$/, annPage.renderAdmin, "announcements", "ticket.manage_all"],
];

let cleanup = null;
let pollTimer = null;
let annTimer = null;

function parseHash() {
  const h = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = h.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(qs || "")) };
}
export function navigate(path) { location.hash = path; }

// ------------------------------------------------------------------ shell
function navLink(href, key, ic, label, extra = "") {
  return html`<a href="#${href}" data-nav="${key}">${icon(ic)}<span>${label}</span>${extra}</a>`;
}

function renderShell() {
  const me = state.me;
  const app = $("#app");
  mount(app, html`
  <div class="shell" id="shell">
    <aside class="sidebar" aria-label="Main navigation">
      <div class="brand"><div class="brand-mark">${brandMark()}</div>
        <div><div class="brand-name">IT Service Desk</div><div class="brand-sub">Vision Infra · VIESL</div></div></div>
      <nav class="nav">
        <div class="nav-section">Workspace</div>
        ${navLink("/", "dashboard", "home", isStaff() || can("dashboard.ops") ? "Dashboard" : "Home")}
        ${navLink("/tickets", "tickets", "ticket", isStaff() || can("ticket.view_all") ? "Tickets" : "My tickets")}
        ${navLink("/tickets/new", "new", "plus", "Raise a ticket")}
        ${navLink("/notifications", "notifications", "bell", "Notifications", html`<span class="count" id="nav-unread" hidden></span>`)}
        <div class="nav-section">Self-service</div>
        ${navLink("/kb", "kb", "book", "Knowledge base")}
        ${navLink("/kb/guide", "guide", "info", "How to use")}
        ${can("user.manage") || can("audit.view") || can("ticket.manage_all") ? html`<div class="nav-section">Administration</div>` : ""}
        ${can("user.manage") ? navLink("/admin/users", "users", "users", "Users & roles") : ""}
        ${can("ticket.manage_all") ? navLink("/admin/announcements", "announcements", "megaphone", "Announcements") : ""}
        ${can("settings.manage") ? navLink("/admin/email", "email", "mail", "Email notifications") : ""}
        ${can("audit.view") ? navLink("/admin/audit", "audit", "shield", "Audit log") : ""}
        <button type="button" class="side-theme" id="side-theme">${icon("palette")}<span>Colours & dark mode</span></button>
      </nav>
      <div class="sidebar-foot">Need urgent help? Call the IT Service Desk<br>for P1 outages after raising a ticket.</div>
    </aside>
    <div class="main">
      <header class="topbar">
        <button class="icon-btn menu-btn" id="menu-btn" aria-label="Open navigation">${icon("menu")}</button>
        <div class="company-title" title="${COMPANY}">${COMPANY}</div>
        <div class="search" role="search">
          ${icon("search")}
          <input type="search" id="global-search" placeholder="${isStaff() ? "Search tickets, employee ID or name…  ( / )" : "Search tickets and articles…  ( / )"}" autocomplete="off"
            aria-label="Search tickets and knowledge articles">
          <div class="search-results" id="search-results" hidden></div>
        </div>
        <div class="topbar-right">
          <button class="icon-btn search-btn" id="search-btn" aria-label="Search" title="Search">${icon("search")}</button>
          <a class="icon-btn" href="#/notifications" aria-label="Notifications" title="Notifications">${icon("bell")}
            <span class="dot-count" id="bell-count" hidden></span></a>
          <button class="icon-btn theme-btn" id="theme-btn" aria-label="Colour theme and dark mode" title="Colour theme & dark mode" aria-haspopup="dialog" aria-expanded="false">${icon("palette")}</button>
          <button class="user-chip" id="user-btn" aria-haspopup="menu" aria-expanded="false">
            <span class="avatar">${initials(me.full_name)}</span>
            <span class="who"><b>${me.full_name}</b><span>${roleLabel()}${me.employee_code ? ` · ${me.employee_code}` : ""}</span></span>
          </button>
        </div>
      </header>
      <div id="ann-bar" class="ann-bar" aria-live="polite"></div>
      <main class="content" id="view" tabindex="-1"></main>
      <nav class="bottom-nav" aria-label="Quick navigation">
        <a href="#/" data-nav="dashboard">${icon("home")}<span>Home</span></a>
        <a href="#/tickets" data-nav="tickets">${icon("ticket")}<span>Tickets</span></a>
        <a href="#/tickets/new" data-nav="new" class="bn-raise">${icon("plus")}<span>Raise</span></a>
        <a href="#/notifications" data-nav="notifications">${icon("bell")}<span>Alerts</span><span class="bn-count" id="bn-unread" hidden></span></a>
        <button type="button" id="bn-more">${icon("menu")}<span>Menu</span></button>
      </nav>
      <div class="nav-scrim" id="nav-scrim"></div>
    </div>
  </div>`);

  $("#menu-btn").addEventListener("click", () => $("#shell").classList.toggle("nav-open"));
  $("#bn-more").addEventListener("click", () => $("#shell").classList.toggle("nav-open"));
  $("#nav-scrim").addEventListener("click", () => $("#shell").classList.remove("nav-open"));
  $("#side-theme").addEventListener("click", (e) => { e.stopPropagation(); $("#shell").classList.remove("nav-open"); setTimeout(() => $("#theme-btn").click(), 50); });
  $("#search-btn").addEventListener("click", () => {
    const open = $("#shell").classList.toggle("search-open");
    if (open) setTimeout(() => $("#global-search")?.focus(), 30);
  });
  $(".sidebar").addEventListener("click", (e) => { if (e.target.closest("a")) $("#shell").classList.remove("nav-open"); });
  setupUserMenu();
  setupThemeMenu($("#theme-btn"));
  annPage.loadBanner();
  clearInterval(annTimer);
  annTimer = setInterval(() => { if (!document.hidden && $("#ann-bar")) annPage.loadBanner(); }, 300000);
  setupSearch();
  pollUnread();
}

function setupUserMenu() {
  const btn = $("#user-btn");
  let menu = null;
  const close = () => { menu?.remove(); menu = null; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (menu) return close();
    menu = document.createElement("div");
    menu.className = "menu"; menu.setAttribute("role", "menu");
    const me = state.me;
    mount(menu, html`<div class="meta"><b style="color:var(--text)">${me.full_name}</b><br>${realEmail(me.email) || `Employee ID ${me.employee_code}`}<br>
        ${me.department || ""}${me.location ? html` · ${me.location}` : ""}</div><hr>
      <button role="menuitem" data-act="pw">${icon("key")} Change password</button>
      <button role="menuitem" data-act="out">${icon("logout")} Sign out</button>`);
    document.body.appendChild(menu);
    btn.setAttribute("aria-expanded", "true");
    menu.addEventListener("click", async (ev) => {
      const act = ev.target.closest("[data-act]")?.dataset.act;
      close();
      if (act === "out") await signOut();
      if (act === "pw") changePassword();
    });
  });
  document.addEventListener("click", (e) => { if (menu && !menu.contains(e.target)) close(); });
}

function changePassword() {
  openModal({
    title: "Change password", subtitle: "Choose any password you like.",
    body: html`<form id="pw-form" class="stack" style="gap:14px" novalidate>
      <label class="field"><span class="lbl">Current password</span><input type="password" name="current_password" autocomplete="current-password" required></label>
      <label class="field"><span class="lbl">New password</span><input type="password" name="new_password" autocomplete="new-password" required></label>
      <label class="field"><span class="lbl">Confirm new password</span><input type="password" name="confirm" autocomplete="new-password" required></label></form>`,
    actions: html`<button class="btn" data-close>Cancel</button><button class="btn primary" id="pw-save">Update password</button>`,
    onMount: (el, close) => {
      $("#pw-save", el).addEventListener("click", async (e) => {
        const f = $("#pw-form", el);
        const d = Object.fromEntries(new FormData(f));
        if (d.new_password !== d.confirm) return showFieldErrors(f, { confirm: "Passwords do not match." });
        busy(e.currentTarget);
        try {
          await api.post("/auth/change-password", { current_password: d.current_password, new_password: d.new_password });
          close(); toast("Password updated. Please sign in again on other devices.");
        } catch (err) { showFieldErrors(f, err.fieldErrors?.() || {}); errorToast(err); } finally { busy(e.currentTarget, false); }
      });
    },
  });
}

function setupSearch() {
  const input = $("#global-search"), box = $("#search-results");
  const hide = () => { box.hidden = true; };
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) return hide();
    try {
      const r = await api.get("/dashboard/search", { q });
      const none = !r.tickets.length && !r.articles.length && !(r.people || []).length;
      mount(box, none ? html`<div class="muted small" style="padding:12px">No matches for “${q}”.</div>` : html`
        ${(r.people || []).length ? html`<div class="group-label">Employees — all their tickets</div>${r.people.map((m) => html`
          <a href="#/tickets?scope=all&requester=${encodeURIComponent(m.employee_code)}">${icon("user")}<span style="flex:1;min-width:0">${m.name} <span class="emp-id">${m.employee_code}</span></span><span class="muted small">${m.tickets} ticket${m.tickets === 1 ? "" : "s"}</span></a>`)}` : ""}
        ${r.tickets.length ? html`<div class="group-label">Tickets</div>${r.tickets.map((t) => html`
          <a href="#/tickets/${t.number}"><span class="t-id">${t.number}</span><span style="flex:1;min-width:0" class="t-subject">${t.subject}${t.requester ? html`<span class="t-sub2">${t.requester}${t.requester_code ? ` (${t.requester_code})` : ""}</span>` : ""}</span><span class="muted small">${t.status}</span></a>`)}` : ""}
        ${r.articles.length ? html`<div class="group-label">Knowledge base</div>${r.articles.map((a) => html`
          <a href="#/kb/${a.id}">${icon("book")}<span>${a.title}</span></a>`)}` : ""}`);
      box.hidden = false;
    } catch { hide(); }
  }, 250);
  input.addEventListener("input", run);
  input.addEventListener("focus", () => { if (box.innerHTML && input.value.trim().length > 1) box.hidden = false; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { hide(); input.blur(); }
    if (e.key === "Enter") { const a = $("a", box); if (a) { location.hash = a.getAttribute("href"); hide(); input.blur(); } }
  });
  box.addEventListener("click", (e) => { if (e.target.closest("a")) { hide(); input.value = ""; } });
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) hide(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
  });
}

export async function refreshUnread() {
  try {
    const { count } = await api.get("/notifications/unread-count");
    for (const id of ["bell-count", "nav-unread", "bn-unread"]) {
      const el = document.getElementById(id);
      if (!el) continue;
      el.hidden = !count; el.textContent = count > 99 ? "99+" : count;
    }
  } catch { /* ignore polling errors */ }
}
function pollUnread() {
  clearInterval(pollTimer);
  refreshUnread();
  pollTimer = setInterval(() => { if (!document.hidden) refreshUnread(); }, 60000);
}

async function signOut() {
  try { await api.logout(); } catch { /* ignore */ }
  clearInterval(pollTimer);
  resetState();
  navigate("/login");
  route();
}

// ------------------------------------------------------------------ router
async function route() {
  const { path, query } = parseHash();
  if (typeof cleanup === "function") { try { cleanup(); } catch { /* ignore */ } }
  cleanup = null;

  if (path === "/login") {
    if (state.me) return navigate("/");
    return loginPage.render($("#app"), { onLogin: boot });
  }
  if (!state.me) return navigate("/login");
  if (!$("#view")) renderShell();

  // Each navigation renders into a fresh container, so a slow page that finishes loading after the
  // user has moved on writes into a detached element instead of over the current page.
  const host = $("#view");
  const view = document.createElement("div");
  view.className = "page";
  host.replaceChildren(view);
  for (const [re, fn, key, perm] of ROUTES) {
    const m = path.match(re);
    if (!m) continue;
    $$(".nav a, .bottom-nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === key));
    $("#shell")?.classList.remove("nav-open", "search-open");
    if (perm && !can(perm)) {
      mount(view, html`<div class="card"><div class="empty">${icon("lock")}<h3>Not available</h3><p>You do not have access to this page.</p></div></div>`);
      return;
    }
    window.scrollTo(0, 0);
    try {
      const c = await fn(view, m.slice(1), query);
      if (view.isConnected) cleanup = c; else if (typeof c === "function") c();  // navigated away meanwhile
    } catch (e) { if (view.isConnected) errorToast(e); }
    if (view.isConnected) host.focus({ preventScroll: true });
    return;
  }
  mount(view, html`<div class="card"><div class="empty">${icon("alert")}<h3>Page not found</h3>
    <p><a href="#/">Back to dashboard</a></p></div></div>`);
}

async function boot() {
  try {
    // load the profile and the (rarely changing) catalog together: saves one round trip on most pages
    await Promise.all([loadMe(), catalog().catch(() => null)]);
    setTimezone(state.me.timezone);
    $("#app").innerHTML = "";
    if (parseHash().path === "/login") navigate("/"); // hashchange triggers route()
    else route();
  } catch (e) { errorToast(e); }
}

setSessionLostHandler(() => {
  if (!state.me) return;
  resetState();
  toast("Your session has ended. Please sign in again.", "info");
  navigate("/login");
});

window.addEventListener("hashchange", route);
(async function start() {
  const ok = await refreshSession().catch(() => false);
  if (ok) await boot();
  else if (parseHash().path !== "/login") navigate("/login"); // hashchange triggers route()
  else route();
})();

export { esc };
