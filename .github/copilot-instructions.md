# Artillery Copilot Instructions

Artillery is a Flask-based UI for managing `gallery-dl` downloads with scheduling, task isolation, and a media wall dashboard. This guide covers critical architectural patterns and workflows.

## Architecture Overview

**Three core processes:**
1. **Flask web server** (`app.py`) - REST API + UI for task management, config editing, media wall
2. **Cron scheduler** (`scheduler.py`) - Runs every minute, checks `cron.txt` files, spawns background task runners
3. **Media wall indexer** (`mediawall_index.py`) - Scans `gallery-dl` logs to catalog downloads into SQLite, caches thumbnails

**Task isolation model:**
- Each task lives in `/tasks/<slug>/` with files: `urls.txt`, `command.txt`, `cron.txt`, `logs.txt`, `name.txt`, `lock`, `paused`
- Lock file (`lock`) indicates task is running; `paused` file means task won't run via cron (manual runs still allowed)
- Gallery-dl config is shared globally at `/config/gallery-dl.conf` (editable via UI)

**Data flows:**
- UI → create task → writes `/tasks/slug/{name.txt,urls.txt,command.txt,cron.txt}`
- Cron triggers → `scheduler.py` detects matching cron.txt → spawns `run_task_background()` thread
- Task execution → gallery-dl outputs to `/downloads/<site>/<artist>/<file>`
- Media wall → parses task logs for file paths → indexes into SQLite → copies latest 100 to `/config/media_wall/` cache

## Key Implementation Patterns

**File-based state (no DB for tasks):**
- Task metadata stored as text files, not database. Use `read_text(path)` and `write_text(path, content)` helpers
- Slugs are derived from task names via `slugify()` (lowercase, hyphens, alphanumeric only)
- Always check for `lock` and `paused` files before state changes

**Subprocess execution (`run_task_background`):**
- Runs in daemon thread; sets `GALLERY_DL_CONFIG` env var pointing to shared config
- Command is parsed with `shlex.split()` to handle quoted args; run from task directory
- All stdout/stderr appended to `logs.txt` with timestamps and exit codes
- **Lock file removed in finally block** to ensure cleanup even on error

**Media wall indexing:**
- Two separate modules: `app.py` has inline SQLite logic, `mediawall_index.py` is standalone for future background workers
- DB schema: `media` table (path, ext, task, first_seen, last_seen, seen_count) + `task_offsets` table (tracks log file offset per task)
- Log ingestion uses file offset to only parse new lines; on task completion, auto-ingests and refreshes cache if throttle allows
- Cache refresh throttled by `MEDIA_WALL_MIN_REFRESH_SECONDS` (default 300s) to avoid copying 100 files per task in rapid succession

**Threading & concurrency:**
- Background task runs in daemon thread (`threading.Thread(..., daemon=True)`)
- Media wall refresh guarded by `MEDIA_WALL_REFRESH_LOCK` to prevent concurrent cache copies
- Cron scheduler runs as separate process (via crontab) every minute; checks for `lock` and `paused` before execution

**Flask routing patterns:**
- `/` (home) - renders media wall dashboard (3 rows of cached images, conditional on `MEDIA_WALL_ENABLED`)
- `/tasks` - GET lists all tasks, POST creates new task
- `/tasks/<slug>/action` - POST for run/pause/delete actions
- `/tasks/<slug>/logs` - GET returns JSON with task log content (used by real-time output viewer)
- `/config` - GET shows editor, POST saves gallery-dl.conf
- `/mediawall/toggle` - POST toggles media wall enabled/disabled
- `/mediawall/refresh` - POST refreshes wall cache
- `/mediawall/seed` - POST rebuilds media index then refreshes cache
- `/mediawall/status` - GET returns media wall status
- `/mediawall/api/cache_index` - returns paginated JSON of cached media
- `/wall/<filename>` - serves cached media files

**Real-time task output viewer:**
- `/tasks/<slug>/logs` endpoint returns JSON: `{"slug": slug, "content": log_text}`
- JavaScript polls every 1 second for live log updates with auto-scroll
- ANSI color parsing via `parseANSIColors()` function maps codes to CSS classes:
  - `1;32` → `.ansi-success` (bright green, bold)
  - `1;31` → `.ansi-error` (bright red, bold)
  - `1;33` → `.ansi-warning` (bright yellow, bold)
  - `1;37` → `.ansi-info` (bright white, bold)
  - `0;37` → `.ansi-debug` (white)
  - `2` → `.ansi-skip` (dim, opacity 0.5)
- Collapsible output panel with task selector dropdown (show/hide button)
- Auto-refresh stops when panel is hidden to reduce polling overhead

