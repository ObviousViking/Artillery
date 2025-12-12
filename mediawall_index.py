# mediawall_index.py
import os
import sqlite3
import datetime as dt
from typing import Iterable, Optional

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp4", ".webm", ".mkv",
}

def _utcnow() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def open_media_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,         -- relative to downloads root
            ext  TEXT NOT NULL,
            task TEXT,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_offsets (
            task TEXT PRIMARY KEY,         -- task slug (folder name)
            log_path TEXT NOT NULL,
            offset INTEGER NOT NULL DEFAULT 0,
            updated TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_ext ON media(ext);
        CREATE INDEX IF NOT EXISTS idx_media_last_seen ON media(last_seen);
        """
    )
    conn.commit()


def ingest_all_task_logs(
    conn: sqlite3.Connection,
    tasks_root: str,
    downloads_root: str,
    *,
    full_rescan: bool = False,
) -> dict:
    """
    Parse /tasks/*/logs.txt and ingest any media paths that begin with downloads_root.
    Uses stored byte offsets for incremental ingestion (unless full_rescan=True).
    """
    tasks_root = os.path.abspath(tasks_root)
    downloads_root = downloads_root.rstrip("/")

    ingested = 0
    tasks_seen = 0

    if not os.path.isdir(tasks_root):
        return {"tasks_seen": 0, "paths_ingested": 0}

    for slug in sorted(os.listdir(tasks_root)):
        task_dir = os.path.join(tasks_root, slug)
        if not os.path.isdir(task_dir):
            continue

        log_path = os.path.join(task_dir, "logs.txt")
        if not os.path.exists(log_path):
            continue

        tasks_seen += 1
        ingested += ingest_task_log(
            conn,
            task_slug=slug,
            log_path=log_path,
            downloads_root=downloads_root,
            full_rescan=full_rescan,
        )

    return {"tasks_seen": tasks_seen, "paths_ingested": ingested}


def ingest_task_log(
    conn: sqlite3.Connection,
    *,
    task_slug: str,
    log_path: str,
    downloads_root: str,
    full_rescan: bool = False,
) -> int:
    """
    Ingest one task's logs.txt, incrementally by default.
    Returns the number of *new unique* paths inserted (not total matches).
    """
    # Determine start offset
    start_offset = 0
    if not full_rescan:
        row = conn.execute(
            "SELECT offset FROM task_offsets WHERE task=? AND log_path=?",
            (task_slug, log_path),
        ).fetchone()
        if row:
            start_offset = int(row[0])

    # Read new bytes only
    try:
        with open(log_path, "rb") as f:
            if start_offset > 0:
                f.seek(start_offset)
            data = f.read()
            end_offset = f.tell()
    except OSError:
        return 0

    if not data:
        # still update offset timestamp so you can see it ran
        _upsert_offset(conn, task_slug, log_path, start_offset)
        return 0

    text = data.decode("utf-8", errors="ignore")
    now = _utcnow()

    new_unique = 0
    for line in text.splitlines():
        rel = _extract_relpath_from_log_line(line, downloads_root)
        if not rel:
            continue

        ext = os.path.splitext(rel)[1].lower()
        if ext not in MEDIA_EXTS:
            continue

        # Insert or update
        cur = conn.execute(
            """
            INSERT INTO media(path, ext, task, first_seen, last_seen, seen_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(path) DO UPDATE SET
                last_seen=excluded.last_seen,
                task=excluded.task,
                ext=excluded.ext,
                seen_count=media.seen_count + 1
            """,
            (rel, ext, task_slug, now, now),
        )
        # sqlite3 doesn't directly tell "insert vs update" reliably; we can detect
        # new unique by trying an INSERT OR IGNORE first, but that doubles work.
        # Instead: treat "new unique" as rows that were absent pre-run is optional.
        # For now, just count matches (or you can change behavior later).
        new_unique += 1

    _upsert_offset(conn, task_slug, log_path, end_offset)
    conn.commit()
    return new_unique


def _upsert_offset(conn: sqlite3.Connection, task_slug: str, log_path: str, offset: int) -> None:
    conn.execute(
        """
        INSERT INTO task_offsets(task, log_path, offset, updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(task) DO UPDATE SET
            log_path=excluded.log_path,
            offset=excluded.offset,
            updated=excluded.updated
        """,
        (task_slug, log_path, int(offset), _utcnow()),
    )


def _extract_relpath_from_log_line(line: str, downloads_root: str) -> Optional[str]:
    """
    Accepts lines like:
      /downloads/site/artist/file.jpg
      /downloads\\site\\artist\\file.jpg   (rare, but handle)
    Returns:
      site/artist/file.jpg
    """
    s = line.strip()
    if not s:
        return None

    # Fast path: must contain the downloads root string
    # (Avoid regex; keep it cheap.)
    if downloads_root not in s:
        return None

    # Find the first occurrence and slice from there
    i = s.find(downloads_root)
    if i < 0:
        return None
    s2 = s[i:]

    # Normalize slashes
    s2 = s2.replace("\\", "/")

    # Ensure it starts with downloads_root as a path segment
    dr = downloads_root.replace("\\", "/").rstrip("/")
    if not (s2 == dr or s2.startswith(dr + "/")):
        return None

    rel = s2[len(dr):].lstrip("/")
    if not rel:
        return None

    # Defensive: ignore weird "directory" lines without an extension
    ext = os.path.splitext(rel)[1].lower()
    if not ext:
        return None

    return rel


def get_random_media_paths(conn: sqlite3.Connection, n: int = 60) -> list[str]:
    rows = conn.execute(
        "SELECT path FROM media ORDER BY RANDOM() LIMIT ?",
        (int(n),)
    ).fetchall()
    return [r[0] for r in rows]
