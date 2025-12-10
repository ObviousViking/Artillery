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

# Keep gallery-dl current if available in the image
if command -v pip >/dev/null 2>&1; then
    echo "Updating gallery-dl to the latest version..."
    if ! pip install --no-cache-dir --upgrade gallery-dl; then
        echo "Warning: Failed to update gallery-dl; continuing with existing version." >&2
    fi
else
    echo "Skipping gallery-dl auto-update; set GALLERY_DL_AUTOUPDATE=true to enable."
fi

exec "$@"
