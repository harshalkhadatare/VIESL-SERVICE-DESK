BEGIN TRANSACTION;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

GO

-- Running upgrade  -> 0001_initial

CREATE TABLE business_calendars (
    id INTEGER NOT NULL IDENTITY, 
    name NVARCHAR(80) NOT NULL, 
    timezone NVARCHAR(60) NOT NULL, 
    work_start DATETIME NOT NULL, 
    work_end DATETIME NOT NULL, 
    working_days NVARCHAR(7) NOT NULL, 
    is_default BIT NOT NULL DEFAULT 0, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_business_calendars PRIMARY KEY (id), 
    CONSTRAINT uq_business_calendars_name UNIQUE (name)
);

GO

CREATE TABLE departments (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(20) NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_departments PRIMARY KEY (id), 
    CONSTRAINT uq_departments_code UNIQUE (code)
);

GO

CREATE TABLE locations (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(20) NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_locations PRIMARY KEY (id), 
    CONSTRAINT uq_locations_code UNIQUE (code)
);

GO

CREATE TABLE permissions (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(60) NOT NULL, 
    description NVARCHAR(255) NULL, 
    CONSTRAINT pk_permissions PRIMARY KEY (id), 
    CONSTRAINT uq_permissions_code UNIQUE (code)
);

GO

CREATE TABLE priorities (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(5) NOT NULL, 
    name NVARCHAR(40) NOT NULL, 
    rank INTEGER NOT NULL, 
    description NVARCHAR(255) NULL, 
    CONSTRAINT pk_priorities PRIMARY KEY (id), 
    CONSTRAINT uq_priorities_code UNIQUE (code)
);

GO

CREATE TABLE roles (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(40) NOT NULL, 
    name NVARCHAR(80) NOT NULL, 
    description NVARCHAR(255) NULL, 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_code UNIQUE (code)
);

GO

CREATE TABLE ticket_sequences (
    year INTEGER NOT NULL, 
    last_value INTEGER NOT NULL, 
    CONSTRAINT pk_ticket_sequences PRIMARY KEY (year)
);

GO

CREATE TABLE ticket_statuses (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(30) NOT NULL, 
    name NVARCHAR(60) NOT NULL, 
    is_open BIT NOT NULL, 
    pauses_sla BIT NOT NULL, 
    sort_order INTEGER NOT NULL, 
    CONSTRAINT pk_ticket_statuses PRIMARY KEY (id), 
    CONSTRAINT uq_ticket_statuses_code UNIQUE (code)
);

GO

CREATE TABLE holidays (
    id INTEGER NOT NULL IDENTITY, 
    calendar_id INTEGER NOT NULL, 
    holiday_date DATETIME NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    CONSTRAINT pk_holidays PRIMARY KEY (id), 
    CONSTRAINT fk_holidays_calendar_id_business_calendars FOREIGN KEY(calendar_id) REFERENCES business_calendars (id), 
    CONSTRAINT uq_holidays_calendar_id_holiday_date UNIQUE (calendar_id, holiday_date)
);

GO

CREATE TABLE priority_matrix (
    id INTEGER NOT NULL IDENTITY, 
    impact INTEGER NOT NULL, 
    urgency INTEGER NOT NULL, 
    priority_id INTEGER NOT NULL, 
    CONSTRAINT pk_priority_matrix PRIMARY KEY (id), 
    CONSTRAINT ck_priority_matrix_impact_range CHECK (impact BETWEEN 1 AND 3), 
    CONSTRAINT ck_priority_matrix_urgency_range CHECK (urgency BETWEEN 1 AND 3), 
    CONSTRAINT fk_priority_matrix_priority_id_priorities FOREIGN KEY(priority_id) REFERENCES priorities (id), 
    CONSTRAINT uq_priority_matrix_impact_urgency UNIQUE (impact, urgency)
);

GO

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL, 
    permission_id INTEGER NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
    CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id), 
    CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id)
);

GO

CREATE TABLE status_transitions (
    id INTEGER NOT NULL IDENTITY, 
    from_code NVARCHAR(30) NOT NULL, 
    to_code NVARCHAR(30) NOT NULL, 
    actor NVARCHAR(10) NOT NULL, 
    requires_reason BIT NOT NULL, 
    CONSTRAINT pk_status_transitions PRIMARY KEY (id), 
    CONSTRAINT ck_status_transitions_actor CHECK (actor IN ('staff','requester','any')), 
    CONSTRAINT fk_status_transitions_from_code_ticket_statuses FOREIGN KEY(from_code) REFERENCES ticket_statuses (code), 
    CONSTRAINT fk_status_transitions_to_code_ticket_statuses FOREIGN KEY(to_code) REFERENCES ticket_statuses (code), 
    CONSTRAINT uq_status_transitions_from_code_to_code_actor UNIQUE (from_code, to_code, actor)
);

