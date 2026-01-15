# Artillery Copilot Instructions

Artillery is a Flask-based UI for managing `gallery-dl` downloads with scheduling, task isolation, and a media wall dashboard. This guide covers critical architectural patterns and workflows.

**Last Updated:** January 2026  
**Current Version:** With validated Config system, media wall state persistence, and security hardening

## Architecture Overview

**Three core processes:**
1. **Flask web server** (`app.py`) - REST API + UI for task management, config editing, media wall
   - Uses `config.py` for centralized configuration management with validation
   - Loads settings on startup and validates all paths are writable
2. **Cron scheduler** (`scheduler.py`) - Runs every minute via crontab, checks `cron.txt` files, spawns background task runners
3. **Media wall system** (`mediawall_runtime.py`) - Scans `gallery-dl` logs to catalog downloads into SQLite, caches thumbnails
   - Now supports state persistence for media wall enabled/disabled setting

**Task isolation model:**
- Each task lives in `/tasks/<slug>/` with files: `urls.txt`, `command.txt`, `cron.txt`, `logs/run_*.log`, `logs.txt`, `name.txt`, `lock`, `paused`, `pid` (when running)
- Lock file (`lock`) indicates task is running; `paused` file means task is halted (process stopped via SIGSTOP) and won't run via cron
- PID file (`pid`) stores the process group ID for signal delivery (cancel, pause, resume)
- Gallery-dl config is shared globally at `/config/gallery-dl.conf` (editable via UI)
- Status logic: if paused file exists, show "paused" even if locked; otherwise if locked show "running"; else "idle"

**Data flows:**
- UI → create task → writes `/tasks/slug/{name.txt,urls.txt,command.txt,cron.txt}`
- Cron triggers → `scheduler.py` detects matching cron.txt → spawns `run_task_background()` thread
- Task execution → gallery-dl outputs to `/downloads/<site>/<artist>/<file>`
- Media wall → parses task logs for file paths → indexes into SQLite → copies latest 100 to `/config/media_wall/` cache

## Key Implementation Patterns

**Configuration Management (NEW in Jan 2026):**
- `config.py` provides centralized `Config` dataclass with all settings validated on startup
- All environment variables validated with type checking and bounds:
  - Directories: created if missing, verified writable
  - Integers: checked against min/max bounds (e.g., `MEDIA_WALL_ITEMS` 1-500)
  - Booleans: accepts "1/0", "true/false", "yes/no", "on/off"
- `Config.from_env()` called at app startup (line 31 in app.py) - exits with error on misconfiguration
- Directory validation also performed in `entrypoint.sh` before app starts
- Falls back gracefully if validation fails with clear error messages

**File-based state (no DB for tasks):**
- Task metadata stored as text files, not database. Use `read_text(path)` and `write_text(path, content)` helpers
- Slugs are derived from task names via `slugify()` (lowercase, hyphens, alphanumeric only)
- Always check for `lock` and `paused` files before state changes

**Subprocess execution (`run_task_background`):**
- Runs in daemon thread; sets `GALLERY_DL_CONFIG` env var pointing to shared config
- Command is parsed with `shlex.split()` to handle quoted args; run from task directory
- Subprocess started with `Popen` and `start_new_session=True` to allow process group signaling
- PID recorded immediately in task folder and tracked in `RUNNING_PROCS` dict for cancel/pause/resume
- Per-run log created at `/tasks/<slug>/logs/run_YYYYMMDD_HHMMSS.log`; stdout/stderr written directly
- Task output then appended to main `logs.txt` after completion
- **Lock file and PID file cleaned up in finally block** to ensure cleanup even on error or cancellation

**Media wall indexing:**
- Single integrated module `mediawall_runtime.py` handles all SQLite logic
- DB schema: `media` table (path, ext, task, first_seen, last_seen, seen_count) + `task_offsets` table (tracks log file offset per task)
- Log ingestion uses file offset to only parse new lines; on task completion, auto-ingests and refreshes cache if throttle allows
- Cache refresh throttled by `MEDIA_WALL_MIN_REFRESH_SECONDS` (default 300s) to avoid copying 100 files per task in rapid succession

**Media wall state persistence (NEW in Jan 2026):**
- Media wall enabled/disabled state now persists to `artillery.conf` (no longer lost on restart)
- `/mediawall/toggle` endpoint saves state to disk via `save_artillery_config()`
- On app startup, persisted state loaded from file via `load_artillery_config()`
- Backward compatible: falls back to `MEDIA_WALL_ENABLED` environment variable if no saved config exists
- Config file format: `media_wall_enabled=true` or `media_wall_enabled=false`

