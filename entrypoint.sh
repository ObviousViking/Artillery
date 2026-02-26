#!/bin/sh
set -e

log() {
  printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# Unraid-style PUID / PGID
PUID="${PUID:-0}"
PGID="${PGID:-0}"
CHOWN_DOWNLOADS="${CHOWN_DOWNLOADS:-0}"

# Ensure directories exist (Unraid maps these)
: "${TASKS_DIR:=/tasks}"
: "${CONFIG_DIR:=/config}"
: "${DOWNLOADS_DIR:=/downloads}"


mkdir -p "$TASKS_DIR" "$CONFIG_DIR" "$DOWNLOADS_DIR"

# Ensure media wall cache is writable (non-critical cache)
mkdir -p "$CONFIG_DIR/media_wall"
chmod 777 "$CONFIG_DIR/media_wall" 2>/dev/null || true

log "Updating gallery-dl to latest..."
pip install --no-cache-dir --upgrade gallery-dl

log "Updating yt-dlp to latest..."
pip install --no-cache-dir --upgrade yt-dlp

log "Ensuring ffmpeg is installed..."
if ! command -v ffmpeg > /dev/null 2>&1; then
  apt-get update -qq && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
else
  log "ffmpeg already present ($(ffmpeg -version 2>&1 | head -1))"
fi

# remove stale lock files from previous container run
find /tasks -maxdepth 2 -type f -iname "*lock*" -print -delete || true


# Decide how we run things: as root or as numeric uid:gid
if [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  APP_USER_SPEC="$PUID:$PGID"
  log "Using PUID=$PUID PGID=$PGID for ownership and processes"

  # Own the mapped directories (best effort)
  chown -R "$PUID:$PGID" "$TASKS_DIR" "$CONFIG_DIR" 2>/dev/null || true
  if [ "$CHOWN_DOWNLOADS" = "1" ]; then
    log "Chowning downloads (may be slow on large libraries)..."
    chown -R "$PUID:$PGID" "$DOWNLOADS_DIR" 2>/dev/null || true
  else
    log "Skipping downloads chown (set CHOWN_DOWNLOADS=1 to enable)"
  fi
else
  APP_USER_SPEC="root"
  log "PUID/PGID not set (or zero), running as root."
fi

# Setup cron to run scheduler as the chosen user
log "Setting up cron entry for scheduler..."
CRON_LINE="* * * * * /usr/local/bin/gosu $APP_USER_SPEC /usr/local/bin/python /app/scheduler.py >> /var/log/cron.log 2>&1"

echo "$CRON_LINE" | crontab -

log "Starting cron..."
touch /var/log/cron.log
cron

log "Starting web app as $APP_USER_SPEC..."
# Exec gunicorn as the chosen user so it writes files with correct ownership
exec gosu "$APP_USER_SPEC" "$@"
