# Roles & permissions

There are exactly **two roles**. All checks run on the server for every request.

| Capability | Employee | IT Administrator |
|---|:-:|:-:|
| Raise tickets, add comments and images/PDFs to own tickets | ✓ | ✓ |
| See own tickets | ✓ | ✓ |
| See **all** tickets | | ✓ |
| Confirm / reopen (within 7 days) / cancel own ticket, rate the service | ✓ | ✓ |
| Work tickets: change status, resolve, reply, internal notes, link tickets | | ✓ |
| Assign tickets to any IT administrator (⋮ menu or ticket page), move between teams | | ✓ |
| Change priority | | ✓ |
| Operations dashboard, CSV export | | ✓ |
| Knowledge base (read) | ✓ | ✓ |
| Add users, change roles, activate/deactivate | | ✓ |
| Email notification settings & test email | | ✓ |
| Audit log | | ✓ |

Rules
- Tickets can only be assigned to active users with the IT Administrator role.
- Employees never see internal notes, internal attachments or root-cause notes.
- Tickets an employee cannot see return **404**, so ticket numbers cannot be guessed.
- An administrator cannot remove their own administrator role or deactivate themselves.
- Roles from earlier versions (engineer, team lead, management, department viewer) are converted automatically the
  next time `python -m app.seed` runs: IT roles become IT Administrator, others become Employee.

Verified by `backend/tests/test_permission_matrix.py` (every row above is exercised against the real API).
