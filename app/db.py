"""SQLite 데이터 계층.

테이블
- products : 크롤링한 제품 (이미지 경로는 JSON 배열로 저장)
- jobs     : 영상 제작/게시 작업 1건의 상태 추적
- posts    : 인스타 게시 결과 (permalink 등)
- settings : 런타임에 바뀌는 간단한 키-값 (스케줄 on/off 등)

가볍게 쓰기 위해 표준 라이브러리 sqlite3 만 사용한다.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,         -- Cafe24 product_no
    name         TEXT NOT NULL,
    price        TEXT,
    url          TEXT,
    images_json  TEXT NOT NULL DEFAULT '[]',  -- 로컬 다운로드 이미지 경로 배열
    sold_out     INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|copy|clip|compose|upload|publish|done|error
    stage_msg    TEXT,
    caption      TEXT,
    hashtags     TEXT,
    subtitles_json TEXT,
    video_path   TEXT,
    public_url   TEXT,
    error        TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER,
    product_id   INTEGER NOT NULL,
    ig_media_id  TEXT,
    permalink    TEXT,
    created_at   REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ----------------------------- products -----------------------------

def upsert_product(
    product_id: int,
    name: str,
    price: Optional[str],
    url: Optional[str],
    images: List[str],
    sold_out: bool = False,
) -> None:
    now = time.time()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE products
                   SET name=?, price=?, url=?, images_json=?, sold_out=?, updated_at=?
                   WHERE id=?""",
                (name, price, url, json.dumps(images, ensure_ascii=False),
                 int(sold_out), now, product_id),
            )
        else:
            conn.execute(
                """INSERT INTO products
                   (id, name, price, url, images_json, sold_out, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (product_id, name, price, url,
                 json.dumps(images, ensure_ascii=False),
                 int(sold_out), now, now),
            )


def _row_to_product(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["images"] = json.loads(d.pop("images_json") or "[]")
    d["sold_out"] = bool(d["sold_out"])
    return d


def list_products(include_sold_out: bool = True) -> List[Dict[str, Any]]:
    q = "SELECT * FROM products"
    if not include_sold_out:
        q += " WHERE sold_out = 0"
    q += " ORDER BY updated_at DESC"
    with get_conn() as conn:
        return [_row_to_product(r) for r in conn.execute(q).fetchall()]


def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return _row_to_product(row) if row else None


# ----------------------------- jobs -----------------------------

def create_job(product_id: int) -> int:
    now = time.time()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO jobs (product_id, status, created_at, updated_at)
               VALUES (?, 'pending', ?, ?)""",
            (product_id, now, now),
        )
        return int(cur.lastrowid)


def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT j.*, p.name AS product_name
               FROM jobs j LEFT JOIN products p ON p.id = j.product_id
               ORDER BY j.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ----------------------------- posts -----------------------------

def create_post(job_id: Optional[int], product_id: int,
                ig_media_id: str, permalink: Optional[str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO posts (job_id, product_id, ig_media_id, permalink, created_at)
               VALUES (?,?,?,?,?)""",
            (job_id, product_id, ig_media_id, permalink, time.time()),
        )
        return int(cur.lastrowid)


def list_posts(limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT po.*, p.name AS product_name
               FROM posts po LEFT JOIN products p ON p.id = po.product_id
               ORDER BY po.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_posts_last_24h() -> int:
    """Instagram 24시간 100건 제한 가드용."""
    since = time.time() - 24 * 3600
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE created_at >= ?", (since,)
        ).fetchone()
        return int(row["c"])


def next_product_for_rotation() -> Optional[int]:
    """가장 오래전에(또는 아직 한 번도) 게시한 제품을 골라 순환 게시한다."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT p.id
               FROM products p
               LEFT JOIN (
                   SELECT product_id, MAX(created_at) AS last_post
                   FROM posts GROUP BY product_id
               ) lp ON lp.product_id = p.id
               WHERE p.sold_out = 0
               ORDER BY (lp.last_post IS NULL) DESC, lp.last_post ASC, p.id ASC
               LIMIT 1"""
        ).fetchone()
        return int(row["id"]) if row else None


# ----------------------------- app_settings -----------------------------

def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default