**Security hardening (Jan 2026):**
- Uses `secrets.compare_digest()` for constant-time password comparison (prevents timing attacks)
- Atomic file writes with `.tmp` files and `os.sync()` to prevent corruption
- HTML/ANSI escaping for safe log display
- Secure redirect validation with `_is_safe_redirect()`

**Threading & concurrency:**
- Background task runs in daemon thread (`threading.Thread(..., daemon=True)`)
- Media wall refresh guarded by `MEDIA_WALL_REFRESH_LOCK` to prevent concurrent cache copies
- Cron scheduler runs as separate process (via crontab) every minute; checks for `lock` and `paused` before execution
- Process group signaling used for clean task termination: SIGINT → SIGTERM → SIGKILL escalation

**Flask routing patterns:**
- `/login` - GET displays login page with animated FSS background; POST authenticates user (if `ARTILLERY_AUTH_ENABLED=1`)
- `/logout` - POST clears session and redirects to login
- `/` (home) - renders media wall dashboard (3 rows of cached images, conditional on `MEDIA_WALL_ENABLED`)
- `/tasks` - GET lists all tasks, POST creates new task
- `/tasks/<slug>/action` - POST for run/cancel/pause/delete actions (cancel sends SIGINT, pause sends SIGSTOP)
- `/tasks/<slug>/logs` - GET returns JSON with task log content (used by real-time output viewer)
- `/config` - GET shows editor + media wall controls, POST saves gallery-dl.conf or handles config actions
- `/mediawall/toggle` - POST toggles media wall and persists state to `artillery.conf`
- `/mediawall/refresh` - POST refreshes wall cache
- `/mediawall/seed` - POST rebuilds media index then refreshes cache
- `/mediawall/status` - GET returns media wall status
- `/mediawall/api/cache_index` - returns paginated JSON of cached media
- `/wall/<filename>` - serves cached media files

**Authentication & Login:**
- Login page (`templates/login.html`) displays only when `ARTILLERY_AUTH_ENABLED=1` (default: enabled)
- Login page background uses FSS-style animated visualization (`static/js/login_fss.js`) - GPU-accelerated WebGL canvas animation
- Password authentication uses `secrets.compare_digest()` for constant-time comparison (prevents timing attacks)
- Session stored in Flask session cookie (secured by `SECRET_KEY` environment variable)
- `/login` GET endpoint redirects to home if already authenticated (session exists)
- `/login` POST endpoint compares submitted password against `ARTILLERY_AUTH_PASSWORD` hash:
  - Uses `passlib.context` with `crypt_context` for hashing
  - Hash format: `sha256_crypt$2b$12$...` (bcrypt compatible)
  - Constant-time comparison prevents attackers from inferring password through response timing
  - Sets session `user_authenticated=True` on success
  - Flashes error message on incorrect password
- `/logout` POST endpoint clears session and flashes logout message
- All routes except `/login` require valid session or redirect to login page
- `@require_login` decorator wraps endpoints that need authentication
- Password can be regenerated via environment variable or changed in UI (if future feature added)

**Real-time task output viewer:**
- Located on `/tasks` page as a collapsible "Output" card panel below the task table
- `/tasks/<slug>/logs` endpoint returns JSON: `{"slug": slug, "content": log_text}`
- Server-side: strips ANSI escape sequences (regex: `\x1b\[[0-9;]*[A-Za-z]`) so only text + color formatting remain
- Client-side: `stripAnsi()` and `escapeHtml()` ensure safe HTML rendering; `parseLogColors()` re-applies CSS color classes
- Log level pattern parsing via `parseLogColors()` function maps log level tags to CSS classes:
  - `[warning]` → `.log-warning` (yellow, bold)
  - `[error]` → `.log-error` (red, bold)
  - `[success]` → `.log-success` (green, bold)
  - `[info]` → `.log-info` (white, bold)
  - `[debug]` → `.log-debug` (light gray, bold)
- JavaScript polls every 1 second for live log updates with auto-scroll
- Collapsible output panel with task selector dropdown (Show/Hide button)
- Auto-refresh stops when panel is hidden to reduce polling overhead
- Auto-scroll pauses when user manually scrolls up; resumes on down scroll
- Respects carriage returns (`\r`) in logs for progress line updates

## Critical Developer Workflows

