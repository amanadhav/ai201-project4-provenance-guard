"""
SQLite audit log and data persistence layer.

Schema:
  submissions  — one row per content submission, full decision record
  appeals      — one row per appeal, linked to submissions via content_id
"""

import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "provenance_guard.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't already exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS submissions (
                content_id      TEXT PRIMARY KEY,
                creator_id      TEXT,
                text_excerpt    TEXT,
                text_length     INTEGER,
                llm_score       REAL,
                llm_rationale   TEXT,
                llm_indicators  TEXT,
                style_score     REAL,
                style_sub_scores TEXT,
                ai_probability  REAL,
                confidence      REAL,
                result          TEXT,
                label_variant   TEXT,
                label_text      TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT,
                updated_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS appeals (
                appeal_id       TEXT PRIMARY KEY,
                content_id      TEXT NOT NULL,
                creator_id      TEXT,
                reason          TEXT,
                original_result TEXT,
                original_ai_prob REAL,
                status          TEXT DEFAULT 'under_review',
                created_at      TEXT,
                FOREIGN KEY (content_id) REFERENCES submissions(content_id)
            );
        """)


def log_submission(
    content_id: str,
    creator_id: str | None,
    text: str,
    llm_result: dict,
    style_result: dict,
    score_result: dict,
    label_result: dict,
) -> None:
    """Write a full attribution decision to the audit log."""
    now = datetime.now(timezone.utc).isoformat()
    excerpt = text[:200] + ("..." if len(text) > 200 else "")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                content_id, creator_id, text_excerpt, text_length,
                llm_score, llm_rationale, llm_indicators,
                style_score, style_sub_scores,
                ai_probability, confidence, result,
                label_variant, label_text,
                status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                content_id,
                creator_id,
                excerpt,
                len(text),
                llm_result["score"],
                llm_result.get("rationale", ""),
                json.dumps(llm_result.get("key_indicators", [])),
                style_result["score"],
                json.dumps(style_result.get("sub_scores", {})),
                score_result["ai_probability"],
                score_result["confidence"],
                label_result["result"],
                label_result["variant"],
                label_result["label_text"],
                "analyzed",
                now,
                now,
            ),
        )


def log_appeal(
    appeal_id: str,
    content_id: str,
    creator_id: str | None,
    reason: str,
    original_result: str,
    original_ai_prob: float,
) -> None:
    """Write an appeal record and update the parent submission status."""
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO appeals (
                appeal_id, content_id, creator_id, reason,
                original_result, original_ai_prob, status, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                appeal_id,
                content_id,
                creator_id,
                reason,
                original_result,
                original_ai_prob,
                "under_review",
                now,
            ),
        )
        conn.execute(
            "UPDATE submissions SET status = 'under_review', updated_at = ? WHERE content_id = ?",
            (now, content_id),
        )


def get_submission(content_id: str) -> dict | None:
    """Fetch a submission record by content_id."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE content_id = ?", (content_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["llm_indicators"] = json.loads(d.get("llm_indicators") or "[]")
        d["style_sub_scores"] = json.loads(d.get("style_sub_scores") or "{}")
        return d


def get_appeal_for_submission(content_id: str) -> dict | None:
    """Fetch the most recent appeal for a given submission."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM appeals WHERE content_id = ? ORDER BY created_at DESC LIMIT 1",
            (content_id,),
        ).fetchone()
        return dict(row) if row else None


def get_log(limit: int = 20, offset: int = 0) -> dict:
    """
    Fetch paginated audit log entries (submissions + appeals joined).
    Each entry includes the appeal record if one exists.
    """
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        rows = conn.execute(
            """
            SELECT s.*,
                   a.appeal_id, a.reason AS appeal_reason,
                   a.status AS appeal_status, a.created_at AS appeal_created_at,
                   a.creator_id AS appeal_creator_id
            FROM submissions s
            LEFT JOIN appeals a ON s.content_id = a.content_id
            ORDER BY s.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    entries = []
    for row in rows:
        d = dict(row)
        d["llm_indicators"] = json.loads(d.get("llm_indicators") or "[]")
        d["style_sub_scores"] = json.loads(d.get("style_sub_scores") or "{}")
        appeal = None
        if d.get("appeal_id"):
            appeal = {
                "appeal_id": d.pop("appeal_id"),
                "reason": d.pop("appeal_reason"),
                "status": d.pop("appeal_status"),
                "created_at": d.pop("appeal_created_at"),
                "creator_id": d.pop("appeal_creator_id"),
            }
        else:
            d.pop("appeal_id", None)
            d.pop("appeal_reason", None)
            d.pop("appeal_status", None)
            d.pop("appeal_created_at", None)
            d.pop("appeal_creator_id", None)
        d["appeal"] = appeal
        entries.append(d)

    return {"entries": entries, "total": total, "limit": limit, "offset": offset}
