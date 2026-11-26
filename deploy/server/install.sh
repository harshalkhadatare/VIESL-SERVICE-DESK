#!/usr/bin/env bash
# One-time setup of the Service Desk on a fresh Ubuntu 24.04 server.
#
#   sudo bash install.sh
#
# Installs PostgreSQL 16, Python, Nginx and a free HTTPS certificate, creates the database,
# the "servicedesk" service account, the app service and nightly backups.
# Safe to run again: steps that are already done are skipped.
# Full guide: docs/SERVER_SETUP.md
set -euo pipefail

DOMAIN="${DOMAIN:-viesl.co.in}"
REPO_SSH="${REPO_SSH:-git@github.com:harshalkhadatare/VIESL-SERVICE-DESK.git}"
APP_USER=servicedesk
HOME_DIR=/srv/servicedesk
APP_DIR=$HOME_DIR/app
VENV=$HOME_DIR/venv
ENV_DIR=/etc/servicedesk
ENV_FILE=$ENV_DIR/servicedesk.env
DB_NAME=servicedesk
DB_USER=servicedesk

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m    ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m    ! %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo:  sudo bash install.sh"; exit 1; }

# --------------------------------------------------------------------------- 1. packages
say "1/9  Installing packages (PostgreSQL, Python, Nginx, Certbot, firewall)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q postgresql postgresql-contrib python3 python3-venv python3-pip git nginx \
  certbot python3-certbot-nginx ufw curl ca-certificates unattended-upgrades
systemctl enable --now postgresql nginx
ok "packages installed"

# --------------------------------------------------------------------------- 2. service account
say "2/9  Creating the '$APP_USER' service account"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$HOME_DIR" --shell /bin/bash "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$HOME_DIR" "$HOME_DIR/.ssh" "$HOME_DIR/backups"
chmod 700 "$HOME_DIR/.ssh"
ok "account ready ($HOME_DIR)"

# --------------------------------------------------------------------------- 3. GitHub access (read-only deploy key)
say "3/9  GitHub access for the private repository"
KEY=$HOME_DIR/.ssh/github_deploy
if [ ! -f "$KEY" ]; then
  sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -C "servicedesk-server-read" -f "$KEY" >/dev/null
fi
sudo -u "$APP_USER" bash -c "cat > $HOME_DIR/.ssh/config" <<EOF
Host github.com
  IdentityFile $KEY
  IdentitiesOnly yes
EOF
sudo -u "$APP_USER" bash -c "ssh-keyscan -t ed25519 github.com >> $HOME_DIR/.ssh/known_hosts 2>/dev/null; sort -u -o $HOME_DIR/.ssh/known_hosts $HOME_DIR/.ssh/known_hosts"
if [ ! -d "$APP_DIR/.git" ]; then
  until sudo -u "$APP_USER" git ls-remote "$REPO_SSH" >/dev/null 2>&1; do
    echo
    echo "  Add this key on GitHub:  repository → Settings → Deploy keys → Add deploy key"
    echo "  Title: ubuntu-server   ·   leave 'Allow write access' UNTICKED"
    echo
    cat "$KEY.pub"
    echo
    read -r -p "  Press Enter after adding it… " _
  done
  sudo -u "$APP_USER" git clone -q "$REPO_SSH" "$APP_DIR"
fi
ok "code downloaded to $APP_DIR"

# --------------------------------------------------------------------------- 4. Python
say "4/9  Python environment"
[ -d "$VENV" ] || sudo -u "$APP_USER" python3 -m venv "$VENV"
sudo -u "$APP_USER" "$VENV/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
ok "Python packages installed"

# --------------------------------------------------------------------------- 5. database
say "5/9  PostgreSQL database"
mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
  DB_PASS=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
  SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(64))")
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    sudo -u postgres psql -q -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS'"
  else
    sudo -u postgres psql -q -c "ALTER ROLE $DB_USER PASSWORD '$DB_PASS'"
  fi
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres createdb -O "$DB_USER" -E UTF8 "$DB_NAME"
  cat > "$ENV_FILE" <<EOF
# Service Desk settings. Secret — never copy into Git. After editing: sudo systemctl restart servicedesk
APP_ENV=production
SECRET_KEY=$SECRET
COOKIE_SECURE=true
CORS_ORIGINS=https://$DOMAIN,https://www.$DOMAIN
APP_BASE_URL=https://$DOMAIN
DATABASE_URL=postgresql+psycopg://$DB_USER:$DB_PASS@127.0.0.1:5432/$DB_NAME
ATTACHMENT_STORAGE=database
MAX_UPLOAD_MB=10
FRONTEND_DIR=$APP_DIR/frontend
APP_TIMEZONE=Asia/Kolkata
ENABLE_SCHEDULER=true
RUN_JOBS_ON_REQUEST=false

