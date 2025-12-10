#!/bin/sh
set -e

log() {
  printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# PUID / PGID support (Unraid-style)
PUID="${PUID:-0}"
PGID="${PGID:-0}"
APP_USER="artillery"
APP_GROUP="artillery"

# Ensure directories exist (Unraid maps these)
: "${TASKS_DIR:=/tasks}"
: "${CONFIG_DIR:=/config}"
: "${DOWNLOADS_DIR:=/downloads}"

mkdir -p "$TASKS_DIR" "$CONFIG_DIR" "$DOWNLOADS_DIR"

log "Updating gallery-dl to latest..."
pip install --no-cache-dir --upgrade gallery-dl

# Create user/group if not running as root:root
if [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  log "Configuring user/group: uid=$PUID gid=$PGID"

  # Create group if needed
  if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
    addgroup --gid "$PGID" "$APP_GROUP"
  fi

  # Create user if needed
  if ! id "$APP_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" --uid "$PUID" --gid "$PGID" "$APP_USER"
  fi

  # Own the mapped directories
  chown -R "$PUID:$PGID" "$TASKS_DIR" "$CONFIG_DIR" "$DOWNLOADS_DIR" 2>/dev/null || true
else
  log "PUID/PGID not set (or zero), running as root."
  APP_USER="root"
fi

# Setup cron to run scheduler as the app user
log "Setting up cron entry for scheduler..."
CRON_LINE="* * * * * gosu $APP_USER /usr/local/bin/python /app/scheduler.py >> /var/log/cron.log 2>&1"

echo "$CRON_LINE" | crontab -

log "Starting cron..."
touch /var/log/cron.log
cron

log "Starting web app as $APP_USER..."
# Exec gunicorn as the app user so it writes files as PUID:PGID
exec gosu "$APP_USER" "$@"
