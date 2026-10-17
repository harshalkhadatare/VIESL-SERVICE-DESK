# Known limitations & roadmap

## Known limitations (this release)
- **Not run against a live SQL Server here.** The schema compiles to SQL Server DDL (`docs/sqlserver_schema.sql`) and the Docker stack is provided, but all automated tests ran on SQLite. Run the suite against SQL Server before go-live.
- **Email delivery** is implemented (outbox, retries, SMTP provider) but **not verified** against a real relay; it is disabled by default.
- **Approval workflows** are not built yet: categories flagged `requires_approval` show a notice and staff can use the *Pending Approval* status manually; no approver routing or decisions are recorded.
- **Knowledge base:** search, reading and suggestions work; authoring, review/publish workflow and "convert ticket to article" are not in the UI yet (tables exist).
- **Suggestions portal, IT assets & CMDB** are not built.
- **Admin configuration UIs** for categories, SLA policies, calendars/holidays, routing rules and settings are not built — configure through the seed script / SQL for now. Users & roles admin and the audit viewer are built.
- **Exports** are CSV only (Excel opens them; `.xlsx` and scheduled reports are planned).
- **Dashboard historical metrics** are computed in the application for the selected range — fine for thousands of tickets per period; for very large volumes move to SQL aggregations or a reporting view.
- **Rate limiting and the scheduler are per process.** Use one scheduler instance and a shared store for limits when scaling out.
- **No user import / AD sync** yet; users are created by admins or a script.
- Frontend has no automated browser test suite in the repository (it was exercised end-to-end with a headless browser during the build).

## Improvements added beyond the brief
- Optimistic locking with friendly "someone else updated this" handling.
- Idempotent ticket creation (safe double-click / retry).
- Duplicate-ticket warning and live knowledge-base suggestions while typing the subject.
- Requester reply on *Pending Employee* automatically resumes work and the SLA clock.
- Leads excluded from auto-assignment so they can manage the queue.
- Recurring-issue alert to leads when the same category spikes in 24 h.
- Unassigned P1 auto-escalation after 15 business minutes.
- Global search (tickets + articles, `/` shortcut), light/dark theme, mobile layout, keyboard-accessible forms and modals.
- Demo-data badges everywhere seeded records appear.

## Roadmap
| Next | Item |
|---|---|
| Phase 5 | Multi-stage approvals (sequential/parallel, delegation, separation of duties); KB authoring & review; suggestions portal with anonymous option; email go-live |
| Phase 6 | Assets & CMDB with ticket links; `.xlsx` exports and scheduled reports; admin UIs for categories/SLA/calendars/rules/settings; notification preferences UI |
| Phase 7 | Entra ID SSO + MFA; AD user sync; Redis rate limiting; retention purge jobs; Playwright UI tests in CI; load test; pen test |
| Later | Email-to-ticket intake, Teams notifications, major-incident banner automation, problem management records |
