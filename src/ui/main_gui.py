from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QStackedWidget,
    QFrame,
)

from src.measure.session import MeasureSession, LiveState
from src.storage.db import DigMusicDB
from src.signal.state import Status
from src.ui.heart_monitor import HeartMonitorWidget


DB_PATH = Path("data") / "digmusic.db"


def format_mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


def status_color(status: Status) -> str:
    if status == Status.HYPE:
        return "#FF7A1A"
    if status == Status.CHILL:
        return "#BDEFFF"
    return "#EAEAEA"


class MeasureWorker(QObject):
    update_signal = Signal(object)
    error_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, session: MeasureSession):
        super().__init__()
        self.session = session

    def stop(self):
        self.session.stop()

    def run(self):
        try:
            for st in self.session.run():
                self.update_signal.emit(st)
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            self.finished_signal.emit()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DigMusic")
        self.resize(820, 520)

        self.stack = QStackedWidget()
        self.home_screen = self._build_home()
        self.measure_screen = self._build_measure()

        self.stack.addWidget(self.home_screen)
        self.stack.addWidget(self.measure_screen)

        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)

        self.thread: Optional[QThread] = None
        self.worker: Optional[MeasureWorker] = None

        # REST timer (UI independent)
        self.ui_rest_timer = QTimer(self)
        self.ui_rest_timer.setInterval(200)  # 見た目滑らかにしたいなら200ms
        self.ui_rest_timer.timeout.connect(self._tick_rest_timer)
        self.rest_total_sec = 60
        self.rest_start_epoch: Optional[float] = None
        self.in_rest_mode = False
        self._event_message_expire = 0.0

        # # UI alive heartbeat (debug)
        # self._ui_hb = QTimer(self)
        # self._ui_hb.setInterval(1000)
        # self._ui_hb.timeout.connect(lambda: print("[UI] alive", flush=True))
        # self._ui_hb.start()

    # ---------- Home ----------
    def _build_home(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addStretch(2)

        title = QLabel("DigMusic")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:56px; font-weight:800;")
        layout.addWidget(title)

        layout.addStretch(3)

        self.start_btn = QPushButton("計測開始")
        self.logs_btn = QPushButton("ログ確認")
        self.start_btn.setFixedHeight(56)
        self.logs_btn.setFixedHeight(56)
        self.start_btn.setStyleSheet("font-size:18px;")
        self.logs_btn.setStyleSheet("font-size:18px;")

        layout.addWidget(self.start_btn)
        layout.addWidget(self.logs_btn)

        layout.addStretch(1)

        self.start_btn.clicked.connect(self.start_measurement)
        self.logs_btn.clicked.connect(self.open_logs)

        w.setLayout(layout)
        return w

    # ---------- Measure ----------
    def _build_measure(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout()
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        # Status card
        self.status_card = QFrame()
        self.status_card.setObjectName("statusCard")
        self.status_card.setStyleSheet("""
            QFrame#statusCard { background: #EAEAEA; border-radius: 28px; }
        """)
        self.status_card.setMinimumHeight(200)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(8)

        self.rest_label = QLabel("REST 1:00")
        self.rest_label.setAlignment(Qt.AlignLeft)
        self.rest_label.setStyleSheet("font-size:16px; font-weight:600; color:#000;")
        card_layout.addWidget(self.rest_label)

        self.big_status = QLabel("NEUTRAL")
        self.big_status.setAlignment(Qt.AlignCenter)
        self.big_status.setStyleSheet("font-size:64px; font-weight:800; color:#000;")
        card_layout.addWidget(self.big_status)

        self.pnn50_line = QLabel("pNN50: -   base: -")
        self.pnn50_line.setAlignment(Qt.AlignCenter)
        self.pnn50_line.setStyleSheet("font-size:18px; font-weight:500; color:#000;")
        card_layout.addWidget(self.pnn50_line)

        self.status_card.setLayout(card_layout)

        # Track
        self.track_label = QLabel("—")
        self.track_label.setAlignment(Qt.AlignCenter)
        self.track_label.setStyleSheet("font-size:20px; font-weight:600;")

        # Monitor card
        self.monitor_card = QFrame()
        self.monitor_card.setObjectName("monitorCard")
        self.monitor_card.setStyleSheet("""
            QFrame#monitorCard { background: #BDEFFF; border-radius: 28px; }
        """)
        self.monitor_card.setMinimumHeight(180)

        monitor_layout = QVBoxLayout()
        monitor_layout.setContentsMargins(18, 18, 18, 18)
        monitor_layout.setSpacing(10)

        monitor_title = QLabel("心拍(心電図)モニター")
        monitor_title.setAlignment(Qt.AlignCenter)
        monitor_title.setStyleSheet("font-size:18px; font-weight:700; color:#000;")
        monitor_layout.addWidget(monitor_title)

        self.monitor_widget = HeartMonitorWidget(window_sec=10.0, y_min=0.0, y_max=200.0)
        monitor_layout.addWidget(self.monitor_widget)

        self.hr_text = QLabel("HR: - bpm")
        self.hr_text.setAlignment(Qt.AlignCenter)
        self.hr_text.setStyleSheet("font-size:16px; font-weight:600; color:#000;")
        monitor_layout.addWidget(self.hr_text)

        self.monitor_card.setLayout(monitor_layout)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            color:#111;
            background:#FFFFFF;
            border-radius:18px;
            padding:12px;
            font-size:15px;
            font-weight:600;
        """)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setFixedHeight(48)
        self.stop_btn.setStyleSheet("font-size:16px;")
        self.stop_btn.clicked.connect(self.stop_measurement)

        root.addWidget(self.status_card)
        root.addWidget(self.track_label)
        root.addWidget(self.monitor_card)
        root.addWidget(self.info_label)
        root.addWidget(self.stop_btn)

        w.setLayout(root)
        return w

    # ---------- REST Timer tick (UI independent) ----------
    def _start_rest_ui_timer(self):
        self.in_rest_mode = True
        self.rest_start_epoch = time.time()
        # ここで即座に 1:00 表示
        self.rest_label.setText(f"REST {format_mmss(self.rest_total_sec)}")
        self.big_status.setText("REST")
        self.status_card.setStyleSheet("""
            QFrame#statusCard { background: #EAEAEA; border-radius: 28px; }
        """)
        self.ui_rest_timer.start()

    def _stop_rest_ui_timer(self):
        self.in_rest_mode = False
        self.rest_start_epoch = None
        self.ui_rest_timer.stop()

    def _tick_rest_timer(self):
        if not self.in_rest_mode or self.rest_start_epoch is None:
            return
        elapsed = time.time() - self.rest_start_epoch
        remain = self.rest_total_sec - int(elapsed)
        remain = max(0, remain)
        self.rest_label.setText(f"REST {format_mmss(remain)}")
        if remain <= 0:
            # 表示上は0になったら止めてOK（実際のbaseline確定は計測側がやる）
            self.ui_rest_timer.stop()

    # ---------- Controls ----------
    def start_measurement(self):
        self.stack.setCurrentWidget(self.measure_screen)
        self.start_btn.setEnabled(False)
        self.logs_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.info_label.setText("計測開始：安静にしてください")

        # RESTタイマーはUIで独立スタート
        self._start_rest_ui_timer()

        db = DigMusicDB(DB_PATH)
        session = MeasureSession(
            db=db,
            rest_total_sec=self.rest_total_sec,
            hr_window_sec=10.0,
            track_poll_interval=2.0,
            cooldown_seconds=60,
            serial_port=None,   # 固定したいなら "COM4" とか
            baudrate=115200,
        )

        self.thread = QThread()
        self.worker = MeasureWorker(session)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.update_signal.connect(self.on_update)
        self.worker.error_signal.connect(self.on_error)
        self.worker.finished_signal.connect(self.on_finished)

        self.thread.start()

    def stop_measurement(self):
        self.info_label.setText("停止処理中...")
        self.stop_btn.setEnabled(False)
        if self.worker:
            self.worker.stop()

    def on_update(self, st: LiveState):
        now = time.time()
        # 曲名は常時表示
        self.track_label.setText(st.track_text)

        # HRモニタは常時更新
        if st.hr is None:
            self.hr_text.setText("HR: - bpm")
        else:
            self.hr_text.setText(f"HR: {st.hr:.1f} bpm")
        self.monitor_widget.set_points(st.hr_points)

        # pNN50/base
        ptxt = "-" if st.smoothed is None else f"{st.smoothed:.1f}"
        btxt = "-" if st.baseline is None else f"{st.baseline:.1f}"
        self.pnn50_line.setText(f"pNN50: {ptxt}   base: {btxt}")

        if st.event_message:
            self._event_message_expire = now + 4.0
            self.info_label.setText(st.event_message)
        elif now >= self._event_message_expire:
            if st.mode == "REST":
                self.info_label.setText("RESTモード：安静にしてください")
            else:
                self.info_label.setText("RUNモード：状態を解析しています")

        # REST -> RUN に入ったらUI側RESTタイマーを止め、RUN表示へ
        if st.mode == "RUN":
            if self.in_rest_mode:
                self._stop_rest_ui_timer()
                if now >= self._event_message_expire:
                    self.info_label.setText("RUNモード：状態を解析しています")

            self.rest_label.setText("")  # RUN中は非表示
            self.big_status.setText(st.status.value)
            self.status_card.setStyleSheet(f"""
                QFrame#statusCard {{
                    background: {status_color(st.status)};
                    border-radius: 28px;
                }}
            """)
        else:
            # REST中の見た目はUI側タイマーに任せる（ここではbig_status等を上書きしない）
            pass

    def on_error(self, msg: str):
        QMessageBox.critical(self, "Error", msg)

    def on_finished(self):
        # 計測が終わったらUI RESTタイマーも止める
        self._stop_rest_ui_timer()

        if self.thread:
            self.thread.quit()
            self.thread.wait()

        self.thread = None
        self.worker = None

        self.start_btn.setEnabled(True)
        self.logs_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        self.stack.setCurrentWidget(self.home_screen)

    def open_logs(self):
        import subprocess
        subprocess.Popen([sys.executable, "src/ui/db_viewer.py"])


def main():
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
