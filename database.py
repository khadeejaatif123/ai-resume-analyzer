import sqlite3
import uuid
import json
from datetime import datetime, timezone
from config import DATABASE_PATH, ROLE_TAXONOMY


def get_db():
    """Return a new SQLite connection with row_factory set."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and seed the role taxonomy if empty."""
    conn = get_db()
    cur = conn.cursor()

    # candidates
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id         TEXT PRIMARY KEY,
            original_filename    TEXT NOT NULL,
            file_type            TEXT NOT NULL,
            uploaded_at          TEXT NOT NULL,
            queue_position       INTEGER NOT NULL,
            analysis_status      TEXT NOT NULL DEFAULT 'queued',
            candidate_name       TEXT,
            total_years_experience REAL,
            seniority_level      TEXT,
            overall_score        INTEGER,
            experience_score     REAL,
            primary_role         TEXT,
            primary_role_confidence REAL,
            raw_extracted_text   TEXT,
            analysis_json        TEXT,
            resume_file_path     TEXT
        )
    """)

    # role_fits  (many-to-many)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS role_fits (
            id            TEXT PRIMARY KEY,
            candidate_id  TEXT NOT NULL REFERENCES candidates(candidate_id),
            role          TEXT NOT NULL,
            confidence    REAL NOT NULL,
            reasoning     TEXT
        )
    """)

    # role_taxonomy
    cur.execute("""
        CREATE TABLE IF NOT EXISTS role_taxonomy (
            role_key     TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            active       INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Seed taxonomy from config (ignore if already exists)
    for r in ROLE_TAXONOMY:
        cur.execute("""
            INSERT OR IGNORE INTO role_taxonomy (role_key, display_name, active)
            VALUES (?, ?, 1)
        """, (r["role_key"], r["display_name"]))

    conn.commit()
    conn.close()


# ── Queue position counter ─────────────────────────────────────────────────────

def next_queue_position(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(queue_position), 0) FROM candidates").fetchone()
    return row[0] + 1


# ── Candidate CRUD ─────────────────────────────────────────────────────────────

def create_candidate(original_filename: str, file_type: str, resume_file_path: str) -> dict:
    """Insert a new candidate record immediately on upload (before analysis)."""
    conn = get_db()
    candidate_id = str(uuid.uuid4())
    uploaded_at  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    queue_pos    = next_queue_position(conn)

    conn.execute("""
        INSERT INTO candidates
            (candidate_id, original_filename, file_type, uploaded_at, queue_position,
             analysis_status, resume_file_path)
        VALUES (?, ?, ?, ?, ?, 'queued', ?)
    """, (candidate_id, original_filename, file_type, uploaded_at, queue_pos, resume_file_path))
    conn.commit()
    conn.close()

    return {
        "candidate_id":   candidate_id,
        "uploaded_at":    uploaded_at,
        "queue_position": queue_pos,
    }


def update_candidate_status(candidate_id: str, status: str):
    conn = get_db()
    conn.execute(
        "UPDATE candidates SET analysis_status=? WHERE candidate_id=?",
        (status, candidate_id)
    )
    conn.commit()
    conn.close()


def update_candidate_analysis(candidate_id: str, analysis: dict,
                               experience_score: float,
                               primary_role: str, primary_role_confidence: float,
                               raw_text: str):
    conn = get_db()

    # Upsert role_fits rows
    conn.execute("DELETE FROM role_fits WHERE candidate_id=?", (candidate_id,))
    for rf in analysis.get("role_fit", []):
        conn.execute("""
            INSERT INTO role_fits (id, candidate_id, role, confidence, reasoning)
            VALUES (?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), candidate_id,
              rf.get("role", ""), rf.get("confidence", 0), rf.get("reasoning", "")))

    conn.execute("""
        UPDATE candidates SET
            analysis_status         = 'complete',
            candidate_name          = ?,
            total_years_experience  = ?,
            seniority_level         = ?,
            overall_score           = ?,
            experience_score        = ?,
            primary_role            = ?,
            primary_role_confidence = ?,
            raw_extracted_text      = ?,
            analysis_json           = ?
        WHERE candidate_id = ?
    """, (
        analysis.get("candidate_name"),
        analysis.get("total_years_experience", 0),
        analysis.get("seniority_level", "junior"),
        analysis.get("overall_score", 0),
        experience_score,
        primary_role,
        primary_role_confidence,
        raw_text,
        json.dumps(analysis),
        candidate_id,
    ))
    conn.commit()
    conn.close()


def mark_failed(candidate_id: str):
    conn = get_db()
    conn.execute(
        "UPDATE candidates SET analysis_status='failed' WHERE candidate_id=?",
        (candidate_id,)
    )
    conn.commit()
    conn.close()


def get_candidate(candidate_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)
    if result.get("analysis_json"):
        result["analysis_json"] = json.loads(result["analysis_json"])

    # Attach role_fits
    fits = conn.execute(
        "SELECT * FROM role_fits WHERE candidate_id=? ORDER BY confidence DESC",
        (candidate_id,)
    ).fetchall()
    result["role_fits"] = [dict(f) for f in fits]
    conn.close()
    return result


def get_all_candidates() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM candidates ORDER BY queue_position ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candidates_for_role(role_key: str) -> list[dict]:
    """
    Return candidates whose primary_role matches role_key,
    sorted by the deterministic comparator:
        experience_score DESC → uploaded_at ASC → candidate_id ASC
    """
    conn = get_db()
    # Get display_name for this role_key
    row = conn.execute(
        "SELECT display_name FROM role_taxonomy WHERE role_key=?", (role_key,)
    ).fetchone()
    if not row:
        conn.close()
        return []
    display_name = row["display_name"]

    rows = conn.execute("""
        SELECT * FROM candidates
        WHERE primary_role = ?
          AND analysis_status = 'complete'
        ORDER BY
            experience_score DESC,
            uploaded_at      ASC,
            candidate_id     ASC
    """, (display_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_role_taxonomy() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM role_taxonomy WHERE active=1 ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