GO

CREATE TABLE users (
    id INTEGER NOT NULL IDENTITY, 
    employee_code NVARCHAR(30) NOT NULL, 
    email NVARCHAR(254) NOT NULL, 
    full_name NVARCHAR(150) NOT NULL, 
    phone NVARCHAR(30) NULL, 
    job_title NVARCHAR(120) NULL, 
    department_id INTEGER NULL, 
    location_id INTEGER NULL, 
    password_hash NVARCHAR(255) NULL, 
    auth_provider NVARCHAR(20) NOT NULL, 
    timezone NVARCHAR(60) NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    is_demo BIT NOT NULL DEFAULT 0, 
    failed_logins INTEGER NOT NULL, 
    locked_until DATETIME2(3) NULL, 
    last_login_at DATETIME2(3) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT fk_users_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), 
    CONSTRAINT fk_users_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id), 
    CONSTRAINT uq_users_email UNIQUE (email), 
    CONSTRAINT uq_users_employee_code UNIQUE (employee_code)
);

GO

CREATE TABLE announcements (
    id INTEGER NOT NULL IDENTITY, 
    title NVARCHAR(200) NOT NULL, 
    body NVARCHAR(2000) NOT NULL, 
    severity NVARCHAR(10) NOT NULL, 
    starts_at DATETIME2(3) NOT NULL, 
    ends_at DATETIME2(3) NULL, 
    created_by INTEGER NULL, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_announcements PRIMARY KEY (id), 
    CONSTRAINT fk_announcements_created_by_users FOREIGN KEY(created_by) REFERENCES users (id)
);

GO

CREATE TABLE application_settings (
    [key] NVARCHAR(80) NOT NULL, 
    value NVARCHAR(1000) NOT NULL, 
    description NVARCHAR(255) NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    updated_by INTEGER NULL, 
    CONSTRAINT pk_application_settings PRIMARY KEY ([key]), 
    CONSTRAINT fk_application_settings_updated_by_users FOREIGN KEY(updated_by) REFERENCES users (id)
);

GO

CREATE TABLE audit_logs (
    id INTEGER NOT NULL IDENTITY, 
    actor_id INTEGER NULL, 
    actor_label NVARCHAR(254) NULL, 
    action NVARCHAR(60) NOT NULL, 
    entity_type NVARCHAR(40) NULL, 
    entity_id NVARCHAR(40) NULL, 
    detail NVARCHAR(2000) NULL, 
    ip_address NVARCHAR(45) NULL, 
    request_id NVARCHAR(36) NULL, 
    outcome NVARCHAR(10) NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id)
);

GO

CREATE INDEX ix_audit_actor ON audit_logs (actor_id, created_at);

GO

CREATE INDEX ix_audit_created ON audit_logs (created_at);

GO

CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id);

GO

CREATE TABLE notification_preferences (
    user_id INTEGER NOT NULL, 
    event NVARCHAR(40) NOT NULL, 
    in_app BIT NOT NULL, 
    email BIT NOT NULL, 
    CONSTRAINT pk_notification_preferences PRIMARY KEY (user_id, event), 
    CONSTRAINT fk_notification_preferences_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

GO

CREATE TABLE refresh_tokens (
    id INTEGER NOT NULL IDENTITY, 
    user_id INTEGER NOT NULL, 
    token_hash NVARCHAR(64) NOT NULL, 
    family_id NVARCHAR(36) NOT NULL, 
    expires_at DATETIME2(3) NOT NULL, 
    revoked_at DATETIME2(3) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    user_agent NVARCHAR(255) NULL, 
    CONSTRAINT pk_refresh_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
    CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash)
);

GO

CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);

GO

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

GO

CREATE TABLE support_groups (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(30) NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    email NVARCHAR(254) NULL, 
    assignment_strategy NVARCHAR(20) NOT NULL, 
    last_assigned_user_id INTEGER NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_support_groups PRIMARY KEY (id), 
    CONSTRAINT fk_support_groups_last_assigned_user_id_users FOREIGN KEY(last_assigned_user_id) REFERENCES users (id), 
    CONSTRAINT uq_support_groups_code UNIQUE (code)
);

