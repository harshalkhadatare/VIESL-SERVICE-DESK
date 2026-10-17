-- One-time database + least-privilege login for the application.
-- The app login can read/write data and run migrations in its own database only.
IF DB_ID('ServiceDesk') IS NULL CREATE DATABASE ServiceDesk;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'sd_app')
    CREATE LOGIN sd_app WITH PASSWORD = '$(APP_DB_PASSWORD)', CHECK_POLICY = ON;
GO
USE ServiceDesk;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'sd_app')
    CREATE USER sd_app FOR LOGIN sd_app;
ALTER ROLE db_datareader ADD MEMBER sd_app;
ALTER ROLE db_datawriter ADD MEMBER sd_app;
ALTER ROLE db_ddladmin  ADD MEMBER sd_app;  -- needed for Alembic migrations; see DEPLOYMENT.md to split
GO
