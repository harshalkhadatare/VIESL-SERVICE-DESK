-- =====================================================================
-- CLEAN ALL TEST DATA  (Vision Infra IT Service Desk · PostgreSQL / Neon)
-- Keeps: your real (non-demo) users, roles, categories, priorities,
--        statuses, SLA rules, calendars, holidays, support teams,
--        departments, locations and the knowledge-base articles.
-- Deletes: every ticket (with comments, attachments, history, ratings),
--          all notifications and audit history, all demo users.
-- BEFORE RUNNING: replace YOUR-ADMIN-EMAIL below (2 places).
-- =====================================================================
BEGIN;

-- 1) Tickets and everything attached to them
DELETE FROM notifications;
DELETE FROM idempotency_keys;
DELETE FROM automation_execution_logs;
UPDATE knowledge_articles SET source_ticket_id = NULL;
DELETE FROM ticket_attachment_blobs;
DELETE FROM ticket_attachments;
DELETE FROM ticket_comments;
DELETE FROM ticket_history;
DELETE FROM ticket_assignments;
DELETE FROM ticket_watchers;
DELETE FROM ticket_relationships;
DELETE FROM satisfaction_ratings;
DELETE FROM sla_tracking;
DELETE FROM ticket_erp_details;
DELETE FROM tickets;
DELETE FROM ticket_sequences;          -- new tickets start again at IT-2026-000001

-- 2) Demo users (all have emails ending in @demo.example.com)
UPDATE knowledge_articles SET author_id = (SELECT id FROM users WHERE email = 'YOUR-ADMIN-EMAIL')
  WHERE author_id IN (SELECT id FROM users WHERE is_demo);
UPDATE knowledge_articles SET reviewer_id = NULL WHERE reviewer_id IN (SELECT id FROM users WHERE is_demo);
UPDATE knowledge_article_versions SET edited_by = (SELECT id FROM users WHERE email = 'YOUR-ADMIN-EMAIL')
  WHERE edited_by IN (SELECT id FROM users WHERE is_demo);
DELETE FROM announcements WHERE created_by IN (SELECT id FROM users WHERE is_demo);
UPDATE support_groups SET last_assigned_user_id = NULL;
DELETE FROM support_group_members WHERE user_id IN (SELECT id FROM users WHERE is_demo);
UPDATE user_roles SET granted_by = NULL WHERE granted_by IN (SELECT id FROM users WHERE is_demo);
DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE is_demo);
DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE is_demo);
DELETE FROM notification_preferences WHERE user_id IN (SELECT id FROM users WHERE is_demo);
UPDATE automation_rules SET created_by = NULL WHERE created_by IN (SELECT id FROM users WHERE is_demo);
UPDATE application_settings SET updated_by = NULL WHERE updated_by IN (SELECT id FROM users WHERE is_demo);
DELETE FROM audit_logs;                -- testing history
DELETE FROM users WHERE is_demo;

COMMIT;

-- Check the result
SELECT 'users' AS what, count(*) FROM users
UNION ALL SELECT 'tickets', count(*) FROM tickets
UNION ALL SELECT 'kb articles', count(*) FROM knowledge_articles;
