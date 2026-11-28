import { api } from "./api.js";

export const state = { me: null, catalog: null, groups: null, tasks: null };

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
  const base = r.includes("it_admin") ? "IT Administrator" : "Employee";
  if (r.includes("top_management")) return r.includes("it_admin") ? "Managing Director · IT Admin" : "Managing Director";
  if (r.includes("manager_l1")) return r.includes("it_admin") ? "Manager L1 · IT Admin" : "Manager L1";
  if (r.includes("manager_l2")) return r.includes("it_admin") ? "Manager L2 · IT Admin" : "Manager L2";
  return base;
}

export function resetState() { state.me = null; state.catalog = null; state.groups = null; state.tasks = null; }
