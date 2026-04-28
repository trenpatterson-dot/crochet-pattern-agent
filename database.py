import json
import os
import sqlite3
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


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
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
                free_only          INTEGER DEFAULT 0,
                wants_video        INTEGER DEFAULT 1,
                wants_printable    INTEGER DEFAULT 0,
                special_interests  TEXT    DEFAULT '',
                active             INTEGER DEFAULT 1,
                created_at         TEXT    DEFAULT CURRENT_TIMESTAMP,
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


def upsert_user(name, email, skill_level, project_types, yarn_weights,
                time_commitment, color_preferences, aesthetic, budget,
                free_only, wants_video, wants_printable, special_interests):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users
                (name, email, skill_level, project_types, yarn_weights,
                 time_commitment, color_preferences, aesthetic, budget,
                 free_only, wants_video, wants_printable, special_interests)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,
                skill_level=excluded.skill_level,
                project_types=excluded.project_types,
                yarn_weights=excluded.yarn_weights,
                time_commitment=excluded.time_commitment,
                color_preferences=excluded.color_preferences,
                aesthetic=excluded.aesthetic,
                budget=excluded.budget,
                free_only=excluded.free_only,
                wants_video=excluded.wants_video,
                wants_printable=excluded.wants_printable,
                special_interests=excluded.special_interests,
                active=1
        """, (
            name, email, skill_level,
            json.dumps(project_types), json.dumps(yarn_weights),
            time_commitment, color_preferences, aesthetic, budget,
            1 if free_only else 0,
            1 if wants_video else 0,
            1 if wants_printable else 0,
            special_interests,
        ))


def get_active_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE active=1").fetchall()
    return [_deserialize(dict(r)) for r in rows]


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [_deserialize(dict(r)) for r in rows]


def deactivate_user(email):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active=0 WHERE email=?", (email,))


def reset_user_due_now(email):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_report_sent=NULL WHERE email=?",
            (email,),
        )


def save_report(user_id, patterns):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reports (user_id, patterns_json) VALUES (?, ?)",
            (user_id, json.dumps(patterns))
        )
        conn.execute(
            "UPDATE users SET last_report_sent=? WHERE id=?",
            (datetime.now().isoformat(), user_id)
        )


def get_reports_for_user(user_id, limit=5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE user_id=? ORDER BY sent_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def save_competition_run(started_at, finished_at, status, summary, artifacts):
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    return user
