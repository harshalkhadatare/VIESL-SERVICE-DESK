# Security checklist

Legend: ✅ implemented & tested · ☑ implemented (configuration/operational) · ⬜ to do before/after go-live

## Authentication & sessions
- ⚠️ **Readable passwords (owner's decision, 22 Oct 2026):** passwords are stored in plain text in `users.password_plain`
  so the database owner can see and edit them; logins are checked against that column. An Argon2id hash is still kept
  in `password_hash`. Anyone with database access can read every password — restrict Neon access, never share the
  connection string, and ask staff not to reuse passwords from other systems. To go back to hashed-only storage, run
  `UPDATE users SET password_plain = NULL;` (logins then use the hash again).
- ✅ Identical error for wrong password vs unknown user
- ✅ Account lockout (5 failures → 15 min) and per-IP login rate limit
- ✅ 15-minute JWT access token held in memory only (never localStorage)
- ✅ Refresh token: random, stored hashed, HttpOnly + SameSite=Strict + path-scoped cookie, rotated on every use, reuse detection revokes the whole family
- ✅ Logout, password change, role change and deactivation revoke sessions
- ✅ Anti-CSRF header required on cookie-authenticated endpoints
- ☑ `COOKIE_SECURE=true` + HSTS in production (enforced at startup)
- ⬜ SSO (Entra ID / OIDC) and MFA — roadmap

## Authorization
- ✅ Server-side permission checks on every endpoint; role/permission data in DB
- ✅ Row-level visibility filter applied to list, detail, search, export, related tickets, attachments, comments, history
- ✅ 404 for unauthorised tickets (no enumeration)
- ✅ Internal notes / internal attachments / root cause hidden from requesters
- ✅ Protected fields cannot be set by clients (`extra="forbid"`), requester identity derived from session
- ✅ Admin cannot remove own admin role or deactivate self

## Input, output & files
- ✅ Pydantic validation with length limits; parameterised queries only (SQLAlchemy)
- ✅ Frontend escapes all interpolated data (`html` tagged template); no `eval`, no inline scripts
- ✅ CSP `script-src 'self'`, `frame-ancestors 'none'`, nosniff, Referrer-Policy, Permissions-Policy
- ✅ Uploads: allow-list + magic-byte check, size limit, random stored names outside web root, sanitised display names, per-ticket file cap
- ✅ Downloads: authorised endpoint, `Content-Disposition: attachment`, `nosniff`, `no-store`; audited
- ✅ CSV export neutralises formula injection (`= + - @` prefixes) and is audited
- ⬜ Antivirus scanning of uploads (e.g. ClamAV/ICAP hook in `services/attachments.py`)

## Data & operations
- ✅ Audit log: sign-in success/failure/lockout, token reuse, role changes, activation, ticket create/status/assign/priority/comment/link, uploads, downloads, exports
- ✅ Logs never contain passwords, tokens or file contents
- ✅ Stack traces never returned to clients; every error carries a request id for log correlation
- ✅ Demo data refused in production; demo users use reserved `demo.example.com` addresses and are flagged
- ☑ Least-privilege SQL login (`deploy/sql/init.sql`), encrypted DB connection
- ☑ Secrets only via environment; `.env*` git-ignored
- ⬜ Shared rate-limit store (Redis) when running multiple instances
- ⬜ Data-retention purge jobs (policy in DEPLOYMENT.md)
- ⬜ External penetration test before go-live