# ---- Email (copy the values you use on Vercel: Settings → Environment Variables)
EMAIL_ENABLED=false
SMTP_HOST=
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_FROM_NAME=VIESL IT Service Desk

# ---- Only for a brand-new empty database (not needed when you copy your data from Neon)
# BOOTSTRAP_ADMIN_EMAIL=
# BOOTSTRAP_ADMIN_PASSWORD=
EOF
fi
chown root:"$APP_USER" "$ENV_DIR" "$ENV_FILE"
chmod 750 "$ENV_DIR"; chmod 640 "$ENV_FILE"
ok "database '$DB_NAME' ready · settings in $ENV_FILE"

# --------------------------------------------------------------------------- 6. tables + app service
say "6/9  Creating tables and the app service"
sudo -u "$APP_USER" bash -c "set -a; . $ENV_FILE; set +a; cd $APP_DIR/backend && $VENV/bin/alembic upgrade head && $VENV/bin/python -m app.seed" >/dev/null 2>&1
install -m 644 "$APP_DIR/deploy/server/servicedesk.service" /etc/systemd/system/servicedesk.service
# the deploy script may restart the app (and nothing else) without a password
echo "$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart servicedesk, /usr/bin/systemctl is-active servicedesk" \
  > /etc/sudoers.d/servicedesk
chmod 440 /etc/sudoers.d/servicedesk
systemctl daemon-reload
systemctl enable --now servicedesk
systemctl restart servicedesk
sleep 3
curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null && ok "app is running" || warn "app did not answer yet — check: journalctl -u servicedesk -n 50"

# --------------------------------------------------------------------------- 7. Nginx + HTTPS
say "7/9  Website on https://$DOMAIN"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/server/nginx.conf" > /etc/nginx/sites-available/servicedesk
ln -sf /etc/nginx/sites-available/servicedesk /etc/nginx/sites-enabled/servicedesk
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx
ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null; ufw --force enable >/dev/null
ok "firewall: only SSH (22) and web (80/443) are open — the database is not reachable from outside"
if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
  if certbot --nginx -n --agree-tos --register-unsafely-without-email --redirect -d "$DOMAIN" -d "www.$DOMAIN"; then
    ok "HTTPS certificate installed (renews automatically)"
  else
    warn "HTTPS certificate failed — the GoDaddy DNS may not point here yet. When it does, run:"
    warn "  sudo certbot --nginx --redirect -d $DOMAIN -d www.$DOMAIN"
  fi
fi

# --------------------------------------------------------------------------- 8. backups
say "8/9  Nightly backups (02:30, kept 14 days)"
install -m 755 "$APP_DIR/deploy/server/backup.sh" /usr/local/bin/servicedesk-backup
echo "30 2 * * * root /usr/local/bin/servicedesk-backup >> /var/log/servicedesk-backup.log 2>&1" > /etc/cron.d/servicedesk-backup
ok "backups go to $HOME_DIR/backups"

# --------------------------------------------------------------------------- 9. auto-deploy key for GitHub Actions
say "9/9  Key for automatic deployment from GitHub"
DKEY=$HOME_DIR/.ssh/actions_deploy
if [ ! -f "$DKEY" ]; then
  sudo -u "$APP_USER" ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f "$DKEY" >/dev/null
  # this key can ONLY run the deploy script — no shell, no forwarding
  echo "command=\"bash $APP_DIR/deploy/server/deploy.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $(cat "$DKEY.pub")" \
    | sudo -u "$APP_USER" tee -a "$HOME_DIR/.ssh/authorized_keys" >/dev/null
  chmod 600 "$HOME_DIR/.ssh/authorized_keys"
fi
cat <<EOF

────────────────────────────────────────────────────────────────────────────
 Done.  Open https://$DOMAIN

 Next (see docs/SERVER_SETUP.md):
  • Email:   sudo nano $ENV_FILE   then   sudo systemctl restart servicedesk
  • Data:    copy your data from Neon (step 5 of the guide)
  • Auto-deploy: GitHub → repository → Settings → Secrets and variables → Actions:
      SERVER_HOST = this server's public IP or $DOMAIN
      SERVER_USER = $APP_USER
      SERVER_SSH_KEY = the private key printed below (copy everything, including the BEGIN/END lines)
────────────────────────────────────────────────────────────────────────────
EOF
echo; cat "$DKEY"; echo
