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
    UPDATE_LOG="${LOGS_DIR}/gallery-dl-update.log"
    echo "Starting background update of gallery-dl; logs at ${UPDATE_LOG}" >&2
    (
        set +e
        echo "$(date --iso-8601=seconds) Updating gallery-dl to the latest version..." >>"${UPDATE_LOG}"
        if /opt/venv/bin/pip install --no-cache-dir --upgrade gallery-dl >>"${UPDATE_LOG}" 2>&1; then
            echo "$(date --iso-8601=seconds) gallery-dl update completed successfully." >>"${UPDATE_LOG}"
        else
            echo "$(date --iso-8601=seconds) Warning: gallery-dl update failed; continuing with existing version." >>"${UPDATE_LOG}"
        fi
    ) &
fi

exec "$@"
