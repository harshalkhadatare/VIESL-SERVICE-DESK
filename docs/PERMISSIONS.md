# Roles & permissions

All checks run on the server. Roles are data (`roles`, `permissions`, `role_permissions`) and can be changed by an IT Administrator; a user may hold several roles.

## Role → permission matrix

| Permission | Employee | Dept. Viewer | IT Engineer | IT Lead | IT Admin | Management / Auditor |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| ticket.create — raise tickets | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ticket.view_own | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ticket.view_department (explicit grant) | | ✓ | | | ✓ | |
| ticket.view_group — own groups + assigned | | | ✓ | ✓ | ✓ | |
| ticket.view_all | | | | | ✓ | ✓ |
| ticket.view_internal — read internal notes | | | | | ✓ | ✓ |
| ticket.work — update, resolve, reply | | | ✓ | ✓ | ✓ | |
| ticket.accept — self-assign queued ticket | | | ✓ | ✓ | ✓ | |
| ticket.escalate — move to another group | | | ✓ | ✓ | ✓ | |
| ticket.comment_internal | | | ✓ | ✓ | ✓ | |
| ticket.link — related / duplicate | | | ✓ | ✓ | ✓ | |
| ticket.assign — within groups they lead | | | | ✓ | ✓ | |
| ticket.set_priority | | | | ✓ | ✓ | |
| ticket.manage_all — act on any ticket | | | | | ✓ | |
| dashboard.ops | | | ✓ | ✓ | ✓ | ✓ |
| report.export | | | | ✓ | ✓ | ✓ |
| kb.view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| kb.manage | | | | ✓ | ✓ | |
| user.manage | | | | | ✓ | |
| audit.view | | | | | ✓ | ✓ |
| settings.manage | | | | | ✓ | |

Row-level rules on top of permissions
- Engineers/leads act only on tickets in **their** support groups or assigned to them; leads assign only within groups they **lead**.
- Engineers can escalate (change group, no assignee) with a mandatory reason, but cannot pick an engineer.
- Requesters can confirm/close or reopen (within the window) their resolved tickets and cancel queued ones.
- Management can read everything including internal notes but cannot change tickets.
- Tickets a user cannot see return **404**.

## Verified test matrix (`backend/tests/test_permission_matrix.py`)

| Action on an employee's ERP ticket | Employee (owner) | Other employee | ERP engineer | Infra engineer | ERP lead | Infra lead | Admin | Management |
|---|---|---|---|---|---|---|---|---|
| Create ticket | 201 | – | 201 | – | 201 | – | 201 | 201 |
| View ticket | 200 | 404 | 200 | 404 | 200 | 404 | 200 | 200 |
| Internal note | 403 | – | 201 | – | 201 | – | 201 | 403 |
| Ops dashboard | 403 | – | 200 | – | 200 | – | 200 | 200 |
| Export CSV | 403 | – | 403 | – | 200 | – | 200 | 200 |
| User admin | 403 | – | 403 | – | 403 | – | 200 | 403 |
| Audit log | 403 | – | – | – | 403 | – | 200 | 200 |
| Change priority | 403 | – | 403 | – | 200 | – | 200 | 403 |

Further behaviour covered by tests: identity spoofing rejected, cross-group assignment blocked, internal notes/attachments hidden, related tickets don't leak, exports scoped like lists, notifications private, deactivated users lose access immediately.
