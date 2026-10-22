// UI helpers: safe HTML templating, icons, formatting, toasts, modals.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"'`]/g, (c) => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);

/** Tagged template that escapes every interpolation unless wrapped in raw() / html``. */
export function html(strings, ...vals) {
  let out = "";
  strings.forEach((s, i) => {
    out += s;
    if (i < vals.length) out += render(vals[i]);
  });
  return new Raw(out);
}
function render(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(render).join("");
  if (v === null || v === undefined || v === false) return "";
  return esc(v);
}
// Ignores missing targets: an async page load may finish after the user has navigated away.
export function mount(el, tpl) { if (el) el.innerHTML = render(tpl); return el; }
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ------------------------------------------------------------------ icons (Lucide-style paths, MIT)
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  ticket: '<path d="M3 8a2 2 0 0 0 2-2V5h14v1a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2v1H5v-1a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/><path d="M13 5v2m0 4v2m0 4v2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32 1.41-1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  star: '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" fill="currentColor"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  arrowLeft: '<path d="M19 12H5m7 7-7-7 7-7"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  filter: '<path d="M22 3H2l8 9.46V19l4 2v-8.54z"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  megaphone: '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  more: '<circle cx="12" cy="5" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1.6" fill="currentColor" stroke="none"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
};
export function icon(name, cls = "") {
  return raw(`<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ""}</svg>`);
}
export const brandMark = () => raw(`<svg width="20" height="20" viewBox="0 0 32 32" aria-hidden="true"><path d="M7 9l6.2 14h1.6L21 9" fill="none" stroke="#8EC5FF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="24.5" cy="22" r="2.4" fill="#fff"/></svg>`);

// ------------------------------------------------------------------ formatting
let TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
export function setTimezone(tz) { if (tz) TZ = tz; }
export function fmtDate(v, withTime = true) {
  if (!v) return "—";
  const d = new Date(v);
  return d.toLocaleString("en-IN", { timeZone: TZ, day: "2-digit", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) });
}
export function fmtRelative(v) {
  if (!v) return "—";
  const s = (Date.now() - new Date(v).getTime()) / 1000;
  const a = Math.abs(s);
  const f = (n, u) => `${Math.round(n)} ${u}${Math.round(n) === 1 ? "" : "s"}`;
  let txt;
  if (a < 60) txt = "just now";
  else if (a < 3600) txt = f(a / 60, "min");
  else if (a < 86400) txt = f(a / 3600, "hour");
  else if (a < 86400 * 30) txt = f(a / 86400, "day");
  else return fmtDate(v, false);
  if (txt === "just now") return txt;
  return s >= 0 ? `${txt} ago` : `in ${txt}`;
}
export function fmtMinutes(m) {
  if (m === null || m === undefined) return "—";
  const neg = m < 0; m = Math.abs(Math.round(m));
  const h = Math.floor(m / 60), mm = m % 60;
  const d = Math.floor(h / 9); // 9-hour business day
  let s = h ? (d >= 2 ? `${d}d ${h % 9}h` : `${h}h ${mm}m`) : `${mm}m`;
  return neg ? `-${s}` : s;
}
export const fmtNum = (n) => (n === null || n === undefined ? "—" : new Intl.NumberFormat("en-IN").format(n));
export const initials = (name = "") => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
export function fileSize(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

// ------------------------------------------------------------------ badges
const STATUS_TONE = {
  NEW: "info", SUBMITTED: "info", TRIAGED: "info", ASSIGNED: "info", IN_PROGRESS: "info", REOPENED: "warn",
  PENDING_EMPLOYEE: "warn", PENDING_APPROVAL: "warn", PENDING_VENDOR: "warn", PENDING_CHANGE: "warn",
  RESOLVED: "ok", CLOSED: "", CANCELLED: "",
};
export const statusBadge = (s) => html`<span class="badge ${STATUS_TONE[s.code] ?? ""}">${s.name}</span>`;
export const prioBadge = (p) => {
  const code = typeof p === "string" ? p : p.code;
  const name = typeof p === "string" ? "" : p.name;
  return html`<span class="prio ${code}" title="${name}"><i></i>${code}${name ? html` <span class="muted" style="font-weight:500">${name}</span>` : ""}</span>`;
};
const SLA_LABEL = { on_track: ["On track", "ok"], at_risk: ["At risk", "warn"], breached: ["Breached", "danger"],
  paused: ["Paused", ""], met: ["Met", "ok"] };
export const slaBadge = (state) => {
  if (!state) return html`<span class="muted">—</span>`;
  const [l, t] = SLA_LABEL[state] || [state, ""];
  return html`<span class="badge ${t}">${l}</span>`;
};

// ------------------------------------------------------------------ feedback
export function toast(message, kind = "ok", ms = 3800) {
  const root = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  mount(el, html`${icon(kind === "ok" ? "checkCircle" : kind === "err" ? "alert" : "info")}<div>${message}</div>`);
  root.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
export function errorToast(e) {
  toast(e?.message || "Something went wrong.", "err", 5200);
  if (e?.requestId) console.warn("request id", e.requestId);
}

let lastFocus = null;
export function openModal({ title, subtitle, body, actions, wide = false, onMount }) {
  const root = $("#modal-root");
  lastFocus = document.activeElement;
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  mount(wrap, html`<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="mdl-t">
    <div class="modal-head"><div><h2 id="mdl-t">${title}</h2>${subtitle ? html`<p>${subtitle}</p>` : ""}</div>
      <button class="icon-btn" data-close aria-label="Close">${icon("x")}</button></div>
    <div class="modal-body">${body}</div>
    ${actions ? html`<div class="modal-foot">${actions}</div>` : ""}</div>`);
  root.appendChild(wrap);
  const close = () => { wrap.remove(); document.removeEventListener("keydown", onKey); lastFocus?.focus?.(); };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Tab") { // simple focus trap
      const f = $$("button, [href], input, select, textarea", wrap).filter((x) => !x.disabled);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  };
  document.addEventListener("keydown", onKey);
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(); });
  $$("[data-close]", wrap).forEach((b) => b.addEventListener("click", close));
  const first = $("input, select, textarea", wrap) || $(".modal-foot .btn.primary", wrap);
  setTimeout(() => first?.focus(), 30);
  onMount?.(wrap, close);
  return { el: wrap, close };
}

