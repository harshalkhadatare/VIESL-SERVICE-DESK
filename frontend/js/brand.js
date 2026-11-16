// Company branding comes from the server (COMPANY_NAME / COMPANY_SHORT settings), so a copy of this portal for
// another company needs no code changes — only those two environment variables.
export const brand = { name: "Vision Infra Equipment Solutions Ltd.", short: "Vision Infra · VIESL",
  help_contacts: [
    { name: "Mr. Sandeep Patil", email: "pnm_audit@visioninfraindia.com" },
    { name: "Mr. Harshal Khadatare", email: "itsupport@visioninfraindia.com" },
    { name: "Mr. Aniket", email: "it@visioninfraindia.com" },
    { name: "Mr. Vishal", email: "it@visioninfraindia.com" },
  ] };

export async function loadBrand() {
  try {
    const r = await fetch("/api/v1/brand", { headers: { "X-Requested-With": "fetch" } });
    if (r.ok) Object.assign(brand, await r.json());
  } catch { /* keep the defaults */ }
  document.title = `IT Service Desk · ${brand.name}`;
}