**Local development:**
```bash
pip install -r requirements.txt
export TASKS_DIR=/tmp/tasks CONFIG_DIR=/tmp/config DOWNLOADS_DIR=/tmp/downloads
python app.py  # Flask dev server on :5000
```

**Config system initialization:**
- `Config.from_env()` is called at app startup (line 31 in app.py)
- All environment variables are validated during this call with type checking and bounds validation
- Invalid configuration causes app to exit immediately with detailed error message
- Validation includes:
  - Directory existence and write permissions (auto-creates if missing)
  - Integer bounds (e.g., MEDIA_WALL_ITEMS 1-500, MEDIA_WALL_COPY_LIMIT 1-1000)
  - Boolean parsing (accepts "1/0", "true/false", "yes/no", "on/off")
  - Logging level validation (must be valid Python logging module level)
- Example: to validate before running: `python -c "from config import Config; Config.from_env()"`
- To modify config: update environment variables then restart app (or container in Docker)

**Debug mode:**
- `ARTILLERY_LOG_LEVEL=DEBUG` - verbose logging (set before starting app)
- `ARTILLERY_DEBUG_REQUESTS=1` - log request timing
- `ARTILLERY_DEBUG_FS=1` - log filesystem operation timing
- `ARTILLERY_HANG_DUMP_SECONDS=30` - dump thread stacks after 30s (signals SIGUSR1)

**Docker build/run:**
- `Dockerfile` installs cron + gosu for process ownership management
- `entrypoint.sh` upgrades gallery-dl, validates directories, sets up cron scheduler, handles PUID/PGID ownership
  - Performs directory validation before app starts (exits if any directory is not writable)
  - Logs configuration to console for debugging
- Volume mounts: `/config` (gallery-dl.conf + media_wall cache + artillery.conf), `/tasks` (task folders), `/downloads` (final output)

**Testing gallery-dl command:**
- Before saving task, verify command locally: `gallery-dl --help` shows all flags
- Common: `--input-file urls.txt` (read URLs from file), `-o setting=value` (inline config), `--archive archive.sqlite3` (avoid re-downloads)
- Test with `GALLERY_DL_CONFIG=/path/to/config gallery-dl [args]` to verify config loading

**Debugging media wall issues:**
- Check SQLite DB: `sqlite3 /config/mediawall.sqlite3 "SELECT COUNT(*) FROM media; SELECT * FROM task_offsets;"`
- Verify cache directory: `ls -la /config/media_wall/` - should contain symlinks or copies of recent media
- Check task offset tracking: `task_offsets` table shows last parsed byte position in each task's log
- If re-indexing needed: `DELETE FROM task_offsets WHERE task='<slug>'` then trigger refresh button
- Media wall can be toggled on/off via `/config` page - there's a dedicated "Media wall" card section with:
  - Toggle button that shows "Media wall enabled" (green) or "Media wall disabled" (outline) based on current state
  - "Refresh media wall" button (only visible when enabled) that triggers `/mediawall/seed` endpoint
- The toggle button calls `/mediawall/toggle` endpoint which updates the global `MEDIA_WALL_ENABLED` flag AND persists the state to `artillery.conf`
- When disabled, media wall section is completely hidden from home page and no indexing occurs
- Media wall controls are located below the gallery-dl config editor on the config page

## Project-Specific Conventions

