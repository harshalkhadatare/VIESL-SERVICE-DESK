// Lightweight, dependency-free SVG charts (works offline on the intranet, CSP-safe).
import { html, raw, esc } from "./ui.js";

function tipHandlers(svg) {
  let tip;
  svg.addEventListener("mousemove", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) { tip?.remove(); tip = null; return; }
    if (!tip) { tip = document.createElement("div"); tip.className = "chart-tip"; document.body.appendChild(tip); }
    tip.textContent = t.dataset.tip;
    tip.style.left = `${e.clientX + 12}px`;
    tip.style.top = `${e.clientY - 34}px`;
  });
  svg.addEventListener("mouseleave", () => { tip?.remove(); tip = null; });
}

/** Two-series trend line (created vs resolved). */
export function trendChart(el, points) {
  const W = 640, H = 220, L = 34, R = 12, T = 12, B = 28;
  const max = Math.max(4, ...points.map((p) => Math.max(p.created, p.resolved)));
  const nice = Math.ceil(max / 4) * 4;
  const x = (i) => L + (i * (W - L - R)) / Math.max(1, points.length - 1);
  const y = (v) => T + (H - T - B) * (1 - v / nice);
  const path = (k) => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ");
  const area = `${path("created")} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const ticks = [0, 1, 2, 3, 4].map((i) => (nice / 4) * i);
  const step = Math.ceil(points.length / 7);
  const label = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Tickets created and resolved per day">
    <g class="grid">${ticks.map((t) => `<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("")}</g>
    <path d="${area}" fill="var(--chart-1)" opacity=".08"/>
    <path d="${path("resolved")}" fill="none" stroke="var(--chart-2)" stroke-width="2" stroke-dasharray="5 4"/>
    <path d="${path("created")}" fill="none" stroke="var(--chart-1)" stroke-width="2.2"/>
    ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.created)}" r="3" fill="var(--surface)" stroke="var(--chart-1)" stroke-width="2"/>`).join("")}
    ${points.map((p, i) => (i % step === 0 || i === points.length - 1) ? `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${label(p.date)}</text>` : "").join("")}
    ${points.map((p, i) => `<rect x="${x(i) - (W - L - R) / points.length / 2}" y="${T}" width="${(W - L - R) / points.length}" height="${H - T - B}" fill="transparent" data-tip="${esc(label(p.date))}: ${p.created} created · ${p.resolved} resolved"/>`).join("")}
  </svg>`;
  tipHandlers(el.querySelector("svg"));
}

/** Horizontal bars as HTML (crisper text, wraps nicely on mobile). */
export function hbars(items, { max = 8, href } = {}) {
  const top = items.slice(0, max);
  const m = Math.max(1, ...top.map((i) => i.value));
  if (!top.length) return html`<p class="muted small">No data for this period.</p>`;
  return html`${top.map((i) => html`<div class="hbar"><span class="lbl" title="${i.label}">${i.label}</span>
    <span class="track"><span class="fill" style="display:block;width:${((i.value / m) * 100).toFixed(1)}%"></span></span>
    <span class="n">${i.value}</span></div>`)}`;
}

/** Small donut for priority mix. */
export function donut(items, colors) {
  const total = items.reduce((a, b) => a + b.value, 0) || 1;
  let acc = 0;
  const R = 42, C = 2 * Math.PI * R;
  const segs = items.map((it, i) => {
    const len = (it.value / total) * C;
    const s = `<circle r="${R}" cx="60" cy="60" fill="none" stroke="${colors[it.label] || colors[i] || "#999"}" stroke-width="16"
      stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-acc}" transform="rotate(-90 60 60)" data-tip="${esc(it.label)}: ${it.value}"/>`;
    acc += len; return s;
  }).join("");
  return raw(`<svg viewBox="0 0 120 120" width="120" height="120" role="img" aria-label="Priority mix">
    <circle r="${R}" cx="60" cy="60" fill="none" stroke="var(--surface-2)" stroke-width="16"/>${segs}
    <text x="60" y="58" text-anchor="middle" style="font-size:20px;font-weight:600;fill:var(--text)">${total === 1 && !items.length ? 0 : items.reduce((a, b) => a + b.value, 0)}</text>
    <text x="60" y="75" text-anchor="middle" style="font-size:10px;fill:var(--muted)">tickets</text></svg>`);
}
export { tipHandlers };
