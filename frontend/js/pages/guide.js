// "How to use the IT Service Desk" — built-in guide, pinned at the top of the Knowledge base.
import { isStaff } from "../state.js";
import { html, mount, icon, statusBadge } from "../ui.js";

const S = (code, name) => statusBadge({ code, name });

const steps = (list) => html`<ol class="g-steps">${list.map((s) => html`<li>${s}</li>`)}</ol>`;

function sections(staff) {
  const all = [
    { id: "signin", icon: "key", title: "Sign in", body: html`
      ${steps([
        html`Open the portal and enter your <b>Employee ID</b> (for example <span class="emp-id">12520</span>) or your company email.`,
        html`Enter your password and click <b>Sign in</b>.`,
        html`To change your password: click your name at the top right → <b>Change password</b>.`])}
      <p class="g-tip">${icon("info")} Forgot your password? Call or message the IT department — they can reset it for you.</p>` },

    { id: "raise", icon: "plus", title: "Raise a ticket", body: html`
      ${steps([
        html`Click <b>Raise a ticket</b> in the left menu — or use a <b>Quick help</b> tile on the Home page (Forgot password, Printer, ERP…) to get a form that's already filled in.`,
        html`Choose the <b>IT department</b>: <b>IT</b> (computers, printers, network, email, accounts), <b>ERP-IT</b> (ERP software, data, reports) or <b>Both / not sure</b>.`,
        html`Then choose the <b>category</b> — the list only shows what that department handles. Subcategory is optional.`,
        html`Write a short <b>Subject</b> and a clear <b>Description</b>: what happened, since when, and any error text.`,
        html`Add <b>screenshots or a PDF</b> right below the description (images and PDF only).`,
        html`Pick how many people are affected and how urgent it is — the priority is set automatically.`,
        html`Click <b>Submit ticket</b>. You get a ticket number: <span class="mono">IT-26-000123</span> for IT, <span class="mono">ERP-26-000123</span> for ERP-IT, <span class="mono">ITERP-26-000123</span> for both.`])}
      <p class="g-tip">${icon("zap")} Before submitting, look at the suggested articles on the right — many common problems have a ready fix.</p>` },

    { id: "track", icon: "ticket", title: "Track your ticket", body: html`
      <p>Open <b>My tickets</b> to see everything you raised. Click a ticket to see its details and messages.
        The <b>progress bar</b> at the top shows how far it has got: Submitted → Assigned → In progress → Resolved → Closed.
        Click the <b>★</b> next to any ticket to star it — starred tickets are collected in the <b>★ Starred</b> tab.
        The coloured label shows the exact status:</p>
      <dl class="g-status">
        <dt>${S("SUBMITTED", "Submitted")}</dt><dd>Received. The IT team will pick it up shortly.</dd>
        <dt>${S("ASSIGNED", "Assigned")}</dt><dd>An IT administrator has been assigned — their name is shown on the ticket.</dd>
        <dt>${S("IN_PROGRESS", "In Progress")}</dt><dd>Someone is working on it.</dd>
        <dt>${S("PENDING_EMPLOYEE", "Pending Employee")}</dt><dd><b>IT is waiting for you.</b> Read their message and reply.</dd>
        <dt>${S("RESOLVED", "Resolved")}</dt><dd>IT thinks it's fixed. Please confirm or tell them it's still not working.</dd>
        <dt>${S("CLOSED", "Closed")}</dt><dd>Finished. Raise a new ticket if the problem comes back later.</dd>
      </dl>` },

    { id: "messages", icon: "send", title: "Talk to the IT team", body: html`
      ${steps([
        html`Open the ticket and go to the <b>Messages</b> tab.`,
        html`Your messages appear on the right, IT's replies on the left.`,
        html`Type in the box at the bottom and click <b>Send</b> (or press <span class="kbd">Ctrl</span> + <span class="kbd">Enter</span>).`,
        html`Need to send another screenshot? Use <b>Add an image or PDF</b> in the Attachments box.`])}
      <p class="g-tip">${icon("clock")} When a ticket is <i>Pending Employee</i>, replying automatically puts it back to work.</p>` },

    { id: "finish", icon: "checkCircle", title: "When it's fixed", body: html`
      ${steps([
        html`When IT marks the ticket <b>Resolved</b>, you'll get a notification.`,
        html`Click <b>Confirm it's fixed</b> to close it — or <b>Still not working</b> to send it back (within 7 days).`,
        html`Give a quick star rating — it helps the team improve.`])}` },

    { id: "delete", icon: "x", title: "Cancel a ticket", body: html`
      <p>No longer need help? Open the ticket and click <b>Cancel ticket</b>, with a short reason. You can cancel at any stage
        until it is resolved. A cancelled ticket stays in <b>My tickets → All my tickets</b> (and the <b>Cancelled</b> tab) for your records.
        Tickets can only be deleted by the IT team.</p>` },

    { id: "notify", icon: "bell", title: "Notifications", body: html`
      <p>The bell at the top shows updates on your tickets: who it is assigned to, new replies, and status changes.
        If your email is registered, you also get the same update by email. Click a notification to open the ticket.</p>` },

    { id: "ann", icon: "megaphone", title: "Announcements", body: html`
      <p>When IT has planned maintenance or an outage, a coloured banner appears at the top of every page.
        Click ✕ to hide it. Red outage banners stay until the problem is fixed.</p>` },

    { id: "kb", icon: "book", title: "Find answers yourself", body: html`
      <p>Use the <b>Knowledge base</b> (or the search box at the top — press <span class="kbd">/</span>) to find step-by-step fixes
        for common problems like Outlook, VPN, printers and ERP errors.</p>` },

    { id: "theme", icon: "palette", title: "Change colours and dark mode", body: html`
      <p>Click the ${icon("palette")} <b>palette button</b> next to your name at the top right and pick a colour theme or <b>Dark</b>.
        Your choice is remembered on this device.</p>` },

    { id: "tips", icon: "star", title: "Tips for faster help", body: html`
      <ul class="g-list">
        <li>One problem per ticket.</li>
        <li>Copy the exact error message, or attach a screenshot of it.</li>
        <li>For ERP issues, add the document number (PO, invoice, GRN…).</li>
        <li>Choose <i>High</i> urgency only when work is really blocked — it helps the team handle true emergencies first.</li>
      </ul>` },
  ];
  const admin = [
    { id: "it-queue", icon: "inbox", title: "IT: work the queue", body: html`
      ${steps([
        html`Open <b>Tickets</b>. Use the tabs: <i>All open</i>, <i>Assigned to me</i>, <i>Unassigned</i>.`,
        html`The <b>Dashboard</b> shows live numbers (open, unassigned, overdue…) — click any number to see those tickets.`,
        html`Use the <b>IT tickets · ERP-IT tickets · All tickets</b> buttons above the list. You start on your own department; tickets marked “Both” appear in both. The <b>Dashboard</b> has the same IT / ERP-IT split.`,
        html`<b>Export to Excel</b> downloads exactly what the list shows (all pages) as a formatted spreadsheet with filters.`,
        html`<b>Light-green rows marked NEW</b> are tickets raised in the last 3 days that you haven't opened yet.`,
        html`<b>Find an employee's tickets:</b> type their Employee ID, name or email in the search box (or the <i>Employee ID</i> box), or click the requester's name in the list. In <i>Users & roles</i>, the <b>Tickets</b> button does the same.`,
        html`Click <b>⋮</b> on any row to assign it to an IT administrator (or unassign it).`,
        html`Open a ticket and click <b>Accept & start</b> to take it, then <b>Update status</b> as you work.`,
        html`Use <b>Internal note</b> for notes the employee must not see. Use <b>Reply to requester</b> to talk to them — the <b>Quick reply</b> buttons fill in common answers for you.`,
        html`Set <b>Resolved</b> with a short resolution note when done — the employee confirms, or it closes automatically after 5 days.`])}` },
    { id: "it-users", icon: "users", title: "IT: manage users", body: html`
      ${steps([
        html`<b>Users & roles</b> → <b>Add user</b> for one person, or <b>Import from Excel</b> for many (download the template there).`,
        html`Use <b>Password</b> to reset someone's password, <b>Roles</b> to make them IT Administrator, <b>Deactivate</b> when they leave.`,
        html`<b>Delete</b> (bin icon) removes an account permanently with the tickets they raised — use it for test or wrong accounts only.`,
        html`<b>Announcements</b> posts a banner for everyone (maintenance, outages). <b>Email notifications</b> shows whether email is set up.`])}` },
  ];
  return staff ? [...all, ...admin] : all;
}

export function render(view) {
  const list = sections(isStaff());
  mount(view, html`
    <div class="crumbs"><a href="#/kb">Knowledge base</a> / <span>How to use</span></div>
    <div class="g-hero">
      <span class="g-hero-ic">${icon("book")}</span>
      <div><h1>How to use the IT Service Desk</h1>
        <p>Everything you need in 5 minutes — raising tickets, talking to IT and tracking progress.</p></div>
      <a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a>
    </div>
    <div class="g-layout">
      <nav class="g-toc card" aria-label="Guide contents"><div class="g-toc-title">On this page</div>
        ${list.map((s, i) => html`<a href="#/kb/guide" data-jump="${s.id}"><span class="n">${i + 1}</span>${s.title}</a>`)}</nav>
      <div class="stack">
        ${list.map((s, i) => html`<section class="card g-sec" id="g-${s.id}">
          <div class="g-sec-head"><span class="g-ic">${icon(s.icon)}</span><h2><span class="muted">${i + 1}.</span> ${s.title}</h2></div>
          <div class="g-sec-body">${s.body}</div></section>`)}
        <div class="card"><div class="card-body row" style="justify-content:space-between">
          <span><b>Still stuck?</b> <span class="muted">Raise a ticket and the IT team will help.</span></span>
          <a class="btn primary" href="#/tickets/new">${icon("plus")} Raise a ticket</a></div></div>
      </div>
    </div>`);
  view.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById(`g-${a.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}
