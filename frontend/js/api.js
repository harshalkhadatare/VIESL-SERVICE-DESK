// API client. The access token lives only in memory; the refresh token is an HttpOnly cookie
// the browser sends to /api/v1/auth only. Every call carries X-Requested-With as an anti-CSRF signal.
const BASE = "/api/v1";
let accessToken = null;
let refreshing = null;
let onSessionLost = () => {};

export class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || `Request failed (${status})`);
    this.status = status;
    this.code = e.code || "error";
    this.details = e.details || [];
    this.requestId = e.request_id;
  }
  fieldErrors() {
    const out = {};
    for (const d of this.details) if (d.field) out[d.field.replace(/^erp\./, "erp_")] = d.message || this.message;
    return out;
  }
}

export function setSessionLostHandler(fn) { onSessionLost = fn; }
export function hasToken() { return !!accessToken; }

async function doRefresh() {
  const r = await fetch(`${BASE}/auth/refresh`, {
    method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "fetch" },
  });
  if (!r.ok) { accessToken = null; return false; }
  accessToken = (await r.json()).access_token;
  return true;
}

export function refreshSession() {
  if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null; });
  return refreshing;
}

export async function request(method, path, { body, query, headers = {}, raw = false, form } = {}, retry = true) {
  let url = BASE + path;
  if (query) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const h = { "X-Requested-With": "fetch", ...headers };
  if (accessToken) h.Authorization = `Bearer ${accessToken}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { h["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  const r = await fetch(url, { method, headers: h, body: payload, credentials: "same-origin" });
  if (r.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await refreshSession()) return request(method, path, { body, query, headers, raw, form }, false);
    onSessionLost();
  }
  if (raw) {
    if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => null));
    return r;
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}

export const api = {
  get: (p, query) => request("GET", p, { query }),
  post: (p, body, opts = {}) => request("POST", p, { body, ...opts }),
  put: (p, body) => request("PUT", p, { body }),
  patch: (p, body) => request("PATCH", p, { body }),
  upload: (p, form) => request("POST", p, { form }),
  async login(email, password) {
    const data = await request("POST", "/auth/login", { body: { email, password } }, false);
    accessToken = data.access_token;
    return data;
  },
  async logout() {
    try { await request("POST", "/auth/logout", {}, false); } finally { accessToken = null; }
  },
  async download(path, query, fallbackName) {
    const r = await request("GET", path, { query, raw: true });
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  },
};
