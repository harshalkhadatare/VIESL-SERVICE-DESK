import { api } from "../api.js";
import { $, html, mount, icon, brandMark, busy } from "../ui.js";

const COMPANY = "Vision Infra Equipment Solutions Ltd.";

export async function render(root, { onLogin }) {
  mount(root, html`<div class="login">
    <section class="login-art">
      <div class="brand" style="padding:0"><div class="brand-mark">${brandMark()}</div>
        <div><div class="brand-name">IT Service Desk</div><div class="brand-sub">Internal support portal</div></div></div>
      <div class="company-big">${COMPANY}</div>
      <p class="lead">One place for every IT request, issue and idea — raise tickets, follow progress and find answers
        without chasing emails or calls.</p>
      <div class="login-points">
        <div>${icon("zap")}<span>Tickets reach the right IT administrator automatically.</span></div>
        <div>${icon("mail")}<span>Email and in-app updates whenever your ticket moves.</span></div>
        <div>${icon("shield")}<span>Secure sign-in, private internal notes and a full audit trail.</span></div>
      </div>
      <div class="foot">Internal system · Authorised users only · Activity is logged</div>
    </section>
    <section class="login-form">
      <form id="login-form" novalidate>
        <div class="login-company">
          <div class="logo">${brandMark()}</div>
          <h1>${COMPANY}</h1>
          <span class="tag">IT Service Desk</span>
        </div>
        <h2>Sign in</h2>
        <p class="muted" style="margin-bottom:22px">Use your company email address and password.</p>
        <div id="login-error" class="notice danger" role="alert" hidden style="margin-bottom:16px">${icon("alert")}<div></div></div>
        <div class="stack" style="gap:16px">
          <label class="field"><span class="lbl">Email</span>
            <input type="email" name="email" autocomplete="username" required placeholder="name@company.com"></label>
          <label class="field"><span class="lbl">Password</span>
            <input type="password" name="password" autocomplete="current-password" required></label>
          <button class="btn primary block" type="submit" style="height:42px">Sign in</button>
        </div>
        <p class="muted small" style="margin-top:16px">Forgot your password? Contact the IT department to reset it.</p>
      </form>
    </section></div>`);

  const form = $("#login-form", root);
  const err = $("#login-error", root);
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
