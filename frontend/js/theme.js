// Colour theme + light/dark picker (palette button in the top bar).
import { html, mount, icon } from "./ui.js";

export const ACCENTS = [
  ["ocean", "Ocean", "#1d5fc4", "#0b2545"],
  ["teal", "Teal", "#0f8a85", "#08363a"],
  ["indigo", "Indigo", "#5a48d6", "#1e1a4d"],
  ["emerald", "Emerald", "#178a4c", "#0d3321"],
  ["crimson", "Crimson", "#c02a46", "#3b0d18"],
  ["amber", "Sunset", "#c4610f", "#3a1e08"],
  ["slate", "Graphite", "#4b5b72", "#161d29"],
];
const MODES = [["light", "Light", "sun"], ["dark", "Dark", "moon"], ["system", "Auto", "refresh"]];

const read = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };
const media = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;

export function applyTheme(accent = read("sd-accent", "ocean"), mode = read("sd-mode", "light")) {
  const d = document.documentElement;
  d.setAttribute("data-accent", ACCENTS.some((a) => a[0] === accent) ? accent : "ocean");
  d.setAttribute("data-mode", mode === "system" ? (media?.matches ? "dark" : "light") : mode);
}
media?.addEventListener?.("change", () => { if (read("sd-mode", "light") === "system") applyTheme(); });

export function setupThemeMenu(btn) {
  let pop = null;
  const close = () => { pop?.remove(); pop = null; btn.setAttribute("aria-expanded", "false"); };
  const draw = () => {
    const accent = read("sd-accent", "ocean"), mode = read("sd-mode", "light");
    mount(pop, html`<div class="theme-title">Colour theme</div>
      <div class="swatches">${ACCENTS.map(([k, name, c1, c2]) => html`<button class="swatch ${k === accent ? "on" : ""}" data-accent="${k}" title="${name}" aria-label="${name}" aria-pressed="${k === accent}">
        <span class="sw" style="--c1:${c1};--c2:${c2}">${k === accent ? icon("check") : ""}</span><span class="nm">${name}</span></button>`)}</div>
      <div class="theme-title">Appearance</div>
      <div class="seg mode-seg">${MODES.map(([k, name, ic]) => html`<button class="${k === mode ? "on" : ""}" data-mode="${k}">${icon(ic)} ${name}</button>`)}</div>`);
  };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (pop) return close();
    pop = document.createElement("div");
    pop.className = "menu theme-menu"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Theme");
    draw();
    document.body.appendChild(pop);
    btn.setAttribute("aria-expanded", "true");
    pop.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const a = ev.target.closest("[data-accent]")?.dataset.accent, m = ev.target.closest("[data-mode]")?.dataset.mode;
      if (a) save("sd-accent", a);
      if (m) save("sd-mode", m);
      if (a || m) { applyTheme(); draw(); }
    });
  });
  document.addEventListener("click", (e) => { if (pop && !pop.contains(e.target) && e.target !== btn) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}
