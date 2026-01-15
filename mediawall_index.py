"""Standalone media wall indexer.

This file remains as a compatibility layer for older callers while
delegating the core DB/schema/ingest logic to `mediawall_runtime.py`.
"""

import os
import sqlite3
import shutil
from typing import List, Dict

import mediawall_runtime as mw

IMAGE_EXTS = mw.IMAGE_EXTS
VIDEO_EXTS = mw.VIDEO_EXTS
MEDIA_EXTS = mw.MEDIA_EXTS


def _utcnow() -> str:
    return mw.utcnow()


def open_db(db_path: str) -> sqlite3.Connection:
    return mw.open_db(db_path)


def _extract_relpath_from_log_line(line: str, downloads_root: str):
    return mw.extract_relpath_from_log_line(line, downloads_root)


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
        matched, inserted = mw.ingest_task_log(
            conn,
            task_slug,
            log_path,
            downloads_root=downloads_root,
            full_rescan=full_rescan,
        )
        return {"task": task_slug, "matched": matched, "inserted": inserted}
    finally:
        conn.close()


def ingest_all_task_logs(
    db_path: str,
    *,
    tasks_root: str,
    downloads_root: str,
    full_rescan: bool = False,
) -> Dict:
    conn = open_db(db_path)
    try:
        return mw.ingest_all_task_logs(
            conn,
            tasks_root=tasks_root,
            downloads_root=downloads_root,
            full_rescan=full_rescan,
        )
    finally:
        conn.close()


def status(db_path: str) -> Dict:
    conn = open_db(db_path)
    try:
        s = mw.get_status(conn)
        # Preserve historical output shape.
        return {"media_count": s.get("media_count", 0), "last_ingest": s.get("last_ingest")}
    finally:
        conn.close()


def _cache_name_for_relpath(relpath: str) -> str:
    return mw._cache_name_for_relpath(relpath)


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
            try:
                for entry in os.scandir(cache_dir):
                    if entry.is_file():
                        try:
                            os.remove(entry.path)
                        except Exception:
                            pass
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