export function confirmDialog({ title, message, confirmText = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const m = openModal({
      title, body: html`<p class="muted">${message}</p>`,
      actions: html`<button class="btn" data-close>Cancel</button>
        <button class="btn ${danger ? "danger solid" : "primary"}" data-ok>${confirmText}</button>`,
      onMount: (el, close) => {
        $("[data-ok]", el).addEventListener("click", () => { done = true; close(); resolve(true); });
        new MutationObserver((_, o) => { if (!el.isConnected) { o.disconnect(); if (!done) resolve(false); } })
          .observe($("#modal-root"), { childList: true });
      },
    });
    return m;
  });
}

export function busy(btn, on = true) {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span>${btn.textContent.trim()}`; }
  else { btn.disabled = false; if (btn.dataset.label) btn.innerHTML = btn.dataset.label; }
}

export function skeletonRows(n = 6, cols = 5) {
  return html`${Array.from({ length: n }, () => html`<tr>${Array.from({ length: cols }, (_, i) =>
    html`<td><div class="skeleton" style="width:${[60, 85, 50, 70, 40][i % 5]}%"></div></td>`)}</tr>`)}`;
}
export const emptyState = (title, text, ic = "inbox", action = "") =>
  html`<div class="empty">${icon(ic)}<h3>${title}</h3><p>${text}</p>${action ? html`<div style="margin-top:14px">${action}</div>` : ""}</div>`;

export function showFieldErrors(form, errors) {
  $$("[aria-invalid]", form).forEach((el) => el.removeAttribute("aria-invalid"));
  $$(".err[data-for]", form).forEach((el) => el.remove());
  for (const [field, msg] of Object.entries(errors)) {
    const el = form.querySelector(`[name="${CSS.escape(field)}"]`);
    if (!el) continue;
    el.setAttribute("aria-invalid", "true");
    const d = document.createElement("div");
    d.className = "err"; d.dataset.for = field; d.textContent = msg;
    el.closest(".field")?.appendChild(d);
  }
  const first = form.querySelector("[aria-invalid=true]");
  first?.focus();
}

export function debounce(fn, ms = 300) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