GO

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL, 
    role_id INTEGER NOT NULL, 
    granted_at DATETIME2(3) NOT NULL, 
    granted_by INTEGER NULL, 
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_user_roles_granted_by_users FOREIGN KEY(granted_by) REFERENCES users (id), 
    CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id), 
    CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

GO

CREATE TABLE categories (
    id INTEGER NOT NULL IDENTITY, 
    code NVARCHAR(40) NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    description NVARCHAR(500) NULL, 
    default_ticket_type NVARCHAR(20) NOT NULL, 
    default_group_id INTEGER NULL, 
    uses_erp_fields BIT NOT NULL DEFAULT 0, 
    requires_approval BIT NOT NULL DEFAULT 0, 
    is_protected BIT NOT NULL DEFAULT 0, 
    sort_order INTEGER NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_categories PRIMARY KEY (id), 
    CONSTRAINT ck_categories_ticket_type CHECK (default_ticket_type IN ('incident','service_request')), 
    CONSTRAINT fk_categories_default_group_id_support_groups FOREIGN KEY(default_group_id) REFERENCES support_groups (id), 
    CONSTRAINT uq_categories_code UNIQUE (code)
);

GO

CREATE TABLE support_group_members (
    id INTEGER NOT NULL IDENTITY, 
    group_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    is_lead BIT NOT NULL DEFAULT 0, 
    is_available BIT NOT NULL DEFAULT 1, 
    skills NVARCHAR(255) NULL, 
    CONSTRAINT pk_support_group_members PRIMARY KEY (id), 
    CONSTRAINT fk_support_group_members_group_id_support_groups FOREIGN KEY(group_id) REFERENCES support_groups (id), 
    CONSTRAINT fk_support_group_members_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
    CONSTRAINT uq_support_group_members_group_id_user_id UNIQUE (group_id, user_id)
);

GO

CREATE INDEX ix_sgm_user ON support_group_members (user_id);

GO

CREATE TABLE sla_policies (
    id INTEGER NOT NULL IDENTITY, 
    name NVARCHAR(120) NOT NULL, 
    priority_id INTEGER NOT NULL, 
    category_id INTEGER NULL, 
    calendar_id INTEGER NOT NULL, 
    response_minutes INTEGER NOT NULL, 
    resolution_minutes INTEGER NOT NULL, 
    warning_percent INTEGER NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_sla_policies PRIMARY KEY (id), 
    CONSTRAINT ck_sla_policies_positive_targets CHECK (response_minutes > 0 AND resolution_minutes > 0), 
    CONSTRAINT ck_sla_policies_warning_pct CHECK (warning_percent BETWEEN 1 AND 99), 
    CONSTRAINT fk_sla_policies_calendar_id_business_calendars FOREIGN KEY(calendar_id) REFERENCES business_calendars (id), 
    CONSTRAINT fk_sla_policies_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
    CONSTRAINT fk_sla_policies_priority_id_priorities FOREIGN KEY(priority_id) REFERENCES priorities (id)
);

GO

CREATE TABLE subcategories (
    id INTEGER NOT NULL IDENTITY, 
    category_id INTEGER NOT NULL, 
    name NVARCHAR(120) NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    CONSTRAINT pk_subcategories PRIMARY KEY (id), 
    CONSTRAINT fk_subcategories_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
    CONSTRAINT uq_subcategories_category_id_name UNIQUE (category_id, name)
);

GO

