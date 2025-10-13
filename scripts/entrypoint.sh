#!/bin/bash
set -euo pipefail

CONFIG_DIR="/config"
LOGS_DIR="/logs"
DOWNLOADS_DIR="/downloads"
DIRECTORIES=($CONFIG_DIR $LOGS_DIR $DOWNLOADS_DIR)

for dir in "${DIRECTORIES[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
    fi

    # Attempt to ensure www-data owns the directory for PHP-FPM access
    if id -u www-data >/dev/null 2>&1; then
        chown -R www-data:www-data "$dir" 2>/dev/null || true
    fi

    chmod 0777 "$dir" || true

done

if [ -x /opt/venv/bin/pip ]; then
    echo "Updating gallery-dl to the latest version..."
    if ! /opt/venv/bin/pip install --no-cache-dir --upgrade gallery-dl; then
        echo "Warning: Failed to update gallery-dl; continuing with existing version." >&2
    fi
fi

exec "$@"