## Critical Developer Workflows

**Local development:**
```bash
pip install -r requirements.txt
export TASKS_DIR=/tmp/tasks CONFIG_DIR=/tmp/config DOWNLOADS_DIR=/tmp/downloads
python app.py  # Flask dev server on :5000
```

**Debug mode:**
- `ARTILLERY_LOG_LEVEL=DEBUG` - verbose logging
- `ARTILLERY_DEBUG_REQUESTS=1` - log request timing
- `ARTILLERY_DEBUG_FS=1` - log filesystem operation timing
- `ARTILLERY_HANG_DUMP_SECONDS=30` - dump thread stacks after 30s (signals SIGUSR1)

**Docker build/run:**
- `Dockerfile` installs cron + gosu for process ownership management
- `entrypoint.sh` upgrades gallery-dl, sets up cron scheduler, handles PUID/PGID ownership
- Volume mounts: `/config` (gallery-dl.conf + media_wall cache), `/tasks` (task folders), `/downloads` (final output)

**Testing gallery-dl command:**
- Before saving task, verify command locally: `gallery-dl --help` shows all flags
- Common: `--input-file urls.txt` (read URLs from file), `-o setting=value` (inline config), `--archive archive.sqlite3` (avoid re-downloads)
- Test with `GALLERY_DL_CONFIG=/path/to/config gallery-dl [args]` to verify config loading

**Debugging media wall issues:**
- Check SQLite DB: `sqlite3 /config/mediawall.sqlite3 "SELECT COUNT(*) FROM media; SELECT * FROM task_offsets;"`
- Verify cache directory: `ls -la /config/media_wall/` - should contain symlinks or copies of recent media
- Check task offset tracking: `task_offsets` table shows last parsed byte position in each task's log
- If re-indexing needed: `DELETE FROM task_offsets WHERE task='<slug>'` then trigger refresh button
- Media wall can be toggled on/off via `/config` page - set `MEDIA_WALL_ENABLED` environment variable or use toggle button
- When disabled, media wall section is completely hidden from home page and no indexing occurs

## Project-Specific Conventions

**Environment variables:**
- `TASKS_DIR`, `CONFIG_DIR`, `DOWNLOADS_DIR` - mount points (default: /tasks, /config, /downloads)
- `ARTILLERY_LOG_LEVEL` - logging level (default: INFO)
- `MEDIA_WALL_ENABLED` - enable/disable media wall feature (default: 1)
- `MEDIA_WALL_ITEMS` - items per row on dashboard (default: 45)
- `MEDIA_WALL_COPY_LIMIT` - max files to cache after task completion (default: 100)
- `MEDIA_WALL_AUTO_INGEST_ON_TASK_END` - auto-parse logs on completion (default: 1)
- `MEDIA_WALL_CACHE_VIDEOS` - cache video files in media wall (default: 0)
- `MEDIA_WALL_MIN_REFRESH_SECONDS` - throttle media wall refresh interval (default: 300)
- `PUID`/`PGID` - Unraid-style numeric uid:gid for file ownership (Docker only)

**File encoding:**
- All text files UTF-8 with error='replace' fallback for corrupted logs

**Media detection:**
- Images: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
- Videos: `.mp4`, `.webm`, `.mkv` (optional caching via `MEDIA_WALL_CACHE_VIDEOS`)
- Media wall only indexes files it recognizes

**Cron expressions:**
- Standard crontab format: `0 2 * * *` (2am daily), `*/15 * * * *` (every 15min)
- Validated via `croniter.match()` - matches per minute precision
- Empty or invalid cron → task won't schedule (manual run still works)

## Common Issues & Debugging

**Task won't run:**
1. Check `paused` file exists → delete it
2. Check `lock` file stuck (previous crash) → delete it via UI or manually
3. Check `urls.txt` exists and isn't empty
4. Check `command.txt` is valid gallery-dl command
5. Verify config: `GALLERY_DL_CONFIG=/config/gallery-dl.conf gallery-dl --help` succeeds

**Media wall empty:**
1. Verify `/downloads` has actual files (not just directories)
2. Check task logs for file paths: `cat /tasks/<slug>/logs.txt | grep /downloads`
3. Inspect DB: media table should show entries with valid task names
4. Trigger `/mediawall/rebuild` to force full rescan

**Permission issues (Docker):**
- If files owned by wrong user, check PUID/PGID environment variables match host
- `entrypoint.sh` chowns directories on startup - verify in logs

**Slow media wall refresh:**
- Copying 100 files is throttled by `MEDIA_WALL_MIN_REFRESH_SECONDS` - tune if needed
- Check disk I/O on `/config/media_wall/` - cache should be on fast storage
