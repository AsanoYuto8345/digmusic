from __future__ import annotations

import time
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
)

from src.sensors.serial_rr_reader import rr_stream
from src.signal.pnn50 import PNN50Calculator
from src.signal.state import FixedBaselineClassifier, Status

from src.music.readmusic import get_now_playing


DB_PATH = Path("data") / "digmusic.db"


# -------------------------
# DB: baseline & events
# -------------------------
def get_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS baseline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            baseline_pnn50 REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            status TEXT NOT NULL,
            pnn50 REAL NOT NULL,
            artist_name TEXT NOT NULL,
            track_name TEXT NOT NULL
        )
        """
    )
    conn.commit()


def save_baseline(conn: sqlite3.Connection, baseline_pnn50: float) -> int:
    ts = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO baseline (ts, baseline_pnn50) VALUES (?, ?)",
        (ts, float(baseline_pnn50)),
    )
    conn.commit()
    return int(cur.lastrowid)


def load_latest_baseline(conn: sqlite3.Connection) -> Optional[float]:
    row = conn.execute(
        "SELECT baseline_pnn50 FROM baseline ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return float(row["baseline_pnn50"])


def insert_event(
    conn: sqlite3.Connection,
    ts: datetime,
    status: Status,
    pnn50: float,
    artist: str,
    track: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO events (ts, status, pnn50, artist_name, track_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ts.isoformat(timespec="seconds"),
            status.value,
            float(pnn50),
            artist,
            track,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def should_save_event(
    conn: sqlite3.Connection,
    ts: datetime,
    status: Status,
    artist: str,
    track: str,
    cooldown_seconds: int = 60,
) -> bool:
    row = conn.execute(
        """
        SELECT ts, status, artist_name, track_name
        FROM events
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    if row is None:
        return True

    try:
        last_ts = datetime.fromisoformat(row["ts"])
    except Exception:
        return True

    if (ts - last_ts).total_seconds() < cooldown_seconds:
        return False

    if row["artist_name"] == artist and row["track_name"] == track and row["status"] == status.value:
        return False

    return True


# -------------------------
# Worker (QThread)
# -------------------------
@dataclass
class LiveState:
    hr: Optional[float]
    pnn50: Optional[float]
    smoothed: Optional[float]
    baseline: Optional[float]
    status: Status
    mode: str  # "REST" or "RUN"


class MeasureWorker(QObject):
    update_signal = Signal(object)
    info_signal = Signal(str)
    error_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path
        self._stop = False

        self.calc = PNN50Calculator(window_beats=30, max_jump_ms=250)
        self.clf = FixedBaselineClassifier(smooth_size=5, chill_delta=6.0, hype_delta=6.0)

        self.rest_seconds_total = 60
        self.rest_end_epoch: Optional[float] = None
        self.rest_pnn50_values: list[float] = []

        self.last_status: Status = Status.NEUTRAL

    def stop(self):
        self._stop = True

    def _emit(self, mode: str, p: Optional[float], hr: Optional[float], sm: Optional[float], base: Optional[float], st: Status):
        self.update_signal.emit(
            LiveState(
                hr=hr,
                pnn50=p,
                smoothed=sm,
                baseline=base,
                status=st,
                mode=mode,
            )
        )

    def run(self):
        try:
            conn = get_conn(self.db_path)
            init_db(conn)
        except Exception as e:
            self.error_signal.emit(f"DB初期化に失敗: {e}")
            self.finished_signal.emit()
            return

        prev_base = load_latest_baseline(conn)
        if prev_base is not None:
            self.clf.set_baseline(prev_base)
            self.info_signal.emit(f"前回のbaselineを読み込み: {prev_base:.1f}%")

        self.info_signal.emit("計測開始：まず1分間安静にしてください。")
        self.rest_end_epoch = time.time() + self.rest_seconds_total
        self.rest_pnn50_values = []
        self.last_status = Status.NEUTRAL

        for msg in rr_stream():
            if self._stop:
                break

            if not self.calc.add_rr(msg.rr_ms):
                continue

            p = self.calc.pnn50_percent()
            hr = self.calc.hr_bpm()
            if p is None:
                continue

            now = time.time()

            if self.rest_end_epoch is not None and now < self.rest_end_epoch:
                self.rest_pnn50_values.append(float(p))
                sm, base, st = self.clf.update(p)
                self._emit("REST", p, hr, sm, base, Status.NEUTRAL)
                continue

            if self.rest_end_epoch is not None and now >= self.rest_end_epoch:
                self.rest_end_epoch = None

                if len(self.rest_pnn50_values) == 0:
                    self.error_signal.emit("安静1分中にpNN50が取得できませんでした。")
                    break

                baseline = sum(self.rest_pnn50_values) / len(self.rest_pnn50_values)
                self.clf.set_baseline(baseline)

                try:
                    baseline_id = save_baseline(conn, baseline)
                    self.info_signal.emit(f"baseline確定: {baseline:.1f}%（保存ID={baseline_id}）")
                except Exception as e:
                    self.error_signal.emit(f"baseline保存に失敗: {e}")
                    break

            sm, base, st = self.clf.update(p)
            self._emit("RUN", p, hr, sm, base, st)

            if self.last_status != st and st in (Status.CHILL, Status.HYPE):
                now_playing = get_now_playing()
                if now_playing is None:
                    self.info_signal.emit("[WARN] 曲情報が取得できないので保存をスキップ")
                    self.last_status = st
                    continue

                artist, track = now_playing
                ts = datetime.now()

                try:
                    if should_save_event(conn, ts, st, artist, track, cooldown_seconds=60):
                        value_to_save = float(sm) if sm is not None else float(p)
                        new_id = insert_event(conn, ts, st, value_to_save, artist, track)
                        self.info_signal.emit(f"[SAVED] id={new_id} {st.value} pNN50={value_to_save:.1f}% {artist} - {track}")
                    else:
                        self.info_signal.emit("[SKIP] クールダウン/同曲で抑止")
                except Exception as e:
                    self.error_signal.emit(f"イベント保存に失敗: {e}")
                    break

            self.last_status = st

        self.finished_signal.emit()


