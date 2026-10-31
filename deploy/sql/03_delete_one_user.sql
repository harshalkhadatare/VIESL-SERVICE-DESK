-- Delete ONE user by Employee ID (Neon / PostgreSQL).
-- Change the employee code on the line marked  <<< CHANGE  and run the whole script.
--
-- * Removes the user's roles, sessions, team membership, notifications and preferences.
-- * Keeps audit logs and ticket history but shows the action as "System" (actor set to NULL).
-- * Stops safely (nothing is deleted) if the user raised tickets, wrote comments, uploaded files,
--   rated tickets or wrote KB articles - those records need the user. For such people use
--   Users & roles -> Deactivate instead (they can no longer sign in, history stays correct).

DO $$
DECLARE
  v_code text := '11111';              -- <<< CHANGE: employee code to delete
  v_id   int;
  v_name text;
  v_blockers text := '';
  n int;
BEGIN
  SELECT id, full_name INTO v_id, v_name FROM users WHERE upper(employee_code) = upper(v_code);
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'No user with employee code %', v_code;
  END IF;

  -- records that cannot exist without the user
  SELECT count(*) INTO n FROM tickets WHERE requester_id = v_id;              IF n > 0 THEN v_blockers := v_blockers || n || ' ticket(s) raised, '; END IF;
  SELECT count(*) INTO n FROM ticket_comments WHERE author_id = v_id;         IF n > 0 THEN v_blockers := v_blockers || n || ' comment(s), '; END IF;
  SELECT count(*) INTO n FROM ticket_attachments WHERE uploaded_by = v_id;    IF n > 0 THEN v_blockers := v_blockers || n || ' attachment(s), '; END IF;
  SELECT count(*) INTO n FROM satisfaction_ratings WHERE rated_by = v_id;     IF n > 0 THEN v_blockers := v_blockers || n || ' rating(s), '; END IF;
  SELECT count(*) INTO n FROM ticket_relationships WHERE created_by = v_id;   IF n > 0 THEN v_blockers := v_blockers || n || ' ticket link(s), '; END IF;
  SELECT count(*) INTO n FROM knowledge_articles WHERE author_id = v_id;      IF n > 0 THEN v_blockers := v_blockers || n || ' KB article(s), '; END IF;
  SELECT count(*) INTO n FROM knowledge_article_versions WHERE edited_by = v_id; IF n > 0 THEN v_blockers := v_blockers || n || ' KB edit(s), '; END IF;
  IF v_blockers <> '' THEN
    RAISE EXCEPTION 'Not deleted: % (%) has %. Deactivate this user in Users & roles instead.',
      v_name, v_code, rtrim(v_blockers, ', ');
  END IF;

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

  RAISE NOTICE 'Deleted user % (%)', v_name, v_code;
END $$;
