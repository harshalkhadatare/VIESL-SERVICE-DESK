# Task management

Management assigns tasks to anyone in the company; the person reports progress and submits the work;
the manager approves it or sends it back with feedback. It lives inside the IT Service Desk (same login,
same users), in its own area with its own data.

## Who sees what

| Person | What they get |
|---|---|
| **Top management (MD)** | Starts on **Task overview**. Assigns tasks to anyone. Sees **every** task (switch "Assigned by me / Whole company"). |
| **Management** | Starts on **Task overview**. Assigns tasks to anyone. Sees only the tasks **they** assigned (and tasks given to them). |
| **IT Administrator** | Starts on the IT dashboard as before. Has a **Tasks \| IT Service Desk** switch and can see and fix any task (Task admin). Every action is in the audit log under their own name. |
| **Employee** | No change — unless someone gives them a task. Then a **My tasks** item appears in their menu. |

## Making someone management (admins)

Users & roles → find the person → **Roles** → tick **Management** or **Top management (MD)** *next to* their
normal role (Employee or IT Administrator) → Save. They see the Tasks area the next time they sign in.

## The flow

1. **Assign** — title, details, person, deadline, priority, optional category, and whether you want to approve the work.
2. The person gets an email, opens the task, clicks **Start**, and posts **updates** (progress % + a note).
3. Need more time? They click **Ask for more time** (new date + reason). The manager approves or keeps the deadline.
4. **Mark as complete** → the manager reviews: **Approve** (with optional 1–5 star rating and feedback)
   or **Send back** with what needs to change.

Tasks are numbered `TSK-26-000001`. Every step is kept in the task's **Timeline**.

## Emails and reminders

Emails go out when a task is assigned, updated, submitted, approved, sent back, cancelled, when more time is asked
for or decided, **24 hours before the deadline**, and **once when it becomes overdue** (to both people).
Same mailbox and design as the ticket emails.

## Overview screen

Overdue · Due this week · Waiting for your approval · On-time completion (30 days) · Open tasks,
then **Needs your attention** (approvals, extension requests, overdue, no update for 5+ days),
**Deadlines in the next 7 days**, **Team progress** per person, and **Latest updates**.

## Safety

A user who has tasks (assigned by or to them) can't be permanently deleted — deactivate them instead, so the
tasks and their history are kept.

## Planned next

Attachments on tasks, "View as" for admins (read-only), customisable start page and tiles, linking tickets to tasks,
recurring tasks, subtasks/checklists and Excel reports.
