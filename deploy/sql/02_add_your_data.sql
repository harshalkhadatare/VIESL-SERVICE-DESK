-- ADD YOUR OWN DATA (PostgreSQL / Neon). Run one block at a time in the Neon SQL Editor.
-- Replace YOUR-ADMIN-EMAIL / EMPLOYEE-EMAIL with real addresses. Create users in the app (Users & roles -> Add user).

-- 1) Departments
INSERT INTO departments (code, name, is_active, created_at, updated_at) VALUES
  ('ACCT', 'Accounts', true, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'),
  ('SITE', 'Site Operations', true, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc');

-- 2) Locations / branches
INSERT INTO locations (code, name, is_active, created_at, updated_at) VALUES
  ('NSK', 'Nashik Branch', true, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc');

-- 3) Put a user into a department and location (users themselves are added in the app)
UPDATE users SET department_id = (SELECT id FROM departments WHERE code = 'ACCT'),
                 location_id   = (SELECT id FROM locations   WHERE code = 'NSK')
WHERE email = 'EMPLOYEE-EMAIL';

-- 4) Add an IT administrator to a support team (tickets of that team are auto-assigned to its members)
--    Team codes: ERP, INFRA (network/email), EUC (laptops/printers), SD (service desk), SEC (security)
INSERT INTO support_group_members (group_id, user_id, is_lead, is_available)
SELECT g.id, u.id, false, true FROM support_groups g, users u
WHERE g.code = 'EUC' AND u.email = 'YOUR-ADMIN-EMAIL';

-- 5) Company holidays (SLA timers skip them)
INSERT INTO holidays (calendar_id, holiday_date, name)
SELECT id, DATE '2026-11-09', 'Diwali (Lakshmi Puja)' FROM business_calendars WHERE is_default;

-- 6) A new subcategory under an existing category
INSERT INTO subcategories (category_id, name, is_active)
SELECT id, 'Biometric attendance device', true FROM categories WHERE code = 'HARDWARE';

-- 7) Announcement on everyone's home page (shown until ends_at)
INSERT INTO announcements (title, body, severity, starts_at, ends_at, created_at, updated_at, created_by)
VALUES ('Welcome to the IT Service Desk',
        'Please raise all IT requests here instead of calling or emailing.',
        'info', now() AT TIME ZONE 'utc', (now() + interval '30 days') AT TIME ZONE 'utc',
        now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc',
        (SELECT id FROM users WHERE email = 'YOUR-ADMIN-EMAIL'));

-- 8) Knowledge-base article (visible to employees when status = 'published')
INSERT INTO knowledge_articles (title, category_id, keywords, problem, solution, status, author_id,
                                version, view_count, published_at, created_at, updated_at)
VALUES ('Connect to office Wi-Fi',
        (SELECT id FROM categories WHERE code = 'NETWORK'),
        'wifi wireless network connect password',
        'You cannot connect your laptop to the office Wi-Fi.',
        E'1. Select the network VIESL-Staff.\n2. Sign in with your Windows username and password.\n3. If it fails, raise a Network ticket.',
        'published', (SELECT id FROM users WHERE email = 'YOUR-ADMIN-EMAIL'),
        1, 0, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc');
