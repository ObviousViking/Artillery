import os
import sqlite3
import shutil
import threading
import datetime as dt
import hashlib
from typing import Optional, Tuple, Dict, Set

IMAGE_EXTS: Set[str] = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS: Set[str] = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS: Set[str] = IMAGE_EXTS | VIDEO_EXTS

CONFIG_ROOT = os.environ.get("CONFIG_DIR") or "/config"
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR") or "/downloads"

MEDIA_DB = os.path.join(CONFIG_ROOT, "mediawall.sqlite")
MEDIA_WALL_DIR = os.path.join(CONFIG_ROOT, "media_wall")
MEDIA_WALL_DIR_PREV = os.path.join(CONFIG_ROOT, "media_wall_prev")
MEDIA_WALL_DIR_NEXT = os.path.join(CONFIG_ROOT, "media_wall_next")

MEDIA_WALL_REFRESH_LOCK = threading.Lock()

# Throttle refresh to avoid copying many files repeatedly
MEDIA_WALL_MIN_REFRESH_SECONDS = int(os.environ.get("MEDIA_WALL_MIN_REFRESH_SECONDS", "300"))


def utcnow() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "")
        + "Z"
    )


def open_db(db_path: str = MEDIA_DB) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,
            ext  TEXT NOT NULL,
            task TEXT,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_offsets (
            task TEXT PRIMARY KEY,
            log_path TEXT NOT NULL,
            offset INTEGER NOT NULL DEFAULT 0,
            updated TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_ext ON media(ext);
        CREATE INDEX IF NOT EXISTS idx_media_last_seen ON media(last_seen);
        """
    )
    conn.commit()
    return conn


def extract_relpath_from_log_line(line: str, downloads_root: str = DOWNLOADS_ROOT) -> Optional[str]:
    s = line.strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    dr = downloads_root.replace("\\", "/").rstrip("/")

    if not (s == dr or s.startswith(dr + "/")):
        return None

    rel = s[len(dr) :].lstrip("/")
    if not rel:
        return None

    ext = os.path.splitext(rel)[1].lower()
    if not ext or ext not in MEDIA_EXTS:
        return None

    return rel


def ingest_task_log(
    conn: sqlite3.Connection,
    task_slug: str,
    log_path: str,
    *,
    downloads_root: str = DOWNLOADS_ROOT,
    full_rescan: bool = False,
) -> Tuple[int, int]:
    start_offset = 0
    if not full_rescan:
        row = conn.execute(
            "SELECT offset FROM task_offsets WHERE task=? AND log_path=?",
            (task_slug, log_path),
        ).fetchone()
        if row:
            start_offset = int(row[0])

    try:
        with open(log_path, "rb") as f:
            if start_offset > 0:
                f.seek(start_offset)
            data = f.read()
            end_offset = f.tell()
    except OSError:
        return (0, 0)

    def upsert_offset(offset: int) -> None:
        conn.execute(
            """
            INSERT INTO task_offsets(task, log_path, offset, updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(task) DO UPDATE SET
                log_path=excluded.log_path,
                offset=excluded.offset,
                updated=excluded.updated
            """,
            (task_slug, log_path, int(offset), utcnow()),
        )

    if not data:
        upsert_offset(start_offset)
        conn.commit()
        return (0, 0)

    text = data.decode("utf-8", errors="replace")
    now = utcnow()

    matched = 0
    inserted = 0

    for line in text.splitlines():
        rel = extract_relpath_from_log_line(line, downloads_root)
        if not rel:
            continue

        matched += 1
        ext = os.path.splitext(rel)[1].lower()

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO media(path, ext, task, first_seen, last_seen, seen_count)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (rel, ext, task_slug, now, now),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            conn.execute(
                """
                UPDATE media
                SET last_seen=?, task=?, ext=?, seen_count=seen_count + 1
                WHERE path=?
                """,
                (now, task_slug, ext, rel),
            )

    upsert_offset(end_offset)
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES ('last_ingest', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (now,),
    )
    conn.commit()
    return (matched, inserted)


def ingest_all_task_logs(
    conn: sqlite3.Connection,
    *,
    tasks_root: str,
    downloads_root: str = DOWNLOADS_ROOT,
    full_rescan: bool = False,
) -> Dict:
    tasks_seen = 0
    matched_total = 0
    inserted_total = 0

    if not os.path.isdir(tasks_root):
        return {"tasks_seen": 0, "matched": 0, "inserted": 0}

    try:
        entries = list(os.scandir(tasks_root))
    except Exception:
        entries = []

    for entry in sorted(entries, key=lambda e: e.name):
        if not entry.is_dir():
            continue

        slug = entry.name
        task_dir = entry.path
        log_path = os.path.join(task_dir, "logs.txt")
        if not os.path.exists(log_path):
            continue

        tasks_seen += 1
        matched, inserted = ingest_task_log(
            conn,
            slug,
            log_path,
            downloads_root=downloads_root,
            full_rescan=full_rescan,
        )
        matched_total += matched
        inserted_total += inserted

    return {"tasks_seen": tasks_seen, "matched": matched_total, "inserted": inserted_total}


def get_status(conn: sqlite3.Connection) -> Dict:
    media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    def meta(key: str) -> Optional[str]:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    return {
        "media_count": int(media_count),
        "last_ingest": meta("last_ingest"),
        "last_cache_refresh": meta("last_cache_refresh"),
    }


def _cache_name_for_relpath(relpath: str) -> str:
    ext = os.path.splitext(relpath)[1].lower()
    h = hashlib.sha1(relpath.encode("utf-8", errors="ignore")).hexdigest()
    return f"{h}{ext}"


def _clean_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                except Exception:
                    # Best-effort cleanup: ignore errors removing individual files (e.g. races, perms).
                    pass
    except Exception:
        # Best-effort cleanup: ignore errors listing/scanning the directory; failures are non-fatal.
        pass


def should_refresh_cache(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='last_cache_refresh'").fetchone()
        if not row or not row[0]:
            return True
        last = row[0].replace("Z", "")
        last_dt = dt.datetime.fromisoformat(last).replace(tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds()
        return age >= MEDIA_WALL_MIN_REFRESH_SECONDS
    except Exception:
        return True


def refresh_wall_cache(
    conn: sqlite3.Connection,
    n: int,
    *,
    downloads_root: str = DOWNLOADS_ROOT,
    cache_videos: bool = False,
) -> Dict:
    """Atomic refresh:

    - build new cache in MEDIA_WALL_DIR_NEXT
    - rotate MEDIA_WALL_DIR -> PREV
    - swap NEXT -> current
    """
    with MEDIA_WALL_REFRESH_LOCK:
        if cache_videos:
            rows = conn.execute(
                "SELECT path, ext FROM media ORDER BY RANDOM() LIMIT ?",
                (int(n),),
            ).fetchall()
        else:
            q = "SELECT path, ext FROM media WHERE ext IN ({}) ORDER BY RANDOM() LIMIT ?".format(
                ",".join(["?"] * len(IMAGE_EXTS))
            )
            rows = conn.execute(q, tuple(sorted(IMAGE_EXTS)) + (int(n),)).fetchall()

        picked = [(r[0], r[1]) for r in rows]
        if not picked:
            return {"picked": 0, "copied": 0, "failed": 0}

        _clean_dir(MEDIA_WALL_DIR_NEXT)

        copied = 0
        failed = 0
        for rel, _ext in picked:
            src = os.path.join(downloads_root, rel)
            name = _cache_name_for_relpath(rel)
            dst = os.path.join(MEDIA_WALL_DIR_NEXT, name)

            tmp = dst + ".tmp"
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                copied += 1
            except Exception:
                failed += 1
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

        if copied == 0:
            return {"picked": len(picked), "copied": 0, "failed": failed}

        try:
            if os.path.isdir(MEDIA_WALL_DIR_PREV):
                shutil.rmtree(MEDIA_WALL_DIR_PREV)
        except Exception:
            pass

        try:
            if os.path.isdir(MEDIA_WALL_DIR):
                os.replace(MEDIA_WALL_DIR, MEDIA_WALL_DIR_PREV)
        except Exception:
            pass

        os.replace(MEDIA_WALL_DIR_NEXT, MEDIA_WALL_DIR)
        os.makedirs(MEDIA_WALL_DIR_NEXT, exist_ok=True)

        now = utcnow()
        conn.execute(
            """
            INSERT INTO meta(key, value)
            VALUES ('last_cache_refresh', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (now,),
        )
        conn.commit()

        return {"picked": len(picked), "copied": copied, "failed": failed}
