-- FORCE delete ONE user by Employee ID, INCLUDING everything they created (Neon / PostgreSQL).
-- Use for test / wrong accounts. Permanently removes:
--   * tickets the user RAISED (with their comments, files, history, SLA, ratings)
--   * the user's comments, uploaded files, ratings and ticket links on other tickets
--   * KB articles the user wrote
-- Change the employee code on the line marked  <<< CHANGE  and run the whole script.

DO $$
DECLARE
  v_code text := '11111';              -- <<< CHANGE: employee code to delete
  v_id   int;
  v_name text;
  v_tix  int[];
  v_att  int[];
BEGIN
  SELECT id, full_name INTO v_id, v_name FROM users WHERE upper(employee_code) = upper(v_code);
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'No user with employee code %', v_code;
  END IF;

  -- 1. tickets raised by the user, with everything attached to them
  SELECT coalesce(array_agg(id), '{}') INTO v_tix FROM tickets WHERE requester_id = v_id;
  DELETE FROM ticket_attachment_blobs WHERE attachment_id IN (SELECT id FROM ticket_attachments WHERE ticket_id = ANY(v_tix));
  DELETE FROM ticket_attachments      WHERE ticket_id = ANY(v_tix);
  DELETE FROM ticket_comments         WHERE ticket_id = ANY(v_tix);
  DELETE FROM ticket_history          WHERE ticket_id = ANY(v_tix);
  DELETE FROM ticket_assignments      WHERE ticket_id = ANY(v_tix);
  DELETE FROM ticket_watchers         WHERE ticket_id = ANY(v_tix);
  DELETE FROM ticket_relationships    WHERE source_ticket_id = ANY(v_tix) OR target_ticket_id = ANY(v_tix);
  DELETE FROM ticket_erp_details      WHERE ticket_id = ANY(v_tix);
  DELETE FROM sla_tracking            WHERE ticket_id = ANY(v_tix);
  DELETE FROM satisfaction_ratings    WHERE ticket_id = ANY(v_tix);
  DELETE FROM idempotency_keys        WHERE ticket_id = ANY(v_tix);
  UPDATE notifications             SET ticket_id = NULL WHERE ticket_id = ANY(v_tix);
  UPDATE automation_execution_logs SET ticket_id = NULL WHERE ticket_id = ANY(v_tix);
  UPDATE knowledge_articles        SET source_ticket_id = NULL WHERE source_ticket_id = ANY(v_tix);
  DELETE FROM tickets                 WHERE id = ANY(v_tix);

  -- 2. the user's content on other people's tickets
  SELECT coalesce(array_agg(id), '{}') INTO v_att FROM ticket_attachments WHERE uploaded_by = v_id;
  DELETE FROM ticket_attachment_blobs WHERE attachment_id = ANY(v_att);
  DELETE FROM ticket_attachments      WHERE id = ANY(v_att);
  UPDATE ticket_attachments SET comment_id = NULL WHERE comment_id IN (SELECT id FROM ticket_comments WHERE author_id = v_id);
  DELETE FROM ticket_comments         WHERE author_id = v_id;
  DELETE FROM satisfaction_ratings    WHERE rated_by = v_id;
  DELETE FROM ticket_relationships    WHERE created_by = v_id;

  -- 3. knowledge base content
  DELETE FROM knowledge_article_versions WHERE edited_by = v_id
     OR article_id IN (SELECT id FROM knowledge_articles WHERE author_id = v_id);
  DELETE FROM knowledge_articles      WHERE author_id = v_id;

  -- optional references -> NULL (history kept, shown as System)
  UPDATE audit_logs           SET actor_id = NULL              WHERE actor_id = v_id;
  UPDATE ticket_history       SET actor_id = NULL              WHERE actor_id = v_id;
  UPDATE tickets              SET assignee_id = NULL           WHERE assignee_id = v_id;
  UPDATE tickets              SET created_by = NULL            WHERE created_by = v_id;
  UPDATE tickets              SET closed_by = NULL             WHERE closed_by = v_id;
  UPDATE ticket_assignments   SET assignee_id = NULL           WHERE assignee_id = v_id;
  UPDATE ticket_assignments   SET assigned_by = NULL           WHERE assigned_by = v_id;
  UPDATE support_groups       SET last_assigned_user_id = NULL WHERE last_assigned_user_id = v_id;
  UPDATE user_roles           SET granted_by = NULL            WHERE granted_by = v_id;
  UPDATE announcements        SET created_by = NULL            WHERE created_by = v_id;
  UPDATE application_settings SET updated_by = NULL            WHERE updated_by = v_id;
  UPDATE automation_rules     SET created_by = NULL            WHERE created_by = v_id;
  UPDATE knowledge_articles   SET reviewer_id = NULL           WHERE reviewer_id = v_id;

  -- the user's own rows
  DELETE FROM ticket_watchers          WHERE user_id = v_id;
  DELETE FROM notifications            WHERE user_id = v_id;
  DELETE FROM notification_preferences WHERE user_id = v_id;
  DELETE FROM idempotency_keys         WHERE user_id = v_id;
  DELETE FROM refresh_tokens           WHERE user_id = v_id;
  DELETE FROM support_group_members    WHERE user_id = v_id;
  DELETE FROM user_roles               WHERE user_id = v_id;
  DELETE FROM users                    WHERE id = v_id;

  RAISE NOTICE 'Deleted user % (%) and % ticket(s) they raised', v_name, v_code, coalesce(array_length(v_tix, 1), 0);
END $$;