CREATE TABLE automation_rules (
    id INTEGER NOT NULL IDENTITY, 
    name NVARCHAR(120) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    is_active BIT NOT NULL DEFAULT 1, 
    match_category_id INTEGER NULL, 
    match_subcategory_id INTEGER NULL, 
    match_department_id INTEGER NULL, 
    match_location_id INTEGER NULL, 
    match_priority_id INTEGER NULL, 
    match_erp_module NVARCHAR(60) NULL, 
    target_group_id INTEGER NOT NULL, 
    assignment_strategy NVARCHAR(20) NOT NULL, 
    created_by INTEGER NULL, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_automation_rules PRIMARY KEY (id), 
    CONSTRAINT ck_automation_rules_strategy CHECK (assignment_strategy IN ('group_default','manual','round_robin','least_loaded')), 
    CONSTRAINT fk_automation_rules_created_by_users FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_automation_rules_match_category_id_categories FOREIGN KEY(match_category_id) REFERENCES categories (id), 
    CONSTRAINT fk_automation_rules_match_department_id_departments FOREIGN KEY(match_department_id) REFERENCES departments (id), 
    CONSTRAINT fk_automation_rules_match_location_id_locations FOREIGN KEY(match_location_id) REFERENCES locations (id), 
    CONSTRAINT fk_automation_rules_match_priority_id_priorities FOREIGN KEY(match_priority_id) REFERENCES priorities (id), 
    CONSTRAINT fk_automation_rules_match_subcategory_id_subcategories FOREIGN KEY(match_subcategory_id) REFERENCES subcategories (id), 
    CONSTRAINT fk_automation_rules_target_group_id_support_groups FOREIGN KEY(target_group_id) REFERENCES support_groups (id)
);

GO

CREATE TABLE tickets (
    id INTEGER NOT NULL IDENTITY, 
    number NVARCHAR(20) NOT NULL, 
    ticket_type NVARCHAR(20) NOT NULL, 
    subject NVARCHAR(200) NOT NULL, 
    description NVARCHAR(max) NOT NULL, 
    requester_id INTEGER NOT NULL, 
    department_id INTEGER NULL, 
    location_id INTEGER NULL, 
    category_id INTEGER NOT NULL, 
    subcategory_id INTEGER NULL, 
    impact INTEGER NOT NULL, 
    urgency INTEGER NOT NULL, 
    priority_id INTEGER NOT NULL, 
    status_code NVARCHAR(30) NOT NULL, 
    support_group_id INTEGER NULL, 
    assignee_id INTEGER NULL, 
    contact_method NVARCHAR(20) NULL, 
    root_cause NVARCHAR(max) NULL, 
    resolution_notes NVARCHAR(max) NULL, 
    first_response_at DATETIME2(3) NULL, 
    assigned_at DATETIME2(3) NULL, 
    resolved_at DATETIME2(3) NULL, 
    closed_at DATETIME2(3) NULL, 
    closed_by INTEGER NULL, 
    closure_reason NVARCHAR(30) NULL, 
    reopen_count INTEGER NOT NULL, 
    is_demo BIT NOT NULL DEFAULT 0, 
    version INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    created_by INTEGER NULL, 
    CONSTRAINT pk_tickets PRIMARY KEY (id), 
    CONSTRAINT ck_tickets_ticket_type CHECK (ticket_type IN ('incident','service_request')), 
    CONSTRAINT ck_tickets_impact_range CHECK (impact BETWEEN 1 AND 3), 
    CONSTRAINT ck_tickets_urgency_range CHECK (urgency BETWEEN 1 AND 3), 
    CONSTRAINT fk_tickets_assignee_id_users FOREIGN KEY(assignee_id) REFERENCES users (id), 
    CONSTRAINT fk_tickets_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
    CONSTRAINT fk_tickets_closed_by_users FOREIGN KEY(closed_by) REFERENCES users (id), 
    CONSTRAINT fk_tickets_created_by_users FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_tickets_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), 
    CONSTRAINT fk_tickets_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id), 
    CONSTRAINT fk_tickets_priority_id_priorities FOREIGN KEY(priority_id) REFERENCES priorities (id), 
    CONSTRAINT fk_tickets_requester_id_users FOREIGN KEY(requester_id) REFERENCES users (id), 
    CONSTRAINT fk_tickets_status_code_ticket_statuses FOREIGN KEY(status_code) REFERENCES ticket_statuses (code), 
    CONSTRAINT fk_tickets_subcategory_id_subcategories FOREIGN KEY(subcategory_id) REFERENCES subcategories (id), 
    CONSTRAINT fk_tickets_support_group_id_support_groups FOREIGN KEY(support_group_id) REFERENCES support_groups (id), 
    CONSTRAINT uq_tickets_number UNIQUE (number)
);

GO

CREATE INDEX ix_tickets_assignee ON tickets (assignee_id, status_code);

GO

CREATE INDEX ix_tickets_created ON tickets (created_at);

GO

CREATE INDEX ix_tickets_requester ON tickets (requester_id, created_at);

GO

CREATE INDEX ix_tickets_status_group ON tickets (status_code, support_group_id);

GO

