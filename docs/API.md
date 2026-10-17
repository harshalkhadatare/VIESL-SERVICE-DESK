# API Reference

Base path: `/api/v1` · JSON · Bearer access token in `Authorization` header.
Interactive docs (non-production only): `/api/docs` (Swagger) and `/api/redoc`. Full spec: `docs/openapi.json`.

## Conventions
- **Errors** always use one envelope: `{"error": {"code", "message", "details": [{field, message}], "request_id"}}`.
  Codes: `validation_error` (422), `business_rule` (422), `unauthorized`/`token_expired`/`invalid_credentials`/`account_locked` (401),
  `forbidden` (403), `not_found` (404), `conflict` (409), `rate_limited` (429), `internal_error` (500, no stack trace).
- **Unauthorized tickets return 404**, not 403, so ticket numbers cannot be enumerated.
- **Optimistic concurrency:** state-changing ticket actions require `expected_version` (from the last GET). Stale → 409.
- **Idempotency:** `POST /tickets` accepts an `Idempotency-Key` header; retries with the same key return the same ticket.
- **Unknown fields are rejected** (422) so protected attributes (`requester_id`, `status_code`, …) cannot be injected.
- **Pagination:** `page`, `page_size` (max 100) → `{items, total, page, page_size}`.
- **Anti-CSRF:** cookie-based auth endpoints (`/auth/login|refresh|logout`) require header `X-Requested-With: fetch`; the refresh cookie is HttpOnly, SameSite=Strict, path-scoped to `/api/v1/auth`.

## Ticket list filters
`GET /tickets?q=&scope=all|mine|assigned|queue&status=open|CODE,CODE&priority=P1,P2&category_id=&group_id=&assignee=me|unassigned|<id>&sla=breached|at_risk&date_from=&date_to=&sort=updated_desc|created_desc|created_asc|priority|due`
The same filters apply to `GET /tickets/export.csv` (requires `report.export`; formula-injection safe; audited).

## Endpoints
| Method | Path | Group | Summary |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Authentication | Login |
| POST | `/api/v1/auth/refresh` | Authentication | Refresh |
| POST | `/api/v1/auth/logout` | Authentication | Logout |
| GET | `/api/v1/auth/me` | Authentication | Me |
| POST | `/api/v1/auth/change-password` | Authentication | Change Password |
| GET | `/api/v1/tickets` | Tickets | List Tickets |
| POST | `/api/v1/tickets` | Tickets | Create Ticket |
| GET | `/api/v1/tickets/export.csv` | Tickets | Export Csv |
| POST | `/api/v1/tickets/duplicate-check` | Tickets | Duplicate Check |
| GET | `/api/v1/tickets/{number}` | Tickets | Get Ticket |
| GET | `/api/v1/tickets/{number}/comments` | Tickets | List Comments |
| POST | `/api/v1/tickets/{number}/comments` | Tickets | Add Comment |
| GET | `/api/v1/tickets/{number}/history` | Tickets | List History |
| POST | `/api/v1/tickets/{number}/status` | Tickets | Change Status |
| POST | `/api/v1/tickets/{number}/assign` | Tickets | Assign |
| POST | `/api/v1/tickets/{number}/accept` | Tickets | Accept |
| POST | `/api/v1/tickets/{number}/priority` | Tickets | Change Priority |
| POST | `/api/v1/tickets/{number}/rating` | Tickets | Rate |
| POST | `/api/v1/tickets/{number}/links` | Tickets | Link |
| GET | `/api/v1/tickets/{number}/attachments` | Tickets | List Attachments |
| POST | `/api/v1/tickets/{number}/attachments` | Tickets | Upload Attachment |
| GET | `/api/v1/tickets/{number}/attachments/{attachment_id}` | Tickets | Download Attachment |
| GET | `/api/v1/meta/catalog` | Reference data | Catalog |
| GET | `/api/v1/meta/priority-preview` | Reference data | Priority Preview |
| GET | `/api/v1/support-groups` | Reference data | Support Groups |
| GET | `/api/v1/support-groups/{group_id}/members` | Reference data | Group Members |
| GET | `/api/v1/departments` | Reference data | Departments |
| GET | `/api/v1/announcements` | Reference data | Announcements |
| GET | `/api/v1/dashboard/employee` | Dashboards | Employee |
| GET | `/api/v1/dashboard/ops` | Dashboards | Ops |
| GET | `/api/v1/dashboard/search` | Dashboards | Global Search |
| GET | `/api/v1/notifications` | Notifications | Notifications |
| GET | `/api/v1/notifications/unread-count` | Notifications | Unread Count |
| POST | `/api/v1/notifications/{nid}/read` | Notifications | Mark Read |
| POST | `/api/v1/notifications/read-all` | Notifications | Mark All |
| GET | `/api/v1/kb/articles` | Knowledge base | Kb Search |
| GET | `/api/v1/kb/articles/{aid}` | Knowledge base | Kb Article |
| GET | `/api/v1/admin/roles` | Administration | List Roles |
| GET | `/api/v1/admin/users` | Administration | List Users |
| PUT | `/api/v1/admin/users/{uid}/roles` | Administration | Set Roles |
| PATCH | `/api/v1/admin/users/{uid}/active` | Administration | Set Active |
| GET | `/api/v1/audit-logs` | Audit | Audit Logs |
| GET | `/api/v1/health` | Health | Health |
