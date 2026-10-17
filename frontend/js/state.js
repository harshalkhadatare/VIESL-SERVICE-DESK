import { api } from "./api.js";

export const state = { me: null, catalog: null, groups: null };

export const can = (perm) => !!state.me?.permissions?.includes(perm);
export const isStaff = () => can("ticket.work");
export const hasRole = (r) => !!state.me?.roles?.includes(r);

export async function loadMe() {
  state.me = await api.get("/auth/me");
  return state.me;
}

export async function catalog() {
  if (!state.catalog) state.catalog = await api.get("/meta/catalog");
  return state.catalog;
}

export async function supportGroups() {
  if (!state.groups) state.groups = await api.get("/support-groups");
  return state.groups;
}

export function roleLabel() {
  const r = state.me?.roles || [];
  if (r.includes("it_admin")) return "IT Administrator";
  if (r.includes("it_lead")) return "IT Team Lead";
  if (r.includes("it_engineer")) return "IT Support Engineer";
  if (r.includes("management")) return "Management";
  return "Employee";
}

export function resetState() { state.me = null; state.catalog = null; state.groups = null; }
