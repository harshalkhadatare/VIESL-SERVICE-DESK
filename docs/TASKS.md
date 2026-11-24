# Task management

Management assigns tasks to anyone in the company; the person reports progress and submits the work;
the manager approves it or sends it back with feedback. It lives inside the IT Service Desk (same login,
same users), in its own area with its own data.

## Who sees what

| Person | What they get |
|---|---|
| **Top management (MD)** | Starts on **Task overview**. Assigns tasks to anyone. Sees only the tasks they assigned and the tasks given to them. |
| **Management** | Starts on **Task overview**. Assigns tasks to anyone. Sees only the tasks **they** assigned (and tasks given to them). |
| **IT Administrator** | Starts on the IT dashboard as before. Has a **Tasks \| IT Service Desk** switch. Like everyone else, sees only the tasks they are on. |
| **Employee** | No change — unless someone gives them a task. Then a **My tasks** item appears in their menu. |

## Privacy (important)

A task is visible **only to the people on it** — the person who assigned it and the people it is assigned to.
There is no "whole company" view: IT administrators and top management cannot open, search, count or see a task
they are not on (it simply doesn't exist for them). This is enforced by the server (API, search, overview,
analytics, notifications, emails), not just hidden on screen. Note: anyone with direct access to the database
itself (the Neon owner) can still read it.

## Several people on one task

Pick one or more people when you assign (or later with **Edit**). Everyone on the task gets the email, sees it under
**My tasks**, can post updates and can mark it complete. The first person is shown first; all are equal.

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

Every email shows the exact words the person wrote ("Message from …") and the task description.
Emails go out when a task is assigned, updated, submitted, approved, sent back, cancelled, when more time is asked
for or decided, **24 hours before the deadline**, and **once when it becomes overdue** (to both people).
Same mailbox and design as the ticket emails.

## Screens

* **Tasks** — green **+ Create** (or a quick task), a preset menu (Ongoing, Assigned by me, Assigned to me, Waiting for
  my approval, Overdue, With new comments, Completed, All tasks), filter chips with search, and **Advanced search**
  (words, role, status, priority, person, assigned by, category, deadline and created dates, overdue / new comments /
  no deadline / more time asked). Views: **List · Deadline · Planner · Calendar · Gantt**. Counters: **Overdue**,
  **Comments** (unread), **Mark all as read**. The ⚙ button sets the view Tasks opens in and hides/shows "Completed".
* **Deadline** columns: Overdue · Due today · Due this week · Due next week · Due over two weeks · No deadline · Completed,
  each with **+** to add a quick task with that deadline.
* **Performance** — efficiency (on time ÷ completed + overdue), per person for management.
* **Analytics** — created vs completed by week, by status, priority and category.
* The Tasks area uses the sky background; the IT desk keeps its normal look.

## Overview screen

Overdue · Due this week · Waiting for your approval · On-time completion (30 days) · Open tasks,
then **Needs your attention** (approvals, extension requests, overdue, no update for 5+ days),
**Deadlines in the next 7 days**, **Team progress** per person, and **Latest updates**.

## Safety

A user who has tasks (assigned by or to them) can't be permanently deleted — deactivate them instead, so the
tasks and their history are kept.

## Planned next

Attachments on tasks, linking tickets to tasks, recurring tasks, subtasks/checklists and Excel reports.

## Files on a task

Anyone on the task can attach files — on the **Assign a task** form, with the 📎 button next to *Send*, the
**Files** card on the task page, or by pasting a screenshot (Ctrl+V). Allowed: images, PDF, Word, Excel and
PowerPoint (macro files such as .xlsm are refused), up to 30 files per task. Images and PDFs open in the built-in
viewer; Office files are downloaded. Only the people on the task can see or open the files. The person who added a
file, or the person who assigned the task, can remove it.

## Export to Excel

**Tasks → Export to Excel** downloads the tasks in the current list (same filters) as one workbook:
*Tasks* (all details, latest update, link to open the task), *Updates* (every message and change) and
*Attachments* (one row per file with a link that opens that file — sign-in required). Only tasks you are on are
included.

## Emails

To keep inboxes quiet, task emails are sent only for: **a new task assigned**, **a task completed** (marked
complete / approved), and **deadline changes** (deadline changed, more time asked for, more time approved or
refused). Everything else — messages, progress updates, files, reminders, overdue alerts — appears only in the
app's **Notifications**.