**Environment variables (all validated on startup via config.py):**
- `TASKS_DIR` - path to task folders (default: /tasks; must be writable; auto-created if missing)
- `CONFIG_DIR` - path to gallery-dl.conf and media_wall cache (default: /config; must be writable; auto-created if missing)
- `DOWNLOADS_DIR` - path to final gallery-dl output (default: /downloads; must be writable; auto-created if missing)
- `SECRET_KEY` - Flask session secret (default: generated randomly on each startup; set to string for persistence)
- `ARTILLERY_LOG_LEVEL` - logging verbosity (default: INFO; valid: DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `MEDIA_WALL_ENABLED` - enable/disable media wall feature (default: 1; accepts: 1/0, true/false, yes/no, on/off; note: overridden by persisted state in artillery.conf if present)
- `MEDIA_WALL_ITEMS` - items per row on dashboard (default: 45; validated: 1-500)
- `MEDIA_WALL_COPY_LIMIT` - max files to cache per task (default: 100; validated: 1-1000)
- `MEDIA_WALL_AUTO_INGEST_ON_TASK_END` - auto-parse logs on task completion (default: 1; accepts: 1/0, true/false, yes/no, on/off)
- `MEDIA_WALL_CACHE_VIDEOS` - cache video files in media wall (default: 0; accepts: 1/0, true/false, yes/no, on/off)
- `MEDIA_WALL_MIN_REFRESH_SECONDS` - throttle media wall refresh interval (default: 300; validated: >= 0)
- `ARTILLERY_AUTH_ENABLED` - require password for web UI (default: 1; accepts: 1/0, true/false, yes/no, on/off)
- `ARTILLERY_AUTH_PASSWORD` - password hash for authentication (default: auto-generated; format: `sha256_crypt$2b$12$...$`)
- `ARTILLERY_DEBUG_REQUESTS` - log request timing (default: 0; accepts: 1/0, true/false, yes/no, on/off)
- `ARTILLERY_DEBUG_FS` - log filesystem operation timing (default: 0; accepts: 1/0, true/false, yes/no, on/off)
- `ARTILLERY_HANG_DUMP_SECONDS` - dump thread stacks after N seconds (default: 0; validated: >= 0; sends SIGUSR1 to trigger dump)
- `PUID` - numeric UID for file ownership (Docker only; handled by entrypoint.sh with gosu)
- `PGID` - numeric GID for file ownership (Docker only; handled by entrypoint.sh with gosu)

**Configuration persistence:**
- `artillery.conf` stored in CONFIG_DIR: INI-style file with `media_wall_enabled=true/false` setting
- Persisted by `/mediawall/toggle` endpoint, loaded at app startup
- Falls back to `MEDIA_WALL_ENABLED` environment variable if file doesn't exist (backward compatible)
- Format: single setting per line, `key=value` style

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
1. Check `paused` file exists → unpause via UI or delete manually
2. Check `lock` file stuck (previous crash) → UI now auto-detects stale lock on Run attempt and clears it
3. Check `pid` file exists but process is gone → UI pause/cancel/run actions clean up stale state automatically
4. Check `urls.txt` exists and isn't empty
5. Check `command.txt` is valid gallery-dl command
6. Verify config: `GALLERY_DL_CONFIG=/config/gallery-dl.conf gallery-dl --help` succeeds

**Cancel not stopping task:**
- Cancel uses SIGINT first, then escalates to SIGTERM, then SIGKILL if needed
- After cancel, lock/pid are always cleaned up so task can run again
- For stuck processes: check `ps aux | grep gallery-dl` and `ps -o pgrp= -p <pid>` to verify process group

**Pause/resume not working:**
- Pause sends SIGSTOP to process group (halts execution)
- Resume sends SIGCONT to process group (resumes from checkpoint)
- If process not responding, pause/resume actions now detect stale state and clear lock
- Paused processes still hold file locks (expected); unpause or cancel to release

**Media wall empty:**
1. Verify `/downloads` has actual files (not just directories)
2. Check task logs for file paths: `cat /tasks/<slug>/logs.txt | grep /downloads`
3. Inspect DB: media table should show entries with valid task names
4. Trigger `/mediawall/seed` to force full rescan

**Media wall not persisting enabled/disabled state:**
- Verify `artillery.conf` exists in CONFIG_DIR (default: /config)
- Check file contains: `media_wall_enabled=true` or `media_wall_enabled=false`
- Restart app: should load persisted state from file
- If file doesn't exist, falls back to `MEDIA_WALL_ENABLED` environment variable (backward compatible)
- After first toggle via UI, `artillery.conf` file is created automatically

**Config validation error on startup:**
- App exits with code 1 and detailed error message if any validation fails
- Common issues:
  - Directory path doesn't exist and can't be created (parent dir missing)
  - Directory not writable (permission denied)
  - Integer out of bounds (e.g., MEDIA_WALL_ITEMS=501 when max is 500)
  - Invalid logging level (must be DEBUG/INFO/WARNING/ERROR/CRITICAL)
  - Boolean value not recognized (use 1/0, true/false, yes/no, on/off)
- Solution: Fix environment variables and restart app
- Verify before running: `python -c "from config import Config; Config.from_env()"`

**Permission issues (Docker):**
- If files owned by wrong user, check PUID/PGID environment variables match host
- `entrypoint.sh` chowns directories on startup - verify in logs

**Slow media wall refresh:**
- Copying 100 files is throttled by `MEDIA_WALL_MIN_REFRESH_SECONDS` - tune if needed
- Check disk I/O on `/config/media_wall/` - cache should be on fast storage
