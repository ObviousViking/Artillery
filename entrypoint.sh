#!/bin/sh
set -e

log() {
  printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# Unraid-style PUID / PGID
PUID="${PUID:-0}"
PGID="${PGID:-0}"

# Ensure directories exist (Unraid maps these)
: "${TASKS_DIR:=/tasks}"
: "${CONFIG_DIR:=/config}"
: "${DOWNLOADS_DIR:=/downloads}"

mkdir -p "$TASKS_DIR" "$CONFIG_DIR" "$DOWNLOADS_DIR"

log "Updating gallery-dl to latest..."
pip install --no-cache-dir --upgrade gallery-dl

# Decide how we run things: as root or as numeric uid:gid
if [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  APP_USER_SPEC="$PUID:$PGID"
  log "Using PUID=$PUID PGID=$PGID for ownership and processes"

  # Own the mapped directories (best effort)
  chown -R "$PUID:$PGID" "$TASKS_DIR" "$CONFIG_DIR" "$DOWNLOADS_DIR" 2>/dev/null || true
else
  APP_USER_SPEC="root"
  log "PUID/PGID not set (or zero), running as root."
fi

# Setup cron to run scheduler as the chosen user
log "Setting up cron entry for scheduler..."

GOSU_BIN="$(command -v gosu || true)"
PY_BIN="$(command -v python3 || command -v python || true)"

if [ -z "$PY_BIN" ]; then
  log "ERROR: python (python3/python) not found in PATH"
  exit 1
fi

if [ "$APP_USER_SPEC" != "root" ]; then
  if [ -z "$GOSU_BIN" ]; then
    log "ERROR: gosu not found in PATH (needed for non-root PUID/PGID)"
    exit 1
  fi
  CRON_CMD="$GOSU_BIN $APP_USER_SPEC $PY_BIN /app/scheduler.py"
else
  CRON_CMD="$PY_BIN /app/scheduler.py"
fi

# Install crontab with explicit PATH (cron has a minimal environment)
crontab - <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * $CRON_CMD >> /var/log/cron.log 2>&1
EOF

log "Starting cron..."
mkdir -p /var/log
touch /var/log/cron.log

# Start the right cron daemon (varies by base image)
if command -v crond >/dev/null 2>&1; then
  crond
else
  cron
fi

log "Starting web app as $APP_USER_SPEC..."
# Exec gunicorn as the chosen user so it writes files with correct ownership
exec gosu "$APP_USER_SPEC" "$@"
