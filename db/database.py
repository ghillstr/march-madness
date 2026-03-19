"""SQLite database helpers."""

import os
import sqlite3
from contextlib import contextmanager

from config import DB_PATH


def get_connection(db_path=None):
    """Get a SQLite connection with WAL mode and foreign keys."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db(db_path=None):
    """Context manager for database connections."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """Initialize database from schema.sql."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema = f.read()
    with get_db(db_path) as conn:
        conn.executescript(schema)
    print(f"Database initialized at {db_path or DB_PATH}")


def get_or_create_team(conn, school_name, slug=None, conference=None):
    """Get team_id, creating the team if it doesn't exist."""
    row = conn.execute(
        "SELECT team_id FROM teams WHERE school_name = ?", (school_name,)
    ).fetchone()
    if not row and slug:
        row = conn.execute(
            "SELECT team_id FROM teams WHERE sports_ref_slug = ?", (slug,)
        ).fetchone()
    if row:
        team_id = row["team_id"]
        # Update slug/conference if provided
        if slug:
            conn.execute(
                "UPDATE teams SET sports_ref_slug = ? WHERE team_id = ? AND sports_ref_slug IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM teams WHERE sports_ref_slug = ? AND team_id != ?)",
                (slug, team_id, slug, team_id),
            )
        if conference:
            conn.execute(
                "UPDATE teams SET conference = ? WHERE team_id = ?",
                (conference, team_id),
            )
        return team_id
    cur = conn.execute(
        "INSERT INTO teams (school_name, sports_ref_slug, conference) VALUES (?, ?, ?)",
        (school_name, slug, conference),
    )
    return cur.lastrowid


def upsert_team_season(conn, team_id, season, stats_dict):
    """Insert or update team season stats."""
    existing = conn.execute(
        "SELECT id FROM team_seasons WHERE team_id = ? AND season = ?",
        (team_id, season),
    ).fetchone()
    cols = list(stats_dict.keys())
    vals = list(stats_dict.values())
    if existing:
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        conn.execute(
            f"UPDATE team_seasons SET {set_clause} WHERE team_id = ? AND season = ?",
            vals + [team_id, season],
        )
    else:
        cols_str = ", ".join(["team_id", "season"] + cols)
        placeholders = ", ".join(["?"] * (len(cols) + 2))
        conn.execute(
            f"INSERT INTO team_seasons ({cols_str}) VALUES ({placeholders})",
            [team_id, season] + vals,
        )


def get_team_id_by_name(conn, name):
    """Look up team_id by school name (fuzzy)."""
    row = conn.execute(
        "SELECT team_id FROM teams WHERE school_name = ?", (name,)
    ).fetchone()
    if row:
        return row["team_id"]
    # Try partial match
    row = conn.execute(
        "SELECT team_id FROM teams WHERE school_name LIKE ?", (f"%{name}%",)
    ).fetchone()
    return row["team_id"] if row else None


def get_all_teams(conn, season=None):
    """Get all teams, optionally filtered to those with data for a season."""
    if season:
        return conn.execute(
            """SELECT t.team_id, t.school_name, t.sports_ref_slug, t.conference
               FROM teams t JOIN team_seasons ts ON t.team_id = ts.team_id
               WHERE ts.season = ? ORDER BY t.school_name""",
            (season,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM teams ORDER BY school_name"
    ).fetchall()


if __name__ == "__main__":
    init_db()
