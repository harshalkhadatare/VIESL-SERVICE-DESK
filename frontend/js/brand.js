// Company branding comes from the server (COMPANY_NAME / COMPANY_SHORT settings), so a copy of this portal for
// another company needs no code changes — only those two environment variables.
export const brand = { name: "Vision Infra Equipment Solutions Ltd.", short: "VIESL" };

export async function loadBrand() {
  try {
    const r = await fetch("/api/v1/brand", { headers: { "X-Requested-With": "fetch" } });
    if (r.ok) Object.assign(brand, await r.json());
  } catch { /* keep the defaults */ }
  document.title = `IT Service Desk · ${brand.name}`;
}