CREATE TABLE automation_execution_logs (
    id INTEGER NOT NULL IDENTITY, 
    rule_id INTEGER NULL, 
    ticket_id INTEGER NULL, 
    action NVARCHAR(60) NOT NULL, 
    outcome NVARCHAR(20) NOT NULL, 
    detail NVARCHAR(1000) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_automation_execution_logs PRIMARY KEY (id), 
    CONSTRAINT fk_automation_execution_logs_rule_id_automation_rules FOREIGN KEY(rule_id) REFERENCES automation_rules (id), 
    CONSTRAINT fk_automation_execution_logs_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_automation_execution_logs_ticket_id ON automation_execution_logs (ticket_id);

GO

CREATE TABLE idempotency_keys (
    id INTEGER NOT NULL IDENTITY, 
    user_id INTEGER NOT NULL, 
    [key] NVARCHAR(80) NOT NULL, 
    ticket_id INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_idempotency_keys PRIMARY KEY (id), 
    CONSTRAINT fk_idempotency_keys_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
    CONSTRAINT fk_idempotency_keys_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
    CONSTRAINT uq_idempotency_keys_user_id_key UNIQUE (user_id, [key])
);

GO

CREATE TABLE knowledge_articles (
    id INTEGER NOT NULL IDENTITY, 
    title NVARCHAR(200) NOT NULL, 
    category_id INTEGER NULL, 
    keywords NVARCHAR(400) NULL, 
    problem NVARCHAR(max) NOT NULL, 
    solution NVARCHAR(max) NOT NULL, 
    status NVARCHAR(12) NOT NULL, 
    author_id INTEGER NOT NULL, 
    reviewer_id INTEGER NULL, 
    source_ticket_id INTEGER NULL, 
    version INTEGER NOT NULL, 
    view_count INTEGER NOT NULL, 
    published_at DATETIME2(3) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_knowledge_articles PRIMARY KEY (id), 
    CONSTRAINT ck_knowledge_articles_status CHECK (status IN ('draft','in_review','published','retired')), 
    CONSTRAINT fk_knowledge_articles_author_id_users FOREIGN KEY(author_id) REFERENCES users (id), 
    CONSTRAINT fk_knowledge_articles_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id), 
    CONSTRAINT fk_knowledge_articles_reviewer_id_users FOREIGN KEY(reviewer_id) REFERENCES users (id), 
    CONSTRAINT fk_knowledge_articles_source_ticket_id_tickets FOREIGN KEY(source_ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_kb_status ON knowledge_articles (status, category_id);

GO

CREATE TABLE notifications (
    id INTEGER NOT NULL IDENTITY, 
    user_id INTEGER NOT NULL, 
    ticket_id INTEGER NULL, 
    event NVARCHAR(40) NOT NULL, 
    title NVARCHAR(200) NOT NULL, 
    body NVARCHAR(1000) NULL, 
    link NVARCHAR(200) NULL, 
    dedupe_key NVARCHAR(120) NOT NULL, 
    is_read BIT NOT NULL, 
    email_status NVARCHAR(10) NOT NULL, 
    email_attempts INTEGER NOT NULL, 
    email_last_error NVARCHAR(500) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_notifications PRIMARY KEY (id), 
    CONSTRAINT fk_notifications_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
    CONSTRAINT fk_notifications_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), 
    CONSTRAINT uq_notifications_dedupe_key UNIQUE (dedupe_key)
);

GO

CREATE INDEX ix_notifications_email ON notifications (email_status);

GO

CREATE INDEX ix_notifications_user ON notifications (user_id, is_read, created_at);

GO

CREATE TABLE satisfaction_ratings (
    id INTEGER NOT NULL IDENTITY, 
    ticket_id INTEGER NOT NULL, 
    rating INTEGER NOT NULL, 
    comment NVARCHAR(1000) NULL, 
    rated_by INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_satisfaction_ratings PRIMARY KEY (id), 
    CONSTRAINT ck_satisfaction_ratings_rating_range CHECK (rating BETWEEN 1 AND 5), 
    CONSTRAINT fk_satisfaction_ratings_rated_by_users FOREIGN KEY(rated_by) REFERENCES users (id), 
    CONSTRAINT fk_satisfaction_ratings_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
    CONSTRAINT uq_satisfaction_ratings_ticket_id UNIQUE (ticket_id)
);

GO

CREATE TABLE sla_tracking (
    ticket_id INTEGER NOT NULL, 
    policy_id INTEGER NULL, 
    calendar_id INTEGER NOT NULL, 
    started_at DATETIME2(3) NOT NULL, 
    response_target_minutes INTEGER NOT NULL, 
    resolution_target_minutes INTEGER NOT NULL, 
    warning_percent INTEGER NOT NULL, 
    response_due_at DATETIME2(3) NOT NULL, 
    resolution_due_at DATETIME2(3) NOT NULL, 
    paused_at DATETIME2(3) NULL, 
    paused_minutes INTEGER NOT NULL, 
    response_breached BIT NOT NULL, 
    resolution_breached BIT NOT NULL, 
    warning_sent BIT NOT NULL, 
    escalation_level INTEGER NOT NULL, 
    updated_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_sla_tracking PRIMARY KEY (ticket_id), 
    CONSTRAINT fk_sla_tracking_calendar_id_business_calendars FOREIGN KEY(calendar_id) REFERENCES business_calendars (id), 
    CONSTRAINT fk_sla_tracking_policy_id_sla_policies FOREIGN KEY(policy_id) REFERENCES sla_policies (id), 
    CONSTRAINT fk_sla_tracking_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_sla_tracking_due ON sla_tracking (resolution_due_at, resolution_breached);

GO

CREATE TABLE ticket_assignments (
    id INTEGER NOT NULL IDENTITY, 
    ticket_id INTEGER NOT NULL, 
    support_group_id INTEGER NULL, 
    assignee_id INTEGER NULL, 
    assigned_by INTEGER NULL, 
    method NVARCHAR(20) NOT NULL, 
    reason NVARCHAR(500) NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_ticket_assignments PRIMARY KEY (id), 
    CONSTRAINT fk_ticket_assignments_assigned_by_users FOREIGN KEY(assigned_by) REFERENCES users (id), 
    CONSTRAINT fk_ticket_assignments_assignee_id_users FOREIGN KEY(assignee_id) REFERENCES users (id), 
    CONSTRAINT fk_ticket_assignments_support_group_id_support_groups FOREIGN KEY(support_group_id) REFERENCES support_groups (id), 
    CONSTRAINT fk_ticket_assignments_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_ticket_assignments_ticket_id ON ticket_assignments (ticket_id);

GO

CREATE TABLE ticket_comments (
    id INTEGER NOT NULL IDENTITY, 
    ticket_id INTEGER NOT NULL, 
    author_id INTEGER NOT NULL, 
    body NVARCHAR(max) NOT NULL, 
    is_internal BIT NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_ticket_comments PRIMARY KEY (id), 
    CONSTRAINT fk_ticket_comments_author_id_users FOREIGN KEY(author_id) REFERENCES users (id), 
    CONSTRAINT fk_ticket_comments_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_ticket_comments_ticket ON ticket_comments (ticket_id, created_at);

GO

CREATE TABLE ticket_erp_details (
    ticket_id INTEGER NOT NULL, 
    erp_module NVARCHAR(60) NULL, 
    transaction_type NVARCHAR(80) NULL, 
    reference_no NVARCHAR(80) NULL, 
    company_branch NVARCHAR(120) NULL, 
    error_message NVARCHAR(max) NULL, 
    expected_result NVARCHAR(max) NULL, 
    actual_result NVARCHAR(max) NULL, 
    steps_to_reproduce NVARCHAR(max) NULL, 
    occurred_at DATETIME2(3) NULL, 
    business_impact NVARCHAR(500) NULL, 
    workaround_available BIT NULL, 
    CONSTRAINT pk_ticket_erp_details PRIMARY KEY (ticket_id), 
    CONSTRAINT fk_ticket_erp_details_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_ticket_erp_details_reference_no ON ticket_erp_details (reference_no);

GO

CREATE TABLE ticket_history (
    id INTEGER NOT NULL IDENTITY, 
    ticket_id INTEGER NOT NULL, 
    field NVARCHAR(40) NOT NULL, 
    old_value NVARCHAR(500) NULL, 
    new_value NVARCHAR(500) NULL, 
    reason NVARCHAR(1000) NULL, 
    actor_id INTEGER NULL, 
    is_internal BIT NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_ticket_history PRIMARY KEY (id), 
    CONSTRAINT fk_ticket_history_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id), 
    CONSTRAINT fk_ticket_history_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id)
);

GO

CREATE INDEX ix_ticket_history_ticket ON ticket_history (ticket_id, created_at);

GO

CREATE TABLE ticket_relationships (
    id INTEGER NOT NULL IDENTITY, 
    source_ticket_id INTEGER NOT NULL, 
    target_ticket_id INTEGER NOT NULL, 
    relation_type NVARCHAR(20) NOT NULL, 
    created_by INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_ticket_relationships PRIMARY KEY (id), 
    CONSTRAINT ck_ticket_relationships_relation_type CHECK (relation_type IN ('duplicate_of','related')), 
    CONSTRAINT ck_ticket_relationships_no_self CHECK (source_ticket_id <> target_ticket_id), 
    CONSTRAINT fk_ticket_relationships_created_by_users FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_ticket_relationships_source_ticket_id_tickets FOREIGN KEY(source_ticket_id) REFERENCES tickets (id), 
    CONSTRAINT fk_ticket_relationships_target_ticket_id_tickets FOREIGN KEY(target_ticket_id) REFERENCES tickets (id), 
    CONSTRAINT uq_ticket_relationships_source_ticket_id_target_ticket_id_relation_type UNIQUE (source_ticket_id, target_ticket_id, relation_type)
);

GO

CREATE TABLE ticket_watchers (
    ticket_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    CONSTRAINT pk_ticket_watchers PRIMARY KEY (ticket_id, user_id), 
    CONSTRAINT fk_ticket_watchers_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
    CONSTRAINT fk_ticket_watchers_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)
);

GO

CREATE TABLE knowledge_article_versions (
    id INTEGER NOT NULL IDENTITY, 
    article_id INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    title NVARCHAR(200) NOT NULL, 
    problem NVARCHAR(max) NOT NULL, 
    solution NVARCHAR(max) NOT NULL, 
    edited_by INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_knowledge_article_versions PRIMARY KEY (id), 
    CONSTRAINT fk_knowledge_article_versions_article_id_knowledge_articles FOREIGN KEY(article_id) REFERENCES knowledge_articles (id), 
    CONSTRAINT fk_knowledge_article_versions_edited_by_users FOREIGN KEY(edited_by) REFERENCES users (id)
);

GO

CREATE INDEX ix_knowledge_article_versions_article_id ON knowledge_article_versions (article_id);

GO

CREATE TABLE ticket_attachments (
    id INTEGER NOT NULL IDENTITY, 
    ticket_id INTEGER NOT NULL, 
    comment_id INTEGER NULL, 
    original_name NVARCHAR(255) NOT NULL, 
    stored_name NVARCHAR(64) NOT NULL, 
    content_type NVARCHAR(100) NOT NULL, 
    size_bytes BIGINT NOT NULL, 
    sha256 NVARCHAR(64) NOT NULL, 
    is_internal BIT NOT NULL, 
    uploaded_by INTEGER NOT NULL, 
    created_at DATETIME2(3) NOT NULL, 
    CONSTRAINT pk_ticket_attachments PRIMARY KEY (id), 
    CONSTRAINT fk_ticket_attachments_comment_id_ticket_comments FOREIGN KEY(comment_id) REFERENCES ticket_comments (id), 
    CONSTRAINT fk_ticket_attachments_ticket_id_tickets FOREIGN KEY(ticket_id) REFERENCES tickets (id), 
    CONSTRAINT fk_ticket_attachments_uploaded_by_users FOREIGN KEY(uploaded_by) REFERENCES users (id), 
    CONSTRAINT uq_ticket_attachments_stored_name UNIQUE (stored_name)
);

GO

CREATE INDEX ix_ticket_attachments_ticket_id ON ticket_attachments (ticket_id);

GO

INSERT INTO alembic_version (version_num) OUTPUT inserted.version_num VALUES ('0001_initial');

GO

-- Running upgrade 0001_initial -> 0002_attachment_blobs

CREATE TABLE ticket_attachment_blobs (
    attachment_id INTEGER NOT NULL, 
    data VARBINARY(max) NOT NULL, 
    CONSTRAINT pk_ticket_attachment_blobs PRIMARY KEY (attachment_id), 
    CONSTRAINT fk_ticket_attachment_blobs_attachment_id_ticket_attachments FOREIGN KEY(attachment_id) REFERENCES ticket_attachments (id)
);

GO

UPDATE alembic_version SET version_num='0002_attachment_blobs' WHERE alembic_version.version_num = '0001_initial';

GO

COMMIT;

GO

