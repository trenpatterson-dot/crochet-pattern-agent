import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


def _default_db_path() -> Path:
    env_path = os.getenv("DB_PATH", "").strip()
    if env_path:
        return Path(env_path)

    container_db = Path("/app/data/crochet_agent.db")
    running_in_container = Path("/.dockerenv").exists()
    running_on_render = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
    if (running_in_container or running_on_render) and os.name != "nt":
        return container_db

    return Path(__file__).parent / "crochet_patterns.db"


DB_PATH = _default_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                name               TEXT    NOT NULL,
                email              TEXT    UNIQUE NOT NULL,
                skill_level        TEXT    NOT NULL,
                project_types      TEXT    NOT NULL,
                yarn_weights       TEXT    NOT NULL,
                time_commitment    TEXT    NOT NULL,
                color_preferences  TEXT    DEFAULT '',
                aesthetic          TEXT    DEFAULT '',
                budget             TEXT    DEFAULT '',
                email_frequency    TEXT    DEFAULT 'every_2_weeks',
                free_only          INTEGER DEFAULT 0,
                wants_video        INTEGER DEFAULT 1,
                wants_printable    INTEGER DEFAULT 0,
                special_interests  TEXT    DEFAULT '',
                active             INTEGER DEFAULT 1,
                created_at         TEXT    DEFAULT CURRENT_TIMESTAMP,
                updated_at         TEXT    DEFAULT CURRENT_TIMESTAMP,
                last_report_sent   TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                sent_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
                patterns_json TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS competition_runs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at    TEXT    NOT NULL,
                finished_at   TEXT    NOT NULL,
                status        TEXT    NOT NULL,
                summary_json  TEXT    NOT NULL,
                created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS competition_artifacts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id         INTEGER NOT NULL,
                artifact_name  TEXT    NOT NULL,
                artifact_json  TEXT    NOT NULL,
                created_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES competition_runs(id)
            );
        """)
        _ensure_column(conn, "users", "updated_at", "TEXT")
        _ensure_column(conn, "users", "email_frequency", "TEXT DEFAULT 'every_2_weeks'")


def upsert_user(name, email, skill_level, project_types, yarn_weights,
                time_commitment, color_preferences, aesthetic, budget,
                free_only, wants_video, wants_printable, special_interests,
                email_frequency="every_2_weeks"):
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, active, created_at, updated_at FROM users WHERE email=?",
            (email,),
        ).fetchone()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute("""
            INSERT INTO users
                (name, email, skill_level, project_types, yarn_weights,
                 time_commitment, color_preferences, aesthetic, budget,
                 email_frequency, free_only, wants_video, wants_printable,
                 special_interests, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,
                skill_level=excluded.skill_level,
                project_types=excluded.project_types,
                yarn_weights=excluded.yarn_weights,
                time_commitment=excluded.time_commitment,
                color_preferences=excluded.color_preferences,
                aesthetic=excluded.aesthetic,
                budget=excluded.budget,
                email_frequency=excluded.email_frequency,
                free_only=excluded.free_only,
                wants_video=excluded.wants_video,
                wants_printable=excluded.wants_printable,
                special_interests=excluded.special_interests,
                updated_at=excluded.updated_at,
                active=1
        """, (
            name, email, skill_level,
            json.dumps(project_types), json.dumps(yarn_weights),
            time_commitment, color_preferences, aesthetic, budget,
            email_frequency,
            1 if free_only else 0,
            1 if wants_video else 0,
            1 if wants_printable else 0,
            special_interests,
            now,
        ))
        saved = conn.execute(
            "SELECT id, active, created_at, updated_at FROM users WHERE email=?",
            (email,),
        ).fetchone()
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    return {
        "action": "updated" if existing else "created",
        "user_id": saved["id"] if saved else None,
        "active": int(saved["active"]) if saved else 0,
        "created_at": saved["created_at"] if saved else None,
        "updated_at": saved["updated_at"] if saved else now,
        "total_users": total_users,
        "active_users": active_users,
    }


def get_active_users():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users WHERE active=1").fetchall()
    return [_deserialize(dict(r)) for r in rows]


def get_all_users():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY COALESCE(updated_at, created_at) DESC, id DESC"
        ).fetchall()
    return [_deserialize(dict(r)) for r in rows]


def get_user_by_email(email: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return _deserialize(dict(row)) if row else None


def get_storage_debug_summary():
    with connect() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
        inactive_users = conn.execute("SELECT COUNT(*) FROM users WHERE active=0").fetchone()[0]
        total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    return {
        "db_path": str(DB_PATH),
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "total_reports": total_reports,
    }


def deactivate_user(email):
    with connect() as conn:
        conn.execute("UPDATE users SET active=0 WHERE email=?", (email,))


def reset_user_due_now(email):
    with connect() as conn:
        conn.execute(
            "UPDATE users SET last_report_sent=NULL WHERE email=?",
            (email,),
        )


def save_report(user_id, patterns):
    with connect() as conn:
        conn.execute(
            "INSERT INTO reports (user_id, patterns_json) VALUES (?, ?)",
            (user_id, json.dumps(patterns))
        )
        conn.execute(
            "UPDATE users SET last_report_sent=? WHERE id=?",
            (datetime.now().isoformat(), user_id)
        )


def get_reports_for_user(user_id, limit=5):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE user_id=? ORDER BY sent_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def save_competition_run(started_at, finished_at, status, summary, artifacts):
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO competition_runs (started_at, finished_at, status, summary_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                started_at,
                finished_at,
                status,
                json.dumps(summary),
            ),
        )
        run_id = cursor.lastrowid
        for artifact_name, payload in artifacts.items():
            conn.execute(
                """
                INSERT INTO competition_artifacts (run_id, artifact_name, artifact_json)
                VALUES (?, ?, ?)
                """,
                (run_id, artifact_name, json.dumps(payload)),
            )
    return run_id


def get_latest_competition_run():
    with connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM competition_runs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["summary_json"] = json.loads(data["summary_json"])
    return data


def get_latest_competition_artifact(artifact_name):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT artifact_json, created_at
            FROM competition_artifacts
            WHERE artifact_name=?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (artifact_name,),
        ).fetchone()
    if not row:
        return None
    return {
        "artifact_name": artifact_name,
        "artifact_json": json.loads(row["artifact_json"]),
        "created_at": row["created_at"],
    }


def _deserialize(user: dict) -> dict:
    user["project_types"] = json.loads(user["project_types"])
    user["yarn_weights"] = json.loads(user["yarn_weights"])
    user["email_frequency"] = user.get("email_frequency") or "every_2_weeks"
    return user


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
