import { api } from "../api.js";
import { $, html, mount, icon, brandMark, busy } from "../ui.js";

import { brand } from "../brand.js";

export async function render(root, { onLogin }) {
  mount(root, html`<div class="login">
    <section class="login-art">
      <div class="brand login-brand" style="padding:0"><div class="brand-mark">${brandMark()}</div>
        <div><div class="brand-name">IT Service Desk</div><div class="brand-sub">${brand.short}</div></div></div>
      <div class="login-hero-logo"><img src="/static/assets/logo-full.png" alt="Vision — #NewBharat #NewVision" width="640" height="599"></div>
      <div class="company-big">${brand.name}</div>
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
          <div class="logo-full"><img src="/static/assets/logo-full.png" alt="Vision — #NewBharat #NewVision" width="240" height="224"></div>
          <h1>${brand.name}</h1>
          <span class="tag">IT Service Desk</span>
        </div>
        <h2>Sign in</h2>
        <p class="muted" style="margin-bottom:22px">Use your Employee ID (or company email) and password.</p>
        <div id="login-error" class="notice danger" role="alert" hidden style="margin-bottom:16px">${icon("alert")}<div></div></div>
        <div class="stack" style="gap:16px">
          <label class="field"><span class="lbl">Employee ID or email</span>
            <input type="text" name="email" autocomplete="username" autocapitalize="none" spellcheck="false" required placeholder="e.g. 12520"></label>
          <label class="field"><span class="lbl">Password</span>
            <input type="password" name="password" autocomplete="current-password" required></label>
          <button class="btn primary block" type="submit" style="height:42px">Sign in</button>
        </div>
        <div class="pw-help">
          <div class="pw-help-head">${icon("key")}<span><b>Forgot your password?</b> Please contact any of the following IT administrators to have it reset:</span></div>
          <ol class="pw-list">${brand.help_contacts.map((c) => {
            const n = typeof c === "string" ? { name: c } : c;
            const ini = n.name.replace(/^(mr|mrs|ms|dr)\.?\s+/i, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
            return html`<li><span class="avatar">${ini}</span><div class="pw-who"><b>${n.name}</b>
              ${n.email ? html`<a href="mailto:${n.email}?subject=${encodeURIComponent("Password reset request — IT Service Desk")}">${icon("mail")}${n.email}</a>` : ""}
              ${n.phone ? html`<a href="tel:${n.phone.replace(/[^\d+]/g, "")}">${icon("phone")}${n.phone}</a>` : ""}</div></li>`;
          })}</ol>
        </div>
      </form>
    </section></div>`);

  const form = $("#login-form", root);
  const err = $("#login-error", root);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    const email = form.email.value.trim(), password = form.password.value;
    if (!email || !password) { err.hidden = false; err.lastElementChild.textContent = "Enter your Employee ID and password."; return; }
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
