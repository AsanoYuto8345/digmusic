from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional, List

from .models import Event, Status


def insert_event(conn: sqlite3.Connection, event: Event) -> int:
    cur = conn.execute(
        """
        INSERT INTO events (ts, status, pnn50, track_name, artist_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.ts.isoformat(),
            event.status.value,
            float(event.pnn50),
            event.track_name,
            event.artist_name,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_latest_event(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT id, ts, status, pnn50, track_name, artist_name
        FROM events
        ORDER BY ts DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def get_events(conn: sqlite3.Connection, limit: int = 100) -> List[dict]:
    rows = conn.execute(
        """
        SELECT id, ts, status, pnn50, track_name, artist_name
        FROM events
        ORDER BY ts DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def should_save_event(
    *,
    conn: sqlite3.Connection,
    ts: datetime,
    status: Status,
    track_name: str,
    artist_name: str,
    cooldown_seconds: int = 60,
) -> bool:
    """
    ログ爆発を防ぐための最低限ガード。
    - CHILL/HYPE以外は保存しない
    - 直近イベントが同じ曲なら保存しない
    - 直近イベントからcooldown秒以内なら保存しない
    """
    if status not in (Status.CHILL, Status.HYPE):
        return False

    latest = get_latest_event(conn)
    if not latest:
        return True

    # 同じ曲なら保存しない
    if latest["track_name"] == track_name and latest["artist_name"] == artist_name:
        return False

    # クールダウン判定
    try:
        latest_ts = datetime.fromisoformat(latest["ts"])
        dt = (ts - latest_ts).total_seconds()
        if dt < cooldown_seconds:
            return False
    except Exception:
        # tsパースできない等なら安全側で保存許可
        return True

    return True
