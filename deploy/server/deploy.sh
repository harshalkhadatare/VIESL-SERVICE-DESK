#!/usr/bin/env bash
# Update the running Service Desk to the latest code on GitHub (branch main).
# Run automatically by GitHub Actions after every push, or by hand on the server:
#   sudo -u servicedesk bash /srv/servicedesk/app/deploy/server/deploy.sh
set -euo pipefail
APP_DIR=/srv/servicedesk/app
VENV=/srv/servicedesk/venv
ENV_FILE=/etc/servicedesk/servicedesk.env
LOCK=/srv/servicedesk/.deploy.lock

exec 9>"$LOCK"
flock -n 9 || { echo "Another deployment is running — try again in a minute."; exit 1; }

cd "$APP_DIR"
before=$(git rev-parse --short HEAD)
git fetch -q origin main
git reset -q --hard origin/main
after=$(git rev-parse --short HEAD)
echo "code: $before → $after  ($(git log -1 --format=%s))"

# re-exec the fresh copy of this script if it changed
if [ "${DEPLOY_REEXEC:-}" != 1 ] && ! git diff --quiet "$before" "$after" -- deploy/server/deploy.sh; then
  DEPLOY_REEXEC=1 exec bash "$APP_DIR/deploy/server/deploy.sh"
fi

"$VENV/bin/pip" install -q -r requirements.txt
set -a; . "$ENV_FILE"; set +a
cd backend
"$VENV/bin/alembic" upgrade head
"$VENV/bin/python" -m app.seed >/dev/null
sudo /usr/bin/systemctl restart servicedesk

for i in $(seq 1 20); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/api/v1/health; then
    echo "deployed $after — the site is up"
    exit 0
  fi
  sleep 1
done
echo "The app did not come back after the update. Logs: journalctl -u servicedesk -n 80"
exit 1
