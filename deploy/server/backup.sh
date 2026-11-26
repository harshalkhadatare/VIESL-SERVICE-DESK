#!/usr/bin/env bash
# Nightly database backup (includes every ticket, task and attached file).
# Installed by install.sh as /usr/local/bin/servicedesk-backup, run by cron at 02:30.
# Restore:  see docs/SERVER_SETUP.md → "Backups"
set -euo pipefail
DIR=/srv/servicedesk/backups
KEEP_DAYS=14
stamp=$(date +%Y-%m-%d_%H%M)
out="$DIR/servicedesk_$stamp.dump"
sudo -u postgres pg_dump -Fc -Z 6 servicedesk > "$out.part"
mv "$out.part" "$out"
chown servicedesk:servicedesk "$out"; chmod 640 "$out"
find "$DIR" -name 'servicedesk_*.dump' -mtime +$KEEP_DAYS -delete
echo "$(date '+%F %T') backup ok: $out ($(du -h "$out" | cut -f1))"
