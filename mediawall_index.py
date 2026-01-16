# mediawall.py
import os
import sqlite3
import shutil
import hashlib
import datetime as dt
from typing import Optional, Tuple, List, Dict

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def _utcnow() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,   -- relative to downloads root
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
        """
    )
    conn.commit()
    return conn


def _extract_relpath_from_log_line(line: str, downloads_root: str) -> Optional[str]:
    """
    Accepts lines like:
      /downloads/site/artist/file.jpg
    Returns:
      site/artist/file.jpg
    """
    s = line.strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    dr = downloads_root.replace("\\", "/").rstrip("/")

    if not (s == dr or s.startswith(dr + "/")):
        return None

    rel = s[len(dr):].lstrip("/")
    if not rel:
        return None

    ext = os.path.splitext(rel)[1].lower()
    if not ext or ext not in MEDIA_EXTS:
        return None

    return rel


def ingest_task_log(
    db_path: str,
    *,
    task_slug: str,
    log_path: str,
    downloads_root: str,
    full_rescan: bool = False,
) -> Dict:
    conn = open_db(db_path)
    try:
        matched, inserted = _ingest_task_log_conn(
            conn,
            task_slug=task_slug,
            log_path=log_path,
            downloads_root=downloads_root,
            full_rescan=full_rescan,
        )
        return {"task": task_slug, "matched": matched, "inserted": inserted}
    finally:
        conn.close()


def _ingest_task_log_conn(
    conn: sqlite3.Connection,
    *,
    task_slug: str,
    log_path: str,
    downloads_root: str,
    full_rescan: bool,
    last_lines: int = 100,
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
            (task_slug, log_path, int(offset), _utcnow()),
        )

    if not data:
        upsert_offset(start_offset)
        conn.commit()
        return (0, 0)

    text = data.decode("utf-8", errors="ignore")
    
    # Only process last N lines to avoid scanning millions of lines
    lines = text.splitlines()
    if len(lines) > last_lines:
        lines = lines[-last_lines:]
    
    now = _utcnow()

    matched = 0
    inserted = 0

    for line in lines:
        rel = _extract_relpath_from_log_line(line, downloads_root)
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
    db_path: str,
    *,
    tasks_root: str,
    downloads_root: str,
    full_rescan: bool = False,
) -> Dict:
    conn = open_db(db_path)
    try:
        tasks_seen = 0
        matched_total = 0
        inserted_total = 0

        if not os.path.isdir(tasks_root):
            return {"tasks_seen": 0, "matched": 0, "inserted": 0}

        for slug in sorted(os.listdir(tasks_root)):
            task_dir = os.path.join(tasks_root, slug)
            if not os.path.isdir(task_dir):
                continue

            log_path = os.path.join(task_dir, "logs.txt")
            if not os.path.exists(log_path):
                continue

            tasks_seen += 1
            matched, inserted = _ingest_task_log_conn(
                conn,
                task_slug=slug,
                log_path=log_path,
                downloads_root=downloads_root,
                full_rescan=full_rescan,
            )
            matched_total += matched
            inserted_total += inserted

        return {"tasks_seen": tasks_seen, "matched": matched_total, "inserted": inserted_total}
    finally:
        conn.close()


def status(db_path: str) -> Dict:
    conn = open_db(db_path)
    try:
        media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        last_ingest = conn.execute("SELECT value FROM meta WHERE key='last_ingest'").fetchone()
        return {
            "media_count": int(media_count),
            "last_ingest": last_ingest[0] if last_ingest else None,
        }
    finally:
        conn.close()


def _cache_name_for_relpath(relpath: str) -> str:
    ext = os.path.splitext(relpath)[1].lower()
    h = hashlib.sha1(relpath.encode("utf-8", errors="ignore")).hexdigest()
    return f"{h}{ext}"


def refresh_cache(
    db_path: str,
    *,
    downloads_root: str,
    cache_dir: str,
    n: int = 60,
    cache_videos: bool = False,
    clean: bool = True,
) -> Dict:
    """
    Pick N random items from DB and copy them into cache_dir.
    Home page should serve ONLY from cache_dir.
    """
    os.makedirs(cache_dir, exist_ok=True)

    conn = open_db(db_path)
    try:
        if cache_videos:
            rows = conn.execute(
                "SELECT path, ext FROM media ORDER BY RANDOM() LIMIT ?",
                (int(n),),
            ).fetchall()
        else:
            # images only
            q = "SELECT path, ext FROM media WHERE ext IN ({}) ORDER BY RANDOM() LIMIT ?".format(
                ",".join(["?"] * len(IMAGE_EXTS))
            )
            rows = conn.execute(q, tuple(sorted(IMAGE_EXTS)) + (int(n),)).fetchall()

        picked = [(r[0], r[1]) for r in rows]

        if clean:
            # keep cache folder small + predictable
            for fn in os.listdir(cache_dir):
                try:
                    os.remove(os.path.join(cache_dir, fn))
                except Exception:
                    pass

        copied = 0
        failed = 0
        for rel, _ext in picked:
            src = os.path.join(downloads_root, rel)
            dst_name = _cache_name_for_relpath(rel)
            dst = os.path.join(cache_dir, dst_name)

            try:
                tmp = dst + ".tmp"
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

        now = _utcnow()
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
    finally:
        conn.close()


def list_cached_files(cache_dir: str, *, limit: int = 60) -> List[str]:
    if not os.path.isdir(cache_dir):
        return []
    files = []
    for fn in os.listdir(cache_dir):
        ext = os.path.splitext(fn)[1].lower()
        if ext in MEDIA_EXTS and not fn.endswith(".tmp"):
            files.append(fn)
    # random-ish order not required; your template rows already shuffle via refresh
    files.sort()
    return files[:limit]
