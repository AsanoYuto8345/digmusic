from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.signal.state import Status


@dataclass(frozen=True)
class EventRow:
    ts: datetime
    status: Status
    pnn50: float
    artist_name: str
    track_name: str


class DigMusicDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS baseline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    baseline_pnn50 REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pnn50 REAL NOT NULL,
                    artist_name TEXT NOT NULL,
                    track_name TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_baseline(self, baseline_pnn50: float, ts: Optional[datetime] = None) -> int:
        ts = ts or datetime.now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO baseline (ts, baseline_pnn50) VALUES (?, ?)",
                (ts.isoformat(timespec="seconds"), float(baseline_pnn50)),
            )
            conn.commit()
            return int(cur.lastrowid)

    def load_latest_baseline(self) -> Optional[float]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT baseline_pnn50 FROM baseline ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return float(row["baseline_pnn50"])

    def insert_event(self, event: EventRow) -> int:
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT INTO events (ts, status, pnn50, artist_name, track_name)
                VALUES (?, ?, ?, ?, ?)
            """, (
                event.ts.isoformat(timespec="seconds"),
                event.status.value,
                float(event.pnn50),
                event.artist_name,
                event.track_name,
            ))
            conn.commit()
            return int(cur.lastrowid)

    def should_save_event_cooldown(self, ts: datetime, cooldown_seconds: int = 60) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT ts FROM events ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return True
            try:
                last_ts = datetime.fromisoformat(row["ts"])
            except Exception:
                return True
            return (ts - last_ts).total_seconds() >= cooldown_seconds
