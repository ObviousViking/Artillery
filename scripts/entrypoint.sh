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

SKIP_GALLERY_DL_UPDATE=0
SKIP_REASON=""
if [ "${CI:-}" = "true" ]; then
    SKIP_GALLERY_DL_UPDATE=1
    SKIP_REASON="CI environment"
fi
if [ -n "${DISABLE_GALLERY_DL_AUTOUPDATE:-}" ]; then
    SKIP_GALLERY_DL_UPDATE=1
    if [ -z "$SKIP_REASON" ]; then
        SKIP_REASON="DISABLE_GALLERY_DL_AUTOUPDATE is set"
    else
        SKIP_REASON="${SKIP_REASON}; DISABLE_GALLERY_DL_AUTOUPDATE is set"
    fi
fi

if [ -x /opt/venv/bin/pip ] && [ "$SKIP_GALLERY_DL_UPDATE" -eq 0 ]; then
    UPDATE_LOG="${LOGS_DIR}/gallery-dl-update.log"
    echo "Starting background update of gallery-dl; logs at ${UPDATE_LOG}" >&2
    (
        set +e
        sleep 2
        echo "$(date --iso-8601=seconds) Updating gallery-dl to the latest version..." >>"${UPDATE_LOG}"
        INSTALL_CMD=(/opt/venv/bin/pip install --no-cache-dir --upgrade gallery-dl)
        if command -v nice >/dev/null 2>&1; then
            INSTALL_CMD=(nice -n 10 "${INSTALL_CMD[@]}")
        fi
        if command -v ionice >/dev/null 2>&1; then
            INSTALL_CMD=(ionice -c3 "${INSTALL_CMD[@]}")
        fi
        if "${INSTALL_CMD[@]}" >>"${UPDATE_LOG}" 2>&1; then
            echo "$(date --iso-8601=seconds) gallery-dl update completed successfully." >>"${UPDATE_LOG}"
        else
            echo "$(date --iso-8601=seconds) Warning: gallery-dl update failed; continuing with existing version." >>"${UPDATE_LOG}"
            echo "Warning: gallery-dl update failed; continuing with existing version. See ${UPDATE_LOG} for details." >&2
        fi
    ) &
elif [ "$SKIP_GALLERY_DL_UPDATE" -eq 1 ]; then
    if [ -n "$SKIP_REASON" ]; then
        echo "Skipping gallery-dl auto-update (${SKIP_REASON})." >&2
    else
        echo "Skipping gallery-dl auto-update (disabled via environment)." >&2
    fi
fi

exec "$@"
