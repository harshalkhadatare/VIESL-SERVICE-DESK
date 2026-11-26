// Company branding comes from the server (COMPANY_NAME / COMPANY_SHORT settings), so a copy of this portal for
// another company needs no code changes — only those two environment variables.
export const brand = { name: "Vision Infra Equipment Solutions Ltd.", short: "Vision Infra · VIESL",
  help_contacts: [
    { name: "Mr. Sandeep Patil", email: "pnm_audit@visioninfraindia.com", phone: "+91 89566 67459" },
    { name: "Mr. Harshal Khadatare", email: "itsupport@visioninfraindia.com", phone: "+91 70282 17817" },
    { name: "Mr. Aniket Ghadge", email: "it@visioninfraindia.com", phone: "+91 70284 52170" },
    { name: "Mr. Vishal Borade", email: "it@visioninfraindia.com", phone: "+91 89563 73233" },
  ] };

export async function loadBrand() {
  try {
    const r = await fetch("/api/v1/brand", { headers: { "X-Requested-With": "fetch" } });
    if (r.ok) Object.assign(brand, await r.json());
  } catch { /* keep the defaults */ }
  document.title = `IT Service Desk · ${brand.name}`;
}