# -------------------------
# Main GUI
# -------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DigMusic - Main")
        self.resize(720, 360)

        self.conn = get_conn(DB_PATH)
        init_db(self.conn)

        self.status_label = QLabel("状態: -")
        self.mode_label = QLabel("モード: -")
        self.countdown_label = QLabel("安静カウントダウン: -")
        self.metrics_label = QLabel("HR: -   pNN50: -   sm: -   base: -")
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)

        self.start_btn = QPushButton("計測開始")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.logs_btn = QPushButton("ログ確認（DB Viewer）")

        root = QVBoxLayout()
        root.addWidget(self.mode_label)
        root.addWidget(self.countdown_label)
        root.addWidget(self.metrics_label)
        root.addWidget(self.status_label)
        root.addSpacing(12)
        root.addWidget(self.info_label)

        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addStretch(1)
        btns.addWidget(self.logs_btn)
        root.addLayout(btns)

        self.setLayout(root)

        self.thread: Optional[QThread] = None
        self.worker: Optional[MeasureWorker] = None

        self.start_btn.clicked.connect(self.start_measurement)
        self.stop_btn.clicked.connect(self.stop_measurement)
        self.logs_btn.clicked.connect(self.open_logs)

        prev = load_latest_baseline(self.conn)
        if prev is not None:
            self.info_label.setText(f"前回baseline: {prev:.1f}%（計測開始で新しいbaselineを作ります）")

    def start_measurement(self):
        if self.thread is not None:
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.logs_btn.setEnabled(False)

        self.info_label.setText("計測準備中...")

        self.thread = QThread()
        self.worker = MeasureWorker(DB_PATH)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.update_signal.connect(self.on_update)
        self.worker.info_signal.connect(self.on_info)
        self.worker.error_signal.connect(self.on_error)
        self.worker.finished_signal.connect(self.on_finished)

        self.thread.start()

    def stop_measurement(self):
        if self.worker is not None:
            self.worker.stop()
        self.info_label.setText("停止処理中...")

    def on_update(self, state: LiveState):
        self.mode_label.setText(f"モード: {state.mode}")

        if state.mode == "REST" and self.worker is not None and self.worker.rest_end_epoch is not None:
            remain = max(0, int(self.worker.rest_end_epoch - time.time()))
            self.countdown_label.setText(f"安静カウントダウン: 残り {remain} 秒（動かないでね）")
        else:
            self.countdown_label.setText("安静カウントダウン: -")

        hr = "-" if state.hr is None else f"{state.hr:.1f} bpm"
        p = "-" if state.pnn50 is None else f"{state.pnn50:.1f}%"
        sm = "-" if state.smoothed is None else f"{state.smoothed:.1f}%"
        base = "-" if state.baseline is None else f"{state.baseline:.1f}%"
        self.metrics_label.setText(f"HR: {hr}   pNN50: {p}   sm: {sm}   base: {base}")

        self.status_label.setText(f"状態: {state.status.value}")

    def on_info(self, msg: str):
        self.info_label.setText(msg)

    def on_error(self, msg: str):
        QMessageBox.critical(self, "Error", msg)
        self.info_label.setText(msg)

    def on_finished(self):
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()

        self.thread = None
        self.worker = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.logs_btn.setEnabled(True)

        self.info_label.setText("停止しました。")

    def open_logs(self):
        try:
            import subprocess
            subprocess.Popen([sys.executable, "src/ui/db_viewer.py"])
        except Exception as e:
            QMessageBox.warning(self, "Logs", f"DB Viewer起動に失敗: {e}")


def main():
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
