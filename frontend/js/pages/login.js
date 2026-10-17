import { api } from "../api.js";
import { $, $$, html, mount, icon, brandMark, busy } from "../ui.js";

const DEMO = [
  ["anjali.sharma", "Employee"], ["amit.deshmukh", "ERP engineer"], ["sanjay.patil", "IT team lead"],
  ["rohan.mehta", "IT administrator"], ["kavita.rao", "Management"], ["rahul.kulkarni", "Network engineer"],
];

export async function render(root, { onLogin }) {
  let env = "production";
  try { env = (await fetch("/api/v1/health").then((r) => r.json())).env; } catch { /* keep production */ }

  mount(root, html`<div class="login">
    <section class="login-art">
      <div class="brand" style="padding:0"><div class="brand-mark">${brandMark()}</div>
        <div><div class="brand-name">IT Service Desk</div><div class="brand-sub">Vision Infra Equipment Solutions Ltd.</div></div></div>
      <h1>One place for every IT request, issue and idea.</h1>
      <p class="lead">Raise tickets, follow progress in real time and find answers in the knowledge base — without chasing emails or calls.</p>
      <div class="login-points">
        <div>${icon("zap")}<span>Smart routing sends ERP, network and hardware issues straight to the right team.</span></div>
        <div>${icon("clock")}<span>Business-hours SLA tracking with early warnings and escalation.</span></div>
        <div>${icon("shield")}<span>Role-based access, internal notes kept private, every change audited.</span></div>
      </div>
      <div class="foot">Internal system · Authorised users only · Activity is logged</div>
    </section>
    <section class="login-form">
      <form id="login-form" novalidate>
        <h2>Sign in</h2>
        <p class="muted" style="margin-bottom:24px">Use your company email address.</p>
        <div id="login-error" class="notice danger" role="alert" hidden style="margin-bottom:16px">${icon("alert")}<div></div></div>
        <div class="stack" style="gap:16px">
          <label class="field"><span class="lbl">Email</span>
            <input type="email" name="email" autocomplete="username" required placeholder="name@company.com"></label>
          <label class="field"><span class="lbl">Password</span>
            <input type="password" name="password" autocomplete="current-password" required></label>
          <button class="btn primary block" type="submit" style="height:42px">Sign in</button>
        </div>
        <p class="muted small" style="margin-top:16px">Forgot your password? Ask a colleague to raise a
          <b>Password Reset</b> ticket for you, or contact the IT Service Desk.</p>
        ${env !== "production" ? html`<div class="demo-box"><b>Demo accounts</b> <span class="pill demo">${env}</span>
          <div class="muted" style="margin-top:4px">Fictional users. Password: <code>Vision@Demo2026</code> (set via DEMO_PASSWORD).</div>
          <div class="accts">${DEMO.map(([u, r]) => html`<button type="button" data-u="${u}@demo.example.com">${u.replace(".", " ").replace(/\b\w/g, (c) => c.toUpperCase())}<span>${r}</span></button>`)}</div></div>` : ""}
      </form>
    </section></div>`);

  const form = $("#login-form", root);
  const err = $("#login-error", root);
  $$(".demo-box button", root).forEach((b) => b.addEventListener("click", () => {
    form.email.value = b.dataset.u; form.password.value = "Vision@Demo2026"; form.requestSubmit();
  }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    const email = form.email.value.trim(), password = form.password.value;
    if (!email || !password) { err.hidden = false; err.lastElementChild.textContent = "Enter your email and password."; return; }
    const btn = $("button[type=submit]", form);
    busy(btn);
    try {
      await api.login(email, password);
      form.password.value = "";
      await onLogin();
    } catch (ex) {
      err.hidden = false;
      err.lastElementChild.textContent = ex.message;
      form.password.select();
    } finally { busy(btn, false); }
  });
  setTimeout(() => form.email.focus(), 50);
}
