#!/bin/bash
set -euo pipefail

CONFIG_DIR="/config"
LOGS_DIR="/logs"
DOWNLOADS_DIR="/downloads"
TASKS_DIR="/tasks"
DIRECTORIES=($CONFIG_DIR $LOGS_DIR $DOWNLOADS_DIR $TASKS_DIR)

for dir in "${DIRECTORIES[@]}"; do
    mkdir -p "$dir"
    chmod 0777 "$dir" || true
done

# Optionally update gallery-dl on startup. Disabled by default to avoid slow boots
# when the container lacks fast internet access. Set GALLERY_DL_AUTOUPDATE=true to
# opt in. The update runs in the background with a timeout so the web UI becomes
# available immediately even if the upgrade is slow.
if [ "${GALLERY_DL_AUTOUPDATE:-false}" = "true" ] && command -v pip >/dev/null 2>&1; then
    echo "Updating gallery-dl to the latest version in the background..."
    (
        timeout "${GALLERY_DL_AUTOUPDATE_TIMEOUT:-60}s" pip install --no-cache-dir --upgrade gallery-dl \
            && echo "gallery-dl update completed." \
            || echo "Warning: gallery-dl update timed out or failed; continuing with existing version." >&2
    ) &
else
    echo "Skipping gallery-dl auto-update; set GALLERY_DL_AUTOUPDATE=true to enable."
fi

exec "$@"
