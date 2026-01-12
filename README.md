# Artillery

Artillery is a simple web UI for [`gallery-dl`](https://github.com/mikf/gallery-dl).

It lets you:

* Create repeatable download tasks
* Schedule them with cron
* Run them on demand
* Keep everything isolated per-task
* Browse your latest downloads via an animated media wall

All wrapped in a dark, minimal interface designed to live inside Docker/Unraid.

---

## Features

* Task management

  * Create/edit named tasks
  * Each task has:

    * URL list (`urls.txt`)
    * Custom `gallery-dl` command
    * Optional cron schedule
    * Per-task logs (`logs.txt`)
* Per-task isolation

  * Each task gets its own folder under `/tasks/<task-slug>`
  * Stores name, URLs, cron, command, logs, last run, archive, pause/lock state, etc.
* Global gallery-dl config

  * Single `gallery-dl.conf` shared across all tasks
  * Editable from the UI
  * Button to “Load default from GitHub”
* Scheduling

  * Cron-based scheduler runs inside the container
  * Cron expressions per task (`* * * * *`, `*/5 * * * *`, etc.)
  * Tasks can be:

    * Run manually
    * Paused/unpaused
    * Run automatically by cron
* Logging

  * Each run creates a timestamped log file at `/tasks/<slug>/logs/run_YYYYMMDD_HHMMSS.log`
  * Main `logs.txt` accumulates all runs after completion
  * ANSI escape sequences stripped for clean display in UI (only color formatting retained)
  * Real-time log viewer with auto-scroll, level-based coloring, and manual pause support
  * Includes command line + exit code info
* Media wall dashboard

  * Home page shows a 3-row animated wall of recent downloads from `/downloads`
  * Rows scroll alternately left/right
  * Handles huge libraries by only scanning the most recently active directories
* Docker/Unraid-friendly

  * Runs under `gunicorn`
  * Uses `PUID` / `PGID` for proper file ownership on the host
  * Uses `/config`, `/tasks`, `/downloads` as primary mount points
  * Automatically updates `gallery-dl` on container start

---

## Interface

### Dashboard

* Welcome panel explaining how Artillery and gallery-dl fit together
* 3-row animated media wall:

  * Recent images (and basic video placeholders) from `/downloads`
  * Smooth scrolling rows, alternating direction per row

![Artillery Home](screenshots/home.png)

### Tasks

* Table of tasks showing:

  * Name
  * Status (idle / running / paused)
  * Cron expression
  * Last run time
  * Actions (Run, Cancel, Pause/Unpause, Edit, Delete)
* Task editor:

  * Task name
  * URL list (one URL per line)
  * Cron schedule
  * Command builder for common flags (input file, archive, metadata, etc.)
  * Raw command text area for advanced users

![Artillery Tasks](screenshots/tasks.png)

### Config

* A simple editor for `gallery-dl.conf`
* Buttons:

  * Save – write your changes
  * Load default from GitHub – fetches the example config from the official gallery-dl repo

![Artillery Config](screenshots/config.png)

---

## Example docker run

```bash
docker run -d \
  --name artillery \
  -p 8088:80 \
  -e TASKS_DIR=/tasks \
  -e CONFIG_DIR=/config \
  -e DOWNLOADS_DIR=/downloads \
  -e PUID=99 \
  -e PGID=100 \
  -v /mnt/user/appdata/artillery/config:/config \
  -v /mnt/user/appdata/artillery/tasks:/tasks \
  -v /mnt/user/pictures:/downloads \
  obviousviking/artillery
```
